import {
  BrowserAuthError,
  PublicClientApplication,
  type AccountInfo,
  type AuthenticationResult,
} from "@azure/msal-browser";
import { msalConfig, loginRequest } from "./azure-ad-config";

const AUTH_RETURN_TO_KEY = "idp_auth_return_to";

let _msalInstance: PublicClientApplication | null = null;
let msalReady: Promise<AuthenticationResult | null> | null = null;

/** Lazy client-only MSAL instance (avoids Next.js SSR window access). */
export function getMsalInstance(): PublicClientApplication {
  if (typeof window === "undefined") {
    throw new Error("MSAL is only available in the browser");
  }
  if (!_msalInstance) {
    _msalInstance = new PublicClientApplication(msalConfig);
  }
  return _msalInstance;
}

/** @deprecated Prefer getMsalInstance() — kept for call sites that expect a const. */
export const msalInstance = {
  getActiveAccount: () => getMsalInstance().getActiveAccount(),
  getAllAccounts: () => getMsalInstance().getAllAccounts(),
  setActiveAccount: (account: AccountInfo | null) =>
    getMsalInstance().setActiveAccount(account),
};

export function setAuthReturnTo(path: string): void {
  sessionStorage.setItem(AUTH_RETURN_TO_KEY, path);
}

export function peekAuthReturnTo(): string | null {
  return sessionStorage.getItem(AUTH_RETURN_TO_KEY);
}

export function clearAuthReturnTo(): void {
  sessionStorage.removeItem(AUTH_RETURN_TO_KEY);
}

export function consumeAuthReturnTo(defaultPath = "/extract"): string {
  const path = sessionStorage.getItem(AUTH_RETURN_TO_KEY) || defaultPath;
  sessionStorage.removeItem(AUTH_RETURN_TO_KEY);
  return path;
}

export async function ensureMsalReady(): Promise<AuthenticationResult | null> {
  if (!msalReady) {
    msalReady = (async () => {
      const instance = getMsalInstance();
      await instance.initialize();
      return (await instance.handleRedirectPromise()) ?? null;
    })();
  }
  return msalReady;
}

export function formatAuthError(error: unknown): string {
  const message =
    error instanceof BrowserAuthError
      ? error.errorMessage || error.message
      : error instanceof Error
        ? error.message
        : "";

  if (
    message.includes("interaction_in_progress") ||
    (error instanceof BrowserAuthError &&
      error.errorCode === "interaction_in_progress")
  ) {
    return "Sign-in is already in progress. Please wait a moment and try again.";
  }
  if (
    message.includes("user_cancelled") ||
    (error instanceof BrowserAuthError && error.errorCode === "user_cancelled")
  ) {
    return "Sign-in was cancelled.";
  }
  if (message) return message;
  return "Microsoft sign-in failed. Please try again.";
}

/** Redirect-based login (same tab — no popup loading the landing page). */
export async function loginWithMicrosoftRedirect(
  returnTo = "/extract"
): Promise<AccountInfo | null> {
  const instance = getMsalInstance();
  const redirectResult = await ensureMsalReady();

  if (redirectResult?.account) {
    instance.setActiveAccount(redirectResult.account);
    return redirectResult.account;
  }

  const existing = instance.getAllAccounts();
  if (existing.length > 0) {
    instance.setActiveAccount(existing[0]);
    return existing[0];
  }

  setAuthReturnTo(returnTo);
  await instance.loginRedirect({
    ...loginRequest,
    prompt: "select_account",
  });
  return null;
}

export async function logoutWithMicrosoftRedirect(): Promise<void> {
  const instance = getMsalInstance();
  await ensureMsalReady();
  const account =
    instance.getActiveAccount() ?? instance.getAllAccounts()[0];
  sessionStorage.removeItem(AUTH_RETURN_TO_KEY);
  await instance.logoutRedirect({
    account,
    postLogoutRedirectUri:
      process.env.NEXT_PUBLIC_WEB_URL || window.location.origin,
  });
}

export async function acquireMicrosoftAccessToken(
  account?: AccountInfo | null
): Promise<string | null> {
  const instance = getMsalInstance();
  await ensureMsalReady();
  const active =
    account ??
    instance.getActiveAccount() ??
    instance.getAllAccounts()[0] ??
    null;
  if (!active) return null;

  instance.setActiveAccount(active);
  const result = await instance.acquireTokenSilent({
    ...loginRequest,
    account: active,
  });
  return result.accessToken || null;
}
