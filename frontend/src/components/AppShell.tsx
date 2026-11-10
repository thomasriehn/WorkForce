import { type ReactNode, useEffect, useState } from 'react';
import { Link, NavLink, useLocation } from 'react-router';
import { useAuth } from '../auth/AuthContext';
import { Icon, type IconName } from './Icon';

interface NavItem {
  to: string;
  label: string;
  icon: IconName;
  end?: boolean;
}

/** Die sieben Bereiche der Anwendung. */
const NAV: NavItem[] = [
  { to: '/', label: 'Dashboard', icon: 'dashboard', end: true },
  { to: '/suche', label: 'Stellensuche', icon: 'search' },
  { to: '/karte', label: 'Karte', icon: 'map' },
  { to: '/regionen', label: 'Regionen', icon: 'region' },
  { to: '/anzeigen', label: 'Anzeigen', icon: 'posting' },
  { to: '/quellen', label: 'Quellenverwaltung', icon: 'sources' },
  { to: '/methodik', label: 'Methodik und Quellen', icon: 'book' },
];

export function AppShell({ children }: { children: ReactNode }) {
  const { user, isAdmin, logout } = useAuth();
  const location = useLocation();
  const [navOpen, setNavOpen] = useState(false);
  const [loggingOut, setLoggingOut] = useState(false);

  // Navigation auf schmalen Bildschirmen nach einem Seitenwechsel wieder einklappen.
  useEffect(() => setNavOpen(false), [location.pathname]);

  useEffect(() => {
    if (!navOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setNavOpen(false);
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [navOpen]);

  return (
    <div className={navOpen ? 'app app--nav-open' : 'app'}>
      <a className="skip-link" href="#inhalt">
        Zum Inhalt springen
      </a>
      <header className="topbar">
        <button type="button" className="icon-btn topbar__menu" aria-label={navOpen ? 'Navigation schließen' : 'Navigation öffnen'} aria-expanded={navOpen} aria-controls="hauptnavigation" onClick={() => setNavOpen((o) => !o)}>
          <Icon name={navOpen ? 'close' : 'menu'} size={22} />
        </button>
        <Link to="/" className="brand" aria-label="WorkForce – zum Dashboard">
          <span className="brand__mark" aria-hidden="true">
            W
          </span>
          <span className="brand__name">WorkForce</span>
        </Link>
        <p className="topbar__claim">Stellenanzeigen als Hinweis auf Arbeitskräftebedarf</p>
        <div className="topbar__user">
          <Icon name="user" size={18} />
          <span className="topbar__username">{user?.username}</span>
          <span className={isAdmin ? 'role role--admin' : 'role'} title={isAdmin ? 'Darf Einstellungen und Daten ändern' : 'Nur lesender Zugriff'}>
            {isAdmin ? 'Administration' : 'Lesezugriff'}
          </span>
          <button
            type="button"
            className="btn btn--ghost btn--sm"
            disabled={loggingOut}
            onClick={() => {
              setLoggingOut(true);
              void logout().finally(() => setLoggingOut(false));
            }}
          >
            <Icon name="logout" size={16} />
            Abmelden
          </button>
        </div>
      </header>

      <nav className="sidebar" id="hauptnavigation" aria-label="Hauptnavigation">
        <ul className="nav">
          {NAV.map((item) => (
            <li key={item.to}>
              <NavLink to={item.to} end={item.end} className={({ isActive }) => (isActive ? 'nav__item is-active' : 'nav__item')}>
                <Icon name={item.icon} size={20} />
                <span>{item.label}</span>
              </NavLink>
            </li>
          ))}
        </ul>
        <p className="sidebar__note">
          Gezählt werden beobachtete Anzeigen der aufgeführten Quellen – keine offenen Stellen und keine Vollerhebung des Stellenmarkts.
        </p>
      </nav>
      <div className="sidebar-backdrop" onClick={() => setNavOpen(false)} aria-hidden="true" />

      <main className="main" id="inhalt" tabIndex={-1}>
        {children}
      </main>
    </div>
  );
}
