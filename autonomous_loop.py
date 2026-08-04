"""
autonomous_loop.py — TradingView'a ihtiyaç duymadan, Binance'den veri çekip
AI'a besleyen tam otonom döngü. Her 5 dakikada bir çalışır.
"""
import logging
import asyncio
from datetime import datetime, timezone
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from data_fetcher import data_fetcher
from indicator_engine import calculate_all_indicators, calculate_mtf_bias
from smc_engine import calculate_all_smc
from models import AIDataPayload
from ai_trader import get_trade_decision
from binance_executor import executor
from telegram_bot import send_telegram_message
from config import get_settings
import html

logger = logging.getLogger(__name__)

# Trading symbol
SYMBOL = "BTCUSDT"

scheduler = AsyncIOScheduler()


async def run_analysis_cycle():
    """Main analysis cycle — runs every 5 minutes."""
    settings = get_settings()
    
    try:
        logger.info(f"🔄 Autonomous cycle started for {SYMBOL}")

        # 1. Fetch all candle data from Binance
        tf_data = data_fetcher.fetch_all_timeframes(SYMBOL)

        df_5m = tf_data['5m']
        df_1h = tf_data['1h']
        df_4h = tf_data['4h']
        df_1d = tf_data['1d']

        if df_5m.empty or len(df_5m) < 200:
            logger.warning("Not enough 5m data. Skipping cycle.")
            return

        # 2. Fetch market context (funding, OI, L/S ratio)
        market_ctx = data_fetcher.fetch_market_context(SYMBOL)

        # 3. Calculate technical indicators
        indicators = calculate_all_indicators(df_5m)
        if not indicators:
            logger.warning("Indicator calculation failed. Skipping cycle.")
            return

        # 4. Calculate MTF bias
        mtf = calculate_mtf_bias(df_1h, df_4h, df_1d)

        # 5. Calculate SMC structures
        smc = calculate_all_smc(df_5m, df_4h)

        # 6. Build AIDataPayload
        bar_time = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        exchange_sym = f"BINANCE:{SYMBOL}.P"

        payload_data = {
            'symbol': f"{SYMBOL}.P",
            'exchange_symbol': exchange_sym,
            'timeframe': '5',
            'bar_time': bar_time,
            'chart_link': f"https://www.tradingview.com/chart/?symbol=BINANCE%3A{SYMBOL}.P",
            'secret': settings.WEBHOOK_SECRET,
            # Price Action
            'price': indicators.get('price', 0),
            'high': indicators.get('high', 0),
            'low': indicators.get('low', 0),
            'volume': indicators.get('volume', 0),
            'atr': indicators.get('atr', 0),
            # Technicals
            'rsi_14': indicators.get('rsi_14', 50),
            'ema_9': indicators.get('ema_9', 0),
            'ema_21': indicators.get('ema_21', 0),
            'ema_50': indicators.get('ema_50', 0),
            'ema_200': indicators.get('ema_200', 0),
            'ema_trend': indicators.get('ema_trend', 'NONE'),
            'ema_50_200_state': indicators.get('ema_50_200_state', 'NEUTRAL'),
            # Momentum
            'macd_histogram': indicators.get('macd_histogram', 0),
            'macd_status': indicators.get('macd_status', 'NEUTRAL'),
            'stoch_rsi_k': indicators.get('stoch_rsi_k', 50),
            'stoch_rsi_d': indicators.get('stoch_rsi_d', 50),
            'vwap': indicators.get('vwap', 0),
            'bb_width': indicators.get('bb_width', 0),
            # MTF
            'daily_bias': mtf.get('daily_bias', 'NONE'),
            'h4_bias': mtf.get('h4_bias', 'NONE'),
            'h1_bias': mtf.get('h1_bias', 'NONE'),
            'daily_open': mtf.get('daily_open', 0),
            'prev_day_high': mtf.get('prev_day_high', 0),
            'prev_day_low': mtf.get('prev_day_low', 0),
            # SMC
            'structure_type': smc.get('structure_type', 'NONE'),
            'structure_direction': smc.get('structure_direction', 'NONE'),
            'broken_level': smc.get('broken_level', 0),
            'liquidity_type': smc.get('liquidity_type', 'NONE'),
            'liquidity_swept': smc.get('liquidity_swept', False),
            'liquidity_level': smc.get('liquidity_level', 0),
            'sfp_detected': smc.get('sfp_detected', False),
            'pd_array_type': smc.get('pd_array_type', 'NONE'),
            'pd_array_direction': smc.get('pd_array_direction', 'NONE'),
            'zone_low': smc.get('zone_low', 0),
            'zone_high': smc.get('zone_high', 0),
            'zone_status': smc.get('zone_status', 'NONE'),
            'premium_discount_zone': smc.get('premium_discount_zone', 'NONE'),
            'session': smc.get('session', 'NONE'),
            'session_power': smc.get('session_power', 'NORMAL'),
            'judas_swing': smc.get('judas_swing', False),
            'asia_high': smc.get('asia_high', 0),
            'asia_low': smc.get('asia_low', 0),
            'london_high': smc.get('london_high', 0),
            'london_low': smc.get('london_low', 0),
            'htf_resistance': smc.get('htf_resistance', 0),
            'htf_support': smc.get('htf_support', 0),
            # Orderflow
            'candle_pattern': indicators.get('candle_pattern', 'NONE'),
            'orderflow_direction': indicators.get('orderflow_direction', 'NEUTRAL'),
            'body_ratio': indicators.get('body_ratio', 0),
            'volume_ratio': indicators.get('volume_ratio', 0),
            'impulse_candle': indicators.get('impulse_candle', False),
            'volume_delta': indicators.get('volume_delta', 0),
            # Swing Levels
            'nearest_swing_high': smc.get('nearest_swing_high', 0),
            'nearest_swing_low': smc.get('nearest_swing_low', 0),
            'fvg_active': smc.get('fvg_active', False),
            'ob_active': smc.get('ob_active', False),
        }

        payload = AIDataPayload(**payload_data)

        # 7. Send to AI for analysis
        decision = await get_trade_decision(payload)
        logger.info(f"🤖 AI Decision: {decision.decision} | Reasoning: {decision.reasoning[:100]}...")

        # 8. Execute trade if needed
        if decision.decision in ["LONG", "SHORT", "CLOSE_LONG", "CLOSE_SHORT"]:
            clean_sym = SYMBOL
            pos_before = executor.get_open_position(clean_sym)
            execution_result = executor.execute_trade(f"{SYMBOL}.P", decision)

            from ai_trader import ai_history
            if len(ai_history) > 0:
                ai_history[0]["execution_price"] = execution_result.get("price", 0.0)
                ai_history[0]["execution_msg"] = execution_result.get("msg", "")

            safe_reasoning = html.escape(decision.reasoning)
            safe_exec_msg = html.escape(str(execution_result.get('msg', '')))

            if decision.decision in ["CLOSE_LONG", "CLOSE_SHORT"]:
                msg = f"🔴 <b>AI POZİSYON KAPATTI ({decision.decision})</b> 🔴\n\n"
                msg += f"<b>Sembol:</b> {SYMBOL}\n"
                msg += f"<b>Kapanış Fiyatı:</b> {execution_result.get('price') or 'MARKET'}\n\n"
                msg += f"<b>Kapatma Sebebi:</b>\n{safe_reasoning}\n\n"
                msg += f"<b>Borsa Sonucu:</b> {safe_exec_msg}"
            else:
                lev = decision.leverage or 10
                notional = decision.trade_amount_usdt or 60.0
                margin_cost = notional / lev
                msg = f"🤖 <b>AI İŞLEM AÇTI ({decision.decision})</b> 🤖\n\n"
                msg += f"<b>Sembol:</b> {SYMBOL}\n"
                msg += f"⚡ <b>Kaldıraç:</b> {lev}x\n"
                msg += f"<b>Pozisyon Büyüklüğü:</b> {notional} USDT\n"
                msg += f"💳 <b>Kullanılan Teminat:</b> ~{margin_cost:.2f} USDT\n"
                msg += f"<b>Giriş:</b> {execution_result.get('price') or decision.entry_price or 'MARKET'}\n"
                msg += f"<b>Zarar Kes (SL):</b> {decision.stop_loss}\n"
                msg += f"<b>Kar Al (TP):</b> {decision.take_profit}\n\n"
                msg += f"<b>Yapay Zeka Analizi:</b>\n{safe_reasoning}\n\n"
                msg += f"<b>Borsa Sonucu:</b> {safe_exec_msg}"

            # Add market context info
            msg += f"\n\n📊 <b>Piyasa Konteksti:</b>\n"
            msg += f"Funding Rate: {market_ctx['funding_rate']:.6f}\n"
            msg += f"Open Interest: {market_ctx['open_interest']:.2f} BTC\n"
            msg += f"Long/Short Ratio: {market_ctx['long_short_ratio']:.4f}"

            await send_telegram_message(msg)
            logger.info(f"✅ Trade executed and Telegram sent: {decision.decision}")

        elif decision.decision == "MODIFY":
            # AI wants to adjust SL/TP on the open position
            logger.info(f"🔧 AI requested MODIFY: new_sl={decision.new_stop_loss}, new_tp={decision.new_take_profit}")
            safe_reasoning = html.escape(decision.reasoning)
            msg = f"🔧 <b>AI POZİSYON GÜNCELLEDİ (MODIFY)</b> 🔧\n\n"
            msg += f"<b>Sembol:</b> {SYMBOL}\n"
            if decision.new_stop_loss:
                msg += f"<b>Yeni Stop Loss:</b> {decision.new_stop_loss}\n"
            if decision.new_take_profit:
                msg += f"<b>Yeni Take Profit:</b> {decision.new_take_profit}\n"
            msg += f"\n<b>Yapay Zeka Açıklaması:</b>\n{safe_reasoning}"
            await send_telegram_message(msg)

        else:
            logger.info(f"⏳ AI said WAIT. No action taken. Reason: {decision.reasoning[:80]}")

    except Exception as e:
        logger.error(f"❌ Autonomous cycle error: {e}", exc_info=True)


async def run_protection_cycle():
    """1-minute position monitoring cycle — runs only when there's an open position."""
    try:
        clean_symbol = SYMBOL
        open_pos = executor.get_open_position(clean_symbol)

        if not open_pos["has_position"]:
            return  # No position, no need to monitor

        logger.info(f"🛡️ 1m Protection check — monitoring {open_pos['side']} position...")

        # Fetch 1m candle data
        df_1m = data_fetcher.fetch_klines(SYMBOL, '1m', 100)
        if df_1m.empty or len(df_1m) < 30:
            logger.warning("Not enough 1m data. Skipping protection cycle.")
            return

        # Calculate quick indicators on 1m data
        indicators = calculate_all_indicators(df_1m)
        if not indicators:
            return

        # Quick SMC on 1m
        df_4h_empty = pd.DataFrame()
        smc = calculate_all_smc(df_1m, df_4h_empty)

        # Fetch market context
        market_ctx = data_fetcher.fetch_market_context(SYMBOL)

        # Build minimal payload for protection prompt
        bar_time = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        settings = get_settings()

        payload_data = {
            'symbol': f"{SYMBOL}.P",
            'exchange_symbol': f"BINANCE:{SYMBOL}.P",
            'timeframe': '1',
            'bar_time': bar_time,
            'chart_link': '',
            'secret': settings.WEBHOOK_SECRET,
            'price': indicators.get('price', 0),
            'high': indicators.get('high', 0),
            'low': indicators.get('low', 0),
            'volume': indicators.get('volume', 0),
            'atr': indicators.get('atr', 0),
            'rsi_14': indicators.get('rsi_14', 50),
            'ema_9': indicators.get('ema_9', 0),
            'ema_21': indicators.get('ema_21', 0),
            'ema_50': indicators.get('ema_50', 0),
            'ema_200': indicators.get('ema_200', 0),
            'ema_trend': indicators.get('ema_trend', 'NONE'),
            'ema_50_200_state': indicators.get('ema_50_200_state', 'NEUTRAL'),
            'macd_histogram': indicators.get('macd_histogram', 0),
            'macd_status': indicators.get('macd_status', 'NEUTRAL'),
            'stoch_rsi_k': indicators.get('stoch_rsi_k', 50),
            'stoch_rsi_d': indicators.get('stoch_rsi_d', 50),
            'vwap': indicators.get('vwap', 0),
            'bb_width': indicators.get('bb_width', 0),
            'volume_delta': indicators.get('volume_delta', 0),
            'volume_ratio': indicators.get('volume_ratio', 0),
            'body_ratio': indicators.get('body_ratio', 0),
            'impulse_candle': indicators.get('impulse_candle', False),
            'orderflow_direction': indicators.get('orderflow_direction', 'NEUTRAL'),
            'candle_pattern': indicators.get('candle_pattern', 'NONE'),
            'structure_type': smc.get('structure_type', 'NONE'),
            'structure_direction': smc.get('structure_direction', 'NONE'),
            'broken_level': smc.get('broken_level', 0),
            'session': smc.get('session', 'NONE'),
            'nearest_swing_high': smc.get('nearest_swing_high', 0),
            'nearest_swing_low': smc.get('nearest_swing_low', 0),
        }

        payload = AIDataPayload(**payload_data)

        # Send to AI for protection check
        decision = await get_trade_decision(payload)

        if decision.decision in ["CLOSE_LONG", "CLOSE_SHORT"]:
            logger.info(f"🚨 1m PROTECTION: AI closing position — {decision.decision}")
            execution_result = executor.execute_trade(f"{SYMBOL}.P", decision)

            safe_reasoning = html.escape(decision.reasoning)
            safe_exec_msg = html.escape(str(execution_result.get('msg', '')))
            msg = f"🚨 <b>1dk KORUMAdan — POZİSYON KAPATILDI ({decision.decision})</b> 🚨\n\n"
            msg += f"<b>Sembol:</b> {SYMBOL}\n"
            msg += f"<b>Kapanış Fiyatı:</b> {execution_result.get('price') or 'MARKET'}\n\n"
            msg += f"<b>Kapatma Sebebi:</b>\n{safe_reasoning}\n\n"
            msg += f"<b>Borsa Sonucu:</b> {safe_exec_msg}"
            await send_telegram_message(msg)

        elif decision.decision == "MODIFY":
            logger.info(f"🔧 1m PROTECTION: AI modifying position — new_sl={decision.new_stop_loss}, new_tp={decision.new_take_profit}")
            safe_reasoning = html.escape(decision.reasoning)
            msg = f"🔧 <b>1dk KORUMA — POZİSYON GÜNCELLENDİ</b> 🔧\n\n"
            msg += f"<b>Sembol:</b> {SYMBOL}\n"
            if decision.new_stop_loss:
                msg += f"<b>Yeni Stop Loss:</b> {decision.new_stop_loss}\n"
            if decision.new_take_profit:
                msg += f"<b>Yeni Take Profit:</b> {decision.new_take_profit}\n"
            msg += f"\n<b>Yapay Zeka:</b>\n{safe_reasoning}"
            await send_telegram_message(msg)

        else:
            logger.debug(f"🛡️ 1m Protection: WAIT — Position safe. {decision.reasoning[:60]}")

    except Exception as e:
        logger.error(f"❌ Protection cycle error: {e}", exc_info=True)


def start_autonomous_loop():
    """Start both the 5-minute analysis and 1-minute protection loops."""
    logger.info("🚀 Starting Autonomous Trading System...")

    # 5-minute main analysis cycle
    scheduler.add_job(
        run_analysis_cycle,
        'interval',
        minutes=5,
        id='autonomous_trading',
        replace_existing=True,
        max_instances=1,
        next_run_time=datetime.now(timezone.utc),
    )

    # 1-minute position protection cycle
    scheduler.add_job(
        run_protection_cycle,
        'interval',
        minutes=1,
        id='position_protection',
        replace_existing=True,
        max_instances=1,
    )

    scheduler.start()
    logger.info("✅ 5dk Analiz Döngüsü + 1dk Koruma Döngüsü başlatıldı!")


def stop_autonomous_loop():
    """Stop the autonomous trading loop."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("🛑 Autonomous loop stopped.")

