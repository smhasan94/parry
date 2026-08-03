import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import path from "path";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test-setup.ts"],
    coverage: {
      provider: "v8",
      include: ["src/hooks/**", "src/lib/**", "src/components/**"],
      exclude: [
        "src/components/charts/**",
        "src/components/ui/**",
        "src/**/*.d.ts",
      ],
      reporter: ["text", "lcov"],
      // Ratchets, not targets: they exist to catch backsliding, so they
      // sit below current coverage rather than at it. Branches was 78
      // against an actual 79.26 — 1.3 points of slack meant an unrelated
      // PR adding a couple of untested conditionals would fail the build
      // for reasons that had nothing to do with it. Raise these
      // deliberately as coverage improves.
      thresholds: {
        statements: 25,
        branches: 70,
        functions: 35,
        lines: 25,
      },
    },
  },
});
