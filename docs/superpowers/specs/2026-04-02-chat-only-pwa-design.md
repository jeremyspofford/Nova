# Chat-Only Mobile PWA

## Problem

The Nova dashboard exposes all pages (Brain, Tasks, Goals, Settings, etc.) on mobile, but none of them were designed mobile-first. The result is a broken experience — Brain settings don't dismiss properly, the textarea jumps on keyboard open, the nav bar leaves gaps when it hides, and every page has its own mobile bugs. Fixing them all is unbounded work.

Instead: ship a polished chat-only mobile experience. Other pages can be feature-released when they're mobile-ready.

Additionally, the chat input has too many buttons on mobile (drawer, conversation mode, mic, send) crowding the textarea. The voice interaction model needs simplification across all platforms — a single morph button replacing three separate buttons.

## Design

### 1. Mobile Route Scoping

On screens below `md` (768px):

**Route redirects** — All non-chat routes redirect to `/chat` on mobile. Implementation: a `MobileGuard` wrapper component in `App.tsx` that uses `window.matchMedia('(min-width: 768px)')` (matching Tailwind's `md:` breakpoint exactly) and wraps non-chat routes. On mobile viewports it renders `<Navigate to="/chat" replace />`; on desktop it renders the child route normally. The guard listens to the matchMedia `change` event so orientation changes and window resizes are handled live — rotating a tablet from portrait to landscape makes other routes available; rotating back redirects to chat. Direct URL access to `/settings` on mobile intentionally redirects to `/chat`.

**No MobileNav on mobile** — `AppLayout.tsx` conditionally omits `<MobileNav />` on mobile viewports. Use the same `matchMedia` check (via a `useIsMobile` hook or inline). MobileNav's existing `md:hidden` CSS is a visual fallback, but not rendering the component at all avoids mounting unnecessary event listeners and context consumers. The `MobileNavProvider` wrapper stays in place — it's a lightweight context that doesn't hurt, and desktop may use it in the future.

**Remove mobile nav padding** — Change both chat input wrappers in `ChatPage.tsx` from `pb-16 md:pb-4` to just `pb-4`. With no nav bar on mobile, there's nothing to clear. The ChatInput's existing `safe-area-pb` class handles the home indicator on notched phones.

**Desktop unchanged** — All routes, sidebar, and page layouts remain exactly as they are.

### 2. Send/Mic Morph Button (Universal — All Screen Sizes)

Replaces the current three separate buttons (conversation mode toggle, manual mic, send) with a single context-aware button. Applies to both mobile and desktop.

**State priority** (highest to lowest — a higher-priority state always wins):

| Priority | Condition | Button shows | Tap action | Long-press action |
|----------|-----------|-------------|------------|-------------------|
| 1 | Recording (push-to-talk active) | Stop icon (red circle) | Stop recording | — |
| 2 | Conversation mode active | Stop/square icon | Exit conversation mode | — |
| 3 | Transcribing | Spinner icon (disabled) | — | — |
| 4 | Textarea has text | Send icon (teal circle) | Send message | — |
| 5 | Textarea empty, idle | Mic icon (teal circle) | Push-to-talk start | Enter conversation mode |

Recording state always takes priority over textarea content — if live transcript fills the textarea mid-recording, the button stays as Stop, not Send.

**Push-to-talk flow:** Tap mic → recording starts, indicator appears → tap stop → transcription runs → transcribed text fills the textarea (changed from current behavior which auto-submits). Button morphs to send. User can review/edit the transcription, then tap send. This change requires modifying the `handleVoiceTranscript` callback in `ChatPage.tsx` to call `setDraftInput(text)` instead of `handleSubmit(text)`.

**Conversation mode flow (long-press ~500ms):** Enter continuous interruptable loop: listen → transcribe → generate → TTS → listen. The existing conversation mode status bar (listening/processing/speaking indicators in ChatInput) appears above the textarea. User can interrupt Nova mid-speech by talking above the barge-in threshold (already implemented in `useVoiceChat`). Tap the stop button to exit conversation mode. Escape key still exits conversation mode (existing behavior in `useVoiceChat`, preserved).

**Discoverability:** First time the user sees the mic button, show a subtle one-time tooltip: "Hold for conversation mode". Store dismissal in localStorage. This is a known pattern from WhatsApp voice messages.

**What this replaces:**
- The standalone conversation mode toggle button (`AudioLines` icon) — removed
- The standalone manual mic button (`Mic` icon) — removed
- The send button behavior — unchanged, just shared with the morph

**Desktop:** Same morph behavior. The drawer toggle (+) and model picker row remain visible alongside the morph button.

**Mobile:** The morph button is the only button next to the textarea.

**Disabled logic:** The morph button is never disabled except during transcription (`voice.isTranscribing`). In mic-idle state with empty textarea, the button is enabled (this is its primary use case). This replaces the current send button's `disabled={!input.trim()}` which only applies when the button is in send mode (textarea has text).

### 3. Mobile Model Selector

A compact model chip rendered above the textarea on mobile only (below `md`). Desktop keeps the existing `ModelPicker` in the controls row.

**Appearance:** Left-aligned, `text-micro`, `rounded-full`, subtle surface background. Shows truncated model name + dropdown caret (e.g. `llama3.1:8b ▾`).

**Behavior:** Tapping opens the same model picker dropdown that the desktop `ModelPicker` uses. Same data, same selection logic — just a smaller trigger element.

**Positioning:** Inside the ChatInput `rounded-3xl` card, above the textarea + morph button row. Part of the input chrome, consistent with the desktop model picker being inside the same card. Compact enough to not eat into message viewing area.

## Files Affected

| File | Changes |
|------|---------|
| `dashboard/src/App.tsx` | Add `MobileGuard` wrapper for non-chat routes |
| `dashboard/src/hooks/useIsMobile.ts` | New hook: `matchMedia('(min-width: 768px)')` with live listener |
| `dashboard/src/components/layout/AppLayout.tsx` | Conditionally omit `<MobileNav />` on mobile using `useIsMobile` |
| `dashboard/src/pages/chat/ChatPage.tsx` | Change `pb-16 md:pb-4` to `pb-4` (both instances), change `handleVoiceTranscript` to fill textarea instead of auto-submit |
| `dashboard/src/pages/chat/ChatInput.tsx` | Replace 3 voice/send buttons with morph button, add mobile model chip inside the card, restructure mobile layout |
| `dashboard/src/components/ui/MorphButton.tsx` | New component: send/mic morph with long-press gesture, state priority logic |
| `dashboard/src/components/ui/MobileModelChip.tsx` | New component: compact model selector for mobile |

## Out of Scope

- Brain page mobile fixes (not in the mobile PWA)
- Settings page on mobile (desktop only)
- Tasks/Goals/Sources on mobile (future feature releases)
- Nova persona/identity memory (separate initiative)
- PWA manifest or service worker changes (already configured correctly)
- Desktop layout changes (beyond the universal send/mic morph)
