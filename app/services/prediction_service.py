# app/services/prediction_service.py

import csv
import os
from datetime import datetime
import pandas as pd

from app.model.predictor import predict
from app.data.fetcher import (
    fetch_current_price,
    fetch_current_price_from_db,
    fetch_and_store_1h,
    fetch_and_store_1m_ohlc,        # ← tambah import
)
from app.data.processor import compute_and_store
from app.database.models import ActualPrices, Predictions
from app.utils.config import config
from app.utils.logger import get_logger

log = get_logger(__name__)

PRED_LOG = os.path.join(config.LOG_DIR, "prediction.csv")
os.makedirs(config.LOG_DIR, exist_ok=True)


def _ensure_pred_log():
    if not os.path.exists(PRED_LOG):
        with open(PRED_LOG, "w", newline="") as f:
            csv.writer(f).writerow([
                "created_at", "pred_avg", "pred_min",
                "pred_max", "current_price", "mae"
            ])


def run_prediction_cycle() -> dict:
    log.info("━━━━━ Prediction Cycle START ━━━━━")

    # ── 1. Update data 1H (untuk input model) ────────────────
    df = fetch_and_store_1h()
    if not df.empty:
        compute_and_store(df)

    # ── 2. Refresh data 1M sebelum prediksi ──────────────────
    # Pastikan harga terkini tersedia sebelum predict() dipanggil
    log.info("📥 Refresh harga 1M sebelum prediksi...")
    fetch_and_store_1m_ohlc()

    # ── 3. Simpan harga aktual ────────────────────────────────
    current_price = fetch_current_price_from_db()   # ← dari 1M
    if current_price <= 0:
        current_price = fetch_current_price()        # ← fallback API

    if current_price > 0:
        ActualPrices.insert(datetime.utcnow(), current_price)

    # ── 4. Prediksi ───────────────────────────────────────────
    result = predict()
    if not result:
        log.warning("⚠️ Prediksi gagal")
        return {}

    # ── 5. Log CSV ────────────────────────────────────────────
    _ensure_pred_log()
    with open(PRED_LOG, "a", newline="") as f:
        csv.writer(f).writerow([
            datetime.utcnow().isoformat(),
            round(result["pred_avg"], 2),
            round(result["pred_min"], 2),
            round(result["pred_max"], 2),
            round(result.get("current_price", current_price), 2),
            ""
        ])

    log.info("━━━━━ Prediction Cycle DONE ━━━━━")
    return result


def get_prediction_history() -> pd.DataFrame:
    try:
        return pd.read_csv(PRED_LOG)
    except Exception:
        return pd.DataFrame()