"""Стратегии: каждая возвращает массив сигналов по закрытию бара (1 BUY, -1 SELL, 0 нет)."""
from .xadz import xadz_signals
from .fvg_bos import fvg_bos_signals
from . import popular

STRATEGIES = {
    "TR / XADz ZigZag (развороты)": lambda df: xadz_signals(df, 190, reentry=False),
    "TR / XADz ZigZag + повторные входы": lambda df: xadz_signals(df, 190, reentry=True),
    "FVG: OB + FVG + BOS": lambda df: fvg_bos_signals(df),
    "FVG: OB + FVG + BOS по тренду EMA200": lambda df: fvg_bos_signals(df, trend_filter=True),
    "EMA 9/21 + RSI": popular.ema_cross_rsi,
    "MACD + EMA200": popular.macd_trend,
    "Bollinger + RSI (возврат к средней)": popular.bollinger_rsi,
    "Пробой Дончиана 20 + EMA200": popular.donchian_breakout,
    "Supertrend 10/3": popular.supertrend,
}
