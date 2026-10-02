# Draft: captcha-computeruse-bot

## State
- slug: captcha-computeruse-bot
- intent: clear
- review_required: false
- classification: Architecture (5+ modules, long-term)
- status: plan-written (awaiting Metis gap analysis, then handoff)
- pending-action: write and review .omo/plans/captcha-computeruse-bot.md
- scaffold note: planner session has NO shell tool; scaffold script could not be run; plan + draft written by hand following the script-emitted template verbatim (template source: ulw-plan references/full-workflow.md "Plan template" section)

## Request (verbatim intent)
User: buat bot otomatis yang bisa bypass berbagai level captcha otomatis setiap masuk ke suatu platform — RANCANG dulu, tidak dibangun sekarang ("saya tidak jadi"); pelajari human-like bot lama user (vault memory + VPS + private GitHub repo); pecahkan game puzzle 2captcha demo. Later additions: gunakan Jev dari TypeSafe AI (key user, prefix `apikey_...`, asal: console.typesafe.ai) + LLM reasoning untuk computer-use bot; LLM boleh pakai key OpenCode user; benchmark LLM terbaik untuk kapabilitas ini. Semua kunci masuk .env, tidak di-hardcode.

## Owner decisions (all answered via question tool, all recommended options)
1. VPS access: **Repo + worker nanti** — communiteyes-pro repo adalah sumber rujukan; inspeksi live AWS Lightsail (Ireland) oleh worker saat eksekusi bila perlu (read-only).
2. JEV key origin: **console.typesafe.ai official** — env `TYPESAFE_API_KEY`, endpoint `https://api.typesafe.ai/v1/systemone`; rencana tetap memuat probe validasi murah (satu panggilan noul) sebelum lapisan dibangun.
3. Solver strategy family berat (Arkose/FunCaptcha, GeeTest v4, reCAPTCHA Enterprise): **Hybrid** — in-house (stealth + vision LLM) jalur pertama semua family; solver-API pihak ketiga (2captcha) hanya fallback terkonfigurasi via .env untuk family berat.
4. Test strategy: **Tests-after + agent QA** — integration test per solver engine (demo page sebagai fixture) + happy/failure scenario dengan evidence path.

## Adopted defaults (vetoable)
- Stack: Python 3.11+ (kontinuitas communiteyes-pro, Playwright-python, typesafe-sdk) + uv + pydantic-settings + python-dotenv.
- Target operasi: authorized-use framing (aset/platform milik user, security testing, riset); demo 2captcha sebagai fixture pengujian publik.
- `.gitignore` dibuat paling awal sebelum `.env` ada isinya; kunci tidak pernah di-hardcode, tidak pernah di-commit, tidak ditulis literal di artefak plan.
- Kunci sudah terekspos di transcript sesi (.claude/transcripts/*.jsonl plaintext) — rotasi disarankan; worker menerima nilai kunci dari user saat eksekusi.

## Topology (5 components)
1. Stealth browser layer — port communiteyes-pro (session rotation, init scripts, launch flags, human_* behavior, persistent authenticated profile, SOCKS5 optional)
2. Triage layer — Jev choice (family detection dari DOM/script signature) + noul gating + routing
3. Solver engines per family — text reasoning, image OCR vision, click coords, rotate/slide drag, checkbox/grid reCAPTCHA; hybrid fallback solver-API untuk family berat
4. Benchmark harness — validasi key Jev + benchmark kandidat LLM (via key OpenCode user) pada tugas captcha nyata; pin model per task type
5. Orchestrator + telemetry — retry ladder (Jev score), identity rotation, self-healing iteration engine, evidence log

## Key findings index (paths)
- Vault memory: `C:\Users\Naufal Halim\vault\` (AGENTS.md: 3-tier fallback Content Researcher; medium_premium_scraper.py di `10_Projects\Content Researcher\scripts\`; `memory\coding_projects_ingestion.md`: username GitHub naufalhalims, 19 repos; CommunitEyes docs di `30_Resources\Wiki\projects\communiteyes\`)
- Private repo (librarian deep-dive, SHA 22d74b4efb4c0fb4b5408e5639216f4a80ac044c): https://github.com/naufalhalims/communiteyes-pro — scraper/session_manager.py, scraper/stealth_browser.py, scraper/hermes_human_bot.py, scraper/hermes_browser_agent.py, scraper/decrypt_cookies.py, login_via_vps.py, scraper/continuous_scraper.py, config.yaml, iteration_engine pattern; VPS: AWS Lightsail Ireland, systemd hermes-scraper.service, webhook → dashboard Mini PC :8504 via Cloudflare Tunnel; produksi https://social-network.naufalhal.tech
- Gen-1 notebook: `C:\Users\Naufal Halim\Scraping Twitter.ipynb` (Selenium login + scroll harvest)
- Gen-2: `C:\Users\Naufal Halim\vault\10_Projects\Content Researcher\scripts\medium_premium_scraper.py`
- Demo POC (2captcha): Text Captcha SOLVED (reasoning "Friday"); Normal Captcha SOLVED (vision "W9H5K" + pressSequentially + Check → "Captcha is passed successfully!"); Turnstile: silent no-render pada browser otomatis vanilla (iframe null, script loaded) → stealth layer prasyarat; evidence: `.omo/evidence/normal-captcha-page.png` + `.omo/evidence/normal-captcha.png`
- Vision gap: model sesi planner (opencode-go/glm-5.3) non-vision-capable; jalur vision berhasil via sesi multimodal look_at; konsekuensi desain: lapisan LLM bot wajib vision-capable, akurasi transkripsi = metrik benchmark utama
- Jev: https://www.jevtypesafeai.com/how-to-use (POST api.typesafe.ai/v1/systemone, Bearer, state/questions choice|score|noul, jev-latest, 64k ctx, 1200 req/min), SDK `typesafe-sdk`, LangChain TypeSafeClassifier; rate docs https://vercel.com/ai-gateway/models/jev
- Benchmark riset: OSWorld-Verified 2026 (Claude Opus 4.8 83.4% > human 72.4%; open-SOTA Qwen3-VL-235B 66.7%; Kimi K2.5 63.3%); OSWorld-Pro (Opus 4.8 Max 77.7%); WebVoyager (Surfer 2 97.1%); pola pemenang: modular Planner+Grounder+Executor+Verifier; UI grounding = failure mode #1; "harness matters more than the model"; Cloudflare/Arkose/hCaptcha men-skor pola trafik AI-browser
- 2captcha demo set: https://2captcha.com/demo (+ /normal, /text, /clickcaptcha, /rotatecaptcha, /geetest, /cloudflare-turnstile dengan test sitekey 3x00000000000000000000FF, protocol in.php/res.php terdokumentasi di tiap halaman)

## Approval
- Brief presented (findings + topology + 4 fork questions via question tool) — user answered ALL forks with recommended options → approval per ulw-plan contract (answering open ambiguities = approval). Plan authorized to be WRITTEN only; execution belongs to worker session (e.g. $start-work).
