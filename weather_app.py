"""
weather_app.py — учебное CLI-приложение для получения текущей погоды
через OpenWeather API.

Структура файла:
  1. Импорты и конфигурация
  2. HTTP-запрос с ретраями (_request_with_retry)
  3. Функции API: get_coordinates, get_weather_by_coordinates
  4. Кэширование: _save_cache, _load_cache, _offer_cache
  5. CLI: меню + режимы ввода + точка входа main()
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import requests
from colorama import Fore, Style, init
from dotenv import load_dotenv

# ── 1. Инициализация colorama ─────────────────────────────────────────────────
# autoreset=True означает, что цвет автоматически сбрасывается после каждого print,
# и не нужно писать Style.RESET_ALL в конце каждой строки.
init(autoreset=True)

# ── 2. Конфигурация ───────────────────────────────────────────────────────────
# load_dotenv() читает файл .env в текущей папке и кладёт значения в os.environ.
load_dotenv()
API_KEY = os.getenv("API_KEY")  # None, если переменная не задана

# Базовые URL OpenWeather (без параметров — их передаём отдельно)
GEOCODING_URL = "http://api.openweathermap.org/geo/1.0/direct"
WEATHER_URL   = "https://api.openweathermap.org/data/2.5/weather"
FORECAST_URL  = "https://api.openweathermap.org/data/2.5/forecast"

CACHE_FILE    = Path("weather_cache.json")   # имя файла кэша
CACHE_MAX_AGE = timedelta(hours=3)           # максимальный возраст кэша

# ── Каталог всех доступных полей ответа OpenWeather ──────────────────────────
# Каждый элемент — словарь с:
#   "label"   — название поля для отображения пользователю
#   "extract" — функция, которая принимает dict ответа API и возвращает значение
#   "unit"    — единица измерения (пустая строка, если не нужна)
#
# Функции используют .get() или try/except, чтобы не падать на отсутствующих полях
# (например, rain/snow появляются в ответе только при наличии осадков).
WEATHER_FIELDS = [
    {
        "label":   "Температура",
        "extract": lambda w: w["main"]["temp"],
        "unit":    "°C",
    },
    {
        "label":   "Ощущается как",
        "extract": lambda w: w["main"]["feels_like"],
        "unit":    "°C",
    },
    {
        "label":   "Мин. температура",
        "extract": lambda w: w["main"]["temp_min"],
        "unit":    "°C",
    },
    {
        "label":   "Макс. температура",
        "extract": lambda w: w["main"]["temp_max"],
        "unit":    "°C",
    },
    {
        "label":   "Влажность",
        "extract": lambda w: w["main"]["humidity"],
        "unit":    "%",
    },
    {
        "label":   "Давление",
        "extract": lambda w: w["main"]["pressure"],
        "unit":    "гПа",
    },
    {
        "label":   "Давление (уровень моря)",
        # sea_level присутствует не всегда — используем .get()
        "extract": lambda w: w["main"].get("sea_level", "нет данных"),
        "unit":    "гПа",
    },
    {
        "label":   "Давление (у земли)",
        "extract": lambda w: w["main"].get("grnd_level", "нет данных"),
        "unit":    "гПа",
    },
    {
        "label":   "Описание погоды",
        "extract": lambda w: w["weather"][0]["description"],
        "unit":    "",
    },
    {
        "label":   "Погодная группа",
        # "main" внутри "weather" — общее название группы (Rain, Clouds, Clear…)
        "extract": lambda w: w["weather"][0]["main"],
        "unit":    "",
    },
    {
        "label":   "Иконка погоды (код)",
        "extract": lambda w: w["weather"][0]["icon"],
        "unit":    "",
    },
    {
        "label":   "Скорость ветра",
        "extract": lambda w: w["wind"]["speed"],
        "unit":    "м/с",
    },
    {
        "label":   "Направление ветра",
        # deg: 0/360 — север, 90 — восток, 180 — юг, 270 — запад
        "extract": lambda w: w["wind"]["deg"],
        "unit":    "°",
    },
    {
        "label":   "Порывы ветра",
        "extract": lambda w: w["wind"].get("gust", "нет данных"),
        "unit":    "м/с",
    },
    {
        "label":   "Облачность",
        "extract": lambda w: w["clouds"]["all"],
        "unit":    "%",
    },
    {
        "label":   "Видимость",
        # Максимальное значение по API — 10000 м
        "extract": lambda w: w.get("visibility", "нет данных"),
        "unit":    "м",
    },
    {
        "label":   "Осадки (дождь за 1 ч)",
        # Поле "rain" появляется только при наличии дождя
        "extract": lambda w: w.get("rain", {}).get("1h", 0),
        "unit":    "мм",
    },
    {
        "label":   "Осадки (снег за 1 ч)",
        "extract": lambda w: w.get("snow", {}).get("1h", 0),
        "unit":    "мм",
    },
    {
        "label":   "Страна",
        "extract": lambda w: w["sys"]["country"],
        "unit":    "",
    },
    {
        "label":   "Рассвет",
        # dt — Unix-время (секунды с 01.01.1970); fromtimestamp переводит в datetime
        "extract": lambda w: datetime.fromtimestamp(w["sys"]["sunrise"]).strftime("%H:%M"),
        "unit":    "",
    },
    {
        "label":   "Закат",
        "extract": lambda w: datetime.fromtimestamp(w["sys"]["sunset"]).strftime("%H:%M"),
        "unit":    "",
    },
    {
        "label":   "Часовой пояс",
        # timezone — смещение в секундах; делим на 3600, чтобы получить часы
        "extract": lambda w: f"UTC{w['timezone'] // 3600:+d}",
        "unit":    "",
    },
    {
        "label":   "Координаты",
        "extract": lambda w: f"{w['coord']['lat']:.4f}, {w['coord']['lon']:.4f}",
        "unit":    "",
    },
]


# ══════════════════════════════════════════════════════════════════════════════
# БЛОК 1: HTTP-запросы с ретраями
# ══════════════════════════════════════════════════════════════════════════════

class WeatherError(Exception):
    """
    Исключение для «ожидаемых» ошибок: город не найден, HTTP-ошибка и т.п.

    Отличие от sys.exit():
      - sys.exit() завершает всю программу — плохо для меню.
      - WeatherError перехватывается в режимах CLI, выводит сообщение
        и возвращает пользователя обратно в меню.

    sys.exit() оставляем только для по-настоящему фатальных ситуаций
    (отсутствует API_KEY — без него вообще невозможно работать).
    """
    pass


def _check_api_key() -> None:
    """Проверяем наличие ключа до любого запроса. Завершаем приложение, если ключа нет."""
    if not API_KEY:
        print(Fore.RED + "Ошибка: API_KEY не найден. Создайте файл .env и добавьте API_KEY=ваш_ключ.")
        sys.exit(1)


def _request_with_retry(url: str, params: dict, max_retries: int = 3) -> requests.Response:
    """
    Выполняет GET-запрос с экспоненциальными повторами при сбоях.

    Повтор срабатывает при:
      - сетевых ошибках (нет подключения, таймаут и т.п.)
      - статусе 429 (Too Many Requests — сервер просит нас притормозить)

    Экспоненциальная пауза: 1с → 2с → 4с между попытками.
    После max_retries неудач — пробрасываем последнее исключение наверх.
    """
    delay = 1      # начальная пауза в секундах
    last_exc: Optional[Exception] = None

    for attempt in range(1, max_retries + 1):
        try:
            response = requests.get(url, params=params, timeout=10)

            # 429 — не исключение requests, поэтому обрабатываем отдельно
            if response.status_code == 429:
                print(Fore.YELLOW + f"  Лимит запросов (429). Повтор {attempt}/{max_retries} через {delay}с...")
                time.sleep(delay)
                delay *= 2   # удваиваем паузу (exponential backoff)
                last_exc = requests.exceptions.RequestException("429 Too Many Requests")
                continue     # переходим к следующей попытке

            # Любой другой статус (200, 401, 404...) — возвращаем как есть,
            # логику обработки статусов выносим в вызывающие функции.
            return response

        except requests.exceptions.RequestException as exc:
            last_exc = exc
            if attempt < max_retries:
                print(Fore.YELLOW + f"  Сетевая ошибка: {exc}. Повтор {attempt}/{max_retries} через {delay}с...")
                time.sleep(delay)
                delay *= 2
            # После последней попытки выходим из цикла и пробрасываем exc ниже

    # Все попытки исчерпаны
    raise last_exc or requests.exceptions.RequestException("Не удалось выполнить запрос")


# ══════════════════════════════════════════════════════════════════════════════
# БЛОК 2: Функции OpenWeather API
# ══════════════════════════════════════════════════════════════════════════════

def get_coordinates(city: str) -> tuple[float, float, str, str]:
    """
    Возвращает (широта, долгота, найденное_имя, страна) через OpenWeather Geocoding API.

    Endpoint: GET http://api.openweathermap.org/geo/1.0/direct
    Параметры: q=<город>, limit=1, lang=ru, appid=<ключ>

    Возвращаем 4 значения вместо 2, потому что API делает fuzzy-matching:
    запрос «ффф» может вернуть реальный город «Budburan, PH». Вызывающий код
    должен показать пользователю, что именно нашлось, и попросить подтверждение.
    """
    _check_api_key()

    params = {
        "q":     city,
        "limit": 1,
        "lang":  "ru",
        "appid": API_KEY,
    }

    try:
        response = _request_with_retry(GEOCODING_URL, params)
    except requests.exceptions.RequestException as exc:
        raise WeatherError(f"Сетевая ошибка при определении координат: {exc}") from exc

    if response.status_code == 401:
        raise WeatherError("Ошибка 401: невалидный API-ключ. Проверьте значение в .env.")

    if response.status_code != 200:
        raise WeatherError(f"Ошибка геокодирования: сервер вернул HTTP {response.status_code}.")

    data = response.json()

    if not data:
        raise WeatherError(f"Город «{city}» не найден. Проверьте написание.")

    location = data[0]
    # Предпочитаем локализованное название (local_names.ru), иначе берём "name"
    found_name    = location.get("local_names", {}).get("ru") or location["name"]
    found_country = location.get("country", "")
    return float(location["lat"]), float(location["lon"]), found_name, found_country


def get_weather_by_coordinates(lat: float, lon: float) -> dict:
    """
    Возвращает словарь с текущей погодой по координатам.

    Endpoint: GET https://api.openweathermap.org/data/2.5/weather
    Параметры: lat, lon, units=metric (°C), lang=ru, appid=<ключ>

    Ключевые поля ответа:
      data["main"]["temp"]              — температура в °C
      data["weather"][0]["description"] — описание на русском
      data["name"]                      — название города по версии API

    При ошибке выводит сообщение и возвращает пустой dict (не sys.exit,
    чтобы можно было предложить кэш).
    """
    _check_api_key()

    params = {
        "lat":   lat,
        "lon":   lon,
        "units": "metric",   # температура в Цельсиях
        "lang":  "ru",       # описание погоды на русском
        "appid": API_KEY,
    }

    try:
        response = _request_with_retry(WEATHER_URL, params)
    except requests.exceptions.RequestException as exc:
        print(Fore.RED + f"Сетевая ошибка при запросе погоды: {exc}")
        return {}   # пустой dict — сигнал для CLI предложить кэш

    if response.status_code == 401:
        print(Fore.RED + "Ошибка 401: невалидный API-ключ.")
        return {}

    if response.status_code != 200:
        print(Fore.RED + f"Ошибка запроса погоды: HTTP {response.status_code}.")
        return {}

    return response.json()


def get_forecast(lat: float, lon: float) -> dict:
    """
    Возвращает прогноз погоды на 5 дней с шагом 3 часа (40 точек).

    Endpoint: GET https://api.openweathermap.org/data/2.5/forecast
    Ключевые поля ответа:
      data["list"]        — список точек прогноза
      item["dt_txt"]      — дата и время ("2026-06-20 12:00:00")
      item["main"]["temp"]— температура
      item["weather"][0]  — описание и иконка
    """
    _check_api_key()

    params = {
        "lat":   lat,
        "lon":   lon,
        "units": "metric",
        "lang":  "ru",
        "cnt":   40,
        "appid": API_KEY,
    }

    try:
        response = _request_with_retry(FORECAST_URL, params)
    except requests.exceptions.RequestException as exc:
        print(Fore.RED + f"Сетевая ошибка при запросе прогноза: {exc}")
        return {}

    if response.status_code == 401:
        print(Fore.RED + "Ошибка 401: невалидный API-ключ.")
        return {}

    if response.status_code != 200:
        print(Fore.RED + f"Ошибка запроса прогноза: HTTP {response.status_code}.")
        return {}

    return response.json()


# ══════════════════════════════════════════════════════════════════════════════
# БЛОК 3: Кэширование
# ══════════════════════════════════════════════════════════════════════════════

def _save_cache(city: str, lat: float, lon: float, weather: dict) -> None:
    """
    Сохраняет успешный ответ в weather_cache.json.

    Структура кэша:
      {
        "city":       "Москва",
        "lat":        55.7558,
        "lon":        37.6173,
        "fetched_at": "2025-01-15T14:30:00",   ← ISO-формат datetime
        "weather":    { ...полный ответ API... }
      }
    """
    cache = {
        "city":       city,
        "lat":        lat,
        "lon":        lon,
        "fetched_at": datetime.now().isoformat(),
        "weather":    weather,
    }
    CACHE_FILE.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_cache() -> Optional[dict]:
    """
    Читает кэш из файла и проверяет его актуальность.

    Возвращает словарь с кэшем или None, если:
      - файл не существует
      - файл повреждён (невалидный JSON)
      - данные старше CACHE_MAX_AGE (3 часа)
    """
    if not CACHE_FILE.exists():
        return None

    try:
        cache = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        fetched_at = datetime.fromisoformat(cache["fetched_at"])
        age = datetime.now() - fetched_at

        if age > CACHE_MAX_AGE:
            return None   # кэш устарел — лучше не показывать

        return cache
    except (json.JSONDecodeError, KeyError, ValueError):
        return None   # файл повреждён — игнорируем


def _offer_cache() -> bool:
    """
    При сетевой ошибке предлагает показать данные из кэша (если < 3 часов).

    Возвращает True, если кэш был успешно показан.
    """
    cache = _load_cache()

    if not cache:
        print(Fore.YELLOW + "Кэш отсутствует или устарел (> 3 часов). Нет данных для отображения.")
        return False

    weather  = cache["weather"]
    temp     = weather["main"]["temp"]
    desc     = weather["weather"][0]["description"]
    city     = cache["city"]
    age_sec  = (datetime.now() - datetime.fromisoformat(cache["fetched_at"])).total_seconds()
    age_min  = int(age_sec / 60)

    answer = input(Fore.YELLOW + f"Показать данные из кэша ({age_min} мин. назад)? [y/n]: ").strip().lower()
    if answer == "y":
        print(Fore.CYAN + f"\n[Из кэша] Погода в {city}: {temp}°C, {desc}")
        return True

    return False


# ══════════════════════════════════════════════════════════════════════════════
# БЛОК 4: CLI
# ══════════════════════════════════════════════════════════════════════════════

def _print_weather(city: str, weather: dict) -> None:
    """Форматирует и выводит строку погоды в требуемом формате."""
    temp = weather["main"]["temp"]
    desc = weather["weather"][0]["description"]
    # Итоговый формат: «Погода в Москва: 12.4°C, пасмурно»
    print(Fore.GREEN + Style.BRIGHT + f"\nПогода в {city}: {temp}°C, {desc}\n")


def _print_forecast(city: str, data: dict) -> None:
    """Выводит прогноз на 5 дней, сгруппированный по дням."""
    DAY_NAMES = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    MONTHS    = ["янв", "фев", "мар", "апр", "май", "июн",
                 "июл", "авг", "сен", "окт", "ноя", "дек"]

    print(Fore.CYAN + Style.BRIGHT + f"\n  Прогноз на 5 дней для «{city}»:")
    print(Fore.CYAN + "  " + "─" * 54)

    # Группируем 3-часовые точки по дате (YYYY-MM-DD)
    days: dict[str, list] = {}
    for item in data["list"]:
        date = item["dt_txt"][:10]
        days.setdefault(date, []).append(item)

    for date_str, slots in list(days.items())[:5]:
        dt       = datetime.strptime(date_str, "%Y-%m-%d")
        day_name = DAY_NAMES[dt.weekday()]
        label    = f"{day_name} {dt.day} {MONTHS[dt.month - 1]}"

        temps = [s["main"]["temp"] for s in slots]
        t_min = min(temps)
        t_max = max(temps)

        # Описание берём из слота ближайшего к полудню
        noon  = next((s for s in slots if "12:00:00" in s["dt_txt"]), slots[0])
        desc  = noon["weather"][0]["description"]

        print(
            Fore.WHITE + f"  {label:<16}"
            + Fore.CYAN + f"{t_min:.0f}°…{t_max:.0f}°C"
            + "  "
            + Fore.GREEN + desc
        )

    print()


def _print_menu() -> None:
    """Рисует главное меню с помощью colorama."""
    print(Fore.CYAN + Style.BRIGHT + "\n╔══════════════════════════════════╗")
    print(Fore.CYAN + Style.BRIGHT +   "║     ПОГОДА — OpenWeather API     ║")
    print(Fore.CYAN + Style.BRIGHT +   "╚══════════════════════════════════╝")
    print(Fore.WHITE + "  1 — Погода по названию города")
    print(Fore.WHITE + "  2 — Погода по координатам (lat, lon)")
    print(Fore.WHITE + "  3 — Выбрать конкретные поля из ответа API")
    print(Fore.WHITE + "  4 — Прогноз на 5 дней")
    print(Fore.WHITE + "  0 — Выход")
    print(Fore.CYAN  + "  ──────────────────────────────────")


def _mode_city() -> None:
    """
    Режим 1: пользователь вводит название города.

    Шаги:
      1. Запрашиваем город.
      2. Получаем координаты через Geocoding API.
      3. Получаем погоду через Current Weather API.
      4. Выводим результат и сохраняем в кэш.
      5. При ошибке сети — предлагаем кэш.
    """
    city = input(Fore.YELLOW + "Введите название города: ").strip()
    if not city:
        print(Fore.RED + "Название города не может быть пустым.")
        return

    print(Fore.WHITE + "Определяю координаты...")
    try:
        lat, lon, found_name, found_country = get_coordinates(city)
    except WeatherError as err:
        print(Fore.RED + str(err))
        return

    # API делает fuzzy-matching, поэтому показываем, что именно нашлось,
    # и просим подтверждение — пользователь видит «Budburan, PH» вместо «ффф».
    print(Fore.WHITE + f"Найден город: " + Fore.CYAN + Style.BRIGHT + f"{found_name}, {found_country}")
    confirm = input(Fore.YELLOW + "Это правильный город? [y/n]: ").strip().lower()
    if confirm != "y":
        print(Fore.WHITE + "Отменено. Попробуйте другое название.")
        return

    print(Fore.WHITE + f"Координаты: {lat:.4f}°, {lon:.4f}°. Запрашиваю погоду...")
    weather = get_weather_by_coordinates(lat, lon)

    if not weather:
        # Функция уже напечатала причину ошибки — предлагаем кэш
        _offer_cache()
        return

    _print_weather(city, weather)
    _save_cache(city, lat, lon, weather)


def _mode_coordinates() -> None:
    """
    Режим 2: пользователь вводит широту и долготу вручную.

    Имя города берём из поля "name" в ответе API
    (или показываем координаты, если поле пустое).
    """
    try:
        lat = float(input(Fore.YELLOW + "Введите широту  (lat, например 55.7558): ").strip())
        lon = float(input(Fore.YELLOW + "Введите долготу (lon, например 37.6173): ").strip())
    except ValueError:
        print(Fore.RED + "Ошибка: координаты должны быть числами (например: 55.7558).")
        return

    print(Fore.WHITE + "Запрашиваю погоду...")
    weather = get_weather_by_coordinates(lat, lon)

    if not weather:
        _offer_cache()
        return

    # API возвращает название ближайшего населённого пункта в поле "name"
    city = weather.get("name") or f"{lat:.4f}, {lon:.4f}"
    _print_weather(city, weather)
    _save_cache(city, lat, lon, weather)


def _mode_explore_fields() -> None:
    """
    Режим 3: пользователь выбирает, какие именно поля из ответа API показать.

    Шаги:
      1. Запрашиваем город.
      2. Получаем полный ответ API.
      3. Показываем таблицу всех полей с текущими значениями (пронумерованную).
      4. Пользователь вводит номера нужных полей через пробел или «all».
      5. Выводим только выбранные поля.
    """
    city = input(Fore.YELLOW + "Введите название города: ").strip()
    if not city:
        print(Fore.RED + "Название города не может быть пустым.")
        return

    print(Fore.WHITE + "Определяю координаты...")
    try:
        lat, lon, found_name, found_country = get_coordinates(city)
    except WeatherError as err:
        print(Fore.RED + str(err))
        return

    print(Fore.WHITE + f"Найден город: " + Fore.CYAN + Style.BRIGHT + f"{found_name}, {found_country}")
    confirm = input(Fore.YELLOW + "Это правильный город? [y/n]: ").strip().lower()
    if confirm != "y":
        print(Fore.WHITE + "Отменено. Попробуйте другое название.")
        return

    print(Fore.WHITE + "Запрашиваю данные...")
    weather = get_weather_by_coordinates(lat, lon)

    if not weather:
        _offer_cache()
        return

    # ── Шаг 1: показываем все поля с их значениями ───────────────────────────
    print(Fore.CYAN + Style.BRIGHT + f"\n  Доступные поля для города «{weather.get('name', city)}»:")
    print(Fore.CYAN + "  " + "─" * 52)

    # Для каждого поля пробуем вызвать extract(); при ошибке ставим «—»
    extracted: list[tuple[int, str, str, str]] = []  # (номер, label, value, unit)
    for i, field in enumerate(WEATHER_FIELDS, start=1):
        try:
            value = field["extract"](weather)
        except (KeyError, IndexError, TypeError):
            value = "нет данных"

        extracted.append((i, field["label"], str(value), field["unit"]))

        # Форматируем строку: «  1. Температура ......... 14.67 °C»
        label_col = f"{i:2}. {field['label']}"          # «  1. Температура»
        value_col = f"{value} {field['unit']}".strip()  # «14.67 °C»
        # ljust выравнивает label по ширине 38 символов, остаток — значение
        print(Fore.WHITE + f"  {label_col:<38}" + Fore.GREEN + value_col)

    print(Fore.CYAN + "  " + "─" * 52)

    # ── Шаг 2: пользователь выбирает поля ────────────────────────────────────
    print(Fore.WHITE + "  Введите номера полей через пробел (например: 1 3 5)")
    raw = input(Fore.YELLOW + "  Ваш выбор (или «all» для всех): ").strip().lower()

    if not raw:
        print(Fore.RED + "Ничего не выбрано.")
        return

    if raw == "all":
        # «all» — берём все поля
        chosen_indices = list(range(1, len(WEATHER_FIELDS) + 1))
    else:
        # Парсим введённые номера; игнорируем нечисловые токены
        chosen_indices = []
        for token in raw.split():
            if token.isdigit():
                num = int(token)
                if 1 <= num <= len(WEATHER_FIELDS):
                    chosen_indices.append(num)
                else:
                    print(Fore.YELLOW + f"  Поле №{num} не существует — пропускаю.")
            else:
                print(Fore.YELLOW + f"  «{token}» — не число, пропускаю.")

    if not chosen_indices:
        print(Fore.RED + "Ни одного корректного номера не введено.")
        return

    # ── Шаг 3: выводим выбранные поля ────────────────────────────────────────
    print(Fore.CYAN + Style.BRIGHT + f"\n  Выбранные поля для «{weather.get('name', city)}»:")
    print(Fore.CYAN + "  " + "─" * 40)

    for idx in chosen_indices:
        # extracted хранит индексы с 1, поэтому вычитаем 1
        _, label, value, unit = extracted[idx - 1]
        value_str = f"{value} {unit}".strip()
        print(Fore.WHITE + f"  {label:<30}" + Fore.GREEN + Style.BRIGHT + value_str)

    print()   # пустая строка для отступа перед меню


def _mode_forecast() -> None:
    """
    Режим 4: прогноз на 5 дней по названию города.

    Шаги:
      1. Запрашиваем город.
      2. Получаем координаты через Geocoding API.
      3. Получаем прогноз через Forecast API (40 точек, шаг 3 ч).
      4. Группируем по дням и выводим мин/макс температуры и описание.
    """
    city = input(Fore.YELLOW + "Введите название города: ").strip()
    if not city:
        print(Fore.RED + "Название города не может быть пустым.")
        return

    print(Fore.WHITE + "Определяю координаты...")
    try:
        lat, lon, found_name, found_country = get_coordinates(city)
    except WeatherError as err:
        print(Fore.RED + str(err))
        return

    print(Fore.WHITE + f"Найден город: " + Fore.CYAN + Style.BRIGHT + f"{found_name}, {found_country}")
    confirm = input(Fore.YELLOW + "Это правильный город? [y/n]: ").strip().lower()
    if confirm != "y":
        print(Fore.WHITE + "Отменено. Попробуйте другое название.")
        return

    print(Fore.WHITE + "Запрашиваю прогноз на 5 дней...")
    data = get_forecast(lat, lon)

    if not data:
        return

    _print_forecast(found_name, data)


def main() -> None:
    """
    Точка входа: бесконечный цикл с меню.

    Пользователь выбирает режим (1/2/3) или выходит (0).
    """
    _check_api_key()  # сразу проверяем ключ — не тратим время пользователя

    while True:
        _print_menu()
        choice = input(Fore.YELLOW + "Ваш выбор (0/1/2/3/4): ").strip()

        if choice == "0":
            print(Fore.CYAN + "До свидания!")
            break
        elif choice == "1":
            _mode_city()
        elif choice == "2":
            _mode_coordinates()
        elif choice == "3":
            _mode_explore_fields()
        elif choice == "4":
            _mode_forecast()
        else:
            print(Fore.RED + "Неверный выбор. Введите 0, 1, 2, 3 или 4.")


# Стандартная точка входа Python: запускаем main() только при прямом запуске файла,
# а не при импорте модуля в другой файл.
if __name__ == "__main__":
    main()
