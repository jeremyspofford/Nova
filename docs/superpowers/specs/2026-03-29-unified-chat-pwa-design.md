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
- Real-time conversation sync (live updates across channels without refresh)
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

**Multiple users, no links:**
- If more than one registered user exists and auto-link conditions aren't met, the bot replies: "Multiple Nova users detected. Ask your admin for a link code, or visit the dashboard to generate one."

**Unlinking:**
- Available from Settings > Chat Integrations > Telegram per user
- Also via `/unlink` command in Telegram

**Constraints:**
- One Telegram account per Nova user
- Re-linking replaces the old binding
- Unlinked users who message the bot get instructions pointing them to the dashboard or `/link` command

### 2. Conversation Unification

**How Telegram messages join the same conversation as the PWA:**

1. Telegram message arrives at the bridge
2. Bridge resolves the sender: calls `POST /api/v1/linked-accounts/resolve` with platform=telegram and platform_id=chat_id to get the linked `user_id`
3. Bridge fetches that user's single active conversation from the orchestrator (creates one if none exists)
4. Bridge calls `POST /api/v1/chat/stream` with that `conversation_id`, the message, and service auth headers
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

**Lock mechanism:** When a streaming response begins for a conversation, the orchestrator sets a Redis key `nova:chat:streaming:{conversation_id}` with a 120-second TTL (auto-expires if the stream crashes). The key is deleted when streaming completes.

**Behavior:**
- Before starting a new stream, the orchestrator checks for this key
- If locked, returns HTTP 409 with body: `{"error": "Nova is currently responding. Try again in a moment."}`
- This applies to all channels equally — if you send a message from the PWA while Nova is responding to a Telegram message (or vice versa, or same channel), you get the same 409
- The bridge translates the 409 into a friendly Telegram message
- The PWA chat UI shows the "Nova is thinking" state and disables the send button while streaming (this already works for same-session streams; the new lock makes it work cross-channel)

**Rapid messages:** If a user sends multiple messages quickly from Telegram before Nova finishes responding, messages 2+ get the "try again" response. No automatic queuing — the user retries when ready. This matches natural conversation: wait for the other person to finish.

### 4. Chat-Bridge Changes

**Removed responsibilities:**
- No longer creates its own agents per Telegram user
- No longer manages sessions in Redis DB 4
- No longer calls `/api/v1/tasks/stream` directly

**New responsibilities:**
- Resolves Telegram users to Nova users via `POST /api/v1/linked-accounts/resolve`
- Auto-links first user when conditions are met via `POST /api/v1/linked-accounts/auto-link`
- Handles `/link` and `/unlink` commands via linked-accounts API
- Calls `POST /api/v1/chat/stream` on behalf of the linked user (see Bridge Auth section)
- Chunks long responses for Telegram's 4096-character message limit (split on paragraph boundaries)
- Handles rich content gracefully: Telegram photos/voice become attachments, complex tool output degrades to simplified text

**Unchanged:**
- Telegram adapter (webhook and polling modes)
- Message formatting (markdown with plaintext fallback)
- Typing indicators

### 5. Bridge Auth Model

The bridge is a trusted internal service running inside the Docker network. It needs to call `POST /api/v1/chat/stream`, which normally requires user-level JWT auth from the dashboard.

**Mechanism: service-to-service impersonation**

- New env var: `BRIDGE_SERVICE_SECRET` (shared between orchestrator and bridge, set in `.env`)
- Bridge sends two headers on requests to the orchestrator:
  - `X-Service-Secret: <bridge_service_secret>` — proves the caller is a trusted internal service
  - `X-On-Behalf-Of: <user_id>` — identifies which user this request is for
- Orchestrator's auth middleware recognizes this header pair: if `X-Service-Secret` matches the configured secret, it trusts the `X-On-Behalf-Of` user_id and skips JWT validation
- This auth path is only honored when `X-Service-Secret` is valid — external clients cannot use `X-On-Behalf-Of` alone
- `BRIDGE_SERVICE_SECRET` is auto-generated by `setup.sh` alongside the existing `ADMIN_SECRET`

**Why not per-user JWTs in the bridge:** The bridge would need to obtain, store, and refresh JWT tokens for every linked user. Service-level trust is simpler and appropriate since the bridge runs inside the trusted Docker network.

### 6. PWA Chat UI Changes

**Removed:**
- Conversation sidebar / conversation list
- "New chat" button
- Conversation switching

**New behavior:**
- Chat page loads the user's single active conversation automatically
- Messages from Telegram show a small channel indicator
- "Nova is thinking" state prevents sending while any channel is streaming (check the Redis lock or receive 409)

**Phase 2 (not Phase 1):** Live cross-channel streaming — seeing Telegram-originated responses appear in real-time on the PWA. In Phase 1, Telegram messages appear when the user opens or refreshes the PWA. This is acceptable because the messages are in the same database; there's just no push mechanism yet.

**Unchanged:**
- Message rendering, markdown, activity feed
- Streaming, voice input, file attachments, model picker
- Auto-scroll, draft persistence
- All non-chat dashboard functionality

### 7. Telegram Settings UI

**Location:** Settings > Chat Integrations > Telegram

**Bot Token section:**
- Text field, always visible (even when connected), pre-filled if configured
- Save button
- Connection status indicator (connected / disconnected / error)
- Saving the token writes to Redis runtime config (`nova:config:telegram.bot_token` in DB 1) and calls `POST /api/v1/bridge/reload-telegram` to trigger the bridge to teardown and re-setup the Telegram adapter with the new token
- No .env edit or container restart required

**Linked Users section:**
- Table: Nova User | Telegram Username | Status | Actions
- First row auto-populates on first Telegram message (auto-link)
- "Generate Link Code" button — creates a 6-char code with 10-minute countdown
- "Unlink" action per user

**Status footer:**
- Bot online/offline indicator
- Last message received timestamp

**Configuration storage:**
- Bot token: `nova:config:telegram.bot_token` in Redis DB 1 (consistent with other runtime config)
- Link codes: `nova:link:{code}` in Redis DB 1 with 10-minute TTL
- Linked accounts: orchestrator database (linked_accounts table)

### 8. External Access

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

### 9. Orchestrator Changes

**New API endpoints:**

| Endpoint | Method | Auth | Purpose |
|---|---|---|---|
| `/api/v1/linked-accounts` | GET | User (JWT) | List linked accounts for the authenticated user |
| `/api/v1/linked-accounts` | POST | User (JWT) | Manually link a platform account (admin) |
| `/api/v1/linked-accounts/{id}` | DELETE | User (JWT) | Unlink a platform account |
| `/api/v1/linked-accounts/resolve` | POST | Service (X-Service-Secret) | Map platform + platform_id to user_id + conversation_id. Used by bridge. |
| `/api/v1/linked-accounts/auto-link` | POST | Service (X-Service-Secret) | Auto-link when one user exists with no link. Used by bridge. |
| `/api/v1/linked-accounts/link-code` | POST | User (JWT) | Generate a 6-char link code (stored in Redis DB 1, 10-min TTL) |
| `/api/v1/linked-accounts/redeem` | POST | Service (X-Service-Secret) | Validate a link code and create the binding. Used by bridge /link command. |
| `/api/v1/bridge/reload-telegram` | POST | Admin (X-Admin-Secret) | Tell the bridge to teardown and re-setup Telegram adapter. Called by dashboard after saving bot token. |

**Resolve endpoint response:**
```json
{
  "user_id": "uuid",
  "conversation_id": "uuid",
  "username": "jeremy"
}
```
If the user has no conversation yet, the resolve endpoint creates one and returns the new conversation_id.

**New auth path on `/api/v1/chat/stream`:**
- Accepts `X-Service-Secret` + `X-On-Behalf-Of` headers as an alternative to JWT
- Only honored when `X-Service-Secret` matches the configured `BRIDGE_SERVICE_SECRET`
- Treats the request as if the specified user made it

**Concurrent stream lock:**
- On stream start: `SET nova:chat:streaming:{conversation_id} 1 EX 120` in Redis DB 2
- On stream end: `DEL nova:chat:streaming:{conversation_id}`
- Before streaming: check key exists → return 409 if locked

**New database migration — `linked_accounts` table:**

| Column | Type | Notes |
|---|---|---|
| id | UUID | Primary key |
| user_id | UUID | FK to users table |
| platform | TEXT | "telegram", "slack", etc. |
| platform_id | TEXT | Platform-specific user/chat ID |
| platform_username | TEXT | Display name (nullable) |
| linked_at | TIMESTAMPTZ | When the link was created |

**Constraints:** Unique on (platform, platform_id). Unique on (user_id, platform) — one link per platform per user.

### 10. Migration Plan

**Existing conversations:**
- The conversations table schema is unchanged. The "one conversation per user" rule is enforced at the application layer, not the database.
- Existing multi-conversation API endpoints (list, create, delete) remain in the codebase for backward compatibility with chat-api and potential external clients.
- The PWA chat UI simply loads the most recent conversation and doesn't expose the list/create/delete UI. If a user has multiple existing conversations, the newest one becomes "the" conversation.
- No data migration needed — existing conversations are preserved, the UI just stops showing a list.

### 11. chat-api Service

chat-api (port 8080) is the WebSocket streaming bridge for external clients. It is **out of scope for Phase 1**. It continues to work as-is with its own session management. External WebSocket clients are a separate channel that could be unified in a future phase using the same bridge auth pattern.

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
- **Auto-link guard:** Auto-link only fires when exactly one registered user exists and no Telegram account is linked. If multiple users exist with no links, the bot gives instructions to get a link code. Prevents a stranger from claiming the account if the bot token leaks.
- **Bot token change:** Dashboard saves token to Redis and calls the bridge reload endpoint. The bridge tears down the old Telegram adapter and starts a new one. Linked accounts persist (they're bound to Nova users, not bot identity). No container restart needed.
- **Service downtime:** If Nova services are down when a Telegram message arrives, the bridge returns a friendly error message rather than silently dropping the message.
- **Stream crash:** The concurrent stream lock has a 120-second TTL, so even if a stream crashes without cleanup, the lock auto-expires and doesn't permanently block the conversation.
- **Existing multi-conversation data:** Preserved in the database. PWA loads the most recent one. Old conversations are still accessible via API if needed, just not shown in the UI.
