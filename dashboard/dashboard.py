# dashboard/dashboard.py

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytz
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime, timezone, timedelta

# ── Auto refresh library ──────────────────────────────────────
from streamlit_autorefresh import st_autorefresh

from app.database.db import init_db
from app.database.models import (
    Predictions, ActualPrices, ModelLogs,
    SystemState, TradeLogs, BacktestResults,
    BacktestTrades, BacktestEquity,
    PriceData, PriceData1m
)
from app.utils.config import config

# ── Page Config ───────────────────────────────────────────────
st.set_page_config(
    page_title = "BTC AI Dashboard",
    page_icon  = "₿",
    layout     = "wide"
)

# ── Init DB ───────────────────────────────────────────────────
try:
    init_db()
except Exception as e:
    st.error(f"DB Error: {e}")

# ── CSS ───────────────────────────────────────────────────────
st.markdown("""
<style>
    .stButton > button {
        width: 100%;
        border-radius: 8px;
        font-weight: bold;
    }
</style>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════
#  HELPER FUNCTIONS
# ══════════════════════════════════════════════════════════════
def run_prediction_now() -> dict | None:
    try:
        from app.services.prediction_service import run_prediction_cycle
        return run_prediction_cycle()
    except Exception as e:
        st.error(f"Prediksi error: {e}")
        return None


def run_backtest_now(sl: float, tp: float, cd: int) -> dict | None:
    try:
        from app.services.backtesting import run_backtest
        return run_backtest(
            stop_loss_pct   = -abs(sl / 100),
            take_profit_pct = tp / 100,
            cooldown_hours  = cd,
            notes           = f"Dashboard: SL{sl}% TP{tp}% CD{cd}h"
        )
    except Exception as e:
        st.error(f"Backtest error: {e}")
        return None


def get_latest_price_from_1m() -> tuple[float, float, str]:
    """
    Ambil harga terbaru dari price_data_1m.
    Return: (harga_sekarang, harga_sebelumnya, timestamp_str)
    """
    try:
        rows = PriceData1m.get_latest(limit=2)
        if rows and len(rows) >= 2:
            return (
                float(rows[-1]["close"]),
                float(rows[-2]["close"]),
                str(rows[-1]["timestamp"])[:16]
            )
        elif rows:
            p = float(rows[-1]["close"])
            return p, p, str(rows[-1]["timestamp"])[:16]
    except Exception:
        pass
    return 0.0, 0.0, "-"


# ══════════════════════════════════════════════════════════════
#  SIDEBAR
# ══════════════════════════════════════════════════════════════
with st.sidebar:
    st.title("Controls")

    # ── Auto Refresh ──────────────────────────────────────────
    st.markdown("### Auto Refresh")
    auto_refresh = st.checkbox("Aktifkan Auto Refresh", value=False)
    refresh_interval = st.select_slider(
        "Interval (detik):",
        options = [30, 60, 120, 300],
        value   = 60,
        disabled = not auto_refresh
    )

    # ✅ FIX: st_autorefresh tidak membekukan dashboard
    # Hanya aktif jika checkbox dicentang
    if auto_refresh:
        count = st_autorefresh(
            interval = refresh_interval * 1000,  # milidetik
            limit    = None,                     # refresh terus
            key      = "auto_refresh_counter"
        )
        st.caption(f"Refresh ke-{count} | interval {refresh_interval}s")

    if st.button("Refresh Sekarang", use_container_width=True):
        st.rerun()

    st.divider()

    # ── System State ──────────────────────────────────────────
    state = SystemState.get()

    # ── Toggle Auto Prediksi ──────────────────────────────────
    st.markdown("### Auto Prediksi")
    auto_send_now = state.get("auto_send", False)
    st.caption(f"Status: {'🟢 AKTIF' if auto_send_now else '🔴 MATI'}")

    col_ap1, col_ap2 = st.columns(2)
    with col_ap1:
        if st.button("✅ ON", use_container_width=True,
                     type="secondary" if auto_send_now else "primary"):
            SystemState.update(auto_send=True)
            st.rerun()
    with col_ap2:
        if st.button("⛔ OFF", use_container_width=True,
                     type="primary" if auto_send_now else "secondary"):
            SystemState.update(auto_send=False)
            st.rerun()

    st.divider()

    # ── Toggle Paper Trading ──────────────────────────────────
    st.markdown("### Paper Trading")
    trading_on_now = state.get("trading_on", False)
    st.caption(
        f"Status: {'🟢 AKTIF' if trading_on_now else '🔴 MATI'}"
        f" | SL -2% | TP +8% | CD 72h"
    )

    col_tr1, col_tr2 = st.columns(2)
    with col_tr1:
        if st.button("✅ ON", use_container_width=True,
                     key="tr_on",
                     type="secondary" if trading_on_now else "primary"):
            SystemState.update(trading_on=True, paper_trade=True)
            st.rerun()
    with col_tr2:
        if st.button("⛔ OFF", use_container_width=True,
                     key="tr_off",
                     type="primary" if trading_on_now else "secondary"):
            SystemState.update(trading_on=False)
            st.rerun()

    st.divider()

    # ── Manual Prediksi ───────────────────────────────────────
    st.markdown("### Prediksi Manual")
    if st.button("▶ Jalankan Prediksi",
                 use_container_width=True, type="primary"):
        with st.spinner("Menjalankan prediksi..."):
            result = run_prediction_now()
        if result:
            st.success(
                f"✅ Selesai!\n"
                f"Avg: ${result['pred_avg']:,.2f}"
            )
            st.rerun()
        else:
            st.error("❌ Gagal")

    st.divider()

    # ── Backtest Manual ───────────────────────────────────────
    st.markdown("### Backtest Manual")
    sl_input = st.number_input(
        "Stop Loss (%)", min_value=0.5,
        max_value=10.0, value=2.0, step=0.5
    )
    tp_input = st.number_input(
        "Take Profit (%)", min_value=1.0,
        max_value=30.0, value=8.0, step=0.5
    )
    cd_input = st.number_input(
        "Cooldown (jam)", min_value=1,
        max_value=168, value=72, step=12
    )

    if st.button("▶ Jalankan Backtest",
                 use_container_width=True, type="primary"):
        with st.spinner("Menjalankan backtest..."):
            bt_result = run_backtest_now(sl_input, tp_input, cd_input)
        if bt_result:
            roi = bt_result.get("roi_pct", 0)
            st.success(
                f"{'📈' if roi > 0 else '📉'} Selesai!\n"
                f"ROI: {roi:+.2f}%"
            )
            st.rerun()
        else:
            st.error("❌ Gagal")

    st.divider()
    st.caption("BTC AI System v2.0")


# ══════════════════════════════════════════════════════════════
#  HEADER
# ══════════════════════════════════════════════════════════════
st.title("₿ BTC AI Prediction Dashboard")
st.caption(
    f"Last refresh: "
    f"{datetime.now(timezone.utc).astimezone(pytz.timezone('Asia/Jakarta')).strftime('%Y-%m-%d %H:%M:%S')} WIB"
    + (f" | Auto refresh: {refresh_interval}s" if auto_refresh else "")
)


# ══════════════════════════════════════════════════════════════
#  ROW 1: Status Cards
# ══════════════════════════════════════════════════════════════
state     = SystemState.get()
model_log = ModelLogs.get_latest()

col1, col2, col3, col4 = st.columns(4)

with col1:
    st.metric(
        "Auto Prediksi",
        "🟢 ON" if state.get("auto_send") else "🔴 OFF"
    )
with col2:
    st.metric(
        "Paper Trading",
        "🟢 ON" if state.get("trading_on") else "🔴 OFF"
    )
with col3:
    if model_log:
        st.metric(
            "Model Loss",
            f"{model_log.get('loss', 0):.6f}",
            delta=f"val: {model_log.get('val_loss', 0):.6f}"
        )
    else:
        st.metric("Model Loss", "No Model")
with col4:
    if model_log:
        st.metric(
            "Last Trained",
            str(model_log.get("trained_at", ""))[:10],
            delta=f"{model_log.get('epochs', 0)} epochs"
        )
    else:
        st.metric("Last Trained", "Never")

st.divider()


# ══════════════════════════════════════════════════════════════
#  ROW 2: Harga BTC Real-time (dari price_data_1m)
# ══════════════════════════════════════════════════════════════
price_now, price_prev, price_ts = get_latest_price_from_1m()
preds   = Predictions.get_latest(limit=50)
actuals = ActualPrices.get_latest(limit=100)

if price_now > 0:
    price_change = price_now - price_prev
    price_pct    = (price_change / price_prev * 100) if price_prev > 0 else 0

    col_p1, col_p2, col_p3, col_p4 = st.columns(4)

    with col_p1:
        st.metric(
            "Harga BTC (Real-time)",
            f"${price_now:,.2f}",
            delta=f"{price_change:+,.2f} ({price_pct:+.2f}%)"
        )
        st.caption(f"Update: {price_ts} WIB")

    with col_p2:
        if preds:
            last_pred = preds[-1]
            pred_diff = float(last_pred["pred_avg"]) - price_now
            pred_pct  = pred_diff / price_now * 100
            st.metric(
                "Prediksi 1 Jam",
                f"${float(last_pred['pred_avg']):,.2f}",
                delta=f"{pred_diff:+,.2f} ({pred_pct:+.2f}%)"
            )
        else:
            st.metric("Prediksi 1 Jam", "Belum ada")

    with col_p3:
        # Data stats
        try:
            count_1m = PriceData1m.get_count()
            last_1m  = PriceData1m.get_latest_timestamp()
            st.metric(
                "Data 1 Menit",
                f"{count_1m:,} candle",
                delta=f"Terakhir: {str(last_1m)[:16]}"
            )
        except Exception:
            st.metric("Data 1 Menit", "-")

    with col_p4:
        st.metric(
            "Total Prediksi",
            f"{len(preds)} kali",
            delta=f"Aktual: {len(actuals)} data"
        )

else:
    st.warning(
        "⚠️ Data harga belum tersedia. "
        "Pastikan main.py berjalan."
    )

st.divider()


# ══════════════════════════════════════════════════════════════
#  ROW 3: Chart Prediksi vs Harga Aktual
# ══════════════════════════════════════════════════════════════
st.subheader("Prediksi vs Harga Aktual")

col_range, col_res = st.columns([3, 1])
with col_range:
    time_range = st.select_slider(
        "Rentang Waktu:",
        options = ["1 Jam", "3 Jam", "6 Jam", "12 Jam", "24 Jam", "Semua"],
        value   = "6 Jam"
    )
with col_res:
    resolution = st.selectbox(
        "Resolusi:",
        ["Per Menit", "Per 5 Menit", "Per 15 Menit", "Per Jam"],
        index = 1
    )

now_utc   = datetime.now(timezone.utc)
range_map = {
    "1 Jam" : timedelta(hours=1),
    "3 Jam" : timedelta(hours=3),
    "6 Jam" : timedelta(hours=6),
    "12 Jam": timedelta(hours=12),
    "24 Jam": timedelta(hours=24),
    "Semua" : timedelta(days=365),
}
resample_map = {
    "Per Menit"    : "1min",
    "Per 5 Menit"  : "5min",
    "Per 15 Menit" : "15min",
    "Per Jam"      : "1h",
}

cutoff        = now_utc - range_map[time_range]
resample_freq = resample_map[resolution]

# ── Hitung limit sesuai rentang waktu ────────────────────────
# Ambil sedikit lebih banyak dari yang dibutuhkan (buffer 10%)
limit_map = {
    "1 Jam" : int(60   * 1.1),    # 66 candle
    "3 Jam" : int(180  * 1.1),    # 198 candle
    "6 Jam" : int(360  * 1.1),    # 396 candle
    "12 Jam": int(720  * 1.1),    # 792 candle
    "24 Jam": int(1440 * 1.1),    # 1584 candle
    "Semua" : 10000,               # semua data
}
fetch_limit = limit_map[time_range]

# ── Ambil data dari price_data_1m ─────────────────────────────
try:
    rows_1m       = PriceData1m.get_latest(limit=fetch_limit)
    price_df_main = pd.DataFrame(rows_1m) if rows_1m else pd.DataFrame()

    if not price_df_main.empty:
        price_df_main["timestamp"] = pd.to_datetime(
            price_df_main["timestamp"], utc=True
        ).dt.tz_convert("Asia/Jakarta")  # ← konversi UTC → WIB
        price_df_main = price_df_main.sort_values("timestamp")
except Exception as e:
    price_df_main = pd.DataFrame()
    st.warning(f"Gagal ambil data 1M: {e}")

# ── Filter berdasarkan cutoff ─────────────────────────────────
if not price_df_main.empty:
    filtered_price = price_df_main[
        price_df_main["timestamp"] >= cutoff
    ].copy()

    # Resample sesuai resolusi
    if not filtered_price.empty:
        filtered_price = (
            filtered_price
            .set_index("timestamp")[["close"]]
            .resample(resample_freq)
            .agg(
                close  = ("close", "last"),   # harga penutupan
                high   = ("close", "max"),    # tertinggi
                low    = ("close", "min"),    # terendah
            )
            .dropna()
            .reset_index()
        )
    else:
        filtered_price = pd.DataFrame()
else:
    filtered_price = pd.DataFrame()

# ── Filter prediksi ───────────────────────────────────────────
preds_all = Predictions.get_latest(limit=200)
if preds_all:
    pred_df = pd.DataFrame([{
        "time"    : pd.to_datetime(p["created_at"], utc=True),
        "pred_avg": float(p["pred_avg"]),
        "pred_min": float(p["pred_min"]),
        "pred_max": float(p["pred_max"])
    } for p in preds_all]).sort_values("time")

    pred_df = pred_df[pred_df["time"] >= cutoff]
else:
    pred_df = pd.DataFrame()

# ── Plot ──────────────────────────────────────────────────────
if not filtered_price.empty or not pred_df.empty:
    fig = go.Figure()

    # [1] Range prediksi (area min-max)
    if not pred_df.empty:
        avg_price = pred_df["pred_avg"].mean()
        avg_range = (pred_df["pred_max"] - pred_df["pred_min"]).mean()
        range_pct = avg_range / avg_price * 100 if avg_price > 0 else 0

        if range_pct < 20:
            fig.add_trace(go.Scatter(
                x         = pd.concat([
                    pred_df["time"],
                    pred_df["time"][::-1]
                ]),
                y         = pd.concat([
                    pred_df["pred_max"],
                    pred_df["pred_min"][::-1]
                ]),
                fill      = "toself",
                fillcolor = "rgba(247,127,0,0.15)",
                line      = dict(color="rgba(255,255,255,0)"),
                name      = "Range Prediksi",
                hoverinfo = "skip"
            ))

    # [2] Harga aktual dari price_data_1m
    if not filtered_price.empty:
        fig.add_trace(go.Scatter(
            x    = filtered_price["timestamp"],
            y    = filtered_price["close"],
            name = f"Harga Aktual ({resolution})",
            line = dict(color="#00b4d8", width=2),
            mode = "lines",
            hovertemplate = (
                "<b>%{x}</b><br>"
                "Harga: $%{y:,.2f}<br>"
                "<extra></extra>"
            )
        ))

    # [3] Prediksi avg
    if not pred_df.empty:
        fig.add_trace(go.Scatter(
            x      = pred_df["time"],
            y      = pred_df["pred_avg"],
            name   = "Prediksi Avg",
            line   = dict(color="#f77f00", width=2, dash="dash"),
            mode   = "lines+markers",
            marker = dict(size=8, symbol="diamond"),
            hovertemplate = (
                "<b>%{x}</b><br>"
                "Prediksi: $%{y:,.2f}<br>"
                "<extra></extra>"
            )
        ))

    # [4] Garis harga sekarang
    if price_now > 0:
        fig.add_hline(
            y               = price_now,
            line_dash       = "dot",
            line_color      = "#a6e3a1",
            opacity         = 0.5,
            annotation_text = f"Sekarang: ${price_now:,.2f}",
            annotation_position = "bottom right"
        )

    fig.update_layout(
        template    = "plotly_dark",
        height      = 450,
        xaxis_title = "Waktu (WIB)",
        yaxis_title = "Harga BTC (USD)",
        legend      = dict(
            orientation = "h",
            yanchor     = "bottom",
            y           = 1.02,
            xanchor     = "right",
            x           = 1
        ),
        hovermode = "x unified",
        xaxis     = dict(
            rangeslider = dict(visible=True, thickness=0.05),
            type        = "date"
        ),
        margin = dict(t=60)
    )
    st.plotly_chart(fig, use_container_width=True)

    # ── Info singkat ──────────────────────────────────────────
    with st.expander("Debug Info"):
        c1, c2, c3 = st.columns(3)
        c1.metric(
            "Data Harga",
            f"{len(filtered_price)} titik",
            delta=f"Resolusi: {resolution}"
        )
        c2.metric(
            "Data Prediksi",
            f"{len(pred_df)} titik",
            delta=f"Range: {time_range}"
        )
        c3.metric(
            "Data Diambil",
            f"{len(price_df_main)} candle",
            delta=f"Limit: {fetch_limit}"
        )
        if not filtered_price.empty:
            st.write(
                f"Harga: `{filtered_price['timestamp'].iloc[0]}` → "
                f"`{filtered_price['timestamp'].iloc[-1]}`"
            )
        if not pred_df.empty:
            st.write(
                f"Prediksi: `{pred_df['time'].iloc[0]}` → "
                f"`{pred_df['time'].iloc[-1]}`"
            )

else:
    st.info(
        "Belum ada data.\n\n"
        "Pastikan `main.py` berjalan dan `price_data_1m` terisi."
    )

st.divider()


# ══════════════════════════════════════════════════════════════
#  ROW 4: Detail Prediksi vs Harga Real Per Menit
# ══════════════════════════════════════════════════════════════
st.subheader("Detail Prediksi Terakhir vs Harga Real (Per Menit)")

if preds:
    last_pred   = preds[-1]
    pred_prices = last_pred.get("pred_prices", [])
    pred_time   = pd.to_datetime(last_pred["created_at"])

    if pred_prices:
        n_minutes     = len(pred_prices)
        current_price = price_now if price_now > 0 else pred_prices[0]

        pred_times = [
            pred_time + timedelta(minutes=i)
            for i in range(n_minutes)
        ]

        # Ambil data 1M sekitar waktu prediksi
        try:
            rows_detail = PriceData1m.get_latest(limit=180)
            price_df    = pd.DataFrame(rows_detail) \
                          if rows_detail else pd.DataFrame()
            if not price_df.empty:
                price_df["timestamp"] = pd.to_datetime(
                    price_df["timestamp"], utc=True
                )
                price_df = price_df.sort_values("timestamp")
                cutoff_detail = pred_time - timedelta(minutes=30) \
                    if pred_time.tzinfo is None \
                    else pred_time.replace(tzinfo=timezone.utc) \
                         - timedelta(minutes=30)
                price_df = price_df[
                    price_df["timestamp"] >= cutoff_detail
                ]
        except Exception:
            price_df = pd.DataFrame()

        view_mode = st.radio(
            "Tampilkan per:",
            ["Per Menit", "Per Jam"],
            horizontal=True,
            key="detail_view_mode"
        )

        pred_minute_df = pd.DataFrame({
            "timestamp": pred_times,
            "prediksi" : pred_prices
        })

        price_hourly = pd.DataFrame()
        if view_mode == "Per Jam":
            pred_minute_df = (
                pred_minute_df
                .set_index("timestamp")
                .resample("1h").mean()
                .reset_index()
            )
            if not price_df.empty:
                price_hourly = (
                    price_df
                    .set_index("timestamp")[["close"]]
                    .resample("1h").mean()
                    .reset_index()
                )

        fig_detail = go.Figure()

        if not price_df.empty and view_mode == "Per Menit":
            fig_detail.add_trace(go.Scatter(
                x    = price_df["timestamp"],
                y    = price_df["close"],
                name = "Harga Aktual (per menit)",
                line = dict(color="#00b4d8", width=2),
                mode = "lines"
            ))
        elif view_mode == "Per Jam" and not price_hourly.empty:
            fig_detail.add_trace(go.Scatter(
                x      = price_hourly["timestamp"],
                y      = price_hourly["close"],
                name   = "Harga Aktual (per jam)",
                line   = dict(color="#00b4d8", width=2),
                mode   = "lines+markers",
                marker = dict(size=8)
            ))

        fig_detail.add_trace(go.Scatter(
            x      = pred_minute_df["timestamp"],
            y      = pred_minute_df["prediksi"],
            name   = f"Prediksi ({view_mode})",
            line   = dict(color="#f77f00", width=2, dash="dash"),
            mode   = "lines+markers",
            marker = dict(size=5 if view_mode == "Per Menit" else 10)
        ))

        fig_detail.add_hline(
            y               = current_price,
            line_dash       = "dot",
            line_color      = "#a6e3a1",
            opacity         = 0.7,
            annotation_text = f"Sekarang: ${current_price:,.2f}",
            annotation_position = "bottom right"
        )

        pred_time_str = pred_time.strftime("%Y-%m-%d %H:%M:%S")
        fig_detail.add_shape(
            type="line",
            x0=pred_time_str, x1=pred_time_str,
            y0=0, y1=1, xref="x", yref="paper",
            line=dict(color="#cba6f7", width=1.5, dash="dash")
        )
        fig_detail.add_annotation(
            x=pred_time_str, y=1.02,
            xref="x", yref="paper",
            text="⬇ Prediksi dibuat",
            showarrow=False,
            font=dict(color="#cba6f7", size=11),
            xanchor="left"
        )

        fig_detail.update_layout(
            template    = "plotly_dark",
            height      = 420,
            xaxis_title = "Waktu (WIB)",
            yaxis_title = "Harga BTC (USD)",
            legend      = dict(
                orientation="h", yanchor="bottom",
                y=1.02, xanchor="right", x=1
            ),
            hovermode = "x unified",
            xaxis     = dict(
                rangeslider=dict(visible=True),
                type="date"
            )
        )
        st.plotly_chart(fig_detail, use_container_width=True)

        col_a, col_b, col_c, col_d = st.columns(4)
        col_a.metric("Menit 1",  f"${pred_prices[0]:,.2f}",
            delta=f"{(pred_prices[0]-current_price)/current_price*100:+.2f}%")
        col_b.metric("Menit 15",
            f"${pred_prices[14]:,.2f}" if len(pred_prices)>14 else "-",
            delta=f"{(pred_prices[14]-current_price)/current_price*100:+.2f}%"
                  if len(pred_prices)>14 else None)
        col_c.metric("Menit 30",
            f"${pred_prices[29]:,.2f}" if len(pred_prices)>29 else "-",
            delta=f"{(pred_prices[29]-current_price)/current_price*100:+.2f}%"
                  if len(pred_prices)>29 else None)
        col_d.metric("Menit 60", f"${pred_prices[-1]:,.2f}",
            delta=f"{(pred_prices[-1]-current_price)/current_price*100:+.2f}%")

        with st.expander("Tabel Prediksi Per Menit"):
            tbl = pd.DataFrame({
                "Waktu"      : [t.strftime("%H:%M") for t in pred_times],
                "Prediksi $" : [f"${p:,.2f}" for p in pred_prices],
                "Δ dari skrg": [
                    f"{(p-current_price)/current_price*100:+.2f}%"
                    for p in pred_prices
                ]
            })
            st.dataframe(tbl, use_container_width=True, hide_index=True)
    else:
        st.info("Data prediksi per menit tidak tersedia.")
else:
    st.info("Belum ada prediksi.")

st.divider()


# ══════════════════════════════════════════════════════════════
#  ROW 5: Error Metrics & Riwayat Prediksi
# ══════════════════════════════════════════════════════════════
col_left, col_right = st.columns(2)

with col_left:
    st.subheader("Error Metrics")
    if preds and actuals:
        pred_df_m = pd.DataFrame([{
            "time"    : pd.to_datetime(p["created_at"]),
            "pred_avg": float(p["pred_avg"])
        } for p in preds]).sort_values("time")

        actual_df_m = pd.DataFrame([{
            "time"  : pd.to_datetime(a["timestamp"]),
            "actual": float(a["price"])
        } for a in actuals]).sort_values("time")

        merged = pd.merge_asof(
            pred_df_m, actual_df_m,
            on="time", direction="nearest",
            tolerance=pd.Timedelta("2h")
        ).dropna(subset=["actual"])

        if not merged.empty:
            merged["error"]         = merged["pred_avg"] - merged["actual"]
            merged["abs_error"]     = merged["error"].abs()
            merged["dir_up_pred"]   = merged["pred_avg"] > merged["pred_avg"].shift(1)
            merged["dir_up_actual"] = merged["actual"]   > merged["actual"].shift(1)
            merged["dir_correct"]   = merged["dir_up_pred"] == merged["dir_up_actual"]

            mae     = merged["abs_error"].mean()
            dir_acc = merged["dir_correct"].mean() * 100 if len(merged) > 1 else 0

            m1, m2, m3 = st.columns(3)
            m1.metric("MAE",           f"${mae:,.2f}")
            m2.metric("Direction Acc", f"{dir_acc:.1f}%")
            m3.metric("Sample",        f"{len(merged)}")

            fig_err = px.histogram(
                merged, x="error", nbins=15,
                title="Distribusi Error",
                template="plotly_dark",
                color_discrete_sequence=["#f77f00"]
            )
            fig_err.add_vline(
                x=0, line_dash="dash",
                line_color="white", opacity=0.5
            )
            fig_err.update_layout(height=250)
            st.plotly_chart(fig_err, use_container_width=True)
        else:
            st.info("Data belum bisa dicocokkan.")
    else:
        st.info("Belum ada cukup data.")

with col_right:
    st.subheader("Riwayat Prediksi")
    if preds:
        pred_table = pd.DataFrame([{
            "Waktu (WIB)": str(p["created_at"])[:16],
            "Avg ($)"    : f"{p['pred_avg']:,.2f}",
            "Min ($)"    : f"{p['pred_min']:,.2f}",
            "Max ($)"    : f"{p['pred_max']:,.2f}",
            "Range"      : f"${p['pred_max']-p['pred_min']:,.2f}"
        } for p in reversed(preds[-15:])])
        st.dataframe(
            pred_table,
            use_container_width=True,
            hide_index=True
        )
    else:
        st.info("Belum ada prediksi.")

st.divider()


# ══════════════════════════════════════════════════════════════
#  ROW 6: Portfolio
# ══════════════════════════════════════════════════════════════
st.subheader("Portfolio Paper Trading")
try:
    from app.services.paper_trading import get_portfolio
    portfolio = get_portfolio()
    status    = portfolio.get_status()

    upnl    = status.get("unrealized_pnl_pct", 0.0)
    cd_left = status.get("cooldown_remaining_h", 0.0)

    pc1, pc2, pc3, pc4, pc5 = st.columns(5)
    pc1.metric("Balance",    f"${status['balance']:,.2f}")
    pc2.metric("BTC",        f"{status['btc']:.6f}")
    pc3.metric("Total Aset", f"${status['total_asset']:,.2f}")
    pc4.metric("Unrealized PnL", f"{upnl:+.2f}%",
               delta=status.get("position", "NONE"))
    pc5.metric(
        "Cooldown",
        f"{cd_left:.1f}h" if cd_left > 0 else "Siap",
        delta=f"Entry: ${status['entry_price']:,.2f}"
              if status.get("position") == "OPEN" else None
    )
except Exception as e:
    st.warning(f"Portfolio belum tersedia: {e}")

st.divider()


# ══════════════════════════════════════════════════════════════
#  ROW 7: Riwayat Trade
# ══════════════════════════════════════════════════════════════
st.subheader("Riwayat Simulasi Trading")
trades = TradeLogs.get_latest(limit=20)
if trades:
    trade_df = pd.DataFrame([{
        "Waktu"  : str(t["timestamp"])[:16],
        "Aksi"   : t["action"],
        "Harga"  : f"${t['price']:,.2f}",
        "BTC"    : f"{t['amount_btc']:.6f}",
        "Balance": f"${t['balance']:,.2f}",
        "Alasan" : (t["reason"][:40]+"..."
                   if t.get("reason") and len(t["reason"])>40
                   else t.get("reason","-"))
    } for t in trades])

    def color_action(val):
        if val == "BUY":  return "color: #a6e3a1; font-weight: bold"
        if val == "SELL": return "color: #f38ba8; font-weight: bold"
        return ""

    st.dataframe(
        trade_df.style.applymap(color_action, subset=["Aksi"]),
        use_container_width=True, hide_index=True
    )
else:
    st.info("Belum ada trading. Aktifkan Paper Trading di sidebar.")

st.divider()


# ══════════════════════════════════════════════════════════════
#  ROW 8: Info Model
# ══════════════════════════════════════════════════════════════
st.subheader("Info Model")
if model_log:
    mc1, mc2, mc3, mc4 = st.columns(4)
    mc1.metric("Loss",      f"{model_log.get('loss',0):.6f}")
    mc2.metric("Val Loss",  f"{model_log.get('val_loss',0):.6f}")
    mc3.metric("Epochs",    model_log.get("epochs",0))
    mc4.metric("Data Size", f"{model_log.get('data_size',0):,} baris")
    st.caption(f"Model  : `{model_log.get('model_file','-')}`")
    st.caption(f"Trained: `{model_log.get('trained_at','-')}`")
else:
    st.warning("Belum ada model.")

st.divider()


# ══════════════════════════════════════════════════════════════
#  ROW 9: Backtesting
# ══════════════════════════════════════════════════════════════
st.subheader("Backtesting Results")
all_backtests = BacktestResults.get_all()

if all_backtests:
    bt_options = {
        f"#{r['id']} | {str(r['run_at'])[:10]} | "
        f"ROI {r['roi_pct']:+.2f}% | {r.get('notes','')[:20]}": r["id"]
        for r in all_backtests
    }
    selected_label = st.selectbox(
        "Pilih Backtest:", list(bt_options.keys()), index=0
    )
    selected_id = bt_options[selected_label]
    latest_bt   = next(r for r in all_backtests if r["id"]==selected_id)

    roi = latest_bt["roi_pct"]
    pl  = latest_bt["profit_loss"]

    b1, b2, b3, b4 = st.columns(4)
    b1.metric("ROI",           f"{roi:+.2f}%",
              delta="Profit" if roi>0 else "Loss")
    b2.metric("P/L",           f"${pl:+,.2f}",
              delta=f"Final: ${latest_bt['final_total']:,.2f}")
    b3.metric("Win Rate",      f"{latest_bt.get('win_rate',0):.1f}%",
              delta=f"Trades: {latest_bt['total_trades']}")
    b4.metric("Profit Factor", f"{latest_bt.get('profit_factor',0):.2f}")

    b5, b6, b7, b8 = st.columns(4)
    b5.metric("Max Drawdown", f"{latest_bt.get('max_drawdown',0):.2f}%")
    b6.metric("Total Trades", latest_bt["total_trades"])
    b7.metric("Buy / Sell",   f"{latest_bt['buy_count']} / {latest_bt['sell_count']}")
    b8.metric("Data Points",  f"{latest_bt['data_points']:,}")

    equity = BacktestEquity.get_by_backtest(latest_bt["id"])
    if equity:
        eq_df = pd.DataFrame(equity)
        eq_df["timestamp"] = pd.to_datetime(eq_df["timestamp"])
        fig_eq = go.Figure()
        fig_eq.add_trace(go.Scatter(
            x         = eq_df["timestamp"],
            y         = eq_df["total"],
            mode      = "lines",
            name      = "Equity",
            line      = dict(
                color="#a6e3a1" if roi>=0 else "#f38ba8",
                width=2
            ),
            fill      = "tozeroy",
            fillcolor = "rgba(166,227,161,0.1)" if roi>=0
                        else "rgba(243,139,168,0.1)"
        ))
        fig_eq.add_hline(
            y=latest_bt["initial_balance"],
            line_dash="dash", line_color="white", opacity=0.5,
            annotation_text=f"Modal: ${latest_bt['initial_balance']:,.0f}"
        )
        fig_eq.update_layout(
            template="plotly_dark", height=350,
            title="📈 Equity Curve",
            xaxis_title="Waktu", yaxis_title="Total Aset (USD)",
            xaxis=dict(rangeslider=dict(visible=True))
        )
        st.plotly_chart(fig_eq, use_container_width=True)

    col_bt1, col_bt2 = st.columns(2)
    with col_bt1:
        st.markdown("**Semua Riwayat Backtest**")
        bt_table = pd.DataFrame([{
            "ID"     : r["id"],
            "Tanggal": str(r["run_at"])[:10],
            "ROI"    : f"{r['roi_pct']:+.2f}%",
            "P/L"    : f"${r['profit_loss']:+,.2f}",
            "Win%"   : f"{r.get('win_rate',0):.1f}%",
            "DD%"    : f"{r.get('max_drawdown',0):.1f}%",
            "Trades" : r["total_trades"],
            "Notes"  : r.get("notes","")[:25]
        } for r in all_backtests])
        st.dataframe(bt_table, use_container_width=True, hide_index=True)

    with col_bt2:
        st.markdown("**Trade History**")
        bt_trades = BacktestTrades.get_by_backtest(latest_bt["id"])
        if bt_trades:
            tr_table = pd.DataFrame([{
                "Waktu"  : str(t["timestamp"])[:16],
                "Aksi"   : t["action"],
                "Harga"  : f"${t['price']:,.2f}",
                "Balance": f"${t['balance']:,.2f}",
                "Alasan" : (t.get("reason","")[:30]+"..."
                           if len(t.get("reason",""))>30
                           else t.get("reason","-"))
            } for t in bt_trades[-15:]])
            st.dataframe(tr_table, use_container_width=True, hide_index=True)
else:
    st.info("Belum ada backtest. Gunakan form Backtest Manual di sidebar.")

st.divider()
st.caption("BTC AI Prediction System | LSTM + Streamlit | 2026")