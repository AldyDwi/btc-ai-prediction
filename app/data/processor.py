import pandas as pd
import numpy as np
from ta.momentum import RSIIndicator
from ta.trend import MACD, SMAIndicator
from app.utils.logger import get_logger
from app.database.models import Indicators, PriceData

log = get_logger(__name__)


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Hitung RSI, MACD, MA dari DataFrame harga.
    Input df harus punya kolom: close, volume (opsional)
    """
    df = df.copy().sort_values("timestamp").reset_index(drop=True)

    # ── RSI ───────────────────────────────────────────────────────────
    rsi = RSIIndicator(close=df["close"], window=14)
    df["rsi"] = rsi.rsi()

    # ── MACD ──────────────────────────────────────────────────────────
    macd_ind = MACD(
        close=df["close"],
        window_slow=26,
        window_fast=12,
        window_sign=9
    )
    df["macd"]        = macd_ind.macd()
    df["macd_signal"] = macd_ind.macd_signal()

    # ── Moving Average ────────────────────────────────────────────────
    df["ma_20"] = SMAIndicator(close=df["close"], window=20).sma_indicator()
    df["ma_50"] = SMAIndicator(close=df["close"], window=50).sma_indicator()
    
    df["ma_100"] = SMAIndicator(close=df["close"], window=100).sma_indicator()
    df["ma_200"] = SMAIndicator(close=df["close"], window=200).sma_indicator()

    # ── Drop NA ───────────────────────────────────────────────────────
    before = len(df)
    df = df.dropna().reset_index(drop=True)
    log.debug(f"Dropped {before - len(df)} NA rows, kept {len(df)}")

    return df


def compute_and_store(df: pd.DataFrame = None) -> pd.DataFrame:
    """
    Ambil data dari DB (atau pakai df yg diberikan),
    hitung indikator, simpan ke tabel indicators.
    """
    if df is None:
        rows = PriceData.get_latest(limit=500)
        df   = pd.DataFrame(rows)

    if df.empty:
        log.warning("⚠️ Empty DataFrame, skipping indicator computation")
        return df

    df_ind = compute_indicators(df)

    ind_rows = df_ind[[
        "timestamp", "rsi", "macd", "macd_signal", "ma_20", "ma_50"
    ]].to_dict(orient="records")

    Indicators.bulk_insert(ind_rows)
    log.info(f"✅ Stored {len(ind_rows)} indicator rows")

    return df_ind