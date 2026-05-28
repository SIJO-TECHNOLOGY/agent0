import {
  ApiError,
  createConversation,
  deleteConversation,
  getConversation,
  getConversations,
  sendClarification,
  sendMessage,
} from "./api.js";
import {
  getCurrentUser,
  handleRedirect,
  isAuthenticated,
  login,
  logout,
} from "./auth.js";
import { CANDIDATE_CONFIG, DEV_MODE, FEATURES, UI_CONFIG } from "./config.js";

window.addEventListener("error", console.error);
window.addEventListener("unhandledrejection", console.error);

const state = {
  conversations: [],
  currentConversationId: null,
  currentDrawerCandidate: null,
  isBootstrapped: false,
  isLoading: false,
  uiState: "empty",
};

const elements = {
  loginScreen: document.getElementById("loginScreen"),
  loadingScreen: document.getElementById("loadingScreen"),
  loadingText: document.getElementById("loadingText"),
  appShell: document.getElementById("appShell"),
  loginBtn: document.getElementById("loginBtn"),
  loginError: document.getElementById("loginError"),
  logoutBtn: document.getElementById("logoutBtn"),
  currentUser: document.getElementById("currentUser"),
  conversationTitle: document.getElementById("conversationTitle"),
  conversationList: document.getElementById("conversationList"),
  sidebarStatus: document.getElementById("sidebarStatus"),
  newChatBtn: document.getElementById("newChatBtn"),
  messagesArea: document.getElementById("messagesArea"),
  emptyState: document.getElementById("emptyState"),
  messages: document.getElementById("messages"),
  messageInput: document.getElementById("messageInput"),
  sendBtn: document.getElementById("sendBtn"),
  inputError: document.getElementById("inputError"),
  drawerOverlay: document.getElementById("drawerOverlay"),
  candidateDrawer: document.getElementById("candidateDrawer"),
  drawerCloseBtn: document.getElementById("drawerCloseBtn"),
  drawerName: document.getElementById("drawerName"),
  drawerTitle: document.getElementById("drawerTitle"),
  drawerSummary: document.getElementById("drawerSummary"),
  drawerSkills: document.getElementById("drawerSkills"),
  drawerExperience: document.getElementById("drawerExperience"),
  drawerLocation: document.getElementById("drawerLocation"),
  drawerAvailability: document.getElementById("drawerAvailability"),
  drawerMatch: document.getElementById("drawerMatch"),
  drawerBoondBtn: document.getElementById("drawerBoondBtn"),
};

document.addEventListener("DOMContentLoaded", init);

async function init() {
  console.log("[APP] Starting");
  bindEvents();
  applyFeatureVisibility();
  showLoading();

  try {
    await handleRedirect();
    console.log("[AUTH] OK");
  } catch (error) {
    console.error(error);
    showLogin("Impossible de finaliser la connexion Microsoft.");
    return;
  }

  if (!isAuthenticated()) {
    showLogin();
    return;
  }

  showChat();
  await loadConversationsSafely();
}

function bindEvents() {
  if (state.isBootstrapped) return;

  elements.loginBtn.addEventListener("click", async () => {
    elements.loginError.textContent = "Redirection vers Microsoft...";
    elements.loginBtn.disabled = true;

    try {
      await login();

      if (DEV_MODE && isAuthenticated()) {
        showChat();
        await loadConversationsSafely();
      }
    } catch (error) {
      console.error(error);
      elements.loginBtn.disabled = false;
      showLogin("Impossible de démarrer la connexion Microsoft.");
    }
  });

  elements.logoutBtn.addEventListener("click", async () => {
    try {
      showLoading("Déconnexion en cours...");
      await logout();

      if (DEV_MODE) {
        showChat();
        await loadConversationsSafely();
      } else {
        showLogin();
      }
    } catch (error) {
      console.error(error);
      showChat();
      showInputError("Impossible de se déconnecter.");
    }
  });

  elements.newChatBtn.addEventListener("click", newChat);
  elements.sendBtn.addEventListener("click", send);
  elements.drawerCloseBtn.addEventListener("click", closeCandidateDrawer);
  elements.drawerOverlay.addEventListener("click", closeCandidateDrawer);
  elements.drawerBoondBtn.addEventListener("click", () => {
    openBoondManager(state.currentDrawerCandidate?.boond_url);
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeCandidateDrawer();
  });

  elements.messageInput.addEventListener("input", () => {
    resizeInput();
    updateSendButton();
  });

  elements.messageInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      send();
    }
  });

  state.isBootstrapped = true;
}

function applyFeatureVisibility() {
  elements.conversationList.hidden = !FEATURES.conversation_history;
  elements.newChatBtn.disabled = !FEATURES.conversation_history;
  elements.newChatBtn.hidden = !FEATURES.conversation_history;
  elements.candidateDrawer.hidden = true;
  elements.drawerOverlay.hidden = true;
}

function showLogin(message = "") {
  elements.loginScreen.hidden = false;
  elements.loadingScreen.hidden = true;
  elements.appShell.hidden = true;
  elements.loginError.textContent = message;
  elements.loginBtn.disabled = false;
  closeCandidateDrawer();
}

function showLoading(message = UI_CONFIG.auth_loading_message) {
  elements.loginScreen.hidden = true;
  elements.loadingScreen.hidden = false;
  elements.appShell.hidden = true;
  elements.loadingText.textContent = message;
}

function showChat() {
  if (!isAuthenticated()) {
    showLogin();
    return;
  }

  const user = getCurrentUser();
  const displayName = user?.name || user?.username || "Utilisateur SIJO";

  elements.loginScreen.hidden = true;
  elements.loadingScreen.hidden = true;
  elements.appShell.hidden = false;
  elements.currentUser.textContent = displayName;
  elements.conversationTitle.textContent ||= UI_CONFIG.default_conversation_title;
  elements.loginBtn.disabled = false;
  setUiState("empty");
  updateSendButton();
}

async function loadConversationsSafely() {
  if (!FEATURES.conversation_history) {
    state.conversations = [];
    state.currentConversationId = null;
    renderConversationList();
    elements.sidebarStatus.textContent = "";
    return;
  }

  try {
    await loadConversations();
    console.log("[BACKEND] Connected");
  } catch (error) {
    console.error(error);
    console.log("[BACKEND] Offline");
    state.conversations = [];
    state.currentConversationId = null;
    clearMessages();
    renderConversationList();
    elements.sidebarStatus.textContent = getConversationLoadError(error);
    elements.conversationTitle.textContent = UI_CONFIG.default_conversation_title;
    setUiState("empty");
  }
}

async function loadConversations() {
  elements.sidebarStatus.textContent = "Chargement des conversations...";
  state.conversations = await getConversations();
  renderConversationList();
  elements.sidebarStatus.textContent = state.conversations.length
    ? ""
    : "Aucune conversation pour le moment.";
}

function renderConversationList() {
  elements.conversationList.innerHTML = "";

  state.conversations.forEach((conversation) => {
    const row = document.createElement("div");
    row.className = "conversation-row";

    const item = document.createElement("button");
    item.type = "button";
    item.className = "conversation-item";
    item.classList.toggle("active", conversation.id === state.currentConversationId);
    item.addEventListener("click", () => openConversation(conversation.id));

    const title = document.createElement("span");
    title.className = "conversation-title";
    title.textContent = conversation.title || "Conversation sans titre";

    const date = document.createElement("span");
    date.className = "conversation-date";
    date.textContent = formatDate(conversation.updated_at || conversation.created_at);

    item.append(title, date);

    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "delete-conversation";
    remove.setAttribute("aria-label", `Supprimer ${title.textContent}`);
    remove.textContent = "×";
    remove.addEventListener("click", (event) => {
      event.stopPropagation();
      removeConversation(conversation.id);
    });

    row.append(item, remove);
    elements.conversationList.appendChild(row);
  });
}

async function openConversation(conversationId) {
  if (state.isLoading) return;

  setUiState("loading");
  clearMessages();
  closeCandidateDrawer();
  elements.conversationTitle.textContent = "Chargement...";

  try {
    const conversation = await getConversation(conversationId);
    state.currentConversationId = conversation.id;
    elements.conversationTitle.textContent = conversation.title || "Conversation";

    if (conversation.messages?.length) {
      conversation.messages.forEach((message) => {
        renderMessage(normalizeRole(message.role), message.content);
      });
      setUiState("active");
    } else {
      setUiState("empty");
    }

    renderConversationList();
    scrollToBottom();
  } catch (error) {
    console.error(error);
    setUiState("error");
    renderMessage("error", getErrorMessage(error));
  }
}

async function newChat() {
  if (!isAuthenticated()) {
    showLogin("Vous devez être connecté pour créer une conversation.");
    return;
  }

  if (state.isLoading) return;

  setLoading(true);
  showInputError("");

  try {
    const conversation = await createConversation(UI_CONFIG.default_conversation_title);
    state.currentConversationId = conversation.id;
    state.conversations = [conversation, ...state.conversations];
    clearMessages();
    closeCandidateDrawer();
    elements.conversationTitle.textContent = conversation.title || UI_CONFIG.default_conversation_title;
    setUiState("empty");
    renderConversationList();
    elements.messageInput.focus();
  } catch (error) {
    console.error(error);
    showInputError(getErrorMessage(error));
  } finally {
    setLoading(false);
  }
}

async function removeConversation(conversationId) {
  if (state.isLoading) return;

  setLoading(true);
  showInputError("");

  try {
    await deleteConversation(conversationId);
    state.conversations = state.conversations.filter((item) => item.id !== conversationId);

    if (state.currentConversationId === conversationId) {
      state.currentConversationId = null;
      clearMessages();
      closeCandidateDrawer();
      elements.conversationTitle.textContent = UI_CONFIG.default_conversation_title;
      setUiState("empty");
    }

    renderConversationList();
    elements.sidebarStatus.textContent = state.conversations.length
      ? ""
      : "Aucune conversation pour le moment.";
  } catch (error) {
    console.error(error);
    showInputError(getErrorMessage(error));
  } finally {
    setLoading(false);
  }
}

function renderMessage(role, text) {
  const message = document.createElement("div");
  message.className = `message ${role}`;

  const label = document.createElement("div");
  label.className = "msg-label";
  label.textContent = getRoleLabel(role);

  const bubble = document.createElement("div");
  bubble.className = "bubble";
  bubble.textContent = text;

  message.append(label, bubble);
  elements.messages.appendChild(message);
  setUiState(role === "error" ? "error" : "active");
  scrollToBottom();

  return message;
}

function renderAssistantResponse(response) {
  if (response.answer) {
    renderMessage(response.ui?.type === "error" ? "error" : "assistant", response.answer);
  }

  if (response.ui?.type === "clarification") {
    renderClarificationForm(response);
    return;
  }

  if (response.ui?.type === "candidate_detail" && response.candidate) {
    renderCandidateDetail(response.candidate);
    return;
  }

  if (response.ui?.type === "technical_summary") {
    renderTechnicalSummary(response.ui);
    return;
  }

  if (
    FEATURES.candidate_cards
    && response.ui?.type === "candidate_cards"
    && Array.isArray(response.candidates)
    && response.candidates.length > 0
  ) {
    renderCandidateCards(response.candidates);
  }
}

function renderCandidateDetail(candidate) {
  const detail = document.createElement("article");
  detail.className = "candidate-detail-card";

  const header = document.createElement("div");
  header.className = "candidate-card-header";

  const identity = document.createElement("div");
  const name = document.createElement("h3");
  name.textContent = candidate.full_name || "Candidat sans nom";

  const title = document.createElement("p");
  title.textContent = candidate.title || CANDIDATE_CONFIG.fallback_title;

  identity.append(name, title);
  header.appendChild(identity);

  const meta = document.createElement("div");
  meta.className = "candidate-meta";
  meta.append(
    createMetaItem("Expérience", formatExperience(candidate.experience_years)),
    createMetaItem("Localisation", candidate.location || CANDIDATE_CONFIG.fallback_location),
    createMetaItem("Disponibilité", candidate.availability || CANDIDATE_CONFIG.fallback_availability),
    createMetaItem("Contrat", formatList(candidate.contract_preferences)),
    createMetaItem("Salaire", candidate.salary_expectation || "Non renseigné"),
    createMetaItem("TJM", candidate.tjm || "Non renseigné"),
  );

  const summary = document.createElement("p");
  summary.className = "candidate-summary";
  summary.textContent = candidate.summary || "Aucun résumé disponible.";

  detail.append(header, meta, summary, renderSkillTags(candidate.skills));
  elements.messages.appendChild(detail);
  setUiState("active");
  scrollToBottom();
}

function renderTechnicalSummary(ui) {
  const card = document.createElement("article");
  card.className = "technical-summary-card";

  const title = document.createElement("h3");
  title.textContent = ui.title || "Analyse technique";

  const summary = document.createElement("p");
  summary.className = "candidate-summary";
  summary.textContent = ui.summary || "Aucune analyse disponible.";

  card.append(title, summary);

  const grid = document.createElement("div");
  grid.className = "technical-summary-grid";
  grid.append(
    renderSummaryList("Points forts", ui.strengths),
    renderSummaryList("Points de vigilance", ui.weaknesses),
    renderSummaryList("Langues", ui.languages),
  );
  card.appendChild(grid);

  if (Array.isArray(ui.tools) && ui.tools.length > 0) {
    const tools = document.createElement("div");
    tools.className = "technical-tools";

    const toolsTitle = document.createElement("h4");
    toolsTitle.textContent = "Compétences évaluées";
    tools.appendChild(toolsTitle);

    ui.tools.forEach((tool) => {
      const row = document.createElement("div");
      row.className = "technical-tool-row";

      const name = document.createElement("span");
      name.textContent = tool.name || "Outil";

      const level = document.createElement("strong");
      level.textContent = formatToolLevel(tool.level);

      row.append(name, level);
      tools.appendChild(row);
    });

    card.appendChild(tools);
  }

  elements.messages.appendChild(card);
  setUiState("active");
  scrollToBottom();
}

function renderClarificationForm(response) {
  const questions = Array.isArray(response.ui?.questions) ? response.ui.questions : [];
  const wrapper = document.createElement("form");
  wrapper.className = "clarification-form";

  const title = document.createElement("h3");
  title.textContent = response.ui?.title || "Précision nécessaire";
  wrapper.appendChild(title);

  questions.forEach((question) => {
    const field = document.createElement("label");
    field.className = "clarification-field";

    const label = document.createElement("span");
    label.textContent = question.label || question.field || "Précision";

    const input = document.createElement("input");
    input.type = "text";
    input.name = question.field || `field_${wrapper.elements.length}`;
    input.required = Boolean(question.required);
    input.autocomplete = "off";

    field.append(label, input);
    wrapper.appendChild(field);
  });

  const submit = document.createElement("button");
  submit.type = "submit";
  submit.className = "candidate-btn primary";
  submit.textContent = "Envoyer";
  wrapper.appendChild(submit);

  wrapper.addEventListener("submit", (event) => {
    event.preventDefault();
    submitClarification(wrapper, response);
  });

  elements.messages.appendChild(wrapper);
  setUiState("active");
  scrollToBottom();
}

async function submitClarification(form, sourceResponse) {
  if (state.isLoading) return;

  const values = Object.fromEntries(new FormData(form).entries());
  const summary = Object.values(values).filter(Boolean).join(", ");

  form.querySelectorAll("input, button").forEach((node) => {
    node.disabled = true;
  });

  if (summary) {
    renderMessage("user", summary);
  }

  const loadingMessage = renderLoading();
  setLoading(true);

  try {
    const response = await sendClarification({
      type: "clarification",
      action: "submit",
      values,
      source_ui: sourceResponse.ui,
    }, state.currentConversationId);

    loadingMessage.remove();

    if (response.conversation_id) {
      state.currentConversationId = response.conversation_id;
    }

    renderAssistantResponse(response);
    await loadConversationsSafely();
  } catch (error) {
    console.error(error);
    loadingMessage.remove();
    renderMessage("error", getErrorMessage(error));
  } finally {
    setLoading(false);
  }
}

function renderCandidateCards(candidates) {
  const wrapper = document.createElement("div");
  wrapper.className = "candidate-cards";

  candidates.forEach((candidate) => {
    wrapper.appendChild(renderCandidateCard(candidate));
  });

  elements.messages.appendChild(wrapper);
  setUiState("active");
  scrollToBottom();

  return wrapper;
}

function renderCandidateCard(candidate) {
  const card = document.createElement("article");
  card.className = "candidate-card";

  const header = document.createElement("div");
  header.className = "candidate-card-header";

  const identity = document.createElement("div");
  const name = document.createElement("h3");
  name.textContent = candidate.full_name || "Candidat sans nom";

  const title = document.createElement("p");
  title.textContent = candidate.title || CANDIDATE_CONFIG.fallback_title;

  identity.append(name, title);
  header.append(identity, createMatchBadge(candidate.match_score));

  const meta = document.createElement("div");
  meta.className = "candidate-meta";
  meta.append(
    createMetaItem("Expérience", formatExperience(candidate.experience_years)),
    createMetaItem("Localisation", candidate.location || CANDIDATE_CONFIG.fallback_location),
    createMetaItem("Disponibilité", candidate.availability || CANDIDATE_CONFIG.fallback_availability),
  );

  const summary = document.createElement("p");
  summary.className = "candidate-summary";
  summary.textContent = candidate.summary || "Aucun résumé disponible.";

  const skills = renderSkillTags(candidate.skills);

  const actions = document.createElement("div");
  actions.className = "candidate-actions";

  const detailsBtn = document.createElement("button");
  detailsBtn.type = "button";
  detailsBtn.className = "candidate-btn secondary";
  detailsBtn.textContent = "Voir plus";
  detailsBtn.addEventListener("click", () => openCandidateDrawer(candidate));

  const boondBtn = document.createElement("button");
  boondBtn.type = "button";
  boondBtn.className = "candidate-btn primary";
  boondBtn.textContent = "Ouvrir BoondManager";
  boondBtn.disabled = !candidate.boond_url;
  boondBtn.addEventListener("click", () => openBoondManager(candidate.boond_url));

  if (FEATURES.candidate_drawer && CANDIDATE_CONFIG.show_candidate_drawer) {
    actions.appendChild(detailsBtn);
  }

  if (FEATURES.boond_redirect && candidate.boond_url) {
    actions.appendChild(boondBtn);
  }

  card.append(header, meta, summary, skills, actions);

  return card;
}

function openCandidateDrawer(candidate) {
  if (!FEATURES.candidate_drawer || !CANDIDATE_CONFIG.show_candidate_drawer) return;

  state.currentDrawerCandidate = candidate;

  elements.drawerName.textContent = candidate.full_name || "Candidat sans nom";
  elements.drawerTitle.textContent = candidate.title || CANDIDATE_CONFIG.fallback_title;
  elements.drawerSummary.textContent = candidate.summary || "Aucun résumé disponible.";
  elements.drawerExperience.textContent = formatExperience(candidate.experience_years);
  elements.drawerLocation.textContent = candidate.location || CANDIDATE_CONFIG.fallback_location;
  elements.drawerAvailability.textContent = candidate.availability || CANDIDATE_CONFIG.fallback_availability;
  elements.drawerMatch.textContent = formatMatchScore(candidate.match_score);
  elements.drawerSkills.innerHTML = "";
  elements.drawerSkills.append(...createSkillElements(candidate.skills));
  elements.drawerBoondBtn.hidden = !FEATURES.boond_redirect || !candidate.boond_url;
  elements.drawerBoondBtn.disabled = !FEATURES.boond_redirect || !candidate.boond_url;

  elements.drawerOverlay.hidden = false;
  elements.candidateDrawer.hidden = false;
  requestAnimationFrame(() => {
    elements.drawerOverlay.classList.add("open");
    elements.candidateDrawer.classList.add("open");
  });
}

function closeCandidateDrawer() {
  if (!elements.candidateDrawer || !elements.drawerOverlay) return;

  state.currentDrawerCandidate = null;
  elements.drawerOverlay.classList.remove("open");
  elements.candidateDrawer.classList.remove("open");
  elements.drawerOverlay.hidden = true;
  elements.candidateDrawer.hidden = true;
}

function openBoondManager(url) {
  if (!FEATURES.boond_redirect || !url) return;

  if (CANDIDATE_CONFIG.open_boond_in_new_tab) {
    window.open(url, "_blank", "noopener,noreferrer");
    return;
  }

  window.location.href = url;
}

function renderLoading() {
  const message = document.createElement("div");
  message.className = "message assistant";
  message.dataset.loading = "true";

  const label = document.createElement("div");
  label.className = "msg-label";
  label.textContent = UI_CONFIG.assistant_label;

  const bubble = document.createElement("div");
  bubble.className = "bubble loading-bubble";

  const spinner = document.createElement("span");
  spinner.className = "spinner";
  spinner.setAttribute("aria-hidden", "true");

  const text = document.createElement("span");
  text.textContent = UI_CONFIG.loading_message;

  bubble.append(spinner, text);
  message.append(label, bubble);
  elements.messages.appendChild(message);
  setUiState("loading");
  scrollToBottom();

  return message;
}

async function send() {
  const text = elements.messageInput.value.trim();

  if (!text || state.isLoading) return;

  if (!isAuthenticated()) {
    showLogin("Vous devez être connecté pour envoyer un message.");
    return;
  }

  showInputError("");
  renderMessage("user", text);
  updateTitleFromMessage(text);
  resetInput();

  const loadingMessage = renderLoading();
  setLoading(true);

  try {
    const response = await sendMessage(text, state.currentConversationId);
    loadingMessage.remove();

    if (response.conversation_id) {
      state.currentConversationId = response.conversation_id;
    }

    renderAssistantResponse(response);
    await loadConversationsSafely();
  } catch (error) {
    console.error(error);
    loadingMessage.remove();
    renderMessage("error", getErrorMessage(error));
  } finally {
    setLoading(false);
  }
}

function setUiState(nextState) {
  state.uiState = nextState;
  const hasMessages = elements.messages.children.length > 0;

  elements.emptyState.hidden = hasMessages || nextState === "loading" || nextState === "error";
  elements.messages.classList.toggle("active", hasMessages);
}

function setLoading(isLoading) {
  state.isLoading = isLoading;
  elements.messageInput.disabled = isLoading;
  elements.sendBtn.disabled = isLoading;
  elements.newChatBtn.disabled = isLoading;
  elements.messageInput.closest(".input-wrap").classList.toggle("disabled", isLoading);
  updateSendButton();
}

function clearMessages() {
  elements.messages.innerHTML = "";
  setUiState("empty");
}

function resizeInput() {
  elements.messageInput.style.height = "auto";
  elements.messageInput.style.height = `${Math.min(elements.messageInput.scrollHeight, 200)}px`;
}

function resetInput() {
  elements.messageInput.value = "";
  elements.messageInput.style.height = "auto";
  updateSendButton();
}

function updateSendButton() {
  const canSend = elements.messageInput.value.trim().length > 0 && !state.isLoading;
  elements.sendBtn.classList.toggle("on", canSend);
}

function showInputError(message) {
  elements.inputError.textContent = message;
}

function scrollToBottom() {
  requestAnimationFrame(() => {
    elements.messagesArea.scrollTop = elements.messagesArea.scrollHeight;
  });
}

function updateTitleFromMessage(text) {
  if (!state.currentConversationId && elements.messages.children.length <= 1) {
    elements.conversationTitle.textContent = truncateTitle(text);
  }
}

function createMetaItem(label, value) {
  const item = document.createElement("div");
  item.className = "candidate-meta-item";

  const labelNode = document.createElement("span");
  labelNode.textContent = label;

  const valueNode = document.createElement("strong");
  valueNode.textContent = value;

  item.append(labelNode, valueNode);
  return item;
}

function renderSummaryList(title, items) {
  const section = document.createElement("section");
  section.className = "technical-summary-section";

  const heading = document.createElement("h4");
  heading.textContent = title;
  section.appendChild(heading);

  const list = document.createElement("ul");
  const normalizedItems = Array.isArray(items) && items.length ? items : ["Non renseigné"];

  normalizedItems.forEach((item) => {
    const li = document.createElement("li");
    li.textContent = item;
    list.appendChild(li);
  });

  section.appendChild(list);
  return section;
}

function createMatchBadge(score) {
  const badge = document.createElement("span");
  badge.className = "match-badge";
  badge.textContent = formatMatchScore(score);
  return badge;
}

function formatList(items) {
  return Array.isArray(items) && items.length ? items.join(", ") : "Non renseigné";
}

function formatToolLevel(level) {
  const value = Number(level);
  if (Number.isNaN(value)) return "Niveau non renseigné";

  return `${value}/5`;
}

function renderSkillTags(skills) {
  const container = document.createElement("div");
  container.className = "candidate-skills";
  container.append(...createSkillElements(skills));
  return container;
}

function createSkillElements(skills) {
  const normalizedSkills = Array.isArray(skills) && skills.length
    ? skills.slice(0, CANDIDATE_CONFIG.max_visible_skills)
    : ["Compétences non renseignées"];

  return normalizedSkills.map((skill) => {
    const tag = document.createElement("span");
    tag.className = "skill-tag";
    tag.textContent = skill;
    return tag;
  });
}

function formatExperience(years) {
  if (years === null || years === undefined || years === "") return "Non renseignée";

  const value = Number(years);
  if (Number.isNaN(value)) return String(years);

  return `${value} an${value > 1 ? "s" : ""}`;
}

function formatMatchScore(score) {
  if (score === null || score === undefined || score === "") return "Score N/A";

  const value = Number(score);
  if (Number.isNaN(value)) return String(score);

  if (CANDIDATE_CONFIG.score_display !== "percentage") return String(value);

  return `${Math.round(value * 100)}% match`;
}

function truncateTitle(text) {
  return text.length > 42 ? `${text.slice(0, 42)}...` : text;
}

function normalizeRole(role) {
  return role === "user" ? "user" : "assistant";
}

function getRoleLabel(role) {
  if (role === "user") return UI_CONFIG.user_label;
  if (role === "error") return "Erreur";
  return UI_CONFIG.assistant_label;
}

function getErrorMessage(error) {
  if (error instanceof ApiError) {
    if (error.type === "network") return UI_CONFIG.network_error_message;
    if (error.type === "timeout") return UI_CONFIG.timeout_error_message;
    if (error.type === "malformed_response") return UI_CONFIG.malformed_response_message;
    if (error.type === "auth") return "Vous devez être connecté pour continuer.";
    return UI_CONFIG.generic_error_message;
  }

  return UI_CONFIG.generic_error_message;
}

function getConversationLoadError(error) {
  if (error instanceof ApiError && error.type === "network") {
    return UI_CONFIG.backend_offline_message;
  }

  return "Impossible de charger les conversations.";
}

function formatDate(value) {
  if (!value) return "";

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";

  return new Intl.DateTimeFormat("fr-FR", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}
