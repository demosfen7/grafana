# Weather App — тестовый проект для Grafana/Loki

Погодное приложение через [OpenWeather API](https://openweathermap.org/) в двух видах — консольном и веб —
которое служит подопытным для стека логирования [lokigrafana](https://github.com/demosfen7/lokigrafana).

## Ссылки

| Что | Где |
|---|---|
| Веб-интерфейс (в браузере) | https://vibecoding.aithinglab.com/grafana/ |
| Этот репозиторий | https://github.com/demosfen7/grafana |
| Стек Grafana + Loki (логи этого приложения) | https://vibecoding.aithinglab.com/lokigrafana/ |
| Репозиторий стека логирования | https://github.com/demosfen7/lokigrafana |
| Соседний учебный проект на том же поддомене | https://vibecoding.aithinglab.com/gitflow/ · [репозиторий](https://github.com/demosfen7/Gitflow) |
| Получить свой ключ OpenWeather | https://openweathermap.org/ → My Profile → API keys |

---

## Что здесь два сервиса

Оба описаны в [`deploy/docker-compose.yml`](deploy/docker-compose.yml) и деплоятся вместе.

### 1. `vibecoding-grafana` — консольное приложение (`weather_app.py`)

- Обычный CLI с меню (город / координаты / поля ответа / прогноз), без HTTP.
- В контейнере держится живым через `stdin_open`/`tty` (иначе `input()` без терминала уходил бы в краш-луп).
- Подключиться к меню на сервере:
  ```
  ssh hetzner-vibecoding
  docker attach vibecoding-grafana
  # выйти без остановки контейнера: Ctrl+P, затем Ctrl+Q
  ```
- API-ключ читает из `.env` рядом с `docker-compose.yml` **на сервере** (не путать с локальным `.env` в этой папке — они разные файлы, локальный на сервер не попадает).
- Каждый запуск/запрос/ошибка логируются через [`loki_logging.py`](loki_logging.py) — см. раздел про логи ниже.

### 2. `web` — статическая страница (`web/index.html`)

- Тот же функционал, но в браузере: JS напрямую дёргает OpenWeather API.
- API-ключ **не хранится на сервере** — при первом заходе браузер спросит его через `prompt()` и сохранит в `localStorage` того браузера, где вводили. У каждого посетителя свой ключ, ключ в исходниках страницы не виден.
- Раздаётся через `nginx:alpine`, публикуется наружу через Caddy на `/grafana/`.

---

## Логи → Loki → Grafana

`weather_app.py` при заданном `LOKI_URL` пушит записи (`INFO`/`WARNING`/`ERROR`) напрямую в Loki по HTTP —
без Promtail и без Docker logging-плагина (под rootless Docker Promtail не смог бы прочитать файлы логов
других контейнеров — разные UID). Логика — в [`loki_logging.py`](loki_logging.py).

- Лейблы потока: `app="weather-cli"`, `job="weather-cli"` (второй — чтобы работали готовые community-дашборды,
  которые обычно завязаны на `$job`).
- Смотреть логи: https://vibecoding.aithinglab.com/lokigrafana/ → Explore → датасорс Loki → запрос `{job="weather-cli"}`,
  либо через уже импортированный дашборд `sadlil-loki-apps-dashboard`.
- Что логируется: старт приложения, выход из меню, каждый успешный запрос погоды (город + температура),
  сетевые ошибки, ответ 401 (невалидный ключ), отсутствие `API_KEY`.

---

## Сервер: пути и доступ

| Что | Значение |
|---|---|
| SSH | `ssh hetzner-vibecoding` (алиас, ключ `~/.ssh/vibecoding_hetzner`, пользователь без sudo, свой rootless Docker) |
| Папка деплоя | `/opt/vibecoding.aithinglab.com/grafana/` |
| `.env` на сервере | `/opt/vibecoding.aithinglab.com/grafana/.env` — туда руками дописывается `API_KEY=...` (не коммитится, CI его не трогает, только обновляет строку `IMAGE=`) |
| Docker-сеть | `loki-net` (внешняя, общая с проектом `lokigrafana` — так `vibecoding-grafana` достаёт до `loki` по имени сервиса) |
| Порт наружу | `8092` (только веб-страница; у CLI-контейнера порта нет) — проброшен через `172.28.0.1:8092` в общую сеть Caddy, разрешён в `ufw` только из неё |
| Пересоздать после правки `.env` | `cd /opt/vibecoding.aithinglab.com/grafana && docker compose up -d --force-recreate` (просто `restart` не подхватит новые переменные) |

Общий Caddy-роутинг для всего поддомена лежит на сервере в `/opt/briefgenerator/deploy/conf.d/vibecoding.aithinglab.com.caddy`
(правится только вручную, CI его не трогает). Актуальная копия для справки — [`deploy/vibecoding.aithinglab.com.caddy`](deploy/vibecoding.aithinglab.com.caddy) в этом репозитории.

---

## CI/CD

[`.github/workflows/deploy.yml`](.github/workflows/deploy.yml): при пуше в `master` собирает образ, пушит в GHCR
(`ghcr.io/demosfen7/grafana`), копирует `docker-compose.yml` и `web/index.html` на сервер, поднимает контейнеры.

Секреты репозитория (Settings → Secrets → Actions):

| Секрет | Значение |
|---|---|
| `SSH_HOST` | `46.225.73.78` |
| `SSH_USER` | `vibecoding` |
| `SSH_PORT` | `22` |
| `SSH_KEY` | содержимое `~/.ssh/vibecoding_hetzner` |

---

## Локальный запуск CLI

```powershell
# 1. Перейди в папку проекта
cd "c:\путь\к\папке\Grafana"

# 2. Создай виртуальное окружение и активируй его
python -m venv venv
venv\Scripts\activate

# 3. Установи зависимости
pip install -r requirements.txt

# 4. Скопируй .env.example в .env и впиши свой ключ
copy .env.example .env

# 5. Запусти
python weather_app.py
```

Локально `LOKI_URL` не задан — логи никуда не пушатся, приложение работает как обычный CLI.

---

## Структура проекта

```
Grafana/
├── weather_app.py               # CLI: меню, запросы к OpenWeather, кэш
├── http_client.py               # универсальный HTTP-клиент (учебный модуль, самим weather_app не используется)
├── loki_logging.py              # push-логирование в Loki (LokiHandler)
├── web/index.html               # веб-версия того же функционала (ключ — в localStorage браузера)
├── Dockerfile                   # образ для CLI-сервиса (weather_app.py)
├── deploy/
│   ├── docker-compose.yml       # оба сервиса: CLI + web
│   └── vibecoding.aithinglab.com.caddy   # копия общего Caddy-роутинга — для справки, не для CI
├── .github/workflows/deploy.yml # сборка образа + деплой по SSH
├── .env.example                 # шаблон переменных (реальный .env — не в репозитории)
└── requirements.txt
```

---

## Использование CLI

При запуске появится меню:

```
╔══════════════════════════════════╗
║     ПОГОДА — OpenWeather API     ║
╚══════════════════════════════════╝
  1 — Погода по названию города
  2 — Погода по координатам (lat, lon)
  3 — Выбрать конкретные поля из ответа API
  4 — Прогноз на 5 дней
  0 — Выход
```

## Зависимости

| Пакет          | Назначение                            |
|----------------|---------------------------------------|
| `requests`     | HTTP-запросы к OpenWeather API и к Loki push API |
| `python-dotenv`| Загрузка API-ключа из файла `.env`    |
| `colorama`     | Цветной вывод в терминале             |
