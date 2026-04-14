import "@testing-library/jest-dom"
import { notifyManager } from "@tanstack/react-query"

// TanStack Query v5 uses notifyManager.batch() with setTimeout(fn, 0) to schedule state
// notifications. In jsdom tests this causes notifications to fire asynchronously between
// tests, which makes vitest's unhandledRejection handler misattribute mutation errors from
// one test to the next. Setting a synchronous scheduler collapses all notifications into
// the same microtask queue as the mutation, eliminating cross-test bleed.
notifyManager.setScheduler(cb => cb())
