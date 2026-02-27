"""
API 엔드포인트 모듈 (모바일 대시보드용)

기존 quant_dashboard.py의 API를 인증 의존성과 함께 제공
"""

from fastapi import Depends, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from typing import Dict, List, Optional
from datetime import datetime
import logging

from quant_dashboard_mobile import (
    app, state, get_current_user,
    RiskConfig, StockSelectionConfig, ManualOrder
)
from stock_selector import StockSelector
from stock_selection_presets import get_preset, list_presets
from quant_trading_safe import safe_execute_order

logger = logging.getLogger(__name__)

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
            "daily_trades": 0
        })
    
    return JSONResponse({
        "is_running": state.is_running,
        "env_name": "모의투자" if state.is_paper_trading else "실전투자",
        "account_balance": state.risk_manager.account_balance,
        "daily_pnl": state.risk_manager.daily_pnl,
        "daily_trades": state.risk_manager.daily_trades
    })

@app.post("/api/system/start")
async def start_system(current_user: str = Depends(get_current_user)):
    """시스템 시작"""
    try:
        if state.is_running:
            return JSONResponse({"success": False, "message": "이미 실행 중입니다."})
        
        state.is_running = True
        await send_status_update()
        
        return JSONResponse({"success": True, "message": "시스템이 시작되었습니다."})
    except Exception as e:
        logger.error(f"시스템 시작 오류: {e}")
        return JSONResponse({"success": False, "message": str(e)})

@app.post("/api/system/stop")
async def stop_system(current_user: str = Depends(get_current_user)):
    """시스템 중지"""
    try:
        state.is_running = False
        await send_status_update()
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

@app.post("/api/config/risk")
async def update_risk_config(config: RiskConfig, current_user: str = Depends(get_current_user)):
    """리스크 설정 업데이트"""
    try:
        if state.risk_manager:
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
            return JSONResponse({"success": False, "message": "종목 선정기가 초기화되지 않았습니다."})
        
        selected = state.stock_selector.select_stocks_by_fluctuation()
        state.selected_stocks = selected
        
        await state.broadcast({
            "type": "log",
            "message": f"종목 재선정 완료: {', '.join(selected)}",
            "level": "info"
        })
        
        return JSONResponse({"success": True, "stocks": selected})
    except Exception as e:
        logger.error(f"종목 선정 오류: {e}")
        return JSONResponse({"success": False, "message": str(e)})

@app.post("/api/order/manual")
async def execute_manual_order(order: ManualOrder, current_user: str = Depends(get_current_user)):
    """수동 주문 실행"""
    try:
        if not state.strategy or not state.trenv:
            return JSONResponse({"success": False, "message": "시스템이 초기화되지 않았습니다."})
        
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
        import kis_auth as ka
        svr = "vps" if is_paper_trading else "prod"
        ka.changeTREnv(None, svr=svr, product="01")
        ka.auth()
        ka.auth_ws()
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
        
        logger.info("거래 시스템 초기화 완료")
        return True
    except Exception as e:
        logger.error(f"시스템 초기화 오류: {e}")
        return False

# 메인 실행 시 API 엔드포인트 로드
if __name__ != "__main__":
    # 모듈 import 시 자동으로 API 엔드포인트 등록
    pass
