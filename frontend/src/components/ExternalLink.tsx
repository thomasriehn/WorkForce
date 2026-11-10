import type { ReactNode } from 'react';
import { Icon } from './Icon';

/** Nur http(s)-Verweise werden zu Links – alles andere (javascript:, data: …) wird nie verlinkt. */
export function safeHttpUrl(url: string | null | undefined): string | null {
  if (!url) return null;
  const trimmed = url.trim();
  return /^https?:\/\//i.test(trimmed) ? trimmed : null;
}

interface Props {
  href: string | null | undefined;
  children: ReactNode;
  className?: string;
  /** Was angezeigt wird, wenn der Verweis fehlt oder nicht zulässig ist. */
  fallback?: ReactNode;
}

export function ExternalLink({ href, children, className, fallback = null }: Props) {
  const safe = safeHttpUrl(href);
  if (!safe) return <>{fallback}</>;
  return (
    <a className={className ? `ext-link ${className}` : 'ext-link'} href={safe} target="_blank" rel="noopener noreferrer">
      {children}
      <Icon name="external" size={14} />
      <span className="visually-hidden"> (öffnet in neuem Tab)</span>
    </a>
  );
}

export function hostOf(url: string | null | undefined): string | null {
  const safe = safeHttpUrl(url);
  if (!safe) return null;
  try {
    return new URL(safe).host;
  } catch {
    return null;
  }
}
