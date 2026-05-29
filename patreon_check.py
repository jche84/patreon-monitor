#!/usr/bin/env python3
"""
Single-run Patreon membership checker — designed for GitHub Actions.
Runs once, sends email if the tier is no longer "Sold Out", then exits.
EMAIL_PASSWORD is read from the environment (GitHub Secret).

Detection strategy (tuned to the real page 2026-05-29):
  - Tier "3月特別開放" currently shows "Sold Out" / "Limited spaces - SOLD OUT".
  - ANCHOR text confirms the real membership page loaded (not a block/challenge page).
  - If page loaded AND "sold out" is GONE  -> spot is OPEN -> alert.
  - If page loaded AND "sold out" present  -> still full -> no alert.
  - If ANCHOR missing                      -> page blocked/empty -> cannot verify, no alert.
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

# Text that proves the real membership page rendered:
ANCHORS    = ["choose your membership", "研究中心", "3月特別開放"]
# Text that means the tier is still full:
SOLD_OUT   = ["sold out", "limited spaces"]
# ────────────────────────────────────────────────────────────────────────────


def scrape_page() -> tuple[str, str]:
    """
    Returns (verdict, detail) where verdict is one of:
      "OPEN"      -> tier no longer sold out, alert!
      "FULL"      -> still sold out
      "NOVERIFY"  -> page didn't load real content (blocked/empty)
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="en-US",
        )
        page.goto(PATREON_URL, wait_until="networkidle", timeout=45_000)
        page.wait_for_timeout(6_000)
        raw  = page.inner_text("body")
        browser.close()

    text     = raw.lower()
    anchored = any(a.lower() in text for a in ANCHORS)
    sold_out = any(s in text for s in SOLD_OUT)

    # --- debug so we can see what the runner actually got ---
    print(f"DEBUG page_len={len(raw)}  anchored={anchored}  sold_out={sold_out}")
    print("DEBUG first 400 chars:\n" + raw[:400].replace("\n", " | "))
    print("-" * 50)

    if not anchored:
        return "NOVERIFY", f"page did not load real content (len={len(raw)})"
    if sold_out:
        return "FULL", "tier still shows Sold Out"
    return "OPEN", "Sold Out text GONE — spot likely open!"


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

    verdict, detail = scrape_page()
    print(f"VERDICT: {verdict} — {detail}")

    if verdict == "OPEN":
        subject = "🎉 Patreon 研究中心 — membership OPEN!"
        body = (
            f"The tier '3月特別開放' is no longer Sold Out!\n\n"
            f"Go join NOW:\n{PATREON_URL}\n\n"
            f"Detected at: {now}\n"
            f"Detail: {detail}\n\n"
            f"(This alert fires every 15 min while the spot stays open.)"
        )
        send_email(subject, body)
        print("*** ALERT: Spot available! Email sent. ***")
    elif verdict == "NOVERIFY":
        print("Could not verify page (possible IP block). No alert.")
    else:
        print("Still Sold Out. Next check in ~15 min.")

    sys.exit(0)


if __name__ == "__main__":
    main()
