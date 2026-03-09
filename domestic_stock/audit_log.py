"""
감사 로그: 설정 변경, 수동 주문, 신호 승인/거절을 시간·사유와 함께 기록.
파일 또는 인메모리 저장. 사용자별 로그는 username 포함.
"""

import json
import logging
import os
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_AUDIT_DIR = os.environ.get("AUDIT_LOG_DIR", "")
_AUDIT_IN_MEMORY: List[Dict] = []
_AUDIT_LOCK = threading.Lock()
_AUDIT_MAX_IN_MEMORY = 500


def _ensure_audit_dir() -> Optional[str]:
    if not _AUDIT_DIR:
        return None
    d = os.path.abspath(os.path.expanduser(_AUDIT_DIR.strip()))
    if not os.path.isdir(d):
        try:
            os.makedirs(d, exist_ok=True)
        except Exception:
            return None
    return d


def audit_log(
    username: str,
    action: str,
    details: Optional[Dict[str, Any]] = None,
) -> None:
    """
    감사 이벤트 기록.
    action: config_save | manual_order | signal_approve | signal_reject
    details: { "section": "risk"|"strategy"|..., "signal_id": ..., "stock_code": ..., "reason": ... }
    """
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "user": str(username or "").strip(),
        "action": str(action or "").strip(),
        "details": dict(details) if details else {},
    }
    with _AUDIT_LOCK:
        _AUDIT_IN_MEMORY.append(entry)
        if len(_AUDIT_IN_MEMORY) > _AUDIT_MAX_IN_MEMORY:
            _AUDIT_IN_MEMORY[:] = _AUDIT_IN_MEMORY[-_AUDIT_MAX_IN_MEMORY:]
    d = _ensure_audit_dir()
    if d:
        try:
            path = os.path.join(d, "audit.log")
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.warning("audit log file write failed: %s", e)


def audit_get(from_ts: Optional[str] = None, to_ts: Optional[str] = None, limit: int = 200) -> List[Dict]:
    """인메모리 로그에서 from_ts~to_ts 구간 조회 (limit 건). ts는 ISO 문자열."""
    with _AUDIT_LOCK:
        rows = list(_AUDIT_IN_MEMORY)
    if from_ts or to_ts:
        def in_range(e):
            t = (e.get("ts") or "")
            if from_ts and t < from_ts:
                return False
            if to_ts and t > to_ts:
                return False
            return True
        rows = [e for e in rows if in_range(e)]
    rows = rows[-limit:] if limit else rows
    return list(reversed(rows))
