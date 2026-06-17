import os
import logging
from twilio.rest import Client

logger = logging.getLogger(__name__)

TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_WHATSAPP_FROM = os.getenv("TWILIO_WHATSAPP_FROM", "whatsapp:+14155238886")  # sandbox default


def send_whatsapp(to_number: str, message: str) -> bool:
    """Send a WhatsApp message. to_number should be E.164 like +919876543210"""
    if not TWILIO_ACCOUNT_SID or not TWILIO_AUTH_TOKEN:
        logger.error("Twilio credentials not configured")
        return False

    try:
        client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        to_whatsapp = f"whatsapp:{to_number}" if not to_number.startswith("whatsapp:") else to_number

        msg = client.messages.create(
            from_=TWILIO_WHATSAPP_FROM,
            to=to_whatsapp,
            body=message,
        )
        logger.info("WhatsApp sent: SID=%s", msg.sid)
        return True
    except Exception as e:
        logger.exception("Failed to send WhatsApp to %s", to_number)
        return False


def build_in_stock_message(product_name: str, url: str, price: str | None) -> str:
    price_line = f"💰 Price: {price}" if price else ""
    return (
        f"🔔 *StockSentinel Alert!*\n\n"
        f"✅ *{product_name}* is now *IN STOCK!*\n\n"
        f"{price_line}\n"
        f"🔗 {url}\n\n"
        f"Go to the StockSentinel app and tap *Got It!* to stop alerts."
    ).strip()


def build_back_out_of_stock_message(product_name: str) -> str:
    return (
        f"📦 *StockSentinel Update*\n\n"
        f"❌ *{product_name}* went back *out of stock*.\n"
        f"We'll keep watching and alert you when it's available again."
    )
