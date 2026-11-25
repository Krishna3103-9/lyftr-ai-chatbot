"""Build DEMO.mp4: narrated slides from the verified live run.

Usage:
  python tools/make_demo.py slides   # writes PNG frames + narration text files
  (PowerShell) generate WAVs from narration files with System.Speech
  python tools/make_demo.py video    # composes frames + WAVs into DEMO.mp4
"""

from __future__ import annotations

import sys
import wave
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "demo_assets"
W, H = 1280, 720

SLIDES = [
    {
        "title": "Lyftr AI — Full-Stack Assignment",
        "lines": [
            "React frontend on GitHub Pages",
            "FastAPI + SQLite backend behind a public tunnel",
            "LiteLLM gateway: key failover + response caching",
            "Live URLs and source are in README.md",
        ],
        "code": "Frontend  https://krishna3103-9.github.io/lyftr-ai-chatbot/\nBackend   https://flying-sku-atom-shape.trycloudflare.com",
        "narration": "Hi, this is my Lyftr AI full stack assignment. The React frontend is deployed on GitHub Pages, the FastAPI backend is publicly reachable through a Cloudflare tunnel, and the source repository is public. The app uses SQLite for session history and LiteLLM for model calls, key failover and response caching.",
    },
    {
        "title": "1. Health endpoint",
        "lines": [
            "200 once the app, database and key pool are ready",
            "Two keys configured, built-in cache enabled",
        ],
        "code": 'GET /health\n{\n  "status": "ok",\n  "keys_configured": 2,\n  "cache_enabled": true\n}',
        "narration": "The health endpoint returns HTTP 200 with two configured keys and the cache enabled. This is the public backend URL, reachable without any login.",
    },
    {
        "title": "2. Live inference",
        "lines": [
            "First question in a brand-new session",
            "Metadata is per request, never a conversation total",
        ],
        "code": 'POST /chat  {"session_id":"verify-live-1",\n            "message":"What is the capital of Germany?"}\n\nreply: "Berlin"\nresolution_source: LIVE_INFERENCE\nmodel: openai/openai-fast\nlatency_ms: 9238   input_tokens: 95   output_tokens: 16\nkey_id: key_1      fallback_attempts: 0',
        "narration": "The first question produces a live answer. Each reply carries its own metadata: the resolution source, the LiteLLM model name, server measured latency, and input and output tokens for that request only. Here key one answered with ninety five input and sixteen output tokens.",
    },
    {
        "title": "3. Cache hit across sessions",
        "lines": [
            "Same model + full message list in a NEW session",
            "Identical reply, stored token usage, no provider call",
            "Cache hit is much faster than the live call",
        ],
        "code": 'POST /chat  {"session_id":"verify-cache-1",\n            "message":"What is the capital of Germany?"}\n\nreply: "Berlin"          (identical)\nresolution_source: LLM_CACHE\nlatency_ms: 495          (vs 9238 live)\ninput_tokens: 95   output_tokens: 16\nkey_id: null       fallback_attempts: 0',
        "narration": "Repeating the exact message in a new session is served by LiteLLM's built in cache. The reply text and token counts are identical, the key id is null, fallback attempts are zero, and latency drops from over nine seconds to under half a second.",
    },
    {
        "title": "4. Key failover on HTTP 429",
        "lines": [
            "X-Simulate-Failure: key_1=429",
            "key_1 is skipped, key_2 answers with a real reply",
        ],
        "code": 'POST /chat  header: X-Simulate-Failure: key_1=429\n\nreply: "13"\nresolution_source: LIVE_INFERENCE\nmodel: openai/openai-fast   latency_ms: 6197\ninput_tokens: 93   output_tokens: 33\nkey_id: key_2      fallback_attempts: 1',
        "narration": "With the failure test hook enabled, I simulate a 429 on key one. The gateway automatically moves to key two and returns a real answer, reporting one fallback attempt. The user never sees a broken screen or an error wrapped in a two hundred.",
    },
    {
        "title": "5. All keys fail — clean 503",
        "lines": [
            "X-Simulate-Failure: *=429",
            "Uniform JSON error, no stack trace",
            "Failed request is NOT written to history",
        ],
        "code": 'HTTP 503\n{"detail": "all providers unavailable"}\n\nGET /sessions/public-fail-all/messages -> 404\n{"detail": "session not found"}',
        "narration": "When every key fails, the API returns a clean 503 with the exact detail, all providers unavailable. There is no stack trace, and because the request failed nothing is added to SQLite history — the session still returns 404.",
    },
    {
        "title": "6. Multi-turn state in SQLite",
        "lines": [
            "Client sends only the new message",
            "Backend loads history from SQLite per session_id",
            "System prompt stored per session, never shown as a message",
        ],
        "code": 'GET /sessions/verify-live-1/messages\n[\n  {"role":"user","content":"..."},\n  {"role":"assistant","content":"Berlin","metadata":{...}}\n]\n\nSchema: messages(id, session_id, role, content, metadata, created_at)',
        "narration": "Multi turn state lives in SQLite. The client sends only the new message; the backend loads earlier turns from the messages table, ordered oldest first. Sessions stay separate, and the system prompt is stored in a small session table but never returned as a chat message.",
    },
    {
        "title": "7. UI metadata badges",
        "lines": [
            "assistant-message with meta-source, meta-model,",
            "meta-latency, meta-input-tokens, meta-output-tokens",
            "Error cards keep 422 and 503 readable",
        ],
        "code": "LIVE_INFERENCE | openai/openai-fast | 9238 ms | in 95 | out 16\nLLM_CACHE     | openai/openai-fast |  495 ms | in 95 | out 16",
        "narration": "The interface shows all required test IDs next to every assistant reply: the source badge, model, latency, and per request input and output tokens. Validation and provider errors appear as readable cards instead of a blank screen.",
    },
    {
        "title": "8. Run locally & ship",
        "lines": [
            "make up -> frontend :3000, backend :8000",
            "Named Docker volume mounted at /data",
            "Multi-stage Dockerfiles, Makefile, .env.example, README",
            "11 pytest tests pass; frontend production build passes",
        ],
        "code": "docker compose up --build -d\nbackend  http://localhost:8000/health\nfrontend http://localhost:3000\nvolume   app_data:/data/app.db",
        "narration": "Locally the whole stack starts with make up: backend on port eight thousand, frontend on port three thousand, and SQLite on a named Docker volume at slash data slash app dot d b. Multi stage Dockerfiles keep runtime images small. Eleven backend tests and the production frontend build all pass. That completes the demo — thank you.",
    },
]


def font(size: int, bold: bool = False, mono: bool = False):
    names = (
        ["consolab.ttf", "consola.ttf"] if mono else
        ["segoeuib.ttf", "segoeui.ttf"] if bold else
        ["segoeui.ttf", "arial.ttf"]
    )
    for name in names:
        path = Path("C:/Windows/Fonts") / name
        if path.exists():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


def make_slides() -> None:
    OUT.mkdir(exist_ok=True)
    for i, slide in enumerate(SLIDES, 1):
        image = Image.new("RGB", (W, H), "#080b18")
        d = ImageDraw.Draw(image)
        for y in range(H):
            t = y / H
            d.line([(0, y), (W, y)], fill=(int(8 + 18 * t), int(11 + 12 * t), int(24 + 40 * t)))
        d.rounded_rectangle((44, 40, W - 44, H - 40), radius=22, fill=(17, 21, 40), outline=(55, 62, 110), width=2)
        d.rounded_rectangle((72, 72, 108, 108), radius=10, fill=(99, 102, 241))
        d.text((82, 78), "✦", font=font(22, bold=True), fill="white")
        d.text((124, 78), "Lyftr AI", font=font(22, bold=True), fill="#e8eaf6")
        d.text((W - 150, 84), f"{i:02d}/{len(SLIDES):02d}", font=font(14, mono=True), fill="#7a83a9")
        d.text((72, 132), slide["title"], font=font(34, bold=True), fill="#ffffff")
        y = 200
        for line in slide["lines"]:
            d.ellipse((76, y + 12, 84, y + 20), fill="#818cf8")
            d.text((100, y), line, font=font(20), fill="#c3c9e8")
            y += 38
        code_y = max(y + 22, 360)
        d.rounded_rectangle((72, code_y, W - 72, H - 88), radius=14, fill=(11, 15, 30), outline=(48, 55, 95))
        d.text((96, code_y + 18), slide["code"], font=font(17, mono=True), fill="#8be9c0", spacing=8)
        d.text((72, H - 66), "https://github.com/Krishna3103-9/lyftr-ai-chatbot", font=font(13, mono=True), fill="#6b74a0")
        image.save(OUT / f"slide_{i:02d}.png")
        (OUT / f"narration_{i:02d}.txt").write_text(slide["narration"], encoding="utf-8")
    print(f"wrote {len(SLIDES)} slides to {OUT}")


def wav_duration(path: Path) -> float:
    with wave.open(str(path), "rb") as w:
        return w.getnframes() / w.getframerate()


def make_video() -> None:
    from moviepy import AudioFileClip, concatenate_audioclips, concatenate_videoclips, ImageClip

    clips, audios = [], []
    for i in range(1, len(SLIDES) + 1):
        wav = OUT / f"narration_{i:02d}.wav"
        if not wav.exists():
            raise SystemExit(f"missing {wav} — generate WAVs first")
        duration = wav_duration(wav)
        clips.append(ImageClip(str(OUT / f"slide_{i:02d}.png")).with_duration(duration))
        audios.append(AudioFileClip(str(wav)).with_duration(duration))
    video = concatenate_videoclips(clips).with_audio(concatenate_audioclips(audios))
    target = ROOT / "DEMO.mp4"
    video.write_videofile(str(target), fps=24, codec="libx264", audio_codec="aac", preset="medium", logger="bar")
    print(f"wrote {target} ({video.duration:.1f}s)")


if __name__ == "__main__":
    make_slides() if sys.argv[1:] == ["slides"] else make_video()
