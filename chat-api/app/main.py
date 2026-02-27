"""Nova Chat API — main entrypoint."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from app.config import settings
from app.websocket import handle_websocket

logging.basicConfig(level=settings.log_level)
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
    allow_origins=["*"],  # Tighten in production
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
  let ws, sessionId, streamDiv;

  /* ── Auto-grow textarea ── */
  inputEl.addEventListener('input', () => {
    inputEl.style.height = 'auto';
    inputEl.style.height = Math.min(inputEl.scrollHeight, 160) + 'px';
  });

  /* ── WebSocket ── */
  function connect() {
    ws = new WebSocket(`ws://${location.host}/ws/chat`);

    ws.onopen = () => {
      dot.className = 'connected';
      statusTxt.textContent = 'Connected';
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
        }
        streamDiv.textContent += data.delta;
        scrollBottom();

      } else if (data.type === 'stream_end') {
        if (streamDiv) streamDiv.classList.remove('streaming');
        streamDiv = null;
        sendBtn.disabled = false;

      } else if (data.type === 'error') {
        if (streamDiv) { streamDiv.classList.remove('streaming'); streamDiv = null; }
        addMsg('error', data.content || 'Unknown error');
        sendBtn.disabled = false;
      }
    };

    ws.onclose = () => {
      dot.className = '';
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
    b.textContent = text;
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
