import { createContext, type ReactNode, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { ApiError, api, clearApiCache, errorMessage, setCsrfToken, setUnauthorizedHandler } from '../api/client';
import type { SessionUser } from '../api/types';

type Status = 'checking' | 'anonymous' | 'authenticated' | 'unreachable';

interface AuthValue {
  status: Status;
  user: SessionUser | null;
  /** Nur Administratoren dürfen ändern; Leser sehen keine schreibenden Bedienelemente. */
  isAdmin: boolean;
  /** Hinweis für die Anmeldeseite, z. B. nach abgelaufener Sitzung. */
  notice: string | null;
  checkError: string | null;
  login: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  recheck: () => void;
}

const AuthContext = createContext<AuthValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<Status>('checking');
  const [user, setUser] = useState<SessionUser | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [checkError, setCheckError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  const adopt = useCallback((next: SessionUser) => {
    setCsrfToken(next.csrf_token);
    setUser(next);
    setNotice(null);
    setStatus('authenticated');
  }, []);

  const drop = useCallback((message: string | null) => {
    setCsrfToken(null);
    clearApiCache();
    setUser(null);
    setNotice(message);
    setStatus('anonymous');
  }, []);

  useEffect(() => {
    let active = true;
    setStatus('checking');
    api
      .get<SessionUser>('/api/auth/me', { quiet401: true })
      .then((me) => {
        if (active) adopt(me);
      })
      .catch((err: unknown) => {
        if (!active) return;
        if (err instanceof ApiError && err.status === 401) {
          drop(null);
        } else {
          setCheckError(errorMessage(err));
          setStatus('unreachable');
        }
      });
    return () => {
      active = false;
    };
  }, [adopt, drop, attempt]);

  useEffect(() => {
    setUnauthorizedHandler(() => drop('Ihre Sitzung ist abgelaufen. Bitte melden Sie sich erneut an.'));
    return () => setUnauthorizedHandler(null);
  }, [drop]);

  const login = useCallback(
    async (username: string, password: string) => {
      const me = await api.post<SessionUser>('/api/auth/login', { username, password }, { quiet401: true });
      clearApiCache();
      adopt(me);
    },
    [adopt],
  );

  const logout = useCallback(async () => {
    try {
      await api.post('/api/auth/logout', {}, { quiet401: true });
    } finally {
      drop('Sie wurden abgemeldet.');
    }
  }, [drop]);

  const recheck = useCallback(() => setAttempt((n) => n + 1), []);

  const value = useMemo<AuthValue>(
    () => ({ status, user, isAdmin: user?.role === 'admin', notice, checkError, login, logout, recheck }),
    [status, user, notice, checkError, login, logout, recheck],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth muss innerhalb von <AuthProvider> verwendet werden');
  return ctx;
}
