import os
import time
from datetime import datetime
from pathlib import Path
from typing import TypedDict
from dotenv import load_dotenv
from tavily import TavilyClient

from langchain_openai import ChatOpenAI
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langgraph.graph import StateGraph, START, END

load_dotenv()

# LLM 설정 (일관성을 위해 ChatOpenAI 사용)
llm = ChatOpenAI(model="gpt-5-mini")

# ---------------------------------------------------------
# [NEW] 로그 출력 유틸리티 함수
# ---------------------------------------------------------
def print_log(step_name: str, status: str, start_time: float = None, extra_info: str = None):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    
    if status == "start":
        print(f"[{now}] ⏳ [{step_name}] 시작...")
        return time.time()
        
    elif status == "end" and start_time is not None:
        elapsed = time.time() - start_time
        log_msg = f"[{now}] ✅ [{step_name}] 완료 (소요시간: {elapsed:.3f}초)"
        if extra_info:
            log_msg += f"\n   👉 {extra_info}"
        print(log_msg)
        return elapsed

# ---------------------------------------------------------
# 프롬프트
# ---------------------------------------------------------
CURRENT_DIR = Path(__file__).resolve().parent
PROMPT_DIR = CURRENT_DIR / "prompt" / "web_search"

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
# [LangGraph] 웹 검색 상태
# ---------------------------------------------------------
class WebSearchState(TypedDict, total=False):
    question: str
    context: str
    sources: list
    answer: str

# ---------------------------------------------------------
# [LangGraph] 노드
# ---------------------------------------------------------
def node_answer(state: WebSearchState) -> dict:
    t0 = print_log("Web Search: LLM 기반 최종 답변 생성 (node_answer)", "start")
    template = read_prompt("web_search_01_response.md")
    prompt = PromptTemplate.from_template(template)
    chain = prompt | llm | StrOutputParser()
    answer = chain.invoke({"question": state["question"], "context": state.get("context", "")})
    print_log("Web Search: LLM 기반 최종 답변 생성 (node_answer)", "end", t0)
    return {"answer": answer}

# 그래프: search 결과가 이미 state에 있으므로, answer 노드만 있으면 됨.
# 검색은 클래스 내부에서 하고, context/sources를 state에 넣은 뒤 그래프 호출
def _build_web_search_graph():
    builder = StateGraph(WebSearchState)
    builder.add_node("answer", node_answer)
    builder.add_edge(START, "answer")
    builder.add_edge("answer", END)
    return builder.compile()

_web_search_graph = None

def _get_web_search_graph():
    global _web_search_graph
    if _web_search_graph is None:
        _web_search_graph = _build_web_search_graph()
    return _web_search_graph

# ---------------------------------------------------------
# WebSearchRAG 클래스 (LangGraph 사용)
# ---------------------------------------------------------
class WebSearchRAG:
    def __init__(self):
        tavily_api_key = os.getenv("TAVILY_API_KEY")
        if not tavily_api_key:
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
            print(f"[{now}] ⚠️ [Warning] TAVILY_API_KEY가 설정되지 않았습니다. .env 파일을 확인해주세요.")
        self.tavily = TavilyClient(api_key=tavily_api_key)

    def web_search(self, query):
        """실시간 웹 검색 및 답변 생성 (LangGraph)"""
        print("\n" + "-"*50)
        total_t0 = print_log("Web Search RAG 파이프라인", "start", extra_info=f"검색 쿼리: '{query}'")
        
        try:
            # 1. Tavily API 웹 검색
            t0_search = print_log("Tavily API 웹 검색", "start")
            search_results = self.tavily.search(query, max_results=3)
            
            context_parts = []
            sources = []
            for i, result in enumerate(search_results.get("results", []), 1):
                title = result.get("title", "No Title")
                url = result.get("url", "#")
                content = result.get("content", "")
                context_parts.append(f"=== [Source {i}] {title} ===\nURL: {url}\nContent: {content}\n")
                sources.append({"title": title, "url": url})
            context_str = "\n".join(context_parts)

            print_log("Tavily API 웹 검색", "end", t0_search, extra_info=f"가져온 소스 개수: {len(sources)}개")

            if not context_str:
                print_log("Web Search RAG 파이프라인", "end", total_t0, extra_info="검색 결과 없음")
                print("-" * 50 + "\n")
                return {"answer": "검색 결과가 없습니다.", "sources": [], "source_type": "Web Search"}

            # 2. LangGraph를 통한 답변 생성
            graph = _get_web_search_graph()
            result_state = graph.invoke({"question": query, "context": context_str, "sources": sources})
            answer = result_state.get("answer", "답변 생성 실패")

            print_log("Web Search RAG 파이프라인", "end", total_t0, extra_info="검색 및 답변 생성 완료")
            print("-" * 50 + "\n")
            
            return {
                "answer": answer,
                "sources": sources,
                "source_type": "Web Search",
            }
        except Exception as e:
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
            print(f"[{now}] ❌ [Web Search Error]: {e}")
            print("-" * 50 + "\n")
            return {
                "answer": "죄송합니다. 웹 검색 중 오류가 발생했습니다.",
                "sources": [],
                "source_type": "Error",
            }

# --- 테스트 코드 ---
if __name__ == "__main__":
    rag = WebSearchRAG()
    q = "현재 삼성전자 주가는?"
    result = rag.web_search(q)
    print(f"\n{'='*80}")
    print(f"📝 질문: {q}")
    print(f"{'='*80}\n")
    print(f"💡 답변:\n{result['answer']}\n")
    print(f"📚 출처:")
    for src in result["sources"]:
        print(f" - {src['title']} ({src['url']})")