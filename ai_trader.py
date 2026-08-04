import logging
import json
from datetime import datetime, timezone
import anthropic
from config import get_settings
from models import AIDataPayload, AITradeDecision
from binance_executor import executor
from storage import load_ai_history, save_ai_history, load_initial_balance, save_initial_balance

logger = logging.getLogger(__name__)

class RateLimiter:
    def __init__(self):
        self.calls_today = 0
        self.last_reset_date = datetime.now(timezone.utc).date()

    def can_make_call(self, max_calls: int) -> bool:
        current_date = datetime.now(timezone.utc).date()
        if current_date != self.last_reset_date:
            self.calls_today = 0
            self.last_reset_date = current_date
        if self.calls_today >= max_calls:
            return False
        return True

    def increment(self):
        self.calls_today += 1

rate_limiter = RateLimiter()

# Load interactions from JSON to persist across restarts
ai_history = load_ai_history()

def get_recent_trades_summary() -> str:
    trades = []
    for log in ai_history:
        if log.get("decision") in ["LONG", "SHORT", "CLOSE_LONG", "CLOSE_SHORT"]:
            trades.append(f"{log['time']} | {log['decision']} | {log.get('execution_price', '0.0')}")
        if len(trades) >= 3:
            break
    return "\n  ".join(trades) if trades else "No recent trades."

def generate_protection_prompt(payload: AIDataPayload, current_balance: float, initial_balance: float, open_position: dict, funding_rate: float) -> str:
    """Shorter prompt for 1m emergency checks — with MODIFY capability."""
    pnl_value = current_balance - initial_balance
    pos_str = f"ACTIVE {open_position['side']} | Entry: {open_position['entry_price']} | Unrealized PnL: {open_position['unrealized_pnl']} USDT | Duration: {open_position.get('duration_minutes', 0)} mins"
    recent_trades = get_recent_trades_summary()

    prompt = f"""=== {payload.symbol} 1m POSITION MONITOR ({payload.bar_time}) ===

💰 ACCOUNT & POSITIONS:
  Current Balance: {current_balance:.2f} USDT (Total PnL: {pnl_value:.2f} USDT)
  Open Position: {pos_str}
  Recent Trades:
  {recent_trades}

📉 1m PRICE ACTION:
  Price: {payload.price} | High: {payload.high} | Low: {payload.low}
  RSI(14): {payload.rsi_14} | ATR(14): {payload.atr}
  MACD Status: {payload.macd_status} | MACD Hist: {payload.macd_histogram:.4f}
  Stoch RSI K: {payload.stoch_rsi_k:.2f} | D: {payload.stoch_rsi_d:.2f}
  EMA Trend: {payload.ema_trend} | Session: {payload.session}
  Structure: {payload.structure_type} ({payload.structure_direction})
  Vol Delta Proxy: {payload.volume_delta:.2f} | Funding Rate: {funding_rate:.6f}
  Nearest Swing High: {payload.nearest_swing_high} | Swing Low: {payload.nearest_swing_low}

**POSITION MONITORING RULES:**
You are monitoring the ACTIVE OPEN POSITION on a 1-minute chart. You have 3 options:

1. **CLOSE_LONG / CLOSE_SHORT**: If price is reversing dangerously against you, structure broke opposite, or unrealized PnL is getting very negative → EXIT NOW.
2. **MODIFY**: If the trade is going well and you want to TRAIL your stop loss to lock in profit, or adjust take profit to capture more. Set new_stop_loss and/or new_take_profit.
3. **WAIT**: If the trade is progressing normally and nothing needs to change.

You MUST return your decision as a strictly valid JSON object matching EXACTLY this structure:
```json
{{
  "decision": "WAIT",
  "leverage": null,
  "trade_amount_usdt": null,
  "entry_price": null,
  "stop_loss": null,
  "take_profit": null,
  "new_stop_loss": null,
  "new_take_profit": null,
  "reasoning": "Buraya pozisyon durumunu, tehdit analizini ve kararını TÜRKÇE olarak yaz. (Do NOT use unescaped double quotes or newlines)."
}}
```
CRITICAL: Your response must be ONLY the JSON object. Do not include any other text before or after. The 'reasoning' field MUST be in Turkish, but all other JSON keys and values MUST remain in English."""
    return prompt

def generate_ai_prompt(payload: AIDataPayload, current_balance: float, initial_balance: float, open_position: dict, funding_rate: float, open_interest: float = 0.0, long_short_ratio: float = 1.0) -> str:
    """Format the full SMC payload into a comprehensive prompt for Claude."""
    
    pnl_value = current_balance - initial_balance
    
    pos_str = "None"
    if open_position["has_position"]:
        pos_str = f"ACTIVE {open_position['side']} | Entry: {open_position['entry_price']} | Unrealized PnL: {open_position['unrealized_pnl']} USDT | Duration: {open_position.get('duration_minutes', 0)} mins"
        
    recent_trades = get_recent_trades_summary()

    prompt = f"""=== {payload.symbol} MARKET DATA ({payload.bar_time}) ===

💰 ACCOUNT & POSITIONS:
  Initial Balance: {initial_balance:.2f} USDT
  Current Balance: {current_balance:.2f} USDT
  Total Realized PnL: {pnl_value:.2f} USDT
  Open Position: {pos_str}
  Recent Trades:
  {recent_trades}

📊 PRICE ACTION:
  Price: {payload.price} | High: {payload.high} | Low: {payload.low}
  Volume: {payload.volume} | Vol Delta Proxy: {payload.volume_delta:.2f}
  ATR(14): {payload.atr}
  Body Ratio: {payload.body_ratio:.2f} | Volume Ratio: {payload.volume_ratio:.2f}
  Impulse Candle: {payload.impulse_candle}

📈 TECHNICAL INDICATORS:
  RSI(14): {payload.rsi_14}
  EMA 9: {payload.ema_9} | EMA 21: {payload.ema_21}
  EMA 50: {payload.ema_50} | EMA 200: {payload.ema_200}
  EMA Trend: {payload.ema_trend}
  EMA 50/200 State: {payload.ema_50_200_state}

📉 MOMENTUM:
  MACD Histogram: {payload.macd_histogram:.4f} | MACD Status: {payload.macd_status}
  Stochastic RSI K: {payload.stoch_rsi_k:.2f} | D: {payload.stoch_rsi_d:.2f}
  Bollinger Band Width: {payload.bb_width:.3f}%
  VWAP: {payload.vwap}

🧭 MULTI-TIMEFRAME & SENTIMENT:
  Daily: {payload.daily_bias} | H4: {payload.h4_bias} | H1: {payload.h1_bias}
  HTF (4H) Resistance: {payload.htf_resistance} | HTF (4H) Support: {payload.htf_support}
  Premium/Discount Zone: {payload.premium_discount_zone}
  Funding Rate: {funding_rate:.6f}
  Open Interest: {open_interest:.2f} BTC
  Long/Short Ratio: {long_short_ratio:.4f}

🏗️ MARKET STRUCTURE:
  Structure: {payload.structure_type} ({payload.structure_direction})
  Broken Level: {payload.broken_level}

💧 LIQUIDITY:
  Type: {payload.liquidity_type} | Swept: {payload.liquidity_swept}
  Level: {payload.liquidity_level} | SFP Detected: {payload.sfp_detected}

📦 PD ARRAYS (FVG/OB):
  Type: {payload.pd_array_type} | Direction: {payload.pd_array_direction}
  Zone: {payload.zone_low} - {payload.zone_high} | Status: {payload.zone_status}
  FVG Active: {payload.fvg_active} | OB Active: {payload.ob_active}

🕐 SESSION:
  Current: {payload.session} | Power: {payload.session_power}
  Judas Swing: {payload.judas_swing}
  Asia High: {payload.asia_high} | Asia Low: {payload.asia_low}
  London High: {payload.london_high} | London Low: {payload.london_low}

🕯️ CANDLE & ORDERFLOW:
  Pattern: {payload.candle_pattern}
  Orderflow: {payload.orderflow_direction}

📍 KEY LEVELS:
  Daily Open: {payload.daily_open}
  Previous Day High: {payload.prev_day_high} | Previous Day Low: {payload.prev_day_low}
  Nearest Swing High: {payload.nearest_swing_high}
  Nearest Swing Low: {payload.nearest_swing_low}

Analyze all the above data using ICT/SMC methodology. 
**STRATEGY RULES:** 
1. Do not be overly strict. If the market setup isn't perfect but offers a high-probability, low-risk scalping opportunity for a small profit, you are ALLOWED and ENCOURAGED to take the trade.
2. If you have an Active Open Position, evaluate if the market structure is reversing against you. If so, use "CLOSE_LONG" or "CLOSE_SHORT" to exit the trade early and secure profit or cut losses.
3. You have FULL AUTONOMY over position sizing and leverage. SCALE YOUR RISK BASED ON YOUR CONFIDENCE AND CURRENT BALANCE:
   - **High confidence setup** (strong confluence, multiple confirmations): Use up to 20-25% of Current Balance as notional. Use 10-20x leverage.
   - **Medium confidence** (decent setup, some confluence): Use 10-15% of Current Balance as notional. Use 5-10x leverage.
   - **Low confidence but still tradeable** (scalp opportunity): Use minimum position size. Use 3-5x leverage.
   - Example: Balance=500 USDT, high confidence → trade_amount_usdt=120, leverage=15. Balance=100 USDT, low confidence → trade_amount_usdt=60, leverage=5.
   - "trade_amount_usdt" is NOTIONAL value. Margin cost = trade_amount_usdt / leverage.
   - For BTCUSDT, minimum position is 0.001 BTC (~$60). So "trade_amount_usdt" must be at least 60.
   - NEVER let margin (trade_amount_usdt / leverage) exceed 50% of Current Balance.
4. You are trading {payload.symbol} Perpetual Futures on Binance. This is a crypto market open 24/7.
5. Your goal is to MAXIMIZE profit while protecting capital. The more you earn, the bigger positions you can take. If you are losing, reduce size to survive.
6. If you have an active position and want to adjust SL/TP without closing, use "MODIFY" and set new_stop_loss and/or new_take_profit.

You MUST return your decision as a strictly valid JSON object matching EXACTLY this structure:
```json
{{{{
  "decision": "WAIT",
  "leverage": 10,
  "trade_amount_usdt": 60.0,
  "entry_price": null,
  "stop_loss": null,
  "take_profit": null,
  "new_stop_loss": null,
  "new_take_profit": null,
  "reasoning": "Buraya piyasa analizini, mantığını ve neden bu kararı aldığını TÜRKÇE olarak yaz. (Do NOT use unescaped double quotes or newlines)."
}}}}
```
CRITICAL: Your response must be ONLY the JSON object. Do not include any other text before or after. The 'reasoning' field MUST be in Turkish, but all other JSON keys and values (like LONG, SHORT, WAIT, MODIFY, leverage) MUST remain in English."""
    return prompt

async def get_trade_decision(payload: AIDataPayload) -> AITradeDecision:
    settings = get_settings()

    if not settings.ANTHROPIC_API_KEY:
        logger.warning("No ANTHROPIC_API_KEY provided. Returning WAIT.")
        return AITradeDecision(decision="WAIT", reasoning="No API key provided.")

    if not rate_limiter.can_make_call(settings.MAX_AI_CALLS_PER_DAY):
        logger.warning("Daily AI call limit reached.")
        return AITradeDecision(decision="WAIT", reasoning=f"Daily limit of {settings.MAX_AI_CALLS_PER_DAY} calls reached.")

    client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
    
    current_balance = executor.get_balance()
    
    # Initialize or load initial balance
    initial_balance = load_initial_balance()
    if initial_balance is None and current_balance > 0:
        save_initial_balance(current_balance)
        initial_balance = current_balance
    elif initial_balance is None:
        initial_balance = 0.0
        
    # Get open position and market context
    clean_symbol = payload.symbol.split(":")[-1].replace(".P", "")
    open_pos = executor.get_open_position(clean_symbol)
    funding_rate = executor.get_funding_rate(clean_symbol)
    
    # Fetch Open Interest and Long/Short Ratio
    try:
        from data_fetcher import data_fetcher
        open_interest = data_fetcher.fetch_open_interest(clean_symbol)
        long_short_ratio = data_fetcher.fetch_long_short_ratio(clean_symbol)
    except Exception:
        open_interest = 0.0
        long_short_ratio = 1.0
        
    if payload.timeframe == "1":
        if not open_pos["has_position"]:
            logger.info("1m timeframe but no open position. Skipping AI call to save quota.")
            return AITradeDecision(decision="WAIT", reasoning="No open position to protect on 1m timeframe.")
        user_prompt = generate_protection_prompt(payload, current_balance, initial_balance, open_pos, funding_rate)
    else:
        user_prompt = generate_ai_prompt(payload, current_balance, initial_balance, open_pos, funding_rate, open_interest, long_short_ratio)

    try:
        rate_limiter.increment()
        response = await client.messages.create(
            model=settings.AI_MODEL_NAME,
            max_tokens=1500,
            temperature=0.0,
            system=settings.AI_SYSTEM_PROMPT,
            messages=[
                {"role": "user", "content": user_prompt}
            ]
        )

        content = response.content[0].text

        # JSON extraction: Claude may wrap in ```json ... ```
        json_str = content
        if "```json" in content:
            json_str = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            json_str = content.split("```")[1].split("```")[0].strip()

        data = json.loads(json_str)
        decision_obj = AITradeDecision(**data)
        
        # Save to history
        log_entry = {
            "time": datetime.now(timezone.utc).isoformat(),
            "symbol": payload.symbol,
            "balance": current_balance,
            "prompt": user_prompt,
            "raw_response": content,
            "decision": decision_obj.decision,
            "execution_price": 0.0,
            "execution_msg": ""
        }
        ai_history.insert(0, log_entry)
        if len(ai_history) > 50:
            ai_history.pop()
            
        save_ai_history(ai_history)

        return decision_obj

    except Exception as e:
        logger.error(f"AI API Call failed: {e}")
        return AITradeDecision(decision="WAIT", reasoning=f"API Error: {str(e)}")
