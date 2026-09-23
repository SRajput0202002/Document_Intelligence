import { LogLevel } from "@azure/msal-browser";

export const msalConfig = {
  auth: {
    clientId: process.env.NEXT_PUBLIC_AZURE_AD_CLIENT_ID || "",
    authority: `https://login.microsoftonline.com/${
      process.env.NEXT_PUBLIC_AZURE_AD_TENANT_ID || ""
    }`,
    redirectUri:
      process.env.NEXT_PUBLIC_WEB_URL ||
      (typeof window !== "undefined" ? window.location.origin : ""),
  },
  cache: {
    cacheLocation: "sessionStorage" as const,
    storeAuthStateInCookie: false,
  },
  system: {
    loggerOptions: {
      loggerCallback: (
        level: LogLevel,
        message: string,
        containsPii: boolean
      ) => {
        if (containsPii) return;
        if (level === LogLevel.Error) {
          console.error(message);
        }
      },
    },
  },
};

export const loginRequest = {
  scopes: ["User.Read"],
};

export const graphConfig = {
  graphMeEndpoint: "https://graph.microsoft.com/v1.0/me",
};

/** True when Entra SPA client/tenant IDs are configured for the frontend. */
export function isMicrosoftAuthConfigured(): boolean {
  return Boolean(
    process.env.NEXT_PUBLIC_AZURE_AD_CLIENT_ID &&
      process.env.NEXT_PUBLIC_AZURE_AD_TENANT_ID
  );
}
