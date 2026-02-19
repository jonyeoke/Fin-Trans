import pymysql
import os
from dotenv import load_dotenv
from dbutils.pooled_db import PooledDB

load_dotenv()

# [수정] 전역 풀 생성 (싱글톤 패턴 효과)
POOL = PooledDB(
    creator=pymysql,
    mincached=2,
    maxcached=5,
    maxconnections=10,
    blocking=True,
    host=os.getenv('DB_HOST'),
    user=os.getenv('DB_USER'),
    password=os.getenv('DB_PASSWORD'),
    db=os.getenv('DB_NAME'),
    port=int(os.getenv('DB_PORT', 3306)),
    charset='utf8mb4'
)

def _get_connection():
    # [수정] 풀에서 연결을 빌려옴 (매우 빠름)
    return POOL.connection()
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