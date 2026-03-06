"""
사용자별 일별 성과 저장소 (DynamoDB quant_trading_user_result)

- PK: username (S)
- SK: date (S, YYYYMMDD)
- 속성: equity_start, equity_end, pnl, return_pct, trade_count, updated_at
"""

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# .env 로드 (저장소 사용 전)
def _ensure_env():
    try:
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for path in (os.path.join(root, "config", ".env"), os.path.join(root, ".env")):
            if not os.path.isfile(path):
                continue
            try:
                with open(path, "r", encoding="utf-8") as f:
                    for raw in f:
                        line = raw.strip()
                        if not line or line.startswith("#") or "=" not in line:
                            continue
                        if line.startswith("export "):
                            line = line[len("export ") :].strip()
                        k, v = line.split("=", 1)
                        k, v = k.strip(), v.strip().strip('"').strip("'")
                        if k and k not in os.environ:
                            os.environ[k] = v
            except Exception:
                pass
    except Exception:
        pass


class DynamoDBUserResultStore:
    def __init__(
        self,
        table_name: Optional[str] = None,
        region: Optional[str] = None,
        aws_access_key_id: Optional[str] = None,
        aws_secret_access_key: Optional[str] = None,
        aws_session_token: Optional[str] = None,
    ):
        _ensure_env()
        self.table_name = str(
            table_name
            or os.getenv("USER_RESULT_TABLE_NAME")
            or os.getenv("DYNAMODB_RESULT_TABLE_NAME", "quant_trading_user_result")
        ).strip()
        self.region = str(
            region
            or os.getenv("USER_RESULT_REGION")
            or os.getenv("AWS_DEFAULT_REGION")
            or os.getenv("AWS_REGION", "ap-northeast-2")
        ).strip()

        self._enabled = False
        self._table = None
        self.init_error: Optional[str] = None

        try:
            import boto3
            from botocore.exceptions import ClientError

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
            table.load()
            self._table = table
            self._enabled = True
            logger.info(f"DynamoDB user result store enabled (table={self.table_name}, region={self.region})")
        except Exception as e:
            self.init_error = str(e)
            logger.warning(f"DynamoDB user result store disabled: {e}")

    @property
    def enabled(self) -> bool:
        return bool(self._enabled and self._table is not None)

    def get(self, username: str, date: str) -> Optional[Dict[str, Any]]:
        """당일 기존 row 조회. date=YYYYMMDD."""
        if not self.enabled:
            return None
        try:
            res = self._table.get_item(Key={"username": username, "date": date})
            item = res.get("Item")
            if not item:
                return None
            out = dict(item)
            for k in ("equity_start", "equity_end", "pnl", "return_pct", "trade_count"):
                if k in out and hasattr(out[k], "__float__"):
                    try:
                        out[k] = float(out[k])
                    except Exception:
                        pass
                if k == "trade_count" and k in out:
                    try:
                        out[k] = int(out[k])
                    except Exception:
                        pass
            return out
        except Exception as e:
            logger.warning(f"User result get failed ({username}/{date}): {e}")
            return None

    def save_daily_result(
        self,
        username: str,
        date: str,
        equity_end: float,
        trade_count: int,
        equity_start: Optional[float] = None,
    ) -> bool:
        """
        일별 성과 저장. 기존 row가 있으면 통합(equity_start 유지, equity_end·pnl·trade_count 갱신).
        date=YYYYMMDD.
        """
        if not self.enabled:
            return False
        try:
            existing = self.get(username, date)
            if existing is not None:
                start = float(existing.get("equity_start") or 0)
                # 당일 여러 번 중지 시 거래 횟수 누적
                trade_count = int(existing.get("trade_count") or 0) + int(trade_count)
            else:
                start = float(equity_start if equity_start is not None else equity_end)
                trade_count = int(trade_count)

            pnl = equity_end - start
            return_pct = (pnl / start * 100.0) if start and start != 0 else 0.0
            now = datetime.now(timezone.utc).isoformat()

            self._table.put_item(
                Item={
                    "username": username,
                    "date": date,
                    "equity_start": round(start, 2),
                    "equity_end": round(equity_end, 2),
                    "pnl": round(pnl, 2),
                    "return_pct": round(return_pct, 4),
                    "trade_count": trade_count,
                    "updated_at": now,
                }
            )
            return True
        except Exception as e:
            logger.warning(f"User result save failed ({username}/{date}): {e}", exc_info=True)
            return False

    def query_range(
        self,
        username: str,
        date_from: str,
        date_to: str,
    ) -> List[Dict[str, Any]]:
        """username 기준으로 date_from ~ date_to 구간 조회. date는 YYYYMMDD. 정렬: date 오름차순."""
        if not self.enabled:
            return []
        try:
            from boto3.dynamodb.conditions import Key

            res = self._table.query(
                KeyConditionExpression=Key("username").eq(username) & Key("date").between(date_from, date_to),
                ScanIndexForward=True,
            )
            items = res.get("Items", [])
            while res.get("LastEvaluatedKey"):
                res = self._table.query(
                    KeyConditionExpression=Key("username").eq(username) & Key("date").between(date_from, date_to),
                    ExclusiveStartKey=res["LastEvaluatedKey"],
                    ScanIndexForward=True,
                )
                items.extend(res.get("Items", []))

            out = []
            for item in items:
                row = dict(item)
                for k in ("equity_start", "equity_end", "pnl", "return_pct"):
                    if k in row:
                        try:
                            row[k] = float(row[k])
                        except Exception:
                            pass
                if "trade_count" in row:
                    try:
                        row["trade_count"] = int(row["trade_count"])
                    except Exception:
                        pass
                out.append(row)
            return out
        except Exception as e:
            logger.warning(f"User result query failed ({username} {date_from}~{date_to}): {e}")
            return []
