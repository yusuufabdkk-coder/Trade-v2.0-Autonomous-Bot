"""
indicator_engine.py — Teknik indikatör hesaplamaları.
Tüm hesaplamalar pandas DataFrame üzerinde yapılır.
"""
import logging
import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)


def calc_ema(series: pd.Series, period: int) -> pd.Series:
    """Exponential Moving Average."""
    return series.ewm(span=period, adjust=False).mean()


def calc_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Relative Strength Index."""
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def calc_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average True Range."""
    high, low, close = df['high'], df['low'], df['close']
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.ewm(span=period, adjust=False).mean()


def calc_macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> dict:
    """MACD Line, Signal, Histogram."""
    ema_fast = calc_ema(series, fast)
    ema_slow = calc_ema(series, slow)
    macd_line = ema_fast - ema_slow
    macd_signal = calc_ema(macd_line, signal)
    macd_hist = macd_line - macd_signal
    return {
        'macd_line': macd_line,
        'macd_signal': macd_signal,
        'macd_histogram': macd_hist,
        'macd_status': 'BULLISH' if macd_hist.iloc[-1] > 0 else 'BEARISH'
    }


def calc_stoch_rsi(series: pd.Series, rsi_period: int = 14, stoch_period: int = 14, k_smooth: int = 3, d_smooth: int = 3) -> dict:
    """Stochastic RSI with K and D lines."""
    rsi = calc_rsi(series, rsi_period)
    rsi_min = rsi.rolling(window=stoch_period).min()
    rsi_max = rsi.rolling(window=stoch_period).max()
    stoch_rsi_raw = (rsi - rsi_min) / (rsi_max - rsi_min).replace(0, np.nan) * 100
    k = stoch_rsi_raw.rolling(window=k_smooth).mean()
    d = k.rolling(window=d_smooth).mean()
    return {'stoch_rsi_k': k, 'stoch_rsi_d': d}


def calc_bollinger_bands(series: pd.Series, period: int = 20, std_dev: float = 2.0) -> dict:
    """Bollinger Bands and Width %."""
    mid = series.rolling(window=period).mean()
    std = series.rolling(window=period).std()
    upper = mid + (std * std_dev)
    lower = mid - (std * std_dev)
    width = ((upper - lower) / mid) * 100  # as percentage
    return {'bb_upper': upper, 'bb_lower': lower, 'bb_mid': mid, 'bb_width': width}


def calc_vwap(df: pd.DataFrame) -> pd.Series:
    """Volume Weighted Average Price (intraday reset approximation)."""
    typical_price = (df['high'] + df['low'] + df['close']) / 3
    cum_tp_vol = (typical_price * df['volume']).cumsum()
    cum_vol = df['volume'].cumsum()
    return cum_tp_vol / cum_vol.replace(0, np.nan)


def calc_volume_delta(df: pd.DataFrame) -> float:
    """Volume delta proxy for the last candle."""
    row = df.iloc[-1]
    if row['close'] > row['open']:
        return row['volume']
    elif row['close'] < row['open']:
        return -row['volume']
    return 0.0


def calculate_all_indicators(df: pd.DataFrame) -> dict:
    """Calculate all technical indicators on a 5m DataFrame. Returns dict with latest values."""
    if df.empty or len(df) < 200:
        logger.warning("Not enough data to calculate indicators.")
        return {}

    close = df['close']
    last = df.iloc[-1]

    # EMAs
    ema9 = calc_ema(close, 9)
    ema21 = calc_ema(close, 21)
    ema50 = calc_ema(close, 50)
    ema200 = calc_ema(close, 200)

    # RSI
    rsi = calc_rsi(close, 14)

    # ATR
    atr = calc_atr(df, 14)

    # MACD
    macd = calc_macd(close)

    # Stochastic RSI
    stoch = calc_stoch_rsi(close)

    # Bollinger Bands
    bb = calc_bollinger_bands(close)

    # VWAP
    vwap = calc_vwap(df)

    # Volume delta
    vol_delta = calc_volume_delta(df)

    # Volume ratio
    vol_sma20 = df['volume'].rolling(20).mean()
    vol_ratio = df['volume'].iloc[-1] / vol_sma20.iloc[-1] if vol_sma20.iloc[-1] > 0 else 0

    # Body ratio
    candle_range = last['high'] - last['low']
    body_size = abs(last['close'] - last['open'])
    body_ratio = body_size / candle_range if candle_range > 0 else 0

    # Impulse candle
    impulse = body_ratio >= 0.60 and vol_ratio > 1.0

    # Orderflow direction
    if impulse and last['close'] > last['open']:
        orderflow = "BULLISH"
    elif impulse and last['close'] < last['open']:
        orderflow = "BEARISH"
    else:
        orderflow = "NEUTRAL"

    # Candle pattern
    prev = df.iloc[-2]
    bull_engulf = prev['close'] < prev['open'] and last['close'] > last['open'] and last['close'] > prev['open'] and last['open'] < prev['close']
    bear_engulf = prev['close'] > prev['open'] and last['close'] < last['open'] and last['close'] < prev['open'] and last['open'] > prev['close']
    candle_pattern = "BULLISH_ENGULFING" if bull_engulf else "BEARISH_ENGULFING" if bear_engulf else "NONE"

    # EMA states
    ema_trend = "BULLISH" if close.iloc[-1] > ema200.iloc[-1] else "BEARISH"
    ema_50_200 = "BULLISH_ALIGNMENT" if ema50.iloc[-1] > ema200.iloc[-1] else "BEARISH_ALIGNMENT" if ema50.iloc[-1] < ema200.iloc[-1] else "NEUTRAL"

    return {
        'price': round(last['close'], 2),
        'high': round(last['high'], 2),
        'low': round(last['low'], 2),
        'volume': round(last['volume'], 2),
        'atr': round(float(atr.iloc[-1]) if not pd.isna(atr.iloc[-1]) else 0, 4),
        'rsi_14': round(float(rsi.iloc[-1]) if not pd.isna(rsi.iloc[-1]) else 50, 2),
        'ema_9': round(float(ema9.iloc[-1]), 2),
        'ema_21': round(float(ema21.iloc[-1]), 2),
        'ema_50': round(float(ema50.iloc[-1]), 2),
        'ema_200': round(float(ema200.iloc[-1]), 2),
        'ema_trend': ema_trend,
        'ema_50_200_state': ema_50_200,
        'macd_histogram': round(float(macd['macd_histogram'].iloc[-1]) if not pd.isna(macd['macd_histogram'].iloc[-1]) else 0, 4),
        'macd_status': macd['macd_status'],
        'stoch_rsi_k': round(float(stoch['stoch_rsi_k'].iloc[-1]) if not pd.isna(stoch['stoch_rsi_k'].iloc[-1]) else 50, 2),
        'stoch_rsi_d': round(float(stoch['stoch_rsi_d'].iloc[-1]) if not pd.isna(stoch['stoch_rsi_d'].iloc[-1]) else 50, 2),
        'vwap': round(float(vwap.iloc[-1]) if not pd.isna(vwap.iloc[-1]) else 0, 2),
        'bb_width': round(float(bb['bb_width'].iloc[-1]) if not pd.isna(bb['bb_width'].iloc[-1]) else 0, 3),
        'volume_delta': round(vol_delta, 2),
        'volume_ratio': round(vol_ratio, 3),
        'body_ratio': round(body_ratio, 3),
        'impulse_candle': impulse,
        'orderflow_direction': orderflow,
        'candle_pattern': candle_pattern,
    }


def calculate_mtf_bias(df_1h: pd.DataFrame, df_4h: pd.DataFrame, df_1d: pd.DataFrame) -> dict:
    """Calculate multi-timeframe bias from higher timeframe data."""
    result = {
        'daily_bias': 'NONE', 'h4_bias': 'NONE', 'h1_bias': 'NONE',
        'daily_open': 0.0, 'prev_day_high': 0.0, 'prev_day_low': 0.0,
    }

    # Daily bias
    if not df_1d.empty and len(df_1d) >= 200:
        ema200_d = calc_ema(df_1d['close'], 200)
        result['daily_bias'] = 'BULLISH' if df_1d['close'].iloc[-1] > ema200_d.iloc[-1] else 'BEARISH'
        result['daily_open'] = round(float(df_1d['open'].iloc[-1]), 2)
        if len(df_1d) >= 2:
            result['prev_day_high'] = round(float(df_1d['high'].iloc[-2]), 2)
            result['prev_day_low'] = round(float(df_1d['low'].iloc[-2]), 2)
    elif not df_1d.empty:
        # Use available data even if less than 200
        ema_len = min(len(df_1d), 200)
        ema_d = calc_ema(df_1d['close'], ema_len)
        result['daily_bias'] = 'BULLISH' if df_1d['close'].iloc[-1] > ema_d.iloc[-1] else 'BEARISH'
        result['daily_open'] = round(float(df_1d['open'].iloc[-1]), 2)
        if len(df_1d) >= 2:
            result['prev_day_high'] = round(float(df_1d['high'].iloc[-2]), 2)
            result['prev_day_low'] = round(float(df_1d['low'].iloc[-2]), 2)

    # H4 bias
    if not df_4h.empty and len(df_4h) >= 50:
        ema200_4h = calc_ema(df_4h['close'], min(len(df_4h), 200))
        result['h4_bias'] = 'BULLISH' if df_4h['close'].iloc[-1] > ema200_4h.iloc[-1] else 'BEARISH'

    # H1 bias
    if not df_1h.empty and len(df_1h) >= 50:
        ema200_1h = calc_ema(df_1h['close'], min(len(df_1h), 200))
        result['h1_bias'] = 'BULLISH' if df_1h['close'].iloc[-1] > ema200_1h.iloc[-1] else 'BEARISH'

    return result
