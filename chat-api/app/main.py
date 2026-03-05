"""Nova Chat API — main entrypoint."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from nova_contracts.logging import configure_logging

from app.config import settings
from app.websocket import handle_websocket

configure_logging("chat-api", settings.log_level)
log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("Chat API starting on ws://0.0.0.0:%d/ws/chat", settings.service_port)
    yield
    log.info("Chat API shutting down")


app = FastAPI(
    title="Nova Chat API",
    version="0.1.0",
    description="WebSocket chat interface for Nova agents",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_allowed_origins.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.websocket("/ws/chat")
async def chat_endpoint(websocket: WebSocket):
    await handle_websocket(websocket)


@app.get("/health/live")
async def liveness():
    return {"status": "alive"}


@app.get("/health/ready")
async def readiness():
    import httpx
    checks = {}
    try:
        async with httpx.AsyncClient(base_url=settings.orchestrator_url, timeout=3.0) as c:
            r = await c.get("/health/ready")
            checks["orchestrator"] = "ok" if r.status_code == 200 else f"http_{r.status_code}"
    except Exception as e:
        checks["orchestrator"] = f"error: {e}"
    all_ok = all(v == "ok" for v in checks.values())
    return {"status": "ready" if all_ok else "degraded", "checks": checks}


# Quick test UI — open http://localhost:8080 in a browser to chat
@app.get("/", response_class=HTMLResponse)
async def test_ui():
    return """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Nova Chat</title>
  <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
  <style>
    /* ── Warm Stone + Deep Teal — matches the Nova dashboard ── */
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: #fafaf8;   /* stone-50 */
      color: #1c1917;        /* stone-900 */
      display: flex;
      flex-direction: column;
      height: 100dvh;
      max-width: 780px;
      margin: 0 auto;
    }

    /* ── Top bar ── */
    header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 12px 20px;
      background: #ffffff;
      border-bottom: 1px solid #e7e5e0;
      flex-shrink: 0;
    }
    header .brand {
      font-size: 13px;
      font-weight: 700;
      letter-spacing: 0.12em;
      text-transform: uppercase;
      color: #0f766e;        /* teal-700 */
    }
    #status {
      font-size: 11px;
      color: #a8a29e;        /* stone-400 */
      display: flex;
      align-items: center;
      gap: 6px;
    }
    #status-dot {
      width: 7px; height: 7px;
      border-radius: 50%;
      background: #a8a29e;
      transition: background 0.3s;
    }
    #status-dot.connected { background: #10b981; }

    /* ── Message list ── */
    #messages {
      flex: 1;
      overflow-y: auto;
      padding: 20px;
      display: flex;
      flex-direction: column;
      gap: 12px;
    }

    .msg {
      display: flex;
      flex-direction: column;
      gap: 2px;
      max-width: 88%;
    }
    .msg.user  { align-self: flex-end; align-items: flex-end; }
    .msg.assistant { align-self: flex-start; align-items: flex-start; }
    .msg.system { align-self: center; }

    .bubble {
      padding: 10px 14px;
      border-radius: 12px;
      font-size: 14px;
      line-height: 1.55;
      white-space: pre-wrap;
      word-break: break-word;
    }
    .user .bubble {
      background: #0f766e;   /* teal-700 */
      color: #ffffff;
      border-bottom-right-radius: 4px;
    }
    .assistant .bubble {
      background: #ffffff;
      border: 1px solid #e7e5e0;
      color: #1c1917;
      border-bottom-left-radius: 4px;
    }
    .system .bubble {
      background: transparent;
      font-size: 11px;
      color: #a8a29e;
      border: none;
      padding: 2px 0;
    }
    .error .bubble {
      background: #fef2f2;
      border: 1px solid #fecaca;
      color: #dc2626;
      font-size: 13px;
    }

    /* Typing cursor while streaming */
    .streaming::after {
      content: "▌";
      animation: blink 0.8s step-start infinite;
      color: #0f766e;
      margin-left: 1px;
    }
    @keyframes blink { 50% { opacity: 0; } }

    /* ── Input area ── */
    #composer {
      padding: 12px 16px;
      background: #ffffff;
      border-top: 1px solid #e7e5e0;
      display: flex;
      gap: 10px;
      align-items: flex-end;
      flex-shrink: 0;
    }
    #input {
      flex: 1;
      resize: none;
      padding: 10px 14px;
      border: 1px solid #d6d3d1;   /* stone-300 */
      border-radius: 10px;
      background: #f5f5f4;         /* stone-100 */
      color: #1c1917;
      font-size: 14px;
      font-family: inherit;
      outline: none;
      min-height: 42px;
      max-height: 160px;
      line-height: 1.5;
      transition: border-color 0.15s;
    }
    #input:focus { border-color: #0f766e; background: #ffffff; }
    #input::placeholder { color: #a8a29e; }

    #send {
      flex-shrink: 0;
      width: 42px; height: 42px;
      border-radius: 10px;
      border: none;
      background: #0f766e;
      color: #ffffff;
      cursor: pointer;
      display: flex; align-items: center; justify-content: center;
      transition: background 0.15s;
    }
    #send:hover  { background: #14b8a6; }
    #send:disabled { background: #d6d3d1; cursor: default; }
    #send svg { width: 18px; height: 18px; fill: none; stroke: currentColor; stroke-width: 2; stroke-linecap: round; stroke-linejoin: round; }

    /* ── Markdown inside assistant bubbles ── */
    .assistant .bubble { white-space: normal; }
    .assistant .bubble p { margin: 0.4em 0; }
    .assistant .bubble p:first-child { margin-top: 0; }
    .assistant .bubble p:last-child  { margin-bottom: 0; }

    .assistant .bubble code {
      font-size: 0.85em;
      background: #f5f5f4;
      padding: 0.15em 0.35em;
      border-radius: 4px;
    }
    .assistant .bubble pre {
      margin: 0.5em 0;
      padding: 0.75em 1em;
      background: #1c1917;
      border-radius: 8px;
      overflow-x: auto;
      white-space: pre;
    }
    .assistant .bubble pre code {
      background: none;
      padding: 0;
      color: #e7e5e4;
      font-size: 0.85em;
      line-height: 1.6;
    }

    .assistant .bubble ul, .assistant .bubble ol { margin: 0.4em 0; padding-left: 1.5em; }
    .assistant .bubble ul { list-style: disc; }
    .assistant .bubble ol { list-style: decimal; }
    .assistant .bubble li  { margin: 0.15em 0; }

    .assistant .bubble blockquote {
      margin: 0.5em 0;
      padding: 0.25em 0.75em;
      border-left: 3px solid #d6d3d1;
      color: #78716c;
    }

    .assistant .bubble h1, .assistant .bubble h2, .assistant .bubble h3 { font-weight: 600; margin: 0.6em 0 0.3em; }
    .assistant .bubble h1 { font-size: 1.2em; }
    .assistant .bubble h2 { font-size: 1.1em; }
    .assistant .bubble h3 { font-size: 1.05em; }

    .assistant .bubble { overflow-x: auto; }
    .assistant .bubble table { display: table; border-collapse: collapse; margin: 0.5em 0; font-size: 0.9em; width: auto; }
    .assistant .bubble th, .assistant .bubble td { border: 1px solid #d6d3d1; padding: 0.3em 0.6em; }
    .assistant .bubble th { background: #f5f5f4; font-weight: 600; }
    .assistant .bubble tr:nth-child(even) { background: #fafaf9; }

    .assistant .bubble a { color: #0f766e; text-decoration: underline; }
    .assistant .bubble hr { border: none; border-top: 1px solid #e7e5e4; margin: 0.75em 0; }
  </style>
</head>
<body>

<header>
  <span class="brand">Nova</span>
  <span id="status">
    <span id="status-dot"></span>
    <span id="status-text">Connecting…</span>
  </span>
</header>

<div id="token-bar" style="display:none; padding:8px 16px; background:#f5f5f4; border-bottom:1px solid #e7e5e0; font-size:13px;">
  <label style="display:flex;align-items:center;gap:8px;">
    <span style="color:#78716c;">API Key:</span>
    <input id="token-input" type="password" placeholder="sk-nova-..." style="flex:1;padding:6px 10px;border:1px solid #d6d3d1;border-radius:6px;font-size:13px;background:#fff;" />
    <button onclick="connectWithToken()" style="padding:6px 12px;background:#0f766e;color:#fff;border:none;border-radius:6px;cursor:pointer;font-size:12px;">Connect</button>
  </label>
</div>

<div id="messages"></div>

<div id="composer">
  <textarea id="input" rows="1" placeholder="Message Nova… (Enter to send, Shift+Enter for newline)" autofocus></textarea>
  <button id="send" title="Send" onclick="send()">
    <svg viewBox="0 0 24 24"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>
  </button>
</div>

<script>
  const msgs    = document.getElementById('messages');
  const inputEl = document.getElementById('input');
  const sendBtn = document.getElementById('send');
  const dot     = document.getElementById('status-dot');
  const statusTxt = document.getElementById('status-text');
  const tokenBar = document.getElementById('token-bar');
  const tokenInput = document.getElementById('token-input');
  let ws, sessionId, streamDiv, streamRaw = '';
  let authToken = localStorage.getItem('nova-chat-token') || '';

  marked.setOptions({ breaks: true });

  /* ── Auto-grow textarea ── */
  inputEl.addEventListener('input', () => {
    inputEl.style.height = 'auto';
    inputEl.style.height = Math.min(inputEl.scrollHeight, 160) + 'px';
  });

  /* ── Token helpers ── */
  function connectWithToken() {
    authToken = tokenInput.value.trim();
    if (authToken) {
      localStorage.setItem('nova-chat-token', authToken);
    }
    if (ws) ws.close();
    connect();
  }

  /* ── WebSocket ── */
  function connect() {
    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    let url = `${proto}//${location.host}/ws/chat`;
    if (authToken) url += `?token=${encodeURIComponent(authToken)}`;
    ws = new WebSocket(url);

    ws.onopen = () => {
      dot.className = 'connected';
      statusTxt.textContent = 'Connected';
      tokenBar.style.display = 'none';
      sendBtn.disabled = false;
    };

    ws.onmessage = (e) => {
      const data = JSON.parse(e.data);

      if (data.type === 'system') {
        sessionId = data.session_id;
        addMsg('system', 'Session ' + sessionId.slice(0, 8) + '…');

      } else if (data.type === 'stream_chunk') {
        if (!streamDiv) {
          streamDiv = addBubble('assistant');
          streamDiv.classList.add('streaming');
          streamRaw = '';
        }
        streamRaw += data.delta;
        streamDiv.innerHTML = marked.parse(streamRaw);
        scrollBottom();

      } else if (data.type === 'stream_end') {
        if (streamDiv) {
          streamDiv.classList.remove('streaming');
          streamDiv.innerHTML = marked.parse(streamRaw);
        }
        streamDiv = null;
        streamRaw = '';
        sendBtn.disabled = false;

      } else if (data.type === 'error') {
        if (streamDiv) { streamDiv.classList.remove('streaming'); streamDiv = null; }
        addMsg('error', data.content || 'Unknown error');
        sendBtn.disabled = false;
        if (data.content && data.content.includes('Authentication')) {
          tokenBar.style.display = 'block';
        }
      }
    };

    ws.onclose = (e) => {
      dot.className = '';
      if (e.code === 4001) {
        statusTxt.textContent = 'Auth required';
        tokenBar.style.display = 'block';
        return; // Don't auto-reconnect on auth failure
      }
      statusTxt.textContent = 'Reconnecting…';
      sendBtn.disabled = true;
      setTimeout(connect, 2000);
    };
    ws.onerror = () => ws.close();
  }

  /* ── Helpers ── */
  function addBubble(type) {
    const wrap = document.createElement('div');
    wrap.className = 'msg ' + type;
    const bubble = document.createElement('div');
    bubble.className = 'bubble';
    wrap.appendChild(bubble);
    msgs.appendChild(wrap);
    scrollBottom();
    return bubble;
  }

  function addMsg(type, text) {
    const b = addBubble(type);
    if (type === 'assistant') {
      b.innerHTML = marked.parse(text);
    } else {
      b.textContent = text;
    }
    return b;
  }

  function scrollBottom() {
    msgs.scrollTop = msgs.scrollHeight;
  }

  function send() {
    const text = inputEl.value.trim();
    if (!text || ws.readyState !== WebSocket.OPEN) return;
    addMsg('user', text);
    ws.send(JSON.stringify({ type: 'user', content: text, session_id: sessionId }));
    inputEl.value = '';
    inputEl.style.height = 'auto';
    sendBtn.disabled = true;
    scrollBottom();
  }

  inputEl.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
  });

  connect();
</script>
</body>
</html>
"""
