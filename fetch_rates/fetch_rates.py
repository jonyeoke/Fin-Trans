import requests
import os
import sys
import pandas as pd
import logging
import re
import io
from datetime import datetime
from dotenv import load_dotenv

current_file_path = os.path.abspath(__file__)
project_root = os.path.dirname(os.path.dirname(current_file_path))

if project_root not in sys.path:
    sys.path.append(project_root)

try:
    from utils.handle_sql import execute_query, execute_many
except ImportError as e:
    logging.error(f"❌ utils 폴더를 찾을 수 없습니다. 경로 확인 필요: {e}")
    sys.exit(1)

load_dotenv()

# --- [로깅 설정] ---
def setup_logging():
    log_dir = "logs"
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, "execution.log")

    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] %(levelname)s: %(message)s",
        handlers=[
            logging.FileHandler(log_file, mode='w', encoding='utf-8-sig'),
            logging.StreamHandler(sys.stdout)
        ]
    )

def fetch_naver_rates():
    """네이버 금융 환율 정보를 가져옵니다."""
    url = "https://finance.naver.com/marketindex/exchangeList.naver"
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }

    logging.info("🔄 네이버 금융 데이터 요청 중...")

    try:
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            response.encoding = 'cp949' # 네이버 금융 인코딩
            
            now = datetime.now()
            date_str = now.strftime("%Y%m%d")
            
            save_dir = "data"
            os.makedirs(save_dir, exist_ok=True)
            
            # HTML 파일 저장
            html_filename = os.path.join(save_dir, "naver_exchange.html")
            try:
                with open(html_filename, "w", encoding="utf-8-sig") as f:
                    f.write(response.text)
            except Exception:
                pass # HTML 저장 실패는 로그 생략

            # 데이터 파싱
            try:
                html_io = io.StringIO(response.text)
                dfs = pd.read_html(html_io, header=1)
                
                if dfs:
                    df = dfs[0]
                    target_df = df.iloc[:, [0, 1, 4, 5]].copy()
                    target_df.columns = ['raw_name', '매매기준율', '송금_보내실때', '송금_받으실때']
                    
                    logging.info(f"✅ 파싱 성공! 데이터 {len(target_df)}건을 찾았습니다.")
                    return target_df, date_str
                else:
                    return None, None

            except Exception as parse_error:
                logging.error(f"⚠️ 파싱 중 에러 발생: {parse_error}")
                return None, None
        else:
            return None, None

    except Exception as e:
        logging.error(f"❌ 크롤링 에러: {e}")
        return None, None

def process_and_save(df, date_str):
    """데이터 전처리 및 저장"""
    if df is None or df.empty:
        return

    df = df.copy()

    # 1. 국가명과 통화코드 분리
    def parse_currency(text):
        text = str(text).strip()
        match = re.search(r'^(.*?)\s+([A-Z]{3})', text)
        if match:
            return match.group(1).strip(), match.group(2).strip()
        return text, 'KRW'

    df[['국가명', '통화명']] = df['raw_name'].apply(lambda x: pd.Series(parse_currency(x)))

    # 2. 숫자 데이터 전처리
    numeric_cols = ['매매기준율', '송금_보내실때', '송금_받으실때']
    for col in numeric_cols:
        df[col] = df[col].astype(str).str.replace(",", "").str.strip()
        df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)

    # 3. 기준일자 추가
    df['기준일자'] = date_str

    # 4. CSV 저장 (요청하신 순서: 통화명, 국가명, 매매기준율, 보내실때, 받으실때)
    final_columns = ['기준일자', '통화명', '국가명', '매매기준율', '송금_보내실때', '송금_받으실때']
    df = df[final_columns]

    save_dir = "data"
    csv_filename = os.path.join(save_dir, "exchange_rates.csv")
    df.to_csv(csv_filename, index=False, encoding='utf-8-sig')
    logging.info(f"💾 CSV 저장 완료: {csv_filename}")
    
    # --- MySQL 저장 ---
    save_to_mysql(df, date_str)

def save_to_mysql(df, date_str):
    """MySQL 데이터베이스에 저장 (수정된 테이블 구조 반영)"""
    formatted_date = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"

    try:
        logging.info(f"🔌 MySQL 저장 시작 (기준일: {formatted_date})")
        
        # 1. 기존 데이터 삭제
        delete_sql = "DELETE FROM exchange_rates WHERE reference_date = %s or reference_date != %s"
        execute_query(delete_sql, (formatted_date,formatted_date))
        
        # 2. 새 데이터 삽입 (컬럼명 변경 반영: base_rate, send_rate, get_rate)
        insert_sql = """
        INSERT INTO exchange_rates 
        (reference_date, currency_code, currency_name, base_rate, send_rate, get_rate)
        VALUES (%s, %s, %s, %s, %s, %s)
        """
        
        data_list = []
        for _, row in df.iterrows():
            data_list.append((
                formatted_date,
                row['통화명'],        # currency_code
                row['국가명'],        # currency_name
                row['매매기준율'],     # base_rate
                row['송금_보내실때'],   # send_rate
                row['송금_받으실때']    # get_rate
            ))
        
        inserted_count = execute_many(insert_sql, data_list)
        logging.info(f"📥 DB 저장 완료: {inserted_count}건")

    except Exception as e:
        logging.error(f"❌ DB 저장 오류: {e}")

if __name__ == "__main__":
    setup_logging()
    
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    logging.info("🚀 환율 정보 업데이트 시작...")
    
    rates_data, rates_date = fetch_naver_rates()
    
    if rates_data is not None:
        process_and_save(rates_data, rates_date)
        logging.info("🎉 작업 완료")
    else:
        logging.warning("⚠️ 데이터 없음")