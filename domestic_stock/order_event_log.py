# -*- coding: utf-8 -*-
"""Async JSONL order event log (queue + daemon thread; keep WS/order path light)."""

from __future__ import annotations

import json
import logging
import os
import queue
import threading
import time
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_KST = timezone(timedelta(hours=9))
_queue: Optional[queue.Queue[Optional[Dict[str, Any]]]] = None
_writer_thread: Optional[threading.Thread] = None
_lock = threading.Lock()
_MAX_QUEUE = 2000
_drop_warn_ts = 0.0


def _log_path_for_today() -> str:
    base = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
    os.makedirs(base, exist_ok=True)
    day = datetime.now(_KST).strftime("%Y%m%d")
    return os.path.join(base, f"order_events_{day}.jsonl")


def _writer_loop() -> None:
    global _queue
    q = _queue
    if q is None:
        return
    last_rotate = ""
    while True:
        try:
            item = q.get(timeout=1.0)
        except queue.Empty:
            continue
        if item is None:
            continue
        if item.get("__shutdown__"):
            break
        try:
            p = _log_path_for_today()
            if p != last_rotate:
                last_rotate = p
            line = json.dumps(item, ensure_ascii=False, default=str) + "\n"
            with open(p, "a", encoding="utf-8") as f:
                f.write(line)
        except Exception as e:
            logger.debug("order_event_log write failed: %s", e)


def ensure_order_event_writer_started() -> None:
    global _queue, _writer_thread
    with _lock:
        if _queue is not None and _writer_thread is not None and _writer_thread.is_alive():
            return
        _queue = queue.Queue(maxsize=_MAX_QUEUE)
        _writer_thread = threading.Thread(target=_writer_loop, name="order_event_log", daemon=True)
        _writer_thread.start()


def enqueue_order_event(event: Dict[str, Any]) -> None:
    """Non-blocking enqueue; drops when queue is full (occasional warning)."""
    global _drop_warn_ts
    try:
        ensure_order_event_writer_started()
        if _queue is None:
            return
        ev = dict(event)
        ev["_enqueued_at"] = time.time()
        _queue.put_nowait(ev)
    except queue.Full:
        now = time.time()
        if now - _drop_warn_ts > 60.0:
            _drop_warn_ts = now
            logger.warning("order_event_log queue full (%s), dropping events", _MAX_QUEUE)
    except Exception as e:
        logger.debug("order_event_log enqueue failed: %s", e)
