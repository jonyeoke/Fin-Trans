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
    # ==========================================
    # 공통 정적 CSS
    # ==========================================
    st.markdown("""
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Poppins:wght@300;400;500;600;700&display=swap');
        html, body, [class*="css"] { 
            font-family: 'Poppins', sans-serif; 
        }
        
        .main .block-container { padding-top: 2rem; padding-bottom: 2rem; }
        
        [data-testid="stForm"] {
            background-color: #FFFFFF; padding: 3.5rem; border-radius: 28px;
            box-shadow: 0 10px 30px rgba(0, 0, 0, 0.1); border: 1px solid #E2E8F0;
        }
        [data-testid="stImage"] { display: flex; justify-content: center; align-items: center; }
        
        /* 폼 입력 필드 (로그인/회원가입) */
        div[data-baseweb="input"] {
            background-color: #F1F5F9 !important; border-radius: 8px !important;
            border: 1px solid transparent !important; transition: all 0.3s ease;
        }
        div[data-baseweb="input"]:focus-within { border-color: #FF4B4B !important; transform: translateY(-1px); }
        div[data-baseweb="input"] div { background-color: transparent !important; }
        div[data-baseweb="base-input"] { padding-top: 8px !important; padding-bottom: 8px !important; }           

        /* 브라우저 자동완성(Autofill) 배경색 간섭 방지 */
        input:-webkit-autofill,
        input:-webkit-autofill:hover, 
        input:-webkit-autofill:focus, 
        input:-webkit-autofill:active {
            -webkit-box-shadow: 0 0 0 30px #F1F5F9 inset !important; /* 겉 껍데기와 똑같은 회색으로 내부를 꽉 채움 */
            -webkit-text-fill-color: #1E293B !important; /* 글자색 유지 */
            transition: background-color 5000s ease-in-out 0s; /* 배경색이 바뀌는 것을 투명하게 지연시킴 */
        }
        
        /* 버튼 스타일 */
        div.stButton > button {
            background: #FFFFFF; color: #64748B !important; border: 1px solid #CBD5E1 !important;
            padding: 0.5rem 1rem !important; width: 100%;
        }
        div.stButton > button:hover {
            background: #FFFFFF !important; color: #64748B !important;
            transform: translateY(-2px); box-shadow: 0 10px 20px -5px rgba(99, 102, 241, 0.4);
        }
        button[kind="secondary"] { 
            background: #FFFFFF; 
            border: 1px solid #CBD5E1 !important; 
            color: #64748B !important; 
        }  
                
        /* 메시지 버블 스타일 */
        [data-testid="stChatMessage"][data-message-author="user"] {
            background-color: #667eea !important; border-radius: 18px 18px 4px 18px !important;
            padding: 0.75rem 1rem !important; margin-left: auto !important; margin-right: 0 !important;
            max-width: 70% !important; box-shadow: 0 2px 8px rgba(102, 126, 234, 0.2) !important;
        }
        [data-testid="stChatMessage"][data-message-author="user"] p,
        [data-testid="stChatMessage"][data-message-author="user"] div,
        [data-testid="stChatMessage"][data-message-author="user"] span { color: #FFFFFF !important; }
        
        [data-testid="stChatMessage"][data-message-author="assistant"] {
            background-color: #F1F5F9 !important; border-radius: 18px 18px 18px 4px !important;
            padding: 0.75rem 1rem !important; margin-left: 0 !important; margin-right: auto !important;
            max-width: 70% !important; box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08) !important; border: 1px solid #E2E8F0 !important;
        }
        [data-testid="stChatMessage"][data-message-author="assistant"] p,
        [data-testid="stChatMessage"][data-message-author="assistant"] div,
        [data-testid="stChatMessage"][data-message-author="assistant"] span { color: #1E293B !important; }
        
        /* ========== 채팅 입력 필드 ========== */
        [data-testid="stChatInput"] {
            background-color: #FFFFFF;
            border-radius: 20px;
            padding: 1rem;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
            border: 2px solid #E2E8F0;
        }
        [data-testid="stChatInput"]:focus-within {
            border-color: #E2E8F0 !important;
            box-shadow: 0 4px 12px rgba(102, 126, 234, 0.15);
        }
        [data-testid="stChatInput"] textarea {
            color: #1E293B !important;
        }

        /* 사이드바 프로필 카드 */
        [data-testid="stSidebar"] [class*="st-key-profile"] {
            background-color: #FFFFFF !important;
            border-radius: 16px !important;
            border: 1px solid #E2E8F0 !important;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08) !important;
            padding: 15px !important;
            margin-bottom: 20px !important;
        }
        
        [data-testid="stSidebar"] [class*="st-key-profile"] button{
            padding: 0.1rem 0.5rem !important;
            font-size: 0.85rem !important;
            min-height: 32px !important;
            margin-top: 5px !important;
            border-radius: 8px !important;
        }

        .stAlert { border-radius: 16px; border-left: 4px solid #ef4444; }
    </style>
    """, unsafe_allow_html=True)

    # 동적 배경색
    app_bg = "#FFFFFF" if st.session_state.get('logged_in', False) else "#F4F9FC"
    sidebar_bg = "#F4F9FC"

    st.markdown(f"""
    <style>
        .stApp {{ background-color: {app_bg} !important; background-image: none; }}
        [data-testid="stSidebar"], [data-testid="stSidebarHeader"] {{
            background-color: {sidebar_bg} !important;
            border-right: 1px solid #E2E8F0;
        }}
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
    
    _, col2, _ = st.columns([1, 5, 1]) 
    
    with col2:        
        with st.form("login_form"):
            _, col_img_2, _ = st.columns([0.5, 2, 0.5]) 

            with col_img_2:
                st.image("img/벗_로고.png")

            username = st.text_input("아이디 (ID)", placeholder="example@woorifis.com")
            password_input = st.text_input("계정 비밀번호 (Password)", type="password", placeholder="비밀번호를 입력하세요")
            
            st.markdown("####") 
            _, col_btn = st.columns([3.5, 1.5])
            with col_btn:
                submitted = st.form_submit_button("로그인", use_container_width=True)
            
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
        if st.button("✨ 회원가입 하러 가기", type="secondary", use_container_width=True):
            st.session_state['page'] = 'register'
            st.rerun()

def register_page():
    st.write("")
    
    _, col2, _ = st.columns([1, 5, 1])
    
    with col2:
        with st.form("register_form"):
            st.image("img/버디_회원가입.png")
            
            
            new_user = st.text_input("아이디 (ID)", placeholder="unique_id")
            new_name = st.text_input("이름 (Name)", placeholder="홍길동")
            
            new_pw = st.text_input("비밀번호 (Password)", type="password")
            new_pw_cf = st.text_input("비밀번호 확인 (Verify password)", type="password")
            
            new_pin = st.text_input("PIN 번호 (PIN code)", type="password")
            new_pin_cf = st.text_input("PIN 번호 확인 (Verify PIN code)", type="password")
            
            new_lang = st.selectbox("선호 언어 (Preferred language)", ["ko", "en", "vi", "id"], index=0)
            
            st.markdown("####")
            _, col_btn = st.columns([3.5, 1.5])
            with col_btn:
                submit = st.form_submit_button("회원가입", use_container_width=True)
            
            if submit:
                if not all([new_user, new_name, new_pw]):
                    st.error("모든 필수 정보를 입력해주세요.")
                elif new_pw != new_pw_cf:
                    st.error("계정 비밀번호가 일치하지 않습니다.")
                elif new_pin != new_pin_cf:
                    st.error("PIN 번호가 일치하지 않습니다.")
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

        st.write("")
        if st.button("✨ 로그인 화면으로 돌아가기", type="secondary", use_container_width=True):
            st.session_state['page'] = 'login'
            st.rerun()

def chat_page():
    with st.sidebar:
        # 1. 프로필 카드 컨테이너 (st.container 사용)
        with st.container(border=True, key="profile-card"):
            st.markdown("<span id='profile-card-marker' style='display:none' aria-hidden='true'></span>", unsafe_allow_html=True)
            st.markdown("<h3 style='margin: 0 0 10px 0; color: #1E293B; font-size: 1.3rem; font-weight: 700;'>👋 반가워요!</h3>", unsafe_allow_html=True)
            
            # 이름(6)과 로그아웃 버튼(4)의 비율로 배치
            col_name, col_logout = st.columns([6, 4])
            with col_name:
                user_name = st.session_state.get('user_name_real', '사용자')
                st.markdown(f"<div style='margin-top: 10px; color: #1E293B; font-size: 1rem; font-weight: 600;'>{user_name}님</div>", unsafe_allow_html=True)    
                        
            with col_logout:
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

        # 2. 새 대화 시작 버튼
        if st.button("✨ 새 대화 시작", use_container_width=True):
            st.session_state['messages'] = [{"role": "assistant", "content": "안녕하세요! 저는 당신의 금융 친구 버디에요! 무엇을 도와드릴까요?"}]
            st.session_state["transfer_context"] = None
            st.session_state["last_result"] = None
            st.rerun()

    st.caption("🔒 BeoTT Service | Powered by Buddy-Agent")

    # 1. 기존 메시지 렌더링 (아바타 로직 추가)
    for message in st.session_state['messages']:
        if message["role"] == "assistant":
            with st.chat_message(message["role"], avatar="img/버디_기본.png"):
                st.markdown(message["content"])
        else:
            # 사용자 아바타 추가 (이모지 또는 기본 아이콘)
            with st.chat_message(message["role"], avatar="👤"):
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

        st.markdown("<br>", unsafe_allow_html=True)
        _, col1, col2, _ = st.columns([2.5, 1.2, 1.2, 2.5])
        with col1:
            if st.button("✅ 확인", key="confirm_yes", type="primary", use_container_width=True):
                handle_confirm("__YES__")
        with col2:
            if st.button("❌ 취소", key="confirm_no", use_container_width=True):
                handle_confirm("__NO__")

    # 3. 사용자 입력 처리
    if user_input := st.chat_input("메시지를 입력해 주세요..."):
        st.session_state['messages'].append({"role": "user", "content": user_input})
        with st.chat_message("user", avatar="👤"):
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
                time.sleep(0.005)
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