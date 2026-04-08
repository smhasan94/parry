import { defineConfig } from "astro/config";
import tailwind from "@astrojs/tailwind";

// Static-only marketing site. No SSR, no API routes — the dashboard
// app handles every authenticated surface, this exists purely to
// convert visitors into signups.
export default defineConfig({
  integrations: [tailwind()],
  site: "https://parry.dev",
});
