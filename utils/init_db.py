import pymysql
import os
import bcrypt
import csv
from dotenv import load_dotenv

# .env 파일 로드
load_dotenv()

def get_connection():
    return pymysql.connect(
        host=os.getenv('DB_HOST'),
        user=os.getenv('DB_USER'),
        password=os.getenv('DB_PASSWORD'),
        db=os.getenv('DB_NAME'),
        port=int(os.getenv('DB_PORT', 3306)),
        charset='utf8mb4'
    )

def insert_from_csv(cursor, table_name, csv_file):
    """CSV 파일을 읽어서 테이블에 자동으로 INSERT 하는 함수"""
    print(f"📄 {csv_file} 읽어서 {table_name} 테이블에 데이터 적재 중...")
    
    # utf-8-sig로 읽어서 만약 있을 수 있는 BOM 문자를 제거합니다.
    with open(csv_file, 'r', encoding='utf-8-sig') as f:
        reader = csv.reader(f)
        headers = next(reader) # 첫 줄은 컬럼명
        
        # INSERT 쿼리를 동적으로 생성
        cols = ", ".join(headers)
        placeholders = ", ".join(["%s"] * len(headers))
        sql = f"INSERT INTO {table_name} ({cols}) VALUES ({placeholders})"
        
        for row in reader:
            # CSV 안의 'NULL' 문자열이나 빈 값을 파이썬의 None (DB의 NULL)로 변환
            clean_row = [val if val not in ('NULL', '') else None for val in row]
            cursor.execute(sql, clean_row)

def init_database():
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            print("🔧 데이터베이스 초기화 시작...")

            # 1. 외래키 체크 해제 (삭제/생성 시 오류 방지)
            cursor.execute("SET FOREIGN_KEY_CHECKS = 0")

            # 2. 기존 테이블 삭제 (종속성 역순으로 삭제)
            print("🗑️ 기존 테이블 삭제 중...")
            cursor.execute("DROP TABLE IF EXISTS ledger")
            cursor.execute("DROP TABLE IF EXISTS contacts")
            cursor.execute("DROP TABLE IF EXISTS accounts")
            cursor.execute("DROP TABLE IF EXISTS members")

            # 3. 테이블 새로 생성 
            print("✨ 테이블 생성 중...")
            
            # [members 테이블]
            cursor.execute("""
            CREATE TABLE members (
                user_id INT AUTO_INCREMENT PRIMARY KEY, 
                username VARCHAR(50) NOT NULL UNIQUE,
                password VARCHAR(255) NOT NULL,
                pin_code VARCHAR(255) NOT NULL,
                korean_name VARCHAR(50) NOT NULL,
                preferred_language VARCHAR(10) DEFAULT 'ko',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """)

            # [accounts 테이블]
            cursor.execute("""
            CREATE TABLE accounts (
                account_id INT AUTO_INCREMENT PRIMARY KEY,
                user_id INT NOT NULL,
                bank_name VARCHAR(50) NOT NULL,
                bank_code VARCHAR(10) DEFAULT NULL,
                account_number VARCHAR(50) NOT NULL,
                account_alias VARCHAR(50) DEFAULT NULL,
                balance DECIMAL(15,2) NOT NULL DEFAULT 0.00,
                is_primary TINYINT(1) NOT NULL DEFAULT 0,
                FOREIGN KEY (user_id) REFERENCES members(user_id) ON DELETE CASCADE
            )
            """)

            # [contacts 테이블]
            cursor.execute("""
            CREATE TABLE contacts (
                contact_id INT AUTO_INCREMENT PRIMARY KEY,
                user_id INT NOT NULL,
                contact_name VARCHAR(50) NOT NULL,
                relationship VARCHAR(30) DEFAULT NULL,
                bank_name VARCHAR(50) NOT NULL,
                bank_code VARCHAR(10) DEFAULT NULL,
                account_number VARCHAR(50) NOT NULL,
                swift_code VARCHAR(11) DEFAULT NULL,
                target_currency_code CHAR(3) NOT NULL DEFAULT 'KRW',
                last_transfer_date DATETIME DEFAULT NULL,
                FOREIGN KEY (user_id) REFERENCES members(user_id) ON DELETE CASCADE
            )
            """)

            # [ledger 테이블]
            cursor.execute("""
            CREATE TABLE ledger (
                transaction_id INT AUTO_INCREMENT PRIMARY KEY,
                account_id INT NOT NULL,
                contact_id INT DEFAULT NULL,
                transaction_type VARCHAR(20) NOT NULL,
                amount DECIMAL(15,2) NOT NULL,
                balance_after DECIMAL(15,2) NOT NULL,
                exchange_rate DECIMAL(10,4) NOT NULL DEFAULT 1.0000,
                target_amount DECIMAL(15,2) DEFAULT NULL,
                target_currency_code CHAR(3) DEFAULT NULL,
                description VARCHAR(255) DEFAULT NULL,
                category VARCHAR(50) DEFAULT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (account_id) REFERENCES accounts(account_id) ON DELETE CASCADE,
                FOREIGN KEY (contact_id) REFERENCES contacts(contact_id) ON DELETE SET NULL
            )
            """)
            
            # 4. 외래키 체크 다시 활성화
            cursor.execute("SET FOREIGN_KEY_CHECKS = 1")

            # 5. Members 더미 데이터 준비 (하드코딩된 원본 유지)
            dummy_users = [
                {
                    "username": "user_kr",
                    "korean_name": "김철수",
                    "pw": "1234",
                    "pin": "123456",
                    "lang": "ko"
                },
                {
                    "username": "user_us",
                    "korean_name": "John Miller",
                    "pw": "1234",
                    "pin": "123456",
                    "lang": "en"
                },
                {
                    "username": "user_vn",
                    "korean_name": "Nguyen Minh",
                    "pw": "1234",
                    "pin": "123456",
                    "lang": "vi"
                }
            ]

            print("🚀 members 더미 데이터 적재 중 (비밀번호 암호화 적용)...")
            insert_member_sql = """
            INSERT INTO members (username, korean_name, password, pin_code, preferred_language)
            VALUES (%s, %s, %s, %s, %s)
            """

            for u in dummy_users:
                hashed_pw = bcrypt.hashpw(u['pw'].encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
                hashed_pin = bcrypt.hashpw(u['pin'].encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
                
                cursor.execute(insert_member_sql, (
                    u['username'], 
                    u['korean_name'], 
                    hashed_pw, 
                    hashed_pin, 
                    u['lang']
                ))

            # 6. CSV 파일을 이용한 더미 데이터 적재 (의존성 순서대로 accounts -> contacts -> ledger)
            print("🚀 CSV 기반 나머지 더미 데이터 적재 시작...")
            # 현재 실행 중인 init_db.py 파일의 위치(utils)를 기준으로 부모 디렉토리의 data 폴더 경로 계산
            base_dir = os.path.dirname(os.path.abspath(__file__))
            data_dir = os.path.join(base_dir, '..', 'data')

            # 경로 확인용 출력 (생략 가능)
            print(f"📁 데이터 폴더 경로: {data_dir}")

            # os.path.join을 사용하여 OS에 맞는 안전한 절대 경로 생성
            insert_from_csv(cursor, 'accounts', os.path.join(data_dir, 'accounts_data.csv'))
            insert_from_csv(cursor, 'contacts', os.path.join(data_dir, 'contacts_data.csv'))
            insert_from_csv(cursor, 'ledger', os.path.join(data_dir, 'ledger_data.csv'))
            
            # 7. 변경사항 확정
            conn.commit()
            print("✅ DB 초기화 및 더미 데이터 생성 완료!")
            print("-------------------------------------------------")
            print("👉 테스트 계정 정보 (모든 계정 동일)")
            print("   비밀번호(Password): 1234")
            print("   PIN번호(Pin Code): 123456")

    except Exception as e:
        conn.rollback()
        print(f"❌ 오류 발생: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    init_database()