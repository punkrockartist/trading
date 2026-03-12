"""
시스템 로그 파일 저장: 대시보드에 표시되는 로그(주문 체결, 스킵, 불일치 등)를
일자별 파일에 기록. 백테스트·분석 시 거래내역과 함께 활용.

- 기본: ./logs/system_YYYYMMDD.log (SYSTEM_LOG_DIR 미설정 시)
- 비활성화: 환경변수 SYSTEM_LOG_DIR=0
- 로테이션: SYSTEM_LOG_RETENTION_DAYS(기본 30)일 지난 system_*.log 파일 자동 삭제 (쓰기 시 하루 1회 점검)
- 포맷: 한 줄에 "날짜시간(KST)\\tlevel\\t메시지"
"""

import logging
import os
import re
import threading
from datetime import datetime, timezone, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

# 환경변수 SYSTEM_LOG_DIR: 시스템 로그 파일을 쓸 디렉터리. 비면 기본값 logs(프로젝트 기준). 비활성화는 SYSTEM_LOG_DIR=0
_SYSTEM_LOG_DIR = os.environ.get("SYSTEM_LOG_DIR", "logs").strip()
if _SYSTEM_LOG_DIR in ("0", "off", "false", "no"):
    _SYSTEM_LOG_DIR = ""
# 로테이션: 이 일수보다 오래된 system_YYYYMMDD.log 삭제 (0이면 비활성화)
try:
    _RETENTION_DAYS = int(os.environ.get("SYSTEM_LOG_RETENTION_DAYS", "30").strip() or "30")
except Exception:
    _RETENTION_DAYS = 30
_SYSTEM_LOG_LOCK = threading.Lock()
_KST = timezone(timedelta(hours=9))
# 로테이션은 하루에 한 번만 수행 (마지막 수행일)
_last_rotation_date: Optional[str] = None
_SYSTEM_LOG_FILE_PATTERN = re.compile(r"^system_(\d{8})\.log$")


def _ensure_system_log_dir() -> Optional[str]:
    if not _SYSTEM_LOG_DIR:
        return None
    d = os.path.abspath(os.path.expanduser(_SYSTEM_LOG_DIR))
    if not os.path.isdir(d):
        try:
            os.makedirs(d, exist_ok=True)
        except Exception:
            return None
    return d


def _rotate_system_logs(log_dir: str) -> None:
    """30일(또는 SYSTEM_LOG_RETENTION_DAYS)이 지난 system_YYYYMMDD.log 파일 삭제. 하루 1회만 호출하도록 호출처에서 제한."""
    if _RETENTION_DAYS <= 0:
        return
    try:
        now = datetime.now(_KST)
        cutoff = now - timedelta(days=_RETENTION_DAYS)
        removed = 0
        for name in os.listdir(log_dir):
            m = _SYSTEM_LOG_FILE_PATTERN.match(name)
            if not m:
                continue
            yyyymmdd = m.group(1)
            try:
                file_date = datetime.strptime(yyyymmdd, "%Y%m%d").date()
            except ValueError:
                continue
            if file_date >= cutoff.date():
                continue
            path = os.path.join(log_dir, name)
            try:
                if os.path.isfile(path):
                    os.remove(path)
                    removed += 1
            except Exception as e:
                logger.warning("system_log rotation: failed to remove %s: %s", path, e)
        if removed:
            logger.info("system_log rotation: removed %d file(s) older than %d days", removed, _RETENTION_DAYS)
    except Exception as e:
        logger.warning("system_log rotation failed: %s", e)


def system_log_append(level: str, message: str) -> None:
    """
    시스템 로그 한 줄을 당일 파일에 추가.
    level: info | warning | error
    message: 대시보드에 표시되는 메시지(한 줄로 정규화).
    """
    d = _ensure_system_log_dir()
    if not d:
        return
    level = (level or "info").strip().lower()
    if level not in ("info", "warning", "error"):
        level = "info"
    msg_line = (message or "").replace("\r", " ").replace("\n", " ")
    msg_line = msg_line.strip() or "-"
    ts = datetime.now(_KST).strftime("%Y-%m-%dT%H:%M:%S")
    line = f"{ts}\t{level}\t{msg_line}\n"
    with _SYSTEM_LOG_LOCK:
        try:
            today = datetime.now(_KST).strftime("%Y%m%d")
            # 로테이션: 하루에 한 번만 실행
            global _last_rotation_date
            if _RETENTION_DAYS > 0 and _last_rotation_date != today:
                _rotate_system_logs(d)
                _last_rotation_date = today
            path = os.path.join(d, f"system_{today}.log")
            with open(path, "a", encoding="utf-8") as f:
                f.write(line)
        except Exception as e:
            logger.warning("system_log file write failed: %s", e)
