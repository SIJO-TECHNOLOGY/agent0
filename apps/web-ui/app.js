import {
  ApiError,
  createConversation,
  deleteAllConversations,
  deleteConversation,
  getConversation,
  getConversations,
  renameConversation,
  resetChatSession,
  sendClarification,
  streamSearch,
} from "./api.js";
import {
  getCurrentUser,
  handleRedirect,
  isAuthenticated,
  login,
  logout,
} from "./auth.js";
import { CANDIDATE_CONFIG, DEV_MODE, FEATURES } from "./config.js";
import {
  applyStaticTranslations,
  formatDate,
  getLanguage,
  initLanguage,
  onLanguageChange,
  setLanguage,
  t,
  tCount,
} from "./i18n.js";

window.addEventListener("error", console.error);
window.addEventListener("unhandledrejection", console.error);

const state = {
  conversations: [],
  currentConversationId: null,
  currentDrawerCandidate: null,
  isBootstrapped: false,
  isLoading: false,
  uiState: "empty",
  abortController: null,
  renderedResults: [],
  drawerTrigger: null,
  conversationQuery: "",
};

function generateSessionId() {
  if (window.crypto?.randomUUID) return `session_${window.crypto.randomUUID().replaceAll("-", "").slice(0, 12)}`;
  return `session_${Date.now().toString(36)}${Math.random().toString(36).slice(2, 8)}`;
}

function ensureSessionId() {
  if (!state.currentConversationId) {
    state.currentConversationId = generateSessionId();
  }
  return state.currentConversationId;
}

const elements = {
  loginScreen: document.getElementById("loginScreen"),
  loadingScreen: document.getElementById("loadingScreen"),
  loadingText: document.getElementById("loadingText"),
  appShell: document.getElementById("appShell"),
  loginBtn: document.getElementById("loginBtn"),
  loginError: document.getElementById("loginError"),
  logoutBtn: document.getElementById("logoutBtn"),
  conversationTitle: document.getElementById("conversationTitle"),
  conversationList: document.getElementById("conversationList"),
  sidebarStatus: document.getElementById("sidebarStatus"),
  newChatBtn: document.getElementById("newChatBtn"),
  searchBtn: document.getElementById("searchBtn"),
  conversationSearch: document.getElementById("conversationSearch"),
  clearAllBtn: document.getElementById("clearAllBtn"),
  settingsBtn: document.getElementById("settingsBtn"),
  settingsMenu: document.getElementById("settingsMenu"),
  userBtn: document.getElementById("userBtn"),
  userMenu: document.getElementById("userMenu"),
  sidebarUser: document.getElementById("sidebarUser"),
  sidebarAvatar: document.getElementById("sidebarAvatar"),
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
  drawerExtra: document.getElementById("drawerExtra"),
  drawerBoondBtn: document.getElementById("drawerBoondBtn"),
  langSwitcher: document.getElementById("langSwitcher"),
  srStatus: document.getElementById("srStatus"),
};

document.addEventListener("DOMContentLoaded", init);

async function init() {
  console.log("[APP] Starting");
  initLanguage();
  applyStaticTranslations();
  bindEvents();
  applyFeatureVisibility();
  showLoading();

  try {
    await handleRedirect();
    console.log("[AUTH] OK");
  } catch (error) {
    console.error(error);
    showLogin(t("auth.errors.finalize"));
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

  if (elements.langSwitcher) {
    elements.langSwitcher.value = getLanguage();
    elements.langSwitcher.addEventListener("change", (event) => {
      setLanguage(event.target.value);
    });
  }
  onLanguageChange(handleLanguageChange);

  elements.loginBtn.addEventListener("click", async () => {
    elements.loginError.textContent = t("auth.redirecting");
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
      showLogin(t("auth.errors.start"));
    }
  });

  elements.logoutBtn.addEventListener("click", async () => {
    try {
      if (state.abortController) state.abortController.abort();
      showLoading(t("auth.logging_out"));
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
      showInputError(t("auth.errors.logout"));
    }
  });

  elements.newChatBtn.addEventListener("click", newChat);
  elements.sendBtn.addEventListener("click", send);

  if (elements.searchBtn) {
    elements.searchBtn.addEventListener("click", toggleConversationSearch);
  }
  if (elements.conversationSearch) {
    elements.conversationSearch.addEventListener("input", (event) => {
      state.conversationQuery = event.target.value.trim().toLowerCase();
      renderConversationList();
    });
  }
  if (elements.clearAllBtn) {
    elements.clearAllBtn.addEventListener("click", clearAllConversations);
  }
  if (elements.settingsBtn && elements.settingsMenu) {
    elements.settingsBtn.addEventListener("click", (event) => {
      event.stopPropagation();
      toggleMenu(elements.settingsMenu, elements.settingsBtn, [
        [elements.userMenu, elements.userBtn],
      ]);
    });
  }
  if (elements.userBtn && elements.userMenu) {
    elements.userBtn.addEventListener("click", (event) => {
      event.stopPropagation();
      toggleMenu(elements.userMenu, elements.userBtn, [
        [elements.settingsMenu, elements.settingsBtn],
      ]);
    });
  }
  document.addEventListener("click", (event) => {
    if (
      elements.settingsMenu
      && !elements.settingsMenu.hidden
      && !elements.settingsMenu.contains(event.target)
      && !elements.settingsBtn?.contains(event.target)
    ) {
      closeMenu(elements.settingsMenu, elements.settingsBtn);
    }
    if (
      elements.userMenu
      && !elements.userMenu.hidden
      && !elements.userMenu.contains(event.target)
      && !elements.userBtn?.contains(event.target)
    ) {
      closeMenu(elements.userMenu, elements.userBtn);
    }
  });

  elements.drawerCloseBtn.addEventListener("click", closeCandidateDrawer);
  elements.drawerOverlay.addEventListener("click", closeCandidateDrawer);
  elements.drawerBoondBtn.addEventListener("click", () => {
    openBoondManager(state.currentDrawerCandidate?.boond_url);
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      closeCandidateDrawer();
      if (elements.settingsMenu && !elements.settingsMenu.hidden) {
        closeMenu(elements.settingsMenu, elements.settingsBtn);
        elements.settingsBtn?.focus();
      }
      if (elements.userMenu && !elements.userMenu.hidden) {
        closeMenu(elements.userMenu, elements.userBtn);
        elements.userBtn?.focus();
      }
    }
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

function handleLanguageChange() {
  applyStaticTranslations();
  if (elements.langSwitcher) elements.langSwitcher.value = getLanguage();
  if (!elements.appShell.hidden) updateSidebarIdentity();

  // Re-render the dynamically-generated chrome we can cheaply refresh.
  // Already-streamed chat bubbles and candidate cards keep their original
  // language until the next render/search.
  renderConversationList();
  if (FEATURES.conversation_history) {
    elements.sidebarStatus.textContent = state.conversations.length
      ? ""
      : t("conversations.empty");
  }

  // Re-render candidate-result blocks (toolbar + cards) in the new language,
  // preserving each block's filter/sort selections.
  state.renderedResults.forEach(({ wrapper, candidates, ui, viewState }) => {
    populateCandidateResults(wrapper, candidates, ui, viewState);
  });
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

function showLoading(message = t("auth.connecting")) {
  elements.loginScreen.hidden = true;
  elements.loadingScreen.hidden = false;
  elements.appShell.hidden = true;
  elements.loadingText.textContent = message;
}

function updateSidebarIdentity() {
  const user = getCurrentUser();
  const displayName = user?.name || user?.username || t("app.user_label");
  if (elements.sidebarUser) elements.sidebarUser.textContent = displayName;
  if (elements.sidebarAvatar) elements.sidebarAvatar.textContent = initials(displayName);
}

function showChat() {
  if (!isAuthenticated()) {
    showLogin();
    return;
  }

  elements.loginScreen.hidden = true;
  elements.loadingScreen.hidden = true;
  elements.appShell.hidden = false;
  updateSidebarIdentity();
  elements.conversationTitle.textContent ||= t("conversations.default_title");
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
    elements.conversationTitle.textContent = t("conversations.default_title");
    setUiState("empty");
  }
}

async function loadConversations() {
  elements.sidebarStatus.textContent = t("conversations.loading_list");
  state.conversations = await getConversations();
  renderConversationList();
  elements.sidebarStatus.textContent = state.conversations.length
    ? ""
    : t("conversations.empty");
}

const CONVERSATION_ICON_SVG =
  '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 11.5a8.4 8.4 0 0 1-8.5 8.5 8.4 8.4 0 0 1-3.8-.9L3 21l1.9-5.7A8.4 8.4 0 0 1 4 11.5 8.4 8.4 0 0 1 12.5 3 8.4 8.4 0 0 1 21 11.5z"></path></svg>';

function renderConversationList() {
  elements.conversationList.innerHTML = "";

  const query = state.conversationQuery;
  const visible = query
    ? state.conversations.filter((conversation) =>
        (conversation.title || t("conversations.untitled")).toLowerCase().includes(query),
      )
    : state.conversations;

  visible.forEach((conversation) => {
    const row = document.createElement("div");
    row.className = "conversation-row";

    const item = document.createElement("button");
    item.type = "button";
    item.className = "conversation-item";
    item.classList.toggle("active", conversation.id === state.currentConversationId);
    item.addEventListener("click", () => openConversation(conversation.id));

    const icon = document.createElement("span");
    icon.className = "conv-icon";
    icon.innerHTML = CONVERSATION_ICON_SVG;

    const textCol = document.createElement("span");
    textCol.className = "conv-text";

    const title = document.createElement("span");
    title.className = "conversation-title";
    title.textContent = conversation.title || t("conversations.untitled");

    const date = document.createElement("span");
    date.className = "conversation-date";
    date.textContent = formatDate(conversation.updated_at || conversation.created_at);

    textCol.append(title, date);
    item.append(icon, textCol);

    const rename = document.createElement("button");
    rename.type = "button";
    rename.className = "rename-conversation";
    rename.setAttribute("aria-label", t("conversations.rename_aria", { title: title.textContent }));
    rename.textContent = "✎";
    rename.addEventListener("click", (event) => {
      event.stopPropagation();
      promptRenameConversation(conversation);
    });

    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "delete-conversation";
    remove.setAttribute("aria-label", t("conversations.delete_aria", { title: title.textContent }));
    remove.textContent = "×";
    remove.addEventListener("click", (event) => {
      event.stopPropagation();
      removeConversation(conversation.id);
    });

    row.append(item, rename, remove);
    elements.conversationList.appendChild(row);
  });
}

function openMenu(menu, btn) {
  if (!menu) return;
  menu.hidden = false;
  btn?.setAttribute("aria-expanded", "true");
}

function closeMenu(menu, btn) {
  if (!menu) return;
  menu.hidden = true;
  btn?.setAttribute("aria-expanded", "false");
}

function toggleMenu(menu, btn, others = []) {
  if (!menu) return;
  others.forEach(([otherMenu, otherBtn]) => closeMenu(otherMenu, otherBtn));
  if (menu.hidden) {
    openMenu(menu, btn);
  } else {
    closeMenu(menu, btn);
  }
}

function toggleConversationSearch() {
  const input = elements.conversationSearch;
  if (!input) return;

  const willShow = input.hidden;
  input.hidden = !willShow;
  elements.searchBtn?.setAttribute("aria-expanded", String(willShow));
  elements.searchBtn?.classList.toggle("active", willShow);

  if (willShow) {
    input.focus();
  } else {
    input.value = "";
    state.conversationQuery = "";
    renderConversationList();
  }
}

async function clearAllConversations() {
  if (state.isLoading || !state.conversations.length) return;
  if (!window.confirm(t("sidebar.clear_all_confirm"))) return;

  if (state.abortController) state.abortController.abort();
  setLoading(true);
  showInputError("");

  try {
    await deleteAllConversations();
    state.conversations = [];
    state.currentConversationId = null;
    clearMessages();
    closeCandidateDrawer();
    elements.conversationTitle.textContent = t("conversations.default_title");
    setUiState("empty");
    renderConversationList();
    elements.sidebarStatus.textContent = t("conversations.empty");
  } catch (error) {
    console.error(error);
    showInputError(getErrorMessage(error));
  } finally {
    setLoading(false);
  }
}

function initials(name) {
  const parts = String(name || "").trim().split(/\s+/).filter(Boolean);
  if (!parts.length) return "?";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

async function openConversation(conversationId) {
  if (state.isLoading) return;

  if (state.abortController) state.abortController.abort();

  setUiState("loading");
  clearMessages();
  closeCandidateDrawer();
  elements.conversationTitle.textContent = t("conversations.loading_one");

  try {
    const conversation = await getConversation(conversationId);
    state.currentConversationId = conversation.id;
    elements.conversationTitle.textContent = conversation.title || t("conversations.open_fallback");

    if (conversation.messages?.length) {
      conversation.messages.forEach((message) => {
        const role = normalizeRole(message.role);
        // Assistant turns persist their UI payload (candidate cards…):
        // replay them exactly as the live stream rendered them.
        if (role === "assistant" && message.ui && typeof message.ui === "object") {
          renderStreamFinalResponse({ message: message.content, ui: message.ui });
        } else {
          renderMessage(role, message.content);
        }
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
    showLogin(t("auth.errors.login_required_conversation"));
    return;
  }

  if (state.isLoading) return;

  if (state.abortController) state.abortController.abort();

  setLoading(true);
  showInputError("");

  try {
    const previousSessionId = state.currentConversationId;
    if (previousSessionId) {
      await resetChatSession(previousSessionId).catch(console.warn);
    }
    const conversation = await createConversation(t("conversations.default_title"));
    state.currentConversationId = conversation.id;
    state.conversations = [conversation, ...state.conversations];
    clearMessages();
    closeCandidateDrawer();
    elements.conversationTitle.textContent = conversation.title || t("conversations.default_title");
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

async function promptRenameConversation(conversation) {
  if (state.isLoading) return;

  const current = conversation.title || t("conversations.untitled");
  const input = window.prompt(t("conversations.rename_prompt"), current);
  if (input === null) return;
  const title = input.trim();
  if (!title || title === current) return;

  try {
    const updated = await renameConversation(conversation.id, title);
    state.conversations = state.conversations.map((item) =>
      item.id === updated.id ? { ...item, ...updated } : item,
    );
    if (state.currentConversationId === updated.id) {
      elements.conversationTitle.textContent = updated.title;
    }
    renderConversationList();
  } catch (error) {
    console.error(error);
    showInputError(getErrorMessage(error));
  }
}

async function removeConversation(conversationId) {
  if (state.isLoading) return;

  if (state.abortController) state.abortController.abort();

  setLoading(true);
  showInputError("");

  try {
    await deleteConversation(conversationId);
    state.conversations = state.conversations.filter((item) => item.id !== conversationId);

    if (state.currentConversationId === conversationId) {
      state.currentConversationId = null;
      clearMessages();
      closeCandidateDrawer();
      elements.conversationTitle.textContent = t("conversations.default_title");
      setUiState("empty");
    }

    renderConversationList();
    elements.sidebarStatus.textContent = state.conversations.length
      ? ""
      : t("conversations.empty");
  } catch (error) {
    console.error(error);
    showInputError(getErrorMessage(error));
  } finally {
    setLoading(false);
  }
}

function buildMessageHead(role) {
  const head = document.createElement("div");
  head.className = "msg-head";

  const avatar = document.createElement("span");
  const name = document.createElement("span");
  name.className = "msg-name";

  if (role === "user") {
    avatar.className = "msg-avatar user";
    const displayName = getCurrentUser()?.name || getCurrentUser()?.username || t("app.user_label");
    avatar.textContent = initials(displayName);
    name.textContent = displayName;
  } else {
    avatar.className = "msg-avatar assistant";
    avatar.textContent = "S";
    name.textContent = t("app.assistant_label");
  }

  avatar.setAttribute("aria-hidden", "true");
  head.append(avatar, name);
  return head;
}

function renderMessage(role, text) {
  const message = document.createElement("div");
  message.className = `message ${role}`;

  const body = document.createElement("div");
  body.className = "msg-body";
  body.textContent = text;

  message.append(buildMessageHead(role), body);
  elements.messages.appendChild(message);
  setUiState(role === "error" ? "error" : "active");
  // Auto-scroll only when the user sends a message, not for assistant responses.
  if (role === "user") scrollToBottom();

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
    renderCandidateCards(response.candidates, response.ui);
  }
}

function renderStreamFinalResponse(data) {
  const ui = data?.ui && typeof data.ui === "object" ? data.ui : { type: "text" };
  const candidates = Array.isArray(ui.candidates)
    ? ui.candidates
    : Array.isArray(data?.candidates)
      ? data.candidates
      : [];

  if (typeof data?.message === "string" && data.message.trim()) {
    renderMessage("assistant", data.message);
    if (elements.srStatus) elements.srStatus.textContent = data.message;
  }

  if (
    FEATURES.candidate_cards
    && ui.type === "candidate_cards"
    && candidates.length > 0
  ) {
    renderCandidateCards(candidates, ui);
  }
}

function renderCandidateDetail(candidate) {
  const detail = document.createElement("article");
  detail.className = "candidate-detail-card";

  const header = document.createElement("div");
  header.className = "candidate-card-header";

  const identity = document.createElement("div");
  const name = document.createElement("h3");
  name.textContent = candidate.full_name || t("candidate.no_name");

  const title = document.createElement("p");
  title.textContent = candidate.title || t("candidate.fallback_title");

  identity.append(name, title);
  header.appendChild(identity);

  const meta = document.createElement("div");
  meta.className = "candidate-meta";
  meta.append(
    createMetaItem(t("candidate.meta.experience"), experienceDisplay(candidate)),
    createMetaItem(t("candidate.meta.location"), candidate.location || t("candidate.fallback_location")),
    createMetaItem(t("candidate.meta.availability"), candidate.availability || t("candidate.fallback_availability")),
    createMetaItem(t("candidate.meta.contract"), formatList(candidate.contract_preferences)),
    createMetaItem(t("candidate.meta.salary"), candidate.salary_expectation || t("candidate.not_specified")),
    createMetaItem(t("candidate.meta.tjm"), candidate.tjm || t("candidate.not_specified")),
  );

  const summary = document.createElement("p");
  summary.className = "candidate-summary";
  summary.textContent = candidate.summary || t("candidate.no_summary");

  detail.append(
    header,
    meta,
    summary,
    renderHighlightTags(candidate.highlights),
    renderSkillTags(candidate.skills, candidate.highlights),
    renderAiEvaluation(candidate),
    renderExperiences(candidate.experiences),
    renderCandidateInsights(candidate),
  );
  elements.messages.appendChild(detail);
  setUiState("active");
}

function renderTechnicalSummary(ui) {
  const card = document.createElement("article");
  card.className = "technical-summary-card";

  const title = document.createElement("h3");
  title.textContent = ui.title || t("technical.fallback_title");

  const summary = document.createElement("p");
  summary.className = "candidate-summary";
  summary.textContent = ui.summary || t("technical.no_analysis");

  card.append(title, summary);

  const grid = document.createElement("div");
  grid.className = "technical-summary-grid";
  grid.append(
    renderSummaryList(t("technical.strengths"), ui.strengths),
    renderSummaryList(t("technical.weaknesses"), ui.weaknesses),
    renderSummaryList(t("technical.languages"), ui.languages),
  );
  card.appendChild(grid);

  if (Array.isArray(ui.tools) && ui.tools.length > 0) {
    const tools = document.createElement("div");
    tools.className = "technical-tools";

    const toolsTitle = document.createElement("h4");
    toolsTitle.textContent = t("technical.tools_title");
    tools.appendChild(toolsTitle);

    ui.tools.forEach((tool) => {
      const row = document.createElement("div");
      row.className = "technical-tool-row";

      const name = document.createElement("span");
      name.textContent = tool.name || t("technical.tool_fallback");

      const level = document.createElement("strong");
      level.textContent = formatToolLevel(tool.level);

      row.append(name, level);
      tools.appendChild(row);
    });

    card.appendChild(tools);
  }

  elements.messages.appendChild(card);
  setUiState("active");
}

function renderClarificationForm(response) {
  const questions = Array.isArray(response.ui?.questions) ? response.ui.questions : [];
  const wrapper = document.createElement("form");
  wrapper.className = "clarification-form";

  const title = document.createElement("h3");
  title.textContent = response.ui?.title || t("clarification.fallback_title");
  wrapper.appendChild(title);

  questions.forEach((question) => {
    const field = document.createElement("label");
    field.className = "clarification-field";

    const label = document.createElement("span");
    label.textContent = question.label || question.field || t("clarification.field_fallback");

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
  submit.textContent = t("clarification.submit");
  wrapper.appendChild(submit);

  wrapper.addEventListener("submit", (event) => {
    event.preventDefault();
    submitClarification(wrapper, response);
  });

  elements.messages.appendChild(wrapper);
  setUiState("active");
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

function renderCandidateCards(candidates, ui = {}) {
  const wrapper = document.createElement("div");
  wrapper.className = "candidate-results";

  // Preserve filter/sort state across re-renders (e.g. language switch).
  const viewState = { strictOnly: false, availableOnly: false, sortMode: "default" };
  populateCandidateResults(wrapper, candidates, ui, viewState);

  // Register for re-render on language change (toolbar + cards are built with
  // t() and would otherwise stay in the previous language).
  state.renderedResults.push({ wrapper, candidates, ui, viewState });

  elements.messages.appendChild(wrapper);
  setUiState("active");

  return wrapper;
}

function populateCandidateResults(wrapper, candidates, ui, viewState) {
  wrapper.innerHTML = "";

  const toolbar = renderCandidateResultsToolbar(ui, candidates);
  const list = document.createElement("div");
  list.className = "candidate-cards";

  const strictInput = toolbar.querySelector("[data-strict-only]");
  const availableInput = toolbar.querySelector("[data-available-only]");
  const sortSelect = toolbar.querySelector("[data-sort]");

  // Restore prior view state so a re-render does not reset the user's choices.
  if (strictInput) strictInput.checked = viewState.strictOnly;
  if (availableInput) availableInput.checked = viewState.availableOnly;
  if (sortSelect) sortSelect.value = viewState.sortMode;

  const renderList = () => {
    viewState.strictOnly = Boolean(strictInput?.checked);
    viewState.availableOnly = Boolean(availableInput?.checked);
    viewState.sortMode = sortSelect?.value || "default";

    list.innerHTML = "";

    let visibleCandidates = [...candidates];
    if (viewState.strictOnly) {
      visibleCandidates = visibleCandidates.filter((candidate) => candidate.is_full_match === true);
    }
    if (viewState.availableOnly) {
      visibleCandidates = visibleCandidates.filter(isAvailableSoon);
    }

    if (viewState.sortMode === "score") {
      visibleCandidates.sort((a, b) => Number(b.match_score || 0) - Number(a.match_score || 0));
    }

    if (visibleCandidates.length === 0) {
      const empty = document.createElement("p");
      empty.className = "candidate-empty-note";
      empty.textContent = t("results.empty_filter");
      list.appendChild(empty);
      return;
    }

    visibleCandidates.forEach((candidate) => {
      list.appendChild(renderCandidateCard(candidate));
    });
  };

  toolbar.querySelectorAll("input, select").forEach((control) => {
    control.addEventListener("change", renderList);
  });

  renderList();
  wrapper.append(toolbar, list);
}

function renderCandidateCard(candidate) {
  const card = document.createElement("article");
  card.className = "candidate-card";

  const header = document.createElement("div");
  header.className = "candidate-card-header";

  const identity = document.createElement("div");
  const name = document.createElement("h3");
  name.textContent = candidate.full_name || t("candidate.no_name");

  const title = document.createElement("p");
  title.textContent = candidate.title || t("candidate.fallback_title");

  identity.append(name, title);
  header.append(identity, createMatchBadge(candidate.match_score));

  const meta = document.createElement("div");
  meta.className = "candidate-meta";
  meta.append(
    createMetaItem(t("candidate.meta.experience"), experienceDisplay(candidate)),
    createMetaItem(t("candidate.meta.location"), candidate.location || t("candidate.fallback_location")),
    createMetaItem(t("candidate.meta.contract"), formatList(candidate.contract_preferences)),
    createMetaItem(t("candidate.meta.availability"), candidate.availability || t("candidate.fallback_availability")),
  );

  const summary = document.createElement("p");
  summary.className = "candidate-summary";
  summary.textContent = candidate.summary || t("candidate.no_summary");

  const skills = renderSkillTags(candidate.skills, candidate.highlights);

  const actions = document.createElement("div");
  actions.className = "candidate-actions";

  const detailsBtn = document.createElement("button");
  detailsBtn.type = "button";
  detailsBtn.className = "candidate-btn secondary";
  detailsBtn.textContent = t("candidate.see_more");
  detailsBtn.setAttribute("aria-controls", "candidateDrawer");
  detailsBtn.setAttribute("aria-expanded", "false");
  detailsBtn.addEventListener("click", () => openCandidateDrawer(candidate));

  const boondBtn = document.createElement("button");
  boondBtn.type = "button";
  boondBtn.className = "candidate-btn primary";
  boondBtn.textContent = t("candidate.open_boond");
  boondBtn.disabled = !candidate.boond_url;
  boondBtn.addEventListener("click", () => openBoondManager(candidate.boond_url));

  if (FEATURES.candidate_drawer && CANDIDATE_CONFIG.show_candidate_drawer) {
    actions.appendChild(detailsBtn);
  }

  if (FEATURES.boond_redirect && candidate.boond_url) {
    actions.appendChild(boondBtn);
  }

  card.append(
    header,
    meta,
    renderHighlightTags(candidate.highlights),
    summary,
    renderAiEvaluation(candidate),
    skills,
    renderExperiences(candidate.experiences),
    renderCandidateInsights(candidate),
    actions,
  );

  return card;
}

function openCandidateDrawer(candidate) {
  if (!FEATURES.candidate_drawer || !CANDIDATE_CONFIG.show_candidate_drawer) return;

  state.currentDrawerCandidate = candidate;

  elements.drawerName.textContent = candidate.full_name || t("candidate.no_name");
  elements.drawerTitle.textContent = candidate.title || t("candidate.fallback_title");
  elements.drawerSummary.textContent = candidate.summary || t("candidate.no_summary");
  elements.drawerExperience.textContent = experienceDisplay(candidate);
  elements.drawerLocation.textContent = candidate.location || t("candidate.fallback_location");
  elements.drawerAvailability.textContent = candidate.availability || t("candidate.fallback_availability");
  elements.drawerMatch.textContent = formatMatchScore(candidate.match_score);
  elements.drawerSkills.innerHTML = "";
  elements.drawerSkills.append(...createSkillElements(candidate.skills, candidate.highlights));
  elements.drawerExtra.innerHTML = "";
  elements.drawerExtra.append(
    renderDrawerDetailList(candidate),
    renderDrawerSection(t("candidate.sections.ai_eval"), renderAiEvaluation(candidate)),
    renderDrawerSection(t("candidate.sections.experiences"), renderExperiences(candidate.experiences, 5)),
    renderDrawerSection(t("candidate.sections.technical"), renderTechnicalNotes(candidate)),
    renderDrawerSection(t("candidate.sections.keywords"), renderHighlightTags(candidate.highlights)),
  );
  elements.drawerBoondBtn.hidden = !FEATURES.boond_redirect || !candidate.boond_url;
  elements.drawerBoondBtn.disabled = !FEATURES.boond_redirect || !candidate.boond_url;

  // Remember what to restore focus to, then move focus into the drawer.
  state.drawerTrigger = document.activeElement;

  elements.drawerOverlay.hidden = false;
  elements.candidateDrawer.hidden = false;
  document.body.style.overflow = "hidden";
  elements.appShell.setAttribute("aria-hidden", "true");
  document
    .querySelectorAll('[aria-controls="candidateDrawer"]')
    .forEach((btn) => btn.setAttribute("aria-expanded", "true"));
  elements.candidateDrawer.addEventListener("keydown", trapDrawerFocus);

  requestAnimationFrame(() => {
    elements.drawerOverlay.classList.add("open");
    elements.candidateDrawer.classList.add("open");
    elements.drawerCloseBtn.focus();
  });
}

function trapDrawerFocus(event) {
  if (event.key !== "Tab") return;

  const focusables = elements.candidateDrawer.querySelectorAll(
    'button:not([hidden]):not([disabled]), [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
  );
  if (!focusables.length) return;

  const first = focusables[0];
  const last = focusables[focusables.length - 1];

  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
}

function closeCandidateDrawer() {
  if (!elements.candidateDrawer || !elements.drawerOverlay) return;

  const wasOpen = elements.candidateDrawer.classList.contains("open");

  state.currentDrawerCandidate = null;
  elements.drawerOverlay.classList.remove("open");
  elements.candidateDrawer.classList.remove("open");
  elements.drawerOverlay.hidden = true;
  elements.candidateDrawer.hidden = true;
  elements.candidateDrawer.removeEventListener("keydown", trapDrawerFocus);

  document.body.style.overflow = "";
  elements.appShell.removeAttribute("aria-hidden");
  document
    .querySelectorAll('[aria-controls="candidateDrawer"]')
    .forEach((btn) => btn.setAttribute("aria-expanded", "false"));

  // Return focus to the element that opened the drawer.
  if (wasOpen && state.drawerTrigger && typeof state.drawerTrigger.focus === "function") {
    state.drawerTrigger.focus();
  }
  state.drawerTrigger = null;
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

  const body = document.createElement("div");
  body.className = "msg-body loading-row";

  const spinner = document.createElement("span");
  spinner.className = "spinner";
  spinner.setAttribute("aria-hidden", "true");

  const text = document.createElement("span");
  text.textContent = t("loading.reflecting");

  body.append(spinner, text);
  message.append(buildMessageHead("assistant"), body);
  elements.messages.appendChild(message);
  setUiState("loading");

  return message;
}

function renderThinking() {
  const message = document.createElement("div");
  message.className = "message assistant";
  message.dataset.loading = "true";

  const body = document.createElement("div");
  body.className = "msg-body";

  const steps = document.createElement("ul");
  steps.className = "thinking-steps";
  steps.setAttribute("role", "status");
  steps.setAttribute("aria-live", "polite");

  body.append(steps);
  message.append(buildMessageHead("assistant"), body);
  elements.messages.appendChild(message);
  setUiState("loading");

  let currentStep = null;

  function completeStep(step) {
    if (!step) return;
    step.li.classList.remove("active");
    step.li.classList.add("done");
    step.icon.textContent = "✓";
  }

  return {
    element: message,
    addStep(text, detail) {
      if (!text) return;
      completeStep(currentStep);

      const li = document.createElement("li");
      li.className = "thinking-step active";

      const icon = document.createElement("span");
      icon.className = "step-icon";
      icon.setAttribute("aria-hidden", "true");

      const stepText = document.createElement("span");
      stepText.className = "step-text";
      stepText.textContent = text;

      li.append(icon, stepText);
      // Optional dynamic detail (the agent's actual reasoning) under the
      // localized step label — secondary, muted.
      if (detail) {
        const stepDetail = document.createElement("span");
        stepDetail.className = "step-detail";
        stepDetail.textContent = detail;
        li.append(stepDetail);
      }
      steps.appendChild(li);
      currentStep = { li, icon };
    },
    finish() {
      completeStep(currentStep);
      currentStep = null;
    },
    remove() {
      message.remove();
    },
  };
}

function clip(text, max = 160) {
  if (!text) return "";
  const flat = String(text).replace(/\s+/g, " ").trim();
  return flat.length > max ? `${flat.slice(0, max - 1)}…` : flat;
}

function planSearchReason(data) {
  const steps = Array.isArray(data?.plan) ? data.plan : [];
  const search = steps.find(
    (s) => (s?.tool_name || s?.tool) === "searchCandidates",
  );
  return clip(search?.reason);
}

function stepDescriptorForEvent(type, data) {
  const label = (key) => t(`stream.step_labels.${key}`);

  switch (type) {
    case "search_started":
      return { key: "start", label: label("start") };

    case "plan_created":
    case "replan_created":
      // Surface the LLM's actual search intent as a secondary detail line.
      return { key: "plan", label: label("plan"), detail: planSearchReason(data) };

    case "replan_requested":
      // The headline sync: the LLM's observe-then-replan decision, with its
      // reason. `decided_by` is "llm".
      return {
        key: "replan",
        label: label("replan"),
        detail: clip(data?.reason || data?.guidance),
      };

    case "plan_validated":
      return { key: "plan_validated", label: label("plan_validated") };

    case "tool_call_started": {
      const tool = String(data?.tool || "");
      if (tool === "searchCandidates") return { key: "searching", label: label("searching") };
      if (tool === "getCandidateTechnicalDocument") return { key: "reading_docs", label: label("reading_docs") };
      if (tool === "getCandidateDetail") return { key: "reading_details", label: label("reading_details") };
      return { key: "tool", label: label("tool") };
    }

    case "tool_call_completed": {
      const tool = String(data?.tool || "");
      const count = Number(data?.result_count);
      if (tool === "searchCandidates" && Number.isFinite(count) && count > 0) {
        return { key: "search_done", label: tCount("stream.step_labels.search_done", count, { count }) };
      }
      return null;
    }

    case "candidate_cards_partial":
      return { key: "ranking", label: label("ranking") };

    default:
      return null;
  }
}

async function runSearchStream(text, thinking) {
  let finalResponse = null;
  let failure = null;
  let round = 0;
  const shownSteps = new Set();

  await streamSearch(
    text,
    ({ type, data }) => {
      if (type === "search_started" && data?.conversation_id) {
        state.currentConversationId = data.conversation_id;
      }

      if (type === "final_response") {
        finalResponse = data;
        return;
      }

      if (type === "search_failed") {
        failure = data?.error || {};
        return;
      }

      // A replan opens a new round, so the second pass's steps show again
      // instead of being de-duped away (which made the bubble look frozen).
      if (type === "replan_requested") round += 1;

      const step = stepDescriptorForEvent(type, data);
      if (!step) return;
      const key = `${round}:${step.key}`;
      if (!shownSteps.has(key)) {
        shownSteps.add(key);
        thinking.addStep(step.label, step.detail);
      }
    },
    {
      signal: state.abortController.signal,
      conversationId: ensureSessionId(),
    },
  );

  return { finalResponse, failure };
}

async function send() {
  const text = elements.messageInput.value.trim();

  if (!text || state.isLoading) return;

  if (!isAuthenticated()) {
    showLogin(t("auth.errors.login_required_message"));
    return;
  }

  showInputError("");
  ensureSessionId();
  renderMessage("user", text);
  updateTitleFromMessage(text);
  resetInput();

  const thinking = renderThinking();
  state.abortController = new AbortController();
  setLoading(true);

  try {
    const { finalResponse, failure } = await runSearchStream(text, thinking);
    thinking.remove();

    if (failure) {
      renderMessage("error", failure.message || t("errors.generic"));
      return;
    }

    if (!finalResponse) {
      renderMessage("error", t("errors.incomplete_stream"));
      return;
    }

    if (finalResponse.conversation_id) {
      state.currentConversationId = finalResponse.conversation_id;
    }

    renderStreamFinalResponse(finalResponse);
    await loadConversationsSafely();
  } catch (error) {
    console.error(error);
    thinking.remove();

    if (!(error instanceof ApiError && error.type === "abort")) {
      renderMessage("error", getErrorMessage(error));
    }
  } finally {
    state.abortController = null;
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
  state.renderedResults = [];
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

function renderCandidateResultsToolbar(ui, candidates) {
  const toolbar = document.createElement("section");
  toolbar.className = "candidate-results-toolbar";

  const copy = document.createElement("div");
  copy.className = "candidate-results-copy";

  const title = document.createElement("h3");
  title.textContent = ui.title || tCount("results.count", candidates.length, { count: candidates.length });
  copy.appendChild(title);

  if (ui.subtitle) {
    const subtitle = document.createElement("p");
    subtitle.textContent = ui.subtitle;
    copy.appendChild(subtitle);
  }

  const filters = Array.isArray(ui.filters_summary) ? ui.filters_summary : [];
  if (filters.length) {
    const filterList = document.createElement("div");
    filterList.className = "result-filter-tags";
    filters.forEach((filter) => {
      const tag = document.createElement("span");
      tag.textContent = filter;
      filterList.appendChild(tag);
    });
    copy.appendChild(filterList);
  }

  const controls = document.createElement("div");
  controls.className = "candidate-result-controls";

  if (candidates.some((candidate) => typeof candidate.is_full_match === "boolean")) {
    const label = document.createElement("label");
    label.className = "availability-toggle";

    const input = document.createElement("input");
    input.type = "checkbox";
    input.dataset.strictOnly = "true";

    const text = document.createElement("span");
    text.textContent = t("results.strict_toggle");

    label.append(input, text);
    controls.appendChild(label);
  }

  if (candidates.some((candidate) => candidate.availability)) {
    const label = document.createElement("label");
    label.className = "availability-toggle";

    const input = document.createElement("input");
    input.type = "checkbox";
    input.dataset.availableOnly = "true";

    const text = document.createElement("span");
    text.textContent = t("results.available_toggle");

    label.append(input, text);
    controls.appendChild(label);
  }

  if (candidates.some((candidate) => candidate.match_score !== null && candidate.match_score !== undefined)) {
    const sort = document.createElement("select");
    sort.dataset.sort = "true";
    sort.setAttribute("aria-label", t("results.sort_aria"));

    const defaultOption = document.createElement("option");
    defaultOption.value = "default";
    defaultOption.textContent = t("results.sort_default");

    const scoreOption = document.createElement("option");
    scoreOption.value = "score";
    scoreOption.textContent = t("results.sort_score");

    sort.append(defaultOption, scoreOption);
    controls.appendChild(sort);
  }

  toolbar.append(copy, controls);
  return toolbar;
}

function renderHighlightTags(highlights) {
  const normalized = Array.isArray(highlights) ? highlights.filter(Boolean) : [];
  if (!normalized.length) return emptyFragment();

  const wrapper = document.createElement("div");
  wrapper.className = "highlight-tags";

  normalized.forEach((highlight) => {
    const tag = document.createElement("span");
    tag.textContent = highlight;
    wrapper.appendChild(tag);
  });

  return wrapper;
}

function renderAiEvaluation(candidate) {
  const evaluation = candidate?.ai_evaluation || candidate?.match_explanation;
  if (!evaluation || typeof evaluation !== "object") return emptyFragment();

  const wrapper = document.createElement("section");
  wrapper.className = "ai-evaluation";

  const heading = document.createElement("div");
  heading.className = "ai-evaluation-heading";

  const label = document.createElement("span");
  label.textContent = evaluation.label || t("candidate.sections.ai_eval");
  heading.appendChild(label);

  if (evaluation.score_label) {
    const score = document.createElement("strong");
    score.textContent = evaluation.score_label;
    heading.appendChild(score);
  }

  wrapper.appendChild(heading);

  const reasons = Array.isArray(evaluation.reasons) ? evaluation.reasons.filter(Boolean).slice(0, 4) : [];
  if (reasons.length) {
    const list = document.createElement("ul");
    reasons.forEach((reason) => {
      const item = document.createElement("li");
      item.textContent = reason;
      list.appendChild(item);
    });
    wrapper.appendChild(list);
  }

  return wrapper;
}

function renderExperiences(experiences, limit = 3) {
  const normalized = Array.isArray(experiences) ? experiences.filter(Boolean).slice(0, limit) : [];
  if (!normalized.length) return emptyFragment();

  const section = document.createElement("section");
  section.className = "candidate-experiences";

  const title = document.createElement("h4");
  title.textContent = t("candidate.sections.experiences");
  section.appendChild(title);

  const list = document.createElement("ul");
  normalized.forEach((experience) => {
    const item = document.createElement("li");

    const main = document.createElement("strong");
    main.textContent = [experience.title, experience.company].filter(Boolean).join(" · ") || t("candidate.sections.experience_item_fallback");
    item.appendChild(main);

    if (experience.period) {
      const period = document.createElement("span");
      period.textContent = experience.period;
      item.appendChild(period);
    }

    list.appendChild(item);
  });

  section.appendChild(list);
  return section;
}

function renderCandidateInsights(candidate) {
  const strengths = candidate?.strengths || candidate?.strong_points;
  const warnings = candidate?.watch_points || candidate?.weaknesses || candidate?.vigilance_points;
  const hasStrengths = Array.isArray(strengths) && strengths.length > 0;
  const hasWarnings = Array.isArray(warnings) && warnings.length > 0;
  if (!hasStrengths && !hasWarnings) return emptyFragment();

  const wrapper = document.createElement("div");
  wrapper.className = "candidate-insights";

  if (hasStrengths) {
    wrapper.appendChild(renderSummaryList(t("candidate.sections.strengths"), strengths.slice(0, 4)));
  }

  if (hasWarnings) {
    wrapper.appendChild(renderSummaryList(t("candidate.sections.watch_points"), warnings.slice(0, 4)));
  }

  return wrapper;
}

function renderDrawerDetailList(candidate) {
  const details = document.createElement("dl");
  details.className = "drawer-details";
  details.append(
    createMetaItem(t("candidate.meta.contract"), formatList(candidate.contract_preferences)),
    createMetaItem(t("candidate.meta.salary"), candidate.salary_expectation || t("candidate.not_specified")),
    createMetaItem(t("candidate.meta.tjm"), candidate.tjm || t("candidate.not_specified")),
    createMetaItem(t("candidate.meta.mobility"), candidate.mobility || t("candidate.not_specified_f")),
  );
  return details;
}

function renderTechnicalNotes(candidate) {
  if (candidate?.technical_summary && typeof candidate.technical_summary === "string") {
    const paragraph = document.createElement("p");
    paragraph.textContent = candidate.technical_summary;
    return paragraph;
  }

  return renderCandidateInsights(candidate);
}

function renderDrawerSection(title, content) {
  if (!content || !content.childNodes?.length) return emptyFragment();

  const section = document.createElement("section");
  section.className = "drawer-section";

  const heading = document.createElement("h3");
  heading.textContent = title;
  section.append(heading, content);
  return section;
}

function renderSummaryList(title, items) {
  const section = document.createElement("section");
  section.className = "technical-summary-section";

  const heading = document.createElement("h4");
  heading.textContent = title;
  section.appendChild(heading);

  const list = document.createElement("ul");
  const normalizedItems = Array.isArray(items) && items.length ? items : [t("candidate.not_specified")];

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
  return Array.isArray(items) && items.length ? items.join(", ") : t("candidate.not_specified");
}

function formatToolLevel(level) {
  const value = Number(level);
  if (Number.isNaN(value)) return t("candidate.tool_level_unknown");

  return `${value}/5`;
}

function renderSkillTags(skills, highlights = []) {
  const container = document.createElement("div");
  container.className = "candidate-skills";
  container.append(...createSkillElements(skills, highlights));
  return container;
}

function createSkillElements(skills, highlights = []) {
  const normalizedSkills = Array.isArray(skills) && skills.length
    ? skills.slice(0, CANDIDATE_CONFIG.max_visible_skills)
    : [t("candidate.skills_empty")];
  const highlightSet = new Set((Array.isArray(highlights) ? highlights : []).map((item) => String(item).toLowerCase()));

  return normalizedSkills.map((skill) => {
    const tag = document.createElement("span");
    tag.className = "skill-tag";
    tag.classList.toggle("highlight", highlightSet.has(String(skill).toLowerCase()));
    tag.textContent = skill;
    return tag;
  });
}

function isAvailableSoon(candidate) {
  const availability = String(candidate.availability || "").toLowerCase();
  if (!availability) return false;
  if (availability.includes("préavis") || availability.includes("preavis")) return false;
  return availability.includes("disponible") || availability.includes("immédiat") || availability.includes("immediat");
}

function emptyFragment() {
  return document.createDocumentFragment();
}

function formatExperience(years) {
  if (years === null || years === undefined || years === "") return t("candidate.not_specified_f");

  const value = Number(years);
  if (Number.isNaN(value)) return String(years);

  return tCount("candidate.years", value, { count: value });
}

// Experience display value: prefer the numeric years, otherwise fall back to
// the BoondManager experience-level band label (e.g. "10 à 15 ans"), which is
// often the only experience signal a profile carries.
function experienceDisplay(candidate) {
  const years = candidate.experience_years;
  if (years !== null && years !== undefined && years !== "") {
    return formatExperience(years);
  }
  const label = candidate.experience_label;
  if (typeof label === "string" && label.trim()) {
    return label.trim();
  }
  return t("candidate.not_specified_f");
}

function formatMatchScore(score) {
  if (score === null || score === undefined || score === "") return t("match.na");

  const value = Number(score);
  if (Number.isNaN(value)) return String(score);

  if (CANDIDATE_CONFIG.score_display !== "percentage") return String(value);

  return t("match.percent", { value: Math.round(value * 100) });
}

function truncateTitle(text) {
  return text.length > 42 ? `${text.slice(0, 42)}...` : text;
}

function normalizeRole(role) {
  return role === "user" ? "user" : "assistant";
}

function getRoleLabel(role) {
  if (role === "user") return t("app.user_label");
  if (role === "error") return t("roles.error");
  return t("app.assistant_label");
}

function getErrorMessage(error) {
  if (error instanceof ApiError) {
    if (error.type === "abort") return "";
    if (error.type === "network") return t("errors.network");
    if (error.type === "timeout") return t("errors.timeout");
    if (error.type === "malformed_response") return t("errors.malformed");
    if (error.type === "auth") return t("errors.auth_required");
    return t("errors.generic");
  }

  return t("errors.generic");
}

function getConversationLoadError(error) {
  if (error instanceof ApiError && error.type === "network") {
    return t("errors.backend_offline");
  }

  return t("errors.conversations_load");
}

