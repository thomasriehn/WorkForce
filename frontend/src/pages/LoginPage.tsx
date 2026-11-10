import { type FormEvent, useId, useRef, useState } from 'react';
import { errorMessage } from '../api/client';
import { useAuth } from '../auth/AuthContext';
import { Alert, Button } from '../components/ui';

export function LoginPage() {
  const { login, notice } = useAuth();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const userId = useId();
  const passId = useId();
  const errorRef = useRef<HTMLDivElement>(null);

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    login(username.trim(), password)
      .catch((err: unknown) => {
        setError(errorMessage(err));
        setPassword('');
        window.setTimeout(() => errorRef.current?.focus(), 0);
      })
      .finally(() => setBusy(false));
  };

  return (
    <div className="login">
      <main className="login__card">
        <div className="login__brand">
          <span className="brand__mark" aria-hidden="true">
            W
          </span>
          <div>
            <h1 className="login__title">WorkForce</h1>
            <p className="login__claim">Stellenanzeigen als Hinweis auf Arbeitskräftebedarf</p>
          </div>
        </div>

        {notice && !error ? (
          <Alert tone="info" role="status" compact>
            {notice}
          </Alert>
        ) : null}
        <div ref={errorRef} tabIndex={-1} className="login__error">
          {error ? (
            <Alert tone="crit" title="Anmeldung nicht möglich" compact>
              {error}
            </Alert>
          ) : null}
        </div>

        <form className="login__form" onSubmit={onSubmit} noValidate={false}>
          <div className="field">
            <label className="field__label" htmlFor={userId}>
              Benutzername
            </label>
            <input id={userId} className="input" name="username" type="text" autoComplete="username" autoCapitalize="none" spellCheck={false} required autoFocus value={username} onChange={(e) => setUsername(e.target.value)} />
          </div>
          <div className="field">
            <label className="field__label" htmlFor={passId}>
              Passwort
            </label>
            <input id={passId} className="input" name="password" type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
          </div>
          <Button type="submit" variant="primary" busy={busy} className="login__submit">
            Anmelden
          </Button>
        </form>

        <p className="login__hint">Zugänge vergibt die Administration dieser Installation. Bei vergessenem Passwort setzt sie es zurück.</p>
      </main>
      <p className="login__footer">Selbst gehostete Beobachtung öffentlich ausgeschriebener Stellenanzeigen – keine amtliche Statistik.</p>
    </div>
  );
}
