import argparse
import json
import os
import warnings
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
from playwright.sync_api import sync_playwright

warnings.filterwarnings("ignore", category=UserWarning)

EVENTS_PATH = "events.json"
STATE_PATH = "state.json"
MADRID_TZ = ZoneInfo("Europe/Madrid")
HEARTBEAT_HOUR = 10
HEARTBEAT_MINUTE = 30

PHRASES_BY_LOCALE = {
    "en": {
        "buy": ("BUY TICKETS",),
        "unavailable": ("NOT AVAILABLE", "TEMPORARILY UNAVAILABLE"),
    },
    "es": {
        "buy": ("COMPRAR ENTRADAS",),
        "unavailable": ("NO DISPONIBLE", "TEMPORALMENTE NO DISPONIBLE"),
    },
}

NOTIFY_MODAL_CLASS_HINTS = ("modal-activate",)
UNAVAILABLE_CLASS_HINTS = ("button-buy__non-available", "btn--disabled")

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")


def load_events(path=EVENTS_PATH):
    with open(path, encoding="utf-8") as f:
        return json.load(f)["events"]


def load_state(path=STATE_PATH):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_state(state, path=STATE_PATH):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, sort_keys=True)
        f.write("\n")


def now_madrid():
    return datetime.now(MADRID_TZ)


def locale_from_url(url):
    if "/en/" in url:
        return "en"
    if "/es/" in url:
        return "es"
    raise ValueError(f"Could not determine locale (expected '/en/' or '/es/' segment) from URL: {url}")


def extract_buy_buttons_info(page):
    buttons_info = []
    cards = page.query_selector_all("div.card-info")
    for card in cards:
        parent_classes = card.evaluate("el => el.parentElement.className").lower()
        if "premium" in parent_classes or "vippremium" in parent_classes:
            continue

        for button in card.query_selector_all("a.button-buy"):
            buttons_info.append({
                "text": button.inner_text().strip().upper(),
                "href": (button.get_attribute("href") or "").strip(),
                "classes": (button.get_attribute("class") or "").lower(),
            })

    return buttons_info


def classify_status(buttons_info, locale):
    phrases = PHRASES_BY_LOCALE[locale]
    per_button_status = []

    for button in buttons_info:
        text = button["text"]
        href = button["href"]
        classes = button["classes"]

        is_unavailable_class = any(hint in classes for hint in UNAVAILABLE_CLASS_HINTS)
        is_unavailable_text = any(phrase in text for phrase in phrases["unavailable"])
        is_buy_text = any(phrase in text for phrase in phrases["buy"])

        if is_unavailable_text or is_unavailable_class:
            per_button_status.append("unavailable")
        elif is_buy_text:
            is_real_link = href not in ("", "#") and not href.lower().startswith("javascript:")
            is_notify_modal = any(hint in classes for hint in NOTIFY_MODAL_CLASS_HINTS)
            if is_real_link and not is_notify_modal:
                per_button_status.append("buyable")
            else:
                per_button_status.append("pending")
        else:
            per_button_status.append("unknown")

    if "buyable" in per_button_status:
        return "buyable"
    if any(status in ("unavailable", "pending") for status in per_button_status):
        return "unavailable"
    return "unknown"


def check_page(url, browser):
    print(f"[LOG] Comprobando: {url}")
    locale = locale_from_url(url)
    page = browser.new_page()
    try:
        page.goto(url, timeout=30000)
        page.wait_for_timeout(3000)
        buttons_info = extract_buy_buttons_info(page)
    finally:
        page.close()

    status = classify_status(buttons_info, locale)
    print(f"[LOG] Resultado: {status} ({len(buttons_info)} botones encontrados)")
    return status


def build_buyable_message(event):
    return f"🎉 {event['title']}\n🎟️ ¡Ya puedes comprar tus tickets!\n🔗 Accede aquí: {event['url']}"


def build_unavailable_message(event):
    return f"⚠️ {event['title']}\n🎟️ Las entradas han dejado de estar disponibles.\n🔗 Accede aquí: {event['url']}"


def build_heartbeat_message(event):
    return f"✅ {event['title']}\n🎟️ Sigue habiendo entradas disponibles (recordatorio diario).\n🔗 Accede aquí: {event['url']}"


def build_unknown_warning_message(event):
    return f"ℹ️ {event['title']}\n🎟️ No se pudo determinar el estado de las entradas (revisar el script).\n🔗 Accede aquí: {event['url']}"


def send_telegram_message(message, dry_run=False):
    if dry_run:
        print(f"[DRY-RUN] Would send: {message}")
        return

    print(f"[LOG] Enviando mensaje a Telegram: {message}")
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        response = requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": message}, timeout=10)
        response.raise_for_status()
        print("[LOG] Mensaje enviado correctamente")
    except Exception as e:
        print(f"[ERROR] No se pudo enviar el mensaje: {e}")


def should_send_heartbeat(prev_entry, now):
    last_notified_at = prev_entry.get("last_notified_at")
    if last_notified_at is None:
        return True

    last = datetime.fromisoformat(last_notified_at).astimezone(MADRID_TZ)
    if last.date() == now.date():
        return False

    threshold = now.replace(hour=HEARTBEAT_HOUR, minute=HEARTBEAT_MINUTE, second=0, microsecond=0)
    return now >= threshold


def decide_notification(event, current_status, prev_entry, now):
    prev_status = prev_entry.get("status", "unknown")

    if current_status != prev_status:
        notify = True
        if current_status == "buyable":
            message = build_buyable_message(event)
        elif current_status == "unavailable":
            message = build_unavailable_message(event)
        else:
            message = build_unknown_warning_message(event)
    elif current_status == "buyable":
        notify = should_send_heartbeat(prev_entry, now)
        message = build_heartbeat_message(event) if notify else None
    elif current_status == "unknown":
        notify = should_send_heartbeat(prev_entry, now)
        message = build_unknown_warning_message(event) if notify else None
    else:
        notify = False
        message = None

    new_last_notified_at = now.isoformat() if notify else prev_entry.get("last_notified_at")
    return notify, message, current_status, new_last_notified_at


def parse_args(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=os.environ.get("DRY_RUN", "").lower() in ("1", "true", "yes"),
        help="Skip sending real Telegram messages and skip writing state.json",
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    if args.dry_run:
        print("[LOG] Ejecutando en modo --dry-run")

    print("[LOG] Chequeando disponibilidad de tickets...")

    events = load_events()
    state = load_state()
    now = now_madrid()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            for event in events:
                prev_entry = state.get(event["id"], {})
                status = check_page(event["url"], browser)
                notify, message, new_status, new_last_notified_at = decide_notification(
                    event, status, prev_entry, now
                )

                if notify:
                    send_telegram_message(message, dry_run=args.dry_run)

                state[event["id"]] = {
                    "status": new_status,
                    "last_notified_at": new_last_notified_at,
                }
        finally:
            browser.close()

    if args.dry_run:
        print("[DRY-RUN] Skipping state.json write")
    else:
        save_state(state)

    print("[LOG] Chequeo finalizado")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
