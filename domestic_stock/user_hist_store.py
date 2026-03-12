"""
사용자별 거래 내역 저장소 (DynamoDB quant_trading_user_hist)

테이블 스키마 (생성 시):
- PK: username (S)
- SK: sk (S), 값 예: YYYYMMDD#HHmmss#id — 일자·시간 순 정렬, 동일 초 구분용 id
- 속성: date, time, stock_code, order_type, quantity, price, pnl, reason, timestamp, ttl
- TTL: ttl (N) 속성에 Unix epoch 초 설정 시, 해당 시각 경과 후 자동 삭제 (10일 보관)
"""

import logging
import os
import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

RETENTION_DAYS = 10


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


class DynamoDBUserHistStore:
    def __init__(
        self,
        table_name: Optional[str] = None,
        region: Optional[str] = None,
        aws_access_key_id: Optional[str] = None,
        aws_secret_access_key: Optional[str] = None,
        aws_session_token: Optional[str] = None,
        retention_days: int = RETENTION_DAYS,
    ):
        _ensure_env()
        self.table_name = str(
            table_name
            or os.getenv("USER_HIST_TABLE_NAME")
            or os.getenv("DYNAMODB_HIST_TABLE_NAME", "quant_trading_user_hist")
        ).strip()
        self.region = str(
            region
            or os.getenv("USER_HIST_REGION")
            or os.getenv("AWS_DEFAULT_REGION")
            or os.getenv("AWS_REGION", "ap-northeast-2")
        ).strip()
        self.retention_days = max(1, int(retention_days))

        self._enabled = False
        self._table = None
        self.init_error: Optional[str] = None

        try:
            import boto3

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
            logger.info(
                "DynamoDB user hist store enabled (table=%s, region=%s, retention_days=%s)",
                self.table_name, self.region, self.retention_days,
            )
        except Exception as e:
            self.init_error = str(e)
            logger.warning("DynamoDB user hist store disabled: table=%s region=%s error=%s", self.table_name, self.region, e)

    @property
    def enabled(self) -> bool:
        return bool(self._enabled and self._table is not None)

    def put_trade(self, username: str, trade_info: Dict[str, Any]) -> bool:
        """
        거래 한 건 저장. 일자(YYYYMMDD)는 trade_info['timestamp'] 또는 현재 시각 기준.
        TTL로 retention_days 일 후 자동 삭제.
        """
        if not self.enabled or not username:
            return False
        try:
            ts = trade_info.get("timestamp") or datetime.now(timezone.utc).isoformat()
            if isinstance(ts, str) and "T" in ts:
                try:
                    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                except Exception:
                    dt = datetime.now(timezone.utc)
            else:
                dt = datetime.now(timezone.utc)
            date_str = dt.strftime("%Y%m%d")
            time_str = dt.strftime("%H%M%S")
            unique_id = str(uuid.uuid4())[:6]
            sk = f"{date_str}#{time_str}#{unique_id}"

            # TTL: 보관 일수 경과 후 삭제 (DynamoDB TTL은 Unix epoch 초)
            ttl_dt = datetime.now(timezone.utc) + timedelta(days=self.retention_days)
            ttl_ts = int(ttl_dt.timestamp())

            def _to_decimal(value: Optional[float], ndigits: Optional[int] = None) -> Optional[Decimal]:
                if value is None:
                    return None
                try:
                    f = float(value)
                    if ndigits is not None:
                        f = round(f, ndigits)
                    return Decimal(str(f))
                except Exception:
                    return None

            item = {
                "username": username,
                "sk": sk,
                "date": date_str,
                "time": time_str,
                "stock_code": str(trade_info.get("stock_code") or ""),
                "order_type": str(trade_info.get("order_type") or ""),
                "quantity": int(trade_info.get("quantity") or 0),
                # DynamoDB는 float 대신 Decimal 타입을 권장/요구하므로 변환
                "price": _to_decimal(trade_info.get("price") or 0, 2),
                "timestamp": ts,
                "ttl": ttl_ts,
            }
            pnl = trade_info.get("pnl")
            if pnl is not None:
                item["pnl"] = _to_decimal(pnl, 2)
            reason = trade_info.get("reason")
            if reason is not None:
                item["reason"] = str(reason)
            stock_name = trade_info.get("stock_name")
            if stock_name not in (None, ""):
                item["stock_name"] = str(stock_name).strip()[:80]
            order_status = trade_info.get("order_status")
            if order_status not in (None, ""):
                item["order_status"] = str(order_status).strip()[:40]

            self._table.put_item(Item=item)
            return True
        except Exception as e:
            logger.warning(f"User hist put_trade failed ({username}): {e}", exc_info=True)
            return False

    def get_trades(
        self,
        username: str,
        date_from: str,
        date_to: str,
    ) -> List[Dict[str, Any]]:
        """
        일자 범위 조회. date_from, date_to는 YYYYMMDD.
        최근 10일만 보관되므로 그 안의 기간만 유효.
        """
        if not self.enabled or not username:
            return []
        try:
            from boto3.dynamodb.conditions import Key

            # SK가 일자#시간#id 형태이므로 date_from ~ date_to 범위는
            # SK between "date_from#" and "date_to#\xff..." 로 조회
            sk_start = f"{date_from}#"
            sk_end = f"{date_to}#" + "\xff" * 20  # date_to 일의 모든 시간·id 포함

            res = self._table.query(
                KeyConditionExpression=Key("username").eq(username) & Key("sk").between(sk_start, sk_end)
            )
            items = res.get("Items", [])
            while res.get("LastEvaluatedKey"):
                res = self._table.query(
                    KeyConditionExpression=Key("username").eq(username) & Key("sk").between(sk_start, sk_end),
                    ExclusiveStartKey=res["LastEvaluatedKey"],
                )
                items.extend(res.get("Items", []))

            out = []
            for it in items:
                rec = {
                    "date": it.get("date"),
                    "time": it.get("time"),
                    "stock_code": it.get("stock_code"),
                    "stock_name": it.get("stock_name") or "",
                    "order_status": it.get("order_status") or "",
                    "order_type": it.get("order_type"),
                    "quantity": int(it.get("quantity") or 0),
                    "price": float(it.get("price") or 0),
                    "pnl": float(it["pnl"]) if it.get("pnl") is not None else None,
                    "reason": it.get("reason"),
                    "timestamp": it.get("timestamp"),
                }
                out.append(rec)
            return out
        except Exception as e:
            logger.warning(f"User hist get_trades failed ({username}): {e}")
            return []


_store: Optional[DynamoDBUserHistStore] = None


def get_user_hist_store() -> DynamoDBUserHistStore:
    global _store
    if _store is None:
        _store = DynamoDBUserHistStore()
    return _store
