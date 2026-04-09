from dataclasses import dataclass
from app.utils.config import config
from app.utils.logger import get_logger

log = get_logger(__name__)


@dataclass
class Signal:
    action    : str    # BUY / SELL / HOLD
    score     : int
    confidence: float  # 0.0 – 1.0
    reasons   : list[str]


def hybrid_signal(
    current_price : float,
    pred_avg      : float,
    rsi           : float,
    macd          : float,
    macd_signal   : float,
    ma_20         : float,
    ma_50         : float
) -> Signal:
    """
    Strategi hybrid AI + rule-based.
    
    Scoring system (max 5 poin):
    +1 AI bullish (pred_avg > current * 1.005)
    +1 RSI < oversold
    +1 MACD > MACD Signal (bullish crossover)
    +1 Harga di atas MA20
    +1 MA20 di atas MA50 (uptrend)
    
    Kebalikannya untuk bearish.
    """
    score   = 0
    reasons = []

    price_change_pct = (pred_avg - current_price) / current_price * 100

    # ── AI Signal ─────────────────────────────────────────────
    if price_change_pct > 0.5:
        score += 1
        reasons.append(f"AI bullish +{price_change_pct:.2f}%")
    elif price_change_pct < -0.5:
        score -= 1
        reasons.append(f"AI bearish {price_change_pct:.2f}%")

    # ── RSI ───────────────────────────────────────────────────
    if rsi < config.RSI_OVERSOLD:
        score += 1
        reasons.append(f"RSI oversold ({rsi:.1f})")
    elif rsi > config.RSI_OVERBOUGHT:
        score -= 1
        reasons.append(f"RSI overbought ({rsi:.1f})")

    # ── MACD ──────────────────────────────────────────────────
    if macd > macd_signal:
        score += 1
        reasons.append("MACD bullish crossover")
    elif macd < macd_signal:
        score -= 1
        reasons.append("MACD bearish crossover")

    # ── Harga vs MA20 ─────────────────────────────────────────
    if current_price > ma_20:
        score += 1
        reasons.append("Price above MA20")
    else:
        score -= 1
        reasons.append("Price below MA20")

    # ── MA Trend ──────────────────────────────────────────────
    if ma_20 > ma_50:
        score += 1
        reasons.append("MA20 > MA50 (uptrend)")
    else:
        score -= 1
        reasons.append("MA20 < MA50 (downtrend)")

    # ── Tentukan aksi ─────────────────────────────────────────
    confidence = abs(score) / 5.0    # normalized 0–1

    if score >= config.MIN_SCORE:
        action = "BUY"
    elif score <= -config.MIN_SCORE:
        action = "SELL"
    else:
        action = "HOLD"

    log.info(
        f"📊 Signal: {action} | Score: {score}/5 | "
        f"Conf: {confidence:.0%} | {', '.join(reasons)}"
    )

    return Signal(
        action     = action,
        score      = score,
        confidence = confidence,
        reasons    = reasons
    )