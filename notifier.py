"""
notifier.py
-----------
Sends alerts by EMAIL over SMTP. Works with any email provider (Gmail, Outlook,
Yahoo, your own domain, etc.). Credentials come from environment variables / a
.env file / GitHub Secrets - never hard-coded here.

Required variables:
  EMAIL_SMTP_HOST   e.g. smtp.gmail.com
  EMAIL_SMTP_PORT   usually 587 (STARTTLS) or 465 (SSL)
  EMAIL_USER        the sending address / login
  EMAIL_PASSWORD    an APP PASSWORD (not your normal login password)
  EMAIL_TO          where to send alerts (defaults to EMAIL_USER if omitted)

Every alert is also printed to the console/log so you always have a record.
"""

import os
import smtplib
import ssl
from email.mime.text import MIMEText


def _env(name, default=None):
    val = os.environ.get(name, default)
    return val.strip() if isinstance(val, str) else val


def send_email(subject: str, body: str) -> bool:
    host = _env("EMAIL_SMTP_HOST")
    port = int(_env("EMAIL_SMTP_PORT", "587"))
    user = _env("EMAIL_USER")
    password = _env("EMAIL_PASSWORD")
    to_addr = _env("EMAIL_TO") or user

    if not (host and user and password):
        return False

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = to_addr

    try:
        ctx = ssl.create_default_context()
        if port == 465:
            # Implicit SSL
            with smtplib.SMTP_SSL(host, port, context=ctx, timeout=30) as server:
                server.login(user, password)
                server.sendmail(user, [a.strip() for a in to_addr.split(",")], msg.as_string())
        else:
            # STARTTLS (587)
            with smtplib.SMTP(host, port, timeout=30) as server:
                server.starttls(context=ctx)
                server.login(user, password)
                server.sendmail(user, [a.strip() for a in to_addr.split(",")], msg.as_string())
        return True
    except Exception as e:
        print(f"[email] error: {e}")
        return False


def notify(subject: str, body: str) -> None:
    """Email the alert through the configured account; always log to console."""
    print("\n" + "=" * 50)
    print(subject)
    print(body)
    print("=" * 50)
    sent = send_email(subject, body)
    if not sent:
        print("[notify] Email not configured (or send failed) - alert only printed "
              "above. Set EMAIL_* variables to receive emails.")
