from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    PORT: int = 8000
    HOST: str = "0.0.0.0"
    WEBHOOK_SECRET: str = "mysecret"

    ANTHROPIC_API_KEY: str = ""
    AI_MODEL_NAME: str = "claude-3-5-sonnet-20240620"
    MAX_AI_CALLS_PER_DAY: int = 200
    AI_SYSTEM_PROMPT: str = "You are a professional ICT/SMC crypto futures trader specializing in BTCUSDT. Analyze market structure, liquidity sweeps, order blocks, FVGs, and RSI. Be smart with risk management - the account has limited capital. Respond ONLY with JSON containing: decision, trade_amount_usdt, entry_price, stop_loss, take_profit, and reasoning."

    BINANCE_API_KEY: str = ""
    BINANCE_API_SECRET: str = ""
    BINANCE_TESTNET: bool = False
    TRADE_RISK_PERCENT: float = 1.0

    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_CHAT_ID: str = ""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

_settings = None

def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
