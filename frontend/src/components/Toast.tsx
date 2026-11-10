import { createContext, type ReactNode, useCallback, useContext, useMemo, useRef, useState } from 'react';
import { Icon } from './Icon';

interface Toast {
  id: number;
  tone: 'good' | 'crit' | 'info';
  message: string;
}

interface ToastApi {
  success: (message: string) => void;
  error: (message: string) => void;
  info: (message: string) => void;
}

const ToastContext = createContext<ToastApi | null>(null);

/** Kurze Rückmeldungen nach Aktionen (z. B. „Suche gespeichert“), für Vorleseprogramme als Live-Region. */
export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const nextId = useRef(1);

  const dismiss = useCallback((id: number) => setToasts((list) => list.filter((t) => t.id !== id)), []);

  const push = useCallback(
    (tone: Toast['tone'], message: string) => {
      const id = nextId.current++;
      setToasts((list) => [...list.slice(-3), { id, tone, message }]);
      window.setTimeout(() => dismiss(id), tone === 'crit' ? 9000 : 5000);
    },
    [dismiss],
  );

  const value = useMemo<ToastApi>(
    () => ({
      success: (m) => push('good', m),
      error: (m) => push('crit', m),
      info: (m) => push('info', m),
    }),
    [push],
  );

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className="toasts" role="status" aria-live="polite">
        {toasts.map((t) => (
          <div key={t.id} className={`toast toast--${t.tone}`}>
            <Icon name={t.tone === 'good' ? 'check' : t.tone === 'crit' ? 'alert' : 'info'} size={18} />
            <span className="toast__text">{t.message}</span>
            <button type="button" className="icon-btn icon-btn--sm" onClick={() => dismiss(t.id)} aria-label="Meldung schließen">
              <Icon name="close" size={14} />
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastApi {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error('useToast muss innerhalb von <ToastProvider> verwendet werden');
  return ctx;
}
