from datetime import datetime, timedelta, timezone
from app.model.trainer import train
from app.data.fetcher import fetch_and_store_1h
from app.data.processor import compute_and_store
from app.database.models import ModelLogs
from app.utils.config import config
from app.utils.logger import get_logger

log = get_logger(__name__)


def should_retrain() -> bool:
    """
    Cek apakah perlu retrain berdasarkan waktu training terakhir.
    Return True jika belum pernah train atau sudah > RETRAIN_INTERVAL_DAYS.
    """
    last = ModelLogs.get_latest()
    if not last:
        return True

    last_trained = last["trained_at"]
    if isinstance(last_trained, str):
        last_trained = datetime.fromisoformat(last_trained)

    delta = datetime.utcnow() - last_trained
    return delta > timedelta(days=config.RETRAIN_INTERVAL_DAYS)


def run_training_pipeline(
    incremental : bool = True,
    historical  : bool = False,
    total_days  : int  = 365
) -> dict:

    log.info("🚀 Training Pipeline START")

    if historical:
        log.info(f"📥 Mode historis: {total_days} hari (Kraken 1H)")
        from app.data.fetcher import fetch_and_store_historical
        from app.data.fetcher import INTERVAL_1H
        df = fetch_and_store_historical(
            total_days = total_days,
            interval   = INTERVAL_1H
        )
    else:
        from app.data.fetcher import fetch_and_store_1h
        df = fetch_and_store_1h()

    if not df.empty:
        from app.data.processor import compute_and_store
        compute_and_store(df)

    result = train(incremental=incremental)
    log.info(f"✅ Training Pipeline DONE: {result}")
    return result


def auto_retrain_if_needed():
    """
    Retrain model dengan data 365 hari terbaru (interval 1H).
    Dipanggil setiap Senin jam 02:00 UTC.
    """
    log.info("🔍 Checking retrain condition...")

    model_log = ModelLogs.get_latest()

    if model_log:
        trained_at = model_log.get("trained_at")
        if isinstance(trained_at, str):
            trained_at = datetime.fromisoformat(trained_at)

        # Pastikan timezone aware
        if trained_at.tzinfo is None:
            trained_at = trained_at.replace(tzinfo=timezone.utc)

        now      = datetime.now(timezone.utc)
        days_old = (now - trained_at).days

        log.info(f"   Model terakhir dilatih: {days_old} hari lalu")

        # Jika model belum seminggu, skip
        if days_old < 6:
            log.info(
                f"   ⏭️  Skip retrain, model baru {days_old} hari"
            )
            return

    log.info("🚀 Memulai weekly retrain...")
    run_training_pipeline(incremental=True)
    log.info("✅ Weekly retrain selesai")