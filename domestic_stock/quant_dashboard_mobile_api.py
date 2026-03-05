"""
API 엔드포인트 모듈 (모바일 대시보드용)

기존 quant_dashboard.py의 API를 인증 의존성과 함께 제공
"""

from fastapi import Depends, HTTPException, WebSocket, WebSocketDisconnect, Query, Body
from fastapi.responses import JSONResponse
from typing import Dict, List, Optional
from datetime import datetime, time as dtime, timedelta, timezone
import logging
import asyncio
import threading
import uuid
import time
import os

import kis_auth as ka
from domestic_stock_functions_ws import ccnl_krx, asking_price_krx

from quant_dashboard_mobile import (
    app, state, get_current_user,
    RiskConfig, StockSelectionConfig, StrategyConfig, OperationalConfig, ManualOrder
)
from stock_selector import StockSelector
from stock_selection_presets import get_preset, list_presets
from quant_trading_safe import safe_execute_order

logger = logging.getLogger(__name__)
pending_signals_lock = threading.Lock()
DEFAULT_STOCK_INFO = [
    {"code": "005930", "name": "삼성전자"},
    {"code": "000660", "name": "SK하이닉스"},
]

_user_settings_store = None
_user_settings_store_init_error: Optional[str] = None
_signal_skip_log_last_at: Dict[str, float] = {}
_signal_skip_log_lock = threading.Lock()
_skip_stats_lock = threading.Lock()


def _to_int(v, default: int = 0) -> int:
    try:
        if v is None:
            return default
        s = str(v).strip().replace(",", "")
        if s == "":
            return default
        return int(float(s))
    except Exception:
        return default


def _to_float(v, default: float = 0.0) -> float:
    try:
        if v is None:
            return default
        s = str(v).strip().replace(",", "")
        if s == "":
            return default
        return float(s)
    except Exception:
        return default


def _pick_first(row: dict, keys: list):
    for k in keys:
        if k in row and row.get(k) not in (None, "", " "):
            return row.get(k)
    return None


def _extract_exec_from_ccld_df(df, fallback_qty: int, fallback_px: float) -> dict:
    """체결조회 output1에서 체결수량/가격을 최대한 안전하게 추정."""
    try:
        if df is None or getattr(df, "empty", True):
            return {"qty": int(fallback_qty or 0), "px": float(fallback_px or 0.0), "fields": {}}
        row = {}
        try:
            row = df.iloc[0].to_dict()
        except Exception:
            row = {}

        qty_raw = _pick_first(row, [
            "CCLD_QTY", "ccld_qty",
            "TOT_CCLD_QTY", "tot_ccld_qty",
            "CCLD_QTY_TOT", "ccld_qty_tot",
            "ORD_QTY", "ord_qty",
        ])
        px_raw = _pick_first(row, [
            "CCLD_UNPR", "ccld_unpr",
            "CCLD_PRC", "ccld_prc",
            "AVG_PRC", "avg_prc",
            "AVG_UNPR", "avg_unpr",
            "ORD_UNPR", "ord_unpr",
        ])
        qty = _to_int(qty_raw, int(fallback_qty or 0))
        px = _to_float(px_raw, float(fallback_px or 0.0))
        if qty <= 0:
            qty = int(fallback_qty or 0)
        if px <= 0:
            px = float(fallback_px or 0.0)
        return {"qty": int(qty), "px": float(px), "fields": row, "columns": list(df.columns)}
    except Exception:
        return {"qty": int(fallback_qty or 0), "px": float(fallback_px or 0.0), "fields": {}}


def _reconcile_pending_orders_sync(max_per_run: int = 5, min_check_interval_sec: float = 2.0) -> List[dict]:
    """
    pending 주문을 조회해 체결되었으면 포지션/거래내역 반영 이벤트를 생성.
    - 실제 I/O(inquire_daily_ccld) 포함: asyncio.to_thread로 호출되어야 함
    """
    events: List[dict] = []
    try:
        if not getattr(state, "is_running", False):
            return events
        if not getattr(state, "risk_manager", None) or not getattr(state, "trenv", None):
            return events

        rm = state.risk_manager
        trenv = state.trenv
        lock = getattr(rm, "_lock", None)

        pending = getattr(rm, "_pending_orders", None)
        if not isinstance(pending, dict) or not pending:
            return events

        if lock:
            with lock:
                if hasattr(rm, "_prune_pending_orders"):
                    rm._prune_pending_orders()
                keys_snapshot = sorted(list(pending.keys()))
        else:
            try:
                if hasattr(rm, "_prune_pending_orders"):
                    rm._prune_pending_orders()
            except Exception:
                pass
            keys_snapshot = sorted(list(pending.keys()))

        if not keys_snapshot:
            return events

        from domestic_stock_functions import inquire_daily_ccld

        tz = timezone(timedelta(hours=9))
        today = datetime.now(tz).strftime("%Y%m%d")
        cano = getattr(trenv, "my_acct", "") or ""
        acnt_prdt_cd = getattr(trenv, "my_prod", "") or ""
        if not cano or not acnt_prdt_cd:
            return events

        now_ts = time.time()
        checked = 0

        for key in keys_snapshot:
            if checked >= int(max_per_run or 0):
                break
            if lock:
                with lock:
                    item = dict(pending.get(key) or {})
            else:
                item = dict(pending.get(key) or {})
            if not item:
                continue
            stock_code = str(item.get("stock_code") or "").strip().zfill(6)
            side = str(item.get("side") or "").strip().lower()
            env_dv = str(item.get("env_dv") or ("demo" if getattr(state, "is_paper_trading", True) else "real"))
            qty_fallback = _to_int(item.get("quantity"), 0)
            px_fallback = _to_float(item.get("price"), 0.0)
            odno_orig_empty = not str(item.get("odno") or "").strip()
            odno = str(item.get("odno") or "").strip()
            if not stock_code or side not in ("buy", "sell"):
                continue

            try:
                last_chk = float(item.get("last_check_ts") or 0.0)
            except Exception:
                last_chk = 0.0
            if last_chk and (now_ts - last_chk) < float(min_check_interval_sec):
                continue

            try:
                item["last_check_ts"] = now_ts
                item["checks"] = int(item.get("checks") or 0) + 1
                if lock:
                    with lock:
                        pending[key] = item
                else:
                    pending[key] = item
            except Exception:
                pass

            sll_buy = "02" if side == "buy" else "01"

            # ODNO가 없으면 우선 미체결 조회에서 ODNO를 확보 시도 (가능하면)
            if not odno:
                try:
                    df_unf, _ = inquire_daily_ccld(
                        env_dv=env_dv,
                        pd_dv="inner",
                        cano=cano,
                        acnt_prdt_cd=acnt_prdt_cd,
                        inqr_strt_dt=today,
                        inqr_end_dt=today,
                        sll_buy_dvsn_cd=sll_buy,
                        ccld_dvsn="02",
                        inqr_dvsn="00",
                        inqr_dvsn_3="00",
                        pdno=stock_code,
                        odno="",
                    )
                    if df_unf is not None and getattr(df_unf, "empty", True) is False:
                        try:
                            row = df_unf.iloc[0].to_dict()
                            odno2 = str(row.get("ODNO") or row.get("odno") or "").strip()
                            if odno2:
                                odno = odno2
                                item["odno"] = odno2
                                if lock:
                                    with lock:
                                        pending[key] = item
                                else:
                                    pending[key] = item
                        except Exception:
                            pass
                except Exception:
                    pass

            # 체결 조회(ODNO 있으면 정확도↑)
            try:
                df_filled, _ = inquire_daily_ccld(
                    env_dv=env_dv,
                    pd_dv="inner",
                    cano=cano,
                    acnt_prdt_cd=acnt_prdt_cd,
                    inqr_strt_dt=today,
                    inqr_end_dt=today,
                    sll_buy_dvsn_cd=sll_buy,
                    ccld_dvsn="01",
                    inqr_dvsn="00",
                    inqr_dvsn_3="00",
                    pdno=stock_code,
                    odno=odno,
                )
            except Exception:
                df_filled = None

            if df_filled is None or getattr(df_filled, "empty", True):
                checked += 1
                continue

            exec_info = _extract_exec_from_ccld_df(df_filled, fallback_qty=qty_fallback, fallback_px=px_fallback)
            exec_qty = int(exec_info.get("qty") or 0)
            exec_px = float(exec_info.get("px") or 0.0)

            if exec_qty <= 0 or exec_px <= 0:
                checked += 1
                continue

            # ODNO 없이 접수된 pending: 동일 종목 다건 혼동 방지 — 수량·가격 일치 검증
            if odno_orig_empty:
                if exec_qty != qty_fallback:
                    checked += 1
                    continue
                if px_fallback > 0 and abs(exec_px - px_fallback) / px_fallback > 0.05:
                    checked += 1
                    continue

            # 포지션 반영
            pnl = None
            try:
                if side == "buy":
                    if stock_code in getattr(rm, "positions", {}):
                        # 이미 반영된 케이스면 pending만 제거
                        pass
                    else:
                        rm.update_position(stock_code, exec_px, exec_qty, "buy")
                else:
                    if stock_code in getattr(rm, "positions", {}):
                        pnl = rm.update_position(stock_code, exec_px, exec_qty, "sell")
                    else:
                        # 포지션이 없으면 반영 불가: pending만 제거하지 않고 유지(운영자가 확인)
                        checked += 1
                        continue
            except Exception:
                checked += 1
                continue

            # pending clear
            try:
                if hasattr(rm, "clear_pending_order"):
                    rm.clear_pending_order(stock_code, side=side)
                else:
                    pending.pop(key, None)
            except Exception:
                pending.pop(key, None)

            events.append({
                "kind": "pending_filled",
                "stock_code": stock_code,
                "side": side,
                "qty": exec_qty,
                "px": exec_px,
                "pnl": pnl,
                "env_dv": env_dv,
                "odno": odno,
            })
            checked += 1

        return events
    except Exception:
        return events


def _check_balance_vs_positions_sync() -> Optional[str]:
    """잔고 조회와 risk_manager.positions 비교, 불일치 시 경고 문구 반환. asyncio.to_thread로 호출."""
    try:
        if not getattr(state, "is_running", False):
            return None
        rm = getattr(state, "risk_manager", None)
        trenv = getattr(state, "trenv", None)
        if not rm or not trenv:
            return None
        from domestic_stock_functions import inquire_balance
        env_dv = "demo" if getattr(state, "is_paper_trading", True) else "real"
        cano = getattr(trenv, "my_acct", "") or ""
        acnt_prdt_cd = getattr(trenv, "my_prod", "") or ""
        if not cano or not acnt_prdt_cd:
            return None
        df1, _ = inquire_balance(
            env_dv=env_dv,
            cano=cano,
            acnt_prdt_cd=acnt_prdt_cd,
            afhr_flpr_yn="N",
            inqr_dvsn="01",
            unpr_dvsn="01",
            fund_sttl_icld_yn="N",
            fncg_amt_auto_rdpt_yn="N",
            prcs_dvsn="00",
        )
        if df1 is None or getattr(df1, "empty", True):
            pos_codes = set(getattr(rm, "positions", {}).keys())
            if pos_codes:
                return f"포지션 vs 잔고 불일치 가능: 잔고 조회 0건, 시스템 포지션 {len(pos_codes)}건"
            return None
        codes_from_balance = set()
        for _, row in df1.iterrows():
            code = str(row.get("PDNO") or row.get("pdno") or row.get("MKSC_SHRN_ISCD") or "").strip().zfill(6)
            if code:
                qty = _to_int(row.get("HOLD_QTY") or row.get("hold_qty") or row.get("ORD_PSBL_QTY"), 0)
                if qty > 0:
                    codes_from_balance.add(code)
        pos_codes = set(getattr(rm, "positions", {}).keys())
        only_balance = codes_from_balance - pos_codes
        only_pos = pos_codes - codes_from_balance
        if only_balance or only_pos:
            return (
                f"포지션 vs 잔고 불일치: 잔고만 있음 {sorted(only_balance)[:5]}{'…' if len(only_balance) > 5 else ''} "
                f"/ 포지션만 있음 {sorted(only_pos)[:5]}{'…' if len(only_pos) > 5 else ''}"
            )
        return None
    except Exception as e:
        return f"잔고 비교 오류: {e}"


def _run_auto_rebalance_sync() -> tuple:
    """종목 재선정 실행(동기). 반환: (selected_codes 리스트, selected_info 리스트) 또는 ([], []) 실패 시."""
    try:
        sel = getattr(state, "stock_selector", None)
        if not sel:
            return ([], [])
        selected = sel.select_stocks_by_fluctuation()
        if not selected:
            return ([], [])
        info = getattr(sel, "last_selected_stock_info", None) or [{"code": c, "name": c} for c in selected]
        return (selected, info)
    except Exception as e:
        logger.warning(f"자동 리밸런싱(종목 재선정) 오류: {e}")
        return ([], [])


async def _pending_order_reconciler_loop():
    """시스템 구동 중 pending 주문을 주기적으로 체결 확인하여 반영."""
    try:
        interval = float(getattr(state, "pending_order_reconcile_interval_sec", 3.0) or 3.0)
    except Exception:
        interval = 3.0
    interval = max(1.0, min(10.0, interval))
    max_per_run = int(getattr(state, "pending_order_reconcile_max_per_run", 5) or 5)
    max_per_run = max(1, min(20, max_per_run))
    last_balance_check_ts = time.time()
    last_rebalance_ts = 0.0
    last_recommend_ts = 0.0
    BALANCE_CHECK_INTERVAL_SEC = 60.0

    while True:
        try:
            if not getattr(state, "is_running", False):
                break

            now_ts = time.time()

            # 자동 리밸런싱(종목 주기 재선정): 설정 시 N분마다 재선정, 목록 갱신(다음 시작 시 적용)
            enable_rebal = bool(getattr(state, "enable_auto_rebalance", False))
            rebal_min = int(getattr(state, "auto_rebalance_interval_minutes", 30) or 30)
            rebal_min = max(5, min(120, rebal_min))
            if enable_rebal and (now_ts - last_rebalance_ts) >= (rebal_min * 60.0):
                last_rebalance_ts = now_ts
                try:
                    selected_codes, selected_info = await asyncio.to_thread(_run_auto_rebalance_sync)
                    if selected_codes:
                        state.selected_stocks = selected_codes
                        state.selected_stock_info = selected_info
                        await state.broadcast({"type": "log", "level": "info", "message": f"자동 리밸런싱: 종목 {len(selected_codes)}개 갱신됨. 변경 사항은 다음 시스템 시작 시 적용됩니다."})
                        await state.broadcast({"type": "selected_stocks", "data": {"codes": selected_codes, "info": selected_info}})
                except Exception as e:
                    logger.warning(f"자동 리밸런싱 오류(무시): {e}")

            # 성과 기반 자동 추천: 설정 시 N분마다 권장 문구를 로그로 브로드캐스트
            enable_rec = bool(getattr(state, "enable_performance_auto_recommend", False))
            rec_min = int(getattr(state, "performance_recommend_interval_minutes", 5) or 5)
            rec_min = max(1, min(60, rec_min))
            if enable_rec and (now_ts - last_recommend_ts) >= (rec_min * 60.0):
                last_recommend_ts = now_ts
                try:
                    summary = _performance_summary_from_trades()
                    recs = summary.get("recommendations") or []
                    if recs:
                        for r in recs:
                            await state.broadcast({"type": "log", "level": r.get("level", "info"), "message": f"[성과 추천] {r.get('message', '')}"})
                except Exception as e:
                    logger.warning(f"성과 추천 오류(무시): {e}")

            events = await asyncio.to_thread(
                _reconcile_pending_orders_sync,
                max_per_run,
                2.0,
            )
            if events:
                for ev in events:
                    try:
                        side = str(ev.get("side") or "").lower()
                        code = str(ev.get("stock_code") or "").strip().zfill(6)
                        qty = int(ev.get("qty") or 0)
                        px = float(ev.get("px") or 0.0)
                        odno = str(ev.get("odno") or "").strip()
                        env_dv = str(ev.get("env_dv") or "-")
                        pnl = ev.get("pnl")

                        await state.broadcast({
                            "type": "log",
                            "level": "info",
                            "message": f"주문 체결 확인 | {side.upper()} {code} qty={qty} px={px:,.0f} env={env_dv} odno={odno or '-'}",
                        })

                        trade_info = {
                            "stock_code": code,
                            "order_type": side,
                            "quantity": qty,
                            "price": px,
                            "pnl": pnl,
                        }
                        state.add_trade(trade_info)
                        await state.broadcast({"type": "trade", "data": trade_info})
                        await state.broadcast({"type": "position", "data": _build_positions_message()})
                        await send_status_update()
                    except Exception:
                        continue

            # 포지션 vs 잔고 불일치 주기 점검(60초 간격)
            now_ts = time.time()
            if now_ts - last_balance_check_ts >= BALANCE_CHECK_INTERVAL_SEC:
                last_balance_check_ts = now_ts
                try:
                    msg = await asyncio.to_thread(_check_balance_vs_positions_sync)
                    if msg:
                        await state.broadcast({"type": "log", "level": "warning", "message": msg})
                except Exception:
                    pass

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.warning(f"pending 주문 reconcile 오류(무시): {e}")

        await asyncio.sleep(interval)


def _record_buy_skip(stock_code: str, reason_key: str):
    """BUY 스킵 통계 누적(스레드 안전)."""
    try:
        code = str(stock_code or "").strip().zfill(6)
        key = str(reason_key or "").strip() or "unknown"
        with _skip_stats_lock:
            if not hasattr(state, "buy_skip_stats") or not isinstance(getattr(state, "buy_skip_stats", None), dict):
                state.buy_skip_stats = {"total": 0, "by_reason": {}, "by_stock": {}, "by_reason_stock": {}}
            stats = state.buy_skip_stats
            stats["total"] = int(stats.get("total") or 0) + 1
            by_reason = stats.setdefault("by_reason", {})
            by_reason[key] = int(by_reason.get(key) or 0) + 1
            if code:
                by_stock = stats.setdefault("by_stock", {})
                by_stock[code] = int(by_stock.get(code) or 0) + 1
                brs = stats.setdefault("by_reason_stock", {})
                rs = brs.setdefault(key, {})
                rs[code] = int(rs.get(code) or 0) + 1

                # 무한 성장 방지(대략적인 상한)
                if len(by_stock) > 2000:
                    for c in list(by_stock.keys())[:200]:
                        by_stock.pop(c, None)
                if len(rs) > 500:
                    for c in list(rs.keys())[:100]:
                        rs.pop(c, None)
    except Exception:
        return


def _get_buy_skip_stats_summary(top_n: int = 5) -> dict:
    """대시보드 표시에 적합한 요약만 반환."""
    try:
        with _skip_stats_lock:
            stats = getattr(state, "buy_skip_stats", None)
            if not isinstance(stats, dict):
                return {"total": 0, "by_reason": [], "top_stocks": []}
            total = int(stats.get("total") or 0)
            by_reason = stats.get("by_reason") or {}
            by_stock = stats.get("by_stock") or {}

        reason_list = sorted(
            [(k, int(v or 0)) for k, v in by_reason.items()],
            key=lambda x: x[1],
            reverse=True,
        )[: max(1, int(top_n))]

        stock_list = sorted(
            [(k, int(v or 0)) for k, v in by_stock.items()],
            key=lambda x: x[1],
            reverse=True,
        )[: max(1, int(top_n))]

        return {
            "total": total,
            "by_reason": [{"key": k, "count": c} for k, c in reason_list],
            "top_stocks": [{"code": k, "count": c} for k, c in stock_list],
        }
    except Exception:
        return {"total": 0, "by_reason": [], "top_stocks": []}


def _throttled_skip_log(stock_code: str, reason: str, *, ttl_sec: int = 30):
    """엔진 스레드에서 buy 스킵 사유를 과도하게 찍지 않도록 throttling."""
    try:
        key = f"{stock_code}:{reason}"
        now_ts = time.time()
        with _signal_skip_log_lock:
            last = float(_signal_skip_log_last_at.get(key) or 0.0)
            if now_ts - last < float(ttl_sec):
                return
            _signal_skip_log_last_at[key] = now_ts
        _run_async_broadcast({
            "type": "log",
            "level": "info",
            "message": f"BUY 스킵 | {stock_code} | {reason}",
        })
    except Exception:
        return


def _apply_risk_config_dict_to_state(d: dict) -> None:
    """DB에서 불러온 risk_config 딕셔너리를 state.risk_manager에 반영 (폼·DB·실행값 일치)."""
    if not d or not getattr(state, "risk_manager", None):
        return
    rm = state.risk_manager
    try:
        if "max_single_trade_amount" in d:
            rm.max_single_trade_amount = int(d["max_single_trade_amount"])
        if "min_order_quantity" in d:
            rm.min_order_quantity = max(1, int(d.get("min_order_quantity") or 1))
        if "stop_loss_ratio" in d:
            rm.stop_loss_ratio = float(d["stop_loss_ratio"])
        if "take_profit_ratio" in d:
            rm.take_profit_ratio = float(d["take_profit_ratio"])
        if "daily_loss_limit" in d:
            rm.daily_loss_limit = int(d["daily_loss_limit"])
        if "daily_profit_limit" in d:
            rm.daily_profit_limit = int(d.get("daily_profit_limit") or 0)
        if "daily_total_loss_limit" in d:
            rm.daily_total_loss_limit = int(d.get("daily_total_loss_limit") or 0)
        if "daily_profit_limit_basis" in d:
            rm.daily_profit_limit_basis = str(d.get("daily_profit_limit_basis") or "total")
        if "daily_loss_limit_basis" in d:
            rm.daily_loss_limit_basis = str(d.get("daily_loss_limit_basis") or "realized")
        if "buy_order_style" in d:
            rm.buy_order_style = str(d.get("buy_order_style") or "market")
        if "sell_order_style" in d:
            rm.sell_order_style = str(d.get("sell_order_style") or "market")
        if "order_retry_count" in d:
            rm.order_retry_count = int(d.get("order_retry_count") or 0)
        if "order_retry_delay_ms" in d:
            rm.order_retry_delay_ms = int(d.get("order_retry_delay_ms") or 300)
        if "order_fallback_to_market" in d:
            rm.order_fallback_to_market = bool(d.get("order_fallback_to_market", True))
        if "enable_volatility_sizing" in d:
            rm.enable_volatility_sizing = bool(d.get("enable_volatility_sizing", False))
        if "volatility_lookback_ticks" in d:
            rm.volatility_lookback_ticks = int(d.get("volatility_lookback_ticks") or 20)
        if "volatility_stop_mult" in d:
            rm.volatility_stop_mult = float(d.get("volatility_stop_mult") or 1.0)
        if "max_loss_per_stock_krw" in d:
            rm.max_loss_per_stock_krw = int(d.get("max_loss_per_stock_krw") or 0)
        if "slippage_bps" in d:
            rm.slippage_bps = max(0, min(500, int(d.get("slippage_bps") or 0)))
        if "volatility_floor_ratio" in d:
            rm.volatility_floor_ratio = max(0.0, min(0.05, float(d.get("volatility_floor_ratio") or 0.005)))
        if "trailing_stop_ratio" in d:
            rm.trailing_stop_ratio = float(d.get("trailing_stop_ratio") or 0.0)
        if "trailing_activation_ratio" in d:
            rm.trailing_activation_ratio = float(d.get("trailing_activation_ratio") or 0.0)
        if "partial_take_profit_ratio" in d:
            rm.partial_take_profit_ratio = float(d.get("partial_take_profit_ratio") or 0.0)
        if "partial_take_profit_fraction" in d:
            rm.partial_take_profit_fraction = float(d.get("partial_take_profit_fraction") or 0.5)
        if "max_trades_per_day" in d:
            rm.max_trades_per_day = int(d.get("max_trades_per_day") or 5)
        if "max_position_size_ratio" in d:
            rm.max_position_size_ratio = float(d.get("max_position_size_ratio") or 0.1)
    except Exception as e:
        logger.warning(f"저장된 리스크 설정 적용 중 오류(무시): {e}")


def _apply_operational_config_dict_to_state(d: dict) -> None:
    """DB에서 불러온 operational_config를 state에 반영."""
    if not d:
        return
    try:
        if "enable_auto_rebalance" in d:
            state.enable_auto_rebalance = bool(d.get("enable_auto_rebalance", False))
        if "auto_rebalance_interval_minutes" in d:
            state.auto_rebalance_interval_minutes = max(5, min(120, int(d.get("auto_rebalance_interval_minutes") or 30)))
        if "enable_performance_auto_recommend" in d:
            state.enable_performance_auto_recommend = bool(d.get("enable_performance_auto_recommend", False))
        if "performance_recommend_interval_minutes" in d:
            state.performance_recommend_interval_minutes = max(1, min(60, int(d.get("performance_recommend_interval_minutes") or 5)))
    except Exception as e:
        logger.warning(f"저장된 운영 옵션 적용 중 오류(무시): {e}")


def _get_user_settings_store():
    global _user_settings_store
    global _user_settings_store_init_error
    if _user_settings_store is not None:
        return _user_settings_store
    try:
        from user_settings_store import DynamoDBUserSettingsStore

        _user_settings_store = DynamoDBUserSettingsStore()
        try:
            _user_settings_store_init_error = getattr(_user_settings_store, "init_error", None)
        except Exception:
            _user_settings_store_init_error = None
    except Exception as e:
        logger.warning(f"User settings store init failed: {e}")
        _user_settings_store = None
        _user_settings_store_init_error = str(e)
    return _user_settings_store


@app.get("/api/config/user-settings/store-status")
async def get_user_settings_store_status(current_user: str = Depends(get_current_user)):
    """DynamoDB 유저 설정 저장소 상태 진단용. 비활성화 시 원인(init_error)과 설정 방법 안내 포함."""
    store = _get_user_settings_store()
    if store and hasattr(store, "status"):
        try:
            st = store.status()
            if not st.get("enabled"):
                st["hint"] = (
                    "설정 저장을 쓰려면: (1) .env에 AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY 설정 또는 aws configure 실행, "
                    "(2) USER_SETTINGS_TABLE_NAME(또는 DYNAMODB_TABLE_NAME) 테이블이 해당 리전에 존재하는지 확인. "
                    "테이블 없으면 AWS 콘솔에서 생성(파티션 키 username 문자열) 또는 USER_SETTINGS_AUTO_CREATE_TABLE=true 로 자동 생성."
                )
            return JSONResponse({"success": True, "store": st})
        except Exception as e:
            return JSONResponse({"success": False, "message": str(e), "store": {"enabled": False, "init_error": str(e)}})
    return JSONResponse({
        "success": True,
        "store": {
            "enabled": False,
            "init_error": _user_settings_store_init_error or "저장소 초기화 실패",
            "hint": ".env에 AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_DEFAULT_REGION(예: ap-northeast-2) 설정 후 서버 재시작.",
        }
    })


def _format_order_log(details: dict) -> str:
    try:
        signal = str(details.get("signal", "")).upper()
        stock_code = str(details.get("stock_code", "")).strip()
        qty = details.get("quantity", "-")
        price = details.get("price", "-")
        env_dv = details.get("env_dv", "-")
        ok = bool(details.get("ok", False))
        filled = bool(details.get("filled", False))
        status = str(details.get("status", "") or "").strip().lower()

        resp = details.get("order_response") or {}
        fields = resp.get("fields") or {}
        odno = fields.get("ODNO") or fields.get("odno") or "-"
        ord_tmd = fields.get("ORD_TMD") or fields.get("ord_tmd") or "-"
        msg = fields.get("MSG1") or fields.get("msg1") or fields.get("message") or ""
        msg_cd = fields.get("MSG_CD") or fields.get("msg_cd") or ""
        rt_cd = fields.get("RT_CD") or fields.get("rt_cd") or ""

        if status == "accepted_pending" and ok and not filled:
            verdict = "접수(대기)"
        elif filled and ok:
            verdict = "체결"
        else:
            verdict = "실패"

        base = f"주문 {verdict} | {signal} {stock_code} qty={qty} px={price} env={env_dv}"
        tail = f" | odno={odno} t={ord_tmd}"
        if rt_cd or msg_cd or msg:
            tail += f" | rt_cd={rt_cd} msg_cd={msg_cd} msg={msg}"
        return base + tail
    except Exception:
        return f"주문 결과(details 파싱 실패): {details}"


def _env_bool(key: str, default: bool) -> bool:
    raw = os.getenv(key)
    if raw is None:
        return default
    v = str(raw).strip().lower()
    if v in {"1", "true", "t", "yes", "y", "on"}:
        return True
    if v in {"0", "false", "f", "no", "n", "off"}:
        return False
    return default


def _env_float(key: str, default: float) -> float:
    raw = os.getenv(key)
    if raw is None:
        return default
    try:
        return float(str(raw).strip())
    except Exception:
        return default


def _ensure_initialized() -> bool:
    """Start 버튼에서 lazy-init."""
    if state.strategy and state.trenv and state.risk_manager:
        return True

    account_balance = _env_float("ACCOUNT_BALANCE", 100000.0)
    is_paper = _env_bool("IS_PAPER_TRADING", getattr(state, "is_paper_trading", True))
    return bool(initialize_trading_system(account_balance=account_balance, is_paper_trading=is_paper))


def _run_async_broadcast(message: dict):
    """스레드 컨텍스트에서 안전하게 브로드캐스트."""
    try:
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(state.broadcast(message))
        except RuntimeError:
            asyncio.run(state.broadcast(message))
    except Exception as e:
        logger.error(f"브로드캐스트 오류: {e}")


def _to_float(value, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        text = str(value).replace(",", "").strip()
        if text == "":
            return default
        return float(text)
    except Exception:
        return default


def _to_int_money(value, default: int = 0) -> int:
    try:
        if value is None:
            return default
        text = str(value).replace(",", "").strip()
        if text == "":
            return default
        return int(float(text))
    except Exception:
        return default


def _extract_kis_account_balance(output2: dict) -> int:
    """
    KIS 계좌/잔고조회 output2에서 대표 잔고(예수금/총평가 등) 값을 추출.
    키가 환경/버전에 따라 다를 수 있어 후보 키 우선순위 + 휴리스틱으로 처리.
    """
    if not isinstance(output2, dict):
        return 0

    candidates = [
        "dnca_tot_amt",
        "dnca_tot_amt1",
        "tot_evlu_amt",
        "nass_amt",
        "prvs_rcdl_excc_amt",
    ]
    for k in candidates:
        if k in output2:
            v = _to_int_money(output2.get(k), 0)
            if v > 0:
                return v

    best = 0
    for k, v in output2.items():
        key = str(k).lower()
        if not any(tok in key for tok in ("dnca", "amt", "money", "cash", "evlu", "nass")):
            continue
        iv = _to_int_money(v, 0)
        if iv > best:
            best = iv
    return best


def _refresh_kis_account_balance_sync() -> int:
    """동기 컨텍스트에서 KIS 계좌 잔고를 1회 조회하고 state/risk_manager에 반영."""
    try:
        if not getattr(state, "trenv", None):
            return 0
        trenv = state.trenv
        cano = getattr(trenv, "my_acct", "") or ""
        acnt_prdt_cd = getattr(trenv, "my_prod", "") or ""
        if not cano or not acnt_prdt_cd:
            return 0

        # 모의/실전별 TR_ID가 다른 API를 사용 (주식잔고조회)
        from domestic_stock_functions import inquire_balance

        env_dv = "demo" if getattr(state, "is_paper_trading", True) else "real"
        _, df2 = inquire_balance(
            env_dv=env_dv,
            cano=cano,
            acnt_prdt_cd=acnt_prdt_cd,
            afhr_flpr_yn="N",
            inqr_dvsn="01",
            unpr_dvsn="01",
            fund_sttl_icld_yn="N",
            fncg_amt_auto_rdpt_yn="N",
            prcs_dvsn="00",
        )
        if df2 is None or getattr(df2, "empty", True) is True:
            state.kis_account_balance_ok = False
            return 0

        output2 = {}
        try:
            output2 = df2.iloc[0].to_dict()
        except Exception:
            output2 = {}

        bal = _extract_kis_account_balance(output2)
        # KIS 조회 성공이면 0도 유효한 값으로 취급 (0일 때 fallback 방지)
        state.kis_account_balance_ok = True
        state.kis_account_balance = int(bal or 0)
        state.kis_account_balance_at = time.time()
        if getattr(state, "risk_manager", None):
            state.risk_manager.account_balance = float(state.kis_account_balance)
        return bal
    except Exception as e:
        logger.warning(f"KIS 잔고 조회 실패(무시): {e}")
        state.kis_account_balance_ok = False
        return 0


async def _refresh_kis_account_balance(force: bool = False, ttl_sec: int = 60) -> int:
    """비동기 컨텍스트에서 TTL 기반으로 KIS 잔고를 갱신."""
    try:
        now = time.time()
        last_at = float(getattr(state, "kis_account_balance_at", 0) or 0)
        if not force and last_at and (now - last_at) < ttl_sec:
            return int(getattr(state, "kis_account_balance", 0) or 0)

        if not getattr(state, "trenv", None):
            return 0

        bal = await asyncio.to_thread(_refresh_kis_account_balance_sync)
        return int(bal or 0)
    except Exception as e:
        logger.warning(f"KIS 잔고 갱신 실패(무시): {e}")
        return int(getattr(state, "kis_account_balance", 0) or 0)


def _get_display_account_balance() -> int:
    """대시보드에 표시할 계좌 잔고 결정 (KIS 성공값 우선, 실패 시에만 fallback)."""
    if getattr(state, "kis_account_balance_ok", False) and hasattr(state, "kis_account_balance_at"):
        return int(getattr(state, "kis_account_balance", 0) or 0)
    if getattr(state, "risk_manager", None):
        return int(getattr(state.risk_manager, "account_balance", 0) or 0)
    return 0


def _print_tick_summary(row):
    """시세 수신 로그를 필요한 필드만 간결하게 출력."""
    stock_code = str(row.get("MKSC_SHRN_ISCD", "")).strip().zfill(6)
    price = _to_float(row.get("STCK_PRPR", 0))
    diff = _to_float(row.get("PRDY_VRSS", row.get("PRDY_CTRT", 0)))
    volume = _to_float(row.get("CNTG_VOL", row.get("ACML_VOL", 0)))

    if not stock_code or price <= 0:
        return

    now_str = datetime.now().strftime("%H:%M:%S")
    print(
        f"[{now_str}] [{stock_code}] 체결가 {price:,.0f} | 대비 {diff:+,.0f} | 거래량 {volume:,.0f}"
    )


def _print_signal_decision(stock_code: str, current_price: float):
    """시그널 의사결정 근거를 한 줄로 출력."""
    if not state.strategy or not state.risk_manager:
        return

    prices = state.strategy.price_history.get(stock_code, [])
    history_len = len(prices)
    short_ma = state.strategy.calculate_ma(stock_code, state.strategy.short_ma_period)
    long_ma = state.strategy.calculate_ma(stock_code, state.strategy.long_ma_period)

    has_position = stock_code in state.risk_manager.positions
    pnl_ratio_text = "-"
    if has_position:
        buy_price = state.risk_manager.positions[stock_code]["buy_price"]
        pnl_ratio = ((current_price - buy_price) / buy_price) * 100 if buy_price else 0.0
        pnl_ratio_text = f"{pnl_ratio:+.2f}%"

    final_signal = "-"
    if short_ma is not None and long_ma is not None:
        if short_ma > long_ma and current_price > short_ma and not has_position:
            final_signal = "BUY"
        elif short_ma < long_ma and has_position:
            final_signal = "SELL"

    short_text = f"{short_ma:,.2f}" if short_ma is not None else "NA"
    long_text = f"{long_ma:,.2f}" if long_ma is not None else "NA"
    now_str = datetime.now().strftime("%H:%M:%S")

    print(
        f"[{now_str}] [{stock_code}] SIGNAL | px={current_price:,.0f} | h={history_len} "
        f"| sMA={short_text} | lMA={long_text} | pos={has_position} | pnl={pnl_ratio_text} | out={final_signal}"
    )


def _build_pending_signal(stock_code: str, signal: str, price: float, reason: str, suggested_qty_override: Optional[int] = None) -> dict:
    signal_id = f"sig_{datetime.now().strftime('%Y%m%d%H%M%S')}_{stock_code}_{uuid.uuid4().hex[:6]}"
    now = datetime.now()
    suggested_qty = 0
    if suggested_qty_override is not None:
        try:
            suggested_qty = int(suggested_qty_override)
        except Exception:
            suggested_qty = 0
    if suggested_qty <= 0:
        if signal == "buy" and state.risk_manager:
            suggested_qty = state.risk_manager.calculate_quantity(price)
        elif signal == "sell" and state.risk_manager and stock_code in state.risk_manager.positions:
            suggested_qty = int(state.risk_manager.positions[stock_code].get("quantity") or 0)

    stock_name = ""
    try:
        for item in (getattr(state, "selected_stock_info", []) or []):
            if str(item.get("code", "")).strip().zfill(6) == str(stock_code).strip().zfill(6):
                stock_name = str(item.get("name", "")).strip()
                break
    except Exception:
        stock_name = ""

    return {
        "signal_id": signal_id,
        "stock_code": stock_code,
        "stock_name": stock_name,
        "signal": signal,
        "price": price,
        "suggested_qty": suggested_qty,
        "reason": reason,
        "created_at": now.isoformat(),
        "expires_at": (now.timestamp() + 60),
        "status": "pending",
    }


def _create_or_replace_pending_signal(signal_data: dict) -> Optional[dict]:
    """동일 종목/방향의 기존 신호를 교체하고 신규 신호 저장."""
    with pending_signals_lock:
        expired_keys = []
        now_ts = time.time()
        for key, data in state.pending_signals.items():
            if data.get("status") != "pending" or data.get("expires_at", 0) < now_ts:
                expired_keys.append(key)
        for key in expired_keys:
            state.pending_signals.pop(key, None)

        for key, data in list(state.pending_signals.items()):
            if (
                data.get("status") == "pending"
                and data.get("stock_code") == signal_data["stock_code"]
                and data.get("signal") == signal_data["signal"]
            ):
                state.pending_signals.pop(key, None)

        state.pending_signals[signal_data["signal_id"]] = signal_data
        return signal_data


def _build_positions_message():
    """리스크 매니저 포지션을 브로드캐스트용 dict로 변환"""
    if not state.risk_manager:
        return {}
    positions = {}
    for code, pos in state.risk_manager.positions.items():
        positions[code] = {
            "quantity": pos["quantity"],
            "buy_price": pos["buy_price"],
            "current_price": pos.get("current_price", pos["buy_price"]),
            "buy_time": pos["buy_time"].isoformat() if isinstance(pos.get("buy_time"), datetime) else str(pos.get("buy_time", ""))
        }
    return positions


def _handle_signal(stock_code: str, signal: str, price: float, reason: str, suggested_qty_override: Optional[int] = None):
    """신호 처리: 수동 모드면 승인대기 등록, 자동 모드면 즉시 주문 실행"""
    manual = getattr(state, "manual_approval", True)
    if manual:
        sig = _build_pending_signal(stock_code=stock_code, signal=signal, price=price, reason=reason, suggested_qty_override=suggested_qty_override)
        created = _create_or_replace_pending_signal(sig)
        if created:
            _run_async_broadcast({"type": "signal_pending", "data": created})
        return

    result, details = safe_execute_order(
        signal=signal,
        stock_code=stock_code,
        price=price,
        strategy=state.strategy,
        trenv=state.trenv,
        is_paper_trading=state.is_paper_trading,
        manual_approval=False,
        return_details=True,
        quantity_override=suggested_qty_override,
    )
    if not result:
        _run_async_broadcast({"type": "log", "message": _format_order_log(details), "level": "error"})
        return

    filled = bool(details.get("filled", False))
    level = "info" if filled else "warning"
    _run_async_broadcast({"type": "log", "message": _format_order_log(details), "level": level})
    if not filled:
        # 주문 접수는 되었으나 체결 미확정/미체결 상태면, 포지션/거래내역 반영은 보류
        return
    # 부분매도(부분익절 등) 체결 시: 잔여 수량을 함께 로깅
    try:
        if signal == "sell" and state.risk_manager and stock_code in getattr(state.risk_manager, "positions", {}):
            remain = int(state.risk_manager.positions[stock_code].get("quantity") or 0)
            sold = 0
            try:
                sold = int(details.get("quantity") or 0)
            except Exception:
                sold = 0
            if remain > 0 and sold > 0:
                _run_async_broadcast({
                    "type": "log",
                    "level": "info",
                    "message": f"부분 매도 체결: {stock_code} sold={sold} remain={remain} ({reason})",
                })
    except Exception:
        pass
    suggested_qty = 0
    try:
        suggested_qty = int(details.get("quantity") or 0)
    except Exception:
        suggested_qty = 0
    trade_info = {
        "stock_code": stock_code,
        "order_type": signal,
        "quantity": suggested_qty,
        "price": price,
        "pnl": None
    }
    state.add_trade(trade_info)
    _run_async_broadcast({"type": "trade", "data": trade_info})
    _run_async_broadcast({"type": "position", "data": _build_positions_message()})
    _run_async_broadcast({"type": "log", "message": f"자동 체결: {stock_code} {signal.upper()} {price:,.0f}원", "level": "info"})


def _start_trading_engine_thread():
    """실시간 체결 수신 -> 신호 생성 -> 승인 대기 등록."""
    if state.engine_running:
        return

    def _engine_runner():
        try:
            state.engine_running = True
            kws = ka.KISWebSocket(api_url="/tryitout")
            stocks = state.selected_stocks if state.selected_stocks else ["005930", "000660"]
            kws.subscribe(request=ccnl_krx, data=stocks)
            # 스프레드 필터를 위해 실시간 호가도 구독
            try:
                kws.subscribe(request=asking_price_krx, data=stocks, kwargs={"env_dv": "demo" if state.is_paper_trading else "real"})
            except Exception:
                pass

            def on_result(ws, tr_id, result, data_info):
                if not state.is_running or not state.strategy or not state.risk_manager:
                    return
                # 호가 TR: 스프레드 계산용 캐시 갱신
                if tr_id in ["H0STASP0", "H0NXASP0", "H0UNASP0"] and not result.empty:
                    try:
                        for _, row in result.iterrows():
                            code = str(row.get("MKSC_SHRN_ISCD", "")).strip().zfill(6)
                            ask = _to_float(row.get("ASKP1", 0))
                            bid = _to_float(row.get("BIDP1", 0))
                            if code and ask > 0 and bid > 0:
                                state.latest_quotes[code] = {
                                    "ask": float(ask),
                                    "bid": float(bid),
                                    "at": datetime.now().isoformat(),
                                }
                    except Exception:
                        pass
                    return

                if tr_id not in ["H0STCNT0", "H0STCNT1"] or result.empty:
                    return

                # 시간 기반 청산 (오늘 1회만)
                try:
                    if bool(getattr(state, "enable_time_liquidation", False)) and getattr(state.risk_manager, "positions", None):
                        tz = timezone(timedelta(hours=9))
                        now_dt = datetime.now(tz)
                        now_t = now_dt.time()
                        liq_hhmm = str(getattr(state, "liquidate_after_hhmm", "11:55") or "11:55")
                        liq_t = _parse_hhmm(liq_hhmm)
                        today_key = now_dt.strftime("%Y%m%d")
                        if liq_t and now_t >= liq_t:
                            if getattr(state, "_time_liquidation_done_day", "") != today_key:
                                state._time_liquidation_done_day = today_key
                                positions_snapshot = list(state.risk_manager.positions.items())
                                for code, pos in positions_snapshot:
                                    qty = int(pos.get("quantity", 0) or 0)
                                    if qty <= 0:
                                        continue
                                    px = float(state.risk_manager.last_prices.get(code, pos.get("buy_price", 0)) or pos.get("buy_price", 0) or 0)
                                    if px <= 0:
                                        px = float(pos.get("buy_price", 0) or 0)
                                    if px <= 0:
                                        continue
                                    _handle_signal(code, "sell", px, f"시간기반 청산({liq_hhmm} 이후)", suggested_qty_override=qty)
                except Exception:
                    pass

                # 일일 이익 한도 도달 시: 5초 디바운스 후 전량 매도/신규매수 차단 (flicker 방지)
                try:
                    rm = getattr(state, "risk_manager", None)
                    if rm and getattr(rm, "positions", None):
                        limit = int(getattr(rm, "daily_profit_limit", 0) or 0)
                        if limit and limit > 0:
                            tz = timezone(timedelta(hours=9))
                            now_dt = datetime.now(tz)
                            today_key = now_dt.strftime("%Y%m%d")
                            if getattr(state, "_profit_limit_done_day", "") != today_key:
                                realized = float(getattr(rm, "daily_pnl", 0.0) or 0.0)
                                total_if_liq = float(getattr(rm, "get_total_pnl", lambda: realized)() or realized)
                                basis = str(getattr(rm, "daily_profit_limit_basis", "total") or "total").strip().lower()
                                cur_pnl = total_if_liq if basis == "total" else realized
                                now_ts = time.time()
                                if cur_pnl >= float(limit):
                                    triggered_at = getattr(state, "_profit_limit_triggered_at", 0.0) or 0.0
                                    if triggered_at == 0.0:
                                        state._profit_limit_triggered_at = now_ts
                                    elif (now_ts - triggered_at) >= 5.0:
                                        state._profit_limit_done_day = today_key
                                        state._profit_limit_triggered_at = 0.0
                                        try:
                                            rm.halt_new_buys_day = today_key
                                            rm.halt_new_buys_reason = f"일일 이익 한도({limit:,}원) 도달"
                                        except Exception:
                                            pass
                                        if basis == "total":
                                            _run_async_broadcast({
                                                "type": "log",
                                                "level": "warning",
                                                "message": f"일일 이익 한도 도달(total): {cur_pnl:,.0f}원 >= {limit:,.0f}원 (전량 매도 신호 생성)",
                                            })
                                            for code, pos in list(rm.positions.items()):
                                                qty = int(pos.get("quantity", 0) or 0)
                                                if qty <= 0:
                                                    continue
                                                px = float(pos.get("current_price") or rm.last_prices.get(code) or pos.get("buy_price") or 0)
                                                if px <= 0:
                                                    continue
                                                _handle_signal(code, "sell", px, f"일일 이익 한도({limit:,}원) 도달", suggested_qty_override=qty)
                                        else:
                                            _run_async_broadcast({
                                                "type": "log",
                                                "level": "warning",
                                                "message": f"일일 이익 한도 도달(realized): {cur_pnl:,.0f}원 >= {limit:,.0f}원 (신규매수 차단)",
                                            })
                                else:
                                    state._profit_limit_triggered_at = 0.0
                except Exception:
                    pass

                # 일일 손실 한도(total basis) 도달 시: 5초 디바운스 후 전량 매도 + 신규매수 차단
                try:
                    rm = getattr(state, "risk_manager", None)
                    if rm and getattr(rm, "positions", None):
                        basis = str(getattr(rm, "daily_loss_limit_basis", "realized") or "realized").strip().lower()
                        limit = int(getattr(rm, "daily_loss_limit", 0) or 0) if basis == "total" else 0
                        if limit and limit > 0 and basis == "total":
                            tz = timezone(timedelta(hours=9))
                            now_dt = datetime.now(tz)
                            today_key = now_dt.strftime("%Y%m%d")
                            if getattr(state, "_loss_limit_total_done_day", "") != today_key:
                                realized = float(getattr(rm, "daily_pnl", 0.0) or 0.0)
                                total_if_liq = float(getattr(rm, "get_total_pnl", lambda: realized)() or realized)
                                now_ts = time.time()
                                if total_if_liq <= -float(limit):
                                    triggered_at = getattr(state, "_loss_limit_total_triggered_at", 0.0) or 0.0
                                    if triggered_at == 0.0:
                                        state._loss_limit_total_triggered_at = now_ts
                                    elif (now_ts - triggered_at) >= 5.0:
                                        state._loss_limit_total_done_day = today_key
                                        state._loss_limit_total_triggered_at = 0.0
                                        try:
                                            rm.halt_new_buys_day = today_key
                                            rm.halt_new_buys_reason = f"일일 손실 한도(total)({limit:,}원) 도달"
                                        except Exception:
                                            pass
                                        _run_async_broadcast({
                                            "type": "log",
                                            "level": "error",
                                            "message": f"일일 손실 한도(total) 도달: {total_if_liq:,.0f}원 <= -{limit:,.0f}원 (전량 매도 신호 생성)",
                                        })
                                        for code, pos in list(rm.positions.items()):
                                            qty = int(pos.get("quantity", 0) or 0)
                                            if qty <= 0:
                                                continue
                                            px = float(pos.get("current_price") or rm.last_prices.get(code) or pos.get("buy_price") or 0)
                                            if px <= 0:
                                                continue
                                            _handle_signal(code, "sell", px, f"일일 손실 한도(total)({limit:,}원) 도달", suggested_qty_override=qty)
                                else:
                                    state._loss_limit_total_triggered_at = 0.0
                except Exception:
                    pass

                # (레거시) 일일 손실 한도(합산 전용 필드) 도달 시: 5초 디바운스 후 전량 매도 + 신규매수 차단
                try:
                    rm = getattr(state, "risk_manager", None)
                    if rm and getattr(rm, "positions", None):
                        limit = int(getattr(rm, "daily_total_loss_limit", 0) or 0)
                        basis = str(getattr(rm, "daily_loss_limit_basis", "realized") or "realized").strip().lower()
                        if basis == "total":
                            limit = 0
                        if limit and limit > 0:
                            tz = timezone(timedelta(hours=9))
                            now_dt = datetime.now(tz)
                            today_key = now_dt.strftime("%Y%m%d")
                            if getattr(state, "_total_loss_limit_done_day", "") != today_key:
                                realized = float(getattr(rm, "daily_pnl", 0.0) or 0.0)
                                total_if_liq = float(getattr(rm, "get_total_pnl", lambda: realized)() or realized)
                                now_ts = time.time()
                                if total_if_liq <= -float(limit):
                                    triggered_at = getattr(state, "_total_loss_limit_triggered_at", 0.0) or 0.0
                                    if triggered_at == 0.0:
                                        state._total_loss_limit_triggered_at = now_ts
                                    elif (now_ts - triggered_at) >= 5.0:
                                        state._total_loss_limit_done_day = today_key
                                        state._total_loss_limit_triggered_at = 0.0
                                        try:
                                            rm.halt_new_buys_day = today_key
                                            rm.halt_new_buys_reason = f"일일 손실 한도(합산)({limit:,}원) 도달"
                                        except Exception:
                                            pass
                                        _run_async_broadcast({
                                            "type": "log",
                                            "level": "error",
                                            "message": f"일일 손실 한도(합산) 도달: {total_if_liq:,.0f}원 <= -{limit:,.0f}원 (전량 매도 신호 생성)",
                                        })
                                        for code, pos in list(rm.positions.items()):
                                            qty = int(pos.get("quantity", 0) or 0)
                                            if qty <= 0:
                                                continue
                                            px = float(pos.get("current_price") or rm.last_prices.get(code) or pos.get("buy_price") or 0)
                                            if px <= 0:
                                                continue
                                            _handle_signal(code, "sell", px, f"일일 손실 한도(합산)({limit:,}원) 도달", suggested_qty_override=qty)
                                else:
                                    state._total_loss_limit_triggered_at = 0.0
                except Exception:
                    pass

                for _, row in result.iterrows():
                    try:
                        _print_tick_summary(row)
                        stock_code = str(row.get("MKSC_SHRN_ISCD", "")).strip().zfill(6)
                        current_price = float(row.get("STCK_PRPR", 0))
                        if not stock_code or current_price <= 0:
                            continue

                        # 오전장 레짐(초반/메인) 판별 (KST)
                        early_regime = False
                        try:
                            if bool(getattr(state, "enable_morning_regime_split", False)):
                                tz = timezone(timedelta(hours=9))
                                now_t = datetime.now(tz).time()
                                end_hhmm = str(getattr(state, "morning_regime_early_end_hhmm", "09:10") or "09:10")
                                end_t = _parse_hhmm(end_hhmm)
                                start_t = _parse_hhmm("09:00")
                                if start_t and end_t and start_t <= now_t < end_t:
                                    early_regime = True
                        except Exception:
                            early_regime = False

                        def _eff_float(key: str, default: float) -> float:
                            try:
                                if early_regime:
                                    return float(getattr(state, f"early_{key}", getattr(state, key, default)) or 0.0)
                                return float(getattr(state, key, default) or 0.0)
                            except Exception:
                                try:
                                    return float(getattr(state, key, default) or 0.0)
                                except Exception:
                                    return float(default or 0.0)

                        def _eff_int(key: str, default: int) -> int:
                            try:
                                if early_regime:
                                    v = int(getattr(state, f"early_{key}", getattr(state, key, default)) or 0)
                                    return int(v)
                                return int(getattr(state, key, default) or 0)
                            except Exception:
                                try:
                                    return int(getattr(state, key, default) or 0)
                                except Exception:
                                    return int(default or 0)

                        def _avg_abs_diff_ratio(prices: list, lookback: int, cur_px: float) -> float:
                            try:
                                if cur_px <= 0:
                                    return 0.0
                                n = int(lookback or 0)
                                n = max(2, min(300, n))
                                if len(prices) < n + 1:
                                    return 0.0
                                window = prices[-(n + 1):]
                                diffs = []
                                for i in range(1, len(window)):
                                    diffs.append(abs(float(window[i]) - float(window[i - 1])))
                                if not diffs:
                                    return 0.0
                                avg_abs = float(sum(diffs) / float(len(diffs)))
                                return float(avg_abs / float(cur_px))
                            except Exception:
                                return 0.0

                        state.risk_manager.update_price(stock_code, current_price)
                        state.strategy.update_price(stock_code, current_price)
                        _print_signal_decision(stock_code, current_price)

                        # 1~2분봉 추세 유지/고점 근접 회피를 위해 간단 분봉(1분) 생성
                        try:
                            now_ts = time.time()
                            cur_min = int(now_ts // 60)
                            if not hasattr(state, "_minute_bars"):
                                state._minute_bars = {}
                            bars = state._minute_bars.get(stock_code) or []
                            if not bars or int(bars[-1].get("m", -1)) != cur_min:
                                bars.append({"m": cur_min, "o": float(current_price), "h": float(current_price), "l": float(current_price), "c": float(current_price)})
                            else:
                                b = bars[-1]
                                b["h"] = float(max(float(b.get("h", current_price)), float(current_price)))
                                b["l"] = float(min(float(b.get("l", current_price)), float(current_price)))
                                b["c"] = float(current_price)
                            # 최근 120분까지만 유지
                            if len(bars) > 120:
                                bars = bars[-120:]
                            state._minute_bars[stock_code] = bars
                        except Exception:
                            pass

                        exit_sig = None
                        try:
                            if hasattr(state.risk_manager, "check_exit_signal"):
                                exit_sig = state.risk_manager.check_exit_signal(stock_code, current_price)
                        except Exception:
                            exit_sig = None
                        if exit_sig and exit_sig.get("action") == "sell":
                            qty = int(exit_sig.get("quantity") or 0)
                            reason = str(exit_sig.get("reason") or "리스크 조건 충족")
                            _handle_signal(stock_code, "sell", current_price, reason, suggested_qty_override=qty)
                            continue

                        short_ma = state.strategy.calculate_ma(stock_code, state.strategy.short_ma_period)
                        long_ma = state.strategy.calculate_ma(stock_code, state.strategy.long_ma_period)
                        signal_type = None
                        if (
                            stock_code in state.strategy.price_history
                            and len(state.strategy.price_history[stock_code]) >= state.strategy.min_history_length
                            and short_ma is not None
                            and long_ma is not None
                        ):
                            if short_ma > long_ma and current_price > short_ma and stock_code not in state.risk_manager.positions:
                                # (0) 스프레드 필터: 호가 스프레드가 너무 크면 매수 스킵
                                try:
                                    max_spread = float(_eff_float("max_spread_ratio", 0.0) or 0.0)
                                    if max_spread > 0:
                                        q = (getattr(state, "latest_quotes", {}) or {}).get(stock_code) or {}
                                        ask = float(q.get("ask") or 0)
                                        bid = float(q.get("bid") or 0)
                                        if ask > 0 and bid > 0 and current_price > 0:
                                            spread_ratio = (ask - bid) / float(current_price)
                                            if spread_ratio > max_spread:
                                                _record_buy_skip(stock_code, "spread")
                                                _throttled_skip_log(
                                                    stock_code,
                                                    f"스프레드 과대({spread_ratio*100:.3f}% > {max_spread*100:.3f}%)",
                                                )
                                                continue
                                except Exception:
                                    pass

                                # (0-1) 횡보장(레인지) 필터: 최근 N틱 박스권이면 매수 스킵
                                try:
                                    lookback = int(_eff_int("range_lookback_ticks", 0) or 0)
                                    min_range = float(_eff_float("min_range_ratio", 0.0) or 0.0)
                                    if lookback > 0 and min_range > 0:
                                        prices = (state.strategy.price_history.get(stock_code) or [])
                                        if len(prices) >= lookback:
                                            window = prices[-lookback:]
                                            hi = float(max(window))
                                            lo = float(min(window))
                                            if current_price > 0:
                                                rr = (hi - lo) / float(current_price)
                                                # 변동성 정규화(보조): avgAbsDiff/current_price 비율에 비례한 최소 레인지 추가
                                                vol_lb = int(getattr(state, "vol_norm_lookback_ticks", 20) or 20)
                                                vol_ratio = _avg_abs_diff_ratio(prices, vol_lb, current_price)
                                                mult = float(getattr(state, "range_vs_vol_mult", 0.0) or 0.0)
                                                thr = float(min_range)
                                                if mult and mult > 0 and vol_ratio > 0:
                                                    thr = max(thr, float(mult) * float(vol_ratio))
                                                if rr < thr:
                                                    _record_buy_skip(stock_code, "range")
                                                    _throttled_skip_log(
                                                        stock_code,
                                                        f"횡보장 제외(range {rr*100:.3f}% < {thr*100:.3f}%, N={lookback})",
                                                    )
                                                    continue
                                except Exception:
                                    pass

                                # (1) 재진입 쿨다운: 직전 매도 직후 재매수 방지
                                try:
                                    if getattr(state, "reentry_cooldown_seconds", 0) and getattr(state.risk_manager, "is_in_reentry_cooldown", None):
                                        if state.risk_manager.is_in_reentry_cooldown(stock_code):
                                            _record_buy_skip(stock_code, "cooldown")
                                            _throttled_skip_log(stock_code, f"쿨다운({getattr(state, 'reentry_cooldown_seconds', 0)}s)")
                                            continue
                                except Exception:
                                    pass

                                # (2) 추세 강도: 단기 MA 기울기(직전 대비)가 일정 이상일 때만 buy
                                try:
                                    min_slope = float(_eff_float("min_short_ma_slope_ratio", 0.0) or 0.0)
                                    if min_slope > 0 and hasattr(state.strategy, "calculate_ma_offset"):
                                        prev_short = state.strategy.calculate_ma_offset(stock_code, state.strategy.short_ma_period, offset=1)
                                        if prev_short is not None and current_price > 0:
                                            slope_ratio = (float(short_ma) - float(prev_short)) / float(current_price)
                                            # 변동성 정규화(보조): slope가 평균 변동폭 대비 충분히 커야 함
                                            prices = (state.strategy.price_history.get(stock_code) or [])
                                            vol_lb = int(getattr(state, "vol_norm_lookback_ticks", 20) or 20)
                                            vol_ratio = _avg_abs_diff_ratio(prices, vol_lb, current_price)
                                            mult = float(getattr(state, "slope_vs_vol_mult", 0.0) or 0.0)
                                            thr = float(min_slope)
                                            if mult and mult > 0 and vol_ratio > 0:
                                                thr = max(thr, float(mult) * float(vol_ratio))
                                            if slope_ratio < thr:
                                                _record_buy_skip(stock_code, "slope")
                                                _throttled_skip_log(
                                                    stock_code,
                                                    f"단기MA 기울기 부족({slope_ratio*100:.3f}%/tick < {thr*100:.3f}%/tick)",
                                                )
                                                continue
                                except Exception:
                                    pass

                                # (2-1) 모멘텀 필터: 최근 N틱 전 대비 상승률이 일정 이상일 때만 buy
                                try:
                                    mom_n = int(_eff_int("momentum_lookback_ticks", 0) or 0)
                                    mom_r = float(_eff_float("min_momentum_ratio", 0.0) or 0.0)
                                    if mom_n > 0 and mom_r > 0:
                                        prices = (state.strategy.price_history.get(stock_code) or [])
                                        if len(prices) > mom_n:
                                            prev_px = float(prices[-mom_n - 1])
                                            if prev_px > 0:
                                                mr = (float(current_price) - prev_px) / prev_px
                                                if mr < mom_r:
                                                    _record_buy_skip(stock_code, "momentum")
                                                    _throttled_skip_log(
                                                        stock_code,
                                                        f"모멘텀 부족({mr*100:.3f}% < {mom_r*100:.3f}%, N={mom_n})",
                                                    )
                                                    continue
                                        else:
                                            _record_buy_skip(stock_code, "momentum")
                                            _throttled_skip_log(stock_code, f"모멘텀 히스토리 부족(N={mom_n})", ttl_sec=20)
                                            continue
                                except Exception:
                                    pass

                                # (2-1-1) 진입 직전 추가 필터: 고점 근접(피크 추격) 회피
                                try:
                                    if bool(getattr(state, "avoid_chase_near_high_enabled", False)):
                                        mins = int(getattr(state, "near_high_lookback_minutes", 2) or 2)
                                        mins = max(1, min(30, mins))
                                        r = float(getattr(state, "avoid_near_high_ratio", 0.003) or 0.003)
                                        r = max(0.0, min(0.05, r))
                                        # 변동성 기반 동적 임계값(기본 r 보다 더 크게)
                                        try:
                                            if bool(getattr(state, "avoid_near_high_dynamic", False)):
                                                prices = (state.strategy.price_history.get(stock_code) or [])
                                                vol_lb = int(getattr(state, "vol_norm_lookback_ticks", 20) or 20)
                                                vol_ratio = _avg_abs_diff_ratio(prices, vol_lb, current_price)
                                                mult = float(getattr(state, "avoid_near_high_vs_vol_mult", 0.0) or 0.0)
                                                if mult and mult > 0 and vol_ratio > 0:
                                                    r = max(r, float(mult) * float(vol_ratio))
                                                    r = max(0.0, min(0.05, r))
                                        except Exception:
                                            pass
                                        bars = (getattr(state, "_minute_bars", {}) or {}).get(stock_code) or []
                                        if bars:
                                            cur_min = int(time.time() // 60)
                                            window = [b for b in bars if int(b.get("m", -1)) >= cur_min - mins]
                                            if window:
                                                hi = max(float(b.get("h", 0.0) or 0.0) for b in window)
                                                if hi > 0:
                                                    near = (hi - float(current_price)) / float(hi)
                                                    if near < r:
                                                        _record_buy_skip(stock_code, "near_high")
                                                        _throttled_skip_log(stock_code, f"고점 근접 추격 회피({near*100:.2f}% < {r*100:.2f}%/{mins}m)", ttl_sec=10)
                                                        continue
                                except Exception:
                                    pass

                                # (2-1-2) 진입 직전 추가 필터: 1~2분봉 추세 유지
                                try:
                                    if bool(getattr(state, "minute_trend_enabled", False)):
                                        # 레짐 초반에만 적용 옵션
                                        apply_now = True
                                        try:
                                            if bool(getattr(state, "minute_trend_early_only", False)) and not early_regime:
                                                apply_now = False
                                        except Exception:
                                            apply_now = True

                                        if apply_now:
                                            mode = str(getattr(state, "minute_trend_mode", "green") or "green").strip().lower()
                                            n = int(getattr(state, "minute_trend_lookback_bars", 2) or 2)
                                            n = max(1, min(5, n))
                                            min_green = int(getattr(state, "minute_trend_min_green_bars", 2) or 2)
                                            min_green = max(0, min(n, min_green))
                                            bars = (getattr(state, "_minute_bars", {}) or {}).get(stock_code) or []

                                            if len(bars) < n:
                                                _record_buy_skip(stock_code, "minute_trend")
                                                _throttled_skip_log(stock_code, f"분봉 히스토리 부족(N={n})", ttl_sec=20)
                                                continue

                                            last = bars[-n:]
                                            if mode == "higher_close":
                                                ok = True
                                                prev_c = None
                                                for b in last:
                                                    c = float(b.get("c", 0.0) or 0.0)
                                                    if prev_c is not None and c < prev_c:
                                                        ok = False
                                                        break
                                                    prev_c = c
                                                if not ok:
                                                    _record_buy_skip(stock_code, "minute_trend")
                                                    _throttled_skip_log(stock_code, f"분봉 추세 유지 실패(higher_close, N={n})", ttl_sec=10)
                                                    continue
                                            elif mode == "higher_low":
                                                ok = True
                                                prev_l = None
                                                for b in last:
                                                    l = float(b.get("l", 0.0) or 0.0)
                                                    if prev_l is not None and l < prev_l:
                                                        ok = False
                                                        break
                                                    prev_l = l
                                                if not ok:
                                                    _record_buy_skip(stock_code, "minute_trend")
                                                    _throttled_skip_log(stock_code, f"분봉 추세 유지 실패(higher_low, N={n})", ttl_sec=10)
                                                    continue
                                            elif mode == "hh_hl":
                                                ok = True
                                                prev_h = None
                                                prev_l = None
                                                for b in last:
                                                    h = float(b.get("h", 0.0) or 0.0)
                                                    l = float(b.get("l", 0.0) or 0.0)
                                                    if prev_h is not None and h < prev_h:
                                                        ok = False
                                                        break
                                                    if prev_l is not None and l < prev_l:
                                                        ok = False
                                                        break
                                                    prev_h = h
                                                    prev_l = l
                                                if not ok:
                                                    _record_buy_skip(stock_code, "minute_trend")
                                                    _throttled_skip_log(stock_code, f"분봉 추세 유지 실패(hh_hl, N={n})", ttl_sec=10)
                                                    continue
                                            else:
                                                green = 0
                                                for b in last:
                                                    o = float(b.get("o", 0.0) or 0.0)
                                                    c = float(b.get("c", 0.0) or 0.0)
                                                    if c >= o and o > 0 and c > 0:
                                                        green += 1
                                                if green < min_green:
                                                    _record_buy_skip(stock_code, "minute_trend")
                                                    _throttled_skip_log(stock_code, f"분봉 추세 유지 실패(green {green}/{n} < {min_green})", ttl_sec=10)
                                                    continue
                                except Exception:
                                    pass

                                # (2-2) 진입 보강(2단): 추세 조건 + (보강조건 N개 이상) 만족 필요
                                try:
                                    if bool(getattr(state, "entry_confirm_enabled", False)):
                                        need = int(getattr(state, "entry_confirm_min_count", 1) or 1)
                                        need = max(1, min(3, need))
                                        prices = (state.strategy.price_history.get(stock_code) or [])

                                        hit = 0
                                        hits = []

                                        # (a) 신고가(최근 N틱 고점) 돌파
                                        if bool(getattr(state, "confirm_breakout_enabled", False)):
                                            n = int(getattr(state, "breakout_lookback_ticks", 20) or 20)
                                            n = max(2, min(300, n))
                                            buf = float(getattr(state, "breakout_buffer_ratio", 0.0) or 0.0)
                                            if len(prices) > n:
                                                prev_window = prices[-n-1:-1]
                                                hi = float(max(prev_window)) if prev_window else 0.0
                                                ok = (hi > 0 and float(current_price) >= hi * (1.0 + float(buf)))
                                                if ok:
                                                    hit += 1
                                                    hits.append("breakout")

                                        # (b) 거래량 급증 (틱 체결량 기준)
                                        vol_tick = None
                                        try:
                                            if row.get("CNTG_VOL") is not None:
                                                vol_tick = float(row.get("CNTG_VOL") or 0.0)
                                            elif row.get("ACML_VOL") is not None:
                                                cur_acml = float(row.get("ACML_VOL") or 0.0)
                                                if not hasattr(state, "_acml_vol_last"):
                                                    state._acml_vol_last = {}
                                                prev_acml = float((state._acml_vol_last.get(stock_code) or 0.0))
                                                state._acml_vol_last[stock_code] = cur_acml
                                                dv = cur_acml - prev_acml
                                                vol_tick = float(dv) if dv >= 0 else 0.0
                                        except Exception:
                                            vol_tick = None

                                        if bool(getattr(state, "confirm_volume_surge_enabled", False)):
                                            n = int(getattr(state, "volume_surge_lookback_ticks", 20) or 20)
                                            n = max(2, min(200, n))
                                            ratio = float(getattr(state, "volume_surge_ratio", 2.0) or 2.0)
                                            if vol_tick is not None and vol_tick > 0:
                                                if not hasattr(state, "_vol_tick_hist"):
                                                    state._vol_tick_hist = {}
                                                h = state._vol_tick_hist.get(stock_code) or []
                                                avg = float(sum(h) / len(h)) if len(h) > 0 else 0.0
                                                ok = (avg > 0 and float(vol_tick) >= float(avg) * float(ratio))
                                                h.append(float(vol_tick))
                                                if len(h) > n:
                                                    h = h[-n:]
                                                state._vol_tick_hist[stock_code] = h
                                                if ok:
                                                    hit += 1
                                                    hits.append("vol_surge")

                                        # (c) 거래대금 급증 (틱 체결량 * 가격 기준)
                                        if bool(getattr(state, "confirm_trade_value_surge_enabled", False)):
                                            n = int(getattr(state, "trade_value_surge_lookback_ticks", 20) or 20)
                                            n = max(2, min(200, n))
                                            ratio = float(getattr(state, "trade_value_surge_ratio", 2.0) or 2.0)
                                            if vol_tick is not None and vol_tick > 0 and current_price > 0:
                                                tv_tick = float(vol_tick) * float(current_price)
                                                if not hasattr(state, "_tv_tick_hist"):
                                                    state._tv_tick_hist = {}
                                                h = state._tv_tick_hist.get(stock_code) or []
                                                avg = float(sum(h) / len(h)) if len(h) > 0 else 0.0
                                                ok = (avg > 0 and float(tv_tick) >= float(avg) * float(ratio))
                                                h.append(float(tv_tick))
                                                if len(h) > n:
                                                    h = h[-n:]
                                                state._tv_tick_hist[stock_code] = h
                                                if ok:
                                                    hit += 1
                                                    hits.append("tv_surge")

                                        if hit < need:
                                            _record_buy_skip(stock_code, "confirm2")
                                            _throttled_skip_log(
                                                stock_code,
                                                f"진입 보강 조건 미충족({hit}/{need}, hits={hits})",
                                                ttl_sec=10,
                                            )
                                            continue
                                except Exception:
                                    pass

                                # (3) 2틱 확인(confirmation): 조건이 연속으로 유지될 때만 진입
                                try:
                                    ticks = int(_eff_int("buy_confirm_ticks", 1) or 1)
                                    ticks = max(1, min(10, ticks))
                                    if not hasattr(state, "_buy_confirm_counts"):
                                        state._buy_confirm_counts = {}
                                    cnt = int(state._buy_confirm_counts.get(stock_code) or 0)
                                    cnt += 1
                                    state._buy_confirm_counts[stock_code] = cnt
                                    if cnt < ticks:
                                        _record_buy_skip(stock_code, "confirm")
                                        _throttled_skip_log(stock_code, f"진입확인 대기({cnt}/{ticks})", ttl_sec=10)
                                        continue
                                    state._buy_confirm_counts[stock_code] = 0
                                except Exception:
                                    pass

                                signal_type = "buy"
                            elif short_ma < long_ma and stock_code in state.risk_manager.positions:
                                signal_type = "sell"
                            else:
                                # buy 조건이 깨지면 confirm 카운트 리셋
                                try:
                                    if hasattr(state, "_buy_confirm_counts"):
                                        state._buy_confirm_counts[stock_code] = 0
                                except Exception:
                                    pass
                        if signal_type:
                            # 신규 매수 시간대 제한 (KST 기준). 매도는 항상 허용.
                            if signal_type == "buy":
                                # 잔고보다 현재가가 큰 종목은 매수 불가 -> 신호 감지에서 제외
                                try:
                                    balance = float(getattr(state.risk_manager, "account_balance", 0) or 0)
                                    if balance > 0 and current_price > balance:
                                        _record_buy_skip(stock_code, "balance")
                                        _throttled_skip_log(stock_code, f"잔고({balance:,.0f}원) 미만 현재가({current_price:,.0f}원) 제외", ttl_sec=10)
                                        continue
                                except Exception:
                                    pass
                                try:
                                    tz = timezone(timedelta(hours=9))
                                    now_t = datetime.now(tz).time()
                                    start_hhmm = getattr(state, "buy_window_start_hhmm", "09:05")
                                    end_hhmm = getattr(state, "buy_window_end_hhmm", "11:30")
                                    if not _is_within_window(now_t, start_hhmm, end_hhmm):
                                        _record_buy_skip(stock_code, "time_window")
                                        _throttled_skip_log(stock_code, f"신규매수 시간외({start_hhmm}-{end_hhmm})")
                                        continue
                                except Exception:
                                    pass
                            _handle_signal(stock_code, signal_type, current_price, "이동평균 크로스 조건 충족")
                    except Exception:
                        continue

            kws.start(on_result=on_result)
        except Exception as e:
            logger.error(f"트레이딩 엔진 오류: {e}")
            _run_async_broadcast({"type": "log", "message": f"트레이딩 엔진 오류: {e}", "level": "error"})
        finally:
            state.engine_running = False

    state.engine_thread = threading.Thread(target=_engine_runner, daemon=True)
    state.engine_thread.start()

# ============================================================================
# WebSocket
# ============================================================================

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket 연결"""
    await websocket.accept()
    state.websocket_clients.append(websocket)
    
    try:
        await send_status_update()
        with pending_signals_lock:
            pending_list = list(state.pending_signals.values())
        await websocket.send_json({"type": "signal_snapshot", "data": pending_list})
        while True:
            data = await websocket.receive_text()
    except WebSocketDisconnect:
        if websocket in state.websocket_clients:
            state.websocket_clients.remove(websocket)

async def send_status_update():
    """상태 업데이트 전송"""
    if state.risk_manager:
        await _refresh_kis_account_balance(force=False, ttl_sec=60)
        await state.broadcast({
            "type": "status",
            "data": {
                "is_running": state.is_running,
                "is_paper_trading": state.is_paper_trading,
                "manual_approval": getattr(state, "manual_approval", True),
                "env_name": "모의투자" if state.is_paper_trading else "실전투자",
                "account_balance": _get_display_account_balance(),
                "daily_pnl": state.risk_manager.daily_pnl,
                "daily_trades": state.risk_manager.daily_trades
                ,
                "buy_window_start_hhmm": getattr(state, "buy_window_start_hhmm", "09:05"),
                "buy_window_end_hhmm": getattr(state, "buy_window_end_hhmm", "11:30"),
                "buy_skip_stats": _get_buy_skip_stats_summary(top_n=5),
            }
        })
        
        positions = {}
        for code, pos in state.risk_manager.positions.items():
            positions[code] = {
                "quantity": pos["quantity"],
                "buy_price": pos["buy_price"],
                "current_price": pos.get("current_price", pos["buy_price"]),
                "buy_time": pos["buy_time"].isoformat() if isinstance(pos["buy_time"], datetime) else str(pos["buy_time"])
            }
        
        await state.broadcast({
            "type": "position",
            "data": positions
        })

# ============================================================================
# 시스템 API (인증 필요)
# ============================================================================

@app.get("/api/system/status")
async def get_system_status(current_user: str = Depends(get_current_user)):
    """시스템 상태 조회"""
    if not state.risk_manager:
        return JSONResponse({
            "is_running": False,
            "is_paper_trading": getattr(state, "is_paper_trading", True),
            "manual_approval": getattr(state, "manual_approval", True),
            "env_name": "-",
            "account_balance": 0,
            "daily_pnl": 0,
            "daily_trades": 0,
            "selected_stocks": getattr(state, "selected_stocks", []) or [],
            "selected_stock_info": getattr(state, "selected_stock_info", []) or [],
            "short_ma_period": state.strategy.short_ma_period if state.strategy else None,
            "long_ma_period": state.strategy.long_ma_period if state.strategy else None,
            "buy_window_start_hhmm": getattr(state, "buy_window_start_hhmm", "09:05"),
            "buy_window_end_hhmm": getattr(state, "buy_window_end_hhmm", "11:30"),
            "min_short_ma_slope_ratio": getattr(state, "min_short_ma_slope_ratio", 0.0),
            "momentum_lookback_ticks": getattr(state, "momentum_lookback_ticks", 0),
            "min_momentum_ratio": getattr(state, "min_momentum_ratio", 0.0),
            "reentry_cooldown_seconds": getattr(state, "reentry_cooldown_seconds", 0),
            "buy_confirm_ticks": getattr(state, "buy_confirm_ticks", 1),
            "enable_time_liquidation": getattr(state, "enable_time_liquidation", False),
            "liquidate_after_hhmm": getattr(state, "liquidate_after_hhmm", "11:55"),
            "max_spread_ratio": getattr(state, "max_spread_ratio", 0.0),
            "range_lookback_ticks": getattr(state, "range_lookback_ticks", 0),
            "min_range_ratio": getattr(state, "min_range_ratio", 0.0),
            "buy_skip_stats": _get_buy_skip_stats_summary(top_n=5),
            "enable_auto_rebalance": getattr(state, "enable_auto_rebalance", False),
            "auto_rebalance_interval_minutes": int(getattr(state, "auto_rebalance_interval_minutes", 30) or 30),
            "enable_performance_auto_recommend": getattr(state, "enable_performance_auto_recommend", False),
            "performance_recommend_interval_minutes": int(getattr(state, "performance_recommend_interval_minutes", 5) or 5),
        })
    
    await _refresh_kis_account_balance(force=False, ttl_sec=60)
    return JSONResponse({
        "is_running": state.is_running,
        "is_paper_trading": state.is_paper_trading,
        "manual_approval": getattr(state, "manual_approval", True),
        "env_name": "모의투자" if state.is_paper_trading else "실전투자",
        "account_balance": _get_display_account_balance(),
        "daily_pnl": state.risk_manager.daily_pnl,
        "daily_trades": state.risk_manager.daily_trades,
        "selected_stocks": state.selected_stocks,
        "selected_stock_info": getattr(state, "selected_stock_info", []),
        "short_ma_period": state.strategy.short_ma_period if state.strategy else None,
        "long_ma_period": state.strategy.long_ma_period if state.strategy else None,
        "buy_window_start_hhmm": getattr(state, "buy_window_start_hhmm", "09:05"),
        "buy_window_end_hhmm": getattr(state, "buy_window_end_hhmm", "11:30"),
        "min_short_ma_slope_ratio": getattr(state, "min_short_ma_slope_ratio", 0.0),
        "momentum_lookback_ticks": getattr(state, "momentum_lookback_ticks", 0),
        "min_momentum_ratio": getattr(state, "min_momentum_ratio", 0.0),
        "reentry_cooldown_seconds": getattr(state, "reentry_cooldown_seconds", 0),
        "buy_confirm_ticks": getattr(state, "buy_confirm_ticks", 1),
        "enable_time_liquidation": getattr(state, "enable_time_liquidation", False),
        "liquidate_after_hhmm": getattr(state, "liquidate_after_hhmm", "11:55"),
        "max_spread_ratio": getattr(state, "max_spread_ratio", 0.0),
        "range_lookback_ticks": getattr(state, "range_lookback_ticks", 0),
        "min_range_ratio": getattr(state, "min_range_ratio", 0.0),
        "buy_skip_stats": _get_buy_skip_stats_summary(top_n=5),
        "enable_auto_rebalance": getattr(state, "enable_auto_rebalance", False),
        "auto_rebalance_interval_minutes": int(getattr(state, "auto_rebalance_interval_minutes", 30) or 30),
        "enable_performance_auto_recommend": getattr(state, "enable_performance_auto_recommend", False),
        "performance_recommend_interval_minutes": int(getattr(state, "performance_recommend_interval_minutes", 5) or 5),
    })


def _parse_hhmm(text: str) -> Optional[dtime]:
    try:
        t = str(text or "").strip()
        if not t:
            return None
        hh, mm = t.split(":")
        return dtime(hour=int(hh), minute=int(mm))
    except Exception:
        return None


def _is_within_window(now_t: dtime, start_hhmm: str, end_hhmm: str) -> bool:
    start_t = _parse_hhmm(start_hhmm)
    end_t = _parse_hhmm(end_hhmm)
    if not start_t or not end_t:
        return True
    # 동일일 내 구간만 지원 (start <= end). 그렇지 않으면 always-true로 처리.
    if start_t <= end_t:
        return start_t <= now_t <= end_t
    return True


def _mask_account(text: str) -> str:
    t = str(text or "").strip()
    if len(t) <= 4:
        return t
    return f"{t[:2]}{'*' * (len(t) - 4)}{t[-2:]}"


@app.get("/api/account/status")
async def get_account_status(current_user: str = Depends(get_current_user)):
    """KIS 계좌 연결/조회가 실제로 되는지 1회성으로 확인 (인증 필요)."""
    try:
        if not state.strategy or not state.trenv or not state.risk_manager:
            ok = _ensure_initialized()
            if not ok or not state.trenv:
                detail = getattr(state, "last_init_error", None)
                msg = "시스템 초기화 실패: KIS 설정(.env/kis_devlp.yaml), 네트워크, 계정 설정을 확인하세요."
                if detail:
                    msg = f"{msg} (detail: {detail})"
                return JSONResponse({"success": False, "message": msg})

        trenv = state.trenv
        cano = getattr(trenv, "my_acct", "") or ""
        acnt_prdt_cd = getattr(trenv, "my_prod", "") or ""
        svr = "vps" if state.is_paper_trading else "prod"

        from domestic_stock_functions import inquire_balance
        env_dv = "demo" if state.is_paper_trading else "real"

        df1, df2 = await asyncio.to_thread(
            inquire_balance,
            env_dv=env_dv,
            cano=cano,
            acnt_prdt_cd=acnt_prdt_cd,
            afhr_flpr_yn="N",
            inqr_dvsn="01",
            unpr_dvsn="01",
            fund_sttl_icld_yn="N",
            fncg_amt_auto_rdpt_yn="N",
            prcs_dvsn="00",
        )

        output2 = {}
        if df2 is not None and getattr(df2, "empty", True) is False:
            try:
                output2 = df2.iloc[0].to_dict()
            except Exception:
                output2 = {}
        else:
            # 라이브러리 함수가 오류를 stdout으로만 찍는 케이스가 있어, 응답이 비면 실패로 처리
            return JSONResponse({
                "success": False,
                "message": "계좌 잔고 조회 실패(응답이 비어있음). 서버 로그의 KIS 에러 메시지를 확인하세요.",
                "svr": svr,
                "cano": _mask_account(cano),
                "acnt_prdt_cd": acnt_prdt_cd,
            })

        bal = _extract_kis_account_balance(output2)
        # KIS 조회 성공이면 0도 유효한 값으로 취급 (0일 때 fallback 방지)
        state.kis_account_balance_ok = True
        state.kis_account_balance = int(bal or 0)
        state.kis_account_balance_at = time.time()
        if getattr(state, "risk_manager", None):
            state.risk_manager.account_balance = float(state.kis_account_balance)

        return JSONResponse({
            "success": True,
            "svr": svr,
            "cano": _mask_account(cano),
            "acnt_prdt_cd": acnt_prdt_cd,
            "output1_rows": int(len(df1)) if df1 is not None else 0,
            "output2_keys": int(len(output2)),
            "output2": output2,
            "account_balance": bal,
        })
    except Exception as e:
        logger.error(f"계좌 상태 확인 오류: {e}")
        return JSONResponse({"success": False, "message": str(e)})

@app.post("/api/system/start")
async def start_system(current_user: str = Depends(get_current_user)):
    """시스템 시작"""
    try:
        if state.is_running:
            return JSONResponse({"success": False, "message": "이미 실행 중입니다."})

        if not state.strategy or not state.trenv or not state.risk_manager:
            ok = _ensure_initialized()
            if not ok or not state.strategy or not state.trenv or not state.risk_manager:
                detail = getattr(state, "last_init_error", None)
                msg = "시스템 초기화 실패: KIS 설정(.env/kis_devlp.yaml), 네트워크, 계정 설정을 확인하세요."
                if detail:
                    msg = f"{msg} (detail: {detail})"
                return JSONResponse({"success": False, "message": msg})

        # 시작 전 DB에 저장된 설정을 state에 반영 (리스크·운영 등이 DB와 일치하도록)
        store = _get_user_settings_store()
        if store and getattr(store, "enabled", False):
            try:
                saved = store.load(current_user) or {}
                _apply_risk_config_dict_to_state(saved.get("risk_config"))
                _apply_operational_config_dict_to_state(saved.get("operational_config"))
            except Exception as e:
                logger.warning(f"시작 시 저장 설정 적용 실패(무시): {e}")

        if not state.selected_stocks:
            state.selected_stocks = ["005930", "000660"]
        if not getattr(state, "selected_stock_info", None):
            state.selected_stock_info = DEFAULT_STOCK_INFO.copy()

        state.is_running = True
        _start_trading_engine_thread()
        # pending 주문 체결 확인 루프 시작(중복 방지)
        try:
            t = getattr(state, "pending_order_reconciler_task", None)
            if t is None or getattr(t, "done", lambda: True)():
                state.pending_order_reconciler_task = asyncio.create_task(_pending_order_reconciler_loop())
        except Exception:
            try:
                state.pending_order_reconciler_task = asyncio.create_task(_pending_order_reconciler_loop())
            except Exception:
                pass
        await send_status_update()

        return JSONResponse({"success": True, "message": f"시스템 시작 (감시 종목: {', '.join(state.selected_stocks)})"})
    except Exception as e:
        logger.error(f"시스템 시작 오류: {e}")
        return JSONResponse({"success": False, "message": str(e)})

@app.post("/api/system/set-env")
async def set_trading_env(
    body: dict = Body(...),
    current_user: str = Depends(get_current_user)
):
    """모의투자/실전투자 환경 전환 (시스템 중지 상태에서만 가능)"""
    is_paper_trading = body.get("is_paper_trading", True)
    if not isinstance(is_paper_trading, bool):
        is_paper_trading = str(is_paper_trading).lower() in ("true", "1", "yes")
    try:
        if state.is_running:
            return JSONResponse({
                "success": False,
                "message": "시스템을 중지한 후 투자 환경을 변경할 수 있습니다."
            })
        balance = float(getattr(state.risk_manager, "account_balance", 100000) if state.risk_manager else 100000)
        ok = initialize_trading_system(account_balance=balance, is_paper_trading=is_paper_trading)
        if not ok:
            detail = getattr(state, "last_init_error", None)
            msg = "환경 전환 실패: KIS 설정·네트워크·계정을 확인하세요."
            if detail:
                msg = f"{msg} ({detail})"
            return JSONResponse({"success": False, "message": msg})
        await send_status_update()
        env_label = "모의투자" if is_paper_trading else "실전투자"
        return JSONResponse({"success": True, "message": f"환경이 {env_label}(으)로 변경되었습니다.", "is_paper_trading": is_paper_trading})
    except Exception as e:
        logger.error(f"환경 전환 오류: {e}")
        return JSONResponse({"success": False, "message": str(e)})


@app.post("/api/system/set-trade-mode")
async def set_trade_mode(
    body: dict = Body(...),
    current_user: str = Depends(get_current_user)
):
    """매매 모드 전환: 수동(승인대기) / 자동(즉시 체결)"""
    try:
        manual_approval = body.get("manual_approval", True)
        if not isinstance(manual_approval, bool):
            manual_approval = str(manual_approval).lower() in ("true", "1", "yes")
        state.manual_approval = manual_approval
        await send_status_update()
        label = "수동(승인대기)" if manual_approval else "자동(즉시 체결)"
        return JSONResponse({"success": True, "message": f"매매 모드가 {label}(으)로 변경되었습니다.", "manual_approval": manual_approval})
    except Exception as e:
        logger.error(f"매매 모드 전환 오류: {e}")
        return JSONResponse({"success": False, "message": str(e)})


@app.post("/api/system/stop")
async def stop_system(
    liquidate: bool = Query(False),
    current_user: str = Depends(get_current_user)
):
    """시스템 중지"""
    try:
        state.is_running = False
        # pending 주문 reconcile 루프 중지
        try:
            t = getattr(state, "pending_order_reconciler_task", None)
            if t is not None and hasattr(t, "cancel"):
                t.cancel()
            state.pending_order_reconciler_task = None
        except Exception:
            pass
        with pending_signals_lock:
            state.pending_signals = {}
        # pending 주문도 초기화(재시작 시 매수/매도 막힘 방지)
        try:
            if getattr(state, "risk_manager", None) and hasattr(state.risk_manager, "_pending_orders"):
                state.risk_manager._pending_orders = {}
        except Exception:
            pass

        if liquidate and state.risk_manager and state.strategy and state.trenv:
            positions_snapshot = list(state.risk_manager.positions.items())
            await state.broadcast({
                "type": "log",
                "message": f"청산 시작: {len(positions_snapshot)}개 포지션",
                "level": "warning"
            })

            for code, pos in positions_snapshot:
                qty = int(pos.get("quantity", 0) or 0)
                if qty <= 0:
                    continue

                current_price = state.risk_manager.last_prices.get(code, pos.get("buy_price", 0)) if hasattr(state.risk_manager, "last_prices") else pos.get("buy_price", 0)
                if not current_price:
                    current_price = pos.get("buy_price", 0) or 0

                result = await asyncio.to_thread(
                    safe_execute_order,
                    "sell",
                    code,
                    float(current_price),
                    state.strategy,
                    state.trenv,
                    state.is_paper_trading,
                    False
                )

                if result:
                    pnl = None
                    try:
                        buy_price = float(pos.get("buy_price", 0) or 0)
                        pnl = (float(current_price) - buy_price) * qty
                    except Exception:
                        pnl = None

                    trade_info = {
                        "stock_code": code,
                        "order_type": "sell",
                        "quantity": qty,
                        "price": float(current_price) if current_price else 0,
                        "pnl": pnl
                    }
                    state.add_trade(trade_info)
                    await state.broadcast({"type": "trade", "data": trade_info})

            await state.broadcast({"type": "log", "message": "청산 완료", "level": "info"})

        await send_status_update()
        await state.broadcast({"type": "signal_snapshot", "data": []})
        return JSONResponse({"success": True, "message": "시스템이 중지되었습니다."})
    except Exception as e:
        logger.error(f"시스템 중지 오류: {e}")
        return JSONResponse({"success": False, "message": str(e)})

@app.get("/api/positions")
async def get_positions(current_user: str = Depends(get_current_user)):
    """현재 포지션 조회"""
    if not state.risk_manager:
        return JSONResponse([])
    
    positions = []
    for code, pos in state.risk_manager.positions.items():
        positions.append({
            "stock_code": code,
            "quantity": pos["quantity"],
            "buy_price": pos["buy_price"],
            "buy_time": pos["buy_time"].isoformat() if isinstance(pos["buy_time"], datetime) else str(pos["buy_time"])
        })
    
    return JSONResponse(positions)

@app.get("/api/trades")
async def get_trades(limit: int = 50, current_user: str = Depends(get_current_user)):
    """거래 내역 조회"""
    return JSONResponse(state.trade_history[-limit:])


def _performance_summary_from_trades() -> dict:
    """trade_history 기반 일일·세션 성과 및 권장 설정 추천."""
    tz = timezone(timedelta(hours=9))
    today_str = datetime.now(tz).strftime("%Y-%m-%d")
    history = getattr(state, "trade_history", []) or []
    today_trades = []
    for t in history:
        ts = t.get("timestamp") or ""
        if isinstance(ts, str) and ts.startswith(today_str):
            today_trades.append(t)
        elif isinstance(ts, str) and "T" in ts:
            try:
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone(timedelta(hours=9)))
                if dt.strftime("%Y-%m-%d") == today_str:
                    today_trades.append(t)
            except Exception:
                pass

    total_pnl = 0.0
    wins = 0
    losses = 0
    pnls = []
    for t in today_trades:
        pnl = t.get("pnl")
        if pnl is not None:
            try:
                v = float(pnl)
                total_pnl += v
                pnls.append(v)
                if v > 0:
                    wins += 1
                elif v < 0:
                    losses += 1
            except Exception:
                pass
    trade_count = len(pnls)
    win_rate = (wins / trade_count * 100.0) if trade_count else 0.0
    avg_win = (sum(p for p in pnls if p > 0) / wins) if wins else 0.0
    avg_loss = (sum(p for p in pnls if p < 0) / losses) if losses else 0.0

    # 세션 최대 낙폭: 시간순 누적 PnL에서 peak 대비 하락
    cumulative = 0.0
    peak = 0.0
    max_drawdown = 0.0
    for t in sorted(today_trades, key=lambda x: x.get("timestamp") or ""):
        pnl = t.get("pnl")
        if pnl is not None:
            try:
                cumulative += float(pnl)
                if cumulative > peak:
                    peak = cumulative
                dd = peak - cumulative
                if dd > max_drawdown:
                    max_drawdown = dd
            except Exception:
                pass
    balance_ref = float(getattr(state.risk_manager, "account_balance", 0) or 0) or 100000.0
    max_drawdown_pct = (max_drawdown / balance_ref * 100.0) if balance_ref else 0.0

    # 성과 기반 권장 설정
    recommendations = []
    if trade_count >= 3 and win_rate < 35.0:
        recommendations.append({
            "level": "warning",
            "message": "오늘 승률이 낮습니다. 손절 비율 강화 또는 진입 조건(보강/필터) 강화를 권장합니다.",
        })
    if trade_count >= 1 and max_drawdown_pct > 3.0:
        recommendations.append({
            "level": "warning",
            "message": f"세션 최대 낙폭이 {max_drawdown_pct:.1f}%입니다. 일일 손실 한도·포지션 크기를 확인하세요.",
        })
    consecutive = 0
    for p in reversed(pnls):
        if p < 0:
            consecutive += 1
        else:
            break
    if consecutive >= 3:
        recommendations.append({
            "level": "info",
            "message": "연속 손실이 발생했습니다. 재진입 쿨다운 확대 또는 변동성 사이징 검토를 권장합니다.",
        })
    if trade_count >= 5 and win_rate >= 60.0 and max_drawdown_pct < 1.0:
        recommendations.append({
            "level": "success",
            "message": "오늘 성과가 안정적입니다. 현재 설정 유지 또는 보수적 완화만 검토하세요.",
        })

    return {
        "date": today_str,
        "trade_count": trade_count,
        "wins": wins,
        "losses": losses,
        "total_pnl": round(total_pnl, 0),
        "win_rate_pct": round(win_rate, 1),
        "avg_win": round(avg_win, 0),
        "avg_loss": round(avg_loss, 0),
        "session_max_drawdown": round(max_drawdown, 0),
        "session_max_drawdown_pct": round(max_drawdown_pct, 2),
        "recommendations": recommendations,
    }


@app.get("/api/performance/summary")
async def get_performance_summary(current_user: str = Depends(get_current_user)):
    """일일·세션 성과 요약 및 성과 기반 권장 설정."""
    try:
        summary = _performance_summary_from_trades()
        return JSONResponse({"success": True, "summary": summary})
    except Exception as e:
        logger.exception(e)
        return JSONResponse({"success": False, "message": str(e)})


@app.get("/api/signals/pending")
async def get_pending_signals(current_user: str = Depends(get_current_user)):
    """승인 대기 신호 목록 조회"""
    with pending_signals_lock:
        now_ts = time.time()
        pending_list = [
            data for data in state.pending_signals.values()
            if data.get("status") == "pending" and data.get("expires_at", 0) >= now_ts
        ]
    pending_list.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return JSONResponse({"success": True, "signals": pending_list})


@app.post("/api/signals/{signal_id}/approve")
async def approve_signal(signal_id: str, current_user: str = Depends(get_current_user)):
    """신호 승인 후 주문 실행"""
    if not state.strategy or not state.trenv or not state.risk_manager:
        ok = _ensure_initialized()
        if not ok or not state.strategy or not state.trenv or not state.risk_manager:
            detail = getattr(state, "last_init_error", None)
            msg = "시스템 초기화 실패: KIS 설정(.env/kis_devlp.yaml), 네트워크, 계정 설정을 확인하세요."
            if detail:
                msg = f"{msg} (detail: {detail})"
            return JSONResponse({"success": False, "message": msg})

    with pending_signals_lock:
        signal_data = state.pending_signals.get(signal_id)
        if not signal_data:
            return JSONResponse({"success": False, "message": "신호를 찾을 수 없습니다."})
        if signal_data.get("status") != "pending":
            return JSONResponse({"success": False, "message": "이미 처리된 신호입니다."})
        if signal_data.get("expires_at", 0) < time.time():
            signal_data["status"] = "expired"
            return JSONResponse({"success": False, "message": "만료된 신호입니다."})

    result, details = safe_execute_order(
        signal=signal_data["signal"],
        stock_code=signal_data["stock_code"],
        price=float(signal_data["price"]),
        strategy=state.strategy,
        trenv=state.trenv,
        is_paper_trading=state.is_paper_trading,
        manual_approval=False,
        return_details=True,
        quantity_override=int(signal_data.get("suggested_qty") or 0) or None,
    )
    filled = bool(details.get("filled", False))
    await state.broadcast({"type": "log", "message": _format_order_log(details), "level": "info" if (result and filled) else ("warning" if result else "error")})
    # 부분매도(부분익절 등) 체결 시: 잔여 수량을 함께 로깅
    try:
        if result and filled and signal_data.get("signal") == "sell" and state.risk_manager:
            code = str(signal_data.get("stock_code") or "").strip().zfill(6)
            if code and code in getattr(state.risk_manager, "positions", {}):
                remain = int(state.risk_manager.positions[code].get("quantity") or 0)
                sold = 0
                try:
                    sold = int(details.get("quantity") or 0)
                except Exception:
                    sold = 0
                if remain > 0 and sold > 0:
                    await state.broadcast({
                        "type": "log",
                        "level": "info",
                        "message": f"부분 매도 체결: {code} sold={sold} remain={remain} ({signal_data.get('reason', '')})",
                    })
    except Exception:
        pass

    with pending_signals_lock:
        if signal_id in state.pending_signals:
            if not result:
                state.pending_signals[signal_id]["status"] = "failed"
            else:
                state.pending_signals[signal_id]["status"] = "approved" if filled else "approved_pending"
            resolved = state.pending_signals[signal_id]
            state.pending_signals.pop(signal_id, None)
        else:
            resolved = signal_data

    if result:
        qty = signal_data.get("suggested_qty", 0)
        try:
            qty = int(details.get("quantity") or qty)
        except Exception:
            pass
        trade_info = {
            "stock_code": signal_data["stock_code"],
            "order_type": signal_data["signal"],
            "quantity": qty,
            "price": signal_data["price"],
            "pnl": None
        }
        state.add_trade(trade_info)
        await state.broadcast({"type": "trade", "data": trade_info})
        await send_status_update()
        await state.broadcast({"type": "signal_resolved", "data": {"signal_id": signal_id, "status": "approved"}})
        return JSONResponse({"success": True, "message": "신호 승인 및 주문 실행 완료", "order_details": details})

    await state.broadcast({"type": "signal_resolved", "data": {"signal_id": signal_id, "status": "failed"}})
    return JSONResponse({"success": False, "message": "주문 실행 실패", "order_details": details})


@app.post("/api/signals/{signal_id}/reject")
async def reject_signal(signal_id: str, current_user: str = Depends(get_current_user)):
    """승인 대기 신호 거절"""
    with pending_signals_lock:
        signal_data = state.pending_signals.get(signal_id)
        if not signal_data:
            return JSONResponse({"success": False, "message": "신호를 찾을 수 없습니다."})
        signal_data["status"] = "rejected"
        state.pending_signals.pop(signal_id, None)

    await state.broadcast({"type": "signal_resolved", "data": {"signal_id": signal_id, "status": "rejected"}})
    return JSONResponse({"success": True, "message": "신호를 거절했습니다."})

@app.post("/api/config/risk")
async def update_risk_config(config: RiskConfig, current_user: str = Depends(get_current_user)):
    """리스크 설정 업데이트"""
    try:
        if not state.risk_manager:
            ok = _ensure_initialized()
            if not ok or not state.risk_manager:
                return JSONResponse({"success": False, "message": "리스크 관리자가 초기화되지 않았습니다."})

        state.risk_manager.max_single_trade_amount = config.max_single_trade_amount
        try:
            state.risk_manager.min_order_quantity = int(getattr(config, "min_order_quantity", 1) or 1)
        except Exception:
            state.risk_manager.min_order_quantity = 1
        state.risk_manager.stop_loss_ratio = config.stop_loss_ratio
        state.risk_manager.take_profit_ratio = config.take_profit_ratio
        state.risk_manager.daily_loss_limit = config.daily_loss_limit
        try:
            state.risk_manager.daily_profit_limit = int(getattr(config, "daily_profit_limit", 0) or 0)
        except Exception:
            state.risk_manager.daily_profit_limit = 0
        try:
            state.risk_manager.daily_total_loss_limit = int(getattr(config, "daily_total_loss_limit", 0) or 0)
        except Exception:
            state.risk_manager.daily_total_loss_limit = 0
        try:
            state.risk_manager.daily_profit_limit_basis = str(getattr(config, "daily_profit_limit_basis", "total") or "total")
        except Exception:
            state.risk_manager.daily_profit_limit_basis = "total"
        try:
            state.risk_manager.daily_loss_limit_basis = str(getattr(config, "daily_loss_limit_basis", "realized") or "realized")
        except Exception:
            state.risk_manager.daily_loss_limit_basis = "realized"
        try:
            state.risk_manager.buy_order_style = str(getattr(config, "buy_order_style", "market") or "market")
            state.risk_manager.sell_order_style = str(getattr(config, "sell_order_style", "market") or "market")
        except Exception:
            state.risk_manager.buy_order_style = "market"
            state.risk_manager.sell_order_style = "market"
        try:
            state.risk_manager.order_retry_count = int(getattr(config, "order_retry_count", 0) or 0)
            state.risk_manager.order_retry_delay_ms = int(getattr(config, "order_retry_delay_ms", 300) or 300)
            state.risk_manager.order_fallback_to_market = bool(getattr(config, "order_fallback_to_market", True))
        except Exception:
            state.risk_manager.order_retry_count = 0
            state.risk_manager.order_retry_delay_ms = 300
            state.risk_manager.order_fallback_to_market = True
        try:
            state.risk_manager.enable_volatility_sizing = bool(getattr(config, "enable_volatility_sizing", False))
            state.risk_manager.volatility_lookback_ticks = int(getattr(config, "volatility_lookback_ticks", 20) or 20)
            state.risk_manager.volatility_stop_mult = float(getattr(config, "volatility_stop_mult", 1.0) or 1.0)
            state.risk_manager.max_loss_per_stock_krw = int(getattr(config, "max_loss_per_stock_krw", 0) or 0)
            state.risk_manager.slippage_bps = int(getattr(config, "slippage_bps", 0) or 0)
            state.risk_manager.slippage_bps = max(0, min(500, state.risk_manager.slippage_bps))
            state.risk_manager.volatility_floor_ratio = float(getattr(config, "volatility_floor_ratio", 0.005) or 0.005)
            state.risk_manager.volatility_floor_ratio = max(0.0, min(0.05, state.risk_manager.volatility_floor_ratio))
        except Exception:
            state.risk_manager.enable_volatility_sizing = False
            state.risk_manager.volatility_lookback_ticks = 20
            state.risk_manager.volatility_stop_mult = 1.0
            state.risk_manager.max_loss_per_stock_krw = 0
            state.risk_manager.slippage_bps = 0
            state.risk_manager.volatility_floor_ratio = 0.005
        state.risk_manager.max_trades_per_day = config.max_trades_per_day
        state.risk_manager.max_position_size_ratio = config.max_position_size_ratio
        state.risk_manager.trailing_stop_ratio = getattr(config, "trailing_stop_ratio", 0.0) or 0.0
        state.risk_manager.trailing_activation_ratio = getattr(config, "trailing_activation_ratio", 0.0) or 0.0
        state.risk_manager.partial_take_profit_ratio = getattr(config, "partial_take_profit_ratio", 0.0) or 0.0
        state.risk_manager.partial_take_profit_fraction = getattr(config, "partial_take_profit_fraction", 0.5) or 0.5

        store = _get_user_settings_store()
        persisted = False
        if store and getattr(store, "enabled", False):
            persisted = bool(store.save(current_user, risk_config=config.model_dump()))
        else:
            persisted = False
            await state.broadcast({
                "type": "log",
                "level": "warning",
                "message": "리스크 설정 저장: DynamoDB 설정 저장소가 비활성화되어 저장되지 않았습니다. (/api/config/user-settings/store-status 로 원인 확인)",
            })
        
        # 신규 total-basis와 레거시 daily_total_loss_limit이 동시에 켜지면 혼선을 줄이기 위해 경고
        try:
            if str(getattr(state.risk_manager, "daily_loss_limit_basis", "realized") or "realized").strip().lower() == "total":
                if int(getattr(state.risk_manager, "daily_total_loss_limit", 0) or 0) > 0:
                    await state.broadcast({
                        "type": "log",
                        "level": "warning",
                        "message": "리스크 설정: daily_loss_limit_basis=total 사용 중에는 레거시 daily_total_loss_limit 트리거는 중복 방지를 위해 무시됩니다.",
                    })
        except Exception:
            pass

        await state.broadcast({"type": "log", "message": "리스크 설정이 업데이트되었습니다.", "level": "info"})
        return JSONResponse({"success": True, "persisted": persisted})
    except Exception as e:
        logger.error(f"리스크 설정 업데이트 오류: {e}")
        return JSONResponse({"success": False, "message": str(e)})


@app.post("/api/config/strategy")
async def update_strategy_config(config: StrategyConfig, current_user: str = Depends(get_current_user)):
    """전략 설정(이동평균 기간) 업데이트"""
    try:
        if not state.strategy or not state.trenv or not state.risk_manager:
            ok = _ensure_initialized()
            if not ok or not state.strategy:
                return JSONResponse({"success": False, "message": "전략이 초기화되지 않았습니다."})

        short_period = int(config.short_ma_period)
        long_period = int(config.long_ma_period)
        if short_period < 2 or long_period < 3:
            return JSONResponse({"success": False, "message": "이동평균 기간은 short>=2, long>=3 이어야 합니다."})
        if short_period >= long_period:
            return JSONResponse({"success": False, "message": "단기 이동평균은 장기 이동평균보다 작아야 합니다."})

        state.strategy.short_ma_period = short_period
        state.strategy.long_ma_period = long_period
        state.strategy.min_history_length = long_period

        # 신규 매수 허용 시간대(한국시간)
        start_hhmm = str(getattr(config, "buy_window_start_hhmm", getattr(state, "buy_window_start_hhmm", "09:05")) or "09:05")
        end_hhmm = str(getattr(config, "buy_window_end_hhmm", getattr(state, "buy_window_end_hhmm", "11:30")) or "11:30")
        state.buy_window_start_hhmm = start_hhmm
        state.buy_window_end_hhmm = end_hhmm
        # 추세 강도 필터 + 재진입 쿨다운
        state.min_short_ma_slope_ratio = float(getattr(config, "min_short_ma_slope_ratio", getattr(state, "min_short_ma_slope_ratio", 0.0)) or 0.0)
        state.momentum_lookback_ticks = int(getattr(config, "momentum_lookback_ticks", getattr(state, "momentum_lookback_ticks", 0)) or 0)
        state.min_momentum_ratio = float(getattr(config, "min_momentum_ratio", getattr(state, "min_momentum_ratio", 0.0)) or 0.0)
        # 진입 보강(2단)
        state.entry_confirm_enabled = bool(getattr(config, "entry_confirm_enabled", getattr(state, "entry_confirm_enabled", False)))
        state.entry_confirm_min_count = int(getattr(config, "entry_confirm_min_count", getattr(state, "entry_confirm_min_count", 1)) or 1)
        state.confirm_breakout_enabled = bool(getattr(config, "confirm_breakout_enabled", getattr(state, "confirm_breakout_enabled", False)))
        state.breakout_lookback_ticks = int(getattr(config, "breakout_lookback_ticks", getattr(state, "breakout_lookback_ticks", 20)) or 20)
        state.breakout_buffer_ratio = float(getattr(config, "breakout_buffer_ratio", getattr(state, "breakout_buffer_ratio", 0.0)) or 0.0)
        state.confirm_volume_surge_enabled = bool(getattr(config, "confirm_volume_surge_enabled", getattr(state, "confirm_volume_surge_enabled", False)))
        state.volume_surge_lookback_ticks = int(getattr(config, "volume_surge_lookback_ticks", getattr(state, "volume_surge_lookback_ticks", 20)) or 20)
        state.volume_surge_ratio = float(getattr(config, "volume_surge_ratio", getattr(state, "volume_surge_ratio", 2.0)) or 2.0)
        state.confirm_trade_value_surge_enabled = bool(getattr(config, "confirm_trade_value_surge_enabled", getattr(state, "confirm_trade_value_surge_enabled", False)))
        state.trade_value_surge_lookback_ticks = int(getattr(config, "trade_value_surge_lookback_ticks", getattr(state, "trade_value_surge_lookback_ticks", 20)) or 20)
        state.trade_value_surge_ratio = float(getattr(config, "trade_value_surge_ratio", getattr(state, "trade_value_surge_ratio", 2.0)) or 2.0)
        # 진입 직전 추가 필터(피크 추격/초단기 추세)
        state.avoid_chase_near_high_enabled = bool(getattr(config, "avoid_chase_near_high_enabled", getattr(state, "avoid_chase_near_high_enabled", False)))
        state.near_high_lookback_minutes = int(getattr(config, "near_high_lookback_minutes", getattr(state, "near_high_lookback_minutes", 2)) or 2)
        state.avoid_near_high_ratio = float(getattr(config, "avoid_near_high_ratio", getattr(state, "avoid_near_high_ratio", 0.003)) or 0.003)
        state.avoid_near_high_dynamic = bool(getattr(config, "avoid_near_high_dynamic", getattr(state, "avoid_near_high_dynamic", False)))
        state.avoid_near_high_vs_vol_mult = float(getattr(config, "avoid_near_high_vs_vol_mult", getattr(state, "avoid_near_high_vs_vol_mult", 0.0)) or 0.0)
        state.minute_trend_enabled = bool(getattr(config, "minute_trend_enabled", getattr(state, "minute_trend_enabled", False)))
        state.minute_trend_lookback_bars = int(getattr(config, "minute_trend_lookback_bars", getattr(state, "minute_trend_lookback_bars", 2)) or 2)
        state.minute_trend_min_green_bars = int(getattr(config, "minute_trend_min_green_bars", getattr(state, "minute_trend_min_green_bars", 2)) or 2)
        state.minute_trend_mode = str(getattr(config, "minute_trend_mode", getattr(state, "minute_trend_mode", "green")) or "green")
        state.minute_trend_early_only = bool(getattr(config, "minute_trend_early_only", getattr(state, "minute_trend_early_only", False)))
        # 변동성 정규화(보조)
        state.vol_norm_lookback_ticks = int(getattr(config, "vol_norm_lookback_ticks", getattr(state, "vol_norm_lookback_ticks", 20)) or 20)
        state.slope_vs_vol_mult = float(getattr(config, "slope_vs_vol_mult", getattr(state, "slope_vs_vol_mult", 0.0)) or 0.0)
        state.range_vs_vol_mult = float(getattr(config, "range_vs_vol_mult", getattr(state, "range_vs_vol_mult", 0.0)) or 0.0)
        # 오전장 레짐 분기(초반/메인)
        state.enable_morning_regime_split = bool(getattr(config, "enable_morning_regime_split", getattr(state, "enable_morning_regime_split", False)))
        state.morning_regime_early_end_hhmm = str(getattr(config, "morning_regime_early_end_hhmm", getattr(state, "morning_regime_early_end_hhmm", "09:10")) or "09:10")
        state.early_min_short_ma_slope_ratio = float(getattr(config, "early_min_short_ma_slope_ratio", getattr(state, "early_min_short_ma_slope_ratio", 0.0)) or 0.0)
        state.early_momentum_lookback_ticks = int(getattr(config, "early_momentum_lookback_ticks", getattr(state, "early_momentum_lookback_ticks", 0)) or 0)
        state.early_min_momentum_ratio = float(getattr(config, "early_min_momentum_ratio", getattr(state, "early_min_momentum_ratio", 0.0)) or 0.0)
        state.early_buy_confirm_ticks = int(getattr(config, "early_buy_confirm_ticks", getattr(state, "early_buy_confirm_ticks", 1)) or 1)
        state.early_max_spread_ratio = float(getattr(config, "early_max_spread_ratio", getattr(state, "early_max_spread_ratio", 0.0)) or 0.0)
        state.early_range_lookback_ticks = int(getattr(config, "early_range_lookback_ticks", getattr(state, "early_range_lookback_ticks", 0)) or 0)
        state.early_min_range_ratio = float(getattr(config, "early_min_range_ratio", getattr(state, "early_min_range_ratio", 0.0)) or 0.0)
        state.reentry_cooldown_seconds = int(getattr(config, "reentry_cooldown_seconds", getattr(state, "reentry_cooldown_seconds", 0)) or 0)
        if getattr(state, "risk_manager", None):
            state.risk_manager.reentry_cooldown_seconds = int(state.reentry_cooldown_seconds or 0)
        # 2틱 확인 + 시간기반 청산
        state.buy_confirm_ticks = int(getattr(config, "buy_confirm_ticks", getattr(state, "buy_confirm_ticks", 1)) or 1)
        state.enable_time_liquidation = bool(getattr(config, "enable_time_liquidation", getattr(state, "enable_time_liquidation", False)))
        state.liquidate_after_hhmm = str(getattr(config, "liquidate_after_hhmm", getattr(state, "liquidate_after_hhmm", "11:55")) or "11:55")
        # 스프레드/횡보장 필터
        state.max_spread_ratio = float(getattr(config, "max_spread_ratio", getattr(state, "max_spread_ratio", 0.0)) or 0.0)
        state.range_lookback_ticks = int(getattr(config, "range_lookback_ticks", getattr(state, "range_lookback_ticks", 0)) or 0)
        state.min_range_ratio = float(getattr(config, "min_range_ratio", getattr(state, "min_range_ratio", 0.0)) or 0.0)

        store = _get_user_settings_store()
        persisted = False
        if store and getattr(store, "enabled", False):
            persisted = bool(store.save(current_user, strategy_config=config.model_dump()))
        else:
            persisted = False
            await state.broadcast({
                "type": "log",
                "level": "warning",
                "message": "전략 설정 저장: DynamoDB 설정 저장소가 비활성화되어 저장되지 않았습니다. (/api/config/user-settings/store-status 로 원인 확인)",
            })

        await state.broadcast({
            "type": "log",
            "message": (
                f"전략 설정 업데이트: short={short_period}, long={long_period}, "
                f"buy_window={start_hhmm}-{end_hhmm}, "
                f"slope>={state.min_short_ma_slope_ratio*100:.3f}%/tick, "
                f"momentum>={getattr(state,'min_momentum_ratio',0.0)*100:.2f}%/N{int(getattr(state,'momentum_lookback_ticks',0) or 0)}, "
                f"entryConfirm={'on' if getattr(state,'entry_confirm_enabled',False) else 'off'}(min={int(getattr(state,'entry_confirm_min_count',1) or 1)}), "
                f"volNorm=N{int(getattr(state,'vol_norm_lookback_ticks',20) or 20)} slopeMult={float(getattr(state,'slope_vs_vol_mult',0.0) or 0.0):.2f} rangeMult={float(getattr(state,'range_vs_vol_mult',0.0) or 0.0):.2f}, "
                f"regimeSplit={'on' if getattr(state,'enable_morning_regime_split',False) else 'off'}@{getattr(state,'morning_regime_early_end_hhmm','09:10')}, "
                f"cooldown={state.reentry_cooldown_seconds}s, "
                f"confirm={int(state.buy_confirm_ticks)}tick, "
                f"time_liq={'on' if state.enable_time_liquidation else 'off'}@{state.liquidate_after_hhmm}, "
                f"spread<={state.max_spread_ratio*100:.3f}%, "
                f"range>={state.min_range_ratio*100:.3f}%/N{state.range_lookback_ticks}"
            ),
            "level": "info"
        })
        return JSONResponse({"success": True, "persisted": persisted})
    except Exception as e:
        logger.error(f"전략 설정 업데이트 오류: {e}")
        return JSONResponse({"success": False, "message": str(e)})

@app.get("/api/config/preset/{preset_name}")
async def get_preset_endpoint(preset_name: str, current_user: str = Depends(get_current_user)):
    """프리셋 가져오기"""
    try:
        preset = get_preset(preset_name)
        return JSONResponse({"success": True, "preset": preset})
    except Exception as e:
        logger.error(f"프리셋 가져오기 오류: {e}")
        return JSONResponse({"success": False, "message": str(e)})

@app.get("/api/config/presets")
async def list_all_presets(current_user: str = Depends(get_current_user)):
    """모든 프리셋 목록"""
    try:
        presets = list_presets()
        return JSONResponse({"success": True, "presets": presets})
    except Exception as e:
        logger.error(f"프리셋 목록 조회 오류: {e}")
        return JSONResponse({"success": False, "message": str(e)})

@app.post("/api/config/stock-selection")
async def update_stock_selection_config(config: StockSelectionConfig, current_user: str = Depends(get_current_user)):
    """종목 선정 기준 업데이트"""
    try:
        state.stock_selector = StockSelector(
            env_dv="demo" if state.is_paper_trading else "real",
            min_price_change_ratio=config.min_price_change_ratio,
            max_price_change_ratio=config.max_price_change_ratio,
            min_price=config.min_price,
            max_price=config.max_price,
            min_volume=config.min_volume,
            min_trade_amount=config.min_trade_amount,
            max_stocks=config.max_stocks,
            exclude_risk_stocks=config.exclude_risk_stocks,
            sort_by=str(getattr(config, "sort_by", "change") or "change"),
            prev_day_rank_pool_size=int(getattr(config, "prev_day_rank_pool_size", 80) or 80),
            market_open_hhmm=getattr(config, "market_open_hhmm", "09:00"),
            warmup_minutes=int(getattr(config, "warmup_minutes", 5) or 5),
            early_strict=bool(getattr(config, "early_strict", False)),
            early_strict_minutes=int(getattr(config, "early_strict_minutes", 30) or 30),
            early_min_volume=int(getattr(config, "early_min_volume", 200000) or 200000),
            early_min_trade_amount=int(getattr(config, "early_min_trade_amount", 0) or 0),
            exclude_drawdown=bool(getattr(config, "exclude_drawdown", False)),
            max_drawdown_from_high_ratio=float(getattr(config, "max_drawdown_from_high_ratio", 0.02) or 0.02),
            drawdown_filter_after_hhmm=getattr(config, "drawdown_filter_after_hhmm", "12:00"),
            kospi_only=bool(getattr(config, "kospi_only", False)),
        )

        store = _get_user_settings_store()
        persisted = False
        if store and getattr(store, "enabled", False):
            persisted = bool(store.save(current_user, stock_selection_config=config.model_dump()))
        else:
            persisted = False
            await state.broadcast({
                "type": "log",
                "level": "warning",
                "message": "종목 선정 기준 저장: DynamoDB 설정 저장소가 비활성화되어 저장되지 않았습니다. (/api/config/user-settings/store-status 로 원인 확인)",
            })
        
        await state.broadcast({"type": "log", "message": "종목 선정 기준이 업데이트되었습니다.", "level": "info"})
        return JSONResponse({"success": True, "persisted": persisted})
    except Exception as e:
        logger.error(f"종목 선정 기준 업데이트 오류: {e}")
        return JSONResponse({"success": False, "message": str(e)})


@app.post("/api/config/operational")
async def update_operational_config(config: OperationalConfig, current_user: str = Depends(get_current_user)):
    """운영 옵션 저장: 자동 리밸런싱, 성과 기반 자동 추천"""
    try:
        state.enable_auto_rebalance = bool(config.enable_auto_rebalance)
        state.auto_rebalance_interval_minutes = max(5, min(120, int(config.auto_rebalance_interval_minutes or 30)))
        state.enable_performance_auto_recommend = bool(config.enable_performance_auto_recommend)
        state.performance_recommend_interval_minutes = max(1, min(60, int(config.performance_recommend_interval_minutes or 5)))
        store = _get_user_settings_store()
        persisted = False
        if store and getattr(store, "enabled", False):
            persisted = bool(store.save(current_user, operational_config=config.model_dump()))
        await state.broadcast({"type": "log", "message": "운영 옵션이 업데이트되었습니다.", "level": "info"})
        return JSONResponse({"success": True, "persisted": persisted})
    except Exception as e:
        logger.error(f"운영 옵션 업데이트 오류: {e}")
        return JSONResponse({"success": False, "message": str(e)})


@app.get("/api/config/user-settings")
async def get_user_settings(current_user: str = Depends(get_current_user)):
    """로그인 사용자별 저장된 설정값 조회. 조회한 값은 백엔드 state에도 반영해 DB·화면·실행값이 일치하도록 함."""
    store = _get_user_settings_store()
    if not store or not getattr(store, "enabled", False):
        return JSONResponse({"success": False, "message": "DynamoDB 설정 저장소를 사용할 수 없습니다."})
    settings = store.load(current_user) or {}
    # DB에서 불러온 설정을 state에 반영 → 리스크 관리 등 화면값과 실제 적용값·DB가 같아짐
    _apply_risk_config_dict_to_state(settings.get("risk_config"))
    _apply_operational_config_dict_to_state(settings.get("operational_config"))
    return JSONResponse({"success": True, "settings": settings})

@app.post("/api/stocks/select")
async def select_stocks(current_user: str = Depends(get_current_user)):
    """종목 재선정"""
    try:
        # 전역 KIS 환경을 일시 전환할 수 있어 실행 중에는 방지 (엔진/WS 안정성)
        if getattr(state, "is_running", False):
            return JSONResponse({"success": False, "message": "실행 중에는 종목을 재선정할 수 없습니다. 시스템을 중지한 후 다시 시도하세요."})

        if not state.stock_selector:
            ok = _ensure_initialized()
            if not ok or not state.stock_selector:
                return JSONResponse({"success": False, "message": "종목 선정기가 초기화되지 않았습니다."})
        # 종목 선정은 KIS 인증이 필요할 수 있어, TR 환경이 없으면 1회 초기화
        if not getattr(state, "trenv", None):
            ok = _ensure_initialized()
            if not ok or not getattr(state, "trenv", None):
                detail = getattr(state, "last_init_error", None)
                msg = "시스템 초기화 실패: KIS 설정(.env/kis_devlp.yaml), 네트워크, 계정 설정을 확인하세요."
                if detail:
                    msg = f"{msg} (detail: {detail})"
                return JSONResponse({"success": False, "message": msg})

        await state.broadcast({
            "type": "log",
            "message": (
                f"종목 재선정 요청: min_change={state.stock_selector.min_price_change_ratio*100:.1f}% "
                f"max_change={state.stock_selector.max_price_change_ratio*100:.1f}% "
                f"price={state.stock_selector.min_price:,}-{state.stock_selector.max_price:,} "
                f"vol>={state.stock_selector.min_volume:,} "
                f"trade_amt>={getattr(state.stock_selector, 'min_trade_amount', 0):,} "
                f"max={state.stock_selector.max_stocks} env_dv={state.stock_selector.env_dv}"
            ),
            "level": "info"
        })
        
        selected = state.stock_selector.select_stocks_by_fluctuation()
        if not selected:
            state.selected_stocks = []
            state.selected_stock_info = []
            detail = getattr(state.stock_selector, "last_error_message", "") if state.stock_selector else ""
            debug = getattr(state.stock_selector, "last_debug", {}) if state.stock_selector else {}
            if detail:
                # 장초 워밍업/가드 같은 경우는 "API 실패"로 오해하지 않게 그대로 노출
                if "워밍업" in detail or "다시 시도" in detail or "장 시작" in detail:
                    message = detail
                else:
                    if "API OK but output" in detail:
                        message = f"종목 선정 결과 없음: {detail} (조건을 완화해보세요)"
                    else:
                        message = f"종목 선정 API 실패: {detail}"
            else:
                message = "조건에 맞는 종목이 없습니다. (가격/거래량/등락률 조건을 완화해보세요)"
            await state.broadcast({"type": "log", "message": message, "level": "warning"})
            if debug:
                await state.broadcast({"type": "log", "message": f"종목 선정 디버그: {debug}", "level": "warning"})
            return JSONResponse({"success": False, "message": message, "stocks": [], "stock_info": [], "debug": debug})

        state.selected_stocks = selected
        state.selected_stock_info = getattr(
            state.stock_selector,
            "last_selected_stock_info",
            [{"code": code, "name": code} for code in selected]
        )
        
        await state.broadcast({
            "type": "log",
            "message": f"종목 재선정 완료: {', '.join(selected)}",
            "level": "info"
        })
        
        return JSONResponse({"success": True, "message": f"{len(selected)}개 종목 선정", "stocks": selected, "stock_info": state.selected_stock_info})
    except Exception as e:
        logger.error(f"종목 선정 오류: {e}")
        return JSONResponse({"success": False, "message": str(e)})

@app.post("/api/order/manual")
async def execute_manual_order(order: ManualOrder, current_user: str = Depends(get_current_user)):
    """수동 주문 실행"""
    try:
        if not state.strategy or not state.trenv or not state.risk_manager:
            ok = _ensure_initialized()
            if not ok or not state.strategy or not state.trenv or not state.risk_manager:
                detail = getattr(state, "last_init_error", None)
                msg = "시스템 초기화 실패: KIS 설정(.env/kis_devlp.yaml), 네트워크, 계정 설정을 확인하세요."
                if detail:
                    msg = f"{msg} (detail: {detail})"
                return JSONResponse({"success": False, "message": msg})
        
        result, details = safe_execute_order(
            signal=order.order_type,
            stock_code=order.stock_code,
            price=order.price or 0,
            strategy=state.strategy,
            trenv=state.trenv,
            is_paper_trading=state.is_paper_trading,
            manual_approval=False,
            return_details=True,
            quantity_override=int(order.quantity or 0) or None,
        )
        filled = bool(details.get("filled", False))
        await state.broadcast({"type": "log", "message": _format_order_log(details), "level": "info" if (result and filled) else ("warning" if result else "error")})
        # 수동 매도에서도 부분매도 체결 시 잔여 수량 표시
        try:
            if result and filled and str(order.order_type).lower() == "sell" and state.risk_manager:
                code = str(order.stock_code or "").strip().zfill(6)
                if code and code in getattr(state.risk_manager, "positions", {}):
                    remain = int(state.risk_manager.positions[code].get("quantity") or 0)
                    sold = 0
                    try:
                        sold = int(details.get("quantity") or 0)
                    except Exception:
                        sold = 0
                    if remain > 0 and sold > 0:
                        await state.broadcast({
                            "type": "log",
                            "level": "info",
                            "message": f"부분 매도 체결: {code} sold={sold} remain={remain} (수동주문)",
                        })
        except Exception:
            pass
        
        if result and filled:
            qty = order.quantity
            try:
                qty = int(details.get("quantity") or qty)
            except Exception:
                pass
            trade_info = {
                "stock_code": order.stock_code,
                "order_type": order.order_type,
                "quantity": qty,
                "price": order.price or 0,
                "pnl": None
            }
            state.add_trade(trade_info)
            await state.broadcast({"type": "trade", "data": trade_info})
            await send_status_update()
            
            return JSONResponse({"success": True, "message": "주문이 실행되었습니다.", "order_details": details})
        if result and not filled:
            return JSONResponse({"success": True, "message": "주문이 접수되었지만 체결 대기/미체결 상태입니다. (포지션 반영 보류)", "order_details": details})
        return JSONResponse({"success": False, "message": "주문 실행에 실패했습니다.", "order_details": details})
    except Exception as e:
        logger.error(f"수동 주문 오류: {e}")
        return JSONResponse({"success": False, "message": str(e)})

# ============================================================================
# 시스템 초기화
# ============================================================================

def initialize_trading_system(
    account_balance: float = 100000,
    is_paper_trading: bool = True
):
    """거래 시스템 초기화"""
    try:
        state.last_init_error = None
        svr = "vps" if is_paper_trading else "prod"
        ka.changeTREnv(None, svr=svr, product="01")
        ka.auth(svr=svr, product="01")
        ka.auth_ws(svr=svr, product="01")
        trenv = ka.getTREnv()
        
        from quant_trading_safe import RiskManager, QuantStrategy
        risk_manager = RiskManager(account_balance=account_balance)
        strategy = QuantStrategy(risk_manager)
        
        stock_selector = StockSelector(
            env_dv="demo" if is_paper_trading else "real",
            min_price_change_ratio=0.01,
            max_price_change_ratio=0.15,
            min_price=1000,
            max_price=50000,
            min_volume=50000,
            max_stocks=5,
            exclude_risk_stocks=True,
            market_open_hhmm="09:00",
            warmup_minutes=5,
            early_strict=False,
            early_strict_minutes=30,
            early_min_volume=200000,
            early_min_trade_amount=0,
            exclude_drawdown=False,
            max_drawdown_from_high_ratio=0.02,
            drawdown_filter_after_hhmm="12:00",
            kospi_only=False,
        )
        
        state.risk_manager = risk_manager
        state.strategy = strategy
        state.trenv = trenv
        state.is_paper_trading = is_paper_trading
        if not getattr(state, "buy_window_start_hhmm", None):
            state.buy_window_start_hhmm = "09:05"
        if not getattr(state, "buy_window_end_hhmm", None):
            state.buy_window_end_hhmm = "11:30"
        # 사용자가 설정에서 stock_selector를 저장해두었다면 덮어쓰지 않음
        if not getattr(state, "stock_selector", None):
            state.stock_selector = stock_selector
        # 로그인 직후에는 디폴트 종목을 강제하지 않고, 선정 결과가 있을 때만 표시
        if not getattr(state, "selected_stocks", None):
            state.selected_stocks = []
        if not getattr(state, "selected_stock_info", None):
            state.selected_stock_info = []
        state.pending_signals = {}
        state.engine_thread = None
        state.engine_running = False

        # 초기화 직후 1회 실제 계좌 잔고를 조회해 반영 (가능하면)
        _refresh_kis_account_balance_sync()
        
        logger.info("거래 시스템 초기화 완료")
        return True
    except Exception as e:
        state.last_init_error = str(e)
        logger.error(f"시스템 초기화 오류: {e}")
        return False

# 메인 실행 시 API 엔드포인트 로드
if __name__ != "__main__":
    # 모듈 import 시 자동으로 API 엔드포인트 등록
    pass
