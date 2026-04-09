# BTC AI Prediction System

Sistem prediksi harga Bitcoin berbasis Machine Learning (LSTM) dengan 
fitur paper trading otomatis, dashboard realtime, dan notifikasi Telegram.

---

## Daftar Isi

- [Fitur](#-fitur)
- [Arsitektur Sistem](#-arsitektur-sistem)
- [Teknologi](#-teknologi)
- [Persyaratan](#-persyaratan)
- [Instalasi](#-instalasi)
- [Konfigurasi](#-konfigurasi)
- [Menjalankan Sistem](#-menjalankan-sistem)
- [Struktur Proyek](#-struktur-proyek)
- [Dashboard](#-dashboard)
- [Telegram Bot](#-telegram-bot)
- [Paper Trading](#-paper-trading)

---

## Fitur

- **Prediksi Harga** — Model LSTM memprediksi harga BTC 1 jam ke depan
- **Data Realtime** — Fetch OHLC dari Kraken API setiap 1 & 5 menit
- **Dashboard Interaktif** — Visualisasi harga, prediksi, dan portofolio via Streamlit
- **Paper Trading** — Simulasi trading otomatis berdasarkan sinyal teknikal
- **Telegram Bot** — Notifikasi prediksi & trade langsung ke HP
- **Auto Retrain** — Model dilatih ulang otomatis setiap Senin 09:00 WIB
- **Timezone WIB** — Semua tampilan waktu dalam WIB (UTC+7)

---

## Arsitektur Sistem

Sistem terdiri dari empat lapisan utama yang bekerja secara bersamaan:

**1. Lapisan Data (Data Layer)**
Data harga Bitcoin diambil dari Kraken Public API dalam dua interval waktu. Interval 1 menit digunakan untuk memantau harga terkini dan dijalankan setiap 5 menit, sedangkan interval 1 jam digunakan sebagai input model LSTM dan dijalankan setiap jam. Semua data disimpan ke database PostgreSQL secara incremental (hanya data baru yang disimpan).

**2. Lapisan Model (Model Layer)**
Model LSTM dilatih menggunakan data historis 1 jam (hingga 365 hari). Setiap jam, model menghasilkan satu prediksi harga 1 jam ke depan, kemudian diinterpolasi menjadi 60 titik harga per menit untuk visualisasi. Model dilatih ulang otomatis setiap Senin pukul 09:00 WIB.

**3. Lapisan Trading (Trading Layer)**
Setiap menit, sistem mengambil harga terbaru dari database lokal (tanpa request ke internet) dan menghitung sinyal trading berdasarkan indikator teknikal (RSI, MACD, MA20, MA50, MA200). Jika sinyal memenuhi threshold, sistem mengeksekusi order beli atau jual secara simulasi (paper trading).

**4. Lapisan Antarmuka (Interface Layer)**
Hasil prediksi, sinyal, dan status portfolio ditampilkan melalui dua antarmuka: dashboard Streamlit yang dapat diakses via browser, dan Telegram bot yang mengirim notifikasi langsung ke HP.

---

## Alur Data

Kraken API → OHLC 1M → `price_data_1m` → Harga Realtime → Dashboard & Paper Trading

Kraken API → OHLC 1H → `price_data` → Indikator (RSI, MACD, MA) → Model LSTM → Prediksi 1H → Dashboard & Telegram

---

## Teknologi

| Komponen | Teknologi |
|---|---|
| Machine Learning | TensorFlow / Keras (LSTM) |
| Database | PostgreSQL |
| Dashboard | Streamlit + Plotly |
| Bot | python-telegram-bot |
| Data Source | Kraken Public API |
| Scheduler | APScheduler |
| Bahasa | Python 3.10+ |

---

## Persyaratan

- Python **3.10** atau lebih baru
- PostgreSQL **14** atau lebih baru
- Koneksi internet (untuk fetch data Kraken & Telegram)
- Telegram Bot Token (dari [@BotFather](https://t.me/BotFather))

### Dependencies Utama

| Package | Versi | Fungsi |
|---|---|---|
| `tensorflow` | 2.13.0 | Model LSTM |
| `keras` | 2.13.1 | API model deep learning |
| `numpy` | 1.24.3 | Komputasi numerik |
| `pandas` | 1.5.3 | Manipulasi data |
| `scikit-learn` | 1.3.0 | Preprocessing & scaler |
| `psycopg2-binary` | 2.9.7 | Koneksi PostgreSQL |
| `requests` | 2.31.0 | HTTP request ke Kraken API |
| `python-telegram-bot` | 20.5 | Telegram bot |
| `streamlit` | 1.27.0 | Dashboard web |
| `plotly` | 5.17.0 | Visualisasi chart interaktif |
| `apscheduler` | 3.10.4 | Penjadwalan job otomatis |
| `ta` | 0.10.2 | Indikator teknikal |
| `pytz` | 2023.3 | Konversi timezone WIB |
| `joblib` | 1.3.2 | Simpan & load scaler |

---

## Instalasi

### 1. Clone Repository

```bash
git clone https://github.com/AldyDwi/btc-ai-prediction.git
cd btc-ai-prediction
```

### 2. Buat Virtual Environment

```bash
python -m venv venv

# Windows
venv\Scripts\activate

# Linux / Mac
source venv/bin/activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Setup PostgreSQL
Buat database baru:

```sql
-- Jalankan di psql atau pgAdmin
CREATE DATABASE btc_prediction;
CREATE USER btc_user WITH PASSWORD 'password_kamu';
GRANT ALL PRIVILEGES ON DATABASE btc_prediction TO btc_user;
```

### 5. Buat File .env
Salin dari template:

```bash
cp .env.example .env
```

Edit file .env sesuai konfigurasi kamu (lihat bagian Konfigurasi).

### 6. Inisialisasi Database

```bash
python -c "from app.database.db import init_db; init_db()"
```

### 7. Training Model Awal

```bash
python -c "from app.services.training_service import run_training_pipeline; run_training_pipeline()"
```

Catatan: Proses training awal membutuhkan waktu 5–15 menit tergantung spesifikasi komputer

## Konfigurasi
Buat file .env di root project:

```bash
# ── Database ──────────────────────────────────────
DB_HOST     = localhost
DB_PORT     = 5432
DB_NAME     = btc_prediction
DB_USER     = btc_user
DB_PASSWORD = password_kamu

# ── Telegram ──────────────────────────────────────
TELEGRAM_TOKEN   = your_bot_token_here
TELEGRAM_CHAT_ID = your_chat_id_here

# ── Model ─────────────────────────────────────────
WINDOW_SIZE      = 60       # Jumlah candle input LSTM
PREDICTION_STEPS = 1        # Jumlah candle yang diprediksi

# ── Trading ───────────────────────────────────────
INITIAL_BALANCE  = 1000     # Modal awal paper trading (USD)
```

## Cara Mendapatkan Telegram Token & Chat ID

### Bot Token:
1. Buka Telegram, cari @BotFather
2. Kirim /newbot
3. Ikuti instruksi, copy token yang diberikan

### Chat ID:
1. Kirim pesan ke bot kamu
2. Buka: https://api.telegram.org/bot<TOKEN>/getUpdates
3. Cari nilai "chat": {"id": ...}

## Menjalankan Sistem

### Jalankan Backend (main.py)

```bash
python main.py
```

Sistem akan otomatis:
1. Inisialisasi database
2. Load model terbaru
3. Fetch data awal dari Kraken
4. Menjalankan scheduler
5. Menjalankan Telegram bot

### Jalankan Dashboard (Streamlit)
Buka terminal baru:

```bash
streamlit run dashboard.py
```

Buka browser: http://localhost:8501

Catatan: main.py harus berjalan terlebih dahulu agar dashboard mendapat data.

## Struktur Proyek

```bash
btc-ai-prediction/
│
├── main.py                     # Entry point utama
├── dashboard.py                # Dashboard Streamlit
├── requirements.txt
├── .env                        # Konfigurasi (tidak di-commit)
├── .env.example                # Template konfigurasi
├── test_fetch_1h.py            # Script testing ambil data 1 jam
├── test_predict.py             # Script testing prediksi
├── test_signal.py              # Script testing signal
├── test_kraken_ping.py         # Script testing api kraken
│
├── app/
│   ├── bot/
│   │   └── telegram.py         # Telegram bot & command handlers
│   │
│   ├── data/
│   │   ├── fetcher.py          # Fetch data dari Kraken API
│   │   └── processor.py        # Hitung indikator teknikal
│   │
│   ├── database/
│   │   ├── db.py               # Koneksi & inisialisasi PostgreSQL
│   │   └── models.py           # Model/query database
│   │
│   ├── model/
│   │   ├── lstm.py             # Arsitektur model LSTM
│   │   ├── predictor.py        # Prediksi harga
│   │   └── trainer.py          # Training & evaluasi model
│   │
│   ├── services/
│   │   ├── paper_trading.py    # Engine paper trading
│   │   ├── prediction_service.py
│   │   └── training_service.py
│   │
│   └── utils/
│       ├── config.py           # Load konfigurasi .env
│       ├── logger.py           # Setup logging
│       └── timezone_helper.py  # Helper konversi WIB
│
├── models/                     # File model (.keras) tersimpan di sini
└── logs/                       # Log file
```

## Dashboard

Dashboard terdiri dari beberapa bagian:

| Row | Konten |
|---|---|
| Row 1 | Harga BTC realtime, prediksi, perubahan harga |
| Row 2 | Status sistem, portfolio, model info |
| Row 3 | Chart prediksi vs harga aktual (interaktif) |
| Row 4 | Tabel prediksi terbaru |
| Row 5 | Portfolio & riwayat trade |

### Fitur chart:
1. Pilih rentang waktu: 1 Jam, 3 Jam, 6 Jam, 12 Jam, 24 Jam, Semua
2. Pilih resolusi: Per Menit, Per 5 Menit, Per 15 Menit, Per Jam
3. Range prediksi min-max ditampilkan sebagai area

## Telegram Bot

### Perintah Tersedia

| Perintah | Fungsi |
|---|---|
| /sekarang | Prediksi & sinyal trading saat ini |
| /signal | Sinyal trading saja |
| /prediksi | Aktifkan notifikasi prediksi per jam |
| /berhenti | Matikan notifikasi prediksi |
| /portfolio | Status portfolio paper trading |
| /trading_on | Aktifkan paper trading |
| /trading_off | Matikan paper trading |
| /status | Status sistem keseluruhan |
| /info | Informasi lengkap sistem & model |
| /help | Tampilkan menu bantuan |

## Paper Trading

### Cara Kerja
1. Sistem mengecek sinyal setiap 1 menit berdasarkan harga terbaru
2. Sinyal dihitung dari indikator teknikal (RSI, MACD, MA20, MA50, MA200)
3. BUY jika: Score ≥ 5 dan RSI < 45
4. SELL jika: Score ≤ -5 dan RSI > 55

### Parameter Trading

| Parameter | Nilai | Keterangan |
|---|---|---|
| Stop Loss | -2% | Jual otomatis jika rugi 2% |
| Take Profit | +8% | Jual otomatis jika untung 8% |
| Cooldown | 72 jam | Jeda antar trade |
| Modal Awal | $1,000 | Dapat diubah di .env |
| Fee | 0.1% | Per transaksi (simulasi Kraken) |

### Sistem Scoring Signal

| Kondisi | Score |
|---|---|
| Uptrend (> MA200) | +2 |
| RSI < 25 (ekstrem oversold) | +4 |
| RSI 25–35 (sangat oversold) | +3 |
| RSI 35–45 (oversold) | +2 |
| MACD bullish cross | +2 |
| MA20 > MA50 | +1 |
| Price di bawah MA20 | +1 |
| Downtrend (< MA200) | -2 |
| RSI > 80 (ekstrem overbought) | -4 |
| MACD bearish cross | -2 |

## Lisensi

Bebas digunakan dan dimodifikasi.

Disclaimer: Sistem ini hanya untuk tujuan edukasi dan penelitian.
Prediksi harga cryptocurrency tidak akurat 100%.
Jangan gunakan untuk trading nyata tanpa riset mendalam.
