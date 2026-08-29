"""loki_logging.py — минимальный логгинг-хендлер, отправляющий записи в Loki.

Работает по принципу push: каждая запись лога отправляется отдельным
HTTP-запросом на Loki push API (/loki/api/v1/push). Если переменная
окружения LOKI_URL не задана или Loki недоступен, отправка просто
не выполняется — работа приложения при этом не блокируется и не падает.
"""

from __future__ import annotations

import logging
import os

import requests


class LokiHandler(logging.Handler):
    """Отправляет каждую запись лога в Loki через push API."""

    def __init__(self, url: str, labels: dict[str, str], timeout: float = 2.0) -> None:
        super().__init__()
        self.push_url = url.rstrip("/") + "/loki/api/v1/push"
        self.labels = labels
        self.timeout = timeout

    def emit(self, record: logging.LogRecord) -> None:
        line = self.format(record)
        ts_ns = str(int(record.created * 1_000_000_000))
        payload = {
            "streams": [
                {
                    "stream": {**self.labels, "level": record.levelname.lower()},
                    "values": [[ts_ns, line]],
                }
            ]
        }
        try:
            requests.post(self.push_url, json=payload, timeout=self.timeout)
        except requests.RequestException:
            pass  # сеть/Loki недоступны — приложение из-за логов падать не должно


def setup_logging(app_name: str = "weather-cli") -> logging.Logger:
    """Настраивает логгер приложения; при заданном LOKI_URL добавляет отправку в Loki."""
    logger = logging.getLogger(app_name)
    logger.setLevel(logging.INFO)

    loki_url = os.getenv("LOKI_URL")
    if loki_url:
        formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
        # job/app — конвенция большинства готовых дашбордов; container_name/service_name/instance —
        # конвенция дашбордов, рассчитанных на Promtail + Docker service discovery (например 24574)
        handler = LokiHandler(
            loki_url,
            labels={
                "app": app_name,
                "job": app_name,
                "container_name": app_name,
                "service_name": app_name,
                "instance": app_name,
            },
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    return logger
