"""
종목 선정 기준 프리셋 (보편적/보수적)

실전에서 많이 사용하는 종목 선정 기준을 프리셋으로 제공합니다.
"""

from typing import Dict

# ============================================================================
# 보편적 기준 (일반적으로 많이 사용하는 기준)
# ============================================================================

PRESET_COMMON = {
    "name": "보편적 기준",
    "description": "일반적으로 많이 사용하는 모멘텀 + 유동성 기준",
    "min_price_change_ratio": 0.02,  # 최소 2% 상승
    "max_price_change_ratio": 0.12,  # 최대 12% 상승 (과열 제외)
    "min_price": 1000,  # 최소 1,000원
    "max_price": 100000,  # 최대 10만원
    "min_volume": 100000,  # 최소 10만주 거래량
    "min_trade_amount": 2000000000,  # 최소 거래대금 20억원 (유동성 확보)
    "max_stocks": 10,  # 최대 10개 종목
    "exclude_risk_stocks": True,  # 위험 종목 제외
    "market_cap_filter": "medium_large",  # 중대형주 위주
    "exclude_limit_up": True,  # 상한가 종목 제외
}

# ============================================================================
# 보수적 기준 (리스크 최소화)
# ============================================================================

PRESET_CONSERVATIVE = {
    "name": "보수적 기준",
    "description": "체결/슬리피지/급변 리스크 최소화",
    "min_price_change_ratio": 0.005,  # 최소 0.5% 상승
    "max_price_change_ratio": 0.06,  # 최대 6% 상승 (과열 제외)
    "min_price": 5000,  # 최소 5,000원 (저가주 제외)
    "max_price": 50000,  # 최대 5만원
    "min_volume": 200000,  # 최소 20만주 거래량
    "min_trade_amount": 5000000000,  # 최소 거래대금 50억원 (유동성 강화)
    "max_stocks": 5,  # 최대 5개 종목 (집중도 높임)
    "exclude_risk_stocks": True,  # 위험 종목 제외
    "market_cap_filter": "large",  # 대형주 위주
    "exclude_limit_up": True,  # 상한가 종목 제외
    "exclude_high_volatility": True,  # 고변동성 종목 제외
}

# ============================================================================
# 공격적 기준 (고수익 추구, 리스크 높음)
# ============================================================================

PRESET_AGGRESSIVE = {
    "name": "공격적 기준",
    "description": "고수익 추구 (리스크 높음)",
    "min_price_change_ratio": 0.03,  # 최소 3% 상승
    "max_price_change_ratio": 0.20,  # 최대 20% 상승
    "min_price": 1000,  # 최소 1,000원
    "max_price": 200000,  # 최대 20만원
    "min_volume": 50000,  # 최소 5만주 거래량
    "min_trade_amount": 1000000000,  # 최소 거래대금 10억원
    "max_stocks": 15,  # 최대 15개 종목
    "exclude_risk_stocks": False,  # 위험 종목도 포함 가능
    "market_cap_filter": "all",  # 모든 시가총액
    "exclude_limit_up": False,  # 상한가도 포함 가능
}

# ============================================================================
# 초보자용 기준 (최저 리스크, 사실상 유니버스 고정)
# ============================================================================

PRESET_BEGINNER = {
    "name": "초보자용 기준",
    "description": "최저 리스크, 대형주 중심",
    "min_price_change_ratio": 0.0,  # 상승률 제한 없음
    "max_price_change_ratio": 0.05,  # 최대 5% 상승 (과열 제외)
    "min_price": 10000,  # 최소 1만원
    "max_price": 200000,  # 최대 20만원
    "min_volume": 500000,  # 최소 50만주 거래량
    "min_trade_amount": 10000000000,  # 최소 거래대금 100억원 (대형주만)
    "max_stocks": 3,  # 최대 3개 종목
    "exclude_risk_stocks": True,  # 위험 종목 제외
    "market_cap_filter": "large",  # 대형주만
    "exclude_limit_up": True,  # 상한가 제외
    "fixed_universe": True,  # 고정 유니버스 사용 권장
}

# ============================================================================
# 프리셋 딕셔너리
# ============================================================================

PRESETS = {
    "common": PRESET_COMMON,
    "conservative": PRESET_CONSERVATIVE,
    "aggressive": PRESET_AGGRESSIVE,
    "beginner": PRESET_BEGINNER,
}

def get_preset(preset_name: str) -> Dict:
    """
    프리셋 가져오기
    
    Args:
        preset_name: "common", "conservative", "aggressive", "beginner"
    
    Returns:
        프리셋 설정 딕셔너리
    """
    if preset_name not in PRESETS:
        raise ValueError(f"알 수 없는 프리셋: {preset_name}. 사용 가능: {list(PRESETS.keys())}")
    
    return PRESETS[preset_name].copy()

def list_presets() -> Dict[str, Dict]:
    """모든 프리셋 목록 반환"""
    return {name: {
        "name": preset["name"],
        "description": preset["description"]
    } for name, preset in PRESETS.items()}
