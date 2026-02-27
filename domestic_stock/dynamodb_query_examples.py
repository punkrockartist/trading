"""
DynamoDB 테이블 값 조회 예제

여러 방법으로 DynamoDB 테이블의 데이터를 조회하는 방법을 보여줍니다.
"""

import boto3
from botocore.exceptions import ClientError
from dynamodb_config import get_dynamodb_config
from typing import List, Dict, Optional
import json

def get_table_item(table_name: str, key: Dict) -> Optional[Dict]:
    """
    특정 항목 조회 (get_item)
    
    Args:
        table_name: 테이블 이름
        key: 파티션 키 (필수) 및 정렬 키 (있는 경우)
    
    Returns:
        항목이 있으면 Dict, 없으면 None
    """
    config = get_dynamodb_config()
    
    dynamodb = boto3.resource(
        'dynamodb',
        region_name=config.get('region'),
        aws_access_key_id=config.get('aws_access_key_id'),
        aws_secret_access_key=config.get('aws_secret_access_key')
    )
    
    table = dynamodb.Table(table_name)
    
    try:
        response = table.get_item(Key=key)
        if 'Item' in response:
            return response['Item']
        else:
            return None
    except ClientError as e:
        print(f"오류: {e}")
        return None

def scan_table(table_name: str, filter_expression=None) -> List[Dict]:
    """
    전체 테이블 스캔 (scan)
    
    Args:
        table_name: 테이블 이름
        filter_expression: 필터 표현식 (선택)
    
    Returns:
        항목 리스트
    """
    config = get_dynamodb_config()
    
    dynamodb = boto3.resource(
        'dynamodb',
        region_name=config.get('region'),
        aws_access_key_id=config.get('aws_access_key_id'),
        aws_secret_access_key=config.get('aws_secret_access_key')
    )
    
    table = dynamodb.Table(table_name)
    items = []
    
    try:
        if filter_expression:
            response = table.scan(FilterExpression=filter_expression)
        else:
            response = table.scan()
        
        items.extend(response['Items'])
        
        # 페이지네이션 처리 (LastEvaluatedKey가 있으면 계속 조회)
        while 'LastEvaluatedKey' in response:
            if filter_expression:
                response = table.scan(
                    FilterExpression=filter_expression,
                    ExclusiveStartKey=response['LastEvaluatedKey']
                )
            else:
                response = table.scan(
                    ExclusiveStartKey=response['LastEvaluatedKey']
                )
            items.extend(response['Items'])
        
        return items
    except ClientError as e:
        print(f"오류: {e}")
        return []

def query_table(
    table_name: str,
    key_condition_expression,
    filter_expression=None,
    index_name: Optional[str] = None
) -> List[Dict]:
    """
    쿼리 실행 (query)
    
    Args:
        table_name: 테이블 이름
        key_condition_expression: 키 조건 표현식
        filter_expression: 필터 표현식 (선택)
        index_name: 인덱스 이름 (GSI 사용 시)
    
    Returns:
        항목 리스트
    """
    from boto3.dynamodb.conditions import Key
    
    config = get_dynamodb_config()
    
    dynamodb = boto3.resource(
        'dynamodb',
        region_name=config.get('region'),
        aws_access_key_id=config.get('aws_access_key_id'),
        aws_secret_access_key=config.get('aws_secret_access_key')
    )
    
    table = dynamodb.Table(table_name)
    items = []
    
    try:
        kwargs = {
            'KeyConditionExpression': key_condition_expression
        }
        
        if filter_expression:
            kwargs['FilterExpression'] = filter_expression
        
        if index_name:
            kwargs['IndexName'] = index_name
        
        response = table.query(**kwargs)
        items.extend(response['Items'])
        
        # 페이지네이션 처리
        while 'LastEvaluatedKey' in response:
            kwargs['ExclusiveStartKey'] = response['LastEvaluatedKey']
            response = table.query(**kwargs)
            items.extend(response['Items'])
        
        return items
    except ClientError as e:
        print(f"오류: {e}")
        return []

def list_all_users() -> List[Dict]:
    """quant_trading_users 테이블의 모든 사용자 조회"""
    config = get_dynamodb_config()
    table_name = config.get('table_name', 'quant_trading_users')
    return scan_table(table_name)

def get_user(username: str) -> Optional[Dict]:
    """특정 사용자 조회"""
    config = get_dynamodb_config()
    table_name = config.get('table_name', 'quant_trading_users')
    return get_table_item(table_name, {'username': username})

def count_items(table_name: str) -> int:
    """테이블의 항목 개수 조회"""
    config = get_dynamodb_config()
    
    dynamodb = boto3.resource(
        'dynamodb',
        region_name=config.get('region'),
        aws_access_key_id=config.get('aws_access_key_id'),
        aws_secret_access_key=config.get('aws_secret_access_key')
    )
    
    table = dynamodb.Table(table_name)
    
    try:
        response = table.scan(Select='COUNT')
        count = response['Count']
        
        # 페이지네이션 처리
        while 'LastEvaluatedKey' in response:
            response = table.scan(
                Select='COUNT',
                ExclusiveStartKey=response['LastEvaluatedKey']
            )
            count += response['Count']
        
        return count
    except ClientError as e:
        print(f"오류: {e}")
        return 0

# ============================================================================
# 사용 예제
# ============================================================================

if __name__ == "__main__":
    print("=" * 80)
    print("DynamoDB 테이블 값 조회 예제")
    print("=" * 80)
    
    config = get_dynamodb_config()
    table_name = config.get('table_name', 'quant_trading_users')
    
    # 1. 특정 사용자 조회
    print("\n[1] 특정 사용자 조회 (get_item)")
    print("-" * 80)
    user = get_user('admin')
    if user:
        print(f"사용자명: {user.get('username')}")
        print(f"이메일: {user.get('email', 'N/A')}")
        print(f"생성일: {user.get('created_at', 'N/A')}")
        print(f"활성화: {user.get('is_active', False)}")
    else:
        print("사용자를 찾을 수 없습니다.")
    
    # 2. 모든 사용자 조회
    print("\n[2] 모든 사용자 조회 (scan)")
    print("-" * 80)
    all_users = list_all_users()
    print(f"총 사용자 수: {len(all_users)}")
    for user in all_users:
        print(f"  - {user.get('username')}: {user.get('email', 'N/A')}")
    
    # 3. 항목 개수 조회
    print("\n[3] 테이블 항목 개수 조회")
    print("-" * 80)
    count = count_items(table_name)
    print(f"총 항목 수: {count}")
    
    # 4. 필터링 조회 예제
    print("\n[4] 필터링 조회 (활성화된 사용자만)")
    print("-" * 80)
    from boto3.dynamodb.conditions import Attr
    active_users = scan_table(
        table_name,
        filter_expression=Attr('is_active').eq(True)
    )
    print(f"활성화된 사용자 수: {len(active_users)}")
    for user in active_users:
        print(f"  - {user.get('username')}")
    
    # 5. JSON 형식으로 출력
    print("\n[5] JSON 형식으로 출력")
    print("-" * 80)
    if all_users:
        print(json.dumps(all_users, indent=2, ensure_ascii=False, default=str))
    
    print("\n" + "=" * 80)
