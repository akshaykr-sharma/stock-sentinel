import os
import logging
import requests

logger = logging.getLogger(__name__)

WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN", "")          # Meta permanent token
WHATSAPP_PHONE_ID = os.getenv("WHATSAPP_PHONE_ID", "")    # Phone number ID from Meta
META_API_URL = "https://graph.facebook.com/v21.0/{phone_id}/messages"


def send_whatsapp(to_number: str, message: str) -> bool:
    """
    Send a WhatsApp message via Meta Cloud API.
    to_number: E.164 format without '+', e.g. 919876543210
    """
    if not WHATSAPP_TOKEN or not WHATSAPP_PHONE_ID:
        logger.error("WHATSAPP_TOKEN or WHATSAPP_PHONE_ID not configured")
        return False

    # Strip leading + if present
    to = to_number.lstrip("+")

    url = META_API_URL.format(phone_id=WHATSAPP_PHONE_ID)
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": message},
    }
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json",
    }

    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=10)
        data = resp.json()
        if resp.status_code == 200 and "messages" in data:
            logger.info("WhatsApp sent to %s, message id: %s", to, data["messages"][0].get("id"))
            return True
        else:
            logger.error("Meta API error: %s", data)
            return False
    except Exception:
        logger.exception("Failed to send WhatsApp to %s", to_number)
        return False


def build_in_stock_message(product_name: str, url: str, price: str | None) -> str:
    price_line = f"💰 Price: {price}\n" if price else ""
    return (
        f"🔔 StockSentinel Alert!\n\n"
        f"✅ {product_name} is now IN STOCK!\n\n"
        f"{price_line}"
        f"🔗 {url}\n\n"
        f"Go to the StockSentinel app and tap 'Got It!' to stop alerts."
    ).strip()


def build_back_out_of_stock_message(product_name: str) -> str:
    return (
        f"📦 StockSentinel Update\n\n"
        f"❌ {product_name} went back out of stock.\n"
        f"We'll keep watching and alert you when it's available again."
    )


def build_status_message(product_name: str, url: str, status: str, price: str | None) -> str:
    if status == "in_stock":
        icon = "✅"
        status_text = "IN STOCK"
    elif status == "out_of_stock":
        icon = "❌"
        status_text = "OUT OF STOCK"
    else:
        icon = "⚠️"
        status_text = status.upper()

    price_line = f"💰 Price: {price}\n" if price else ""
    return (
        f"📋 StockSentinel Status Update\n\n"
        f"{icon} {product_name} is currently {status_text}\n\n"
        f"{price_line}"
        f"🔗 {url}"
    ).strip()
