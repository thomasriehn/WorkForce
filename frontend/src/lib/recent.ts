/** Zuletzt geöffnete Anzeigen – nur für die Dauer des Browser-Tabs (sessionStorage), nie auf dem Server. */
export interface RecentPosting {
  id: number;
  title: string;
  employer: string | null;
}

const KEY = 'wf.recentPostings';
const MAX = 12;

export function readRecent(): RecentPosting[] {
  try {
    const raw = window.sessionStorage.getItem(KEY);
    const parsed: unknown = raw ? JSON.parse(raw) : [];
    if (!Array.isArray(parsed)) return [];
    return parsed.filter((p): p is RecentPosting => Boolean(p) && typeof (p as RecentPosting).id === 'number' && typeof (p as RecentPosting).title === 'string');
  } catch {
    return [];
  }
}

export function rememberPosting(entry: RecentPosting): void {
  try {
    const next = [entry, ...readRecent().filter((p) => p.id !== entry.id)].slice(0, MAX);
    window.sessionStorage.setItem(KEY, JSON.stringify(next));
  } catch {
    // Speicher nicht verfügbar (z. B. privater Modus) – die Liste ist nur eine Bequemlichkeit.
  }
}
