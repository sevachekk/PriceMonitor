# PriceMonitor

Полностью dockerized-проект для серверного деплоя:

- `nginx` — публичный reverse proxy для домена
- `fastapi` — backend, REST/API слой и выдача административного фронтенда
- `celery-worker` — фоновые задачи
- `celery-beat` — запуск периодических задач
- `redis` — брокер Celery

Туннелирование из проекта удалено. Снаружи проект принимает трафик через `nginx`, а внутри Docker-сети он проксирует всё на `fastapi`.

## Быстрый старт

1. Создайте `.env` по примеру `.env.example`
2. Заполните реальные переменные окружения
3. Запустите:

```bash
docker compose up --build -d
```

По умолчанию приложение будет доступно на:

```text
http://localhost
```

Swagger:

```text
http://localhost/docs
```

## Что важно для продакшена

- bootstrap super-admin создаётся автоматически при первом старте:
  - `ADMIN_BOOTSTRAP_USERNAME`
  - `ADMIN_BOOTSTRAP_PASSWORD`
  - `ADMIN_BOOTSTRAP_FULL_NAME`
- резервные копии сохраняются в `BACKUP_DIR`
- `nginx` уже включён в `docker-compose`, отдельный системный nginx не нужен
- SMTP теперь можно настраивать через env:
  - `SMTP_HOST`
  - `SMTP_PORT`
  - `SMTP_USE_TLS`
  - `SMTP_START_TLS`
  - `SMTP_TIMEOUT_SECONDS`

## Cookies без volumes

Если парсерам нужны cookies, их можно передать через env:

- `COOKIE_WB_BASE64`
- `COOKIE_LEMANA_BASE64`
- `COOKIE_OZON_BASE64`

Пример подготовки значения:

```bash
base64 -i cookies/cookie_wb.txt | tr -d '\n'
```

## Timeweb

Проект подготовлен под деплой через Docker Compose в Timeweb App Platform.

Что учёл:

- публичный вход теперь идёт через `nginx`
- по умолчанию `nginx` слушает `80`
- не используется `network_mode: host`

Документация Timeweb:

- [Деплой из Docker Compose](https://timeweb.cloud/docs/apps/deploying-with-docker-compose)
- [Docker Compose в Apps](https://timeweb.cloud/blog/docker-compose-v-apps)
