# test_debug_1h.py
import sys, os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.database.db import init_db
from app.database.models import PriceData
from datetime import datetime, timezone, timedelta
import pandas as pd

init_db()

rows = PriceData.get_latest(limit=5)

print("=== Raw Data dari DB ===")
for r in rows:
    print(f"  raw timestamp: {repr(r['timestamp'])}")

print()

now_utc = datetime.now(timezone.utc)
last_ts = rows[-1]["timestamp"] if rows else None

if last_ts:
    if isinstance(last_ts, str):
        last_ts = pd.Timestamp(last_ts)
    
    print(f"=== Parsing Timestamp ===")
    print(f"  Type          : {type(last_ts)}")
    print(f"  tzinfo        : {last_ts.tzinfo}")
    print(f"  Raw value     : {last_ts}")
    
    if last_ts.tzinfo is None:
        last_ts_utc = last_ts.replace(tzinfo=timezone.utc)
        print(f"  Setelah localize: {last_ts_utc}")
    else:
        last_ts_utc = last_ts.astimezone(timezone.utc)
        print(f"  Setelah convert : {last_ts_utc}")
    
    next_candle = last_ts_utc + timedelta(hours=1)
    remaining   = next_candle - now_utc
    
    print(f"\n=== Kalkulasi ===")
    print(f"  now_utc       : {now_utc}")
    print(f"  last_ts_utc   : {last_ts_utc}")
    print(f"  next_candle   : {next_candle}")
    print(f"  remaining     : {remaining}")
    print(f"  total_seconds : {remaining.total_seconds():.0f}")
    print(f"  Status        : {'⏳ Belum' if remaining.total_seconds() > 0 else '✅ Siap'}")