import sys
from contextlib import contextmanager

from loguru import logger
import time, json
from typing import Dict, Any, Optional, Mapping

class SystemMonitor:
    def __init__(self, log_file: str = "system.log", service_name: str = "audio-engine", console: bool = True):
        self.log_file = log_file
        self.service_name = service_name
        self._configured=False
        self._bind_base = {"service" : service_name}
        self.setup_logging(console=console)

    def setup_logging(self, console: bool = True) -> None:
        if self._configured:
            return
        logger.remove()

        if console:
            logger.add(sys.stderr,
                       level="INFO",
                       format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
                              "<level>{level}</level> | "
                              "{extra[service]} | "
                              "<cyan>{message}</cyan>",
                       enqueue=True,
                       backtrace=True,
                       diagnose=False)

        logger.add(
            self.log_file,
            level="INFO",
            rotation="10 MB",
            retention="30 days",
            compression="zip",
            serialize=True,
            enqueue=True,
            backtrace=True,
            diagnose=False
        )
        self._configured = True

    def log_event(self,
                  event_type: str,
                  level: str = "INFO",
                  data: Optional[Mapping[str, Any]] = None,
                  **context: Any) -> None:
        data = dict(data or {})
        payload = {
            "timestamp": time.time(),
            "event_type": event_type,
            "data": data,
        }
        bound= logger.bind(**self._bind_base, **context)
        bound.log(level.upper(), "event", payload)

    def log_system_event(self, event_type: str, data: Dict[str, Any], **context: Any) -> None:
        self.log_event(event_type, "INFO",data=data, **context)

    def log_network_event(self, event_type: str, details: str, **context: Any) -> None:
        lvl = "WARNING" if event_type.lower() in {"retry", "flap"} else "INFO"
        self.log_event(event_type, lvl,data ={"details" : details}, **context)

    def log_error_event(self, event_type: str, err: Exception, **context: Any) -> None:
        bound = logger.bind(**self._bind_base, **context, event_type=event_type)
        bound.exception(f"{event_type}: {err}")

    @contextmanager
    def time_block(self, name: str, **context: Any):
        start = time.perf_counter()
        try:
            yield
        except Exception as e:
            self.log_error_event(f"{name}.error", e, **context)
            raise
        finally:
            dur_ms = (time.perf_counter() - start) * 1000.0
            self.log_event(f"{name}.duration", level="INFO", data={"dur_ms": dur_ms}, **context)