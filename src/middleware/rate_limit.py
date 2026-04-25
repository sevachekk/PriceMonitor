from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from services.admin_auth import decode_access_token
from settings.config import get_settings


settings = get_settings()


class InMemoryRateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app):
        super().__init__(app)
        self._buckets: dict[str, deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if not self._should_limit(path):
            return await call_next(request)

        limit, window_seconds = self._resolve_rule(path)
        identifier = self._resolve_identifier(request)
        bucket_key = f"{path}:{identifier}:{window_seconds}:{limit}"

        async with self._lock:
            timestamps = self._buckets[bucket_key]
            now = time.monotonic()
            while timestamps and now - timestamps[0] >= window_seconds:
                timestamps.popleft()

            if len(timestamps) >= limit:
                retry_after = max(1, int(window_seconds - (now - timestamps[0])))
                return JSONResponse(
                    status_code=429,
                    content={
                        "detail": "Rate limit exceeded",
                        "retry_after_seconds": retry_after,
                    },
                    headers={"Retry-After": str(retry_after)},
                )

            timestamps.append(now)

        return await call_next(request)

    @staticmethod
    def _should_limit(path: str) -> bool:
        if path == "/admin-api/jobs/run-due":
            return False
        return path.startswith("/admin-api") or path.startswith("/api/v1")

    @staticmethod
    def _resolve_rule(path: str) -> tuple[int, int]:
        login_paths = {"/admin-api/auth/login", "/api/v1/auth/login"}
        if path in login_paths:
            return settings.API_AUTH_RATE_LIMIT_REQUESTS, settings.API_AUTH_RATE_LIMIT_WINDOW_SECONDS
        return settings.API_RATE_LIMIT_REQUESTS, settings.API_RATE_LIMIT_WINDOW_SECONDS

    @staticmethod
    def _resolve_identifier(request: Request) -> str:
        auth_header = request.headers.get("authorization", "")
        if auth_header.lower().startswith("bearer "):
            token = auth_header.split(" ", 1)[1].strip()
            try:
                payload = decode_access_token(token)
            except Exception:  # noqa: BLE001
                pass
            else:
                return f"user:{payload.get('sub', 'unknown')}"

        client_host = request.client.host if request.client else "unknown"
        forwarded_for = request.headers.get("x-forwarded-for")
        if forwarded_for:
            client_host = forwarded_for.split(",", 1)[0].strip() or client_host
        return f"ip:{client_host}"
