import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// Pure-logic tests only for now: no DOM, no network. UI behaviour is covered by
// the Playwright scripts, so keep this fast enough to run on every save.
export default defineConfig({
  plugins: [react()],
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"],
  },
});
