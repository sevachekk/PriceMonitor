import asyncio
import ssl
import certifi
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import Header
import aiosmtplib
from html import escape

from settings.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

USERNAME = settings.EMAIL
PASSWORD = (settings.EMAIL_PASSWORD or "").replace(" ", "")

SMTP_HOST = "smtp.gmail.com"
SMTP_TIMEOUT_SECONDS = 15
SMTP_TRANSPORTS = (
    {"port": 465, "use_tls": True, "start_tls": False},
    {"port": 587, "use_tls": False, "start_tls": True},
)

# создаём безопасный SSLContext с использованием certifi
ssl_context = ssl.create_default_context(cafile=certifi.where())


async def _create_smtp_connection():
    """
    Создаёт и логинит SMTP-подключение (aiosmtplib.SMTP).
    """
    transport_errors: list[str] = []

    for transport in SMTP_TRANSPORTS:
        smtp = aiosmtplib.SMTP(
            hostname=SMTP_HOST,
            port=transport["port"],
            use_tls=transport["use_tls"],
            start_tls=transport["start_tls"],
            tls_context=ssl_context,
            timeout=SMTP_TIMEOUT_SECONDS,
        )
        try:
            await smtp.connect()
            await smtp.login(USERNAME, PASSWORD)
            logger.info(
                "SMTP connection established via %s:%s (use_tls=%s, start_tls=%s)",
                SMTP_HOST,
                transport["port"],
                transport["use_tls"],
                transport["start_tls"],
            )
            return smtp
        except Exception as exc:
            transport_errors.append(
                f"{SMTP_HOST}:{transport['port']} failed with {type(exc).__name__}: {exc}"
            )
            logger.warning(
                "SMTP transport failed via %s:%s",
                SMTP_HOST,
                transport["port"],
                exc_info=exc,
            )
            try:
                await smtp.quit()
            except Exception:
                pass

    raise RuntimeError(
        "Не удалось установить SMTP-соединение. "
        + " | ".join(transport_errors)
    )


async def send_with_smtp(smtp, to_email: str, subject: str, plain_body: str, html_body: str | None = None):
    """
    Отправляет одно письмо через уже созданное smtp-подключение.
    Если html_body передан — формируем multipart/alternative с plain и html.
    """
    if html_body:
        msg = MIMEMultipart("alternative")
        # plain part
        part_plain = MIMEText(plain_body or "", "plain", "utf-8")
        # html part
        part_html = MIMEText(html_body or "", "html", "utf-8")
        msg.attach(part_plain)
        msg.attach(part_html)
    else:
        msg = MIMEText(plain_body or "", "plain", "utf-8")

    # Заголовки
    msg["Subject"] = Header(subject, "utf-8")
    msg["From"] = USERNAME
    msg["To"] = to_email

    # Отправляем
    await smtp.send_message(msg)


async def send_bulk_smtp_pool(
    recipients: list[str],
    subject: str,
    body: str,
    html_body: str | None = None,
    concurrency: int = 5,
    batch_sleep: float = 0.5,
):
    """
    Отправляет письма параллельно с пулом smtp-подключений.
    - recipients: список email-адресов (каждому отправляется отдельное письмо).
    - body: plain текст.
    - html_body: если передан — будет отправлен как HTML-часть в multipart/alternative.
    - concurrency: размер пула одновременно открытых SMTP-соединений.
    - batch_sleep: пауза между батчами задач (чтобы не перегружать smtp-сервер).
    Возвращает список булевых значений (True/False) по каждому адресу в том же порядке.
    """
    if not recipients:
        return []

    if not USERNAME or not PASSWORD:
        raise RuntimeError("EMAIL / EMAIL_PASSWORD не заданы для отправки оповещений.")

    # Создаём пул подключений
    pool: asyncio.Queue[aiosmtplib.SMTP] = asyncio.Queue()
    connections = []
    try:
        for _ in range(concurrency):
            conn = await _create_smtp_connection()
            connections.append(conn)
            await pool.put(conn)
    except Exception as e:
        # Если не удалось создать пул — закрываем уже открытые и пробрасываем ошибку
        for c in connections:
            try:
                await c.quit()
            except Exception:
                pass
        raise RuntimeError(f"Не удалось инициализировать SMTP-пул: {e}") from e

    async def worker(email: str) -> bool:
        smtp = await pool.get()
        try:
            await send_with_smtp(smtp, email, subject, body, html_body=html_body)
            return True
        except Exception as e:
            # Логируем ошибку — в проде можно заменить на logger
            print(f"Error sending to {email}: {e}")
            return False
        finally:
            # Возвращаем соединение в пул, если оно ещё открыто.
            try:
                # aiosmtplib.SMTP не имеет is_connected публичного атрибута, ловим ошибки при put
                await pool.put(smtp)
            except Exception:
                # Если не получилось вернуть соединение в пул — пытаемся закрыть
                try:
                    await smtp.quit()
                except Exception:
                    pass

    # Создаём задачи (все сразу) — но будем их запускать батчами через gather
    tasks = [asyncio.create_task(worker(email)) for email in recipients]

    results: list[bool] = []
    BATCH_SIZE = 100
    try:
        for i in range(0, len(tasks), BATCH_SIZE):
            batch = tasks[i:i + BATCH_SIZE]
            # ждём завершения батча
            batch_results = await asyncio.gather(*batch)
            results.extend(batch_results)
            await asyncio.sleep(batch_sleep)
    finally:
        # В конце всегда корректно закрываем все соединения, которые остались в пуле
        for _ in range(concurrency):
            try:
                conn = await pool.get()
            except Exception:
                continue
            try:
                await conn.quit()
            except Exception:
                # если соединение уже закрыто — игнорируем
                pass

    return results

def format_alert_email(
    alert,
    alert_method: str,
    competitor_name: str,
    product_id: int,
    product_name: str | None,
    current_price: float,
    recent_prices: list[float],
    detection_info: dict,
    prod_url: str | None = None,
) -> tuple[str, str]:
    """
    Возвращает (plain_text, html_text) - оба на русском языке.
    HTML содержит и <style> (для клиентов, которые его читают), и inline-стили для совместимости.
    """
    prod_name = product_name or "-"
    # plain (оставляем как раньше)
    header = f"Оповещение по цене — продукт {product_id} ({prod_name})\n"
    intro = (
        f"Тип оповещения: {getattr(alert.type, 'name', str(alert.type))} (id: {alert.id})\n"
        f"Конкурент: {competitor_name}\n"
        f"Текущая цена: {current_price}\n\n"
    )
    recent_list_plain = "Последние цены конкурента (старые → новые):\n"
    for i, p in enumerate(recent_prices, start=1):
        recent_list_plain += f"  {i}. {p}\n"

    # краткие детект-инфо (plain)
    det_plain_lines = []
    if alert_method == "zscore":
        det_plain_lines.append(f"z-score: {detection_info.get('z')}")
        det_plain_lines.append(f"mean: {detection_info.get('mean')}")
        det_plain_lines.append(f"std: {detection_info.get('std')}")
        det_plain_lines.append(f"threshold: {detection_info.get('threshold')}")
    elif alert_method == "pct_change":
        det_plain_lines.append(f"percent change: {detection_info.get('pct_change')}")
        det_plain_lines.append(f"baseline ({detection_info.get('baseline_type')}): {detection_info.get('baseline')}")
        det_plain_lines.append(f"threshold_pct: {detection_info.get('threshold_pct')}")
        det_plain_lines.append(f"direction: {detection_info.get('direction')}")
    elif alert_method == "below_threshold":
        mode = detection_info.get("mode")
        det_plain_lines.append(f"mode: {mode}")
        if mode == "absolute":
            det_plain_lines.append(f"threshold_value: {detection_info.get('threshold_value')}")
        else:
            det_plain_lines.append(f"baseline: {detection_info.get('baseline')}")
            det_plain_lines.append(f"threshold_pct: {detection_info.get('threshold_pct')}")
            det_plain_lines.append(f"threshold_abs: {detection_info.get('threshold_abs')}")
    det_plain = "\n".join(det_plain_lines)

    footer_plain = "\n---\nАвтоматическое уведомление. Для изменения параметров — обновите alert в системе."

    plain = header + intro + recent_list_plain + "\nДетектирование:\n" + det_plain + "\n\nРекомендации:\n"
    if alert_method == "zscore":
        plain += "- Проверьте корректность данных парсера/скрейпера.\n- Проверьте историю изменений на странице конкурента.\n"
    elif alert_method == "pct_change":
        plain += "- Убедитесь в причинах процентного изменения (акция/ошибка).\n- Подумайте об изменении baseline/threshold.\n"
    elif alert_method == "below_threshold":
        plain += "- Проверьте наличие скидок/акций у конкурента.\n- Оцените необходимость ответных действий.\n"
    plain += footer_plain

    # --------------------------
    # HTML-часть (красиво, но email-safe)
    # --------------------------
    # Минимальный набор CSS (в теге <style>) и дубляж inline-стилями для совместимости.
    safe_prod_name = escape(str(prod_name))
    safe_competitor = escape(str(competitor_name))
    safe_alert_type = escape(getattr(alert.type, "name", str(alert.type)))

    # Собираем список последних цен как HTML-лист (escape не нужен для числа, но на всякий случай)
    recent_items_html = "".join(f"<li style='padding:4px 0;font-size:14px;color:#222;'>{escape(str(p))}</li>" for p in recent_prices)

    # Формируем таблицу метрик в зависимости от типа
    metrics_rows = ""
    if alert_method == "zscore":
        z = detection_info.get("z")
        mu = detection_info.get("mean")
        sigma = detection_info.get("std")
        threshold = detection_info.get("threshold")
        metrics_rows += f"<tr><td>z-score</td><td>{z}</td></tr>"
        metrics_rows += f"<tr><td>mean</td><td>{mu}</td></tr>"
        metrics_rows += f"<tr><td>std</td><td>{sigma}</td></tr>"
        metrics_rows += f"<tr><td>threshold</td><td>{threshold}</td></tr>"
    elif alert_method == "pct_change":
        pct = detection_info.get("pct_change")
        baseline = detection_info.get("baseline")
        baseline_type = detection_info.get("baseline_type")
        threshold_pct = detection_info.get("threshold_pct")
        direction = detection_info.get("direction")
        metrics_rows += f"<tr><td>percent change</td><td>{pct:.4f}%</td></tr>"
        metrics_rows += f"<tr><td>baseline ({escape(str(baseline_type))})</td><td>{baseline}</td></tr>"
        metrics_rows += f"<tr><td>threshold_pct</td><td>{threshold_pct}%</td></tr>"
        metrics_rows += f"<tr><td>direction</td><td>{escape(str(direction))}</td></tr>"
    elif alert_method == "below_threshold":
        mode = detection_info.get("mode")
        metrics_rows += f"<tr><td>mode</td><td>{escape(str(mode))}</td></tr>"
        if mode == "absolute":
            tv = detection_info.get("threshold_value")
            metrics_rows += f"<tr><td>threshold_value</td><td>{tv}</td></tr>"
        else:
            base = detection_info.get("baseline")
            tp = detection_info.get("threshold_pct")
            ta = detection_info.get("threshold_abs")
            metrics_rows += f"<tr><td>baseline</td><td>{base}</td></tr>"
            metrics_rows += f"<tr><td>threshold_pct</td><td>{tp}%</td></tr>"
            metrics_rows += f"<tr><td>threshold_abs</td><td>{ta}</td></tr>"

    # Рекомендации HTML
    recs_html = ""
    if alert_method == "zscore":
        recs_html = (
            "<li>Проверьте корректность данных парсера/скрейпера.</li>"
            "<li>Проверьте историю изменений на странице конкурента.</li>"
            "<li>Если часто ложные срабатывания — уменьшите чувствительность (увеличьте threshold или lookback).</li>"
        )
    elif alert_method == "pct_change":
        recs_html = (
            "<li>Проверьте, ожидаемо ли изменение (акция или ошибка парсинга).</li>"
            "<li>Если нет — проверьте источник данных у конкурента.</li>"
            "<li>Подумайте об изменении baseline (mean/prev) или порога threshold_pct.</li>"
        )
    elif alert_method == "below_threshold":
        recs_html = (
            "<li>Проверьте страницу конкурента на наличие скидок/акций.</li>"
            "<li>Сопоставьте с собственной политикой цен — возможно требуется ответная акция.</li>"
        )

    # Inline-стили для основных элементов (дублируют <style>)
    card_bg = "#ffffff"
    accent = "#1e88e5"  # приятный синий
    muted = "#6b7280"
    border = "#e6e6e9"

    html = f"""\
<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width,initial-scale=1" />
    <style>
      /* Небольшая часть CSS: большинство клиентов поддерживает базовые правила */
      .card {{
        max-width: 680px;
        margin: 6px auto;
        background: {card_bg};
        border: 1px solid {border};
        border-radius: 8px;
        padding: 18px;
      }}
      .header {{
        display:flex;
        align-items:center;
        justify-content:space-between;
        gap:12px;
      }}
      .title {{
        font-size:18px;
        margin:0;
        color:#111;
      }}
      .badge {{
        background:{accent};
        color:white;
        padding:6px 10px;
        border-radius:20px;
        font-size:13px;
        font-weight:600;
      }}
      .price {{
        font-size:20px;
        font-weight:700;
        color:#111;
        margin:6px 0 0 0;
      }}
      .muted {{ color: {muted}; font-size:13px; }}
      .metrics td {{ padding:8px 10px; border-top:1px solid {border}; font-size:14px; }}
      .metrics td:first-child {{ color:#333; width:45%; }}
      .btn {{
        display:inline-block;
        text-decoration:none;
        padding:8px 12px;
        border-radius:6px;
        background:{accent};
        color:#fff;
        font-weight:600;
        font-size:14px;
      }}
      @media (max-width:500px) {{
        .card {{ padding:12px; }}
        .title {{ font-size:16px; }}
      }}
    </style>
  </head>
  <body style="margin:0; font-family: Arial, Helvetica, sans-serif; background:#f5f6f8; padding:12px;">
    <div class="card" style="background:{card_bg}; border:1px solid {border}; border-radius:8px; padding:18px; max-width:680px; margin:8px auto;">
      <div class="header" style="display:flex; align-items:center; justify-content:space-between; gap:12px;">
        <div style="flex:1;">
          <h1 class="title" style="font-size:18px; margin:0 0 4px 0; color:#111;">Оповещение по цене — продукт {product_id}</h1>
          <div style="font-size:13px; color:{muted}; margin-bottom:6px;">{safe_prod_name} · Тип: <strong style="color:#111;">{safe_alert_type}</strong> · id: {alert.id}</div>
          <div style="font-size:14px; color:{muted};">Конкурент: <strong style="color:#111;">{safe_competitor}</strong></div>
        </div>
        <div style="text-align:right; min-width:160px;">
          <div class="badge" style="background:{accent}; color:#fff; display:inline-block; padding:6px 10px; border-radius:20px; font-weight:700;">Текущая цена</div>
          <div class="price" style="font-size:20px; font-weight:700; margin-top:8px;">{current_price}</div>
        </div>
      </div>

      <div style="margin-top:14px;">
        <h3 style="margin:0 0 8px 0; font-size:15px;">Последние цены конкурента</h3>
        <div style="background:#fbfbfd; border:1px solid {border}; border-radius:6px; padding:10px;">
          <ol style="margin:0 0 0 18px; padding:0;">{recent_items_html}</ol>
        </div>
      </div>

      <div style="margin-top:12px;">
        <h3 style="margin:0 0 8px 0; font-size:15px;">Параметры детектирования</h3>
        <table class="metrics" role="presentation" style="width:100%; border-collapse:collapse; margin-top:6px;">
          <tbody>
            {metrics_rows}
          </tbody>
        </table>
      </div>

      <div style="margin-top:12px; display:flex; gap:12px; align-items:flex-start; justify-content:space-between; flex-wrap:wrap;">
        <div style="flex:1; min-width:220px;">
          <h4 style="margin:0 0 6px 0; font-size:14px;">Рекомендации</h4>
          <ul style="margin:0 0 0 18px; padding:0 0 0 0; color:#222;">
            {recs_html}
          </ul>
        </div>

        <!-- Пример кнопки (если есть URL продукта, можно заменить # на фактическую ссылку) -->
        <div style="min-width:160px; text-align:right;">
          <a href="{prod_url}" class="btn" style="display:inline-block; text-decoration:none; padding:8px 12px; border-radius:6px; background:{accent}; color:#fff;">Перейти к продукту</a>
        </div>
      </div>

      <div style="margin-top:14px; color:{muted}; font-size:12px;">
        Автоматическое уведомление. Для изменения параметров оповещений — обновите alert (id: {alert.id}).
      </div>
    </div>
  </body>
</html>
"""

    return plain, html


async def send_alert_email(recipients: list[str], subject: str, plain_body: str, html_body: str | None = None):
    """
    Универсальная оболочка для отправки: использует ваш send_bulk_smtp_pool,
    который поддерживает html_body (если вы подключили ранее предложенную версию).
    """
    # при наличии html_body — передаём его отдельным параметром
    if html_body is not None:
        await send_bulk_smtp_pool(recipients=recipients, subject=subject, body=plain_body, html_body=html_body)
    else:
        await send_bulk_smtp_pool(recipients=recipients, subject=subject, body=plain_body)
