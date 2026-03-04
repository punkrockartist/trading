"""
퀀트 매매 시스템 웹 대시보드 (FastAPI) - 모바일 최적화 + 로그인

기능:
1. 모바일 반응형 UI
2. 로그인/회원가입
3. JWT 토큰 기반 인증
4. DynamoDB 또는 인메모리 사용자 저장소
5. 실시간 모니터링
"""

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Depends, Request, status, Cookie
from starlette.requests import Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Dict, List, Optional
import json
import logging
from datetime import datetime
from pydantic import BaseModel
import uvicorn

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
from auth_manager import auth_manager, AuthManager

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# FastAPI 앱 생성
app = FastAPI(title="퀀트 매매 시스템 대시보드")

# JWT 보안
security = HTTPBearer(auto_error=False)

# 전역 상태 관리
class TradingState:
    """거래 시스템 상태 관리"""
    def __init__(self):
        self.risk_manager: Optional[RiskManager] = None
        self.strategy: Optional[QuantStrategy] = None
        self.trenv = None
        self.is_paper_trading = True
        self.manual_approval = True  # True: 승인대기 후 수동 처리, False: 신호 발생 시 자동 매수/매도
        self.is_running = False
        self.websocket_clients: List[WebSocket] = []
        self.trade_history: List[Dict] = []
        self.current_positions: Dict[str, Dict] = {}
        self.selected_stocks: List[str] = []
        self.stock_selector: Optional[StockSelector] = None
        self.pending_signals: Dict[str, Dict] = {}
        self.engine_thread = None
        self.engine_running = False
        # 신규 매수 허용 시간(한국시간, HH:MM). 매도/청산은 항상 허용.
        self.buy_window_start_hhmm: str = "09:05"
        self.buy_window_end_hhmm: str = "11:30"
        # 실시간 호가(스프레드) 캐시: {code: {"ask": float, "bid": float, "at": iso}}
        self.latest_quotes: Dict[str, Dict] = {}
        
    async def broadcast(self, message: dict):
        """모든 WebSocket 클라이언트에 메시지 전송"""
        disconnected = []
        for client in self.websocket_clients:
            try:
                await client.send_json(message)
            except:
                disconnected.append(client)
        
        for client in disconnected:
            if client in self.websocket_clients:
                self.websocket_clients.remove(client)
    
    def add_trade(self, trade_info: dict):
        """거래 내역 추가"""
        trade_info["timestamp"] = datetime.now().isoformat()
        self.trade_history.append(trade_info)
        if len(self.trade_history) > 100:
            self.trade_history = self.trade_history[-100:]

state = TradingState()

# Pydantic 모델
class LoginRequest(BaseModel):
    username: str
    password: str

class RegisterRequest(BaseModel):
    username: str
    password: str
    email: str = ""

class RiskConfig(BaseModel):
    max_single_trade_amount: int
    min_order_quantity: int = 1
    stop_loss_ratio: float
    take_profit_ratio: float
    daily_loss_limit: int
    daily_profit_limit: int = 0  # 0이면 사용 안 함 (원). 도달 시 신규 매수 차단 + 전량매도 트리거에 사용 가능
    daily_total_loss_limit: int = 0  # 0이면 사용 안 함 (원). (실현+미실현) 합산이 -한도 이하이면 전량매도 + 신규매수 차단
    # 일일 손익 한도 기준(실현/실현+미실현)
    daily_profit_limit_basis: str = "total"  # realized | total
    daily_loss_limit_basis: str = "realized"  # realized | total
    # 주문 실행 방식/재시도
    buy_order_style: str = "market"  # market | best_limit
    sell_order_style: str = "market"  # market | best_limit
    order_retry_count: int = 0
    order_retry_delay_ms: int = 300
    order_fallback_to_market: bool = True
    # 변동성 기반 포지션 사이징 + 종목당 최대 손실액
    enable_volatility_sizing: bool = False
    volatility_lookback_ticks: int = 20
    volatility_stop_mult: float = 1.0
    max_loss_per_stock_krw: int = 0  # 0이면 사용 안 함
    max_trades_per_day: int
    max_position_size_ratio: float
    trailing_stop_ratio: float = 0.0
    trailing_activation_ratio: float = 0.0
    partial_take_profit_ratio: float = 0.0
    partial_take_profit_fraction: float = 0.5

class StockSelectionConfig(BaseModel):
    min_price_change_ratio: float
    max_price_change_ratio: float
    min_price: int
    max_price: int
    min_volume: int
    min_trade_amount: int = 0
    max_stocks: int
    exclude_risk_stocks: bool
    # 정렬 기준(최종 후보 중 무엇을 우선으로 뽑을지)
    # - change: 등락률(기본, API 랭킹 그대로)
    # - trade_amount: (가능할 때) 당일 누적 거래대금 우선
    # - prev_day_trade_value: 전일 거래대금(또는 거래량*종가) 우선 (비용↑, 상위 pool만 조회)
    sort_by: str = "change"
    # prev_day_trade_value 정렬 시 조회할 후보 pool 크기 (비용 제한)
    prev_day_rank_pool_size: int = 80
    # 장초/장중 품질 개선 옵션 (기존 env 기반 옵션을 UI로 노출)
    market_open_hhmm: str = "09:00"
    warmup_minutes: int = 5
    early_strict: bool = False
    early_strict_minutes: int = 30
    early_min_volume: int = 200000
    early_min_trade_amount: int = 0
    exclude_drawdown: bool = False
    max_drawdown_from_high_ratio: float = 0.02
    drawdown_filter_after_hhmm: str = "12:00"

class StrategyConfig(BaseModel):
    short_ma_period: int
    long_ma_period: int
    buy_window_start_hhmm: str = "09:05"
    buy_window_end_hhmm: str = "11:30"
    min_short_ma_slope_ratio: float = 0.0
    # 모멘텀(추가 진입 필터): lookback N틱 전 대비 상승률
    momentum_lookback_ticks: int = 0
    min_momentum_ratio: float = 0.0
    # 진입 보강(2단): 추세 조건 + (아래 조건 중 N개 이상) 만족 시에만 매수
    entry_confirm_enabled: bool = False
    entry_confirm_min_count: int = 1
    confirm_breakout_enabled: bool = False
    breakout_lookback_ticks: int = 20
    breakout_buffer_ratio: float = 0.0
    confirm_volume_surge_enabled: bool = False
    volume_surge_lookback_ticks: int = 20
    volume_surge_ratio: float = 2.0
    confirm_trade_value_surge_enabled: bool = False
    trade_value_surge_lookback_ticks: int = 20
    trade_value_surge_ratio: float = 2.0
    # 변동성 정규화(보조): 평균 변동폭 대비 slope/range 기준을 추가로 적용
    vol_norm_lookback_ticks: int = 20
    slope_vs_vol_mult: float = 0.0
    range_vs_vol_mult: float = 0.0
    # 오전장 레짐 분기(초반/메인): 초반(예: 09:00~09:10)에는 다른 임계값 적용
    enable_morning_regime_split: bool = False
    morning_regime_early_end_hhmm: str = "09:10"
    early_min_short_ma_slope_ratio: float = 0.0
    early_momentum_lookback_ticks: int = 0
    early_min_momentum_ratio: float = 0.0
    early_buy_confirm_ticks: int = 1
    early_max_spread_ratio: float = 0.0
    early_range_lookback_ticks: int = 0
    early_min_range_ratio: float = 0.0
    # 진입 직전 추가 필터(피크 추격 완화/초단기 추세 유지)
    avoid_chase_near_high_enabled: bool = False
    near_high_lookback_minutes: int = 2
    avoid_near_high_ratio: float = 0.003  # 0.003=0.3% 이내(고점에 너무 근접하면 스킵)
    # 변동성 기반으로 고점근접 회피 임계값을 자동 상향(피크 추격 더 강하게 차단)
    avoid_near_high_dynamic: bool = False
    avoid_near_high_vs_vol_mult: float = 0.0
    minute_trend_enabled: bool = False
    minute_trend_lookback_bars: int = 2  # 1~2분봉 추세 유지(최근 N개)
    minute_trend_min_green_bars: int = 2  # 최근 N개 중 양봉 최소 개수
    minute_trend_mode: str = "green"  # green | higher_close | higher_low | hh_hl
    minute_trend_early_only: bool = False
    reentry_cooldown_seconds: int = 0
    buy_confirm_ticks: int = 1
    enable_time_liquidation: bool = False
    liquidate_after_hhmm: str = "11:55"
    # 스프레드/횡보장 필터(0이면 사용 안 함)
    max_spread_ratio: float = 0.0  # 예: 0.001 = 0.1%
    range_lookback_ticks: int = 0
    min_range_ratio: float = 0.0  # 예: 0.003 = 0.3%

class ManualOrder(BaseModel):
    stock_code: str
    order_type: str
    quantity: int
    price: Optional[float] = None

# ============================================================================
# 인증 의존성
# ============================================================================

async def get_current_user(
    token: Optional[str] = Cookie(None),
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)
) -> str:
    """현재 사용자 확인"""
    # 쿠키에서 토큰 확인
    if token:
        username = auth_manager.verify_token(token)
        if username:
            return username
    
    # Authorization 헤더에서 토큰 확인
    if credentials:
        username = auth_manager.verify_token(credentials.credentials)
        if username:
            return username
    
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="인증이 필요합니다",
        headers={"WWW-Authenticate": "Bearer"},
    )

# ============================================================================
# 로그인/회원가입 페이지
# ============================================================================

@app.get("/login", response_class=HTMLResponse)
async def login_page():
    """로그인 페이지"""
    return get_login_html()

@app.get("/register", response_class=HTMLResponse)
async def register_page():
    """회원가입 페이지"""
    return get_register_html()

@app.post("/api/auth/login")
async def login(login_data: LoginRequest, response: JSONResponse):
    """로그인"""
    token = auth_manager.authenticate(login_data.username, login_data.password)
    if not token:
        raise HTTPException(status_code=401, detail="사용자명 또는 비밀번호가 잘못되었습니다")
    
    response = JSONResponse({"success": True, "token": token})
    response.set_cookie(key="token", value=token, httponly=True, max_age=86400, samesite="lax")
    return response

@app.post("/api/auth/register")
async def register(register_data: RegisterRequest):
    """회원가입"""
    success = auth_manager.register(register_data.username, register_data.password, register_data.email)
    if not success:
        raise HTTPException(status_code=400, detail="이미 존재하는 사용자명입니다")
    return JSONResponse({"success": True, "message": "회원가입이 완료되었습니다"})

@app.post("/api/auth/logout")
async def logout():
    """로그아웃"""
    response = JSONResponse({"success": True})
    response.delete_cookie(key="token")
    return response

# ============================================================================
# 대시보드 페이지 (인증 필요)
# ============================================================================

@app.get("/", response_class=HTMLResponse)
async def get_dashboard(request: Request):
    """대시보드 HTML (모바일 최적화)"""
    # 인증 확인
    token = request.cookies.get("token")
    if token:
        username = auth_manager.verify_token(token)
        if username:
            from dashboard_html_mobile import get_dashboard_html_mobile
            return get_dashboard_html_mobile(username)
    
    # 인증 실패 시 로그인 페이지로 리다이렉트
    return RedirectResponse(url="/login", status_code=302)

def get_login_html() -> str:
    """로그인 페이지 HTML"""
    return """
<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <meta name="apple-mobile-web-app-capable" content="yes">
    <title>로그인 - 퀀트 매매 시스템</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            background: #f2f3f3;
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 20px;
        }
        .login-container {
            background: #ffffff;
            color: #0f1b2d;
            border-radius: 20px;
            padding: 30px;
            width: 100%;
            max-width: 400px;
            box-shadow: 0 18px 55px rgba(0,0,0,0.12);
            border: 1px solid #d5dbdb;
        }
        .login-header {
            text-align: center;
            margin-bottom: 30px;
        }
        .login-header h1 {
            color: #0f1b2d;
            font-size: 28px;
            margin-bottom: 10px;
            letter-spacing: -0.2px;
        }
        .login-header p {
            color: #5f6b7a;
            font-size: 14px;
        }
        .form-group {
            margin-bottom: 20px;
        }
        .form-group label {
            display: block;
            color: #5f6b7a;
            font-weight: 600;
            margin-bottom: 8px;
            font-size: 14px;
        }
        .form-group input {
            width: 100%;
            padding: 14px;
            background: #ffffff;
            border: 1px solid #d5dbdb;
            color: #0f1b2d;
            border-radius: 10px;
            font-size: 16px;
            transition: border-color 0.25s, box-shadow 0.25s, background 0.25s;
        }
        .form-group input::placeholder { color: rgba(95, 107, 122, 0.75); }
        .form-group input:focus {
            outline: none;
            border-color: #0972d3;
            box-shadow: 0 0 0 4px rgba(9, 114, 211, 0.18);
            background: #ffffff;
        }
        .btn {
            width: 100%;
            padding: 14px;
            background: #0972d3;
            color: white;
            border: none;
            border-radius: 10px;
            font-size: 16px;
            font-weight: 600;
            cursor: pointer;
            transition: transform 0.08s, filter 0.25s;
            margin-top: 10px;
        }
        .btn:hover { filter: brightness(0.95); }
        .btn:active { transform: scale(0.98); }
        .btn-secondary {
            background: #6c757d;
        }
        .btn-secondary:hover { background: #5a6268; }
        .error-message {
            color: #d13212;
            font-size: 14px;
            margin-top: 10px;
            text-align: center;
            display: none;
        }
        .link {
            text-align: center;
            margin-top: 20px;
        }
        .link a {
            color: #0972d3;
            text-decoration: none;
            font-size: 14px;
        }
        @media (max-width: 480px) {
            .login-container {
                padding: 20px;
                border-radius: 15px;
            }
            .login-header h1 {
                font-size: 24px;
            }
        }
    </style>
</head>
<body>
    <div class="login-container">
        <div class="login-header">
            <h1>퀀트 매매 시스템</h1>
            <p>로그인하여 시작하세요</p>
        </div>
        <form id="loginForm">
            <div class="form-group">
                <label>사용자명</label>
                <input type="text" id="username" required autocomplete="username">
            </div>
            <div class="form-group">
                <label>비밀번호</label>
                <input type="password" id="password" required autocomplete="current-password">
            </div>
            <div class="error-message" id="errorMessage"></div>
            <button type="submit" class="btn">로그인</button>
        </form>
        <div class="link">
            <!--
            <a href="/register">계정이 없으신가요? 회원가입</a>
            -->
        </div>
    </div>
    <script>
        document.getElementById('loginForm').addEventListener('submit', async (e) => {
            e.preventDefault();
            const username = document.getElementById('username').value;
            const password = document.getElementById('password').value;
            const errorMsg = document.getElementById('errorMessage');
            
            try {
                const response = await fetch('/api/auth/login', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ username, password })
                });
                
                const data = await response.json();
                if (data.success) {
                    window.location.href = '/';
                } else {
                    errorMsg.textContent = data.detail || '로그인 실패';
                    errorMsg.style.display = 'block';
                }
            } catch (error) {
                errorMsg.textContent = '로그인 중 오류가 발생했습니다';
                errorMsg.style.display = 'block';
            }
        });
    </script>
</body>
</html>
    """

def get_register_html() -> str:
    """회원가입 페이지 HTML"""
    return """
<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>회원가입 - 퀀트 매매 시스템</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 20px;
        }
        .register-container {
            background: white;
            border-radius: 20px;
            padding: 30px;
            width: 100%;
            max-width: 400px;
            box-shadow: 0 10px 40px rgba(0,0,0,0.2);
        }
        .register-header {
            text-align: center;
            margin-bottom: 30px;
        }
        .register-header h1 {
            color: #667eea;
            font-size: 28px;
            margin-bottom: 10px;
        }
        .form-group {
            margin-bottom: 20px;
        }
        .form-group label {
            display: block;
            color: #333;
            font-weight: 600;
            margin-bottom: 8px;
            font-size: 14px;
        }
        .form-group input {
            width: 100%;
            padding: 14px;
            border: 2px solid #e0e0e0;
            border-radius: 10px;
            font-size: 16px;
        }
        .form-group input:focus {
            outline: none;
            border-color: #667eea;
        }
        .btn {
            width: 100%;
            padding: 14px;
            background: #667eea;
            color: white;
            border: none;
            border-radius: 10px;
            font-size: 16px;
            font-weight: 600;
            cursor: pointer;
            margin-top: 10px;
        }
        .btn:hover { background: #5568d3; }
        .error-message {
            color: #f44336;
            font-size: 14px;
            margin-top: 10px;
            text-align: center;
            display: none;
        }
        .link {
            text-align: center;
            margin-top: 20px;
        }
        .link a {
            color: #667eea;
            text-decoration: none;
            font-size: 14px;
        }
    </style>
</head>
<body>
    <div class="register-container">
        <div class="register-header">
            <h1>회원가입</h1>
        </div>
        <form id="registerForm">
            <div class="form-group">
                <label>사용자명</label>
                <input type="text" id="username" required autocomplete="username">
            </div>
            <div class="form-group">
                <label>비밀번호</label>
                <input type="password" id="password" required autocomplete="new-password">
            </div>
            <div class="form-group">
                <label>이메일 (선택)</label>
                <input type="email" id="email" autocomplete="email">
            </div>
            <div class="error-message" id="errorMessage"></div>
            <button type="submit" class="btn">회원가입</button>
        </form>
        <div class="link">
            <a href="/login">이미 계정이 있으신가요? 로그인</a>
        </div>
    </div>
    <script>
        document.getElementById('registerForm').addEventListener('submit', async (e) => {
            e.preventDefault();
            const username = document.getElementById('username').value;
            const password = document.getElementById('password').value;
            const email = document.getElementById('email').value;
            const errorMsg = document.getElementById('errorMessage');
            
            try {
                const response = await fetch('/api/auth/register', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ username, password, email })
                });
                
                const data = await response.json();
                if (data.success) {
                    alert('회원가입이 완료되었습니다. 로그인해주세요.');
                    window.location.href = '/login';
                } else {
                    errorMsg.textContent = data.detail || '회원가입 실패';
                    errorMsg.style.display = 'block';
                }
            } catch (error) {
                errorMsg.textContent = '회원가입 중 오류가 발생했습니다';
                errorMsg.style.display = 'block';
            }
        });
    </script>
</body>
</html>
    """

def get_dashboard_html(username: str) -> str:
    """대시보드 HTML (모바일 최적화)"""
    from dashboard_html_mobile import get_dashboard_html_mobile
    return get_dashboard_html_mobile(username)

# API 엔드포인트 로드
from quant_dashboard_mobile_api import *

# ============================================================================
# 메인 실행
# ============================================================================

if __name__ == "__main__":
    from quant_dashboard_mobile_api import initialize_trading_system
    
    # 시스템 초기화
    initialize_trading_system(account_balance=100000, is_paper_trading=True)
    
    print("=" * 80)
    print("퀀트 매매 시스템 대시보드 (모바일 최적화) 시작")
    print("=" * 80)
    print("웹 브라우저에서 http://localhost:8000 접속")
    print("기본 계정: admin / admin123")
    print("종료하려면 Ctrl+C를 누르세요")
    print("=" * 80)
    
    uvicorn.run(app, host="0.0.0.0", port=8000)
