"""
DynamoDB 설정 파일

DynamoDB 접속 정보를 설정합니다.
여러 방법 중 하나를 선택하여 사용하세요.
"""

import os
from typing import Optional

# ============================================================================
# 방법 1: 환경 변수 사용 (권장)
# ============================================================================
# Windows PowerShell:
#   $env:AWS_ACCESS_KEY_ID="your_access_key"
#   $env:AWS_SECRET_ACCESS_KEY="your_secret_key"
#   $env:AWS_DEFAULT_REGION="ap-northeast-2"
#
# Linux/Mac:
#   export AWS_ACCESS_KEY_ID="your_access_key"
#   export AWS_SECRET_ACCESS_KEY="your_secret_key"
#   export AWS_DEFAULT_REGION="ap-northeast-2"

# ============================================================================
# 방법 2: AWS CLI 설정 (권장)
# ============================================================================
# 명령어:
#   aws configure
#
# 입력 항목:
#   AWS Access Key ID: your_access_key
#   AWS Secret Access Key: your_secret_key
#   Default region name: ap-northeast-2
#   Default output format: json
#
# 설정 파일 위치:
#   Windows: C:\Users\사용자명\.aws\credentials
#   Linux/Mac: ~/.aws/credentials

# ============================================================================
# 방법 3: 코드에서 직접 설정 (개발/테스트용)
# ============================================================================
# ⚠️ 보안 주의: 실제 운영 환경에서는 환경변수나 AWS CLI 사용 권장

# DynamoDB 설정
DYNAMODB_CONFIG = {
    # 환경변수가 있으면 환경변수를 우선 적용 (컨테이너/배포 환경에서 제어 가능하게)
    "use_dynamodb": os.getenv("USE_DYNAMODB", "true").lower() == "true",
    "table_name": os.getenv("DYNAMODB_TABLE_NAME", "quant_trading_users"),
    "region": os.getenv("AWS_DEFAULT_REGION", os.getenv("AWS_REGION", "us-east-1")),
    
    # 방법 3을 사용하는 경우에만 아래 값 설정
    # 환경변수가 있으면 환경변수가 우선 적용됨
    "aws_access_key_id": os.getenv("AWS_ACCESS_KEY_ID"),
    "aws_secret_access_key": os.getenv("AWS_SECRET_ACCESS_KEY"),
    "aws_session_token": os.getenv("AWS_SESSION_TOKEN"),  # 임시 자격 증명용 (선택)
}

# ============================================================================
# 사용 예제
# ============================================================================

def get_dynamodb_config() -> dict:
    """DynamoDB 설정 반환"""
    return DYNAMODB_CONFIG.copy()

def update_dynamodb_config(
    use_dynamodb: Optional[bool] = None,
    table_name: Optional[str] = None,
    region: Optional[str] = None,
    aws_access_key_id: Optional[str] = None,
    aws_secret_access_key: Optional[str] = None,
    aws_session_token: Optional[str] = None
):
    """DynamoDB 설정 업데이트"""
    if use_dynamodb is not None:
        DYNAMODB_CONFIG["use_dynamodb"] = use_dynamodb
    if table_name is not None:
        DYNAMODB_CONFIG["table_name"] = table_name
    if region is not None:
        DYNAMODB_CONFIG["region"] = region
    if aws_access_key_id is not None:
        DYNAMODB_CONFIG["aws_access_key_id"] = aws_access_key_id
    if aws_secret_access_key is not None:
        DYNAMODB_CONFIG["aws_secret_access_key"] = aws_secret_access_key
    if aws_session_token is not None:
        DYNAMODB_CONFIG["aws_session_token"] = aws_session_token
