import { Component, type ErrorInfo, lazy, type ReactNode, Suspense, useEffect } from 'react';
import { Link, Route, Routes, useLocation } from 'react-router';
import { useAuth } from './auth/AuthContext';
import { AppShell } from './components/AppShell';
import { Button, EmptyState, ErrorState, LoadingState } from './components/ui';
import { LoginPage } from './pages/LoginPage';

// Jede Seite ist ein eigenes Paket: Karte (Leaflet) und Diagramme (Recharts) werden erst bei Bedarf geladen.
const DashboardPage = lazy(() => import('./pages/DashboardPage'));
const SearchPage = lazy(() => import('./pages/SearchPage'));
const MapPage = lazy(() => import('./pages/MapPage'));
const RegionsIndexPage = lazy(() => import('./pages/RegionsIndexPage'));
const RegionDetailPage = lazy(() => import('./pages/RegionDetailPage'));
const PostingsIndexPage = lazy(() => import('./pages/PostingsIndexPage'));
const PostingDetailPage = lazy(() => import('./pages/PostingDetailPage'));
const SourcesPage = lazy(() => import('./pages/SourcesPage'));
const SourceDetailPage = lazy(() => import('./pages/SourceDetailPage'));
const RunDetailPage = lazy(() => import('./pages/RunDetailPage'));
const MethodologyPage = lazy(() => import('./pages/MethodologyPage'));

const TITLES: [RegExp, string][] = [
  [/^\/$/, 'Dashboard'],
  [/^\/suche/, 'Stellensuche'],
  [/^\/karte/, 'Karte'],
  [/^\/regionen/, 'Regionen'],
  [/^\/anzeigen/, 'Anzeigen'],
  [/^\/quellen/, 'Quellenverwaltung'],
  [/^\/methodik/, 'Methodik und Quellen'],
];

function useDocumentTitle(authenticated: boolean) {
  const { pathname } = useLocation();
  useEffect(() => {
    const hit = authenticated ? TITLES.find(([re]) => re.test(pathname)) : undefined;
    document.title = hit ? `${hit[1]} – WorkForce` : authenticated ? 'WorkForce' : 'Anmeldung – WorkForce';
  }, [pathname, authenticated]);
}

interface BoundaryState {
  error: Error | null;
}

/** Fängt unerwartete Darstellungsfehler ab, damit nie eine leere Seite bleibt. */
class ErrorBoundary extends Component<{ children: ReactNode; resetKey: string }, BoundaryState> {
  override state: BoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): BoundaryState {
    return { error };
  }

  override componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('Darstellungsfehler', error, info.componentStack);
  }

  override componentDidUpdate(prev: { resetKey: string }) {
    if (prev.resetKey !== this.props.resetKey && this.state.error) this.setState({ error: null });
  }

  override render() {
    if (this.state.error) {
      return (
        <div className="page">
          <ErrorState title="Diese Ansicht konnte nicht dargestellt werden" error={this.state.error.message || 'Unerwarteter Fehler in der Oberfläche.'} onRetry={() => this.setState({ error: null })} />
        </div>
      );
    }
    return this.props.children;
  }
}

function NotFound() {
  return (
    <div className="page">
      <EmptyState title="Diese Seite gibt es nicht" action={<Link className="btn btn--primary" to="/">Zum Dashboard</Link>}>
        Die Adresse führt zu keinem Bereich von WorkForce. Möglicherweise wurde ein Link unvollständig kopiert.
      </EmptyState>
    </div>
  );
}

export function App() {
  const { status, checkError, recheck } = useAuth();
  const location = useLocation();
  useDocumentTitle(status === 'authenticated');

  if (status === 'checking') {
    return (
      <div className="boot">
        <LoadingState label="WorkForce wird geladen …" />
      </div>
    );
  }
  if (status === 'unreachable') {
    return (
      <div className="boot">
        <ErrorState title="WorkForce ist gerade nicht erreichbar" error={checkError ?? 'Der Server antwortet nicht.'} />
        <Button variant="primary" icon="refresh" onClick={recheck}>
          Erneut versuchen
        </Button>
      </div>
    );
  }
  if (status === 'anonymous') return <LoginPage />;

  return (
    <AppShell>
      <ErrorBoundary resetKey={location.pathname}>
        <Suspense fallback={<div className="page"><LoadingState label="Ansicht wird geladen …" /></div>}>
          <Routes>
            <Route path="/" element={<DashboardPage />} />
            <Route path="/suche" element={<SearchPage />} />
            <Route path="/karte" element={<MapPage />} />
            <Route path="/regionen" element={<RegionsIndexPage />} />
            <Route path="/regionen/:key" element={<RegionDetailPage />} />
            <Route path="/anzeigen" element={<PostingsIndexPage />} />
            <Route path="/anzeigen/:id" element={<PostingDetailPage />} />
            <Route path="/quellen" element={<SourcesPage tab="quellen" />} />
            <Route path="/quellen/laeufe" element={<SourcesPage tab="laeufe" />} />
            <Route path="/quellen/laeufe/:runId" element={<RunDetailPage />} />
            <Route path="/quellen/system" element={<SourcesPage tab="system" />} />
            <Route path="/quellen/:sourceId" element={<SourceDetailPage />} />
            <Route path="/methodik" element={<MethodologyPage />} />
            <Route path="*" element={<NotFound />} />
          </Routes>
        </Suspense>
      </ErrorBoundary>
    </AppShell>
  );
}
