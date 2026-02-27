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
        self.is_running = False
        self.websocket_clients: List[WebSocket] = []
        self.trade_history: List[Dict] = []
        self.current_positions: Dict[str, Dict] = {}
        self.selected_stocks: List[str] = []
        self.stock_selector: Optional[StockSelector] = None
        self.pending_signals: Dict[str, Dict] = {}
        self.engine_thread = None
        self.engine_running = False
        
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
    min_trade_amount: int = 0
    max_stocks: int
    exclude_risk_stocks: bool

class StrategyConfig(BaseModel):
    short_ma_period: int
    long_ma_period: int

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
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 20px;
        }
        .login-container {
            background: white;
            border-radius: 20px;
            padding: 30px;
            width: 100%;
            max-width: 400px;
            box-shadow: 0 10px 40px rgba(0,0,0,0.2);
        }
        .login-header {
            text-align: center;
            margin-bottom: 30px;
        }
        .login-header h1 {
            color: #667eea;
            font-size: 28px;
            margin-bottom: 10px;
        }
        .login-header p {
            color: #666;
            font-size: 14px;
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
            transition: border-color 0.3s;
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
            transition: background 0.3s;
            margin-top: 10px;
        }
        .btn:hover { background: #5568d3; }
        .btn:active { transform: scale(0.98); }
        .btn-secondary {
            background: #6c757d;
        }
        .btn-secondary:hover { background: #5a6268; }
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
            <a href="/register">계정이 없으신가요? 회원가입</a>
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
