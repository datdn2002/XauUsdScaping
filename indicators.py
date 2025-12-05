def calculate_sma(prices, period):
    """
    Calculate Simple Moving Average.
    Returns the SMA value for the most recent period, or None if not enough data.
    """
    if prices is None or len(prices) < period:
        return None
    return sum(prices[-period:]) / period


def calculate_ema(prices, period):
    """
    Calculate Exponential Moving Average.
    Returns the EMA value for the most recent period, or None if not enough data.
    """
    if prices is None or len(prices) < period:
        return None
    
    multiplier = 2 / (period + 1)
    # Start with SMA for initial EMA
    ema = sum(prices[:period]) / period
    
    # Calculate EMA for remaining prices
    for price in prices[period:]:
        ema = (price - ema) * multiplier + ema
    
    return ema


def calculate_rsi(prices, period=14):
    """
    Calculate Relative Strength Index.
    Returns the RSI value (0-100), or None if not enough data.
    """
    if prices is None or len(prices) < period + 1:
        return None
    
    # Calculate price changes
    changes = [prices[i] - prices[i-1] for i in range(1, len(prices))]
    
    # Separate gains and losses
    gains = [max(0, change) for change in changes]
    losses = [max(0, -change) for change in changes]
    
    # Calculate initial average gain and loss
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    
    # Calculate smoothed averages for remaining periods
    for i in range(period, len(changes)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    
    # Calculate RSI
    if avg_loss == 0:
        return 100
    
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    
    return rsi
