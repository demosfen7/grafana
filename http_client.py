"""Универсальный HTTP-клиент для учебного CLI-проекта.

Этот модуль содержит общий обработчик HTTP-запросов.
Идея модуля: один раз описать стандартную логику работы с requests,
а затем переиспользовать её в разных API-модулях.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

import requests


class HttpClient:
    """Простой универсальный клиент для GET-запросов.

    Здесь можно централизованно хранить базовые настройки:
    - timeout
    - headers
    - обработку ошибок
    - возврат подробной информации о запросе и ответе
    """

    def __init__(self, timeout: int = 10, default_headers: Optional[Dict[str, str]] = None) -> None:
        self.timeout = timeout
        self.default_headers = default_headers or {
            "User-Agent": "Educational-API-CLI/1.0"
        }

    def get(
        self,
        url: str,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Выполняет GET-запрос и возвращает расширенную информацию.

        Возвращаем словарь, а не только requests.Response, чтобы main.py мог:
        1. красиво вывести результат пользователю;
        2. при желании показать полный отправленный запрос и полученный ответ.
        """
        merged_headers = {**self.default_headers, **(headers or {})}

        try:
            response = requests.get(
                url,
                params=params,
                headers=merged_headers,
                timeout=self.timeout,
            )
            response.raise_for_status()

            try:
                response_data = response.json()
            except ValueError:
                response_data = response.text

            return {
                "success": True,
                "url": response.url,
                "method": "GET",
                "status_code": response.status_code,
                "request_headers": merged_headers,
                "params": params or {},
                "response_data": response_data,
            }
        except requests.RequestException as error:
            status_code = None
            response_text = None

            if getattr(error, "response", None) is not None:
                status_code = error.response.status_code
                response_text = error.response.text

            return {
                "success": False,
                "url": url,
                "method": "GET",
                "status_code": status_code,
                "request_headers": merged_headers,
                "params": params or {},
                "error": str(error),
                "response_data": response_text,
            }

    @staticmethod
    def pretty_json(data: Any) -> str:
        """Форматирует Python-объект в красивый JSON-текст для CLI."""
        return json.dumps(data, ensure_ascii=False, indent=2)
