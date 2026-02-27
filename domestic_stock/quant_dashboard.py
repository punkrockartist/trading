"""
퀀트 매매 시스템 웹 대시보드 (FastAPI)

기능:
1. 실시간 포지션 모니터링
2. 거래 내역 조회
3. 리스크 관리 설정 변경
4. 종목 선정 기준 변경
5. 수동 거래 실행
6. 시스템 상태 모니터링
"""

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Depends, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.staticfiles import StaticFiles
from typing import Dict, List, Optional
import json
import asyncio
import logging
from datetime import datetime
from pydantic import BaseModel
import uvicorn
# from auth_manager import auth_manager, AuthManager  # 로그인 기능이 없는 버전이므로 주석 처리

# 퀀트 매매 시스템 import
import sys
sys.path.extend(['..', '.'])
import kis_auth as ka
from quant_trading_safe import (
    RiskManager, QuantStrategy,
    safe_execute_order, create_safe_on_result
)
from stock_selector import StockSelector
from domestic_stock_functions_ws import ccnl_krx
from stock_selection_presets import PRESETS, get_preset, list_presets

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# FastAPI 앱 생성
app = FastAPI(title="퀀트 매매 시스템 대시보드")

# 전역 상태 관리
class TradingState:
    """거래 시스템 상태 관리"""
    def __init__(self):
        self.risk_manager: Optional[RiskManager] = None
        self.strategy: Optional[QuantStrategy] = None
        self.trenv = None
        self.is_paper_trading = True
        self.is_running = False
        self.websocket_clients: List[WebSocket] = []
        self.trade_history: List[Dict] = []
        self.current_positions: Dict[str, Dict] = {}
        self.selected_stocks: List[str] = []
        self.stock_selector: Optional[StockSelector] = None
        
    async def broadcast(self, message: dict):
        """모든 WebSocket 클라이언트에 메시지 전송"""
        disconnected = []
        for client in self.websocket_clients:
            try:
                await client.send_json(message)
            except:
                disconnected.append(client)
        
        # 연결 끊어진 클라이언트 제거
        for client in disconnected:
            if client in self.websocket_clients:
                self.websocket_clients.remove(client)
    
    def add_trade(self, trade_info: dict):
        """거래 내역 추가"""
        trade_info["timestamp"] = datetime.now().isoformat()
        self.trade_history.append(trade_info)
        # 최근 100개만 유지
        if len(self.trade_history) > 100:
            self.trade_history = self.trade_history[-100:]

# 전역 상태
state = TradingState()

# Pydantic 모델
class RiskConfig(BaseModel):
    max_single_trade_amount: int
    stop_loss_ratio: float
    take_profit_ratio: float
    daily_loss_limit: int
    max_trades_per_day: int
    max_position_size_ratio: float

class StockSelectionConfig(BaseModel):
    min_price_change_ratio: float
    max_price_change_ratio: float
    min_price: int
    max_price: int
    min_volume: int
    min_trade_amount: int = 0  # 최소 거래대금 (선택)
    max_stocks: int
    exclude_risk_stocks: bool

class ManualOrder(BaseModel):
    stock_code: str
    order_type: str  # "buy" or "sell"
    quantity: int
    price: Optional[float] = None  # None이면 시장가

# ============================================================================
# API 엔드포인트
# ============================================================================

@app.get("/", response_class=HTMLResponse)
async def get_dashboard():
    """대시보드 HTML"""
    html_content = """
<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>퀀트 매매 시스템 대시보드</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: #333;
            padding: 20px;
        }
        .container {
            max-width: 1400px;
            margin: 0 auto;
        }
        .header {
            background: white;
            padding: 20px;
            border-radius: 10px;
            margin-bottom: 20px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        }
        .header h1 {
            color: #667eea;
            margin-bottom: 10px;
        }
        .status {
            display: inline-block;
            padding: 5px 15px;
            border-radius: 20px;
            font-weight: bold;
            margin-left: 10px;
        }
        .status.running { background: #4caf50; color: white; }
        .status.stopped { background: #f44336; color: white; }
        .grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(400px, 1fr));
            gap: 20px;
            margin-bottom: 20px;
        }
        .card {
            background: white;
            padding: 20px;
            border-radius: 10px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        }
        .card h2 {
            color: #667eea;
            margin-bottom: 15px;
            border-bottom: 2px solid #667eea;
            padding-bottom: 10px;
        }
        .metric {
            display: flex;
            justify-content: space-between;
            padding: 10px 0;
            border-bottom: 1px solid #eee;
        }
        .metric:last-child { border-bottom: none; }
        .metric-label { color: #666; }
        .metric-value {
            font-weight: bold;
            color: #333;
        }
        .metric-value.positive { color: #4caf50; }
        .metric-value.negative { color: #f44336; }
        button {
            background: #667eea;
            color: white;
            border: none;
            padding: 10px 20px;
            border-radius: 5px;
            cursor: pointer;
            font-size: 14px;
            margin: 5px;
        }
        button:hover { background: #5568d3; }
        button.danger { background: #f44336; }
        button.danger:hover { background: #d32f2f; }
        input, select {
            width: 100%;
            padding: 8px;
            margin: 5px 0;
            border: 1px solid #ddd;
            border-radius: 5px;
        }
        .form-group {
            margin: 10px 0;
        }
        .form-group label {
            display: block;
            margin-bottom: 5px;
            color: #666;
            font-weight: bold;
        }
        table {
            width: 100%;
            border-collapse: collapse;
            margin-top: 10px;
        }
        th, td {
            padding: 10px;
            text-align: left;
            border-bottom: 1px solid #eee;
        }
        th {
            background: #f5f5f5;
            color: #667eea;
            font-weight: bold;
        }
        tr:hover { background: #f9f9f9; }
        .log {
            background: #1e1e1e;
            color: #d4d4d4;
            padding: 15px;
            border-radius: 5px;
            max-height: 400px;
            overflow-y: auto;
            font-family: 'Courier New', monospace;
            font-size: 12px;
        }
        .log-entry {
            margin: 5px 0;
            padding: 5px;
        }
        .log-entry.info { color: #4ec9b0; }
        .log-entry.warning { color: #dcdcaa; }
        .log-entry.error { color: #f48771; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>퀀트 매매 시스템 대시보드 <span id="status" class="status stopped">중지됨</span></h1>
            <p>실시간 모니터링 및 제어</p>
        </div>

        <div class="grid">
            <!-- 시스템 상태 -->
            <div class="card">
                <h2>시스템 상태</h2>
                <div class="metric">
                    <span class="metric-label">환경:</span>
                    <span class="metric-value" id="env">-</span>
                </div>
                <div class="metric">
                    <span class="metric-label">계좌 잔고:</span>
                    <span class="metric-value" id="balance">-</span>
                </div>
                <div class="metric">
                    <span class="metric-label">일일 손익:</span>
                    <span class="metric-value" id="daily_pnl">-</span>
                </div>
                <div class="metric">
                    <span class="metric-label">일일 거래 횟수:</span>
                    <span class="metric-value" id="daily_trades">-</span>
                </div>
                <div style="margin-top: 15px;">
                    <button onclick="startSystem()">시작</button>
                    <button onclick="stopSystem()" class="danger">중지</button>
                    <button onclick="refreshData()">새로고침</button>
                </div>
            </div>

            <!-- 현재 포지션 -->
            <div class="card">
                <h2>현재 포지션</h2>
                <div id="positions">
                    <p style="color: #999;">보유 종목이 없습니다.</p>
                </div>
            </div>

            <!-- 리스크 설정 -->
            <div class="card">
                <h2>리스크 관리 설정</h2>
                <div class="form-group">
                    <label>최대 거래 금액 (원):</label>
                    <input type="number" id="max_trade_amount" value="1000000">
                </div>
                <div class="form-group">
                    <label>손절매 비율 (%):</label>
                    <input type="number" id="stop_loss" value="2" step="0.1">
                </div>
                <div class="form-group">
                    <label>익절매 비율 (%):</label>
                    <input type="number" id="take_profit" value="5" step="0.1">
                </div>
                <div class="form-group">
                    <label>일일 손실 한도 (원):</label>
                    <input type="number" id="daily_loss_limit" value="500000">
                </div>
                <button onclick="updateRiskConfig()">설정 저장</button>
            </div>

            <!-- 종목 선정 기준 -->
            <div class="card">
                <h2>종목 선정 기준</h2>
                <div class="form-group">
                    <label>프리셋 선택:</label>
                    <select id="preset_select" onchange="loadPreset()">
                        <option value="">직접 설정</option>
                        <option value="common">보편적 기준</option>
                        <option value="conservative">보수적 기준</option>
                        <option value="aggressive">공격적 기준</option>
                        <option value="beginner">초보자용 기준</option>
                    </select>
                </div>
                <div class="form-group">
                    <label>최소 상승률 (%):</label>
                    <input type="number" id="min_change" value="1" step="0.1">
                </div>
                <div class="form-group">
                    <label>최대 상승률 (%):</label>
                    <input type="number" id="max_change" value="15" step="0.1">
                </div>
                <div class="form-group">
                    <label>최소 가격 (원):</label>
                    <input type="number" id="min_price" value="1000">
                </div>
                <div class="form-group">
                    <label>최대 가격 (원):</label>
                    <input type="number" id="max_price" value="50000">
                </div>
                <div class="form-group">
                    <label>최소 거래량 (주):</label>
                    <input type="number" id="min_volume" value="50000">
                </div>
                <div class="form-group">
                    <label>최소 거래대금 (원):</label>
                    <input type="number" id="min_trade_amount" value="2000000000" placeholder="20억">
                </div>
                <div class="form-group">
                    <label>최대 선정 종목 수:</label>
                    <input type="number" id="max_stocks" value="5">
                </div>
                <button onclick="updateStockSelection()">설정 저장</button>
                <button onclick="selectStocks()" style="margin-top: 10px;">종목 재선정</button>
            </div>

            <!-- 수동 주문 -->
            <div class="card">
                <h2>수동 주문</h2>
                <div class="form-group">
                    <label>종목코드:</label>
                    <input type="text" id="order_stock_code" placeholder="005930">
                </div>
                <div class="form-group">
                    <label>주문 유형:</label>
                    <select id="order_type">
                        <option value="buy">매수</option>
                        <option value="sell">매도</option>
                    </select>
                </div>
                <div class="form-group">
                    <label>수량:</label>
                    <input type="number" id="order_quantity" value="1">
                </div>
                <div class="form-group">
                    <label>가격 (시장가는 0):</label>
                    <input type="number" id="order_price" value="0" placeholder="0 = 시장가">
                </div>
                <button onclick="executeManualOrder()">주문 실행</button>
            </div>

            <!-- 거래 내역 -->
            <div class="card">
                <h2>거래 내역</h2>
                <div id="trade_history" style="max-height: 300px; overflow-y: auto;">
                    <table>
                        <thead>
                            <tr>
                                <th>시간</th>
                                <th>종목</th>
                                <th>유형</th>
                                <th>수량</th>
                                <th>가격</th>
                                <th>손익</th>
                            </tr>
                        </thead>
                        <tbody id="trade_history_body">
                        </tbody>
                    </table>
                </div>
            </div>
        </div>

        <!-- 시스템 로그 -->
        <div class="card">
            <h2>시스템 로그</h2>
            <div class="log" id="log">
                <div class="log-entry info">대시보드 연결 중...</div>
            </div>
        </div>
    </div>

    <script>
        let ws = null;
        let reconnectInterval = null;

        function connectWebSocket() {
            const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            const wsUrl = `${protocol}//${window.location.host}/ws`;
            
            ws = new WebSocket(wsUrl);
            
            ws.onopen = () => {
                addLog('WebSocket 연결됨', 'info');
                if (reconnectInterval) {
                    clearInterval(reconnectInterval);
                    reconnectInterval = null;
                }
            };
            
            ws.onmessage = (event) => {
                const data = JSON.parse(event.data);
                handleWebSocketMessage(data);
            };
            
            ws.onclose = () => {
                addLog('WebSocket 연결 끊김', 'warning');
                if (!reconnectInterval) {
                    reconnectInterval = setInterval(connectWebSocket, 3000);
                }
            };
            
            ws.onerror = (error) => {
                addLog('WebSocket 오류: ' + error, 'error');
            };
        }

        function handleWebSocketMessage(data) {
            if (data.type === 'status') {
                updateStatus(data.data);
            } else if (data.type === 'position') {
                updatePositions(data.data);
            } else if (data.type === 'trade') {
                addTradeToHistory(data.data);
            } else if (data.type === 'log') {
                addLog(data.message, data.level || 'info');
            }
        }

        function updateStatus(data) {
            document.getElementById('status').textContent = data.is_running ? '실행 중' : '중지됨';
            document.getElementById('status').className = 'status ' + (data.is_running ? 'running' : 'stopped');
            document.getElementById('env').textContent = data.env_name || '-';
            document.getElementById('balance').textContent = formatNumber(data.account_balance) + '원';
            document.getElementById('daily_pnl').textContent = formatNumber(data.daily_pnl) + '원';
            document.getElementById('daily_pnl').className = 'metric-value ' + (data.daily_pnl >= 0 ? 'positive' : 'negative');
            document.getElementById('daily_trades').textContent = data.daily_trades + '회';
        }

        function updatePositions(positions) {
            const container = document.getElementById('positions');
            if (!positions || Object.keys(positions).length === 0) {
                container.innerHTML = '<p style="color: #999;">보유 종목이 없습니다.</p>';
                return;
            }
            
            let html = '<table><thead><tr><th>종목</th><th>수량</th><th>매수가</th><th>현재가</th><th>손익</th><th>손익률</th></tr></thead><tbody>';
            for (const [code, pos] of Object.entries(positions)) {
                const pnl = (pos.current_price - pos.buy_price) * pos.quantity;
                const pnl_ratio = ((pos.current_price / pos.buy_price) - 1) * 100;
                html += `<tr>
                    <td>${code}</td>
                    <td>${pos.quantity}주</td>
                    <td>${formatNumber(pos.buy_price)}원</td>
                    <td>${formatNumber(pos.current_price)}원</td>
                    <td class="${pnl >= 0 ? 'positive' : 'negative'}">${formatNumber(pnl)}원</td>
                    <td class="${pnl >= 0 ? 'positive' : 'negative'}">${pnl_ratio.toFixed(2)}%</td>
                </tr>`;
            }
            html += '</tbody></table>';
            container.innerHTML = html;
        }

        function addTradeToHistory(trade) {
            const tbody = document.getElementById('trade_history_body');
            const row = document.createElement('tr');
            row.innerHTML = `
                <td>${new Date(trade.timestamp).toLocaleTimeString()}</td>
                <td>${trade.stock_code}</td>
                <td>${trade.order_type === 'buy' ? '매수' : '매도'}</td>
                <td>${trade.quantity}주</td>
                <td>${formatNumber(trade.price)}원</td>
                <td class="${trade.pnl >= 0 ? 'positive' : 'negative'}">${trade.pnl ? formatNumber(trade.pnl) + '원' : '-'}</td>
            `;
            tbody.insertBefore(row, tbody.firstChild);
        }

        function addLog(message, level = 'info') {
            const log = document.getElementById('log');
            const entry = document.createElement('div');
            entry.className = 'log-entry ' + level;
            entry.textContent = `[${new Date().toLocaleTimeString()}] ${message}`;
            log.appendChild(entry);
            log.scrollTop = log.scrollHeight;
        }

        function formatNumber(num) {
            return new Intl.NumberFormat('ko-KR').format(num);
        }

        async function startSystem() {
            try {
                const response = await fetch('/api/system/start', { method: 'POST' });
                const data = await response.json();
                if (data.success) {
                    addLog('시스템 시작됨', 'info');
                } else {
                    addLog('시스템 시작 실패: ' + data.message, 'error');
                }
            } catch (error) {
                addLog('오류: ' + error, 'error');
            }
        }

        async function stopSystem() {
            try {
                const response = await fetch('/api/system/stop', { method: 'POST' });
                const data = await response.json();
                if (data.success) {
                    addLog('시스템 중지됨', 'info');
                } else {
                    addLog('시스템 중지 실패: ' + data.message, 'error');
                }
            } catch (error) {
                addLog('오류: ' + error, 'error');
            }
        }

        async function refreshData() {
            try {
                const response = await fetch('/api/system/status');
                const data = await response.json();
                updateStatus(data);
            } catch (error) {
                addLog('새로고침 오류: ' + error, 'error');
            }
        }

        async function updateRiskConfig() {
            try {
                const config = {
                    max_single_trade_amount: parseInt(document.getElementById('max_trade_amount').value),
                    stop_loss_ratio: parseFloat(document.getElementById('stop_loss').value) / 100,
                    take_profit_ratio: parseFloat(document.getElementById('take_profit').value) / 100,
                    daily_loss_limit: parseInt(document.getElementById('daily_loss_limit').value),
                    max_trades_per_day: 5,
                    max_position_size_ratio: 0.1
                };
                const response = await fetch('/api/config/risk', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(config)
                });
                const data = await response.json();
                if (data.success) {
                    addLog('리스크 설정 저장됨', 'info');
                } else {
                    addLog('설정 저장 실패: ' + data.message, 'error');
                }
            } catch (error) {
                addLog('오류: ' + error, 'error');
            }
        }

        async function loadPreset() {
            const presetName = document.getElementById('preset_select').value;
            if (!presetName) return;
            
            try {
                const response = await fetch(`/api/config/preset/${presetName}`);
                const data = await response.json();
                if (data.success) {
                    const preset = data.preset;
                    document.getElementById('min_change').value = (preset.min_price_change_ratio * 100).toFixed(1);
                    document.getElementById('max_change').value = (preset.max_price_change_ratio * 100).toFixed(1);
                    document.getElementById('min_price').value = preset.min_price;
                    document.getElementById('max_price').value = preset.max_price;
                    document.getElementById('min_volume').value = preset.min_volume;
                    document.getElementById('min_trade_amount').value = preset.min_trade_amount || 0;
                    document.getElementById('max_stocks').value = preset.max_stocks;
                    addLog(`프리셋 로드: ${preset.name}`, 'info');
                }
            } catch (error) {
                addLog('프리셋 로드 오류: ' + error, 'error');
            }
        }

        async function updateStockSelection() {
            try {
                const config = {
                    min_price_change_ratio: parseFloat(document.getElementById('min_change').value) / 100,
                    max_price_change_ratio: parseFloat(document.getElementById('max_change').value) / 100,
                    min_price: parseInt(document.getElementById('min_price').value),
                    max_price: parseInt(document.getElementById('max_price').value),
                    min_volume: parseInt(document.getElementById('min_volume').value),
                    min_trade_amount: parseInt(document.getElementById('min_trade_amount').value) || 0,
                    max_stocks: parseInt(document.getElementById('max_stocks').value),
                    exclude_risk_stocks: true
                };
                const response = await fetch('/api/config/stock-selection', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(config)
                });
                const data = await response.json();
                if (data.success) {
                    addLog('종목 선정 기준 저장됨', 'info');
                } else {
                    addLog('설정 저장 실패: ' + data.message, 'error');
                }
            } catch (error) {
                addLog('오류: ' + error, 'error');
            }
        }

        async function selectStocks() {
            try {
                addLog('종목 재선정 중...', 'info');
                const response = await fetch('/api/stocks/select', { method: 'POST' });
                const data = await response.json();
                if (data.success) {
                    addLog(`종목 선정 완료: ${data.stocks.join(', ')}`, 'info');
                } else {
                    addLog('종목 선정 실패: ' + data.message, 'error');
                }
            } catch (error) {
                addLog('오류: ' + error, 'error');
            }
        }

        async function executeManualOrder() {
            try {
                const order = {
                    stock_code: document.getElementById('order_stock_code').value,
                    order_type: document.getElementById('order_type').value,
                    quantity: parseInt(document.getElementById('order_quantity').value),
                    price: parseFloat(document.getElementById('order_price').value) || None
                };
                const response = await fetch('/api/order/manual', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(order)
                });
                const data = await response.json();
                if (data.success) {
                    addLog(`주문 실행: ${order.order_type} ${order.stock_code} ${order.quantity}주`, 'info');
                } else {
                    addLog('주문 실패: ' + data.message, 'error');
                }
            } catch (error) {
                addLog('오류: ' + error, 'error');
            }
        }

        // 초기화
        connectWebSocket();
        refreshData();
        setInterval(refreshData, 5000); // 5초마다 상태 업데이트
    </script>
</body>
</html>
    """
    return html_content

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket 연결"""
    await websocket.accept()
    state.websocket_clients.append(websocket)
    
    try:
        # 초기 상태 전송
        await send_status_update()
        
        while True:
            # 클라이언트로부터 메시지 수신 (필요시)
            data = await websocket.receive_text()
            # 필요시 처리
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
        
        # 포지션 업데이트
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

@app.get("/api/system/status")
async def get_system_status():
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
async def start_system():
    """시스템 시작"""
    try:
        if state.is_running:
            return JSONResponse({"success": False, "message": "이미 실행 중입니다."})
        
        # 시스템 초기화 (필요시)
        # 실제로는 별도 스레드에서 실행되어야 함
        state.is_running = True
        await send_status_update()
        
        return JSONResponse({"success": True, "message": "시스템이 시작되었습니다."})
    except Exception as e:
        logger.error(f"시스템 시작 오류: {e}")
        return JSONResponse({"success": False, "message": str(e)})

@app.post("/api/system/stop")
async def stop_system():
    """시스템 중지"""
    try:
        state.is_running = False
        await send_status_update()
        return JSONResponse({"success": True, "message": "시스템이 중지되었습니다."})
    except Exception as e:
        logger.error(f"시스템 중지 오류: {e}")
        return JSONResponse({"success": False, "message": str(e)})

@app.get("/api/positions")
async def get_positions():
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
async def get_trades(limit: int = 50):
    """거래 내역 조회"""
    return JSONResponse(state.trade_history[-limit:])

@app.post("/api/config/risk")
async def update_risk_config(config: RiskConfig):
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
async def get_preset(preset_name: str):
    """프리셋 가져오기"""
    try:
        preset = get_preset(preset_name)
        return JSONResponse({"success": True, "preset": preset})
    except Exception as e:
        logger.error(f"프리셋 가져오기 오류: {e}")
        return JSONResponse({"success": False, "message": str(e)})

@app.get("/api/config/presets")
async def list_all_presets():
    """모든 프리셋 목록"""
    try:
        presets = list_presets()
        return JSONResponse({"success": True, "presets": presets})
    except Exception as e:
        logger.error(f"프리셋 목록 조회 오류: {e}")
        return JSONResponse({"success": False, "message": str(e)})

@app.post("/api/config/stock-selection")
async def update_stock_selection_config(config: StockSelectionConfig):
    """종목 선정 기준 업데이트"""
    try:
        state.stock_selector = StockSelector(
            env_dv="demo" if state.is_paper_trading else "real",
            min_price_change_ratio=config.min_price_change_ratio,
            max_price_change_ratio=config.max_price_change_ratio,
            min_price=config.min_price,
            max_price=config.max_price,
            min_volume=config.min_volume,
            max_stocks=config.max_stocks,
            exclude_risk_stocks=config.exclude_risk_stocks
        )
        
        await state.broadcast({"type": "log", "message": "종목 선정 기준이 업데이트되었습니다.", "level": "info"})
        return JSONResponse({"success": True})
    except Exception as e:
        logger.error(f"종목 선정 기준 업데이트 오류: {e}")
        return JSONResponse({"success": False, "message": str(e)})

@app.post("/api/stocks/select")
async def select_stocks():
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
async def execute_manual_order(order: ManualOrder):
    """수동 주문 실행"""
    try:
        if not state.strategy or not state.trenv:
            return JSONResponse({"success": False, "message": "시스템이 초기화되지 않았습니다."})
        
        # 주문 실행 (실제로는 별도 스레드에서 실행)
        # 여기서는 시뮬레이션
        result = safe_execute_order(
            signal=order.order_type,
            stock_code=order.stock_code,
            price=order.price or 0,  # 시장가
            strategy=state.strategy,
            trenv=state.trenv,
            is_paper_trading=state.is_paper_trading,
            manual_approval=False  # 대시보드에서 승인했으므로
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
# 시스템 초기화 함수
# ============================================================================

def initialize_trading_system(
    account_balance: float = 100000,
    is_paper_trading: bool = True
):
    """거래 시스템 초기화"""
    try:
        # KIS API 인증
        svr = "vps" if is_paper_trading else "prod"
        ka.changeTREnv(None, svr=svr, product="01")
        ka.auth()
        ka.auth_ws()
        trenv = ka.getTREnv()
        
        # 리스크 관리자 및 전략 초기화
        risk_manager = RiskManager(account_balance=account_balance)
        strategy = QuantStrategy(risk_manager)
        
        # 종목 선정기 초기화
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
        
        # 상태 업데이트
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

# ============================================================================
# 메인 실행
# ============================================================================

if __name__ == "__main__":
    import uvicorn
    
    # 시스템 초기화
    initialize_trading_system(account_balance=100000, is_paper_trading=True)
    
    # 서버 시작
    print("=" * 80)
    print("퀀트 매매 시스템 대시보드 시작")
    print("=" * 80)
    print("웹 브라우저에서 http://localhost:8000 접속")
    print("종료하려면 Ctrl+C를 누르세요")
    print("=" * 80)
    
    uvicorn.run(app, host="0.0.0.0", port=8000)
