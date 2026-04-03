# Mobile Chat UX & Conversation Persistence — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix mobile chat bugs (Brain route, input overlap), overhaul chat to feel like a messaging app on all screen sizes, add auto-hiding nav bar, and switch to always-on server-side conversation persistence.

**Architecture:** All changes are in the React dashboard. Bug fixes are surgical edits to MobileNav and ChatPage. The chat style overhaul modifies MessageBubble (bubble shapes, avatar, timestamps) and ChatInput (pill shape, alignment). A new `useMobileNav` React context controls nav bar visibility from ChatPage. The persistence change removes the `isAuthenticated` gate in ChatPage and the localStorage message fallback in chat-store, making PostgreSQL the single source of truth.

**Tech Stack:** React 18, TypeScript, Tailwind CSS, TanStack Query, date-fns, react-router-dom

**Spec:** `docs/superpowers/specs/2026-04-01-mobile-chat-ux-design.md`

---

### Task 1: Fix Brain Route in MobileNav

**Files:**
- Modify: `dashboard/src/components/layout/MobileNav.tsx:37,84-85`

- [ ] **Step 1: Fix the Brain tab route**

In `MobileNav.tsx`, change the primaryTabs Brain entry (line 37) from `to: '/'` to `to: '/brain'`:

```tsx
// line 37 — change:
  { to: '/', label: 'Brain', icon: Brain, minRole: 'guest' },
// to:
  { to: '/brain', label: 'Brain', icon: Brain, minRole: 'guest' },
```

- [ ] **Step 2: Update the brainEnabled filter**

The filter on lines 84-86 checks `tab.to !== '/'` to hide Brain when disabled. Update to match the new route:

```tsx
// lines 84-86 — change:
  const visibleTabs = primaryTabs.filter(tab =>
    hasMinRole(userRole, tab.minRole) && (tab.to !== '/' || brainEnabled)
  )
// to:
  const visibleTabs = primaryTabs.filter(tab =>
    hasMinRole(userRole, tab.minRole) && (tab.to !== '/brain' || brainEnabled)
  )
```

- [ ] **Step 3: Verify in browser**

Open mobile view (Chrome DevTools device toolbar, 390px width). Tap the Brain tab — should navigate to `/brain` and render the 3D graph. Toggle brain off in Settings — Brain tab should disappear from the nav bar.

- [ ] **Step 4: Commit**

```bash
git add dashboard/src/components/layout/MobileNav.tsx
git commit -m "fix(dashboard): Brain tab routes to /brain instead of / redirect"
```

---

### Task 2: Create useMobileNav Context

**Files:**
- Create: `dashboard/src/hooks/useMobileNav.tsx`
- Modify: `dashboard/src/components/layout/AppLayout.tsx`

- [ ] **Step 1: Create the context and provider**

Create `dashboard/src/hooks/useMobileNav.tsx`:

```tsx
import { createContext, useContext, useState, type ReactNode } from 'react'

interface MobileNavContext {
  hidden: boolean
  setHidden: (hidden: boolean) => void
}

const MobileNavCtx = createContext<MobileNavContext>({ hidden: false, setHidden: () => {} })

export function MobileNavProvider({ children }: { children: ReactNode }) {
  const [hidden, setHidden] = useState(false)
  return (
    <MobileNavCtx.Provider value={{ hidden, setHidden }}>
      {children}
    </MobileNavCtx.Provider>
  )
}

export function useMobileNav() {
  return useContext(MobileNavCtx)
}
```

- [ ] **Step 2: Wrap AppLayout with the provider**

In `dashboard/src/components/layout/AppLayout.tsx`, import and wrap:

```tsx
// Add import at top:
import { MobileNavProvider } from '../../hooks/useMobileNav'

// Wrap the return (line 49-64) — add provider around the outer div:
  return (
    <MobileNavProvider>
      <div className="flex h-screen bg-surface-root dark:bg-transparent">
        <Sidebar collapsed={collapsed} onToggle={() => setCollapsed(c => !c)} />
        <main className={`flex-1 min-h-0 ${fullWidth ? 'overflow-hidden' : 'overflow-y-auto custom-scrollbar'}`}>
          {fullWidth ? (
            children
          ) : (
            <div className="mx-auto max-w-[1200px] w-full px-6 py-8 animate-fade-in">
              {children}
            </div>
          )}
        </main>
        <MobileNav />
        {isDebug && <LogFrictionButton />}
      </div>
    </MobileNavProvider>
  )
```

- [ ] **Step 3: Commit**

```bash
git add dashboard/src/hooks/useMobileNav.tsx dashboard/src/components/layout/AppLayout.tsx
git commit -m "feat(dashboard): add useMobileNav context for nav bar visibility control"
```

---

### Task 3: Auto-Hide MobileNav on Chat

**Files:**
- Modify: `dashboard/src/components/layout/MobileNav.tsx:88-121`
- Modify: `dashboard/src/pages/chat/ChatPage.tsx:173-191`

- [ ] **Step 1: MobileNav reads hidden state and applies transition**

In `MobileNav.tsx`, import the hook and apply the transition:

```tsx
// Add import at top:
import { useMobileNav } from '../../hooks/useMobileNav'

// Inside MobileNav(), after the brainEnabled line (line 73), add:
  const { hidden } = useMobileNav()

// Change the nav element (line 91) to add transition classes:
// From:
      <nav className="md:hidden fixed bottom-0 left-0 right-0 z-40 bg-surface border-t border-border-subtle pb-[env(safe-area-inset-bottom)] glass-nav dark:border-white/[0.06]">
// To:
      <nav className={clsx(
        'md:hidden fixed bottom-0 left-0 right-0 z-40 bg-surface border-t border-border-subtle pb-[env(safe-area-inset-bottom)] glass-nav dark:border-white/[0.06] transition-transform duration-fast',
        hidden && 'translate-y-full',
      )}>
```

- [ ] **Step 2: ChatPage drives hide state on keyboard open**

In `ChatPage.tsx`, import and use the hook. Modify the existing `visualViewport` effect (lines 173-191) to also hide the nav:

```tsx
// Add import at top:
import { useMobileNav } from '../../hooks/useMobileNav'

// Inside Chat(), add after the other hooks:
  const { setHidden: setNavHidden } = useMobileNav()
  const keyboardOpenRef = useRef(false)

// Replace the visualViewport effect (lines 173-191) with:
  useEffect(() => {
    const vv = window.visualViewport
    if (!vv || !containerRef.current) return
    if (!('ontouchstart' in window)) return

    const onResize = () => {
      if (containerRef.current) {
        containerRef.current.style.height = `${vv.height}px`
      }
      // Hide nav when keyboard is open (viewport shrinks significantly).
      // Compare against window.innerHeight which updates on orientation change.
      const keyboardOpen = vv.height < window.innerHeight - 100
      keyboardOpenRef.current = keyboardOpen
      setNavHidden(keyboardOpen)
      requestAnimationFrame(() => {
        bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
      })
    }
    vv.addEventListener('resize', onResize)
    return () => {
      vv.removeEventListener('resize', onResize)
      keyboardOpenRef.current = false
      setNavHidden(false)
    }
  }, [setNavHidden])
```

- [ ] **Step 3: ChatPage drives hide state on scroll down**

Add a scroll direction tracker effect in `ChatPage.tsx`, after the visualViewport effect:

```tsx
  // Auto-hide mobile nav on scroll down (skip when keyboard is open — keyboard handler takes priority)
  useEffect(() => {
    const el = scrollContainerRef.current
    if (!el || !('ontouchstart' in window)) return

    let lastScrollTop = el.scrollTop
    const threshold = 10

    const onScroll = () => {
      if (keyboardOpenRef.current) return // keyboard handler owns nav state
      const delta = el.scrollTop - lastScrollTop
      if (Math.abs(delta) < threshold) return
      setNavHidden(delta > 0) // scrolling down = hide
      lastScrollTop = el.scrollTop
    }

    el.addEventListener('scroll', onScroll, { passive: true })
    return () => el.removeEventListener('scroll', onScroll)
  }, [setNavHidden])
```

- [ ] **Step 4: Verify in browser**

Mobile device toolbar: scroll down in chat — nav should slide out. Scroll up — nav slides back. Focus the text input (keyboard) — nav should hide. Dismiss keyboard — nav returns.

- [ ] **Step 5: Commit**

```bash
git add dashboard/src/components/layout/MobileNav.tsx dashboard/src/pages/chat/ChatPage.tsx
git commit -m "feat(dashboard): auto-hide mobile nav on keyboard open and scroll down"
```

---

### Task 4: Fix Input Overlap (Bottom Padding)

**Files:**
- Modify: `dashboard/src/pages/chat/ChatPage.tsx:470,521`

- [ ] **Step 1: Add bottom padding to both input wrappers**

In `ChatPage.tsx`, both the empty-state input wrapper (line 470) and the active-chat input wrapper (line 521) need mobile bottom padding.

```tsx
// line 470 — empty state input wrapper, change:
            <div className="shrink-0 w-full px-4 md:px-8 pb-4">
// to:
            <div className="shrink-0 w-full px-4 md:px-8 pb-16 md:pb-4">

// line 521 — active chat input wrapper, change:
            <div className="shrink-0 w-full px-4 md:px-8 pb-4">
// to:
            <div className="shrink-0 w-full px-4 md:px-8 pb-16 md:pb-4">
```

Note: `pb-16` (64px) instead of `pb-14` (56px) to give a bit of breathing room above the 56px nav bar.

- [ ] **Step 2: Verify in browser**

Mobile view: the chat input should sit clearly above the bottom nav bar with visible spacing. Desktop view: should have the same compact `pb-4` as before.

- [ ] **Step 3: Commit**

```bash
git add dashboard/src/pages/chat/ChatPage.tsx
git commit -m "fix(dashboard): add mobile bottom padding so chat input clears nav bar"
```

---

### Task 5: Chat Style — MessageBubble Overhaul

**Files:**
- Modify: `dashboard/src/pages/chat/MessageBubble.tsx`

This is the biggest visual change. Replaces bubble shapes, adds avatar fallback logic, and changes timestamp format.

- [ ] **Step 1: Rewrite MessageBubble.tsx**

Replace the full contents of `dashboard/src/pages/chat/MessageBubble.tsx`:

```tsx
import { memo, useMemo } from 'react'
import { useNovaIdentity } from '../../hooks/useNovaIdentity'
import { User, FileText } from 'lucide-react'
import { format } from 'date-fns'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import clsx from 'clsx'
import { ActivityFeed } from '../../components/ActivityFeed'
import { cleanToolArtifacts } from '../../utils/cleanToolArtifacts'
import type { Message } from '../../stores/chat-store'

export const MessageBubble = memo(function MessageBubble({ message }: { message: Message }) {
  const { avatarUrl, isDefaultAvatar } = useNovaIdentity()
  const isUser = message.role === 'user'
  const isThinking = !isUser && message.isStreaming && !message.content
  const cleanedContent = useMemo(
    () => !isUser && message.content ? cleanToolArtifacts(message.content) : message.content,
    [isUser, message.content],
  )

  return (
    <div className={clsx('flex gap-2', isUser ? 'justify-end' : 'items-start')}>
      {/* Assistant avatar */}
      {!isUser && (
        isDefaultAvatar ? (
          <div className={clsx(
            'mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-xs font-semibold',
            isThinking
              ? 'bg-amber-500/20 text-amber-400'
              : 'bg-teal-500/20 text-teal-400',
          )}>
            N
          </div>
        ) : (
          <img src={avatarUrl} alt="Nova" className={clsx(
            'mt-0.5 h-7 w-7 shrink-0 rounded-full object-cover',
            isThinking && 'ring-2 ring-amber-500/40',
          )} />
        )
      )}

      {/* Bubble column */}
      <div className={clsx(
        isUser ? 'max-w-[80%] md:max-w-prose' : 'flex-1 min-w-0 max-w-prose',
      )}>
        <div
          className={clsx(
            'text-compact leading-relaxed',
            isUser
              ? 'glass-card text-content-primary whitespace-pre-wrap rounded-tl-xl rounded-tr-sm rounded-br-xl rounded-bl-xl px-4 py-3'
              : clsx(
                  'glass-card text-content-primary markdown-body overflow-x-auto rounded-tl-sm rounded-tr-xl rounded-br-xl rounded-bl-xl px-5 py-[18px]',
                  isThinking && 'border-amber-500/15',
                ),
          )}
        >
          {!isUser && message.activitySteps && message.activitySteps.length > 0 && (
            <ActivityFeed
              steps={message.activitySteps}
              collapsed={message.activityCollapsed ?? false}
              isStreaming={message.isStreaming ?? false}
            />
          )}

          {/* User message attachments */}
          {isUser && message.attachments && message.attachments.length > 0 && (
            <div className="flex flex-wrap gap-2 mb-2">
              {message.attachments.map(att =>
                att.type === 'image' && att.previewUrl ? (
                  <img
                    key={att.id}
                    src={att.previewUrl}
                    alt={att.file.name}
                    className="max-w-[200px] max-h-[150px] rounded-sm object-cover"
                  />
                ) : (
                  <span
                    key={att.id}
                    className="inline-flex items-center gap-1 rounded-xs bg-accent-500/20 px-2 py-1 text-micro"
                  >
                    <FileText size={12} />
                    {att.file.name}
                  </span>
                ),
              )}
            </div>
          )}

          {cleanedContent ? (
            isUser ? cleanedContent : (
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {cleanedContent}
              </ReactMarkdown>
            )
          ) : message.isStreaming ? (
            <span className="inline-flex items-center gap-1 py-1">
              <span className={clsx(
                'h-1.5 w-1.5 rounded-full animate-bounce [animation-delay:-0.3s]',
                isThinking ? 'bg-amber-400 dark:shadow-[0_0_6px_rgb(251_191_36/0.5)]' : 'bg-accent dark:shadow-[0_0_6px_rgb(var(--accent-500)/0.5)]',
              )} />
              <span className={clsx(
                'h-1.5 w-1.5 rounded-full animate-bounce [animation-delay:-0.15s]',
                isThinking ? 'bg-amber-400 dark:shadow-[0_0_6px_rgb(251_191_36/0.5)]' : 'bg-accent dark:shadow-[0_0_6px_rgb(var(--accent-500)/0.5)]',
              )} />
              <span className={clsx(
                'h-1.5 w-1.5 rounded-full animate-bounce',
                isThinking ? 'bg-amber-400 dark:shadow-[0_0_6px_rgb(251_191_36/0.5)]' : 'bg-accent dark:shadow-[0_0_6px_rgb(var(--accent-500)/0.5)]',
              )} />
            </span>
          ) : '\u2014'}
        </div>

        {/* Footer: time, model, category, channel */}
        <p
          className={clsx(
            'mt-1 font-mono text-mono-sm text-content-tertiary px-1',
            isUser && 'text-right',
          )}
        >
          {format(message.timestamp, 'h:mm a')}
          {message.metadata?.channel === 'telegram' && (
            <span className="ml-1.5 text-content-tertiary/50">via Telegram</span>
          )}
          {!isUser && message.modelUsed && (
            <span className="ml-1.5">
              &middot; {message.modelUsed}
              {message.category && (
                <span className="text-content-tertiary/60"> ({message.category})</span>
              )}
            </span>
          )}
        </p>
      </div>

      {/* User avatar */}
      {isUser && (
        <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-surface-elevated text-content-secondary">
          <User size={13} />
        </div>
      )}
    </div>
  )
})
```

Key changes from the original:
- `formatDistanceToNow` replaced with `format(timestamp, 'h:mm a')` — import changes from `{ formatDistanceToNow }` to `{ format }`
- Bubble shapes: assistant gets `rounded-tl-sm rounded-tr-xl rounded-br-xl rounded-bl-xl`, user gets `rounded-tl-xl rounded-tr-sm rounded-br-xl rounded-bl-xl`
- Removed `border-l-2 border-teal-800` from assistant bubble (the flat corner is the new "tail")
- Avatar: uses teal "N" circle when `isDefaultAvatar`, otherwise renders the custom `<img>`. Amber variant when `isThinking`.
- Max-width: `max-w-prose` instead of `max-w-[85%]`
- User avatar moved to right side of the flex row
- Thinking dots use amber instead of teal when `isThinking`

- [ ] **Step 2: Verify in browser**

Check on both desktop and mobile views:
- Assistant messages: flat top-left corner, teal "N" avatar on the left, absolute timestamp
- User messages: flat top-right corner, user icon on the right
- While streaming with no content yet: amber avatar, amber dots
- Long messages should cap at `max-w-prose` (~65ch) width

- [ ] **Step 3: Commit**

```bash
git add dashboard/src/pages/chat/MessageBubble.tsx
git commit -m "feat(dashboard): messaging-app bubble style with asymmetric corners, avatar, timestamps"
```

---

### Task 6: Chat Style — Pill Input and Alignment

**Files:**
- Modify: `dashboard/src/pages/chat/ChatInput.tsx:167-168`
- Modify: `dashboard/src/pages/chat/ChatPage.tsx:459,471,480,522`

- [ ] **Step 1: Change ChatInput to pill shape**

In `ChatInput.tsx`, change the outer container border-radius (line 168). Use `rounded-3xl` instead of `rounded-full` — the container grows when the textarea expands to multiple lines, and `rounded-full` (9999px) creates an ugly capsule shape on tall elements. `rounded-3xl` (24px) gives the pill feel at single-line height and degrades gracefully when multi-line:

```tsx
// line 167-168 — change:
        'relative bg-surface rounded-2xl border border-border-subtle p-3 safe-area-pb shadow-sm transition-colors duration-fast',
// to:
        'relative bg-surface rounded-3xl border border-border-subtle p-3 safe-area-pb shadow-sm transition-colors duration-fast',
```

- [ ] **Step 2: Widen desktop container and add input alignment**

In `ChatPage.tsx`, update all 4 instances of `max-w-[780px]` to responsive widths, and add input alignment padding.

```tsx
// line 459 — empty state messages container, change:
              <div className="max-w-[780px] mx-auto px-4 md:px-8 py-6">
// to:
              <div className="mx-auto px-3 md:px-8 py-6 max-w-none md:max-w-3xl xl:max-w-4xl">

// line 471 — empty state input wrapper inner div, change:
              <div className="max-w-[780px] mx-auto">
// to:
              <div className="mx-auto pl-0 md:pl-9 max-w-none md:max-w-3xl xl:max-w-4xl">

// line 480 — active chat messages container, change:
              <div className="max-w-[780px] mx-auto px-4 md:px-8 py-6 space-y-6">
// to:
              <div className="mx-auto px-3 md:px-8 py-6 space-y-4 max-w-none md:max-w-3xl xl:max-w-4xl">

// line 522 — active chat input wrapper inner div, change:
              <div className="max-w-[780px] mx-auto">
// to:
              <div className="mx-auto pl-0 md:pl-9 max-w-none md:max-w-3xl xl:max-w-4xl">
```

Notes:
- `max-w-none` on mobile = edge-to-edge. `md:max-w-3xl xl:max-w-4xl` on desktop = responsive widening.
- `px-3` on mobile (tighter), `md:px-8` on desktop (existing).
- `pl-0 md:pl-9` on input wrappers = no indent on mobile (no avatars column offset needed with edge-to-edge), `pl-9` on desktop aligns with the bubble content after the 28px avatar + 8px gap = 36px = `pl-9`.
- `space-y-6` reduced to `space-y-4` for tighter message spacing (messaging-app feel).

- [ ] **Step 3: Verify in browser**

Desktop: chat container should be wider (768px, up to 896px on XL screens). Input left edge should align with where message bubble text starts (offset by avatar column). Mobile: messages edge-to-edge with small padding, input full-width.

- [ ] **Step 4: Commit**

```bash
git add dashboard/src/pages/chat/ChatInput.tsx dashboard/src/pages/chat/ChatPage.tsx
git commit -m "feat(dashboard): pill-shaped input, wider desktop chat, input alignment with avatar column"
```

---

### Task 7: Server-Side Conversation Persistence

**Files:**
- Modify: `dashboard/src/pages/chat/ChatPage.tsx:39,148-171,239-253`
- Modify: `dashboard/src/stores/chat-store.tsx:85-111,116-135,138-142,190-200,250-258`

- [ ] **Step 1: Remove isAuthenticated gate in ChatPage**

In `ChatPage.tsx`, the conversation load on mount (lines 148-171) and auto-create during submit (lines 239-253) are gated behind `isAuthenticated`. Remove the gate.

```tsx
// line 39 — remove isAuthenticated from destructuring:
// change:
  const { isAuthenticated } = useAuth()
// to:
  // Auth import and destructuring can be removed entirely if not used elsewhere
  // Check: isAuthenticated is used on lines 151 and 241. Remove those checks.

// lines 148-171 — conversation load on mount. Change:
    if (!isAuthenticated) return

    if (conversationId) {
// to (remove the guard):
    if (conversationId) {

// lines 239-253 — auto-create during submit. Change:
    let activeConversationId = conversationId
    if (isAuthenticated && !activeConversationId) {
// to:
    let activeConversationId = conversationId
    if (!activeConversationId) {
```

If `useAuth` is no longer used in ChatPage after this, remove the import and destructuring entirely.

- [ ] **Step 2: Remove localStorage message persistence from chat-store**

In `chat-store.tsx`:

Remove the `restoreLocalMessages` function (lines 116-135) and its call on line 139. Remove the localStorage persistence effect (lines 190-200). Keep the `STORAGE_KEY` constant and the `hasLegacyChat`/`getLegacyChat`/`clearLegacyChat` exports — they may be used elsewhere for migration.

```tsx
// line 139 — remove the call:
// change:
  const stored = restoreLocalMessages()
  const activeConvId = localStorage.getItem('nova_active_conversation')

  const [messages, setMessages] = useState<Message[]>(activeConvId ? [] : stored.messages)
  const [sessionId, setSessionId] = useState<string | undefined>(
    activeConvId ?? stored.sessionId ?? undefined
  )
// to:
  const activeConvId = localStorage.getItem('nova_active_conversation')

  const [messages, setMessages] = useState<Message[]>([])
  const [sessionId, setSessionId] = useState<string | undefined>(
    activeConvId ?? undefined
  )

// lines 190-200 — remove the localStorage message persistence effect entirely:
// DELETE:
  // Persist messages to localStorage for unauthenticated users
  useEffect(() => {
    if (conversationId) return  // Authenticated: Postgres handles persistence
    if (messages.length === 0 && !sessionIdRef.current) return  // Nothing to persist
    localStorage.setItem(STORAGE_KEY, JSON.stringify({
      sessionId: sessionIdRef.current,
      messages: messages
        .filter(m => !m.isStreaming)
        .map(m => ({ id: m.id, role: m.role, content: m.content, timestamp: m.timestamp.toISOString(), modelUsed: m.modelUsed })),
    }))
  }, [messages, conversationId])

// line 257 — in resetConversation, remove localStorage.removeItem:
// change:
    localStorage.removeItem(STORAGE_KEY)
// to:
    // (remove this line)
```

- [ ] **Step 3: Keep graceful degradation for API failures**

The existing `newConversation` (lines 229-248) already falls back to local-only on API failure. The `handleSubmit` in ChatPage (lines 241-253) catches conversation creation failure and continues without persistence. This is the correct graceful degradation — messages stay in the in-memory React state even if the API is unreachable. No additional changes needed here.

- [ ] **Step 4: Verify behavior**

1. Start Nova services (`make dev`)
2. Open chat, send a message — should create a server-side conversation
3. Refresh page — message history should reload from PostgreSQL
4. Open in a different browser/device — same conversation should appear
5. Stop the orchestrator — sending a message should still work (no persistence, but no crash)
6. Restart orchestrator — new messages should persist again

- [ ] **Step 5: Commit**

```bash
git add dashboard/src/pages/chat/ChatPage.tsx dashboard/src/stores/chat-store.tsx
git commit -m "feat(dashboard): always-on server-side conversation persistence, drop localStorage fallback"
```

---

### Task 8: Final Verification and Cleanup

**Files:**
- All modified files

- [ ] **Step 1: TypeScript compilation check**

```bash
cd dashboard && npm run build
```

Expected: clean build, no type errors.

- [ ] **Step 2: Full mobile QA in browser**

Using Chrome DevTools device toolbar (iPhone 14, 390x844):

1. Chat page: input above nav bar, pill-shaped, aligned with message content
2. Messages: asymmetric bubble corners, avatar, absolute timestamps
3. Scroll down in chat: nav bar slides away
4. Focus input (simulate keyboard): nav bar hides
5. Brain tab: navigates to `/brain`, shows graph
6. Send message, refresh: messages persist from server
7. Desktop (full width): wider chat area, messages cap at `max-w-prose`

- [ ] **Step 3: Commit any remaining fixes**

```bash
git add -A
git commit -m "fix(dashboard): mobile chat UX polish and cleanup"
```
