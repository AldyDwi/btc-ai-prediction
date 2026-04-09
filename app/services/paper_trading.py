# app/services/paper_trading.py

import csv
import os
from datetime import datetime, timezone, timedelta

import pandas as pd

from app.data.processor import compute_indicators
from app.database.models import (
    TradeLogs, Indicators, PriceData,
    ActualPrices, SystemState
)
from app.utils.config import config
from app.utils.logger import get_logger

log = get_logger(__name__)

TRADE_LOG = os.path.join(config.LOG_DIR, "trades.csv")
os.makedirs(config.LOG_DIR, exist_ok=True)

# ── Parameter terbaik dari backtest ──────────────────────────
BEST_SL_PCT        = -0.02   # Stop Loss  -2%
BEST_TP_PCT        =  0.08   # Take Profit +8%
BEST_COOLDOWN_HOUR =  72     # 72 jam


def _generate_signal(row: pd.Series, prev_row: pd.Series) -> dict:
    """
    Signal generator v4 - sama persis dengan backtesting.py
    Agar live trading konsisten dengan hasil backtest.
    """
    price        = float(row.get("close", 0))
    rsi          = float(row.get("rsi", 50))
    macd         = float(row.get("macd", 0))
    macd_signal  = float(row.get("macd_signal", 0))
    ma_20        = float(row.get("ma_20", price))
    ma_50        = float(row.get("ma_50", price))
    ma_200       = float(row.get("ma_200", price))
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

    # [1] Trend filter
    if in_uptrend:
        score += 2
        reasons.append("✅ Uptrend (> MA200)")
    elif in_downtrend:
        score -= 2
        reasons.append("❌ Downtrend (< MA200)")
    else:
        reasons.append("↔ Sideways")

    # [2] RSI
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

    # [3] MACD
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

    # [4] MA Trend
    if ma_20 > ma_50 * 1.002:
        score += 1
        reasons.append("MA20 > MA50")
    elif ma_20 < ma_50 * 0.998:
        score -= 1
        reasons.append("MA20 < MA50")

    # [5] Price vs MA20
    if price < ma_20 * 0.99:
        score += 1
        reasons.append("Price dip bawah MA20")
    elif price > ma_20 * 1.01:
        score -= 1
        reasons.append("Price jauh di atas MA20")

    # [6] Volume
    if vol_spike and macd_cross_up:
        score += 1
        reasons.append("Volume spike bullish")
    elif vol_spike and macd_cross_down:
        score -= 1
        reasons.append("Volume spike bearish")

    # ── Gate Rules ────────────────────────────────────────────
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


class PaperPortfolio:
    """
    Simulasi portfolio paper trading.
    Parameter SL/TP/Cooldown sesuai hasil backtest terbaik:
      SL = -2%, TP = +8%, Cooldown = 72 jam
    """

    def __init__(self):
        self.balance     : float         = config.INITIAL_BALANCE
        self.btc         : float         = 0.0
        self.entry_price : float         = 0.0
        self.last_trade  : datetime|None = None
        self._last_price : float         = 0.0

        # Parameter dari backtest terbaik
        self.sl_pct       = BEST_SL_PCT
        self.tp_pct       = BEST_TP_PCT
        self.cooldown_hours = BEST_COOLDOWN_HOUR

        self._ensure_log()
        self._restore_state()

    def _ensure_log(self):
        if not os.path.exists(TRADE_LOG):
            with open(TRADE_LOG, "w", newline="") as f:
                csv.writer(f).writerow([
                    "timestamp", "action", "price",
                    "amount_btc", "balance",
                    "total_asset", "reason"
                ])

    def _restore_state(self):
        """
        Restore state dari trade_logs DB.
        Cari BUY terakhir yang belum ada pasangan SELL-nya.
        """
        trades = TradeLogs.get_latest(limit=200)
        if not trades:
            log.info("📋 Portfolio baru, mulai dari awal")
            return

        # Cari posisi terbuka (BUY tanpa SELL setelahnya)
        open_position = None
        last_sell_balance = None

        for t in trades:
            if t["action"] == "BUY":
                open_position = t
            elif t["action"] == "SELL":
                open_position    = None
                last_sell_balance = t["balance"]

        if open_position:
            # Ada posisi terbuka
            self.btc         = open_position["amount_btc"]
            self.balance     = 0.0
            self.entry_price = open_position["price"]
            ts = open_position["timestamp"]
            self.last_trade  = (
                datetime.fromisoformat(ts)
                if isinstance(ts, str) else ts
            )
            log.info(
                f"📂 Restore posisi TERBUKA | "
                f"Entry: ${self.entry_price:,.2f} | "
                f"BTC: {self.btc:.6f}"
            )
        else:
            # Tidak ada posisi terbuka
            self.btc         = 0.0
            self.entry_price = 0.0
            if last_sell_balance:
                self.balance = last_sell_balance

            # Ambil last_trade dari trade terakhir
            last = trades[-1]
            ts   = last["timestamp"]
            self.last_trade = (
                datetime.fromisoformat(ts)
                if isinstance(ts, str) else ts
            )
            log.info(
                f"📂 Restore selesai | "
                f"Balance: ${self.balance:,.2f} | "
                f"Posisi: KOSONG"
            )

    # ── Properties ────────────────────────────────────────────
    @property
    def total_asset(self) -> float:
        return self.balance + self.btc * self._last_price

    @property
    def unrealized_pnl(self) -> float:
        """PnL posisi yang sedang terbuka."""
        if self.btc <= 0 or self.entry_price <= 0:
            return 0.0
        return (self._last_price - self.entry_price) / self.entry_price * 100

    # ── Cooldown ──────────────────────────────────────────────
    def _cooldown_ok(self) -> bool:
        """Cek apakah sudah lewat cooldown 72 jam."""
        if self.last_trade is None:
            return True

        now = datetime.now(timezone.utc)

        # Pastikan last_trade timezone-aware
        lt = self.last_trade
        if lt.tzinfo is None:
            lt = lt.replace(tzinfo=timezone.utc)

        elapsed = now - lt
        remaining = timedelta(hours=self.cooldown_hours) - elapsed

        if remaining.total_seconds() > 0:
            hours_left = remaining.total_seconds() / 3600
            log.debug(f"⏳ Cooldown: {hours_left:.1f} jam lagi")
            return False
        return True

    # ── Risk Management ───────────────────────────────────────
    def _check_sl_tp(self, current_price: float) -> str | None:
        """
        Cek Stop Loss / Take Profit.
        Return reason string jika terpicu, None jika tidak.
        SL = -2%, TP = +8% (dari backtest terbaik)
        """
        if self.btc <= 0 or self.entry_price <= 0:
            return None

        change = (current_price - self.entry_price) / self.entry_price

        if change <= self.sl_pct:
            return f"🛑 Stop Loss ({change*100:.2f}%)"
        if change >= self.tp_pct:
            return f"✅ Take Profit ({change*100:.2f}%)"
        return None

    # ── Main Execute ──────────────────────────────────────────
    def execute(self, signal: dict, current_price: float):
        """
        Eksekusi sinyal trading.
        Priority: SL/TP > Cooldown > Signal
        """
        self._last_price = current_price

        # [1] SL/TP - prioritas tertinggi, abaikan cooldown
        sl_tp_reason = self._check_sl_tp(current_price)
        if sl_tp_reason:
            self._sell(current_price, sl_tp_reason)
            return

        # [2] Cooldown check
        if not self._cooldown_ok():
            return

        # [3] Eksekusi signal
        action = signal.get("action", "HOLD")

        if action == "BUY" and self.balance > 10 and self.btc == 0:
            reason = (
                f"Score:{signal.get('score', 0)} | "
                + " | ".join(signal.get("reasons", [])[:3])
            )
            self._buy(current_price, reason)

        elif action == "SELL" and self.btc > 0:
            reason = (
                f"Score:{signal.get('score', 0)} | "
                + " | ".join(signal.get("reasons", [])[:3])
            )
            self._sell(current_price, reason)

        else:
            # HOLD - log status singkat
            upnl = self.unrealized_pnl
            if self.btc > 0:
                log.debug(
                    f"⏸️ HOLD | BTC: {self.btc:.6f} | "
                    f"Entry: ${self.entry_price:,.2f} | "
                    f"uPnL: {upnl:+.2f}%"
                )
            else:
                log.debug(
                    f"⏸️ HOLD | Balance: ${self.balance:,.2f}"
                )

    # ── BUY ───────────────────────────────────────────────────
    def _buy(self, price: float, reason: str):
        fee            = 0.001                          # 0.1% fee
        self.btc       = (self.balance * (1 - fee)) / price
        self.balance   = 0.0
        self.entry_price = price
        self.last_trade  = datetime.now(timezone.utc)

        self._log_trade("BUY", price, self.btc, reason)

    # ── SELL ──────────────────────────────────────────────────
    def _sell(self, price: float, reason: str):
        fee            = 0.001                          # 0.1% fee
        amount_btc     = self.btc
        self.balance   = amount_btc * price * (1 - fee)
        self.btc       = 0.0
        self.entry_price = 0.0
        self.last_trade  = datetime.now(timezone.utc)

        self._log_trade("SELL", price, amount_btc, reason)

    # ── Log Trade ─────────────────────────────────────────────
    def _log_trade(self, action: str, price: float,
                   amount_btc: float, reason: str):
        total  = self.balance + self.btc * price
        emoji  = "🟢" if action == "BUY" else "🔴"

        log.info(
            f"{emoji} {action} | "
            f"Price: ${price:,.2f} | "
            f"BTC: {amount_btc:.6f} | "
            f"Balance: ${self.balance:,.2f} | "
            f"Total: ${total:,.2f} | "
            f"{reason}"
        )

        # Simpan ke DB
        TradeLogs.insert(
            action     = action,
            price      = price,
            amount_btc = amount_btc,
            balance    = self.balance,
            reason     = reason,
            mode       = "paper"
        )

        # Simpan ke CSV
        with open(TRADE_LOG, "a", newline="") as f:
            csv.writer(f).writerow([
                datetime.now(timezone.utc).isoformat(),
                action, price, amount_btc,
                self.balance, total, reason
            ])

    # ── Status ────────────────────────────────────────────────
    def get_status(self) -> dict:
        upnl = self.unrealized_pnl

        # Hitung cooldown sisa
        cooldown_remaining_h = 0.0
        if self.last_trade:
            now = datetime.now(timezone.utc)
            lt  = self.last_trade
            if lt.tzinfo is None:
                lt = lt.replace(tzinfo=timezone.utc)
            elapsed   = (now - lt).total_seconds() / 3600
            remaining = self.cooldown_hours - elapsed
            cooldown_remaining_h = max(0.0, round(remaining, 1))

        return {
            "balance"             : round(self.balance, 2),
            "btc"                 : round(self.btc, 8),
            "entry_price"         : round(self.entry_price, 2),
            "total_asset"         : round(self.total_asset, 2),
            "unrealized_pnl_pct"  : round(upnl, 2),
            "last_trade"          : str(self.last_trade),
            "cooldown_remaining_h": cooldown_remaining_h,
            "sl_pct"              : self.sl_pct * 100,
            "tp_pct"              : self.tp_pct * 100,
            "position"            : "OPEN" if self.btc > 0 else "NONE",
        }


# ── Singleton ─────────────────────────────────────────────────
_portfolio: PaperPortfolio | None = None

def get_portfolio() -> PaperPortfolio:
    global _portfolio
    if _portfolio is None:
        _portfolio = PaperPortfolio()
    return _portfolio


def run_trading_cycle(
    prediction_result : dict,
    current_price     : float
):
    """
    Panggil setelah prediction_cycle selesai.
    Ambil 2 baris indikator terakhir → generate signal → eksekusi.
    Butuh 2 baris untuk deteksi MACD crossover.
    """
    state = SystemState.get()
    if not state.get("trading_on", False):
        log.debug("Trading OFF, skip")
        return

    # ── Ambil data harga + indikator terbaru ─────────────────
    rows = PriceData.get_latest(limit=500)
    if not rows or len(rows) < 2:
        log.warning("⚠️ Data harga tidak cukup")
        return

    df = pd.DataFrame(rows)

    # Hitung indikator (termasuk MA200)
    if "ma_200" not in df.columns:
        df = compute_indicators(df)

    if df.empty or len(df) < 2:
        log.warning("⚠️ Data setelah indikator terlalu sedikit")
        return

    # Ambil 2 baris terakhir
    row      = df.iloc[-1]
    prev_row = df.iloc[-2]

    # Update harga close dari harga real-time jika berbeda
    # (agar SL/TP pakai harga live, bukan candle close)
    row_with_price = row.copy()
    row_with_price["close"] = current_price

    # ── Generate signal ───────────────────────────────────────
    signal = _generate_signal(row_with_price, prev_row)

    log.debug(
        f"📊 Signal: {signal['action']} | "
        f"Score: {signal['score']} | "
        f"RSI: {signal['rsi']} | "
        f"Trend: {'UP' if signal['in_uptrend'] else 'DOWN/SIDE'}"
    )

    # ── Eksekusi ──────────────────────────────────────────────
    portfolio = get_portfolio()
    portfolio.execute(signal, current_price)


def run_trading_cycle_realtime(current_price: float):
    """
    Trading cycle ringan untuk realtime (tiap 1 menit).
    Tidak fetch data baru, hanya pakai data yang sudah ada di DB.
    """
    state = SystemState.get()
    if not state.get("trading_on", False):
        log.debug("Trading OFF, skip")
        return

    rows = PriceData.get_latest(limit=500)
    if not rows or len(rows) < 2:
        log.warning("⚠️ Data harga tidak cukup")
        return

    df = pd.DataFrame(rows)

    if "ma_200" not in df.columns:
        df = compute_indicators(df)

    if df.empty or len(df) < 2:
        log.warning("⚠️ Data setelah indikator terlalu sedikit")
        return

    row      = df.iloc[-1]
    prev_row = df.iloc[-2]

    # Pakai harga realtime dari 1M
    row_with_price          = row.copy()
    row_with_price["close"] = current_price

    signal = _generate_signal(row_with_price, prev_row)

    log.debug(
        f"📊 [RT] Signal: {signal['action']} | "
        f"Score: {signal['score']} | "
        f"RSI: {signal['rsi']} | "
        f"Price: ${current_price:,.2f}"
    )

    portfolio = get_portfolio()
    portfolio.execute(signal, current_price)