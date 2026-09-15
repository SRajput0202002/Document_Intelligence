"use client";

import { AuthProvider as AuthProviderBase } from "@/hooks/use-auth";
import { ReactNode } from "react";

interface AuthProviderProps {
  children: ReactNode;
}

export function AuthProvider({ children }: AuthProviderProps) {
  return <AuthProviderBase>{children}</AuthProviderBase>;
}
