"use client";

import {
  createContext,
  useContext,
  useState,
  useEffect,
  useCallback,
  ReactNode,
} from "react";
import { useRouter, usePathname } from "next/navigation";
import { isMicrosoftAuthConfigured } from "@/lib/auth/azure-ad-config";
import {
  acquireMicrosoftAccessToken,
  clearAuthReturnTo,
  consumeAuthReturnTo,
  ensureMsalReady,
  formatAuthError,
  loginWithMicrosoftRedirect,
  logoutWithMicrosoftRedirect,
  msalInstance,
} from "@/lib/auth/msal";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8001";

// Types
export interface User {
  id: string;
  username: string;
  email?: string;
  display_name?: string;
  role: "admin" | "contributor" | "viewer";
  auth_provider?: "local" | "azure_ad" | string;
  is_active: boolean;
  created_at?: string;
  last_login_at?: string;
}

export interface AuthContextType {
  user: User | null;
  token: string | null;
  isLoading: boolean;
  isAuthenticated: boolean;
  setupRequired: boolean;
  microsoftAuthEnabled: boolean;
  login: (username: string, password: string) => Promise<void>;
  loginWithMicrosoft: () => Promise<void>;
  logout: () => Promise<void>;
  setupAdmin: (username: string, password: string, email?: string, displayName?: string) => Promise<void>;
  refreshAuth: () => Promise<void>;
  isAdmin: boolean;
  isContributor: boolean;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

// Storage keys
const TOKEN_KEY = "idp_auth_token";
const USER_KEY = "idp_auth_user";

interface AuthProviderProps {
  children: ReactNode;
}

export function AuthProvider({ children }: AuthProviderProps) {
  const [user, setUser] = useState<User | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [setupRequired, setSetupRequired] = useState(false);
  const microsoftAuthEnabled = isMicrosoftAuthConfigured();
  const router = useRouter();
  const pathname = usePathname();

  // Check if setup is required
  const checkSetupStatus = useCallback(async () => {
    try {
      console.log("[Auth] Checking setup status at:", `${API_BASE_URL}/api/auth/setup-status`);
      const response = await fetch(`${API_BASE_URL}/api/auth/setup-status`);
      console.log("[Auth] Setup status response:", response.status);
      if (response.ok) {
        const data = await response.json();
        console.log("[Auth] Setup required:", data.setup_required);
        setSetupRequired(data.setup_required);
        return data.setup_required;
      } else {
        console.error("[Auth] Setup status check failed:", response.status, response.statusText);
      }
    } catch (error) {
      console.error("[Auth] Failed to check setup status:", error);
    }
    return false;
  }, []);

  // Verify token and get user
  const verifyAuth = useCallback(async (storedToken: string) => {
    try {
      const response = await fetch(`${API_BASE_URL}/api/auth/check`, {
        headers: {
          Authorization: `Bearer ${storedToken}`,
        },
      });

      if (response.ok) {
        const data = await response.json();
        if (data.authenticated && data.user) {
          setUser(data.user);
          setToken(storedToken);
          localStorage.setItem(TOKEN_KEY, storedToken);
          localStorage.setItem(USER_KEY, JSON.stringify(data.user));
          return true;
        }
      }
    } catch (error) {
      console.error("Auth verification failed:", error);
    }

    // Clear invalid token
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
    setUser(null);
    setToken(null);
    return false;
  }, []);

  // Initialize auth state (local JWT restore + MSAL redirect handling)
  useEffect(() => {
    const initAuth = async () => {
      setIsLoading(true);

      try {
        const needsSetup = await checkSetupStatus();

        let microsoftHandled = false;

        if (microsoftAuthEnabled && !needsSetup) {
          try {
            const redirectResult = await ensureMsalReady();
            const justReturnedFromEntra = Boolean(redirectResult?.account);
            const account =
              redirectResult?.account ??
              msalInstance.getActiveAccount() ??
              msalInstance.getAllAccounts()[0] ??
              null;

            if (account) {
              msalInstance.setActiveAccount(account);
              const accessToken = await acquireMicrosoftAccessToken(account);
              if (accessToken) {
                const ok = await verifyAuth(accessToken);
                if (ok) {
                  microsoftHandled = true;
                  if (justReturnedFromEntra) {
                    router.replace(consumeAuthReturnTo("/"));
                  } else if (pathname === "/login" || pathname === "/setup") {
                    router.replace(consumeAuthReturnTo("/"));
                  }
                }
              }
            }
          } catch (error) {
            console.error("[Auth] MSAL init failed:", error);
            clearAuthReturnTo();
          }
        }

        if (!needsSetup && !microsoftHandled) {
          const storedToken = localStorage.getItem(TOKEN_KEY);
          if (storedToken) {
            await verifyAuth(storedToken);
          }
        }
      } catch (error) {
        console.error("Auth initialization failed:", error);
      } finally {
        setIsLoading(false);
      }
    };

    initAuth();
    // Intentionally run once on mount
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Login (local username/password)
  const login = useCallback(async (username: string, password: string) => {
    const response = await fetch(`${API_BASE_URL}/api/auth/login`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ username, password }),
    });

    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: "Login failed" }));
      throw new Error(error.detail || "Login failed");
    }

    const data = await response.json();

    localStorage.setItem(TOKEN_KEY, data.access_token);
    localStorage.setItem(USER_KEY, JSON.stringify(data.user));
    setToken(data.access_token);
    setUser(data.user);

    router.push("/");
  }, [router]);

  // Microsoft / Entra login (redirect)
  const loginWithMicrosoft = useCallback(async () => {
    if (!microsoftAuthEnabled) {
      throw new Error("Microsoft sign-in is not configured.");
    }
    try {
      const account = await loginWithMicrosoftRedirect("/");
      if (account) {
        const accessToken = await acquireMicrosoftAccessToken(account);
        if (!accessToken) {
          throw new Error("Could not acquire Microsoft access token.");
        }
        const ok = await verifyAuth(accessToken);
        if (!ok) {
          throw new Error("Microsoft token was rejected by the API.");
        }
        router.push(consumeAuthReturnTo("/"));
      }
      // If null, loginRedirect navigated away — nothing else to do
    } catch (error) {
      throw new Error(formatAuthError(error));
    }
  }, [microsoftAuthEnabled, router, verifyAuth]);

  // Setup admin
  const setupAdmin = useCallback(async (
    username: string,
    password: string,
    email?: string,
    displayName?: string
  ) => {
    const response = await fetch(`${API_BASE_URL}/api/auth/setup`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        username,
        password,
        email,
        display_name: displayName,
        role: "admin",
      }),
    });

    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: "Setup failed" }));
      throw new Error(error.detail || "Setup failed");
    }

    const data = await response.json();

    localStorage.setItem(TOKEN_KEY, data.access_token);
    localStorage.setItem(USER_KEY, JSON.stringify(data.user));
    setToken(data.access_token);
    setUser(data.user);
    setSetupRequired(false);

    router.push("/");
  }, [router]);

  // Logout
  const logout = useCallback(async () => {
    const hadMicrosoftAccount =
      microsoftAuthEnabled &&
      (msalInstance.getActiveAccount() || msalInstance.getAllAccounts().length > 0);

    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
    setToken(null);
    setUser(null);
    clearAuthReturnTo();

    if (hadMicrosoftAccount) {
      try {
        await ensureMsalReady();
        await logoutWithMicrosoftRedirect();
        return;
      } catch (error) {
        console.error("[Auth] Microsoft logout failed:", error);
      }
    }

    router.push("/login");
  }, [microsoftAuthEnabled, router]);

  // Refresh auth
  const refreshAuth = useCallback(async () => {
    const storedToken = localStorage.getItem(TOKEN_KEY);
    if (storedToken) {
      await verifyAuth(storedToken);
    }
  }, [verifyAuth]);

  const value: AuthContextType = {
    user,
    token,
    isLoading,
    isAuthenticated: !!user,
    setupRequired,
    microsoftAuthEnabled,
    login,
    loginWithMicrosoft,
    logout,
    setupAdmin,
    refreshAuth,
    isAdmin: user?.role === "admin",
    isContributor: user?.role === "contributor" || user?.role === "admin",
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
}

// Helper to get auth headers for API calls
export function getAuthHeaders(): HeadersInit {
  const token = localStorage.getItem(TOKEN_KEY);
  if (token) {
    return {
      Authorization: `Bearer ${token}`,
    };
  }
  return {};
}
