import psycopg2
from psycopg2.extras import RealDictCursor
from contextlib import contextmanager
from app.utils.config import config
from app.utils.logger import get_logger

log = get_logger(__name__)

# ── Connection string ─────────────────────────────────────────────────────────
DSN = (
    f"dbname={config.DB_NAME} "
    f"user={config.DB_USER} "
    f"password={config.DB_PASSWORD} "
    f"host={config.DB_HOST} "
    f"port={config.DB_PORT}"
)

@contextmanager
def get_conn():
    
    # Context manager koneksi PostgreSQL.
    # Auto commit & close, auto rollback jika error.
    
    conn = None
    try:
        conn = psycopg2.connect(DSN, cursor_factory=RealDictCursor)
        yield conn
        conn.commit()
    except Exception as e:
        if conn:
            conn.rollback()
        log.error(f"DB error: {e}")
        raise
    finally:
        if conn:
            conn.close()


def init_db():
    """Buat semua tabel jika belum ada."""
    sql = """
    -- ── price_data ─────────────────────────────────────
    CREATE TABLE IF NOT EXISTS price_data (
        id          SERIAL PRIMARY KEY,
        timestamp   TIMESTAMP UNIQUE NOT NULL,
        open        FLOAT,
        high        FLOAT,
        low         FLOAT,
        close       FLOAT NOT NULL,
        volume      FLOAT
    );
    CREATE INDEX IF NOT EXISTS idx_price_time
        ON price_data(timestamp);

    -- ── indicators ──────────────────────────────────────
    CREATE TABLE IF NOT EXISTS indicators (
        id          SERIAL PRIMARY KEY,
        timestamp   TIMESTAMP UNIQUE NOT NULL,
        rsi         FLOAT,
        macd        FLOAT,
        macd_signal FLOAT,
        ma_20       FLOAT,
        ma_50       FLOAT
    );
    CREATE INDEX IF NOT EXISTS idx_ind_time
        ON indicators(timestamp);

    -- ── predictions ─────────────────────────────────────
    CREATE TABLE IF NOT EXISTS predictions (
        id          SERIAL PRIMARY KEY,
        created_at  TIMESTAMP NOT NULL,
        pred_min    FLOAT,
        pred_max    FLOAT,
        pred_avg    FLOAT,
        pred_prices TEXT
    );

    -- ── actual_prices ────────────────────────────────────
    CREATE TABLE IF NOT EXISTS actual_prices (
        id          SERIAL PRIMARY KEY,
        timestamp   TIMESTAMP UNIQUE NOT NULL,
        price       FLOAT NOT NULL
    );

    -- ── model_logs ───────────────────────────────────────
    CREATE TABLE IF NOT EXISTS model_logs (
        id          SERIAL PRIMARY KEY,
        trained_at  TIMESTAMP NOT NULL,
        loss        FLOAT,
        val_loss    FLOAT,
        epochs      INT,
        data_size   INT,
        model_file  TEXT
    );

    -- ── system_state ─────────────────────────────────────
    CREATE TABLE IF NOT EXISTS system_state (
        id          SERIAL PRIMARY KEY,
        auto_send   BOOLEAN DEFAULT FALSE,
        paper_trade BOOLEAN DEFAULT TRUE,
        trading_on  BOOLEAN DEFAULT FALSE,
        updated_at  TIMESTAMP DEFAULT NOW()
    );

    -- ── trade_logs ───────────────────────────────────────
    CREATE TABLE IF NOT EXISTS trade_logs (
        id          SERIAL PRIMARY KEY,
        timestamp   TIMESTAMP NOT NULL,
        action      TEXT,
        price       FLOAT,
        amount_btc  FLOAT,
        balance     FLOAT,
        reason      TEXT,
        mode        TEXT
    );

    -- ── backtest_results ─────────────────────────────────
    CREATE TABLE IF NOT EXISTS backtest_results (
        id               SERIAL PRIMARY KEY,
        run_at           TIMESTAMP NOT NULL,
        initial_balance  FLOAT,
        final_total      FLOAT,
        profit_loss      FLOAT,
        roi_pct          FLOAT,
        total_trades     INT,
        buy_count        INT,
        sell_count       INT,
        win_rate         FLOAT DEFAULT 0,    -- ← tambah
        max_drawdown     FLOAT DEFAULT 0,    -- ← tambah
        profit_factor    FLOAT DEFAULT 0,    -- ← tambah
        data_from        TIMESTAMP,
        data_to          TIMESTAMP,
        data_points      INT,
        notes            TEXT
    );

    -- ── backtest_trades ──────────────────────────────────
    CREATE TABLE IF NOT EXISTS backtest_trades (
        id              SERIAL PRIMARY KEY,
        backtest_id     INT REFERENCES backtest_results(id),
        timestamp       TIMESTAMP,
        action          TEXT,
        price           FLOAT,
        btc             FLOAT,
        balance         FLOAT,
        reason          TEXT
    );

    -- ── backtest_equity ──────────────────────────────────
    CREATE TABLE IF NOT EXISTS backtest_equity (
        id          SERIAL PRIMARY KEY,
        backtest_id INT REFERENCES backtest_results(id),
        timestamp   TIMESTAMP,
        total       FLOAT
    );

    -- ── price_data_1m ─────────────────────────────────────

    CREATE TABLE IF NOT EXISTS price_data_1m (
        id          SERIAL PRIMARY KEY,
        timestamp   TIMESTAMP UNIQUE NOT NULL,
        open        REAL NOT NULL,
        high        REAL NOT NULL,
        low         REAL NOT NULL,
        close       REAL NOT NULL,
        volume      REAL NOT NULL
    );
    
    CREATE INDEX IF NOT EXISTS idx_price_1m_ts
        ON price_data_1m (timestamp DESC);

    -- Insert default state jika belum ada
    INSERT INTO system_state (auto_send, paper_trade, trading_on)
    SELECT FALSE, TRUE, FALSE
    WHERE NOT EXISTS (SELECT 1 FROM system_state);
    """

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql)

    log.info("✅ Database initialized successfully")