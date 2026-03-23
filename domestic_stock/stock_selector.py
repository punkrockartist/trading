"""
자동 종목 선정 클래스

등락률 순위 API를 사용하여 종목을 자동으로 선정합니다.
"""

import sys
import logging
import threading
from typing import Dict, List, Optional

import os
sys.path.extend(['..', '.'])
from domestic_stock_functions import fluctuation
import kis_auth as ka
import pandas as pd
from datetime import datetime, time as dtime, timedelta, timezone

_KIS_ENV_LOCK = threading.Lock()

# ============================================================================
# 자동 종목 선정 클래스
# ============================================================================

class StockSelector:
    """자동 종목 선정 클래스"""
    
    def __init__(
        self,
        env_dv: str = "demo",
        min_price_change_ratio: float = 0.01,  # 최소 1% 상승
        max_price_change_ratio: float = 0.15,  # 최대 15% 상승 (상한가 제외)
        min_price: int = 1000,  # 최소 가격 (1,000원)
        max_price: int = 100000,  # 최대 가격 (10만원)
        min_volume: int = 100000,  # 최소 거래량 (10만주)
        min_trade_amount: int = 0,  # 최소 거래대금 (0 = 사용 안 함)
        max_stocks: int = 10,  # 최대 선정 종목 수
        exclude_risk_stocks: bool = True,  # 위험/경고/주의 종목 제외
        sort_by: str = "change",
        prev_day_rank_pool_size: int = 80,
        market_open_hhmm: Optional[str] = None,
        warmup_minutes: Optional[int] = None,
        early_strict: Optional[bool] = None,
        early_strict_minutes: Optional[int] = None,
        early_min_volume: Optional[int] = None,
        early_min_trade_amount: Optional[int] = None,
        exclude_drawdown: Optional[bool] = None,
        max_drawdown_from_high_ratio: Optional[float] = None,
        drawdown_filter_after_hhmm: Optional[str] = None,
        kospi_only: bool = False,  # True: 코스피만(거래소), False: 전체(코스피+코스닥)
    ):
        """
        Args:
            env_dv: 환경 구분 ("demo" or "real")
            min_price_change_ratio: 최소 상승률 (0.01 = 1%)
            max_price_change_ratio: 최대 상승률 (0.15 = 15%)
            min_price: 최소 가격
            max_price: 최대 가격
            min_volume: 최소 거래량
            min_trade_amount: 최소 거래대금 (0 = 사용 안 함)
            max_stocks: 최대 선정 종목 수
            exclude_risk_stocks: 위험 종목 제외 여부
        """
        self.env_dv = env_dv
        self.min_price_change_ratio = min_price_change_ratio
        self.max_price_change_ratio = max_price_change_ratio
        self.min_price = min_price
        self.max_price = max_price
        self.min_volume = min_volume
        self.min_trade_amount = min_trade_amount
        self.max_stocks = max_stocks
        self.exclude_risk_stocks = exclude_risk_stocks
        self.sort_by = (sort_by or "change").strip()
        try:
            self.prev_day_rank_pool_size = int(prev_day_rank_pool_size or 80)
        except Exception:
            self.prev_day_rank_pool_size = 80
        self.prev_day_rank_pool_size = max(10, min(200, int(self.prev_day_rank_pool_size)))

        # 기존 환경변수 기반 옵션들을 UI/저장값으로도 제어할 수 있게 확장.
        self.market_open_hhmm = (market_open_hhmm or os.getenv("MARKET_OPEN_HHMM", "09:00")).strip()
        self.warmup_minutes = int(warmup_minutes) if warmup_minutes is not None else int(os.getenv("STOCK_SELECTION_WARMUP_MINUTES", "5") or "5")

        if early_strict is None:
            self.early_strict = str(os.getenv("STOCK_SELECTION_EARLY_STRICT", "false")).strip().lower() in {
                "1", "true", "t", "yes", "y", "on"
            }
        else:
            self.early_strict = bool(early_strict)
        self.early_strict_minutes = int(early_strict_minutes) if early_strict_minutes is not None else int(os.getenv("STOCK_SELECTION_EARLY_STRICT_MINUTES", "30") or "30")
        self.early_min_volume = int(early_min_volume) if early_min_volume is not None else int(os.getenv("STOCK_SELECTION_EARLY_MIN_VOLUME", "200000") or "200000")
        self.early_min_trade_amount = int(early_min_trade_amount) if early_min_trade_amount is not None else int(os.getenv("STOCK_SELECTION_EARLY_MIN_TRADE_AMOUNT", "0") or "0")

        if exclude_drawdown is None:
            self.exclude_drawdown = str(os.getenv("STOCK_SELECTION_EXCLUDE_DRAWDOWN", "false")).strip().lower() in {
                "1", "true", "t", "yes", "y", "on"
            }
        else:
            self.exclude_drawdown = bool(exclude_drawdown)
        self.max_drawdown_from_high_ratio = float(max_drawdown_from_high_ratio) if max_drawdown_from_high_ratio is not None else float(os.getenv("STOCK_SELECTION_MAX_DRAWDOWN_FROM_HIGH_RATIO", "0.12") or "0.12")
        self.drawdown_filter_after_hhmm = (drawdown_filter_after_hhmm or os.getenv("STOCK_SELECTION_DRAWDOWN_FILTER_AFTER_HHMM", "12:00")).strip()
        # fid_input_iscd: 0000=전체, 0001=거래소(코스피), 1001=코스닥, 2001=코스피200
        self.kospi_only = bool(kospi_only) if kospi_only is not None else (str(os.getenv("STOCK_SELECTION_KOSPI_ONLY", "false")).strip().lower() in ("1", "true", "t", "yes", "y", "on"))
        self.last_selected_stock_info: List[Dict[str, str]] = []
        self.last_error_message: str = ""
        self.last_debug: Dict[str, int] = {}
        # 폴백(넓게 가져오기) 경로에서 "전일 거래대금 상위" 정렬을 위해 캐시 사용
        self._prev_day_trade_value_cache: Dict[str, float] = {}
    
    def select_stocks_by_fluctuation(self) -> List[str]:
        """
        등락률 순위 API를 사용하여 종목 선정
        
        Returns:
            선정된 종목코드 리스트
        """
        try:
            self.last_error_message = ""
            self.last_debug = {}

            def _find_col(df_: pd.DataFrame, *candidates: str) -> str:
                cols = list(df_.columns)
                lower_map = {str(c).lower(): c for c in cols}
                for cand in candidates:
                    key = str(cand).lower()
                    if key in lower_map:
                        return lower_map[key]
                return ""

            def _parse_hhmm(text: str) -> Optional[dtime]:
                try:
                    t = str(text or "").strip()
                    if not t:
                        return None
                    hh, mm = t.split(":")
                    return dtime(hour=int(hh), minute=int(mm))
                except Exception:
                    return None

            def _get_prev_day_trade_value(code: str) -> float:
                """
                전일 거래대금(가능하면 API 제공값, 없으면 거래량*종가) 추정치.
                - 비용이 크므로 폴백 경로에서만 제한적으로 사용
                """
                try:
                    c = str(code or "").strip().zfill(6)
                    if not c:
                        return 0.0

                    tz = timezone(timedelta(hours=9))
                    today = datetime.now(tz).strftime("%Y%m%d")
                    cache_key = f"{today}:{c}"
                    if cache_key in self._prev_day_trade_value_cache:
                        return float(self._prev_day_trade_value_cache.get(cache_key) or 0.0)

                    api_url2 = "/uapi/domestic-stock/v1/quotations/inquire-daily-price"
                    tr_id2 = "FHKST01010400"
                    params2 = {
                        "FID_COND_MRKT_DIV_CODE": "J",
                        "FID_INPUT_ISCD": c,
                        "FID_PERIOD_DIV_CODE": "D",
                        "FID_ORG_ADJ_PRC": "1",
                    }
                    res2 = ka._url_fetch(api_url2, tr_id2, "", params2)
                    try:
                        if not bool(res2.isOK()):
                            self._prev_day_trade_value_cache[cache_key] = 0.0
                            return 0.0
                    except Exception:
                        self._prev_day_trade_value_cache[cache_key] = 0.0
                        return 0.0

                    body2 = res2.getBody()
                    out2 = None
                    for k2 in ("output", "output1", "output2", "output3"):
                        try:
                            v2 = getattr(body2, k2, None)
                            if v2 is not None:
                                out2 = v2
                                break
                        except Exception:
                            continue
                    if not isinstance(out2, (list, tuple)) or len(out2) == 0:
                        self._prev_day_trade_value_cache[cache_key] = 0.0
                        return 0.0

                    dfd = pd.DataFrame(out2)
                    if dfd.empty:
                        self._prev_day_trade_value_cache[cache_key] = 0.0
                        return 0.0

                    dt_col = _find_col(dfd, "STCK_BSOP_DATE", "stck_bsop_date", "BAS_DT", "bas_dt")
                    tv_col = _find_col(dfd, "ACML_TR_PBMN", "acml_tr_pbmn")
                    vol_col = _find_col(dfd, "ACML_VOL", "acml_vol")
                    close_col = _find_col(
                        dfd,
                        "STCK_CLPR",
                        "stck_clpr",
                        "STCK_PRPR",
                        "stck_prpr",
                        "BSPR",
                        "bspr",
                    )

                    # 전일(=오늘 날짜보다 작은 가장 최근 거래일) 찾기
                    pick = None
                    if dt_col:
                        try:
                            dfd["_dt"] = dfd[dt_col].astype(str).str.strip()
                            dfd["_dt_int"] = pd.to_numeric(dfd["_dt"], errors="coerce")
                            dfd2 = dfd.dropna(subset=["_dt_int"]).copy()
                            dfd2["_dt_int"] = dfd2["_dt_int"].astype(int)
                            today_int = int(today)
                            dfd2 = dfd2[dfd2["_dt_int"] < today_int]
                            if not dfd2.empty:
                                pick = dfd2.sort_values(by="_dt_int", ascending=False).iloc[0]
                        except Exception:
                            pick = None
                    if pick is None:
                        pick = dfd.iloc[0]

                    val = 0.0
                    if tv_col:
                        try:
                            val = float(pick.get(tv_col) or 0.0)
                        except Exception:
                            val = 0.0
                    if (not val or val <= 0) and vol_col and close_col:
                        try:
                            val = float(pick.get(vol_col) or 0.0) * float(pick.get(close_col) or 0.0)
                        except Exception:
                            val = 0.0

                    self._prev_day_trade_value_cache[cache_key] = float(val or 0.0)
                    return float(val or 0.0)
                except Exception:
                    return 0.0

            # 장초 워밍업: 09:00 이후 일정 시간 동안은 종목선정을 막아 장초 노이즈를 피한다.
            # - 기본: 5분
            # - UI 설정값(없으면 env 기본값)
            try:
                tz = timezone(timedelta(hours=9))
                now = datetime.now(tz)
                hh, mm = self.market_open_hhmm.split(":")
                market_open = datetime.combine(now.date(), dtime(hour=int(hh), minute=int(mm)), tzinfo=tz)
                warmup_end = market_open + timedelta(minutes=int(self.warmup_minutes))
                if market_open <= now < warmup_end:
                    remain = int((warmup_end - now).total_seconds() // 60) + 1
                    self.last_error_message = f"장 시작 직후 워밍업 중입니다. 약 {remain}분 후 다시 시도하세요."
                    self.last_debug["blocked_warmup"] = 1
                    return []
            except Exception:
                # 워밍업 계산 실패 시에는 선정 로직 계속 진행
                pass

            # 장초 강화 옵션(선택): 워밍업 이후에도 일정 시간 동안 최소 거래량/거래대금을 더 강하게 적용
            # - env:
            #   STOCK_SELECTION_EARLY_STRICT=true
            #   STOCK_SELECTION_EARLY_STRICT_MINUTES=30
            #   STOCK_SELECTION_EARLY_MIN_VOLUME=200000
            #   STOCK_SELECTION_EARLY_MIN_TRADE_AMOUNT=0
            effective_min_volume = int(self.min_volume)
            effective_min_trade_amount = int(self.min_trade_amount)
            if bool(self.early_strict):
                try:
                    tz = timezone(timedelta(hours=9))
                    now = datetime.now(tz)
                    hh, mm = self.market_open_hhmm.split(":")
                    market_open = datetime.combine(now.date(), dtime(hour=int(hh), minute=int(mm)), tzinfo=tz)
                    strict_minutes = int(self.early_strict_minutes)
                    strict_end = market_open + timedelta(minutes=strict_minutes)
                    if market_open <= now < strict_end:
                        effective_min_volume = max(effective_min_volume, int(self.early_min_volume))
                        effective_min_trade_amount = max(effective_min_trade_amount, int(self.early_min_trade_amount))
                        self.last_debug["early_strict"] = 1
                except Exception:
                    pass

            # 등락률 순위 API 호출
            # 최소 상승률 이상인 종목 조회
            min_change_pct = int(self.min_price_change_ratio * 100)  # 퍼센트로 변환
            max_change_pct = int(self.max_price_change_ratio * 100)
            
            # 대상 제외 구분 코드 (위험 종목 제외)
            # 10자리: 투자위험/경고/주의 관리종목 정리매매 불성실공시 우선주 거래정지 ETF ETN 신용주문불가 SPAC
            if self.exclude_risk_stocks:
                fid_trgt_exls_cls_code = "1111111111"  # 모든 위험 종목 제외
            else:
                fid_trgt_exls_cls_code = "0000000000"  # 제외 없음
            
            # 종목선정은 ranking/fluctuation API를 사용.
            # 모의투자(vps) 환경에서 제한되는 경우가 있어, demo일 때는 prod 조회로 우회한다.
            with _KIS_ENV_LOCK:
                prev_is_paper = bool(ka.isPaperTrading())
                prev_svr = "vps" if prev_is_paper else "prod"
                switched = False
                try:
                    if self.env_dv == "demo" and prev_svr != "prod":
                        ka.changeTREnv(None, svr="prod", product="01")
                        ka.auth(svr="prod", product="01")
                        switched = True

                    # fluctuation()은 실패 시에도 빈 DF로 내려주기 쉬워서,
                    # 먼저 _url_fetch로 에러코드/메시지를 확보하고, OK면 output으로 DF 구성
                    api_url = "/uapi/domestic-stock/v1/ranking/fluctuation"
                    tr_id = "FHPST01700000"
                    # fid_input_iscd: 0000=전체, 0001=거래소(코스피만), 1001=코스닥, 2001=코스피200
                    fid_input_iscd = "0001" if getattr(self, "kospi_only", False) else "0000"
                    # /ranking/fluctuation 은 소문자 fid_* (domestic_stock_functions.fluctuation 과 동일).
                    params = {
                        "fid_rsfl_rate2": str(max_change_pct),
                        "fid_cond_mrkt_div_code": "J",
                        "fid_cond_scr_div_code": "20170",
                        "fid_input_iscd": fid_input_iscd,
                        "fid_rank_sort_cls_code": "0",
                        "fid_input_cnt_1": str(self.max_stocks * 3),
                        "fid_prc_cls_code": "0",
                        "fid_input_price_1": str(self.min_price),
                        "fid_input_price_2": str(self.max_price),
                        "fid_vol_cnt": str(effective_min_volume),
                        "fid_trgt_cls_code": "000000000",
                        "fid_trgt_exls_cls_code": fid_trgt_exls_cls_code,
                        "fid_div_cls_code": "0",
                        "fid_rsfl_rate1": str(min_change_pct),
                    }
                    params_for_debug = dict(params)

                    res = ka._url_fetch(api_url, tr_id, "", params)
                    ok = False
                    try:
                        ok = bool(res.isOK())
                    except Exception:
                        ok = False

                    if not ok:
                        try:
                            em = str(res.getErrorMessage() or "")
                            if "OPSQ2002" in em or "FID_RANK_SORT" in em or "INPUT_FILED_SIZE" in em:
                                params_u = {k.upper(): v for k, v in params.items()}
                                res = ka._url_fetch(api_url, tr_id, "", params_u)
                                ok = bool(res.isOK())
                        except Exception:
                            pass

                    if not ok:
                        try:
                            self.last_error_message = f"{res.getErrorCode()} / {res.getErrorMessage()}"
                        except Exception:
                            self.last_error_message = "API call failed"
                        logging.warning(f"종목 선정: API 실패 - {self.last_error_message}")
                        return []

                    body = res.getBody()
                    fields = []
                    try:
                        fields = list(getattr(body, "_fields", []) or [])
                    except Exception:
                        fields = []
                    self.last_debug["api_body_fields"] = fields
                    self.last_debug["api_params"] = {
                        "fid_rsfl_rate1": params_for_debug.get("fid_rsfl_rate1"),
                        "fid_rsfl_rate2": params_for_debug.get("fid_rsfl_rate2"),
                        "fid_input_price_1": params_for_debug.get("fid_input_price_1"),
                        "fid_input_price_2": params_for_debug.get("fid_input_price_2"),
                        "fid_vol_cnt": params_for_debug.get("fid_vol_cnt"),
                        "fid_trgt_exls_cls_code": params_for_debug.get("fid_trgt_exls_cls_code"),
                        "fid_input_cnt_1": params_for_debug.get("fid_input_cnt_1"),
                    }

                    output = None
                    for k in ("output", "output1", "output2", "output3"):
                        try:
                            v = getattr(body, k, None)
                            if v is not None:
                                output = v
                                break
                        except Exception:
                            continue

                    if output is None:
                        self.last_error_message = f"API OK but output field missing (fields={fields})"
                        logging.warning(f"종목 선정: {self.last_error_message}")
                        return []
                    if isinstance(output, (list, tuple)) and len(output) == 0:
                        # 1차 쿼리에서 비면 2차 폴백: 서버측 필터를 크게 완화해 넓게 가져온 뒤, 로컬에서 다시 필터링
                        self.last_debug["fallback_stage1_empty"] = 1
                        try:
                            params2 = dict(params)
                            # 등락률 조건 완화 + 가격/거래량 서버 필터 제거(로컬에서 필터)
                            params2["fid_rsfl_rate1"] = "0"
                            params2["fid_rsfl_rate2"] = str(max(int(max_change_pct), 30))
                            params2["fid_input_price_1"] = "0"
                            params2["fid_input_price_2"] = str(max(int(self.max_price), 5000000))
                            params2["fid_vol_cnt"] = "0"
                            params2["fid_input_cnt_1"] = str(max(int(self.max_stocks) * 40, 120))
                            self.last_debug["fallback_params"] = {
                                "fid_rsfl_rate1": params2.get("fid_rsfl_rate1"),
                                "fid_rsfl_rate2": params2.get("fid_rsfl_rate2"),
                                "fid_input_price_1": params2.get("fid_input_price_1"),
                                "fid_input_price_2": params2.get("fid_input_price_2"),
                                "fid_vol_cnt": params2.get("fid_vol_cnt"),
                                "fid_trgt_exls_cls_code": params2.get("fid_trgt_exls_cls_code"),
                                "fid_input_cnt_1": params2.get("fid_input_cnt_1"),
                            }

                            res2 = ka._url_fetch(api_url, tr_id, "", params2)
                            ok2 = False
                            try:
                                ok2 = bool(res2.isOK())
                            except Exception:
                                ok2 = False
                            if not ok2:
                                try:
                                    self.last_error_message = f"(fallback) {res2.getErrorCode()} / {res2.getErrorMessage()}"
                                except Exception:
                                    self.last_error_message = "(fallback) API call failed"
                                logging.warning(f"종목 선정: API 실패 - {self.last_error_message}")
                                return []

                            body2 = res2.getBody()
                            output2 = None
                            for k2 in ("output", "output1", "output2", "output3"):
                                try:
                                    v2 = getattr(body2, k2, None)
                                    if v2 is not None:
                                        output2 = v2
                                        break
                                except Exception:
                                    continue
                            if isinstance(output2, (list, tuple)) and len(output2) > 0:
                                output = output2
                                self.last_debug["fallback_used"] = 1
                            else:
                                self.last_error_message = "API OK but output list is empty"
                                logging.warning(f"종목 선정: {self.last_error_message} | params={self.last_debug.get('api_params')} | fallback also empty")
                                return []
                        except Exception:
                            self.last_error_message = "API OK but output list is empty"
                            logging.warning(f"종목 선정: {self.last_error_message} | params={self.last_debug.get('api_params')} | fallback error")
                            return []
                    if not isinstance(output, (list, tuple)):
                        self.last_error_message = f"API OK but output is not a list (type={type(output).__name__})"
                        logging.warning(f"종목 선정: {self.last_error_message}")
                        return []

                    df = pd.DataFrame(output)
                finally:
                    if switched:
                        try:
                            ka.changeTREnv(None, svr=prev_svr, product="01")
                            ka.auth(svr=prev_svr, product="01")
                        except Exception as e:
                            logging.warning(f"종목 선정: TRENV 복구 실패(무시): {e}")
            
            if df.empty:
                logging.warning("종목 선정: 조회 결과가 없습니다.")
                return []

            self.last_debug["raw"] = int(len(df))
            
            # 필터링: 최소 상승률 이상
            prdy_ctrt_col = _find_col(df, "PRDY_CTRT", "prdy_ctrt")
            if prdy_ctrt_col:  # 전일 대비 등락률 컬럼
                min_change_pct = self.min_price_change_ratio * 100
                max_change_pct = self.max_price_change_ratio * 100
                df_filtered = df[
                    (df[prdy_ctrt_col].astype(float) >= float(min_change_pct)) &
                    (df[prdy_ctrt_col].astype(float) <= float(max_change_pct))
                ]
            else:
                df_filtered = df
            self.last_debug["after_change"] = int(len(df_filtered))
            
            # 최소 거래대금 필터링 (있는 경우)
            acml_tr_pbmn_col = _find_col(df_filtered, "ACML_TR_PBMN", "acml_tr_pbmn")
            if effective_min_trade_amount > 0 and acml_tr_pbmn_col:
                df_filtered = df_filtered[
                    df_filtered[acml_tr_pbmn_col].astype(float) >= effective_min_trade_amount
                ]
            self.last_debug["after_trade_amount"] = int(len(df_filtered))
            
            # 가격 범위 필터링
            stck_prpr_col = _find_col(df_filtered, "STCK_PRPR", "stck_prpr")
            if stck_prpr_col:  # 현재가 컬럼
                df_filtered = df_filtered[
                    (df_filtered[stck_prpr_col].astype(float) >= self.min_price) &
                    (df_filtered[stck_prpr_col].astype(float) <= self.max_price)
                ]
            self.last_debug["after_price"] = int(len(df_filtered))
            
            # 거래량 필터링
            acml_vol_col = _find_col(df_filtered, "ACML_VOL", "acml_vol")
            if acml_vol_col:  # 누적 거래량 컬럼
                df_filtered = df_filtered[
                    df_filtered[acml_vol_col].astype(float) >= effective_min_volume
                ]
            self.last_debug["after_volume"] = int(len(df_filtered))

            # 단계적 완화(최소거래대금/거래량 -> 등락률 하한) : 결과가 0이면 조금씩 완화해 후보군을 확보
            try:
                if df_filtered.empty:
                    self.last_debug["relax_start_empty"] = 1
                    # 1) 최소 거래대금 완화
                    if effective_min_trade_amount > 0 and acml_tr_pbmn_col:
                        df_tmp = df.copy()
                        if prdy_ctrt_col:
                            min_change_pct = self.min_price_change_ratio * 100
                            max_change_pct = self.max_price_change_ratio * 100
                            df_tmp = df_tmp[
                                (df_tmp[prdy_ctrt_col].astype(float) >= float(min_change_pct)) &
                                (df_tmp[prdy_ctrt_col].astype(float) <= float(max_change_pct))
                            ]
                        if stck_prpr_col:
                            df_tmp = df_tmp[
                                (df_tmp[stck_prpr_col].astype(float) >= self.min_price) &
                                (df_tmp[stck_prpr_col].astype(float) <= self.max_price)
                            ]
                        if acml_vol_col:
                            df_tmp = df_tmp[df_tmp[acml_vol_col].astype(float) >= effective_min_volume]
                        df_filtered = df_tmp
                        self.last_debug["relax_drop_trade_amount"] = int(len(df_filtered))

                if df_filtered.empty:
                    # 2) 최소 거래량 완화
                    if effective_min_volume > 0 and acml_vol_col:
                        df_tmp = df.copy()
                        if prdy_ctrt_col:
                            min_change_pct = self.min_price_change_ratio * 100
                            max_change_pct = self.max_price_change_ratio * 100
                            df_tmp = df_tmp[
                                (df_tmp[prdy_ctrt_col].astype(float) >= float(min_change_pct)) &
                                (df_tmp[prdy_ctrt_col].astype(float) <= float(max_change_pct))
                            ]
                        if stck_prpr_col:
                            df_tmp = df_tmp[
                                (df_tmp[stck_prpr_col].astype(float) >= self.min_price) &
                                (df_tmp[stck_prpr_col].astype(float) <= self.max_price)
                            ]
                        if acml_tr_pbmn_col and effective_min_trade_amount > 0:
                            df_tmp = df_tmp[df_tmp[acml_tr_pbmn_col].astype(float) >= effective_min_trade_amount]
                        df_filtered = df_tmp
                        self.last_debug["relax_drop_volume"] = int(len(df_filtered))

                if df_filtered.empty:
                    # 3) 등락률 하한 완화(0%부터)
                    if prdy_ctrt_col:
                        df_tmp = df.copy()
                        max_change_pct = self.max_price_change_ratio * 100
                        df_tmp = df_tmp[df_tmp[prdy_ctrt_col].astype(float) <= float(max_change_pct)]
                        if stck_prpr_col:
                            df_tmp = df_tmp[
                                (df_tmp[stck_prpr_col].astype(float) >= self.min_price) &
                                (df_tmp[stck_prpr_col].astype(float) <= self.max_price)
                            ]
                        if acml_vol_col:
                            df_tmp = df_tmp[df_tmp[acml_vol_col].astype(float) >= effective_min_volume]
                        if acml_tr_pbmn_col and effective_min_trade_amount > 0:
                            df_tmp = df_tmp[df_tmp[acml_tr_pbmn_col].astype(float) >= effective_min_trade_amount]
                        df_filtered = df_tmp
                        self.last_debug["relax_min_change_to_0"] = int(len(df_filtered))
            except Exception:
                pass

            # (선택) 고점 대비 하락추세(드로우다운) 종목 제외
            # - 목적: 장중(특히 오후) 시작 시점에 이미 고점 찍고 밀린 종목을 배제
            # - 기준: 현재가 vs 당일 고가(STCK_HGPR, 장 시작~선정 시점까지의 고가). 9:30 선정이면 고가가
            #   아직 현재가에 가까워 드로우다운이 작고, 13:00 선정이면 오전 고점 대비 하락이 커져 같은
            #   비율도 더 많이 걸러짐. 선정 시각에 따라 같은 max_drawdown 값의 효과가 크게 달라짐.
            # - env:
            #   STOCK_SELECTION_EXCLUDE_DRAWDOWN=true/false (default false)
            #   STOCK_SELECTION_MAX_DRAWDOWN_FROM_HIGH_RATIO=0.02  (2% 이상 밀리면 제외)
            #   STOCK_SELECTION_DRAWDOWN_FILTER_AFTER_HHMM=12:00   (이 시간 이후에만 적용)
            try:
                exclude_dd = bool(self.exclude_drawdown)
                max_dd = float(self.max_drawdown_from_high_ratio)
                after_t = _parse_hhmm(self.drawdown_filter_after_hhmm)

                tz = timezone(timedelta(hours=9))
                now_t = datetime.now(tz).time()
                apply_dd = bool(exclude_dd and max_dd > 0 and (after_t is None or now_t >= after_t))

                if apply_dd and not df_filtered.empty:
                    hgpr_col = _find_col(df_filtered, "STCK_HGPR", "stck_hgpr", "HGPR", "hgpr")
                    if stck_prpr_col and hgpr_col:
                        self.last_debug["before_drawdown"] = int(len(df_filtered))
                        pr = df_filtered[stck_prpr_col].astype(float)
                        hi = df_filtered[hgpr_col].astype(float)
                        # hi<=0이면 계산 불가 -> 통과 처리
                        dd = (hi - pr) / hi.replace(0, float("nan"))
                        df_filtered = df_filtered[(hi <= 0) | (dd <= max_dd)]
                        self.last_debug["after_drawdown"] = int(len(df_filtered))
                        if df_filtered.empty:
                            self.last_error_message = (
                                f"고점 대비 하락추세 제외 조건으로 모두 제외됨 "
                                f"(max_drawdown={max_dd*100:.1f}% 이상 제외). "
                                f"장초 선정 시: drawdown_filter_after_hhmm을 12:00으로 두면 이 필터가 적용되지 않음. "
                                f"또는 max_drawdown_from_high_ratio를 10~12%로 완화해 보세요."
                            )
            except Exception:
                pass
            
            # 종목코드 추출
            code_col = _find_col(
                df_filtered,
                "ISCD",
                "MKSC_SHRN_ISCD",
                "mksc_shrn_iscd",
                "STCK_SHRN_ISCD",
                "stck_shrn_iscd",
            )
            if not code_col:
                cols = [str(c) for c in list(df_filtered.columns)]
                self.last_error_message = (
                    "종목코드 컬럼을 찾을 수 없습니다. "
                    f"(columns={cols[:30]}{'...' if len(cols) > 30 else ''})"
                )
                logging.error(f"종목 선정: {self.last_error_message}")
                return []

            # 최종 후보 정렬(무엇을 우선으로 max_stocks를 뽑을지)
            try:
                sort_by = str(getattr(self, "sort_by", "change") or "change").strip().lower()
                if sort_by == "prev_day_trade_value":
                    pool = df_filtered.copy()
                    cap = min(len(pool), int(getattr(self, "prev_day_rank_pool_size", 80) or 80))
                    if cap > 0:
                        pool_head = pool.head(cap).copy()
                        vals: List[float] = []
                        for _, r in pool_head.iterrows():
                            try:
                                code = str(r.get(code_col) or "").strip().zfill(6) if code_col else ""
                            except Exception:
                                code = ""
                            vals.append(_get_prev_day_trade_value(code))
                        pool_head["__prev_traded_value"] = vals
                        pool_head = pool_head.sort_values(by="__prev_traded_value", ascending=False)
                        tail = pool.iloc[cap:].copy()
                        if not tail.empty:
                            # tail은 가벼운 기준으로만 정렬
                            if acml_tr_pbmn_col:
                                tail = tail.sort_values(by=acml_tr_pbmn_col, ascending=False)
                            elif acml_vol_col:
                                tail = tail.sort_values(by=acml_vol_col, ascending=False)
                        df_filtered = pd.concat([pool_head.drop(columns=["__prev_traded_value"], errors="ignore"), tail], ignore_index=True)
                        self.last_debug["sorted_by_prev_day_trade_value"] = 1
                elif sort_by == "trade_amount":
                    if acml_tr_pbmn_col:
                        df_filtered = df_filtered.sort_values(by=acml_tr_pbmn_col, ascending=False)
                        self.last_debug["sorted_by_trade_amount"] = 1
                    elif acml_vol_col:
                        df_filtered = df_filtered.sort_values(by=acml_vol_col, ascending=False)
                        self.last_debug["sorted_by_volume"] = 1
            except Exception:
                pass

            selected_codes = (
                df_filtered[code_col].astype(str).str.strip().str.zfill(6).tolist()
            )
            
            # 최대 종목 수로 제한
            selected_codes = selected_codes[:self.max_stocks]
            self.last_debug["selected"] = int(len(selected_codes))

            # 종목명 정보 보관 (대시보드 표시용)
            name_col = _find_col(
                df_filtered,
                "HTS_KOR_ISNM",
                "hts_kor_isnm",
                "PRDT_NAME",
                "prdt_name",
                "ISNM",
                "isnm",
                "STCK_SHRN_ISCD_NM",
                "stck_shrn_iscd_nm",
            ) or None
            selected_info: List[Dict[str, str]] = []
            if name_col:
                selected_df = df_filtered[[code_col, name_col]].copy()
                selected_df[code_col] = selected_df[code_col].astype(str).str.strip().str.zfill(6)
                selected_df = selected_df.drop_duplicates(subset=[code_col])
                for code in selected_codes:
                    matched = selected_df[selected_df[code_col] == code]
                    if not matched.empty:
                        stock_name = str(matched.iloc[0][name_col]).strip()
                        selected_info.append({"code": code, "name": stock_name or code})
                    else:
                        selected_info.append({"code": code, "name": code})
            else:
                selected_info = [{"code": code, "name": code} for code in selected_codes]
            self.last_selected_stock_info = selected_info
            
            logging.info(f"종목 선정 완료: {len(selected_codes)}개 종목 ({', '.join(selected_codes)})")
            return selected_codes
            
        except Exception as e:
            logging.error(f"종목 선정 오류: {e}")
            import traceback
            traceback.print_exc()
            return []
