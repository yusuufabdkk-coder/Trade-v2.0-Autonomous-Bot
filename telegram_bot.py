import httpx
import logging
from config import get_settings

logger = logging.getLogger(__name__)

async def send_telegram_message(text: str):
    settings = get_settings()
    
    if not settings.TELEGRAM_BOT_TOKEN or not settings.TELEGRAM_CHAT_ID:
        logger.info(f"Telegram not configured. Message: {text}")
        return

    url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": settings.TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML"
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            logger.info("Telegram message sent successfully.")
    except Exception as e:
        logger.error(f"Failed to send Telegram message: {e}")
