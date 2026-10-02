# captcha-computeruse-bot - Work Plan

## TL;DR (For humans)

**Apa yang kamu dapat:** Bot Python "computer-use" di repo KOMDIGI yang bisa masuk ke suatu platform dan melewati captcha secara otomatis lintas family — dibangun di atas teknik human-like bot kamu sendiri yang sudah terbukti di `communiteyes-pro`, ditambah dua otak baru: **Jev** (TypeSafe AI) sebagai lapisan keputusan cepat ter-tipe, dan **LLM vision-capable** (via key OpenCode kamu, dipilih lewat benchmark) sebagai lapisan reasoning.

**Kenapa pendekatan ini:** (1) Teknik stealth kamu sudah terbukti produksi — hasil riset vault + repo private memuat semuanya (rotasi profil, init-script anti-deteksi, perilaku manusia ber-jitter, cookie ter-autentikasi). (2) POC hidup di demo 2captcha membuktikan dua jalur solver bekerja: reasoning murni (Text Captcha ✅) dan vision (Normal Captcha ✅), plus temuan kritis bahwa Turnstile menolak render di browser otomatis vanilla → stealth layer adalah prasyarat, bukan fitur. (3) Arsitektur Jev+LLM mengikuti pola pemenang benchmark computer-use 2026: modul Planner+Grounder+Executor+Verifier.

**Yang TIDAK akan dilakukan:** Tidak menyerang platform pihak ketiga tanpa otorisasi eksplisit kamu (framing authorized-use: aset milikmu, security testing, riset); tidak ada fitur mass-account/spam/registration; kunci API tidak pernah di-hardcode (hanya .env, gitignored, ditulis saat eksekusi); repo `communiteyes-pro` tidak diubah (hanya referensi); tidak ada mutasi VPS (inspeksi read-only oleh worker bila perlu).

**Effort:** 10 todo implementasi dalam 2 wave + 4 final verifier; Python 3.11+/uv/Playwright/pydantic-settings.

**Risk:** (a) Key Jev `apikey_...` belum terverifikasi asal-usulnya — mitigasi: probe validasi murah di todo 4 sebelum lapisan dibangun; (b) family captcha berat (Arkose 3D, GeeTest v4) sulit in-house — mitigasi: kebijakan hybrid dengan fallback solver-API terkonfigurasi; (c) model vision lewat key OpenCode belum dibenchmark — mitigasi: harness benchmark di todo 9 memilih + mem-pin model; (d) Turnstile di luar demo bisa lebih agresif daripada test-sitekey — mitigasi: stealth layer + retry ladder + fallback API.

**Decisions (keputusan kamu, terkunci):** VPS = repo + worker nanti; key Jev = console.typesafe.ai official (`TYPESAFE_API_KEY`, `api.typesafe.ai/v1/systemone`); solver = hybrid (in-house first, solver-API fallback untuk family berat via .env); test = tests-after + agent QA. Default yang diadopsi: stack Python, `.gitignore` sebelum `.env`, kunci masuk saat eksekusi lewat worker.

## Scope

**IN — 5 komponen (topologi terkonfirmasi):**
1. **Stealth browser layer** — port teknik `communiteyes-pro`: rotasi profil sesi (4 viewport × 4 UA), launch flags (`--disable-blink-features=AutomationControlled`, `--no-sandbox`, window-size), init-script (navigator.webdriver undefined, plugins, languages, window.chrome.runtime), perilaku manusia (`human_click` random-in-bbox, `human_type` per-karakter 30–120ms, `human_scroll` + scroll-back 30%, `_human_delay` jitter), persistent authenticated profile opsional (pola `login_x.py`/storage_state), SOCKS5 tunnel opsional (pola `login_via_vps.py`).
2. **Triage layer** — deteksi family captcha dari DOM/script signature (recaptcha/google.com/recaptcha, hcaptcha, turnstile/challenges.cloudflare.com + window.turnstile, arkose/funcaptcha, geetest, form image/text/click/rotate) + routing via Jev `choice` + gating via Jev `noul`.
3. **Solver engines per family** — `text_reasoning` (LLM), `image_ocr` (vision LLM → pressSequentially → submit; pola terbukti "W9H5K"), `click_coords` (vision → koordinat), `rotate_slide` (vision → sudut/jarak → drag trajectory ber-ritme manusia), `checkbox_grid` (stealth + click; grid multi-select via vision); LLM provider abstraction OpenAI-compatible (base URL + key dari .env = key OpenCode kamu; WAJIB vision-capable).
4. **Hybrid fallback** — adapter solver-API 2captcha (protocol `in.php`/`res.php` + token injection `cf-turnstile-response`/callback, terdokumentasi di halaman demo) HANYA untuk family berat yang terdaftar config: arkose, geetest_v4, recaptcha_enterprise; env `SOLVER_API_KEY_2CAPTCHA` opsional.
5. **Orchestrator + telemetry + benchmark** — retry ladder dipacing Jev `score`, rotasi identitas antar attempt, pola self-healing iteration engine (port pola `continuous_scraper.py`/iteration engine), evidence log `outputs/evidence/attempts.jsonl` + screenshot per attempt; harness benchmark kandidat LLM via key OpenCode (transkripsi/grid/koordinat/latency/cost) → pin model per task ke config.

**OUT / Must-NOT-Have:**
- TIDAK menargetkan platform pihak ketiga apa pun di luar halaman demo publik 2captcha tanpa otorisasi eksplisit user tertulis pada sesi eksekusi.
- TIDAK ada fitur pembuatan akun massal, spam, atau registrasi otomatis.
- TIDAK ada kunci/secret di-hardcode, di-commit, atau ditulis literal di source/artefak (hanya `.env.example` berisi placeholder; `.gitignore` menutup `.env` SEBELUM file tersebut pernah berisi nilai).
- TIDAK mengubah repo `naufalhalims/communiteyes-pro` (read-only reference; clone gitignored).
- TIDAK ada mutasi VPS AWS Lightsail (worker hanya boleh inspeksi read-only bila perlu, sesuai keputusan user "repo + worker nanti").
- TIDAK memperluas family captcha di luar daftar scope tanpa re-plan (user meminta "berbagai level captcha" — tercakup: normal/text/click/rotate/geetest/recaptcha-v2-checkbox+grid/hcaptcha-mirror/turnstile/arkose-fallback/enterprise-fallback).

## Verification strategy

- **Tests-after + agent QA** (keputusan user). Setiap solver engine mendapat integration test yang dieksekusi agent dengan halaman demo publik 2captcha sebagai fixture (halaman tersebut memang dibuat untuk menguji solver; test-sitekey Turnstile `3x00000000000000000000FF` selalu pass) — plus unit test untuk logika murni (rotasi, triage fixture HTML, retry ladder, policy mapping) dan mocked-HTTP test untuk klien Jev & adapter solver-API.
- **Happy path per family:** pesan `"Captcha is passed successfully!"` terdeteksi di snapshot halaman (pola terbukti di sesi riset: `browser_find`/page content assert) + screenshot evidence `outputs/evidence/<family>-solved.png`.
- **Failure path per family:** jawaban salah → orchestrator mencatat attempt gagal di `outputs/evidence/attempts.jsonl`, memutar profil, menjalankan retry ladder (maks dari config), lalu melaporkan kegagalan terstruktur — TIDAK ada exception yang telanjang atau hang.
- **Bukti anti-bocor kunci:** `git grep -I -nE "(apikey_|jv_live_|sk-|TYPESAFE_API_KEY=|OPENCODE_API_KEY=|SOLVER_API_KEY=)[A-Za-z0-9]"` di history + worktree harus kosong (kecuali `.env.example` placeholder).
- **Final verification wave** F1–F4 (di bawah) — semua harus APPROVE.

## Execution strategy

- Stack: Python 3.11+, `uv`, Playwright (chromium `channel="chrome"`), `pydantic-settings` + `python-dotenv`, `typesafe-sdk` (atau httpx raw), pytest + ruff + basedpyright.
- **Wave 1 (fondasi & keputusan):** todo 1–5 — bootstrap repo + `.gitignore`-first + `.env.example` → vendor-reference clone + port config → stealth browser layer → klien Jev + probe validasi key → triage engine. Todo 3 bergantung 1–2; todo 4–5 bergantung 1–2 (4) dan 3 (5).
- **Wave 2 (solver & integrasi):** todo 6–10 — solver engines in-house → hybrid fallback adapter → orchestrator + telemetry → benchmark harness LLM → e2e demo set + docs. Bergantung wave 1 penuh; 8 bergantung 6+7; 9 mem-pin model untuk 6; 10 integrasi penuh.
- **Matriks dependensi:** 1→2→{3,4}; {3,4}→5; 5→{6,7}; {6,7}→8; {6,8}→9; {8,9}→10; 1..10→F{1..4}.
- Urutan kerja wajib: `.gitignore` ditulis dan di-commit SEBELUM `.env` dibuat berisi nilai apa pun; kunci diterima worker dari user pada sesi eksekusi (user memegang nilai; planner sengaja tidak menuliskannya di artefak).
- Vendor reference: `gh repo clone naufalhalims/communiteyes-pro vendor-reference/communiteyes-pro` (gh sudah ter-autentikasi sebagai naufalhalims — terverifikasi sesi riset; folder digitignore).

## Todos

- [ ] 1. Bootstrap proyek KOMDIGI bot (Python 3.11+/uv, .gitignore-FIRST, .env.example, struktur paket)
  - **References:** root `E:\Coding\Coding\KOMDIGI` (repo kosong, belum ada commit — verifikasi `git log` kosong); template templat: `pyproject.toml` (uv, ruff, basedpyright, pytest), paket `src/komdigi_bot/` (`__init__.py`, `config.py`, `logging.py`); `.env.example` berisi HANYA placeholder: `TYPESAFE_API_KEY=` (Jev console.typesafe.ai), `LLM_BASE_URL=` + `LLM_API_KEY=` (key OpenCode user, OpenAI-compatible), `SOLVER_API_KEY_2CAPTCHA=` (opsional, default kosong); `config/config.yaml` kosong akan diisi todo 2.
  - **Acceptance:** `uv sync` sukses; `uv run python -c "import komdigi_bot"` sukses; `git status` bersih; `cat .gitignore` memuat `.env`, `vendor-reference/`, `outputs/`, `.omo/evidence/`, `__pycache__/`, `.venv/`; commit pertama ada.
  - **QA happy:** `uv run pytest` (kosong → exit 0); **QA failure:** `git check-ignore .env` mengembalikan `.env` (buat file uji `.env` dummy lalu hapus — bukti `outputs/evidence/gitignore-proof.txt` berisi output perintah).
  - **Commit:** `chore: bootstrap komdigi captcha bot skeleton with gitignore-first and env example`

- [ ] 2. Vendor-reference clone communiteyes-pro + port config schema
  - **References:** `gh repo clone naufalhalims/communiteyes-pro vendor-reference/communiteyes-pro` (repo PRIVATE, gh ter-autentikasi naufalhalims — terverifikasi sesi riset); file rujukan: `scraper/session_manager.py` (PROFILES/USER_AGENTS/rotate/random_delay/jitter_delay), `scraper/stealth_browser.py` (launch args + init script + human_*), `config.yaml` (interval_seconds 1800, jitter_seconds 180, dsb.); port ke `src/komdigi_bot/config.py` (pydantic-settings, baca `.env` + `config/config.yaml`): schema `stealth`, `llm`, `jev`, `solver_policy` (default `hybrid`), `families` (berat: arkose, geetest_v4, recaptcha_enterprise), `retry` (max_attempts, backoff).
  - **Acceptance:** `vendor-reference/communiteyes-pro/scraper/session_manager.py` ada (bukti clone); `uv run python -c "from komdigi_bot.config import get_settings; s=get_settings(); assert s.solver_policy=='hybrid'"` sukses; config test dengan file YAML fixture lulus.
  - **QA happy:** load config default → semua nilai default terdefinisi (evidence `outputs/evidence/config-default.json`); **QA failure:** config YAML korup → pydantic raise `ValidationError` terstruktur (test), TIDAK silently-default.
  - **Commit:** `feat(config): port communiteyes-pro config schema into pydantic settings`

- [ ] 3. Stealth browser layer (port session_manager + stealth_browser + human behavior)
  - **References:** `vendor-reference/communiteyes-pro/scraper/session_manager.py` (PROFILES 4 viewport/platform/language, USER_AGENTS 4, `rotate()`, `random_delay()`, `jitter_delay(base, jitter)`); `vendor-reference/communiteyes-pro/scraper/stealth_browser.py` (launch_args: `--disable-blink-features=AutomationControlled`, `--disable-infobars`, `--no-sandbox`, `--window-size`; init script: `navigator.webdriver` undefined, `navigator.plugins` [1..5], `navigator.languages` ['id-ID','id','en-US','en'], `window.chrome={runtime:{}}`; `human_click` random-in-bbox + delay 0.1–0.4s; `human_type` per-char 30–120ms; `human_scroll` 300–800px, pause 1.0–2.5s×(1+rand), scroll-back 50–150px @30%; `_human_delay(min,max)`); juga `vault\10_Projects\Content Researcher\scripts\medium_premium_scraper.py` (pola channel="chrome", Referer t.co) sebagai pembanding. Implementasi: `src/komdigi_bot/stealth/session.py` + `src/komdigi_bot/stealth/browser.py`, Playwright sync API, `channel="chrome"`, viewport/UA/locale dari rotasi sesi.
  - **Acceptance:** unit test rotasi (4 profil siklus, deterministic seed) + delay bounds lulus; integration test: dengan stealth layer ON buka `https://2captcha.com/demo/cloudflare-turnstile` → assert iframe `challenges.cloudflare.com` RENDER (rect non-null, `window.turnstile` ada) — ini membalik temuan riset bahwa browser vanilla NO-RENDER (bukti baseline vanilla: sesi riset iframeSrc null).
  - **QA happy:** screenshot `outputs/evidence/turnstile-render.png` menampilkan widget; **QA failure:** menjalankan kontrol TANPA stealth flags → iframe null → test kontrol mendokumentasikan gap (evidence `outputs/evidence/turnstile-nostyle.json` berisi iframeSrc null) — kedua kondisi adalah assertion test.
  - **Commit:** `feat(stealth): port session rotation and human-behavior browser layer from communiteyes-pro`

- [ ] 4. Klien Jev (TypeSafe AI) + probe validasi key
  - **References:** endpoint `POST https://api.typesafe.ai/v1/systemone` Bearer `TYPESAFE_API_KEY` dari `.env`; body `{model: "jev-latest"|pin, state: string|object|array, questions: {name: {type: choice|score|noul, instructions, criteria?}}}`; response `{model, answers: {name: {choice|score|noul, probability/confidence, ...}}, usage}`; sumber terverifikasi sesi riset: jevtypesafeai.com/how-to-use + jevtypesafeai.com/docs (rate 250k tok/s, 1200 req/min, state ≤64k tok, pin versi di produksi, jangan quietly replace unavailable response dengan confident default); SDK `typesafe-sdk` alternatif httpx raw. Implementasi `src/komdigi_bot/decision/jev.py` + `src/komdigi_bot/probe/jev.py`.
  - **Acceptance:** `uv run python -m komdigi_bot.probe.jev` melakukan SATU panggilan `noul` murah (contoh instructions "Is 2+2=4?") dan menulis `outputs/evidence/jev-probe.json` (answers + usage + resolved model); unit test dengan mocked HTTP (choice/score/noul parsing, 401 → error jelas "cek asal key (console.typesafe.ai)", 502 → retry backoff); TIDAK ada silent-confident-default — failure → raise terstruktur + WARN log.
  - **QA happy:** probe.json berisi `answers.*.noul` numerik; **QA failure:** `.env` tanpa key → probe exit code ≠ 0 dengan pesan eksplisit (evidence file error-nya).
  - **Commit:** `feat(decision): jev systemone client with typed choice/score/noul wrappers and validation probe`

- [ ] 5. Triage engine (deteksi family + routing Jev)
  - **References:** signature DOM/script per family (dari riset halaman demo + praktik umum yang terverifikasi di sesi): recaptcha (`google.com/recaptcha/api2/anchor`, `grecaptcha`), hcaptcha (`hcaptcha.com/1/api.js`, iframe h-captcha), turnstile (`challenges.cloudflare.com/turnstile`, `window.turnstile`, `.cf-turnstile`), arkose (`funcaptcha`/`arkoselabs`), geetest (`geetest.com`/`gt.js`), image/text/click/rotate form (pola halaman demo 2captcha: img alt "normal captcha example", textbox placeholder "Enter answer here..."); halaman fixture: `https://2captcha.com/demo/{normal,text,clickcaptcha,rotatecaptcha,geetest,cloudflare-turnstile}`; routing via Jev `choice` (criteria = family engine map, ≤255 opsi) + pre-gate `noul` ("tidak ada captcha di halaman ini?"). Implementasi `src/komdigi_bot/triage/detector.py` + `src/komdigi_bot/triage/router.py`.
  - **Acceptance:** unit test dengan fixture HTML snippet per family (12 fixture) lulus; integration: triage dijalankan pada ≥5 halaman demo live → family benar ≥5/5 (evidence `outputs/evidence/triage-live.json` per halaman: detected family, confidence, signature yang match); Jev routing ter-record.
  - **QA happy:** family terdeteksi + confidence > threshold config; **QA failure:** halaman tanpa captcha (mis. `https://example.com`) → hasil `none` (bukan exception), routing skip.
  - **Commit:** `feat(triage): dom-signature captcha family detector with jev choice routing`

- [ ] 6. Solver engines in-house (5 engine) + LLM provider abstraction
  - **References:** pola terbukti sesi riset (WAJIB direplikasi): snapshot → screenshot elemen/viewport → transkripsi vision → `pressSequentially` (per-karakter) → click Check → assert "Captcha is passed successfully!" (Text Captcha dijawab "Friday" reasoning murni; Normal Captcha dijawab "W9H5K" vision — bukti `outputs/evidence/` sesi riset); human_* behavior dari todo 3 untuk semua interaksi; LLM provider abstraction OpenAI-compatible: `LLM_BASE_URL` + `LLM_API_KEY` (key OpenCode user) + `LLM_MODEL_VISION` + `LLM_MODEL_REASONING` (model dipin todo 9; default `LLM_MODEL_VISION` WAJIB vision-capable — temuan riset: model non-vision gagal baca gambar); engine: `src/komdigi_bot/solvers/{text_reasoning,image_ocr,click_coords,rotate_slide,checkbox_grid}.py`; prompt template per task + output parser ketat (koordinat/sudut/teks — parse error → retry).
  - **Acceptance:** integration test per engine pada halaman demo terkait: `text_reasoning` di `/demo/text`, `image_ocr` di `/demo/normal`, `click_coords` di `/demo/clickcaptcha`, `rotate_slide` di `/demo/rotatecaptcha`, `checkbox_grid` di `/demo/recaptcha-v2` (grid muncul) — masing-masing attempt tercatat di attempts.jsonl DENGAN hasil pass/fail + screenshot path; unit test parser output LLM (happy + malformed).
  - **QA happy:** ≥3 dari 5 engine mencapai "Captcha is passed successfully!" pada minimal satu attempt (evidence `outputs/evidence/<family>-solved.png`); **QA failure:** transkripsi salah satu karakter (mis. "9" vs "g" — kasus nyata sesi riset) → attempt tercatat fail, retry ladder jalan, lalu fallback family-policy (todo 7) bila family terdaftar berat; TIDAK ada loop tak berujung (max_attempts dari config).
  - **Commit:** `feat(solvers): five in-house solver engines with vision llm provider abstraction`

- [ ] 7. Hybrid fallback: adapter solver-API 2captcha untuk family berat
  - **References:** policy `solver_policy=hybrid` (keputusan user) — fallback HANYA untuk family di config `families` (arkose, geetest_v4, recaptcha_enterprise); protocol terdokumentasi di halaman demo yang dikumpulkan sesi riset: `POST https://2captcha.com/in.php` (key, method=turnstile|funcaptcha|geetest_v4..., sitekey, pageurl, json=1) → poll `GET https://2captcha.com/res.php?key=...&action=get&id=...` tiap 5s sampai `OK|token` (bukan `CAPCHA_NOT_READY`); token injection: set input `[name="cf-turnstile-response"]` (pola `document.querySelector('[name="cf-turnstile-response"]').value='TOKEN'` dari halaman demo) atau callback `turnstile.render`/`data-callback`; sitekey didapat via triage (`data-sitekey` attribute — pola `<div class="cf-turnstile" data-sitekey=...>`). Implementasi `src/komdigi_bot/solvers/api_fallback.py` + policy di orchestrator.
  - **Acceptance:** unit test policy mapping (family berat → in-house first → fallback API; family ringan → in-house only); mocked-HTTP test protocol in.php/res.php/token-injection lulus (termasuk kasus `CAPCHA_NOT_READY` 3× lalu OK); bila `SOLVER_API_KEY_2CAPTCHA` kosong → fallback dinonaktifkan dengan WARN (bukan error), family berat → report "unsolved (fallback off)".
  - **QA happy:** dengan mocked API, token diterima + diinjeksi + form disubmit (evidence `outputs/evidence/fallback-mocked.json`); **QA failure:** API 402/invalid key → error terstruktur tercatat, policy melaporkan family "unsolved", TIDAK retry tak berujung.
  - **Commit:** `feat(solvers): hybrid 2captcha api fallback adapter for heavy families behind env-gated policy`

- [ ] 8. Orchestrator + telemetry + self-healing
  - **References:** retry ladder dipacing Jev `score` (rubrik pacing: terlalu-cepat/kurang-yakin/backoff-level — bila Jev tidak tersedia: ladder deterministik dari config, dengan WARN, TIDAK silent confident default); rotasi identitas antar attempt (stealth session rotate dari todo 3); pola self-healing port dari communiteyes-pro (iteration engine: cycles 1/10/20/40/60 menit, cek health endpoint scraper freshness → restart; `scraper/continuous_scraper.py`, systemd pattern — diadaptasi ke konteks lokal: watchdog proses + resume state); evidence log `outputs/evidence/attempts.jsonl` (ts, url, family, engine, attempt_n, profile_id, result, latency_ms, screenshot_path, llm_model) + ringkasan `outputs/evidence/summary.json`; entrypoint `uv run python -m komdigi_bot --url <target> --max-attempts N`.
  - **Acceptance:** unit test ladder (attempt → fail → rotate profile → pacing naik → max attempts → stop); e2e dummy (fixture HTML lokal) menghasilkan attempts.jsonl valid (JSONL parse lulus, ≥2 baris); watchdog restart worker dummy yang sengaja di-crash (test proses terisolasi).
  - **QA happy:** run pada demo set menghasilkan summary.json dengan ≥2 family solved (bergantung todo 6); **QA failure:** seluruh attempt gagal → exit code ≠ 0 + summary.json berisi `solved: 0` + alasan per family (TIDAK hang, TIDAK exception telanjang).
  - **Commit:** `feat(orchestrator): retry ladder with jev pacing, identity rotation, self-healing and attempts telemetry`

- [ ] 9. Benchmark harness LLM (via key OpenCode user) + pin model
  - **References:** kandidat dari riset benchmark 2026 sebagai shortlist awal (dipilih via key OpenCode user sesuai ketersediaan): tier closed (Claude Opus/Sonnet 4.8+, GPT-5.x, Gemini 3.x Pro/Flash — pemimpin OSWorld-Verified 2026, Opus 4.8 83.4% > human 72.4%), tier open (Qwen3-VL-235B/72B — open-SOTA 66.7%, Kimi K2.5 — 63.3%); enumeration: daftar model tersedia via config/OpenCode key user (bila endpoint enumerasi tidak tersedia: shortlist riset + konfirmasi user di sesi eksekusi — pertanyaan tunggal, bukan judgment bebas); task suite: (a) transkripsi — ≥20 gambar captcha normal (dikumpulkan dari demo `/demo/normal` tombol Reset; ground truth = jawaban lolos server), (b) grid-selection — fixture reCAPTCHA-style grid, (c) presisi koordinat — target elemen dengan bbox diketahui ( Playwright bounding box sebagai ground truth), (d) latency per task, (e) estimasi biaya per 1000 solve; metrik WAJIB mengukur akurasi transkripsi (temuan riset: ini penentu utama); artifact `outputs/benchmarks/leaderboard.md` + `outputs/benchmarks/results.json`; hasil mem-pin `LLM_MODEL_VISION` + `LLM_MODEL_REASONING` di `config/config.yaml` (pin versi eksplisit, pola "pin model version in production" dari docs Jev).
  - **Acceptance:** harness menjalankan ≥3 kandidat × suite (a)-(e); leaderboard.md ter-generate dengan ranking + rekomendasi; config ter-update dengan model pin; TIDAK ada key/value kunci di artifact (hanya nama model + angka).
  - **QA happy:** vision winner akurasi transkripsi ≥60% pada dataset (threshold inisial — pola POC riset: 5/5 karakter benar pada 1 sampel); **QA failure:** kandidat <3 tersedia → harness tetap menghasilkan leaderboard dengan kandidat yang ada + catatan keterbatasan (bukan kegagalan silent).
  - **Commit:** `feat(bench): llm benchmark harness for captcha tasks with leaderboard and model pinning`

- [ ] 10. E2E demo set + README etis + authorized-use framing
  - **References:** demo set final: `https://2captcha.com/demo/{normal,text,clickcaptcha,rotatecaptcha,geetest,cloudflare-turnstile}` (Turnstile demo = test-sitekey `3x00000000000000000000FF` selalu-pass — cocok untuk menguji stealth render + jalur fallback token, BUKAN indikator kemampuan bypass Turnstile produksi — catat eksplisit di README); README.md: arsitektur (5 komponen + diagram), setup (`uv sync`, `.env` dari `.env.example`, playwright install), cara pakai (entrypoint), hasil benchmark + bukti demo, bagian **Authorized Use & Batasan**: hanya untuk platform/aset milik user, security testing, dan riset; menghormati ToS/hukum berlaku; tidak untuk mass-registration/spam; kunci .env-only; CHANGELOG.md.
  - **Acceptance:** `uv run python -m komdigi_bot --url https://2captcha.com/demo/normal --max-attempts 5` mencapai solved dengan screenshot bukti; run serupa pada ≥2 family lain; README lengkap dengan semua section di atas; `grep -L "api key" README` — TIDAK ada nilai kunci di docs.
  - **QA happy:** summary.json final menampilkan ≥3 family solved lintas run; **QA failure:** satu family gagal → tetap tercatat dengan alasan + screenshot attempt terakhir (bukti run, bukan silent-skip).
  - **Commit:** `docs(e2e): demo-set runbook, ethical authorized-use readme, and final integration`

## Final verification wave

- [ ] F1. Plan compliance audit — verifikasi setiap todo 1–10 selesai sesuai rencana: setiap References yang disebut ada/di-eksekusi, setiap Acceptance criteria terpenuhi, setiap evidence path (`outputs/evidence/*`, `outputs/benchmarks/*`) eksis dan berisi. Output: audit report di `outputs/evidence/f1-audit.md` dengan verdict APPROVE/REJECT per todo.
- [ ] F2. Code quality review — `uv run ruff check .` dan `uv run basedpyright .` bersih (atau semua finding diperbaiki/di-suppress dengan alasan tertulis); scan bocor kunci: `git grep -I -nE "(apikey_|jv_live_|sk-|TYPESAFE_API_KEY=|OPENCODE_API_KEY=|SOLVER_API_KEY=)[A-Za-z0-9]"` harus kosong di worktree + `git log -p | grep -E "(apikey_|jv_live_)[A-Za-z0-9]"` kosong di history. Output: `outputs/evidence/f2-quality.md`.
- [ ] F3. Real manual QA (agent-executed) — jalankan orchestrator live pada demo set ≥4 family; verify "Captcha is passed successfully!" pada ≥3 family termasuk ≥1 family vision (image_ocr atau rotate/click); kumpulkan screenshot solved per family di `outputs/evidence/f3-*/`. Verdict per family + overall.
- [ ] F4. Scope fidelity — audit Must-NOT-Have: tidak ada penargetan pihak ketiga di luar demo publik; tidak ada fitur mass-account/spam; tidak ada nilai kunci di repo/artefak/history; `communiteys-pro` vendor-reference tidak dimodifikasi (`git -C vendor-reference/communiteyes-pro status` bersih); tidak ada mutasi VPS. Output: `outputs/evidence/f4-scope.md` dengan checklist PASS/FAIL per item Must-NOT-Have.

## Commit strategy

- Conventional commits per todo (pesan commit sudah ditentukan di tiap todo di atas); commit hanya setelah acceptance + QA todo itu lulus.
- Sebelum setiap commit: `git status` wajib bersih dari `.env` dan `outputs/` (gitignored) — verifier F2 meng-audit ini.
- Wave 1 ditutup dengan tag `wave-1`, wave 2 dengan tag `wave-2`; handoff final = merge/commit `docs(e2e)` + tag `v0.1.0`.

## Success criteria

1. Stealth layer membalik temuan riset: Turnstile iframe RENDER di browser otomatis dengan stealth ON (vs null tanpa stealth) — bukti `outputs/evidence/turnstile-render.png` + `turnstile-nostyle.json`.
2. Probe Jev lolos: `outputs/evidence/jev-probe.json` berisi answers ter-tipe + usage (key `TYPESAFE_API_KEY` valid terhadap `api.typesafe.ai/v1/systemone`).
3. ≥3 family demo 2captcha SOLVED live dengan bukti screenshot + "Captcha is passed successfully!", termasuk ≥1 family vision — dicatat di `outputs/evidence/summary.json`.
4. Benchmark leaderboard ter-generate (≥3 kandidat, ≥5 metrik) + model vision/reasoning ter-pin di config; akurasi transkripsi winner ≥60%.
5. Semua F1–F4 APPROVE; zero kebocoran kunci di repo/history/artefak.
6. Must-NOT-Have terpenuhi seluruhnya (F4 checklist PASS semua).
