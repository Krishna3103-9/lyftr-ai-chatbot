# Lyftr AI — LLM Chatbot with Key Failover & Response Caching

React frontend · FastAPI backend · SQLite storage · LiteLLM gateway.

Repository: `https://github.com/Krishna3103-9/lyftr-ai-chatbot`

## 1. Live URLs

| Tier | URL | Status |
| --- | --- | --- |
| Frontend | `https://krishna3103-9.github.io/lyftr-ai-chatbot/` | Public (GitHub Pages, `gh-pages` branch) |
| Backend | `https://flying-sku-atom-shape.trycloudflare.com` | Public (Cloudflare quick tunnel to the running backend) |
| Health check | `https://flying-sku-atom-shape.trycloudflare.com/health` | 200 with 2 keys and cache enabled |
| Demo video | See `DEMO_VIDEO_SCRIPT.md` | 2–3 min walkthrough script |
| Source | `https://github.com/Krishna3103-9/lyftr-ai-chatbot` | Public |

> **Demo provider:** no paid keys were available, so the live pool uses two
> distinct demo keys (`demo-key-1`, `demo-key-2`) with the free no-signup
> Pollinations OpenAI-compatible endpoint (`LLM_API_BASE`,
> `LLM_MODEL=openai/openai-fast`). That endpoint allows roughly one live call
> per 45 seconds per IP, so cache hits and simulated failover are instant while
> repeated *unique* live prompts may be rate-limited. Replace `LLM_API_KEYS` /
> `LLM_MODEL` / `LLM_API_BASE` with real provider keys for production. The
> quick-tunnel backend URL is temporary; `render.yaml` and section 2 provide a
> permanent hosted backend.

## 2. Run locally: with Docker and without

### With Docker (mandatory path)

```bash
cp .env.example .env
# 1. Put at least two real API keys in LLM_API_KEYS (comma-separated).
# 2. Keep ENABLE_FAILURE_SIMULATION=true to use the test hook.
make up
# Frontend: http://localhost:3000   Backend: http://localhost:8000/health
make down
```

`make up` builds both multi-stage images and starts both services. The SQLite
file lives at `/data/app.db` on the named Docker volume `app_data`, so history
survives container restarts. `make logs` tails the services and `make test`
runs the backend suite.

### Without Docker

Backend (Python 3.11+):

```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate     macOS/Linux: source .venv/bin/activate
pip install -r requirements-dev.txt
# Windows PowerShell:
#   $env:DATABASE_URL="sqlite:///./data/app.db"
#   $env:LLM_API_KEYS="key-one,key-two"
#   $env:ENABLE_FAILURE_SIMULATION="true"
# macOS/Linux:
export DATABASE_URL=sqlite:///./data/app.db
export LLM_API_KEYS=key-one,key-two
export ENABLE_FAILURE_SIMULATION=true
uvicorn app.main:app --reload --port 8000
```

Frontend (Node 20.19+ / 22+):

```bash
cd frontend
npm install
# Windows PowerShell: $env:VITE_API_BASE_URL="http://localhost:8000"
export VITE_API_BASE_URL=http://localhost:8000
npm run dev     # http://localhost:3000
npm run build   # production bundle in dist/
```

Tests: `cd backend && python -m pytest` (11 tests: health, validation,
multi-turn, sessions, system prompt, failover, 503, cache labels/tokens).

### Deploying the live tiers

1. **Backend — Render (Web Service):** connect this repo, root directory
   `backend`, build `pip install -r requirements.txt`, start
   `uvicorn app.main:app --host 0.0.0.0 --port $PORT`. Add a persistent disk
   mounted at `/data` and set `DATABASE_URL=sqlite:////data/app.db`,
   `LLM_API_KEYS`, `ALLOWED_ORIGINS=https://<frontend-host>`,
   `ENABLE_FAILURE_SIMULATION=true`. Railway/Fly.io work the same way.
2. **Frontend — Vercel/Netlify/Cloudflare Pages:** framework Vite, root
   directory `frontend`, build `npm run build`, output `dist`, environment
   variable `VITE_API_BASE_URL=https://<backend-host>`.
3. Add the deployed frontend origin to the backend's `ALLOWED_ORIGINS` and
   redeploy the backend. Both URLs must be public and reachable without login.

## 3. Design decisions: key fallback, caching, SQLite session storage

**Key fallback.** `LLMService` owns an ordered pool built from `LLM_API_KEYS`
(`key_1`, `key_2`, …). Each key may be plain (uses `LLM_MODEL`) or written as
`model|api_key` to span providers/models. Every request walks the pool in order
and calls `litellm.completion(..., api_key=key)`. Provider exceptions (429,
quota, 5xx, auth, network, timeout) advance to the next key; the response counts
`fallback_attempts` and reports only `key_id` (never the secret). If all keys
fail the endpoint returns exactly `503 {"detail": "all providers unavailable"}`
and nothing is written to SQLite. `X-Simulate-Failure` is parsed per request and
short-circuits chosen keys with synthetic statuses; it is ignored unless
`ENABLE_FAILURE_SIMULATION=true`.

**Caching.** LiteLLM's built-in cache is enabled at startup
(`litellm.Cache(type="local")`, or `disk` via `LITELLM_CACHE_TYPE`) and every
call passes `caching=True`. Its key is the model plus the full message list
(system prompt + stored history + new message), so the same first message in a
new session is a hit and a different message is always a miss. A hit is detected
from `response._hidden_params["cache_hit"]`; it returns the identical reply and
the usage stored with the cached response, with `resolution_source=LLM_CACHE`,
`key_id=null`, `fallback_attempts=0` and lower latency because no provider is
contacted. Live calls report `LIVE_INFERENCE` with the key that answered.

**SQLite session storage.** SQLAlchemy creates the `messages` table on startup
with the columns from the brief (`id`, `session_id`, `role`, `content`,
`metadata`, ISO-8601 `created_at`) plus an index on `(session_id, id)`. A small
`chat_sessions` table stores each session's system prompt, which is never shown
as a message. `DATABASE_URL` points at `/data/app.db` under a named Docker
volume (WAL mode enabled for concurrent reads). Only successful requests are
persisted: the user turn and the assistant turn with its metadata JSON are
committed together. `GET /sessions/{id}/messages` returns history oldest-first,
without the system prompt, and `404 session not found` for unknown ids.

## 4. Verification: how to see failover, cache hits and per-message token usage

```bash
BASE=http://localhost:8000

# 1. Health (200, two keys, cache enabled)
curl -s $BASE/health

# 2. Live call — note LIVE_INFERENCE, key_1, input/output tokens, latency
curl -s -X POST $BASE/chat -H 'Content-Type: application/json' \
  -d '{"session_id":"s-7f3a","message":"What is the capital of France?"}'

# 3. Cache hit — same message/model/system prompt in a NEW session
curl -s -X POST $BASE/chat -H 'Content-Type: application/json' \
  -d '{"session_id":"s-9999","message":"What is the capital of France?"}'
# -> resolution_source LLM_CACHE, identical reply, key_id null, ~0-5 ms

# 4. Different message — must be LIVE_INFERENCE again
curl -s -X POST $BASE/chat -H 'Content-Type: application/json' \
  -d '{"session_id":"s-8888","message":"What is the capital of Italy?"}'

# 5. Failover — key_1 simulated 429, key_2 answers
curl -s -X POST $BASE/chat -H 'Content-Type: application/json' \
  -H 'X-Simulate-Failure: key_1=429' \
  -d '{"session_id":"s-fail","message":"Explain caching in one line."}'

# 6. Every key fails — clean 503, no history written
curl -i -X POST $BASE/chat -H 'Content-Type: application/json' \
  -H 'X-Simulate-Failure: *=429' \
  -d '{"session_id":"s-none","message":"hi"}'
curl -s -o /dev/null -w '%{http_code}\n' $BASE/sessions/s-none/messages   # 404

# 7. Stored history, oldest first
curl -s $BASE/sessions/s-7f3a/messages
```

In the UI each assistant card shows the four required metadata fields next to
the reply: source badge, model, latency in ms, and per-request input/output
token counts (plus the key id and fallback count when useful). A 422/503 is
rendered as a readable red error card, never a blank screen. The demo video
walks through these same seven checks.

## 5. Setup Used

- **Editor:** Visual Studio Code (Windows 11), integrated terminal.
- **AI tools:** GitHub Copilot / ChatGPT and the OpenCode coding assistant.
- **Runtime:** Python 3.13 locally (3.12 slim in Docker), Node 22 with Vite 7
  and TypeScript 5.9, SQLite via SQLAlchemy, LiteLLM 1.111.
- **Verification:** `pytest` (11 tests), `npm run build`, manual curl requests.
  Docker/Node were not preinstalled in the authoring environment, so portable
  Node 22 was used for the production build check.

## 6. Bonus features (if any): what you added beyond the requirements and why

- **Session system-prompt editor** (gear button) so behaviour can be changed
  per session; stored in SQLite and included in the cache key.
- **Key/fallback chips** in the UI to make failover visible during a demo.
- **New-chat button and clickable prompt suggestions** for a smoother demo.
- **Health pill** in the header showing configured keys and cache state.
- **WAL mode, indexed history, non-root runtime images, health checks, uniform
  JSON error handler, and CORS from `ALLOWED_ORIGINS`** for resilience/security.
- **Multi-model key pool** via `model|api_key` entries, and a `disk` cache option
  when answers should survive a container restart.
- **Backend test suite** with deterministic fakes so failover/cache behaviour is
  reproducible without spending real API credits.
