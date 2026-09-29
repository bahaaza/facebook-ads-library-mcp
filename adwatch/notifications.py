import smtplib
import ssl
from datetime import timedelta
from email.message import EmailMessage

import httpx
from sqlalchemy import select

from adwatch.config import settings
from adwatch.db import now
from adwatch.models import Alert, Delivery


def send(channel: str, item: Alert):
    config = settings()
    link = config.public_url.rstrip("/") + "/?tab=alerts"
    body = f"{item.title}\n\n{item.body}\n\nOpen Adwatch: {link}\nEvent #{item.id}"
    if channel == "email":
        if not config.smtp_host:
            raise RuntimeError("Email configuration was removed.")
        message = EmailMessage()
        message["Subject"] = "[Adwatch] " + item.title
        message["From"] = config.smtp_from
        message["To"] = config.smtp_to
        message["Message-ID"] = f"<adwatch-{item.id}@{config.smtp_from.split('@')[-1]}>"
        message.set_content(body)
        client = smtplib.SMTP_SSL if config.smtp_tls == "ssl" else smtplib.SMTP
        kwargs = {"context": ssl.create_default_context()} if config.smtp_tls == "ssl" else {}
        with client(config.smtp_host, config.smtp_port, timeout=20, **kwargs) as smtp:
            if config.smtp_tls == "starttls":
                smtp.starttls(context=ssl.create_default_context())
            if config.smtp_username:
                smtp.login(config.smtp_username, config.smtp_password)
            smtp.send_message(message)
    elif channel == "telegram":
        if not config.telegram_bot_token:
            raise RuntimeError("Telegram configuration was removed.")
        # URLs are never logged: they contain the bot secret.
        with httpx.Client(timeout=20) as client:
            response = client.post(
                f"https://api.telegram.org/bot{config.telegram_bot_token}/sendMessage",
                json={
                    "chat_id": config.telegram_chat_id,
                    "text": body[:4000],
                    "disable_web_page_preview": True,
                },
            )
            if response.status_code != 200 or not response.json().get("ok"):
                raise RuntimeError(f"Telegram rejected delivery (HTTP {response.status_code}).")
    else:
        raise RuntimeError("Unknown notification channel.")


def deliver_pending(session):
    # Only the elected worker processes the outbox. Persist after every attempt.
    pending = session.scalars(
        select(Delivery)
        .where(Delivery.status == "pending", Delivery.next_attempt_at <= now())
        .order_by(Delivery.id)
        .limit(10)
    ).all()
    for delivery in pending:
        delivery.attempts += 1
        try:
            send(delivery.channel, session.get(Alert, delivery.alert_id))
            delivery.status = "sent"
            delivery.sent_at = now()
            delivery.error = ""
        except Exception as exc:
            delivery.status = "failed" if delivery.attempts >= 5 else "pending"
            delivery.next_attempt_at = now() + timedelta(minutes=min(60, 2**delivery.attempts))
            # Avoid storing credentials from SMTP/HTTP error strings.
            delivery.error = f"{type(exc).__name__}: delivery failed; check channel configuration."
        session.commit()
