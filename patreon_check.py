#!/usr/bin/env python3
"""
Single-run Patreon membership checker — designed for GitHub Actions.
Runs once, sends email if a spot is open, then exits.
EMAIL_PASSWORD is read from the environment (GitHub Secret).
"""

import os
import smtplib
import sys
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timezone
from playwright.sync_api import sync_playwright

# ── Config ──────────────────────────────────────────────────────────────────
PATREON_URL    = "https://www.patreon.com/smalldragoninvest/membership?vanity=smalldragoninvest"
EMAIL_TO       = "jackycheung1984@gmail.com"
EMAIL_FROM     = "jackycheung1984@gmail.com"
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD", "")
# ────────────────────────────────────────────────────────────────────────────


def scrape_page() -> tuple[bool, str]:
    """
    Returns (spots_available, status_summary).
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        )
        page.goto(PATREON_URL, wait_until="networkidle", timeout=45_000)
        page.wait_for_timeout(3_000)
        text = page.inner_text("body").lower()
        browser.close()

    open_signals = [
        "join for free", "become a patron", "subscribe",
        "select", "join now", "get access",
    ]
    full_signals = [
        "membership is full", "sold out", "no spots",
        "waitlist", "join waitlist", "notify me",
        "full membership", "limited availability",
    ]

    is_full      = any(s in text for s in full_signals)
    has_open_btn = any(s in text for s in open_signals)

    if is_full and not has_open_btn:
        return False, "full / waitlist only"
    if has_open_btn and not is_full:
        return True, "open — join button detected"
    if has_open_btn and is_full:
        return True, "mixed — at least one tier may be open"
    return False, "unknown (no clear signals)"


def send_email(subject: str, body: str):
    if not EMAIL_PASSWORD:
        print("WARNING: EMAIL_PASSWORD not set, skipping email")
        return
    msg = MIMEMultipart()
    msg["From"]    = EMAIL_FROM
    msg["To"]      = EMAIL_TO
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain", "utf-8"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=15) as srv:
        srv.login(EMAIL_FROM, EMAIL_PASSWORD)
        srv.sendmail(EMAIL_FROM, EMAIL_TO, msg.as_string())
    print("Email sent.")


def main():
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    print(f"[{now}] Checking {PATREON_URL}")

    available, summary = scrape_page()
    print(f"Status: {summary}")

    if available:
        subject = "🎉 Patreon smalldragoninvest — membership OPEN!"
        body = (
            f"A membership spot is now available!\n\n"
            f"Go join NOW:\n{PATREON_URL}\n\n"
            f"Detected at: {now}\n"
            f"Status: {summary}\n\n"
            f"(This alert fires every 15 min while spots remain open.)"
        )
        send_email(subject, body)
        print("*** ALERT: Spot available! ***")
        sys.exit(0)
    else:
        print("No spots available. Next check in ~15 min.")
        sys.exit(0)


if __name__ == "__main__":
    main()
