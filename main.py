# main.py

import asyncio
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger
import pytz

from app.database.db import init_db
from app.data.fetcher import (
    fetch_and_store_1h,
    fetch_and_store_1m_ohlc,
    fetch_current_price_from_db
)
from app.data.processor import compute_and_store
from app.services.prediction_service import run_prediction_cycle
from app.services.training_service import (
    run_training_pipeline, auto_retrain_if_needed
)
from app.services.paper_trading import (
    run_trading_cycle,
    run_trading_cycle_realtime
)
from app.bot.telegram import build_bot
from app.utils.logger import get_logger
from app.utils.config import config
from app.utils.timezone_helper import now_wib, format_wib

log = get_logger("main")

# Timezone WIB untuk scheduler
WIB_TZ = pytz.timezone("Asia/Jakarta")


def job_fetch_ohlc_1m():
    try:
        fetch_and_store_1m_ohlc()
    except Exception as e:
        log.warning(f"⚠️ job_fetch_ohlc_1m skip: {e}")


def job_fetch_1h():
    try:
        df = fetch_and_store_1h()
        if not df.empty:
            compute_and_store(df)
    except Exception as e:
        log.warning(f"⚠️ job_fetch_1h skip: {e}")


def job_prediction():
    try:
        result = run_prediction_cycle()
        if result:
            price = fetch_current_price_from_db()
            if price > 0:
                run_trading_cycle(result, price)
    except Exception as e:
        log.warning(f"⚠️ job_prediction skip: {e}")


def job_trading_realtime():
    try:
        price = fetch_current_price_from_db()
        if price <= 0:
            log.debug("⚠️ Harga 1M tidak tersedia, skip trading")
            return
        run_trading_cycle_realtime(price)
    except Exception as e:
        log.warning(f"⚠️ job_trading_realtime skip: {e}")


def job_auto_retrain():
    try:
        log.info(
            f"🔄 Weekly retrain dimulai "
            f"({format_wib(now_wib())})"
        )
        auto_retrain_if_needed()
    except Exception as e:
        log.error(f"❌ job_auto_retrain error: {e}")


def main():
    log.info("🚀 BTC AI System Starting...")
    log.info(f"   Waktu WIB: {format_wib(now_wib())}")

    if not config.TELEGRAM_TOKEN or \
       config.TELEGRAM_TOKEN == "your_bot_token_here":
        log.error("❌ TELEGRAM_TOKEN belum diisi di .env!")
        return

    init_db()
    log.info("✅ Database ready")

    from app.model.trainer import get_latest_model_path
    model_path, _ = get_latest_model_path()
    if not model_path:
        log.info("🆕 Training awal...")
        run_training_pipeline(incremental=False)
    else:
        log.info(f"✅ Model: {model_path}")

    # Fetch data awal
    log.info("📥 Fetch data awal...")
    job_fetch_ohlc_1m()
    job_fetch_1h()

    # Scheduler pakai WIB
    scheduler = BackgroundScheduler(
        timezone = WIB_TZ    # ← WIB
    )

    # Per 5 menit: OHLC 1M
    scheduler.add_job(
        job_fetch_ohlc_1m,
        trigger          = IntervalTrigger(minutes=5),
        id               = "fetch_ohlc_1m",
        name             = "Fetch OHLC 1M",
        max_instances    = 1,
        replace_existing = True
    )

    # Per 1 jam: OHLC 1H + indikator
    scheduler.add_job(
        job_fetch_1h,
        trigger          = IntervalTrigger(hours=1),
        id               = "fetch_1h",
        name             = "Fetch OHLC 1H",
        max_instances    = 1,
        replace_existing = True
    )

    # Per 1 jam + 2 menit: prediksi
    scheduler.add_job(
        job_prediction,
        trigger          = IntervalTrigger(hours=1, minutes=2),
        id               = "prediction",
        name             = "Hourly Prediction",
        max_instances    = 1,
        replace_existing = True
    )

    # Per 1 menit: trading realtime (1M)
    scheduler.add_job(
        job_trading_realtime,
        trigger          = IntervalTrigger(minutes=1),
        id               = "trading_rt",
        name             = "Trading Realtime (1M)",
        max_instances    = 1,
        replace_existing = True
    )

    # Setiap Senin jam 09:00 WIB (= 02:00 UTC)
    scheduler.add_job(
        job_auto_retrain,
        trigger          = CronTrigger(
            day_of_week = "mon",
            hour        = 9,      # ← 09:00 WIB
            minute      = 0,
            timezone    = WIB_TZ
        ),
        id               = "retrain",
        name             = "Weekly Retrain (Senin 09:00 WIB)",
        max_instances    = 1,
        replace_existing = True
    )

    scheduler.start()

    log.info("✅ Scheduler aktif (WIB):")
    for job in scheduler.get_jobs():
        next_run = job.next_run_time
        if next_run:
            next_wib = next_run.astimezone(WIB_TZ)
            log.info(
                f"   ├── [{job.id}] {job.name}"
                f" | next: {next_wib.strftime('%Y-%m-%d %H:%M WIB')}"
            )

    log.info("🤖 Starting Telegram Bot...")
    bot = build_bot()
    bot.run_polling(allowed_updates=["message"])


if __name__ == "__main__":
    main()