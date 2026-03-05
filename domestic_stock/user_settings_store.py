import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class DynamoDBUserSettingsStore:
    """
    사용자별 설정 저장소 (DynamoDB)

    - PK: username (S)
    - Attributes:
        - risk_config_json
        - strategy_config_json
        - stock_selection_config_json
        - operational_config_json
        - updated_at (ISO8601)
        - schema_version (int)
    """

    def __init__(
        self,
        table_name: Optional[str] = None,
        region: Optional[str] = None,
        aws_access_key_id: Optional[str] = None,
        aws_secret_access_key: Optional[str] = None,
        aws_session_token: Optional[str] = None,
    ):
        self.table_name = (
            table_name
            or os.getenv("USER_SETTINGS_TABLE_NAME")
            or os.getenv("DYNAMODB_TABLE_NAME", "quant_trading_user_settings")
        )
        # USER_SETTINGS_REGION 있으면 우선, 없으면 AWS_DEFAULT_REGION / AWS_REGION, 기본 ap-northeast-2
        self.region = (
            region
            or os.getenv("USER_SETTINGS_REGION")
            or os.getenv("AWS_DEFAULT_REGION")
            or os.getenv("AWS_REGION", "ap-northeast-2")
        )

        self._enabled = False
        self._table = None
        self.init_error: Optional[str] = None
        self.init_error_code: Optional[str] = None
        self.init_error_type: Optional[str] = None

        try:
            import boto3
            from botocore.exceptions import ClientError, NoCredentialsError

            if aws_access_key_id is None:
                aws_access_key_id = os.getenv("AWS_ACCESS_KEY_ID")
            if aws_secret_access_key is None:
                aws_secret_access_key = os.getenv("AWS_SECRET_ACCESS_KEY")
            if aws_session_token is None:
                aws_session_token = os.getenv("AWS_SESSION_TOKEN")

            if aws_access_key_id and aws_secret_access_key:
                session = boto3.Session(
                    aws_access_key_id=aws_access_key_id,
                    aws_secret_access_key=aws_secret_access_key,
                    aws_session_token=aws_session_token,
                    region_name=self.region,
                )
                dynamodb = session.resource("dynamodb")
            else:
                dynamodb = boto3.resource("dynamodb", region_name=self.region)

            table = dynamodb.Table(self.table_name)

            # Ensure table exists (optionally create if missing)
            auto_create = str(os.getenv("USER_SETTINGS_AUTO_CREATE_TABLE", "false")).strip().lower() in {
                "1", "true", "t", "yes", "y", "on"
            }
            try:
                table.load()
            except NoCredentialsError:
                raise
            except ClientError as e:
                code = e.response.get("Error", {}).get("Code")
                if code == "ResourceNotFoundException":
                    if not auto_create:
                        raise RuntimeError(
                            f"DynamoDB settings table not found: {self.table_name} "
                            f"(region={self.region}). Create it first or set USER_SETTINGS_AUTO_CREATE_TABLE=true."
                        )

                    logger.warning(
                        f"DynamoDB settings table not found. Creating: {self.table_name}"
                    )
                    created = dynamodb.create_table(
                        TableName=self.table_name,
                        KeySchema=[{"AttributeName": "username", "KeyType": "HASH"}],
                        AttributeDefinitions=[
                            {"AttributeName": "username", "AttributeType": "S"}
                        ],
                        BillingMode="PAY_PER_REQUEST",
                    )
                    created.wait_until_exists()
                    table = dynamodb.Table(self.table_name)
                else:
                    raise

            self._table = table
            self._enabled = True
            logger.info(
                f"DynamoDB user settings enabled (table={self.table_name}, region={self.region})"
            )
        except Exception as e:
            self.init_error = str(e)
            self.init_error_type = type(e).__name__
            try:
                # botocore ClientError일 경우 에러 코드 기록
                resp = getattr(e, "response", None) or {}
                self.init_error_code = (resp.get("Error") or {}).get("Code")
            except Exception:
                self.init_error_code = None
            logger.warning(f"DynamoDB user settings disabled: {e}")

    @property
    def enabled(self) -> bool:
        return bool(self._enabled and self._table is not None)

    def status(self) -> Dict[str, Any]:
        """진단용 상태 정보(민감정보 제외)."""
        return {
            "enabled": self.enabled,
            "table_name": self.table_name,
            "region": self.region,
            "auto_create": str(os.getenv("USER_SETTINGS_AUTO_CREATE_TABLE", "false")).strip().lower() in {"1","true","t","yes","y","on"},
            "init_error": self.init_error,
            "init_error_type": self.init_error_type,
            "init_error_code": self.init_error_code,
            "has_aws_access_key_id": bool(os.getenv("AWS_ACCESS_KEY_ID")),
            "has_aws_secret_access_key": bool(os.getenv("AWS_SECRET_ACCESS_KEY")),
            "has_aws_session_token": bool(os.getenv("AWS_SESSION_TOKEN")),
        }

    def load(self, username: str, consistent_read: bool = True) -> Dict[str, Any]:
        """저장 직후 조회 시 최신 값이 보이도록 기본값은 Strongly Consistent Read."""
        if not self.enabled:
            return {}
        try:
            res = self._table.get_item(
                Key={"username": username},
                ConsistentRead=consistent_read,
            )
            item = res.get("Item") or {}
            out: Dict[str, Any] = {}
            for key, field in (
                ("risk_config", "risk_config_json"),
                ("strategy_config", "strategy_config_json"),
                ("stock_selection_config", "stock_selection_config_json"),
                ("operational_config", "operational_config_json"),
            ):
                raw = item.get(field)
                if isinstance(raw, str) and raw.strip():
                    try:
                        out[key] = json.loads(raw)
                    except Exception:
                        continue
            return out
        except Exception as e:
            logger.warning(f"User settings load failed ({username}): {e}")
            return {}

    def save(
        self,
        username: str,
        *,
        risk_config: Optional[Dict[str, Any]] = None,
        strategy_config: Optional[Dict[str, Any]] = None,
        stock_selection_config: Optional[Dict[str, Any]] = None,
        operational_config: Optional[Dict[str, Any]] = None,
    ) -> bool:
        if not self.enabled:
            return False
        try:
            sets = []
            values: Dict[str, Any] = {}
            if risk_config is not None:
                sets.append("risk_config_json=:risk")
                values[":risk"] = json.dumps(risk_config, ensure_ascii=False)
            if strategy_config is not None:
                sets.append("strategy_config_json=:strategy")
                values[":strategy"] = json.dumps(strategy_config, ensure_ascii=False)
            if stock_selection_config is not None:
                sets.append("stock_selection_config_json=:stocksel")
                values[":stocksel"] = json.dumps(stock_selection_config, ensure_ascii=False)
            if operational_config is not None:
                sets.append("operational_config_json=:oper")
                values[":oper"] = json.dumps(operational_config, ensure_ascii=False)

            now = datetime.now(timezone.utc).isoformat()
            sets.append("updated_at=:u")
            sets.append("schema_version=:v")
            values[":u"] = now
            values[":v"] = 1

            update_expr = "SET " + ", ".join(sets)
            self._table.update_item(
                Key={"username": username},
                UpdateExpression=update_expr,
                ExpressionAttributeValues=values,
            )
            return True
        except Exception as e:
            logger.warning(f"User settings save failed ({username}): {e}", exc_info=True)
            return False

