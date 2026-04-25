# PriceMonitor

Полностью dockerized-проект для серверного деплоя:

- `fastapi` — backend, REST/API слой и выдача административного фронтенда
- `celery-worker` — фоновые задачи
- `celery-beat` — запуск периодических задач
- `redis` — брокер Celery

Туннелирование из проекта удалено. Фронтенд теперь отдаётся самим backend и работает через тот же origin.

## Быстрый старт

1. Создайте `.env` по примеру `.env.example`
2. Заполните реальные переменные окружения
3. Запустите:

```bash
docker compose up --build -d
```

По умолчанию приложение будет доступно на:

```text
http://localhost:8080
```

Swagger:

```text
http://localhost:8080/docs
```

## Что важно для продакшена

- bootstrap super-admin создаётся автоматически при первом старте:
  - `ADMIN_BOOTSTRAP_USERNAME`
  - `ADMIN_BOOTSTRAP_PASSWORD`
  - `ADMIN_BOOTSTRAP_FULL_NAME`
- резервные копии сохраняются в `BACKUP_DIR`
- фронтенд уже привязан к backend через один контейнер FastAPI, отдельный API URL не нужен
- bind mounts не требуются: это удобно для Timeweb App Platform
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

- первый сервис в `docker-compose.yml` — это `fastapi`, чтобы именно он был основным публичным сервисом
- хост-порт по умолчанию не `80`, а `8080`
- из compose убраны `volumes`
- не используется `network_mode: host`

Документация Timeweb:

- [Деплой из Docker Compose](https://timeweb.cloud/docs/apps/deploying-with-docker-compose)
- [Docker Compose в Apps](https://timeweb.cloud/blog/docker-compose-v-apps)
