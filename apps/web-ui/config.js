// Build-time overrides (VITE_API_URL, VITE_DEV_MODE) let deployed builds
// point at another API origin (empty string = same origin behind a proxy)
// without touching this file. Local dev keeps the defaults below.
const ENV = import.meta.env ?? {};
export const API_URL = ENV.VITE_API_URL ?? "http://127.0.0.1:8000";
export const DEV_MODE = ENV.VITE_DEV_MODE ? ENV.VITE_DEV_MODE !== "false" : true;
export const DEV_API_MOCKS = false;

export const APP_NAME = "SIJO Assistant";

export const API_ENDPOINTS = {
  health: "/api/health",
  chat: "/api/chat",
  search_stream: "/api/search/stream",
  conversations: "/api/conversations",
  conversation_detail: "/api/conversations/:id",
  candidates_detail: "/api/candidates/:id",
};

export const CHAT_TIMEOUT_MS = null;

export const FEATURES = {
  auth: true,
  conversation_history: true,
  candidate_cards: true,
  candidate_drawer: true,
  boond_redirect: true,
};

// User-facing strings live in the locale dictionaries (locales/fr.js,
// locales/en.js) and are accessed via i18n.js `t()`. This file holds only
// structural / non-text configuration.
export const CANDIDATE_CONFIG = {
  max_visible_skills: 5,
  score_display: "percentage",
  open_boond_in_new_tab: true,
  show_candidate_drawer: true,
};
