# UI/UX Audit — 2026-04-16

## Scope

Reviewed the Nova React dashboard (`dashboard/src/`) against `DESIGN.md`, the three dashboard/UX redesign specs (`2026-03-16-dashboard-redesign`, `2026-03-28-dashboard-nav-restructure`, `2026-04-01-mobile-chat-ux`, `2026-04-02-chat-only-pwa`), and the skills/rules specs. Focus areas: design-system conformance, empty/loading/error states, tab persistence, keyboard affordances, a11y spot-checks, mobile/PWA readiness, error recovery, first-run experience, and shipping status of unified chat PWA and Skills/Rules UI.

Out of scope: full WCAG 2.1 audit, taste-level visual critique, backend behavior, feature-completeness (see `feature-completeness.md`).

Evidence is grounded in specific file paths and line numbers. The stack is currently running; I relied on code review, not in-browser verification.

---

## Findings

### [P1] Five legacy auth/boot pages bypass the design system entirely

- **Evidence:**
  - `dashboard/src/pages/Expired.tsx:7-24` — hardcoded `bg-neutral-50 dark:bg-neutral-950`, `text-neutral-900`, `bg-neutral-700`, raw `button` with Tailwind classes, `text-2xl` emoji clock; no `Card`, `Button`, or token usage.
  - `dashboard/src/pages/Invite.tsx:31-46, 89-170` — identical pattern: `bg-neutral-50 dark:bg-neutral-950`, `bg-teal-600 hover:bg-teal-700`, `rounded-lg` buttons built by hand. 31 `text-sm` / `text-xs` hits and 20+ `neutral-*` references in one file.
  - `dashboard/src/components/StartupScreen.tsx:37-140` — hand-rolled card (`bg-white dark:bg-neutral-900`), `bg-emerald-500` / `bg-red-500` status dots, `text-accent-700 dark:text-accent-400` uppercase title, raw `<button>` rather than the `Button` component. First screen a user sees during cold boot.
  - `dashboard/src/App.tsx:75-79` — `AuthGate`'s own loading splash uses `bg-neutral-50 dark:bg-neutral-950` + `text-neutral-400`, no glass tier or token.
  - `dashboard/src/pages/onboarding/OnboardingWizard.tsx:88-90` — onboarding step-circle uses `text-neutral-950` on accent (hardcoded hex-style neutral) instead of `text-content-*` tokens.
- **Impact:** These are the highest-stakes surfaces a new user encounters (startup, first-run onboarding, expired/invited/logged-out states). They feel like a different product from the rest of the dashboard — no Plus Jakarta Sans hierarchy tokens (`text-h1`, `text-body`), no glass tiers, no custom Nova teal (the hardcoded `teal-600` in Invite bypasses the Nova teal palette defined in `DESIGN.md §Color`). A user hitting a stale bookmark at `/expired` or `/invite/:code` sees a visually inconsistent screen that undermines the "calm control room" aesthetic.
- **Recommendation:** Rewrite each file using `components/ui`: `Card` with `glass-card` tier, `Button` with `variant="primary"`, type tokens (`text-h1`, `text-caption`, `text-compact`), surface tokens (`bg-surface-root`, `text-content-primary/secondary`). StartupScreen especially should use `glass-card` and the same Plus Jakarta/Geist Mono pairing as the rest of the app — it's the first impression.
- **Effort:** S (≤1 day — all five files are small, under 280 lines total).

---

### [P1] Tab persistence is inconsistent — several tabbed pages lose state on refresh

- **Evidence:** The `useTabHash` hook (`dashboard/src/hooks/useTabHash.ts`) was built specifically for this, and is correctly used by `Sources.tsx:41`, `Users.tsx:42`, `Integrations.tsx:23`, `Editors.tsx`, and Settings via its own `useTabHash` consumer. But it is **not** used in:
  - `dashboard/src/pages/AIQuality.tsx:750` — `const [activeTab, setActiveTab] = useState('live')` — refresh on the Benchmarks tab drops you back to Live Scores.
  - `dashboard/src/pages/Tasks.tsx:693-697` — `TaskDetailSheet` uses `useState` for its nested Output/Findings/Reviews/Artifacts tabs. Refresh with a sheet open loses the detail-level tab.
  - `dashboard/src/pages/Tasks.tsx:1204-1208` — `statusFilter`, `sourceFilter`, `search`, `podFilter` all in local `useState`. Filter state vanishes on refresh.
  - `dashboard/src/pages/Goals.tsx:929-932` — `statusFilter`, `pageView` ('goals' | 'suggested') in `useState`. The whole "suggested" vs "goals" toggle is refresh-ephemeral.
  - `dashboard/src/pages/AIQuality.tsx:291-292` — `expandedRunId`, `selectedMemRun` in `useState` (less critical, but still a UX paper-cut during investigations).
- **Impact:** Previously flagged by the user ("tab state must survive refresh"). Daily-driver impact is high for Tasks (where refresh is used to see new state) and Goals (where the suggested/goals split is the page's primary navigation). Users repeatedly land on the wrong tab after refresh and have to reorient.
- **Recommendation:** Convert tabbed selectors to `useTabHash` with a bounded literal union; convert filter selectors to URL search params via `useSearchParams` (React Router already imported). Pattern to standardize: hash for tabs (`#tab=x`), query string for filters (`?status=running&source=mine`). This is a mechanical change but needs to touch every tabbed page.
- **Effort:** S per page, M cumulative across the 5+ pages.

---

### [P1] Chat-only mobile PWA: partially shipped, core gating is in place but several spec items are not implemented

- **Evidence:** Comparing `2026-04-02-chat-only-pwa-design.md` to code:
  - ✓ `MobileGuard` exists and redirects non-chat routes on mobile (`dashboard/src/App.tsx:136-140, 208-223`).
  - ✓ `useIsMobile` matches spec (`dashboard/src/hooks/useIsMobile.ts:1-22`).
  - ✓ `AppLayout` conditionally omits `MobileNav` on mobile (`dashboard/src/components/layout/AppLayout.tsx:51`).
  - ✓ `MorphButton` exists (`dashboard/src/components/ui/MorphButton.tsx`, imported in ChatInput).
  - ✗ Mobile model chip: spec calls for a left-aligned chip "rendered above the textarea on mobile only." Actual implementation (`dashboard/src/pages/chat/ChatInput.tsx:332-338`) shows the `ModelPicker` on the right side of the controls row on all viewports. No dedicated mobile model chip component exists; `components/ui/MobileModelChip.tsx` from the spec's file-list is absent.
  - ✗ Chat bottom-pad spec: spec says change `pb-16 md:pb-4` to `pb-4`. Actual (`dashboard/src/pages/chat/ChatPage.tsx:508, 559`) is `pb-[env(safe-area-inset-bottom)] md:pb-4` — this is fine, but there's also no `safe-area-pb` usage on the ChatInput card itself despite the class existing in `index.css:205-207`.
  - ✓ Voice transcript fills textarea rather than auto-submits (`ChatPage.tsx:94-100`).
  - ✗ First-time conversation-mode long-press tooltip (spec: "Hold for conversation mode"). Not found in code — grep for "Hold for conversation" returns nothing.
  - ✗ MessageBubble mobile branch (`MessageBubble.tsx:67-73`) uses `bg-stone-800` for user bubbles on mobile, which is a direct neutral rather than using `glass-card` / surface tokens. Fine functionally, drift from DESIGN.md.
- **Impact:** On phone viewports, Chat is usable but not the polished experience the spec promised. Mobile model switching requires tapping a compressed desktop ModelPicker. No discoverability affordance for long-press conversation mode. The iOS input-zoom prevention (`index.css:192-202`) is in place, good.
- **Recommendation:** Complete the spec: build `MobileModelChip.tsx`, add the one-time conversation-mode tooltip (store dismissal in localStorage), and adopt `glass-card` on the mobile user bubble for DESIGN.md conformance. Consider adding `apple-mobile-web-app-capable` meta tag (see below finding).
- **Effort:** S.

---

### [P2] PWA manifest and HTML missing mobile-web-app meta tags and splash config

- **Evidence:**
  - `dashboard/public/manifest.json:1-13` — has `display: standalone`, `theme_color: #0d9488`, icons at 192 and 512, but no `maskable` icon purpose, no `scope`, no `orientation`, no `categories`, no screenshots. `start_url: /` while `/` redirects to `/chat` via `HomeRoute` (`App.tsx:131-133`).
  - `dashboard/index.html:1-19` — no `apple-mobile-web-app-capable`, no `apple-mobile-web-app-status-bar-style`, no `apple-mobile-web-app-title`. `viewport` is correct (`viewport-fit=cover`, `maximum-scale=1.0`, `user-scalable=no`).
  - `dashboard/public/sw.js` — service worker is simple and correct (network-first for API, cache-first for assets, stale-while-revalidate for shell). No background sync, no push handling.
  - `#0d9488` in manifest is **stock Tailwind teal-600**, not the custom Nova teal-500 (`#19A89E`) defined in DESIGN.md. Same drift appears in `index.html:12` (`theme-color`). DESIGN.md:193 calls this out explicitly as a thing not to do.
- **Impact:** On iOS, installing Nova to Home Screen uses the default black status bar and shows "Nova" in Safari chrome rather than pure standalone mode. Chrome Lighthouse PWA audit would flag missing `maskable` icon. Splash screens on iOS won't match the app.
- **Recommendation:** Update `manifest.json` to include a maskable icon variant, set `scope: "/"`, set `start_url: "/chat"` (matching where the user actually lands), bring `theme_color` to Nova's `#19A89E`, add screenshots for install sheets. In `index.html` add `apple-mobile-web-app-capable`, status-bar-style `black-translucent`, and a correct `theme-color`.
- **Effort:** S.

---

### [P2] Loading, empty, and error states are inconsistent across pages

- **Evidence:** The design system ships `Skeleton`, `EmptyState`, and conventions for error cards, but usage is uneven:
  - **Good:** `Skills.tsx:389-421` and `Rules.tsx:410-438` use `Skeleton` + `EmptyState` + an isError card. `Goals.tsx:102-112` uses `Skeleton` in a grid. `Pods.tsx:995-1029` covers all three.
  - **Loading strings instead of Skeleton:**
    - `Keys.tsx:132-134` — `<p className="text-compact text-content-tertiary text-center">Loading...</p>` wrapped in a Card.
    - `Usage.tsx:242, 348` — both use `<p>Loading...</p>`.
    - `Recovery.tsx:94` — `<p>Checking services...</p>`.
    - `StartupScreen.tsx:96-101` — "Waiting for recovery service..." (hand-rolled spinner+text).
  - **No error branch rendered at all:**
    - `Tasks.tsx` — TanStack Query errors on `getPipelineTasks` / `getQueueStats` / etc. are invisible; only `isLoading` branches exist.
    - `Brain.tsx:161-174` — graph query with `retry: 1` but no fallback UI when it fails; Brain just renders nothing.
    - `AIQuality.tsx` — only the `runBenchmark` mutation error is surfaced (`:375`), not page-level query errors.
  - **No empty-state component in pages that need one:**
    - `Tasks.tsx` — when there are no tasks, shows an empty table. Spec (`2026-03-16-dashboard-redesign.md §4.2`) calls for filter pills + empty state with contextual messaging.
    - `Goals.tsx` recommendations tab — no explicit empty state when pending recs is 0 (visible by reading the JSX).
  - **Mixed error styling:** `Recovery.tsx:88-91` uses `border border-red-200 dark:border-red-800` — hardcoded red scale — while DESIGN.md prescribes `border-danger/30 bg-danger-dim` semantic tokens (used correctly in `ChatPage.tsx:542`, `Tasks.tsx`, `Usage.tsx:348`).
- **Impact:** Inconsistent polish. Users see "Loading..." text on some pages and a shimmer skeleton on others. When a backend query fails, several pages show a blank area and the user has no idea if the system is broken or just empty. This directly violates the design spec's Phase 6 goal: "Loading skeletons for every page / Empty states with contextual guidance for every list/table."
- **Recommendation:** Adopt a convention — every TanStack Query-backed page renders `<Skeleton>` on `isLoading`, `<Card>` with `text-danger` + retry button on `isError`, and `<EmptyState>` on `data.length === 0`. Replace hardcoded red-200/red-800 with `border-danger/30 bg-danger-dim`. Add a top-level error boundary fallback that distinguishes "query failed" from "component crashed" — currently `ErrorBoundary` only catches render-time exceptions.
- **Effort:** M (touches ~15 pages).

---

### [P2] Mobile/responsive behavior on non-chat pages is largely untested — wide pages use fixed max-widths with no mobile stacking

- **Evidence:**
  - `AppLayout.tsx:46` — uses `mx-auto max-w-[1200px] w-full px-6 py-8`. Padding `px-6` (24px) is aggressive for 375px viewports where the `MobileGuard` isn't in effect (e.g. resizing a desktop browser narrow).
  - Despite the `MobileGuard` intercepting mobile users from non-chat pages, the pages themselves have **minimal responsive adaptation**. Running `grep -c "sm:\|md:\|lg:"` per page:
    - `Pods.tsx`: 10 breakpoint uses across 1053 lines.
    - `Tasks.tsx`: 8 across 1506 lines.
    - `Goals.tsx`: 4 across 1173 lines.
    - `Sources.tsx`: 4 across 452 lines.
    - `Settings.tsx`: 3 across 821 lines.
    - `Brain.tsx`: 0 breakpoint classes.
  - `Goals.tsx:104-112` — stats grid `grid-cols-2 sm:grid-cols-4` is one of the few responsive grids.
  - `Settings.tsx` — the sub-nav sidebar pattern inside Settings is likely a two-column layout; no evidence it collapses to mobile.
  - **Practical implication:** At a tablet width (e.g. 800–1000px, which is still desktop per `useIsMobile`), pages like Pods, Tasks, Settings, Brain are designed for 1200px and do not adapt.
- **Impact:** The redesign spec (`2026-03-16-dashboard-redesign.md §3.4`) defines explicit breakpoint behavior (`< 768px: Bottom tab bar; 768-1024px: Collapsed (60px, icon-only); 1024-1280px: Expanded`). The `MobileGuard` handles the `< 768px` case by redirecting, but 768-1024px tablets see a full 1200px layout crammed into 900px with no grid collapse. Settings, with its dense sub-nav, will be particularly painful.
- **Recommendation:** Either (a) extend `MobileGuard` to also redirect the 768-1024px range — documenting that Nova is desktop-only except for chat — or (b) add a responsive pass to at least Tasks, Pods, Settings, Goals. Option (a) is faster and honest; option (b) is correct but L-effort. Given the chat-PWA spec already scoped away from multi-page mobile, (a) is the defensible Phase 1 move.
- **Effort:** S for option (a); L for option (b).

---

### [P2] Accessibility: low ARIA coverage, keyboard discoverability missing for chat features

- **Evidence:**
  - 46 total occurrences of `aria-label|role=|alt=` across 25 files (grep). Most are `alt=` on avatar `<img>` and a handful of `role="dialog"` / `role="switch"`. Coverage is thin compared to a dashboard of this size.
  - `Tabs.tsx:17-55` — the `Tabs` component does not emit `role="tablist" / tab / tabpanel` or `aria-selected` / `aria-controls`. Used on 8+ pages. Keyboard navigation (arrow keys) also absent.
  - `Modal.tsx:24-86` — no focus trap, no `role="dialog"`, no `aria-modal`. Closes on Escape (`:27`) but doesn't restore focus to the trigger on close. Backdrop click handler is doubly-bound (`:48` and `:53`).
  - `CommandPalette.tsx` — not shown here but the spec expected Cmd+K with keyboard nav. Need to verify `role="listbox"` / arrow-key handling.
  - `ChatInput.tsx:114-119` — Enter sends, Shift+Enter inserts newline. Correct. But IME composition (East-Asian input methods) is not guarded via `e.nativeEvent.isComposing` — pressing Enter to confirm kanji selection will submit the message.
  - `ChatInput.tsx:182-185` — the entire input card is a `<div>` rather than a `<form>`; the submit button is not `type="submit"`. Screen reader users don't get "Form, Message Nova" framing.
  - `Brain.tsx:198-?` — keyboard shortcuts exist per the comment on line 198, but are undiscoverable. There's no `?` help overlay visible in the grep.
  - Color contrast: `text-content-tertiary/60` (e.g. `MessageBubble.tsx:90, 146`) on timestamps sits on the `glass-card` (rgba(12,10,9,0.70)) background. `neutral-500 @ 60%` = `#71717a @ 60%` effective ≈ `#5a5a62` on near-black — this is likely below WCAG AA 4.5:1 for 10px text. Would fail a contrast check.
  - Icon-only buttons: `ChatInput.tsx:313-344` uses `Tooltip` for labels (good) but several icon-only buttons elsewhere (`Sidebar.tsx:199-216` collapse toggle) lack an `aria-label` on the button itself — screen readers announce nothing semantic.
- **Impact:** A keyboard-only or screen-reader user can sign in and send a chat message (Login uses semantic form, Input has `htmlFor`/`aria-describedby`), but cannot reliably navigate tabs, use the model picker, or dismiss modals predictably. Text contrast on timestamps and `/60` tokens likely fails WCAG AA.
- **Recommendation:** High-value a11y fixes: (1) Add `role="tablist"` + roving tabindex to `Tabs.tsx`. (2) Add focus trap + focus restore + `role="dialog"` / `aria-modal="true"` to `Modal.tsx`. (3) Guard Enter submit in ChatInput with `!e.nativeEvent.isComposing`. (4) Replace `text-content-tertiary/60` with `text-content-tertiary` on timestamps (or bump background opacity). (5) Audit icon-only buttons for `aria-label`. Full WCAG is out of scope per the task.
- **Effort:** M for the listed fixes; L for a full audit.

---

### [P2] Sidebar labels diverge from DESIGN spec + CLAUDE.md mapping, and route 404s exist

- **Evidence:**
  - `Sidebar.tsx:44-81` — visible sections are `[Core, Knowledge, Infrastructure, System]`. Spec (`2026-03-16 §3.2`) defined `[Core, Configure, Monitor, System]` with different grouping (e.g. "Pods / Models / Keys / Integrations" under Configure; "Usage" under Monitor). Current grouping puts Brain + Knowledge under "Knowledge" and pods/editor/IDE under "Infrastructure". Spec was authoritative per the nav-restructure follow-up.
  - `Sidebar.tsx:57` — Brain shown as `/brain` in `Knowledge` rather than the landing page per `2026-03-28-dashboard-nav-restructure-design.md §1` ("Brain becomes the landing page … renders at `/`"). `App.tsx:131-133` still routes `/` → `/chat` via `HomeRoute`. The nav-restructure spec has not shipped.
  - `Sidebar.tsx:67` — "Editor" nav item goes to `/editor`, which renders the embedded-editor page. But mobile tab `MobileNav.tsx:53` says `/editors` (plural). `App.tsx:217` then redirects `/editors` → `/ide-connections`. So the sidebar "Editor" and the mobile "Editors" lead to different pages.
  - `MobileNav.tsx:64` has "Recovery" but `Sidebar.tsx` does not (Recovery is accessed via Settings > System per `Settings.tsx:145` and the orphaned `/recovery` route at `App.tsx:220`). Inconsistent.
  - The sidebar's "Friction" debug-only item is only shown when `isDebug` is true (`:51`), good.
- **Impact:** Users comparing the desktop sidebar to the docs find a different nav structure than expected. The nav-restructure design spec exists but is not the shipped nav. This is also a sign of design/code drift — the design spec process isn't being enforced.
- **Recommendation:** Pick one of (a) ship the nav-restructure spec (make `/` → Brain, remove Memory page etc.) or (b) formally update the spec log to reflect the current shipped nav. Reconcile `/editor` vs `/editors` — pick one URL and make both sidebar and mobile tab bar agree.
- **Effort:** S.

---

### [P2] Skills/Rules UI: shipped as standalone pages, then absorbed into Settings, but navigation is confusing

- **Evidence:**
  - `Skills.tsx` and `Rules.tsx` both define a `SkillsContent` / `RulesContent` export that is "shared between standalone page and Settings section" (comment at `Skills.tsx:339`).
  - `Settings.tsx:33-34` imports `SkillsSection` / `RulesSection` (from the settings subdirectory — separate components).
  - `App.tsx:230-231` — both `/skills` and `/rules` routes redirect to `/settings#behavior`.
  - So the Skills/Rules standalone pages are effectively dead code; they are only reachable by going to Settings > Behavior. The standalone `.tsx` files still compile into the bundle, importing full React Query + component library.
  - Quality of the settings-embedded versions: `Skills.tsx` content is generally good — `EmptyState`, `Skeleton`, `ConfirmDialog`, `Modal` all used. `Rules.tsx` has a ToolSelector with manual state + dropdown which is well-crafted but lacks keyboard navigation on the dropdown (`:87-98`).
  - **UX gap:** Skills and Rules have no affordance in top-level nav — users discover them only by clicking Settings → Behavior. The Sidebar used to have them but now doesn't.
- **Impact:** Skills/Rules shipped functionally but is hard to find. A daily-driver user who wanted to edit a rule mid-session has to click through 2 levels (Settings, then Behavior section). Dead standalone pages bloat the bundle (~900 lines of TSX).
- **Recommendation:** Either (a) delete the standalone pages entirely and the redirect (keep only the SettingsSection wrappers), or (b) promote Skills/Rules to top-level sidebar items (design-consultation call — the spec-restructure seemed to deliberately hide them, so confirm with user first). Regardless, add keyboard navigation to the tool dropdown in `Rules.tsx:87-98`.
- **Effort:** S.

---

### [P2] Error recovery UX: non-trivial service failures result in silent blank areas

- **Evidence:**
  - `App.tsx:56-63` — `checkBackendReady` pings `/api/v1/pipeline/stats` at startup; on failure shows `StartupScreen`. Good.
  - But during a running session, if a service goes down, per-page behavior varies:
    - `Chat.tsx` (`ChatPage.tsx:394-405`) — stream errors surface as a red error div with the message text. Good.
    - `Brain.tsx` — graph fetch failure (retry=1) results in a blank black viewport with no message.
    - `Tasks.tsx` — pipeline-task fetch failure results in an infinite skeleton. Query errors are not rendered.
    - `Settings.tsx` — a failed platform-config fetch leaves fields empty with no error state.
  - `ErrorBoundary.tsx` — catches render exceptions but not network/query errors. When it does fire (rare), the fallback card is correct but generic (`ErrorBoundary.tsx:36-56`).
  - `Recovery.tsx:88-91` uses a local `restartError` banner (`border-red-200 dark:border-red-800` — hardcoded red). Good surfaces the action's result but styling drifts from tokens.
- **Impact:** When the orchestrator hiccups, the user sees skeletons forever or empty panels with no guidance. The startup screen covers the boot case well; the mid-session case does not.
- **Recommendation:** Add a global "query failed" banner component (or use `ToastProvider` to surface an error toast when any long-running query errors twice). Every page should have a visible error-state component on `query.isError`. Consider extending `App.tsx`'s health check to run periodically in-session — if the orchestrator goes down, show a non-modal top banner "Connection to Nova lost. Retrying…".
- **Effort:** M.

---

### [P3] Text-size system (compact/medium/large) is set via localStorage and not exposed in Appearance settings UI

- **Evidence:** `ChatInput.tsx:66-76` defines a three-state text-size cycle stored in `localStorage['nova_text_size']`, surfaced via an `<A>` icon button in the input row. `MessageBubble.tsx:15-19` consumes it. The button uses `iconBtn` styling and a `<span>` showing `S|M|L`. No Settings UI entry.
- **Impact:** The feature exists but is discoverable only by hovering over the text-size button. Users expecting font scaling in Appearance (per DESIGN.md §Typography "All sizes scale via `--font-scale` CSS variable for accessibility") won't find it. DESIGN.md also says sizes *scale via a CSS variable* — the implementation uses hardcoded class maps in MessageBubble rather than `--font-scale`.
- **Recommendation:** Either wire `--font-scale` properly (set the CSS variable from the text-size selection, use `rem`-based sizes throughout MessageBubble) or move the text-size switch into Appearance settings. The current impl is a useful but orphan feature.
- **Effort:** S.

---

### [P3] Onboarding wizard is the pre-redesign 6-step flow — doesn't match the spec's 7-step identity-aware flow

- **Evidence:** `OnboardingWizard.tsx:13-15` defines steps `['welcome', 'hardware', 'engine', 'model', 'downloading', 'ready']`. Spec (`2026-03-16 §4.13`) calls for `[Welcome, Hardware Detection, Deployment Profile, Provider Setup, Model Selection (merges PickModel+Downloading), Identity, Ready]` — a new Identity step and a merged model+download step. Provider-Setup step is absent; `handleEngineNext` branches on engine type (`:53-59`).
- **Impact:** First-run users don't get a guided provider setup or an Identity step. Not a blocker, but design spec explicitly flagged the old flow as incomplete. "Identity" was called out as valuable.
- **Recommendation:** Implement the spec's 7-step flow if Phase 1 priorities warrant. Otherwise mark the design spec as "deferred" so future audits don't re-flag.
- **Effort:** M.

---

### [P3] Dead / duplicate code paths: multiple pages have orphaned or redirected routes

- **Evidence:**
  - `App.tsx:225-233` has 7 redirect routes for old paths (`/intelligence`, `/mcp`, `/agents`, `/keys`, `/skills`, `/editors`, `/rules`, `/benchmarks`). Long redirect tails are a code smell; some of these are over a month old.
  - `MCP.tsx` still exists at 703 lines, not imported anywhere (I see no `from './pages/MCP'` grep hit in `App.tsx`). Dead file.
  - `Pods.tsx`, `Keys.tsx`, `MCP.tsx`, `Integrations.tsx` all define both a page component and content components used elsewhere (e.g. `KeysContent`, `SkillsContent`, `RulesContent`). The dual-mount pattern causes confusion about where to make edits.
- **Impact:** Bundle bloat + developer confusion. Not user-facing.
- **Recommendation:** Delete `MCP.tsx` (confirm not imported). Roll up the 7 redirects into 3–4 once the nav-restructure settles. Decide for each of Skills/Rules/Keys whether the standalone page is wanted; delete otherwise.
- **Effort:** S.

---

### [P3] Inconsistent use of neutral-* Tailwind classes vs semantic content-* tokens

- **Evidence:** 165 occurrences of `neutral-*` across 30 files. Most are legitimate (theme CSS, Avatar color buckets, Tooltip). But `Invite.tsx` uses 31 `neutral-*` / 20 `text-sm` / 4 `text-xl` — none of the Nova tokens (`text-h1`, `text-content-*`). `Expired.tsx` has 4 `neutral-*` uses. `StartupScreen.tsx` has 12. These files predate the redesign spec and have not been migrated.
- **Impact:** Bulk visual drift on auth/boot flows (see P1 finding above for the impact framing). Secondary concern: theme palette changes (e.g. switching from stone to slate) won't propagate to these files because they bypass the token layer.
- **Recommendation:** Grep-based sweep. Replace `bg-neutral-*`/`text-neutral-*` with the semantic tokens. Tooling idea: add an ESLint rule disallowing raw `neutral-*`, `teal-*`, `stone-*` classes outside the `ui/` component library and `index.css`.
- **Effort:** S for the migration; M for the lint rule + enforcement.

---

## Summary

- **Five first-impression pages (Expired, Invite, StartupScreen, AuthGate loading, Onboarding step-circles) bypass the design system**, using hardcoded `neutral-*`/`teal-600` classes and raw `<button>`s instead of `Card`/`Button`/tokens. These are the highest-stakes surfaces a user sees; rebuilding them on `components/ui` is ≤1 day of work. [P1]
- **Tab persistence is half-shipped** — `useTabHash` exists and is used in 5 places but not in AIQuality, Tasks (detail tabs + filters), or Goals. Users lose state on refresh on daily-driver pages. [P1]
- **The chat-only mobile PWA is gated correctly** (MobileGuard, useIsMobile, MorphButton shipped) **but missing the mobile model chip, the first-time long-press tooltip, and PWA manifest polish** (maskable icon, Apple meta tags, wrong theme_color). Completing the spec is S-effort. [P1–P2]
- **Loading/empty/error states are inconsistent** — Skeleton is used on ~half the pages, "Loading..." strings on the rest; several pages have no error UI at all. Fixing this is M-effort across ~15 pages but directly maps to design-spec Phase 6 commitments. [P2]
- **Skills/Rules UI shipped** but is only reachable via Settings → Behavior; the standalone `/skills` and `/rules` routes are redirects and the standalone page files are effectively dead code. [P2]
- **Accessibility is thin** — Tabs lacks ARIA roles, Modal lacks focus trap, ChatInput doesn't guard IME Enter, contrast on `/60` timestamps likely fails WCAG AA. [P2]
- **Nav-restructure design spec (Brain = landing page) hasn't shipped** and `/editor` vs `/editors` lead to different surfaces via inconsistent redirects. Reconcile the nav or update the spec. [P2]
