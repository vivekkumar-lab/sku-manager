"""
Email OTP service.

Uses Resend (https://resend.com) — works on all cloud hosts including Render free tier.
Set RESEND_API_KEY in environment. Leave blank to print OTPs to console (dev mode).

Optional:
  FROM_EMAIL    — sender address (default: onboarding@resend.dev for testing,
                  or noreply@yourdomain.com once domain is verified in Resend)
  SMTP_FROM_NAME — display name (default: SKU Manager)
"""

import secrets, os


def generate_otp(length=6):
    return "".join([str(secrets.randbelow(10)) for _ in range(length)])


def send_otp(to_email, otp):
    """Send OTP email. Returns (True, None) on success or (False, error_message)."""
    api_key = os.environ.get("RESEND_API_KEY", "")

    if not api_key:
        print(f"\n[DEV] OTP for {to_email}: {otp}\n", flush=True)
        return True, None

    from_name  = os.environ.get("SMTP_FROM_NAME", "SKU Manager")
    from_email = os.environ.get("FROM_EMAIL", "onboarding@resend.dev")

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

    try:
        import resend
        resend.api_key = api_key
        resend.Emails.send({
            "from": f"{from_name} <{from_email}>",
            "to":   [to_email],
            "subject": f"Your SKU Manager sign-in code: {otp}",
            "text": text_body,
            "html": html_body,
        })
        return True, None
    except Exception as e:
        return False, str(e)
