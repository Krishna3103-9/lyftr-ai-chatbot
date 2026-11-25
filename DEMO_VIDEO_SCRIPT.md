# Demo video script (2–3 minutes, with voice)

Record at 1280×720 or higher. Keep the browser DevTools Network tab visible for
the latency/token checks, then switch to the chat UI for the visual walkthrough.

## 0:00–0:20 — Intro and live URLs

> "Hi, this is my Lyftr AI full-stack assignment. The frontend is deployed on
> GitHub Pages and the FastAPI backend is publicly reachable through a Cloudflare
> tunnel. The repository is public on GitHub. The app uses React, FastAPI,
> SQLite, and LiteLLM for the model gateway, caching, and key failover."

Show: `https://krishna3103-9.github.io/lyftr-ai-chatbot/` and
`https://flying-sku-atom-shape.trycloudflare.com/health`.

## 0:20–0:45 — Health and repository

> "The health endpoint returns 200, two configured keys, and cache enabled.
> The repo contains backend, frontend, docker-compose, Makefile, environment
> example, README, and a passing pytest suite."

Show `/health` JSON, then the repo file tree.

## 0:45–1:20 — Live inference and multi-turn context

> "I'll ask the first question in the UI. The reply is labelled LIVE_INFERENCE,
> with the model name, server latency in milliseconds, and the input and output
> tokens for this request only. I'll ask a follow-up, and the backend sends the
> stored history from SQLite so the bot remembers the earlier turn."

Type: "What is the capital of France?" then "What country is that in?"
Show both assistant metadata rows.

## 1:20–1:45 — Cache hit across a new session

> "Now I repeat the exact first question in a brand-new session using the API.
> Because the cache key is the model plus the full message list, the second
> request is answered by LiteLLM's built-in cache: identical text, LLM_CACHE,
> null key id, zero fallback attempts, the same stored token usage, and much
> lower latency."

Run the two `curl` commands from README section 4 (steps 2 and 3).

## 1:45–2:20 — Key failover and clean 503

> "With the failover test hook enabled, I simulate a 429 on key one. The app
> automatically retries with key two and returns a real answer, with one
> fallback attempt. Finally, simulating a 429 on every key gives a clean 503
> with the detail 'all providers unavailable', and nothing is written to the
> session history."

Run:
`curl -H 'X-Simulate-Failure: key_1=429' ... /chat`
then `curl -H 'X-Simulate-Failure: *=429' ... /chat`
and `curl .../sessions/s-none/messages` to show the 404.

## 2:20–2:50 — History, Docker and wrap-up

> "The history endpoint shows the stored turns oldest first, without the system
> prompt. Locally, the entire stack starts with `make up`: backend on port 8000
> and frontend on port 3000, with SQLite on a named Docker volume at
> /data/app.db. Multi-stage Dockerfiles keep both runtime images small. That
> covers resilience, caching, per-request token tracking, multi-turn state, and
> deployment — thank you."

Show `GET /sessions/<id>/messages`, then `make up` and `docker compose ps`.
