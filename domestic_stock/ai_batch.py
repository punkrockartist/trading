"""
Batch learner for trading logs -> DynamoDB (quant_trading_user_ai).

Usage examples:
  python ai_batch.py --username smjeon --date 20260423
  python ai_batch.py --username smjeon --date 20260423 --include-diagnostic
"""

from __future__ import annotations

import argparse
import json
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, List, Tuple


KST = timezone(timedelta(hours=9))


def _ensure_env() -> None:
    """Load .env values if present."""
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
                        k = k.strip()
                        v = v.strip().strip('"').strip("'")
                        if k and k not in os.environ:
                            os.environ[k] = v
            except Exception:
                pass
    except Exception:
        pass


def _to_decimal_recursive(value: Any) -> Any:
    """Convert float recursively for DynamoDB put_item."""
    if isinstance(value, float):
        return Decimal(str(round(value, 10)))
    if isinstance(value, dict):
        return {k: _to_decimal_recursive(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_to_decimal_recursive(v) for v in value]
    return value


def _today_yyyymmdd_kst() -> str:
    return datetime.now(KST).strftime("%Y%m%d")


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except Exception:
        return default


def _safe_int(v: Any, default: int = 0) -> int:
    try:
        return int(v)
    except Exception:
        return default


@dataclass
class LoadedEvents:
    all_events: List[Dict[str, Any]]
    main_events: List[Dict[str, Any]]
    diagnostic_events: List[Dict[str, Any]]


def load_order_events(logs_dir: str, date_yyyymmdd: str, include_diagnostic: bool) -> LoadedEvents:
    path = os.path.join(logs_dir, f"order_events_{date_yyyymmdd}.jsonl")
    if not os.path.isfile(path):
        raise FileNotFoundError(f"order events file not found: {path}")

    all_events: List[Dict[str, Any]] = []
    main_events: List[Dict[str, Any]] = []
    diagnostic_events: List[Dict[str, Any]] = []

    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except Exception:
                continue
            all_events.append(ev)

            # Main learning samples: filled trades only
            if bool(ev.get("filled", False)):
                main_events.append(ev)
                continue

            # Optional: include diagnostic attempts as extra inputs
            if include_diagnostic:
                diagnostic_events.append(ev)

    return LoadedEvents(all_events=all_events, main_events=main_events, diagnostic_events=diagnostic_events)


def summarize_events(loaded: LoadedEvents) -> Dict[str, Any]:
    events = loaded.all_events
    attempts = len(events)
    success = sum(1 for e in events if bool(e.get("success", False)))
    filled = sum(1 for e in events if bool(e.get("filled", False)))
    failed = attempts - success

    by_side: Dict[str, int] = {}
    by_stock: Dict[str, int] = {}
    reject_reasons: Dict[str, int] = {}
    range_ratios: List[float] = []

    for e in events:
        side = str(e.get("signal", "") or "").lower()
        code = str(e.get("stock_code", "") or "").strip()
        by_side[side] = by_side.get(side, 0) + 1
        if code:
            by_stock[code] = by_stock.get(code, 0) + 1

        if not bool(e.get("success", False)):
            r = str(e.get("reason", "") or "unknown").strip()
            reject_reasons[r] = reject_reasons.get(r, 0) + 1

        rr = _safe_float(((e.get("tick_summary_60s") or {}).get("px_range_ratio")), -1.0)
        if rr >= 0:
            range_ratios.append(rr)

    avg_range_ratio = (sum(range_ratios) / len(range_ratios)) if range_ratios else 0.0

    top_reject = sorted(reject_reasons.items(), key=lambda x: x[1], reverse=True)[:5]
    top_stocks = sorted(by_stock.items(), key=lambda x: x[1], reverse=True)[:10]

    return {
        "attempts": attempts,
        "success_count": success,
        "failed_count": failed,
        "filled_count": filled,
        "success_rate": (success / attempts) if attempts else 0.0,
        "filled_rate": (filled / attempts) if attempts else 0.0,
        "avg_range_ratio_60s": avg_range_ratio,
        "by_side": by_side,
        "top_stocks": [{"stock_code": c, "count": n} for c, n in top_stocks],
        "top_reject_reasons": [{"reason": r, "count": n} for r, n in top_reject],
        "main_sample_count": len(loaded.main_events),
        "diagnostic_sample_count": len(loaded.diagnostic_events),
    }


def recommend_from_summary(summary: Dict[str, Any]) -> Dict[str, Any]:
    """Simple rule-based recommendation (safe starter)."""
    recs: List[Dict[str, Any]] = []
    notes: List[str] = []

    attempts = _safe_int(summary.get("attempts"))
    filled_rate = _safe_float(summary.get("filled_rate"))
    avg_range = _safe_float(summary.get("avg_range_ratio_60s"))

    reason_map = {r["reason"]: _safe_int(r["count"]) for r in summary.get("top_reject_reasons", [])}
    pending_sell = reason_map.get("pending_sell_order", 0)
    pending_sell_rate = (pending_sell / attempts) if attempts > 0 else 0.0

    if attempts == 0:
        notes.append("No data: order_events file is empty for this date.")
    else:
        notes.append(f"Attempts={attempts}, filled_rate={filled_rate*100:.2f}%")

    # Conservative rules: suggestions only, no auto-apply
    if pending_sell_rate >= 0.20:
        recs.append({
            "key": "sell_qty_reject_cooldown_sec",
            "current": "existing",
            "suggested": 60,
            "why": "High pending_sell_order rate indicates duplicate sell retry bursts"
        })
    if avg_range < 0.002:
        recs.append({
            "key": "min_range_ratio",
            "current": "existing",
            "suggested": 0.001,
            "why": "Low recent range implies noisy entries in narrow regimes"
        })
    if attempts > 0 and filled_rate < 0.02:
        recs.append({
            "key": "order_style_check",
            "current": "best_limit",
            "suggested": "best_limit_keep_or_retry_tune",
            "why": "Very low fill rate; review order style and retry policy"
        })

    if not recs:
        recs.append({
            "key": "no_change",
            "current": "n/a",
            "suggested": "keep",
            "why": "No strong adjustment signal from current data"
        })

    return {
        "summary": notes[0] if notes else "No learning summary",
        "notes": notes,
        "recommendations": recs,
    }


def save_to_dynamodb(
    username: str,
    date_yyyymmdd: str,
    summary: Dict[str, Any],
    recommendation: Dict[str, Any],
    include_diagnostic: bool,
) -> Tuple[bool, str]:
    _ensure_env()
    try:
        import boto3
    except Exception as e:
        return False, f"boto3 import failed: {e}"

    table_name = os.getenv("DYNAMODB_AI_TABLE_NAME", "quant_trading_user_ai").strip()
    region = os.getenv("AWS_DEFAULT_REGION", os.getenv("AWS_REGION", "ap-northeast-2")).strip()

    aws_access_key_id = os.getenv("AWS_ACCESS_KEY_ID")
    aws_secret_access_key = os.getenv("AWS_SECRET_ACCESS_KEY")
    aws_session_token = os.getenv("AWS_SESSION_TOKEN")

    if aws_access_key_id and aws_secret_access_key:
        session = boto3.Session(
            aws_access_key_id=aws_access_key_id,
            aws_secret_access_key=aws_secret_access_key,
            aws_session_token=aws_session_token,
            region_name=region,
        )
        dynamodb = session.resource("dynamodb")
    else:
        dynamodb = boto3.resource("dynamodb", region_name=region)

    table = dynamodb.Table(table_name)
    run_id = f"{date_yyyymmdd}#{datetime.now(timezone.utc).strftime('%H%M%S')}#{uuid.uuid4().hex[:8]}"

    pk_name = os.getenv("DYNAMODB_AI_PK", "username").strip() or "username"
    sk_name = os.getenv("DYNAMODB_AI_SK", "run_id").strip() or "run_id"

    item: Dict[str, Any] = {
        pk_name: username,
        sk_name: run_id,
        "entity_type": "batch_learning_result",
        "date": date_yyyymmdd,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "learning_scope": "filled_plus_diagnostic" if include_diagnostic else "filled_only",
        "summary": summary,
        "recommendation": recommendation,
        "source": {
            "order_events_file": f"order_events_{date_yyyymmdd}.jsonl",
            "version": "v1",
        },
    }

    table.put_item(Item=_to_decimal_recursive(item))
    return True, f"saved to {table_name} ({pk_name}/{sk_name})"


def main() -> int:
    parser = argparse.ArgumentParser(description="Batch learner for AI shadow from order events.")
    parser.add_argument("--username", required=True, help="user id/name")
    parser.add_argument("--date", default=_today_yyyymmdd_kst(), help="YYYYMMDD (default: today KST)")
    parser.add_argument("--logs-dir", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs"))
    parser.add_argument("--include-diagnostic", action="store_true", help="include non-filled attempts in learning set")
    parser.add_argument("--dry-run", action="store_true", help="print result only, no DB write")
    args = parser.parse_args()

    loaded = load_order_events(args.logs_dir, args.date, args.include_diagnostic)
    summary = summarize_events(loaded)
    recommendation = recommend_from_summary(summary)

    output = {
        "username": args.username,
        "date": args.date,
        "learning_scope": "filled_plus_diagnostic" if args.include_diagnostic else "filled_only",
        "summary": summary,
        "recommendation": recommendation,
    }

    print(json.dumps(output, ensure_ascii=False, indent=2))

    if args.dry_run:
        return 0

    ok, msg = save_to_dynamodb(
        username=args.username,
        date_yyyymmdd=args.date,
        summary=summary,
        recommendation=recommendation,
        include_diagnostic=args.include_diagnostic,
    )
    print(json.dumps({"saved": ok, "message": msg}, ensure_ascii=False))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

