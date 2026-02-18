from openai import OpenAI
from tavily import TavilyClient
from dotenv import load_dotenv 
import os

load_dotenv()

class WebSearchRAG:
    def __init__(self):
        self.openai = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        self.tavily = TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))
    
    def web_search(self, query):
        """실시간 검색"""
        search_results = self.tavily.search(query, max_results=3)
        
        # 컨텍스트 포맷팅 (출처 포함)
        context_parts = []
        for i, result in enumerate(search_results['results'], 1):
            context_parts.append(f"""
=== 출처 {i}: {result['title']} ===
URL: {result['url']}
내용: {result['content']}
""")
        context = "\n".join(context_parts)
        
        # GPT 답변 생성
        response = self.openai.chat.completions.create(
            model="gpt-5-mini",
            messages=[{
                "role": "user",
                "content": f"""다음 웹 검색 결과를 참고하여 질문에 답변해주세요.

질문: {query}

{context}

검색 결과를 바탕으로 정확하고 유용한 답변을 제공해주세요. 출처도 함께 언급해주세요."""
            }]
        )
        
        return {
            'answer': response.choices[0].message.content,
            'sources': [{'title': r['title'], 'url': r['url']} for r in search_results['results']],
            'source_type': '실시간 검색'
        }
    

# 사용 예시
if __name__ == "__main__":
    rag = WebSearchRAG()
    
    # 예쁘게 출력하는 함수
    def print_result(result, query):
        print(f"\n{'='*80}")
        print(f"📝 질문: {query}")
        print(f"{'='*80}\n")
        print(f"🤖 답변:\n{result['answer']}\n")
        print(f"{'='*80}")
        print(f"🔗 참고 출처 ({result['source_type']}):")
        print(f"{'='*80}")
        for i, source in enumerate(result['sources'], 1):
            print(f"{i}. {source['title']}")
            print(f"   {source['url']}\n")
        print(f"{'='*80}\n")
        
    result3 = rag.web_search("더블딥이 뭐야?")
    print_result(result3, "더블딥이 뭐야?")
    