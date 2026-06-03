// Lightweight, framework-free i18n for UI chrome.
// - t(key, params) / tCount(key, count, params) resolve against the active
//   locale with a fallback chain: active -> default (fr) -> the key itself.
// - Language is detected from localStorage, then the browser, else French.
// - applyStaticTranslations() localizes static index.html elements tagged with
//   data-i18n / data-i18n-placeholder / data-i18n-aria.
import fr from "./locales/fr.js";
import en from "./locales/en.js";

const DICTS = { fr, en };

export const SUPPORTED_LANGS = ["fr", "en"];
export const DEFAULT_LANG = "fr";

const STORAGE_KEY = "sijo_lang";
const LOCALE_TAGS = { fr: "fr-FR", en: "en-US" };

const listeners = new Set();
let currentLang = DEFAULT_LANG;

function normalize(lang) {
  if (!lang) return null;
  const short = String(lang).toLowerCase().split("-")[0];
  return SUPPORTED_LANGS.includes(short) ? short : null;
}

export function detectLanguage() {
  let stored = null;
  try {
    stored = window.localStorage.getItem(STORAGE_KEY);
  } catch (error) {
    stored = null;
  }

  return (
    normalize(stored)
    || normalize(typeof navigator !== "undefined" ? navigator.language : null)
    || DEFAULT_LANG
  );
}

export function getLanguage() {
  return currentLang;
}

export function initLanguage() {
  currentLang = detectLanguage();
  document.documentElement.lang = currentLang;
  return currentLang;
}

export function setLanguage(lang) {
  const next = normalize(lang) || DEFAULT_LANG;
  currentLang = next;

  try {
    window.localStorage.setItem(STORAGE_KEY, next);
  } catch (error) {
    /* ignore persistence failures */
  }

  document.documentElement.lang = next;
  listeners.forEach((callback) => callback(next));
}

export function onLanguageChange(callback) {
  listeners.add(callback);
  return () => listeners.delete(callback);
}

function lookup(dict, path) {
  return path
    .split(".")
    .reduce((node, key) => (node && typeof node === "object" ? node[key] : undefined), dict);
}

function resolve(path) {
  const active = lookup(DICTS[currentLang], path);
  if (typeof active === "string") return active;

  const fallback = lookup(DICTS[DEFAULT_LANG], path);
  if (typeof fallback === "string") return fallback;

  return path;
}

function interpolate(template, params) {
  if (!params) return template;

  return template.replace(/\{(\w+)\}/g, (match, key) =>
    Object.prototype.hasOwnProperty.call(params, key) ? String(params[key]) : match,
  );
}

export function t(path, params) {
  return interpolate(resolve(path), params);
}

export function tCount(path, count, params = {}) {
  const suffix = Number(count) === 1 ? "_one" : "_other";
  return interpolate(resolve(`${path}${suffix}`), { count, ...params });
}

export function formatDate(value) {
  if (!value) return "";

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";

  const tag = LOCALE_TAGS[currentLang] || LOCALE_TAGS[DEFAULT_LANG];
  return new Intl.DateTimeFormat(tag, {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

export function applyStaticTranslations(root = document) {
  root.querySelectorAll("[data-i18n]").forEach((el) => {
    el.textContent = t(el.dataset.i18n);
  });

  root.querySelectorAll("[data-i18n-placeholder]").forEach((el) => {
    el.setAttribute("placeholder", t(el.dataset.i18nPlaceholder));
  });

  root.querySelectorAll("[data-i18n-aria]").forEach((el) => {
    el.setAttribute("aria-label", t(el.dataset.i18nAria));
  });
}
