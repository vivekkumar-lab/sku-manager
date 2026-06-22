"""
Email OTP service via Brevo (https://brevo.com).
Requires only a verified sender email address — no domain DNS changes needed.

Env vars:
  BREVO_API_KEY  — from brevo.com SMTP & API > API Keys
  FROM_EMAIL     — a verified sender address in your Brevo account
  SMTP_FROM_NAME — display name (default: SKU Manager)
"""

import secrets, os, json
from urllib.request import urlopen, Request
from urllib.error import URLError


def generate_otp(length=6):
    return "".join([str(secrets.randbelow(10)) for _ in range(length)])


def send_otp(to_email, otp):
    """Send OTP email. Returns (True, None) on success or (False, error_message)."""
    api_key   = os.environ.get("BREVO_API_KEY", "")
    from_name = os.environ.get("SMTP_FROM_NAME", "SKU Manager")
    from_addr = os.environ.get("FROM_EMAIL", "")

    if not api_key or not from_addr:
        print(f"\n[DEV] OTP for {to_email}: {otp}\n", flush=True)
        return True, None

    html_body = f"""
    <div style="font-family:Inter,Arial,sans-serif;max-width:480px;margin:40px auto;padding:32px;
                background:#f8fafc;border-radius:16px;border:1px solid #e2e8f0;">
      <h2 style="color:#1e293b;margin:0 0 8px;">SKU Manager</h2>
      <p style="color:#64748b;margin:0 0 24px;">Your sign-in code</p>
      <div style="background:#1e293b;color:#fff;font-size:36px;font-weight:700;letter-spacing:12px;
                  text-align:center;padding:20px;border-radius:12px;">{otp}</div>
      <p style="color:#94a3b8;font-size:13px;margin:20px 0 0;">
        Expires in 10 minutes. If you didn't request this, ignore this email.
      </p>
    </div>"""

    payload = json.dumps({
        "sender":      {"name": from_name, "email": from_addr},
        "to":          [{"email": to_email}],
        "subject":     f"Your SKU Manager sign-in code: {otp}",
        "textContent": f"Your sign-in code is: {otp}\n\nExpires in 10 minutes.",
        "htmlContent": html_body,
    }).encode()

    req = Request(
        "https://api.brevo.com/v3/smtp/email",
        data=payload,
        headers={
            "accept":       "application/json",
            "api-key":      api_key,
            "content-type": "application/json",
        },
        method="POST",
    )

    try:
        with urlopen(req, timeout=15) as resp:
            if resp.status == 201:
                return True, None
            return False, f"Unexpected status {resp.status}"
    except URLError as e:
        return False, str(e)
