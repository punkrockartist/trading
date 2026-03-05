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
        # 최소 매수 수량 (0/1이면 사실상 제한 없음)
        self.min_order_quantity = 1
        
        # 손절매/익절매 설정
        self.stop_loss_ratio = 0.02  # 2% 손실 시 매도
        self.take_profit_ratio = 0.05  # 5% 수익 시 매도
        # 트레일링 스탑 (0이면 사용 안 함)
        self.trailing_stop_ratio = 0.0
        self.trailing_activation_ratio = 0.0  # 수익이 이 비율 이상일 때부터 trailing 적용
        # 부분 익절 (0이면 사용 안 함)
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

        # 주문 실행 방식/재시도
        self.buy_order_style = "market"  # market | best_limit
        self.sell_order_style = "market"  # market | best_limit
        self.order_retry_count = 0
        self.order_retry_delay_ms = 300
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
        self.max_trades_per_day = 5  # 하루 최대 거래 횟수 (매수+매도 = 1회)
        self.min_price_change_ratio = 0.01  # 최소 1% 변동 시만 거래
        
        # 현재 상태 추적
        self.daily_trades = 0  # 거래 횟수 (매수+매도 = 1회)
        self.daily_pnl = 0.0
        self.positions: Dict[str, Dict] = {}  # {종목코드: {매수가, 수량, 시간}}
        self.last_prices: Dict[str, float] = {}  # 가격 변동 추적용
        self._price_history: Dict[str, list] = {}  # 변동성 계산용(최근 N틱 가격)
        # 주문 접수는 됐지만 체결이 확정되지 않은 상태(중복 주문 방지용)
        # key: "{stock_code}:{side}" where side in {"buy","sell"}
        self._pending_orders: Dict[str, Dict] = {}
        self.pending_order_ttl_seconds = 120
        # 재진입 쿨다운
        self.reentry_cooldown_seconds = 0
        self._last_exit_at: Dict[str, datetime] = {}
        self._last_exit_reason: Dict[str, str] = {}
        # 포지션별 고점 추적 (트레일링 스탑)
        self._highest_price: Dict[str, float] = {}
        # 동시성: 엔진 스레드 vs reconcile 루프에서 positions/_pending_orders 보호
        self._lock = threading.Lock()
        
    def can_trade(self, stock_code: str, price: float, quantity: int) -> Tuple[bool, str]:
        """
        거래 가능 여부 확인
        
        Returns:
            (가능여부, 이유)
        """
        # 0. 오늘 신규 매수 중지 상태면 차단
        try:
            tz = timezone(timedelta(hours=9))
            today_key = datetime.now(tz).strftime("%Y%m%d")
            if self.halt_new_buys_day and str(self.halt_new_buys_day) != today_key:
                self.halt_new_buys_day = ""
                self.halt_new_buys_reason = ""
            if str(self.halt_new_buys_day or "") == today_key:
                return False, str(self.halt_new_buys_reason or "일일 신규 매수 중지")
        except Exception:
            pass

        # 1. 일일 거래 횟수 체크
        if self.daily_trades >= self.max_trades_per_day:
            return False, "일일 거래 횟수 초과"
        
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
        
        # 3. 거래 금액 체크
        trade_amount = price * quantity
        if trade_amount > self.max_single_trade_amount:
            return False, f"거래 금액 초과 (최대: {self.max_single_trade_amount:,}원)"
        
        # 4. 포지션 크기 비율 체크
        max_position_value = self.account_balance * self.max_position_size_ratio
        if trade_amount > max_position_value:
            return False, f"포지션 크기 초과 (최대: {max_position_value:,.0f}원, 계좌의 {self.max_position_size_ratio*100}%)"
        
        # 5. 기존 포지션 체크 (중복 매수 방지)
        if stock_code in self.positions:
            return False, "이미 보유 중인 종목"

        # 5-0. pending 주문이 있으면 중복 주문 방지(특히 지정가/응답 애매 케이스)
        try:
            self._prune_pending_orders()
            if self.has_pending_order(stock_code=stock_code, side="buy"):
                return False, "체결 대기 중인 매수 주문이 있습니다"
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
    
    def calculate_quantity(self, price: float) -> int:
        """
        거래 수량 계산 (계좌 잔고의 일정 비율)
        
        Returns:
            거래 수량
        """
        max_trade_amount = min(
            self.max_single_trade_amount,
            self.account_balance * self.max_position_size_ratio
        )
        # 기본: 금액 기반 수량
        quantity = int(max_trade_amount / price) if price > 0 else 0
        min_q = 1
        try:
            min_q = int(self.min_order_quantity or 1)
        except Exception:
            min_q = 1
        min_q = max(1, min_q)
        quantity = max(min_q, quantity)
        return quantity

    def calculate_quantity_with_volatility(
        self,
        stock_code: str,
        price: float,
        fallback_quantity: int,
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
                max_trade_amount = min(
                    float(getattr(self, "max_single_trade_amount", 0) or 0),
                    float(getattr(self, "account_balance", 0) or 0) * float(getattr(self, "max_position_size_ratio", 0) or 0),
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
                        max_trade_amount = min(
                            float(getattr(self, "max_single_trade_amount", 0) or 0),
                            float(getattr(self, "account_balance", 0) or 0) * float(getattr(self, "max_position_size_ratio", 0) or 0),
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

            # 금액 기반 상한도 같이 적용
            max_trade_amount = min(
                float(getattr(self, "max_single_trade_amount", 0) or 0),
                float(getattr(self, "account_balance", 0) or 0) * float(getattr(self, "max_position_size_ratio", 0) or 0),
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
            self.positions[stock_code] = {
                "buy_price": price,
                "quantity": quantity,
                "buy_time": datetime.now(),
                "partial_taken": False,
                "current_price": float(price),
            }
            self.daily_trades += 1  # 매수 시 거래 횟수 증가
            self.last_prices[stock_code] = price
            self._highest_price[stock_code] = float(price)
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
        Returns:
            {"action":"sell","quantity":int,"reason":str} or None
        """
        if stock_code not in self.positions:
            return None

        pos = self.positions[stock_code]
        buy_price = float(pos.get("buy_price") or 0)
        qty = int(pos.get("quantity") or 0)
        if buy_price <= 0 or qty <= 0:
            return None

        # 슬리피지 보수 반영: 매수 시 불리하게 체결된 것으로 가정한 기준가
        try:
            bps = float(getattr(self, "slippage_bps", 0) or 0)
            bps = max(0.0, min(500.0, bps))
            effective_buy = buy_price * (1.0 + bps / 10000.0)
        except Exception:
            effective_buy = buy_price
        change_ratio = (float(current_price) - effective_buy) / effective_buy if effective_buy > 0 else 0.0

        # 손절
        if self.stop_loss_ratio and change_ratio <= -float(self.stop_loss_ratio):
            return {"action": "sell", "quantity": qty, "reason": "손절"}

        # 부분 익절
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
                return {"action": "sell", "quantity": sell_qty, "reason": "부분익절"}
        except Exception:
            pass

        # 익절(전량)
        if self.take_profit_ratio and change_ratio >= float(self.take_profit_ratio):
            return {"action": "sell", "quantity": qty, "reason": "익절"}

        # 트레일링 스탑
        try:
            if self.trailing_stop_ratio and float(self.trailing_stop_ratio) > 0:
                highest = float(self._highest_price.get(stock_code) or buy_price)
                if highest > 0:
                    gain = (highest - buy_price) / buy_price
                    if gain >= float(self.trailing_activation_ratio or 0.0):
                        if float(current_price) <= highest * (1.0 - float(self.trailing_stop_ratio)):
                            return {"action": "sell", "quantity": qty, "reason": "트레일링스탑"}
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
        try:
            bps = float(getattr(self, "slippage_bps", 0) or 0)
            bps = max(0.0, min(500.0, bps))
            effective_buy = buy_price * (1.0 + bps / 10000.0)
        except Exception:
            effective_buy = buy_price
        change_ratio = (current_price - effective_buy) / effective_buy if effective_buy > 0 else 0.0
        
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
        # 실시간 데이터에 맞게 짧은 기간으로 조정
        self.short_ma_period = 3  # 단기 이동평균 (3틱)
        self.long_ma_period = 10  # 장기 이동평균 (10틱)
        self.min_history_length = self.long_ma_period  # 최소 히스토리 길이
        
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
        매매 신호 생성 (실시간 데이터 기반)
        
        Returns:
            "buy", "sell", or None
        """
        # 가격 업데이트
        self.update_price(stock_code, current_price)
        
        # 최소 히스토리가 없으면 신호 생성 안 함
        if stock_code not in self.price_history:
            return None
        
        prices = self.price_history[stock_code]
        if len(prices) < self.min_history_length:
            return None
        
        # 이동평균 계산
        short_ma = self.calculate_ma(stock_code, self.short_ma_period)
        long_ma = self.calculate_ma(stock_code, self.long_ma_period)
        
        if short_ma is None or long_ma is None:
            return None
        
        # 골든크로스 (단기 > 장기): 매수 신호
        if short_ma > long_ma and current_price > short_ma:
            # 기존 포지션이 없을 때만 매수
            if stock_code not in self.risk_manager.positions:
                return "buy"
        
        # 데드크로스 (단기 < 장기): 매도 신호
        if short_ma < long_ma and stock_code in self.risk_manager.positions:
            return "sell"
        
        return None


# ============================================================================
# 안전한 매매 실행 함수
# ============================================================================

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
        return {"ok": True, "found": True, "rows": int(len(df1.index)), "columns": list(df1.columns)}
    except Exception as e:
        return {"ok": False, "found": False, "reason": str(e)}


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
    """
    risk_mgr = strategy.risk_manager
    
    # 환경 설정 확인
    env_dv = "demo" if is_paper_trading else "real"
    
    details = {
        "signal": signal,
        "stock_code": stock_code,
        "price": price,
        "is_paper_trading": is_paper_trading,
        "env_dv": "demo" if is_paper_trading else "real",
    }

    if signal == "buy":
        # 거래 수량 계산 (override가 있으면 우선)
        quantity = None
        try:
            if quantity_override is not None and int(quantity_override) > 0:
                quantity = int(quantity_override)
        except Exception:
            quantity = None
        if quantity is None:
            base_qty = risk_mgr.calculate_quantity(price)
            quantity = risk_mgr.calculate_quantity_with_volatility(stock_code, price, fallback_quantity=base_qty)
        details["quantity"] = int(quantity)
        
        # 거래 가능 여부 확인
        can_trade, reason = risk_mgr.can_trade(stock_code, price, quantity)
        
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
            for i in range(retries + 1):
                style_used = last_style_used
                ord_dvsn = "01" if style_used == "market" else "04"  # 04: 최우선 지정가
                ord_unpr = "0"
                result = order_cash(
                    env_dv=details["env_dv"],
                    ord_dv="buy",
                    cano=trenv.my_acct,
                    acnt_prdt_cd=trenv.my_prod,
                    pdno=stock_code,
                    ord_dvsn=ord_dvsn,
                    ord_qty=str(quantity),
                    ord_unpr=ord_unpr,
                    excg_id_dvsn_cd="KRX",
                )
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
                    risk_mgr.update_position(stock_code, price, quantity, "buy")
                    logging.info(f"[매수 체결] {stock_code}: {price:,.0f}원, {quantity}주, 금액: {price*quantity:,.0f}원")
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
                if return_details:
                    return False, details
                return False

        except Exception as e:
            logging.error(f"[매수 오류] {stock_code}: {e}")
            import traceback
            traceback.print_exc()
            details["ok"] = False
            details["error"] = str(e)
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
            retries = int(getattr(risk_mgr, "order_retry_count", 0) or 0)
            delay_ms = int(getattr(risk_mgr, "order_retry_delay_ms", 300) or 300)
            fallback_to_mkt = bool(getattr(risk_mgr, "order_fallback_to_market", True))
            retries = max(0, min(10, retries))
            delay_ms = max(0, min(10000, delay_ms))

            attempts = []
            last_result = pd.DataFrame()
            last_style_used = style
            for i in range(retries + 1):
                style_used = last_style_used
                ord_dvsn = "01" if style_used == "market" else "04"
                ord_unpr = "0"
                result = order_cash(
                    env_dv=details["env_dv"],
                    ord_dv="sell",
                    cano=trenv.my_acct,
                    acnt_prdt_cd=trenv.my_prod,
                    pdno=stock_code,
                    ord_dvsn=ord_dvsn,
                    ord_qty=str(quantity),
                    ord_unpr=ord_unpr,
                    excg_id_dvsn_cd="KRX",
                )
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
                    pnl = risk_mgr.update_position(stock_code, price, quantity, "sell")
                    logging.info(f"[매도 체결] {stock_code}: {price:,.0f}원, {quantity}주, 손익: {pnl:+,.0f}원")
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
                if return_details:
                    return False, details
                return False

        except Exception as e:
            logging.error(f"[매도 오류] {stock_code}: {e}")
            import traceback
            traceback.print_exc()
            details["ok"] = False
            details["error"] = str(e)
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
