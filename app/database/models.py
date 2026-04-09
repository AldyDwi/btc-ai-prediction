import json
from datetime import datetime, timezone
from typing import Optional
from app.database.db import get_conn
from app.utils.logger import get_logger

log = get_logger(__name__)


# ══════════════════════════════════════════════════════════════
#  PRICE DATA
# ══════════════════════════════════════════════════════════════
class PriceData:

    @staticmethod
    def bulk_insert(rows: list[dict]):
        """
        Insert banyak baris sekaligus (batch insert).
        Skip jika timestamp sudah ada (ON CONFLICT DO NOTHING).
        """
        if not rows:
            return

        sql = """
            INSERT INTO price_data
                (timestamp, open, high, low, close, volume)
            VALUES
                (%(timestamp)s, %(open)s, %(high)s,
                 %(low)s, %(close)s, %(volume)s)
            ON CONFLICT (timestamp) DO NOTHING
        """
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.executemany(sql, rows)
        log.debug(f"Inserted {len(rows)} price rows")

    @staticmethod
    def get_latest(limit: int = 200) -> list[dict]:
        sql = """
            SELECT * FROM price_data
            ORDER BY timestamp DESC
            LIMIT %s
        """
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (limit,))
                rows = cur.fetchall()
        return [dict(r) for r in rows][::-1]   # ascending

    @staticmethod
    def get_latest_timestamp():
        """Ambil timestamp terbaru dalam UTC."""
        sql = """
            SELECT timestamp AT TIME ZONE 'UTC' as timestamp
            FROM price_data
            ORDER BY timestamp DESC
            LIMIT 1
        """
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql)
                row = cur.fetchone()

        if not row:
            return None

        ts = row["timestamp"]
        if hasattr(ts, "tzinfo") and ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts
    
    @staticmethod
    def get_count() -> int:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) as c FROM price_data")
                return cur.fetchone()["c"]


# ══════════════════════════════════════════════════════════════
#  INDICATORS
# ══════════════════════════════════════════════════════════════
class Indicators:

    @staticmethod
    def bulk_insert(rows: list[dict]):
        sql = """
            INSERT INTO indicators
                (timestamp, rsi, macd, macd_signal, ma_20, ma_50)
            VALUES
                (%(timestamp)s, %(rsi)s, %(macd)s,
                 %(macd_signal)s, %(ma_20)s, %(ma_50)s)
            ON CONFLICT (timestamp) DO NOTHING
        """
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.executemany(sql, rows)

    @staticmethod
    def get_latest(limit: int = 200) -> list[dict]:
        sql = """
            SELECT * FROM indicators
            ORDER BY timestamp DESC
            LIMIT %s
        """
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (limit,))
                rows = cur.fetchall()
        return [dict(r) for r in rows][::-1]


# ══════════════════════════════════════════════════════════════
#  PREDICTIONS
# ══════════════════════════════════════════════════════════════
class Predictions:

    @staticmethod
    def insert(pred_min: float, pred_max: float,
               pred_avg: float, pred_prices: list[float]):
        sql = """
            INSERT INTO predictions
                (created_at, pred_min, pred_max, pred_avg, pred_prices)
            VALUES
                (NOW(), %s, %s, %s, %s)
            RETURNING id
        """
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (
                    pred_min, pred_max, pred_avg,
                    json.dumps(pred_prices)
                ))
                return cur.fetchone()["id"]

    @staticmethod
    def get_latest(limit: int = 50) -> list[dict]:
        sql = """
            SELECT * FROM predictions
            ORDER BY created_at DESC
            LIMIT %s
        """
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (limit,))
                rows = cur.fetchall()
        result = []
        for r in rows:
            d = dict(r)
            if d.get("pred_prices"):
                d["pred_prices"] = json.loads(d["pred_prices"])
            result.append(d)
        return result[::-1]


# ══════════════════════════════════════════════════════════════
#  ACTUAL PRICES
# ══════════════════════════════════════════════════════════════
class ActualPrices:

    @staticmethod
    def insert(timestamp: datetime, price: float):
        sql = """
            INSERT INTO actual_prices (timestamp, price)
            VALUES (%s, %s)
            ON CONFLICT (timestamp) DO NOTHING
        """
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (timestamp, price))

    @staticmethod
    def get_latest(limit: int = 100) -> list[dict]:
        sql = """
            SELECT * FROM actual_prices
            ORDER BY timestamp DESC
            LIMIT %s
        """
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (limit,))
                rows = cur.fetchall()
        return [dict(r) for r in rows][::-1]


# ══════════════════════════════════════════════════════════════
#  MODEL LOGS
# ══════════════════════════════════════════════════════════════
class ModelLogs:

    @staticmethod
    def insert(loss: float, val_loss: float,
               epochs: int, data_size: int, model_file: str):
        sql = """
            INSERT INTO model_logs
                (trained_at, loss, val_loss, epochs, data_size, model_file)
            VALUES
                (NOW(), %s, %s, %s, %s, %s)
        """
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (
                    loss, val_loss, epochs, data_size, model_file
                ))

    @staticmethod
    def get_latest() -> Optional[dict]:
        sql = """
            SELECT * FROM model_logs
            ORDER BY trained_at DESC
            LIMIT 1
        """
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql)
                row = cur.fetchone()
        return dict(row) if row else None


# ══════════════════════════════════════════════════════════════
#  SYSTEM STATE
# ══════════════════════════════════════════════════════════════
class SystemState:

    @staticmethod
    def get() -> dict:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM system_state ORDER BY id DESC LIMIT 1"
                )
                row = cur.fetchone()
        return dict(row) if row else {}

    @staticmethod
    def update(**kwargs):
        """
        Update field apapun di system_state.
        Contoh: SystemState.update(auto_send=True)
        """
        fields = ", ".join(
            f"{k} = %s" for k in kwargs
        )
        values = list(kwargs.values())
        sql = f"""
            UPDATE system_state
            SET {fields}, updated_at = NOW()
            WHERE id = (SELECT id FROM system_state ORDER BY id DESC LIMIT 1)
        """
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, values)


# ══════════════════════════════════════════════════════════════
#  TRADE LOGS
# ══════════════════════════════════════════════════════════════
class TradeLogs:

    @staticmethod
    def insert(action: str, price: float, amount_btc: float,
               balance: float, reason: str, mode: str = "paper"):
        sql = """
            INSERT INTO trade_logs
                (timestamp, action, price, amount_btc,
                 balance, reason, mode)
            VALUES
                (NOW(), %s, %s, %s, %s, %s, %s)
        """
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (
                    action, price, amount_btc,
                    balance, reason, mode
                ))

    @staticmethod
    def get_latest(limit: int = 50) -> list[dict]:
        sql = """
            SELECT * FROM trade_logs
            ORDER BY timestamp DESC
            LIMIT %s
        """
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (limit,))
                rows = cur.fetchall()
        return [dict(r) for r in rows][::-1]


# ══════════════════════════════════════════════════════════════
#  Backtest
# ══════════════════════════════════════════════════════════════
class BacktestResults:

    @staticmethod
    def insert(
        initial_balance : float,
        final_total     : float,
        profit_loss     : float,
        roi_pct         : float,
        total_trades    : int,
        buy_count       : int,
        sell_count      : int,
        win_rate        : float,
        max_drawdown    : float,
        profit_factor   : float,
        data_from       : str,
        data_to         : str,
        data_points     : int,
        notes           : str = ""
    ) -> int:
        sql = """
            INSERT INTO backtest_results (
                run_at, initial_balance, final_total,
                profit_loss, roi_pct, total_trades,
                buy_count, sell_count,
                win_rate, max_drawdown, profit_factor,
                data_from, data_to, data_points, notes
            )
            VALUES (
                NOW(), %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s
            )
            RETURNING id
        """
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (
                    initial_balance, final_total,
                    profit_loss, roi_pct, total_trades,
                    buy_count, sell_count,
                    win_rate, max_drawdown, profit_factor,
                    data_from, data_to, data_points, notes
                ))
                return cur.fetchone()["id"]

    @staticmethod
    def get_all() -> list[dict]:
        sql = """
            SELECT * FROM backtest_results
            ORDER BY run_at DESC
        """
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql)
                rows = cur.fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    def get_latest() -> dict | None:
        sql = """
            SELECT * FROM backtest_results
            ORDER BY run_at DESC LIMIT 1
        """
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql)
                row = cur.fetchone()
        return dict(row) if row else None



class BacktestTrades:

    @staticmethod
    def bulk_insert(backtest_id: int, trades: list[dict]):
        if not trades:
            return
        sql = """
            INSERT INTO backtest_trades
                (backtest_id, timestamp, action, price, btc, balance, reason)
            VALUES
                (%s, %s, %s, %s, %s, %s, %s)
        """
        rows = [(
            backtest_id,
            t.get("timestamp"),
            t.get("action"),
            t.get("price"),
            t.get("btc"),
            t.get("balance"),
            t.get("reason", "")
        ) for t in trades]

        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.executemany(sql, rows)

    @staticmethod
    def get_by_backtest(backtest_id: int) -> list[dict]:
        sql = """
            SELECT * FROM backtest_trades
            WHERE backtest_id = %s
            ORDER BY timestamp ASC
        """
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (backtest_id,))
                rows = cur.fetchall()
        return [dict(r) for r in rows]



class BacktestEquity:

    @staticmethod
    def bulk_insert(backtest_id: int, equity_curve: list[dict]):
        if not equity_curve:
            return

        # Simpan setiap 10 titik saja biar tidak terlalu banyak
        sampled = equity_curve[::10]

        sql = """
            INSERT INTO backtest_equity
                (backtest_id, timestamp, total)
            VALUES
                (%s, %s, %s)
        """
        rows = [(
            backtest_id,
            e.get("timestamp"),
            e.get("total")
        ) for e in sampled]

        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.executemany(sql, rows)

    @staticmethod
    def get_by_backtest(backtest_id: int) -> list[dict]:
        sql = """
            SELECT * FROM backtest_equity
            WHERE backtest_id = %s
            ORDER BY timestamp ASC
        """
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (backtest_id,))
                rows = cur.fetchall()
        return [dict(r) for r in rows]


# ══════════════════════════════════════════════════════════════
#  PRICE DATA 1 MENIT
# ══════════════════════════════════════════════════════════════
class PriceData1m:

    @staticmethod
    def get_latest_timestamp():
        """
        Ambil timestamp terbaru.
        Selalu return dalam UTC timezone-aware.
        """
        sql = """
            SELECT timestamp AT TIME ZONE 'UTC' as timestamp
            FROM price_data_1m
            ORDER BY timestamp DESC
            LIMIT 1
        """
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql)
                row = cur.fetchone()

        if not row:
            return None

        ts = row["timestamp"]

        # Pastikan timezone-aware UTC
        if hasattr(ts, "tzinfo"):
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            else:
                ts = ts.astimezone(timezone.utc)

        return ts

    @staticmethod
    def get_latest_price() -> float:
        sql = """
            SELECT close
            FROM price_data_1m
            ORDER BY timestamp DESC
            LIMIT 1
        """
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql)
                row = cur.fetchone()
        return float(row["close"]) if row else 0.0

    @staticmethod
    def bulk_insert(rows: list[dict]):
        if not rows:
            return
        sql = """
            INSERT INTO price_data_1m
                (timestamp, open, high, low, close, volume)
            VALUES
                (%(timestamp)s, %(open)s, %(high)s,
                 %(low)s, %(close)s, %(volume)s)
            ON CONFLICT (timestamp) DO NOTHING
        """
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.executemany(sql, rows)
        log.debug(f"Inserted {len(rows)} rows ke price_data_1m")

    @staticmethod
    def get_latest(limit: int = 200) -> list[dict]:
        sql = """
            SELECT * FROM price_data_1m
            ORDER BY timestamp DESC
            LIMIT %s
        """
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (limit,))
                rows = cur.fetchall()
        return [dict(r) for r in rows][::-1]

    @staticmethod
    def get_count() -> int:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) as c FROM price_data_1m"
                )
                return cur.fetchone()["c"]