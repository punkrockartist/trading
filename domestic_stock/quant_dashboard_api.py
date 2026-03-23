"""
API 엔드포인트 모듈 (모바일 대시보드용)

기존 quant_dashboard.py의 API를 인증 의존성과 함께 제공
"""

from fastapi import Depends, HTTPException, WebSocket, WebSocketDisconnect, Query, Body
from fastapi.responses import JSONResponse
from typing import Dict, List, Optional, Any
from datetime import datetime, time as dtime, timedelta, timezone
import logging
import asyncio
import threading
import uuid
import time
import os
import json

import kis_auth as ka
from domestic_stock_functions_ws import ccnl_krx, asking_price_krx, market_status_krx
from domestic_stock_functions import inquire_index_daily_price, inquire_index_price, fluctuation, volume_rank, inquire_vi_status

from quant_dashboard import (
    app, state, get_current_user,
    RiskConfig, StockSelectionConfig, StrategyConfig, OperationalConfig, ManualOrder
)
from auth_manager import auth_manager
from stock_selector import StockSelector
from stock_selection_presets import get_preset, list_presets
from quant_trading_safe import safe_execute_order
from audit_log import audit_log, audit_get
from notifier import send_alert
from system_log import system_log_append

try:
    # OpenAI Python SDK (v1.x). AI 리포트 생성을 위해 사용. 환경에 설치·키 설정이 안 되어 있으면 graceful fallback.
    from openai import OpenAI  # type: ignore
except Exception:  # pragma: no cover - 환경 의존
    OpenAI = None  # type: ignore

logger = logging.getLogger(__name__)
pending_signals_lock = threading.Lock()
DEFAULT_STOCK_INFO = [
    {"code": "005930", "name": "삼성전자"},
    {"code": "000660", "name": "SK하이닉스"},
]

_user_settings_store = None
_user_settings_store_init_error: Optional[str] = None
_user_result_store = None
_signal_skip_log_last_at: Dict[str, float] = {}
_signal_skip_log_lock = threading.Lock()
_last_atr_log_ts: Dict[str, float] = {}  # ATR 필터 로그 throttle (종목별 5분)
_last_sap_log_ts: Dict[str, float] = {}  # SAP 필터 로그 throttle (종목별 5분)
_skip_stats_lock = threading.Lock()

# 지수 MA 시장 레짐 캐시: (key -> (current, ma, ts))
_index_ma_cache: Dict[str, tuple] = {}
_index_ma_cache_ttl = 300  # 5분
_index_ma_cache_lock = threading.Lock()

# 거래소 지수 전일대비 변동률 캐시: key = market_code, value = (change_pct, ts). 서킷/사이드카 공용.
_index_change_cache: Dict[str, tuple] = {}
_index_change_cache_ttl = 120  # 2분
_index_change_cache_lock = threading.Lock()

# VI(종목별 변동성완화장치) 캐시: key = stock_code, value = (triggered: bool, ts)
_vi_status_cache: Dict[str, tuple] = {}
_vi_status_cache_ttl = 60  # 1분
_vi_status_cache_lock = threading.Lock()

# WS 장운영정보가 이 시간 이상 갱신 없으면 REST로 재판단 (초)
_VI_WS_STALE_SECONDS = 120


def _get_index_ma_ok(index_code: str, period: int) -> bool:
    """
    지수(코스닥/코스피) 현재가 >= N일 MA 이면 True (매수 허용).
    필터 비활성화/API 오류 시 True 반환(보수적).
    """
    if not index_code or period < 2:
        return True
    key = f"{index_code}_{period}"
    with _index_ma_cache_lock:
        ent = _index_ma_cache.get(key)
        if ent is not None and (time.time() - ent[2]) < _index_ma_cache_ttl:
            cur, ma, _ = ent
            if cur is not None and ma is not None and ma > 0:
                return float(cur) >= float(ma)
            return True
    ma_val, current_val = None, None
    try:
        from datetime import datetime as dt
        now = dt.now(timezone(timedelta(hours=9)))
        today_str = now.strftime("%Y%m%d")
        df1, df2 = inquire_index_daily_price("D", "U", index_code, today_str)
        def _find_close_and_date(df):
            if df is None or df.empty:
                return None, None
            cols = [c for c in df.columns if isinstance(c, str)]
            date_col = None
            close_col = None
            for c in cols:
                c_lower = c.lower()
                if "date" in c_lower or "prdy" in c_lower or "bsop" in c_lower or c_lower == "bstp_nmix_prdy":
                    date_col = c
                if "clos" in c_lower or "prpr" in c_lower or "clpr" in c_lower or c_lower == "bstp_nmix_prpr":
                    close_col = c
            if not close_col and len(cols) >= 2:
                for c in reversed(cols):
                    if str(getattr(df[c].dtype, "name", df[c].dtype)) in ("float64", "int64", "object") and "date" not in (c or "").lower():
                        close_col = c
                        break
            if not date_col and len(cols) >= 1:
                date_col = cols[0]
            return date_col, close_col
        for df in (df1, df2):
            dc, cc = _find_close_and_date(df)
            if dc is None or cc is None:
                continue
            try:
                df_s = df.sort_values(by=dc, ascending=True).tail(max(period, 60))
                closes = df_s[cc].astype(float).dropna()
                if len(closes) < period:
                    continue
                ma_val = float(closes.tail(period).mean())
                current_val = float(closes.iloc[-1])
                break
            except Exception:
                continue
        if ma_val is None or current_val is None:
            with _index_ma_cache_lock:
                _index_ma_cache[key] = (None, None, time.time())
            return True
        try:
            cur_df = inquire_index_price("U", index_code)
            if cur_df is not None and not cur_df.empty:
                for c in cur_df.columns:
                    if c and ("prpr" in c.lower() or "clpr" in c.lower() or "clos" in c.lower()):
                        current_val = float(cur_df[c].iloc[0])
                        break
        except Exception:
            pass
        with _index_ma_cache_lock:
            _index_ma_cache[key] = (current_val, ma_val, time.time())
        return float(current_val) >= float(ma_val)
    except Exception as e:
        logger.debug("index_ma filter fetch failed: %s", e)
        with _index_ma_cache_lock:
            _index_ma_cache[key] = (None, None, time.time())
        return True


def _get_exchange_circuit_breaker_risk(
    market_code: str = "0001",
    threshold_pct: float = -7.0,
) -> tuple:
    """
    거래소 서킷브레이커(급락) 구간 여부 추정. 전일 대비 지수 하락률이 threshold_pct 이하이면 True.
    KRX 1단계 서킷은 전일 대비 약 -8% 하락 시 발동. threshold_pct 기본 -7%로 그 직전 구간부터 신규 매수 스킵.
    Returns:
        (is_risk: bool, change_pct: Optional[float])
    """
    if not market_code:
        return False, None
    with _index_change_cache_lock:
        ent = _index_change_cache.get(market_code)
        if ent is not None and (time.time() - ent[1]) < _index_change_cache_ttl and ent[0] is not None:
            change_pct = ent[0]
            return (change_pct <= threshold_pct, change_pct)
    # 캐시 없으면 조회 (아래 로직으로 change_pct 계산 후 캐시에 넣음)
    prev_close = None
    current_val = None
    try:
        from datetime import datetime as dt
        now = dt.now(timezone(timedelta(hours=9)))
        today_str = now.strftime("%Y%m%d")
        df1, df2 = inquire_index_daily_price("D", "U", market_code, today_str)
        def _find_close_col(df):
            if df is None or df.empty:
                return None
            for c in df.columns:
                if not isinstance(c, str):
                    continue
                c_lower = c.lower()
                if "clpr" in c_lower or "clos" in c_lower or "prpr" in c_lower or c_lower == "bstp_nmix_prpr":
                    return c
            return None
        def _find_date_col(df):
            if df is None or df.empty:
                return None
            for c in df.columns:
                if not isinstance(c, str):
                    continue
                if "date" in c.lower() or "prdy" in c.lower() or "bstp" in c.lower():
                    return c
            return df.columns[0] if len(df.columns) else None
        for df in (df1, df2):
            if df is None or df.empty:
                continue
            dc, cc = _find_date_col(df), _find_close_col(df)
            if not cc:
                continue
            try:
                df_s = df.sort_values(by=dc if dc else df.columns[0], ascending=False).head(5)
                closes = df_s[cc].astype(float).dropna()
                if len(closes) >= 2:
                    prev_close = float(closes.iloc[1])
                elif len(closes) == 1:
                    prev_close = float(closes.iloc[0])
                if prev_close is not None and prev_close > 0:
                    break
            except Exception:
                continue
        if prev_close is None or prev_close <= 0:
            with _index_change_cache_lock:
                _index_change_cache[market_code] = (None, time.time())
            return False, None
        cur_df = inquire_index_price("U", market_code)
        if cur_df is not None and not cur_df.empty:
            for c in cur_df.columns:
                if isinstance(c, str) and ("prpr" in c.lower() or "clpr" in c.lower() or "clos" in c.lower()):
                    try:
                        current_val = float(cur_df[c].iloc[0])
                        break
                    except Exception:
                        pass
        if current_val is None or current_val <= 0:
            with _index_change_cache_lock:
                _index_change_cache[market_code] = (None, time.time())
            return False, None
        change_pct = (current_val - prev_close) / prev_close * 100.0
        with _index_change_cache_lock:
            _index_change_cache[market_code] = (change_pct, time.time())
        return (change_pct <= threshold_pct, change_pct)
    except Exception as e:
        logger.debug("circuit_breaker check failed: %s", e)
        with _index_change_cache_lock:
            _index_change_cache[market_code] = (None, time.time())
        return False, None


def _get_exchange_sidecar_risk(market_code: str = "0001") -> tuple:
    """
    사이드카 발동 가능 구간 추정. (선물이 아닌) 현물 지수 전일대비 변동이 ±5%(코스피) 또는 ±6%(코스닥) 이상이면 True.
    KRX 사이드카: 프로그램매매 5분 정지. 일반 매매는 가능하나 변동성 큼 → 보수적으로 신규 매수 스킵 옵션 제공.
    Returns:
        (is_risk: bool, change_pct: Optional[float])
    """
    if not market_code:
        return False, None
    _, change_pct = _get_exchange_circuit_breaker_risk(market_code, threshold_pct=-20.0)
    if change_pct is None:
        return False, None
    threshold = 6.0 if market_code == "1001" else 5.0  # 코스닥 6%, 코스피 5%
    is_risk = abs(change_pct) >= threshold
    return is_risk, change_pct


def _vi_cls_code_implies_active(raw) -> bool:
    """
    KRX 장운영 VI적용구분코드 등. 0/공백 = 미적용, 그 외 숫자·코드는 적용으로 간주.
    (정적·동적 VI는 보통 1, 2 — 확장 코드는 0이 아니면 적용으로 처리)
    """
    if raw is None:
        return False
    s = str(raw).strip()
    if not s or s.lower() in ("nan", "none"):
        return False
    if s.upper() in ("N", "-", "."):
        return False
    if s in ("0", "00", "000"):
        return False
    if s.isdigit():
        try:
            return int(s) != 0
        except ValueError:
            return True
    return True


def _rest_vi_dataframe_active(df) -> Optional[bool]:
    """
    VI 현황 REST 응답에서 '지금 적용 중'만 True.
    Returns:
        True/False — 컬럼으로 판별됨
        None — VI 관련 컬럼을 못 찾음 (호출부에서 폴백)
    """
    if df is None or getattr(df, "empty", True):
        return False
    found_signal = False
    for col in df.columns:
        cl = str(col).lower().replace(" ", "")
        if "vi" not in cl:
            continue
        if not any(k in cl for k in ("cls", "stts", "stat", "type", "code", "div", "aplc", "yn")):
            continue
        found_signal = True
        for val in df[col].astype(str).str.strip():
            if not val or val.lower() in ("nan", "none"):
                continue
            if _vi_cls_code_implies_active(val):
                return True
    if found_signal:
        return False
    return None


def _get_stock_vi_triggered(stock_code: str) -> bool:
    """
    종목별 VI(변동성완화장치) 적용 여부.
    1) 장운영 WS(H0STMKO0) vi_cls_code가 최근 갱신되어 있으면 우선.
    2) 없거나 오래되면 inquire_vi_status — 행 유무만으로는 판단하지 않고 VI 구분 컬럼으로 판단;
       컬럼을 못 찾으면 레거시(행 있음=True)로만 폴백.
    캐시 1분.
    """
    if not stock_code or len(str(stock_code).strip()) < 6:
        return False
    code = str(stock_code).strip().zfill(6)
    with _vi_status_cache_lock:
        ent = _vi_status_cache.get(code)
        if ent is not None and (time.time() - ent[1]) < _vi_status_cache_ttl:
            return ent[0]

    triggered = False
    try:
        now_ts = time.time()
        ws_map = getattr(state, "_vi_ws_active", None) or {}
        ws_ent = ws_map.get(code)
        if ws_ent is not None and (now_ts - ws_ent[1]) < _VI_WS_STALE_SECONDS:
            triggered = bool(ws_ent[0])
        else:
            tz = timezone(timedelta(hours=9))
            today_str = datetime.now(tz).strftime("%Y%m%d")
            df = inquire_vi_status(
                fid_div_cls_code="0",
                fid_cond_scr_div_code="20139",
                fid_mrkt_cls_code="0",
                fid_input_iscd=code,
                fid_rank_sort_cls_code="0",
                fid_input_date_1=today_str,
                fid_trgt_cls_code="",
                fid_trgt_exls_cls_code="",
            )
            parsed = _rest_vi_dataframe_active(df)
            if parsed is not None:
                triggered = parsed
            else:
                triggered = df is not None and not getattr(df, "empty", True) and len(df) > 0
    except Exception as e:
        logger.debug("VI status check failed for %s: %s", code, e)
    with _vi_status_cache_lock:
        _vi_status_cache[code] = (triggered, time.time())
    return triggered


# 상승 종목 비율 캐시 (등락률 순위 API 기반)
_advance_ratio_cache: Dict[str, tuple] = {}
_advance_ratio_cache_ttl = 300
_advance_ratio_cache_lock = threading.Lock()

# 등락률 순위 API 공통 파라미터 (20170=등락률 화면)
_FLUCT_DEFAULT = {
    "fid_cond_scr_div_code": "20170",
    "fid_rank_sort_cls_code": "0",
    "fid_input_cnt_1": "500",
    "fid_prc_cls_code": "0",
    "fid_input_price_1": "0",
    "fid_input_price_2": "1000000",
    "fid_vol_cnt": "0",
    "fid_trgt_cls_code": "000000000",
    "fid_trgt_exls_cls_code": "0000000000",
    "fid_rsfl_rate1": "0",
    "fid_rsfl_rate2": "100",
}


def _get_advance_ratio(market_code: str) -> Optional[float]:
    """
    등락률 순위 API(fluctuation)로 상승/하락 각각 연속 조회해 전체 건수로 상승 비율 반환.
    상승 비율 = 상승 종목 수 / (상승 종목 수 + 하락 종목 수). 0~1 또는 None(오류 시).
    market_code: 1001=코스닥, 0001=코스피. 캐시 5분.
    """
    if not market_code or market_code not in ("1001", "0001"):
        return None
    key = f"adv_{market_code}"
    with _advance_ratio_cache_lock:
        ent = _advance_ratio_cache.get(key)
        if ent is not None and (time.time() - ent[1]) < _advance_ratio_cache_ttl:
            return ent[0]
    try:
        # J=거래소(코스피), Q=코스닥
        fid_mrkt = "Q" if market_code == "1001" else "J"
        up_df = fluctuation(
            fid_cond_mrkt_div_code=fid_mrkt,
            fid_input_iscd=market_code,
            fid_div_cls_code="1",  # 상승만
            **_FLUCT_DEFAULT,
        )
        down_df = fluctuation(
            fid_cond_mrkt_div_code=fid_mrkt,
            fid_input_iscd=market_code,
            fid_div_cls_code="2",  # 하락만
            **_FLUCT_DEFAULT,
        )
        # 연속 조회로 반환된 전체 상승/하락 종목 수 사용 (fluctuation 내부 연속 조회)
        up_cnt = len(up_df) if up_df is not None and not up_df.empty else 0
        down_cnt = len(down_df) if down_df is not None and not down_df.empty else 0
        total = up_cnt + down_cnt
        if total == 0:
            ratio = 0.5
        else:
            ratio = float(up_cnt) / float(total)
        logger.debug("advance_ratio %s: up=%d down=%d total=%d ratio=%.2f%%", market_code, up_cnt, down_cnt, total, ratio * 100.0)
        with _advance_ratio_cache_lock:
            _advance_ratio_cache[key] = (ratio, time.time())
        return ratio
    except Exception as e:
        logger.debug("advance_ratio fetch failed: %s", e)
        with _advance_ratio_cache_lock:
            _advance_ratio_cache[key] = (None, time.time())
        return None


# 거래대금 집중도 캐시 (거래금액순 1페이지 기준)
_trade_value_concentration_cache: Dict[str, tuple] = {}
_trade_value_concentration_cache_ttl = 300
_trade_value_concentration_cache_lock = threading.Lock()

_VOLUME_RANK_DEFAULT = {
    "fid_cond_scr_div_code": "20171",
    "fid_div_cls_code": "0",
    "fid_blng_cls_code": "3",  # 거래금액순
    "fid_trgt_cls_code": "111111111",
    "fid_trgt_exls_cls_code": "0000000000",
    "fid_input_price_1": "0",
    "fid_input_price_2": "10000000",
    "fid_vol_cnt": "0",
    "fid_input_date_1": "",
}


def _get_trade_value_concentration_ok(
    market_code: str,
    top_n: int,
    denom_n: int,
    max_pct: float,
) -> bool:
    """
    거래금액순(volume_rank blng=3) 1페이지로 상위 top_n / 상위 denom_n 비율 계산.
    비율이 max_pct(%) 초과면 False(매수 스킵), 이하면 True.
    오류 시 True(보수적).
    """
    if top_n < 2 or denom_n < top_n or max_pct <= 0:
        return True
    key = f"tvc_{market_code}_{top_n}_{denom_n}"
    with _trade_value_concentration_cache_lock:
        ent = _trade_value_concentration_cache.get(key)
        if ent is not None and (time.time() - ent[1]) < _trade_value_concentration_cache_ttl:
            ratio = ent[0]
            if ratio is None:
                return True
            return (ratio * 100.0) <= max_pct
    try:
        df = volume_rank(
            fid_cond_mrkt_div_code="J",
            fid_input_iscd=market_code,
            **_VOLUME_RANK_DEFAULT,
        )
        if df is None or df.empty or len(df) < top_n:
            with _trade_value_concentration_cache_lock:
                _trade_value_concentration_cache[key] = (None, time.time())
            return True
        cols = [c for c in df.columns if isinstance(c, str)]
        amt_col = None
        for c in cols:
            c_lower = (c or "").lower()
            if "pbmn" in c_lower or "amt" in c_lower or "acml_tr" in c_lower or "거래" in (c or ""):
                amt_col = c
                break
        if not amt_col and len(cols) >= 2:
            for c in cols:
                if "vol" not in (c or "").lower() and "prdy" not in (c or "").lower():
                    try:
                        df[c].astype(float)
                        amt_col = c
                        break
                    except Exception:
                        continue
        if not amt_col:
            with _trade_value_concentration_cache_lock:
                _trade_value_concentration_cache[key] = (None, time.time())
            return True
        vals = df[amt_col].astype(float).replace([float("nan"), float("inf")], 0.0).fillna(0.0)
        n_use = min(denom_n, len(vals))
        if n_use < top_n:
            with _trade_value_concentration_cache_lock:
                _trade_value_concentration_cache[key] = (None, time.time())
            return True
        sum_denom = float(vals.iloc[:n_use].sum())
        sum_top = float(vals.iloc[:top_n].sum())
        if sum_denom <= 0:
            with _trade_value_concentration_cache_lock:
                _trade_value_concentration_cache[key] = (None, time.time())
            return True
        ratio = sum_top / sum_denom
        with _trade_value_concentration_cache_lock:
            _trade_value_concentration_cache[key] = (ratio, time.time())
        return (ratio * 100.0) <= max_pct
    except Exception as e:
        logger.debug("trade_value_concentration fetch failed: %s", e)
        with _trade_value_concentration_cache_lock:
            _trade_value_concentration_cache[key] = (None, time.time())
        return True


def _get_atr_ratio_from_minute_bars(bars: list, current_price: float, period: int = 14) -> Optional[float]:
    """
    분봉 리스트에서 ATR(period) 계산 후 현재가 대비 비율 반환. bars는 [{"m", "o","h","l","c"}, ...] 시간순.
    봉이 period개 미만이면 None(데이터 부족). None이면 필터에서 매수 스킵 권장.
    반환: ATR/current_price (비율) 또는 None.
    """
    if not bars or period < 2 or current_price <= 0:
        return None
    try:
        tr_list = []
        for i, b in enumerate(bars):
            h = float(b.get("h") or 0)
            l_ = float(b.get("l") or 0)
            c = float(b.get("c") or 0)
            if h <= 0 or l_ < 0:
                continue
            if i == 0:
                tr = h - l_
            else:
                prev_c = float(bars[i - 1].get("c") or 0)
                tr = max(h - l_, abs(h - prev_c), abs(l_ - prev_c))
            tr_list.append(tr)
        if len(tr_list) < period:
            return None
        atr = sum(tr_list[-period:]) / float(period)
        return float(atr) / float(current_price)
    except Exception:
        return None


# SAP: 1봉만 있으면 '세션 평균' 의미가 약하므로 최소 2봉부터 사용. 미달 시 None → 필터에서 매수 스킵
MIN_SAP_BARS = 2


def _get_sap_deviation_pct_from_minute_bars(bars: list, current_price: float) -> Optional[tuple]:
    """
    분봉으로 세션 평균가(SAP) 계산: (h+l+c)/3 의 평균. 이탈률 = (current - SAP) / SAP * 100.
    봉이 MIN_SAP_BARS개 미만이면 None. None이면 필터에서 매수 스킵 권장.
    반환: (sap, 이탈률(%)) 또는 None.
    """
    if not bars or current_price <= 0:
        return None
    try:
        typicals = []
        for b in bars:
            h = float(b.get("h") or 0)
            l_ = float(b.get("l") or 0)
            c = float(b.get("c") or 0)
            if h > 0 or l_ > 0 or c > 0:
                typicals.append((h + l_ + c) / 3.0)
        if not typicals or len(typicals) < MIN_SAP_BARS:
            return None
        sap = sum(typicals) / len(typicals)
        if sap <= 0:
            return None
        dev_pct = (float(current_price) - sap) / sap * 100.0
        return (sap, dev_pct)
    except Exception:
        return None


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
    - 실제 I/O(inquire_daily_ccld) 포함: asyncio.to_thread로 호출되어야 함.
    - 부분 체결: 체결 조회의 exec_qty/exec_px만 반영. RiskManager.update_position이
      부분 매도 시 남은 수량 유지하므로 부분 체결은 정상 처리됨.
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
                # API 지연/세션 끊김 시 이번 라운드는 스킵, 다음 주기에 재시도
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
                    # 추가 매수(동일 종목 누적)도 반영해야 MTS 잔고와 일치함
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
                if getattr(state, "is_paper_trading", True):
                    return f"모의투자: 잔고 API 0건, 시스템 포지션 {len(pos_codes)}건 유지(API 반영 지연 가능)"
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
            if getattr(state, "is_paper_trading", True) and only_pos and not only_balance:
                return (
                    f"모의투자: 잔고에 없음/포지션만 있음 {sorted(only_pos)[:5]}{'…' if len(only_pos) > 5 else ''} (API 지연 가능)"
                )
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
    last_advance_ratio_log_ts = 0.0
    BALANCE_CHECK_INTERVAL_SEC = 60.0
    ADVANCE_RATIO_LOG_INTERVAL_SEC = 300  # 5분

    while True:
        try:
            if not getattr(state, "is_running", False):
                break

            now_ts = time.time()

            # 자동 리밸런싱(종목 주기 재선정)
            # 정책: 실행 중에는 종목 변경 불가(중지→재선정→재시작). 실행 중에는 자동 재선정도 수행하지 않음.
            enable_rebal = bool(getattr(state, "enable_auto_rebalance", False))
            rebal_min = int(getattr(state, "auto_rebalance_interval_minutes", 30) or 30)
            rebal_min = max(5, min(120, rebal_min))
            if enable_rebal and (now_ts - last_rebalance_ts) >= (rebal_min * 60.0):
                last_rebalance_ts = now_ts
                try:
                    await state.broadcast({
                        "type": "log",
                        "level": "warning",
                        "message": "자동 리밸런싱: 실행 중에는 종목을 변경할 수 없어 자동 재선정을 수행하지 않습니다. (중지 → 재선정 → 시작)",
                    })
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

            # 상승 종목 비율 필터 켜져 있을 때 5분마다 비율·설정 하한을 시스템 로그(대시보드+파일)에 기록
            if bool(getattr(state, "advance_ratio_filter_enabled", False)) and (now_ts - last_advance_ratio_log_ts) >= ADVANCE_RATIO_LOG_INTERVAL_SEC:
                last_advance_ratio_log_ts = now_ts
                try:
                    mkt = str(getattr(state, "advance_ratio_market", "1001") or "1001")
                    min_pct = float(getattr(state, "advance_ratio_min_pct", 40.0) or 40.0)
                    ratio = await asyncio.to_thread(_get_advance_ratio, mkt)
                    if ratio is not None:
                        ratio_pct = ratio * 100.0
                        msg = f"상승 종목 비율(5분 갱신): {ratio_pct:.1f}% | 설정 하한(advance_ratio_min_pct): {min_pct:.0f}%"
                    else:
                        msg = f"상승 종목 비율(5분 갱신): 조회 실패 | 설정 하한(advance_ratio_min_pct): {min_pct:.0f}%"
                    await state.broadcast({"type": "log", "level": "info", "message": msg})
                except Exception as e:
                    logger.warning("advance_ratio 로그 오류(무시): %s", e)

            try:
                events = await asyncio.to_thread(
                    _reconcile_pending_orders_sync,
                    max_per_run,
                    2.0,
                )
            except Exception as e:
                logger.warning("Reconcile 실패: %s", e, exc_info=True)
                await asyncio.sleep(2)
                try:
                    events = await asyncio.to_thread(
                        _reconcile_pending_orders_sync,
                        max_per_run,
                        2.0,
                    )
                except Exception as e2:
                    logger.warning("Reconcile 재시도 실패: %s", e2)
                    events = []
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
                            "reason": "체결확인",
                            "order_status": "filled",
                        }
                        state.add_trade(trade_info)
                        await state.broadcast({"type": "trade", "data": trade_info})
                        await state.broadcast({"type": "position", "data": _build_positions_message()})
                        await send_status_update()
                    except Exception:
                        continue

            # 엔진 헬스체크: 틱 미수 N초 시 경고 (WebSocket 끊김 가능성)
            now_ts = time.time()
            if getattr(state, "is_running", False):
                last_tick = getattr(state, "_last_tick_at", 0) or 0
                if last_tick > 0 and (now_ts - last_tick) > 120:
                    last_alert = getattr(state, "_last_tick_alerted_ts", 0) or 0
                    if last_alert == 0 or (now_ts - last_alert) > 300:
                        state._last_tick_alerted_ts = now_ts
                        _run_async_broadcast({
                            "type": "log",
                            "level": "warning",
                            "message": f"엔진 헬스체크: 틱 미수 {int(now_ts - last_tick)}초 (WebSocket 끊김 가능성)",
                        })
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
        if "order_retry_exponential_backoff" in d:
            rm.order_retry_exponential_backoff = bool(d.get("order_retry_exponential_backoff", True))
        if "order_retry_base_delay_ms" in d:
            rm.order_retry_base_delay_ms = max(200, min(10000, int(d.get("order_retry_base_delay_ms") or 1000)))
        if "order_fallback_to_market" in d:
            rm.order_fallback_to_market = bool(d.get("order_fallback_to_market", True))
        if "daily_loss_limit_calendar" in d:
            rm.daily_loss_limit_calendar = bool(d.get("daily_loss_limit_calendar", True))
        if "daily_profit_limit_calendar" in d:
            rm.daily_profit_limit_calendar = bool(d.get("daily_profit_limit_calendar", True))
        if "monthly_loss_limit" in d:
            rm.monthly_loss_limit = max(0, int(d.get("monthly_loss_limit") or 0))
        if "cumulative_loss_limit" in d:
            rm.cumulative_loss_limit = max(0, int(d.get("cumulative_loss_limit") or 0))
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
        if "min_price_change_ratio" in d:
            rm.min_price_change_ratio = max(0.0, min(0.10, float(d.get("min_price_change_ratio") or 0)))
        if "partial_take_profit_ratio" in d:
            rm.partial_take_profit_ratio = float(d.get("partial_take_profit_ratio") or 0.0)
        if "partial_take_profit_fraction" in d:
            rm.partial_take_profit_fraction = float(d.get("partial_take_profit_fraction") or 0.5)
        if "max_trades_per_day" in d:
            rm.max_trades_per_day = int(d.get("max_trades_per_day") or 12)
        if "max_trades_per_stock_per_day" in d:
            rm.max_trades_per_stock_per_day = max(0, min(20, int(d.get("max_trades_per_stock_per_day") or 0)))
        if "max_intraday_vol_pct" in d:
            v = float(d.get("max_intraday_vol_pct") or 0)
            rm.max_intraday_vol_pct = max(0.0, min(20.0, v))
        if "atr_filter_enabled" in d:
            rm.atr_filter_enabled = bool(d.get("atr_filter_enabled", False))
        if "atr_period" in d:
            rm.atr_period = max(2, min(30, int(d.get("atr_period") or 14)))
        if "atr_ratio_max_pct" in d:
            rm.atr_ratio_max_pct = max(0.0, min(20.0, float(d.get("atr_ratio_max_pct") or 0)))
        if "sap_deviation_filter_enabled" in d:
            rm.sap_deviation_filter_enabled = bool(d.get("sap_deviation_filter_enabled", False))
        if "sap_deviation_max_pct" in d:
            rm.sap_deviation_max_pct = max(0.1, min(20.0, float(d.get("sap_deviation_max_pct") or 3.0)))
        if "max_position_size_ratio" in d:
            rm.max_position_size_ratio = float(d.get("max_position_size_ratio") or 0.1)
        if "use_atr_for_stop_take" in d:
            rm.use_atr_for_stop_take = bool(d.get("use_atr_for_stop_take", False))
        if "atr_stop_mult" in d:
            rm.atr_stop_mult = max(0.5, min(5.0, float(d.get("atr_stop_mult") or 1.5)))
        if "atr_take_mult" in d:
            rm.atr_take_mult = max(0.5, min(10.0, float(d.get("atr_take_mult") or 2.0)))
        if "atr_lookback_ticks" in d:
            rm.atr_lookback_ticks = max(2, min(300, int(d.get("atr_lookback_ticks") or 20)))
        if "max_positions_count" in d:
            rm.max_positions_count = max(0, min(50, int(d.get("max_positions_count") or 0)))
        if "expand_position_when_few_stocks" in d:
            rm.expand_position_when_few_stocks = bool(d.get("expand_position_when_few_stocks", True))
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
        if "ws_reconnect_sleep_sec" in d:
            state.ws_reconnect_sleep_sec = max(3, min(60, int(d.get("ws_reconnect_sleep_sec") or 5)))
        if "emergency_liquidate_disconnect_minutes" in d:
            state.emergency_liquidate_disconnect_minutes = max(0, min(120, int(d.get("emergency_liquidate_disconnect_minutes") or 0)))
        if "keep_previous_on_empty_selection" in d:
            state.keep_previous_on_empty_selection = bool(d.get("keep_previous_on_empty_selection", True))
        if "auto_schedule_enabled" in d:
            state.auto_schedule_enabled = bool(d.get("auto_schedule_enabled", False))
        if "auto_start_hhmm" in d:
            state.auto_start_hhmm = str(d.get("auto_start_hhmm", "09:30") or "09:30").strip()[:5]
        if "auto_stop_hhmm" in d:
            state.auto_stop_hhmm = str(d.get("auto_stop_hhmm", "12:00") or "12:00").strip()[:5]
        if "liquidate_on_auto_stop" in d:
            state.liquidate_on_auto_stop = bool(d.get("liquidate_on_auto_stop", True))
        if "auto_schedule_username" in d:
            state.auto_schedule_username = str(d.get("auto_schedule_username", "") or "").strip()
    except Exception as e:
        logger.warning(f"저장된 운영 옵션 적용 중 오류(무시): {e}")


def _apply_strategy_config_to_state(config: "StrategyConfig") -> None:
    """StrategyConfig를 state 및 state.strategy에 반영. POST /api/config/strategy와 DB 로드 시 공통 사용."""
    if getattr(state, "strategy", None):
        short_period = int(config.short_ma_period)
        long_period = int(config.long_ma_period)
        if short_period >= 2 and long_period >= 3 and short_period < long_period:
            state.strategy.short_ma_period = short_period
            state.strategy.long_ma_period = long_period
            state.strategy.min_history_length = long_period
        state.strategy.min_hold_seconds = max(0, int(getattr(config, "min_hold_seconds", 0) or 0))
    start_hhmm = str(getattr(config, "buy_window_start_hhmm", getattr(state, "buy_window_start_hhmm", "09:05")) or "09:05")
    end_hhmm = str(getattr(config, "buy_window_end_hhmm", getattr(state, "buy_window_end_hhmm", "11:30")) or "11:30")
    state.buy_window_start_hhmm = start_hhmm
    state.buy_window_end_hhmm = end_hhmm
    state.min_short_ma_slope_ratio = float(getattr(config, "min_short_ma_slope_ratio", getattr(state, "min_short_ma_slope_ratio", 0.0)) or 0.0)
    state.momentum_lookback_ticks = int(getattr(config, "momentum_lookback_ticks", getattr(state, "momentum_lookback_ticks", 0)) or 0)
    state.min_momentum_ratio = float(getattr(config, "min_momentum_ratio", getattr(state, "min_momentum_ratio", 0.0)) or 0.0)
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
    state.vol_norm_lookback_ticks = int(getattr(config, "vol_norm_lookback_ticks", getattr(state, "vol_norm_lookback_ticks", 20)) or 20)
    state.slope_vs_vol_mult = float(getattr(config, "slope_vs_vol_mult", getattr(state, "slope_vs_vol_mult", 0.0)) or 0.0)
    state.range_vs_vol_mult = float(getattr(config, "range_vs_vol_mult", getattr(state, "range_vs_vol_mult", 0.0)) or 0.0)
    state.enable_morning_regime_split = bool(getattr(config, "enable_morning_regime_split", getattr(state, "enable_morning_regime_split", False)))
    state.morning_regime_early_end_hhmm = str(getattr(config, "morning_regime_early_end_hhmm", getattr(state, "morning_regime_early_end_hhmm", "09:10")) or "09:10")
    state.early_min_short_ma_slope_ratio = float(getattr(config, "early_min_short_ma_slope_ratio", getattr(state, "early_min_short_ma_slope_ratio", 0.0)) or 0.0)
    state.early_momentum_lookback_ticks = int(getattr(config, "early_momentum_lookback_ticks", getattr(state, "early_momentum_lookback_ticks", 0)) or 0)
    state.early_min_momentum_ratio = float(getattr(config, "early_min_momentum_ratio", getattr(state, "early_min_momentum_ratio", 0.0)) or 0.0)
    state.early_buy_confirm_ticks = int(getattr(config, "early_buy_confirm_ticks", getattr(state, "early_buy_confirm_ticks", 1)) or 1)
    state.early_max_spread_ratio = float(getattr(config, "early_max_spread_ratio", getattr(state, "early_max_spread_ratio", 0.0)) or 0.0)
    state.early_range_lookback_ticks = int(getattr(config, "early_range_lookback_ticks", getattr(state, "early_range_lookback_ticks", 0)) or 0)
    state.early_min_range_ratio = float(getattr(config, "early_min_range_ratio", getattr(state, "early_min_range_ratio", 0.0)) or 0.0)
    state.reentry_cooldown_seconds = int(getattr(config, "reentry_cooldown_seconds", getattr(state, "reentry_cooldown_seconds", 240)) or 0)
    if getattr(state, "risk_manager", None):
        state.risk_manager.reentry_cooldown_seconds = int(state.reentry_cooldown_seconds or 0)
    state.consecutive_loss_cooldown_enabled = bool(getattr(config, "consecutive_loss_cooldown_enabled", getattr(state, "consecutive_loss_cooldown_enabled", False)))
    state.consecutive_loss_count_threshold = max(2, min(5, int(getattr(config, "consecutive_loss_count_threshold", getattr(state, "consecutive_loss_count_threshold", 2)) or 2)))
    state.consecutive_loss_cooldown_mult = max(1.0, min(5.0, float(getattr(config, "consecutive_loss_cooldown_mult", getattr(state, "consecutive_loss_cooldown_mult", 2.0)) or 2.0)))
    state.index_ma_filter_enabled = bool(getattr(config, "index_ma_filter_enabled", getattr(state, "index_ma_filter_enabled", False)))
    state.index_ma_code = str(getattr(config, "index_ma_code", getattr(state, "index_ma_code", "1001")) or "1001")
    state.index_ma_period = max(5, min(60, int(getattr(config, "index_ma_period", getattr(state, "index_ma_period", 20)) or 20)))
    state.advance_ratio_filter_enabled = bool(getattr(config, "advance_ratio_filter_enabled", getattr(state, "advance_ratio_filter_enabled", False)))
    state.advance_ratio_market = str(getattr(config, "advance_ratio_market", getattr(state, "advance_ratio_market", "1001")) or "1001")
    state.advance_ratio_min_pct = max(0.0, min(100.0, float(getattr(config, "advance_ratio_min_pct", getattr(state, "advance_ratio_min_pct", 35.0)) or 35.0)))
    state.circuit_breaker_filter_enabled = bool(getattr(config, "circuit_breaker_filter_enabled", getattr(state, "circuit_breaker_filter_enabled", True)))
    state.circuit_breaker_market = str(getattr(config, "circuit_breaker_market", getattr(state, "circuit_breaker_market", "0001")) or "0001")
    state.circuit_breaker_threshold_pct = max(-20.0, min(0.0, float(getattr(config, "circuit_breaker_threshold_pct", getattr(state, "circuit_breaker_threshold_pct", -7.0)) or -7.0)))
    state.circuit_breaker_action = str(getattr(config, "circuit_breaker_action", getattr(state, "circuit_breaker_action", "skip_buy_only")) or "skip_buy_only").strip().lower()
    if state.circuit_breaker_action not in ("skip_buy_only", "liquidate_all", "liquidate_partial", "no_buy_rest_of_day"):
        state.circuit_breaker_action = "skip_buy_only"
    state.sidecar_filter_enabled = bool(getattr(config, "sidecar_filter_enabled", getattr(state, "sidecar_filter_enabled", True)))
    state.sidecar_market = str(getattr(config, "sidecar_market", getattr(state, "sidecar_market", "0001")) or "0001")
    state.sidecar_cooling_minutes = max(1, min(30, int(getattr(config, "sidecar_cooling_minutes", getattr(state, "sidecar_cooling_minutes", 5)) or 5)))
    state.sidecar_action = str(getattr(config, "sidecar_action", getattr(state, "sidecar_action", "skip_buy_only")) or "skip_buy_only").strip().lower()
    if state.sidecar_action not in ("skip_buy_only", "liquidate_all", "liquidate_partial", "no_buy_rest_of_day"):
        state.sidecar_action = "skip_buy_only"
    state.vi_filter_enabled = bool(getattr(config, "vi_filter_enabled", getattr(state, "vi_filter_enabled", True)))
    state.vi_cooling_minutes = max(1, min(30, int(getattr(config, "vi_cooling_minutes", getattr(state, "vi_cooling_minutes", 5)) or 5)))
    state.trade_value_concentration_filter_enabled = bool(getattr(config, "trade_value_concentration_filter_enabled", getattr(state, "trade_value_concentration_filter_enabled", False)))
    state.trade_value_concentration_market = str(getattr(config, "trade_value_concentration_market", getattr(state, "trade_value_concentration_market", "1001")) or "1001")
    state.trade_value_concentration_top_n = max(2, min(20, int(getattr(config, "trade_value_concentration_top_n", getattr(state, "trade_value_concentration_top_n", 10)) or 10)))
    state.trade_value_concentration_denom_n = max(state.trade_value_concentration_top_n + 1, min(50, int(getattr(config, "trade_value_concentration_denom_n", getattr(state, "trade_value_concentration_denom_n", 30)) or 30)))
    state.trade_value_concentration_max_pct = max(10.0, min(80.0, float(getattr(config, "trade_value_concentration_max_pct", getattr(state, "trade_value_concentration_max_pct", 45.0)) or 45.0)))
    state.buy_confirm_ticks = int(getattr(config, "buy_confirm_ticks", getattr(state, "buy_confirm_ticks", 1)) or 1)
    state.enable_time_liquidation = bool(getattr(config, "enable_time_liquidation", getattr(state, "enable_time_liquidation", False)))
    state.liquidate_after_hhmm = str(getattr(config, "liquidate_after_hhmm", getattr(state, "liquidate_after_hhmm", "11:55")) or "11:55")
    state.max_spread_ratio = float(getattr(config, "max_spread_ratio", getattr(state, "max_spread_ratio", 0.0)) or 0.0)
    state.range_lookback_ticks = int(getattr(config, "range_lookback_ticks", getattr(state, "range_lookback_ticks", 0)) or 0)
    state.min_range_ratio = float(getattr(config, "min_range_ratio", getattr(state, "min_range_ratio", 0.0)) or 0.0)
    state.use_sap_revert_entry = bool(getattr(config, "use_sap_revert_entry", getattr(state, "use_sap_revert_entry", False)))
    # 주의: `or`는 0.0을 falsy로 간주해서 기본값으로 덮어쓸 수 있음.
    _sap_from = getattr(config, "sap_revert_entry_from_pct", getattr(state, "sap_revert_entry_from_pct", -1.5))
    state.sap_revert_entry_from_pct = float(_sap_from if _sap_from is not None else -1.5)
    _sap_to = getattr(config, "sap_revert_entry_to_pct", getattr(state, "sap_revert_entry_to_pct", -0.5))
    state.sap_revert_entry_to_pct = float(_sap_to if _sap_to is not None else -0.5)
    state.min_volume_ratio_for_entry = max(0.0, min(5.0, float(getattr(config, "min_volume_ratio_for_entry", 0.0) or 0.0)))
    state.min_trade_amount_ratio_for_entry = max(0.0, min(5.0, float(getattr(config, "min_trade_amount_ratio_for_entry", 0.0) or 0.0)))
    state.skip_buy_first_minutes = max(0, min(30, int(getattr(config, "skip_buy_first_minutes", 0) or 0)))
    state.relative_strength_filter_enabled = bool(getattr(config, "relative_strength_filter_enabled", False))
    state.relative_strength_index_code = str(getattr(config, "relative_strength_index_code", "0001") or "0001")
    state.relative_strength_margin_pct = float(getattr(config, "relative_strength_margin_pct", 0.0) or 0.0)
    state.last_minutes_no_buy = max(0, min(60, int(getattr(config, "last_minutes_no_buy", 0) or 0)))
    state.advance_ratio_down_market_skip = bool(getattr(config, "advance_ratio_down_market_skip", True))
    state.skip_buy_below_high_pct = max(0.0, min(0.20, float(getattr(config, "skip_buy_below_high_pct", 0.0) or 0.0)))


def _apply_strategy_config_dict_to_state(d: dict) -> None:
    """DB에서 불러온 strategy_config를 state에 반영. StrategyConfig로 검증 후 _apply_strategy_config_to_state 호출."""
    if not d or not isinstance(d, dict):
        return
    try:
        config = StrategyConfig.model_validate(d)
        _apply_strategy_config_to_state(config)
    except Exception as e:
        logger.warning(f"저장된 전략 설정 적용 중 오류(무시): {e}")


def _apply_stock_selection_config_dict_to_state(d: dict) -> None:
    """DB에서 불러온 stock_selection_config를 state.stock_selector에 반영. 시작 시 저장된 기준으로 종목 선정하기 위함."""
    if not d or not isinstance(d, dict):
        return
    try:
        config = StockSelectionConfig.model_validate(d)
    except Exception:
        return
    try:
        state.stock_selector = StockSelector(
            env_dv="demo" if getattr(state, "is_paper_trading", True) else "real",
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
            max_drawdown_from_high_ratio=float(getattr(config, "max_drawdown_from_high_ratio", 0.12) or 0.12),
            drawdown_filter_after_hhmm=getattr(config, "drawdown_filter_after_hhmm", "12:00"),
            kospi_only=bool(getattr(config, "kospi_only", False)),
        )
    except Exception as e:
        logger.warning(f"저장된 종목선정 설정 적용 중 오류(무시): {e}")


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


def _get_user_result_store():
    global _user_result_store
    if _user_result_store is not None:
        return _user_result_store
    try:
        from user_result_store import DynamoDBUserResultStore
        _user_result_store = DynamoDBUserResultStore()
    except Exception as e:
        logger.warning(f"User result store init failed: {e}")
        _user_result_store = None
    return _user_result_store


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
        summary = resp.get("summary") or {}
        odno = fields.get("ODNO") or fields.get("odno") or summary.get("odno") or "-"
        ord_tmd = fields.get("ORD_TMD") or fields.get("ord_tmd") or "-"
        msg = fields.get("MSG1") or fields.get("msg1") or summary.get("msg") or fields.get("message") or ""
        msg_cd = fields.get("MSG_CD") or fields.get("msg_cd") or summary.get("msg_cd") or ""
        rt_cd = fields.get("RT_CD") or fields.get("rt_cd") or summary.get("rt_cd") or ""

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
        if not ok and (details.get("error") or details.get("reason")):
            err = details.get("error") or details.get("reason")
            tail += f" | reason={err}"
        if details.get("rejection_message"):
            tail += f" | 거절사유={details['rejection_message']}"
        if details.get("error_type") == "auth_expired":
            tail += " | 토큰 만료 가능성, 재로그인 권장"
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


def _sync_positions_from_balance_sync() -> int:
    """KIS 잔고조회(df1) 기준으로 risk_manager.positions를 강제 동기화. 반환: 반영된 보유 종목 수.
    모의환경에서는 조회구분(INQR_DVSN) 등에 따라 df1이 비어 나오는 경우가 있어 몇 가지 조합으로 재시도한다.
    """
    try:
        rm = getattr(state, "risk_manager", None)
        trenv = getattr(state, "trenv", None)
        if not rm or not trenv:
            return 0
        cano = getattr(trenv, "my_acct", "") or ""
        acnt_prdt_cd = getattr(trenv, "my_prod", "") or ""
        if not cano or not acnt_prdt_cd:
            return 0

        from domestic_stock_functions import inquire_balance

        env_dv = "demo" if getattr(state, "is_paper_trading", True) else "real"
        # 모의/일부 환경에서 INQR_DVSN=01이 비어 나오는 경우가 있어 02(종목별) 등으로 재시도
        df1 = None
        attempts = [
            ("N", "01", "00"),
            ("N", "02", "00"),
            ("N", "01", "01"),
            ("N", "02", "01"),
        ]
        for afhr_flpr_yn, inqr_dvsn, prcs_dvsn in attempts:
            try:
                cand1, _ = inquire_balance(
                    env_dv=env_dv,
                    cano=cano,
                    acnt_prdt_cd=acnt_prdt_cd,
                    afhr_flpr_yn=afhr_flpr_yn,
                    inqr_dvsn=inqr_dvsn,
                    unpr_dvsn="01",
                    fund_sttl_icld_yn="N",
                    fncg_amt_auto_rdpt_yn="N",
                    prcs_dvsn=prcs_dvsn,
                )
                if cand1 is not None and getattr(cand1, "empty", True) is False:
                    df1 = cand1
                    # 진단용 기록
                    state._last_positions_sync_attempt = {
                        "env_dv": env_dv,
                        "afhr_flpr_yn": afhr_flpr_yn,
                        "inqr_dvsn": inqr_dvsn,
                        "prcs_dvsn": prcs_dvsn,
                        "rows": int(len(cand1)),
                        "columns": list(getattr(cand1, "columns", [])),
                    }
                    break
            except Exception:
                continue

        if df1 is None or getattr(df1, "empty", True):
            if hasattr(rm, "positions"):
                rm.positions = {}
            state._last_positions_sync_attempt = {
                "env_dv": env_dv,
                "attempts": [{"afhr_flpr_yn": a, "inqr_dvsn": b, "prcs_dvsn": c} for (a, b, c) in attempts],
                "rows": 0,
            }
            return 0

        existing = getattr(rm, "positions", {}) or {}
        last_prices = getattr(rm, "last_prices", {}) or {}
        new_positions = {}
        skipped = 0
        sample_row = None

        def _normalize_price_scale(px: float) -> float:
            """KIS 잔고/체결 데이터에서 간헐적으로 가격 스케일이 100/1000배로 들어오는 케이스 보정."""
            try:
                v = float(px or 0)
            except Exception:
                return 0.0
            if v <= 0:
                return 0.0
            # 정상 주가 범위(대략): 100 ~ 2,000,000원
            if 100.0 <= v <= 2_000_000.0:
                return v
            # 100배/1000배로 들어온 경우를 보정
            if v > 2_000_000.0:
                v1 = v / 1000.0
                if 100.0 <= v1 <= 2_000_000.0:
                    return v1
                v2 = v / 100.0
                if 100.0 <= v2 <= 2_000_000.0:
                    return v2
                v3 = v / 10.0
                if 100.0 <= v3 <= 2_000_000.0:
                    return v3
            return v

        def _pick_qty_from_row(r: dict) -> int:
            # 우선순위 키
            qty_raw = _pick_first(r, [
                "HOLD_QTY", "hold_qty",
                "HLDG_QTY", "hldg_qty",
                "HLDG_QTY1", "hldg_qty1",
                "ORD_PSBL_QTY", "ord_psbl_qty",
                "ORD_PSBL_QTY1", "ord_psbl_qty1",
                "RMN_QTY", "rmn_qty",
            ])
            q = _to_int(qty_raw, 0)
            if q > 0:
                return q
            # 휴리스틱: qty로 끝나고 hold/hld가 포함된 키의 최대값
            best = 0
            for k, v in (r or {}).items():
                kk = str(k).lower()
                if "qty" not in kk:
                    continue
                if not any(tok in kk for tok in ("hold", "hld", "hldg", "psbl", "rmn")):
                    continue
                iv = _to_int(v, 0)
                if iv > best:
                    best = iv
            return int(best)

        for _, row in df1.iterrows():
            rdict = {}
            try:
                rdict = row.to_dict() if hasattr(row, "to_dict") else dict(row)
            except Exception:
                rdict = {}
            if sample_row is None:
                # 일부 컬럼만 샘플로 남김(진단용)
                sample_row = {k: rdict.get(k) for k in list(rdict.keys())[:20]}

            code = str(rdict.get("PDNO") or rdict.get("pdno") or rdict.get("MKSC_SHRN_ISCD") or rdict.get("mksc_shrn_iscd") or "").strip().zfill(6)
            if not code:
                skipped += 1
                continue
            qty = _pick_qty_from_row(rdict)
            if qty <= 0:
                skipped += 1
                continue
            buy_price = 0.0
            try:
                buy_price = _to_float(
                    rdict.get("PCHS_AVG_PRIC")
                    or rdict.get("pchs_avg_pric")
                    or rdict.get("PCHS_AVG_PRIC1")
                    or rdict.get("pchs_avg_pric1")
                    or 0,
                    0.0,
                ) or 0.0
            except Exception:
                buy_price = 0.0
            buy_price = _normalize_price_scale(buy_price)
            # 국내주식 호가 단위는 원 단위이므로 평균단가는 정수로 반올림(표시/손익 계산 안정화)
            try:
                if buy_price > 0:
                    buy_price = float(round(buy_price))
            except Exception:
                pass
            if buy_price <= 0 and code in existing:
                try:
                    buy_price = float(existing[code].get("buy_price") or 0) or 0.0
                except Exception:
                    buy_price = 0.0
            try:
                # 잔고조회 응답에 현재가(prpr)가 있으면 우선 사용
                prpr = _to_float(rdict.get("PRPR") or rdict.get("prpr") or 0, 0.0)
                if prpr and prpr > 0:
                    cur_price = _normalize_price_scale(float(prpr))
                else:
                    cur_price = _normalize_price_scale(float(last_prices.get(code) or buy_price or 0))
            except Exception:
                cur_price = float(buy_price or 0)
            stock_name = (rdict.get("PRDT_NAME") or rdict.get("prdt_name") or "").strip()
            new_positions[code] = {
                "buy_price": buy_price,
                "quantity": qty,
                "current_price": cur_price,
                "buy_time": existing[code].get("buy_time") if code in existing else datetime.now(),
                "partial_taken": existing[code].get("partial_taken", False) if code in existing else False,
            }
            if stock_name:
                new_positions[code]["stock_name"] = stock_name

        if hasattr(rm, "positions"):
            rm.positions = new_positions
        # 진단 정보 갱신
        try:
            if isinstance(getattr(state, "_last_positions_sync_attempt", None), dict):
                state._last_positions_sync_attempt = {
                    **state._last_positions_sync_attempt,
                    "synced": int(len(new_positions)),
                    "skipped_rows": int(skipped),
                    "sample_row": sample_row or {},
                }
        except Exception:
            pass
        return len(new_positions)
    except Exception as e:
        logger.warning("포지션 잔고 동기화 실패: %s", e)
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
    """대시보드에 표시할 계좌 잔고 결정. 모의투자 시 '시작 잔고+일일 손익'으로 표시(API가 거래 반영 안 할 수 있음)."""
    # 모의투자: KIS API 잔고가 체결 후에도 갱신되지 않는 경우가 있으므로, 시작잔고+일일손익으로 표시
    if getattr(state, "is_paper_trading", True) and getattr(state, "risk_manager", None):
        start = getattr(state, "session_start_balance", None)
        if start is not None:
            try:
                pnl = float(getattr(state.risk_manager, "daily_pnl", 0) or 0)
                return int(round(float(start) + pnl))
            except (TypeError, ValueError):
                pass
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
    """리스크 매니저 포지션을 브로드캐스트용 dict로 변환. 종목명은 selected_stock_info에서 조회해 포함."""
    if not state.risk_manager:
        return {}
    info_list = getattr(state, "selected_stock_info", None) or []
    code_to_name = {}
    for item in info_list:
        c = str(item.get("code") or "").strip()
        if c:
            code_to_name[c] = str(item.get("name") or "").strip()
    positions = {}
    for code, pos in state.risk_manager.positions.items():
        out = {
            "quantity": pos["quantity"],
            "buy_price": pos["buy_price"],
            "current_price": pos.get("current_price", pos["buy_price"]),
            "buy_time": pos["buy_time"].isoformat() if isinstance(pos.get("buy_time"), datetime) else str(pos.get("buy_time", ""))
        }
        name = code_to_name.get(code) or (pos.get("stock_name") or pos.get("name") or "")
        if name:
            out["stock_name"] = name
        positions[code] = out
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

    # 매도 시: 진입 후 최소 보유 시간 이내면 스킵 (손절/익절/데드크로스 모두 적용. 시간청산·일일한도·긴급청산은 예외)
    if signal == "sell" and state.risk_manager and stock_code in state.risk_manager.positions and state.strategy:
        min_hold = int(getattr(state.strategy, "min_hold_seconds", 0) or 0)
        if min_hold > 0:
            r = (reason or "")
            bypass = "시간기반" in r or "시간 청산" in r or "일일 이익 한도" in r or "일일 손실 한도" in r or "긴급 청산" in r or "서킷브레이커" in r or "사이드카" in r or "수동 청산" in r
            if not bypass:
                pos = state.risk_manager.positions.get(stock_code)
                buy_time = pos.get("buy_time") if pos else None
                if isinstance(buy_time, datetime):
                    elapsed = (datetime.now() - buy_time).total_seconds()
                    if elapsed < min_hold:
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
        selected_stocks_count=len(getattr(state, "selected_stocks", None) or []),
    )
    if not result:
        reason = details.get("reason") or ""
        rej_msg = (details.get("rejection_message") or "").strip()
        # 반복 로그 억제: 일일 거래 횟수 초과, 모의투자 잔고내역 없음 등은 5분에 한 번만
        skip_log = False
        if reason == "일일 거래 횟수 초과":
            last_log = getattr(state, "_last_daily_trade_limit_log_time", 0) or 0
            if time.time() - last_log < 300:
                skip_log = True
            else:
                state._last_daily_trade_limit_log_time = time.time()
        elif "모의투자 잔고내역이 없습니다" in reason or "모의투자 잔고내역이 없습니다" in rej_msg:
            last_log = getattr(state, "_last_no_balance_log_time", 0) or 0
            if time.time() - last_log < 300:
                skip_log = True
            else:
                state._last_no_balance_log_time = time.time()
            # 서버 잔고 기준 동기화: 매도 실패 시 KIS가 해당 종목 잔고 없음으로 본 것이므로 포지션에서 제거
            if signal == "sell" and stock_code and getattr(state, "risk_manager", None):
                pos = getattr(state.risk_manager, "positions", None) or {}
                if stock_code in pos:
                    try:
                        state.risk_manager.positions = {k: v for k, v in pos.items() if k != stock_code}
                        _run_async_broadcast({"type": "position", "data": _build_positions_message()})
                        _run_async_broadcast({"type": "log", "level": "warning", "message": f"모의 잔고 없음: {stock_code} 포지션 제거(서버 기준 동기화)"})
                    except Exception as e:
                        logger.warning("잔고 없음 포지션 제거 실패 %s: %s", stock_code, e)
        elif reason in ("pending_sell_order", "pending_buy_order"):
            # 이미 접수(대기) 중인 동일 방향 주문이 있어 중복 요청 무시 — 로그 스팸 방지
            pending_key = f"_last_pending_order_log_{stock_code}_{(details.get('signal') or '').upper()}"
            last_pending = getattr(state, pending_key, 0) or 0
            if time.time() - last_pending < 30:
                skip_log = True
            else:
                setattr(state, pending_key, time.time())
                _run_async_broadcast({"type": "log", "message": f"중복 주문 무시(이미 접수됨) | {(details.get('signal') or '').upper()} {stock_code}", "level": "info"})
                skip_log = True
        if not skip_log:
            _run_async_broadcast({"type": "log", "message": _format_order_log(details), "level": "error"})
        if reason and ("월간 손실 한도" in reason or "누적 손실 한도" in reason):
            try:
                tz = timezone(timedelta(hours=9))
                now_dt = datetime.now(tz)
                ym_key = now_dt.strftime("%Y%m")
                date_key = now_dt.strftime("%Y%m%d")
                if "월간 손실 한도" in reason:
                    if getattr(state, "_monthly_limit_alerted_ym", "") != ym_key:
                        send_alert("error", reason, title="월간 손실 한도 도달")
                        state._monthly_limit_alerted_ym = ym_key
                if "누적 손실 한도" in reason:
                    if getattr(state, "_cumulative_limit_alerted_date", "") != date_key:
                        send_alert("error", reason, title="누적 손실 한도 도달")
                        state._cumulative_limit_alerted_date = date_key
            except Exception:
                pass
        rej = details.get("rejection_reason") or ""
        if rej == "vi" and stock_code:
            vi_cooling = max(1, min(30, int(getattr(state, "vi_cooling_minutes", 5) or 5)))
            vi_skip = getattr(state, "_vi_skip_until", None) or {}
            if not isinstance(vi_skip, dict):
                vi_skip = {}
            state._vi_skip_until = {**vi_skip, stock_code: time.time() + vi_cooling * 60}
            _run_async_broadcast({"type": "log", "level": "warning", "message": f"주문 거절(VI): {stock_code} → {vi_cooling}분간 해당 종목 매수 스킵"})
        if details.get("error_type") == "auth_expired":
            _run_async_broadcast({"type": "log", "level": "error", "message": "토큰 만료 가능성. 재로그인 후 이용하세요."})
            try:
                send_alert("error", "토큰 만료 가능성. 재로그인 후 이용하세요.", title="인증 만료")
            except Exception:
                pass
        return

    filled = bool(details.get("filled", False))
    level = "info" if filled else "warning"
    _run_async_broadcast({"type": "log", "message": _format_order_log(details), "level": level})
    if not filled:
        # 주문 접수는 되었으나 체결 미확정/미체결 상태도 거래내역에 남겨, "접수(대기)"와 "체결"을 구분 가능하게 함
        try:
            qty = 0
            try:
                qty = int(details.get("quantity") or 0)
            except Exception:
                qty = 0
            trade_info = {
                "stock_code": stock_code,
                "order_type": signal,
                "quantity": qty,
                "price": price,
                "pnl": None,
                "reason": reason or "",
                "order_status": str(details.get("status") or "accepted_pending"),
            }
            state.add_trade(trade_info)
            _run_async_broadcast({"type": "trade", "data": trade_info})
        except Exception:
            pass
        # 포지션/거래내역 손익 반영은 체결 확인 시점에 수행
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
    pnl_val = details.get("pnl")
    if pnl_val is not None:
        try:
            pnl_val = float(pnl_val)
        except (TypeError, ValueError):
            pnl_val = None
    trade_info = {
        "stock_code": stock_code,
        "order_type": signal,
        "quantity": suggested_qty,
        "price": price,
        "pnl": pnl_val,
        "reason": reason or "",
        "order_status": str(details.get("status") or "filled"),
    }
    state.add_trade(trade_info)
    _run_async_broadcast({"type": "trade", "data": trade_info})
    _run_async_broadcast({"type": "position", "data": _build_positions_message()})
    _run_async_broadcast({"type": "log", "message": f"자동 체결: {stock_code} {signal.upper()} {price:,.0f}원", "level": "info"})


def _start_trading_engine_thread():
    """실시간 체결 수신 -> 신호 생성 -> 승인 대기 등록. 선정 종목 목록은 구독 시점의 state.selected_stocks 사용."""
    # 이전 엔진 스레드가 아직 살아 있으면(중지 후 WS가 아직 끊기지 않은 경우) 종료될 때까지 대기
    engine_thread = getattr(state, "engine_thread", None)
    if engine_thread is not None and engine_thread.is_alive():
        state.engine_running = False
        for _ in range(16):
            time.sleep(0.5)
            if not (getattr(state, "engine_thread", None) and state.engine_thread.is_alive()):
                break
        if getattr(state, "engine_thread", None) and state.engine_thread.is_alive():
            logger.warning("엔진 스레드가 아직 종료되지 않음. WebSocket 연결이 끊길 때까지 잠시 기다린 뒤 다시 시작하세요.")
            return
    if state.engine_running:
        return

    def _sync_state_after_ws_reconnect():
        """WebSocket 재연결 후 잔고/포지션 동기화"""
        try:
            _refresh_kis_account_balance_sync()
        except Exception as e:
            logger.warning("WS 재연결 후 잔고 동기화 실패: %s", e)
        try:
            _sync_positions_from_balance_sync()
        except Exception as e:
            logger.warning("WS 재연결 후 포지션 동기화 실패: %s", e)
        try:
            _run_async_broadcast({"type": "log", "message": "WebSocket 재연결 후 상태 동기화 완료", "level": "info"})
            _run_async_broadcast({"type": "position", "data": _build_positions_message()})
        except Exception:
            pass

    def _engine_runner():
        try:
            state.engine_running = True
            first_disconnect_ts = None
            ws_reconnect_sleep = max(3, min(60, int(getattr(state, "ws_reconnect_sleep_sec", 5) or 5)))
            emergency_minutes = max(0, min(120, int(getattr(state, "emergency_liquidate_disconnect_minutes", 0) or 0)))
            while True:
                if not getattr(state, "engine_running", True):
                    break
                try:
                    # 매 연결마다 구독 목록 초기화 (재선정 시 새 목록만 구독하도록)
                    for _sub_key in ("ccnl_krx", "asking_price_krx", "market_status_krx"):
                        getattr(ka, "open_map", {}).pop(_sub_key, None)
                    kws = ka.KISWebSocket(api_url="/tryitout")
                    # 선정 종목 + 보유 포지션 종목 모두 구독 (재선정으로 빠진 보유 종목도 매도 신호 수신 가능)
                    selected = state.selected_stocks or []
                    position_codes = list(getattr(state.risk_manager, "positions", {}).keys())
                    stocks = list(dict.fromkeys(selected + position_codes)) if (selected or position_codes) else ["005930", "000660"]
                    try:
                        system_log_append(
                            "info",
                            f"WS 구독 종목 결정: selected={','.join(selected)} positions={','.join(position_codes)} subscribe={','.join(stocks)}",
                        )
                    except Exception:
                        pass
                    kws.subscribe(request=ccnl_krx, data=stocks)
                    try:
                        kws.subscribe(request=asking_price_krx, data=stocks, kwargs={"env_dv": "demo" if state.is_paper_trading else "real"})
                    except Exception:
                        pass
                    try:
                        kws.subscribe(request=market_status_krx, data=stocks)
                    except Exception as e:
                        logger.warning("장운영정보(VI) WS 구독 실패: %s", e)
                    first_disconnect_ts = None

                    def on_result(ws, tr_id, result, data_info):
                        if not state.is_running or not state.strategy or not state.risk_manager:
                            return
                        if result is not None and not result.empty:
                            state._last_tick_at = time.time()
                        # 장운영/VI(KRX H0STMKO0): vi_cls_code 기준 실시간 반영, VI 해제 시 냉각 타이머 제거
                        if tr_id == "H0STMKO0" and result is not None and not result.empty:
                            try:
                                if not hasattr(state, "_vi_ws_active") or state._vi_ws_active is None:
                                    state._vi_ws_active = {}
                                for _, row in result.iterrows():
                                    code = None
                                    for key in ("mksc_shrn_iscd", "MKSC_SHRN_ISCD"):
                                        v = row.get(key)
                                        if v is not None and str(v).strip():
                                            code = str(v).strip().zfill(6)
                                            break
                                    if not code:
                                        continue
                                    vi_raw = row.get("vi_cls_code")
                                    if vi_raw is None:
                                        vi_raw = row.get("VI_CLS_CODE")
                                    vi_active = _vi_cls_code_implies_active(vi_raw)
                                    prev = state._vi_ws_active.get(code)
                                    state._vi_ws_active[code] = (vi_active, time.time())
                                    with _vi_status_cache_lock:
                                        _vi_status_cache.pop(code, None)
                                    if prev is not None and prev[0] and not vi_active:
                                        vi_skip = getattr(state, "_vi_skip_until", None) or {}
                                        if isinstance(vi_skip, dict) and vi_skip.get(code, 0) > time.time():
                                            state._vi_skip_until = {k: v for k, v in vi_skip.items() if k != code}
                                            with _vi_status_cache_lock:
                                                _vi_status_cache.pop(code, None)
                                            _run_async_broadcast({
                                                "type": "log",
                                                "level": "info",
                                                "message": f"VI 해제(장운영 WS): {code} → 해당 종목 VI 냉각 해제, 매수 필터 재평가",
                                            })
                            except Exception as ex:
                                logger.debug("H0STMKO0 VI 처리 실패: %s", ex)
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
                                                    msg = f"일일 이익 한도 도달(total): {cur_pnl:,.0f}원 >= {limit:,.0f}원 (전량 매도 신호 생성)"
                                                    _run_async_broadcast({"type": "log", "level": "warning", "message": msg})
                                                    try:
                                                        send_alert("warning", msg, title="일일 이익 한도")
                                                    except Exception:
                                                        pass
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
                                                msg = f"일일 손실 한도(total) 도달: {total_if_liq:,.0f}원 <= -{limit:,.0f}원 (전량 매도 신호 생성)"
                                                _run_async_broadcast({"type": "log", "level": "error", "message": msg})
                                                try:
                                                    send_alert("error", msg, title="일일 손실 한도")
                                                except Exception:
                                                    pass
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
                                                msg = f"일일 손실 한도(합산) 도달: {total_if_liq:,.0f}원 <= -{limit:,.0f}원 (전량 매도 신호 생성)"
                                                _run_async_broadcast({"type": "log", "level": "error", "message": msg})
                                                try:
                                                    send_alert("error", msg, title="일일 손실 한도")
                                                except Exception:
                                                    pass
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

                                # 당일 시가(상대강도용): 종목별 오늘 첫 가격
                                try:
                                    tz = timezone(timedelta(hours=9))
                                    today_key = datetime.now(tz).strftime("%Y%m%d")
                                    if not hasattr(state, "_stock_open_today"):
                                        state._stock_open_today = {}
                                    if state._stock_open_today.get("_day") != today_key:
                                        state._stock_open_today = {"_day": today_key}
                                    if stock_code not in state._stock_open_today:
                                        state._stock_open_today[stock_code] = float(current_price)
                                except Exception:
                                    pass

                                # 틱 거래량/거래대금 이력(진입 하한·급증 조건용): 매 틱 누적
                                try:
                                    vol_tick = None
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
                                    if vol_tick is not None and vol_tick >= 0:
                                        if not hasattr(state, "_vol_tick_hist"):
                                            state._vol_tick_hist = {}
                                        h = state._vol_tick_hist.get(stock_code) or []
                                        h.append(float(vol_tick))
                                        if len(h) > 120:
                                            h = h[-120:]
                                        state._vol_tick_hist[stock_code] = h
                                        if current_price > 0:
                                            if not hasattr(state, "_tv_tick_hist"):
                                                state._tv_tick_hist = {}
                                            tvh = state._tv_tick_hist.get(stock_code) or []
                                            tvh.append(float(vol_tick) * float(current_price))
                                            if len(tvh) > 120:
                                                tvh = tvh[-120:]
                                            state._tv_tick_hist[stock_code] = tvh
                                except Exception:
                                    pass

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
                                        # 새 봉 추가 시에만 120봉으로 트림(매 틱 슬라이스 방지)
                                        if len(bars) > 120:
                                            bars = bars[-120:]
                                    else:
                                        b = bars[-1]
                                        b["h"] = float(max(float(b.get("h", current_price)), float(current_price)))
                                        b["l"] = float(min(float(b.get("l", current_price)), float(current_price)))
                                        b["c"] = float(current_price)
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
                                    if short_ma > long_ma and current_price > short_ma and stock_code not in state.risk_manager.positions and stock_code in (state.selected_stocks or []):
                                        # 선정 종목에 있을 때만 매수. 포지션에만 있고 선정에 없는 종목(전일 잔여 등)은 매도만 허용·매수 스킵
                                        # (0-0) 재진입 쿨다운: 직전 매도 직후 같은 종목 재매수 방지(횡보장 와입 방지) — 가장 먼저 검사
                                        try:
                                            if getattr(state.risk_manager, "reentry_cooldown_seconds", 0) and getattr(state.risk_manager, "is_in_reentry_cooldown", None):
                                                if state.risk_manager.is_in_reentry_cooldown(stock_code):
                                                    _record_buy_skip(stock_code, "cooldown")
                                                    _throttled_skip_log(stock_code, f"재진입 쿨다운({getattr(state.risk_manager, 'reentry_cooldown_seconds', 0)}s)")
                                                    continue
                                        except Exception:
                                            pass
                                        # (0-0a) 거래소 서킷브레이커(급락) 구간: 전일 대비 지수 하락률이 N% 이하이면 신규 매수 스킵
                                        try:
                                            if bool(getattr(state, "circuit_breaker_filter_enabled", True)):
                                                mkt = str(getattr(state, "circuit_breaker_market", "0001") or "0001")
                                                thresh = float(getattr(state, "circuit_breaker_threshold_pct", -7.0) or -7.0)
                                                is_risk, drop_pct = _get_exchange_circuit_breaker_risk(mkt, thresh)
                                                if is_risk and drop_pct is not None:
                                                    _record_buy_skip(stock_code, "circuit_breaker")
                                                    _throttled_skip_log(
                                                        stock_code,
                                                        f"거래소 서킷(급락) 구간 추정: 지수 전일대비 {drop_pct:.1f}% (신규 매수 스킵)",
                                                    )
                                                    _tz = timezone(timedelta(hours=9))
                                                    _today_key = datetime.now(_tz).strftime("%Y%m%d")
                                                    action = str(getattr(state, "circuit_breaker_action", "skip_buy_only") or "skip_buy_only").strip().lower()
                                                    if action == "no_buy_rest_of_day" and getattr(state, "risk_manager", None):
                                                        state.risk_manager.halt_new_buys_day = _today_key
                                                        state.risk_manager.halt_new_buys_reason = "서킷브레이커(급락) 구간 → 당일 신규 매수 중지"
                                                    elif action in ("liquidate_all", "liquidate_partial") and getattr(state, "risk_manager", None):
                                                        rm = state.risk_manager
                                                        for code, pos in list(rm.positions.items()):
                                                            qty = int(pos.get("quantity", 0) or 0)
                                                            if qty <= 0:
                                                                continue
                                                            px = float(pos.get("current_price") or rm.last_prices.get(code) or pos.get("buy_price") or 0)
                                                            if px <= 0:
                                                                continue
                                                            sell_qty = (qty // 2) if action == "liquidate_partial" else qty
                                                            if sell_qty > 0:
                                                                _handle_signal(code, "sell", px, f"서킷브레이커 구간 {action}", suggested_qty_override=sell_qty)
                                                    continue
                                        except Exception:
                                            pass
                                        # (0-0a2) 사이드카 발동 가능 구간: 지수 ±5%(코스피)/±6%(코스닥) 변동 시 N분간 신규 매수 스킵
                                        try:
                                            if bool(getattr(state, "sidecar_filter_enabled", True)):
                                                mkt = str(getattr(state, "sidecar_market", "0001") or "0001")
                                                cooling_min = max(1, min(30, int(getattr(state, "sidecar_cooling_minutes", 5) or 5)))
                                                tz = timezone(timedelta(hours=9))
                                                today_key = datetime.now(tz).strftime("%Y%m%d")
                                                now_ts = time.time()
                                                skip_until = float(getattr(state, "_sidecar_skip_until_ts", 0) or 0)
                                                triggered_day = str(getattr(state, "_sidecar_triggered_day", "") or "")
                                                if now_ts < skip_until:
                                                    _record_buy_skip(stock_code, "sidecar_cooling")
                                                    _throttled_skip_log(stock_code, f"사이드카 냉각 구간({cooling_min}분) 신규 매수 스킵")
                                                    continue
                                                is_sidecar, chg_pct = _get_exchange_sidecar_risk(mkt)
                                                if is_sidecar and chg_pct is not None and triggered_day != today_key:
                                                    state._sidecar_skip_until_ts = now_ts + cooling_min * 60
                                                    state._sidecar_triggered_day = today_key
                                                    _run_async_broadcast({
                                                        "type": "log",
                                                        "level": "warning",
                                                        "message": f"사이드카 구간 추정: 지수 전일대비 {chg_pct:+.1f}% → {cooling_min}분간 신규 매수 스킵",
                                                    })
                                                    _record_buy_skip(stock_code, "sidecar")
                                                    action = str(getattr(state, "sidecar_action", "skip_buy_only") or "skip_buy_only").strip().lower()
                                                    if action == "no_buy_rest_of_day" and getattr(state, "risk_manager", None):
                                                        state.risk_manager.halt_new_buys_day = today_key  # today_key already in scope
                                                        state.risk_manager.halt_new_buys_reason = "사이드카 구간 → 당일 신규 매수 중지"
                                                    elif action in ("liquidate_all", "liquidate_partial") and getattr(state, "risk_manager", None):
                                                        rm = state.risk_manager
                                                        for code, pos in list(rm.positions.items()):
                                                            qty = int(pos.get("quantity", 0) or 0)
                                                            if qty <= 0:
                                                                continue
                                                            px = float(pos.get("current_price") or rm.last_prices.get(code) or pos.get("buy_price") or 0)
                                                            if px <= 0:
                                                                continue
                                                            sell_qty = (qty // 2) if action == "liquidate_partial" else qty
                                                            if sell_qty > 0:
                                                                _handle_signal(code, "sell", px, f"사이드카 구간 {action}", suggested_qty_override=sell_qty)
                                                    continue
                                        except Exception:
                                            pass
                                        # (0-0a3) VI(종목별 변동성완화장치) 발동 시 해당 종목 N분 스킵
                                        try:
                                            if bool(getattr(state, "vi_filter_enabled", True)):
                                                vi_cooling = max(1, min(30, int(getattr(state, "vi_cooling_minutes", 5) or 5)))
                                                vi_skip_until = getattr(state, "_vi_skip_until", None) or {}
                                                if not isinstance(vi_skip_until, dict):
                                                    vi_skip_until = {}
                                                if vi_skip_until.get(stock_code, 0) > time.time():
                                                    _record_buy_skip(stock_code, "vi_cooling")
                                                    _throttled_skip_log(stock_code, "VI 냉각 구간(해당 종목) 신규 매수 스킵")
                                                    continue
                                                if _get_stock_vi_triggered(stock_code):
                                                    state._vi_skip_until = {**vi_skip_until, stock_code: time.time() + vi_cooling * 60}
                                                    _run_async_broadcast({
                                                        "type": "log",
                                                        "level": "warning",
                                                        "message": f"VI 발동(종목): {stock_code} → {vi_cooling}분간 해당 종목 매수 스킵",
                                                    })
                                                    _record_buy_skip(stock_code, "vi")
                                                    continue
                                        except Exception:
                                            pass
                                        # (0-0) 지수 MA 시장 레짐: 지수(코스닥 등)가 N일 MA 미만이면 매수 스킵
                                        try:
                                            if bool(getattr(state, "index_ma_filter_enabled", False)):
                                                idx_code = str(getattr(state, "index_ma_code", "1001") or "1001")
                                                idx_period = max(5, min(60, int(getattr(state, "index_ma_period", 20)) or 20))
                                                if not _get_index_ma_ok(idx_code, idx_period):
                                                    _record_buy_skip(stock_code, "index_ma")
                                                    _throttled_skip_log(stock_code, "시장 레짐(지수<MA)")
                                                    continue
                                        except Exception:
                                            pass
                                        # (0-0b) 상승 종목 비율 시장 레짐: 상승 비율이 N% 미만이면 매수 스킵
                                        try:
                                            if bool(getattr(state, "advance_ratio_filter_enabled", False)):
                                                mkt = str(getattr(state, "advance_ratio_market", "1001") or "1001")
                                                min_pct = float(getattr(state, "advance_ratio_min_pct", 40.0) or 40.0) / 100.0
                                                ratio = _get_advance_ratio(mkt)
                                                if ratio is not None and ratio < min_pct:
                                                    _record_buy_skip(stock_code, "advance_ratio")
                                                    _throttled_skip_log(
                                                        stock_code,
                                                        f"시장 레짐(상승비율 {ratio*100:.1f}% < {min_pct*100:.0f}%)",
                                                    )
                                                    continue
                                                # (6) 하락장 강화: 상승 비율 < 50%이면 전량 매수 스킵
                                                if bool(getattr(state, "advance_ratio_down_market_skip", True)) and ratio is not None and ratio < 0.5:
                                                    _record_buy_skip(stock_code, "advance_ratio_down")
                                                    _throttled_skip_log(
                                                        stock_code,
                                                        f"하락장 강화 스킵(상승비율 {ratio*100:.1f}% < 50%)",
                                                    )
                                                    continue
                                        except Exception:
                                            pass
                                        # (0-0d) 지수 대비 상대 강도: 종목 변동률 > 지수 변동률 + margin일 때만 매수
                                        try:
                                            if bool(getattr(state, "relative_strength_filter_enabled", False)):
                                                idx_code = str(getattr(state, "relative_strength_index_code", "0001") or "0001")
                                                margin_pct = float(getattr(state, "relative_strength_margin_pct", 0.0) or 0.0)
                                                _, index_chg = _get_exchange_circuit_breaker_risk(idx_code, -20.0)
                                                open_today = (getattr(state, "_stock_open_today", None) or {}).get(stock_code)
                                                if index_chg is not None and open_today is not None and float(open_today) > 0:
                                                    stock_chg_pct = (float(current_price) - float(open_today)) / float(open_today) * 100.0
                                                    if stock_chg_pct <= index_chg + margin_pct:
                                                        _record_buy_skip(stock_code, "relative_strength")
                                                        _throttled_skip_log(
                                                            stock_code,
                                                            f"상대강도 미달(종목 {stock_chg_pct:.2f}% <= 지수 {index_chg:.2f}%+{margin_pct}%)",
                                                        )
                                                        continue
                                        except Exception:
                                            pass
                                        # (0-0c) 거래대금 집중 시장 레짐: 상위 N종목 거래대금 비율이 X% 초과면 매수 스킵
                                        try:
                                            if bool(getattr(state, "trade_value_concentration_filter_enabled", False)):
                                                mkt = str(getattr(state, "trade_value_concentration_market", "1001") or "1001")
                                                top_n = max(2, min(20, int(getattr(state, "trade_value_concentration_top_n", 10)) or 10))
                                                denom_n = max(top_n + 1, min(50, int(getattr(state, "trade_value_concentration_denom_n", 30)) or 30))
                                                max_pct = float(getattr(state, "trade_value_concentration_max_pct", 45.0) or 45.0)
                                                if not _get_trade_value_concentration_ok(mkt, top_n, denom_n, max_pct):
                                                    _record_buy_skip(stock_code, "trade_value_concentration")
                                                    _throttled_skip_log(
                                                        stock_code,
                                                        f"시장 레짐(거래대금 집중 상위{top_n}/{denom_n}>{max_pct:.0f}%)",
                                                    )
                                                    continue
                                        except Exception:
                                            pass
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

                                        # (0-1) 진입 변동성 상한: 틱 변동성(가격 대비)이 N% 초과면 스킵
                                        try:
                                            max_vol_pct = float(getattr(state.risk_manager, "max_intraday_vol_pct", 0) or 0)
                                            if max_vol_pct > 0 and hasattr(state.risk_manager, "get_intraday_vol_ratio"):
                                                vol_ratio = state.risk_manager.get_intraday_vol_ratio(stock_code)
                                                if vol_ratio is not None and (vol_ratio * 100.0) > max_vol_pct:
                                                    _record_buy_skip(stock_code, "vol_cap")
                                                    _throttled_skip_log(
                                                        stock_code,
                                                        f"변동성 상한 초과({vol_ratio*100:.2f}% > {max_vol_pct}%)",
                                                    )
                                                    continue
                                        except Exception:
                                            pass

                                        # (0-1b) ATR(분봉) 변동성 필터: ATR/현재가 비율이 상한 초과면 스킵
                                        try:
                                            if bool(getattr(state.risk_manager, "atr_filter_enabled", False)):
                                                max_atr_pct = float(getattr(state.risk_manager, "atr_ratio_max_pct", 0) or 0)
                                                if max_atr_pct > 0:
                                                    period_atr = max(2, min(30, int(getattr(state.risk_manager, "atr_period", 14)) or 14))
                                                    bars = (getattr(state, "_minute_bars", {}) or {}).get(stock_code) or []
                                                    atr_ratio = _get_atr_ratio_from_minute_bars(bars, float(current_price), period_atr)
                                                    if atr_ratio is not None:
                                                        atr_value = atr_ratio * float(current_price)
                                                        now_ts_atr = time.time()
                                                        with _signal_skip_log_lock:
                                                            last_atr = _last_atr_log_ts.get(stock_code) or 0.0
                                                            if now_ts_atr - last_atr >= 300:
                                                                _last_atr_log_ts[stock_code] = now_ts_atr
                                                                _run_async_broadcast({
                                                                    "type": "log",
                                                                    "level": "info",
                                                                    "message": f"ATR 필터 | {stock_code} ATR={atr_value:.0f}원 비율={atr_ratio*100:.2f}% 상한(atr_ratio_max_pct)={max_atr_pct}%",
                                                                })
                                                    # 분봉이 period 미만이면 이번 틱에서는 ATR 검사 생략 → 장 초반에도 매수 가능(기다릴 필요 없음)
                                                    if atr_ratio is not None and (atr_ratio * 100.0) > max_atr_pct:
                                                        _record_buy_skip(stock_code, "atr_cap")
                                                        _throttled_skip_log(
                                                            stock_code,
                                                            f"ATR 변동성 상한 초과(ATR/가격 {atr_ratio*100:.2f}% > {max_atr_pct}%)",
                                                        )
                                                        continue
                                        except Exception:
                                            pass

                                        # (0-1c) SAP(세션 평균가) 이탈 필터: 현재가가 SAP 대비 ±X% 초과면 스킵
                                        try:
                                            if bool(getattr(state.risk_manager, "sap_deviation_filter_enabled", False)):
                                                max_dev_pct = float(getattr(state.risk_manager, "sap_deviation_max_pct", 3.0) or 3.0)
                                                if max_dev_pct > 0:
                                                    bars = (getattr(state, "_minute_bars", {}) or {}).get(stock_code) or []
                                                    result = _get_sap_deviation_pct_from_minute_bars(bars, float(current_price))
                                                    if result is not None:
                                                        sap, dev_pct = result
                                                        now_ts_sap = time.time()
                                                        with _signal_skip_log_lock:
                                                            last_sap = _last_sap_log_ts.get(stock_code) or 0.0
                                                            if now_ts_sap - last_sap >= 300:
                                                                _last_sap_log_ts[stock_code] = now_ts_sap
                                                                _run_async_broadcast({
                                                                    "type": "log",
                                                                    "level": "info",
                                                                    "message": f"SAP 필터 | {stock_code} SAP={sap:.0f}원 이탈률={dev_pct:.2f}% 상한(sap_deviation_max_pct)={max_dev_pct}%",
                                                                })
                                                    if result is None:
                                                        _record_buy_skip(stock_code, "sap_deviation")
                                                        _throttled_skip_log(stock_code, "SAP 데이터 부족(분봉 2개 미만) → 매수 스킵")
                                                        continue
                                                    # 기본 이탈 상한: 평균가에서 너무 멀리 벗어나면 스킵
                                                    if abs(result[1]) > max_dev_pct:
                                                        _record_buy_skip(stock_code, "sap_deviation")
                                                        _throttled_skip_log(
                                                            stock_code,
                                                            f"SAP 이탈 과대(|{result[1]:.2f}%| > {max_dev_pct}%)",
                                                        )
                                                        continue
                                                    # 선택적 SAP 풀백 진입 모드: 평균가 대비 하단 특정 구간에서만 신규 매수 허용
                                                    try:
                                                        if bool(getattr(state, "use_sap_revert_entry", False)):
                                                            # 주의: 0.0은 유효값인데 `or` 때문에 falsy로 처리되면 기본값(-1.0 등)으로 덮어써질 수 있음
                                                            _entry_from = getattr(state, "sap_revert_entry_from_pct", None)
                                                            entry_from = float(_entry_from) if _entry_from is not None else -2.5
                                                            _entry_to = getattr(state, "sap_revert_entry_to_pct", None)
                                                            entry_to = float(_entry_to) if _entry_to is not None else -1.0
                                                            low = min(entry_from, entry_to)
                                                            high = max(entry_from, entry_to)
                                                            dev = float(result[1])
                                                            # dev는 음수(하단)일 때만 의미 있게 사용. 범위 밖이면 매수 스킵.
                                                            if not (low <= dev <= high):
                                                                _record_buy_skip(stock_code, "sap_revert_window")
                                                                _throttled_skip_log(
                                                                    stock_code,
                                                                    # low/high를 1자리 반올림하지 않고, -0.05 같은 경계값을 정확히 확인할 수 있게 소수 2자리 표시
                                                                    f"SAP 풀백 범위 밖으로 신규 매수 스킵(dev={dev:.2f}% not in [{low:.2f}%,{high:.2f}%])",
                                                                )
                                                                continue
                                                    except Exception:
                                                        pass
                                        except Exception:
                                            pass

                                        # (2) 진입 시 평균 대비 거래량/거래대금 하한
                                        try:
                                            min_vol_r = float(getattr(state, "min_volume_ratio_for_entry", 0) or 0)
                                            min_tv_r = float(getattr(state, "min_trade_amount_ratio_for_entry", 0) or 0)
                                            if min_vol_r > 0 or min_tv_r > 0:
                                                h = (getattr(state, "_vol_tick_hist", None) or {}).get(stock_code) or []
                                                tvh = (getattr(state, "_tv_tick_hist", None) or {}).get(stock_code) or []
                                                if min_vol_r > 0 and len(h) >= 2:
                                                    vol_tick = float(h[-1])
                                                    avg_vol = sum(h) / len(h)
                                                    if avg_vol > 0 and vol_tick < min_vol_r * avg_vol:
                                                        _record_buy_skip(stock_code, "min_volume_ratio")
                                                        _throttled_skip_log(
                                                            stock_code,
                                                            f"진입 거래량 하한 미달(현재 {vol_tick:.0f} < {min_vol_r:.2f}×평균 {avg_vol:.0f})",
                                                        )
                                                        continue
                                                if min_tv_r > 0 and len(tvh) >= 2:
                                                    tv_tick = float(tvh[-1])
                                                    avg_tv = sum(tvh) / len(tvh)
                                                    if avg_tv > 0 and tv_tick < min_tv_r * avg_tv:
                                                        _record_buy_skip(stock_code, "min_trade_amount_ratio")
                                                        _throttled_skip_log(
                                                            stock_code,
                                                            f"진입 거래대금 하한 미달(현재 {tv_tick:.0f} < {min_tv_r:.2f}×평균 {avg_tv:.0f})",
                                                        )
                                                        continue
                                        except Exception:
                                            pass

                                        # (0-2) 연속 손실 시 쿨다운 확대: 직전 N회 모두 손실이면 재진입 쿨다운×배수만큼 대기 후 매수 허용
                                        try:
                                            if bool(getattr(state, "consecutive_loss_cooldown_enabled", False)):
                                                thresh = int(getattr(state, "consecutive_loss_count_threshold", 2) or 2)
                                                mult = float(getattr(state, "consecutive_loss_cooldown_mult", 2.0) or 2.0)
                                                base_cd = int(getattr(state, "reentry_cooldown_seconds", 0) or 0)
                                                consec = int(getattr(state, "consecutive_losses", 0) or 0)
                                                last_t = getattr(state, "last_consecutive_loss_time", None)
                                                if thresh >= 2 and consec >= thresh and last_t and base_cd > 0:
                                                    required = base_cd * mult
                                                    elapsed = time.time() - float(last_t)
                                                    if elapsed < required:
                                                        _record_buy_skip(stock_code, "loss_cooldown")
                                                        _throttled_skip_log(
                                                            stock_code,
                                                            f"연속 손실 쿨다운({int(required - elapsed)}s 남음)",
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

                                        # (2-1-1b) 당일 고점 대비 N% 이상 하락 시 매수 스킵 (고점 꺾인 후 하락추세 진입 방지)
                                        try:
                                            below_high_pct = float(getattr(state, "skip_buy_below_high_pct", 0.0) or 0.0)
                                            if below_high_pct > 0:
                                                prices = (state.strategy.price_history.get(stock_code) or [])
                                                min_bars = 20
                                                if len(prices) >= min_bars:
                                                    session_high = max(float(p) for p in prices)
                                                    if session_high > 0:
                                                        drawdown = (session_high - float(current_price)) / session_high
                                                        if drawdown >= below_high_pct:
                                                            _record_buy_skip(stock_code, "below_high")
                                                            _throttled_skip_log(
                                                                stock_code,
                                                                f"고점 대비 하락({drawdown*100:.2f}% >= {below_high_pct*100:.2f}%) 매수 스킵",
                                                                ttl_sec=10,
                                                            )
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

                                                # (b) 거래량 급증 (틱 체결량 기준). _vol_tick_hist는 매 틱 상단에서 이미 갱신됨
                                                h_vol = (getattr(state, "_vol_tick_hist", None) or {}).get(stock_code) or []
                                                vol_tick = float(h_vol[-1]) if h_vol else None

                                                if bool(getattr(state, "confirm_volume_surge_enabled", False)):
                                                    n = int(getattr(state, "volume_surge_lookback_ticks", 20) or 20)
                                                    n = max(2, min(200, n))
                                                    ratio = float(getattr(state, "volume_surge_ratio", 2.0) or 2.0)
                                                    if vol_tick is not None and vol_tick > 0 and len(h_vol) > 1:
                                                        prev_h = h_vol[:-1]
                                                        if len(prev_h) > n:
                                                            prev_h = prev_h[-n:]
                                                        avg = float(sum(prev_h) / len(prev_h)) if prev_h else 0.0
                                                        ok = (avg > 0 and float(vol_tick) >= float(avg) * float(ratio))
                                                        if ok:
                                                            hit += 1
                                                            hits.append("vol_surge")

                                                # (c) 거래대금 급증 (틱 체결량 * 가격 기준). _tv_tick_hist는 매 틱 상단에서 이미 갱신됨
                                                tvh = (getattr(state, "_tv_tick_hist", None) or {}).get(stock_code) or []
                                                tv_tick = float(tvh[-1]) if tvh else None
                                                if bool(getattr(state, "confirm_trade_value_surge_enabled", False)):
                                                    n = int(getattr(state, "trade_value_surge_lookback_ticks", 20) or 20)
                                                    n = max(2, min(200, n))
                                                    ratio = float(getattr(state, "trade_value_surge_ratio", 2.0) or 2.0)
                                                    if tv_tick is not None and tv_tick > 0 and len(tvh) > 1:
                                                        prev_tvh = tvh[:-1]
                                                        if len(prev_tvh) > n:
                                                            prev_tvh = prev_tvh[-n:]
                                                        avg = float(sum(prev_tvh) / len(prev_tvh)) if prev_tvh else 0.0
                                                        ok = (avg > 0 and float(tv_tick) >= float(avg) * float(ratio))
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
                                            now_min = now_t.hour * 60 + now_t.minute
                                            # (3) 장 초반 N분 매수 스킵 (09:00 KST 기준)
                                            skip_first = int(getattr(state, "skip_buy_first_minutes", 0) or 0)
                                            if skip_first > 0:
                                                open_min = 9 * 60 + 0
                                                if now_min < open_min + skip_first:
                                                    _record_buy_skip(stock_code, "skip_first_minutes")
                                                    _throttled_skip_log(stock_code, f"장 초반 {skip_first}분 매수 스킵")
                                                    continue
                                            # (5) 장 마감 전 N분 신규 매수 스킵
                                            last_no_buy = int(getattr(state, "last_minutes_no_buy", 0) or 0)
                                            if last_no_buy > 0:
                                                end_t = _parse_hhmm(end_hhmm)
                                                if end_t:
                                                    end_min = end_t.hour * 60 + end_t.minute
                                                    if now_min >= end_min - last_no_buy:
                                                        _record_buy_skip(stock_code, "last_minutes_no_buy")
                                                        _throttled_skip_log(stock_code, f"마감 {last_no_buy}분 전 매수 스킵")
                                                        continue
                                        except Exception:
                                            pass
                                    # 선정에 없는 종목(전일 잔여 등)은 매도만 허용·매수 무시
                                    if signal_type == "buy" and stock_code not in (state.selected_stocks or []):
                                        signal_type = None
                                    if signal_type:
                                        _handle_signal(stock_code, signal_type, current_price, "이동평균 크로스 조건 충족")
                            except Exception:
                                continue

                    kws.start(on_result=on_result)
                except Exception as e:
                    logger.error(f"트레이딩 엔진 오류: {e}")
                    _run_async_broadcast({"type": "log", "message": f"트레이딩 엔진 오류: {e}", "level": "error"})
                if first_disconnect_ts is None:
                    first_disconnect_ts = time.time()
                try:
                    _sync_state_after_ws_reconnect()
                except Exception:
                    pass
                if emergency_minutes > 0 and first_disconnect_ts and (time.time() - first_disconnect_ts) >= emergency_minutes * 60:
                    rm = getattr(state, "risk_manager", None)
                    if rm and getattr(rm, "positions", None) and state.is_running:
                        for code, pos in list(rm.positions.items()):
                            qty = int(pos.get("quantity", 0) or 0)
                            if qty <= 0:
                                continue
                            px = float(pos.get("current_price") or rm.last_prices.get(code) or pos.get("buy_price") or 0)
                            if px <= 0:
                                continue
                            _handle_signal(code, "sell", px, "긴급 청산(WS 장시간 단절)", suggested_qty_override=qty)
                        _run_async_broadcast({"type": "log", "message": "긴급 청산: WebSocket 장시간 단절로 전량 매도 신호 실행", "level": "error"})
                    first_disconnect_ts = None
                time.sleep(ws_reconnect_sleep)
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

def _get_stock_selection_criteria(current_user: str):
    """현재 적용된 또는 저장된 종목 선정 기준을 dict로 반환. 없으면 None. 표시용으로 저장된 설정을 우선 반환."""
    store = _get_user_settings_store()
    if store and getattr(store, "enabled", False):
        try:
            saved = store.load(current_user) or {}
            cfg = saved.get("stock_selection_config")
            if cfg and isinstance(cfg, dict):
                return cfg
        except Exception:
            pass
    sel = getattr(state, "stock_selector", None)
    if sel is not None:
        return {
            "min_price_change_ratio": getattr(sel, "min_price_change_ratio", 0.01),
            "max_price_change_ratio": getattr(sel, "max_price_change_ratio", 0.15),
            "min_price": getattr(sel, "min_price", 1000),
            "max_price": getattr(sel, "max_price", 100000),
            "min_volume": getattr(sel, "min_volume", 100000),
            "min_trade_amount": getattr(sel, "min_trade_amount", 0),
            "max_stocks": getattr(sel, "max_stocks", 10),
            "exclude_risk_stocks": getattr(sel, "exclude_risk_stocks", True),
            "sort_by": getattr(sel, "sort_by", "change"),
            "warmup_minutes": getattr(sel, "warmup_minutes", 5),
            "early_strict": getattr(sel, "early_strict", False),
            "early_min_volume": getattr(sel, "early_min_volume", 200000),
            "early_min_trade_amount": getattr(sel, "early_min_trade_amount", 0),
            "exclude_drawdown": getattr(sel, "exclude_drawdown", False),
            "kospi_only": getattr(sel, "kospi_only", False),
        }
    return None


_STATUS_NO_CACHE = {"Cache-Control": "no-store, no-cache, must-revalidate"}


def _build_settings_snapshot_for_preflight(username: str) -> Dict[str, Any]:
    """시작 전 점검용: DB 설정 + 현재 state 핵심값 스냅샷."""
    snap: Dict[str, Any] = {
        "username": username,
        "is_paper_trading": bool(getattr(state, "is_paper_trading", True)),
        "manual_approval": bool(getattr(state, "manual_approval", True)),
        "selected_stocks": list(getattr(state, "selected_stocks", []) or []),
    }
    try:
        rm = getattr(state, "risk_manager", None)
        if rm:
            snap["risk"] = {
                "account_balance": float(getattr(rm, "account_balance", 0) or 0),
                "max_single_trade_amount": int(getattr(rm, "max_single_trade_amount", 0) or 0),
                "max_position_size_ratio": float(getattr(rm, "max_position_size_ratio", 0.0) or 0.0),
                "max_positions_count": int(getattr(rm, "max_positions_count", 0) or 0),
                "min_order_quantity": int(getattr(rm, "min_order_quantity", 1) or 1),
                "stop_loss_ratio": float(getattr(rm, "stop_loss_ratio", 0.0) or 0.0),
                "take_profit_ratio": float(getattr(rm, "take_profit_ratio", 0.0) or 0.0),
                "daily_loss_limit": int(getattr(rm, "daily_loss_limit", 0) or 0),
                "daily_total_loss_limit": int(getattr(rm, "daily_total_loss_limit", 0) or 0),
                "daily_profit_limit": int(getattr(rm, "daily_profit_limit", 0) or 0),
                "max_trades_per_day": int(getattr(rm, "max_trades_per_day", 0) or 0),
                "max_trades_per_stock_per_day": int(getattr(rm, "max_trades_per_stock_per_day", 0) or 0),
                "slippage_bps": int(getattr(rm, "slippage_bps", 0) or 0),
            }
    except Exception:
        pass
    try:
        strat = getattr(state, "strategy", None)
        if strat:
            snap["strategy"] = {
                "short_ma_period": int(getattr(strat, "short_ma_period", 0) or 0),
                "long_ma_period": int(getattr(strat, "long_ma_period", 0) or 0),
                "min_hold_seconds": int(getattr(strat, "min_hold_seconds", 0) or 0),
                "buy_window_start_hhmm": str(getattr(state, "buy_window_start_hhmm", "09:05") or "09:05"),
                "buy_window_end_hhmm": str(getattr(state, "buy_window_end_hhmm", "11:30") or "11:30"),
            }
    except Exception:
        pass
    try:
        snap["operational"] = {
            "enable_auto_rebalance": bool(getattr(state, "enable_auto_rebalance", False)),
            "auto_rebalance_interval_minutes": int(getattr(state, "auto_rebalance_interval_minutes", 30) or 30),
        }
    except Exception:
        pass
    try:
        store = _get_user_settings_store()
        if store and getattr(store, "enabled", False):
            snap["db_settings"] = store.load(username) or {}
    except Exception:
        pass
    return snap


def _preflight_check(username: str) -> Dict[str, Any]:
    """
    시작 전 강제 점검:
    - 치명 이슈(issues)가 있으면 시작 차단
    - 경고(warnings)는 로그로 남기되 시작은 허용(필요 시 강화 가능)
    """
    issues: List[str] = []
    warnings: List[str] = []

    # 필수 객체
    if not getattr(state, "trenv", None):
        issues.append("KIS 환경(trenv)이 없습니다. (초기화 실패)")
    if not getattr(state, "risk_manager", None):
        issues.append("RiskManager가 초기화되지 않았습니다.")
    if not getattr(state, "strategy", None):
        issues.append("Strategy가 초기화되지 않았습니다.")
    if not getattr(state, "stock_selector", None):
        warnings.append("StockSelector가 없습니다. 종목 재선정 기능이 제한될 수 있습니다.")

    # 실전/자동 안전장치(추가 안전: 여기서는 점검용 메시지)
    if (not bool(getattr(state, "is_paper_trading", True))) and (not bool(getattr(state, "manual_approval", True))):
        warnings.append("실전 + 자동(즉시체결) 조합입니다. 안전장치 설정에 따라 시작이 차단될 수 있습니다.")

    # 리스크 핵심값 sanity
    rm = getattr(state, "risk_manager", None)
    if rm:
        try:
            bal = float(getattr(rm, "account_balance", 0) or 0)
            if bal <= 0:
                warnings.append("계좌 잔고(account_balance)가 0 이하입니다. (잔고 조회 실패/초기화 문제 가능)")
        except Exception:
            warnings.append("account_balance 파싱 실패")
        try:
            msa = int(getattr(rm, "max_single_trade_amount", 0) or 0)
            if msa <= 0:
                issues.append("max_single_trade_amount가 0 이하입니다. (주문 상한 미설정)")
        except Exception:
            issues.append("max_single_trade_amount 파싱 실패")
        try:
            mpsr = float(getattr(rm, "max_position_size_ratio", 0.0) or 0.0)
            if mpsr <= 0 or mpsr > 1.0:
                issues.append("max_position_size_ratio가 비정상입니다. (0 < ratio <= 1 이어야 함)")
        except Exception:
            issues.append("max_position_size_ratio 파싱 실패")
        try:
            sl = float(getattr(rm, "stop_loss_ratio", 0.0) or 0.0)
            tp = float(getattr(rm, "take_profit_ratio", 0.0) or 0.0)
            if sl <= 0 or sl > 0.2:
                issues.append("stop_loss_ratio가 비정상입니다. (0 < ratio <= 0.2 권장)")
            if tp <= 0 or tp > 0.5:
                issues.append("take_profit_ratio가 비정상입니다. (0 < ratio <= 0.5 권장)")
        except Exception:
            issues.append("손절/익절 비율 파싱 실패")
        try:
            dll = int(getattr(rm, "daily_loss_limit", 0) or 0)
            if dll <= 0:
                issues.append("daily_loss_limit가 0 이하입니다. (일일 손실 한도 미설정)")
        except Exception:
            issues.append("daily_loss_limit 파싱 실패")
        try:
            mtd = int(getattr(rm, "max_trades_per_day", 0) or 0)
            if mtd <= 0:
                issues.append("max_trades_per_day가 0 이하입니다.")
        except Exception:
            issues.append("max_trades_per_day 파싱 실패")
        try:
            miq = int(getattr(rm, "min_order_quantity", 1) or 1)
            if miq < 1:
                issues.append("min_order_quantity가 1 미만입니다.")
        except Exception:
            issues.append("min_order_quantity 파싱 실패")

    # 종목 목록
    sel = getattr(state, "selected_stocks", None)
    if not isinstance(sel, list) or not sel:
        warnings.append("selected_stocks가 비어있습니다. (시작 시 자동 선정이 실패했을 수 있음)")

    snap = _build_settings_snapshot_for_preflight(username)
    return {
        "ok": len(issues) == 0,
        "issues": issues,
        "warnings": warnings,
        "snapshot": snap,
    }


def _load_today_daily_stats(current_user: str) -> tuple:
    """당일 일일 손익·거래 횟수를 user_result 또는 user_hist에서 조회. (daily_pnl, daily_trades) 또는 (None, None)."""
    if not current_user:
        return (None, None)
    tz = timezone(timedelta(hours=9))
    today = datetime.now(tz).strftime("%Y%m%d")
    try:
        store = _get_user_result_store()
        if store and store.enabled:
            row = store.get(current_user, today)
            if row is not None:
                pnl = float(row.get("pnl") or 0)
                cnt = int(row.get("trade_count") or 0)
                return (pnl, cnt)
    except Exception:
        pass
    try:
        from user_hist_store import get_user_hist_store
        hist = get_user_hist_store()
        if hist and getattr(hist, "enabled", False):
            rows = hist.get_trades(current_user, today, today)
            if rows:
                daily_pnl = sum(float(t.get("pnl") or 0) for t in rows if (t.get("order_type") or "").strip().lower() == "sell" and t.get("pnl") is not None)
                daily_trades = sum(1 for t in rows if (t.get("order_type") or "").strip().lower() == "buy")
                return (daily_pnl, daily_trades)
    except Exception:
        pass
    return (None, None)


@app.get("/api/system/status")
async def get_system_status(current_user: str = Depends(get_current_user)):
    """시스템 상태 조회"""
    criteria = _get_stock_selection_criteria(current_user)
    if not state.risk_manager:
        # 시스템 중지 상태에서도 DB( user_result / user_hist ) 기준 당일 손익·거래 횟수 표시
        daily_pnl, daily_trades = 0, 0
        try:
            pnl, cnt = _load_today_daily_stats(current_user)
            if pnl is not None and cnt is not None:
                daily_pnl, daily_trades = float(pnl), int(cnt)
        except Exception:
            pass
        return JSONResponse({
            "is_running": False,
            "is_paper_trading": getattr(state, "is_paper_trading", True),
            "manual_approval": getattr(state, "manual_approval", True),
            "env_name": "-",
            "account_balance": 0,
            "daily_pnl": daily_pnl,
            "daily_trades": daily_trades,
            "selected_stocks": getattr(state, "selected_stocks", []) or [],
            "selected_stock_info": getattr(state, "selected_stock_info", []) or [],
            "stock_selection_criteria": criteria,
            "stock_selection_last_debug": getattr(getattr(state, "stock_selector", None), "last_debug", {}) or {},
            "stock_selection_last_error": getattr(getattr(state, "stock_selector", None), "last_error_message", "") or "",
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
            "auto_schedule_enabled": getattr(state, "auto_schedule_enabled", False),
            "auto_start_hhmm": getattr(state, "auto_start_hhmm", "09:30") or "09:30",
            "auto_stop_hhmm": getattr(state, "auto_stop_hhmm", "12:00") or "12:00",
            "liquidate_on_auto_stop": getattr(state, "liquidate_on_auto_stop", True),
            "auto_schedule_username": getattr(state, "auto_schedule_username", "") or "",
            "stock_selection_criteria": criteria,
            "positions": {},
        }, headers=_STATUS_NO_CACHE)
    
    await _refresh_kis_account_balance(force=False, ttl_sec=60)
    # 재시작 후 접속 시 당일 손익이 0이면 DB에서 복원
    try:
        rm = state.risk_manager
        if float(getattr(rm, "daily_pnl", 0) or 0) == 0:
            pnl, cnt = _load_today_daily_stats(current_user)
            if pnl is not None:
                rm.daily_pnl = float(pnl)
                # 거래 횟수는 이미 값이 있으면 유지, 없으면 DB 기준으로 채움
                if cnt is not None and int(getattr(rm, "daily_trades", 0) or 0) == 0:
                    rm.daily_trades = int(cnt)
                if getattr(state, "is_paper_trading", True):
                    kis_bal = int(getattr(state, "kis_account_balance", 0) or 0)
                    if kis_bal > 0:
                        state.session_start_balance = float(kis_bal) - float(pnl)
    except Exception:
        pass
    kis_balance = int(getattr(state, "kis_account_balance", 0) or 0)
    kis_balance_ok = bool(getattr(state, "kis_account_balance_ok", False))
    return JSONResponse({
        "is_running": state.is_running,
        "is_paper_trading": state.is_paper_trading,
        "manual_approval": getattr(state, "manual_approval", True),
        "env_name": "모의투자" if state.is_paper_trading else "실전투자",
        "account_balance": _get_display_account_balance(),
        "kis_account_balance": kis_balance,
        "kis_account_balance_ok": kis_balance_ok,
        "daily_pnl": state.risk_manager.daily_pnl,
        "daily_trades": state.risk_manager.daily_trades,
        "selected_stocks": state.selected_stocks,
        "selected_stock_info": getattr(state, "selected_stock_info", []),
        "short_ma_period": state.strategy.short_ma_period if state.strategy else None,
        "long_ma_period": state.strategy.long_ma_period if state.strategy else None,
        "stock_selection_last_debug": getattr(getattr(state, "stock_selector", None), "last_debug", {}) or {},
        "stock_selection_last_error": getattr(getattr(state, "stock_selector", None), "last_error_message", "") or "",
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
        "auto_schedule_enabled": getattr(state, "auto_schedule_enabled", False),
        "auto_start_hhmm": getattr(state, "auto_start_hhmm", "09:30") or "09:30",
        "auto_stop_hhmm": getattr(state, "auto_stop_hhmm", "12:00") or "12:00",
        "liquidate_on_auto_stop": getattr(state, "liquidate_on_auto_stop", True),
        "auto_schedule_username": getattr(state, "auto_schedule_username", "") or "",
        "stock_selection_criteria": criteria,
        "positions": _build_positions_message(),
    }, headers=_STATUS_NO_CACHE)


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

async def _do_start_system(username: str) -> tuple:
    """시스템 시작 내부 로직. (success: bool, message: str) 반환."""
    try:
        if state.is_running:
            return False, "이미 실행 중입니다."

        if not state.strategy or not state.trenv or not state.risk_manager:
            ok = _ensure_initialized()
            if not ok or not state.strategy or not state.trenv or not state.risk_manager:
                detail = getattr(state, "last_init_error", None)
                msg = "시스템 초기화 실패: KIS 설정(.env/kis_devlp.yaml), 네트워크, 계정 설정을 확인하세요."
                if detail:
                    msg = f"{msg} (detail: {detail})"
                return False, msg

        store = _get_user_settings_store()
        if store and getattr(store, "enabled", False):
            try:
                saved = store.load(username) or {}
                _apply_risk_config_dict_to_state(saved.get("risk_config"))
                _apply_operational_config_dict_to_state(saved.get("operational_config"))
                _apply_strategy_config_dict_to_state(saved.get("strategy_config"))
                _apply_stock_selection_config_dict_to_state(saved.get("stock_selection_config"))
                try:
                    # 시작 시 실제 반영된 핵심값을 시스템 로그에 남김 (커스텀(DB 저장값) 적용 확인용)
                    sp = getattr(state.strategy, "short_ma_period", None)
                    lp = getattr(state.strategy, "long_ma_period", None)
                    mtd = getattr(state.risk_manager, "max_trades_per_day", None) if getattr(state, "risk_manager", None) else None
                    system_log_append("info", f"시작 시 DB 저장 설정 적용: user={username} short_ma_period={sp} long_ma_period={lp} max_trades_per_day={mtd}")
                except Exception:
                    pass
            except Exception as e:
                logger.warning(f"시작 시 저장 설정 적용 실패(무시): {e}")

        # 저장된 종목선정 설정으로 1회 자동 선정
        # 정책: 사용자가 이미 `state.selected_stocks`를 지정해 둔 경우(종목 재선정 완료 후 시작)는
        # 시작 시 자동 재선정이 이를 덮어쓰지 않도록 selected가 비어있을 때만 수행합니다.
        if getattr(state, "stock_selector", None) and not getattr(state, "selected_stocks", None):
            try:
                selected = state.stock_selector.select_stocks_by_fluctuation()
                if selected:
                    state.selected_stocks = selected
                    state.selected_stock_info = getattr(
                        state.stock_selector,
                        "last_selected_stock_info",
                        [{"code": c, "name": c} for c in selected],
                    )
                    logger.info("시작 시 종목 선정 완료: %s", ", ".join(selected))
                else:
                    keep_prev = bool(getattr(state, "keep_previous_on_empty_selection", True))
                    if not keep_prev or not getattr(state, "selected_stocks", None):
                        state.selected_stocks = ["005930", "000660"]
                        state.selected_stock_info = DEFAULT_STOCK_INFO.copy()
                        logger.info("시작 시 종목 선정 결과 없음 → 디폴트 종목 적용")
                    else:
                        logger.info("시작 시 종목 선정 결과 없음 → 이전 목록 유지")
            except Exception as e:
                logger.warning(f"시작 시 종목 선정 실패(무시): {e}")
        if not state.selected_stocks:
            state.selected_stocks = ["005930", "000660"]
        if not getattr(state, "selected_stock_info", None):
            state.selected_stock_info = DEFAULT_STOCK_INFO.copy()

        # Preflight: 강제 점검(치명 이슈 시 시작 차단)
        try:
            pf = _preflight_check(username)
            if not pf.get("ok"):
                issues = pf.get("issues") or []
                warnings = pf.get("warnings") or []
                msg = "시작 차단(Preflight 실패): " + ("; ".join(issues) if issues else "unknown")
                # 시스템 로그(파일) + 대시보드 로그에 남김
                try:
                    system_log_append("error", msg)
                    if warnings:
                        system_log_append("warning", "Preflight warnings: " + "; ".join(warnings))
                except Exception:
                    pass
                try:
                    await state.broadcast({"type": "log", "level": "error", "message": msg})
                    for w in warnings:
                        await state.broadcast({"type": "log", "level": "warning", "message": f"[Preflight] {w}"})
                except Exception:
                    pass
                return False, msg
            else:
                warnings = pf.get("warnings") or []
                if warnings:
                    try:
                        for w in warnings:
                            await state.broadcast({"type": "log", "level": "warning", "message": f"[Preflight] {w}"})
                    except Exception:
                        pass
                try:
                    snap = pf.get("snapshot") or {}
                    # 너무 길어지는 것을 피하기 위해 핵심만 남김
                    r = (snap.get("risk") or {}) if isinstance(snap, dict) else {}
                    s = (snap.get("strategy") or {}) if isinstance(snap, dict) else {}
                    system_log_append(
                        "info",
                        "Preflight OK: "
                        f"paper={snap.get('is_paper_trading')} manual={snap.get('manual_approval')} "
                        f"max_single={r.get('max_single_trade_amount')} daily_loss={r.get('daily_loss_limit')} "
                        f"short={s.get('short_ma_period')} long={s.get('long_ma_period')}",
                    )
                except Exception:
                    pass
        except Exception as e:
            # 점검 로직 자체 오류는 보수적으로 차단
            msg = f"시작 차단(Preflight 오류): {e}"
            try:
                await state.broadcast({"type": "log", "level": "error", "message": msg})
            except Exception:
                pass
            return False, msg

        # 시작 시 당일 손익·거래 횟수 복원(초기화로 0이 된 값은 DB/거래내역 기준으로 합산 유지)
        try:
            pnl, cnt = _load_today_daily_stats(username)
            if pnl is not None and cnt is not None:
                state.risk_manager.daily_pnl = float(pnl)
                state.risk_manager.daily_trades = int(cnt)
                if getattr(state, "is_paper_trading", True):
                    kis_bal = int(getattr(state, "kis_account_balance", 0) or 0)
                    if kis_bal > 0:
                        state.session_start_balance = float(kis_bal) - float(pnl)
        except Exception:
            pass

        # 안전장치: 실전(real) + 자동(즉시 체결) 조합은 기본적으로 차단 (환경변수로만 해제)
        # - 실수로 실전 자동매매를 켜서 손실이 나는 사고 방지 목적
        try:
            allow_real_auto = str(os.getenv("ALLOW_REAL_AUTO_TRADING", "false") or "false").strip().lower() in {"1", "true", "t", "yes", "y", "on"}
        except Exception:
            allow_real_auto = False
        if (not getattr(state, "is_paper_trading", True)) and (not bool(getattr(state, "manual_approval", True))) and (not allow_real_auto):
            msg = "안전장치: 실전투자 + 자동(즉시 체결) 모드는 기본적으로 차단됩니다. 수동(승인대기)으로 바꾸거나, 반드시 필요하면 서버 환경변수 ALLOW_REAL_AUTO_TRADING=true로 해제한 뒤 다시 시작하세요."
            try:
                await state.broadcast({"type": "log", "level": "error", "message": msg})
            except Exception:
                pass
            return False, msg

        state.is_running = True
        state.trading_username = username
        logger.info("시스템 시작: trading_username=%s (quant_trading_user_hist 저장 대상)", username)
        try:
            if getattr(state, "session_start_balance", None) is None:
                state.session_start_balance = float(_get_display_account_balance() or getattr(state.risk_manager, "account_balance", 0) or 0)
        except Exception:
            if getattr(state, "session_start_balance", None) is None:
                state.session_start_balance = float(getattr(state.risk_manager, "account_balance", 0) or 0)
        _start_trading_engine_thread()
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
        return True, f"시스템 시작 (감시 종목: {', '.join(state.selected_stocks)})"
    except Exception as e:
        logger.error(f"시스템 시작 오류: {e}")
        return False, str(e)


@app.post("/api/system/start")
async def start_system(current_user: str = Depends(get_current_user)):
    """시스템 시작"""
    success, message = await _do_start_system(current_user)
    return JSONResponse({"success": success, "message": message})


@app.get("/api/system/preflight")
async def system_preflight(current_user: str = Depends(get_current_user)):
    """시스템 시작 전 강제 점검(Preflight). 시작은 하지 않고 결과만 반환."""
    try:
        if not state.strategy or not state.trenv or not state.risk_manager:
            _ensure_initialized()
        # DB 설정을 먼저 반영한 뒤 점검
        store = _get_user_settings_store()
        if store and getattr(store, "enabled", False):
            saved = store.load(current_user) or {}
            _apply_risk_config_dict_to_state(saved.get("risk_config"))
            _apply_operational_config_dict_to_state(saved.get("operational_config"))
            _apply_strategy_config_dict_to_state(saved.get("strategy_config"))
            _apply_stock_selection_config_dict_to_state(saved.get("stock_selection_config"))
        pf = _preflight_check(current_user)
        return JSONResponse({"success": True, "preflight": pf})
    except Exception as e:
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


async def _do_stop_system(username: str, liquidate: bool) -> tuple:
    """시스템 중지 내부 로직. (success: bool, message: str) 반환."""
    try:
        state.is_running = False
        # 엔진 스레드가 다음 WebSocket 끊김 시 루프를 빠져나가도록 설정 (재시작 시 새 선정 목록으로 구독하려면 필수)
        state.engine_running = False
        try:
            t = getattr(state, "pending_order_reconciler_task", None)
            if t is not None and hasattr(t, "cancel"):
                t.cancel()
            state.pending_order_reconciler_task = None
        except Exception:
            pass
        with pending_signals_lock:
            state.pending_signals = {}
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
                        "pnl": pnl,
                        "reason": "자동종료 청산" if liquidate else "시간기반 청산",
                    }
                    state.add_trade(trade_info)
                    await state.broadcast({"type": "trade", "data": trade_info})
            await state.broadcast({"type": "log", "message": "청산 완료", "level": "info"})

        try:
            store = _get_user_result_store()
            if store and store.enabled and state.risk_manager:
                tz = timezone(timedelta(hours=9))
                today = datetime.now(tz).strftime("%Y%m%d")
                today_ymd = today[:4] + "-" + today[4:6] + "-" + today[6:8]
                equity_end = float(_get_display_account_balance() or getattr(state.risk_manager, "account_balance", 0) or 0)
                trade_count = int(getattr(state.risk_manager, "daily_trades", 0) or 0)
                equity_start = getattr(state, "session_start_balance", None)
                wins, losses, gross_profit, gross_loss = None, None, None, None
                history = getattr(state, "trade_history", []) or []
                today_pnls = []
                for t in history:
                    ts = t.get("timestamp") or ""
                    if isinstance(ts, str) and (ts.startswith(today_ymd) or ts.startswith(today)):
                        pnl = t.get("pnl")
                        if pnl is not None:
                            try:
                                today_pnls.append(float(pnl))
                            except Exception:
                                pass
                if today_pnls:
                    wins = sum(1 for p in today_pnls if p > 0)
                    losses = sum(1 for p in today_pnls if p < 0)
                    gross_profit = sum(p for p in today_pnls if p > 0)
                    gross_loss = sum(p for p in today_pnls if p < 0)
                store.save_daily_result(
                    username, today, equity_end, trade_count, equity_start=equity_start,
                    wins=wins, losses=losses, gross_profit=gross_profit, gross_loss=gross_loss,
                )
                await state.broadcast({"type": "log", "message": f"일별 성과 저장됨: {today}", "level": "info"})
        except Exception as e:
            logger.warning("일별 성과 저장 실패(무시): %s", e, exc_info=True)

        await send_status_update()
        await state.broadcast({"type": "signal_snapshot", "data": []})
        return True, "시스템이 중지되었습니다."
    except Exception as e:
        logger.error(f"시스템 중지 오류: {e}")
        return False, str(e)


@app.post("/api/system/stop")
async def stop_system(
    liquidate: bool = Query(False),
    current_user: str = Depends(get_current_user)
):
    """시스템 중지"""
    success, message = await _do_stop_system(current_user, liquidate)
    return JSONResponse({"success": success, "message": message})


async def _auto_schedule_loop():
    """매일 지정 시각(KST)에 자동 시작/종료. 60초마다 확인."""
    kst = timezone(timedelta(hours=9))
    while True:
        await asyncio.sleep(60)
        if not getattr(state, "auto_schedule_enabled", False):
            continue
        now = datetime.now(kst)
        today = now.strftime("%Y-%m-%d")
        hhmm = now.strftime("%H:%M")
        start_hhmm = (getattr(state, "auto_start_hhmm", None) or "09:30").strip()[:5]
        stop_hhmm = (getattr(state, "auto_stop_hhmm", None) or "12:00").strip()[:5]
        liquidate = getattr(state, "liquidate_on_auto_stop", True)
        username = (getattr(state, "auto_schedule_username", None) or "").strip() or "admin"
        if hhmm == start_hhmm and getattr(state, "_last_auto_start_date", None) != today:
            state._last_auto_start_date = today
            try:
                ok, msg = await _do_start_system(username)
                logger.info("자동 시작: %s %s", ok, msg)
                await state.broadcast({"type": "log", "message": f"자동 시작: {msg}", "level": "info" if ok else "error"})
            except Exception as e:
                logger.exception("자동 시작 예외")
                await state.broadcast({"type": "log", "message": f"자동 시작 실패: {e}", "level": "error"})
        if hhmm == stop_hhmm and getattr(state, "_last_auto_stop_date", None) != today:
            state._last_auto_stop_date = today
            try:
                ok, msg = await _do_stop_system(username, liquidate)
                logger.info("자동 종료: %s %s (청산=%s)", ok, msg, liquidate)
                await state.broadcast({"type": "log", "message": f"자동 종료: {msg}", "level": "info" if ok else "error"})
            except Exception as e:
                logger.exception("자동 종료 예외")
                await state.broadcast({"type": "log", "message": f"자동 종료 실패: {e}", "level": "error"})


@app.on_event("startup")
async def _start_auto_schedule():
    """앱 기동 시 자동 스케줄 루프 시작."""
    asyncio.create_task(_auto_schedule_loop())
    logger.info("자동 스케줄 루프 시작 (매일 auto_start_hhmm/auto_stop_hhmm 적용)")


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
    """거래 내역 조회 (메모리, 최근 limit건)"""
    return JSONResponse(state.trade_history[-limit:])


@app.get("/api/trades/system")
async def get_trades_system(
    date_from: Optional[str] = Query(None, description="시작일 YYYYMMDD"),
    date_to: Optional[str] = Query(None, description="종료일 YYYYMMDD"),
    current_user: str = Depends(get_current_user),
):
    """매매 시스템 거래내역: DB(quant_trading_user_hist) 또는 메모리. 미지정 시 오늘."""
    tz = timezone(timedelta(hours=9))
    today = datetime.now(tz).strftime("%Y%m%d")
    d_from = date_from or today
    d_to = date_to or today
    try:
        store = None
        try:
            from user_hist_store import get_user_hist_store
            store = get_user_hist_store()
        except Exception:
            pass
        if store and store.enabled:
            rows = store.get_trades(current_user, d_from, d_to)
            if rows:
                # timestamp 필드로 정렬 (최신 먼저)
                for r in rows:
                    if r.get("timestamp") is None and r.get("date") and r.get("time"):
                        r["timestamp"] = f"{r['date'][:4]}-{r['date'][4:6]}-{r['date'][6:8]}T{r['time'][:2]}:{r['time'][2:4]}:{r['time'][4:6]}"
                rows.sort(key=lambda x: (x.get("timestamp") or ""), reverse=True)
                return JSONResponse(rows)
        # fallback: 메모리에서 해당 기간만
        history = getattr(state, "trade_history", []) or []
        out = []
        for t in history:
            ts = (t.get("timestamp") or "")
            if not ts or "T" not in ts:
                continue
            try:
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=tz)
                d = dt.strftime("%Y%m%d")
                if d_from <= d <= d_to:
                    out.append(dict(t))
            except Exception:
                pass
        out.sort(key=lambda x: (x.get("timestamp") or ""), reverse=True)
        return JSONResponse(out[:200])
    except Exception as e:
        logger.warning("get_trades_system failed: %s", e)
        return JSONResponse({"error": str(e)}, status_code=500)


def _read_system_log_for_date(yyyymmdd: str) -> str:
    """
    system_YYYYMMDD.log 내용을 문자열로 반환. 너무 길면 최근 부분만 잘라서 반환.
    """
    try:
        log_dir_env = os.environ.get("SYSTEM_LOG_DIR", "logs").strip()
        if log_dir_env in ("0", "off", "false", "no"):
            return ""
        if os.path.isabs(log_dir_env):
            log_dir = log_dir_env
        else:
            root = os.path.dirname(os.path.abspath(__file__))
            log_dir = os.path.join(root, log_dir_env)
        path = os.path.join(log_dir, f"system_{yyyymmdd}.log")
        if not os.path.isfile(path):
            return ""
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        # 로그가 너무 길면 최근 1000줄만 사용
        if len(lines) > 1000:
            lines = lines[-1000:]
        return "".join(lines)
    except Exception as e:
        logger.warning("AI report: system log read failed for %s: %s", yyyymmdd, e)
        return ""


def _build_ai_daily_input(username: str, yyyymmdd: str) -> Dict[str, Any]:
    """
    AI 일일 리포트 입력 데이터 구성: 로그 + 거래내역 + 설정 스냅샷.
    """
    from user_hist_store import get_user_hist_store

    log_text = _read_system_log_for_date(yyyymmdd)

    # 거래내역: quant_trading_user_hist (1일 범위)
    trades: List[Dict[str, Any]] = []
    try:
        hist = get_user_hist_store()
        if hist and hist.enabled:
            trades = hist.get_trades(username, yyyymmdd, yyyymmdd)
    except Exception as e:
        logger.warning("AI report: get_trades failed (%s %s): %s", username, yyyymmdd, e)

    # 설정 스냅샷: quant_trading_user_settings
    settings: Dict[str, Any] = {}
    try:
        store = _get_user_settings_store()
        if store and getattr(store, "enabled", False):
            settings = store.load(username) or {}
    except Exception as e:
        logger.warning("AI report: user settings load failed (%s): %s", username, e)

    return {
        "username": username,
        "date": yyyymmdd,
        "log_text": log_text,
        "trades": trades,
        "settings": settings,
    }


def _get_ai_client():
    if OpenAI is None:
        return None
    try:
        return OpenAI()
    except Exception as e:  # pragma: no cover - 환경 의존
        logger.warning("AI report: OpenAI client init failed: %s", e)
        return None


def _generate_ai_daily_report(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    AI 모델을 호출해 일일 리포트(JSON)를 생성.
    """
    client = _get_ai_client()
    if client is None:
        raise RuntimeError("AI client not configured (OpenAI SDK 또는 API 키 미설정)")

    model = os.getenv("AI_REPORT_MODEL", "gpt-4.1-mini")

    system_prompt = (
        "당신은 퀀트 주식 자동매매 시스템의 리스크/전략 분석 어드바이저입니다. "
        "입력으로 하루치 시스템 로그, 거래내역(quant_trading_user_hist), "
        "사용자 설정(quant_trading_user_settings 스냅샷)을 받습니다. "
        "전략 성과, 리스크, 파라미터 적정성, 개선 아이디어를 구조화된 JSON으로 출력하세요. "
        "실제 매매 변경은 사람이 결정하므로, 제안은 보수적으로 하고 근거를 함께 제시하세요."
    )

    # 프롬프트 입력 데이터 정리 (너무 길지 않게 요약 필드 포함)
    log_text = payload.get("log_text") or ""
    trades = payload.get("trades") or []
    settings = payload.get("settings") or {}

    # 거래건수가 많아도 요약 가능하도록 상한 제한
    max_trades = 300
    if len(trades) > max_trades:
        trades_input = trades[:max_trades]
    else:
        trades_input = trades

    user_payload = {
        "username": payload.get("username"),
        "date": payload.get("date"),
        "log_text": log_text,
        "trades": trades_input,
        "trades_truncated": len(trades) > len(trades_input),
        "settings": settings,
    }

    try:
        resp = client.responses.create(
            model=model,
            input=[
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": "아래 JSON 데이터를 분석해서 일일 리포트를 생성해 주세요.\n"
                    "반드시 JSON 객체 형식만 출력하세요.\n"
                    + json.dumps(user_payload, ensure_ascii=False),
                },
            ],
            response_format={"type": "json_object"},
        )
        text = resp.output[0].content[0].text  # type: ignore[attr-defined]
        data = json.loads(text)
        if not isinstance(data, dict):
            raise ValueError("AI 응답이 JSON 객체 형식이 아닙니다.")
        return data
    except Exception as e:
        logger.warning("AI report: generation failed: %s", e, exc_info=True)
        raise


@app.get("/api/ai/report/daily")
async def get_ai_report_daily(
    date: Optional[str] = Query(None, description="YYYYMMDD. 비면 오늘."),
    current_user: str = Depends(get_current_user),
):
    """
    AI 일일 리포트 생성/조회.

    - 입력: system_YYYYMMDD.log, quant_trading_user_hist(해당일), quant_trading_user_settings 스냅샷
    - 출력: AI가 생성한 JSON 리포트 (요약, 지표 해석, 문제점, 파라미터 제안, 액션 아이템 등)
    """
    try:
        tz = timezone(timedelta(hours=9))
        today = datetime.now(tz).strftime("%Y%m%d")
        yyyymmdd = (date or today).strip().replace("-", "").replace("/", "")[:8]
        if len(yyyymmdd) != 8 or not yyyymmdd.isdigit():
            return JSONResponse({"success": False, "message": "date는 YYYYMMDD 형식이어야 합니다."}, status_code=400)

        payload = await asyncio.to_thread(_build_ai_daily_input, current_user, yyyymmdd)

        # AI 비활성화/미설정 시 안내
        if OpenAI is None or not os.getenv("OPENAI_API_KEY"):
            return JSONResponse(
                {
                    "success": False,
                    "message": "AI 리포트 기능이 비활성화되어 있습니다. 서버 환경에 OpenAI Python SDK와 OPENAI_API_KEY를 설정하세요.",
                    "date": yyyymmdd,
                    "input_preview": {
                        "has_log": bool(payload.get("log_text")),
                        "trade_count": len(payload.get("trades") or []),
                        "has_settings": bool(payload.get("settings")),
                    },
                },
                status_code=501,
            )

        report = await asyncio.to_thread(_generate_ai_daily_report, payload)
        return JSONResponse(
            {
                "success": True,
                "date": yyyymmdd,
                "report": report,
            }
        )
    except Exception as e:
        logger.warning("get_ai_report_daily failed: %s", e, exc_info=True)
        return JSONResponse({"success": False, "message": str(e)}, status_code=500)


@app.post("/api/positions/sync-from-balance")
async def sync_positions_from_balance(current_user: str = Depends(get_current_user)):
    """계좌 잔고 기준으로 포지션을 강제 동기화 (MTS 잔고와 불일치 시 복구용)."""
    try:
        if not state.strategy or not state.trenv or not state.risk_manager:
            ok = _ensure_initialized()
            if not ok or not state.trenv or not state.risk_manager:
                detail = getattr(state, "last_init_error", None)
                msg = "시스템 초기화 실패: KIS 설정(.env/kis_devlp.yaml), 네트워크, 계정 설정을 확인하세요."
                if detail:
                    msg = f"{msg} (detail: {detail})"
                return JSONResponse({"success": False, "message": msg}, status_code=400)

        n = await asyncio.to_thread(_sync_positions_from_balance_sync)
        attempt = getattr(state, "_last_positions_sync_attempt", None)
        await state.broadcast({"type": "position", "data": _build_positions_message()})
        await send_status_update()
        msg = f"{n}종목 동기화"
        if n == 0 and isinstance(attempt, dict):
            msg = f"0종목 동기화(잔고조회 결과 비어있음). attempt={attempt}"
        await state.broadcast({"type": "log", "level": "info" if n > 0 else "warning", "message": f"잔고 기반 포지션 동기화: {msg}"})
        return JSONResponse({"success": True, "message": msg, "count": n, "attempt": attempt})
    except Exception as e:
        logger.warning("positions sync-from-balance failed: %s", e, exc_info=True)
        return JSONResponse({"success": False, "message": str(e)}, status_code=500)


@app.post("/api/positions/liquidate")
async def liquidate_position(body: Optional[dict] = None, current_user: str = Depends(get_current_user)):
    """해당 종목 전량 매도 신호 생성(수동 청산). 수동 모드면 승인대기, 자동 모드면 즉시 주문."""
    stock_code = (body or {}).get("stock_code", "").strip().zfill(6)
    if not stock_code:
        return JSONResponse({"success": False, "message": "stock_code 필드가 필요합니다."}, status_code=400)
    rm = getattr(state, "risk_manager", None)
    if not rm or not getattr(rm, "positions", None):
        return JSONResponse({"success": False, "message": "포지션 정보가 없습니다."}, status_code=400)
    if stock_code not in rm.positions:
        return JSONResponse({"success": False, "message": f"보유 중인 종목이 아닙니다: {stock_code}"}, status_code=400)
    pos = rm.positions[stock_code]
    qty = int(pos.get("quantity", 0) or 0)
    if qty <= 0:
        return JSONResponse({"success": False, "message": "보유 수량이 없습니다."}, status_code=400)
    price = float(pos.get("current_price") or rm.last_prices.get(stock_code) or pos.get("buy_price") or 0)
    if price <= 0:
        price = float(pos.get("buy_price") or 0)
    if price <= 0:
        return JSONResponse({"success": False, "message": "유효한 가격을 알 수 없습니다. 잠시 후 다시 시도하세요."}, status_code=400)
    try:
        await asyncio.to_thread(_handle_signal, stock_code, "sell", price, "수동 청산", suggested_qty_override=qty)
        await state.broadcast({"type": "position", "data": _build_positions_message()})
        await send_status_update()
        return JSONResponse({"success": True, "message": f"{stock_code} 전량 매도 신호 처리됨(수동 청산)"})
    except Exception as e:
        logger.warning("liquidate_position failed: %s", e)
        return JSONResponse({"success": False, "message": str(e)}, status_code=500)


@app.get("/api/trades/account")
async def get_trades_account(
    date: Optional[str] = Query(None, description="조회일 YYYYMMDD, 미지정 시 오늘"),
    current_user: str = Depends(get_current_user),
):
    """계좌(한국투자증권) 거래내역: 주식일별주문체결조회 API."""
    tz = timezone(timedelta(hours=9))
    today = datetime.now(tz).strftime("%Y%m%d")
    inqr_date = date or today
    try:
        if not state.trenv:
            return JSONResponse(
                {"error": "계좌 미연결. 시스템 시작 후 다시 시도하세요.", "rows": []},
                status_code=400,
            )
        from domestic_stock_functions import inquire_daily_ccld

        env_dv = "demo" if getattr(state, "is_paper_trading", True) else "real"
        cano = getattr(state.trenv, "my_acct", "") or ""
        acnt_prdt_cd = getattr(state.trenv, "my_prod", "") or ""
        if not cano or not acnt_prdt_cd:
            return JSONResponse({"error": "계좌정보 없음.", "rows": []}, status_code=400)

        df1, _ = await asyncio.to_thread(
            inquire_daily_ccld,
            env_dv=env_dv,
            pd_dv="inner",
            cano=cano,
            acnt_prdt_cd=acnt_prdt_cd,
            inqr_strt_dt=inqr_date,
            inqr_end_dt=inqr_date,
            sll_buy_dvsn_cd="00",
            ccld_dvsn="01",
            inqr_dvsn="00",
            inqr_dvsn_3="00",
        )
        if df1 is None or (hasattr(df1, "empty") and df1.empty):
            return JSONResponse({"rows": [], "date": inqr_date})
        # DataFrame → 리스트 (JSON 직렬화 가능한 native 타입으로)
        def _to_native(v):
            if v is None:
                return None
            if hasattr(v, "item"):
                v = v.item()
            if isinstance(v, float) and (v != v or v == float("inf") or v == float("-inf")):
                return None
            if isinstance(v, (str, int, float, bool)):
                return v
            if isinstance(v, (int, float)):
                return int(v) if v == int(v) else float(v)
            return str(v)

        def _pick(row, *keys):
            for k in keys:
                v = row.get(k)
                if v is None:
                    v = row.get(k.upper()) if k.islower() else row.get(k.lower())
                if v is not None and v != "":
                    return _to_native(v)
            return None

        cols = list(df1.columns)
        rows = []
        for _, r in df1.iterrows():
            row = {c: _to_native(r.get(c)) for c in cols}
            ccld_qty = _pick(row, "ccld_qty", "CCLD_QTY", "tot_ccld_qty", "TOT_CCLD_QTY", "ccld_qty_tot", "CCLD_QTY_TOT")
            if ccld_qty is not None:
                row["ccld_qty"] = ccld_qty
            elif _pick(row, "ord_qty", "ORD_QTY") is not None:
                row["ccld_qty"] = _pick(row, "ord_qty", "ORD_QTY")
            rows.append(row)
        return JSONResponse({"rows": rows, "date": inqr_date})
    except Exception as e:
        logger.warning("get_trades_account failed: %s", e, exc_info=True)
        return JSONResponse({"error": str(e), "rows": []}, status_code=500)


def _compute_summary_from_trade_list(today_trades: list, today_str: str) -> dict:
    """당일 거래 리스트로 일일·세션 성과 및 권장 설정 계산. (공통 로직)"""
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
    gross_profit = sum(p for p in pnls if p > 0)
    gross_loss = sum(p for p in pnls if p < 0)
    profit_factor = (gross_profit / abs(gross_loss)) if gross_loss and abs(gross_loss) > 0 else (float(gross_profit) if gross_profit else None)

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
        "profit_factor": round(profit_factor, 2) if profit_factor is not None else None,
        "avg_win": round(avg_win, 0),
        "avg_loss": round(avg_loss, 0),
        "session_max_drawdown": round(max_drawdown, 0),
        "session_max_drawdown_pct": round(max_drawdown_pct, 2),
        "recommendations": recommendations,
    }


def _performance_summary_from_trades() -> dict:
    """trade_history 기반 당일 거래만 필터 후 _compute_summary_from_trade_list 호출."""
    tz = timezone(timedelta(hours=9))
    today_str = datetime.now(tz).strftime("%Y-%m-%d")
    today_ymd = today_str
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
                if dt.strftime("%Y-%m-%d") == today_ymd:
                    today_trades.append(t)
            except Exception:
                pass
    return _compute_summary_from_trade_list(today_trades, today_str)


def _today_trades_from_user_hist(current_user: str) -> list:
    """당일 거래를 user_hist에서 로드."""
    if not current_user:
        return []
    try:
        from user_hist_store import get_user_hist_store
        hist = get_user_hist_store()
        if not hist or not getattr(hist, "enabled", False):
            return []
        tz = timezone(timedelta(hours=9))
        today_yyyymmdd = datetime.now(tz).strftime("%Y%m%d")
        rows = hist.get_trades(current_user, today_yyyymmdd, today_yyyymmdd)
        if not rows:
            return []
        today_trades = []
        for r in rows:
            ts = r.get("timestamp")
            if not ts and r.get("date") and r.get("time"):
                d, tm = r["date"], r["time"]
                ts = f"{d[:4]}-{d[4:6]}-{d[6:8]}T{tm[:2]}:{tm[2:4]}:{tm[4:6]}"
            today_trades.append({"timestamp": ts or "", "pnl": r.get("pnl")})
        return today_trades
    except Exception:
        return []


def _get_today_daily_row(current_user: str) -> Optional[dict]:
    """일별 성과 API와 동일한 방식으로 '오늘' 일별 행 1건 반환. (user_result → 보정 → user_hist 집계 순)."""
    if not current_user:
        return None
    tz = timezone(timedelta(hours=9))
    today_yyyymmdd = datetime.now(tz).strftime("%Y%m%d")

    def _get_num(r: dict, *keys: str):
        for k in keys:
            v = r.get(k)
            if v is None:
                continue
            try:
                return float(v)
            except (TypeError, ValueError):
                pass
        return None

    rows = []
    store = _get_user_result_store()
    if store and store.enabled:
        rows = store.query_range(current_user, today_yyyymmdd, today_yyyymmdd)
    if not rows:
        rows = _daily_rows_from_user_hist(current_user, today_yyyymmdd, today_yyyymmdd)
    if not rows:
        return None
    r = rows[0]
    try:
        from decimal import Decimal
        for key in list(r.keys()):
            if isinstance(r[key], Decimal):
                r[key] = float(r[key])
    except Exception:
        pass
    es, ee = _get_num(r, "equity_start", "Equity_Start"), _get_num(r, "equity_end", "Equity_End")
    if es is not None and ee is not None:
        pnl_val = ee - es
        r["pnl"] = round(pnl_val, 0)
        r["return_pct"] = round((pnl_val / es * 100.0), 4) if es and es != 0 else 0.0
    if (r.get("pnl") == 0 or r.get("pnl") is None) and es is not None and ee is not None and es == ee:
        gp, gl = _get_num(r, "gross_profit"), _get_num(r, "gross_loss")
        if gp is not None or gl is not None:
            gross_pnl = (gp or 0) + (gl or 0)
            r["pnl"] = round(gross_pnl, 0)
            r["return_pct"] = round((gross_pnl / es * 100.0), 4) if es and es != 0 else 0.0
    return r


@app.get("/api/performance/summary")
async def get_performance_summary(current_user: str = Depends(get_current_user)):
    """일일·세션 성과 요약. 당일 거래(user_hist/메모리)가 있으면 그걸로 집계, 없을 때만 일별 성과 DB 행 사용."""
    try:
        tz = timezone(timedelta(hours=9))
        today_str = datetime.now(tz).strftime("%Y-%m-%d")
        today_ymd = today_str.replace("-", "")[:8]
        # 1) 당일 거래 리스트 우선 수집 (user_hist + 메모리 trade_history)
        today_trades = _today_trades_from_user_hist(current_user)
        if not today_trades:
            history = getattr(state, "trade_history", []) or []
            for t in history:
                ts = t.get("timestamp") or ""
                if isinstance(ts, str) and (ts.startswith(today_str) or ts.replace("-", "")[:8] == today_ymd):
                    today_trades.append(t)
                elif isinstance(ts, str) and "T" in ts:
                    try:
                        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                        if dt.tzinfo is None:
                            dt = dt.replace(tzinfo=tz)
                        if dt.strftime("%Y-%m-%d") == today_str:
                            today_trades.append(t)
                    except Exception:
                        pass
        # 2) 거래가 있으면 거래 기준으로 집계 (실제 손익 반영, 갱신됨)
        if today_trades:
            summary = _compute_summary_from_trade_list(today_trades, today_str)
            return JSONResponse({"success": True, "summary": summary})
        # 3) 거래 없을 때만 일별 성과 DB 행 사용 (저장된 오늘 행)
        today_row = _get_today_daily_row(current_user)
        if today_row is not None:
            pnl = today_row.get("pnl")
            tc = int(today_row.get("trade_count") or 0)
            wins = int(today_row.get("wins") or 0)
            losses = int(today_row.get("losses") or 0)
            gp = float(today_row.get("gross_profit") or 0)
            gl = float(today_row.get("gross_loss") or 0)
            total_wl = wins + losses
            win_rate = round(wins / total_wl * 100.0, 1) if total_wl else 0.0
            avg_win = round(gp / wins, 0) if wins else 0.0
            avg_loss = round(gl / losses, 0) if losses else 0.0
            pf = (gp / abs(gl)) if gl and abs(gl) > 0 else (float(gp) if gp else None)
            summary = {
                "date": today_str,
                "trade_count": tc,
                "wins": wins,
                "losses": losses,
                "total_pnl": round(float(pnl or 0), 0),
                "win_rate_pct": win_rate,
                "profit_factor": round(pf, 2) if pf is not None else None,
                "avg_win": avg_win,
                "avg_loss": avg_loss,
                "session_max_drawdown": 0,
                "session_max_drawdown_pct": 0.0,
                "recommendations": _compute_summary_from_trade_list([], today_str).get("recommendations", []),
            }
            return JSONResponse({"success": True, "summary": summary})
        # 4) 거래도 없고 DB 행도 없으면 0 요약
        summary = _compute_summary_from_trade_list([], today_str)
        return JSONResponse({"success": True, "summary": summary})
    except Exception as e:
        logger.exception(e)
        return JSONResponse({"success": False, "message": str(e)})


@app.get("/api/performance/store-status")
async def get_performance_store_status(current_user: str = Depends(get_current_user)):
    """일별 성과 저장소(quant_trading_user_result) 상태. 조회 시 사용하는 사용자명·테이블·연동 여부 확인용."""
    store = _get_user_result_store()
    if not store:
        return JSONResponse({
            "enabled": False,
            "message": "성과 저장소 초기화 실패(모듈/환경 확인)",
            "current_user": current_user,
        })
    return JSONResponse({
        "enabled": bool(store.enabled),
        "table_name": getattr(store, "table_name", ""),
        "region": getattr(store, "region", ""),
        "init_error": getattr(store, "init_error", None),
        "current_user": current_user,
        "message": "조회 시 current_user를 DynamoDB 파티션 키(username)로 사용합니다. 테이블에 해당 username으로 저장된 데이터가 있어야 일별 성과에 표시됩니다.",
    })


def _daily_rows_from_user_hist(username: str, date_from: str, date_to: str) -> list:
    """quant_trading_user_hist를 일자별로 집계해 일별 성과 형태의 리스트 반환. (user_result 비었을 때 보강용)"""
    try:
        from user_hist_store import get_user_hist_store
        hist = get_user_hist_store()
        if not hist or not getattr(hist, "enabled", False):
            return []
        all_rows = hist.get_trades(username, date_from, date_to)
        if not all_rows:
            return []
        # 일자별로 그룹화: pnl(매도만), trade_count(매수 건수), wins, losses, gross_profit, gross_loss
        by_date = {}
        for r in all_rows:
            d = (r.get("date") or "").strip()
            if len(d) != 8:
                continue
            if d not in by_date:
                by_date[d] = {"pnls": [], "buys": 0}
            ot = (r.get("order_type") or "").strip().lower()
            if ot == "sell" and r.get("pnl") is not None:
                try:
                    by_date[d]["pnls"].append(float(r["pnl"]))
                except (TypeError, ValueError):
                    pass
            elif ot == "buy":
                by_date[d]["buys"] += 1
        rows = []
        for d in sorted(by_date.keys()):
            pnls = by_date[d]["pnls"]
            buys = by_date[d]["buys"]
            trade_count = buys
            pnl = sum(pnls)
            wins = sum(1 for p in pnls if p > 0)
            losses = sum(1 for p in pnls if p < 0)
            gross_profit = sum(p for p in pnls if p > 0)
            gross_loss = sum(p for p in pnls if p < 0)
            rows.append({
                "date": d,
                "equity_start": 0,
                "equity_end": 0,
                "pnl": round(pnl, 0),
                "return_pct": 0.0,
                "trade_count": trade_count,
                "wins": wins,
                "losses": losses,
                "gross_profit": round(gross_profit, 0),
                "gross_loss": round(gross_loss, 0),
            })
        return rows
    except Exception as e:
        logger.debug("_daily_rows_from_user_hist: %s", e)
        return []


@app.get("/api/performance/daily")
async def get_performance_daily(
    date_from: str = Query(..., description="시작일 YYYYMMDD"),
    date_to: str = Query(..., description="종료일 YYYYMMDD"),
    current_user: str = Depends(get_current_user),
):
    """일별 성과 조회 (quant_trading_user_result). 비었으면 quant_trading_user_hist 기준 일별 집계로 보강."""
    try:
        if len(date_from) != 8 or len(date_to) != 8 or not date_from.isdigit() or not date_to.isdigit():
            return JSONResponse({"success": False, "message": "date_from, date_to는 YYYYMMDD 8자리여야 합니다."})
        if date_from > date_to:
            date_from, date_to = date_to, date_from

        store = _get_user_result_store()
        rows = []
        source = "user_result"
        if store and store.enabled:
            rows = store.query_range(current_user, date_from, date_to)
        if not rows:
            rows = _daily_rows_from_user_hist(current_user, date_from, date_to)
            if rows:
                source = "user_hist"
        # Decimal 등 JSON 비호환 타입 제거 + equity 기준 pnl/return_pct 보정(대시보드 0 표시 방지)
        def _get_num(r: dict, *keys: str):
            for k in keys:
                v = r.get(k)
                if v is None:
                    continue
                try:
                    return float(v)
                except (TypeError, ValueError):
                    pass
            return None

        try:
            from decimal import Decimal
            for r in rows:
                for key in list(r.keys()):
                    v = r[key]
                    if isinstance(v, Decimal):
                        r[key] = float(v)
                es = _get_num(r, "equity_start", "Equity_Start", "EQUITY_START")
                ee = _get_num(r, "equity_end", "Equity_End", "EQUITY_END")
                if es is not None and ee is not None:
                    pnl_val = ee - es
                    r["pnl"] = round(pnl_val, 0)
                    r["return_pct"] = round((pnl_val / es * 100.0), 4) if es and es != 0 else 0.0
                # equity가 동일해 손익 0인 경우: gross_profit + gross_loss 로 실현손익 표시(DB 저장 오류/다른 리전 등 보정)
                if (r.get("pnl") == 0 or r.get("pnl") is None) and (es is not None and ee is not None and es == ee):
                    gp = _get_num(r, "gross_profit")
                    gl = _get_num(r, "gross_loss")
                    if gp is not None or gl is not None:
                        gross_pnl = (gp or 0) + (gl or 0)
                        r["pnl"] = round(gross_pnl, 0)
                        r["return_pct"] = round((gross_pnl / es * 100.0), 4) if es and es != 0 else 0.0
        except Exception:
            pass
        # 최신일자 순 내림차순 정렬
        rows = sorted(rows, key=lambda r: (r.get("date") or ""), reverse=True)
        out = {"success": True, "rows": rows, "queried_user": current_user, "date_from": date_from, "date_to": date_to, "source": source}
        if not rows:
            out["hint"] = f"조회 사용자: {current_user}. 구간: {date_from}~{date_to}. user_result와 user_hist 모두 해당 기간 데이터가 없습니다."
            if not (store and store.enabled):
                out["hint"] = f"일별 성과 저장소(quant_trading_user_result) 미연동. 거래내역(quant_trading_user_hist)에도 해당 기간 데이터가 없습니다. /api/performance/store-status 로 저장소 상태 확인."
        try:
            attempt_parts = [f"{current_user} {date_from}~{date_to} → {len(rows)}건 ({source})"]
            if rows:
                r0 = rows[0]
                # 반환값 샘플(손익 0 원인 확인용): date, pnl, equity_start, equity_end, keys
                sample = (
                    f"date={r0.get('date')} pnl={r0.get('pnl')} return_pct={r0.get('return_pct')} "
                    f"equity_start={r0.get('equity_start')} equity_end={r0.get('equity_end')} "
                    f"gross_profit={r0.get('gross_profit')} gross_loss={r0.get('gross_loss')}"
                )
                attempt_parts.append(sample)
            system_log_append("info", f"일별 성과 조회: {' | '.join(attempt_parts)}")
        except Exception:
            pass
        return JSONResponse(out)
    except Exception as e:
        logger.exception(e)
        try:
            system_log_append("error", f"일별 성과 조회 실패: {current_user} {date_from or '-'}~{date_to or '-'} — {e}")
        except Exception:
            pass
        return JSONResponse({"success": False, "message": str(e)})


@app.get("/api/performance/export")
async def get_performance_export(
    date_from: str = Query(..., description="시작일 YYYYMMDD"),
    date_to: str = Query(..., description="종료일 YYYYMMDD"),
    format: str = Query("csv", description="csv | json"),
    slippage_bps: int = Query(0, ge=0, le=500, description="백테스트 슬리피지(bps)"),
    fee_bps: int = Query(0, ge=0, le=500, description="백테스트 수수료(bps)"),
    fill_assumption: str = Query("signal_price", description="체결가정: signal_price | next_open"),
    apply_limits: bool = Query(True, description="일일 한도 적용 여부(백테스트 시뮬)"),
    current_user: str = Depends(get_current_user),
):
    """일별 성과 내보내기 (백테스트/워크포워드 분석용). CSV 또는 JSON. 슬리피지·수수료·체결가정·한도 적용 옵션 포함."""
    try:
        store = _get_user_result_store()
        if not store or not store.enabled:
            return JSONResponse({
                "success": False,
                "message": "성과 저장소를 사용할 수 없습니다.",
            })
        if len(date_from) != 8 or len(date_to) != 8 or not date_from.isdigit() or not date_to.isdigit():
            return JSONResponse({"success": False, "message": "date_from, date_to는 YYYYMMDD 8자리여야 합니다."})
        if date_from > date_to:
            date_from, date_to = date_to, date_from
        fill_assumption = (fill_assumption or "signal_price").strip().lower()
        if fill_assumption not in ("signal_price", "next_open"):
            fill_assumption = "signal_price"
        rows = store.query_range(current_user, date_from, date_to)
        backtest_params = {
            "slippage_bps": max(0, min(500, int(slippage_bps or 0))),
            "fee_bps": max(0, min(500, int(fee_bps or 0))),
            "fill_assumption": fill_assumption,
            "apply_limits": bool(apply_limits),
            "date_from": date_from,
            "date_to": date_to,
        }
        if (format or "").strip().lower() == "json":
            return JSONResponse({
                "success": True,
                "date_from": date_from,
                "date_to": date_to,
                "backtest_params": backtest_params,
                "rows": rows,
            })
        # CSV: 첫 줄에 백테스트 파라미터 주석
        import io
        import csv
        buf = io.StringIO()
        buf.write("# backtest_params: slippage_bps={}, fee_bps={}, fill_assumption={}, apply_limits={}\n".format(
            backtest_params["slippage_bps"], backtest_params["fee_bps"],
            backtest_params["fill_assumption"], backtest_params["apply_limits"],
        ))
        cols = ["date", "equity_start", "equity_end", "pnl", "return_pct", "trade_count", "wins", "losses", "gross_profit", "gross_loss"]
        w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in cols})
        body = buf.getvalue()
        from fastapi.responses import Response
        return Response(
            content=body.encode("utf-8-sig"),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="performance_{date_from}_{date_to}.csv"'},
        )
    except Exception as e:
        logger.exception(e)
        return JSONResponse({"success": False, "message": str(e)})


def _period_stats_from_daily_rows(rows: list, date_from: str, date_to: str) -> dict:
    """일별 저장 rows로 기간 수익률·기간 최대낙폭 계산."""
    if not rows:
        return {
            "monthly_return_pct": None,
            "period_max_drawdown_pct": None,
            "period_trade_count": 0,
            "period_win_rate_pct": None,
            "period_profit_factor": None,
        }
    rows_sorted = sorted(rows, key=lambda r: r.get("date") or "")
    equity_start_first = None
    for r in rows_sorted:
        es = r.get("equity_start")
        if es is not None:
            try:
                equity_start_first = float(es)
                break
            except Exception:
                pass
    equity_end_last = None
    for r in reversed(rows_sorted):
        ee = r.get("equity_end")
        if ee is not None:
            try:
                equity_end_last = float(ee)
                break
            except Exception:
                pass
    if equity_start_first is None:
        equity_start_first = equity_end_last
    if equity_start_first is None or equity_start_first == 0:
        monthly_return_pct = None
    else:
        end_val = equity_end_last if equity_end_last is not None else equity_start_first
        monthly_return_pct = (end_val - equity_start_first) / equity_start_first * 100.0

    # 기간 최대낙폭: 자산 곡선에서 peak 대비 하락
    peak = None
    max_dd_pct = 0.0
    for r in rows_sorted:
        ee = r.get("equity_end")
        es = r.get("equity_start")
        val = None
        if ee is not None:
            try:
                val = float(ee)
            except Exception:
                pass
        if val is None and es is not None:
            try:
                val = float(es)
            except Exception:
                pass
        if val is not None:
            if peak is None or val > peak:
                peak = val
            if peak and peak > 0:
                dd_pct = (peak - val) / peak * 100.0
                if dd_pct > max_dd_pct:
                    max_dd_pct = dd_pct
    period_trade_count = sum(int(r.get("trade_count") or 0) for r in rows_sorted)
    period_wins = sum(int(r.get("wins") or 0) for r in rows_sorted)
    period_losses = sum(int(r.get("losses") or 0) for r in rows_sorted)
    total_trades_wl = period_wins + period_losses
    period_win_rate_pct = round(period_wins / total_trades_wl * 100.0, 1) if total_trades_wl else None
    period_gross_profit = sum(float(r.get("gross_profit") or 0) for r in rows_sorted)
    period_gross_loss = sum(float(r.get("gross_loss") or 0) for r in rows_sorted)
    if period_gross_loss and abs(period_gross_loss) > 0:
        period_profit_factor = round(period_gross_profit / abs(period_gross_loss), 2)
    elif period_gross_profit and period_gross_profit > 0:
        period_profit_factor = None  # 무한대에 가까움, 프론트에서 "∞" 등 표기
    else:
        period_profit_factor = None

    return {
        "monthly_return_pct": round(monthly_return_pct, 2) if monthly_return_pct is not None else None,
        "period_max_drawdown_pct": round(max_dd_pct, 2) if max_dd_pct else None,
        "period_trade_count": period_trade_count,
        "period_win_rate_pct": period_win_rate_pct,
        "period_profit_factor": period_profit_factor,
        "date_from": date_from,
        "date_to": date_to,
    }


@app.get("/api/performance/period-stats")
async def get_performance_period_stats(
    months: int = Query(1, ge=1, le=24, description="기간(월 수)"),
    current_user: str = Depends(get_current_user),
):
    """기간 성과: 월간 수익률·기간 최대낙폭 (일별 저장 또는 user_hist 집계 기준)."""
    try:
        tz = timezone(timedelta(hours=9))
        end_dt = datetime.now(tz)
        start_dt = end_dt - timedelta(days=months * 31)
        date_from = start_dt.strftime("%Y%m%d")
        date_to = end_dt.strftime("%Y%m%d")
        rows = []
        store = _get_user_result_store()
        if store and store.enabled:
            rows = store.query_range(current_user, date_from, date_to)
        if not rows:
            rows = _daily_rows_from_user_hist(current_user, date_from, date_to)
        stats = _period_stats_from_daily_rows(rows, date_from, date_to)
        return JSONResponse({"success": True, "period_stats": stats})
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
        selected_stocks_count=len(getattr(state, "selected_stocks", None) or []),
    )
    filled = bool(details.get("filled", False))
    await state.broadcast({"type": "log", "message": _format_order_log(details), "level": "info" if (result and filled) else ("warning" if result else "error")})
    if not result:
        sc = str(signal_data.get("stock_code") or "").strip().zfill(6)
        if details.get("rejection_reason") == "vi" and sc:
            vi_cooling = max(1, min(30, int(getattr(state, "vi_cooling_minutes", 5) or 5)))
            vi_skip = getattr(state, "_vi_skip_until", None) or {}
            if not isinstance(vi_skip, dict):
                vi_skip = {}
            state._vi_skip_until = {**vi_skip, sc: time.time() + vi_cooling * 60}
            await state.broadcast({"type": "log", "level": "warning", "message": f"주문 거절(VI): {sc} → {vi_cooling}분간 해당 종목 매수 스킵"})
        if details.get("error_type") == "auth_expired":
            await state.broadcast({"type": "log", "level": "error", "message": "토큰 만료 가능성. 재로그인 후 이용하세요."})
            try:
                send_alert("error", "토큰 만료 가능성. 재로그인 후 이용하세요.", title="인증 만료")
            except Exception:
                pass
    try:
        audit_log(current_user, "signal_approve", {"signal_id": signal_id, "stock_code": signal_data.get("stock_code"), "result": result, "filled": filled})
    except Exception:
        pass
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
            "pnl": None,
            "reason": signal_data.get("reason") or "승인체결",
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

    try:
        audit_log(current_user, "signal_reject", {"signal_id": signal_id})
    except Exception:
        pass
    await state.broadcast({"type": "signal_resolved", "data": {"signal_id": signal_id, "status": "rejected"}})
    return JSONResponse({"success": True, "message": "신호를 거절했습니다."})

@app.get("/api/audit")
async def get_audit_log(
    from_ts: Optional[str] = Query(None, description="시작 시각 ISO"),
    to_ts: Optional[str] = Query(None, description="종료 시각 ISO"),
    limit: int = Query(200, ge=1, le=500),
    current_user: str = Depends(get_current_user),
):
    """감사 로그 조회 (설정 저장, 수동 주문, 신호 승인/거절)."""
    try:
        entries = audit_get(from_ts=from_ts, to_ts=to_ts, limit=limit)
        return JSONResponse({"success": True, "entries": entries})
    except Exception as e:
        logger.exception(e)
        return JSONResponse({"success": False, "message": str(e)})


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
            state.risk_manager.order_retry_exponential_backoff = bool(getattr(config, "order_retry_exponential_backoff", True))
            state.risk_manager.order_retry_base_delay_ms = max(200, min(10000, int(getattr(config, "order_retry_base_delay_ms", 1000) or 1000)))
            state.risk_manager.order_fallback_to_market = bool(getattr(config, "order_fallback_to_market", True))
        except Exception:
            state.risk_manager.order_retry_count = 0
            state.risk_manager.order_retry_delay_ms = 300
            state.risk_manager.order_retry_exponential_backoff = True
            state.risk_manager.order_retry_base_delay_ms = 1000
            state.risk_manager.order_fallback_to_market = True
        try:
            state.risk_manager.daily_loss_limit_calendar = bool(getattr(config, "daily_loss_limit_calendar", True))
            state.risk_manager.daily_profit_limit_calendar = bool(getattr(config, "daily_profit_limit_calendar", True))
            state.risk_manager.monthly_loss_limit = max(0, int(getattr(config, "monthly_loss_limit", 0) or 0))
            state.risk_manager.cumulative_loss_limit = max(0, int(getattr(config, "cumulative_loss_limit", 0) or 0))
        except Exception:
            state.risk_manager.daily_loss_limit_calendar = True
            state.risk_manager.daily_profit_limit_calendar = True
            state.risk_manager.monthly_loss_limit = 0
            state.risk_manager.cumulative_loss_limit = 0
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
            state.risk_manager.max_intraday_vol_pct = 0.0
        try:
            state.risk_manager.max_intraday_vol_pct = max(0.0, min(20.0, float(getattr(config, "max_intraday_vol_pct", 0) or 0)))
        except Exception:
            state.risk_manager.max_intraday_vol_pct = 0.0
        try:
            state.risk_manager.atr_filter_enabled = bool(getattr(config, "atr_filter_enabled", False))
            state.risk_manager.atr_period = max(2, min(30, int(getattr(config, "atr_period", 14) or 14)))
            state.risk_manager.atr_ratio_max_pct = max(0.0, min(20.0, float(getattr(config, "atr_ratio_max_pct", 0) or 0)))
            state.risk_manager.sap_deviation_filter_enabled = bool(getattr(config, "sap_deviation_filter_enabled", False))
            state.risk_manager.sap_deviation_max_pct = max(0.1, min(20.0, float(getattr(config, "sap_deviation_max_pct", 3.0) or 3.0)))
        except Exception:
            state.risk_manager.atr_filter_enabled = False
            state.risk_manager.atr_ratio_max_pct = 0.0
            state.risk_manager.sap_deviation_filter_enabled = False
            state.risk_manager.sap_deviation_max_pct = 3.0
        state.risk_manager.max_trades_per_day = config.max_trades_per_day
        state.risk_manager.max_trades_per_stock_per_day = max(0, min(20, int(getattr(config, "max_trades_per_stock_per_day", 0) or 0)))
        state.risk_manager.max_position_size_ratio = config.max_position_size_ratio
        state.risk_manager.max_positions_count = max(0, min(50, int(getattr(config, "max_positions_count", 0) or 0)))
        state.risk_manager.expand_position_when_few_stocks = bool(getattr(config, "expand_position_when_few_stocks", True))
        state.risk_manager.trailing_stop_ratio = getattr(config, "trailing_stop_ratio", 0.0) or 0.0
        state.risk_manager.trailing_activation_ratio = getattr(config, "trailing_activation_ratio", 0.0) or 0.0
        state.risk_manager.partial_take_profit_ratio = getattr(config, "partial_take_profit_ratio", 0.0) or 0.0
        state.risk_manager.partial_take_profit_fraction = getattr(config, "partial_take_profit_fraction", 0.5) or 0.5
        state.risk_manager.min_price_change_ratio = max(0.0, min(0.10, float(getattr(config, "min_price_change_ratio", 0) or 0)))
        try:
            state.risk_manager.use_atr_for_stop_take = bool(getattr(config, "use_atr_for_stop_take", False))
            state.risk_manager.atr_stop_mult = max(0.5, min(5.0, float(getattr(config, "atr_stop_mult", 1.5) or 1.5)))
            state.risk_manager.atr_take_mult = max(0.5, min(10.0, float(getattr(config, "atr_take_mult", 2.0) or 2.0)))
            state.risk_manager.atr_lookback_ticks = max(2, min(300, int(getattr(config, "atr_lookback_ticks", 20) or 20)))
        except Exception:
            state.risk_manager.use_atr_for_stop_take = False
            state.risk_manager.atr_stop_mult = 1.5
            state.risk_manager.atr_take_mult = 2.0
            state.risk_manager.atr_lookback_ticks = 20

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
        try:
            audit_log(current_user, "config_save", {"section": "risk"})
        except Exception:
            pass
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

        _apply_strategy_config_to_state(config)

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
        try:
            audit_log(current_user, "config_save", {"section": "strategy"})
        except Exception:
            pass
        await state.broadcast({
            "type": "log",
            "message": (
                f"전략 설정 업데이트: short={short_period}, long={long_period}, "
                f"buy_window={getattr(state, 'buy_window_start_hhmm', '09:05')}-{getattr(state, 'buy_window_end_hhmm', '11:30')}, "
                f"slope>={state.min_short_ma_slope_ratio*100:.3f}%/tick, "
                f"momentum>={getattr(state,'min_momentum_ratio',0.0)*100:.2f}%/N{int(getattr(state,'momentum_lookback_ticks',0) or 0)}, "
                f"entryConfirm={'on' if getattr(state,'entry_confirm_enabled',False) else 'off'}(min={int(getattr(state,'entry_confirm_min_count',1) or 1)}), "
                f"volNorm=N{int(getattr(state,'vol_norm_lookback_ticks',20) or 20)} slopeMult={float(getattr(state,'slope_vs_vol_mult',0.0) or 0.0):.2f} rangeMult={float(getattr(state,'range_vs_vol_mult',0.0) or 0.0):.2f}, "
                f"regimeSplit={'on' if getattr(state,'enable_morning_regime_split',False) else 'off'}@{getattr(state,'morning_regime_early_end_hhmm','09:10')}, "
                f"cooldown={state.reentry_cooldown_seconds}s, "
                f"confirm={int(state.buy_confirm_ticks)}tick, "
                f"time_liq={'on' if state.enable_time_liquidation else 'off'}@{state.liquidate_after_hhmm}, "
                f"spread<={state.max_spread_ratio*100:.3f}%, "
                f"range>={state.min_range_ratio*100:.3f}%/N{state.range_lookback_ticks}, "
                f"sapRevert={'on' if getattr(state,'use_sap_revert_entry',False) else 'off'}({getattr(state,'sap_revert_entry_from_pct',0.0):.3f}%~{getattr(state,'sap_revert_entry_to_pct',0.0):.3f}%)"
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
            max_drawdown_from_high_ratio=float(getattr(config, "max_drawdown_from_high_ratio", 0.12) or 0.12),
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
        try:
            audit_log(current_user, "config_save", {"section": "stock_selection"})
        except Exception:
            pass

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
        state.ws_reconnect_sleep_sec = max(3, min(60, int(getattr(config, "ws_reconnect_sleep_sec", 5) or 5)))
        state.emergency_liquidate_disconnect_minutes = max(0, min(120, int(getattr(config, "emergency_liquidate_disconnect_minutes", 0) or 0)))
        state.keep_previous_on_empty_selection = bool(getattr(config, "keep_previous_on_empty_selection", True))
        state.auto_schedule_enabled = bool(getattr(config, "auto_schedule_enabled", False))
        state.auto_start_hhmm = str(getattr(config, "auto_start_hhmm", "09:30") or "09:30").strip()[:5]
        state.auto_stop_hhmm = str(getattr(config, "auto_stop_hhmm", "12:00") or "12:00").strip()[:5]
        state.liquidate_on_auto_stop = bool(getattr(config, "liquidate_on_auto_stop", True))
        state.auto_schedule_username = str(getattr(config, "auto_schedule_username", "") or "").strip()
        store = _get_user_settings_store()
        persisted = False
        if store and getattr(store, "enabled", False):
            persisted = bool(store.save(current_user, operational_config=config.model_dump()))
        try:
            audit_log(current_user, "config_save", {"section": "operational"})
        except Exception:
            pass
        await state.broadcast({"type": "log", "message": "운영 옵션이 업데이트되었습니다.", "level": "info"})
        return JSONResponse({"success": True, "persisted": persisted})
    except Exception as e:
        logger.error(f"운영 옵션 업데이트 오류: {e}")
        return JSONResponse({"success": False, "message": str(e)})


def _normalize_strategy_config_for_json(sc: dict) -> dict:
    """strategy_config 내 short_ma_period/long_ma_period 보장 및 Decimal 등 JSON 비호환 타입 정규화."""
    if not sc or not isinstance(sc, dict):
        return sc or {}
    out = dict(sc)
    # 단기/장기 이동평균이 없거나 None이면 state 또는 기본값으로 채움 (DB 저장값이 폼에 반영되도록)
    default_short = 3
    default_long = 10
    if getattr(state, "strategy", None):
        default_short = getattr(state.strategy, "short_ma_period", 3)
        default_long = getattr(state.strategy, "long_ma_period", 10)
    if out.get("short_ma_period") is None:
        out["short_ma_period"] = default_short
    if out.get("long_ma_period") is None:
        out["long_ma_period"] = default_long
    # Decimal -> int/float 변환 (다른 저장소 경로에서 Map으로 읽은 경우 대비)
    from decimal import Decimal
    for k, v in list(out.items()):
        if isinstance(v, Decimal):
            out[k] = int(v) if v % 1 == 0 else float(v)
    return out


@app.get("/api/config/user-settings")
async def get_user_settings(current_user: str = Depends(get_current_user)):
    """로그인 사용자별 저장된 설정값 조회. 조회한 값은 백엔드 state에도 반영해 DB·화면·실행값이 일치하도록 함."""
    store = _get_user_settings_store()
    if not store or not getattr(store, "enabled", False):
        return JSONResponse({"success": False, "message": "DynamoDB 설정 저장소를 사용할 수 없습니다."})
    settings = store.load(current_user) or {}
    # strategy_config에 short_ma_period/long_ma_period가 항상 포함되도록 정규화 (전략 폼 DB 반영)
    sc = settings.get("strategy_config")
    if isinstance(sc, dict):
        settings = {**settings, "strategy_config": _normalize_strategy_config_for_json(sc)}
    # DB에서 불러온 설정을 state에 반영 → 리스크 관리 등 화면값과 실제 적용값·DB가 같아짐
    _apply_risk_config_dict_to_state(settings.get("risk_config"))
    _apply_operational_config_dict_to_state(settings.get("operational_config"))
    _apply_strategy_config_dict_to_state(settings.get("strategy_config"))
    if settings.get("stock_selection_config"):
        try:
            _apply_stock_selection_config_dict_to_state(settings.get("stock_selection_config"))
        except Exception:
            pass
    return JSONResponse({"success": True, "settings": settings, "loaded_for_username": current_user})


@app.post("/api/config/custom-slots/save")
async def save_custom_slot(
    current_user: str = Depends(get_current_user),
    body: dict = Body(..., embed=False),
):
    """커스텀 슬롯(1~10) 하나에 현재 설정 저장. slot_id, name, risk_config, strategy_config, stock_selection_config, operational_config."""
    store = _get_user_settings_store()
    if not store or not getattr(store, "enabled", False):
        return JSONResponse({"success": False, "message": "DynamoDB 설정 저장소를 사용할 수 없습니다."})
    try:
        slot_id = max(1, min(getattr(store, "NUM_CUSTOM_SLOTS", 10), int(body.get("slot_id", 1))))
        name = (str(body.get("name") or "").strip()) or f"Custom {slot_id}"
        risk_config = body.get("risk_config") if isinstance(body.get("risk_config"), dict) else None
        strategy_config = body.get("strategy_config") if isinstance(body.get("strategy_config"), dict) else None
        stock_selection_config = body.get("stock_selection_config") if isinstance(body.get("stock_selection_config"), dict) else None
        operational_config = body.get("operational_config") if isinstance(body.get("operational_config"), dict) else None
        # 요청에 설정이 없으면 DB에 저장된 현재 메인 설정을 슬롯에 복사 (프론트에서 먼저 각 탭 저장 후 호출하는 경우)
        if not any((risk_config, strategy_config, stock_selection_config, operational_config)):
            loaded = store.load(current_user) or {}
            risk_config = loaded.get("risk_config")
            strategy_config = loaded.get("strategy_config")
            stock_selection_config = loaded.get("stock_selection_config")
            operational_config = loaded.get("operational_config")
        if not any((risk_config, strategy_config, stock_selection_config, operational_config)):
            return JSONResponse({"success": False, "message": "저장할 설정이 없습니다. 리스크/전략/종목선정/운영 탭에서 먼저 저장한 뒤 슬롯 저장을 하거나, 폼 값을 그대로 슬롯에 저장하려면 저장하기를 사용하세요."})
        ok = store.save_custom_slot(
            current_user,
            slot_id=slot_id,
            name=name,
            risk_config=risk_config,
            strategy_config=strategy_config,
            stock_selection_config=stock_selection_config,
            operational_config=operational_config,
        )
        if not ok:
            return JSONResponse({"success": False, "message": "커스텀 슬롯 저장 실패."})
        # state에 반영 (저장한 슬롯 = 현재 적용값)
        if risk_config:
            _apply_risk_config_dict_to_state(risk_config)
        if operational_config:
            _apply_operational_config_dict_to_state(operational_config)
        if strategy_config:
            _apply_strategy_config_dict_to_state(strategy_config)
        if stock_selection_config and getattr(state, "stock_selector", None):
            try:
                _apply_stock_selection_config_dict_to_state(stock_selection_config)
            except Exception:
                pass
        try:
            audit_log(current_user, "config_save", {"section": "custom_slot", "slot_id": slot_id})
        except Exception:
            pass
        return JSONResponse({
            "success": True,
            "message": f"커스텀 슬롯 {slot_id}({name})에 저장했습니다.",
            "slot_id": slot_id,
            "name": name,
        })
    except Exception as e:
        logger.exception("Custom slot save error")
        return JSONResponse({"success": False, "message": str(e)})


@app.post("/api/config/custom-slots/load")
async def load_custom_slot_to_main(
    current_user: str = Depends(get_current_user),
    body: dict = Body(..., embed=False),
):
    """커스텀 슬롯(1~5) 내용을 메인 설정으로 불러오기. slot_id 필수."""
    store = _get_user_settings_store()
    if not store or not getattr(store, "enabled", False):
        return JSONResponse({"success": False, "message": "DynamoDB 설정 저장소를 사용할 수 없습니다."})
    try:
        slot_id = max(1, min(5, int(body.get("slot_id", 1))))
        loaded = store.load(current_user) or {}
        slots = loaded.get("custom_slots") or {}
        slot = slots.get(str(slot_id)) if isinstance(slots.get(str(slot_id)), dict) else None
        if not slot or not any((slot.get("risk_config"), slot.get("strategy_config"), slot.get("stock_selection_config"), slot.get("operational_config"))):
            return JSONResponse({"success": False, "message": f"슬롯 {slot_id}에 저장된 설정이 없습니다."})
        r = slot.get("risk_config")
        s = slot.get("strategy_config")
        st = slot.get("stock_selection_config")
        o = slot.get("operational_config")
        ok = store.save(current_user, risk_config=r, strategy_config=s, stock_selection_config=st, operational_config=o)
        if not ok:
            return JSONResponse({"success": False, "message": "메인 설정 저장 실패."})
        if r:
            _apply_risk_config_dict_to_state(r)
        if o:
            _apply_operational_config_dict_to_state(o)
        if s:
            _apply_strategy_config_dict_to_state(s)
        if st and getattr(state, "stock_selector", None):
            try:
                _apply_stock_selection_config_dict_to_state(st)
            except Exception:
                pass
        return JSONResponse({"success": True, "message": f"커스텀 슬롯 {slot_id}을(를) 메인 설정으로 불러왔습니다.", "slot_id": slot_id})
    except Exception as e:
        logger.exception("Custom slot load error")
        return JSONResponse({"success": False, "message": str(e)})


@app.get("/api/profile")
async def get_profile(current_user: str = Depends(get_current_user)):
    """현재 사용자 프로필 조회 (quant_trading_users, password_hash 제외)."""
    profile = auth_manager.get_user_profile(current_user)
    if profile is None:
        return JSONResponse({"success": False, "message": "사용자를 찾을 수 없습니다."}, status_code=404)
    return JSONResponse({"success": True, "profile": profile})


@app.put("/api/profile")
async def update_profile(
    current_user: str = Depends(get_current_user),
    body: dict = Body(..., embed=False),
):
    """현재 사용자 프로필 수정 (실전/모의 계좌, KIS app key/secret, AWS 키 등)."""
    try:
        ok = auth_manager.update_user_profile(current_user, **body)
        if not ok:
            return JSONResponse({"success": False, "message": "프로필 업데이트에 실패했습니다."})
        try:
            audit_log(current_user, "profile_update", {"keys": list(body.keys())})
        except Exception:
            pass
        return JSONResponse({"success": True, "message": "프로필이 저장되었습니다."})
    except Exception as e:
        logger.exception("프로필 업데이트 오류")
        return JSONResponse({"success": False, "message": str(e)})


@app.post("/api/stocks/select")
async def select_stocks(current_user: str = Depends(get_current_user)):
    """종목 재선정. 실행 중에는 변경 불가(중지 → 재선정 → 재시작으로 통일)."""
    try:
        if getattr(state, "is_running", False):
            msg = "실행 중에는 종목을 재선정할 수 없습니다. 시스템을 중지 → 종목 재선정 → 시스템 시작 순서로 진행하세요."
            try:
                await state.broadcast({"type": "log", "level": "warning", "message": msg})
            except Exception:
                pass
            return JSONResponse({"success": False, "message": msg})

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
            keep_prev = bool(getattr(state, "keep_previous_on_empty_selection", True))
            if keep_prev and getattr(state, "selected_stocks", None):
                await state.broadcast({
                    "type": "log",
                    "message": "종목 선정 결과 없음. 이전 목록 유지.",
                    "level": "warning"
                })
                return JSONResponse({
                    "success": True,
                    "message": "선정 결과 없음(이전 목록 유지)",
                    "stocks": state.selected_stocks,
                    "stock_info": getattr(state, "selected_stock_info", []),
                    "kept_previous": True,
                })
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
        try:
            audit_log(current_user, "stock_selection", {
                "count": len(selected),
                "stocks": selected,
                "criteria": {
                    "min_price_change_ratio": getattr(state.stock_selector, "min_price_change_ratio", None),
                    "max_price_change_ratio": getattr(state.stock_selector, "max_price_change_ratio", None),
                    "max_stocks": getattr(state.stock_selector, "max_stocks", None),
                }
            })
        except Exception:
            pass
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
            selected_stocks_count=len(getattr(state, "selected_stocks", None) or []),
        )
        filled = bool(details.get("filled", False))
        await state.broadcast({"type": "log", "message": _format_order_log(details), "level": "info" if (result and filled) else ("warning" if result else "error")})
        if not result:
            sc = str(order.stock_code or "").strip().zfill(6)
            if details.get("rejection_reason") == "vi" and sc:
                vi_cooling = max(1, min(30, int(getattr(state, "vi_cooling_minutes", 5) or 5)))
                vi_skip = getattr(state, "_vi_skip_until", None) or {}
                if not isinstance(vi_skip, dict):
                    vi_skip = {}
                state._vi_skip_until = {**vi_skip, sc: time.time() + vi_cooling * 60}
                await state.broadcast({"type": "log", "level": "warning", "message": f"주문 거절(VI): {sc} → {vi_cooling}분간 해당 종목 매수 스킵"})
            if details.get("error_type") == "auth_expired":
                await state.broadcast({"type": "log", "level": "error", "message": "토큰 만료 가능성. 재로그인 후 이용하세요."})
                try:
                    send_alert("error", "토큰 만료 가능성. 재로그인 후 이용하세요.", title="인증 만료")
                except Exception:
                    pass
        try:
            audit_log(current_user, "manual_order", {"stock_code": order.stock_code, "order_type": order.order_type, "quantity": order.quantity, "result": result, "filled": filled})
        except Exception:
            pass
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
                "pnl": None,
                "reason": "수동주문",
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
            max_drawdown_from_high_ratio=0.12,
            drawdown_filter_after_hhmm="12:00",
            kospi_only=False,
        )
        
        state.risk_manager = risk_manager
        state.strategy = strategy
        state.trenv = trenv
        # 동시 보유 종목 수로 매수 거절 직전에 체결 확인 1회 실행(접수대기→체결 반영 지연 보정)
        try:
            state.risk_manager.on_before_max_positions_reject = lambda: _reconcile_pending_orders_sync(10, 0.0)
        except Exception:
            pass
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
