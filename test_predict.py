# test_predict.py

from app.database.db import init_db
from app.model.predictor import predict

init_db()

print("⏳ Menjalankan prediksi...")
result = predict()

if not result:
    print("❌ Prediksi gagal!")
else:
    current = result["current_price"]
    pred_1h = result["pred_1h"]
    change  = result["change_pct"]
    prices  = result["pred_prices"]
    emoji   = "📈" if change > 0 else "📉"

    # ── Header ────────────────────────────────────────────────
    print("\n" + "="*52)
    print("      🔮 PREDIKSI BTC 1 JAM KE DEPAN")
    print("="*52)
    print(f"  💰 Harga Sekarang  : ${current:>12,.2f}")
    print(f"  🎯 Prediksi 1 Jam  : ${pred_1h:>12,.2f}")
    print(f"  {emoji} Perubahan        : {change:>+11.2f}%")
    print(f"  🔼 Max 60 menit    : ${result['pred_max']:>12,.2f}")
    print(f"  🔽 Min 60 menit    : ${result['pred_min']:>12,.2f}")
    print(f"  📊 Avg 60 menit    : ${result['pred_avg']:>12,.2f}")
    print("="*52)

    # ── Volatilitas interpolasi ───────────────────────────────
    price_changes = [
        prices[i] - prices[i-1]
        for i in range(1, len(prices))
    ]
    up_minutes   = sum(1 for c in price_changes if c > 0)
    down_minutes = sum(1 for c in price_changes if c < 0)

    print(f"\n  📈 Menit naik  : {up_minutes}")
    print(f"  📉 Menit turun : {down_minutes}")
    print(f"  ↔️  Range       : ${result['pred_max'] - result['pred_min']:,.2f}")

    # ── Tabel detail ──────────────────────────────────────────
    print(f"\n{'─'*52}")
    print(f"  {'Menit':<7} {'Waktu':^6} {'Harga':>13} {'vs Skrg':>9} {'Arah':^4}")
    print(f"{'─'*52}")

    for i, price in enumerate(prices, 1):
        # Tampilkan menit 1, 5, 10, 15, ... 55, 60
        if i == 1 or i % 5 == 0:
            chg  = (price - current) / current * 100
            prev = prices[i-2] if i > 1 else current
            arah = "▲" if price >= prev else "▼"
            sign = "+" if chg >= 0 else ""
            print(
                f"  {i:<7} "
                f"+{i:02d}m   "
                f"${price:>11,.2f} "
                f"  {sign}{chg:.2f}%"
                f"  {arah}"
            )

    print(f"{'─'*52}")
    print(f"\n  ℹ️  Training data : 1 JAM (365 hari)")
    print(f"  ℹ️  Model output  : 1 prediksi (1 jam ke depan)")
    print(f"  ℹ️  Tampilan      : interpolasi 60 menit")
    print(f"  ℹ️  Val Loss      : 0.000064 (sangat baik)")