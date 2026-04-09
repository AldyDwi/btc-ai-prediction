# test_fetch_1h.py

import sys, os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.database.db import init_db
from app.database.models import PriceData
from app.data.fetcher import fetch_ohlc_kraken, INTERVAL_1H
from datetime import datetime, timezone, timedelta
import pandas as pd

init_db()

now_utc = datetime.now(timezone.utc)
now_wib = now_utc + timedelta(hours=7)

print(f"=== STATUS ===")
print(f"Sekarang UTC : {now_utc.strftime('%Y-%m-%d %H:%M:%S')} UTC")
print(f"Sekarang WIB : {now_wib.strftime('%Y-%m-%d %H:%M:%S')} WIB")

# Data terakhir di DB
rows = PriceData.get_latest(limit=3)
print(f"\n=== Data Terakhir di DB ===")
for r in rows:
    ts = r["timestamp"]
    if isinstance(ts, str):
        ts = pd.Timestamp(ts)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    ts_wib = ts + timedelta(hours=7)
    print(
        f"  UTC: {ts.strftime('%H:%M')} | "
        f"WIB: {ts_wib.strftime('%H:%M')} | "
        f"close: ${r['close']:,.2f}"
    )

# Analisis kapan candle berikutnya tersedia
last_ts = rows[-1]["timestamp"] if rows else None
if last_ts:
    if isinstance(last_ts, str):
        last_ts = pd.Timestamp(last_ts)
    if last_ts.tzinfo is None:
        last_ts = last_ts.replace(tzinfo=timezone.utc)

    next_candle = last_ts + timedelta(hours=1)
    remaining   = next_candle - now_utc

    print(f"\n=== Analisis Candle ===")
    print(
        f"Last candle  : "
        f"{last_ts.strftime('%H:%M')} UTC / "
        f"{(last_ts+timedelta(hours=7)).strftime('%H:%M')} WIB"
    )
    print(
        f"Next candle  : "
        f"{next_candle.strftime('%H:%M')} UTC / "
        f"{(next_candle+timedelta(hours=7)).strftime('%H:%M')} WIB"
    )

    if remaining.total_seconds() > 0:
        mins = int(remaining.total_seconds() / 60)
        print(
            f"Status       : ⏳ Tunggu {mins} menit lagi "
            f"sampai candle berikutnya closed"
        )
    else:
        print(f"Status       : ✅ Candle baru siap diambil!")

        since = int(last_ts.timestamp())
        df    = fetch_ohlc_kraken(interval=INTERVAL_1H, since=since)

        print(f"\n=== Raw dari Kraken ===")
        if not df.empty:
            print(f"Total candle : {len(df)}")
            print(f"Range        : {df['timestamp'].iloc[0]} → {df['timestamp'].iloc[-1]}")
            print(f"\n5 Candle terakhir:")
            for _, row in df.tail(5).iterrows():
                print(f"  {row['timestamp']} | close: ${float(row['close']):,.2f}")

            if df["timestamp"].dt.tz is None:
                df["timestamp"] = df["timestamp"].dt.tz_localize("UTC")

            print(f"\n=== Filter ===")
            print(f"last_ts      : {last_ts}")
            print(f"Candle > last_ts:")
            df_new = df[df["timestamp"] > last_ts]
            print(f"  Jumlah     : {len(df_new)}")
            if not df_new.empty:
                for _, row in df_new.iterrows():
                    print(f"  {row['timestamp']} | close: ${float(row['close']):,.2f}")
            else:
                print("  (kosong)")

            # Cek now_utc vs candle terakhir
            now_utc_check = pd.Timestamp.now(tz="UTC")
            last_candle   = df.iloc[-1]["timestamp"]
            candle_end    = last_candle + pd.Timedelta(minutes=60)
            print(f"\n=== Cek Candle Last ===")
            print(f"now_utc      : {now_utc_check}")
            print(f"last_candle  : {last_candle}")
            print(f"candle_end   : {candle_end}")
            print(f"Belum closed : {candle_end > now_utc_check}")
        else:
            print("❌ Kraken return kosong / timeout")