"""
인증 관리 모듈

사용자 인증 및 세션 관리를 담당합니다.
DynamoDB 또는 SQLite를 사용할 수 있습니다.
"""

import hashlib
import secrets
import jwt
from datetime import datetime, timedelta
from typing import Optional, Dict
import logging
import os

logger = logging.getLogger(__name__)

# JWT 설정
SECRET_KEY = secrets.token_urlsafe(32)  # 실제 운영에서는 환경변수로 관리
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  # 24시간


def _load_dotenv_file(dotenv_path: str) -> bool:
    """Load KEY=VALUE pairs into os.environ (does not override existing)."""
    try:
        with open(dotenv_path, "r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("export "):
                    line = line[len("export ") :].strip()
                if "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                if k and k not in os.environ:
                    os.environ[k] = v
        return True
    except FileNotFoundError:
        return False
    except Exception as e:
        logger.warning(f".env 로드 실패: {e}")
        return False


def _maybe_load_dotenv():
    """Best-effort: load .env from common config locations."""
    candidates = []
    explicit = os.getenv("ENV_FILE") or os.getenv("DOTENV_PATH")
    if explicit:
        candidates.append(explicit)
    config_root = os.getenv("KIS_CONFIG_ROOT", "/root/kis-api/config")
    candidates.append(os.path.join(config_root, ".env"))
    candidates.append("/app/config/.env")

    for p in candidates:
        if _load_dotenv_file(p):
            logger.info(f".env 로드: {p}")
            break


_maybe_load_dotenv()

# ============================================================================
# 간단한 인메모리 사용자 저장소 (개발용)
# ============================================================================

class SimpleUserStore:
    """간단한 인메모리 사용자 저장소 (개발/테스트용)"""
    
    def __init__(self):
        # 기본 사용자 (username: admin, password: admin123)
        self.users = {
            "admin": {
                "username": "admin",
                "password_hash": self._hash_password("admin123"),
                "email": "admin@example.com",
                "created_at": datetime.now().isoformat(),
                "is_active": True
            }
        }
    
    def _hash_password(self, password: str) -> str:
        """비밀번호 해시"""
        return hashlib.sha256(password.encode()).hexdigest()
    
    def create_user(self, username: str, password: str, email: str = "") -> bool:
        """사용자 생성"""
        if username in self.users:
            return False
        self.users[username] = {
            "username": username,
            "password_hash": self._hash_password(password),
            "email": email,
            "created_at": datetime.now().isoformat(),
            "is_active": True
        }
        return True
    
    def verify_user(self, username: str, password: str) -> bool:
        """사용자 인증"""
        if username not in self.users:
            return False
        user = self.users[username]
        if not user["is_active"]:
            return False
        password_hash = self._hash_password(password)
        return user["password_hash"] == password_hash
    
    def get_user(self, username: str) -> Optional[Dict]:
        """사용자 정보 조회"""
        return self.users.get(username)

# ============================================================================
# DynamoDB 사용자 저장소 (프로덕션용)
# ============================================================================

try:
    import boto3
    from botocore.exceptions import ClientError, NoCredentialsError
    
    class DynamoDBUserStore:
        """DynamoDB 사용자 저장소"""
        
        def __init__(
            self, 
            table_name: str = "quant_trading_users", 
            region: str = "ap-northeast-2",
            aws_access_key_id: Optional[str] = None,
            aws_secret_access_key: Optional[str] = None,
            aws_session_token: Optional[str] = None
        ):
            """
            Args:
                table_name: DynamoDB 테이블 이름
                region: AWS 리전 (기본값: ap-northeast-2)
                aws_access_key_id: AWS Access Key ID (환경변수 또는 파라미터)
                aws_secret_access_key: AWS Secret Access Key (환경변수 또는 파라미터)
                aws_session_token: AWS Session Token (임시 자격 증명용, 선택)
            """
            # 자격 증명 설정 (우선순위: 파라미터 > 환경변수 > 기본 자격 증명 체인)
            self.aws_access_key_id = aws_access_key_id or os.getenv('AWS_ACCESS_KEY_ID')
            self.aws_secret_access_key = aws_secret_access_key or os.getenv('AWS_SECRET_ACCESS_KEY')
            self.aws_session_token = aws_session_token or os.getenv('AWS_SESSION_TOKEN')
            self.region = region or os.getenv('AWS_DEFAULT_REGION', 'ap-northeast-2')
            
            # boto3 클라이언트 생성
            if self.aws_access_key_id and self.aws_secret_access_key:
                # 명시적 자격 증명 사용
                session = boto3.Session(
                    aws_access_key_id=self.aws_access_key_id,
                    aws_secret_access_key=self.aws_secret_access_key,
                    aws_session_token=self.aws_session_token,
                    region_name=self.region
                )
                self.dynamodb = session.resource('dynamodb')
                logger.info(f"DynamoDB 연결: 명시적 자격 증명 사용 (리전: {self.region})")
            else:
                # 기본 자격 증명 체인 사용 (AWS CLI 설정, IAM Role 등)
                self.dynamodb = boto3.resource('dynamodb', region_name=self.region)
                logger.info(f"DynamoDB 연결: 기본 자격 증명 체인 사용 (리전: {self.region})")
            
            self.table = self.dynamodb.Table(table_name)
            self._ensure_table_exists()
            self._ensure_default_admin()
        
        def _ensure_table_exists(self):
            """테이블이 없으면 생성"""
            try:
                self.table.load()
            except ClientError as e:
                if e.response['Error']['Code'] == 'ResourceNotFoundException':
                    # 테이블 생성
                    try:
                        table = self.dynamodb.create_table(
                            TableName=self.table.name,
                            KeySchema=[
                                {'AttributeName': 'username', 'KeyType': 'HASH'}
                            ],
                            AttributeDefinitions=[
                                {'AttributeName': 'username', 'AttributeType': 'S'}
                            ],
                            BillingMode='PAY_PER_REQUEST'
                        )
                        table.wait_until_exists()
                        logger.info(f"DynamoDB 테이블 생성됨: {self.table.name}")
                    except ClientError as create_error:
                        if create_error.response['Error']['Code'] != 'ResourceInUseException':
                            logger.error(f"테이블 생성 실패: {create_error}")
        
        def _ensure_default_admin(self):
            """기본 admin 계정이 없으면 생성"""
            try:
                response = self.table.get_item(Key={'username': 'admin'})
                if 'Item' not in response:
                    # admin 계정 생성
                    self.table.put_item(
                        Item={
                            'username': 'admin',
                            'password_hash': self._hash_password('admin123'),
                            'email': 'admin@example.com',
                            'created_at': datetime.now().isoformat(),
                            'is_active': True
                        },
                        ConditionExpression='attribute_not_exists(username)'
                    )
                    logger.info("기본 admin 계정 생성됨 (username: admin, password: admin123)")
            except ClientError as e:
                logger.warning(f"기본 admin 계정 생성 실패 (무시): {e}")
        
        def _hash_password(self, password: str) -> str:
            """비밀번호 해시"""
            return hashlib.sha256(password.encode()).hexdigest()
        
        def create_user(self, username: str, password: str, email: str = "") -> bool:
            """사용자 생성"""
            try:
                self.table.put_item(
                    Item={
                        'username': username,
                        'password_hash': self._hash_password(password),
                        'email': email,
                        'created_at': datetime.now().isoformat(),
                        'is_active': True
                    },
                    ConditionExpression='attribute_not_exists(username)'
                )
                return True
            except ClientError as e:
                if e.response['Error']['Code'] == 'ConditionalCheckFailedException':
                    return False
                logger.error(f"DynamoDB 오류: {e}")
                return False
        
        def verify_user(self, username: str, password: str) -> bool:
            """사용자 인증"""
            try:
                response = self.table.get_item(Key={'username': username})
                if 'Item' not in response:
                    return False
                user = response['Item']
                if not user.get('is_active', True):
                    return False
                password_hash = self._hash_password(password)
                return user['password_hash'] == password_hash
            except ClientError as e:
                logger.error(f"DynamoDB 오류: {e}")
                return False
        
        def get_user(self, username: str) -> Optional[Dict]:
            """사용자 정보 조회"""
            try:
                response = self.table.get_item(Key={'username': username})
                if 'Item' not in response:
                    return None
                return response['Item']
            except ClientError as e:
                logger.error(f"DynamoDB 오류: {e}")
                return None
    
    DYNAMODB_AVAILABLE = True
except ImportError:
    DYNAMODB_AVAILABLE = False
    logger.warning("boto3가 설치되지 않았습니다. DynamoDB 기능을 사용할 수 없습니다.")


# ============================================================================
# 인증 관리자
# ============================================================================

class AuthManager:
    """인증 관리자"""
    
    def __init__(
        self, 
        use_dynamodb: bool = False, 
        table_name: str = "quant_trading_users",
        region: str = "ap-northeast-2",
        aws_access_key_id: Optional[str] = None,
        aws_secret_access_key: Optional[str] = None,
        aws_session_token: Optional[str] = None
    ):
        """
        Args:
            use_dynamodb: DynamoDB 사용 여부 (False면 인메모리 저장소 사용)
            table_name: DynamoDB 테이블 이름
            region: AWS 리전 (기본값: ap-northeast-2)
            aws_access_key_id: AWS Access Key ID (선택, 환경변수 사용 가능)
            aws_secret_access_key: AWS Secret Access Key (선택, 환경변수 사용 가능)
            aws_session_token: AWS Session Token (임시 자격 증명용, 선택)
        """
        if use_dynamodb and DYNAMODB_AVAILABLE:
            try:
                self.user_store = DynamoDBUserStore(
                    table_name=table_name,
                    region=region,
                    aws_access_key_id=aws_access_key_id,
                    aws_secret_access_key=aws_secret_access_key,
                    aws_session_token=aws_session_token
                )
                logger.info("DynamoDB 사용자 저장소 사용")
            except NoCredentialsError:
                self.user_store = SimpleUserStore()
                logger.warning(
                    "DynamoDB를 요청했지만 AWS 자격 증명을 찾지 못해 인메모리 저장소로 전환합니다. "
                    "해결: USE_DYNAMODB=false 또는 AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY 설정, "
                    "혹은 EC2 IAM Role(Instance Profile) 부여"
                )
            except ClientError as e:
                self.user_store = SimpleUserStore()
                logger.warning(f"DynamoDB 초기화 실패로 인메모리 저장소로 전환합니다: {e}")
        else:
            self.user_store = SimpleUserStore()
            if use_dynamodb:
                logger.warning("DynamoDB를 요청했지만 boto3가 없어 인메모리 저장소를 사용합니다.")
            else:
                logger.info("인메모리 사용자 저장소 사용")
    
    def create_access_token(self, username: str) -> str:
        """JWT 액세스 토큰 생성"""
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        payload = {
            "sub": username,
            "exp": expire,
            "iat": datetime.utcnow()
        }
        return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)
    
    def verify_token(self, token: str) -> Optional[str]:
        """JWT 토큰 검증"""
        try:
            payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
            username = payload.get("sub")
            return username
        except jwt.ExpiredSignatureError:
            return None
        except jwt.InvalidTokenError:
            return None
    
    def authenticate(self, username: str, password: str) -> Optional[str]:
        """사용자 인증 및 토큰 발급"""
        if self.user_store.verify_user(username, password):
            return self.create_access_token(username)
        return None
    
    def register(self, username: str, password: str, email: str = "") -> bool:
        """사용자 등록"""
        return self.user_store.create_user(username, password, email)
    
    def get_user(self, username: str) -> Optional[Dict]:
        """사용자 정보 조회"""
        return self.user_store.get_user(username)

# 전역 인증 관리자 설정
# DynamoDB 설정을 사용하려면 dynamodb_config.py를 수정하거나
# 환경변수를 설정하세요
try:
    from dynamodb_config import get_dynamodb_config
    config = get_dynamodb_config()
    auth_manager = AuthManager(
        use_dynamodb=config.get("use_dynamodb", False),
        table_name=config.get("table_name", "quant_trading_users"),
        region=config.get("region", "ap-northeast-2"),
        aws_access_key_id=config.get("aws_access_key_id"),
        aws_secret_access_key=config.get("aws_secret_access_key"),
        aws_session_token=config.get("aws_session_token")
    )
except ImportError:
    # dynamodb_config.py가 없으면 기본값 사용
    import os
    auth_manager = AuthManager(
        use_dynamodb=os.getenv("USE_DYNAMODB", "False").lower() == "true",
        table_name=os.getenv("DYNAMODB_TABLE_NAME", "quant_trading_users"),
        region=os.getenv("AWS_DEFAULT_REGION", "ap-northeast-2"),
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
        aws_session_token=os.getenv("AWS_SESSION_TOKEN")
    )
