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
from typing import Any, Dict, List, Optional
from collections import deque
import json
import logging
from datetime import datetime
from pydantic import BaseModel, Field
import uvicorn
import os
import signal
import threading
import traceback
import faulthandler

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

# 대시보드(Uvicorn) 생명주기: system_*.log에 시작/정상 종료/비정상 종료 흔적
_dashboard_fastapi_shutdown_done: bool = False
_dashboard_uvicorn_fatal_logged: bool = False
_dashboard_atexit_registered: bool = False
_dashboard_signal_handlers_registered: bool = False
_dashboard_excepthook_registered: bool = False
_dashboard_fault_log_opened = None


def ensure_dashboard_atexit_registered() -> None:
    """비정상 종료 추정(atexit) 로그를 한 번만 등록."""
    global _dashboard_atexit_registered
    if _dashboard_atexit_registered:
        return
    import atexit

    atexit.register(_atexit_dashboard_if_abrupt)
    _dashboard_atexit_registered = True


def _record_dashboard_http_shutdown_graceful() -> None:
    """FastAPI shutdown 훅에서 호출 (Uvicorn 정상 종료 시)."""
    global _dashboard_fastapi_shutdown_done
    if _dashboard_fastapi_shutdown_done:
        return
    _dashboard_fastapi_shutdown_done = True
    try:
        from system_log import system_log_append

        system_log_append("info", "대시보드 HTTP 서비스 종료 (FastAPI/Uvicorn 정상 shutdown)")
    except Exception:
        pass


def _record_dashboard_uvicorn_exception(exc: BaseException) -> None:
    """uvicorn.run()이 예외로 빠질 때 atexit 비정상 추정과 중복되지 않도록 기록."""
    global _dashboard_uvicorn_fatal_logged, _dashboard_fastapi_shutdown_done
    _dashboard_uvicorn_fatal_logged = True
    _dashboard_fastapi_shutdown_done = True
    try:
        from system_log import system_log_append

        system_log_append("error", f"대시보드 Uvicorn 실행 예외 종료: {type(exc).__name__}: {exc}")
    except Exception:
        pass


def _atexit_dashboard_if_abrupt() -> None:
    """정상 shutdown 로그가 없이 프로세스가 끝나는 경우에만 기록 (강제 종료·크래시 등)."""
    if _dashboard_fastapi_shutdown_done or _dashboard_uvicorn_fatal_logged:
        return
    try:
        from system_log import system_log_append

        system_log_append(
            "warning",
            "대시보드 프로세스 종료: 정상 HTTP shutdown 기록 없음 (강제 종료·크래시·SIGKILL·OS 종료 등 가능)",
        )
    except Exception:
        pass


def _log_system_event(level: str, message: str) -> None:
    try:
        from system_log import system_log_append
        system_log_append(level, message)
    except Exception:
        pass


def _install_dashboard_fault_handler() -> None:
    global _dashboard_fault_log_opened
    if _dashboard_fault_log_opened is not None:
        return
    try:
        log_dir = os.path.join(os.path.dirname(__file__), "logs")
        os.makedirs(log_dir, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        fault_path = os.path.join(log_dir, f"dashboard_fault_{ts}.log")
        fp = open(fault_path, "a", encoding="utf-8")
        faulthandler.enable(file=fp, all_threads=True)
        _dashboard_fault_log_opened = fp
        _log_system_event("info", f"faulthandler 활성화: {fault_path}")
    except Exception as e:
        _log_system_event("warning", f"faulthandler 활성화 실패: {type(e).__name__}: {e}")


def _register_dashboard_signal_handlers() -> None:
    global _dashboard_signal_handlers_registered
    if _dashboard_signal_handlers_registered:
        return

    def _handler(signum, _frame):
        sig_name = getattr(signal, "Signals", None)
        if sig_name:
            try:
                name = signal.Signals(signum).name
            except Exception:
                name = str(signum)
        else:
            name = str(signum)
        _log_system_event("warning", f"대시보드 종료 시그널 수신: {name}({signum})")

    for s in (getattr(signal, "SIGINT", None), getattr(signal, "SIGTERM", None), getattr(signal, "SIGBREAK", None)):
        if s is None:
            continue
        try:
            signal.signal(s, _handler)
        except Exception:
            continue

    _dashboard_signal_handlers_registered = True


def _register_dashboard_excepthooks() -> None:
    global _dashboard_excepthook_registered
    if _dashboard_excepthook_registered:
        return

    def _sys_excepthook(exc_type, exc_value, exc_tb):
        tb = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        _log_system_event("error", f"대시보드 미처리 예외(sys.excepthook): {exc_type.__name__}: {exc_value}\n{tb}")

    def _thread_excepthook(args):
        tb = "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback))
        _log_system_event(
            "error",
            f"대시보드 스레드 미처리 예외(threading.excepthook): thread={getattr(args.thread, 'name', '?')} "
            f"{args.exc_type.__name__}: {args.exc_value}\n{tb}",
        )

    try:
        sys.excepthook = _sys_excepthook
    except Exception:
        pass

    try:
        threading.excepthook = _thread_excepthook
    except Exception:
        pass

    _dashboard_excepthook_registered = True


def initialize_dashboard_runtime_guards() -> None:
    _install_dashboard_fault_handler()
    _register_dashboard_signal_handlers()
    _register_dashboard_excepthooks()


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
        self.consecutive_losses: int = 0  # 연속 손실 횟수 (매도 체결 시 갱신)
        self.last_consecutive_loss_time: Optional[float] = None  # 마지막 손실 매도 시각 (time.time())
        self.current_positions: Dict[str, Dict] = {}
        self.selected_stocks: List[str] = []
        self.stock_selector: Optional[StockSelector] = None
        self.pending_signals: Dict[str, Dict] = {}
        self.engine_thread = None
        self.engine_running = False
        # 신규 매수 허용 시간(한국시간, HH:MM). 매도/청산은 항상 허용.
        self.buy_window_start_hhmm: str = "09:05"
        self.buy_window_end_hhmm: str = "11:30"
        # 실시간 호가 캐시: 1~5호가 가격·잔량, 총잔량, depth5 요약(WS)
        self.latest_quotes: Dict[str, Dict] = {}
        # 체결 틱 링버퍼(종목별 고정 maxlen): (time.time(), price, cntg_vol)
        self._exec_tick_ring: Dict[str, deque] = {}
        # 장운영 WS(H0STMKO0) VI 적용 여부: 종목코드 -> (active: bool, time.time() 수신시각)
        self._vi_ws_active: Dict[str, tuple] = {}
        # 통합 시장 레짐: 저장 베이스(오버레이 없음) + 현재 라벨
        self._strategy_config_snapshot: Dict[str, Any] = {}
        self._unified_regime_base_strategy: Dict[str, Any] = {}
        self._unified_regime_base_risk: Dict[str, Any] = {}
        self.unified_regime_active_label: str = "neutral"
        self._unified_regime_pending_label: Optional[str] = None
        self._unified_regime_pending_streak: int = 0
        self._unified_regime_last_eval_ts: float = 0.0

    async def broadcast(self, message: dict):
        """모든 WebSocket 클라이언트에 메시지 전송. type=log 시 시스템 로그 파일에도 기록."""
        if isinstance(message, dict) and message.get("type") == "log":
            try:
                from system_log import system_log_append
                system_log_append(message.get("level", "info"), message.get("message", ""))
            except Exception:
                pass
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
        """거래 내역 추가 (메모리 + quant_trading_user_hist, 10일 보관)"""
        import time as _time
        if trade_info.get("stock_code") and "stock_name" not in trade_info:
            code = str(trade_info["stock_code"]).strip().zfill(6)
            for item in (getattr(self, "selected_stock_info", None) or []):
                if str(item.get("code", "")).strip().zfill(6) == code:
                    trade_info["stock_name"] = str(item.get("name", "")).strip()
                    break
            else:
                trade_info["stock_name"] = ""
        trade_info["timestamp"] = datetime.now().isoformat()
        # pending 주문이 이후 체결확인으로 들어오면 같은 주문 레코드를 갱신(append 중복 방지)
        did_upsert = False
        try:
            incoming_status = str(trade_info.get("order_status") or "").strip().lower()
            incoming_code = str(trade_info.get("stock_code") or "").strip().zfill(6)
            incoming_side = str(trade_info.get("order_type") or "").strip().lower()
            incoming_odno = str(trade_info.get("odno") or "").strip()
            if incoming_status == "filled":
                for i in range(len(self.trade_history) - 1, -1, -1):
                    prev = self.trade_history[i] or {}
                    prev_status = str(prev.get("order_status") or "").strip().lower()
                    if prev_status != "accepted_pending":
                        continue
                    prev_code = str(prev.get("stock_code") or "").strip().zfill(6)
                    prev_side = str(prev.get("order_type") or "").strip().lower()
                    if prev_code != incoming_code or prev_side != incoming_side:
                        continue
                    prev_odno = str(prev.get("odno") or "").strip()
                    if incoming_odno and prev_odno and incoming_odno != prev_odno:
                        continue
                    merged = dict(prev)
                    merged.update(trade_info)
                    merged["accepted_timestamp"] = prev.get("timestamp")
                    merged["timestamp"] = trade_info["timestamp"]
                    self.trade_history[i] = merged
                    did_upsert = True
                    break
        except Exception:
            did_upsert = False
        if not did_upsert:
            self.trade_history.append(trade_info)
        if len(self.trade_history) > 100:
            self.trade_history = self.trade_history[-100:]
        # DynamoDB quant_trading_user_hist 저장 (일자별 10일 보관, TTL)
        try:
            from user_hist_store import get_user_hist_store
            store = get_user_hist_store()
            u = getattr(self, "trading_username", None)
            if not u:
                logger.debug("user_hist: skip (trading_username not set — 시스템 시작 후 저장됨)")
            elif not store.enabled:
                logger.warning("user_hist: skip (store disabled). table=%s reason=%s", getattr(store, "table_name", ""), getattr(store, "init_error", "unknown"))
            else:
                if not store.put_trade(u, trade_info):
                    logger.warning("user_hist: put_trade returned False for user=%s", u)
        except Exception as e:
            logger.warning("user_hist: save failed: %s", e, exc_info=True)
        # 연속 손실 추적: 매도 체결 시 pnl 기준
        if trade_info.get("order_type") == "sell" and trade_info.get("pnl") is not None:
            try:
                pnl = float(trade_info["pnl"])
                if pnl < 0:
                    self.consecutive_losses = getattr(self, "consecutive_losses", 0) + 1
                    self.last_consecutive_loss_time = _time.time()
                    # 임계 도달 시 1회: 전역 매수 스킵(연속손실쿨다운)이 켜짐을 로그에 남김 — 스킵 로그의 종목코드는 '후보'일 뿐 손실 원인 종목이 아님
                    try:
                        thresh = max(2, min(5, int(getattr(self, "consecutive_loss_count_threshold", 2) or 2)))
                        if (
                            bool(getattr(self, "consecutive_loss_cooldown_enabled", False))
                            and self.consecutive_losses == thresh
                        ):
                            base_cd = int(getattr(self, "reentry_cooldown_seconds", 0) or 0)
                            mult = float(getattr(self, "consecutive_loss_cooldown_mult", 2.0) or 2.0)
                            required = int(base_cd * mult) if base_cd > 0 else 0
                            msg = (
                                f"연속 손실 {self.consecutive_losses}회 도달 → 연속손실쿨다운 적용(신규 매수 전역 대기 약 {required}s, "
                                f"reentry_cooldown_seconds×배수). 이후 로그의 'BUY 스킵 | 종목코드 | 연속 손실 쿨다운'에서 종목코드는 해당 틱의 매수 후보이며 손실 원인 종목을 뜻하지 않습니다."
                            )
                            logger.warning(msg)
                            try:
                                from system_log import system_log_append

                                system_log_append("warning", msg)
                            except Exception:
                                pass
                    except Exception:
                        pass
                else:
                    self.consecutive_losses = 0
                    self.last_consecutive_loss_time = None
            except (TypeError, ValueError):
                pass

state = TradingState()

# Pydantic 모델
class LoginRequest(BaseModel):
    username: str
    password: str

class RegisterRequest(BaseModel):
    username: str
    password: str
    email: str = ""


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


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
    daily_loss_limit_calendar: bool = True  # True=캘린더일(자정 리셋), False=세션
    daily_profit_limit_calendar: bool = True
    monthly_loss_limit: int = 0  # 0=미적용. 월간 손실 한도(원)
    cumulative_loss_limit: int = 0  # 0=미적용. 누적 손실 한도(원)
    # 주문 실행 방식/재시도
    buy_order_style: str = "market"  # market | best_limit
    sell_order_style: str = "market"  # market | best_limit
    order_retry_count: int = 0
    order_retry_delay_ms: int = 300
    order_retry_exponential_backoff: bool = True
    order_retry_base_delay_ms: int = 1000
    order_fallback_to_market: bool = True
    # 변동성 기반 포지션 사이징 + 종목당 최대 손실액
    enable_volatility_sizing: bool = False
    volatility_lookback_ticks: int = 20
    volatility_stop_mult: float = 1.0
    max_loss_per_stock_krw: int = 0  # 0이면 사용 안 함
    # 슬리피지·체결지연 보수 반영(bps). 손절/익절 판단 시 매수가 불리하게 체결된 것으로 가정
    slippage_bps: int = 0
    # 변동성 틱 부족 시 하한(가격 대비 비율, 예: 0.005=0.5%). 장 초반 사이징 완화
    volatility_floor_ratio: float = 0.005
    max_trades_per_day: int
    max_trades_per_stock_per_day: int = 0  # 종목당 일일 최대 거래 횟수. 0=미적용
    max_position_size_ratio: float
    max_positions_count: int = 0  # 동시 보유 종목 수 상한. 0=제한 없음
    expand_position_when_few_stocks: bool = True  # True: 선정 1~2종목일 때 잔고 활용 확대, False: 항상 max_position_size_ratio
    # 확대 시 종목당 최대 비율(0~1). 3종목 이상은 항상 max_position_size_ratio.
    expand_position_ratio_1_stock: float = 1.0
    expand_position_ratio_2_stocks: float = 0.5
    # 당일 매수 한도 소모분 상한. 0=미적용. 매수 +가격×수량, 매도 −평단×매도수량.
    daily_max_buy_amount_krw: int = 0
    trailing_stop_ratio: float = 0.0
    trailing_activation_ratio: float = 0.0
    partial_take_profit_ratio: float = 0.0
    partial_take_profit_fraction: float = 0.5
    # ATR(틱 변동성) 배수 손절/익절
    use_atr_for_stop_take: bool = False
    atr_stop_mult: float = 1.5
    atr_take_mult: float = 2.0
    atr_lookback_ticks: int = 20
    # 매수 허용 최소 가격 변동(0~10%). 직전 틱 대비 이 비율만큼 변동해야 주문 실행. 0=미적용(보통), 0.01=1% 이상이면 급등 순간만
    min_price_change_ratio: float = 0.0
    # 변동성 필터(계산 지표): API 미제공 → 분봉/틱으로 자체 계산
    atr_filter_enabled: bool = False  # ATR(분봉) 비율 상한 초과 시 매수 스킵
    atr_period: int = 14
    atr_ratio_max_pct: float = 0.0  # 0=미적용. ATR/현재가*100 > 이 값이면 스킵 (예: 2.5)
    sap_deviation_filter_enabled: bool = False  # 세션 평균가(SAP) 대비 이탈률 상한
    sap_deviation_max_pct: float = 3.0  # |현재가-SAP|/SAP*100 > 이 값이면 스킵 (과열/과매도 구간)
    # 횡보 구간 본전/소폭익절 청산(진입 후 일정 시간 경과 + 박스권 + 진입가 위)
    sideways_be_exit_enabled: bool = False
    sideways_be_hold_seconds: int = 180
    sideways_be_buffer_ratio: float = 0.0005
    sideways_be_range_lookback_ticks: int = 24
    sideways_be_max_range_ratio: float = 0.0012

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
    max_drawdown_from_high_ratio: float = 0.12  # 12%; 실전에서는 10~12% 이상이어야 종목이 선정되는 경우 많음
    drawdown_filter_after_hhmm: str = "12:00"
    kospi_only: bool = False  # True: 코스피만(코스닥 제외)


def _default_unified_regime_profile_trend() -> "UnifiedRegimeProfile":
    """추세장: 넓은 손절·트레일링, 진입 다소 보수(확인 틱), 데드크로스 지연."""
    return UnifiedRegimeProfile(
        strategy={
            "min_short_ma_slope_ratio": 0.0001,
            "buy_confirm_ticks": 2,
            "dead_cross_confirm_ticks": 2,
            "minute_trend_enabled": True,
            "range_lookback_ticks": 6,
            "min_range_ratio": 0.001,
        },
        risk={
            "stop_loss_ratio": 0.028,
            "trailing_stop_ratio": 0.014,
            "trailing_activation_ratio": 0.007,
            "partial_take_profit_ratio": 0.015,
            "atr_filter_enabled": False,
            "atr_ratio_max_pct": 0.0,
        },
    )


def _default_unified_regime_profile_range() -> "UnifiedRegimeProfile":
    """박스권: 타이트 스탑·빠른 청산, ATR 필터 강화, 짧은 확인."""
    return UnifiedRegimeProfile(
        strategy={
            "min_short_ma_slope_ratio": 0.00025,
            "buy_confirm_ticks": 1,
            "dead_cross_confirm_ticks": 0,
            "minute_trend_enabled": False,
            "range_lookback_ticks": 12,
            "min_range_ratio": 0.0012,
        },
        risk={
            "stop_loss_ratio": 0.014,
            "trailing_stop_ratio": 0.006,
            "trailing_activation_ratio": 0.012,
            "partial_take_profit_ratio": 0.008,
            "atr_filter_enabled": True,
            "atr_period": 14,
            "atr_ratio_max_pct": 2.5,
        },
    )


def _default_unified_regime_profile_neutral() -> "UnifiedRegimeProfile":
    return UnifiedRegimeProfile(strategy={}, risk={})


class UnifiedRegimeProfile(BaseModel):
    """레짐별 전략/리스크 덮어쓰기. 키는 StrategyConfig / RiskConfig 필드명과 동일."""

    strategy: Dict[str, Any] = Field(default_factory=dict)
    risk: Dict[str, Any] = Field(default_factory=dict)


class UnifiedRegimeSwitchConfig(BaseModel):
    """통합 레짐 스위치: 지수·상승비율·지수변동률·거래대금 집중으로 trend|range|neutral → 프로필 적용."""

    enabled: bool = False
    eval_interval_sec: int = 60
    hysteresis_streak: int = 2
    index_ma_code: str = "1001"
    trend_require_index_bull: bool = True
    advance_ratio_market: str = "1001"
    trend_min_advance_ratio: float = 0.48
    range_max_advance_ratio: float = 0.46
    circuit_breaker_market_for_vol: str = "0001"
    volatility_index_change_trend_min: float = 0.12
    volatility_index_change_range_max: float = 0.35
    trade_value_concentration_market: str = "1001"
    concentration_implies_range: bool = True
    decision_margin: float = 0.8
    profile_trend: UnifiedRegimeProfile = Field(default_factory=_default_unified_regime_profile_trend)
    profile_range: UnifiedRegimeProfile = Field(default_factory=_default_unified_regime_profile_range)
    profile_neutral: UnifiedRegimeProfile = Field(default_factory=_default_unified_regime_profile_neutral)


class OperationalConfig(BaseModel):
    """운영 옵션: 자동 리밸런싱, 성과 기반 자동 추천, WS 재연결·긴급 청산, 매일 자동 시작/종료"""
    enable_auto_rebalance: bool = False
    auto_rebalance_interval_minutes: int = 30
    enable_performance_auto_recommend: bool = False
    performance_recommend_interval_minutes: int = 5
    ws_reconnect_sleep_sec: int = 5  # WebSocket 끊김 후 재연결 대기(초)
    emergency_liquidate_disconnect_minutes: int = 0  # 단절 N분 초과 시 전량 매도(0=미적용)
    keep_previous_on_empty_selection: bool = True  # 종목 선정 결과 0건 시 이전 목록 유지
    # 매일 자동 시작/종료 (KST)
    auto_schedule_enabled: bool = False
    auto_start_hhmm: str = "09:30"
    auto_stop_hhmm: str = "12:00"
    liquidate_on_auto_stop: bool = True  # 자동 종료 시 보유 종목 청산 여부
    auto_schedule_username: str = ""  # 비면 admin 사용


class MacroConfig(BaseModel):
    as_of_date: str = ""
    headline_note: str = ""
    vix: Optional[float] = None
    spx_fut_pct: Optional[float] = None
    ndx_fut_pct: Optional[float] = None
    dxy: Optional[float] = None
    usdkrw: Optional[float] = None
    us2y: Optional[float] = None
    us10y: Optional[float] = None
    hy_oas: Optional[float] = None
    sofr: Optional[float] = None
    iorb: Optional[float] = None
    tbill_3m: Optional[float] = None
    sofr_iorb: Optional[float] = None
    tbill_sofr: Optional[float] = None
    wti: Optional[float] = None
    gold: Optional[float] = None


class StrategyConfig(BaseModel):
    short_ma_period: int
    long_ma_period: int
    min_hold_seconds: int = 0  # 진입 후 N초 이내 전략(데드크로스) 매도 방지. 0=미적용
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
    reentry_cooldown_seconds: int = 240  # 휩쏘 완화: 600→240초 권장
    consecutive_loss_cooldown_enabled: bool = False
    consecutive_loss_count_threshold: int = 2
    consecutive_loss_cooldown_mult: float = 2.0
    # 지수 MA 시장 레짐: 지수(코스닥 등)가 N일 MA 미만이면 매수 스킵
    index_ma_filter_enabled: bool = False
    index_ma_code: str = "1001"  # 1001:코스닥, 0001:코스피
    index_ma_period: int = 20
    # 상승 종목 비율 시장 레짐: 등락률 순위 API로 상승/하락 건수 비율, N% 미만이면 매수 스킵
    advance_ratio_filter_enabled: bool = False
    advance_ratio_market: str = "1001"  # 1001:코스닥, 0001:코스피
    advance_ratio_min_pct: float = 35.0  # 상승 비율 하한(0~100%). 40→35 완화
    # 거래소 서킷브레이커(급락) 구간: 전일 대비 지수 하락률이 N% 이하이면 신규 매수 스킵 (KRX 1단계 서킷 ~-8% 직전)
    circuit_breaker_filter_enabled: bool = True
    circuit_breaker_market: str = "0001"  # 0001:코스피, 1001:코스닥
    circuit_breaker_threshold_pct: float = -7.0  # 이 하락률 이하이면 스킵 (예: -7 = 7% 하락 시)
    circuit_breaker_action: str = "skip_buy_only"  # skip_buy_only | liquidate_all | liquidate_partial | no_buy_rest_of_day
    # 사이드카 구간: 지수 ±5%(코스피)/±6%(코스닥) 변동 시 N분간 신규 매수 스킵 (KRX 프로그램매매 5분 정지에 맞춤)
    sidecar_filter_enabled: bool = True
    sidecar_market: str = "0001"  # 0001:코스피, 1001:코스닥
    sidecar_cooling_minutes: int = 5  # 냉각 분
    sidecar_action: str = "skip_buy_only"  # skip_buy_only | liquidate_all | liquidate_partial | no_buy_rest_of_day
    # VI(종목별 변동성완화장치) 발동 시 해당 종목 N분 매수 스킵
    vi_filter_enabled: bool = True
    vi_cooling_minutes: int = 5  # 해당 종목 냉각 분
    # VI 해제 후 강세주 재평가: 즉시 추격 대신 짧은 안정화 후 직전 VI 고점 재돌파 시에만 재평가
    vi_reentry_eval_enabled: bool = True
    vi_reentry_stabilization_seconds: int = 20
    vi_reentry_breakout_buffer_ratio: float = 0.001  # 0.1% 상향 재돌파
    # 거래대금 집중 시장 레짐: 상위 N종목 거래대금 비율이 X% 초과면 매수 스킵(좁은 시장)
    trade_value_concentration_filter_enabled: bool = False
    trade_value_concentration_market: str = "1001"  # 1001:코스닥, 0001:코스피
    trade_value_concentration_top_n: int = 10
    trade_value_concentration_denom_n: int = 30
    trade_value_concentration_max_pct: float = 45.0  # 상위 top_n / 상위 denom_n 비율이 이 값 초과면 스킵
    buy_confirm_ticks: int = 1
    # 데드크로스(MA 매도) 연속 확인: short<long 이 N틱 연속일 때만 매도. 0=즉시(기존 동작)
    dead_cross_confirm_ticks: int = 0
    enable_time_liquidation: bool = False
    liquidate_after_hhmm: str = "11:55"
    # 스프레드/횡보장 필터(0이면 사용 안 함)
    max_spread_ratio: float = 0.0  # 예: 0.001 = 0.1%
    range_lookback_ticks: int = 0
    min_range_ratio: float = 0.0  # 예: 0.003 = 0.3%
    # 2. 진입 시 평균 대비 거래량/거래대금 하한 (0이면 미적용)
    min_volume_ratio_for_entry: float = 0.0
    min_trade_amount_ratio_for_entry: float = 0.0
    # 3. 장 초반 N분 매수 스킵 (0이면 미적용)
    skip_buy_first_minutes: int = 0
    # 4. 지수 대비 상대 강도: 종목 > 지수 + margin일 때만 매수
    relative_strength_filter_enabled: bool = False
    relative_strength_index_code: str = "0001"  # 0001:코스피, 1001:코스닥
    relative_strength_margin_pct: float = 0.0  # 종목 변동률 > 지수 변동률 + margin(%) 일 때만 매수
    # 5. 장 마감 전 N분 신규 매수 스킵 (0이면 미적용)
    last_minutes_no_buy: int = 0
    # 5-1. 당일(세션) 고점 대비 N% 이상 하락 시 매수 스킵 (하락추세 진입 방지). 0=미적용
    skip_buy_below_high_pct: float = 0.0
    # 6. 등락 비율 하락장 시 매수 스킵 강화: 상승 비율 < 50%이면 전량 스킵
    advance_ratio_down_market_skip: bool = True
    # SAP 기반 풀백/역추세 진입 보조: 당일 세션 평균가(SAP) 대비 하단 구간에서만 매수 허용
    use_sap_revert_entry: bool = False
    # 예: -1.5~-0.5 구간(실제 변동폭에 맞춤). -2.5~-1.0은 변동 작을 때 진입 안 나옴
    sap_revert_entry_from_pct: float = -1.5
    sap_revert_entry_to_pct: float = -0.5
    # 듀얼 레짐(종목 분봉 박스 기반): 추세(MA 골든) vs 횡보(MR) 진입 방식 선택
    regime_dual_switch_enabled: bool = True
    # Deprecated: 시장 약세/박스 차단은 index_ma_filter, advance_ratio_filter, range 필터로 통합.
    # 저장 호환을 위해 필드는 남기지만 런타임에서는 무시된다.
    regime_block_ma_buy_when_index_bear: bool = False
    regime_block_ma_buy_when_stock_range: bool = False
    regime_stock_range_lookback_minutes: int = 15  # 단타: 12~20분대 권장(프리셋별 조정)
    regime_stock_range_max_ratio: float = 0.0065  # (고-저)/현재가; ~0.65% 미만이면 좁은 박스
    regime_mr_buy_enabled: bool = False  # 오전·보수는 끔, 전일·오후·공격만 켜는 것을 권장
    regime_mr_max_zone_pct: float = 0.32  # 박스 하단 32% 구간
    regime_mr_require_index_bull: bool = True  # MR도 지수 >= MA 요구 시 True
    # 통합 시장 레짐(trend|range|neutral): 저장된 베이스 전략/리스크 위에 런타임 오버레이
    unified_regime: UnifiedRegimeSwitchConfig = Field(default_factory=UnifiedRegimeSwitchConfig)


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


GUEST_USERNAME = "guest"


def is_guest_user(username: Optional[str]) -> bool:
    """게스트(읽기 전용) 계정 여부."""
    return str(username or "").strip().lower() == GUEST_USERNAME


async def get_write_enabled_user(current_user: str = Depends(get_current_user)) -> str:
    """쓰기 권한이 필요한 API용 의존성."""
    if is_guest_user(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="guest 계정은 읽기 전용입니다. 이 기능은 사용할 수 없습니다.",
        )
    return current_user

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


@app.post("/api/auth/change-password")
async def change_password(
    body: ChangePasswordRequest,
    current_user: str = Depends(get_write_enabled_user),
):
    """로그인 비밀번호 변경 (현재 비밀번호 확인 필요)."""
    if not body.new_password or len(body.new_password) < 4:
        return JSONResponse(
            {"success": False, "message": "새 비밀번호는 4자 이상이어야 합니다."},
            status_code=400,
        )
    ok = auth_manager.change_password(current_user, body.current_password, body.new_password)
    if not ok:
        return JSONResponse(
            {"success": False, "message": "현재 비밀번호가 일치하지 않습니다."},
            status_code=400,
        )
    return JSONResponse({"success": True, "message": "비밀번호가 변경되었습니다."})


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
            from dashboard_html import get_dashboard_html
            return get_dashboard_html(username)
    
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
                    if (data.token) {
                        try { localStorage.setItem('token', data.token); } catch (e) {}
                    }
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
    """대시보드 HTML (반응형)"""
    from dashboard_html import get_dashboard_html as _get_html
    return _get_html(username)

# API 엔드포인트 로드
from quant_dashboard_api import *

# ============================================================================
# 메인 실행
# ============================================================================

if __name__ == "__main__":
    import sys
    # Windows 기본 ProactorEventLoop는 Ctrl+C 종료 시 __del__에서 _ssock None → AttributeError가
    # "Exception ignored in BaseEventLoop.__del__"로 남는 경우가 있음. SelectorEventLoop로 바꿔 해당 경로 회피.
    if sys.platform == "win32":
        import asyncio
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    from quant_dashboard_api import initialize_trading_system

    # 시스템 초기화
    initialize_trading_system(account_balance=100000, is_paper_trading=True)
    
    print("=" * 80)
    print("퀀트 매매 시스템 대시보드 (모바일 최적화) 시작")
    print("=" * 80)
    print("웹 브라우저에서 http://localhost:8000 접속")
    print("기본 계정: admin / admin123")
    print("종료하려면 Ctrl+C를 누르세요 (한 번에 안 꺼지면 잠시 대기 후 다시 Ctrl+C 또는 프로세스 종료)")
    print("=" * 80)
    ensure_dashboard_atexit_registered()
    initialize_dashboard_runtime_guards()
    try:
        # None이면 진행 중 요청·WebSocket 정리에 시간 제한 없이 대기해 '안 꺼지는 것처럼' 보일 수 있음.
        uvicorn.run(app, host="0.0.0.0", port=8000, timeout_graceful_shutdown=10)
    except KeyboardInterrupt:
        print("\n종료합니다.")
    except Exception as e:
        _record_dashboard_uvicorn_exception(e)
        raise
    # Windows에서 Ctrl+C 후 "Exception ignored in: BaseEventLoop.__del__" / "'NoneType' object has no attribute 'close'"
    # 는 asyncio ProactorEventLoop 정리 순서 이슈로, 동작에는 영향 없음. (Python 이슈)
