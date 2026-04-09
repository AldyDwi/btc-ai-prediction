import numpy as np
from tensorflow.keras.models import Sequential, load_model
from tensorflow.keras.layers import (
    LSTM, Dense, Dropout, Bidirectional, Input
)
from tensorflow.keras.optimizers import Adam
from tensorflow.keras.callbacks import EarlyStopping, ReduceLROnPlateau
from app.utils.config import config
from app.utils.logger import get_logger

log = get_logger(__name__)

FEATURES = ["close", "volume", "rsi", "macd", "macd_signal", "ma_20", "ma_50"]


def build_model(
    window_size  : int = config.WINDOW_SIZE,    # 60 jam input
    n_features   : int = len(FEATURES),
    output_steps : int = config.PREDICTION_STEPS  # 1 output
) -> Sequential:
    """
    Model LSTM untuk prediksi 1 JAM ke depan.

    Input : 60 jam data historis
    Output: 1 harga (1 jam ke depan)
    """
    model = Sequential([
        Input(shape=(window_size, n_features)),

        Bidirectional(LSTM(128, return_sequences=True)),
        Dropout(0.2),

        LSTM(64, return_sequences=False),
        Dropout(0.2),

        Dense(64, activation="relu"),
        Dense(32, activation="relu"),

        Dense(output_steps)   # output 1 nilai
    ])

    model.compile(
        optimizer = Adam(learning_rate=0.0005),
        loss      = "huber",
        metrics   = ["mae"]
    )

    return model


def get_callbacks() -> list:
    return [
        EarlyStopping(
            monitor="val_loss",
            patience=15,
            restore_best_weights=True,
            verbose=1
        ),
        ReduceLROnPlateau(
            monitor="val_loss",
            factor=0.5,
            patience=7,
            min_lr=1e-6,
            verbose=1
        )
    ]