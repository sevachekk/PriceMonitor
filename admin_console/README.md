# Admin Console

Административный фронтенд для PriceMonitor.

## Локальный запуск без Docker

По умолчанию `config.js` настроен на локальный backend:

```text
http://localhost:8000
```

Запуск:

```bash
cd admin_console
python3 -m http.server 8081
```

После этого откройте:

- [http://localhost:8081](http://localhost:8081)

## Production-запуск

На сервере отдельный контейнер для фронтенда не нужен:

- `admin_console` отдаётся из FastAPI-контейнера как статический frontend
- API и панель работают через один origin

То есть после `docker compose up --build -d` панель будет доступна на том же адресе, что и backend.
