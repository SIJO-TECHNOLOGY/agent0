import { DEV_MODE } from "./config.js";
import { loginRequest, msalConfig } from "./msalConfig.js";

// Empty identity: the UI falls back to the generic i18n labels
// (auth.default_user / app.user_label) instead of a personal name.
const DEV_USER = {
  name: "",
  username: "",
};

let activeAccount = null;
let publicClientApplication = null;

function getMsalClient() {
  if (DEV_MODE) return null;

  if (!window.msal) {
    throw new Error("MSAL.js n'est pas disponible.");
  }

  if (!publicClientApplication) {
    publicClientApplication = new window.msal.PublicClientApplication(msalConfig);
  }

  return publicClientApplication;
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

  const client = getMsalClient();
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

  await getMsalClient().loginRedirect(loginRequest);
  return null;
}

export function logout() {
  if (DEV_MODE) {
    setActiveAccount(DEV_USER);
    return Promise.resolve();
  }

  const account = getCurrentUser();
  return getMsalClient().logoutRedirect({ account });
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

  try {
    const response = await getMsalClient().acquireTokenSilent({
      ...loginRequest,
      account,
    });

    return response.accessToken;
  } catch (error) {
    if (error instanceof window.msal.InteractionRequiredAuthError) {
      await getMsalClient().acquireTokenRedirect(loginRequest);
      return null;
    }

    throw error;
  }
}
