"""
퀀트 매매 알고리즘 - 리스크 최소화 버전

안전한 자동매매를 위한 필수 기능:
1. 모의투자 환경 필수 사용
2. 포지션 크기 제한
3. 손절매/익절매 자동 실행
4. 일일 손실 한도 설정
5. 수동 승인 시스템 (옵션)
6. 상세 로깅
7. 서킷브레이커

예외 발생 시 동작 (예측 가능성):
- API 지연/장애: order_cash 호출에서 예외 발생 시 safe_execute_order가 catch하여
  details["ok"]=False, details["error"]=메시지, details["status"]="error" 반환.
  재시도는 order_retry_count+1회 수행 후 실패 시 위와 같이 반환.
- 부분 체결: 주문 접수 후 체결은 pending으로 두고, reconcile 루프가 체결 조회 시
  exec_qty/exec_px를 반영. update_position은 부분 매도 시 남은 수량만 유지하여
  부분 체결을 정상 처리.
- 주문 취소 실패: 현재 주문 취소 API 미호출. 미체결 주문은 pending TTL 후 prune.
- 세션 끊김: KIS 토큰 만료 등으로 API 실패 시 위 API 예외와 동일 처리. WebSocket
  대시보드 끊김은 클라이언트만 연결 해제, 엔진은 계속 구동.
"""

import sys
import logging
import threading
from datetime import datetime, timedelta, timezone
import time
from typing import Dict, Optional, Tuple
import pandas as pd

sys.path.extend(['..', '.'])
import kis_auth as ka
from domestic_stock_functions import order_cash
from domestic_stock_functions_ws import *

# ============================================================================
# 리스크 관리 설정
# ============================================================================

class RiskManager:
    """리스크 관리 클래스"""
    
    def __init__(self, account_balance: float = 10000000):
        """
        Args:
            account_balance: 계좌 잔고 (기본값: 1천만원)
        """
        self.account_balance = account_balance
        
        # 포지션 크기 제한 (계좌 자산의 최대 비율)
        self.max_position_size_ratio = 0.1  # 10% (매우 보수적)
        self.max_single_trade_amount = 1000000  # 최대 100만원
        self.expand_position_when_few_stocks = True  # True: 선정 1~2종목일 때 잔고 활용 확대
        # 확대 시 종목당 계좌 대비 최대 비율(0~1). 기본은 구버전과 동일(1종 100%, 2종 각 50%).
        self.expand_position_ratio_1_stock = 1.0
        self.expand_position_ratio_2_stocks = 0.5
        # 최소 매수 수량 (0/1이면 사실상 제한 없음)
        self.min_order_quantity = 1
        
        # 손절매/익절매 설정 (짧은 왕복·제세금 부담 완화: 익절·트레일을 다소 넓게)
        self.stop_loss_ratio = 0.006  # 0.6% (틱 노이즈 대비 0.5%→소폭 완화)
        self.take_profit_ratio = 0.014  # 1.4% (고정 익절 목표를 넓혀 회전·세금 누적 완화)
        # ATR(또는 틱 변동성) 배수 손절/익절: True면 변동성 기반 거리 사용
        self.use_atr_for_stop_take = False
        self.atr_stop_mult = 1.5  # 손절 = 매수가 - atr_stop_mult * ATR
        self.atr_take_mult = 2.0  # 익절 = 매수가 + atr_take_mult * ATR
        self.atr_lookback_ticks = 20  # ATR 대용 틱 변동성 lookback
        # 트레일링 스탑 (너무 이른 활성화·좁은 트레일은 과매매 유발 → 완화)
        self.trailing_stop_ratio = 0.01  # 1.0% 고점 대비 하락 시 청산
        self.trailing_activation_ratio = 0.008  # 0.8% 수익 이상일 때부터 trailing 적용
        # 부분 익절 (0이면 사용 안 함). 사용 시 오늘 실거래 패턴 기준 권장: 0.01(1%)
        self.partial_take_profit_ratio = 0.0
        self.partial_take_profit_fraction = 0.5  # 0~1
        
        # 일일 손실 한도
        self.daily_loss_limit = 500000  # 일일 최대 50만원 손실
        # 일일 이익 한도(목표). 0이면 사용 안 함.
        self.daily_profit_limit = 0
        # (실현+미실현) 합산 기준 일일 손실 한도. 0이면 사용 안 함.
        self.daily_total_loss_limit = 0
        # 이익/손실 트리거 등으로 "오늘 신규 매수 중지" (하루 단위)
        self.halt_new_buys_day = ""
        self.halt_new_buys_reason = ""
        # 일일 손익 한도 기준(실현/합산)
        self.daily_profit_limit_basis = "total"  # realized | total
        self.daily_loss_limit_basis = "realized"  # realized | total
        # 일일 한도 기준일: True=캘린더일(자정 리셋), False=세션(서버 기동 후)
        self.daily_loss_limit_calendar = True
        self.daily_profit_limit_calendar = True
        # 월간 손실 한도(원). 0이면 미적용. 캘린더 월 기준
        self.monthly_loss_limit = 0
        # 누적 손실 한도(원). 0이면 미적용. 세션/저장된 기준일 이후 누적
        self.cumulative_loss_limit = 0
        self._monthly_pnl_reset_ym = ""  # YYYYMM
        self._monthly_pnl = 0.0  # 해당 월 실현손익
        self._cumulative_pnl_since = 0.0  # 누적 실현손익(리셋 없음)
        self._daily_limit_date = ""  # 일일 한도 기준일(YYYYMMDD, 캘린더 리셋용)

        # 주문 실행 방식/재시도
        self.buy_order_style = "market"  # market | best_limit
        self.sell_order_style = "market"  # market | best_limit
        self.order_retry_count = 0
        self.order_retry_delay_ms = 300
        self.order_retry_exponential_backoff = True  # 네트워크 오류 시 지수 백오프
        self.order_retry_base_delay_ms = 1000  # 백오프 기준 지연(ms)
        self.order_fallback_to_market = True

        # 변동성 기반 포지션 사이징/종목당 최대 손실액
        self.enable_volatility_sizing = False
        self.volatility_lookback_ticks = 20
        self.volatility_stop_mult = 1.0
        self.max_loss_per_stock_krw = 0
        # 장 초반 등 틱 부족 시 변동성 하한(가격 대비 비율, 예: 0.005=0.5%). 0이면 미적용
        self.volatility_floor_ratio = 0.005
        # 슬리피지·체결지연 보수적 반영(bps). 매수 시 불리한 방향으로 가정해 손익 판단 시 사용
        self.slippage_bps = 0
        
        # 거래 제한
        self.max_trades_per_day = 12  # 하루 최대 거래 횟수 (매수+매도=1회). 5→12 휩쏘 대응
        self.max_trades_per_stock_per_day = 0  # 종목당 하루 최대 거래 횟수. 0=미적용
        # 당일 일매수 한도용 소모분: 매수 시 +(체결가×수량), 매도 시 -(평단×매도수량)으로 줄어듦.
        self.daily_max_buy_amount_krw = 0
        self.daily_buy_notional = 0.0
        self._daily_buy_notional_date = ""
        self.max_positions_count = 0  # 동시 보유 종목 수 상한. 0이면 제한 없음
        self.min_price_change_ratio = 0.0  # 직전 틱 대비 최소 변동률. 0=미적용, 0.01=1% 이상 변동 시만 거래(급등 순간 위주)
        # 진입 변동성 상한: 틱 변동성(가격 대비)이 이 비율 초과면 매수 스킵. 0이면 미적용
        self.max_intraday_vol_pct = 0.0
        # ATR(분봉) 필터: ATR/현재가*100 > atr_ratio_max_pct 이면 매수 스킵. 0이면 미적용
        self.atr_filter_enabled = False
        self.atr_period = 14
        self.atr_ratio_max_pct = 0.0
        # SAP(세션 평균가) 이탈 필터: |현재가-SAP|/SAP*100 > sap_deviation_max_pct 이면 스킵
        self.sap_deviation_filter_enabled = False
        self.sap_deviation_max_pct = 3.0
        # 횡보 구간 본전/소폭익절 청산: 진입 후 일정 시간 경과 + 박스권일 때만 진입가 위에서 청산
        self.sideways_be_exit_enabled = False
        self.sideways_be_hold_seconds = 180
        self.sideways_be_buffer_ratio = 0.0005
        self.sideways_be_range_lookback_ticks = 24
        self.sideways_be_max_range_ratio = 0.0012

        # 현재 상태 추적
        self.daily_trades = 0  # 거래 횟수 (매수+매도 = 1회)
        self.daily_pnl = 0.0
        self._daily_trades_per_stock: Dict[str, int] = {}  # 종목별 당일 매수(거래) 횟수, 날짜 바뀌면 리셋
        self.positions: Dict[str, Dict] = {}  # {종목코드: {매수가, 수량, 시간}}
        self.last_prices: Dict[str, float] = {}  # 가격 변동 추적용
        self._price_history: Dict[str, list] = {}  # 변동성 계산용(최근 N틱 가격)
        # 주문 접수는 됐지만 체결이 확정되지 않은 상태(중복 주문 방지용)
        # key: "{stock_code}:{side}" where side in {"buy","sell"}
        self._pending_orders: Dict[str, Dict] = {}
        self.pending_order_ttl_seconds = 120
        # 재진입 쿨다운 (기본 240초. 600초는 같은 종목 재진입이 너무 늦음)
        self.reentry_cooldown_seconds = 240
        self._last_exit_at: Dict[str, datetime] = {}
        self._last_exit_reason: Dict[str, str] = {}
        # 포지션별 고점 추적 (트레일링 스탑)
        self._highest_price: Dict[str, float] = {}
        # 동시성: 엔진 스레드 vs reconcile 루프에서 positions/_pending_orders 보호
        self._lock = threading.Lock()

    def get_effective_position_ratio(self, selected_count: Optional[int] = None) -> float:
        """
        선정 종목 수에 따른 종목당 허용 포지션 비율.
        - expand_position_when_few_stocks False면 항상 max_position_size_ratio.
        - True일 때: 1종목 expand_position_ratio_1_stock, 2종목 expand_position_ratio_2_stocks(종목당),
          3종목 이상 max_position_size_ratio.
        """
        if not bool(getattr(self, "expand_position_when_few_stocks", True)):
            return float(getattr(self, "max_position_size_ratio", 0.1) or 0.1)
        n = int(selected_count) if selected_count is not None and selected_count > 0 else 999
        base = float(getattr(self, "max_position_size_ratio", 0.1) or 0.1)
        if n == 1:
            r = float(getattr(self, "expand_position_ratio_1_stock", 1.0) or 1.0)
            return max(0.0, min(1.0, r))
        if n == 2:
            r = float(getattr(self, "expand_position_ratio_2_stocks", 0.5) or 0.5)
            return max(0.0, min(1.0, r))
        return base

    def _roll_daily_buy_notional_if_new_day(self, today_key: str) -> None:
        """KST 캘린더일이 바뀌면 당일 매수 누적 금액을 0으로 리셋."""
        if not today_key:
            return
        if str(getattr(self, "_daily_buy_notional_date", "") or "") != today_key:
            self._daily_buy_notional_date = today_key
            self.daily_buy_notional = 0.0
        
    def can_trade(self, stock_code: str, price: float, quantity: int, selected_count: Optional[int] = None) -> Tuple[bool, str]:
        """
        거래 가능 여부 확인
        
        Returns:
            (가능여부, 이유)
        """
        try:
            tz = timezone(timedelta(hours=9))
            now_dt = datetime.now(tz)
            today_key = now_dt.strftime("%Y%m%d")
            ym_key = now_dt.strftime("%Y%m")
        except Exception:
            today_key = ""
            ym_key = ""

        self._roll_daily_buy_notional_if_new_day(today_key)

        # 0. 캘린더일 기준 일일 리셋
        if today_key:
            calendar_loss = bool(getattr(self, "daily_loss_limit_calendar", True))
            calendar_profit = bool(getattr(self, "daily_profit_limit_calendar", True))
            limit_date = str(getattr(self, "_daily_limit_date", "") or "")
            if (calendar_loss or calendar_profit) and limit_date != today_key:
                self._daily_limit_date = today_key
                self.daily_trades = 0
                self.daily_pnl = 0.0
                self._daily_trades_per_stock = {}
            if ym_key and getattr(self, "_monthly_pnl_reset_ym", "") != ym_key:
                self._monthly_pnl_reset_ym = ym_key
                self._monthly_pnl = 0.0

        # 0-1. 오늘 신규 매수 중지 상태면 차단
        try:
            if self.halt_new_buys_day and str(self.halt_new_buys_day) != today_key:
                self.halt_new_buys_day = ""
                self.halt_new_buys_reason = ""
            if str(self.halt_new_buys_day or "") == today_key:
                return False, str(self.halt_new_buys_reason or "일일 신규 매수 중지")
        except Exception:
            pass

        # 1. 일일 거래 횟수 체크 (전역)
        if self.daily_trades >= self.max_trades_per_day:
            return False, "일일 거래 횟수 초과"

        # 1-1. 종목별 일일 거래 횟수 체크
        max_per_stock = int(getattr(self, "max_trades_per_stock_per_day", 0) or 0)
        if max_per_stock > 0:
            per_stock = getattr(self, "_daily_trades_per_stock", None) or {}
            cnt = int(per_stock.get(stock_code, 0) or 0)
            if cnt >= max_per_stock:
                return False, "종목별 일일 거래 횟수 초과"
        
        # 2. 일일 손익 한도 체크 (실현/합산 옵션)
        try:
            loss_limit = int(getattr(self, "daily_loss_limit", 0) or 0)
        except Exception:
            loss_limit = 0
        try:
            profit_limit = int(getattr(self, "daily_profit_limit", 0) or 0)
        except Exception:
            profit_limit = 0

        realized = float(getattr(self, "daily_pnl", 0.0) or 0.0)
        total = float(self.get_total_pnl() or realized)

        loss_basis = str(getattr(self, "daily_loss_limit_basis", "realized") or "realized").strip().lower()
        profit_basis = str(getattr(self, "daily_profit_limit_basis", "total") or "total").strip().lower()
        loss_pnl = total if loss_basis == "total" else realized
        profit_pnl = total if profit_basis == "total" else realized

        if loss_limit > 0 and float(loss_pnl) <= -float(loss_limit):
            return False, "일일 손실 한도 도달"
        if profit_limit > 0 and float(profit_pnl) >= float(profit_limit):
            return False, "일일 이익 한도(목표) 달성"

        # 2-1. 월간 손실 한도
        try:
            monthly_limit = int(getattr(self, "monthly_loss_limit", 0) or 0)
            if monthly_limit > 0:
                monthly_pnl = float(getattr(self, "_monthly_pnl", 0.0) or 0.0)
                if monthly_pnl <= -float(monthly_limit):
                    return False, "월간 손실 한도 도달"
        except Exception:
            pass
        # 2-2. 누적 손실 한도
        try:
            cum_limit = int(getattr(self, "cumulative_loss_limit", 0) or 0)
            if cum_limit > 0:
                cum_pnl = float(getattr(self, "_cumulative_pnl_since", 0.0) or 0.0)
                if cum_pnl <= -float(cum_limit):
                    return False, "누적 손실 한도 도달"
        except Exception:
            pass
        
        # 3. 거래 금액 체크
        trade_amount = price * quantity
        try:
            dmax_buy = int(getattr(self, "daily_max_buy_amount_krw", 0) or 0)
        except Exception:
            dmax_buy = 0
        if dmax_buy > 0:
            cur_buy = float(getattr(self, "daily_buy_notional", 0.0) or 0.0)
            if cur_buy + float(trade_amount) > float(dmax_buy) + 1e-3:
                return False, (
                    f"일일 매수 한도 소모분 초과 (현재 소모 {cur_buy:,.0f}원 + 이번 {float(trade_amount):,.0f}원 > {dmax_buy:,}원)"
                )
        if trade_amount > self.max_single_trade_amount:
            return False, f"거래 금액 초과 (최대: {self.max_single_trade_amount:,}원)"
        
        # 4. 포지션 크기 비율 체크 (선정 1~2종목일 때 잔고 대비 허용 비율 확대)
        effective_ratio = self.get_effective_position_ratio(selected_count)
        max_position_value = self.account_balance * effective_ratio
        if trade_amount > max_position_value:
            return False, f"포지션 크기 초과 (최대: {max_position_value:,.0f}원, 계좌의 {effective_ratio*100:.0f}%)"
        
        # 4-1. 동시 보유 종목 수 상한 (0이면 미적용). 거절 직전에 체결 확인 훅 실행 후 재검사(접수대기→체결 반영 지연 보정)
        max_pos = int(getattr(self, "max_positions_count", 0) or 0)
        if max_pos > 0 and len(self.positions) >= max_pos:
            try:
                hook = getattr(self, "on_before_max_positions_reject", None)
                if callable(hook):
                    hook()
            except Exception:
                pass
            if len(self.positions) >= max_pos:
                return False, f"동시 보유 종목 수 상한 도달 (최대 {max_pos}종목)"
        
        # 5. 기존 포지션 체크 (중복 매수 방지)
        if stock_code in self.positions:
            return False, "이미 보유 중인 종목"

        # 5-0. pending 주문이 있으면 중복 주문 방지(특히 지정가/응답 애매 케이스)
        try:
            self._prune_pending_orders()
            if self.has_pending_order(stock_code=stock_code, side="buy"):
                return False, "체결 대기 중인 매수 주문이 있습니다"
            # 미체결 매도 주문이 남아 있으면 같은 종목 재진입을 차단한다.
            # (매도 대기 수량이 주문가능수량을 잠가 APBK0400을 유발하는 상황 방지)
            if self.has_pending_order(stock_code=stock_code, side="sell"):
                return False, "체결 대기 중인 매도 주문이 있어 재진입을 차단합니다"
        except Exception:
            pass

        # 5-1. 재진입 쿨다운(직전 매도 직후 재매수 방지)
        if self.reentry_cooldown_seconds and self.reentry_cooldown_seconds > 0:
            last_exit = self._last_exit_at.get(stock_code)
            if isinstance(last_exit, datetime):
                elapsed = (datetime.now() - last_exit).total_seconds()
                if elapsed < float(self.reentry_cooldown_seconds):
                    remain = int(float(self.reentry_cooldown_seconds) - elapsed)
                    return False, f"재진입 쿨다운({remain}s 남음)"
        
        # 6. 최소 가격 변동 체크 (매수 시)
        if stock_code in self.last_prices:
            price_change = abs(price - self.last_prices[stock_code]) / self.last_prices[stock_code]
            if price_change < self.min_price_change_ratio:
                return False, f"가격 변동 부족 (최소 {self.min_price_change_ratio*100}% 필요)"

        # 7. 종목당 최대 손실액(원) 기반 리스크 체크 (변동성 사이징을 쓸 때 특히 중요)
        try:
            if bool(getattr(self, "enable_volatility_sizing", False)):
                max_loss = int(getattr(self, "max_loss_per_stock_krw", 0) or 0)
                if max_loss > 0 and price > 0 and float(getattr(self, "stop_loss_ratio", 0.0) or 0.0) > 0:
                    # 최소 손절거리(원/주)를 기준으로 위험액을 근사
                    stop_by_ratio = float(getattr(self, "stop_loss_ratio", 0.0) or 0.0) * float(price)
                    est_risk = float(quantity) * float(stop_by_ratio)
                    if stop_by_ratio > 0 and est_risk > float(max_loss) * 1.001:
                        return False, f"종목당 최대 손실액 초과(추정 {est_risk:,.0f}원 > {max_loss:,.0f}원)"
        except Exception:
            pass
        
        return True, "OK"

    def _pending_key(self, stock_code: str, side: str) -> str:
        return f"{str(stock_code).strip().zfill(6)}:{str(side).strip().lower()}"

    def _prune_pending_orders(self) -> None:
        """호출 시 _lock을 선점한 상태에서 호출해야 함."""
        try:
            ttl = int(getattr(self, "pending_order_ttl_seconds", 120) or 120)
        except Exception:
            ttl = 120
        ttl = max(5, min(3600, ttl))
        now = time.time()
        for k, v in list(self._pending_orders.items()):
            try:
                ts = float((v or {}).get("ts") or 0)
            except Exception:
                ts = 0
            if not ts or (now - ts) > ttl:
                self._pending_orders.pop(k, None)

    def has_pending_order(self, stock_code: str, side: Optional[str] = None) -> bool:
        with self._lock:
            self._prune_pending_orders()
            code = str(stock_code).strip().zfill(6)
            if side:
                return self._pending_key(code, side) in self._pending_orders
            prefix = f"{code}:"
            return any(k.startswith(prefix) for k in list(self._pending_orders.keys()))

    def set_pending_order(
        self,
        stock_code: str,
        side: str,
        quantity: int,
        price: float,
        env_dv: str,
        odno: str = "",
        reason: str = "",
        sell_trigger_code: str = "",
    ) -> None:
        with self._lock:
            self._prune_pending_orders()
            k = self._pending_key(stock_code, side)
            self._pending_orders[k] = {
                "ts": time.time(),
                "last_check_ts": 0.0,
                "checks": 0,
                "stock_code": str(stock_code).strip().zfill(6),
                "side": str(side).strip().lower(),
                "quantity": int(quantity or 0),
                "price": float(price or 0),
                "env_dv": str(env_dv or ""),
                "odno": str(odno or "").strip(),
                "reason": str(reason or ""),
                "sell_trigger_code": str(sell_trigger_code or "").strip() if str(side).lower() == "sell" else "",
                "reconciled_ccld_qty": 0,
            }

    def clear_pending_order(self, stock_code: str, side: Optional[str] = None) -> None:
        with self._lock:
            self._prune_pending_orders()
            code = str(stock_code).strip().zfill(6)
            if side:
                self._pending_orders.pop(self._pending_key(code, side), None)
                return
            prefix = f"{code}:"
            for k in list(self._pending_orders.keys()):
                if k.startswith(prefix):
                    self._pending_orders.pop(k, None)
    
    def calculate_quantity(self, price: float, selected_count: Optional[int] = None) -> int:
        """
        거래 수량 계산.
        - max_loss_per_stock_krw > 0 이면: position size = risk / stop distance (고정 리스크 per trade).
        - 아니면: 계좌 잔고·최대 거래금액 기반 금액/가격.
        - selected_count 1~2일 때 종목당 허용 비율 확대(잔고 전체 활용).
        """
        min_q = max(1, int(self.min_order_quantity or 1))
        if price <= 0:
            return min_q
        effective_ratio = self.get_effective_position_ratio(selected_count)
        max_trade_amount = min(
            float(getattr(self, "max_single_trade_amount", 0) or 0),
            float(getattr(self, "account_balance", 0) or 0) * effective_ratio,
        )
        # 리스크 기반: 수량 = risk_per_trade / stop_distance (손절거리)
        max_loss = int(getattr(self, "max_loss_per_stock_krw", 0) or 0)
        stop_ratio = float(getattr(self, "stop_loss_ratio", 0.0) or 0.0)
        if max_loss > 0 and stop_ratio > 0:
            stop_distance = price * stop_ratio
            if stop_distance > 0:
                qty_risk = int(max_loss / stop_distance)
                qty_cap = int(max_trade_amount / price) if max_trade_amount > 0 else qty_risk
                quantity = max(min_q, min(qty_risk, qty_cap))
                return quantity
        # 기본: 금액 기반
        quantity = int(max_trade_amount / price) if max_trade_amount > 0 else 0
        return max(min_q, quantity)

    def calculate_quantity_with_volatility(
        self,
        stock_code: str,
        price: float,
        fallback_quantity: int,
        selected_count: Optional[int] = None,
    ) -> int:
        """
        변동성 기반(ATR 유사) 사이징:
        - risk_per_share = max(stop_loss_ratio*price, vol_mult*avg_abs_diff)
        - qty_risk = floor(max_loss_per_stock / risk_per_share)
        - 금액/비율 제한과 함께 최소값 선택
        """
        try:
            if not bool(getattr(self, "enable_volatility_sizing", False)):
                return int(fallback_quantity)
            max_loss = int(getattr(self, "max_loss_per_stock_krw", 0) or 0)
            if max_loss <= 0:
                return int(fallback_quantity)
            if price <= 0:
                return int(fallback_quantity)

            lookback = int(getattr(self, "volatility_lookback_ticks", 20) or 20)
            lookback = max(2, min(300, lookback))
            mult = float(getattr(self, "volatility_stop_mult", 1.0) or 1.0)
            mult = max(0.1, min(10.0, mult))

            hist = self._price_history.get(stock_code) or []
            stop_by_ratio = float(getattr(self, "stop_loss_ratio", 0.0) or 0.0) * float(price)
            floor_ratio = float(getattr(self, "volatility_floor_ratio", 0.0) or 0.0)
            floor_ratio = max(0.0, min(0.05, floor_ratio))
            vol_floor = float(price) * floor_ratio if floor_ratio > 0 else 0.0

            if len(hist) < lookback + 1:
                # 틱 부족 시 변동성 플로어로 사이징(장 초반 보수적 과소 수량 완화)
                if vol_floor <= 0:
                    return int(fallback_quantity)
                risk_per_share = max(stop_by_ratio, vol_floor)
                if risk_per_share <= 0:
                    return int(fallback_quantity)
                qty_risk = int(max_loss / risk_per_share)
                if qty_risk <= 0:
                    return int(fallback_quantity)
                eff_ratio = self.get_effective_position_ratio(selected_count)
                max_trade_amount = min(
                    float(getattr(self, "max_single_trade_amount", 0) or 0),
                    float(getattr(self, "account_balance", 0) or 0) * eff_ratio,
                )
                qty_amount = int(max_trade_amount / price) if max_trade_amount > 0 else qty_risk
                min_q = max(1, int(self.min_order_quantity or 1))
                return max(min_q, min(qty_risk, qty_amount))

            diffs = []
            start = max(1, len(hist) - (lookback + 1))
            for i in range(start, len(hist)):
                try:
                    diffs.append(abs(float(hist[i]) - float(hist[i - 1])))
                except Exception:
                    continue
            if not diffs:
                if vol_floor > 0:
                    risk_per_share = max(stop_by_ratio, vol_floor)
                    qty_risk = int(max_loss / risk_per_share)
                    if qty_risk > 0:
                        eff_ratio = self.get_effective_position_ratio(selected_count)
                        max_trade_amount = min(
                            float(getattr(self, "max_single_trade_amount", 0) or 0),
                            float(getattr(self, "account_balance", 0) or 0) * eff_ratio,
                        )
                        qty_amount = int(max_trade_amount / price) if max_trade_amount > 0 else qty_risk
                        min_q = max(1, int(self.min_order_quantity or 1))
                        return max(min_q, min(qty_risk, qty_amount))
                return int(fallback_quantity)
            avg_abs = float(sum(diffs) / float(len(diffs)))
            risk_per_share = max(stop_by_ratio, mult * avg_abs)
            if vol_floor > 0:
                risk_per_share = max(risk_per_share, vol_floor)
            if risk_per_share <= 0:
                return int(fallback_quantity)

            qty_risk = int(max_loss / risk_per_share)
            if qty_risk <= 0:
                return 0

            # 금액 기반 상한도 같이 적용 (선정 1~2종목일 때 잔고 활용 확대)
            eff_ratio = self.get_effective_position_ratio(selected_count)
            max_trade_amount = min(
                float(getattr(self, "max_single_trade_amount", 0) or 0),
                float(getattr(self, "account_balance", 0) or 0) * eff_ratio,
            )
            qty_amount = int(max_trade_amount / price) if max_trade_amount > 0 else qty_risk
            min_q = 1
            try:
                min_q = int(self.min_order_quantity or 1)
            except Exception:
                min_q = 1
            min_q = max(1, min_q)

            qty = max(min_q, min(qty_risk, qty_amount))
            return int(qty)
        except Exception:
            return int(fallback_quantity)
    
    def update_position(self, stock_code: str, price: float, quantity: int, action: str):
        """포지션 업데이트 (lock으로 동시성 보호)"""
        with self._lock:
            return self._update_position_impl(stock_code, price, quantity, action)

    def _update_position_impl(self, stock_code: str, price: float, quantity: int, action: str):
        if action == "buy":
            try:
                tz = timezone(timedelta(hours=9))
                self._roll_daily_buy_notional_if_new_day(datetime.now(tz).strftime("%Y%m%d"))
            except Exception:
                pass
            # 추가 매수 지원: 기존 포지션이 있으면 수량 누적 + 평단 갱신
            now_dt = datetime.now()
            try:
                px = float(price)
            except Exception:
                px = float(price or 0)
            try:
                q = int(quantity or 0)
            except Exception:
                q = 0
            if q <= 0 or px <= 0:
                return 0.0
            if stock_code in self.positions:
                pos = self.positions[stock_code]
                old_qty = int(pos.get("quantity") or 0)
                old_px = float(pos.get("buy_price") or 0)
                new_qty = old_qty + q
                if new_qty > 0:
                    # 가중평균 평단
                    avg_px = ((old_px * old_qty) + (px * q)) / float(new_qty) if old_qty > 0 and old_px > 0 else px
                    pos["buy_price"] = float(avg_px)
                    pos["quantity"] = int(new_qty)
                    # buy_time은 최초 진입 시각 유지(옵션). 이미 없으면 설정.
                    if not pos.get("buy_time"):
                        pos["buy_time"] = now_dt
                    pos["current_price"] = float(px)
                    pos["partial_taken"] = bool(pos.get("partial_taken", False))
                # 최고가 추적은 최신가/기존 최고가 중 큰 값
                try:
                    prev_high = float(self._highest_price.get(stock_code) or 0.0)
                except Exception:
                    prev_high = 0.0
                self._highest_price[stock_code] = max(prev_high, float(px))
            else:
                self.positions[stock_code] = {
                    "buy_price": float(px),
                    "quantity": int(q),
                    "buy_time": now_dt,
                    "partial_taken": False,
                    "current_price": float(px),
                }
                self._highest_price[stock_code] = float(px)
            # 매수 시 거래 횟수 증가(일일 매수 횟수 제한용)
            self.daily_trades += 1
            per_stock = getattr(self, "_daily_trades_per_stock", None)
            if per_stock is None:
                self._daily_trades_per_stock = {}
                per_stock = self._daily_trades_per_stock
            per_stock[stock_code] = per_stock.get(stock_code, 0) + 1
            self.last_prices[stock_code] = float(px)
            try:
                self.daily_buy_notional = float(getattr(self, "daily_buy_notional", 0.0) or 0.0) + float(px) * float(q)
            except Exception:
                pass
        elif action == "sell":
            if stock_code in self.positions:
                pos = self.positions[stock_code]
                buy_price = float(pos.get("buy_price") or 0)
                pos_qty = int(pos.get("quantity") or 0)
                sell_qty = int(quantity or 0)
                if sell_qty <= 0:
                    return 0.0
                if pos_qty <= 0:
                    del self.positions[stock_code]
                    return 0.0

                # 부분 매도 지원
                actual_qty = min(sell_qty, pos_qty)
                pnl = (price - buy_price) * actual_qty
                self.daily_pnl += pnl
                self._cumulative_pnl_since = float(getattr(self, "_cumulative_pnl_since", 0.0) or 0.0) + pnl
                self._monthly_pnl = float(getattr(self, "_monthly_pnl", 0.0) or 0.0) + pnl
                try:
                    released = float(buy_price) * float(actual_qty)
                    self.daily_buy_notional = max(
                        0.0, float(getattr(self, "daily_buy_notional", 0.0) or 0.0) - released
                    )
                except Exception:
                    pass

                remain = pos_qty - actual_qty
                if remain > 0:
                    pos["quantity"] = remain
                    pos["partial_taken"] = True
                    # 남은 포지션이면 exit/cooldown은 기록하지 않음
                else:
                    del self.positions[stock_code]
                    # 매도 시에는 거래 횟수를 증가시키지 않음 (매수+매도 = 1회)
                    if stock_code in self.last_prices:
                        del self.last_prices[stock_code]
                    self._last_exit_at[stock_code] = datetime.now()
                    if stock_code in self._highest_price:
                        del self._highest_price[stock_code]
                return pnl
        return 0.0

    def update_price(self, stock_code: str, price: float):
        """가격 업데이트 (변동 추적/미실현 손익 계산용)"""
        try:
            px = float(price)
        except Exception:
            return
        self.last_prices[stock_code] = px
        hist = self._price_history.get(stock_code)
        if hist is None:
            hist = []
            self._price_history[stock_code] = hist
        hist.append(px)
        # 최근 600틱까지만 유지
        if len(hist) > 600:
            self._price_history[stock_code] = hist[-600:]

        if stock_code in self.positions:
            try:
                self.positions[stock_code]["current_price"] = px
            except Exception:
                pass
            prev = self._highest_price.get(stock_code, 0.0)
            if float(px) > float(prev or 0.0):
                self._highest_price[stock_code] = float(px)

    def get_intraday_vol_ratio(self, stock_code: str, lookback: Optional[int] = None) -> Optional[float]:
        """최근 N틱 가격 변동의 평균 절대차를 현재가로 나눈 비율. 변동성 상한/ATR용. 데이터 부족 시 None."""
        try:
            hist = self._price_history.get(stock_code) or []
            if lookback is None:
                lookback = int(getattr(self, "volatility_lookback_ticks", 20) or 20)
            lookback = max(2, min(300, lookback))
            if len(hist) < lookback + 1:
                return None
            price = float(hist[-1]) if hist else 0.0
            if price <= 0:
                return None
            start = max(0, len(hist) - (lookback + 1))
            diffs = []
            for i in range(start + 1, len(hist)):
                try:
                    diffs.append(abs(float(hist[i]) - float(hist[i - 1])))
                except Exception:
                    continue
            if not diffs:
                return None
            avg_abs = sum(diffs) / len(diffs)
            return float(avg_abs) / price
        except Exception:
            return None

    def get_unrealized_pnl(self) -> float:
        try:
            unreal = 0.0
            for code, pos in list(self.positions.items()):
                try:
                    qty = int(pos.get("quantity") or 0)
                    if qty <= 0:
                        continue
                    buy_px = float(pos.get("buy_price") or 0)
                    cur_px = float(pos.get("current_price") or self.last_prices.get(code) or buy_px or 0)
                    if buy_px > 0 and cur_px > 0:
                        unreal += (cur_px - buy_px) * qty
                except Exception:
                    continue
            return float(unreal)
        except Exception:
            return 0.0

    def get_total_pnl(self) -> float:
        try:
            return float(self.daily_pnl or 0.0) + float(self.get_unrealized_pnl() or 0.0)
        except Exception:
            return float(self.daily_pnl or 0.0)

    def check_exit_signal(self, stock_code: str, current_price: float) -> Optional[Dict]:
        """
        포지션 청산/부분익절/보호 로직을 통합해서 판단.
        손절/전량익절: 비율과 ATR이 모두 켜져 있으면 더 타이트한 쪽(손절=가격 높은 선,
        익절=목표가 낮은 선)을 적용. trigger_code는 실제로 적용된 규칙(비율 또는 ATR).
        Returns:
            {"action":"sell","quantity":int,"reason":str,"trigger_code":str} or None
            trigger_code는 quant_dashboard_api 의 매도 로그·trade_info와 1:1 매핑용.
        """
        if stock_code not in self.positions:
            return None

        pos = self.positions[stock_code]
        buy_price = float(pos.get("buy_price") or 0)
        qty = int(pos.get("quantity") or 0)
        if buy_price <= 0 or qty <= 0:
            return None

        # 청산 트리거는 실제 체결가 기준으로 해석해야 설정 퍼센트와 체감이 일치한다.
        # slippage_bps는 수익 추정/주문 리스크 보수화에 쓰되, 손절·익절 트리거 자체를 왜곡하지 않는다.
        trigger_base_price = float(buy_price)
        change_ratio = (float(current_price) - trigger_base_price) / trigger_base_price if trigger_base_price > 0 else 0.0

        # 비율 손절/익절 + ATR 손절/익절: 각각 유효할 때 더 타이트한 쪽(손절=높은 가격, 익절=낮은 목표가)을 적용
        min_stop_pct = 0.002
        min_take_pct = 0.002
        atr_stop_price: Optional[float] = None
        atr_take_price: Optional[float] = None
        use_atr = bool(getattr(self, "use_atr_for_stop_take", False))
        if use_atr and hasattr(self, "get_intraday_vol_ratio"):
            lookback = max(2, min(300, int(getattr(self, "atr_lookback_ticks", 20) or 20)))
            vol_ratio = self.get_intraday_vol_ratio(stock_code, lookback=lookback)
            if vol_ratio is not None and vol_ratio > 0 and trigger_base_price > 0:
                atr_proxy = float(vol_ratio) * float(trigger_base_price)
                stop_mult = max(0.5, min(5.0, float(getattr(self, "atr_stop_mult", 1.5) or 1.5)))
                take_mult = max(0.5, min(10.0, float(getattr(self, "atr_take_mult", 2.0) or 2.0)))
                cand_stop = trigger_base_price - stop_mult * atr_proxy
                cand_take = trigger_base_price + take_mult * atr_proxy
                # 진입 직후 변동성이 작으면 손절선이 매수가에 붙어 즉시 터지는 것 방지
                if cand_stop < trigger_base_price * (1.0 - min_stop_pct):
                    atr_stop_price = cand_stop
                if cand_take > trigger_base_price * (1.0 + min_take_pct):
                    atr_take_price = cand_take

        ratio_stop_price: Optional[float] = None
        if self.stop_loss_ratio and float(self.stop_loss_ratio) > 0:
            ratio_stop_price = trigger_base_price * (1.0 - float(self.stop_loss_ratio))

        stop_candidates: list[tuple[float, str, str]] = []
        if ratio_stop_price is not None:
            stop_candidates.append((ratio_stop_price, "risk_stop_loss_ratio", "손절"))
        if atr_stop_price is not None:
            stop_candidates.append((atr_stop_price, "risk_atr_stop_loss", "손절(ATR)"))
        if stop_candidates:
            # 아래로 내려갈 때 먼저 걸리는 선 = 손절가가 더 높은 쪽(허용 손실이 더 작은 쪽)
            sp, tcode, rsn = max(stop_candidates, key=lambda x: x[0])
            if float(current_price) <= sp:
                if len(stop_candidates) > 1:
                    rsn = "손절(비율·ATR 중 타이트)"
                return {"action": "sell", "quantity": qty, "reason": rsn, "trigger_code": tcode}

        # 익절(전량) — 비율·ATR 중 더 낮은 목표가(먼저 도달)를 적용
        ratio_take_price: Optional[float] = None
        if self.take_profit_ratio and float(self.take_profit_ratio) > 0:
            ratio_take_price = trigger_base_price * (1.0 + float(self.take_profit_ratio))
        take_candidates: list[tuple[float, str, str]] = []
        if ratio_take_price is not None:
            take_candidates.append((ratio_take_price, "risk_take_profit_ratio", "익절"))
        if atr_take_price is not None:
            take_candidates.append((atr_take_price, "risk_atr_take_profit", "익절(ATR)"))
        if take_candidates:
            tp, tcode, rsn = min(take_candidates, key=lambda x: x[0])
            if float(current_price) >= tp:
                if len(take_candidates) > 1:
                    rsn = "익절(비율·ATR 중 타이트)"
                return {"action": "sell", "quantity": qty, "reason": rsn, "trigger_code": tcode}

        # 부분 익절 — 전량 익절이 이미 도달한 강한 틱이면 먼저 전량 익절을 우선한다.
        try:
            if (
                self.partial_take_profit_ratio
                and float(self.partial_take_profit_ratio) > 0
                and not bool(pos.get("partial_taken", False))
                and change_ratio >= float(self.partial_take_profit_ratio)
            ):
                frac = float(self.partial_take_profit_fraction or 0.5)
                frac = max(0.0, min(1.0, frac))
                sell_qty = int(max(1, int(qty * frac)))
                if qty > 1:
                    sell_qty = min(sell_qty, qty - 1)
                else:
                    sell_qty = qty
                return {"action": "sell", "quantity": sell_qty, "reason": "부분익절", "trigger_code": "risk_partial_take_profit"}
        except Exception:
            pass

        # 트레일링 스탑
        try:
            if self.trailing_stop_ratio and float(self.trailing_stop_ratio) > 0:
                highest = float(self._highest_price.get(stock_code) or trigger_base_price)
                if highest > 0:
                    gain = (highest - trigger_base_price) / trigger_base_price
                    if gain >= float(self.trailing_activation_ratio or 0.0):
                        if float(current_price) <= highest * (1.0 - float(self.trailing_stop_ratio)):
                            return {"action": "sell", "quantity": qty, "reason": "트레일링스탑", "trigger_code": "risk_trailing_stop"}
        except Exception:
            pass

        # 횡보 구간 본전/소폭익절 청산
        # - 진입 후 hold_seconds 경과
        # - 최근 lookback_ticks 범위가 max_range_ratio 이하(박스권)
        # - 현재가가 (진입가 * (1 + buffer_ratio)) 이상일 때만 청산
        try:
            if bool(getattr(self, "sideways_be_exit_enabled", False)):
                pos_buy_time = pos.get("buy_time")
                hold_sec = max(0, int(getattr(self, "sideways_be_hold_seconds", 180) or 0))
                elapsed_ok = True
                if hold_sec > 0 and isinstance(pos_buy_time, datetime):
                    elapsed = (datetime.now() - pos_buy_time).total_seconds()
                    elapsed_ok = elapsed >= hold_sec
                if elapsed_ok:
                    lookback = max(5, min(300, int(getattr(self, "sideways_be_range_lookback_ticks", 24) or 24)))
                    max_rr = max(0.0, min(0.05, float(getattr(self, "sideways_be_max_range_ratio", 0.0012) or 0.0012)))
                    be_buf = max(0.0, min(0.02, float(getattr(self, "sideways_be_buffer_ratio", 0.0005) or 0.0005)))
                    hist = self._price_history.get(stock_code) or []
                    if len(hist) >= lookback and float(current_price) > 0:
                        recent = hist[-lookback:]
                        hi = max(float(p) for p in recent)
                        lo = min(float(p) for p in recent)
                        rr = (hi - lo) / float(current_price) if float(current_price) > 0 else 0.0
                        be_price = trigger_base_price * (1.0 + be_buf)
                        if rr <= max_rr and float(current_price) >= float(be_price):
                            return {
                                "action": "sell",
                                "quantity": qty,
                                "reason": "횡보 본전청산",
                                "trigger_code": "risk_sideways_breakeven",
                            }
        except Exception:
            pass

        return None
    
    def is_in_reentry_cooldown(self, stock_code: str) -> bool:
        if not self.reentry_cooldown_seconds or self.reentry_cooldown_seconds <= 0:
            return False
        last_exit = self._last_exit_at.get(stock_code)
        if not isinstance(last_exit, datetime):
            return False
        return (datetime.now() - last_exit).total_seconds() < float(self.reentry_cooldown_seconds)
    
    def check_stop_loss_take_profit(self, stock_code: str, current_price: float) -> Optional[str]:
        """
        손절매/익절매 체크
        
        Returns:
            "sell" if should sell, None otherwise
        """
        if stock_code not in self.positions:
            return None
        
        buy_price = float(self.positions[stock_code].get("buy_price") or 0)
        if buy_price <= 0:
            return None
        change_ratio = (current_price - buy_price) / buy_price if buy_price > 0 else 0.0
        
        # 손절매
        if change_ratio <= -self.stop_loss_ratio:
            self._last_exit_reason[stock_code] = "stop_loss"
            return "sell"
        
        # 익절매
        if change_ratio >= self.take_profit_ratio:
            self._last_exit_reason[stock_code] = "take_profit"
            return "sell"

        # 트레일링 스탑 (고점 대비 하락)
        try:
            if self.trailing_stop_ratio and self.trailing_stop_ratio > 0:
                highest = float(self._highest_price.get(stock_code) or buy_price)
                if highest <= 0:
                    return None
                gain = (highest - buy_price) / buy_price
                if gain >= float(self.trailing_activation_ratio or 0.0):
                    if float(current_price) <= highest * (1.0 - float(self.trailing_stop_ratio)):
                        self._last_exit_reason[stock_code] = "trailing_stop"
                        return "sell"
        except Exception:
            pass
        
        return None


# ============================================================================
# 퀀트 매매 알고리즘 (예제: 단순 이동평균 크로스오버)
# ============================================================================

class QuantStrategy:
    """퀀트 전략 클래스 (실시간 데이터에 최적화)"""
    
    def __init__(self, risk_manager: RiskManager):
        self.risk_manager = risk_manager
        self.price_history: Dict[str, list] = {}  # {종목코드: [가격 리스트]}
        # MA 기간 (휩쏘 완화: 5/20 등으로 조정 가능)
        self.short_ma_period = 5  # 단기 이동평균 (틱)
        self.long_ma_period = 20  # 장기 이동평균 (틱)
        self.min_history_length = self.long_ma_period  # 최소 히스토리 길이
        # 휩쏘 완화: 진입 후 N초 이내 데드크로스 매도 방지
        self.min_hold_seconds = 60  # 0=미적용
        # 데드크로스 MA 매도: short<long 이 N틱 연속일 때만 매도. 0=즉시(대시보드 엔진과 동일 의미)
        self.dead_cross_confirm_ticks = 0
        self._dead_cross_sell_confirm_counts: Dict[str, int] = {}
        # 단기 MA 기울기 최소 비율 (가격 대비, 예: 0.001 = 0.1%/틱). 매수 시 단기 상승 추세 확인
        self.min_short_ma_slope_ratio = 0.0  # 0=미적용
        # 매수 시 가격이 short_ma 위로 최소 이격 (예: 0.001 = 0.1%). 살짝만 넘었다 내려가는 휩쏘 완화
        self.min_price_above_short_ma_ratio = 0.001
        # 크로스 확인: 직전 틱(offset=1)에서 반대 크로스였을 때만 신호. 1=적용, 0=미적용
        self.cross_confirm_ticks = 1
        # 급등락/갭 필터: 전틱 대비 변동률 상한(예: 0.02=2%). 초과 시 해당 틱 신호 무시
        self.max_tick_change_ratio_for_signal = 0.02  # 0=미적용
        
    def update_price(self, stock_code: str, price: float):
        """가격 업데이트"""
        if stock_code not in self.price_history:
            self.price_history[stock_code] = []
        
        self.price_history[stock_code].append(price)
        
        # 최근 N개만 유지 (메모리 절약)
        max_history = self.long_ma_period * 3
        if len(self.price_history[stock_code]) > max_history:
            self.price_history[stock_code] = self.price_history[stock_code][-max_history:]
    
    def calculate_ma(self, stock_code: str, period: int) -> Optional[float]:
        """이동평균 계산"""
        if stock_code not in self.price_history:
            return None
        
        prices = self.price_history[stock_code]
        if len(prices) < period:
            return None
        
        return sum(prices[-period:]) / period

    def calculate_ma_offset(self, stock_code: str, period: int, offset: int = 0) -> Optional[float]:
        """
        이동평균 계산(오프셋 포함)
        - offset=0: 최신 기준
        - offset=1: 최신 1개를 제외한 기준
        """
        if stock_code not in self.price_history:
            return None
        prices = self.price_history[stock_code]
        if offset < 0:
            offset = 0
        if len(prices) < period + offset:
            return None
        if offset == 0:
            window = prices[-period:]
        else:
            window = prices[-(period + offset) : -offset]
        if not window or len(window) < period:
            return None
        return sum(window) / period
    
    def get_signal(self, stock_code: str, current_price: float) -> Optional[str]:
        """
        매매 신호 생성 (실시간 데이터 기반, 휩쏘 완화 필터 적용)
        
        Returns:
            "buy", "sell", or None
        """
        # 가격 업데이트
        self.update_price(stock_code, current_price)
        
        if stock_code not in self.price_history:
            return None
        prices = self.price_history[stock_code]
        if len(prices) < self.min_history_length:
            return None
        
        # 급등락/갭 필터: 전틱 대비 변동률이 너무 크면 해당 틱은 신호 무시
        max_chg = float(getattr(self, "max_tick_change_ratio_for_signal", 0) or 0)
        if max_chg > 0 and len(prices) >= 2:
            prev_price = float(prices[-2])
            if prev_price > 0:
                chg_ratio = abs(current_price - prev_price) / prev_price
                if chg_ratio > max_chg:
                    return None
        
        short_ma = self.calculate_ma(stock_code, self.short_ma_period)
        long_ma = self.calculate_ma(stock_code, self.long_ma_period)
        if short_ma is None or long_ma is None:
            return None
        
        # ----- 매수 신호 (골든크로스) -----
        if stock_code not in self.risk_manager.positions and short_ma > long_ma:
            # 크로스 확인: 직전 틱에는 short <= long 이었을 때만 진짜 골든크로스 (매수에만 적용)
            cross_confirm = int(getattr(self, "cross_confirm_ticks", 0) or 0)
            if cross_confirm > 0:
                prev_short = self.calculate_ma_offset(stock_code, self.short_ma_period, offset=1)
                prev_long = self.calculate_ma_offset(stock_code, self.long_ma_period, offset=1)
                if prev_short is None or prev_long is None:
                    return None
                if prev_short > prev_long:
                    return None  # 직전에도 이미 short > long → 새 크로스 아님, 휩쏘 억제
            
            # 가격이 short_ma 위로 최소 이격 (휩쏘: 살짝만 넘었다 내려가는 구간 억제)
            min_above = float(getattr(self, "min_price_above_short_ma_ratio", 0) or 0)
            if current_price <= short_ma:
                return None
            if min_above > 0 and current_price < short_ma * (1 + min_above):
                return None
            
            # 단기 MA 기울기 필터 (상승 추세 확인)
            slope_min = float(getattr(self, "min_short_ma_slope_ratio", 0) or 0)
            if slope_min > 0 and current_price > 0:
                prev_short_ma = self.calculate_ma_offset(stock_code, self.short_ma_period, offset=1)
                if prev_short_ma is not None:
                    slope_ratio = (short_ma - prev_short_ma) / current_price
                    if slope_ratio < slope_min:
                        return None
            return "buy"
        
        # 데드크로스 연속 확인 카운터: 포지션 없음 또는 MA가 데드크로스가 아니면 리셋
        try:
            if stock_code not in self.risk_manager.positions:
                self._dead_cross_sell_confirm_counts.pop(stock_code, None)
            elif short_ma >= long_ma:
                self._dead_cross_sell_confirm_counts.pop(stock_code, None)
        except Exception:
            pass

        # ----- 매도 신호 (데드크로스) -----
        if short_ma < long_ma and stock_code in self.risk_manager.positions:
            min_hold = int(getattr(self, "min_hold_seconds", 0) or 0)
            if min_hold > 0:
                pos = self.risk_manager.positions.get(stock_code)
                buy_time = pos.get("buy_time") if pos else None
                if isinstance(buy_time, datetime):
                    elapsed = (datetime.now() - buy_time).total_seconds()
                    if elapsed < min_hold:
                        return None
            dc = max(0, min(10, int(getattr(self, "dead_cross_confirm_ticks", 0) or 0)))
            if dc <= 0:
                return "sell"
            cnt = int(self._dead_cross_sell_confirm_counts.get(stock_code) or 0) + 1
            self._dead_cross_sell_confirm_counts[stock_code] = cnt
            if cnt < dc:
                return None
            self._dead_cross_sell_confirm_counts[stock_code] = 0
            return "sell"
        
        return None


# ============================================================================
# 안전한 매매 실행 함수
# ============================================================================

def _classify_order_rejection(resp: dict) -> tuple:
    """
    주문 거절 시 사유 분류. (reason_key, label) 반환.
    reason_key: "vi" | "balance" | "suspended" | "auth" | "unknown"
    """
    if not resp or not isinstance(resp, dict):
        return "unknown", ""
    summary = resp.get("summary") or {}
    msg = (summary.get("msg") or summary.get("MSG1") or "").strip()
    msg_cd = (summary.get("msg_cd") or summary.get("MSG_CD") or "").strip()
    msg_lower = msg.lower()
    if "vi" in msg_lower or "변동성" in msg or "완화장치" in msg:
        return "vi", msg or "VI(변동성완화장치) 발동"
    if "잔고" in msg or "balance" in msg_lower or "예수금" in msg or "주문가능" in msg:
        return "balance", msg or "잔고/주문가능수량 부족"
    if "거래정지" in msg or "정지" in msg or "suspended" in msg_lower or "관리" in msg:
        return "suspended", msg or "거래정지/관리종목"
    if "401" in msg or "unauthorized" in msg_lower or "token" in msg_lower or "인증" in msg or "만료" in msg:
        return "auth", msg or "인증/토큰 만료"
    return "unknown", msg or "주문 거절"


def _extract_order_response(df):
    """order_cash 응답 DataFrame에서 핵심 필드만 추출."""
    try:
        if df is None or getattr(df, "empty", True):
            return {"ok": False, "accepted": False, "confidence": "none"}
        row = df.iloc[0].to_dict() if len(df.index) > 0 else {}
        # 흔히 쓰이는 키 후보들(존재하는 것만 반환)
        keys = [
            "ODNO", "odno",  # 주문번호
            "ORD_TMD", "ord_tmd",  # 주문시각
            "KRX_FWDG_ORD_ORGNO", "krx_fwdg_ord_orgno",  # KRX 전달 주문 org
            "ORD_GNO_BRNO", "ord_gno_brno",  # 주문점번호
            "SLL_BUY_DVSN_CD", "sll_buy_dvsn_cd",
            "MSG_CD", "msg_cd",
            "MSG1", "msg1",
            "RT_CD", "rt_cd",
        ]
        picked = {k: row.get(k) for k in keys if k in row}
        odno = picked.get("ODNO") or picked.get("odno") or ""
        rt_cd = picked.get("RT_CD") or picked.get("rt_cd") or ""
        msg_cd = picked.get("MSG_CD") or picked.get("msg_cd") or ""
        msg = picked.get("MSG1") or picked.get("msg1") or ""

        accepted = False
        confidence = "weak"
        try:
            if str(odno).strip():
                accepted = True
                confidence = "strong"
            else:
                # ODNO가 없더라도 RT_CD=0은 성공으로 내려오는 경우가 있어 보수적으로 인정
                if str(rt_cd).strip() in {"0", "00"}:
                    accepted = True
                    confidence = "medium"
        except Exception:
            accepted = False
            confidence = "weak"

        # 키가 예상과 다르면 최소한의 힌트를 위해 컬럼 목록 제공(값은 제외)
        return {
            "ok": True,
            "accepted": bool(accepted),
            "confidence": confidence,
            "fields": picked,
            "columns": list(df.columns),
            "summary": {
                "odno": str(odno).strip() if odno is not None else "",
                "rt_cd": str(rt_cd).strip() if rt_cd is not None else "",
                "msg_cd": str(msg_cd).strip() if msg_cd is not None else "",
                "msg": str(msg).strip() if msg is not None else "",
            },
        }
    except Exception:
        return {"ok": False, "accepted": False, "confidence": "none"}


def _check_unfilled_order_acceptance(env_dv: str, trenv, ord_dv: str, stock_code: str, odno: str = "") -> dict:
    """
    order_cash 응답이 애매할 때, 미체결 내역 조회로 주문 '접수' 여부를 보조 확인.
    - 주의: "미체결 내역에 있다"는 것은 체결이 아니라 주문 접수/미체결 상태일 수 있습니다.
    """
    try:
        from domestic_stock_functions import inquire_daily_ccld

        cano = getattr(trenv, "my_acct", "") or ""
        acnt_prdt_cd = getattr(trenv, "my_prod", "") or ""
        if not cano or not acnt_prdt_cd:
            return {"ok": False, "found": False, "reason": "missing_account"}

        tz = timezone(timedelta(hours=9))
        today = datetime.now(tz).strftime("%Y%m%d")
        sll_buy = "02" if str(ord_dv).lower() == "buy" else "01"

        df1, _ = inquire_daily_ccld(
            env_dv=env_dv,
            pd_dv="inner",
            cano=cano,
            acnt_prdt_cd=acnt_prdt_cd,
            inqr_strt_dt=today,
            inqr_end_dt=today,
            sll_buy_dvsn_cd=sll_buy,
            ccld_dvsn="02",  # 미체결
            inqr_dvsn="00",
            inqr_dvsn_3="00",
            pdno=str(stock_code).strip().zfill(6),
            odno=str(odno or "").strip(),
        )
        if df1 is None or getattr(df1, "empty", True):
            return {"ok": True, "found": False, "rows": 0}

        odno = ""
        try:
            if "ODNO" in df1.columns:
                odno = str(df1.iloc[0].get("ODNO") or "").strip()
            elif "odno" in df1.columns:
                odno = str(df1.iloc[0].get("odno") or "").strip()
        except Exception:
            odno = ""

        return {"ok": True, "found": True, "rows": int(len(df1.index)), "odno": odno, "columns": list(df1.columns)}
    except Exception as e:
        return {"ok": False, "found": False, "reason": str(e)}


def _check_filled_order(env_dv: str, trenv, ord_dv: str, stock_code: str, odno: str = "") -> dict:
    """일별주문체결조회에서 '체결'(ccld_dvsn=01) 여부 확인."""
    try:
        from domestic_stock_functions import inquire_daily_ccld

        cano = getattr(trenv, "my_acct", "") or ""
        acnt_prdt_cd = getattr(trenv, "my_prod", "") or ""
        if not cano or not acnt_prdt_cd:
            return {"ok": False, "found": False, "reason": "missing_account"}

        tz = timezone(timedelta(hours=9))
        today = datetime.now(tz).strftime("%Y%m%d")
        sll_buy = "02" if str(ord_dv).lower() == "buy" else "01"

        df1, _ = inquire_daily_ccld(
            env_dv=env_dv,
            pd_dv="inner",
            cano=cano,
            acnt_prdt_cd=acnt_prdt_cd,
            inqr_strt_dt=today,
            inqr_end_dt=today,
            sll_buy_dvsn_cd=sll_buy,
            ccld_dvsn="01",  # 체결
            inqr_dvsn="00",
            inqr_dvsn_3="00",
            pdno=str(stock_code).strip().zfill(6),
            odno=str(odno or "").strip(),
        )
        if df1 is None or getattr(df1, "empty", True):
            return {"ok": True, "found": False, "rows": 0}

        # 체결조회는 ODNO가 없을 수도 있으니 rows만으로도 '있음' 판정
        exec_qty = 0
        exec_px = 0.0
        try:
            qty_total_cols = ["TOT_CCLD_QTY", "tot_ccld_qty", "CCLD_QTY_TOT", "ccld_qty_tot"]
            qty_line_cols = ["CCLD_QTY", "ccld_qty", "ORD_QTY", "ord_qty"]
            px_cols = ["CCLD_UNPR", "ccld_unpr", "CCLD_PRC", "ccld_prc", "AVG_PRC", "avg_prc", "AVG_UNPR", "avg_unpr", "ORD_UNPR", "ord_unpr"]

            max_tot = 0
            sum_q = 0
            w_px = 0.0
            for _, row in df1.iterrows():
                r = row.to_dict()
                tq = 0
                for c in qty_total_cols:
                    try:
                        v = r.get(c)
                        if v not in (None, "", " "):
                            tq = int(float(v))
                            break
                    except Exception:
                        continue
                if tq > max_tot:
                    max_tot = tq

                cq = 0
                for c in qty_line_cols:
                    try:
                        v = r.get(c)
                        if v not in (None, "", " "):
                            cq = int(float(v))
                            break
                    except Exception:
                        continue
                cp = 0.0
                for c in px_cols:
                    try:
                        v = r.get(c)
                        if v not in (None, "", " "):
                            cp = float(v)
                            break
                    except Exception:
                        continue
                if cq > 0 and cp > 0:
                    sum_q += cq
                    w_px += cq * cp

            exec_qty = max_tot if max_tot > 0 else sum_q
            if sum_q > 0:
                exec_px = w_px / sum_q
        except Exception:
            exec_qty = 0
            exec_px = 0.0
        return {
            "ok": True,
            "found": True,
            "rows": int(len(df1.index)),
            "columns": list(df1.columns),
            "exec_qty": int(exec_qty or 0),
            "exec_px": float(exec_px or 0.0),
        }
    except Exception as e:
        return {"ok": False, "found": False, "reason": str(e)}


def _call_with_network_retry(callable_fn, max_network_retries: int = 3, base_delay_ms: int = 1000, use_exponential: bool = True):
    """네트워크 오류 시 재시도(지수 백오프). callable_fn() 인자 없음. (result, last_error) 반환."""
    last_err = None
    for attempt in range(max(1, max_network_retries + 1)):
        try:
            return callable_fn(), None
        except (TimeoutError, ConnectionError, OSError) as e:
            last_err = e
            if attempt < max_network_retries:
                delay_ms = base_delay_ms * (2 ** attempt) if use_exponential else base_delay_ms
                delay_ms = max(100, min(30000, delay_ms))
                logging.warning(f"[네트워크 재시도] {attempt + 1}/{max_network_retries + 1} 실패, {delay_ms}ms 후 재시도: {e}")
                time.sleep(delay_ms / 1000.0)
            else:
                break
    return None, last_err


def safe_execute_order(
    signal: str,
    stock_code: str,
    price: float,
    strategy: QuantStrategy,
    trenv,
    is_paper_trading: bool = True,  # 모의투자 여부
    manual_approval: bool = True,  # 수동 승인 필요 여부
    return_details: bool = False,
    quantity_override: Optional[int] = None,
    selected_stocks_count: Optional[int] = None,  # 선정 종목 수(1~2일 때 잔고 활용 확대)
    sell_trigger_code: Optional[str] = None,  # 매도 시 system 로그·pending 추적용(매수는 무시)
):
    """
    안전한 주문 실행
    
    Args:
        signal: "buy" or "sell"
        stock_code: 종목코드
        price: 현재가
        strategy: 전략 객체
        trenv: KIS 환경 변수
        is_paper_trading: 모의투자 여부 (True: 모의투자, False: 실전투자)
        manual_approval: 수동 승인 필요 여부
        selected_stocks_count: 선정 종목 수. 1~2일 때 종목당 잔고 활용 비율 확대(100%/50%).
    """
    if signal not in ("buy", "sell"):
        if return_details:
            return False, {"ok": False, "reason": f"invalid signal: {signal}"}
        return False

    risk_mgr = strategy.risk_manager
    
    # 환경 설정 확인
    env_dv = "demo" if is_paper_trading else "real"
    
    _sell_tc = ""
    if signal == "sell" and sell_trigger_code:
        _sell_tc = str(sell_trigger_code).strip()
    details = {
        "signal": signal,
        "stock_code": stock_code,
        "price": price,
        "is_paper_trading": is_paper_trading,
        "env_dv": "demo" if is_paper_trading else "real",
        "sell_trigger_code": _sell_tc,
    }
    # 기본 입력 검증: 비정상 값이면 주문 자체를 막아 예기치 않은 주문/예외를 방지
    try:
        if float(price) <= 0:
            raise ValueError("price<=0")
    except Exception:
        if return_details:
            details["ok"] = False
            details["reason"] = "invalid price"
            return False, details
        return False

    if signal == "buy":
        # 거래 수량 계산 (override가 있으면 우선)
        quantity = None
        try:
            if quantity_override is not None and int(quantity_override) > 0:
                quantity = int(quantity_override)
        except Exception:
            quantity = None
        if quantity is None:
            base_qty = risk_mgr.calculate_quantity(price, selected_count=selected_stocks_count)
            quantity = risk_mgr.calculate_quantity_with_volatility(
                stock_code, price, fallback_quantity=base_qty, selected_count=selected_stocks_count
            )
        # 최대 거래 금액 상한으로 수량 상한 적용 (선정 1~2종목일 때 잔고 비율 반영)
        max_amt = float(getattr(risk_mgr, "max_single_trade_amount", 0) or 0)
        if price > 0 and max_amt > 0:
            eff_ratio = risk_mgr.get_effective_position_ratio(selected_stocks_count)
            amt_cap = min(max_amt, float(getattr(risk_mgr, "account_balance", 0) or 0) * eff_ratio)
            if amt_cap > 0:
                qty_cap = max(1, int(amt_cap / price))
                if quantity > qty_cap:
                    quantity = qty_cap
        details["quantity"] = int(quantity)
        
        # 거래 가능 여부 확인
        can_trade, reason = risk_mgr.can_trade(stock_code, price, quantity, selected_count=selected_stocks_count)
        
        if not can_trade:
            logging.warning(f"[매수 거부] {stock_code}: {reason}")
            if return_details:
                details["ok"] = False
                details["reason"] = reason
                return False, details
            return False
        
        # 수동 승인 필요 시
        if manual_approval:
            trade_amount = price * quantity
            print(f"\n{'='*80}")
            print(f"[매수 신호] 종목: {stock_code}")
            print(f"  가격: {price:,.0f}원")
            print(f"  수량: {quantity}주")
            print(f"  거래금액: {trade_amount:,.0f}원")
            print(f"  환경: {'모의투자' if is_paper_trading else '실전투자'}")
            print(f"승인하시겠습니까? (y/n): ", end="")
            approval = input().strip().lower()
            if approval != 'y':
                logging.info(f"[매수 취소] {stock_code}: 사용자 취소")
                return False
        
        # 주문 실행 (시장가/최우선 지정가 + 재시도)
        try:
            style = str(getattr(risk_mgr, "buy_order_style", "market") or "market").strip().lower()
            retries = int(getattr(risk_mgr, "order_retry_count", 0) or 0)
            delay_ms = int(getattr(risk_mgr, "order_retry_delay_ms", 300) or 300)
            fallback_to_mkt = bool(getattr(risk_mgr, "order_fallback_to_market", True))
            retries = max(0, min(10, retries))
            delay_ms = max(0, min(10000, delay_ms))

            attempts = []
            last_result = pd.DataFrame()
            last_style_used = style
            # 네트워크 재시도(Timeout/Connection/OSError)는 별도로 짧게 수행 (주문 중복 방지 위해 과도하게 늘리지 않음)
            net_retries = 2
            base_delay = max(200, min(10000, int(getattr(risk_mgr, "order_retry_base_delay_ms", 1000) or 1000)))
            use_backoff = bool(getattr(risk_mgr, "order_retry_exponential_backoff", True))
            for i in range(retries + 1):
                style_used = last_style_used
                ord_dvsn = "01" if style_used == "market" else "04"  # 04: 최우선 지정가
                ord_unpr = "0"

                def _do_buy(od=ord_dvsn, oq=str(quantity)):
                    return order_cash(
                        env_dv=details["env_dv"],
                        ord_dv="buy",
                        cano=trenv.my_acct,
                        acnt_prdt_cd=trenv.my_prod,
                        pdno=stock_code,
                        ord_dvsn=od,
                        ord_qty=oq,
                        ord_unpr="0",
                        excg_id_dvsn_cd="KRX",
                    )
                result, net_err = _call_with_network_retry(_do_buy, max_network_retries=net_retries, base_delay_ms=base_delay, use_exponential=use_backoff)
                if net_err is not None:
                    raise net_err
                if result is None:
                    raise ConnectionError("order_cash returned None")
                last_result = result
                resp = _extract_order_response(result)
                accepted = bool(resp.get("accepted", False))
                confidence = str(resp.get("confidence", "none") or "none")
                odno_try = ""
                try:
                    odno_try = str((resp.get("summary") or {}).get("odno") or "").strip()
                except Exception:
                    odno_try = ""
                attempts.append({
                    "try": i + 1,
                    "order_style": style_used,
                    "ord_dvsn": ord_dvsn,
                    "empty": bool(getattr(result, "empty", True)),
                    "accepted": accepted,
                    "confidence": confidence,
                    "odno": odno_try,
                })
                if accepted:
                    break

                # 응답이 애매하면(ODNO 없음/empty 등) 미체결 내역으로 접수 여부 확인 후 중복 재시도 방지
                try:
                    odno = ""
                    try:
                        odno = (resp.get("summary") or {}).get("odno") or ""
                    except Exception:
                        odno = ""
                    rt_cd = ""
                    try:
                        rt_cd = (resp.get("summary") or {}).get("rt_cd") or ""
                    except Exception:
                        rt_cd = ""
                    ambiguous = bool(getattr(result, "empty", True)) or (not str(odno).strip() and not str(rt_cd).strip())
                    if ambiguous:
                        chk = _check_unfilled_order_acceptance(details["env_dv"], trenv, "buy", stock_code, odno=str(odno or "").strip())
                        details["unfilled_check"] = chk
                        if chk and chk.get("ok") and chk.get("found"):
                            attempts[-1]["accepted_via_unfilled"] = True
                            break
                except Exception:
                    pass
                # 최우선 지정가가 비면 시장가로 폴백
                if style_used == "best_limit" and fallback_to_mkt:
                    last_style_used = "market"
                if i < retries and delay_ms > 0:
                    time.sleep(delay_ms / 1000.0)

            details["order_attempts"] = attempts
            details["order_response"] = _extract_order_response(last_result)
            details["order_style_used"] = attempts[-1]["order_style"] if attempts else style

            final_accepted = False
            try:
                if attempts:
                    final_accepted = bool(attempts[-1].get("accepted") or attempts[-1].get("accepted_via_unfilled"))
            except Exception:
                final_accepted = False

            if final_accepted:
                details["accepted"] = True
                odno_final = ""
                try:
                    odno_final = str((details["order_response"].get("summary") or {}).get("odno") or "").strip()
                except Exception:
                    odno_final = ""

                filled = False
                try:
                    chk_filled = _check_filled_order(details["env_dv"], trenv, "buy", stock_code, odno=odno_final)
                    chk_unfilled = _check_unfilled_order_acceptance(details["env_dv"], trenv, "buy", stock_code, odno=odno_final)
                    details["filled_check"] = chk_filled
                    details["unfilled_check"] = chk_unfilled
                    if chk_filled and chk_filled.get("ok") and chk_filled.get("found"):
                        filled = True
                    elif chk_unfilled and chk_unfilled.get("ok") and chk_unfilled.get("found"):
                        filled = False
                    else:
                        filled = False
                        details["fill_unknown"] = True
                except Exception:
                    filled = False
                    details["fill_unknown"] = True

                details["filled"] = bool(filled)
                if filled:
                    try:
                        risk_mgr.clear_pending_order(stock_code, side="buy")
                    except Exception:
                        pass
                    exec_price = float(chk_filled.get("exec_px") or 0.0) if isinstance(chk_filled, dict) else 0.0
                    exec_qty = int(chk_filled.get("exec_qty") or 0) if isinstance(chk_filled, dict) else 0
                    if exec_price <= 0:
                        exec_price = float(price)
                    if exec_qty <= 0:
                        exec_qty = int(quantity)
                    risk_mgr.update_position(stock_code, exec_price, exec_qty, "buy")
                    details["executed_price"] = exec_price
                    details["executed_quantity"] = exec_qty
                    logging.info(f"[매수 체결] {stock_code}: {exec_price:,.0f}원, {exec_qty}주, 금액: {exec_price*exec_qty:,.0f}원")
                    details["ok"] = True
                    details["status"] = "filled"
                    if return_details:
                        return True, details
                    return True

                # 접수는 됐으나 체결 미확정/미체결 → pending 기록(중복 주문 방지)
                try:
                    risk_mgr.set_pending_order(
                        stock_code=stock_code,
                        side="buy",
                        quantity=quantity,
                        price=price,
                        env_dv=details["env_dv"],
                        odno=odno_final,
                        reason="accepted_pending",
                        sell_trigger_code="",
                    )
                except Exception:
                    pass
                logging.warning(f"[매수 접수/대기] {stock_code}: odno={odno_final or '-'} qty={quantity} px={price:,.0f}")
                details["ok"] = True
                details["status"] = "accepted_pending"
                if return_details:
                    return True, details
                return True
            else:
                logging.error(f"[매수 실패] {stock_code}: 주문 실패")
                details["ok"] = False
                details["accepted"] = False
                details["filled"] = False
                details["status"] = "rejected"
                rej_key, rej_msg = _classify_order_rejection(details.get("order_response"))
                details["rejection_reason"] = rej_key
                details["rejection_message"] = rej_msg
                if rej_msg:
                    logging.warning(f"[매수 거절] {stock_code}: {rej_msg}")
                if return_details:
                    return False, details
                return False

        except (TimeoutError, ConnectionError, OSError) as e:
            err_str = str(e).lower()
            if "401" in err_str or "unauthorized" in err_str or "token" in err_str:
                details["error_type"] = "auth_expired"
                details["error"] = "토큰 만료 가능성. 재로그인 후 이용하세요."
                logging.error(f"[매수 오류-인증] {stock_code}: 토큰 만료 가능성")
            else:
                details["error_type"] = "network"
                details["error"] = f"API 지연/연결 실패: {e}"
                logging.error(f"[매수 오류-네트워크] {stock_code}: {e}")
            details["ok"] = False
            details["accepted"] = False
            details["filled"] = False
            details["status"] = "error"
            if return_details:
                return False, details
            return False
        except Exception as e:
            err_str = str(e).lower()
            if "401" in err_str or "unauthorized" in err_str or "token" in err_str:
                details["error_type"] = "auth_expired"
                details["error"] = "토큰 만료 가능성. 재로그인 후 이용하세요."
            else:
                details["error"] = str(e)
            logging.error(f"[매수 오류] {stock_code}: {details.get('error', e)}")
            import traceback
            traceback.print_exc()
            details["ok"] = False
            details["accepted"] = False
            details["filled"] = False
            details["status"] = "error"
            if return_details:
                return False, details
            return False
    
    elif signal == "sell":
        # 이미 매도 주문이 체결 대기 중이면 중복 매도 방지
        try:
            if getattr(risk_mgr, "has_pending_order", None) and risk_mgr.has_pending_order(stock_code=stock_code, side="sell"):
                details["ok"] = False
                details["reason"] = "pending_sell_order"
                details["accepted"] = False
                details["filled"] = False
                details["status"] = "rejected"
                if return_details:
                    return False, details
                return False
        except Exception:
            pass
        if stock_code not in risk_mgr.positions:
            details["ok"] = False
            details["reason"] = "no_position"
            if return_details:
                return False, details
            return False
        
        position = risk_mgr.positions[stock_code]
        quantity = int(position.get("quantity") or 0)
        try:
            if quantity_override is not None and int(quantity_override) > 0:
                quantity = min(quantity, int(quantity_override))
        except Exception:
            pass
        details["quantity"] = int(quantity)
        if quantity <= 0:
            details["ok"] = False
            details["reason"] = "invalid quantity"
            if return_details:
                return False, details
            return False
        
        # 수동 승인 필요 시
        if manual_approval:
            pnl = (price - position["buy_price"]) * quantity
            pnl_ratio = ((price / position["buy_price"]) - 1) * 100
            print(f"\n{'='*80}")
            print(f"[매도 신호] 종목: {stock_code}")
            print(f"  가격: {price:,.0f}원")
            print(f"  수량: {quantity}주")
            print(f"  매수가: {position['buy_price']:,.0f}원")
            print(f"  손익: {pnl:+,.0f}원 ({pnl_ratio:+.2f}%)")
            print(f"  환경: {'모의투자' if is_paper_trading else '실전투자'}")
            print(f"승인하시겠습니까? (y/n): ", end="")
            approval = input().strip().lower()
            if approval != 'y':
                logging.info(f"[매도 취소] {stock_code}: 사용자 취소")
                return False
        
        # 주문 실행 (시장가/최우선 지정가 + 재시도)
        try:
            style = str(getattr(risk_mgr, "sell_order_style", "market") or "market").strip().lower()
            trigger_code = str(details.get("sell_trigger_code") or "").strip().lower()
            # Risk/exit-critical triggers should prioritize fill certainty.
            force_market_triggers = (
                "risk_",
                "strategy_ma_dead_cross",
                "time_liquidation",
                "daily_",
                "exchange_",
                "emergency_",
                "manual_liquidation",
            )
            if any(trigger_code.startswith(x) for x in force_market_triggers):
                style = "market"
            retries = int(getattr(risk_mgr, "order_retry_count", 0) or 0)
            delay_ms = int(getattr(risk_mgr, "order_retry_delay_ms", 300) or 300)
            fallback_to_mkt = bool(getattr(risk_mgr, "order_fallback_to_market", True))
            retries = max(0, min(10, retries))
            delay_ms = max(0, min(10000, delay_ms))

            attempts = []
            last_result = pd.DataFrame()
            last_style_used = style
            net_retries = 2
            base_delay = max(200, min(10000, int(getattr(risk_mgr, "order_retry_base_delay_ms", 1000) or 1000)))
            use_backoff = bool(getattr(risk_mgr, "order_retry_exponential_backoff", True))
            for i in range(retries + 1):
                style_used = last_style_used
                ord_dvsn = "01" if style_used == "market" else "04"
                ord_unpr = "0"

                def _do_sell(od=ord_dvsn, oq=str(quantity)):
                    return order_cash(
                        env_dv=details["env_dv"],
                        ord_dv="sell",
                        cano=trenv.my_acct,
                        acnt_prdt_cd=trenv.my_prod,
                        pdno=stock_code,
                        ord_dvsn=od,
                        ord_qty=oq,
                        ord_unpr="0",
                        excg_id_dvsn_cd="KRX",
                    )
                result, net_err = _call_with_network_retry(_do_sell, max_network_retries=net_retries, base_delay_ms=base_delay, use_exponential=use_backoff)
                if net_err is not None:
                    raise net_err
                if result is None:
                    raise ConnectionError("order_cash returned None")
                last_result = result
                resp = _extract_order_response(result)
                accepted = bool(resp.get("accepted", False))
                confidence = str(resp.get("confidence", "none") or "none")
                odno_try = ""
                try:
                    odno_try = str((resp.get("summary") or {}).get("odno") or "").strip()
                except Exception:
                    odno_try = ""
                attempts.append({
                    "try": i + 1,
                    "order_style": style_used,
                    "ord_dvsn": ord_dvsn,
                    "empty": bool(getattr(result, "empty", True)),
                    "accepted": accepted,
                    "confidence": confidence,
                    "odno": odno_try,
                })
                if accepted:
                    break

                # 응답이 애매하면(ODNO 없음/empty 등) 미체결 내역으로 접수 여부 확인 후 중복 재시도 방지
                try:
                    odno = ""
                    try:
                        odno = (resp.get("summary") or {}).get("odno") or ""
                    except Exception:
                        odno = ""
                    rt_cd = ""
                    try:
                        rt_cd = (resp.get("summary") or {}).get("rt_cd") or ""
                    except Exception:
                        rt_cd = ""
                    ambiguous = bool(getattr(result, "empty", True)) or (not str(odno).strip() and not str(rt_cd).strip())
                    if ambiguous:
                        chk = _check_unfilled_order_acceptance(details["env_dv"], trenv, "sell", stock_code, odno=str(odno or "").strip())
                        details["unfilled_check"] = chk
                        if chk and chk.get("ok") and chk.get("found"):
                            attempts[-1]["accepted_via_unfilled"] = True
                            break
                except Exception:
                    pass
                if style_used == "best_limit" and fallback_to_mkt:
                    last_style_used = "market"
                if i < retries and delay_ms > 0:
                    time.sleep(delay_ms / 1000.0)

            details["order_attempts"] = attempts
            details["order_response"] = _extract_order_response(last_result)
            details["order_style_used"] = attempts[-1]["order_style"] if attempts else style

            final_accepted = False
            try:
                if attempts:
                    final_accepted = bool(attempts[-1].get("accepted") or attempts[-1].get("accepted_via_unfilled"))
            except Exception:
                final_accepted = False

            if final_accepted:
                details["accepted"] = True
                odno_final = ""
                try:
                    odno_final = str((details["order_response"].get("summary") or {}).get("odno") or "").strip()
                except Exception:
                    odno_final = ""

                filled = False
                try:
                    chk_filled = _check_filled_order(details["env_dv"], trenv, "sell", stock_code, odno=odno_final)
                    chk_unfilled = _check_unfilled_order_acceptance(details["env_dv"], trenv, "sell", stock_code, odno=odno_final)
                    details["filled_check"] = chk_filled
                    details["unfilled_check"] = chk_unfilled
                    if chk_filled and chk_filled.get("ok") and chk_filled.get("found"):
                        filled = True
                    elif chk_unfilled and chk_unfilled.get("ok") and chk_unfilled.get("found"):
                        filled = False
                    else:
                        filled = False
                        details["fill_unknown"] = True
                except Exception:
                    filled = False
                    details["fill_unknown"] = True

                details["filled"] = bool(filled)
                if filled:
                    try:
                        risk_mgr.clear_pending_order(stock_code, side="sell")
                    except Exception:
                        pass
                    exec_price = float(chk_filled.get("exec_px") or 0.0) if isinstance(chk_filled, dict) else 0.0
                    exec_qty = int(chk_filled.get("exec_qty") or 0) if isinstance(chk_filled, dict) else 0
                    if exec_price <= 0:
                        exec_price = float(price)
                    if exec_qty <= 0:
                        exec_qty = int(quantity)
                    pnl = risk_mgr.update_position(stock_code, exec_price, exec_qty, "sell")
                    details["executed_price"] = exec_price
                    details["executed_quantity"] = exec_qty
                    logging.info(f"[매도 체결] {stock_code}: {exec_price:,.0f}원, {exec_qty}주, 손익: {pnl:+,.0f}원")
                    details["ok"] = True
                    details["pnl"] = pnl
                    details["status"] = "filled"
                    if return_details:
                        return True, details
                    return True

                try:
                    risk_mgr.set_pending_order(
                        stock_code=stock_code,
                        side="sell",
                        quantity=quantity,
                        price=price,
                        env_dv=details["env_dv"],
                        odno=odno_final,
                        reason="accepted_pending",
                        sell_trigger_code=str(details.get("sell_trigger_code") or ""),
                    )
                except Exception:
                    pass
                logging.warning(f"[매도 접수/대기] {stock_code}: odno={odno_final or '-'} qty={quantity} px={price:,.0f}")
                details["ok"] = True
                details["status"] = "accepted_pending"
                if return_details:
                    return True, details
                return True
            else:
                logging.error(f"[매도 실패] {stock_code}: 주문 실패")
                details["ok"] = False
                details["accepted"] = False
                details["filled"] = False
                details["status"] = "rejected"
                rej_key, rej_msg = _classify_order_rejection(details.get("order_response"))
                details["rejection_reason"] = rej_key
                details["rejection_message"] = rej_msg
                if rej_msg:
                    logging.warning(f"[매도 거절] {stock_code}: {rej_msg}")
                if return_details:
                    return False, details
                return False

        except (TimeoutError, ConnectionError, OSError) as e:
            err_str = str(e).lower()
            if "401" in err_str or "unauthorized" in err_str or "token" in err_str:
                details["error_type"] = "auth_expired"
                details["error"] = "토큰 만료 가능성. 재로그인 후 이용하세요."
                logging.error(f"[매도 오류-인증] {stock_code}: 토큰 만료 가능성")
            else:
                details["error_type"] = "network"
                details["error"] = f"API 지연/연결 실패: {e}"
                logging.error(f"[매도 오류-네트워크] {stock_code}: {e}")
            details["ok"] = False
            details["accepted"] = False
            details["filled"] = False
            details["status"] = "error"
            if return_details:
                return False, details
            return False
        except Exception as e:
            err_str = str(e).lower()
            if "401" in err_str or "unauthorized" in err_str or "token" in err_str:
                details["error_type"] = "auth_expired"
                details["error"] = "토큰 만료 가능성. 재로그인 후 이용하세요."
            else:
                details["error"] = str(e)
            logging.error(f"[매도 오류] {stock_code}: {details.get('error', e)}")
            import traceback
            traceback.print_exc()
            details["ok"] = False
            details["accepted"] = False
            details["filled"] = False
            details["status"] = "error"
            if return_details:
                return False, details
            return False
    
    details["ok"] = False
    details["reason"] = "unknown_signal"
    if return_details:
        return False, details
    return False


# ============================================================================
# WebSocket 실시간 데이터 처리 (리스크 최소화)
# ============================================================================

def create_safe_on_result(strategy: QuantStrategy, trenv, is_paper_trading: bool = True, manual_approval: bool = True):
    """
    안전한 실시간 데이터 처리 함수 생성
    
    Args:
        strategy: 전략 객체
        trenv: KIS 환경 변수
        is_paper_trading: 모의투자 여부
        manual_approval: 수동 승인 필요 여부
    
    Returns:
        on_result 함수
    """
    def on_result(ws, tr_id, result, data_info):
        """실시간 데이터 수신 시 호출"""
        try:
            # 체결가 데이터 처리 (H0STCNT0: 실시간 체결가 TR_ID)
            if tr_id in ["H0STCNT0", "H0STCNT1"]:  # 실제 TR_ID
                if result.empty:
                    return
                
                # 데이터 파싱 (실제 컬럼명 사용)
                for _, row in result.iterrows():
                    # 실제 컬럼명: MKSC_SHRN_ISCD (종목코드), STCK_PRPR (현재가)
                    stock_code = str(row.get("MKSC_SHRN_ISCD", "")).strip().zfill(6)
                    current_price = float(row.get("STCK_PRPR", 0))
                    
                    if not stock_code or current_price == 0:
                        continue
                    
                    # 가격 업데이트 (변동 추적용)
                    strategy.risk_manager.update_price(stock_code, current_price)
                    
                    # 손절매/익절매 체크 (최우선)
                    sell_signal = strategy.risk_manager.check_stop_loss_take_profit(
                        stock_code, current_price
                    )
                    if sell_signal:
                        logging.warning(f"[손절/익절 신호] {stock_code}: {current_price:,.0f}원")
                        safe_execute_order("sell", stock_code, current_price, strategy, trenv, is_paper_trading, manual_approval)
                        continue
                    
                    # 매매 신호 생성
                    signal = strategy.get_signal(stock_code, current_price)
                    if signal:
                        logging.info(f"[매매 신호] {stock_code}: {signal}, 가격: {current_price:,.0f}원")
                        safe_execute_order(signal, stock_code, current_price, strategy, trenv, is_paper_trading, manual_approval)
            
            # 로깅 (다른 TR_ID도 처리)
            if tr_id not in ["H0STCNT0", "H0STCNT1"]:
                logging.debug(f"[실시간 데이터] TR_ID: {tr_id}, 레코드 수: {len(result)}")
            
        except Exception as e:
            logging.error(f"[오류] 실시간 데이터 처리 중: {e}")
            import traceback
            traceback.print_exc()
    
    return on_result


# ============================================================================
# 사용 예제
# ============================================================================

if __name__ == "__main__":
    # 로깅 설정
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(f'quant_trading_{datetime.now().strftime("%Y%m%d")}.log', encoding='utf-8'),
            logging.StreamHandler()
        ]
    )
    
    # ⚠️ 모의투자 환경으로 설정 필수! (안전을 위해 기본값은 모의투자)
    USE_PAPER_TRADING = True  # True: 모의투자, False: 실전투자
    
    if USE_PAPER_TRADING:
        svr = "vps"  # 모의투자
        env_dv = "demo"
        env_name = "모의투자"
    else:
        svr = "prod"  # 실전투자
        env_dv = "real"
        env_name = "실전투자"
    
    ka.changeTREnv(None, svr=svr, product="01")
    ka.auth()
    ka.auth_ws()
    trenv = ka.getTREnv()
    
    # 리스크 관리자 및 전략 초기화
    # 계좌 잔고는 실제 조회 필요 (예제에서는 기본값 사용)
    account_balance = 100000  # 10만원 (실제로는 API로 조회)
    risk_manager = RiskManager(account_balance=account_balance)
    strategy = QuantStrategy(risk_manager)
    
    # WebSocket 설정
    kws = ka.KISWebSocket(api_url="/tryitout")
    
    # 실시간 체결가 구독 (예: 삼성전자, SK하이닉스)
    kws.subscribe(request=ccnl_krx, data=["005930", "000660"])
    
    # 안전한 on_result 함수 생성
    on_result = create_safe_on_result(
        strategy, 
        trenv, 
        is_paper_trading=USE_PAPER_TRADING,
        manual_approval=True
    )
    
    print("=" * 80)
    print("퀀트 매매 시스템 시작")
    print("=" * 80)
    print(f"환경: {env_name} ({env_dv})")
    print(f"계좌 잔고: {account_balance:,}원")
    print(f"일일 손실 한도: {risk_manager.daily_loss_limit:,}원")
    print(f"최대 거래 금액: {risk_manager.max_single_trade_amount:,}원")
    print(f"최대 포지션 크기: {account_balance * risk_manager.max_position_size_ratio:,.0f}원 ({risk_manager.max_position_size_ratio*100}%)")
    print(f"일일 최대 거래 횟수: {risk_manager.max_trades_per_day}회 (매수+매도 = 1회)")
    print(f"손절매: {risk_manager.stop_loss_ratio*100}%, 익절매: {risk_manager.take_profit_ratio*100}%")
    print(f"최소 가격 변동: {risk_manager.min_price_change_ratio*100}%")
    print("=" * 80)
    print("⚠️  모든 거래는 수동 승인이 필요합니다!")
    print("⚠️  시장가 주문을 사용합니다 (체결 보장)")
    print("종료하려면 Ctrl+C를 누르세요")
    print("=" * 80)
    
    try:
        kws.start(on_result=on_result)
    except KeyboardInterrupt:
        print("\n\n시스템 종료")
        print("=" * 80)
        print(f"일일 손익: {risk_manager.daily_pnl:+,.0f}원")
        print(f"일일 거래 횟수: {risk_manager.daily_trades}회")
        print(f"보유 포지션: {len(risk_manager.positions)}개")
        if risk_manager.positions:
            print("\n보유 종목:")
            for code, pos in risk_manager.positions.items():
                print(f"  {code}: {pos['quantity']}주 @ {pos['buy_price']:,.0f}원")
        print("=" * 80)
    except Exception as e:
        logging.error(f"시스템 오류: {e}")
        import traceback
        traceback.print_exc()
