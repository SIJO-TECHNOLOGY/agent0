// Microsoft Entra ID (MSAL) configuration.
//
// Values come from Vite env vars so no tenant-specific id is committed:
//   VITE_ENTRA_CLIENT_ID  — Application (client) ID of the app registration
//   VITE_ENTRA_TENANT_ID  — Directory (tenant) ID
//   VITE_REDIRECT_URI     — optional, defaults to the current origin
//
// The app registration must be single-tenant ("Accounts in this
// organizational directory only") so only SIJO accounts can sign in,
// and must expose the API scope `access_as_user` (Expose an API) so the
// issued access token is addressed to the Agent API, not Microsoft
// Graph. The Agent API rejects Graph tokens.
const ENV = import.meta.env ?? {};

export const clientId = ENV.VITE_ENTRA_CLIENT_ID ?? "TO_BE_CONFIGURED";
export const tenantId = ENV.VITE_ENTRA_TENANT_ID ?? "TO_BE_CONFIGURED";
export const redirectUri =
  ENV.VITE_REDIRECT_URI ??
  (typeof window !== "undefined"
    ? window.location.origin
    : "http://localhost:5500");

export const msalConfig = {
  auth: {
    clientId,
    authority: `https://login.microsoftonline.com/${tenantId}`,
    redirectUri,
    postLogoutRedirectUri: redirectUri,
  },
  cache: {
    cacheLocation: "sessionStorage",
    storeAuthStateInCookie: false,
  },
};

export const loginRequest = {
  scopes: [`api://${clientId}/access_as_user`],
};
