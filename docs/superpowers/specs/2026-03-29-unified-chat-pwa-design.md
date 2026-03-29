# Unified Chat & PWA Design

**Date:** 2026-03-29
**Status:** Draft
**Approach:** Bridge-to-Orchestrator (Option A)
**Phase:** 1 of 2

## Problem

Nova's chat is fragmented. The PWA dashboard and Telegram bridge maintain completely separate sessions, agents, conversation history, and memory context. A user chatting with Nova from Telegram has a different experience than from the PWA — different conversation, different memory. Nova should feel like one person you can reach from any channel.

## Goal

A single user can chat with Nova from the PWA or Telegram (or future channels) and experience one continuous conversation with shared memory and context. Like talking to the same person on the phone vs. in person.

## Mental Model

- Nova is one person. Channels are just how you reach them.
- Each user has exactly one ongoing conversation with Nova.
- Every message from any channel appends to that single conversation.
- Memory, context, and personality are the same regardless of channel.
- No conversation lists, no thread management. Just a chat window.

## Scope

### Phase 1 (This Project)

1. Telegram account linking (auto-link + link codes)
2. Conversation unification via bridge-to-orchestrator
3. PWA chat simplification (single continuous thread)
4. Telegram settings UI (bot token + linked users)
5. External access documentation (Cloudflare Tunnel + Tailscale)
6. Concurrent message handling

### Phase 2 (Roadmap)

- Multi-user memory isolation (per-user engram graph)
- Real-time conversation sync (live updates across channels)
- Push notifications
- Slack adapter
- Conversation history management (archive, search, export)
- Automated VPN/tunnel setup scripts

## Design

### 1. Account Linking

**First user (auto-link):**
- User configures bot token in Settings > Chat Integrations > Telegram
- User messages the bot for the first time
- If exactly one registered Nova user exists and no one is linked for Telegram, the bot auto-links that Telegram account to that Nova user
- Bot responds: "Connected to Nova. You can start chatting."

**Additional users (link code):**
- Admin generates a 6-character link code from the Telegram settings panel (valid for 10 minutes)
- New user sends `/link ABC123` to the bot
- Bot validates code, creates the binding, confirms

**Unlinking:**
- Available from Settings > Chat Integrations > Telegram per user
- Also via `/unlink` command in Telegram

**Constraints:**
- One Telegram account per Nova user
- Re-linking replaces the old binding
- Unlinked users who message the bot get: "Send /link <code> to connect your Nova account."

### 2. Conversation Unification

**How Telegram messages join the same conversation as the PWA:**

1. Telegram message arrives at the bridge
2. Bridge resolves the sender: looks up `telegram:chat_id` to find the linked `user_id`
3. Bridge fetches that user's single active conversation from the orchestrator (creates one if none exists)
4. Bridge calls the same chat streaming endpoint the PWA uses, with the user's `conversation_id` and message
5. Orchestrator processes it identically to a PWA message: memory injection, engram ingestion, tool use, streaming response
6. Bridge collects the streamed response and sends it to Telegram
7. When the user opens the PWA, all messages are already there — same database

**Channel tagging:**
- Each message includes a `channel` field in metadata ("telegram" or "pwa")
- Chat UI can show a subtle indicator of message origin

**Conversation continuity:**
- There is no conversation switching. One user = one conversation.
- Both channels always write to and read from the same conversation.

### 3. Concurrent Message Handling

If Nova is already responding to a message (from either channel), a message from the other channel receives a friendly response: "Nova is thinking — try again in a moment."

This prevents race conditions where two streaming responses would conflict. Same behavior as not talking over someone on the phone.

### 4. Chat-Bridge Changes

**Removed responsibilities:**
- No longer creates its own agents per Telegram user
- No longer manages sessions in Redis DB 4
- No longer calls the task streaming endpoint directly

**New responsibilities:**
- Resolves Telegram users to Nova users via linked accounts
- Auto-links first user when conditions are met
- Handles `/link` and `/unlink` commands
- Calls the orchestrator chat endpoint on behalf of the linked user
- Chunks long responses for Telegram's 4096-character message limit (split on paragraph boundaries)
- Handles rich content gracefully: Telegram photos/voice become attachments, complex tool output degrades to simplified text

**Unchanged:**
- Telegram adapter (webhook and polling modes)
- Message formatting (markdown with plaintext fallback)
- Bot token configuration
- Typing indicators

**Bridge trust model:**
- The bridge is a trusted internal service running inside the Docker network
- It authenticates to the orchestrator with a service secret and can specify which user a message is from
- External clients cannot impersonate users — only the bridge can

### 5. PWA Chat UI Changes

**Removed:**
- Conversation sidebar / conversation list
- "New chat" button
- Conversation switching

**New behavior:**
- Chat page loads the user's single active conversation automatically
- Messages from Telegram show a small channel indicator
- If Nova is responding to a Telegram message, the PWA shows the streaming response live
- "Nova is thinking" state reflects across channels

**Unchanged:**
- Message rendering, markdown, activity feed
- Streaming, voice input, file attachments, model picker
- Auto-scroll, draft persistence
- All non-chat dashboard functionality

### 6. Telegram Settings UI

**Location:** Settings > Chat Integrations > Telegram

**Bot Token section:**
- Text field, always visible (even when connected), pre-filled if configured
- Save button
- Connection status indicator (connected / disconnected / error)
- Changing the token reconnects with the new bot

**Linked Users section:**
- Table: Nova User | Telegram Username | Status | Actions
- First row auto-populates on first Telegram message (auto-link)
- "Generate Link Code" button — creates a 6-char code with 10-minute countdown
- "Unlink" action per user

**Status footer:**
- Bot online/offline indicator
- Last message received timestamp

**Configuration storage:**
- Bot token: runtime config via Redis (dashboard-configurable, no .env edits required)
- Link codes: Redis with 10-minute TTL
- Linked accounts: orchestrator database

### 7. External Access

Two supported options, documented with trade-offs. Users choose based on their priority.

**Cloudflare Tunnel (convenience):**
- No ports opened on the network
- Works from any browser, any device, no client software
- Free tier sufficient
- Enables Telegram webhook mode (faster than polling)
- Trade-off: traffic routes through Cloudflare's network

**Tailscale (privacy):**
- Private mesh network — only user's devices can reach Nova
- Encrypted peer-to-peer, no traffic through third parties
- Requires Tailscale client on each device
- Telegram must use polling mode (Telegram servers can't reach Tailscale IPs)
- Trade-off: can't share access without adding devices to tailnet

**Both can run simultaneously:** Tailscale for direct fast access from personal devices, Cloudflare Tunnel for Telegram webhooks and browser access from untrusted devices.

Scope for this project is documentation and configuration guidance only — no new infrastructure tooling.

### 8. Orchestrator Changes

**New behaviors:**
- Accept messages from the bridge on behalf of a linked user (bridge authenticates with a service secret)
- Resolve platform accounts to Nova users
- Auto-link first user when conditions are met (one registered user, no existing link for that platform)
- Generate and validate link codes
- Create and manage linked account bindings
- Return 409 "Nova is thinking" when a conversation already has an active streaming response

**New database table:**
- Linked accounts: stores which platform accounts are bound to which Nova users

**No changes to:**
- Memory service, engram ingestion, LLM gateway
- These already work correctly once the orchestrator passes the right conversation_id
- Memory and context are unified automatically because all channels flow through the same conversation

## PWA Status

The dashboard is already PWA-ready:
- Web app manifest (standalone mode, icons, theme colors)
- Service worker (offline app shell caching, network-first for APIs)
- Mobile-responsive layout with bottom navigation
- iOS safe-area handling, viewport configuration
- Installable on mobile and desktop today

No PWA infrastructure work needed. The only dashboard changes are to the chat UI (simplification) and settings (Telegram panel).

## Edge Cases

- **Telegram message length:** Responses exceeding 4096 characters are split on paragraph boundaries
- **Rich content mismatch:** Telegram photos/voice become conversation attachments; complex Nova output (tool results, diagrams) degrades to text for Telegram
- **Auto-link guard:** Auto-link only fires when exactly one registered user exists and no Telegram account is linked. Prevents a stranger from claiming the account if the bot token leaks.
- **Bot token change:** Changing the token in settings disconnects the old bot and reconnects with the new one. Linked accounts persist (they're bound to Nova users, not bot identity).
- **Service downtime:** If Nova services are down when a Telegram message arrives, the bridge returns a friendly error message rather than silently dropping the message.
