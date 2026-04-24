# -*- coding: utf-8 -*-
"""AI Shadow helpers (non-invasive): scores and hints only; no order/exit decisions."""

import json
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple


KST = timezone(timedelta(hours=9))


def _to_ddb_num(v: float) -> Decimal:
    return Decimal(str(round(float(v), 10)))


def _resolve_ai_table():
    try:
        import boto3  # type: ignore
    except Exception:
        return None
    table_name = os.getenv("DYNAMODB_AI_TABLE_NAME", "quant_trading_user_ai").strip() or "quant_trading_user_ai"
    region = os.getenv("AWS_DEFAULT_REGION", os.getenv("AWS_REGION", "ap-northeast-2")).strip() or "ap-northeast-2"
    aws_access_key_id = os.getenv("AWS_ACCESS_KEY_ID")
    aws_secret_access_key = os.getenv("AWS_SECRET_ACCESS_KEY")
    aws_session_token = os.getenv("AWS_SESSION_TOKEN")
    try:
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
        return dynamodb.Table(table_name)
    except Exception:
        return None


def persist_execution_shadow_aggregate(
    *,
    username: str,
    run_id: str,
    exec_shadow: Dict[str, Any],
    session: str = "",
) -> Tuple[bool, str]:
    """Persist AI shadow aggregates to DynamoDB (daily + run cumulative)."""
    table = _resolve_ai_table()
    if table is None:
        return False, "dynamodb table unavailable"

    now = datetime.now(KST)
    day_key = now.strftime("%Y%m%d")
    ts = now.isoformat()
    pk_name = os.getenv("DYNAMODB_AI_PK", "username").strip() or "username"
    sk_name = os.getenv("DYNAMODB_AI_SK", "run_id").strip() or "run_id"
    username_v = (username or "admin").strip() or "admin"
    run_id_v = (run_id or "").strip() or f"{day_key}#runtime"

    stock_code = str(exec_shadow.get("stock_code") or "").strip().zfill(6)
    side = str(exec_shadow.get("side") or "").strip().lower()
    level = str(exec_shadow.get("level") or "low").strip().lower()
    score = int(exec_shadow.get("score") or 0)
    spread_ratio = float(exec_shadow.get("spread_ratio") or 0.0)
    range_ratio = float(exec_shadow.get("recent_range_ratio") or 0.0)

    level_hits = {
        "low": Decimal("1") if level == "low" else Decimal("0"),
        "medium": Decimal("1") if level == "medium" else Decimal("0"),
        "high": Decimal("1") if level == "high" else Decimal("0"),
    }
    side_hits = {
        "buy": Decimal("1") if side == "buy" else Decimal("0"),
        "sell": Decimal("1") if side == "sell" else Decimal("0"),
    }
    refs = (
        (f"ai_shadow_day#{day_key}", "day"),
        (f"ai_shadow_run#{day_key}#{run_id_v}", "run"),
    )

    try:
        for sk_val, agg_type in refs:
            table.update_item(
                Key={pk_name: username_v, sk_name: sk_val},
                UpdateExpression=(
                    "SET #typ=:typ, #username=:username, #day=:day, #last_ts=:last_ts, "
                    "#run_ref=:run_ref, #last_stock=:last_stock, #last_side=:last_side, "
                    "#last_level=:last_level, #session=:session "
                    "ADD #exec_count :one, #score_sum :score, #spread_sum :spread, #range_sum :rr, "
                    "#level_low_count :lvl_low, #level_medium_count :lvl_med, #level_high_count :lvl_high, "
                    "#side_buy_count :side_buy, #side_sell_count :side_sell"
                ),
                ExpressionAttributeNames={
                    "#typ": "record_type",
                    "#username": "username",
                    "#day": "date_yyyymmdd",
                    "#last_ts": "last_updated_at",
                    "#run_ref": "run_id_ref",
                    "#last_stock": "last_stock_code",
                    "#last_side": "last_side",
                    "#last_level": "last_risk_level",
                    "#session": "last_session",
                    "#exec_count": "execution_count",
                    "#score_sum": "score_sum",
                    "#spread_sum": "spread_ratio_sum",
                    "#range_sum": "recent_range_ratio_sum",
                    "#level_low_count": "level_low_count",
                    "#level_medium_count": "level_medium_count",
                    "#level_high_count": "level_high_count",
                    "#side_buy_count": "side_buy_count",
                    "#side_sell_count": "side_sell_count",
                },
                ExpressionAttributeValues={
                    ":typ": f"ai_shadow_{agg_type}",
                    ":username": username_v,
                    ":day": day_key,
                    ":last_ts": ts,
                    ":run_ref": run_id_v,
                    ":last_stock": stock_code,
                    ":last_side": side,
                    ":last_level": level,
                    ":session": str(session or ""),
                    ":one": Decimal("1"),
                    ":score": Decimal(str(score)),
                    ":spread": _to_ddb_num(spread_ratio),
                    ":rr": _to_ddb_num(range_ratio),
                    ":lvl_low": level_hits["low"],
                    ":lvl_med": level_hits["medium"],
                    ":lvl_high": level_hits["high"],
                    ":side_buy": side_hits["buy"],
                    ":side_sell": side_hits["sell"],
                },
            )
        return True, "ok"
    except Exception as e:
        return False, f"update_item failed: {e}"


def _ddb_str(v: Any, max_len: int = 900) -> str:
    if v is None:
        return ""
    if isinstance(v, str):
        s = v
    else:
        try:
            s = json.dumps(v, ensure_ascii=False, default=str)
        except Exception:
            s = str(v)
    return s[:max_len] if len(s) > max_len else s


def persist_loss_guard_aggregate(
    *,
    username: str,
    run_id: str,
    loss_guard: Dict[str, Any],
    daily_pnl: float,
) -> Tuple[bool, str]:
    """Loss Guard Shadow 샘플을 일자·실행(run)별로 누적 저장."""
    table = _resolve_ai_table()
    if table is None:
        return False, "dynamodb table unavailable"

    now = datetime.now(KST)
    day_key = now.strftime("%Y%m%d")
    ts = now.isoformat()
    pk_name = os.getenv("DYNAMODB_AI_PK", "username").strip() or "username"
    sk_name = os.getenv("DYNAMODB_AI_SK", "run_id").strip() or "run_id"
    username_v = (username or "admin").strip() or "admin"
    run_id_v = (run_id or "").strip() or f"{day_key}#runtime"

    level = str(loss_guard.get("level") or "normal").strip().lower()
    score = int(loss_guard.get("score") or 0)
    reasons = loss_guard.get("reasons") or []
    reasons_joined = ",".join(str(x) for x in reasons) if isinstance(reasons, list) else str(reasons)

    lvl = {
        "normal": Decimal("1") if level == "normal" else Decimal("0"),
        "warning": Decimal("1") if level == "warning" else Decimal("0"),
        "critical": Decimal("1") if level == "critical" else Decimal("0"),
    }
    refs = (
        (f"ai_loss_guard_day#{day_key}", "ai_loss_guard_day"),
        (f"ai_loss_guard_run#{day_key}#{run_id_v}", "ai_loss_guard_run"),
    )

    try:
        for sk_val, typ in refs:
            table.update_item(
                Key={pk_name: username_v, sk_name: sk_val},
                UpdateExpression=(
                    "SET #typ=:typ, #username=:username, #day=:day, #last_ts=:last_ts, "
                    "#run_ref=:run_ref, #last_daily_pnl=:last_pnl, #last_level=:last_lvl, "
                    "#last_reasons=:last_rs "
                    "ADD #cnt :one, #score_sum :score, "
                    "#ln :lvl_n, #lw :lvl_w, #lc :lvl_c"
                ),
                ExpressionAttributeNames={
                    "#typ": "record_type",
                    "#username": "username",
                    "#day": "date_yyyymmdd",
                    "#last_ts": "last_updated_at",
                    "#run_ref": "run_id_ref",
                    "#last_daily_pnl": "last_daily_pnl",
                    "#last_level": "last_loss_guard_level",
                    "#last_reasons": "last_loss_guard_reasons",
                    "#cnt": "loss_guard_sample_count",
                    "#score_sum": "loss_guard_score_sum",
                    "#ln": "loss_guard_level_normal_count",
                    "#lw": "loss_guard_level_warning_count",
                    "#lc": "loss_guard_level_critical_count",
                },
                ExpressionAttributeValues={
                    ":typ": typ,
                    ":username": username_v,
                    ":day": day_key,
                    ":last_ts": ts,
                    ":run_ref": run_id_v,
                    ":last_pnl": _to_ddb_num(float(daily_pnl)),
                    ":last_lvl": level,
                    ":last_rs": reasons_joined[:900],
                    ":one": Decimal("1"),
                    ":score": Decimal(str(score)),
                    ":lvl_n": lvl["normal"],
                    ":lvl_w": lvl["warning"],
                    ":lvl_c": lvl["critical"],
                },
            )
        return True, "ok"
    except Exception as e:
        return False, f"update_item failed: {e}"


def persist_auto_tuning_aggregate(
    *,
    username: str,
    run_id: str,
    rec: Dict[str, Any],
) -> Tuple[bool, str]:
    """Auto Tuning 평가(약 5분 주기)를 일자·실행(run)별로 누적 저장."""
    table = _resolve_ai_table()
    if table is None:
        return False, "dynamodb table unavailable"

    now = datetime.now(KST)
    day_key = now.strftime("%Y%m%d")
    ts = now.isoformat()
    pk_name = os.getenv("DYNAMODB_AI_PK", "username").strip() or "username"
    sk_name = os.getenv("DYNAMODB_AI_SK", "run_id").strip() or "run_id"
    username_v = (username or "admin").strip() or "admin"
    run_id_v = (run_id or "").strip() or f"{day_key}#runtime"

    available = bool(rec.get("available"))
    summary = str(rec.get("summary") or "")[:900]
    recs = rec.get("recommendations") or []
    has_recs = bool(recs) and isinstance(recs, list)
    top = recs[0] if has_recs else {}
    top_key = str(top.get("key") or "")[:120]
    top_current = _ddb_str(top.get("current"), 300)
    top_suggested = _ddb_str(top.get("suggested"), 300)
    top_why = str(top.get("why") or "")[:600]

    refs = (
        (f"ai_auto_tuning_day#{day_key}", "ai_auto_tuning_day"),
        (f"ai_auto_tuning_run#{day_key}#{run_id_v}", "ai_auto_tuning_run"),
    )

    wr_inc = Decimal("1") if has_recs else Decimal("0")
    try:
        for sk_val, typ in refs:
            table.update_item(
                Key={pk_name: username_v, sk_name: sk_val},
                UpdateExpression=(
                    "SET #typ=:typ, #username=:username, #day=:day, #last_ts=:last_ts, "
                    "#run_ref=:run_ref, #last_avail=:avail, #last_sum=:sum, "
                    "#last_top_key=:tk, #last_top_current=:tc, #last_top_suggested=:tsg, #last_top_why=:tw "
                    "ADD #eval :one, #with_rec :wr_inc"
                ),
                ExpressionAttributeNames={
                    "#typ": "record_type",
                    "#username": "username",
                    "#day": "date_yyyymmdd",
                    "#last_ts": "last_updated_at",
                    "#run_ref": "run_id_ref",
                    "#last_avail": "last_auto_tuning_available",
                    "#last_sum": "last_auto_tuning_summary",
                    "#last_top_key": "last_auto_tuning_top_key",
                    "#last_top_current": "last_auto_tuning_top_current",
                    "#last_top_suggested": "last_auto_tuning_top_suggested",
                    "#last_top_why": "last_auto_tuning_top_why",
                    "#eval": "auto_tuning_eval_count",
                    "#with_rec": "auto_tuning_with_recommendations_count",
                },
                ExpressionAttributeValues={
                    ":typ": typ,
                    ":username": username_v,
                    ":day": day_key,
                    ":last_ts": ts,
                    ":run_ref": run_id_v,
                    ":avail": available,
                    ":sum": summary,
                    ":tk": top_key,
                    ":tc": top_current,
                    ":tsg": top_suggested,
                    ":tw": top_why,
                    ":one": Decimal("1"),
                    ":wr_inc": wr_inc,
                },
            )
        return True, "ok"
    except Exception as e:
        return False, f"update_item failed: {e}"


def execution_shadow_score(
    *,
    stock_code: str,
    side: str,
    price: float,
    ask: float,
    bid: float,
    max_spread_ratio: float,
    recent_range_ratio: float,
    momentum_ratio: Optional[float] = None,
    slope_ratio: Optional[float] = None,
    depth5_ask_vol_sum: Optional[float] = None,
    depth5_bid_vol_sum: Optional[float] = None,
) -> Dict[str, Any]:
    score = 0
    reasons: List[str] = []

    spread_ratio = 0.0
    if price > 0 and ask > 0 and bid > 0 and ask >= bid:
        spread_ratio = (ask - bid) / float(price)
    if max_spread_ratio > 0 and spread_ratio > max_spread_ratio:
        score += 45
        reasons.append("\uc2a4\ud504\ub808\ub4dc \uacfc\ub300")
    elif spread_ratio > 0.0015:
        score += 20
        reasons.append("\uc2a4\ud504\ub808\ub4dc \uc8fc\uc758")

    if recent_range_ratio > 0.015:
        score += 30
        reasons.append("\ub2e8\uae30 \ubcc0\ub3d9\uc131 \ub192\uc74c")
    elif recent_range_ratio > 0.01:
        score += 15
        reasons.append("\ub2e8\uae30 \ubcc0\ub3d9\uc131 \ubcf4\ud1b5")

    if momentum_ratio is not None and momentum_ratio < 0:
        score += 10
        reasons.append("\ubaa8\uba58\ud140 \uc57d\ud654")
    if slope_ratio is not None and slope_ratio < 0:
        score += 10
        reasons.append("\uae30\uc6b8\uae30 \uc57d\ud654")

    # 5-depth book: warn if lift side cumulative qty is thin vs opposite (heuristic).
    aa = float(depth5_ask_vol_sum) if depth5_ask_vol_sum is not None else -1.0
    bb = float(depth5_bid_vol_sum) if depth5_bid_vol_sum is not None else -1.0
    if aa >= 0.0 and bb >= 0.0 and (aa + bb) > 0:
        sd = str(side).lower()
        if sd == "buy" and bb > 0 and aa < bb * 0.25:
            score += 12
            reasons.append("depth5_ask_thin")
        elif sd == "sell" and aa > 0 and bb < aa * 0.25:
            score += 12
            reasons.append("depth5_bid_thin")

    level = "low"
    if score >= 60:
        level = "high"
    elif score >= 30:
        level = "medium"

    return {
        "stock_code": str(stock_code).strip().zfill(6),
        "side": str(side).lower(),
        "score": int(max(0, min(100, score))),
        "level": level,
        "spread_ratio": float(spread_ratio),
        "recent_range_ratio": float(max(0.0, recent_range_ratio)),
        "reasons": reasons,
    }


def loss_guard_shadow(
    *,
    daily_pnl: float,
    daily_loss_limit: float,
    consecutive_losses: int,
    recent_sell_pnls: List[float],
) -> Dict[str, Any]:
    score = 0
    reasons: List[str] = []

    if daily_loss_limit > 0:
        loss_ratio = abs(min(0.0, daily_pnl)) / float(daily_loss_limit)
        if loss_ratio >= 0.7:
            score += 55
            reasons.append("\uc77c\uc190\uc2e4 \ud55c\ub3c4 70% \uc774\uc0c1")
        elif loss_ratio >= 0.5:
            score += 30
            reasons.append("\uc77c\uc190\uc2e4 \ud55c\ub3c4 50% \uc774\uc0c1")

    if consecutive_losses >= 3:
        score += 35
        reasons.append("\uc5f0\uc18d \uc190\uc2e4 3\ud68c+")
    elif consecutive_losses >= 2:
        score += 20
        reasons.append("\uc5f0\uc18d \uc190\uc2e4 2\ud68c")

    if recent_sell_pnls:
        neg = [x for x in recent_sell_pnls if x < 0]
        if len(neg) >= 3 and abs(sum(neg)) > 0:
            score += 10
            reasons.append("\ucd5c\uadfc \ub9e4\ub3c4 \uc190\uc775 \uc545\ud654")

    level = "normal"
    if score >= 60:
        level = "critical"
    elif score >= 30:
        level = "warning"

    return {"score": int(max(0, min(100, score))), "level": level, "reasons": reasons}


def auto_tuning_recommendation(
    *,
    trades: List[Dict[str, Any]],
    current_risk: Dict[str, Any],
    current_strategy: Dict[str, Any],
) -> Dict[str, Any]:
    _ = current_strategy
    sells = [t for t in trades if str(t.get("order_type") or "").lower() == "sell" and t.get("pnl") is not None]
    if not sells:
        return {"available": False, "summary": "\ucd94\ucc9c \ub370\uc774\ud130 \ubd80\uc871", "recommendations": []}

    pnls: List[float] = []
    for s in sells:
        try:
            pnls.append(float(s.get("pnl")))
        except Exception:
            pass
    if not pnls:
        return {"available": False, "summary": "\ucd94\ucc9c \ub370\uc774\ud130 \ubd80\uc871", "recommendations": []}

    wins = sum(1 for p in pnls if p > 0)
    n = len(pnls)
    win_rate = wins / n if n else 0.0
    avg_pnl = sum(pnls) / n if n else 0.0

    recs: List[Dict[str, Any]] = []
    if win_rate < 0.45:
        recs.append(
            {
                "key": "max_trades_per_day",
                "current": current_risk.get("max_trades_per_day"),
                "suggested": max(1, int(current_risk.get("max_trades_per_day") or 3) - 1),
                "why": "\uc2b9\ub960 \uc800\ud558 \uad6c\uac04: \uacfc\ub9e4\ub9e4 \uc644\ud654",
            }
        )
    if avg_pnl > 0 and win_rate >= 0.5:
        cur_tp = float(current_risk.get("take_profit_ratio") or 0.0)
        recs.append(
            {
                "key": "take_profit_ratio",
                "current": cur_tp,
                "suggested": round(cur_tp + 0.001, 4),
                "why": "\ud3c9\uade0 \uc190\uc775 \uc591\ud638: \uc775\uc808\ud3c9 \uc18c\ud3c9 \ud655\ub300",
            }
        )
    cur_be = float(current_risk.get("sideways_be_buffer_ratio") or 0.0)
    if cur_be < 0.003:
        recs.append(
            {
                "key": "sideways_be_buffer_ratio",
                "current": cur_be,
                "suggested": 0.0035,
                "why": "\uc2e4\uac70\ub798 \ube44\uc6a9 \ubc18\uc601: \ubcf8\uc804 \uccad\uc0b0 \ubc84\ud37c \uc0c1\ud5a5",
            }
        )

    summary = f"\ucd5c\uadfc \ub9e4\ub3c4 {n}\uac74, \uc2b9\ub960 {win_rate*100:.1f}%, \ud3c9\uade0\uc190\uc775 {avg_pnl:,.0f}\uc6d0"
    return {"available": True, "summary": summary, "recommendations": recs}
