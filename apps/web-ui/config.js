export const API_URL = "http://127.0.0.1:8000";
export const DEV_MODE = true;
export const DEV_API_MOCKS = false;

export const APP_NAME = "SIJO Assistant";

export const API_ENDPOINTS = {
  health: "/api/health",
  chat: "/api/chat",
  chat_session_reset: "/api/chat/session/reset",
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

