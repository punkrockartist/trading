"""
통합 시장 레짐: 프로필 병합 헬퍼 (레짐 판별 로직은 quant_dashboard_api에서 state·헬퍼에 접근).
"""
from __future__ import annotations

from typing import Any, Dict, Tuple


def merge_strategy_risk(
    base_strategy: Dict[str, Any],
    base_risk: Dict[str, Any],
    strategy_overrides: Dict[str, Any] | None,
    risk_overrides: Dict[str, Any] | None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """베이스 저장값에 레짐별 strategy/risk 덮어쓰기(None·빈 dict 무시)."""
    so = strategy_overrides or {}
    ro = risk_overrides or {}
    ms = {**base_strategy, **so}
    mr = {**base_risk, **ro}
    return (ms, mr)
