import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import { api } from "./api";

interface AuthContextValue {
  /** null = 尚未加载完成 */
  authenticated: boolean | null;
  refresh: () => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [authenticated, setAuthenticated] = useState<boolean | null>(null);

  const refresh = useCallback(async () => {
    try {
      const data = await api<{ authenticated: boolean }>("/me");
      setAuthenticated(data.authenticated);
    } catch {
      setAuthenticated(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const logout = useCallback(async () => {
    try {
      await api("/logout", { method: "POST" });
    } catch {
      // 忽略登出失败
    }
    setAuthenticated(false);
  }, []);

  return (
    <AuthContext.Provider value={{ authenticated, refresh, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth 必须在 AuthProvider 内使用");
  }
  return ctx;
}
