# test_signal.py
import sys, os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.database.db import init_db
from app.database.models import PriceData, SystemState
from app.data.processor import compute_indicators
from app.services.paper_trading import (
    _generate_signal, get_portfolio, BEST_COOLDOWN_HOUR
)
from datetime import datetime, timezone
import pandas as pd

init_db()

print("=== DEBUG PAPER TRADING ===\n")

# Cek system state
state = SystemState.get()
print(f"trading_on : {state.get('trading_on')}")
print(f"paper_trade: {state.get('paper_trade')}")

# Cek portfolio
portfolio = get_portfolio()
status    = portfolio.get_status()
print(f"\n=== Portfolio ===")
print(f"Balance    : ${status['balance']:,.2f}")
print(f"BTC        : {status['btc']:.6f}")
print(f"Position   : {status['position']}")
print(f"Last trade : {status['last_trade']}")
print(f"Cooldown   : {status['cooldown_remaining_h']} jam tersisa")

# Cek data
rows = PriceData.get_latest(limit=500)
df   = pd.DataFrame(rows)
df   = compute_indicators(df)

print(f"\n=== Data ===")
print(f"Total rows : {len(df)}")
print(f"MA200 ada  : {'ma_200' in df.columns}")

row      = df.iloc[-1]
prev_row = df.iloc[-2]

print(f"\n=== Indikator Terbaru ===")
print(f"Close  : ${float(row['close']):,.2f}")
print(f"RSI    : {float(row.get('rsi', 0)):.2f}")
print(f"MACD   : {float(row.get('macd', 0)):.4f}")
print(f"Signal : {float(row.get('macd_signal', 0)):.4f}")
print(f"MA20   : {float(row.get('ma_20', 0)):,.2f}")
print(f"MA50   : {float(row.get('ma_50', 0)):,.2f}")
print(f"MA200  : {float(row.get('ma_200', 0)):,.2f}")
print(f"Volume : {float(row.get('volume', 0)):,.4f}")

# Generate signal
signal = _generate_signal(row, prev_row)
print(f"\n=== Signal ===")
print(f"Action  : {signal['action']}")
print(f"Score   : {signal['score']}")
print(f"RSI     : {signal['rsi']}")
print(f"Uptrend : {signal['in_uptrend']}")
print(f"Reasons :")
for r in signal["reasons"]:
    print(f"  {r}")

print(f"\n=== Threshold ===")
print(f"MIN_SCORE    : 5")
print(f"BUY  kondisi : score >= 5 AND rsi < 45")
print(f"SELL kondisi : score <= -5 AND rsi > 55")
print(f"Cooldown     : {BEST_COOLDOWN_HOUR} jam")
print(f"\nKesimpulan:")
if signal["score"] >= 5 and signal["rsi"] < 45:
    print(f"  ✅ Akan BUY")
elif signal["score"] <= -5 and signal["rsi"] > 55:
    print(f"  ✅ Akan SELL")
else:
    print(f"  ❌ HOLD — score={signal['score']}, rsi={signal['rsi']}")
    if signal["score"] < 5:
        print(f"     Score kurang {5 - signal['score']} poin untuk BUY")
    if signal["rsi"] >= 45:
        print(f"     RSI {signal['rsi']} terlalu tinggi untuk BUY (butuh < 45)")