import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    # ── Database ──────────────────────────────────────────
    DB_NAME     = os.getenv("DB_NAME", "btc_ai")
    DB_USER     = os.getenv("DB_USER", "postgres")
    DB_PASSWORD = os.getenv("DB_PASSWORD", "password")
    DB_HOST     = os.getenv("DB_HOST", "localhost")
    DB_PORT     = os.getenv("DB_PORT", "5432")

    # ── Telegram ──────────────────────────────────────────
    TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN", "")
    TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

    # Validasi saat startup
    def validate(self):
        errors = []
        if not self.TELEGRAM_TOKEN or self.TELEGRAM_TOKEN == "your_bot_token_here":
            errors.append("❌ TELEGRAM_TOKEN belum diisi di .env")
        if not self.TELEGRAM_CHAT_ID:
            errors.append("❌ TELEGRAM_CHAT_ID belum diisi di .env")
        return errors

    # ── Kraken API (tidak butuh key untuk public endpoints) ───
    KRAKEN_BASE_URL = "https://api.kraken.com/0/public"
    KRAKEN_PAIR     = "BTC/USD"

    # ── Model ─────────────────────────────────────────────
    MODEL_DIR   = os.getenv("MODEL_DIR", "models")
    LOG_DIR     = os.getenv("LOG_DIR", "logs")
    WINDOW_SIZE = int(os.getenv("WINDOW_SIZE", 60))

    # ── Training ──────────────────────────────────────────
    RETRAIN_INTERVAL_DAYS = int(os.getenv("RETRAIN_INTERVAL_DAYS", 7))
    EPOCHS                = 50
    BATCH_SIZE            = 32
    MAX_MODEL_VERSIONS    = 5        # simpan max 5 versi model

    # ── Prediction ────────────────────────────────────────
    PREDICTION_INTERVAL_MINUTES = int(
        os.getenv("PREDICTION_INTERVAL_MINUTES", 60)
    )
    PREDICTION_STEPS = 1    # prediksi 1 jam ke depan (1 candle)
    WINDOW_SIZE      = 60   # pakai 60 jam terakhir sebagai input

    # ── Risk Management ───────────────────────────────────
    STOP_LOSS_PCT   = -0.02          # -2%
    TAKE_PROFIT_PCT =  0.03          # +3%
    COOLDOWN_MINUTES = 30            # anti overtrading

    # ── Paper Trading ─────────────────────────────────────
    INITIAL_BALANCE = 1000.0         # USDT

    # ── Strategy ──────────────────────────────────────────
    RSI_OVERSOLD    = 35
    RSI_OVERBOUGHT  = 65
    MIN_SCORE       = 2              # minimum filter score untuk entry

config = Config()