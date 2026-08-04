import logging
from binance.client import Client
from binance.enums import *
from binance.exceptions import BinanceAPIException
import time
from config import get_settings
from models import AITradeDecision

logger = logging.getLogger(__name__)

class BinanceExecutor:
    def __init__(self):
        self.settings = get_settings()
        self.client = None
        
        if self.settings.BINANCE_API_KEY and self.settings.BINANCE_API_SECRET:
            try:
                self.client = Client(
                    self.settings.BINANCE_API_KEY,
                    self.settings.BINANCE_API_SECRET,
                    testnet=self.settings.BINANCE_TESTNET
                )
                logger.info(f"Binance client initialized. Testnet: {self.settings.BINANCE_TESTNET}")
            except Exception as e:
                logger.error(f"Failed to initialize Binance Client: {e}")

    def get_balance(self) -> float:
        """Fetches the available USDT balance."""
        if not self.client:
            return 0.0
        try:
            account = self.client.futures_account()
            for asset in account['assets']:
                if asset['asset'] == 'USDT':
                    return float(asset['walletBalance'])
            return 0.0
        except Exception as e:
            logger.error(f"Failed to fetch balance: {e}")
            return 0.0
    def get_funding_rate(self, symbol: str) -> float:
        """Fetches the current funding rate for the given symbol."""
        if not self.client:
            return 0.0
            
        clean_symbol = symbol.split(":")[-1].replace(".P", "")
        try:
            funding_info = self.client.futures_funding_rate(symbol=clean_symbol, limit=1)
            if funding_info and len(funding_info) > 0:
                return float(funding_info[0]['fundingRate'])
            return 0.0
        except Exception as e:
            logger.error(f"Failed to fetch funding rate for {clean_symbol}: {e}")
            return 0.0

    def get_open_position(self, symbol: str) -> dict:
        """Fetches the current open position for the given symbol."""
        if not self.client:
            return {"has_position": False, "side": None, "entry_price": 0.0, "unrealized_pnl": 0.0, "quantity": 0.0}
            
        clean_symbol = symbol.split(":")[-1].replace(".P", "")
        try:
            positions = self.client.futures_position_information(symbol=clean_symbol)
            for pos in positions:
                position_amt = float(pos['positionAmt'])
                if position_amt != 0:
                    side = "LONG" if position_amt > 0 else "SHORT"
                    
                    update_time_ms = float(pos.get('updateTime', 0))
                    duration_minutes = 0
                    if update_time_ms > 0:
                        duration_minutes = int((time.time() * 1000 - update_time_ms) / 60000)
                        
                    return {
                        "has_position": True,
                        "side": side,
                        "entry_price": float(pos['entryPrice']),
                        "unrealized_pnl": float(pos['unRealizedProfit']),
                        "quantity": abs(position_amt),
                        "duration_minutes": duration_minutes
                    }
            return {"has_position": False, "side": None, "entry_price": 0.0, "unrealized_pnl": 0.0, "quantity": 0.0, "duration_minutes": 0}
        except Exception as e:
            logger.error(f"Failed to fetch position for {clean_symbol}: {e}")
            return {"has_position": False, "side": None, "entry_price": 0.0, "unrealized_pnl": 0.0, "quantity": 0.0, "duration_minutes": 0}

    def close_position(self, symbol: str) -> dict:
        """Closes any open position for the given symbol."""
        if not self.client:
            return {"status": "simulated", "msg": f"SIMULATED: Closed position on {symbol}", "price": 0.0}
            
        clean_symbol = symbol.split(":")[-1].replace(".P", "")
        pos_info = self.get_open_position(clean_symbol)
        
        if not pos_info["has_position"]:
            return {"status": "error", "msg": f"No open position to close for {clean_symbol}", "price": 0.0}
            
        close_side = SIDE_SELL if pos_info["side"] == "LONG" else SIDE_BUY
        
        try:
            order = self.client.futures_create_order(
                symbol=clean_symbol,
                side=close_side,
                type='MARKET',
                quantity=pos_info["quantity"]
            )
            executed_price = 0.0
            if order.get('avgPrice') and float(order.get('avgPrice')) > 0:
                executed_price = float(order.get('avgPrice'))
            elif order.get('cumQuote') and order.get('executedQty') and float(order.get('executedQty')) > 0:
                executed_price = float(order.get('cumQuote')) / float(order.get('executedQty'))
                
            # Try to cancel all open orders (SL/TP) for this symbol
            try:
                self.client.futures_cancel_all_open_orders(symbol=clean_symbol)
            except Exception as e:
                logger.warning(f"Could not cancel open orders for {clean_symbol}: {e}")

            msg = f"LIVE EXECUTION: CLOSED {pos_info['side']} on {clean_symbol} at {executed_price:.2f} | PnL: {pos_info['unrealized_pnl']:.2f} USDT"
            return {"status": "success", "msg": msg, "price": executed_price, "order_id": order.get('orderId')}
        except Exception as e:
            err = f"Execution Error closing position: {e}"
            logger.error(err)
            return {"status": "error", "msg": err, "price": 0.0}

    def modify_position(self, symbol: str, new_stop_loss: float = None, new_take_profit: float = None) -> dict:
        """Modifies SL/TP for an existing position by canceling open orders and placing new ones."""
        if not self.client:
            return {"status": "simulated", "msg": f"SIMULATED MODIFY on {symbol} (SL:{new_stop_loss} TP:{new_take_profit})", "price": 0.0}
            
        pos_info = self.get_open_position(symbol)
        if not pos_info["has_position"]:
            return {"status": "error", "msg": f"No open position on {symbol} to modify", "price": 0.0}
            
        try:
            # 1. Cancel existing SL/TP orders
            self.client.futures_cancel_all_open_orders(symbol=symbol)
            logger.info(f"Canceled all existing orders for {symbol} to apply new SL/TP.")
            
            # 2. Determine side for closing orders
            close_side = SIDE_SELL if pos_info["side"] == "LONG" else SIDE_BUY
            msg_parts = []
            
            # 3. Place new Stop Loss if provided
            if new_stop_loss:
                self.client.futures_create_order(
                    symbol=symbol,
                    side=close_side,
                    type='STOP_MARKET',
                    stopPrice=new_stop_loss,
                    closePosition=True
                )
                msg_parts.append(f"SL set to {new_stop_loss}")
                
            # 4. Place new Take Profit if provided
            if new_take_profit:
                self.client.futures_create_order(
                    symbol=symbol,
                    side=close_side,
                    type='TAKE_PROFIT_MARKET',
                    stopPrice=new_take_profit,
                    closePosition=True
                )
                msg_parts.append(f"TP set to {new_take_profit}")
                
            msg = f"LIVE EXECUTION: MODIFIED {pos_info['side']} on {symbol} | " + " | ".join(msg_parts)
            return {"status": "success", "msg": msg, "price": 0.0}
            
        except Exception as e:
            err = f"Execution Error modifying position: {e}"
            logger.error(err)
            return {"status": "error", "msg": err, "price": 0.0}


    def execute_trade(self, symbol: str, decision: AITradeDecision) -> dict:
        """Executes the trade on Binance Futures and returns execution details."""
        if not self.client:
            return {"status": "simulated", "msg": f"SIMULATED: {decision.decision} on {symbol}", "price": decision.entry_price or 0.0}

        # Clean symbol (e.g., BYBIT:XAUUSDT.P -> XAUUSDT)
        clean_symbol = symbol.split(":")[-1].replace(".P", "")
        
        # Handle CLOSE and MODIFY commands first
        if decision.decision in ["CLOSE_LONG", "CLOSE_SHORT"]:
            return self.close_position(clean_symbol)
            
        if decision.decision == "MODIFY":
            return self.modify_position(clean_symbol, decision.new_stop_loss, decision.new_take_profit)
            
        side = SIDE_BUY if decision.decision == "LONG" else SIDE_SELL

        try:
            # Set leverage dynamically (AI decides per trade)
            leverage = decision.leverage if decision.leverage and 1 <= decision.leverage <= 125 else 10
            try:
                self.client.futures_change_leverage(symbol=clean_symbol, leverage=leverage)
                logger.info(f"Leverage set to {leverage}x for {clean_symbol}")
            except Exception as e:
                logger.warning(f"Could not set leverage to {leverage}x: {e}")

            # Fetch current mark price
            mark_price_info = self.client.futures_mark_price(symbol=clean_symbol)
            current_price = float(mark_price_info['markPrice'])
            
            # Default USDT amount if AI doesn't specify
            usdt_amount = decision.trade_amount_usdt if decision.trade_amount_usdt and decision.trade_amount_usdt > 0 else 15.0
            
            # Symbol-aware step size (minimum lot size)
            # BTC: 0.001, ETH: 0.001, others: 0.1 or 1 etc.
            # We fetch exchange info to get the correct step size
            try:
                exchange_info = self.client.futures_exchange_info()
                step_size = 0.001  # sensible default
                min_qty = 0.001
                for s in exchange_info['symbols']:
                    if s['symbol'] == clean_symbol:
                        for f in s['filters']:
                            if f['filterType'] == 'LOT_SIZE':
                                step_size = float(f['stepSize'])
                                min_qty = float(f['minQty'])
                                break
                        break
            except Exception:
                step_size = 0.001
                min_qty = 0.001
            
            # Calculate raw quantity from USDT amount
            raw_quantity = usdt_amount / current_price
            
            # Round DOWN to the nearest step size
            import math
            precision = max(0, -int(math.floor(math.log10(step_size)))) if step_size < 1 else 0
            quantity = math.floor(raw_quantity / step_size) * step_size
            quantity = round(quantity, precision)
            
            # Enforce minimum quantity
            if quantity < min_qty:
                quantity = min_qty
                logger.warning(f"Quantity too small for {clean_symbol}, using minimum: {min_qty}. This requires ~{min_qty * current_price:.2f} USDT.")
            
            # Enforce minimum notional (Binance requires at least 5 USDT value)
            if quantity * current_price < 5:
                quantity = math.ceil((6.0 / current_price) / step_size) * step_size
                quantity = round(quantity, precision)

            # Place Market Order
            order = self.client.futures_create_order(
                symbol=clean_symbol,
                side=side,
                type='MARKET',
                quantity=quantity
            )
            
            
            executed_price = 0.0
            if order.get('avgPrice') and float(order.get('avgPrice')) > 0:
                executed_price = float(order.get('avgPrice'))
            elif order.get('cumQuote') and order.get('executedQty') and float(order.get('executedQty')) > 0:
                executed_price = float(order.get('cumQuote')) / float(order.get('executedQty'))

            msg = f"LIVE EXECUTION: {decision.decision} {clean_symbol} | Order ID: {order.get('orderId')}"
            
            # Place SL/TP if provided
            if decision.stop_loss:
                sl_side = SIDE_SELL if side == SIDE_BUY else SIDE_BUY
                self.client.futures_create_order(
                    symbol=clean_symbol,
                    side=sl_side,
                    type='STOP_MARKET',
                    stopPrice=decision.stop_loss,
                    closePosition=True
                )
                msg += f" | SL set at {decision.stop_loss}"
                
            if decision.take_profit:
                tp_side = SIDE_SELL if side == SIDE_BUY else SIDE_BUY
                self.client.futures_create_order(
                    symbol=clean_symbol,
                    side=tp_side,
                    type='TAKE_PROFIT_MARKET',
                    stopPrice=decision.take_profit,
                    closePosition=True
                )
                msg += f" | TP set at {decision.take_profit}"

            return {"status": "success", "msg": msg, "price": executed_price, "order_id": order.get('orderId')}
            
        except BinanceAPIException as e:
            err = f"Binance API Error: {e.message}"
            logger.error(err)
            return {"status": "error", "msg": err, "price": 0.0}
        except Exception as e:
            err = f"Execution Error: {e}"
            logger.error(err)
            return {"status": "error", "msg": err, "price": 0.0}

executor = BinanceExecutor()
