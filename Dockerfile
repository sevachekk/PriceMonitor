FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 \
    PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/usr/bin/chromium

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    tar \
    chromium \
    fonts-liberation \
    libasound2 \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libcups2 \
    libdbus-1-3 \
    libdrm2 \
    libgbm1 \
    libglib2.0-0 \
    libnspr4 \
    libnss3 \
    libx11-6 \
    libx11-xcb1 \
    libxcb1 \
    libxcomposite1 \
    libxdamage1 \
    libxext6 \
    libxfixes3 \
    libxkbcommon0 \
    libxrandr2 \
    xdg-utils \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir --upgrade pip

COPY pyproject.toml README.md ./

RUN pip install --no-cache-dir \
    "aiohttp>=3.13.5" \
    "aiosmtplib>=5.1.0" \
    "aiosqlite>=0.22.1" \
    "asyncpg>=0.31.0" \
    "bs4>=0.0.2" \
    "celery>=5.6.2" \
    "fastapi>=0.129.0" \
    "greenlet>=3.3.1" \
    "h2>=4.3.0" \
    "httpx>=0.28.1" \
    "numpy>=2.4.2" \
    "playwright>=1.58.0" \
    "pydantic>=2.12.5" \
    "pydantic-settings>=2.12.0" \
    "python-multipart>=0.0.22" \
    "redis>=7.1.1" \
    "requests>=2.33.1" \
    "sqlalchemy>=2.0.46" \
    "uvicorn>=0.40.0"

COPY . .

RUN mkdir -p /app/cookies /app/data/backups /app/src/celerybeat-data && \
    chmod +x /app/src/scripts/docker_entrypoint.sh

WORKDIR /app/src

ENTRYPOINT ["/app/src/scripts/docker_entrypoint.sh"]
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
