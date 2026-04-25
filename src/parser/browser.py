import os


def get_chromium_launch_options() -> dict:
    executable_path = os.getenv("PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH", "").strip() or None
    return {
        "headless": True,
        "executable_path": executable_path,
        "args": [
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-setuid-sandbox",
            "--disable-gpu",
        ],
    }
