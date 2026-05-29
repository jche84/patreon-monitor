#!/usr/bin/env python3
"""
Single-run Patreon membership checker — designed for GitHub Actions + residential proxy.
Runs once, sends email if the tier is no longer "Sold Out", then exits.

Secrets (GitHub repo secrets / env vars):
  EMAIL_PASSWORD  - Gmail app password (required for email)
  PROXY_SERVER    - residential proxy, e.g. "http://host:port"   (required to beat Cloudflare)
  PROXY_USER      - proxy username
  PROXY_PASS      - proxy password

Detection strategy (tuned to the real page 2026-05-29):
  - Tier "3月特別開放" currently shows "Sold Out" / "Limited spaces - SOLD OUT".
  - ANCHOR text confirms the real membership page loaded (not Cloudflare / block page).
  - page loaded AND "sold out" GONE     -> OPEN  -> alert.
  - page loaded AND "sold out" present  -> FULL  -> no alert.
  - ANCHOR missing (Cloudflare/empty)   -> NOVERIFY -> no alert (logged).
"""

import os
import smtplib
import sys
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timezone
from playwright.sync_api import sync_playwright

# ── Config ──────────────────────────────────────────────────────────────────
PATREON_URL    = "https://www.patreon.com/smalldragoninvest/membership?vanity=smalldragoninvest"
EMAIL_TO       = "jackycheung1984@gmail.com"
EMAIL_FROM     = "jackycheung1984@gmail.com"
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD", "")

PROXY_SERVER   = os.environ.get("PROXY_SERVER", "")   # e.g. http://geo.iproyal.com:12321
PROXY_USER     = os.environ.get("PROXY_USER", "")
PROXY_PASS     = os.environ.get("PROXY_PASS", "")

ANCHORS  = ["choose your membership", "研究中心", "3月特別開放"]
SOLD_OUT = ["sold out", "limited spaces"]
CF_MARKERS = ["performing security verification", "just a moment",
              "verify you are human", "checking your browser"]
# ────────────────────────────────────────────────────────────────────────────


def _block_heavy(route):
    """Abort images/media/fonts/css to slash proxy bandwidth."""
    if route.request.resource_type in ("image", "media", "font", "stylesheet"):
        return route.abort()
    return route.continue_()


def scrape_page() -> tuple[str, str]:
    """
    Returns (verdict, detail): "OPEN" | "FULL" | "NOVERIFY".
    Retries a few times to let the Cloudflare JS challenge auto-clear.
    """
    proxy = None
    if PROXY_SERVER:
        proxy = {"server": PROXY_SERVER}
        if PROXY_USER:
            proxy["username"] = PROXY_USER
            proxy["password"] = PROXY_PASS

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
            proxy=proxy,
        )
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="en-US",
            viewport={"width": 1366, "height": 900},
        )
        context.route("**/*", _block_heavy)
        page = context.new_page()

        raw = ""
        for attempt in range(1, 5):  # up to 4 tries, ~aggregate 30s, for CF to clear
            try:
                page.goto(PATREON_URL, wait_until="domcontentloaded", timeout=45_000)
            except Exception as e:
                print(f"DEBUG goto attempt {attempt} error: {e}")
            page.wait_for_timeout(6_000)
            raw = page.inner_text("body")
            low = raw.lower()
            if any(a.lower() in low for a in ANCHORS):
                break  # real page rendered
            if any(m in low for m in CF_MARKERS):
                print(f"DEBUG attempt {attempt}: Cloudflare challenge, waiting…")
                page.wait_for_timeout(4_000)
                continue
            print(f"DEBUG attempt {attempt}: no anchor yet (len={len(raw)})")

        browser.close()

    low      = raw.lower()
    anchored = any(a.lower() in low for a in ANCHORS)
    sold_out = any(s in low for s in SOLD_OUT)

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
    print(f"Proxy: {'ON ('+PROXY_SERVER+')' if PROXY_SERVER else 'OFF'}")

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
        print("Could not verify page (Cloudflare/proxy issue). No alert.")
    else:
        print("Still Sold Out. Next check in ~15 min.")

    sys.exit(0)


if __name__ == "__main__":
    main()
