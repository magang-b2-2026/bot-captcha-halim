# komdigi-bot v1.1 — Guide Lengkap

> **Release**: 2 Oktober 2026 | **Status**: Production Ready — 6/6 PASS via Service Worker
> **Repo**: `https://github.com/naufalhalims/komdigi-bot`
> **Lokasi Deploy**: Windows Mini PC — `C:\Coding\Komdigi`

---

## Daftar Isi

1. [Apa Itu komdigi-bot?](#apa-itu-komdigi-bot)
2. [Hasil Captcha Solving — 6 Jenis](#hasil-captcha-solving)
3. [Arsitektur Informasi](#arsitektur-informasi)
4. [Arsitektur Bot (Technical)](#arsitektur-bot)
5. [Model LLM & Metode](#model-llm--metode)
6. [Production Service API](#production-service-api)
7. [Changelog v1.0 ke v1.1](#changelog)

---

## Apa Itu komdigi-bot?

**komdigi-bot** adalah automated captcha solving bot yang mampu mendeteksi dan menyelesaikan 6 jenis CAPTCHA secara otomatis menggunakan kombinasi:
- **Vision LLM** (Google AI Studio Gemini — GRATIS)
- **Browser automation** (Playwright Chromium stealth)
- **Real Chrome CDP** via subprocess isolation (fingerprint legitimate untuk Cloudflare)
- **Multi-provider fallback chain** (AI Studio -> Vikey.ai)
- **FastAPI production service** dengan SQLite job queue (persistent 24/7)

---

## Hasil Captcha Solving

### Test Environment
- **Website**: https://solvecaptcha.com/demo (real CAPTCHA demo)
- **Mode**: Production service worker (background thread)
- **Tanggal test**: 2 Oktober 2026
- **Versi**: v1.1

### Scorecard v1.1 — 6/6 PASS via Service Worker

| # | Jenis CAPTCHA | Status | Engine | Model LLM | Avg Solve |
|---|--------------|--------|--------|-----------|-----------|
| 1 | **Image CAPTCHA** | PASS | `text_reasoning` | Gemini 3.5 Flash Lite | ~9s |
| 2 | **Text CAPTCHA** | PASS | `text_reasoning` | Gemini 3.5 Flash Lite | ~11s |
| 3 | **reCAPTCHA v2** | PASS | `checkbox_grid` | Gemini 3.5 Flash Lite | ~78s |
| 4 | **reCAPTCHA v3** | PASS | `checkbox_grid` | Gemini 3.5 Flash Lite | ~14s |
| 5 | **Cloudflare Turnstile** | PASS | `chrome_cdp` | _(no LLM needed)_ | ~13s |
| 6 | **GeeTest v4** | PASS | `chrome_cdp` | _(no LLM needed)_ | ~13s |

> Turnstile & GeeTest pass otomatis via Chrome 154 real fingerprint tanpa LLM.
> v1.1 fix: Chrome CDP kini berjalan via subprocess terpisah sehingga tidak ada konflik asyncio.

### Ringkasan Performa

| Metrik | Nilai |
|--------|-------|
| Total jenis captcha | 6/6 |
| Pass rate via service worker | **100% (6/6)** |
| Waktu solve tercepat | 9.5s (Image/Text via Gemini) |
| Waktu solve terlambat | 78s (reCAPTCHA v2 grid) |
| Rata-rata keseluruhan | ~23s per captcha |
| Biaya per request | Rp 0 (AI Studio free tier) |
| Quota harian | 1.500 request/hari (gratis) |
| Total jobs diproses dalam sesi | 27 jobs, 0 failed |

---

## Arsitektur Informasi

```
komdigi-bot v1.1
|
+-- INPUT: URL target (website dengan CAPTCHA)
|
+-- LAYER 1: TRIAGE (Deteksi Jenis CAPTCHA)
|   CaptchaDetector > weighted regex scoring
|   Families: turnstile, recaptcha, hcaptcha, arkose,
|             geetest, text, image, rotate, click
|
+-- LAYER 2: ROUTING (Pilih Engine)
|   text/image --> text_reasoning / image_ocr
|   recaptcha  --> checkbox_grid
|   rotate     --> rotate_slide
|   click      --> click_coords
|   turnstile/geetest/arkose --> chrome_cdp (auto-pass)
|
+-- LAYER 3: SOLVER ENGINE
|   TextReasoningSolver   (LLM text answer)
|   ImageOCRSolver        (LLM vision decode)
|   CheckboxGridSolver    (LLM grid cell select)
|   RotateSlideSolver     (LLM angle + drag)
|   ClickCoordsSolver     (LLM coordinate click)
|   ChromeCDPSolver v1.1  (subprocess isolation, Chrome 154)
|
+-- LAYER 4: LLM FALLBACK CHAIN
|   PRIMARY:  Google AI Studio > gemini-3.5-flash-lite (GRATIS)
|   FALLBACK: Vikey.ai > claude-fable-5 (vision)
|                      > deepseek-v4.1-flash (reasoning)
|
+-- LAYER 5: NETWORK RESILIENCE (NEW v1.1)
|   ERR_NAME_NOT_RESOLVED -> auto re-queue setelah 15s delay
|   ERR_INTERNET_DISCONNECTED -> auto re-queue
|
+-- OUTPUT: SolveAttempt {family, engine, status, answer, latency_ms}
```

---

## Arsitektur Bot

### Struktur File

```
C:\Coding\Komdigi\
|
+-- src/komdigi_bot/
|   +-- config.py              # Settings, env vars, LLM keys
|   +-- orchestrator.py        # Main controller
|   |
|   +-- triage/
|   |   +-- detector.py        # Regex weighted scoring
|   |   +-- router.py          # Family ke engine mapping
|   |
|   +-- solvers/
|   |   +-- base.py            # BaseSolver + SolveAttempt
|   |   +-- llm.py             # LLMClient multi-provider fallback
|   |   +-- image_ocr.py       # Screenshot + Gemini vision
|   |   +-- text_reasoning.py  # Text question + Gemini
|   |   +-- checkbox_grid.py   # reCAPTCHA grid solving
|   |   +-- rotate_slide.py    # Rotation puzzle
|   |   +-- click_coords.py    # Click coordinate detection
|   |   +-- fallback/
|   |       +-- api_solver.py  # 2captcha API (opsional)
|   |       +-- twocaptcha.py  # 2captcha HTTP client
|   |
|   +-- stealth/
|   |   +-- browser.py         # Playwright stealth browser
|   |
|   +-- service/               [NEW v1.0, updated v1.1]
|       +-- api.py             # FastAPI HTTP server port 8080
|       +-- queue.py           # SQLite persistent job queue
|       +-- worker.py          # Worker + quota + network retry [v1.1]
|       +-- chrome_cdp_solver.py  # Subprocess CDP solver [v1.1 fix]
|
+-- chrome_cdp_runner.py       # [NEW v1.1] CDP subprocess runner
+-- start_service.py           # Entry point uvicorn (UTF-8 safe)
+-- run_service.bat            # Windows watchdog auto-restart
+-- setup_autostart.ps1        # Task Scheduler (run as Admin)
+-- real_browser_test.py       # Standalone Chrome CDP test
+-- benchmark.py               # Benchmark multi-site
+-- guide-komdigibot.md        # [File ini]
+-- .env                       # API keys (tidak di-commit)
```

### Alur Request Production Service

```
Client
  |
  v  POST /solve {"url": "https://..."}
FastAPI (port 8080)
  |
  v  enqueue(url)
SQLite jobs.db  [status: pending]
  |
  v  pop_pending()
Worker Thread (v1.1: network retry resilience)
  + QuotaTracker (1500/hari)
  + cleanup_evidence() setiap jam
  + auto re-queue on ERR_NAME_NOT_RESOLVED
  |
  v  run(url)
Orchestrator
  1. StealthBrowser.goto(url)       <- Playwright Chromium stealth
  2. CaptchaDetector.detect()       <- weighted regex
  3. CaptchaRouter.route()          <- family -> engine
  4. Solver.solve()                 <- LLM-based solving
  5. ChromeCDPSolver fallback       <- subprocess(chrome_cdp_runner.py)
     |                                 Chrome 154 real fingerprint
     v subprocess.run()
     chrome_cdp_runner.py          <- isolated process, own event loop
     Chrome 154 + Playwright CDP   <- auto-pass Turnstile/GeeTest
     JSON result -> stdout
  |
  v  complete(result)
SQLite jobs.db  [status: done]
  |
  v  GET /job/{id}
Client polling
```

### Stack Teknologi

| Komponen | Teknologi | Versi |
|----------|-----------|-------|
| Language | Python | 3.11 |
| Package Manager | uv | latest |
| Browser Automation | Playwright | sync API |
| Real Browser | Google Chrome | 154.0.8037 |
| HTTP Server | FastAPI + Uvicorn | 0.142 / 0.54 |
| Job Queue | SQLite | built-in |
| Testing | pytest | 123 tests |

---

## Model LLM & Metode

### Provider Hierarchy (Fallback Chain)

```
PRIMARY: Google AI Studio (GRATIS)
  Model Vision:    gemini-3.5-flash-lite
  Model Reasoning: gemini-3.5-flash-lite
  Endpoint: https://generativelanguage.googleapis.com/v1beta/openai
  Limit: 1.500 req/hari
  Latency: ~1.7s avg

FALLBACK: Vikey.ai (jika AI Studio error atau quota habis)
  Model Vision:    anthropic/claude-fable-5
  Model Reasoning: deepseek/deepseek-v4.1-flash
  Endpoint: https://api.vikey.ai/v1
  Biaya: ~Rp 50/request (vision)
```

### Metode Solving per Engine

| Engine | Metode | LLM Call | Prompt |
|--------|--------|----------|--------|
| `image_ocr` | Screenshot -> Gemini vision | 1x vision | "Read the text in this CAPTCHA image exactly" |
| `text_reasoning` | Scrape soal -> Gemini text | 1x text | "Answer this question: {question}" |
| `checkbox_grid` | Screenshot grid -> Gemini | 1x vision | "Select cells containing {category}, return 1-9" |
| `rotate_slide` | Screenshot -> Gemini vision | 1x vision | "Degrees clockwise to make image upright?" |
| `click_coords` | Screenshot -> Gemini vision | 1x vision | "Find click coordinates for: {target}" |
| `chrome_cdp` | subprocess chrome_cdp_runner.py | 0 (no LLM) | Auto-pass via Chrome 154 fingerprint |

### Benchmark Model Vision

| Model | Provider | Latency | Akurasi | Biaya |
|-------|----------|---------|---------|-------|
| **gemini-3.5-flash-lite** | AI Studio | **1.7s** | PASS | **GRATIS** |
| gemini-3.1-flash-lite | AI Studio | 3.3s | PASS | GRATIS |
| claude-fable-5 | Vikey.ai | 4.8s | PASS | ~Rp 50/req |
| deepseek/qwen/glm | Vikey.ai | -- | FAIL 502 | -- |

**Winner: gemini-3.5-flash-lite** -- tercepat, gratis, akurat.

---

## Production Service API

Service berjalan di `http://localhost:8080`.

### Endpoints

```
POST /solve
  Body: {"url": "https://target-website.com"}
  Response 202: {"job_id": "uuid", "status": "pending"}

GET /job/{job_id}
  Response: {id, url, status, result{family,engine,status}, started_at, finished_at}

GET /health
  Response: {"status": "ok", "uptime_s": 276, "worker_alive": true}

GET /metrics
  Response: {queue:{done:27}, quota:{remaining_today:1489}, worker:{jobs_done:11}}

GET /docs
  Swagger UI interaktif
```

### Menjalankan Service

```powershell
# Start manual (UTF-8 safe)
cd C:\Coding\Komdigi
$env:PYTHONUTF8 = "1"
uv run python start_service.py --host 0.0.0.0 --port 8080

# Auto-start saat boot (jalankan sebagai Administrator sekali)
.\setup_autostart.ps1

# Monitor log real-time
Get-Content outputs\logs\service.log -Wait -Tail 20

# Cek health
Invoke-RestMethod http://localhost:8080/health | ConvertTo-Json
```

---

## Changelog

### v1.1 (2 Oktober 2026)

**Bug Fixes:**
- Fix Chrome CDP threading: `ChromeCDPSolver` kini spawn `chrome_cdp_runner.py`
  sebagai subprocess terpisah sehingga `sync_playwright()` dapat membuat
  asyncio event loop sendiri tanpa konflik dengan uvicorn worker thread
- Fix `UnicodeEncodeError` pada Windows cp1252: ganti karakter `->` (ASCII)
  di semua log message, set `PYTHONUTF8=1` di environment

**Improvements:**
- Worker network retry resilience: deteksi `ERR_NAME_NOT_RESOLVED`,
  `ERR_INTERNET_DISCONNECTED`, dan `net::` errors -> auto re-queue job
  setelah 15s delay (max 2 retries per job)
- Pass rate via service worker: **4/6 -> 6/6 (100%)**

### v1.0 (2 Oktober 2026)

- Initial release
- 6 captcha types supported (6/6 standalone, 4/6 via service)
- FastAPI HTTP service + SQLite job queue
- LLM fallback chain: AI Studio (free) -> Vikey.ai
- Chrome CDP integration untuk Turnstile/GeeTest
- 123 unit tests passing

---

## Perintah Penting

```powershell
# Unit tests
uv run pytest -o pythonpath=src -q

# Benchmark solvecaptcha.com
uv run python -m komdigi_bot.benchmark --site solvecaptcha --runs 1

# Test Chrome CDP standalone
uv run python real_browser_test.py

# Submit job ke service
$body = '{"url":"https://solvecaptcha.com/demo/image-captcha"}'
Invoke-RestMethod http://localhost:8080/solve -Method Post -Body $body -ContentType "application/json"

# Cek semua status
Invoke-RestMethod http://localhost:8080/metrics | ConvertTo-Json -Depth 3
```

---

*komdigi-bot v1.1 -- Built with Google Gemini AI Studio + Playwright + Chrome CDP*
*Release: 2 Oktober 2026 | Author: naufalhalims | 6/6 PASS*
