import { describe, it, expect, vi, beforeEach } from "vitest"
import { apiFetch } from "../client"

describe("apiFetch", () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it("calls fetch with the correct URL", async () => {
    const spy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ ok: true }), { status: 200 })
    )
    await apiFetch("/board")
    expect(spy).toHaveBeenCalledWith("/board", undefined)
  })

  it("prepends VITE_API_URL when set", async () => {
    vi.stubEnv("VITE_API_URL", "http://localhost:8000")
    const spy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({}), { status: 200 })
    )
    await apiFetch("/tasks")
    expect(spy).toHaveBeenCalledWith("http://localhost:8000/tasks", undefined)
    vi.unstubAllEnvs()
  })

  it("throws on non-2xx response", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response("Not Found", { status: 404 })
    )
    await expect(apiFetch("/missing")).rejects.toThrow("404")
  })
})
