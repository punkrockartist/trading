"""
중요 이벤트 알림: 한도 도달, VI/서킷 스킵, 토큰 만료, 반복 거절 등.
log_only | telegram (선택)
"""

import logging
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Optional

logger = logging.getLogger(__name__)

_NOTIFICATION_TYPE = os.environ.get("NOTIFICATION_TYPE", "log_only").strip().lower()
_TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
_TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()


def send_alert(level: str, message: str, title: Optional[str] = None) -> None:
    """
    level: info | warning | error
    message: 본문
    title: 선택 제목 (텔레그램 등)
    """
    if _NOTIFICATION_TYPE == "none" or not _NOTIFICATION_TYPE:
        return
    if _NOTIFICATION_TYPE == "log_only":
        getattr(logger, level if level in ("info", "warning", "error") else "info")("[알림] %s", message)
        return
    if _NOTIFICATION_TYPE == "telegram" and _TELEGRAM_BOT_TOKEN and _TELEGRAM_CHAT_ID:
        try:
            text = (title or "퀀트 알림") + "\n" + message
            url = f"https://api.telegram.org/bot{_TELEGRAM_BOT_TOKEN}/sendMessage"
            data = urllib.parse.urlencode({"chat_id": _TELEGRAM_CHAT_ID, "text": text}).encode()
            req = urllib.request.Request(url, data=data, method="POST")
            req.add_header("Content-Type", "application/x-www-form-urlencoded")
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status != 200:
                    logger.warning("telegram send status %s", resp.status)
        except Exception as e:
            logger.warning("telegram send failed: %s", e)
        return
    logger.info("[알림] %s", message)
