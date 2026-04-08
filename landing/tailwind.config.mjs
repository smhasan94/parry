/** @type {import('tailwindcss').Config} */
export default {
  content: ["./src/**/*.{astro,html,js,jsx,md,mdx,ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Match the dashboard's dark palette so the visual handoff
        // from marketing → app feels continuous, not jarring.
        ink: {
          50: "#f8fafc",
          200: "#cbd5e1",
          400: "#64748b",
          600: "#334155",
          800: "#0f172a",
          900: "#0b1220",
          950: "#070b15",
        },
        accent: {
          DEFAULT: "#6366f1",
          hover: "#818cf8",
        },
      },
      fontFamily: {
        sans: [
          "ui-sans-serif",
          "system-ui",
          "-apple-system",
          "Segoe UI",
          "Inter",
          "sans-serif",
        ],
      },
    },
  },
  plugins: [],
};
