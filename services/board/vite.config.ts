import { defineConfig } from "vite"
import react from "@vitejs/plugin-react"

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/activity":      "http://localhost:8000",
      "/approvals":     "http://localhost:8000",
      "/board":         "http://localhost:8000",
      "/conversations": "http://localhost:8000",
      "/entities":      "http://localhost:8000",
      "/events":        "http://localhost:8000",
      "/health":        "http://localhost:8000",
      "/llm":           "http://localhost:8000",
      "/runs":          "http://localhost:8000",
      "/system":        "http://localhost:8000",
      "/tasks":         "http://localhost:8000",
      "/tools":         "http://localhost:8000",
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
  },
})
