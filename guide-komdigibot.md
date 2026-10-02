# komdigi-bot v1.0 — Guide Lengkap

> **Release**: 2 Oktober 2026 | **Status**: Production Ready (Standalone 6/6 PASS)
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
7. [Known Limitations & Roadmap v1.1](#known-limitations--roadmap-v11)

---

## Apa Itu komdigi-bot?

**komdigi-bot** adalah automated captcha solving bot yang mampu mendeteksi dan menyelesaikan 6 jenis CAPTCHA secara otomatis menggunakan kombinasi:
- **Vision LLM** (Google AI Studio Gemini — GRATIS)
- **Browser automation** (Playwright Chromium)
- **Real Chrome CDP** (fingerprint legitimate untuk Cloudflare)
- **Multi-provider fallback chain** (AI Studio → Vikey.ai)

---

## Hasil Captcha Solving

### Test Environment
- **Website**: https://solvecaptcha.com/demo (real CAPTCHA demo)
- **Mode**: Standalone direct + Production service
- **Tanggal test**: 2 Oktober 2026

### Scorecard Lengkap

| # | Jenis CAPTCHA | Status | Engine | Model LLM | Avg Solve |
|---|--------------|--------|--------|-----------|-----------|
| 1 | **Image CAPTCHA** | PASS | `image_ocr` | Gemini 3.5 Flash Lite | ~20s |
| 2 | **Text CAPTCHA** | PASS | `text_reasoning` | Gemini 3.5 Flash Lite | ~10s |
| 3 | **reCAPTCHA v2** | PASS | `checkbox_grid` | Gemini 3.5 Flash Lite | ~75s |
| 4 | **reCAPTCHA v3** | PASS | `checkbox_grid` | Gemini 3.5 Flash Lite | ~13s |
| 5 | **Cloudflare Turnstile** | PASS | `chrome_cdp` | _(no LLM needed)_ | ~8s |
| 6 | **GeeTest v4** | PASS | `chrome_cdp` | _(no LLM needed)_ | ~12s |

> Turnstile & GeeTest pass otomatis via Chrome 154 real fingerprint tanpa LLM.

### Ringkasan Performa

| Metrik | Nilai |
|--------|-------|
| Total jenis captcha | 6/6 |
| Pass rate standalone | 100% |
| Pass rate via service worker | 4/6 (Chrome CDP threading bug — fix v1.1) |
| Waktu solve tercepat | 8.3s (Turnstile via Chrome CDP) |
| Waktu solve terlambat | 91s (reCAPTCHA v2 grid solve) |
| Rata-rata keseluruhan | ~23s per captcha |
| Biaya per request | Rp 0 (AI Studio free tier) |
| Quota harian | 1.500 request/hari (gratis) |

---

## Arsitektur Informasi

```
komdigi-bot v1.0
|
+-- INPUT: URL target (website dengan CAPTCHA)
|
+-- LAYER 1: TRIAGE (Deteksi Jenis CAPTCHA)
|   CaptchaDetector > weighted regex scoring
|   Families: turnstile, recaptcha, hcaptcha, arkose,
|             geetest, text, image, rotate, click
|
+-- LAYER 2: ROUTING (Pilih Engine)
|   text      --> text_reasoning
|   image     --> image_ocr
|   recaptcha --> checkbox_grid
|   rotate    --> rotate_slide
|   click     --> click_coords
|   turnstile/geetest/arkose --> chrome_cdp (fallback)
|
+-- LAYER 3: SOLVER ENGINE
|   TextReasoningSolver   (LLM text answer)
|   ImageOCRSolver        (LLM vision decode)
|   CheckboxGridSolver    (LLM grid cell select)
|   RotateSlideSolver     (LLM angle + drag)
|   ClickCoordsSolver     (LLM coordinate click)
|   ChromeCDPSolver       (real Chrome 154 fingerprint)
|
+-- LAYER 4: LLM FALLBACK CHAIN
|   PRIMARY:  Google AI Studio > gemini-3.5-flash-lite (GRATIS)
|   FALLBACK: Vikey.ai > claude-fable-5 (vision)
|                      > deepseek-v4.1-flash (reasoning)
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
|   +-- service/               # [NEW v1.0]
|       +-- api.py             # FastAPI HTTP server port 8080
|       +-- queue.py           # SQLite persistent job queue
|       +-- worker.py          # Background worker + quota tracker
|       +-- chrome_cdp_solver.py  # Chrome 154 CDP fingerprint
|
+-- start_service.py           # Entry point uvicorn
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
Worker Thread
  + QuotaTracker (1500/hari)
  + cleanup_evidence() setiap jam
  |
  v  run(url)
Orchestrator
  1. StealthBrowser.goto(url)
  2. CaptchaDetector.detect()
  3. CaptchaRouter.route()
  4. Solver.solve()
  5. ChromeCDPSolver fallback (Turnstile/GeeTest)
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
| Language | Python | 3.12+ |
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
  Latency: 1.7s avg

FALLBACK: Vikey.ai (jika AI Studio error atau quota habis)
  Model Vision:    anthropic/claude-fable-5
  Model Reasoning: deepseek/deepseek-v4.1-flash
  Endpoint: https://api.vikey.ai/v1
  Biaya: ~Rp 50/request (vision)
```

### Metode Solving per Engine

| Engine | Metode | LLM Call | Prompt |
|--------|--------|----------|--------|
| `image_ocr` | Screenshot > base64 > Gemini vision | 1x vision | "Read the text in this CAPTCHA image exactly" |
| `text_reasoning` | Scrape soal > Gemini text | 1x text | "Answer this question: {question}" |
| `checkbox_grid` | Screenshot grid > Gemini vision | 1x vision | "Select cells containing {category}, return 1-9" |
| `rotate_slide` | Screenshot > Gemini vision | 1x vision | "Degrees clockwise to make image upright?" |
| `click_coords` | Screenshot > Gemini vision | 1x vision | "Find click coordinates for: {target}" |
| `chrome_cdp` | Real Chrome fingerprint via CDP | 0 (no LLM) | Auto-pass via legitimate browser identity |

### Benchmark Model Vision

| Model | Provider | Latency | Akurasi | Biaya |
|-------|----------|---------|---------|-------|
| **gemini-3.5-flash-lite** | AI Studio | **1.7s** | PASS | **GRATIS** |
| gemini-3.1-flash-lite | AI Studio | 3.3s | PASS | GRATIS |
| claude-fable-5 | Vikey.ai | 4.8s | PASS | ~Rp 50/req |
| qwen/minimax/glm/deepseek | Vikey.ai | — | FAIL (502) | — |

**Winner: gemini-3.5-flash-lite** — tercepat, gratis, akurat.

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
  Response: {"status": "ok", "uptime_s": 920, "worker_alive": true}

GET /metrics
  Response: {queue:{done:4}, quota:{remaining_today:1496}, worker:{jobs_done:4}}

GET /docs
  Swagger UI interaktif
```

### Menjalankan Service

```powershell
# Start manual
cd C:\Coding\Komdigi
uv run python start_service.py --host 0.0.0.0 --port 8080

# Auto-start saat boot (jalankan sebagai Administrator sekali)
.\setup_autostart.ps1

# Monitor log real-time
Get-Content outputs\logs\service.log -Wait -Tail 20
```

---

## Known Limitations & Roadmap v1.1

### Limitasi v1.0

| Issue | Dampak | Priority |
|-------|--------|----------|
| Chrome CDP tidak bisa dipanggil dari worker thread | Turnstile/GeeTest FAIL via service (PASS standalone) | High |
| Single-threaded worker | Max ~100 captcha/jam | Medium |
| Auto-start butuh run-as-Admin manual | Sekali setup | Low |

### Roadmap v1.1

- Fix Chrome CDP threading (subprocess terpisah / asyncio.run di thread baru)
- Multi-worker support (N worker thread dari config)
- Telegram/Discord alert (quota < 100 atau error rate tinggi)
- Dashboard web monitoring
- Support hCaptcha
- latency_ms tracking per attempt

---

## Perintah Penting

```powershell
# Unit tests
uv run pytest -o pythonpath=src -q

# Benchmark
uv run python -m komdigi_bot.benchmark --site solvecaptcha --runs 1

# Test Chrome CDP standalone
uv run python real_browser_test.py

# Submit job ke service
$body = '{"url":"https://solvecaptcha.com/demo/image-captcha"}'
Invoke-RestMethod http://localhost:8080/solve -Method Post -Body $body -ContentType "application/json"

# Cek metrics
Invoke-RestMethod http://localhost:8080/metrics | ConvertTo-Json -Depth 3
```

---

*komdigi-bot v1.0 — Built with Google Gemini AI Studio + Playwright + Chrome CDP*
*Release: 2 Oktober 2026 | Author: naufalhalims*
