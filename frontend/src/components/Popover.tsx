import { type ReactNode, useEffect, useId, useRef, useState } from 'react';
import { Icon, type IconName } from './Icon';

interface Props {
  label: string;
  icon?: IconName;
  children: ReactNode;
  /** Text neben dem Symbol; ohne Text erscheint nur das Symbol (mit zugänglichem Namen). */
  text?: string;
  align?: 'left' | 'right';
}

/** Kleines aufklappbares Hinweisfeld (z. B. Hilfe zur Suchsyntax). Schließt bei Escape und Klick außerhalb. */
export function Popover({ label, icon = 'help', children, text, align = 'left' }: Props) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLSpanElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const panelId = useId();

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setOpen(false);
        buttonRef.current?.focus();
      }
    };
    document.addEventListener('mousedown', onDown);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDown);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  return (
    <span className="popover" ref={rootRef}>
      <button
        ref={buttonRef}
        type="button"
        className={text ? 'btn btn--ghost btn--sm' : 'icon-btn'}
        aria-expanded={open}
        aria-controls={panelId}
        aria-label={text ? undefined : label}
        title={text ? undefined : label}
        onClick={() => setOpen((o) => !o)}
      >
        <Icon name={icon} size={18} />
        {text}
      </button>
      {open ? (
        <div
          className={`popover__panel popover__panel--${align}`}
          id={panelId}
          role="region"
          aria-label={label}
          onClick={(e) => {
            if ((e.target as HTMLElement).closest('a')) setOpen(false); // Verweis gewählt: Feld schließen
          }}
        >
          {children}
        </div>
      ) : null}
    </span>
  );
}
