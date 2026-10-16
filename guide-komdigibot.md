# komdigi-bot v1.2 — Guide Lengkap & Spesifikasi Arsitektur

> **Release**: 5 Oktober 2026 | **Status**: Production Ready — 126/126 Tests PASS (100% Green)
> **Repo**: `https://github.com/naufalhalims/komdigi-bot`
> **Lokasi Deploy**: Windows Mini PC — `C:\Coding\Komdigi`

---

## Daftar Isi

1. [Apa Itu komdigi-bot?](#apa-itu-komdigi-bot)
2. [Bagaimana Aslinya Arsitektur Ini Bekerja?](#bagaimana-aslinya-arsitektur-ini-bekerja)
3. [Dua Tingkat Peramban (Two-Tier Browser Engine)](#dua-tingkat-peramban)
4. [Integrasi AI: TypeSafe Jev (System 1) + 9router LLM (System 2)](#integrasi-ai)
5. [Arsitektur Hybrid: Mini PC Residential Node vs VPS Singapore + Egress Proxy](#arsitektur-hybrid)
6. [Hasil Pengujian Tantangan (Scorecard Lengkap)](#hasil-pengujian-tantangan)
7. [Arsitektur Informasi & Alur Data](#arsitektur-informasi)
8. [Arsitektur Bot (Struktur Modul)](#arsitektur-bot)
9. [Production Service API & Monitoring](#production-service-api)
10. [Changelog (v1.0 -> v1.1 -> v1.2)](#changelog)

---

## Apa Itu komdigi-bot?

**komdigi-bot** adalah bot otomasi cerdas yang dirancang untuk mendeteksi dan menyelesaikan berbagai rintangan CAPTCHA secara otomatis dan tangguh. 

Bot ini mengombinasikan:
- **Vision & Reasoning LLM** via 9router Tencent Cloud Singapore (`ag/gemini-3.8-flash-high`) dengan fallback multi-provider (Google AI Studio & Vikey.ai).
- **TypeSafe AI Jev (System 1)** untuk *pre-gating* validasi keberadaan CAPTCHA dan konfirmasi rute engine tanpa pemborosan token.
- **Dua Tingkat Peramban (Two-Tier Engine)**: Headless stealth browser untuk efisiensi kecepatan tinggi dan Google Chrome 154 fisik via Chrome DevTools Protocol (CDP) untuk melewati deteksi anti-bot tercanggih (Cloudflare Turnstile, GeeTest v4).
- **FastAPI Production Service** berbasis antrean persisten SQLite (`jobs.db`) yang siap beroperasi 24/7.

---

## Bagaimana Aslinya Arsitektur Ini Bekerja?

### Membuka Browser Fisik Asli (Bukan Mocking Sintetis)

Bot ini **benar-benar membuka Google Chrome fisik (`chrome.exe`) yang terpasang di sistem operasi Windows Mini PC**, bukan sekadar "meminjam" atau memalsukan (*spoofing*) sidik jari (*fingerprint*) lewat manipulasi skrip JavaScript.

```python
# Dieksekusi oleh chrome_cdp_runner.py sebagai proses terisolasi
CHROME_EXE = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

proc = subprocess.Popen([
    CHROME_EXE,
    f"--remote-debugging-port=9224",
    f"--user-data-dir={TEMP_PROFILE}",
    "--no-first-run",
    "about:blank",
])
```

Saat proses ini dipanggil:
1. **Kernel Windows Mini PC** mengalokasikan PID dan alokasi memori riil untuk peramban Google Chrome versi resmi (v154.0.8037).
2. Peramban terhubung langsung ke **hardware fisik Mini PC**: kartu grafis GPU, driver DirectX/Vulkan native, audio context, dan daftar font Windows lokal.
3. Paket data yang dikirim menggunakan **TCP/IP stack dan TLS handshake (JA3/JA4 fingerprint)** resmi bawaan Windows, bukan emulasi library HTTP Python.

### Mengapa Teknik "Meminjam / Spoofing Fingerprint" Tidak Ampuh?

Sistem anti-bot modern seperti **Cloudflare Turnstile** dan **GeeTest v4** melakukan verifikasi multi-dimensi:
- **Hardware & Shader Compilation**: Cloudflare menguji eksekusi shader WebGL dan WebAssembly. Memalsukan User-Agent (misal mengaku "Macbook M1") saat hardware komputasi sebenarnya adalah kartu grafis AMD/Intel di Windows akan memicu *fingerprint mismatch* dan langsung diblokir.
- **TLS / HTTP2 Fingerprint**: Cloudflare mencocokkan urutan *cipher suite* pada level soket jaringan dengan klaim User-Agent peramban.
- **Internal C++ DOM APIs**: Ratusan properti internal browser C++ (seperti `window.chrome.csi`, `performance.timing`, permissions) tidak mungkin dipalsukan 100% secara sintetis tanpa kebocoran (*leak*).

Dengan membuka `chrome.exe` asli di Mini PC, **tidak ada parameter yang perlu dipalsukan**. Cloudflare mengenali entitas tersebut sebagai pengguna manusia asli yang sedang berselancar dengan Google Chrome di Windows 11.

### Komunikasi via Chrome DevTools Protocol (CDP)

Setelah `chrome.exe` aktif, bot mengendalikannya melalui socket **Chrome DevTools Protocol (CDP)** pada port `9224`. Modul Playwright bertindak sebagai pengendali resmi berbasis protokol internal Chromium tanpa mengganggu sesi pengguna utama.

---

## Dua Tingkat Peramban (Two-Tier Browser Engine)

Untuk mengoptimalkan konsumsi memori dan kecepatan pada Mini PC, sistem membagi eksekusi peramban ke dalam dua tingkat:

```
                  ┌───────────────────────────────┐
                  │      URL Target Diterima      │
                  └──────────────┬────────────────┘
                                 │
                                 ▼
                  ┌───────────────────────────────┐
                  │    Triage & Klasifikasi Jev   │
                  └──────────────┬────────────────┘
                                 │
         ┌───────────────────────┴───────────────────────┐
         │                                               │
   [Tantangan Ringan]                             [Tantangan Berat]
 (Image, Text, reCAPTCHA)                      (Turnstile, GeeTest v4)
         │                                               │
         ▼                                               ▼
┌───────────────────────────────┐               ┌───────────────────────────────┐
│     TIER 1: HEADLESS STEALTH   │               │       TIER 2: REAL CHROME CDP  │
│  - Playwright Chromium         │               │  - Subprocess terisolasi      │
│  - Ramah memori (~150 MB RAM)  │               │  - chrome.exe fisik (Port 9224)│
│  - Latensi navigasi super cepat│               │  - Bypass Cloudflare 100% PASS│
└───────────────────────────────┘               └───────────────────────────────┘
```

---

## Integrasi AI

Sistem menerapkan arsitektur *Decoupled Tool Selection and Execution* (Tri-Tier Cognitive Dispatch):

### Lapisan 1: TypeSafe AI Jev (System 1 Decision Engine)
- **Pre-gate (`noul`)**: Mengevaluasi apakah halaman web benar-benar tidak memiliki CAPTCHA dengan ambang batas keyakinan 85%. Jika tidak ada CAPTCHA, bot langsung berhenti tanpa membuang kuota LLM.
- **Choice Confirmation (`choice`)**: Memilih dan memvalidasi engine solver terbaik (`image_ocr`, `text_reasoning`, `checkbox_grid`, `rotate_slide`, `click_coords`, `chrome_cdp`) sebelum eksekusi.
- **Konfigurasi**: `TYPESAFE_API_KEY` aktif pada berkas [`.env`](file:///c:/Coding/Komdigi/.env).

### Lapisan 2: LLM Inference Engine (System 2 Reasoning & Vision)
- **Primer**: 9router LLM Gateway (`http://<vps-endpoint>:20128/v1` atau `http://localhost:20128/v1`) menggunakan model `ag/gemini-3.8-flash-high`.
- **Sekunder (Fallback)**: Google AI Studio (`gemini-3.5-flash-lite`, kuota gratis 1.500 request/hari) dan Vikey.ai (`claude-fable-5` & `deepseek-v4.1-flash`).

---

## Arsitektur Hybrid

Bot mendukung dua model penyebaran produksi dengan fokus utama pada **Arsitektur Hybrid (VPS 24/7 + Mini PC Egress Node)**:

| Komponen | Opsi 1: Mini PC Standalone Node | Opsi 2: Hybrid VPS 24/7 + Mini PC Residential Egress (Rekomendasi) |
|---|---|---|
| **Lokasi Worker / Service** | Windows Mini PC Lokal | Ubuntu 22.04 LTS (VPS Cloud Singapore / Remote) |
| **Inference 9router LLM** | Lintas negara (~35-50ms) | Intra-datacenter (~1-2ms ultralow latency) |
| **Reputasi IP Browser** | Residensial Asli (Sangat Terpercaya) | Egress di-tunnel ke IP Residensial Mini PC via Tailscale |
| **Konektivitas Antar-Node** | Standalone | Private Mesh WireGuard Tailscale (`<mini-pc-ip>` <-> `<vps-ip>`) |
| **Bypass Anti-Bot** | 100% via Chrome fisik lokal | 100% via SOCKS5 proxy residensial & remote CDP |
| **Konfigurasi Proxy** | Opsional (`PROXY=""`) | Wajib (`PROXY="socks5://<mini-pc-tailscale-ip>:1080"`) |

### Diagram Topologi Hybrid

```text
+-----------------------------------------------------------------------------------+
|                           PRIVATE TAILSCALE MESH NETWORK                          |
|                                                                                   |
|  +-------------------------------------+   SOCKS5   +--------------------------+  |
|  |       VPS CLOUD (24/7 Core Engine)  |  Tunnel    |    MINI PC WORKHORSE     |  |
|  |     IP: <vps-tailscale-ip>          |  (P2P)     |  IP: <mini-pc-tailscale> |  |
|  |                                     | ---------> |                          |  |
|  | - PM2 Daemon: komdigi-bot-worker    |   :1080    | - start_residential_     |  |
|  | - Orchestrator & Task Queue         |            |   proxy.py (Port 1080)   |  |
|  | - Jev System 1 Decision Gate        |            | - Real Chrome CDP Engine |  |
|  | - Local 9router LLM (Port 20128)    |            |   (Port 9224)            |  |
|  |   Latency: 1-2ms                    |            | - Residential IP Egress  |  |
|  +-------------------------------------+            +--------------------------+  |
|                     |                                             |               |
+---------------------|---------------------------------------------|---------------+
                      |                                             |
                      v (Inference)                                 v (Web Egress)
             +-----------------+                           +------------------+
             | 9router LLM API |                           | Target Websites  |
             | (OpenAI-Compat) |                           | (Democaptcha dll)|
             +-----------------+                           +------------------+
```

### Panduan Implementasi & Deployment

1. **Jalankan SOCKS5 Residential Proxy di Mini PC**:
   ```powershell
   # Menjalankan proxy daemon di port 1080 (bind ke seluruh interface/Tailscale)
   uv run python start_residential_proxy.py --host 0.0.0.0 --port 1080
   
   # Atau gunakan watchdog batch script:
   .\run_residential_proxy.bat
   ```

2. **Deploy Worker 24/7 di VPS Cloud**:
   ```bash
   # Masuk ke VPS via SSH Tailscale
   ssh ubuntu@<vps-tailscale-ip>
   
   # Jalankan skrip instalasi dan deployment otomatis
   cd /home/ubuntu/apps/komdigi-bot && bash deploy/setup_vps.sh
   ```

3. **Verifikasi Egress IP dari VPS**:
   ```bash
   # Menjalankan diagnostik untuk memastikan IP publik VPS terdeteksi sebagai IP Mini PC
   python deploy/verify_egress.py socks5://<mini-pc-tailscale-ip>:1080
   ```


## Hasil Pengujian Tantangan

### Scorecard Evaluasi Rintangan (v1.2)

| # | Target Tantangan / Varian | Engine Solver | Model LLM / Komponen | Status | Karakteristik Tantangan |
|---|---|---|---|---|---|
| 1 | `solvecaptcha.com/demo/image-captcha` | `image_ocr` | Gemini 3.8 Flash High | **PASS** | Distorsi huruf acak dalam gambar |
| 2 | `solvecaptcha.com/demo/text-captcha` | `text_reasoning` | Gemini 3.8 Flash High | **PASS** | Pertanyaan penalaran teks |
| 3 | `solvecaptcha.com/demo/recaptcha-v2` | `checkbox_grid` | Gemini 3.8 Flash High | **PASS** | Seleksi grid gambar 3x3 |
| 4 | `solvecaptcha.com/demo/recaptcha-v3` | `checkbox_grid` | Gemini 3.8 Flash High | **PASS** | Skor interaksi latar belakang |
| 5 | `solvecaptcha.com/demo/cloudflare-turnstile` | `chrome_cdp` | Chrome 154 Fisik (CDP) | **PASS** | Validasi hardware & TLS peramban |
| 6 | `solvecaptcha.com/demo/geetest` | `chrome_cdp` | Chrome 154 Fisik (CDP) | **PASS** | Verifikasi anti-fraud GeeTest v4 |
| 7 | `democaptcha.com/demo-form-eng/image.html` | `image_ocr` | Gemini 3.8 Flash High | **PASS** | Form standar dengan OCR gambar |
| 8 | `democaptcha.com/demo-form-eng/math-image.html` | `image_ocr` (math) | Gemini 3.8 Flash High | **PASS** | Persamaan aritmatika (hitung otomatis) |
| 9 | `2captcha.com/demo/text` | `text_reasoning` | Gemini 3.8 Flash High | **PASS** | Pertanyaan teks bebas |
| 10 | `2captcha.com/demo/normal` | `image_ocr` | Gemini 3.8 Flash High | **PASS** | Karakter alfanumerik terdistorsi |

---

## Arsitektur Informasi

```
komdigi-bot v1.2
|
+-- INPUT: URL target
|
+-- LAYER 1: TRIAGE & DETEKSI DOM
|   CaptchaDetector > weighted regex (bobot 1.0 - 1.5)
|
+-- LAYER 2: TYPESAFE JEV SYSTEM 1
|   1. Pre-gate noul (apakah halaman benar-benar bebas CAPTCHA?)
|   2. Engine choice confirmation (pemilihan solver presisi)
|
+-- LAYER 3: DUA TINGKAT DISPATCH PERAMBAN
|   [Tier 1] Headless Stealth Browser (Playwright Chromium)
|   [Tier 2] Real Chrome CDP Subprocess (Chrome 154 port 9224)
|
+-- LAYER 4: MULTI-PROVIDER LLM HIERARCHY
|   [Primary]  9router Tencent Cloud Singapore (ag/gemini-3.8-flash-high)
|   [Fallback] Google AI Studio (gemini-3.5-flash-lite)
|   [Backup]   Vikey.ai (claude-fable-5 / deepseek-v4.1)
|
+-- LAYER 5: KETAHANAN JARINGAN & PROXY
|   - Residential SOCKS5 Egress Proxy routing
|   - Auto re-queue 15s saat terjadi DNS drop (ERR_NAME_NOT_RESOLVED)
|
+-- OUTPUT: SolveAttempt {family, engine, status, answer, latency_ms}
```

---

## Arsitektur Bot

### Struktur Berkas Inti

```
C:\Coding\Komdigi\
|
+-- src/komdigi_bot/
|   +-- config.py              # Schema pydantic (Settings, Proxy, JevConfig)
|   +-- orchestrator.py        # Controller utama (triage -> Jev -> solve)
|   |
|   +-- decision/
|   |   +-- jev.py             # TypeSafe AI Jev System 1 HTTP client
|   |
|   +-- triage/
|   |   +-- detector.py        # Regex DOM detection & signature weights
|   |   +-- router.py          # Routing logic dengan Jev noul & choice
|   |
|   +-- solvers/
|   |   +-- base.py            # BaseSolver + SUCCESS_MARKERS adaptif
|   |   +-- llm.py             # LLMClient dengan multi-provider fallback
|   |   +-- image_ocr.py       # Vision OCR + Math equation calculation
|   |   +-- text_reasoning.py  # Reasoning solver untuk soal teks
|   |   +-- checkbox_grid.py   # reCAPTCHA grid cell selector
|   |   +-- rotate_slide.py    # Rotasi dan slider puzzle solver
|   |   +-- click_coords.py    # Koordinat klik visual
|   |
|   +-- stealth/
|   |   +-- browser.py         # Playwright stealth browser + proxy support
|   |
|   +-- service/
|       +-- api.py             # FastAPI server (port 8080)
|       +-- queue.py           # SQLite persistent job queue (jobs.db)
|       +-- worker.py          # Background worker + network retry resilience
|       +-- chrome_cdp_solver.py # Subprocess wrapper untuk Chrome CDP
|
+-- chrome_cdp_runner.py       # Runner independen untuk Chrome 154 fisik
+-- start_service.py           # Entrypoint service Uvicorn (UTF-8 safe)
+-- run_service.bat            # Windows watchdog auto-restart
+-- setup_autostart.ps1        # Registrar Windows Task Scheduler (Admin)
+-- guide-komdigibot.md        # Dokumentasi lengkap arsitektur (berkas ini)
+-- .env                       # Kredensial rahasia (gitignored)
```

---

## Production Service API

Service berjalan di `http://localhost:8080`.

### Menjalankan Service

```powershell
# Set encoding UTF-8 dan start service
$env:PYTHONUTF8 = "1"
cd C:\Coding\Komdigi
uv run python start_service.py --host 0.0.0.0 --port 8080
```

### Endpoints Utama

- `POST /solve`: Menambahkan URL ke antrean (`{"url": "https://..."}`).
- `GET /job/{id}`: Memeriksa status penyelesaian dan hasil verifikasi.
- `GET /health`: Pemeriksaan kesehatan proses dan status worker.
- `GET /metrics`: Statistik antrean, sisa kuota, dan uptime.
- `GET /docs`: Antarmuka Swagger UI interaktif.

---

## Changelog

### v1.2 (5 Oktober 2026)

- **Integrasi TypeSafe AI Jev (System 1)**: Mengaktifkan pre-gating `noul` dan konfirmasi rute engine `choice` di [`orchestrator.py`](file:///c:/Coding/Komdigi/src/komdigi_bot/orchestrator.py) menggunakan `TYPESAFE_API_KEY`.
- **Dukungan 9router LLM Endpoint**: Primary LLM diarahkan ke 9router / OpenAI-compatible endpoint (`http://<vps-endpoint>:20128/v1`) dengan model `ag/gemini-3.8-flash-high`.
- **Dukungan Math CAPTCHA**: Prompt [`image_ocr.py`](file:///c:/Coding/Komdigi/src/komdigi_bot/solvers/image_ocr.py) diperluas untuk menghitung persamaan aritmatika otomatis (misal: `democaptcha.com` math-image).
- **Indikator Sukses Adaptif**: [`base.py`](file:///c:/Coding/Komdigi/src/komdigi_bot/solvers/base.py) diperbarui dengan `SUCCESS_MARKERS` multi-platform.
- **Arsitektur Hybrid & Egress Proxy**: Dukungan field `proxy` pada `Settings` untuk integrasi SOCKS5/HTTP proxy residensial.
- **Unit Test Suite**: Diperluas menjadi **126/126 tests lulus (100% green)**.

### v1.1 (2 Oktober 2026)

- **Chrome CDP Subprocess Isolation**: Memperbaiki konflik *event loop* asyncio worker thread dengan menjalankan `chrome_cdp_runner.py` secara terpisah.
- **Ketahanan Jaringan Worker**: Mekanisme auto re-queue 15 detik jika terjadi gangguan koneksi (`ERR_NAME_NOT_RESOLVED`).
- **Fix Encoding Windows**: Perbaikan karakter Unicode di logging (`PYTHONUTF8=1`).
- **Pass Rate Service Worker**: Meningkat menjadi 100% (6/6 varian lolos).

### v1.0 (2 Oktober 2026)

- Rilis awal arsitektur modular (Triage, Router, Solvers, Stealth).
- Layanan FastAPI + Antrean Persisten SQLite.
- Integrasi Chrome CDP port 9224 untuk bypass Cloudflare Turnstile.
- 123 unit tests lulus.

---

## Perintah Operasional Penting

```powershell
# Jalankan seluruh unit test suite
uv run pytest -o pythonpath=src -q

# Uji simulasi 4 tantangan target (QA suite)
uv run pytest tests/test_qa_four_challenges.py -o pythonpath=src -v

# Jalankan benchmark solvecaptcha
uv run python -m komdigi_bot.benchmark --site solvecaptcha --runs 1

# Uji langsung Chrome CDP fisik
uv run python chrome_cdp_runner.py https://solvecaptcha.com/demo/cloudflare-turnstile outputs/evidence
```

---

*komdigi-bot v1.2 — Multi-Tier Intelligent CAPTCHA Solving Architecture*  
*Author: naufalhalims | Release: 5 Oktober 2026 | 126/126 Tests Passing*
