"""
API 엔드포인트 모듈 (모바일 대시보드용)

기존 quant_dashboard.py의 API를 인증 의존성과 함께 제공
"""

from fastapi import Depends, HTTPException, WebSocket, WebSocketDisconnect, Query
from fastapi.responses import JSONResponse
from typing import Dict, List, Optional
from datetime import datetime
import logging
import asyncio
import threading
import uuid
import time
import os

import kis_auth as ka
from domestic_stock_functions_ws import ccnl_krx

from quant_dashboard_mobile import (
    app, state, get_current_user,
    RiskConfig, StockSelectionConfig, StrategyConfig, ManualOrder
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


def _build_pending_signal(stock_code: str, signal: str, price: float, reason: str) -> dict:
    signal_id = f"sig_{datetime.now().strftime('%Y%m%d%H%M%S')}_{stock_code}_{uuid.uuid4().hex[:6]}"
    now = datetime.now()
    suggested_qty = 0
    if signal == "buy" and state.risk_manager:
        suggested_qty = state.risk_manager.calculate_quantity(price)
    elif signal == "sell" and state.risk_manager and stock_code in state.risk_manager.positions:
        suggested_qty = state.risk_manager.positions[stock_code]["quantity"]

    return {
        "signal_id": signal_id,
        "stock_code": stock_code,
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

            def on_result(ws, tr_id, result, data_info):
                if not state.is_running or not state.strategy or not state.risk_manager:
                    return
                if tr_id not in ["H0STCNT0", "H0STCNT1"] or result.empty:
                    return

                for _, row in result.iterrows():
                    try:
                        _print_tick_summary(row)
                        stock_code = str(row.get("MKSC_SHRN_ISCD", "")).strip().zfill(6)
                        current_price = float(row.get("STCK_PRPR", 0))
                        if not stock_code or current_price <= 0:
                            continue

                        state.risk_manager.update_price(stock_code, current_price)
                        state.strategy.update_price(stock_code, current_price)
                        _print_signal_decision(stock_code, current_price)

                        sell_signal = state.risk_manager.check_stop_loss_take_profit(stock_code, current_price)
                        if sell_signal:
                            signal = _build_pending_signal(
                                stock_code=stock_code,
                                signal="sell",
                                price=current_price,
                                reason="손절/익절 조건 충족",
                            )
                            created = _create_or_replace_pending_signal(signal)
                            if created:
                                _run_async_broadcast({"type": "signal_pending", "data": created})
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
                                signal_type = "buy"
                            elif short_ma < long_ma and stock_code in state.risk_manager.positions:
                                signal_type = "sell"
                        if signal_type:
                            signal = _build_pending_signal(
                                stock_code=stock_code,
                                signal=signal_type,
                                price=current_price,
                                reason="이동평균 크로스 조건 충족",
                            )
                            created = _create_or_replace_pending_signal(signal)
                            if created:
                                _run_async_broadcast({"type": "signal_pending", "data": created})
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
        await state.broadcast({
            "type": "status",
            "data": {
                "is_running": state.is_running,
                "env_name": "모의투자" if state.is_paper_trading else "실전투자",
                "account_balance": state.risk_manager.account_balance,
                "daily_pnl": state.risk_manager.daily_pnl,
                "daily_trades": state.risk_manager.daily_trades
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
            "env_name": "-",
            "account_balance": 0,
            "daily_pnl": 0,
            "daily_trades": 0,
            "selected_stocks": [],
            "selected_stock_info": []
        })
    
    return JSONResponse({
        "is_running": state.is_running,
        "env_name": "모의투자" if state.is_paper_trading else "실전투자",
        "account_balance": state.risk_manager.account_balance,
        "daily_pnl": state.risk_manager.daily_pnl,
        "daily_trades": state.risk_manager.daily_trades,
        "selected_stocks": state.selected_stocks,
        "selected_stock_info": getattr(state, "selected_stock_info", []),
        "short_ma_period": state.strategy.short_ma_period if state.strategy else None,
        "long_ma_period": state.strategy.long_ma_period if state.strategy else None
    })

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

        if not state.selected_stocks:
            state.selected_stocks = ["005930", "000660"]
        if not getattr(state, "selected_stock_info", None):
            state.selected_stock_info = DEFAULT_STOCK_INFO.copy()

        state.is_running = True
        _start_trading_engine_thread()
        await send_status_update()

        return JSONResponse({"success": True, "message": f"시스템 시작 (감시 종목: {', '.join(state.selected_stocks)})"})
    except Exception as e:
        logger.error(f"시스템 시작 오류: {e}")
        return JSONResponse({"success": False, "message": str(e)})

@app.post("/api/system/stop")
async def stop_system(
    liquidate: bool = Query(False),
    current_user: str = Depends(get_current_user)
):
    """시스템 중지"""
    try:
        state.is_running = False
        with pending_signals_lock:
            state.pending_signals = {}

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

    result = safe_execute_order(
        signal=signal_data["signal"],
        stock_code=signal_data["stock_code"],
        price=float(signal_data["price"]),
        strategy=state.strategy,
        trenv=state.trenv,
        is_paper_trading=state.is_paper_trading,
        manual_approval=False
    )

    with pending_signals_lock:
        if signal_id in state.pending_signals:
            state.pending_signals[signal_id]["status"] = "approved" if result else "failed"
            resolved = state.pending_signals[signal_id]
            state.pending_signals.pop(signal_id, None)
        else:
            resolved = signal_data

    if result:
        trade_info = {
            "stock_code": signal_data["stock_code"],
            "order_type": signal_data["signal"],
            "quantity": signal_data.get("suggested_qty", 0),
            "price": signal_data["price"],
            "pnl": None
        }
        state.add_trade(trade_info)
        await state.broadcast({"type": "trade", "data": trade_info})
        await send_status_update()
        await state.broadcast({"type": "signal_resolved", "data": {"signal_id": signal_id, "status": "approved"}})
        return JSONResponse({"success": True, "message": "신호 승인 및 주문 실행 완료"})

    await state.broadcast({"type": "signal_resolved", "data": {"signal_id": signal_id, "status": "failed"}})
    return JSONResponse({"success": False, "message": "주문 실행 실패"})


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
        state.risk_manager.stop_loss_ratio = config.stop_loss_ratio
        state.risk_manager.take_profit_ratio = config.take_profit_ratio
        state.risk_manager.daily_loss_limit = config.daily_loss_limit
        state.risk_manager.max_trades_per_day = config.max_trades_per_day
        state.risk_manager.max_position_size_ratio = config.max_position_size_ratio
        
        await state.broadcast({"type": "log", "message": "리스크 설정이 업데이트되었습니다.", "level": "info"})
        return JSONResponse({"success": True})
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

        await state.broadcast({
            "type": "log",
            "message": f"전략 설정 업데이트: short={short_period}, long={long_period}",
            "level": "info"
        })
        return JSONResponse({"success": True})
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
            exclude_risk_stocks=config.exclude_risk_stocks
        )
        
        await state.broadcast({"type": "log", "message": "종목 선정 기준이 업데이트되었습니다.", "level": "info"})
        return JSONResponse({"success": True})
    except Exception as e:
        logger.error(f"종목 선정 기준 업데이트 오류: {e}")
        return JSONResponse({"success": False, "message": str(e)})

@app.post("/api/stocks/select")
async def select_stocks(current_user: str = Depends(get_current_user)):
    """종목 재선정"""
    try:
        if not state.stock_selector:
            ok = _ensure_initialized()
            if not ok or not state.stock_selector:
                return JSONResponse({"success": False, "message": "종목 선정기가 초기화되지 않았습니다."})
        
        selected = state.stock_selector.select_stocks_by_fluctuation()
        if not selected:
            state.selected_stocks = []
            state.selected_stock_info = []
            message = "조건에 맞는 종목이 없습니다. (가격/거래량/등락률 조건을 완화해보세요)"
            await state.broadcast({"type": "log", "message": message, "level": "warning"})
            return JSONResponse({"success": False, "message": message, "stocks": [], "stock_info": []})

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
        
        result = safe_execute_order(
            signal=order.order_type,
            stock_code=order.stock_code,
            price=order.price or 0,
            strategy=state.strategy,
            trenv=state.trenv,
            is_paper_trading=state.is_paper_trading,
            manual_approval=False
        )
        
        if result:
            trade_info = {
                "stock_code": order.stock_code,
                "order_type": order.order_type,
                "quantity": order.quantity,
                "price": order.price or 0,
                "pnl": None
            }
            state.add_trade(trade_info)
            await state.broadcast({"type": "trade", "data": trade_info})
            await send_status_update()
            
            return JSONResponse({"success": True, "message": "주문이 실행되었습니다."})
        else:
            return JSONResponse({"success": False, "message": "주문 실행에 실패했습니다."})
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
            exclude_risk_stocks=True
        )
        
        state.risk_manager = risk_manager
        state.strategy = strategy
        state.trenv = trenv
        state.is_paper_trading = is_paper_trading
        state.stock_selector = stock_selector
        state.selected_stocks = ["005930", "000660"]
        state.selected_stock_info = DEFAULT_STOCK_INFO.copy()
        state.pending_signals = {}
        state.engine_thread = None
        state.engine_running = False
        
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
