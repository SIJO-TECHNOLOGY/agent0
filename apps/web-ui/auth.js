import { InteractionRequiredAuthError, PublicClientApplication } from "@azure/msal-browser";
import { DEV_MODE } from "./config.js";
import { loginRequest, msalConfig } from "./msalConfig.js";

// MSAL is bundled from npm (@azure/msal-browser): Microsoft retired the
// alcdn.msauth.net CDN, so the library must ship with the app. The v3+
// API requires an async initialize() before any other call — every
// entry point that talks to MSAL awaits ensureInitialized() first.
// getCurrentUser()/isAuthenticated() stay synchronous: the app always
// awaits handleRedirect() during startup, so by the time they run the
// client is initialized.

// Empty identity: the UI falls back to the generic i18n labels
// (auth.default_user / app.user_label) instead of a personal name.
const DEV_USER = {
  name: "",
  username: "",
};

let activeAccount = null;
let publicClientApplication = null;
let initializePromise = null;

function getMsalClient() {
  if (DEV_MODE) return null;

  if (!publicClientApplication) {
    publicClientApplication = new PublicClientApplication(msalConfig);
  }

  return publicClientApplication;
}

async function ensureInitialized() {
  const client = getMsalClient();

  if (!initializePromise) {
    initializePromise = client.initialize();
  }

  await initializePromise;
  return client;
}

function setActiveAccount(account) {
  activeAccount = account;

  if (account && !DEV_MODE) {
    getMsalClient().setActiveAccount(account);
  }
}

export async function handleRedirect() {
  if (DEV_MODE) {
    setActiveAccount(DEV_USER);
    return DEV_USER;
  }

  const client = await ensureInitialized();
  const response = await client.handleRedirectPromise();

  if (response?.account) {
    setActiveAccount(response.account);
    return response.account;
  }

  const accounts = client.getAllAccounts();
  if (accounts.length > 0) {
    setActiveAccount(accounts[0]);
    return accounts[0];
  }

  return null;
}

export async function login() {
  if (DEV_MODE) {
    setActiveAccount(DEV_USER);
    return DEV_USER;
  }

  const client = await ensureInitialized();
  await client.loginRedirect(loginRequest);
  return null;
}

export async function logout() {
  if (DEV_MODE) {
    setActiveAccount(DEV_USER);
    return;
  }

  const account = getCurrentUser();
  const client = await ensureInitialized();
  await client.logoutRedirect({ account });
}

export function getCurrentUser() {
  if (DEV_MODE) return DEV_USER;

  return activeAccount || getMsalClient().getActiveAccount();
}

export function isAuthenticated() {
  if (DEV_MODE) return true;

  return Boolean(getCurrentUser());
}

export async function getAccessToken() {
  if (DEV_MODE) return "dev-token";

  const account = getCurrentUser();

  if (!account) {
    throw new Error("Utilisateur non authentifié.");
  }

  const client = await ensureInitialized();

  try {
    const response = await client.acquireTokenSilent({
      ...loginRequest,
      account,
    });

    return response.accessToken;
  } catch (error) {
    if (error instanceof InteractionRequiredAuthError) {
      await client.acquireTokenRedirect(loginRequest);
      return null;
    }

    throw error;
  }
}
