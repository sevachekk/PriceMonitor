# Deploy on Timeweb

## Что уже подготовлено

- туннелирование убрано из проекта
- административный фронтенд и API доступны через встроенный `nginx`
- публичный сервис в `docker-compose.yml` — `nginx`
- хост-порт по умолчанию — `80`

Это совместимо с требованиями Timeweb App Platform для Docker Compose:

- [Деплой из Docker Compose](https://timeweb.cloud/docs/apps/deploying-with-docker-compose)

## 1. Подготовьте `.env`

Создайте файл `.env` на основе `.env.example`.

Минимально заполняются:

```env
NGINX_HTTP_PORT=80

DB_URL=postgresql+asyncpg://user:password@host:5432/db
DB_NAME=db
DB_USER=user
DB_PASSWORD=password
DB_HOST=host
DB_PORT=5432

COOKIE_SECRET_KEY=change-me
ADMIN_AUTH_SECRET=change-me
ADMIN_BOOTSTRAP_USERNAME=superadmin
ADMIN_BOOTSTRAP_PASSWORD=change-me
ADMIN_BOOTSTRAP_FULL_NAME=Super Admin
INTERNAL_TASK_SECRET=change-me

EMAIL=alerts@example.com
EMAIL_PASSWORD=change-me
```

## 2. Если нужны cookies парсеров

Передайте их через env в base64-форме:

```env
COOKIE_WB_BASE64=...
COOKIE_LEMANA_BASE64=...
COOKIE_OZON_BASE64=...
```

Пример генерации:

```bash
base64 -i cookies/cookie_wb.txt | tr -d '\n'
```

## 3. Локальная проверка перед деплоем

```bash
docker compose config
docker compose up --build -d
```

После запуска:

- панель: `http://localhost/`
- Swagger: `http://localhost/docs`
- health: `http://localhost/health`

## 4. Деплой в Timeweb App Platform

1. Загрузите проект в git-репозиторий
2. В Timeweb выберите тип приложения `Docker Compose`
3. Подключите репозиторий
4. Проверьте, что в корне есть:
   - `docker-compose.yml`
   - `Dockerfile`
5. Заполните переменные окружения из `.env.example`
6. Запустите деплой

## 5. После деплоя

- панель будет открываться по основному домену приложения
- backend API будет доступен на этом же домене
- `nginx`, `fastapi`, `celery-worker`, `celery-beat` и `redis` поднимутся внутри одного compose-стека

## Вариант для обычного VDS через nginx

Если ты хочешь использовать отдельный системный `nginx` на хосте вместо docker-nginx, оставлен запасной шаблон:

Шаблон конфига:

- [deploy/nginx/pricemonitor.conf](/Users/sevak/Desktop/PriceMonitor/deploy/nginx/pricemonitor.conf)

Шаги:

1. Оставьте docker-приложение на `8080`:

```env
NGINX_HTTP_PORT=8080
```

2. Скопируйте шаблон nginx-конфига на сервер и замените:

- `example.com`
- `www.example.com`

3. Положите конфиг, например, в:

```bash
/etc/nginx/sites-available/pricemonitor
```

4. Включите сайт:

```bash
sudo ln -s /etc/nginx/sites-available/pricemonitor /etc/nginx/sites-enabled/pricemonitor
sudo nginx -t
sudo systemctl reload nginx
```

После этого системный `nginx` будет проксироваться на Docker-приложение на `127.0.0.1:8080`.

## Примечания

- если используешь встроенный docker-nginx, оставь `NGINX_HTTP_PORT=80`
- перед публикацией лучше удалить из локального `.env` старые переменные туннелей и заменить их значениями из нового `.env.example`
