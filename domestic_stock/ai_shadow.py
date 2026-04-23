# -*- coding: utf-8 -*-
"""AI Shadow helpers (non-invasive): scores and hints only; no order/exit decisions."""

from typing import Any, Dict, List, Optional


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
