import os
import warnings
import requests
from playwright.sync_api import sync_playwright

# Suprimir warnings de urllib3/OpenSSL
warnings.filterwarnings("ignore", category=UserWarning)

URLS = [
    {
        "url":"https://www.fcbarcelona.com/en/tickets/football/regular/copa-del-rey/semifinals",
        "title": "⚽ FC Barcelona 🆚 Atletico de Madrid (Copa del Rey Semifinal)"
    },
    {
        "url": "https://www.fcbarcelona.com/en/tickets/football/regular/laliga/fcbarcelona-realmadrid",
        "title": "⚽ FC Barcelona 🆚 Real Madrid"
    },
    {
        "url": "https://www.fcbarcelona.com/en/tickets/football/regular/laliga/fcbarcelona-realbetis",
        "title": "⚽ FC Barcelona 🆚 Real Betis"
    }
]

TEXT_TO_CHECK_UNAVAILABLE = "TEMPORARILY UNAVAILABLE"
TEXT_TO_CHECK_BUY = "BUY TICKETS"

# Credenciales de Telegram
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

def send_telegram_message(message):
    print(f"[LOG] Enviando mensaje a Telegram: {message}")
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        response = requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": message}, timeout=10)
        response.raise_for_status()
        print("[LOG] Mensaje enviado correctamente")
    except Exception as e:
        print(f"[ERROR] No se pudo enviar el mensaje: {e}")

def check_page(url):
    print(f"[LOG] Iniciando Playwright para: {url}")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(url, timeout=30000)
        print("[LOG] Página cargada, esperando 5s para que se ejecute JS...")
        page.wait_for_timeout(5000)  # espera que cargue el JS dinámico

        # Buscar todas las tarjetas de tickets
        cards = page.query_selector_all("div.card-info")
        status_unavailable = False
        status_buy = False

        for card in cards:
            # Ignorar VIP/premium
            parent_classes = card.evaluate("el => el.parentElement.className")
            if "premium" in parent_classes.lower() or "vippremium" in parent_classes.lower():
                continue

            # Verificar si hay "temporarily unavailable" o "buy tickets"
            buttons = card.query_selector_all("a.button-buy")
            for b in buttons:
                text = b.inner_text().strip().upper()
                if TEXT_TO_CHECK_UNAVAILABLE in text:
                    status_unavailable = True
                if TEXT_TO_CHECK_BUY in text:
                    status_buy = True

        print(f"[LOG] Resultados: TEMPORARILY UNAVAILABLE={status_unavailable}, BUY TICKETS={status_buy}")
        browser.close()
        return status_unavailable, status_buy

if __name__ == "__main__":
    print("[LOG] Chequeando disponibilidad de tickets...")

    for event in URLS:
        url = event["url"]
        title = event["title"]
        unavailable, buy = check_page(url)
        
        if buy:
            message = f"🎉 {title}\n🎟️ ¡Ya puedes comprar tus tickets!\n🔗 Accede aquí: {url}"
            send_telegram_message(message)
        elif not unavailable:
            message = f"ℹ️ {title}\n🎟️ No se detectó ni 'Temporalmente no disponibles' ni 'Comprar tickets'.\n🔗 Accede aquí: {url}"
            send_telegram_message(message)

    print(f"[DEBUG] TELEGRAM_BOT_TOKEN: {TELEGRAM_BOT_TOKEN}")
    print(f"[DEBUG] TELEGRAM_CHAT_ID: {TELEGRAM_CHAT_ID}")

    print("[LOG] Chequeo finalizado")