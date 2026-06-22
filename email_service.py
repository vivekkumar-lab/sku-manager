"""
Email OTP service. Reads SMTP config from environment variables.

Required env vars:
  SMTP_HOST  — e.g. smtp.gmail.com
  SMTP_PORT  — e.g. 587
  SMTP_USER  — sender address
  SMTP_PASS  — app password / SMTP password

Optional:
  SMTP_FROM_NAME — display name (default: SKU Manager)
"""

import smtplib, secrets, os
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText


def generate_otp(length=6):
    return "".join([str(secrets.randbelow(10)) for _ in range(length)])


def send_otp(to_email, otp):
    """Send OTP email. Returns (True, None) on success or (False, error_message)."""
    host = os.environ.get("SMTP_HOST", "")
    port = int(os.environ.get("SMTP_PORT", 587))
    user = os.environ.get("SMTP_USER", "")
    password = os.environ.get("SMTP_PASS", "")
    from_name = os.environ.get("SMTP_FROM_NAME", "SKU Manager")

    if not all([host, user, password]):
        # Dev mode: print OTP to console instead of sending email
        print(f"\n[DEV] OTP for {to_email}: {otp}\n")
        return True, None

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Your SKU Manager OTP: {otp}"
    msg["From"] = f"{from_name} <{user}>"
    msg["To"] = to_email

    text_body = f"Your one-time password is: {otp}\n\nExpires in 10 minutes."
    html_body = f"""
    <div style="font-family:Inter,Arial,sans-serif;max-width:480px;margin:40px auto;padding:32px;
                background:#f8fafc;border-radius:16px;border:1px solid #e2e8f0;">
      <h2 style="color:#1e293b;margin:0 0 8px;">SKU Manager</h2>
      <p style="color:#64748b;margin:0 0 24px;">Your sign-in code</p>
      <div style="background:#1e293b;color:#fff;font-size:36px;font-weight:700;letter-spacing:12px;
                  text-align:center;padding:20px;border-radius:12px;">{otp}</div>
      <p style="color:#94a3b8;font-size:13px;margin:20px 0 0;">
        This code expires in 10 minutes. If you didn't request this, ignore this email.
      </p>
    </div>"""

    msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP(host, port, timeout=15) as server:
            server.ehlo()
            server.starttls()
            server.login(user, password)
            server.sendmail(user, to_email, msg.as_string())
        return True, None
    except Exception as e:
        return False, str(e)
