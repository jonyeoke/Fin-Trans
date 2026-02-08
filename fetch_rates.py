import requests
import os
import sys
import pandas as pd
import logging
from datetime import datetime, timedelta
from dotenv import load_dotenv

# utils 폴더의 handle_sql.py에서 함수 불러오기
try:
    from utils.handle_sql import execute_query, execute_many
except ImportError:
    sys.path.append(os.path.dirname(os.path.abspath(__file__)))
    from utils.handle_sql import execute_query, execute_many

# .env 파일 로드
load_dotenv()

# --- [로깅 설정] ---
def setup_logging():
    # 1. logs 폴더 생성
    log_dir = "logs"
    os.makedirs(log_dir, exist_ok=True)
    
    # 2. 로그 파일 경로 (execution.log 로 고정하여 매번 덮어쓰기)
    log_file = os.path.join(log_dir, "execution.log")

    # 3. 로거 설정
    # 'filemode="w"' -> 파일을 열 때마다 기존 내용을 지우고 새로 씀 (덮어쓰기)
    # 'filemode="a"' -> 기존 내용 뒤에 계속 이어 붙이기 (Append)
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] %(levelname)s: %(message)s",
        handlers=[
            logging.FileHandler(log_file, mode='w', encoding='utf-8'), # 파일 저장 (덮어쓰기 모드)
            logging.StreamHandler(sys.stdout) # 터미널 출력
        ]
    )
    logging.info("📝 로그 설정 완료. 자동화 작업을 시작합니다.")

def fetch_koreaexim_rates():
    """한국수출입은행 API에서 환율 정보를 가져옵니다."""
    auth_key = os.getenv('EXCHANGE_KEY')
    if not auth_key:
        logging.error("❌ Error: 환경변수 EXCHANGE_KEY를 찾을 수 없습니다.")
        return None, None

    target_date = datetime.now()
    max_retries = 10 
    
    url = "https://www.koreaexim.go.kr/site/program/financial/exchangeJSON"

    for i in range(max_retries):
        search_date_str = target_date.strftime("%Y%m%d")
        logging.info(f"🔄 시도 {i+1}: {search_date_str} 데이터 조회 중...")

        params = {
            'authkey': auth_key,
            'searchdate': search_date_str,
            'data': 'AP01'
        }

        try:
            response = requests.get(url, params=params, verify=False)
            
            if response.status_code == 200:
                data = response.json()
                if isinstance(data, list) and data:
                    logging.info(f"✅ 성공! {search_date_str} 기준 데이터를 가져왔습니다.")
                    return data, search_date_str 
                else:
                    logging.warning(f"⚠️ {search_date_str} 데이터 없음 (휴일 등)")
            else:
                logging.error(f"❌ 요청 실패 (Status: {response.status_code})")

        except Exception as e:
            logging.error(f"❌ API 요청 중 에러 발생: {e}")

        target_date -= timedelta(days=1)

    logging.error("❌ 최근 10일간의 데이터를 찾을 수 없습니다.")
    return None, None

def save_to_mysql(df, date_str):
    """전처리된 데이터를 MySQL에 저장합니다."""
    formatted_date = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"

    try:
        logging.info(f"🔌 MySQL 저장 시작 (기준일: {formatted_date})")
        
        # 1. 기존 데이터 삭제
        delete_sql = "DELETE FROM exchange_rates WHERE reference_date = %s"
        deleted_count = execute_query(delete_sql, (formatted_date,))
        logging.info(f"🗑️  기존 데이터 {deleted_count}건 삭제 완료.")

        # 2. 새 데이터 삽입
        insert_sql = """
        INSERT INTO exchange_rates 
        (reference_date, currency_code, currency_name, deal_bas_r, ttb, tts)
        VALUES (%s, %s, %s, %s, %s, %s)
        """
        
        data_list = []
        for _, row in df.iterrows():
            data_list.append((
                formatted_date,
                row['통화코드'],
                row['국가/통화명'],
                row['매매기준율'],
                row['전신환_받으실때'],
                row['전신환_보내실때']
            ))
        
        inserted_count = execute_many(insert_sql, data_list)
        logging.info(f"📥 새 데이터 {inserted_count}건 DB 저장 완료.")

    except Exception as e:
        logging.error(f"❌ DB 저장 중 오류 발생: {e}")

def process_and_save(data, date_str):
    """데이터 전처리(콤마 제거 포함) 및 저장"""
    if not data:
        return

    # 1. DataFrame 생성
    df = pd.DataFrame(data)

    # 2. 컬럼명 소문자로 통일
    df.columns = [c.lower() for c in df.columns]

    column_mapping = {
        'cur_unit': '통화코드',
        'cur_nm': '국가/통화명',
        'ttb': '전신환_받으실때',
        'tts': '전신환_보내실때',
        'deal_bas_r': '매매기준율',
        'bkpr': '장부가격',
        'yy_efee_r': '년환가료율',
        'ten_dd_efee_r': '10일환가료율',
        'kftc_deal_bas_r': '서울외국환중개_매매기준율',
        'kftc_bkpr': '서울외국환중개_장부가격'
    }

    rename_map = {k: v for k, v in column_mapping.items() if k in df.columns}
    df.rename(columns=rename_map, inplace=True)
    
    # 3. 기준일자 추가
    df['기준일자'] = date_str
    
    # 4. 숫자 컬럼 변환
    target_numeric_cols = [
        '매매기준율', '전신환_받으실때', '전신환_보내실때', 
        '장부가격', '년환가료율', '10일환가료율', 
        '서울외국환중개_매매기준율', '서울외국환중개_장부가격'
    ]
    
    for col in target_numeric_cols:
        if col in df.columns:
            df[col] = df[col].astype(str).str.replace(",", "").str.strip()
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)

    # 5. 저장할 컬럼 순서 정리
    final_columns = ['기준일자'] + list(rename_map.values())
    final_columns = [c for c in final_columns if c in df.columns]
    df = df[final_columns]

    # --- CSV 저장 ---
    save_dir = "data"
    os.makedirs(save_dir, exist_ok=True)
    csv_filename = os.path.join(save_dir, "exchange_rates.csv")
    df.to_csv(csv_filename, index=False, encoding='utf-8-sig')
    logging.info(f"💾 CSV 파일 저장 완료: {csv_filename}")
    
    # --- MySQL 저장 ---
    save_to_mysql(df, date_str)

if __name__ == "__main__":
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    # 로깅 시작 설정
    setup_logging()

    logging.info("🚀 환율 정보 업데이트 시작...")
    rates_data, rates_date = fetch_koreaexim_rates()
    
    if rates_data:
        process_and_save(rates_data, rates_date)
        logging.info("🎉 모든 작업이 성공적으로 완료되었습니다.")
    else:
        logging.warning("⚠️ 저장할 데이터가 없어 종료합니다.")