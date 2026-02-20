import streamlit as st
import time
import bcrypt
from dotenv import load_dotenv
import os
import sys
import subprocess

from utils.handle_sql import get_data, execute_query
from rag_agent.main_agent import run_fintech_agent, reset_global_context
from rag_agent.finrag_agent import load_knowledge_base

load_dotenv()

# ==========================================
# 1. 페이지 설정 및 디자인
# ==========================================
st.set_page_config(page_title="BeoTT Buddy", page_icon="img/버디_기본.png", layout="centered")

def local_css():
    st.markdown("""
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Poppins:wght@300;400;600;700&display=swap');
        html, body, [class*="css"] { font-family: 'Poppins', sans-serif; }
        .stApp {
            background-color: #F8FAFC;
            background-image: radial-gradient(#E0E7FF 1px, transparent 1px);
            background-size: 20px 20px;
        }
        [data-testid="stForm"] {
            background-color: rgba(255, 255, 255, 0.95);
            padding: 3rem;
            border-radius: 24px;
            box-shadow: 0 20px 40px -10px rgba(0, 0, 0, 0.05);
            border: 1px solid #EEF2FF;
            backdrop-filter: blur(10px);
        }
        div[data-baseweb="input"] > div {
            background-color: #F1F5F9;
            border-radius: 16px;
            border: 2px solid transparent;
            padding: 5px;
        }
        div[data-baseweb="input"] > div:focus-within {
            background-color: #FFFFFF;
            border: 2px solid #6366F1;
            box-shadow: 0 0 0 4px rgba(99, 102, 241, 0.1);
        }
        div.stButton > button {
            background: #FFFFFF;
            color: #64748B !important;
            border: 1px solid #CBD5E1 !important;
            padding: 0.5rem 1rem !important;
            width: 100%;
        }
        div.stButton > button:hover {
            background: #FFFFFF !important;
            color: #64748B !important;
            transform: translateY(-2px);
            box-shadow: 0 10px 20px -5px rgba(99, 102, 241, 0.4);
        }
        /* 보조 버튼 스타일 */
        button[kind="secondary"] {
            background: #FFFFFF;
            border: 1px solid #CBD5E1 !important;
            color: #64748B !important;
        }        
        [data-testid="stSidebar"] { background-color: #FFFFFF; border-right: 1px solid #E2E8F0; }
        h1, h2, h3 { color: #1E293B; }
        
        /* [요구사항 반영] 1. 아바타를 감싸는 부모 컨테이너 크기 자체를 키움 */
        [data-testid="stChatMessageAvatar"] {
            width: 80px !important;      /* 100px은 채팅창에서 너무 클 수 있어 80px로 예시를 작성했습니다. 원하시면 100px로 변경하세요. */
            height: 80px !important;
            min-width: 80px !important;  /* 주변 요소에 의해 찌그러지는 것 방지 */
        }

        /* [요구사항 반영] 2. 컨테이너 내부의 이미지는 부모 크기(100%)에 맞게 채움 */
        [data-testid="stChatMessageAvatar"] img,
        [data-testid="stChatMessageAvatar"] svg {
            width: 100% !important;  
            height: 100% !important; 
            max-width: 100% !important;
            border-radius: 50%;
            object-fit: cover;           /* 이미지가 비율에 맞게 예쁘게 채워지도록 설정 */
        }
    </style>
    """, unsafe_allow_html=True)

local_css()

# ChromaDB 연결 캐싱 및 초기 데이터 구축
@st.cache_resource
def init_chroma_connection():
    target_dir = "data/financial_terms/"
    needs_setup = False
    
    if not os.path.exists(target_dir):
        needs_setup = True
    else:
        files = os.listdir(target_dir)
        if len(files) == 0 or (len(files) == 1 and files[0] == "chroma.sqlite3"):
            needs_setup = True
            
    if needs_setup:
        print(f"DB 데이터가 비어있어 'utils/set_chromaDB.py' 스크립트를 실행합니다.")
        try:
            subprocess.run([sys.executable, "utils/set_chromaDB.py"], check=True)
            print("DB 초기화 및 데이터 임베딩이 성공적으로 완료되었습니다.")
        except subprocess.CalledProcessError as e:
            print(f"DB 초기화 중 오류가 발생했습니다: {e}")
            return False
            
    load_knowledge_base()
    return True

init_chroma_connection()

# ==========================================
# 2. 세션 상태 초기화
# ==========================================
if 'logged_in' not in st.session_state:
    st.session_state['logged_in'] = False
if 'current_user' not in st.session_state:
    st.session_state['current_user'] = None
if 'user_name_real' not in st.session_state:
    st.session_state['user_name_real'] = None
if 'page' not in st.session_state:
    st.session_state['page'] = 'login'
if 'allowed_views' not in st.session_state:
    st.session_state['allowed_views'] = []

if 'messages' not in st.session_state:
    st.session_state['messages'] = [{"role": "assistant", "content": "안녕하세요! 저는 당신의 금융 친구 버디에요! 무엇을 도와드릴까요?"}]
if 'chat_sessions' not in st.session_state:
    st.session_state['chat_sessions'] = []
if 'user_input_text' not in st.session_state:
    st.session_state['user_input_text'] = ""
if "transfer_context" not in st.session_state:
    st.session_state["transfer_context"] = None
if "last_result" not in st.session_state:
    st.session_state["last_result"] = None
    
# ==========================================
# 3. 페이지 함수
# ==========================================

def login_page():
    st.write("")
    st.write("")
    
    col1, col2, col3 = st.columns([1, 5, 1]) 
    
    with col2:
        mode_title = "BeoTT"
        
        with st.form("login_form"):
            col_img_1, col_img_2, col_img_3 = st.columns([1.5, 2, 1.5]) 

            with col_img_2:
                st.image("img/버디_기본.png", width=400)
            st.markdown(f"<h2 style='text-align: center; color: #1E293B;'>{mode_title}</h2>", unsafe_allow_html=True)
            
            username = st.text_input("아이디 (Username)", placeholder="example@woorifis.com")
            password_input = st.text_input("계정 비밀번호 (Password)", type="password", placeholder="비밀번호를 입력하세요")
            
            st.markdown("####") 
            submitted = st.form_submit_button("로그인")
            
            if submitted:
                try:
                    sql = "SELECT pin_code, password, korean_name FROM members WHERE username = %s"
                    user_data = get_data(sql, (username,))
                    
                    if user_data:
                        db_pw = user_data[0]['password']
                        korean_name = user_data[0]['korean_name']
                        
                        target_hash = db_pw
                        
                        if not target_hash:
                             st.error("해당 로그인 방식에 대한 비밀번호가 설정되지 않았습니다.")
                        else:
                            if isinstance(target_hash, str):
                                target_hash = target_hash.encode('utf-8')
                            
                            if bcrypt.checkpw(password_input.encode('utf-8'), target_hash):
                                reset_global_context()
                                st.session_state['logged_in'] = True
                                st.session_state['current_user'] = username
                                st.session_state['user_name_real'] = korean_name
                                
                                st.session_state['messages'] = [{"role": "assistant", "content": "안녕하세요! 저는 당신의 금융 친구 버디에요! 무엇을 도와드릴까요?"}]
                                st.session_state["transfer_context"] = None
                                
                                from utils.create_view import create_user_views
                                view_names = create_user_views(username)
                                st.session_state['allowed_views'] = view_names

                                st.session_state['page'] = 'chat'
                                st.rerun()
                            else:
                                st.error("비밀번호가 일치하지 않습니다.")
                    else:
                        st.error("존재하지 않는 아이디입니다.")
                except Exception as e:
                    st.error(f"시스템 오류: {e}")

        st.write("")
        if st.button("✨ 회원가입", type="secondary", use_container_width=True):
            st.session_state['page'] = 'register'
            st.rerun()

def register_page():
    st.write("")
    
    col1, col2, col3 = st.columns([1, 5, 1])
    
    with col2:
        with st.form("register_form"):
            st.markdown("<h2 style='text-align: center;'>회원가입</h2>", unsafe_allow_html=True)
            
            new_user = st.text_input("아이디 (Username)", placeholder="unique_id")
            new_name = st.text_input("이름 (Korean Name)", placeholder="홍길동")
            
            st.markdown("---")
            st.markdown("**1. 계정 비밀번호 설정** (일반 로그인용)")
            new_pw = st.text_input("비밀번호", type="password")
            new_pw_cf = st.text_input("비밀번호 확인", type="password")
            
            st.markdown("**2. PIN 번호 설정** (간편 로그인용)")
            new_pin = st.text_input("PIN Code (숫자 6자리)", type="password", max_chars=6)
            new_pin_cf = st.text_input("PIN Code 확인", type="password", max_chars=6)
            
            new_lang = st.selectbox("선호 언어", ["ko", "en", "vi", "id"], index=0)
            
            st.markdown("####")
            submit = st.form_submit_button("가입 완료")
            
            if submit:
                if not all([new_user, new_name, new_pw, new_pin]):
                    st.error("모든 필수 정보를 입력해주세요.")
                elif new_pw != new_pw_cf:
                    st.error("계정 비밀번호가 일치하지 않습니다.")
                elif new_pin != new_pin_cf:
                    st.error("PIN 번호가 일치하지 않습니다.")
                elif len(new_pin) != 6 or not new_pin.isdigit():
                    st.error("PIN 번호는 6자리 숫자여야 합니다.")
                else:
                    try:
                        check_sql = "SELECT username FROM members WHERE username = %s"
                        if get_data(check_sql, (new_user,)):
                            st.error("이미 존재하는 아이디입니다.")
                        else:
                            hashed_pw = bcrypt.hashpw(new_pw.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
                            hashed_pin = bcrypt.hashpw(new_pin.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
                            
                            insert_sql = """
                                INSERT INTO members (username, korean_name, password, pin_code, preferred_language)
                                VALUES (%s, %s, %s, %s, %s)
                            """
                            execute_query(insert_sql, (new_user, new_name, hashed_pw, hashed_pin, new_lang))
                            
                            st.success(f"{new_name}님 가입 완료! 로그인 해주세요.")
                            time.sleep(1.5)
                            st.session_state['page'] = 'login'
                            st.rerun()
                    except Exception as e:
                        st.error(f"오류 발생: {e}")

        st.markdown("---")
        if st.button("로그인 화면으로 돌아가기", type="secondary"):
            st.session_state['page'] = 'login'
            st.rerun()

def chat_page():
    with st.sidebar:
        st.markdown(f"""
        <div style='background-color: #F1F5F9; padding: 15px; border-radius: 15px; margin-bottom: 20px;'>
            <h3 style='margin:0; color: #1E293B; font-size: 1.2rem;'>👋 반가워요!</h3>
            <p style='margin:0; color: #64748B; font-size: 0.9rem;'>
                <b>{st.session_state.get('user_name_real', '사용자')}</b>님
            </p>
        </div>
        """, unsafe_allow_html=True)

        if st.button("✨ 새 대화 시작", use_container_width=True):
            st.session_state['messages'] = [{"role": "assistant", "content": "안녕하세요! 저는 당신의 금융 친구 버디에요! 무엇을 도와드릴까요?"}]
            st.session_state["transfer_context"] = None
            st.session_state["last_result"] = None
            st.rerun()

        st.markdown("<div style='margin-top: auto;'></div>", unsafe_allow_html=True)
        st.markdown("---")
        if st.button("로그아웃", use_container_width=True):
            reset_global_context()
            
            st.session_state['logged_in'] = False
            st.session_state['current_user'] = None
            st.session_state['user_name_real'] = None
            
            st.session_state['messages'] = [{"role": "assistant", "content": "안녕하세요! 저는 당신의 금융 친구 버디에요! 무엇을 도와드릴까요?"}]
            st.session_state['transfer_context'] = None
            st.session_state['chat_sessions'] = []
            st.session_state['allowed_views'] = []
            
            st.session_state['page'] = 'login'
            st.rerun()

    st.caption("🔒 BeoTT Service | Powered by Buddy-Agent")

    # 1. 기존 메시지 렌더링 (아바타 로직 추가)
    for message in st.session_state['messages']:
        if message["role"] == "assistant":
            with st.chat_message(message["role"], avatar="img/버디_기본.png"):
                st.markdown(message["content"])
        else:
            with st.chat_message(message["role"]):
                st.markdown(message["content"])

    # 2. 확인 버튼 렌더링
    if (
        st.session_state.get("last_result") and
        st.session_state["last_result"].get("ui_type") == "confirm_buttons"
    ):
        def handle_confirm(signal: str):
            result = run_fintech_agent(
                signal,
                st.session_state['current_user'],
                st.session_state["transfer_context"],
                st.session_state['allowed_views']
            )
            if isinstance(result, dict):
                st.session_state["transfer_context"] = result.get("context")
                final_msg = result.get("message", "")
                if result.get("status") in ["SUCCESS", "CANCEL", "FAIL"]:
                    st.session_state["transfer_context"] = None
                    st.session_state["last_result"] = None
                else:
                    st.session_state["last_result"] = result
            else:
                st.session_state["transfer_context"] = None
                st.session_state["last_result"] = None
                final_msg = result

            st.session_state['messages'].append({"role": "assistant", "content": final_msg})
            st.rerun()

        _, col1, col2, _ = st.columns([3, 1, 1, 3])
        with col1:
            if st.button("✅", key="confirm_yes", type="primary", use_container_width=True):
                handle_confirm("__YES__")
        with col2:
            if st.button("❌", key="confirm_no", use_container_width=True):
                handle_confirm("__NO__")

    # 3. 사용자 입력 처리
    if user_input := st.chat_input("메시지를 입력해 주세요..."):
        st.session_state['messages'].append({"role": "user", "content": user_input})
        with st.chat_message("user"):
            st.markdown(user_input)

        # [요구사항 반영] 1단계: '생각 중' 상태를 보여줄 임시 컨테이너 생성
        thinking_placeholder = st.empty()
        
        # [요구사항 반영] 2단계: 임시 컨테이너에 '생각' 아바타 적용
        with thinking_placeholder.chat_message("assistant", avatar="img/버디_생각.png"):
            with st.spinner("버디가 답변을 생성하고 있어요..."):
                try:
                    result = run_fintech_agent(
                        user_input,
                        st.session_state['current_user'],
                        st.session_state.get("transfer_context"),
                        st.session_state['allowed_views']
                    )

                    if isinstance(result, dict):
                        if result.get("context"):
                            st.session_state["transfer_context"] = result["context"]
                        else:
                            st.session_state["transfer_context"] = None

                        st.session_state["last_result"] = result
                        final_response = result.get("message", "")

                        if result.get("status") in ["SUCCESS", "CANCEL", "FAIL"]:
                            st.session_state["transfer_context"] = None
                            st.session_state["last_result"] = None
                    else:
                        st.session_state["transfer_context"] = None
                        st.session_state["last_result"] = None
                        final_response = result

                except Exception as e:
                    final_response = f"미안해요, 오류가 발생했어요: {e}"
                    st.session_state["last_result"] = None

        # [요구사항 반영] 3단계: 답변 생성이 완료되면 '생각 중' 임시 컨테이너 완전히 삭제
        thinking_placeholder.empty()

        # [요구사항 반영] 4단계: '기본' 아바타로 최종 결과 출력 블록 렌더링
        with st.chat_message("assistant", avatar="img/버디_답변.png"):
            message_placeholder = st.empty()
            
            # 스트리밍 효과
            streamed_text = ""
            for char in final_response:
                streamed_text += char
                time.sleep(0.01)
                message_placeholder.markdown(streamed_text + "▌")

            message_placeholder.markdown(streamed_text)
            st.session_state['messages'].append({"role": "assistant", "content": streamed_text})

        if st.session_state.get("last_result", {}) and \
           st.session_state["last_result"].get("ui_type") == "confirm_buttons":
            st.rerun()            

# ==========================================
# 4. 실행 로직
# ==========================================

if st.session_state['logged_in']:
    chat_page()
else:
    if st.session_state['page'] == 'login':
        login_page()
    elif st.session_state['page'] == 'register':
        register_page()