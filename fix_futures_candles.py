# fix_future_candles.py
import sys, os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.database.db import init_db, get_conn
from datetime import datetime, timezone

init_db()

now_utc = datetime.now(timezone.utc)
# Buat versi naive (tanpa timezone) untuk compare dengan DB
now_naive = now_utc.replace(tzinfo=None)

print(f"Sekarang UTC (aware) : {now_utc}")
print(f"Sekarang UTC (naive) : {now_naive}")

with get_conn() as conn:
    with conn.cursor() as cur:

        # Cek candle future — pakai now NAIVE agar cocok dengan DB
        cur.execute("""
            SELECT COUNT(*), MIN(timestamp), MAX(timestamp)
            FROM price_data
            WHERE timestamp > %s
        """, (now_naive,))
        row   = cur.fetchone()
        count = row["count"]
        min_ts = row["min"]
        max_ts = row["max"]

        print(f"\nCandle future di DB : {count}")
        if count > 0:
            print(f"  Range: {min_ts} → {max_ts}")

            # Hapus candle future
            cur.execute("""
                DELETE FROM price_data
                WHERE timestamp > %s
            """, (now_naive,))
            print(f"✅ {count} candle future dihapus!")
        else:
            print("✅ Tidak ada candle future")

        # Verifikasi
        cur.execute("""
            SELECT timestamp, close
            FROM price_data
            ORDER BY timestamp DESC
            LIMIT 5
        """)
        rows = cur.fetchall()
        print(f"\n=== 5 Candle Terakhir Setelah Cleanup ===")
        for r in rows:
            print(f"  {r['timestamp']} | close: ${r['close']:,.2f}")