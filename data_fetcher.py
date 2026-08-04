"""
data_fetcher.py — Binance API'den çoklu zaman diliminde veri çeker.
Mum verileri, funding rate, open interest, long/short oranı.
"""
import logging
import pandas as pd
import numpy as np
from datetime import datetime, timezone
from binance.client import Client
from config import get_settings

logger = logging.getLogger(__name__)

class BinanceDataFetcher:
    def __init__(self):
        settings = get_settings()
        if settings.BINANCE_API_KEY and settings.BINANCE_API_SECRET:
            self.client = Client(settings.BINANCE_API_KEY, settings.BINANCE_API_SECRET, testnet=settings.BINANCE_TESTNET)
        else:
            self.client = None
            logger.warning("No Binance API keys. Data fetcher disabled.")

    def fetch_klines(self, symbol: str, interval: str, limit: int = 300) -> pd.DataFrame:
        """Fetch OHLCV candle data from Binance Futures."""
        if not self.client:
            return pd.DataFrame()
        
        clean_symbol = symbol.split(":")[-1].replace(".P", "")
        try:
            klines = self.client.futures_klines(symbol=clean_symbol, interval=interval, limit=limit)
            df = pd.DataFrame(klines, columns=[
                'timestamp', 'open', 'high', 'low', 'close', 'volume',
                'close_time', 'quote_volume', 'trades', 'taker_buy_base',
                'taker_buy_quote', 'ignore'
            ])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            for col in ['open', 'high', 'low', 'close', 'volume', 'quote_volume', 'taker_buy_base', 'taker_buy_quote']:
                df[col] = df[col].astype(float)
            df.set_index('timestamp', inplace=True)
            return df
        except Exception as e:
            logger.error(f"Failed to fetch klines for {clean_symbol} {interval}: {e}")
            return pd.DataFrame()

    def fetch_funding_rate(self, symbol: str) -> float:
        """Fetch current funding rate."""
        if not self.client:
            return 0.0
        clean_symbol = symbol.split(":")[-1].replace(".P", "")
        try:
            info = self.client.futures_funding_rate(symbol=clean_symbol, limit=1)
            if info and len(info) > 0:
                return float(info[0]['fundingRate'])
            return 0.0
        except Exception as e:
            logger.error(f"Failed to fetch funding rate: {e}")
            return 0.0

    def fetch_open_interest(self, symbol: str) -> float:
        """Fetch open interest value."""
        if not self.client:
            return 0.0
        clean_symbol = symbol.split(":")[-1].replace(".P", "")
        try:
            oi = self.client.futures_open_interest(symbol=clean_symbol)
            return float(oi.get('openInterest', 0))
        except Exception as e:
            logger.error(f"Failed to fetch open interest: {e}")
            return 0.0

    def fetch_long_short_ratio(self, symbol: str) -> float:
        """Fetch top trader long/short ratio."""
        if not self.client:
            return 1.0
        clean_symbol = symbol.split(":")[-1].replace(".P", "")
        try:
            ratio = self.client.futures_top_longshort_position_ratio(symbol=clean_symbol, period='5m', limit=1)
            if ratio and len(ratio) > 0:
                return float(ratio[0].get('longShortRatio', 1.0))
            return 1.0
        except Exception as e:
            logger.error(f"Failed to fetch long/short ratio: {e}")
            return 1.0

    def fetch_mark_price(self, symbol: str) -> float:
        """Fetch current mark price."""
        if not self.client:
            return 0.0
        clean_symbol = symbol.split(":")[-1].replace(".P", "")
        try:
            info = self.client.futures_mark_price(symbol=clean_symbol)
            return float(info.get('markPrice', 0))
        except Exception as e:
            logger.error(f"Failed to fetch mark price: {e}")
            return 0.0

    def fetch_all_timeframes(self, symbol: str) -> dict:
        """Fetch candle data for all needed timeframes."""
        return {
            '5m': self.fetch_klines(symbol, Client.KLINE_INTERVAL_5MINUTE, 300),
            '1h': self.fetch_klines(symbol, Client.KLINE_INTERVAL_1HOUR, 200),
            '4h': self.fetch_klines(symbol, Client.KLINE_INTERVAL_4HOUR, 200),
            '1d': self.fetch_klines(symbol, Client.KLINE_INTERVAL_1DAY, 50),
        }

    def fetch_market_context(self, symbol: str) -> dict:
        """Fetch all market context data (funding, OI, L/S ratio)."""
        return {
            'funding_rate': self.fetch_funding_rate(symbol),
            'open_interest': self.fetch_open_interest(symbol),
            'long_short_ratio': self.fetch_long_short_ratio(symbol),
            'mark_price': self.fetch_mark_price(symbol),
        }


# Singleton
data_fetcher = BinanceDataFetcher()
