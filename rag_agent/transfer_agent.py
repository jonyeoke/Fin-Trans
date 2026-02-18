import os
import json
from pathlib import Path
from dotenv import load_dotenv
import bcrypt

from langchain_openai import ChatOpenAI
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser

# 사용자 원본 코드의 유틸리티 (DB 핸들러)
from utils.handle_sql import get_data, execute_query

# 1. 환경 설정
load_dotenv()
llm = ChatOpenAI(model="gpt-5-mini")

# ---------------------------------------------------------
# [설정] 프롬프트 경로 설정 및 로딩 함수
# ---------------------------------------------------------
CURRENT_DIR = Path(__file__).resolve().parent
PROMPT_DIR = CURRENT_DIR.parent /"rag_agent"/ "prompt" / "transfer"

def read_prompt(filename: str) -> str:
    """MD 파일을 읽어서 문자열로 반환하는 함수"""
    file_path = PROMPT_DIR / filename
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        print(f"❌ [Error] 프롬프트 파일을 찾을 수 없습니다: {file_path}")
        return ""

# ---------------------------------------------------------
# 체인 구성: 송금 정보 추출 (MD 파일 적용)
# ---------------------------------------------------------
transfer_extract_template = read_prompt("transfer_01_extract.md")
transfer_extract_prompt = PromptTemplate.from_template(transfer_extract_template)

transfer_chain = (
    transfer_extract_prompt
    | llm
    | StrOutputParser()
)

# ---------------------------------------------------------
# JSON 파싱
# ---------------------------------------------------------
def parse_transfer_json(text: str):
    try:
        # 마크다운 코드 블록 제거 처리 추가
        text = text.strip().replace("```json", "").replace("```", "")
        return json.loads(text)
    except:
        return {"target": None, "amount": None, "currency": None}

# ---------------------------------------------------------
# DB 검증 함수들 (사용자 원본 로직 유지)
# ---------------------------------------------------------

def get_member_id(username):
    query = f"SELECT user_id FROM members WHERE username = '{username}'"
    result = get_data(query)
    return result[0]["user_id"] if result else None

def get_contact(user_id, target):
    query = f"""
    SELECT contact_id, contact_name, relationship, target_currency_code
    FROM contacts
    WHERE user_id = {user_id}
    AND contact_name = '{target}'
    """
    result = get_data(query)
    return result[0] if result else None

def get_all_contacts(user_id):
    query = f"SELECT contact_name, relationship FROM contacts WHERE user_id = {user_id}"
    return get_data(query)

def resolve_contact_name(user_id, user_input):
    contacts = get_all_contacts(user_id)
    user_input = user_input.strip()

    for c in contacts:
        if user_input == c["contact_name"]:
            return c["contact_name"]
        if c.get("relationship") and user_input == c["relationship"]:
            return c["contact_name"]
    return None

def get_primary_account(user_id):
    query = f"""
    SELECT account_id, balance, currency_code
    FROM accounts
    WHERE user_id = {user_id}
    AND is_primary = 1
    """
    result = get_data(query)
    return result[0] if result else None

def get_user_password(username):
    query = f"""
    SELECT pin_code FROM members WHERE username = '{username}'
    """
    result = get_data(query)
    return result[0]["pin_code"] if result else None

def get_exchange_rate(currency):
    if currency == "KRW":
        return 1.0

    query = f"""
    SELECT send_rate
    FROM exchange_rates
    WHERE currency_code = '{currency}'
    ORDER BY reference_date DESC
    LIMIT 1
    """
    result = get_data(query)
    if not result:
        return None
    return float(result[0]["send_rate"])

def update_balance(account_id, new_balance):
    query = f"UPDATE accounts SET balance = {new_balance} WHERE account_id = {account_id}"
    execute_query(query)

def insert_ledger(
    account_id, contact_id, amount_krw, balance_after, 
    exchange_rate, target_amount, target_currency
):
    query = f"""
    INSERT INTO ledger (
        account_id, contact_id, transaction_type, amount, balance_after,
        exchange_rate, target_amount, target_currency_code, description, category
    )
    VALUES (
        {account_id}, {contact_id}, 'TRANSFER', {-amount_krw}, {balance_after},
        {exchange_rate}, {target_amount}, '{target_currency}', '송금', '이체'
    )
    """
    execute_query(query)

# ---------------------------------------------------------
# 메인 송금 로직 (사용자 원본 로직 유지)
# ---------------------------------------------------------

def process_transfer(question: str, username: str, context: dict | None = None):
    
    context = context or {}

    user_id = get_member_id(username)
    if not user_id:
        return {"status": "ERROR", "message": "사용자를 찾을 수 없습니다."}

    # --------------------------------------------------
    # 1. PIN Code 입력 단계 (비밀번호 -> PIN Code 변경)
    # --------------------------------------------------
    if context.get("awaiting_password"):

        stored_pin = get_user_password(username)

        if not stored_pin:
            return {"status": "ERROR", "message": "사용자 정보를 찾을 수 없습니다."}

        if isinstance(stored_pin, str):
            stored_pin = stored_pin.encode('utf-8')
                            
        if bcrypt.checkpw(question.encode('utf-8'), stored_pin) == False:
            context["password_attempts"] = context.get("password_attempts", 0) + 1

            if context["password_attempts"] >= 5:
                # [수정] 멘트 변경: 비밀번호 -> PIN Code
                return {"status": "FAIL", "message": "PIN Code 5회 오류. 송금 실패."}

            return {
                "status": "NEED_PASSWORD",
                # [수정] 멘트 변경: 비밀번호 -> PIN Code
                "message": f"PIN Code 오류. 남은 기회: {5 - context['password_attempts']}",
                "context": context
            }

        # 송금 실행
        account = get_primary_account(user_id)
        contact = get_contact(user_id, context["target"])

        new_balance = float(account["balance"]) - context["amount_krw"]

        update_balance(account["account_id"], new_balance)

        insert_ledger(
            account["account_id"],
            contact["contact_id"],
            context["amount_krw"],
            new_balance,
            context["exchange_rate"],
            context["amount"],
            context["currency"]
        )

        # [수정] 송금 완료 시 잔액(new_balance) 표기 추가
        return {"status": "SUCCESS", "message": f"송금이 완료되었습니다. (잔액: {int(new_balance):,}원)"}

    # --------------------------------------------------
    # 2. 확인 단계
    # --------------------------------------------------
    if context.get("awaiting_confirm"):
        if question.lower() not in ["y", "yes", "네", "응", "맞아"]:
            return {"status": "CANCEL", "message": "송금이 취소되었습니다."}

        context["awaiting_confirm"] = False
        context["awaiting_password"] = True
        context["password_attempts"] = 0

        return {
            "status": "NEED_PASSWORD",
            # [수정] 멘트 변경: 비밀번호 -> PIN Code
            "message": "PIN Code를 입력해주세요.",
            "context": context
        }
    
    # --------------------------------------------------
    # 3. HITL 단계 (부족 정보 보완)
    # --------------------------------------------------
    if context.get("missing_field"):
        field = context["missing_field"]

        if field == "target":
            resolved = resolve_contact_name(user_id, question)
            if not resolved:
                return {
                    "status": "NEED_INFO",
                    "field": "target",
                    "message": "연락처에서 찾을 수 없습니다. 정확한 이름을 입력해주세요.",
                    "context": context
                }
            context["target"] = resolved

        elif field == "amount":
            try:
                # 단위 처리 등은 프롬프트가 해주지만, 여기서도 간단한 정제
                clean_amt = question.strip().replace(",", "").replace("원", "")
                context["amount"] = float(clean_amt)
            except:
                return {
                    "status": "NEED_INFO",
                    "field": "amount",
                    "message": "금액을 숫자로 입력해주세요.",
                    "context": context
                }

        elif field == "currency":
            context["currency"] = question.strip().upper()

        context.pop("missing_field")

    # --------------------------------------------------
    # 4. 최초 요청 (LLM 추출)
    # --------------------------------------------------
    if not context.get("target") and not context.get("amount") and not context.get("currency"):
        raw_result = transfer_chain.invoke({"question": question})
        info = parse_transfer_json(raw_result)

        target = info.get("target")
        amount = info.get("amount")
        currency = info.get("currency")

        context["target"] = target
        context["amount"] = amount
        context["currency"] = currency

    else:
        target = context.get("target")
        amount = context.get("amount")
        currency = context.get("currency")

    # 대상 추론 및 검증
    if not target:
        context["missing_field"] = "target"
        return {
            "status": "NEED_INFO",
            "field": "target",
            "message": "송금할 대상을 입력해주세요.",
            "context": context
        }

    resolved = resolve_contact_name(user_id, target)
    if resolved:
        context["target"] = resolved
    if not resolved:
        context["missing_field"] = "target"
        return {
            "status": "NEED_INFO",
            "field": "target",
            "message": "연락처에서 찾을 수 없습니다. 정확한 이름을 입력해주세요.",
            "context": context
        }

    if not amount:
        context["missing_field"] = "amount"
        return {
            "status": "NEED_INFO",
            "field": "amount",
            "message": "송금 금액을 입력해주세요.",
            "context": context
        }

    if not currency:
        # 고도화된 프롬프트는 KRW를 기본값으로 잡을 수 있으나, 만약 null이면 물어봄
        # 여기서 기본값 처리를 코드 레벨에서도 한 번 더 할 수 있음
        context["currency"] = "KRW"
        currency = "KRW"

    rate = get_exchange_rate(currency)
    if rate is None:
        return {
            "status": "ERROR",
            "message": f"{currency} 환율 정보를 찾을 수 없습니다."
        }
    
    account = get_primary_account(user_id)
    if not account:
        return {"status": "ERROR", "message": "주 계좌를 찾을 수 없습니다."}

    amount_krw = float(amount) * rate

    if amount_krw > float(account["balance"]):
        return {"status": "ERROR", "message": "잔액이 부족합니다."}

    context = {
        "target": resolved,
        "amount": float(amount),
        "currency": currency,
        "amount_krw": amount_krw,
        "exchange_rate": rate,
        "awaiting_confirm": True
    }

    return {
        "status": "CONFIRM",
        "message": f"{resolved}에게 {amount} {currency} ({round(amount_krw,2)}원) 송금하시겠습니까? (y/n)",
        "context": context
    }

# ---------------------------------------------------------
# 외부 호출 함수
# ---------------------------------------------------------
def get_transfer_answer(question, username, context=None):
    try:
        return process_transfer(question, username, context)
    except Exception as e:
        return f"송금 처리 중 오류가 발생했습니다: {e}"

if __name__ == "__main__":
    print("Transfer Agent Ready")