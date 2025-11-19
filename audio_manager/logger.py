from __future__ import annotations

import json
import time
import sys
from contextlib import contextmanager
from typing import Any, Dict, Optional
from loguru import logger


class SystemMonitor:
    def __init__(self, service_name: str, log_file: str = "system.log") -> None:
        self.service_name = service_name

        logger.add(
            sys.stderr,
            format="<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
                   "<level>{level: <8}</level> | {message}",
            enqueue=True,
        )
        logger.add(
            log_file,
            rotation="10 MB",
            retention="10 days",
            enqueue=True,
            format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level} | {message}",
        )

    def log_event(
        self,
        event_type: str,
        event_data: Optional[Dict[str, Any]] = None,
        level: str = "INFO",
        message: str = "",
    ) -> None:

        payload = {
            "ts": time.time(),
            "service": self.service_name,
            "event_type": event_type,
            "message": message,
            "data": event_data or {},
        }
        log = logger.bind(service=self.service_name, event_type=event_type)
        log.log(level, json.dumps(payload, ensure_ascii=False))

    def log_error_event(
        self,
        event_type: str,
        exc: BaseException,
        event_data: Optional[Dict[str, Any]] = None,
        message: str = "",
    ) -> None:

        payload = {
            "ts": time.time(),
            "service": self.service_name,
            "event_type": event_type,
            "message": message,
            "error": repr(exc),
            "data": event_data or {},
        }
        log = logger.bind(service=self.service_name, event_type=event_type)
        log.exception(json.dumps(payload, ensure_ascii=False))

    @contextmanager
    def time_block(
        self,
        event_type: str,
        event_data: Optional[Dict[str, Any]] = None,
        message: str = "",
    ):

        start = time.perf_counter()
        try:
            yield
            duration = time.perf_counter() - start
            data = dict(event_data or {})
            data["duration_sec"] = duration
            self.log_event(
                event_type,
                data,
                level="DEBUG",
                message=message or "time_block finished",
            )
        except Exception as exc:
            duration = time.perf_counter() - start
            data = dict(event_data or {})
            data["duration_sec"] = duration
            self.log_error_event(
                event_type + ".error",
                exc,
                event_data=data,
                message=message or "time_block raised exception",
            )
            raise
