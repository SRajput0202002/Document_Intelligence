"use client";

import { useState, useEffect } from "react";
import { GaugeCircle, Loader2, AlertCircle, Info } from "lucide-react";
import { useAuth } from "@/hooks/use-auth";
import { LOGIN_FLASH_SESSION_KEY } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { LockIcon } from "@/components/ui/lock";
import { UserIcon } from "@/components/ui/user";

export default function LoginPage() {
  const { login, isLoading } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [sessionMessage, setSessionMessage] = useState<string | null>(null);

  useEffect(() => {
    const PASSWORD_CHANGED_FALLBACK =
      "Your session ended because your password was changed. Please sign in again.";
    try {
      const flash = sessionStorage.getItem(LOGIN_FLASH_SESSION_KEY);
      if (flash) {
        sessionStorage.removeItem(LOGIN_FLASH_SESSION_KEY);
        setSessionMessage(flash);
        return;
      }
      const params = new URLSearchParams(window.location.search);
      if (params.get("reason") === "password_changed") {
        setSessionMessage(PASSWORD_CHANGED_FALLBACK);
      }
    } catch {
      /* private mode */
    }
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setSubmitting(true);

    try {
      await login(username, password);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed");
    } finally {
      setSubmitting(false);
    }
  };

  if (isLoading) {
    return (
      <div className="flex h-screen items-center justify-center bg-background">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-background p-4">
      <div className="w-full max-w-md space-y-6">
        <div className="flex flex-col items-center space-y-2">
          <div className="flex items-center gap-3">
            <div className="w-12 h-12 rounded-xl bg-primary flex items-center justify-center relative app-icon-container">
              <GaugeCircle className="w-6 h-6 text-primary-foreground animate-spin-slow" />
            </div>
            <div>
              <h1 className="text-2xl font-bold">IDP Platform</h1>
              <p className="text-sm text-muted-foreground">Intelligent Document Processing</p>
            </div>
          </div>
        </div>

        <Card>
          <CardHeader className="space-y-1">
            <CardTitle className="text-xl flex items-center gap-2">
              <LockIcon size={20} />
              Sign In
            </CardTitle>
            <CardDescription>
              Enter your credentials to access the platform
            </CardDescription>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleSubmit} className="space-y-4">
              {sessionMessage && (
                <div
                  className="flex items-start gap-2 p-3 text-sm rounded-lg border border-amber-500/40 bg-amber-500/10 text-amber-950 dark:text-amber-100 dark:border-amber-400/30"
                  role="status"
                >
                  <Info className="h-4 w-4 flex-shrink-0 mt-0.5 text-amber-700 dark:text-amber-300" />
                  <span>{sessionMessage}</span>
                </div>
              )}
              {error && (
                <div className="flex items-center gap-2 p-3 text-sm text-destructive bg-destructive/10 rounded-lg border border-destructive/20">
                  <AlertCircle className="h-4 w-4 flex-shrink-0" />
                  <span>{error}</span>
                </div>
              )}

              <div className="space-y-2">
                <Label htmlFor="username" className="text-sm flex items-center gap-1.5">
                  <UserIcon size={14} />
                  Username
                </Label>
                <Input
                  id="username"
                  type="text"
                  placeholder="Enter your username"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  disabled={submitting}
                  required
                  autoComplete="username"
                  autoFocus
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="password" className="text-sm flex items-center gap-1.5">
                  <LockIcon size={14} />
                  Password
                </Label>
                <Input
                  id="password"
                  type="password"
                  placeholder="Enter your password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  disabled={submitting}
                  required
                  autoComplete="current-password"
                />
              </div>

              <Button
                type="submit"
                className="w-full"
                disabled={submitting || !username || !password}
              >
                {submitting ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    Signing in...
                  </>
                ) : (
                  "Sign In"
                )}
              </Button>
            </form>
          </CardContent>
        </Card>

        <p className="text-center text-xs text-muted-foreground">
          Contact your administrator if you need an account
        </p>
      </div>
    </div>
  );
}
