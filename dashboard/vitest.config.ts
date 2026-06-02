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
      thresholds: {
        statements: 25,
        branches: 78,
        functions: 35,
        lines: 25,
      },
    },
  },
});
