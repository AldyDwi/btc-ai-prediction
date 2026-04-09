# test_run_trading.py
import sys, os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.database.db import init_db
from app.data.fetcher import fetch_current_price_from_db
from app.database.models import PriceData, SystemState
from app.data.processor import compute_indicators
from app.services.paper_trading import _generate_signal, get_portfolio
import pandas as pd

init_db()

price = fetch_current_price_from_db()
print(f"Harga sekarang: ${price:,.2f}\n")

# Cek state
state = SystemState.get()
print(f"=== System State ===")
print(f"trading_on  : {state.get('trading_on')}")
print(f"paper_trade : {state.get('paper_trade')}")

# Cek data
rows = PriceData.get_latest(limit=500)
print(f"\n=== Data ===")
print(f"Rows dari DB : {len(rows) if rows else 0}")

if not rows or len(rows) < 2:
    print("❌ Data tidak cukup, berhenti di sini")
    exit()

df = pd.DataFrame(rows)
print(f"Kolom       : {list(df.columns)}")
print(f"ma_200 ada  : {'ma_200' in df.columns}")

if "ma_200" not in df.columns:
    print("Hitung indikator...")
    df = compute_indicators(df)
    print(f"ma_200 ada  : {'ma_200' in df.columns}")
    print(f"Rows setelah indikator: {len(df)}")

if df.empty or len(df) < 2:
    print("❌ Data setelah indikator kosong")
    exit()

row      = df.iloc[-1]
prev_row = df.iloc[-2]

print(f"\n=== Indikator ===")
print(f"close  : {row.get('close')}")
print(f"rsi    : {row.get('rsi')}")
print(f"macd   : {row.get('macd')}")
print(f"ma_200 : {row.get('ma_200')}")

row_with_price          = row.copy()
row_with_price["close"] = price

signal = _generate_signal(row_with_price, prev_row)
print(f"\n=== Signal ===")
print(f"Action : {signal['action']}")
print(f"Score  : {signal['score']}")
print(f"RSI    : {signal['rsi']}")

# Eksekusi langsung
portfolio = get_portfolio()
print(f"\n=== Portfolio Sebelum ===")
print(f"Balance : ${portfolio.balance:,.2f}")
print(f"BTC     : {portfolio.btc:.6f}")

print(f"\nEksekusi...")
portfolio.execute(signal, price)

print(f"\n=== Portfolio Setelah ===")
print(f"Balance : ${portfolio.balance:,.2f}")
print(f"BTC     : {portfolio.btc:.6f}")