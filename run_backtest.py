# run_backtest.py

from app.database.db import init_db
from app.services.backtesting import run_backtest
from app.database.models import BacktestResults


def display_trades(trades: list, n: int = 10):
    seen   = set()
    unique = []
    for t in trades:
        key = f"{t['timestamp']}_{t['action']}_{t['price']}"
        if key not in seen:
            seen.add(key)
            unique.append(t)

    last_n = unique[-n:]
    print(f"\n📋 {n} Trade Terakhir (dari {len(unique)} total):")
    print(f"  {'Waktu':<18} {'Aksi':<6} {'Harga':>12} "
          f"{'Balance':>12}  Alasan")
    print("  " + "-"*75)
    for t in last_n:
        ts  = str(t["timestamp"])[:16]
        act = t["action"]
        pr  = float(t["price"])
        bal = float(t["balance"])
        rsn = str(t.get("reason", ""))[:30]
        print(f"  {ts:<18} {act:<6} ${pr:>11,.2f} ${bal:>11,.2f}  {rsn}")


def display_results(results: dict):
    roi   = results["roi_pct"]
    pl    = results["profit_loss"]
    emoji = "📈" if roi > 0 else "📉"

    print(f"\n{emoji} HASIL BACKTEST")
    print("="*60)
    print(f"  Modal Awal      : ${results['initial_balance']:>12,.2f}")
    print(f"  Nilai Akhir     : ${results['final_total']:>12,.2f}")
    print(f"  Profit / Loss   : ${pl:>+12,.2f}")
    print(f"  ROI             : {roi:>+11.2f}%")
    print("-"*60)
    print(f"  Total Trades    : {results['total_trades']:>12}")
    print(f"  Buy / Sell      : "
          f"{results['buy_count']:>5} / {results['sell_count']:<5}")
    print(f"  Win Rate        : {results['win_rate']:>11.1f}%")
    print(f"  Avg Win         : {results['avg_win_pct']:>+11.2f}%")
    print(f"  Avg Loss        : {results['avg_loss_pct']:>+11.2f}%")
    print(f"  Profit Factor   : {results['profit_factor']:>12.2f}")
    print(f"  Max Drawdown    : {results['max_drawdown']:>11.2f}%")
    print("-"*60)
    print(f"  Data dari       : {results['data_from'][:10]}")
    print(f"  Data sampai     : {results['data_to'][:10]}")
    print(f"  Data points     : {results['data_points']:>12,}")
    print(f"  Backtest ID     : {results['backtest_id']:>12}")
    print("="*60)


def _print_history(all_bt: list, limit: int = 10):
    if not all_bt:
        return
    print(f"\n📜 Semua Run Backtest ({len(all_bt)} total):")
    print(f"  {'ID':<4} {'Tanggal':<12} {'ROI':>8} "
          f"{'P/L':>12} {'Win%':>6} {'DD%':>6} "
          f"{'Trades':>7}  Notes")
    print("  " + "-"*75)
    for r in all_bt[:limit]:
        print(
            f"  {r['id']:<4} "
            f"{str(r['run_at'])[:10]:<12} "
            f"{r['roi_pct']:>+7.2f}% "
            f"${r['profit_loss']:>+11,.2f} "
            f"{r.get('win_rate', 0) or 0:>5.1f}% "
            f"{r.get('max_drawdown', 0) or 0:>5.1f}% "
            f"{r['total_trades']:>7}  "
            f"{r.get('notes', '')[:20]}"
        )


def main():
    init_db()

    print("\n" + "="*60)
    print("           🧪 BACKTESTING BTC AI SYSTEM")
    print("="*60)

    print("\nPilih mode:")
    print("  1. Single backtest")
    print("  2. Bandingkan beberapa parameter")
    print("  3. Lihat riwayat saja")

    try:
        mode = input("\nPilihan (1/2/3) [default=1]: ").strip() or "1"
    except Exception:
        mode = "1"

    # ── Mode 3: Riwayat ───────────────────────────────────────
    if mode == "3":
        all_bt = BacktestResults.get_all()
        if not all_bt:
            print("❌ Belum ada riwayat")
            return
        _print_history(all_bt, limit=20)
        return

    # ── Mode 2: Compare ───────────────────────────────────────
    if mode == "2":
        # Parameter yang dioptimasi berdasarkan pelajaran sebelumnya
        configs = [
            # SL ketat, TP sedang, cooldown panjang
            {"sl": -0.03, "tp": 0.08, "cd": 72, "label": "SL3% TP8% CD72h"},
            # SL ketat, TP besar, cooldown panjang
            {"sl": -0.03, "tp": 0.10, "cd": 72, "label": "SL3% TP10% CD72h"},
            # SL kecil, TP sedang, cooldown panjang
            {"sl": -0.02, "tp": 0.08, "cd": 72, "label": "SL2% TP8% CD72h"},
            # SL longgar, TP besar, cooldown sangat panjang
            {"sl": -0.03, "tp": 0.08, "cd": 96, "label": "SL3% TP8% CD96h"},
        ]

        print(f"\n🔬 Menjalankan {len(configs)} konfigurasi...")
        print("   (Cooldown panjang = lebih selektif)")
        print("-"*60)

        all_results = []
        for i, cfg in enumerate(configs, 1):
            print(f"\n[{i}/{len(configs)}] {cfg['label']}")
            r = run_backtest(
                initial_balance = 1000.0,
                stop_loss_pct   = cfg["sl"],
                take_profit_pct = cfg["tp"],
                cooldown_hours  = cfg["cd"],
                notes           = cfg["label"]
            )
            if r:
                all_results.append((cfg["label"], r))

        if not all_results:
            print("❌ Semua backtest gagal")
            return

        # Tampilkan perbandingan
        print("\n" + "="*75)
        print("📊 PERBANDINGAN HASIL")
        print("="*75)
        print(f"  {'Config':<22} {'ROI':>8} {'P/L':>10} "
              f"{'Win%':>6} {'PF':>5} {'DD%':>6} {'Trades':>7}")
        print("  " + "-"*70)

        best = max(all_results, key=lambda x: x[1]["roi_pct"])
        for label, r in all_results:
            marker = " ← TERBAIK" if label == best[0] else ""
            print(
                f"  {label:<22} "
                f"{r['roi_pct']:>+7.2f}% "
                f"${r['profit_loss']:>+9,.2f} "
                f"{r['win_rate']:>5.1f}% "
                f"{r['profit_factor']:>4.2f} "
                f"{r['max_drawdown']:>5.1f}% "
                f"{r['total_trades']:>7}"
                f"{marker}"
            )

        print("="*75)
        print(f"\n🏆 Terbaik: {best[0]}")
        print(f"   ROI    : {best[1]['roi_pct']:+.2f}%")
        print(f"   Trades : {best[1]['total_trades']}")
        _print_history(BacktestResults.get_all(), limit=5)
        return

    # ── Mode 1: Single ────────────────────────────────────────
    initial_balance = 1000.0
    stop_loss       = -0.02
    take_profit     = 0.08
    cooldown_hours  = 72     # ← naik ke 72 jam

    notes = (
        f"SL={stop_loss*100:.0f}% "
        f"TP={take_profit*100:.0f}% "
        f"CD={cooldown_hours}h "
        f"v3"
    )

    print(f"  Modal awal    : ${initial_balance:,.2f}")
    print(f"  Stop Loss     : {stop_loss*100:.1f}%")
    print(f"  Take Profit   : {take_profit*100:.1f}%")
    print(f"  Cooldown      : {cooldown_hours} jam")
    print("-"*60)

    results = run_backtest(
        initial_balance = initial_balance,
        stop_loss_pct   = stop_loss,
        take_profit_pct = take_profit,
        cooldown_hours  = cooldown_hours,
        notes           = notes
    )

    if not results:
        print("❌ Backtest gagal!")
        return

    display_results(results)
    display_trades(results["trade_history"], n=10)
    _print_history(BacktestResults.get_all(), limit=10)
    print("\n✅ Hasil disimpan ke DB & logs/backtest.csv")


if __name__ == "__main__":
    main()