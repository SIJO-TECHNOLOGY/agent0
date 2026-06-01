export const API_URL = "http://127.0.0.1:8001";
export const DEV_MODE = true;
export const DEV_API_MOCKS = false;

export const APP_NAME = "SIJO Assistant";

export const API_ENDPOINTS = {
  health: "/api/health",
  chat: "/api/chat",
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

export const UI_CONFIG = {
  default_conversation_title: "Nouvelle conversation",
  login_label: "Connexion",
  assistant_label: "SIJO",
  user_label: "Vous",
  loading_message: "SIJO réfléchit...",
  auth_loading_message: "Connexion en cours...",
  backend_offline_message: "Backend indisponible.",
  generic_error_message: "Une erreur est survenue.",
  network_error_message: "Impossible de contacter le serveur.",
  timeout_error_message: "Désolé, la demande prend trop de temps. Veuillez réessayer.",
  malformed_response_message: "Désolé, la réponse reçue n’est pas exploitable. Veuillez réessayer.",
};

export const CANDIDATE_CONFIG = {
  max_visible_skills: 5,
  score_display: "percentage",
  open_boond_in_new_tab: true,
  show_candidate_drawer: true,
  fallback_title: "Profil candidat",
  fallback_location: "Localisation non renseignée",
  fallback_availability: "Disponibilité non renseignée",
};
