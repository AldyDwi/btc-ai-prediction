# app/services/telegram.py

import asyncio
from datetime import datetime, timezone, timedelta
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, ContextTypes
)
from app.database.models import SystemState, TradeLogs
from app.services.prediction_service import run_prediction_cycle
from app.services.paper_trading import (
    get_portfolio, run_trading_cycle, _generate_signal
)
from app.utils.config import config
from app.utils.logger import get_logger
from app.utils.timezone_helper import format_wib, to_wib, now_wib

import pandas as pd
from app.database.models import PriceData
from app.data.processor import compute_indicators

log = get_logger(__name__)


# ══════════════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════════════
async def _send(context: ContextTypes.DEFAULT_TYPE, text: str):
    """Kirim pesan ke chat utama."""
    try:
        await context.bot.send_message(
            chat_id    = config.TELEGRAM_CHAT_ID,
            text       = text,
            parse_mode = "Markdown"
        )
    except Exception as e:
        log.error(f"Telegram send error: {e}")


def _format_prediction(result: dict) -> str:
    change_pct = (
        (result["pred_avg"] - result["current_price"])
        / result["current_price"] * 100
    )
    emoji     = "📈" if change_pct > 0 else "📉"
    now_str   = format_wib(now_wib(), "%H:%M WIB")

    return (
        f"🔮 *Prediksi BTC 60 Menit ke Depan*\n"
        f"🕒 _{now_str}_\n\n"
        f"💰 Harga Sekarang : `${result['current_price']:,.2f}`\n"
        f"📈 Prediksi Rata2 : `${result['pred_avg']:,.2f}`\n"
        f"🔼 Prediksi Max   : `${result['pred_max']:,.2f}`\n"
        f"🔽 Prediksi Min   : `${result['pred_min']:,.2f}`\n"
        f"{emoji} Perubahan      : `{change_pct:+.2f}%`"
    )


def _format_prediction_with_signal(
    result : dict,
    signal : dict
) -> str:
    """Gabungkan prediksi + signal dalam satu pesan."""
    change_pct = (
        (result["pred_avg"] - result["current_price"])
        / result["current_price"] * 100
    )
    price    = result["current_price"]
    now_str  = format_wib(now_wib(), "%H:%M WIB")

    # Prediksi emoji
    emoji_pred = "📈" if change_pct > 0 else "📉"

    # Signal
    action  = signal.get("action", "HOLD")
    score   = signal.get("score", 0)
    rsi     = signal.get("rsi", 0)
    trend   = "📈 Uptrend" if signal.get("in_uptrend") else "📉 Down/Side"
    reasons = signal.get("reasons", [])

    emoji_action = {
        "BUY" : "🟢",
        "SELL": "🔴",
        "HOLD": "⏸️"
    }.get(action, "⏸️")

    # Keterangan signal
    if action == "BUY":
        signal_desc = "Kondisi mendukung *BELI*"
    elif action == "SELL":
        signal_desc = "Kondisi mendukung *JUAL*"
    else:
        signal_desc = "Belum ada sinyal kuat, *TAHAN*"

    reasons_text = "\n".join(f"  • {r}" for r in reasons[:5])

    return (
        f"🔮 *Prediksi BTC 60 Menit ke Depan*\n"
        f"🕒 _{now_str}_\n\n"

        # ── Harga & Prediksi ──────────────────────────────
        f"💰 Harga Sekarang : `${price:,.2f}`\n"
        f"{emoji_pred} Prediksi Avg   : `${result['pred_avg']:,.2f}`"
        f" (`{change_pct:+.2f}%`)\n"
        f"🔼 Prediksi Max   : `${result['pred_max']:,.2f}`\n"
        f"🔽 Prediksi Min   : `${result['pred_min']:,.2f}`\n\n"

        # ── Signal ───────────────────────────────────────
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 *Signal Trading*\n\n"
        f"{emoji_action} Sinyal  : `{action}` — {signal_desc}\n"
        f"🎯 Score   : `{score}/10`\n"
        f"📉 RSI     : `{rsi}`\n"
        f"🌊 Trend   : {trend}\n\n"
        f"📋 *Analisis:*\n{reasons_text}"
    )


def _format_signal(signal: dict, price: float) -> str:
    """Format signal untuk ditampilkan di Telegram."""
    action  = signal.get("action", "HOLD")
    score   = signal.get("score", 0)
    rsi     = signal.get("rsi", 0)
    trend   = "📈 Uptrend" if signal.get("in_uptrend") else "📉 Down/Side"
    reasons = signal.get("reasons", [])

    emoji_action = {
        "BUY" : "🟢",
        "SELL": "🔴",
        "HOLD": "⏸️"
    }.get(action, "⏸️")

    reasons_text = "\n".join(f"  • {r}" for r in reasons[:5])

    return (
        f"📊 *Signal Saat Ini*\n\n"
        f"💰 Harga    : `${price:,.2f}`\n"
        f"{emoji_action} Sinyal    : `{action}`\n"
        f"🎯 Score    : `{score}`\n"
        f"📉 RSI      : `{rsi}`\n"
        f"🌊 Trend    : `{trend}`\n\n"
        f"📋 *Alasan:*\n{reasons_text}"
    )


def _format_portfolio(status: dict, trades: list) -> str:
    """Format portfolio status untuk Telegram."""
    position = status.get("position", "NONE")
    pos_emoji = "🟡 TERBUKA" if position == "OPEN" else "⚪ KOSONG"

    upnl      = status.get("unrealized_pnl_pct", 0.0)
    upnl_str  = f"`{upnl:+.2f}%`" if position == "OPEN" else "`-`"
    upnl_emoji = "📈" if upnl >= 0 else "📉"

    cd_left   = status.get("cooldown_remaining_h", 0.0)
    cd_str    = f"`{cd_left:.1f} jam`" if cd_left > 0 else "`Siap trade`"

    text = (
        f"💼 *Portfolio Status*\n\n"
        f"💵 Balance     : `${status['balance']:,.2f} USDT`\n"
        f"₿  BTC Held   : `{status['btc']:.6f} BTC`\n"
        f"📍 Entry Price : `${status['entry_price']:,.2f}`\n"
        f"📊 Total Asset : `${status['total_asset']:,.2f}`\n"
        f"📌 Posisi      : {pos_emoji}\n"
        f"{upnl_emoji} Unrealized  : {upnl_str}\n\n"
        f"⚙️ *Config Aktif:*\n"
        f"  • Stop Loss  : `{status.get('sl_pct', -2.0):.1f}%`\n"
        f"  • Take Profit: `{status.get('tp_pct', 8.0):.1f}%`\n"
        f"  • Cooldown   : {cd_str}\n\n"
    )

    if trades:
        text += f"📜 *5 Trade Terakhir:*\n"
        for t in trades[-5:]:
            act   = t["action"]
            emoji = "🟢" if act == "BUY" else "🔴"
            text += (
                f"{emoji} {act} @ `${t['price']:,.2f}` | "
                f"Bal: `${t['balance']:,.2f}`\n"
            )

    return text


def _get_current_signal(current_price: float) -> dict | None:
    """
    Ambil signal terkini berdasarkan data harga terbaru.
    Return None jika data tidak cukup.
    """
    try:
        rows = PriceData.get_latest(limit=500)
        if not rows or len(rows) < 2:
            return None

        df = pd.DataFrame(rows)
        if "ma_200" not in df.columns:
            df = compute_indicators(df)

        if len(df) < 2:
            return None

        row      = df.iloc[-1].copy()
        prev_row = df.iloc[-2]
        row["close"] = current_price

        return _generate_signal(row, prev_row)
    except Exception as e:
        log.error(f"_get_current_signal error: {e}")
        return None


# ══════════════════════════════════════════════════════════════
#  COMMAND HANDLERS
# ══════════════════════════════════════════════════════════════
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 *BTC AI Prediction Bot*\n\n"
        "📌 *Commands:*\n"
        "/sekarang     - Prediksi & signal saat ini\n"
        "/signal       - Signal trading saja\n"
        "/portfolio    - Status portfolio\n"
        "/prediksi     - Aktifkan auto prediksi\n"
        "/berhenti     - Matikan auto prediksi\n"
        "/trading\\_on  - Aktifkan paper trading\n"
        "/trading\\_off - Matikan paper trading\n"
        "/status       - Status sistem\n"
        "/info         - Informasi lengkap sistem\n"
        "/help         - Tampilkan menu ini",
        parse_mode="Markdown"
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await cmd_start(update, context)


async def cmd_prediksi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    SystemState.update(auto_send=True)
    await update.message.reply_text(
        "✅ Auto prediksi *AKTIF*\n"
        "Prediksi akan dikirim setiap jam.",
        parse_mode="Markdown"
    )
    log.info("Auto prediksi: ON")


async def cmd_berhenti(update: Update, context: ContextTypes.DEFAULT_TYPE):
    SystemState.update(auto_send=False)
    await update.message.reply_text(
        "⛔ Auto prediksi *MATI*",
        parse_mode="Markdown"
    )
    log.info("Auto prediksi: OFF")


async def cmd_sekarang(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Tampilkan prediksi + signal sekaligus."""
    await update.message.reply_text("⏳ Mengambil data...")
    try:
        result = run_prediction_cycle()
        if not result:
            await update.message.reply_text("❌ Prediksi gagal. Cek logs.")
            return

        current_price = result["current_price"]

        # Prediksi
        await update.message.reply_text(
            _format_prediction(result),
            parse_mode="Markdown"
        )

        # Signal
        signal = _get_current_signal(current_price)
        if signal:
            await update.message.reply_text(
                _format_signal(signal, current_price),
                parse_mode="Markdown"
            )

    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")
        log.error(f"cmd_sekarang error: {e}", exc_info=True)


async def cmd_signal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Tampilkan signal trading saat ini."""
    await update.message.reply_text("⏳ Menganalisis signal...")
    try:
        result = run_prediction_cycle()
        if not result:
            await update.message.reply_text("❌ Gagal ambil harga.")
            return

        current_price = result["current_price"]
        signal        = _get_current_signal(current_price)

        if signal:
            await update.message.reply_text(
                _format_signal(signal, current_price),
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text(
                "⚠️ Data indikator belum cukup."
            )

    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")
        log.error(f"cmd_signal error: {e}", exc_info=True)


async def cmd_trading_on(update: Update, context: ContextTypes.DEFAULT_TYPE):
    SystemState.update(trading_on=True, paper_trade=True)
    await update.message.reply_text(
        "✅ Paper Trading *AKTIF*\n\n"
        "⚙️ *Config:*\n"
        f"  • Stop Loss  : `-2.0%`\n"
        f"  • Take Profit: `+8.0%`\n"
        f"  • Cooldown   : `72 jam`",
        parse_mode="Markdown"
    )
    log.info("Paper trading: ON")


async def cmd_trading_off(update: Update, context: ContextTypes.DEFAULT_TYPE):
    SystemState.update(trading_on=False)
    await update.message.reply_text(
        "⛔ Trading *MATI*",
        parse_mode="Markdown"
    )
    log.info("Paper trading: OFF")


async def cmd_portfolio(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    try:
        from app.utils.timezone_helper import format_wib
        portfolio = get_portfolio()
        status    = portfolio.get_status()
        trades    = TradeLogs.get_latest(limit=5)

        position  = status.get("position", "NONE")
        pos_emoji = "🟡 TERBUKA" if position == "OPEN" else "⚪ KOSONG"
        upnl      = status.get("unrealized_pnl_pct", 0.0)
        cd_left   = status.get("cooldown_remaining_h", 0.0)
        upnl_str  = f"`{upnl:+.2f}%`" if position == "OPEN" else "`-`"

        text = (
            f"💼 *Portfolio Status*\n\n"
            f"💵 Balance     : `${status['balance']:,.2f} USDT`\n"
            f"₿  BTC Held   : `{status['btc']:.6f} BTC`\n"
            f"📍 Entry Price : `${status['entry_price']:,.2f}`\n"
            f"📊 Total Asset : `${status['total_asset']:,.2f}`\n"
            f"📌 Posisi      : {pos_emoji}\n"
            f"📈 Unrealized  : {upnl_str}\n\n"
            f"⚙️ *Config:*\n"
            f"  • Stop Loss  : `-2.0%`\n"
            f"  • Take Profit: `+8.0%`\n"
            f"  • Cooldown   : "
            f"`{cd_left:.1f} jam lagi`"
            f" ({'Siap' if cd_left <= 0 else 'Tunggu'})\n\n"
        )

        if trades:
            text += "📜 *5 Trade Terakhir:*\n"
            for t in trades[-5:]:
                act   = t["action"]
                emoji = "🟢" if act == "BUY" else "🔴"
                # Konversi timestamp ke WIB
                ts_wib = format_wib(
                    t["timestamp"], "%d/%m %H:%M WIB"
                )
                text += (
                    f"{emoji} {act} `${t['price']:,.2f}` | "
                    f"Bal: `${t['balance']:,.2f}` | "
                    f"_{ts_wib}_\n"
                )

        await update.message.reply_text(text, parse_mode="Markdown")

    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")
        log.error(f"cmd_portfolio error: {e}", exc_info=True)


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        state     = SystemState.get()
        portfolio = get_portfolio()
        status    = portfolio.get_status()

        await update.message.reply_text(
            f"⚙️ *System Status*\n\n"
            f"📬 Auto Prediksi : `{'ON' if state.get('auto_send') else 'OFF'}`\n"
            f"💹 Trading       : `{'ON' if state.get('trading_on') else 'OFF'}`\n"
            f"🧪 Mode          : `{'Paper' if state.get('paper_trade') else 'Real'}`\n"
            f"📌 Posisi        : `{status.get('position', 'NONE')}`\n"
            f"💵 Total Asset   : `${status['total_asset']:,.2f}`\n"
            f"⏳ Cooldown Sisa : `{status.get('cooldown_remaining_h', 0):.1f} jam`\n"
            f"🕒 Updated       : `{state.get('updated_at')}`",
            parse_mode="Markdown"
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")
        log.error(f"cmd_status error: {e}", exc_info=True)


async def cmd_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Mengambil data...")

    try:
        from app.database.models import (
            PriceData1m, BacktestResults,
            ModelLogs, Predictions
        )
        from app.utils.timezone_helper import format_wib, now_wib

        lines = [
            f"📊 *BTC AI System Info*",
            f"🕒 _{format_wib(now_wib())}_\n"
        ]

        # [1] Harga terkini
        rows_1m = PriceData1m.get_latest(limit=2)
        if rows_1m and len(rows_1m) >= 2:
            price     = float(rows_1m[-1]["close"])
            prev      = float(rows_1m[-2]["close"])
            change    = price - prev
            change_pct= change / prev * 100
            ts_wib    = format_wib(rows_1m[-1]["timestamp"], "%H:%M WIB")
            emoji_p   = "📈" if change >= 0 else "📉"

            lines.append("💰 *Harga BTC Sekarang*")
            lines.append(
                f"  {emoji_p} `${price:,.2f}` "
                f"({change:+,.2f} / {change_pct:+.2f}%)"
            )
            lines.append(f"  🕒 Update: `{ts_wib}`\n")

        # [2] Prediksi terakhir
        preds = Predictions.get_latest(limit=1)
        if preds:
            p        = preds[0]
            pred_avg = float(p["pred_avg"])
            diff_pct = (pred_avg - price) / price * 100
            ts_wib   = format_wib(p["created_at"], "%H:%M WIB")
            emoji_p  = "📈" if diff_pct >= 0 else "📉"

            lines.append("🔮 *Prediksi 60 Menit ke Depan*")
            lines.append(
                f"  {emoji_p} Avg: `${pred_avg:,.2f}` "
                f"({diff_pct:+.2f}%)"
            )
            lines.append(
                f"  📉 Min: `${float(p['pred_min']):,.2f}` | "
                f"📈 Max: `${float(p['pred_max']):,.2f}`"
            )
            lines.append(f"  🕒 Dibuat: `{ts_wib}`\n")

        # [3] Backtest terbaik
        all_bt = BacktestResults.get_all()
        if all_bt:
            best_bt   = max(all_bt, key=lambda x: x["roi_pct"])
            latest_bt = all_bt[0]

            lines.append("🧪 *Hasil Backtest*")
            lines.append(
                f"  🏆 Terbaik: ROI `{best_bt['roi_pct']:+.2f}%`"
                f" | WR `{best_bt.get('win_rate',0):.1f}%`"
                f" | PF `{best_bt.get('profit_factor',0):.2f}`"
            )
            lines.append(
                f"  📋 Config: _{best_bt.get('notes','')}_"
            )
            lines.append(
                f"  📅 Terbaru: `{latest_bt['roi_pct']:+.2f}%` "
                f"({format_wib(latest_bt['run_at'], '%d %b %Y')})\n"
            )

        # [4] Model
        model_log = ModelLogs.get_latest()
        if model_log:
            trained_at = model_log.get("trained_at")
            loss       = model_log.get("loss", 0)
            val_loss   = model_log.get("val_loss", 0)
            epochs     = model_log.get("epochs", 0)
            data_sz    = model_log.get("data_size", 0)

            if val_loss < 0.001:   quality = "🟢 Sangat Baik"
            elif val_loss < 0.005: quality = "🟡 Baik"
            elif val_loss < 0.01:  quality = "🟠 Cukup"
            else:                  quality = "🔴 Perlu Retrain"

            # Hitung umur model
            trained_dt = to_wib(trained_at)
            days_old   = (now_wib() - trained_dt).days \
                         if trained_dt else 0

            # Next retrain (Senin 09:00 WIB)
            from datetime import timedelta
            now    = now_wib()
            days_to_monday = (7 - now.weekday()) % 7
            if days_to_monday == 0 and now.hour >= 9:
                days_to_monday = 7
            next_retrain = (now + timedelta(days=days_to_monday))\
                .replace(hour=9, minute=0, second=0)

            lines.append("🤖 *Evaluasi Model*")
            lines.append(f"  📊 Kualitas  : {quality}")
            lines.append(f"  📉 Loss      : `{loss:.6f}`")
            lines.append(f"  📉 Val Loss  : `{val_loss:.6f}`")
            lines.append(f"  🔄 Epochs    : `{epochs}`")
            lines.append(f"  📦 Data      : `{data_sz:,} baris`")
            lines.append(
                f"  📅 Trained   : "
                f"`{format_wib(trained_at, '%d %b %Y %H:%M WIB')}`"
            )
            lines.append(f"  🕐 Umur      : `{days_old} hari`")
            lines.append(
                f"  🔄 Retrain   : "
                f"`{next_retrain.strftime('%d %b %Y 09:00 WIB')} "
                f"(Senin)`\n"
            )

        # [5] Status sistem
        state = SystemState.get()
        lines.append("⚙️ *Status Sistem*")
        lines.append(
            f"  📬 Auto Prediksi : "
            f"`{'ON' if state.get('auto_send') else 'OFF'}`"
        )
        lines.append(
            f"  💹 Paper Trading : "
            f"`{'ON' if state.get('trading_on') else 'OFF'}`"
        )

        await update.message.reply_text(
            "\n".join(lines),
            parse_mode="Markdown"
        )

    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")
        log.error(f"cmd_info error: {e}", exc_info=True)


# ══════════════════════════════════════════════════════════════
#  NOTIFIKASI TRADE OTOMATIS
# ══════════════════════════════════════════════════════════════
async def notify_trade(
    context : ContextTypes.DEFAULT_TYPE,
    action  : str,
    price   : float,
    reason  : str,
    balance : float,
    btc     : float
):
    """
    Kirim notifikasi ke Telegram saat BUY/SELL terjadi.
    Dipanggil dari paper_trading.py via callback.
    """
    emoji = "🟢 *BUY*" if action == "BUY" else "🔴 *SELL*"
    total = balance + btc * price

    text = (
        f"{emoji} *Trade Executed!*\n\n"
        f"💰 Harga   : `${price:,.2f}`\n"
        f"₿  BTC    : `{btc:.6f}`\n"
        f"💵 Balance : `${balance:,.2f}`\n"
        f"📊 Total   : `${total:,.2f}`\n\n"
        f"📋 Alasan  : _{reason}_"
    )
    await _send(context, text)


# ══════════════════════════════════════════════════════════════
#  SCHEDULED JOBS
# ══════════════════════════════════════════════════════════════
async def send_scheduled_prediction(context: ContextTypes.DEFAULT_TYPE):
    """
    Job: kirim prediksi otomatis setiap jam.
    Sekaligus jalankan trading cycle.
    """
    state = SystemState.get()

    try:
        result = run_prediction_cycle()
        if not result:
            return

        current_price = result["current_price"]

        # Kirim prediksi + signal jika auto_send ON
        if state.get("auto_send", False):
            signal = _get_current_signal(current_price)

            if signal:
                # Gabungkan prediksi + signal dalam satu pesan
                await _send(
                    context,
                    _format_prediction_with_signal(result, signal)
                )
            else:
                # Fallback: hanya prediksi
                await _send(context, _format_prediction(result))

        # Jalankan trading cycle
        if state.get("trading_on", False):
            portfolio_before = get_portfolio()
            btc_before       = portfolio_before.btc

            run_trading_cycle(result, current_price)

            portfolio_after = get_portfolio()
            latest_trades   = TradeLogs.get_latest(limit=1)

            if latest_trades:
                last_t    = latest_trades[0]
                btc_after = portfolio_after.btc

                if btc_before != btc_after:
                    await notify_trade(
                        context = context,
                        action  = last_t["action"],
                        price   = last_t["price"],
                        reason  = last_t.get("reason", "-"),
                        balance = portfolio_after.balance,
                        btc     = portfolio_after.btc
                    )

    except Exception as e:
        log.error(f"Scheduled job error: {e}", exc_info=True)


# ══════════════════════════════════════════════════════════════
#  BOT FACTORY
# ══════════════════════════════════════════════════════════════
def build_bot() -> Application:
    app = (
        Application.builder()
        .token(config.TELEGRAM_TOKEN)
        .build()
    )

    # Register command handlers
    handlers = [
        ("start",       cmd_start),
        ("help",        cmd_help),
        ("info",        cmd_info),
        ("prediksi",    cmd_prediksi),
        ("berhenti",    cmd_berhenti),
        ("sekarang",    cmd_sekarang),
        ("signal",      cmd_signal),
        ("trading_on",  cmd_trading_on),
        ("trading_off", cmd_trading_off),
        ("portfolio",   cmd_portfolio),
        ("status",      cmd_status),
    ]

    for name, handler in handlers:
        app.add_handler(CommandHandler(name, handler))

    # Job: prediksi + trading setiap 60 menit
    app.job_queue.run_repeating(
        send_scheduled_prediction,
        interval = 60 * 60,   # 1 jam
        first    = 10         # mulai 10 detik setelah bot start
    )

    log.info("✅ Telegram bot built")
    return app