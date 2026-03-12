"""
사용자별 일별 성과 저장소 (DynamoDB quant_trading_user_result)

- PK: username (S)
- SK: date (S, YYYYMMDD)
- 속성: equity_start, equity_end, pnl, return_pct, trade_count, updated_at
- 선택: wins, losses, gross_profit, gross_loss (기간 Win rate / Profit factor 집계용)
"""

import json
import logging
import os
from datetime import datetime, timezone
from decimal import Decimal
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
            for k in ("equity_start", "equity_end", "pnl", "return_pct", "gross_profit", "gross_loss"):
                if k in out:
                    try:
                        out[k] = float(out[k])
                    except Exception:
                        pass
            for k in ("trade_count", "wins", "losses"):
                if k in out:
                    try:
                        out[k] = int(out[k])
                    except Exception:
                        pass
            return out
        except Exception as e:
            logger.warning(f"User result get failed ({username}/{date}): {e}")
            return None

    def _to_decimal(self, value: Optional[float], ndigits: Optional[int] = None) -> Optional[Decimal]:
        """float → Decimal 변환 (None 안전). ndigits 지정 시 반올림."""
        if value is None:
            return None
        try:
            f = float(value)
            if ndigits is not None:
                f = round(f, ndigits)
            return Decimal(str(f))
        except Exception:
            return None

    def save_daily_result(
        self,
        username: str,
        date: str,
        equity_end: float,
        trade_count: int,
        equity_start: Optional[float] = None,
        wins: Optional[int] = None,
        losses: Optional[int] = None,
        gross_profit: Optional[float] = None,
        gross_loss: Optional[float] = None,
    ) -> bool:
        """
        일별 성과 저장. 기존 row가 있으면 통합(equity_start 유지, equity_end·pnl·trade_count·wins·losses·gross 누적).
        date=YYYYMMDD. wins/losses/gross_profit/gross_loss는 백테스트·기간 통계용.
        """
        if not self.enabled:
            return False
        try:
            existing = self.get(username, date)
            if existing is not None:
                start = float(existing.get("equity_start") or 0)
                trade_count = int(existing.get("trade_count") or 0) + int(trade_count)
                wins = int(existing.get("wins") or 0) + (int(wins) if wins is not None else 0)
                losses = int(existing.get("losses") or 0) + (int(losses) if losses is not None else 0)
                gross_profit = float(existing.get("gross_profit") or 0) + (float(gross_profit) if gross_profit is not None else 0)
                gross_loss = float(existing.get("gross_loss") or 0) + (float(gross_loss) if gross_loss is not None else 0)
            else:
                start = float(equity_start if equity_start is not None else equity_end)
                trade_count = int(trade_count)
                wins = int(wins) if wins is not None else None
                losses = int(losses) if losses is not None else None
                gross_profit = float(gross_profit) if gross_profit is not None else None
                gross_loss = float(gross_loss) if gross_loss is not None else None

            pnl = equity_end - start
            return_pct = (pnl / start * 100.0) if start and start != 0 else 0.0
            now = datetime.now(timezone.utc).isoformat()

            item = {
                "username": username,
                "date": date,
                # DynamoDB는 float 대신 Decimal 타입을 권장/요구하므로 변환
                "equity_start": self._to_decimal(start, 2),
                "equity_end": self._to_decimal(equity_end, 2),
                "pnl": self._to_decimal(pnl, 2),
                "return_pct": self._to_decimal(return_pct, 4),
                "trade_count": trade_count,
                "updated_at": now,
            }
            if wins is not None:
                item["wins"] = wins
            if losses is not None:
                item["losses"] = losses
            if gross_profit is not None:
                item["gross_profit"] = self._to_decimal(gross_profit, 2)
            if gross_loss is not None:
                item["gross_loss"] = self._to_decimal(gross_loss, 2)
            self._table.put_item(Item=item)
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
                for k in ("equity_start", "equity_end", "pnl", "return_pct", "gross_profit", "gross_loss"):
                    if k in row:
                        try:
                            row[k] = float(row[k])
                        except Exception:
                            pass
                for k in ("trade_count", "wins", "losses"):
                    if k in row:
                        try:
                            row[k] = int(row[k])
                        except Exception:
                            pass
                out.append(row)
            return out
        except Exception as e:
            logger.warning(f"User result query failed ({username} {date_from}~{date_to}): {e}", exc_info=True)
            return []
