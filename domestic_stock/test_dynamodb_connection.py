"""
DynamoDB 연결 및 인증 테스트 스크립트

401 에러 원인을 찾기 위해 DynamoDB 연결을 테스트합니다.
"""

import sys
import traceback
from dynamodb_config import get_dynamodb_config

def test_dynamodb_connection():
    """DynamoDB 연결 테스트"""
    print("=" * 80)
    print("DynamoDB 연결 테스트")
    print("=" * 80)
    
    try:
        config = get_dynamodb_config()
        print(f"[OK] 설정 로드 성공")
        print(f"   use_dynamodb: {config.get('use_dynamodb')}")
        print(f"   table_name: {config.get('table_name')}")
        print(f"   region: {config.get('region')}")
        print(f"   aws_access_key_id: {config.get('aws_access_key_id', '')[:10]}...")
        print(f"   aws_secret_access_key: {'설정됨' if config.get('aws_secret_access_key') else '없음'}")
        print()
    except Exception as e:
        print(f"[ERROR] 설정 로드 실패: {e}")
        traceback.print_exc()
        return False
    
    # boto3 테스트
    try:
        import boto3
        from botocore.exceptions import ClientError, NoCredentialsError
        print("[OK] boto3 모듈 로드 성공")
    except ImportError:
        print("[ERROR] boto3 모듈이 설치되지 않았습니다.")
        print("   설치: py -3.12 -m pip install boto3")
        return False
    
    # DynamoDB 연결 테스트
    try:
        print("\n" + "=" * 80)
        print("DynamoDB 리소스 생성 중...")
        print("=" * 80)
        
        if config.get('aws_access_key_id') and config.get('aws_secret_access_key'):
            session = boto3.Session(
                aws_access_key_id=config.get('aws_access_key_id'),
                aws_secret_access_key=config.get('aws_secret_access_key'),
                aws_session_token=config.get('aws_session_token'),
                region_name=config.get('region')
            )
            dynamodb = session.resource('dynamodb')
            print(f"[OK] DynamoDB 리소스 생성 성공 (명시적 자격 증명 사용)")
        else:
            dynamodb = boto3.resource('dynamodb', region_name=config.get('region'))
            print(f"[OK] DynamoDB 리소스 생성 성공 (기본 자격 증명 체인 사용)")
        
        table_name = config.get('table_name')
        table = dynamodb.Table(table_name)
        
        print(f"\n테이블 '{table_name}' 접근 시도 중...")
        
        # 테이블 존재 확인
        try:
            table.load()
            print(f"[OK] 테이블 '{table_name}' 존재 확인")
            print(f"   ARN: {table.table_arn}")
            print(f"   상태: {table.table_status}")
            print(f"   리전: {table.table_arn.split(':')[3]}")
        except ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code == 'ResourceNotFoundException':
                print(f"[ERROR] 테이블 '{table_name}'이 존재하지 않습니다.")
                print(f"   AWS 콘솔에서 테이블을 생성하거나")
                print(f"   auth_manager.py가 자동으로 생성하도록 설정되어 있습니다.")
            elif error_code == 'AccessDeniedException':
                print(f"[ERROR] 접근 권한이 없습니다.")
                print(f"   IAM 사용자에게 DynamoDB 권한이 필요합니다.")
                print(f"   필요한 권한:")
                print(f"   - dynamodb:DescribeTable")
                print(f"   - dynamodb:GetItem")
                print(f"   - dynamodb:PutItem")
                print(f"   - dynamodb:UpdateItem")
                print(f"   - dynamodb:DeleteItem")
                print(f"   - dynamodb:CreateTable (선택)")
            else:
                print(f"[ERROR] 오류: {error_code}")
                print(f"   메시지: {e.response['Error']['Message']}")
            return False
        
        # 테스트 데이터 읽기/쓰기
        print("\n" + "=" * 80)
        print("테스트 데이터 읽기/쓰기 테스트")
        print("=" * 80)
        
        test_username = "__test_user__"
        
        # 테스트 사용자 읽기
        try:
            response = table.get_item(Key={'username': test_username})
            if 'Item' in response:
                print(f"[OK] 테스트 사용자 읽기 성공")
            else:
                print(f"[INFO] 테스트 사용자 없음 (정상)")
        except ClientError as e:
            print(f"[ERROR] 테스트 사용자 읽기 실패: {e.response['Error']['Code']}")
            return False
        
        # 테스트 사용자 쓰기
        try:
            import hashlib
            from datetime import datetime
            table.put_item(
                Item={
                    'username': test_username,
                    'password_hash': hashlib.sha256('test123'.encode()).hexdigest(),
                    'email': 'test@example.com',
                    'created_at': datetime.now().isoformat(),
                    'is_active': True
                },
                ConditionExpression='attribute_not_exists(username)'
            )
            print(f"[OK] 테스트 사용자 쓰기 성공")
            
            # 테스트 사용자 삭제
            table.delete_item(Key={'username': test_username})
            print(f"[OK] 테스트 사용자 삭제 성공")
        except ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code == 'ConditionalCheckFailedException':
                print(f"[INFO] 테스트 사용자 이미 존재 (정상)")
                # 삭제 후 재시도
                table.delete_item(Key={'username': test_username})
                print(f"[OK] 테스트 사용자 삭제 성공")
            elif error_code == 'AccessDeniedException':
                print(f"[ERROR] 쓰기 권한이 없습니다.")
                print(f"   IAM 사용자에게 dynamodb:PutItem 권한이 필요합니다.")
                return False
            else:
                print(f"[ERROR] 쓰기 실패: {error_code}")
                print(f"   메시지: {e.response['Error']['Message']}")
                return False
        
        print("\n" + "=" * 80)
        print("[OK] 모든 테스트 통과!")
        print("=" * 80)
        return True
        
    except NoCredentialsError:
        print("[ERROR] AWS 자격 증명을 찾을 수 없습니다.")
        print("   dynamodb_config.py에 자격 증명을 설정하세요.")
        return False
    except Exception as e:
        print(f"[ERROR] 예상치 못한 오류: {e}")
        traceback.print_exc()
        return False

def test_auth_manager():
    """AuthManager 초기화 테스트"""
    print("\n" + "=" * 80)
    print("AuthManager 초기화 테스트")
    print("=" * 80)
    
    try:
        from auth_manager import auth_manager
        print("[OK] AuthManager 초기화 성공")
        
        # 사용자 저장소 타입 확인
        store_type = type(auth_manager.user_store).__name__
        print(f"   사용자 저장소: {store_type}")
        
        if store_type == 'DynamoDBUserStore':
            print("   [OK] DynamoDB 사용 중")
        else:
            print("   [WARN] 인메모리 저장소 사용 중 (DynamoDB 미사용)")
        
        return True
    except Exception as e:
        print(f"[ERROR] AuthManager 초기화 실패: {e}")
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("\n")
    success1 = test_dynamodb_connection()
    success2 = test_auth_manager()
    
    print("\n" + "=" * 80)
    if success1 and success2:
        print("[OK] 모든 테스트 통과! DynamoDB 연결이 정상입니다.")
    else:
        print("[ERROR] 일부 테스트 실패. 위의 오류 메시지를 확인하세요.")
    print("=" * 80)
