# app/model/predictor.py

import numpy as np
import pandas as pd
import joblib
from datetime import datetime, timezone
from tensorflow.keras.models import load_model

from app.model.lstm import FEATURES
from app.model.trainer import get_latest_model_path, get_training_df
from app.utils.config import config
from app.utils.logger import get_logger
from app.database.models import Predictions, PriceData1m   # ← tambah PriceData1m

log = get_logger(__name__)

_cached_model  = None
_cached_scaler = None
_cached_path   = None


def _load_model_and_scaler():
    global _cached_model, _cached_scaler, _cached_path

    model_path, scaler_path = get_latest_model_path()
    if not model_path:
        log.error("❌ Belum ada model")
        return None, None

    if _cached_path != model_path:
        log.info(f"📂 Loading model: {model_path}")
        _cached_model  = load_model(model_path)
        _cached_scaler = joblib.load(scaler_path)
        _cached_path   = model_path

    return _cached_model, _cached_scaler


def _get_current_price_from_1m() -> float:
    """
    Ambil harga terkini dari price_data_1m (lebih fresh dari 1H).
    Fallback ke 0.0 jika gagal.
    """
    try:
        price = PriceData1m.get_latest_price()
        if price and price > 0:
            log.debug(f"💰 Harga dari 1M: ${price:,.2f}")
            return float(price)
    except Exception as e:
        log.warning(f"⚠️ Gagal ambil harga dari 1M: {e}")
    return 0.0


def _interpolate_to_minutes(
    current_price : float,
    pred_price_1h : float,
    n_minutes     : int = 60
) -> list[float]:
    """
    Random walk dengan drift menuju target.
    Noise bisa sedikit melampaui range current-pred.
    """
    volatility = current_price * 0.0012

    rng = np.random.default_rng(
        seed=int(datetime.now(timezone.utc).timestamp()) % 99999
    )

    prices = [current_price]

    for i in range(1, n_minutes):
        remaining       = n_minutes - i
        correction      = (pred_price_1h - prices[-1]) / max(remaining, 1)
        drift_component = correction * 0.55

        noise_scale = volatility * (remaining / n_minutes) ** 0.5
        noise       = rng.normal(0, noise_scale)

        new_price = prices[-1] + drift_component + noise
        prices.append(new_price)

    prices.append(pred_price_1h)
    prices = prices[:n_minutes]

    prices[0]  = current_price
    prices[-1] = pred_price_1h

    return [round(float(p), 2) for p in prices]


def predict() -> dict:
    model, scaler = _load_model_and_scaler()
    if model is None:
        return {}

    # ── Ambil data training (1H) untuk input model ────────────
    df = get_training_df()
    if df.empty or len(df) < config.WINDOW_SIZE:
        log.error("❌ Data tidak cukup untuk prediksi")
        return {}

    df_feat = df[FEATURES].dropna().tail(config.WINDOW_SIZE)
    if len(df_feat) < config.WINDOW_SIZE:
        log.error(f"❌ Data setelah dropna kurang: {len(df_feat)}")
        return {}

    # ── Harga terkini: ambil dari 1M, fallback ke 1H ──────────
    current_price = _get_current_price_from_1m()
    if current_price <= 0:
        # Fallback ke close candle 1H terakhir
        current_price = float(df_feat["close"].iloc[-1])
        log.warning(
            f"⚠️ Fallback harga dari candle 1H: ${current_price:,.2f}"
        )
    else:
        log.info(
            f"💰 Harga terkini dari 1M: ${current_price:,.2f} "
            f"| Candle 1H terakhir: ${float(df_feat['close'].iloc[-1]):,.2f}"
        )

    # ── Scale & predict ───────────────────────────────────────
    scaled   = scaler.transform(df_feat.values)
    X        = scaled.reshape(1, config.WINDOW_SIZE, -1)
    raw_pred = model.predict(X, verbose=0)

    # ── Inverse scale ─────────────────────────────────────────
    n_feat      = scaler.n_features_in_
    dummy       = np.zeros((config.PREDICTION_STEPS, n_feat))
    dummy[:, 0] = raw_pred[0]
    pred_values = scaler.inverse_transform(dummy)[:, 0]
    pred_1h     = float(pred_values[0])

    # ── Interpolasi ke 60 menit ───────────────────────────────
    pred_prices = _interpolate_to_minutes(
        current_price = current_price,
        pred_price_1h = pred_1h,
        n_minutes     = 60
    )

    change_pct = (pred_1h - current_price) / current_price * 100

    # ── Hitung statistik ──────────────────────────────────────
    prices_arr = np.array(pred_prices)
    result = {
        "current_price": round(current_price, 2),
        "pred_1h"      : round(pred_1h, 2),
        "pred_prices"  : pred_prices,
        "pred_min"     : round(float(prices_arr.min()), 2),
        "pred_max"     : round(float(prices_arr.max()), 2),
        "pred_avg"     : round(float(prices_arr.mean()), 2),
        "change_pct"   : round(change_pct, 2)
    }

    # ── Simpan ke DB ──────────────────────────────────────────
    Predictions.insert(
        pred_min    = result["pred_min"],
        pred_max    = result["pred_max"],
        pred_avg    = result["pred_avg"],
        pred_prices = result["pred_prices"]
    )

    log.info(
        f"🔮 Prediksi | "
        f"Sekarang: ${current_price:,.2f} | "
        f"1 Jam: ${pred_1h:,.2f} | "
        f"Perubahan: {change_pct:+.2f}%"
    )

    return result