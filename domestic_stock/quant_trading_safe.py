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
from datetime import datetime
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
        
        # 거래 제한
        self.max_trades_per_day = 5  # 하루 최대 거래 횟수 (매수+매도 = 1회)
        self.min_price_change_ratio = 0.01  # 최소 1% 변동 시만 거래
        
        # 현재 상태 추적
        self.daily_trades = 0  # 거래 횟수 (매수+매도 = 1회)
        self.daily_pnl = 0.0
        self.positions: Dict[str, Dict] = {}  # {종목코드: {매수가, 수량, 시간}}
        self.last_prices: Dict[str, float] = {}  # 가격 변동 추적용
        # 재진입 쿨다운
        self.reentry_cooldown_seconds = 0
        self._last_exit_at: Dict[str, datetime] = {}
        self._last_exit_reason: Dict[str, str] = {}
        # 포지션별 고점 추적 (트레일링 스탑)
        self._highest_price: Dict[str, float] = {}
        
    def can_trade(self, stock_code: str, price: float, quantity: int) -> Tuple[bool, str]:
        """
        거래 가능 여부 확인
        
        Returns:
            (가능여부, 이유)
        """
        # 1. 일일 거래 횟수 체크
        if self.daily_trades >= self.max_trades_per_day:
            return False, "일일 거래 횟수 초과"
        
        # 2. 일일 손실 한도 체크
        if self.daily_pnl <= -self.daily_loss_limit:
            return False, "일일 손실 한도 초과"

        # 2-1. 일일 이익 한도(목표) 체크: 목표 달성 시 신규 매수 차단
        try:
            if getattr(self, "daily_profit_limit", 0) and float(self.daily_pnl) >= float(self.daily_profit_limit):
                return False, "일일 이익 한도(목표) 달성"
        except Exception:
            pass
        
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
        
        return True, "OK"
    
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
        quantity = int(max_trade_amount / price)
        min_q = 1
        try:
            min_q = int(self.min_order_quantity or 1)
        except Exception:
            min_q = 1
        min_q = max(1, min_q)
        return max(min_q, quantity)
    
    def update_position(self, stock_code: str, price: float, quantity: int, action: str):
        """포지션 업데이트"""
        if action == "buy":
            self.positions[stock_code] = {
                "buy_price": price,
                "quantity": quantity,
                "buy_time": datetime.now(),
                "partial_taken": False,
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

        change_ratio = (float(current_price) - buy_price) / buy_price

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
    
    def update_price(self, stock_code: str, price: float):
        """가격 업데이트 (변동 추적용)"""
        self.last_prices[stock_code] = price
        if stock_code in self.positions:
            prev = self._highest_price.get(stock_code, 0.0)
            if float(price) > float(prev or 0.0):
                self._highest_price[stock_code] = float(price)

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
        
        buy_price = self.positions[stock_code]["buy_price"]
        change_ratio = (current_price - buy_price) / buy_price
        
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
            return {"ok": False}
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
        # 키가 예상과 다르면 최소한의 힌트를 위해 컬럼 목록 제공(값은 제외)
        return {"ok": True, "fields": picked, "columns": list(df.columns)}
    except Exception:
        return {"ok": False}


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
            quantity = risk_mgr.calculate_quantity(price)
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
        
        # 주문 실행
        try:
            result = order_cash(
                env_dv=details["env_dv"],
                ord_dv="buy",
                cano=trenv.my_acct,
                acnt_prdt_cd=trenv.my_prod,
                pdno=stock_code,
                ord_dvsn="01",  # 시장가 (체결 보장)
                ord_qty=str(quantity),
                ord_unpr="0",  # 시장가는 가격 0
                excg_id_dvsn_cd="KRX"
            )
            details["order_response"] = _extract_order_response(result)
            
            if not result.empty:
                risk_mgr.update_position(stock_code, price, quantity, "buy")
                logging.info(f"[매수 체결] {stock_code}: {price:,.0f}원, {quantity}주, 금액: {price*quantity:,.0f}원")
                details["ok"] = True
                if return_details:
                    return True, details
                return True
            else:
                logging.error(f"[매수 실패] {stock_code}: 주문 실패")
                details["ok"] = False
                if return_details:
                    return False, details
                return False
                
        except Exception as e:
            logging.error(f"[매수 오류] {stock_code}: {e}")
            import traceback
            traceback.print_exc()
            details["ok"] = False
            details["error"] = str(e)
            if return_details:
                return False, details
            return False
    
    elif signal == "sell":
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
        
        # 주문 실행
        try:
            result = order_cash(
                env_dv=details["env_dv"],
                ord_dv="sell",
                cano=trenv.my_acct,
                acnt_prdt_cd=trenv.my_prod,
                pdno=stock_code,
                ord_dvsn="01",  # 시장가 (체결 보장)
                ord_qty=str(quantity),
                ord_unpr="0",  # 시장가는 가격 0
                excg_id_dvsn_cd="KRX"
            )
            details["order_response"] = _extract_order_response(result)
            
            if not result.empty:
                pnl = risk_mgr.update_position(stock_code, price, quantity, "sell")
                logging.info(f"[매도 체결] {stock_code}: {price:,.0f}원, {quantity}주, 손익: {pnl:+,.0f}원")
                details["ok"] = True
                details["pnl"] = pnl
                if return_details:
                    return True, details
                return True
            else:
                logging.error(f"[매도 실패] {stock_code}: 주문 실패")
                details["ok"] = False
                if return_details:
                    return False, details
                return False
                
        except Exception as e:
            logging.error(f"[매도 오류] {stock_code}: {e}")
            import traceback
            traceback.print_exc()
            details["ok"] = False
            details["error"] = str(e)
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
