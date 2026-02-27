"""
DynamoDB 테이블 리전 확인 스크립트

현재 설정된 리전과 실제 테이블이 있는 리전을 확인합니다.
"""

import boto3
from botocore.exceptions import ClientError
from dynamodb_config import get_dynamodb_config

def find_table_region():
    """테이블이 있는 리전 찾기"""
    config = get_dynamodb_config()
    table_name = config['table_name']
    access_key = config.get('aws_access_key_id')
    secret_key = config.get('aws_secret_access_key')
    
    print("=" * 80)
    print("DynamoDB 테이블 리전 확인")
    print("=" * 80)
    print(f"테이블 이름: {table_name}")
    print(f"설정된 리전: {config['region']}")
    print(f"설정된 Access Key: {access_key[:10]}..." if access_key else "없음")
    print("=" * 80)
    print()
    
    # 주요 리전 목록
    regions = [
        ('us-east-1', '버지니아 북부'),
        ('us-east-2', '오하이오'),
        ('us-west-1', '캘리포니아 북부'),
        ('us-west-2', '오레곤'),
        ('ap-northeast-2', '서울'),
        ('ap-northeast-1', '도쿄'),
        ('ap-southeast-1', '싱가포르'),
        ('eu-west-1', '아일랜드'),
        ('eu-central-1', '프랑크푸르트')
    ]
    
    print("리전별 테이블 검색 중...\n")
    
    found_regions = []
    
    for region_code, region_name in regions:
        try:
            # DynamoDB 리소스 생성
            if access_key and secret_key:
                dynamodb = boto3.resource(
                    'dynamodb',
                    region_name=region_code,
                    aws_access_key_id=access_key,
                    aws_secret_access_key=secret_key
                )
            else:
                dynamodb = boto3.resource('dynamodb', region_name=region_code)
            
            table = dynamodb.Table(table_name)
            table.load()  # 테이블 메타데이터 로드
            
            # 테이블 발견!
            found_regions.append({
                'region': region_code,
                'name': region_name,
                'arn': table.table_arn,
                'status': table.table_status
            })
            
            print(f"✅ {region_code} ({region_name}): 테이블 발견!")
            print(f"   ARN: {table.table_arn}")
            print(f"   상태: {table.table_status}")
            print()
            
        except ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code == 'ResourceNotFoundException':
                # 테이블이 없음 (정상)
                pass
            elif error_code == 'AccessDeniedException':
                print(f"⚠️  {region_code} ({region_name}): 접근 권한 없음")
            else:
                print(f"❌ {region_code} ({region_name}): {error_code}")
        except Exception as e:
            # 기타 오류
            pass
    
    print("=" * 80)
    
    if found_regions:
        print(f"\n✅ 총 {len(found_regions)}개 리전에서 테이블 발견:")
        for info in found_regions:
            print(f"   - {info['region']} ({info['name']})")
            print(f"     ARN: {info['arn']}")
            print(f"     상태: {info['status']}")
        
        # 설정된 리전과 비교
        if config['region'] in [r['region'] for r in found_regions]:
            print(f"\n✅ 설정된 리전({config['region']})에 테이블이 있습니다!")
        else:
            print(f"\n⚠️  경고: 설정된 리전({config['region']})에 테이블이 없습니다!")
            print(f"   실제 테이블 위치: {found_regions[0]['region']}")
            print(f"   dynamodb_config.py의 'region'을 수정하세요.")
    else:
        print("\n❌ 테이블을 찾을 수 없습니다.")
        print("   다음을 확인하세요:")
        print("   1. 테이블이 생성되었는지")
        print("   2. IAM 사용자 권한")
        print("   3. 리전 설정")
    
    print("=" * 80)
    
    return found_regions

if __name__ == "__main__":
    find_table_region()
