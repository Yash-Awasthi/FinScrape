/// <reference types="vite/client" />

interface ImportMetaEnv {
  // Base URL of the FinScrape API. Empty = same-origin (dev proxy / nginx).
  // Set at build time for split hosting (e.g. Cloudflare Pages → Render API).
  readonly VITE_API_BASE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}

// Module-level caches shared across panels (populated by main.ts loadAll).
interface Window {
  __wfSuggestions?: import("./api").Suggestion[];
  __wfStorylines?: import("./api").Storyline[];
  __wfEvents?: import("./api").EventOut[];
}
