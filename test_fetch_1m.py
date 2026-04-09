# test_fetch_1m.py
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.database.db import init_db
from app.database.models import PriceData1m
from app.data.fetcher import fetch_and_store_1m_ohlc
from datetime import datetime, timezone

init_db()

print(f"Sekarang (UTC): {datetime.now(timezone.utc)}")
print(f"Last timestamp di DB: {PriceData1m.get_latest_timestamp()}")
print(f"Total data: {PriceData1m.get_count()}")
print()
print("Fetching...")
df = fetch_and_store_1m_ohlc()
print(f"Candle baru: {len(df)}")
print(f"Last timestamp sekarang: {PriceData1m.get_latest_timestamp()}")