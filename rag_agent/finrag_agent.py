import os
from pathlib import Path
from openai import OpenAI
from dotenv import load_dotenv

# [변경] ChromaDB 및 LangChain 관련 라이브러리 임포트
from langchain_chroma import Chroma
from langchain_openai import OpenAIEmbeddings

# 1. 환경 설정
load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# 전역 변수 (ChromaDB VectorStore)
vectorstore = None

# 경로 설정
CURRENT_FILE_PATH = Path(__file__).resolve() 
PROJECT_ROOT = CURRENT_FILE_PATH.parent.parent 
PROMPT_PATH = PROJECT_ROOT / "utils" / "system_prompt.md" 

# [변경] ChromaDB 데이터 경로 (../data/financial_terms)
CHROMA_DB_PATH = PROJECT_ROOT / "data" / "financial_terms"
COLLECTION_NAME = "financial_terms"

def load_knowledge_base():
    """ChromaDB 연결 설정"""
    global vectorstore
    if vectorstore is not None: return

    print("⏳ [RAG] ChromaDB 연결 중...")
    try:
        # 임베딩 모델 설정 (저장할 때 사용한 모델과 동일해야 함)
        embeddings = OpenAIEmbeddings(model="text-embedding-3-large")
        
        # 저장된 DB 로드
        vectorstore = Chroma(
            persist_directory=str(CHROMA_DB_PATH),
            embedding_function=embeddings,
            collection_name=COLLECTION_NAME,
            collection_metadata={"hnsw:space": "cosine"}
        )
        print(f"✅ ChromaDB 연결 완료 (경로: {CHROMA_DB_PATH})")
        
    except Exception as e:
        print(f"❌ ChromaDB 연결 오류: {e}")
        vectorstore = None

def read_prompt_file():
    """MD 파일에서 시스템 프롬프트 읽기"""
    try:
        with open(PROMPT_PATH, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return "You are a helpful assistant." # 파일 없을 시 기본값

# 🔥 핵심 함수: ChromaDB 검색으로 변경
# finrag_agent.py 내부

def get_rag_answer(korean_query, original_query=None):
    if vectorstore is None: load_knowledge_base()

    relevant_docs = []
    
    # 1. 문서 검색
    if vectorstore:
        results = vectorstore.similarity_search_with_score(korean_query, k=3)
        relevant_docs = results
    
    # 검색된 문서 정보 출력 (디버깅용)
    if relevant_docs:
        print("📑 [Retrieved Docs]:")
        for doc, score in relevant_docs:
            # 거리(Distance)를 유사도(Similarity)로 변환하여 출력 (1 - distance)
            similarity = 1 - score
            print(f"   - {doc.metadata.get('word', 'Unknown')} (유사도: {similarity:.4f})")
    else:
        print("⚠️ [Retrieved Docs]: 검색 결과 없음")
    
    # 2. 컨텍스트 및 출처(Citation) 구성
    context_text = ""
    citations = []
    
    if relevant_docs:
        for doc, score in relevant_docs:
            word = doc.metadata.get("word", "Term")
            raw_content = doc.page_content  # "더블딥: 경기침체가..." 형태
            
            # 🛠️ [수정 포인트] 내용에서 "단어: " 부분 제거하기
            # 저장할 때 "Word: Definition" 형식으로 저장했으므로, 첫 번째 콜론(:) 뒤만 씁니다.
            if ":" in raw_content:
                definition = raw_content.split(":", 1)[1].strip()
            else:
                definition = raw_content
            
            # 컨텍스트 구성
            context_text += f"Term: {word}\nDefinition: {definition}\n\n"
            
            # 출처 구성 (유사도 계산 포함)
            similarity = 1 - score
            citations.append(f"- **{word}**: {definition[:50]}... (유사도: {similarity:.2f})")
    else:
        context_text = "관련된 DB 정보가 없습니다. 일반적인 지식을 활용하세요."
        citations.append("- 검색된 관련 문서가 없습니다.")

    # 3. 프롬프트 로딩 및 구성
    system_template = read_prompt_file()
    formatted_system_prompt = system_template.format(context=context_text)

    # 4. LLM 호출
    response = client.chat.completions.create(
        model="gpt-5-mini",
        messages=[
            {"role": "system", "content": formatted_system_prompt},
            {"role": "user", "content": f"질문에 대해 초등학생 선생님처럼 핵심만 짧게 답변해 주세요: {korean_query}"}
        ]
    )
    
    ai_answer = response.choices[0].message.content.strip()

    # 5. 최종 출력 포맷팅
    final_output = f"""
### 🌏 질문 (Question)
- **Original**: {original_query if original_query else korean_query}
- **Translated**: {korean_query}

### 💡 선생님의 답변
{ai_answer}

---
### 📚 참고 문헌 (References)
{chr(10).join(citations)}
    """
    
    return final_output

if __name__ == "__main__":
    load_knowledge_base()
    # 테스트 실행
    print(get_rag_answer("집을 구하려면 어떻게 해야해?", "How can I find a house?"))