"""
DynamoDB 쿼리 예제

DynamoDB는 SQL이 아닌 NoSQL API를 사용합니다.
주요 작업: GetItem, PutItem, UpdateItem, DeleteItem, Query, Scan, CreateTable
"""

import boto3
from botocore.exceptions import ClientError
from typing import Dict, Optional, List
import json

# DynamoDB 리소스 생성
dynamodb = boto3.resource('dynamodb', region_name='us-east-1')
table = dynamodb.Table('quant_trading_users')

# ============================================================================
# 1. 테이블 생성 (CreateTable)
# ============================================================================

def create_table_example():
    """테이블 생성 예제"""
    try:
        table = dynamodb.create_table(
            TableName='quant_trading_users',
            KeySchema=[
                {
                    'AttributeName': 'username',
                    'KeyType': 'HASH'  # 파티션 키
                }
            ],
            AttributeDefinitions=[
                {
                    'AttributeName': 'username',
                    'AttributeType': 'S'  # String
                }
            ],
            BillingMode='PAY_PER_REQUEST'  # 온디맨드 모드
        )
        
        # 테이블 생성 대기
        table.wait_until_exists()
        print(f"테이블 생성 완료: {table.table_name}")
        return table
    except ClientError as e:
        if e.response['Error']['Code'] == 'ResourceInUseException':
            print("테이블이 이미 존재합니다.")
        else:
            print(f"오류: {e}")

# ============================================================================
# 2. INSERT (PutItem) - 데이터 삽입
# ============================================================================

def insert_user(username: str, password_hash: str, email: str = ""):
    """사용자 삽입 (INSERT 대신 PutItem 사용)"""
    try:
        response = table.put_item(
            Item={
                'username': username,
                'password_hash': password_hash,
                'email': email,
                'created_at': '2024-02-24T10:00:00',
                'is_active': True
            },
            # 중복 방지 (조건부 삽입)
            ConditionExpression='attribute_not_exists(username)'
        )
        print(f"사용자 삽입 완료: {username}")
        return True
    except ClientError as e:
        if e.response['Error']['Code'] == 'ConditionalCheckFailedException':
            print(f"사용자 {username}가 이미 존재합니다.")
        else:
            print(f"오류: {e}")
        return False

# 사용 예제
# insert_user('testuser', 'hashed_password', 'test@example.com')

# ============================================================================
# 3. SELECT (GetItem) - 단일 항목 조회
# ============================================================================

def get_user(username: str) -> Optional[Dict]:
    """사용자 조회 (SELECT 대신 GetItem 사용)"""
    try:
        response = table.get_item(
            Key={
                'username': username
            }
        )
        
        if 'Item' in response:
            return response['Item']
        else:
            print(f"사용자 {username}를 찾을 수 없습니다.")
            return None
    except ClientError as e:
        print(f"오류: {e}")
        return None

# 사용 예제
# user = get_user('testuser')
# print(user)

# ============================================================================
# 4. UPDATE (UpdateItem) - 데이터 업데이트
# ============================================================================

def update_user_email(username: str, new_email: str):
    """사용자 이메일 업데이트 (UPDATE 대신 UpdateItem 사용)"""
    try:
        response = table.update_item(
            Key={
                'username': username
            },
            UpdateExpression='SET email = :email',
            ExpressionAttributeValues={
                ':email': new_email
            },
            ReturnValues='UPDATED_NEW'  # 업데이트된 값 반환
        )
        print(f"사용자 {username}의 이메일이 업데이트되었습니다.")
        return response['Attributes']
    except ClientError as e:
        print(f"오류: {e}")
        return None

# 사용 예제
# update_user_email('testuser', 'newemail@example.com')

# 여러 필드 업데이트
def update_user_multiple(username: str, email: str = None, is_active: bool = None):
    """여러 필드 업데이트"""
    update_expression_parts = []
    expression_attribute_values = {}
    
    if email:
        update_expression_parts.append('email = :email')
        expression_attribute_values[':email'] = email
    
    if is_active is not None:
        update_expression_parts.append('is_active = :is_active')
        expression_attribute_values[':is_active'] = is_active
    
    if not update_expression_parts:
        return None
    
    try:
        response = table.update_item(
            Key={'username': username},
            UpdateExpression='SET ' + ', '.join(update_expression_parts),
            ExpressionAttributeValues=expression_attribute_values,
            ReturnValues='UPDATED_NEW'
        )
        return response['Attributes']
    except ClientError as e:
        print(f"오류: {e}")
        return None

# ============================================================================
# 5. DELETE (DeleteItem) - 데이터 삭제
# ============================================================================

def delete_user(username: str):
    """사용자 삭제 (DELETE 대신 DeleteItem 사용)"""
    try:
        response = table.delete_item(
            Key={
                'username': username
            },
            # 조건부 삭제 (존재하는 경우에만)
            ConditionExpression='attribute_exists(username)'
        )
        print(f"사용자 {username}가 삭제되었습니다.")
        return True
    except ClientError as e:
        if e.response['Error']['Code'] == 'ConditionalCheckFailedException':
            print(f"사용자 {username}가 존재하지 않습니다.")
        else:
            print(f"오류: {e}")
        return False

# 사용 예제
# delete_user('testuser')

# ============================================================================
# 6. QUERY - 파티션 키로 조회 (인덱스 사용 가능)
# ============================================================================

def query_users_by_username_prefix(prefix: str) -> List[Dict]:
    """사용자명으로 시작하는 사용자 조회 (Query 사용)"""
    # 주의: Query는 파티션 키와 정렬 키가 필요합니다
    # 단순 파티션 키만 있는 경우는 GetItem을 사용하거나
    # Scan을 사용해야 합니다 (비효율적)
    
    # 이 예제는 Scan을 사용 (실제로는 Query가 더 효율적이지만 정렬 키 필요)
    return scan_users_by_prefix(prefix)

# ============================================================================
# 7. SCAN - 전체 테이블 스캔 (비효율적, 작은 데이터에만 사용)
# ============================================================================

def scan_all_users() -> List[Dict]:
    """모든 사용자 조회 (SCAN - 비효율적)"""
    try:
        response = table.scan()
        return response.get('Items', [])
    except ClientError as e:
        print(f"오류: {e}")
        return []

def scan_users_by_prefix(prefix: str) -> List[Dict]:
    """사용자명이 특정 접두사로 시작하는 사용자 조회"""
    try:
        response = table.scan(
            FilterExpression='begins_with(username, :prefix)',
            ExpressionAttributeValues={
                ':prefix': prefix
            }
        )
        return response.get('Items', [])
    except ClientError as e:
        print(f"오류: {e}")
        return []

def scan_active_users() -> List[Dict]:
    """활성 사용자만 조회"""
    try:
        response = table.scan(
            FilterExpression='is_active = :active',
            ExpressionAttributeValues={
                ':active': True
            }
        )
        return response.get('Items', [])
    except ClientError as e:
        print(f"오류: {e}")
        return []

# ============================================================================
# 8. 배치 작업 (BatchGetItem, BatchWriteItem)
# ============================================================================

def batch_get_users(usernames: List[str]) -> List[Dict]:
    """여러 사용자 한 번에 조회"""
    try:
        response = dynamodb.batch_get_item(
            RequestItems={
                'quant_trading_users': {
                    'Keys': [{'username': username} for username in usernames]
                }
            }
        )
        return response.get('Responses', {}).get('quant_trading_users', [])
    except ClientError as e:
        print(f"오류: {e}")
        return []

def batch_write_users(users: List[Dict]):
    """여러 사용자 한 번에 삽입/업데이트"""
    try:
        with table.batch_writer() as batch:
            for user in users:
                batch.put_item(Item=user)
        print(f"{len(users)}명의 사용자가 배치로 저장되었습니다.")
    except ClientError as e:
        print(f"오류: {e}")

# ============================================================================
# 9. 조건부 작업 (Conditional Expressions)
# ============================================================================

def update_user_if_exists(username: str, new_email: str):
    """사용자가 존재하는 경우에만 업데이트"""
    try:
        response = table.update_item(
            Key={'username': username},
            UpdateExpression='SET email = :email',
            ExpressionAttributeValues={':email': new_email},
            ConditionExpression='attribute_exists(username)',  # 조건
            ReturnValues='UPDATED_NEW'
        )
        return response['Attributes']
    except ClientError as e:
        if e.response['Error']['Code'] == 'ConditionalCheckFailedException':
            print(f"사용자 {username}가 존재하지 않습니다.")
        else:
            print(f"오류: {e}")
        return None

# ============================================================================
# 10. 테이블 정보 조회
# ============================================================================

def describe_table():
    """테이블 정보 조회"""
    try:
        response = table.meta.client.describe_table(TableName='quant_trading_users')
        table_info = response['Table']
        print(f"테이블 이름: {table_info['TableName']}")
        print(f"상태: {table_info['TableStatus']}")
        print(f"항목 수: {table_info.get('ItemCount', 'N/A')}")
        print(f"용량 모드: {table_info['BillingModeSummary']['BillingMode']}")
        return table_info
    except ClientError as e:
        print(f"오류: {e}")
        return None

# ============================================================================
# SQL vs DynamoDB 비교
# ============================================================================

"""
SQL                          DynamoDB
─────────────────────────────────────────────────────────
CREATE TABLE                create_table()
INSERT INTO ...             put_item()
SELECT * FROM ...           get_item() / scan() / query()
UPDATE ... SET ...          update_item()
DELETE FROM ...             delete_item()
WHERE ...                   FilterExpression / ConditionExpression
JOIN                        지원 안 함 (별도 쿼리 필요)
ORDER BY                    정렬 키 사용 또는 클라이언트에서 정렬
LIMIT                       Limit 파라미터
"""

# ============================================================================
# 사용 예제
# ============================================================================

if __name__ == "__main__":
    # 테이블 정보 조회
    print("=== 테이블 정보 ===")
    describe_table()
    
    # 사용자 삽입
    print("\n=== 사용자 삽입 ===")
    insert_user('testuser1', 'hash1', 'test1@example.com')
    insert_user('testuser2', 'hash2', 'test2@example.com')
    
    # 사용자 조회
    print("\n=== 사용자 조회 ===")
    user = get_user('testuser1')
    print(json.dumps(user, indent=2, ensure_ascii=False))
    
    # 사용자 업데이트
    print("\n=== 사용자 업데이트 ===")
    update_user_email('testuser1', 'newemail@example.com')
    
    # 모든 사용자 조회
    print("\n=== 모든 사용자 조회 ===")
    all_users = scan_all_users()
    for user in all_users:
        print(f"{user['username']}: {user.get('email', 'N/A')}")
    
    # 활성 사용자만 조회
    print("\n=== 활성 사용자만 조회 ===")
    active_users = scan_active_users()
    for user in active_users:
        print(f"{user['username']}: {user.get('is_active', False)}")
    
    # 사용자 삭제
    print("\n=== 사용자 삭제 ===")
    delete_user('testuser1')
    delete_user('testuser2')
