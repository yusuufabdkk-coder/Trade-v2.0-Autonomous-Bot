from pydantic import BaseModel, Field
from typing import Optional, Literal

class AIDataPayload(BaseModel):
    """Payload from TradingView Pine Script - Full SMC Data Package."""
    # Core
    symbol: str = Field(default="BTCUSDT")
    exchange_symbol: str = Field(default="BINANCE:BTCUSDT.P")
    timeframe: str = Field(default="5")
    bar_time: str = Field(...)
    chart_link: str = Field(default="")
    secret: str = Field(...)

    # Price Action
    price: float
    high: float
    low: float
    volume: float = Field(default=0)
    atr: float = Field(default=0)

    # Technicals
    rsi_14: float = Field(default=50)
    ema_9: float = Field(default=0)
    ema_21: float = Field(default=0)
    ema_50: float = Field(default=0)
    ema_200: float = Field(default=0)

    # Multi-Timeframe Bias
    ema_trend: str = Field(default="NONE")
    ema_50_200_state: str = Field(default="NEUTRAL")
    daily_bias: str = Field(default="NONE")
    h4_bias: str = Field(default="NONE")
    h1_bias: str = Field(default="NONE")

    # Premium/Discount
    premium_discount_zone: str = Field(default="NONE")

    # Session
    session: str = Field(default="NONE")
    session_power: str = Field(default="NORMAL")
    judas_swing: bool = Field(default=False)

    # Structure (BoS / ChoCH / MSS)
    structure_type: str = Field(default="NONE")
    structure_direction: str = Field(default="NONE")
    broken_level: float = Field(default=0)

    # Liquidity
    liquidity_type: str = Field(default="NONE")
    liquidity_swept: bool = Field(default=False)
    liquidity_level: float = Field(default=0)
    sfp_detected: bool = Field(default=False)

    # PD Arrays (FVG / OB)
    pd_array_type: str = Field(default="NONE")
    pd_array_direction: str = Field(default="NONE")
    zone_low: float = Field(default=0)
    zone_high: float = Field(default=0)
    zone_status: str = Field(default="NONE")

    # Orderflow & Candle
    candle_pattern: str = Field(default="NONE")
    orderflow_direction: str = Field(default="NEUTRAL")
    body_ratio: float = Field(default=0)
    volume_ratio: float = Field(default=0)
    impulse_candle: bool = Field(default=False)

    # Swing Levels
    nearest_swing_high: float = Field(default=0)
    nearest_swing_low: float = Field(default=0)
    fvg_active: bool = Field(default=False)
    ob_active: bool = Field(default=False)
    
    # New Fields Requested by AI
    volume_delta: float = Field(default=0.0)
    asia_high: float = Field(default=0.0)
    asia_low: float = Field(default=0.0)
    london_high: float = Field(default=0.0)
    london_low: float = Field(default=0.0)
    htf_resistance: float = Field(default=0.0)
    htf_support: float = Field(default=0.0)

    # Momentum & Context Indicators
    macd_histogram: float = Field(default=0.0)
    macd_status: str = Field(default="NEUTRAL")
    stoch_rsi_k: float = Field(default=50.0)
    stoch_rsi_d: float = Field(default=50.0)
    vwap: float = Field(default=0.0)
    bb_width: float = Field(default=0.0)
    daily_open: float = Field(default=0.0)
    prev_day_high: float = Field(default=0.0)
    prev_day_low: float = Field(default=0.0)


class AITradeDecision(BaseModel):
    """Structured response expected from the LLM."""
    decision: Literal["LONG", "SHORT", "CLOSE_LONG", "CLOSE_SHORT", "WAIT", "MODIFY"]
    leverage: Optional[int] = 10
    trade_amount_usdt: Optional[float] = None
    entry_price: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    new_stop_loss: Optional[float] = None
    new_take_profit: Optional[float] = None
    reasoning: str
