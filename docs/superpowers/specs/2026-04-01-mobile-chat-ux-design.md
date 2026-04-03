# Mobile Chat UX & Conversation Persistence

## Problem

Four issues with the Nova dashboard on mobile:

1. **No conversation sync** — Chat history stored in localStorage (device-local). Opening Nova on a phone shows a blank conversation, not the one from desktop.
2. **Brain tab broken** — MobileNav's Brain tab links to `/` which `HomeRoute` redirects to `/chat`. Tapping Brain does nothing visible.
3. **Input hidden behind nav bar** — MobileNav is `position: fixed` overlaying content. Chat input has no bottom padding to compensate, so it sits behind the 56px nav bar.
4. **Chat feels cramped on mobile** — Uniform bubble corners, max-width constraint wasting space, and a squared-off input field don't feel like a messaging app.

## Design

### 1. Bug Fixes

**Brain route** — Change MobileNav `primaryTabs` entry from `{ to: '/' }` to `{ to: '/brain' }`. Also update the `brainEnabled` filter from `tab.to !== '/'` to `tab.to !== '/brain'` to preserve the brain-toggle behavior.

**Input overlap** — Add `pb-14 md:pb-0` to the chat container's input wrapper areas. Both the empty-state layout (lines 456-475) and the active-chat layout (lines 478-526) in `ChatPage.tsx` have separate input wrappers that need this padding.

### 2. Chat Style Overhaul (Universal — All Screen Sizes)

These changes apply to desktop and mobile equally. The chat should feel like a messaging app everywhere.

**Bubble shapes** — Asymmetric border-radius on `MessageBubble.tsx`:
- Assistant messages: flat top-left corner (the "tail"), rounded elsewhere (`rounded-tl-sm rounded-tr-xl rounded-br-xl rounded-bl-xl`)
- User messages: flat top-right corner, rounded elsewhere (`rounded-tl-xl rounded-tr-sm rounded-br-xl rounded-bl-xl`)
- Replaces the current asymmetric styles: assistant uses `rounded-r-xl` with a `border-l-2` accent, user uses `rounded-xl`. The new shapes give both roles distinct "tail" corners like a messaging app.

**Nova avatar** — Small teal circle with fallback "N" initial to the left of assistant messages. When the user has configured a custom avatar via Settings (provided by `useNovaIdentity().avatarUrl`), use that instead. The teal "N" circle is the default, not a replacement. Amber tint on the circle during thinking/activity states (ties into the design system's cognitive amber).

**User message alignment** — Right-aligned with `ml-auto`, teal-tinted background (existing, just tightened).

**Pill input** — `ChatInput` outer container changes from `rounded-2xl` to `rounded-full` with adjusted padding. Circular send button inside.

**Timestamps** — Change the existing relative timestamps (`formatDistanceToNow`, e.g. "3 minutes ago") to absolute time format (e.g. "2:35 PM"). Keep the existing `font-mono text-mono-sm text-content-tertiary` styling. This is a format change, not adding a new element.

**Input alignment** — Indent the entire `ChatInput` container (including voice controls, file preview bar, and textarea row) by the avatar column width (`pl-[36px]` or matching avatar+gap) so the full input block aligns with the message bubble content column, not the outer container edge.

**Wider desktop chat area** — Bump container from `max-w-[780px]` to responsive `max-w-3xl xl:max-w-4xl` (~768px stepping to ~896px on large screens). There are 4 instances of `max-w-[780px]` in `ChatPage.tsx` across both the empty-state and active-chat layouts — all four need updating. Cap individual message bubble width at `max-w-prose` (~65ch) instead of `max-w-[85%]` to keep messages readable regardless of container width.

### 3. Mobile-Specific Layout

**Edge-to-edge messages** — Below `md` breakpoint, drop the max-width container constraint. Messages use `px-3` padding directly for full-width utilization.

**Bottom padding** — `pb-14 md:pb-0` on chat input wrapper (covered in bug fixes above, listed here for completeness).

### 4. Auto-Hiding Nav Bar

Two triggers hide the MobileNav on the chat page:

**Keyboard open** — Hook into the existing `visualViewport` resize listener in `ChatPage.tsx`. When `visualViewport.height` shrinks significantly (keyboard appeared), set state that hides MobileNav. Nav returns when keyboard dismisses. This is the bigger space win.

**Scroll down** — Track scroll direction on the message container. Scrolling down slides the nav off-screen (`translate-y-full`, `duration-fast` per design system). Scrolling up or reaching the bottom slides it back. Small scroll threshold (~10px) to prevent jitter.

**Implementation** — A `useMobileNav` hook backed by React context. Interface:
- `hidden: boolean` — whether the nav bar should be hidden
- `setHidden: (hidden: boolean) => void` — setter for pages to control visibility
- Provider wraps the app at the `AppLayout` level
- MobileNav reads `hidden` and applies `translate-y-full` transition
- ChatPage calls `setHidden(true)` on keyboard open / scroll down, `setHidden(false)` on keyboard close / scroll up
- Other pages don't call `setHidden`, so the nav stays visible by default

**Transition** — `translate-y-full` with `duration-fast`. No layout shift, smooth slide.

### 5. Server-Side Conversation Persistence

**Remove `isAuthenticated` gate** — The auth gate lives in `ChatPage.tsx` (lines 151, 241) where `useAuth().isAuthenticated` guards the conversation load on mount and auto-create during submit. Remove those checks. Always use `POST/GET /api/v1/conversations` and `/messages` regardless of auth state.

**Drop localStorage message fallback** — Remove the `nova_chat_history` localStorage persistence from `chat-store.tsx` (the `restoreLocalMessages` function and the `STORAGE_KEY` persistence effect). All messages go through PostgreSQL. localStorage still stores UI preferences (model selection, draft input, context panel state, etc.) — just not conversation history.

**Graceful degradation** — If the orchestrator is unreachable (e.g. during startup), keep messages in the in-memory store so the user can still chat. Retry persisting on the next successful API call. Don't silently lose messages just because the API was briefly unavailable.

**Single continuous conversation** — On mount, fetch the most recent conversation (or create one). No conversation switcher, no list. One thread.

**Future: multi-user auth** — Multi-user authentication with segregated memory instances, guest sessions, and identity-aware conversations is needed before production/family use-cases. Not in scope for this work. Track as a separate initiative.

## Files Affected

| File | Changes |
|------|---------|
| `dashboard/src/components/layout/MobileNav.tsx` | Brain route fix (`/brain`), `brainEnabled` filter update, auto-hide via `useMobileNav` context |
| `dashboard/src/components/layout/AppLayout.tsx` | Wrap children with `MobileNavProvider` |
| `dashboard/src/pages/chat/ChatPage.tsx` | Bottom padding (both layouts), keyboard/scroll hide logic, wider container (4 instances), input alignment, remove `isAuthenticated` gate |
| `dashboard/src/pages/chat/MessageBubble.tsx` | Asymmetric bubble shapes, avatar (with `avatarUrl` fallback), timestamp format change |
| `dashboard/src/pages/chat/ChatInput.tsx` | Pill shape (`rounded-full`), left indent for avatar alignment |
| `dashboard/src/stores/chat-store.tsx` | Drop localStorage message persistence (`restoreLocalMessages`, `STORAGE_KEY` effect) |
| `dashboard/src/hooks/useMobileNav.tsx` | New context + hook for nav bar visibility state |

## Out of Scope

- Conversation list/switcher UI (it's one continuous conversation)
- Native mobile app / PWA manifest
- Multi-user authentication
- Context panel on mobile (remains hidden below `md`)
- Changes to desktop sidebar or desktop-specific layout
