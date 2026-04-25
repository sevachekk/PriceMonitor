import os
import re
import socket
import subprocess
import sys
import time


NOISY_PATTERNS = (
    "registering with secret key",
    "registration successful",
    "starting xtunnel http tunnel",
    "connected",
    "connection established",
    "reconnected",
    "tunnel established",
    "tunnel connected",
    "heartbeat",
)


def normalize_line(line: str) -> str:
    line = re.sub(r"\x1b\[[0-9;]*m", "", line)
    line = re.sub(r"^\[[^\]]+\]\s*", "", line)
    return line.strip()


def should_dedupe(line: str) -> bool:
    lowered = line.lower()
    return any(pattern in lowered for pattern in NOISY_PATTERNS)


def is_status_block_start(line: str) -> bool:
    return line.lower().startswith("xtunnel v")


def is_status_block_end(line: str) -> bool:
    return line.lower() == "press ctrl+c to stop"


def flush_status_block(block_lines: list[str], printed_status_block: bool) -> bool:
    if not block_lines:
        return printed_status_block

    if not printed_status_block:
        for block_line in block_lines:
            print(block_line, flush=True)
        return True

    return printed_status_block


def wait_for_backend(host: str, port: int, timeout_seconds: float = 120.0) -> None:
    deadline = time.time() + timeout_seconds
    last_error: Exception | None = None

    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=2.0):
                return
        except OSError as exc:
            last_error = exc
            time.sleep(1.0)

    raise TimeoutError(
        f"Backend {host}:{port} did not become ready within {timeout_seconds} seconds"
    ) from last_error


def stream_process(cmd: list[str], seen_messages: set[str]) -> int:
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    assert process.stdout is not None
    status_block_lines: list[str] = []
    collecting_status_block = False
    printed_status_block = False

    for raw_line in process.stdout:
        line = normalize_line(raw_line)
        if not line:
            continue

        if collecting_status_block:
            status_block_lines.append(line)
            if is_status_block_end(line):
                printed_status_block = flush_status_block(status_block_lines, printed_status_block)
                status_block_lines = []
                collecting_status_block = False
            continue

        if is_status_block_start(line):
            collecting_status_block = True
            status_block_lines = [line]
            continue

        if should_dedupe(line):
            dedupe_key = line.lower()
            if dedupe_key in seen_messages:
                continue
            seen_messages.add(dedupe_key)

        print(line, flush=True)

    if collecting_status_block or status_block_lines:
        flush_status_block(status_block_lines, printed_status_block)

    return process.wait()


def main() -> int:
    xtunnel_key = os.getenv("XTUNNEL_KEY")
    if not xtunnel_key:
        print("XTUNNEL_KEY is not set", file=sys.stderr, flush=True)
        return 1

    backend_host = os.getenv("XTUNNEL_BACKEND_HOST", "127.0.0.1")
    xtunnel_port = os.getenv("XTUNNEL_PORT", "8000")
    backend_port = int(xtunnel_port)
    seen_messages: set[str] = set()

    print(f"Waiting for backend {backend_host}:{backend_port}...", flush=True)
    wait_for_backend(backend_host, backend_port)

    print("Activating xTunnel...", flush=True)
    register_code = stream_process(["xtunnel", "register", xtunnel_key], seen_messages)
    if register_code != 0:
        print("xTunnel activation returned a non-zero exit code, continuing to tunnel startup.", flush=True)

    start_line = f"Starting xTunnel HTTP tunnel for localhost:{xtunnel_port}"
    seen_messages.add(start_line.lower())
    print(start_line, flush=True)

    return stream_process(["xtunnel", "http", xtunnel_port], seen_messages)


if __name__ == "__main__":
    raise SystemExit(main())
