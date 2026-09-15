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

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8001";

// Types
export interface User {
  id: string;
  username: string;
  email?: string;
  display_name?: string;
  role: "admin" | "contributor" | "viewer";
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
  login: (username: string, password: string) => Promise<void>;
  logout: () => void;
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

  // Initialize auth state
  useEffect(() => {
    const initAuth = async () => {
      setIsLoading(true);

      try {
        // Check if setup is required
        const needsSetup = await checkSetupStatus();

        if (!needsSetup) {
          // Try to restore session from localStorage
          const storedToken = localStorage.getItem(TOKEN_KEY);
          if (storedToken) {
            await verifyAuth(storedToken);
          }
        }
      } catch (error) {
        console.error("Auth initialization failed:", error);
      } finally {
        // ALWAYS set loading to false, even on error
        setIsLoading(false);
      }
    };

    initAuth();
  }, [checkSetupStatus, verifyAuth]);

  // Login
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

    // Store token and user
    localStorage.setItem(TOKEN_KEY, data.access_token);
    localStorage.setItem(USER_KEY, JSON.stringify(data.user));
    setToken(data.access_token);
    setUser(data.user);

    // Redirect to home
    router.push("/");
  }, [router]);

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

    // Store token and user
    localStorage.setItem(TOKEN_KEY, data.access_token);
    localStorage.setItem(USER_KEY, JSON.stringify(data.user));
    setToken(data.access_token);
    setUser(data.user);
    setSetupRequired(false);

    // Redirect to home
    router.push("/");
  }, [router]);

  // Logout
  const logout = useCallback(() => {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
    setToken(null);
    setUser(null);
    router.push("/login");
  }, [router]);

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
    login,
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
