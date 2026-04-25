import base64
import os
from pathlib import Path


COOKIE_SOURCES = {
    "cookie_wb.txt": ("COOKIE_WB_BASE64", "COOKIE_WB_CONTENT"),
    "cookie_lemana.txt": ("COOKIE_LEMANA_BASE64", "COOKIE_LEMANA_CONTENT"),
    "cookie_ozon.txt": ("COOKIE_OZON_BASE64", "COOKIE_OZON_CONTENT"),
}


def _decode_cookie_content(base64_value: str | None, raw_value: str | None) -> str | None:
    if base64_value:
        return base64.b64decode(base64_value).decode("utf-8")
    if raw_value:
        return raw_value
    return None


def materialize_cookie_files() -> None:
    cookies_dir = Path(os.getenv("COOKIES_DIR", "/app/cookies"))
    cookies_dir.mkdir(parents=True, exist_ok=True)

    for filename, (base64_env, raw_env) in COOKIE_SOURCES.items():
        payload = _decode_cookie_content(os.getenv(base64_env), os.getenv(raw_env))
        if not payload:
            continue
        (cookies_dir / filename).write_text(payload, encoding="utf-8")


def ensure_runtime_directories() -> None:
    Path(os.getenv("BACKUP_DIR", "/app/data/backups")).mkdir(parents=True, exist_ok=True)
    Path(os.getenv("COOKIES_DIR", "/app/cookies")).mkdir(parents=True, exist_ok=True)


if __name__ == "__main__":
    ensure_runtime_directories()
    materialize_cookie_files()
