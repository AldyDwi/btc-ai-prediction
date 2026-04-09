# app/services/backtesting.py

import os
import csv
import pandas as pd
import numpy as np
from datetime import datetime, timezone

from app.data.processor import compute_indicators
from app.database.models import (
    PriceData, BacktestResults,
    BacktestTrades, BacktestEquity
)
from app.utils.config import config
from app.utils.logger import get_logger

log = get_logger(__name__)

BACKTEST_LOG = os.path.join(config.LOG_DIR, "backtest.csv")
os.makedirs(config.LOG_DIR, exist_ok=True)


def _generate_signal(row: pd.Series, prev_row: pd.Series) -> dict:
    """
    Signal generator v4.

    Fix dari v3:
    - Tambah trend filter MA200 (KRITIS)
    - RSI gate diperketat: BUY < 45, SELL > 55
    - MIN_SCORE naik ke 5
    - Tidak trade melawan trend besar
    """
    price        = float(row["close"])
    rsi          = float(row.get("rsi", 50))
    macd         = float(row.get("macd", 0))
    macd_signal  = float(row.get("macd_signal", 0))
    ma_20        = float(row.get("ma_20", price))
    ma_50        = float(row.get("ma_50", price))
    ma_200       = float(row.get("ma_200", price))   # ← BARU
    volume       = float(row.get("volume", 0))

    prev_macd        = float(prev_row.get("macd", 0))
    prev_macd_signal = float(prev_row.get("macd_signal", 0))
    prev_volume      = float(prev_row.get("volume", 0))

    macd_cross_up   = (prev_macd <= prev_macd_signal) and (macd > macd_signal)
    macd_cross_down = (prev_macd >= prev_macd_signal) and (macd < macd_signal)
    vol_spike       = (volume > prev_volume * 1.5) if prev_volume > 0 else False

    # ── Trend Direction ───────────────────────────────────────
    in_uptrend   = (price > ma_200) and (ma_50 > ma_200)
    in_downtrend = (price < ma_200) and (ma_50 < ma_200)

    score   = 0
    reasons = []

    # ── [1] Trend Filter (PALING PENTING) ────────────────────
    if in_uptrend:
        score += 2
        reasons.append("✅ Uptrend (> MA200)")
    elif in_downtrend:
        score -= 2
        reasons.append("❌ Downtrend (< MA200)")
    else:
        reasons.append("↔ Sideways")

    # ── [2] RSI ───────────────────────────────────────────────
    if rsi < 25:
        score += 4
        reasons.append(f"RSI ekstrem oversold ({rsi:.1f})")
    elif rsi < 35:
        score += 3
        reasons.append(f"RSI sangat oversold ({rsi:.1f})")
    elif rsi < 45:
        score += 2
        reasons.append(f"RSI oversold ({rsi:.1f})")
    elif rsi < 50:
        score += 1
        reasons.append(f"RSI agak lemah ({rsi:.1f})")
    elif rsi > 80:
        score -= 4
        reasons.append(f"RSI ekstrem overbought ({rsi:.1f})")
    elif rsi > 70:
        score -= 3
        reasons.append(f"RSI sangat overbought ({rsi:.1f})")
    elif rsi > 60:
        score -= 2
        reasons.append(f"RSI overbought ({rsi:.1f})")
    elif rsi > 55:
        score -= 1
        reasons.append(f"RSI agak tinggi ({rsi:.1f})")
    else:
        reasons.append(f"RSI netral ({rsi:.1f})")

    # ── [3] MACD ──────────────────────────────────────────────
    if macd_cross_up:
        score += 2
        reasons.append("MACD bullish cross ↑")
    elif macd_cross_down:
        score -= 2
        reasons.append("MACD bearish cross ↓")
    elif macd > macd_signal:
        score += 1
        reasons.append("MACD > Signal")
    elif macd < macd_signal:
        score -= 1
        reasons.append("MACD < Signal")

    # ── [4] MA Trend ──────────────────────────────────────────
    if ma_20 > ma_50 * 1.002:
        score += 1
        reasons.append("MA20 > MA50")
    elif ma_20 < ma_50 * 0.998:
        score -= 1
        reasons.append("MA20 < MA50")

    # ── [5] Price vs MA20 ─────────────────────────────────────
    if price < ma_20 * 0.99:
        score += 1
        reasons.append("Price dip bawah MA20")
    elif price > ma_20 * 1.01:
        score -= 1
        reasons.append("Price jauh di atas MA20")

    # ── [6] Volume konfirmasi ─────────────────────────────────
    if vol_spike and macd_cross_up:
        score += 1
        reasons.append("Volume spike bullish")
    elif vol_spike and macd_cross_down:
        score -= 1
        reasons.append("Volume spike bearish")

    # ── Gate Rules ────────────────────────────────────────────
    """
    BUY  → score >= 5 DAN RSI < 45
    SELL → score <= -5 DAN RSI > 55
    
    Lebih ketat dari v3 (MIN_SCORE 4→5, RSI gate lebih sempit)
    """
    MIN_SCORE = 5

    if score >= MIN_SCORE and rsi < 45:
        action = "BUY"
    elif score <= -MIN_SCORE and rsi > 55:
        action = "SELL"
    else:
        action = "HOLD"

    return {
        "action"     : action,
        "score"      : score,
        "rsi"        : round(rsi, 1),
        "in_uptrend" : in_uptrend,
        "reasons"    : reasons
    }


def _calc_trade_stats(trades: list) -> dict:
    """
    Hitung statistik trade dengan pairing BUY→SELL sequential.
    Fix dari versi lama yang pakai zip() → bisa salah pair.
    """
    pairs    = []
    open_buy = None

    for t in trades:
        if t["action"] == "BUY" and open_buy is None:
            open_buy = t
        elif t["action"] == "SELL" and open_buy is not None:
            pnl_pct = (t["price"] - open_buy["price"]) / open_buy["price"] * 100
            pairs.append({
                "buy_price"  : open_buy["price"],
                "sell_price" : t["price"],
                "pnl_pct"    : pnl_pct,
                "won"        : pnl_pct > 0,
                "reason_sell": t["reason"]
            })
            open_buy = None  # reset untuk pair berikutnya

    if not pairs:
        return {
            "wins": 0, "losses": 0, "win_rate": 0.0,
            "avg_win": 0.0, "avg_loss": 0.0, "profit_factor": 0.0
        }

    wins   = [p for p in pairs if p["won"]]
    losses = [p for p in pairs if not p["won"]]

    win_rate     = len(wins) / len(pairs) * 100
    avg_win      = float(np.mean([p["pnl_pct"] for p in wins]))   if wins   else 0.0
    avg_loss     = float(np.mean([p["pnl_pct"] for p in losses])) if losses else 0.0

    total_profit  = sum(p["pnl_pct"] for p in wins)
    total_loss    = abs(sum(p["pnl_pct"] for p in losses))
    profit_factor = round(total_profit / total_loss, 2) if total_loss > 0 else 9.99

    return {
        "wins"         : len(wins),
        "losses"       : len(losses),
        "win_rate"     : round(win_rate, 2),
        "avg_win"      : round(avg_win, 2),
        "avg_loss"     : round(avg_loss, 2),
        "profit_factor": profit_factor,
    }


def run_backtest(
    df              : pd.DataFrame = None,
    initial_balance : float = 1000.0,
    stop_loss_pct   : float = None,
    take_profit_pct : float = None,
    cooldown_hours  : int   = 48,
    notes           : str   = ""
) -> dict:

    sl_pct = stop_loss_pct   or config.STOP_LOSS_PCT
    tp_pct = take_profit_pct or config.TAKE_PROFIT_PCT

    # Pastikan SL selalu negatif
    if sl_pct > 0:
        sl_pct = -sl_pct

    log.info("🧪 Backtesting START")
    log.info(f"   Modal       : ${initial_balance:,.2f}")
    log.info(f"   Stop Loss   : {sl_pct*100:.1f}%")
    log.info(f"   Take Profit : {tp_pct*100:.1f}%")
    log.info(f"   Cooldown    : {cooldown_hours} jam")

    # ── Ambil data ────────────────────────────────────────────
    if df is None:
        rows = PriceData.get_latest(limit=10000)
        df   = pd.DataFrame(rows)

    if df.empty:
        log.error("❌ Tidak ada data")
        return {}

    # ── Hitung indikator ──────────────────────────────────────
    if "rsi" not in df.columns or "ma_200" not in df.columns:
        df = compute_indicators(df)

    df = df.dropna().reset_index(drop=True)
    log.info(f"   Data siap  : {len(df)} baris")

    if len(df) < 200:
        log.error("❌ Data terlalu sedikit (min 200 untuk MA200)")
        return {}

    # ── Pastikan timestamp datetime ───────────────────────────
    if not pd.api.types.is_datetime64_any_dtype(df["timestamp"]):
        df["timestamp"] = pd.to_datetime(df["timestamp"])

    # ── State ─────────────────────────────────────────────────
    balance         = initial_balance
    btc             = 0.0
    entry_price     = 0.0
    trades          = []
    equity          = []
    last_trade_time = None                              # ← FIX: pakai waktu
    cooldown_delta  = pd.Timedelta(hours=cooldown_hours)

    data_from = df["timestamp"].iloc[0]
    data_to   = df["timestamp"].iloc[-1]

    log.info(f"   Range      : {str(data_from)[:10]} → {str(data_to)[:10]}")
    log.info("   Simulasi trading...")

    # ── Loop ──────────────────────────────────────────────────
    for i in range(1, len(df)):
        row      = df.iloc[i]
        prev_row = df.iloc[i - 1]
        price    = float(row["close"])
        ts       = row["timestamp"]

        total = balance + btc * price
        equity.append({"timestamp": ts, "total": total})

        # ── SL/TP (prioritas tertinggi) ───────────────────────
        if btc > 0 and entry_price > 0:
            change = (price - entry_price) / entry_price

            if change <= sl_pct:
                balance         = btc * price * 0.999
                btc             = 0.0
                entry_price     = 0.0
                last_trade_time = ts
                trades.append({
                    "timestamp": ts,
                    "action"   : "SELL",
                    "price"    : price,
                    "btc"      : 0.0,
                    "balance"  : balance,
                    "reason"   : f"🛑 Stop Loss ({change*100:.2f}%)"
                })
                continue

            elif change >= tp_pct:
                balance         = btc * price * 0.999
                btc             = 0.0
                entry_price     = 0.0
                last_trade_time = ts
                trades.append({
                    "timestamp": ts,
                    "action"   : "SELL",
                    "price"    : price,
                    "btc"      : 0.0,
                    "balance"  : balance,
                    "reason"   : f"✅ Take Profit ({change*100:.2f}%)"
                })
                continue

        # ── Cooldown (pakai waktu nyata) ──────────────────────
        if last_trade_time is not None:
            if (ts - last_trade_time) < cooldown_delta:
                continue

        # ── Signal ────────────────────────────────────────────
        sig = _generate_signal(row, prev_row)

        # ── BUY ───────────────────────────────────────────────
        if sig["action"] == "BUY" and balance > 10 and btc == 0:
            btc             = (balance * 0.999) / price
            entry_price     = price
            balance         = 0.0
            last_trade_time = ts
            trades.append({
                "timestamp": ts,
                "action"   : "BUY",
                "price"    : price,
                "btc"      : btc,
                "balance"  : balance,
                "reason"   : (
                    f"Score:{sig['score']} | "
                    + " | ".join(sig["reasons"][:3])
                )
            })

        # ── SELL (signal) ─────────────────────────────────────
        elif sig["action"] == "SELL" and btc > 0:
            balance         = btc * price * 0.999
            btc             = 0.0
            entry_price     = 0.0
            last_trade_time = ts
            trades.append({
                "timestamp": ts,
                "action"   : "SELL",
                "price"    : price,
                "btc"      : 0.0,
                "balance"  : balance,
                "reason"   : (
                    f"Score:{sig['score']} | "
                    + " | ".join(sig["reasons"][:3])
                )
            })

    # ── Force close posisi terakhir ───────────────────────────
    if btc > 0:
        final_price = float(df.iloc[-1]["close"])
        balance     = btc * final_price * 0.999
        btc         = 0.0
        trades.append({
            "timestamp": df.iloc[-1]["timestamp"],
            "action"   : "SELL",
            "price"    : final_price,
            "btc"      : 0.0,
            "balance"  : balance,
            "reason"   : "Force close end"
        })

    # ── Statistik ─────────────────────────────────────────────
    final_price = float(df.iloc[-1]["close"])
    final_total = balance + btc * final_price
    profit_loss = final_total - initial_balance
    roi_pct     = profit_loss / initial_balance * 100

    buy_trades  = [t for t in trades if t["action"] == "BUY"]
    sell_trades = [t for t in trades if t["action"] == "SELL"]

    # ✅ FIX: pakai _calc_trade_stats, bukan zip()
    stats         = _calc_trade_stats(trades)
    win_rate      = stats["win_rate"]
    avg_win       = stats["avg_win"]
    avg_loss      = stats["avg_loss"]
    profit_factor = stats["profit_factor"]

    # ── Max Drawdown ──────────────────────────────────────────
    peak         = initial_balance
    max_drawdown = 0.0
    for e in equity:
        val = e["total"]
        if val > peak:
            peak = val
        dd = (peak - val) / peak * 100
        if dd > max_drawdown:
            max_drawdown = dd

    # ── Simpan DB ─────────────────────────────────────────────
    backtest_id = BacktestResults.insert(
        initial_balance = initial_balance,
        final_total     = final_total,
        profit_loss     = profit_loss,
        roi_pct         = roi_pct,
        total_trades    = len(trades),
        buy_count       = len(buy_trades),
        sell_count      = len(sell_trades),
        win_rate        = win_rate,
        max_drawdown    = max_drawdown,
        profit_factor   = profit_factor,
        data_from       = str(data_from),
        data_to         = str(data_to),
        data_points     = len(df),
        notes           = notes
    )

    BacktestTrades.bulk_insert(backtest_id, trades)
    BacktestEquity.bulk_insert(backtest_id, equity)

    # ── CSV Log ───────────────────────────────────────────────
    if not os.path.exists(BACKTEST_LOG):
        with open(BACKTEST_LOG, "w", newline="") as f:
            csv.writer(f).writerow([
                "run_at", "initial_balance", "final_total",
                "profit_loss", "roi_pct", "win_rate",
                "profit_factor", "max_drawdown",
                "total_trades", "notes"
            ])

    with open(BACKTEST_LOG, "a", newline="") as f:
        csv.writer(f).writerow([
            datetime.now(timezone.utc).isoformat(),
            initial_balance, round(final_total, 2),
            round(profit_loss, 2), round(roi_pct, 2),
            round(win_rate, 2), profit_factor,
            round(max_drawdown, 2), len(trades), notes
        ])

    emoji = "📈" if roi_pct > 0 else "📉"
    log.info(f"━━━━━ {emoji} Backtest Result ━━━━━")
    log.info(f"  ROI           : {roi_pct:+.2f}%")
    log.info(f"  P/L           : ${profit_loss:+,.2f}")
    log.info(f"  Win Rate      : {win_rate:.1f}%")
    log.info(f"  Profit Factor : {profit_factor:.2f}")
    log.info(f"  Max Drawdown  : {max_drawdown:.2f}%")
    log.info(f"  Total Trades  : {len(trades)}")
    log.info(f"  Wins/Losses   : {stats['wins']}/{stats['losses']}")
    log.info(f"  Avg Win       : +{avg_win:.2f}%")
    log.info(f"  Avg Loss      : {avg_loss:.2f}%")
    log.info(f"  Backtest ID   : {backtest_id}")
    log.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    return {
        "initial_balance": initial_balance,
        "final_total"    : round(final_total, 2),
        "profit_loss"    : round(profit_loss, 2),
        "roi_pct"        : round(roi_pct, 2),
        "total_trades"   : len(trades),
        "buy_count"      : len(buy_trades),
        "sell_count"     : len(sell_trades),
        "win_rate"       : round(win_rate, 2),
        "avg_win_pct"    : round(avg_win, 2),
        "avg_loss_pct"   : round(avg_loss, 2),
        "profit_factor"  : profit_factor,
        "max_drawdown"   : round(max_drawdown, 2),
        "data_from"      : str(data_from),
        "data_to"        : str(data_to),
        "data_points"    : len(df),
        "equity_curve"   : equity,
        "trade_history"  : trades,
        "backtest_id"    : backtest_id,
        "notes"          : notes
    }