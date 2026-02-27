"""
자동 종목 선정 클래스

등락률 순위 API를 사용하여 종목을 자동으로 선정합니다.
"""

import sys
import logging
from typing import Dict, List

sys.path.extend(['..', '.'])
from domestic_stock_functions import fluctuation

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
        exclude_risk_stocks: bool = True  # 위험/경고/주의 종목 제외
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
        self.last_selected_stock_info: List[Dict[str, str]] = []
    
    def select_stocks_by_fluctuation(self) -> List[str]:
        """
        등락률 순위 API를 사용하여 종목 선정
        
        Returns:
            선정된 종목코드 리스트
        """
        try:
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
            
            df = fluctuation(
                fid_cond_mrkt_div_code="J",  # KRX
                fid_cond_scr_div_code="20170",  # 등락률
                fid_input_iscd="0000",  # 전체
                fid_rank_sort_cls_code="0000",  # 등락률순
                fid_input_cnt_1=str(self.max_stocks * 3),  # 여유있게 조회 (필터링 후 최종 선정)
                fid_prc_cls_code="0",  # 가격 구분 (0: 전체)
                fid_input_price_1=str(self.min_price),  # 최소 가격
                fid_input_price_2=str(self.max_price),  # 최대 가격
                fid_vol_cnt=str(self.min_volume),  # 최소 거래량
                fid_trgt_cls_code="0",  # 대상 구분 (0: 전체)
                fid_trgt_exls_cls_code=fid_trgt_exls_cls_code,  # 위험 종목 제외
                fid_div_cls_code="0",  # 분류 구분 (0: 전체)
                fid_rsfl_rate1=str(min_change_pct),  # 최소 상승률 (%)
                fid_rsfl_rate2=str(max_change_pct)  # 최대 상승률 (%)
            )
            
            if df.empty:
                logging.warning("종목 선정: 조회 결과가 없습니다.")
                return []
            
            # 필터링: 최소 상승률 이상
            if "PRDY_CTRT" in df.columns:  # 전일 대비 등락률 컬럼
                min_change_pct = self.min_price_change_ratio * 100
                df_filtered = df[df["PRDY_CTRT"].astype(float) >= min_change_pct]
            else:
                df_filtered = df
            
            # 최소 거래대금 필터링 (있는 경우)
            if self.min_trade_amount > 0 and "ACML_TR_PBMN" in df_filtered.columns:
                df_filtered = df_filtered[
                    df_filtered["ACML_TR_PBMN"].astype(float) >= self.min_trade_amount
                ]
            
            # 가격 범위 필터링
            if "STCK_PRPR" in df_filtered.columns:  # 현재가 컬럼
                df_filtered = df_filtered[
                    (df_filtered["STCK_PRPR"].astype(float) >= self.min_price) &
                    (df_filtered["STCK_PRPR"].astype(float) <= self.max_price)
                ]
            
            # 거래량 필터링
            if "ACML_VOL" in df_filtered.columns:  # 누적 거래량 컬럼
                df_filtered = df_filtered[
                    df_filtered["ACML_VOL"].astype(float) >= self.min_volume
                ]
            
            # 종목코드 추출
            if "ISCD" in df_filtered.columns:  # 종목코드 컬럼
                selected_codes = df_filtered["ISCD"].astype(str).str.strip().str.zfill(6).tolist()
                code_col = "ISCD"
            elif "MKSC_SHRN_ISCD" in df_filtered.columns:
                selected_codes = df_filtered["MKSC_SHRN_ISCD"].astype(str).str.strip().str.zfill(6).tolist()
                code_col = "MKSC_SHRN_ISCD"
            else:
                logging.error("종목 선정: 종목코드 컬럼을 찾을 수 없습니다.")
                return []
            
            # 최대 종목 수로 제한
            selected_codes = selected_codes[:self.max_stocks]

            # 종목명 정보 보관 (대시보드 표시용)
            name_candidates = ["HTS_KOR_ISNM", "PRDT_NAME", "ISNM", "STCK_SHRN_ISCD_NM"]
            name_col = next((c for c in name_candidates if c in df_filtered.columns), None)
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
