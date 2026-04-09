# test_check_future.py
import sys, os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.database.db import init_db
from app.database.models import PriceData
from datetime import datetime, timezone
import pandas as pd

init_db()

now_utc = datetime.now(timezone.utc)
print(f"Sekarang UTC: {now_utc}")
print()

rows = PriceData.get_latest(limit=10)
print("=== 10 Candle Terakhir ===")
for r in rows:
    ts = r["timestamp"]
    if isinstance(ts, str):
        ts = pd.Timestamp(ts)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    
    is_future = ts > now_utc
    flag      = "⚠️ FUTURE!" if is_future else "✅"
    print(f"  {flag} {ts} | close: ${r['close']:,.2f}")