# app/data/fetcher.py

import time
import requests
import pandas as pd
from datetime import datetime, timezone, timedelta
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from app.utils.config import config
from app.utils.logger import get_logger
from app.database.models import PriceData, PriceData1m, ActualPrices

log = get_logger(__name__)

KRAKEN_BASE_URL = "https://api.kraken.com/0/public"
KRAKEN_PAIR     = "XBTUSD"

INTERVAL_1M  = 1
INTERVAL_5M  = 5
INTERVAL_15M = 15
INTERVAL_1H  = 60
INTERVAL_4H  = 240
INTERVAL_1D  = 1440


def _get_session() -> requests.Session:
    """
    Buat session dengan auto retry.
    Retry 3x dengan backoff jika gagal.
    """
    session = requests.Session()

    retry = Retry(
        total             = 3,        # max 3x retry
        backoff_factor    = 2,        # tunggu 2, 4, 8 detik
        status_forcelist  = [429, 500, 502, 503, 504],
        allowed_methods   = ["GET"]
    )

    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://",  adapter)

    return session


def _parse_ohlc(raw_data: list) -> pd.DataFrame:
    if not raw_data:
        return pd.DataFrame()

    df = pd.DataFrame(raw_data, columns=[
        "timestamp", "open", "high", "low",
        "close", "vwap", "volume", "count"
    ])

    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="s", utc=True)
    for col in ["open", "high", "low", "close", "vwap", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.sort_values("timestamp").reset_index(drop=True)

    # ── Buang candle future ───────────────────────────────────
    now_utc = pd.Timestamp.now(tz="UTC")
    before  = len(df)
    df      = df[df["timestamp"] <= now_utc].copy()
    after   = len(df)

    if before != after:
        log.warning(
            f"⚠️ Buang {before - after} candle future "
            f"(timestamp > sekarang)"
        )

    return df


def fetch_ohlc_kraken(
    interval : int  = INTERVAL_1H,
    since    : int  = None,
    timeout  : int  = 90        # ← naikkan default
) -> pd.DataFrame:
    url    = f"{KRAKEN_BASE_URL}/OHLC"
    params = {"pair": KRAKEN_PAIR, "interval": interval}

    if since is not None:
        params["since"] = since

    session = _get_session()

    try:
        resp = session.get(url, params=params, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()

        if data.get("error"):
            log.error(f"❌ Kraken API error: {data['error']}")
            return pd.DataFrame()

        result   = data.get("result", {})
        ohlc_key = [k for k in result.keys() if k != "last"]

        if not ohlc_key:
            return pd.DataFrame()

        df = _parse_ohlc(result[ohlc_key[0]])

        # ── Buang candle terakhir jika belum closed ───────────
        if not df.empty:
            now_utc     = pd.Timestamp.now(tz="UTC")
            last_candle = df.iloc[-1]["timestamp"]
            candle_end  = last_candle + pd.Timedelta(minutes=interval)

            if candle_end > now_utc:
                df = df.iloc[:-1].copy()
                log.debug(
                    f"Buang candle terakhir yg belum closed: "
                    f"{last_candle}"
                )

        log.debug(f"✅ Fetched {len(df)} candles (interval={interval}m)")
        return df

    except requests.exceptions.ConnectTimeout:
        log.warning(
            f"⚠️ Kraken timeout (interval={interval}m) "
            f"→ akan dicoba lagi di schedule berikutnya"
        )
        return pd.DataFrame()

    except requests.exceptions.ReadTimeout:
        log.warning(
            f"⚠️ Kraken read timeout (interval={interval}m) "
            f"→ akan dicoba lagi di schedule berikutnya"
        )
        return pd.DataFrame()

    except requests.exceptions.Timeout:
        log.warning(
            f"⚠️ Kraken timeout (interval={interval}m) "
            f"→ akan dicoba lagi di schedule berikutnya"
        )
        return pd.DataFrame()

    except requests.exceptions.ConnectionError as e:
        log.warning(f"⚠️ Kraken connection error: {e}")
        return pd.DataFrame()

    except requests.exceptions.RequestException as e:
        log.warning(f"⚠️ Kraken request error: {e}")
        return pd.DataFrame()

    except Exception as e:
        log.error(f"❌ fetch_ohlc_kraken unexpected error: {e}")
        return pd.DataFrame()

    finally:
        session.close()



def fetch_current_price() -> float:
    """Ambil harga BTC terkini dari Kraken Ticker."""
    url     = f"{KRAKEN_BASE_URL}/Ticker"
    params  = {"pair": KRAKEN_PAIR}
    session = _get_session()

    try:
        resp = session.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        if data.get("error"):
            return 0.0

        result = data.get("result", {})
        key    = list(result.keys())[0]
        price  = float(result[key]["c"][0])

        log.debug(f"Current BTC: ${price:,.2f}")
        return price

    except requests.exceptions.Timeout:
        log.warning("⚠️ Ticker timeout, skip")
        return 0.0

    except Exception as e:
        log.warning(f"⚠️ fetch_current_price: {e}")
        return 0.0

    finally:
        session.close()


# def fetch_and_store_1h() -> pd.DataFrame:
#     """
#     Fetch candle 1H incremental → price_data.
#     Hanya ambil candle BARU setelah timestamp terakhir di DB.
#     """
#     log.info("📥 Fetch OHLC 1H...")

#     # Cek timestamp terakhir di DB
#     last_ts = PriceData.get_latest_timestamp()
#     since   = None

#     if last_ts is not None:
#         # Pastikan UTC aware
#         if hasattr(last_ts, "tzinfo"):
#             if last_ts.tzinfo is None:
#                 last_ts = last_ts.replace(tzinfo=timezone.utc)
        
#         since = int(last_ts.timestamp())
        
#         # Cek apakah candle berikutnya sudah closed
#         # Candle 1H closed setelah 1 jam penuh
#         next_candle_ts = last_ts + timedelta(hours=1)
#         now_utc        = datetime.now(timezone.utc)
        
#         if now_utc < next_candle_ts:
#             # Candle berikutnya belum closed, tidak perlu fetch
#             remaining = next_candle_ts - now_utc
#             mins      = int(remaining.total_seconds() / 60)
#             log.info(
#                 f"   ⏳ Candle berikutnya belum closed "
#                 f"(tunggu {mins} menit lagi)"
#             )
#             return pd.DataFrame()
        
#         log.info(
#             f"   Incremental sejak: "
#             f"{last_ts.strftime('%Y-%m-%d %H:%M')} UTC"
#         )
#     else:
#         log.info("   Fetch pertama (720 candle terakhir)...")

#     # Fetch dari Kraken
#     df = fetch_ohlc_kraken(interval=INTERVAL_1H, since=since)

#     if df.empty:
#         log.warning("⚠️ Tidak ada data 1H dari Kraken")
#         return df

#     # Pastikan timestamp UTC aware
#     if df["timestamp"].dt.tz is None:
#         df["timestamp"] = df["timestamp"].dt.tz_localize("UTC")

#     # Filter: hanya candle SETELAH last_ts (strict >)
#     if since is not None:
#         cutoff = pd.Timestamp(since, unit="s", tz="UTC")
#         df     = df[df["timestamp"] > cutoff].copy()

#     if df.empty:
#         log.info("   Tidak ada candle 1H baru (sudah up-to-date)")
#         return pd.DataFrame()

#     # Simpan ke DB
#     rows = df[[
#         "timestamp", "open", "high", "low", "close", "volume"
#     ]].to_dict(orient="records")

#     PriceData.bulk_insert(rows)

#     log.info(
#         f"✅ Stored {len(rows)} candle 1H baru → price_data\n"
#         f"   Range: "
#         f"{df['timestamp'].iloc[0].strftime('%Y-%m-%d %H:%M')} → "
#         f"{df['timestamp'].iloc[-1].strftime('%Y-%m-%d %H:%M')} UTC"
#     )

#     return df


def fetch_and_store_1h() -> pd.DataFrame:
    log.info("📥 Fetch OHLC 1H...")

    last_ts = PriceData.get_latest_timestamp()
    since   = None

    if last_ts is not None:
        if hasattr(last_ts, "tzinfo"):
            if last_ts.tzinfo is None:
                last_ts = last_ts.replace(tzinfo=timezone.utc)

        next_candle_ts = last_ts + timedelta(hours=1)
        now_utc        = datetime.now(timezone.utc)

        if now_utc < next_candle_ts:
            remaining = next_candle_ts - now_utc
            mins      = int(remaining.total_seconds() / 60)
            log.info(
                f"   ⏳ Candle berikutnya belum closed "
                f"(tunggu {mins} menit lagi)"
            )
            return pd.DataFrame()

        gap_hours = int((now_utc - last_ts).total_seconds() / 3600)
        log.info(
            f"   Incremental sejak: "
            f"{last_ts.strftime('%Y-%m-%d %H:%M')} UTC "
            f"(gap: ~{gap_hours} jam)"
        )

        # ← Mundurkan since 1 jam agar Kraken include candle terbaru
        since = int((last_ts - timedelta(hours=1)).timestamp())
    else:
        log.info("   Fetch pertama (720 candle terakhir)...")

    # Retry 3x
    df = pd.DataFrame()
    for attempt in range(1, 4):
        log.info(f"   Attempt {attempt}/3...")
        df = fetch_ohlc_kraken(
            interval = INTERVAL_1H,
            since    = since,
            timeout  = 90
        )
        if not df.empty:
            break
        if attempt < 3:
            log.warning(
                f"   ⚠️ Attempt {attempt} gagal, tunggu 15 detik..."
            )
            time.sleep(15)

    if df.empty:
        log.warning("⚠️ Tidak ada data 1H dari Kraken setelah 3x retry")
        return df

    if df["timestamp"].dt.tz is None:
        df["timestamp"] = df["timestamp"].dt.tz_localize("UTC")

    # Filter strict > last_ts (bukan since yang dimundurkan)
    if last_ts is not None:
        df = df[df["timestamp"] > last_ts].copy()

    if df.empty:
        log.info("   Tidak ada candle 1H baru (sudah up-to-date)")
        return pd.DataFrame()

    rows = df[[
        "timestamp", "open", "high", "low", "close", "volume"
    ]].to_dict(orient="records")

    PriceData.bulk_insert(rows)

    log.info(
        f"✅ Stored {len(rows)} candle 1H baru → price_data\n"
        f"   Range: "
        f"{df['timestamp'].iloc[0].strftime('%Y-%m-%d %H:%M')} → "
        f"{df['timestamp'].iloc[-1].strftime('%Y-%m-%d %H:%M')} UTC"
    )

    return df


def fetch_and_store_1m_ohlc() -> pd.DataFrame:
    """
    Fetch OHLC 1M incremental dari Kraken.
    Hanya ambil candle baru sejak timestamp terakhir di DB.
    """
    from app.database.models import PriceData1m, ActualPrices
    from datetime import datetime, timezone

    # ── Cek timestamp terakhir di DB ─────────────────────────
    last_ts = PriceData1m.get_latest_timestamp()
    since   = None

    if last_ts is not None:
        # Pastikan timezone-aware
        if hasattr(last_ts, "tzinfo") and last_ts.tzinfo is not None:
            # Sudah ada timezone, konversi ke UTC
            since = int(last_ts.astimezone(timezone.utc).timestamp())
        elif hasattr(last_ts, "timestamp"):
            # Naive datetime, asumsikan UTC
            since = int(last_ts.timestamp())
        else:
            since = int(pd.Timestamp(last_ts).timestamp())

        last_ts_utc = datetime.fromtimestamp(since, tz=timezone.utc)
        log.info(f"📥 Fetch 1M incremental sejak: {last_ts_utc}")
    else:
        log.info("📥 Fetch 1M pertama kali (720 candle terakhir)...")

    # ── Fetch dari Kraken ─────────────────────────────────────
    df = fetch_ohlc_kraken(interval=INTERVAL_1M, since=since)

    if df.empty:
        log.debug("Tidak ada candle 1M baru dari Kraken")
        return df

    # ── Filter: hanya candle setelah last_ts ─────────────────
    if since is not None and not df.empty:
        cutoff = pd.Timestamp(since, unit="s", tz="UTC")

        # Pastikan df timestamp timezone-aware
        if df["timestamp"].dt.tz is None:
            df["timestamp"] = df["timestamp"].dt.tz_localize("UTC")

        df = df[df["timestamp"] > cutoff].copy()

        if df.empty:
            log.debug("Semua candle sudah ada di DB, tidak ada yang baru")
            return df

    # ── Simpan ke DB ──────────────────────────────────────────
    rows = df[[
        "timestamp", "open", "high", "low", "close", "volume"
    ]].to_dict(orient="records")

    PriceData1m.bulk_insert(rows)
    log.info(f"✅ Stored {len(rows)} candles 1M baru → price_data_1m")

    # ── Update actual_prices ──────────────────────────────────
    latest_close = float(df.iloc[-1]["close"])
    latest_ts    = df.iloc[-1]["timestamp"]
    if latest_close > 0:
        ActualPrices.insert(latest_ts, latest_close)
        log.debug(f"💰 Harga terbaru: ${latest_close:,.2f}")

    return df


def fetch_current_price_from_db() -> float:
    """
    Ambil harga dari DB lokal (price_data_1m).
    Lebih cepat & tidak butuh internet.
    Fallback ke API jika DB kosong.
    """
    price = PriceData1m.get_latest_price()
    if price > 0:
        log.debug(f"💰 Harga dari DB: ${price:,.2f}")
        return price

    log.debug("DB kosong, fallback ke Kraken API...")
    return fetch_current_price()


def fetch_historical_kraken(
    interval   : int = INTERVAL_1H,
    total_days : int = 365
) -> pd.DataFrame:
    """Ambil data historis dengan multiple request."""
    log.info(
        f"📥 Fetch {total_days} hari historis "
        f"(interval={interval}m)..."
    )

    now        = datetime.now(timezone.utc)
    start_time = now - timedelta(days=total_days)
    all_dfs    = []

    candles_per_req    = 719
    seconds_per_candle = interval * 60
    seconds_per_req    = candles_per_req * seconds_per_candle

    current_since = int(start_time.timestamp())
    end_ts        = int(now.timestamp())
    batch_num     = 0
    total_batches = (end_ts - current_since) // seconds_per_req + 1
    fail_count    = 0
    max_fails     = 5   # toleransi max 5 kali gagal berturut-turut

    while current_since < end_ts:
        batch_num += 1
        since_dt  = datetime.fromtimestamp(
            current_since, tz=timezone.utc
        )

        log.info(
            f"   Batch {batch_num}/{total_batches} → "
            f"{since_dt.strftime('%Y-%m-%d %H:%M')}"
        )

        df = fetch_ohlc_kraken(
            interval = interval,
            since    = current_since,
            timeout  = 30
        )

        if df.empty:
            fail_count += 1
            log.warning(
                f"   ⚠️ Batch {batch_num} gagal "
                f"({fail_count}/{max_fails})"
            )

            if fail_count >= max_fails:
                log.error("❌ Terlalu banyak gagal, berhenti")
                break

            # Tunggu lebih lama sebelum retry
            log.info(f"   Tunggu 10 detik...")
            time.sleep(10)
            continue

        fail_count = 0  # reset counter jika berhasil
        all_dfs.append(df)

        last_ts       = int(df["timestamp"].iloc[-1].timestamp())
        current_since = last_ts + 1

        if current_since >= end_ts:
            break

        if len(df) < candles_per_req - 10:
            log.info("   ✅ Sudah sampai data terbaru")
            break

        time.sleep(1.5)  # rate limit

    if not all_dfs:
        log.error("❌ Tidak ada data historis yang berhasil diambil")
        return pd.DataFrame()

    combined = (
        pd.concat(all_dfs, ignore_index=True)
        .drop_duplicates(subset="timestamp")
        .sort_values("timestamp")
        .reset_index(drop=True)
    )

    log.info(f"✅ Total historis: {len(combined)} candles")
    return combined


def fetch_and_store_historical(
    total_days : int = 365,
    interval   : int = INTERVAL_1H
) -> pd.DataFrame:
    """Fetch data historis dan simpan ke DB."""
    df = fetch_historical_kraken(
        interval   = interval,
        total_days = total_days
    )

    if df.empty:
        return df

    rows = df[[
        "timestamp", "open", "high", "low", "close", "volume"
    ]].to_dict(orient="records")

    PriceData.bulk_insert(rows)
    log.info(f"✅ Stored {len(rows)} historical rows → price_data")
    return df