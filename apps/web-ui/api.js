import {
  API_ENDPOINTS,
  API_URL,
  CHAT_TIMEOUT_MS,
  DEV_API_MOCKS,
  DEV_MODE,
} from "./config.js";
import { getAccessToken } from "./auth.js";
import { getLanguage, t } from "./i18n.js";

const SUPPORTED_UI_TYPES = new Set([
  "text",
  "candidate_cards",
  "clarification",
  "candidate_detail",
  "technical_summary",
  "error",
  "loading",
]);

export class ApiError extends Error {
  constructor(message, type = "backend", status = null) {
    super(message);
    this.name = "ApiError";
    this.type = type;
    this.status = status;
  }
}

export function buildEndpoint(name, params = {}) {
  const template = API_ENDPOINTS[name];

  if (!template) {
    throw new ApiError(`Endpoint inconnu: ${name}`, "config");
  }

  return Object.entries(params).reduce((path, [key, value]) => {
    return path.replace(`:${key}`, encodeURIComponent(value));
  }, template);
}

async function authHeaders() {
  const token = await getAccessToken();

  if (!token) {
    throw new ApiError(t("errors.unauthenticated"), "auth");
  }

  return {
    Authorization: `Bearer ${token}`,
    "Content-Type": "application/json",
  };
}

async function request(path, options = {}) {
  if (DEV_MODE && DEV_API_MOCKS) {
    return devRequest(path, options);
  }

  const headers = {
    ...(DEV_MODE || options.auth === false
      ? { "Content-Type": "application/json" }
      : await authHeaders()),
    "Accept-Language": getLanguage(),
    ...(options.headers || {}),
  };

  const controller = options.timeoutMs ? new AbortController() : null;
  const timeoutId = controller
    ? window.setTimeout(() => controller.abort(), options.timeoutMs)
    : null;

  let response;
  try {
    response = await fetch(`${API_URL}${path}`, {
      ...options,
      headers,
      signal: controller?.signal,
    });
  } catch (error) {
    if (error.name === "AbortError") {
      throw new ApiError(t("errors.timeout"), "timeout");
    }

    throw new ApiError(t("errors.network"), "network");
  } finally {
    if (timeoutId) window.clearTimeout(timeoutId);
  }

  if (!response.ok) {
    throw new ApiError(t("errors.generic"), "backend", response.status);
  }

  if (response.status === 204) {
    return null;
  }

  try {
    return await response.json();
  } catch (error) {
    throw new ApiError(t("errors.malformed"), "malformed_response", response.status);
  }
}

async function devRequest(path, options = {}) {
  await getAccessToken();
  await delay(180);

  if (path === buildEndpoint("health")) {
    return { status: "ok", mode: "development" };
  }

  if (path === buildEndpoint("conversations") && options.method === "GET") {
    return [];
  }

  if (path === buildEndpoint("conversations") && options.method === "POST") {
    const body = parseBody(options.body);
    const now = new Date().toISOString();

    return {
      id: `dev_${Date.now()}`,
      title: body.title || t("conversations.default_title"),
      created_at: now,
      updated_at: now,
    };
  }

  if (matchesEndpoint(path, "conversation_detail") && options.method === "GET") {
    const id = decodeURIComponent(path.split("/").pop());

    return {
      id,
      title: "Conversation de développement",
      messages: [],
    };
  }

  if (matchesEndpoint(path, "conversation_detail") && options.method === "DELETE") {
    return null;
  }

  if (matchesEndpoint(path, "candidates_detail") && options.method === "GET") {
    const id = decodeURIComponent(path.split("/").pop());
    return getDevCandidates().find((candidate) => candidate.id === id) || null;
  }

  if (path === buildEndpoint("chat") && options.method === "POST") {
    const body = parseBody(options.body);
    const message = String(body.message || "");

    if (body.interaction?.type === "clarification") {
      return {
        conversation_id: body.conversation_id || `dev_${Date.now()}`,
        message: "Merci, je relance la recherche avec ces précisions.",
        ui: {
          type: "candidate_cards",
          title: "3 profils pertinents trouvés",
          subtitle: "2 profils disponibles rapidement",
          filters_summary: ["Java", "Senior", "Paris", "Finance"],
        },
        candidates: getDevCandidates(),
      };
    }

    if (/technique|technical|analyse/i.test(message)) {
      return {
        conversation_id: body.conversation_id || `dev_${Date.now()}`,
        message: "Voici l’analyse technique du profil.",
        ui: {
          type: "technical_summary",
          title: "Analyse technique — Sarah Martin",
          summary: "Profil très solide sur Java/Spring avec une expérience microservices.",
          strengths: ["Java avancé", "Architecture microservices", "Kafka"],
          weaknesses: ["Peu d’expérience frontend"],
          languages: ["Français courant", "Anglais professionnel"],
          tools: [
            { name: "Java", level: 5 },
            { name: "Spring Boot", level: 4 },
          ],
        },
      };
    }

    if (/d[eé]tail|profil/i.test(message)) {
      return {
        conversation_id: body.conversation_id || `dev_${Date.now()}`,
        message: "Voici le détail du candidat.",
        ui: {
          type: "candidate_detail",
          candidate: {
            ...getDevCandidates()[1],
            contract_preferences: ["CDI", "Freelance"],
            salary_expectation: "55k€",
            tjm: "600€",
          },
        },
      };
    }

    return {
      conversation_id: body.conversation_id || `dev_${Date.now()}`,
      message: "J’ai trouvé 3 candidats correspondant à votre recherche.",
      ui: {
        type: "candidate_cards",
        title: "3 profils pertinents trouvés",
        subtitle: "2 profils disponibles rapidement",
        filters_summary: ["Java", "Senior", "Paris", "Finance"],
        candidates: getDevCandidates(),
      },
      debug: {
        intent: "candidate_search",
        filters: { skills: ["Java"] },
        response_time_ms: 180,
      },
    };
  }

  throw new ApiError(t("errors.generic"), "backend");
}

async function devStreamSearch(query, onEvent, { signal } = {}) {
  await getAccessToken();

  const conversationId = `dev_${Date.now()}`;
  const candidates = getDevCandidates();
  const frames = [
    { type: "search_started", data: { conversation_id: conversationId, query, planner_mode: "dev" } },
    { type: "plan_created", data: { plan: [] } },
    { type: "tool_call_started", data: { tool: "searchCandidates", inputs: {} } },
    { type: "results_normalized", data: { candidate_count: candidates.length } },
    {
      type: "final_response",
      data: {
        conversation_id: conversationId,
        message: candidates.length
          ? `J’ai trouvé ${candidates.length} candidat(s) (mode mock).`
          : "Aucun candidat trouvé (mode mock).",
        ui: { type: "candidate_cards", candidates },
      },
    },
  ];

  for (const frame of frames) {
    if (signal?.aborted) {
      throw new ApiError(t("errors.aborted"), "abort");
    }
    await delay(200);
    onEvent(frame);
  }
}

function matchesEndpoint(path, name) {
  const template = API_ENDPOINTS[name];
  if (!template) return false;

  const pattern = new RegExp(`^${template.replace(/:[^/]+/g, "[^/]+")}$`);
  return pattern.test(path);
}

function getDevCandidates() {
  return [];

  return [
    {
      id: "dev_candidate_1",
      full_name: "Jean Dupont",
      title: "Développeur Java Fullstack",
      experience_years: 5,
      location: "Paris",
      availability: "Disponible sous 1 mois",
      skills: ["Java", "Spring Boot", "Angular", "PostgreSQL", "Docker", "Finance"],
      match_score: 0.92,
      summary: "Profil fullstack Java/Spring avec une expérience significative dans le secteur bancaire.",
      contract_preferences: ["CDI", "Freelance"],
      salary_expectation: "58k€",
      tjm: "620€",
      mobility: "Paris et hybride",
      highlights: ["Java", "Spring Boot", "Finance"],
      ai_evaluation: {
        label: "Évaluation IA",
        score_label: "Match idéal - 92%",
        reasons: [
          "Expérience Java/Spring cohérente avec le besoin",
          "Expérience récente dans le secteur bancaire",
          "Disponible rapidement",
        ],
      },
      experiences: [
        { title: "Développeur Java Fullstack", company: "Banque Populaire", period: "janv. 2022 - présent" },
        { title: "Ingénieur logiciel Java", company: "Société Générale", period: "mars 2020 - déc. 2021" },
        { title: "Développeur Angular / Spring", company: "Crédit Agricole", period: "sept. 2018 - févr. 2020" },
      ],
      strengths: ["Très bon alignement Java/Spring", "Expérience finance", "Autonomie sur applications internes"],
      watch_points: ["Disponibilité sous un mois à confirmer"],
      technical_summary: "Solide socle Java/Spring Boot avec pratique Angular et bases PostgreSQL.",
      boond_url: "https://ui.boondmanager.com/",
    },
    {
      id: "dev_candidate_2",
      full_name: "Sarah Martin",
      title: "Ingénieure Backend Java",
      experience_years: 7,
      location: "Île-de-France",
      availability: "Disponible immédiatement",
      skills: ["Java", "Spring", "Microservices", "Kafka", "Cloud", "SQL"],
      match_score: 0.88,
      summary: "Profil backend confirmé, orienté architecture microservices et environnements exigeants.",
      contract_preferences: ["CDI"],
      salary_expectation: "62k€",
      tjm: "650€",
      mobility: "Île-de-France",
      highlights: ["Java", "Kafka", "Microservices"],
      ai_evaluation: {
        label: "Évaluation IA",
        score_label: "Très bon match - 88%",
        reasons: [
          "Expérience backend confirmée",
          "Forte exposition microservices et Kafka",
          "Disponible immédiatement",
        ],
      },
      experiences: [
        { title: "Ingénieure Backend Java", company: "Euronext", period: "mai 2023 - présent" },
        { title: "Tech Lead Java", company: "AXA", period: "janv. 2021 - avr. 2023" },
        { title: "Développeuse Java", company: "Orange Business", period: "sept. 2018 - déc. 2020" },
      ],
      strengths: ["Microservices", "Kafka", "Disponibilité immédiate"],
      watch_points: ["Peu d'expérience frontend indiquée"],
      technical_summary: "Profil backend senior avec bonne profondeur sur Java, Spring et architectures distribuées.",
      boond_url: "https://ui.boondmanager.com/",
    },
    {
      id: "dev_candidate_3",
      full_name: "Karim Benali",
      title: "Développeur Fullstack",
      experience_years: 4,
      location: "Lyon / Remote",
      availability: "Préavis 2 mois",
      skills: ["Java", "React", "Node.js", "Docker", "CI/CD"],
      match_score: 0.72,
      summary: "Profil polyvalent fullstack avec bonne autonomie et expérience sur applications web internes.",
      contract_preferences: ["Freelance"],
      salary_expectation: null,
      tjm: "520€",
      mobility: "Remote majoritaire",
      highlights: ["Java", "React", "Docker"],
      ai_evaluation: {
        label: "Évaluation IA",
        score_label: "Match intéressant - 72%",
        reasons: [
          "Profil fullstack polyvalent",
          "Compétences Java et React utiles",
          "Disponibilité moins immédiate",
        ],
      },
      experiences: [
        { title: "Développeur Fullstack", company: "Cegid", period: "févr. 2022 - présent" },
        { title: "Développeur Java / React", company: "Sopra Steria", period: "sept. 2020 - janv. 2022" },
      ],
      strengths: ["Polyvalence fullstack", "Bonne autonomie", "Expérience Docker"],
      watch_points: ["Préavis de deux mois", "Moins spécialisé finance"],
      technical_summary: "Profil équilibré Java/React avec culture produit interne et pratiques DevOps de base.",
      boond_url: "https://ui.boondmanager.com/",
    },
  ];
}

function parseBody(body) {
  if (!body) return {};

  try {
    return JSON.parse(body);
  } catch (error) {
    return {};
  }
}

function delay(ms) {
  return new Promise((resolve) => {
    window.setTimeout(resolve, ms);
  });
}

function normalizeChatResponse(response) {
  if (!response || typeof response !== "object" || Array.isArray(response)) {
    throw new ApiError(t("errors.malformed"), "malformed_response");
  }

  const message = typeof response.message === "string"
    ? response.message
    : typeof response.answer === "string"
      ? response.answer
      : "";

  const fallbackCandidates = Array.isArray(response.candidates) ? response.candidates : [];
  const ui = normalizeUi(response.ui, fallbackCandidates);
  const candidates = normalizeCandidates(response, ui);
  const candidate = normalizeCandidate(ui);

  if (ui.type === "clarification" && !Array.isArray(ui.questions)) {
    throw new ApiError(t("errors.malformed"), "malformed_response");
  }

  if (!message && candidates.length === 0 && !candidate && ui.type !== "technical_summary" && ui.type !== "loading") {
    throw new ApiError(t("errors.malformed"), "malformed_response");
  }

  const normalized = {
    ...response,
    answer: message,
    message,
    candidates,
    candidate,
    ui,
  };

  logDevChatDebug(normalized);
  return normalized;
}

function normalizeUi(ui, fallbackCandidates = []) {
  if (ui === undefined || ui === null) {
    return { type: fallbackCandidates.length > 0 ? "candidate_cards" : "text" };
  }

  if (!ui || typeof ui !== "object" || Array.isArray(ui)) {
    throw new ApiError(t("errors.malformed"), "malformed_response");
  }

  if (!SUPPORTED_UI_TYPES.has(ui.type)) {
    throw new ApiError(t("errors.malformed"), "malformed_response");
  }

  return ui;
}

function normalizeCandidates(response, ui) {
  if (response.candidates !== undefined && !Array.isArray(response.candidates)) {
    throw new ApiError(t("errors.malformed"), "malformed_response");
  }

  if (ui.candidates !== undefined && !Array.isArray(ui.candidates)) {
    throw new ApiError(t("errors.malformed"), "malformed_response");
  }

  return Array.isArray(ui.candidates)
    ? ui.candidates
    : Array.isArray(response.candidates)
      ? response.candidates
      : [];
}

function normalizeCandidate(ui) {
  if (ui.candidate === undefined) return null;

  if (!ui.candidate || typeof ui.candidate !== "object" || Array.isArray(ui.candidate)) {
    throw new ApiError(t("errors.malformed"), "malformed_response");
  }

  return ui.candidate;
}

function logDevChatDebug(response) {
  if (!DEV_MODE) return;

  console.log("[DEV] Réponse normalisée", response);

  if (response.debug) {
    console.log("[DEV] debug.intent", response.debug.intent);
    console.log("[DEV] debug.filters", response.debug.filters);
    console.log("[DEV] debug.response_time_ms", response.debug.response_time_ms);
  }
}

export async function healthCheck() {
  return request(buildEndpoint("health"), {
    method: "GET",
  });
}

export async function sendMessage(message, conversationId = null) {
  const response = await request(buildEndpoint("chat"), {
    method: "POST",
    timeoutMs: CHAT_TIMEOUT_MS,
    body: JSON.stringify({
      message,
      conversation_id: conversationId,
      sessionId: conversationId,
    }),
  });

  return normalizeChatResponse(response);
}

function createSseParser() {
  let buffer = "";
  const frameSeparator = /\r?\n\r?\n/;

  function parseFrame(frame) {
    let eventType = "message";
    const dataLines = [];

    for (const rawLine of frame.split("\n")) {
      const line = rawLine.replace(/\r$/, "");
      if (line === "" || line.startsWith(":")) continue;

      const idx = line.indexOf(":");
      const field = idx === -1 ? line : line.slice(0, idx);
      let value = idx === -1 ? "" : line.slice(idx + 1);
      if (value.startsWith(" ")) value = value.slice(1);

      if (field === "event") eventType = value;
      else if (field === "data") dataLines.push(value);
    }

    if (dataLines.length === 0) return null;

    try {
      return { event: eventType, data: JSON.parse(dataLines.join("\n")) };
    } catch (error) {
      return null;
    }
  }

  return {
    push(textChunk) {
      buffer += textChunk;
      const events = [];

      let match;
      while ((match = frameSeparator.exec(buffer)) !== null) {
        const frame = buffer.slice(0, match.index);
        buffer = buffer.slice(match.index + match[0].length);
        const parsed = parseFrame(frame);
        if (parsed) events.push(parsed);
      }

      return events;
    },
    flush() {
      const remaining = buffer.trim();
      buffer = "";
      if (!remaining) return [];
      const parsed = parseFrame(remaining);
      return parsed ? [parsed] : [];
    },
  };
}

function emitSseEvent(parsed, onEvent) {
  // The backend puts the event type on the SSE `event:` line and the payload
  // directly on the `data:` line (it is NOT wrapped as {type, data}).
  const type = parsed.event || parsed.data?.type;
  const data = parsed.data ?? {};
  onEvent({ type, data });
}

export async function streamSearch(query, onEvent, { signal, conversationId } = {}) {
  if (DEV_MODE && DEV_API_MOCKS) {
    return devStreamSearch(query, onEvent, { signal });
  }

  const headers = {
    ...(DEV_MODE ? { "Content-Type": "application/json" } : await authHeaders()),
    Accept: "text/event-stream",
    "Accept-Language": getLanguage(),
  };

  let response;
  try {
    response = await fetch(`${API_URL}${buildEndpoint("search_stream")}`, {
      method: "POST",
      headers,
      body: JSON.stringify({
        query,
        filters: {},
        ...(conversationId ? { conversation_id: conversationId, sessionId: conversationId } : {}),
      }),
      signal,
    });
  } catch (error) {
    if (error.name === "AbortError") {
      throw new ApiError(t("errors.aborted"), "abort");
    }
    throw new ApiError(t("errors.network"), "network");
  }

  if (!response.ok) {
    throw new ApiError(t("errors.generic"), "backend", response.status);
  }

  if (!response.body) {
    throw new ApiError(t("errors.network"), "network");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8");
  const parser = createSseParser();

  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      for (const evt of parser.push(decoder.decode(value, { stream: true }))) {
        emitSseEvent(evt, onEvent);
      }
    }

    const tail = decoder.decode();
    if (tail) {
      for (const evt of parser.push(tail)) emitSseEvent(evt, onEvent);
    }
    for (const evt of parser.flush()) emitSseEvent(evt, onEvent);
  } catch (error) {
    if (error.name === "AbortError") {
      throw new ApiError(t("errors.aborted"), "abort");
    }
    throw new ApiError(t("errors.network"), "network");
  } finally {
    try {
      reader.releaseLock();
    } catch (error) {
      /* noop */
    }
  }
}

export async function sendClarification(interaction, conversationId = null) {
  const response = await request(buildEndpoint("chat"), {
    method: "POST",
    timeoutMs: CHAT_TIMEOUT_MS,
    body: JSON.stringify({
      message: null,
      conversation_id: conversationId,
      interaction,
    }),
  });

  return normalizeChatResponse(response);
}

export async function getConversations() {
  return request(buildEndpoint("conversations"), {
    method: "GET",
  });
}

export async function getConversation(conversationId) {
  return request(buildEndpoint("conversation_detail", { id: conversationId }), {
    method: "GET",
  });
}

export async function createConversation(title = t("conversations.default_title")) {
  return request(buildEndpoint("conversations"), {
    method: "POST",
    body: JSON.stringify({ title }),
  });
}

export async function deleteConversation(conversationId) {
  return request(buildEndpoint("conversation_detail", { id: conversationId }), {
    method: "DELETE",
  });
}

export async function deleteAllConversations() {
  return request(buildEndpoint("conversations"), {
    method: "DELETE",
  });
}

export async function renameConversation(conversationId, title) {
  return request(buildEndpoint("conversation_detail", { id: conversationId }), {
    method: "PATCH",
    body: JSON.stringify({ title }),
  });
}

export async function resetChatSession(sessionId) {
  if (!sessionId) return null;
  return request(buildEndpoint("chat_session_reset"), {
    method: "POST",
    body: JSON.stringify({ sessionId }),
  });
}

export async function getCandidate(candidateId) {
  return request(buildEndpoint("candidates_detail", { id: candidateId }), {
    method: "GET",
  });
}


