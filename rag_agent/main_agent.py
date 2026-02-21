import os
import json
import time
from datetime import datetime
from pathlib import Path
from typing import TypedDict, Literal
from dotenv import load_dotenv

from langchain_openai import ChatOpenAI
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langgraph.graph import StateGraph, START, END
# ---------------------------------------------------------
# [Import] 전문가 에이전트 모듈
# ---------------------------------------------------------
from rag_agent.sql_agent import get_sql_answer
from rag_agent.finrag_agent import get_rag_answer
from rag_agent.transfer_agent import get_transfer_answer
from rag_agent.web_search_rag import WebSearchRAG

# 환경 변수 로드
load_dotenv()

# LLM 설정
llm = ChatOpenAI(model="gpt-5-mini")

GLOBAL_CHAT_CONTEXT = {"summary": ""}

CURRENT_DIR = Path(__file__).resolve().parent
MEMORY_DIR = CURRENT_DIR.parent / "logs"
MEMORY_FILE = MEMORY_DIR / "memory.md"

# ---------------------------------------------------------
# [로그 출력 유틸리티 함수]
# ---------------------------------------------------------
def print_log(step_name: str, status: str, start_time: float = None, extra_info: str = None):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    if status == "start":
        print(f"[{now}] ⏳ [{step_name}] 시작...",flush=True)
        return time.time()
    elif status == "end" and start_time is not None:
        elapsed = time.time() - start_time
        log_msg = f"[{now}] ✅ [{step_name}] 완료 (소요시간: {elapsed:.3f}초)"
        if extra_info:
            log_msg += f"\n   👉 {extra_info}"
        print(log_msg,flush=True)
        return elapsed

def reset_global_context():
    global GLOBAL_CHAT_CONTEXT
    GLOBAL_CHAT_CONTEXT["summary"] = ""
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    with open(MEMORY_FILE, "w", encoding="utf-8") as f:
        f.write("# 대화 기록\n\n")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    print(f"[{now}] 🧹 [Memory] 대화 기록 파일(logs/memory.md)이 초기화되었습니다.")

web_rag = WebSearchRAG()

# ---------------------------------------------------------
# [설정] 프롬프트 경로 설정 및 로딩 함수
# ---------------------------------------------------------
PROMPT_DIR = CURRENT_DIR / "prompt" / "main"

def read_prompt(filename: str) -> str:
    file_path = PROMPT_DIR / filename
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        print(f"[{now}] ❌ [Error] 프롬프트 파일을 찾을 수 없습니다: {file_path}")
        return ""

# ---------------------------------------------------------
# [LangGraph] 상태 스키마
# ---------------------------------------------------------
class MainAgentState(TypedDict, total=False):
    question: str
    korean_query: str
    source_lang: str
    needs_context: bool       # [NEW] 문맥 보정 필요 여부 플래그
    refined_query: str
    category: str
    korean_answer: str
    final_answer: str
    transfer_result: dict
    username: str
    transfer_context: dict
    allowed_views: list
    _history: str
    _skip_re_translate: bool

# ---------------------------------------------------------
# [LangGraph] 프롬프트/체인 빌더
# ---------------------------------------------------------
def _translation_chain():
    t = read_prompt("main_01_translation.md")
    return PromptTemplate.from_template(t) | llm | StrOutputParser()

def _refinement_chain():
    t = read_prompt("main_02_refinement.md")
    return PromptTemplate.from_template(t) | llm | StrOutputParser()

def _router_chain():
    t = read_prompt("main_03_router.md")
    return PromptTemplate.from_template(t) | llm | StrOutputParser()

def _system_prompt_chain():
    t = read_prompt("main_04_system.md")
    return PromptTemplate.from_template(t) | llm | StrOutputParser()

def _re_translation_chain():
    t = read_prompt("main_05_re_translation.md")
    return PromptTemplate.from_template(t) | llm | StrOutputParser()

# ---------------------------------------------------------
# 역번역 헬퍼 함수
# ---------------------------------------------------------
def translate_answer(korean_text: str, target_language: str) -> str:
    if not korean_text:
        return korean_text
    
    if "Korean" in target_language or "한국어" in target_language:
        return korean_text
    
    t0 = print_log(f"역번역 (한국어 -> {target_language})", "start")
    try:
        chain = _re_translation_chain()
        translated = chain.invoke({
            "target_language": target_language,
            "korean_answer": korean_text
        }).strip()
        print_log(f"역번역 (한국어 -> {target_language})", "end", t0)
        return translated
    except Exception as e:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        print(f"[{now}] ⚠️ 역번역 실패: {e}, 원본 반환")
        return korean_text

# ---------------------------------------------------------
# [LangGraph] 노드 함수
# ---------------------------------------------------------
def node_translate(state: MainAgentState) -> dict:
    t0 = print_log("Step 1: 입력 언어 감지 및 한국어 번역 (node_translate)", "start")
    question = state["question"]
    try:
        chain = _translation_chain()
        trans_result_str = chain.invoke({"question": question}).strip()
        trans_result_str = trans_result_str.replace("```json", "").replace("```", "")
        trans_result = json.loads(trans_result_str)
        
        source_lang = trans_result.get("source_language", "Korean")
        korean_query = trans_result.get("korean_query", question)
        # [NEW] JSON에서 needs_context 파싱 (기본값 True로 설정하여 안전하게 폴백)
        needs_context = trans_result.get("needs_context", True)
        
        extra = f"감지 언어: {source_lang} / 변환 쿼리: '{korean_query}' / 보정 필요: {needs_context}"
    except Exception as e:
        source_lang = "Korean"
        korean_query = question
        needs_context = True # 파싱 에러 시 무조건 보정 단계를 거치도록 안전장치 설정
        extra = f"번역 오류로 원본 유지: {e}"
        
    print_log("Step 1: 입력 언어 감지 및 한국어 번역 (node_translate)", "end", t0, extra_info=extra)
    
    # [NEW] 보정 단계(refine)를 건너뛸 수 있으므로 refined_query를 미리 korean_query로 설정
    return {
        "korean_query": korean_query, 
        "source_lang": source_lang, 
        "needs_context": needs_context,
        "refined_query": korean_query
    }

def node_refine(state: MainAgentState) -> dict:
    t0 = print_log("Step 2: 컨텍스트 기반 질문 보정 (node_refine)", "start")
    history_context = state.get("_history") or "이전 대화 기록 없음(No previous conversation history)."
    korean_query = state["korean_query"]
    
    chain = _refinement_chain()
    refined_query = chain.invoke({"history": history_context, "question": korean_query}).strip()
    
    if refined_query != korean_query:
        extra = f"보정됨: '{korean_query}' -> '{refined_query}'"
    else:
        extra = "보정 없음 (변화 없음)"
        
    print_log("Step 2: 컨텍스트 기반 질문 보정 (node_refine)", "end", t0, extra_info=extra)
    return {"refined_query": refined_query}

def node_route(state: MainAgentState) -> dict:
    t0 = print_log("Step 3: 의도 분류 및 라우팅 (node_route)", "start")
    chain = _router_chain()
    # 만약 보정 노드를 거치지 않았더라도 node_translate에서 넣은 refined_query(기본 원문)가 사용됨
    category = chain.invoke({"question": state["refined_query"]}).strip()
    category = category.replace("'", "").replace('"', "").replace(".", "")
    
    print_log("Step 3: 의도 분류 및 라우팅 (node_route)", "end", t0, extra_info=f"분류된 카테고리: [{category}]")
    return {"category": category}

def node_sql(state: MainAgentState) -> dict:
    t0 = print_log("Sub-Agent: SQL Agent 호출", "start")
    answer = get_sql_answer(state["refined_query"], state["username"], state.get("allowed_views") or [])
    print_log("Sub-Agent: SQL Agent 호출", "end", t0)
    return {"korean_answer": answer}

def node_finrag(state: MainAgentState) -> dict:
    t0 = print_log("Sub-Agent: FinRAG Agent 호출", "start")
    answer = get_rag_answer(state["refined_query"], original_query=state["question"])
    print_log("Sub-Agent: FinRAG Agent 호출", "end", t0)
    return {"korean_answer": answer}

def node_transfer(state: MainAgentState) -> dict:
    t0 = print_log("Sub-Agent: Transfer Agent 호출", "start")
    result = get_transfer_answer(state["refined_query"], state["username"], context={})
    
    if isinstance(result, dict):
        if result.get("context") and not result["context"].get("source_language"):
            source_lang = state.get("source_lang", "Korean")
            result["context"]["source_language"] = source_lang
        print_log("Sub-Agent: Transfer Agent 호출", "end", t0, extra_info="송금 플로우 진행 (dict 반환)")
        return {"transfer_result": result, "korean_answer": None}
        
    print_log("Sub-Agent: Transfer Agent 호출", "end", t0, extra_info="일반 텍스트 반환")
    return {"korean_answer": result, "transfer_result": None}

def node_system(state: MainAgentState) -> dict:
    t0 = print_log("Sub-Agent: System Prompt 호출 (일반 대화)", "start")
    chain = _system_prompt_chain()
    answer = chain.invoke({"question": state["korean_query"]})
    print_log("Sub-Agent: System Prompt 호출 (일반 대화)", "end", t0)
    return {"korean_answer": answer}

def node_fallback(state: MainAgentState) -> dict:
    t0 = print_log("Fallback 처리", "start")
    korean_answer = "죄송해요, 질문의 의도를 정확히 파악하지 못했습니다."
    print_log("Fallback 처리", "end", t0, extra_info=f"알 수 없는 카테고리: {state.get('category', '')}")
    return {"korean_answer": korean_answer}

def node_summarize(state: MainAgentState) -> dict:
    t0 = print_log("대화 기록 저장 (node_summarize -> 파일 Append)", "start")
    refined_query = state.get("refined_query", "")
    korean_answer = state.get("korean_answer") or ""
    
    if not isinstance(korean_answer, str):
        print_log("대화 기록 저장 (node_summarize -> 파일 Append)", "end", t0, extra_info="답변이 문자열이 아니므로 스킵")
        return {}
        
    try:
        MEMORY_DIR.mkdir(parents=True, exist_ok=True)
        with open(MEMORY_FILE, "a", encoding="utf-8") as f:
            f.write(f"**User**: {refined_query}\n\n**AI**: {korean_answer}\n\n---\n\n")
        extra = "메모리 파일에 성공적으로 Append 되었습니다."
    except Exception as e:
        extra = f"메모리 업데이트 실패: {e}"
        
    print_log("대화 기록 저장 (node_summarize -> 파일 Append)", "end", t0, extra_info=extra)
    return {}

def node_re_translate(state: MainAgentState) -> dict:
    t0 = print_log("최종 답변 역번역 (node_re_translate)", "start")
    source_lang = state.get("source_lang", "Korean")
    korean_answer = state.get("korean_answer", "")
    final_answer = translate_answer(korean_answer, source_lang)
    print_log("최종 답변 역번역 (node_re_translate)", "end", t0)
    return {"final_answer": final_answer}

# ---------------------------------------------------------
# 라우터 함수들
# ---------------------------------------------------------
def check_needs_context(state: MainAgentState) -> Literal["refine", "route"]:
    """[NEW] 번역 노드에서 판단한 needs_context 값에 따라 보정 노드를 거칠지 결정"""
    if state.get("needs_context", True):
        return "refine"
    return "route"

def route_by_category(state: MainAgentState) -> Literal["sql", "finrag", "transfer", "system", "fallback"]:
    cat = (state.get("category") or "").strip()
    if cat == "DATABASE":
        return "sql"
    if cat == "KNOWLEDGE":
        return "finrag"
    if cat == "TRANSFER":
        return "transfer"
    if cat == "GENERAL":
        return "system"
    return "fallback"

def after_transfer(state: MainAgentState) -> Literal["summarize", "end_transfer"]:
    if state.get("transfer_result") is not None:
        return "end_transfer"
    return "summarize"

# ---------------------------------------------------------
# [LangGraph] 그래프 빌드 및 컴파일
# ---------------------------------------------------------
def _build_main_graph():
    builder = StateGraph(MainAgentState)

    builder.add_node("translate", node_translate)
    builder.add_node("refine", node_refine)
    builder.add_node("route", node_route)
    builder.add_node("sql", node_sql)
    builder.add_node("finrag", node_finrag)
    builder.add_node("transfer", node_transfer)
    builder.add_node("system", node_system)
    builder.add_node("fallback", node_fallback)
    builder.add_node("summarize", node_summarize)
    builder.add_node("re_translate", node_re_translate)

    builder.add_edge(START, "translate")
    
    # [NEW] 기존의 무조건 연결 대신 조건부 연결(Conditional Edge) 적용
    builder.add_conditional_edges(
        "translate",
        check_needs_context,
        {
            "refine": "refine",
            "route": "route"
        }
    )
    
    builder.add_edge("refine", "route")
    
    builder.add_conditional_edges("route", route_by_category, {
        "sql": "sql",
        "finrag": "finrag",
        "transfer": "transfer",
        "system": "system",
        "fallback": "fallback",
    })
    builder.add_conditional_edges("transfer", after_transfer, {"end_transfer": END, "summarize": "summarize"})
    builder.add_edge("sql", "summarize")
    builder.add_edge("finrag", "summarize")
    builder.add_edge("system", "summarize")
    builder.add_edge("fallback", "summarize")
    builder.add_edge("summarize", "re_translate")
    builder.add_edge("re_translate", END)

    return builder.compile()

_compiled_graph = None

def get_main_graph():
    global _compiled_graph
    if _compiled_graph is None:
        _compiled_graph = _build_main_graph()
    return _compiled_graph

# ---------------------------------------------------------
# 메인 에이전트 실행 함수 (Orchestrator)
# ---------------------------------------------------------
def run_fintech_agent(question, username="test_user", transfer_context=None, allowed_views=None):
    print("\n" + "="*60)
    total_t0 = print_log("Main Agent 전체 파이프라인", "start")
    print(f"   [User Input]: {question}")
    print("="*60)

    if transfer_context:
        t0_ctx = print_log("진행 중인 송금 컨텍스트(Transfer Context) 처리", "start")
        source_lang = transfer_context.get("source_language", "Korean")
        
        if question.strip().upper() in ("__YES__", "__NO__"):
            korean_query = question
        elif question.strip().isdigit() or (len(question.strip()) <= 10 and not any(c.isalpha() for c in question)):
            korean_query = question
        else:
            try:
                chain = _translation_chain()
                trans_result_str = chain.invoke({"question": question}).strip()
                trans_result_str = trans_result_str.replace("```json", "").replace("```", "")
                trans_result = json.loads(trans_result_str)
                detected_lang = trans_result.get("source_language", "Korean")
                korean_query = trans_result.get("korean_query", question)
                
                if source_lang == "Korean" and detected_lang != "Korean":
                    source_lang = detected_lang
                    transfer_context["source_language"] = source_lang
            except Exception:
                korean_query = question
        
        transfer_result = get_transfer_answer(korean_query, username, context=transfer_context)
        
        if isinstance(transfer_result, dict) and "message" in transfer_result:
            korean_msg = transfer_result["message"]
            translated_msg = translate_answer(korean_msg, source_lang)
            transfer_result["message"] = translated_msg
            if "context" in transfer_result:
                transfer_result["context"]["source_language"] = source_lang
        
        print_log("진행 중인 송금 컨텍스트(Transfer Context) 처리", "end", t0_ctx)
        print("="*60)
        print_log("Main Agent 전체 파이프라인", "end", total_t0)
        print("="*60 + "\n")
        return transfer_result

    history_text = ""
    if MEMORY_FILE.exists():
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            history_text = f.read()
    else:
        history_text = "이전 대화 기록 없음(No previous conversation history)."

    initial_state: MainAgentState = {
        "question": question,
        "username": username,
        "allowed_views": allowed_views or [],
        "_history": history_text,
    }

    graph = get_main_graph()
    result = graph.invoke(initial_state)

    if result.get("transfer_result") is not None:
        transfer_result = result["transfer_result"]
        source_lang = result.get("source_lang", "Korean")
        if isinstance(transfer_result, dict) and "message" in transfer_result:
            korean_msg = transfer_result["message"]
            translated_msg = translate_answer(korean_msg, source_lang)
            transfer_result["message"] = translated_msg
            
        print("="*60)
        print_log("Main Agent 전체 파이프라인 (Transfer)", "end", total_t0)
        print("="*60 + "\n")
        return transfer_result

    final_answer = result.get("final_answer") or result.get("korean_answer") or ""
    
    print("="*60)
    print_log("Main Agent 전체 파이프라인", "end", total_t0)
    print("="*60 + "\n")
    
    return final_answer