import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { describeError, getHealth, postChat } from "./api";
import type { ChatMessage, ChatMetadata, Health } from "./types";

function newSessionId(): string {
  const random = typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  return `s-${random}`;
}

let nextId = 0;
const messageId = () => ++nextId;

const SUGGESTIONS = [
  "What is the capital of France?",
  "Explain LLM caching in one sentence.",
  "Name three uses of SQLite in small apps.",
];

function AssistantCard({ metadata, content }: { metadata: ChatMetadata; content: string }) {
  const cached = metadata.resolution_source === "LLM_CACHE";
  return (
    <div className="message assistant-message" data-testid="assistant-message">
      <div className="avatar assistant-avatar" aria-hidden="true">✦</div>
      <div className="assistant-body">
        <div className="bubble assistant-bubble">
          <p>{content}</p>
        </div>
        <div className="meta-row" aria-label="Response metadata">
          <span className={`source-badge ${cached ? "source-cache" : "source-live"}`} data-testid="meta-source">
            {metadata.resolution_source}
          </span>
          <span className="meta-item" title="Model used" data-testid="meta-model">{metadata.model}</span>
          <span className="meta-item" title="Server-measured latency">
            <span data-testid="meta-latency">{metadata.latency_ms} ms</span>
          </span>
          <span className="meta-item" title="Input tokens for this request">
            in <span data-testid="meta-input-tokens">{metadata.input_tokens}</span>
          </span>
          <span className="meta-item" title="Output tokens for this reply">
            out <span data-testid="meta-output-tokens">{metadata.output_tokens}</span>
          </span>
          {metadata.key_id && (
            <span className="meta-item subtle" title="Key that answered and keys that failed first">
              {metadata.key_id}{metadata.fallback_attempts > 0 ? ` · +${metadata.fallback_attempts} fallback` : ""}
            </span>
          )}
        </div>
      </div>
    </div>
  );
}

export default function App() {
  const [sessionId, setSessionId] = useState(newSessionId);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [systemPrompt, setSystemPrompt] = useState("");
  const [busy, setBusy] = useState(false);
  const [health, setHealth] = useState<Health | null>(null);
  const [showSystem, setShowSystem] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let active = true;
    getHealth().then((value) => { if (active) setHealth(value); }).catch(() => { if (active) setHealth(null); });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, busy]);

  const send = async () => {
    const text = input.trim();
    if (!text || busy) return;
    setInput("");
    setBusy(true);
    setMessages((current) => [...current, { id: messageId(), role: "user", content: text }]);
    try {
      const trimmedPrompt = systemPrompt.trim();
      const reply = await postChat({
        session_id: sessionId,
        message: text,
        ...(trimmedPrompt ? { system_prompt: trimmedPrompt } : {}),
      });
      setMessages((current) => [
        ...current,
        { id: messageId(), role: "assistant", content: reply.reply, metadata: reply.metadata },
      ]);
    } catch (error) {
      setMessages((current) => [
        ...current,
        { id: messageId(), role: "error", content: describeError(error) },
      ]);
    } finally {
      setBusy(false);
    }
  };

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      void send();
    }
  };

  const newChat = () => {
    setSessionId(newSessionId());
    setMessages([]);
    setInput("");
    setBusy(false);
  };

  const online = health?.status === "ok";

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">✦</span>
          <div>
            <h1>Lyftr AI</h1>
            <p>Resilient chat · key failover · cached answers</p>
          </div>
        </div>
        <div className="header-actions">
          <span className={`status-pill ${online ? "online" : "offline"}`} title="Backend health">
            <span className="dot" />
            {online ? `${health.keys_configured} keys · ${health.cache_enabled ? "cache on" : "cache off"}` : "backend offline"}
          </span>
          <button type="button" className="secondary-button" onClick={newChat}>New chat</button>
        </div>
      </header>

      <main className="chat-area" ref={scrollRef}>
        <div className="chat-inner">
          <div className="session-tag" title="Current session id">Session {sessionId.slice(0, 18)}…</div>
          {messages.length === 0 && (
            <section className="welcome">
              <div className="welcome-icon" aria-hidden="true">✦</div>
              <h2>Ask me anything</h2>
              <p>Every reply shows where it came from, which model answered, how long it took, and the tokens used for that request only.</p>
              <div className="suggestions">
                {SUGGESTIONS.map((suggestion) => (
                  <button key={suggestion} type="button" className="suggestion" onClick={() => setInput(suggestion)}>
                    {suggestion}
                  </button>
                ))}
              </div>
            </section>
          )}

          {messages.map((message) => {
            if (message.role === "user") {
              return (
                <div className="message user-message" key={message.id}>
                  <div className="bubble user-bubble">{message.content}</div>
                  <div className="avatar user-avatar" aria-hidden="true">You</div>
                </div>
              );
            }
            if (message.role === "error") {
              return (
                <div className="message error-wrap" key={message.id}>
                  <div className="error-message" data-testid="error-message" role="alert">
                    <strong>Request failed</strong>
                    <span>{message.content}</span>
                  </div>
                </div>
              );
            }
            return <AssistantCard key={message.id} content={message.content} metadata={message.metadata!} />;
          })}

          {busy && (
            <div className="message assistant-message" aria-label="Assistant is thinking">
              <div className="avatar assistant-avatar" aria-hidden="true">✦</div>
              <div className="typing"><span /><span /><span /></div>
            </div>
          )}
        </div>
      </main>

      <footer className="composer-area">
        <div className="composer-inner">
          {showSystem && (
            <div className="system-panel">
              <label htmlFor="system-prompt">System prompt for this session</label>
              <textarea
                id="system-prompt"
                data-testid="system-prompt-input"
                value={systemPrompt}
                onChange={(event) => setSystemPrompt(event.target.value)}
                placeholder="e.g. Answer like a friendly pirate."
                rows={2}
              />
            </div>
          )}
          <div className="composer">
            <button
              type="button"
              className={`icon-button ${showSystem ? "active" : ""}`}
              onClick={() => setShowSystem((value) => !value)}
              title="Toggle system prompt"
              aria-label="Toggle system prompt"
            >
              ⚙
            </button>
            <textarea
              data-testid="chat-input"
              value={input}
              onChange={(event) => setInput(event.target.value)}
              onKeyDown={onKeyDown}
              placeholder="Send a message…"
              rows={1}
              aria-label="Message"
            />
            <button
              type="button"
              className="send-button"
              data-testid="send-button"
              onClick={() => void send()}
              disabled={busy || input.trim().length === 0}
            >
              {busy ? "Sending…" : "Send"}
              <span aria-hidden="true">➤</span>
            </button>
          </div>
          <p className="hint">Enter to send · Shift + Enter for a new line</p>
        </div>
      </footer>
    </div>
  );
}
