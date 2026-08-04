"""
smc_engine.py — Smart Money Concepts hesaplamaları.
BoS/ChoCH, FVG, Order Blocks, Likidite, Session H/L, Premium/Discount.
"""
import logging
import pandas as pd
import numpy as np
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)


def find_pivots(df: pd.DataFrame, left: int = 10, right: int = 5) -> dict:
    """Find pivot highs and pivot lows."""
    highs = df['high'].values
    lows = df['low'].values
    n = len(df)

    pivot_highs = []
    pivot_lows = []

    for i in range(left, n - right):
        # Pivot High
        is_ph = True
        for j in range(1, left + 1):
            if highs[i] <= highs[i - j]:
                is_ph = False
                break
        if is_ph:
            for j in range(1, right + 1):
                if highs[i] <= highs[i + j]:
                    is_ph = False
                    break
        if is_ph:
            pivot_highs.append({'index': i, 'price': highs[i], 'time': df.index[i]})

        # Pivot Low
        is_pl = True
        for j in range(1, left + 1):
            if lows[i] >= lows[i - j]:
                is_pl = False
                break
        if is_pl:
            for j in range(1, right + 1):
                if lows[i] >= lows[i + j]:
                    is_pl = False
                    break
        if is_pl:
            pivot_lows.append({'index': i, 'price': lows[i], 'time': df.index[i]})

    last_ph = pivot_highs[-1]['price'] if pivot_highs else 0.0
    last_pl = pivot_lows[-1]['price'] if pivot_lows else 0.0

    return {
        'pivot_highs': pivot_highs,
        'pivot_lows': pivot_lows,
        'nearest_swing_high': round(last_ph, 2),
        'nearest_swing_low': round(last_pl, 2),
    }


def detect_structure(df: pd.DataFrame, pivots: dict) -> dict:
    """Detect BoS / ChoCH / MSS based on pivot breaks."""
    result = {
        'structure_type': 'NONE',
        'structure_direction': 'NONE',
        'broken_level': 0.0,
    }

    if not pivots['pivot_highs'] or not pivots['pivot_lows']:
        return result

    last_close = df['close'].iloc[-1]
    last_ph = pivots['pivot_highs'][-1]['price']
    last_pl = pivots['pivot_lows'][-1]['price']

    # Determine previous trend from last 2 pivots
    prev_trend = 'NONE'
    if len(pivots['pivot_highs']) >= 2 and len(pivots['pivot_lows']) >= 2:
        ph_trend = pivots['pivot_highs'][-1]['price'] > pivots['pivot_highs'][-2]['price']
        pl_trend = pivots['pivot_lows'][-1]['price'] > pivots['pivot_lows'][-2]['price']
        if ph_trend and pl_trend:
            prev_trend = 'BULLISH'
        elif not ph_trend and not pl_trend:
            prev_trend = 'BEARISH'

    # Check for SFP first (for MSS detection)
    sfp_bull = df['low'].iloc[-1] < last_pl and last_close > last_pl
    sfp_bear = df['high'].iloc[-1] > last_ph and last_close < last_ph

    # Break above pivot high
    if last_close > last_ph:
        if prev_trend == 'BEARISH':
            result['structure_type'] = 'MSS' if sfp_bull else 'ChoCH'
        else:
            result['structure_type'] = 'BoS'
        result['structure_direction'] = 'BULLISH'
        result['broken_level'] = round(last_ph, 2)

    # Break below pivot low
    elif last_close < last_pl:
        if prev_trend == 'BULLISH':
            result['structure_type'] = 'MSS' if sfp_bear else 'ChoCH'
        else:
            result['structure_type'] = 'BoS'
        result['structure_direction'] = 'BEARISH'
        result['broken_level'] = round(last_pl, 2)

    return result


def detect_liquidity(df: pd.DataFrame, pivots: dict) -> dict:
    """Detect liquidity sweeps and SFP."""
    result = {
        'liquidity_type': 'NONE',
        'liquidity_swept': False,
        'liquidity_level': 0.0,
        'sfp_detected': False,
    }

    if not pivots['pivot_highs'] or not pivots['pivot_lows']:
        return result

    last = df.iloc[-1]
    last_ph = pivots['pivot_highs'][-1]['price']
    last_pl = pivots['pivot_lows'][-1]['price']

    # Sell-side liquidity sweep (price goes below swing low then closes above)
    if last['low'] < last_pl and last['close'] > last_pl:
        result['liquidity_type'] = 'SELL_SIDE'
        result['liquidity_swept'] = True
        result['liquidity_level'] = round(last_pl, 2)
        result['sfp_detected'] = True

    # Buy-side liquidity sweep (price goes above swing high then closes below)
    elif last['high'] > last_ph and last['close'] < last_ph:
        result['liquidity_type'] = 'BUY_SIDE'
        result['liquidity_swept'] = True
        result['liquidity_level'] = round(last_ph, 2)
        result['sfp_detected'] = True

    return result


def detect_fvg(df: pd.DataFrame) -> dict:
    """Detect Fair Value Gaps in last few bars."""
    result = {
        'fvg_active': False,
        'fvg_direction': 'NONE',
        'fvg_low': 0.0,
        'fvg_high': 0.0,
        'fvg_status': 'NONE',
    }

    if len(df) < 10:
        return result

    # Check last 10 bars for FVGs
    for i in range(-8, -2):
        bar_prev = df.iloc[i - 1]
        bar_curr = df.iloc[i]
        bar_next = df.iloc[i + 1]

        # Bullish FVG: gap between current bar's low and 2-bars-ago high
        if bar_next['low'] > bar_prev['high']:
            gap_size = bar_next['low'] - bar_prev['high']
            body = abs(bar_curr['close'] - bar_curr['open'])
            candle_range = bar_curr['high'] - bar_curr['low']
            if candle_range > 0 and body / candle_range >= 0.5:
                fvg_hi = bar_next['low']
                fvg_lo = bar_prev['high']
                current_price = df['close'].iloc[-1]
                if current_price <= fvg_hi:
                    status = 'MITIGATED' if current_price >= fvg_lo else 'ACTIVE'
                else:
                    status = 'ACTIVE'
                result = {
                    'fvg_active': True,
                    'fvg_direction': 'BULLISH',
                    'fvg_low': round(fvg_lo, 2),
                    'fvg_high': round(fvg_hi, 2),
                    'fvg_status': status,
                }

        # Bearish FVG
        if bar_next['high'] < bar_prev['low']:
            fvg_hi = bar_prev['low']
            fvg_lo = bar_next['high']
            current_price = df['close'].iloc[-1]
            if current_price >= fvg_lo:
                status = 'MITIGATED' if current_price <= fvg_hi else 'ACTIVE'
            else:
                status = 'ACTIVE'
            result = {
                'fvg_active': True,
                'fvg_direction': 'BEARISH',
                'fvg_low': round(fvg_lo, 2),
                'fvg_high': round(fvg_hi, 2),
                'fvg_status': status,
            }

    return result


def detect_order_blocks(df: pd.DataFrame, structure: dict) -> dict:
    """Detect Order Blocks based on structure breaks."""
    result = {
        'ob_active': False,
        'ob_direction': 'NONE',
        'ob_low': 0.0,
        'ob_high': 0.0,
        'ob_status': 'NONE',
    }

    if structure['structure_type'] == 'NONE' or len(df) < 20:
        return result

    # Look back for the last opposing candle before the impulse
    lookback = min(20, len(df) - 1)

    if structure['structure_direction'] == 'BULLISH':
        # Find last bearish candle before the bullish break
        for i in range(2, lookback):
            bar = df.iloc[-i]
            if bar['close'] < bar['open']:  # Bearish candle
                ob_hi = bar['high']
                ob_lo = bar['low']
                current_price = df['close'].iloc[-1]
                mitigated = current_price >= ob_lo and current_price <= ob_hi
                result = {
                    'ob_active': True,
                    'ob_direction': 'BULLISH',
                    'ob_low': round(ob_lo, 2),
                    'ob_high': round(ob_hi, 2),
                    'ob_status': 'MITIGATED' if mitigated else 'ACTIVE',
                }
                break

    elif structure['structure_direction'] == 'BEARISH':
        # Find last bullish candle before the bearish break
        for i in range(2, lookback):
            bar = df.iloc[-i]
            if bar['close'] > bar['open']:  # Bullish candle
                ob_hi = bar['high']
                ob_lo = bar['low']
                current_price = df['close'].iloc[-1]
                mitigated = current_price >= ob_lo and current_price <= ob_hi
                result = {
                    'ob_active': True,
                    'ob_direction': 'BEARISH',
                    'ob_low': round(ob_lo, 2),
                    'ob_high': round(ob_hi, 2),
                    'ob_status': 'MITIGATED' if mitigated else 'ACTIVE',
                }
                break

    return result


def calculate_session_levels(df: pd.DataFrame) -> dict:
    """Calculate Asia and London session highs/lows."""
    result = {
        'session': 'NONE',
        'session_power': 'NORMAL',
        'judas_swing': False,
        'asia_high': 0.0,
        'asia_low': 0.0,
        'london_high': 0.0,
        'london_low': 0.0,
    }

    if df.empty:
        return result

    now = datetime.now(timezone.utc)
    ny_offset = timedelta(hours=-4)  # EDT approximate
    ny_now = now + ny_offset

    # Determine current session (NY time)
    hour = ny_now.hour
    if 18 <= hour or hour < 3:
        result['session'] = 'ASIA'
    elif 3 <= hour < 8:
        result['session'] = 'LONDON'
    elif 8 <= hour < 17:
        result['session'] = 'NEW_YORK'

    # Calculate session levels from today's data
    today = now.date()
    
    # Convert index to UTC if needed
    df_utc = df.copy()
    if df_utc.index.tz is None:
        df_utc.index = df_utc.index.tz_localize('UTC')

    # Asia: 22:00 - 07:00 UTC (approximately 18:00-03:00 NY)
    asia_mask = (df_utc.index.hour >= 22) | (df_utc.index.hour < 7)
    today_mask = df_utc.index.date >= (today - timedelta(days=1))
    asia_data = df_utc[asia_mask & today_mask]

    if not asia_data.empty:
        result['asia_high'] = round(float(asia_data['high'].max()), 2)
        result['asia_low'] = round(float(asia_data['low'].min()), 2)

    # London: 07:00 - 12:00 UTC (approximately 03:00-08:00 NY)
    london_mask = (df_utc.index.hour >= 7) & (df_utc.index.hour < 12)
    london_data = df_utc[london_mask & today_mask]

    if not london_data.empty:
        result['london_high'] = round(float(london_data['high'].max()), 2)
        result['london_low'] = round(float(london_data['low'].min()), 2)

    # Judas Swing detection
    if result['session'] == 'LONDON' and result['asia_high'] > 0:
        last_close = df['close'].iloc[-1]
        last_low = df['low'].iloc[-1]
        last_high = df['high'].iloc[-1]
        if last_low < result['asia_low'] and last_close > result['asia_low']:
            result['judas_swing'] = True
            result['session_power'] = 'JUDAS_SWING_CONFIRMED'
        elif last_high > result['asia_high'] and last_close < result['asia_high']:
            result['judas_swing'] = True
            result['session_power'] = 'JUDAS_SWING_CONFIRMED'

    return result


def calculate_premium_discount(df: pd.DataFrame) -> str:
    """Calculate if price is in premium or discount zone."""
    if len(df) < 100:
        return 'NONE'
    highest = df['high'].tail(100).max()
    lowest = df['low'].tail(100).min()
    equilibrium = (highest + lowest) / 2
    return 'DISCOUNT' if df['close'].iloc[-1] < equilibrium else 'PREMIUM'


def find_htf_levels(df_4h: pd.DataFrame) -> dict:
    """Find HTF resistance and support from 4H pivots."""
    result = {'htf_resistance': 0.0, 'htf_support': 0.0}
    if df_4h.empty or len(df_4h) < 15:
        return result

    pivots = find_pivots(df_4h, left=5, right=5)
    result['htf_resistance'] = pivots['nearest_swing_high']
    result['htf_support'] = pivots['nearest_swing_low']
    return result


def calculate_all_smc(df_5m: pd.DataFrame, df_4h: pd.DataFrame) -> dict:
    """Calculate all SMC metrics. Returns a flat dict of values."""
    result = {}

    # Pivots & Swing Levels
    pivots = find_pivots(df_5m)
    result['nearest_swing_high'] = pivots['nearest_swing_high']
    result['nearest_swing_low'] = pivots['nearest_swing_low']

    # Structure (BoS / ChoCH / MSS)
    structure = detect_structure(df_5m, pivots)
    result.update(structure)

    # Liquidity
    liquidity = detect_liquidity(df_5m, pivots)
    result.update(liquidity)

    # FVG
    fvg = detect_fvg(df_5m)
    result['fvg_active'] = fvg['fvg_active']

    # Order Blocks
    ob = detect_order_blocks(df_5m, structure)
    result['ob_active'] = ob['ob_active']

    # PD Array (prefer FVG, fallback to OB)
    if fvg['fvg_active']:
        result['pd_array_type'] = 'FVG'
        result['pd_array_direction'] = fvg['fvg_direction']
        result['zone_low'] = fvg['fvg_low']
        result['zone_high'] = fvg['fvg_high']
        result['zone_status'] = fvg['fvg_status']
    elif ob['ob_active']:
        result['pd_array_type'] = 'OB'
        result['pd_array_direction'] = ob['ob_direction']
        result['zone_low'] = ob['ob_low']
        result['zone_high'] = ob['ob_high']
        result['zone_status'] = ob['ob_status']
    else:
        result['pd_array_type'] = 'NONE'
        result['pd_array_direction'] = 'NONE'
        result['zone_low'] = 0.0
        result['zone_high'] = 0.0
        result['zone_status'] = 'NONE'

    # Session
    session = calculate_session_levels(df_5m)
    result.update(session)

    # Premium/Discount
    result['premium_discount_zone'] = calculate_premium_discount(df_5m)

    # HTF Levels
    htf = find_htf_levels(df_4h)
    result.update(htf)

    return result
