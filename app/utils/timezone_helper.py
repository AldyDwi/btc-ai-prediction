# app/utils/timezone_helper.py

from datetime import datetime, timezone, timedelta
import pandas as pd

WIB        = timezone(timedelta(hours=7))
WIB_OFFSET = timedelta(hours=7)
WIB_PYTZ   = "Asia/Jakarta"


def now_wib() -> datetime:
    """Waktu sekarang dalam WIB."""
    return datetime.now(WIB)


def to_wib(dt) -> datetime | None:
    """Konversi datetime/timestamp/string ke WIB."""
    if dt is None:
        return None
    try:
        # String → Timestamp
        if isinstance(dt, str):
            dt = pd.Timestamp(dt)

        # pd.Timestamp → datetime
        if isinstance(dt, pd.Timestamp):
            dt = dt.to_pydatetime()

        # datetime tanpa timezone → asumsikan UTC
        if isinstance(dt, datetime):
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(WIB)

    except Exception:
        pass
    return None


def format_wib(dt, fmt: str = "%Y-%m-%d %H:%M WIB") -> str:
    """
    Format datetime ke string WIB.
    Input bisa: datetime, string, pd.Timestamp
    """
    if dt is None:
        return "-"
    converted = to_wib(dt)
    if converted is None:
        return str(dt)[:16]   # fallback: tampil apa adanya
    return converted.strftime(fmt)


def pd_to_wib(series: pd.Series) -> pd.Series:
    """
    Konversi kolom timestamp pandas ke WIB.
    Input series harus bertipe datetime.
    """
    if series.empty:
        return series

    # Lokalisasi ke UTC jika belum ada timezone
    if series.dt.tz is None:
        series = series.dt.tz_localize("UTC")

    # Konversi ke WIB
    return series.dt.tz_convert(WIB_PYTZ)