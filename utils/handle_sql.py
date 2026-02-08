import pymysql
import os
from dotenv import load_dotenv

load_dotenv()

# DB 연결 정보를 가져오는 내부 함수 (DRY 원칙)
def _get_connection():
    return pymysql.connect(
        host=os.getenv('DB_HOST'),
        user=os.getenv('DB_USER'),
        password=os.getenv('DB_PASSWORD'),
        db=os.getenv('DB_NAME'),
        port=int(os.getenv('DB_PORT', 3306)),
        charset='utf8mb4'
    )

def get_data(query, args=None):
    """SELECT 전용: 결과를 반환함"""
    conn = _get_connection()
    try:
        with conn.cursor(pymysql.cursors.DictCursor) as cursor:
            cursor.execute(query, args)
            return cursor.fetchall()
    finally:
        conn.close()

def execute_query(query, args=None):
    """INSERT, UPDATE, DELETE 전용 (단건): 커밋을 수행함"""
    conn = _get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(query, args)
            conn.commit()
            return cursor.rowcount # 영향받은 행의 개수 반환
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()

def execute_many(query, args_list):
    """대량 INSERT 전용: 리스트 데이터를 한 번에 넣음"""
    conn = _get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.executemany(query, args_list)
            conn.commit()
            return cursor.rowcount
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()