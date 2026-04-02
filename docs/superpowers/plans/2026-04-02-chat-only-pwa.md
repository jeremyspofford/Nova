# Chat-Only Mobile PWA — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Scope the mobile PWA to chat-only with a send/mic morph button, compact model chip, and no bottom nav bar.

**Architecture:** A `useIsMobile` hook wraps `matchMedia` for consistent mobile detection. A `MobileGuard` component in `App.tsx` redirects non-chat routes on mobile. `AppLayout` conditionally omits `MobileNav`. `ChatInput` replaces three voice/send buttons with a single `MorphButton` that context-switches between send, mic, and stop states. A compact `ModelPicker` instance provides model selection on mobile.

**Tech Stack:** React 18, TypeScript, Tailwind CSS, Lucide icons, date-fns

**Spec:** `docs/superpowers/specs/2026-04-02-chat-only-pwa-design.md`

---

### Task 1: Create useIsMobile Hook

**Files:**
- Create: `dashboard/src/hooks/useIsMobile.ts`

- [ ] **Step 1: Create the hook**

```ts
import { useSyncExternalStore } from 'react'

const MQ = '(min-width: 768px)'

function subscribe(cb: () => void) {
  const mql = window.matchMedia(MQ)
  mql.addEventListener('change', cb)
  return () => mql.removeEventListener('change', cb)
}

function getSnapshot() {
  return !window.matchMedia(MQ).matches
}

function getServerSnapshot() {
  return false // SSR fallback: assume desktop
}

/** Returns true when viewport is below Tailwind's `md` breakpoint (768px). */
export function useIsMobile() {
  return useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot)
}
```

Uses `useSyncExternalStore` for tear-free reads — the same pattern React docs recommend for `matchMedia`. Stays in sync with Tailwind's `md:` breakpoint exactly.

- [ ] **Step 2: Commit**

```bash
git add dashboard/src/hooks/useIsMobile.ts
git commit -m "feat(dashboard): add useIsMobile hook using matchMedia"
```

---

### Task 2: Mobile Route Guard

**Files:**
- Modify: `dashboard/src/App.tsx`

- [ ] **Step 1: Add MobileGuard component and wrap non-chat routes**

In `App.tsx`, add import at top:
```tsx
import { useIsMobile } from './hooks/useIsMobile'
```

Add this component after `HomeRoute` (around line 128):
```tsx
/** On mobile viewports, redirect all non-chat routes to /chat. */
function MobileGuard({ children }: { children: React.ReactNode }) {
  const isMobile = useIsMobile()
  if (isMobile) return <Navigate to="/chat" replace />
  return <>{children}</>
}
```

Then wrap every non-chat `AppLayout` route with `MobileGuard`. Change lines 169-184 from:
```tsx
<Route path="/brain" element={<AppLayout fullWidth><ErrorBoundary><Brain /></ErrorBoundary></AppLayout>} />
<Route path="/chat" element={<AppLayout fullWidth><ErrorBoundary><Chat /></ErrorBoundary></AppLayout>} />
<Route path="/tasks" element={<AppLayout><ErrorBoundary><Tasks /></ErrorBoundary></AppLayout>} />
```
to:
```tsx
<Route path="/brain" element={<MobileGuard><AppLayout fullWidth><ErrorBoundary><Brain /></ErrorBoundary></AppLayout></MobileGuard>} />
<Route path="/chat" element={<AppLayout fullWidth><ErrorBoundary><Chat /></ErrorBoundary></AppLayout>} />
<Route path="/tasks" element={<MobileGuard><AppLayout><ErrorBoundary><Tasks /></ErrorBoundary></AppLayout></MobileGuard>} />
```

Apply `MobileGuard` to ALL routes except `/chat`, `/login`, `/onboarding`, `/invite/:code`, `/expired`, `/dev/components`, and `/` (HomeRoute already goes to /chat). That means wrap: `/brain`, `/tasks`, `/friction`, `/pods`, `/usage`, `/goals`, `/sources`, `/integrations`, `/models`, `/editors`, `/users`, `/settings`, `/recovery`, `/benchmarks`, `/about`.

- [ ] **Step 2: Verify in browser**

Mobile view (390px): navigate to `/brain` → should redirect to `/chat`. Navigate to `/settings` → redirect to `/chat`. Desktop (1440px): `/brain` should render normally.

- [ ] **Step 3: Commit**

```bash
git add dashboard/src/App.tsx
git commit -m "feat(dashboard): redirect non-chat routes to /chat on mobile viewports"
```

---

### Task 3: Remove MobileNav on Mobile

**Files:**
- Modify: `dashboard/src/components/layout/AppLayout.tsx`
- Modify: `dashboard/src/pages/chat/ChatPage.tsx`

- [ ] **Step 1: Conditionally render MobileNav only on desktop**

In `AppLayout.tsx`, add import:
```tsx
import { useIsMobile } from '../../hooks/useIsMobile'
```

Inside the `AppLayout` function, add:
```tsx
const isMobile = useIsMobile()
```

Change line 63 from:
```tsx
        <MobileNav />
```
to:
```tsx
        {!isMobile && <MobileNav />}
```

- [ ] **Step 2: Remove mobile nav padding from ChatPage**

In `ChatPage.tsx`, change both instances of `pb-16 md:pb-4` to `pb-4`:

Line 497:
```tsx
// change:
            <div className="shrink-0 w-full px-4 md:px-8 pb-16 md:pb-4">
// to:
            <div className="shrink-0 w-full px-4 md:px-8 pb-4">
```

Line 548:
```tsx
// change:
            <div className="shrink-0 w-full px-4 md:px-8 pb-16 md:pb-4">
// to:
            <div className="shrink-0 w-full px-4 md:px-8 pb-4">
```

- [ ] **Step 3: Verify in browser**

Mobile view: no bottom nav bar visible. Chat input sits at the bottom with just `safe-area-pb` spacing. Desktop view: sidebar visible, no bottom nav (as before — MobileNav was always `md:hidden`).

- [ ] **Step 4: Commit**

```bash
git add dashboard/src/components/layout/AppLayout.tsx dashboard/src/pages/chat/ChatPage.tsx
git commit -m "feat(dashboard): skip MobileNav render on mobile, remove nav bar padding from chat"
```

---

### Task 4: Create MorphButton Component

**Files:**
- Create: `dashboard/src/components/ui/MorphButton.tsx`

- [ ] **Step 1: Create the morph button**

```tsx
import { useState, useRef, useCallback } from 'react'
import { Send, Mic, Square, Loader2 } from 'lucide-react'
import clsx from 'clsx'

interface MorphButtonProps {
  hasText: boolean
  isRecording: boolean
  isTranscribing: boolean
  conversationMode: boolean
  voiceAvailable: boolean
  onSend: () => void
  onToggleRecording: () => void
  onStartConversation: () => void
  onStopConversation: () => void
}

type MorphState = 'mic' | 'send' | 'stop-recording' | 'stop-conversation' | 'transcribing'

function getMorphState(props: MorphButtonProps): MorphState {
  // Priority order per spec
  if (props.isRecording) return 'stop-recording'
  if (props.conversationMode) return 'stop-conversation'
  if (props.isTranscribing) return 'transcribing'
  if (props.hasText) return 'send'
  if (props.voiceAvailable) return 'mic'
  return 'send' // No voice: always show send (disabled when empty via hasText)
}

const LONG_PRESS_MS = 500

export function MorphButton(props: MorphButtonProps) {
  const { voiceAvailable, onSend, onToggleRecording, onStartConversation, onStopConversation } = props
  const state = getMorphState(props)
  const longPressTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const [longPressTriggered, setLongPressTriggered] = useState(false)
  const [showHint, setShowHint] = useState(() => {
    try { return !localStorage.getItem('nova_morph_hint_dismissed') } catch { return true }
  })

  const handlePointerDown = useCallback(() => {
    if (state !== 'mic' || !voiceAvailable) return
    setLongPressTriggered(false)
    longPressTimer.current = setTimeout(() => {
      setLongPressTriggered(true)
      onStartConversation()
      // Dismiss hint permanently
      if (showHint) {
        setShowHint(false)
        try { localStorage.setItem('nova_morph_hint_dismissed', '1') } catch {}
      }
    }, LONG_PRESS_MS)
  }, [state, voiceAvailable, onStartConversation, showHint])

  const handlePointerUp = useCallback(() => {
    if (longPressTimer.current) {
      clearTimeout(longPressTimer.current)
      longPressTimer.current = null
    }
    // If long press already triggered conversation mode, don't also do a tap action
    if (longPressTriggered) {
      setLongPressTriggered(false)
      return
    }
  }, [longPressTriggered])

  const handleClick = useCallback(() => {
    if (longPressTriggered) return // handled by pointerUp
    switch (state) {
      case 'send': onSend(); break
      case 'mic': onToggleRecording(); break
      case 'stop-recording': onToggleRecording(); break
      case 'stop-conversation': onStopConversation(); break
      case 'transcribing': break // disabled
    }
  }, [state, longPressTriggered, onSend, onToggleRecording, onStopConversation])

  const disabled = state === 'transcribing'
  const isStop = state === 'stop-recording'
  const isConvStop = state === 'stop-conversation'

  return (
    <div className="relative shrink-0">
      <button
        type="button"
        onClick={handleClick}
        onPointerDown={handlePointerDown}
        onPointerUp={handlePointerUp}
        onPointerLeave={handlePointerUp}
        disabled={disabled}
        className={clsx(
          'w-11 h-11 rounded-full flex items-center justify-center transition-all duration-150 shrink-0',
          isStop
            ? 'bg-danger text-white hover:bg-red-500'
            : isConvStop
              ? 'bg-amber-500 text-neutral-950 hover:bg-amber-400'
              : 'bg-teal-500 hover:bg-teal-600 text-white shadow-[0_0_12px_rgba(25,168,158,0.3)] hover:shadow-[0_0_20px_rgba(25,168,158,0.4)]',
          disabled && 'opacity-40 cursor-wait',
        )}
      >
        {state === 'transcribing' && <Loader2 size={16} className="animate-spin" />}
        {state === 'send' && <Send size={16} />}
        {state === 'mic' && <Mic size={16} />}
        {state === 'stop-recording' && <Square size={14} fill="currentColor" />}
        {state === 'stop-conversation' && <Square size={14} fill="currentColor" />}
      </button>
      {/* One-time hint for long-press */}
      {showHint && state === 'mic' && voiceAvailable && (
        <div className="absolute -top-8 left-1/2 -translate-x-1/2 whitespace-nowrap bg-surface-elevated text-content-secondary text-micro px-2 py-1 rounded-md shadow-sm border border-border-subtle pointer-events-none animate-fade-in">
          Hold for conversation
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 2: Commit**

```bash
git add dashboard/src/components/ui/MorphButton.tsx
git commit -m "feat(dashboard): add MorphButton — send/mic/stop with long-press conversation mode"
```

---

### Task 5: Mobile Model Chip (Reusing ModelPicker)

No new component needed. The existing `ModelPicker` accepts `className` and `buttonClassName` props. We render a second `ModelPicker` instance inside the `ChatInput` card with compact mobile styling, visible only below `md`.

This is implemented directly in Task 6 (ChatInput integration) — no separate task or file needed.

---

### Task 6: Integrate MorphButton and MobileModelChip into ChatInput

**Files:**
- Modify: `dashboard/src/pages/chat/ChatInput.tsx`

This is the biggest task — replaces the three voice/send buttons with the morph button and adds the mobile model chip.

- [ ] **Step 1: Add imports**

At the top of `ChatInput.tsx`, add:
```tsx
import { MorphButton } from '../../components/ui/MorphButton'
```

(`ModelPicker` is already imported.)

- [ ] **Step 2: Add mobile model chip inside the card**

After the `<FilePreviewBar>` line (line 280), add a mobile-only `ModelPicker` with compact styling:

```tsx
      <FilePreviewBar files={pendingFiles} onRemove={removeFile} />

      {/* Mobile model selector — compact chip, reuses ModelPicker */}
      <div className="md:hidden mb-1">
        <ModelPicker
          value={modelId}
          onChange={onModelChange}
          models={modelPickerItems}
          className="w-auto"
          buttonClassName="flex items-center gap-1 px-2.5 py-1 bg-surface-elevated rounded-full text-micro font-mono text-content-secondary cursor-pointer border-none"
        />
      </div>
```

- [ ] **Step 3: Replace the three voice/send buttons with MorphButton**

Remove the entire voice controls section (lines 323-366, the `hidden md:contents` div with conversation mode toggle and mic button) AND the send button (lines 368-375).

Replace both with a single MorphButton:

```tsx
        {/* Morph button: send / mic / stop */}
        <MorphButton
          hasText={!!input.trim()}
          isRecording={voice?.isRecording ?? false}
          isTranscribing={voice?.isTranscribing ?? false}
          conversationMode={voice?.conversationMode ?? false}
          voiceAvailable={!!voice?.available}
          onSend={handleSubmit}
          onToggleRecording={voice?.toggleRecording ?? (() => {})}
          onStartConversation={() => voice?.setConversationMode(true)}
          onStopConversation={() => voice?.setConversationMode(false)}
        />
```

- [ ] **Step 4: Remove the `hidden md:block` wrapper from the drawer toggle**

The drawer toggle (lines 283-309) is currently wrapped in `<div className="hidden md:block shrink-0">`. The MorphButton handles mobile input now, but the drawer toggle should still be desktop-only. Keep the `hidden md:block` wrapper as-is.

- [ ] **Step 5: Remove old send button disabled logic note**

The old send button had `disabled={!input.trim() || voice?.conversationMode}`. MorphButton handles its own disabled state internally (only disabled during transcription). No change needed — just noting the old logic is gone.

- [ ] **Step 6: Verify in browser**

Mobile (390px): Should see textarea + morph button (mic icon when empty, send icon when typing). Tap mic → recording indicator. Model chip above textarea. No other buttons.

Desktop (1440px): Should see model picker row, drawer toggle, textarea, morph button. Same morph behavior.

- [ ] **Step 7: Commit**

```bash
git add dashboard/src/pages/chat/ChatInput.tsx
git commit -m "feat(dashboard): integrate MorphButton and MobileModelChip into ChatInput"
```

---

### Task 7: Change Voice Transcript to Fill Textarea (Not Auto-Submit)

**Files:**
- Modify: `dashboard/src/pages/chat/ChatPage.tsx`

- [ ] **Step 1: Change handleVoiceTranscript**

In `ChatPage.tsx`, find the `handleVoiceTranscript` callback (around line 96):

```tsx
  const handleVoiceTranscript = useCallback((text: string) => {
    if (isStreamingRef.current) {
      pendingTranscriptRef.current = text
    } else {
      handleSubmitRef.current(text)
    }
  }, [])
```

Change it to fill the textarea instead of auto-submitting. Import `useChatStore` is already available via the destructuring at the top. Add `setDraftInput` to the destructured values if not already there, then:

```tsx
  const handleVoiceTranscript = useCallback((text: string) => {
    if (isStreamingRef.current) {
      pendingTranscriptRef.current = text
    } else {
      // Fill textarea for review instead of auto-submitting
      setDraftInput(text)
    }
  }, [setDraftInput])
```

Check that `setDraftInput` is already destructured from `useChatStore()` at the top of `Chat()`. Looking at the current code, `useChatStore()` destructures many values but the draft input is accessed via `useChatStore()` in `ChatInput`, not in `ChatPage`. We need to add it.

Find the `useChatStore()` destructuring in `Chat()` (around line 25):
```tsx
  const {
    messages, setMessages,
    sessionId, setSessionId,
    conversationId, setConversationId,
    modelId, setModelId,
    error, setError,
    resetConversation,
    loadConversation,
    pendingFiles, setPendingFiles,
    outputStyle,
    customInstructions,
    webSearchEnabled,
    deepResearchEnabled,
  } = useChatStore()
```

Add `setDraftInput` to the destructuring:
```tsx
  const {
    messages, setMessages,
    sessionId, setSessionId,
    conversationId, setConversationId,
    modelId, setModelId,
    error, setError,
    resetConversation,
    loadConversation,
    pendingFiles, setPendingFiles,
    outputStyle,
    customInstructions,
    webSearchEnabled,
    deepResearchEnabled,
    setDraftInput,
  } = useChatStore()
```

Also update the pending transcript drain effect (around line 388) to fill textarea instead of submitting:
```tsx
  // Drain pending voice transcript when streaming ends
  useEffect(() => {
    if (!isStreaming && pendingTranscriptRef.current) {
      const text = pendingTranscriptRef.current
      pendingTranscriptRef.current = null
      setDraftInput(text)
    }
  }, [isStreaming, setDraftInput])
```

Clean up the now-dead `handleSubmitRef` code. Remove:
- `const handleSubmitRef = useRef<(text: string) => void>(() => {})` (around line 89)
- The sync effect `handleSubmitRef.current = handleSubmit` (around line 408-411)

- [ ] **Step 2: Verify behavior**

Test push-to-talk: tap mic, speak, tap stop → text should appear in textarea (not auto-send). User can edit, then tap send.

- [ ] **Step 3: Commit**

```bash
git add dashboard/src/pages/chat/ChatPage.tsx
git commit -m "feat(dashboard): voice transcript fills textarea for review instead of auto-submitting"
```

---

### Task 8: Build Verification

**Files:**
- All modified files

- [ ] **Step 1: TypeScript build check**

```bash
cd dashboard && npm run build
```

Expected: clean build, no type errors.

- [ ] **Step 2: Mobile QA (390x844)**

1. Navigate to `/brain` → redirects to `/chat`
2. Navigate to `/settings` → redirects to `/chat`
3. No bottom nav bar visible
4. Model chip above textarea, tap opens dropdown
5. Empty textarea: morph button shows mic
6. Type text: morph button shows send
7. Tap send: message sends
8. Clear text, tap mic: recording starts, indicator appears
9. Tap stop: transcript fills textarea (not auto-sent)
10. Rotate device: still on chat, no nav bar appears

- [ ] **Step 3: Desktop QA (1440x900)**

1. All routes accessible (no redirect)
2. Sidebar, context panel visible
3. Morph button replaces old 3-button layout
4. Model picker row still visible
5. Drawer toggle still visible
6. Long-press mic: conversation mode activates

- [ ] **Step 4: Commit any fixes**

```bash
git add -A
git commit -m "fix(dashboard): chat-only PWA polish and cleanup"
```
