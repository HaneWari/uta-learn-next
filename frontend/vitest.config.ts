import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// Pure-logic tests only for now: no DOM, no network. UI behaviour is covered by
// the Playwright scripts, so keep this fast enough to run on every save.
export default defineConfig({
  plugins: [react()],
  test: {
    // jsdom only for the shortcut/typing tests; the rest are pure functions and
    // still run instantly. `environmentMatchGlobs` kept the split without a
    // second config file.
    environment: "jsdom",
    include: ["src/**/*.test.ts"],
  },
});
