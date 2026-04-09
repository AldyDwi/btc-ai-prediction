import os
import glob
import numpy as np
import pandas as pd
import joblib
from datetime import datetime
from sklearn.preprocessing import MinMaxScaler
from sklearn.model_selection import train_test_split
from tensorflow.keras.models import load_model

from app.model.lstm import build_model, get_callbacks, FEATURES
from app.utils.config import config
from app.utils.logger import get_logger
from app.database.models import ModelLogs, Indicators, PriceData

log = get_logger(__name__)

os.makedirs(config.MODEL_DIR, exist_ok=True)


# ══════════════════════════════════════════════════════════════
#  VERSIONING SYSTEM
# ══════════════════════════════════════════════════════════════

def _version_tag() -> str:
    """Buat tag unik berdasarkan waktu. Contoh: 20240115_143022"""
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _get_model_path(tag: str) -> str:
    return os.path.join(config.MODEL_DIR, f"lstm_{tag}.keras")


def _get_scaler_path(tag: str) -> str:
    return os.path.join(config.MODEL_DIR, f"scaler_{tag}.pkl")


def list_all_models() -> list[dict]:
    """
    List semua model yang ada di folder models/.
    Return list of dict, sorted dari TERLAMA ke TERBARU.
    
    Contoh output:
    [
        {"tag": "20240101_120000", "model": "models/lstm_20240101_120000.keras", 
         "scaler": "models/scaler_20240101_120000.pkl"},
        {"tag": "20240108_120000", ...},  ← terbaru
    ]
    """
    pattern = os.path.join(config.MODEL_DIR, "lstm_*.keras")
    model_files = sorted(glob.glob(pattern))  # sorted by filename = by time

    result = []
    for model_file in model_files:
        # Extract tag dari filename
        # "models/lstm_20240115_143022.keras" → "20240115_143022"
        basename = os.path.basename(model_file)
        tag      = basename.replace("lstm_", "").replace(".keras", "")
        
        scaler_file = _get_scaler_path(tag)
        
        result.append({
            "tag"        : tag,
            "model_path" : model_file,
            "scaler_path": scaler_file,
            "scaler_exists": os.path.exists(scaler_file)
        })

    return result


def _cleanup_old_models():
    """
    Hapus model lama jika jumlah model > MAX_MODEL_VERSIONS.
    
    Logika:
    - Misal ada 6 model, MAX = 5
    - Urutkan dari terlama ke terbaru
    - Hapus 1 model terlama
    - Sisa 5 model terbaru tetap ada
    
    Contoh:
    Sebelum: [v1, v2, v3, v4, v5, v6]  ← 6 model
    Hapus  : [v1]                        ← hapus terlama
    Sesudah: [v2, v3, v4, v5, v6]       ← 5 model tersisa
    """
    all_models = list_all_models()
    total      = len(all_models)

    log.info(f"📦 Total model tersimpan: {total} | Max: {config.MAX_MODEL_VERSIONS}")

    if total <= config.MAX_MODEL_VERSIONS:
        log.info("✅ Jumlah model masih dalam batas, tidak perlu hapus")
        return

    # Hitung berapa yang harus dihapus
    to_delete_count = total - config.MAX_MODEL_VERSIONS
    models_to_delete = all_models[:to_delete_count]  # ambil dari depan (terlama)

    log.info(f"🗑️  Akan menghapus {to_delete_count} model lama...")

    for m in models_to_delete:
        # Hapus file .keras
        if os.path.exists(m["model_path"]):
            os.remove(m["model_path"])
            log.info(f"   🗑️  Deleted model : {m['model_path']}")

        # Hapus file scaler .pkl
        if os.path.exists(m["scaler_path"]):
            os.remove(m["scaler_path"])
            log.info(f"   🗑️  Deleted scaler: {m['scaler_path']}")

    # Verifikasi
    remaining = list_all_models()
    log.info(f"✅ Model tersisa setelah cleanup: {len(remaining)}")
    for m in remaining:
        log.info(f"   📁 {m['model_path']}")


def get_latest_model_path() -> tuple[str, str] | tuple[None, None]:
    """
    Return path model & scaler TERBARU.
    Jika tidak ada atau scaler hilang, return (None, None).
    """
    all_models = list_all_models()

    if not all_models:
        log.warning("⚠️ Belum ada model tersimpan")
        return None, None

    # Ambil yang terakhir (terbaru)
    latest = all_models[-1]

    # Validasi scaler ada
    if not latest["scaler_exists"]:
        log.error(
            f"❌ Scaler tidak ditemukan untuk model {latest['tag']}. "
            f"Skip model ini."
        )
        # Coba model sebelumnya
        for m in reversed(all_models[:-1]):
            if m["scaler_exists"]:
                log.warning(f"⚠️ Fallback ke model: {m['tag']}")
                return m["model_path"], m["scaler_path"]
        return None, None

    return latest["model_path"], latest["scaler_path"]


# ══════════════════════════════════════════════════════════════
#  DATA PREPARATION
# ══════════════════════════════════════════════════════════════

def prepare_data(df: pd.DataFrame):
    """
    Scale + windowing data untuk training LSTM.
    
    Returns:
        X      : (samples, window_size, features)
        y      : (samples, prediction_steps)
        scaler : fitted MinMaxScaler
    """
    df = df[FEATURES].copy().dropna().reset_index(drop=True)

    min_required = config.WINDOW_SIZE + config.PREDICTION_STEPS + 10
    if len(df) < min_required:
        raise ValueError(
            f"❌ Data tidak cukup: {len(df)} baris. "
            f"Butuh minimal {min_required} baris."
        )

    # Scale
    scaler = MinMaxScaler(feature_range=(0, 1))
    scaled = scaler.fit_transform(df.values)

    # Windowing
    X, y = [], []
    for i in range(config.WINDOW_SIZE, len(scaled) - config.PREDICTION_STEPS):
        X.append(scaled[i - config.WINDOW_SIZE : i])
        y.append(scaled[i : i + config.PREDICTION_STEPS, 0])  # hanya kolom close

    return np.array(X), np.array(y), scaler


def get_training_df() -> pd.DataFrame:
    """Gabungkan price_data + indicators."""
    price_rows = PriceData.get_latest(limit=10000)
    ind_rows   = Indicators.get_latest(limit=10000)

    price_df = pd.DataFrame(price_rows)
    ind_df   = pd.DataFrame(ind_rows)

    if price_df.empty or ind_df.empty:
        log.warning("⚠️ price_data atau indicators kosong")
        return pd.DataFrame()

    df = price_df.merge(
        ind_df[["timestamp", "rsi", "macd", "macd_signal", "ma_20", "ma_50"]],
        on   = "timestamp",
        how  = "inner"
    ).sort_values("timestamp").reset_index(drop=True)

    log.info(f"Training DataFrame: {len(df)} baris")
    return df


# ══════════════════════════════════════════════════════════════
#  TRAINING
# ══════════════════════════════════════════════════════════════

def train(incremental: bool = True) -> dict:
    """
    Training model LSTM.

    Flow:
    ┌─────────────────────────────────────────────────┐
    │ 1. Ambil & siapkan data                         │
    │ 2. Load model lama (incremental) / build baru   │
    │ 3. Training                                     │
    │ 4. Simpan model baru dengan tag timestamp baru  │
    │ 5. Cleanup: hapus model lama jika > MAX (5)     │
    │    → Model lama TIDAK langsung dihapus          │
    │    → Baru dihapus jika jumlah sudah melebihi    │
    └─────────────────────────────────────────────────┘

    Args:
        incremental: True  → lanjut training dari model terakhir
                     False → bangun model baru dari nol

    Returns:
        dict info hasil training
    """
    mode = "incremental" if incremental else "fresh"
    log.info(f"🚀 Training START | Mode: {mode}")

    # ── 1. Siapkan data ───────────────────────────────────────
    df = get_training_df()
    if df.empty:
        raise ValueError("❌ Tidak ada data untuk training")

    X, y, scaler = prepare_data(df)
    X_train, X_val, y_train, y_val = train_test_split(
        X, y,
        test_size = 0.15,
        shuffle   = False
    )

    log.info(
        f"Data siap | Train: {X_train.shape} | Val: {X_val.shape}"
    )

    # ── 2. Load atau build model ──────────────────────────────
    model_path, _ = get_latest_model_path()

    if incremental and model_path:
        # ✅ Lanjut training dari model SEBELUMNYA
        # Model sebelumnya BELUM dihapus di sini
        log.info(f"📂 Load model existing: {model_path}")
        model = load_model(model_path)
        log.info("✅ Model loaded, akan dilanjutkan training-nya")
    else:
        # 🆕 Buat model baru dari nol
        log.info("🆕 Build model baru dari nol")
        model = build_model(
            window_size  = config.WINDOW_SIZE,
            n_features   = X.shape[2],
            output_steps = config.PREDICTION_STEPS
        )

    # ── 3. Training ───────────────────────────────────────────
    history = model.fit(
        X_train, y_train,
        validation_data = (X_val, y_val),
        epochs          = config.EPOCHS,
        batch_size      = config.BATCH_SIZE,
        callbacks       = get_callbacks(),
        verbose         = 1
    )

    final_loss     = float(history.history["loss"][-1])
    final_val_loss = float(history.history["val_loss"][-1])
    actual_epochs  = len(history.history["loss"])

    log.info(
        f"✅ Training selesai | "
        f"Loss: {final_loss:.6f} | "
        f"Val Loss: {final_val_loss:.6f} | "
        f"Epochs: {actual_epochs}"
    )

    # ── 4. Simpan model BARU (dengan tag waktu baru) ──────────
    # Model lama BELUM dihapus sampai langkah cleanup
    tag        = _version_tag()
    save_path  = _get_model_path(tag)
    scaler_out = _get_scaler_path(tag)

    model.save(save_path)
    joblib.dump(scaler, scaler_out)

    log.info(f"💾 Model baru tersimpan: {save_path}")
    log.info(f"💾 Scaler baru tersimpan: {scaler_out}")

    # ── 5. Cleanup: hapus model lama jika > MAX_MODEL_VERSIONS ─
    # Baru dihapus SETELAH model baru berhasil disimpan
    _cleanup_old_models()

    # ── 6. Log ke database ────────────────────────────────────
    ModelLogs.insert(
        loss       = final_loss,
        val_loss   = final_val_loss,
        epochs     = actual_epochs,
        data_size  = len(df),
        model_file = save_path
    )

    return {
        "tag"        : tag,
        "model_path" : save_path,
        "scaler_path": scaler_out,
        "loss"       : final_loss,
        "val_loss"   : final_val_loss,
        "epochs"     : actual_epochs,
        "data_size"  : len(df),
        "mode"       : mode
    }