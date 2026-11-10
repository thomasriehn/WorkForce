import { type ReactNode, useEffect, useId, useRef } from 'react';
import { Icon } from './Icon';
import { Button } from './ui';

interface DialogProps {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
  /** `drawer` = seitlich einfahrendes Bedienfeld (z. B. Filter auf schmalen Bildschirmen). */
  variant?: 'modal' | 'drawer';
  size?: 'md' | 'lg';
}

/**
 * Auf dem nativen <dialog>-Element aufgebaut: Fokusfalle, Escape und Rückgabe des Fokus
 * übernimmt der Browser.
 */
export function Dialog({ open, onClose, title, children, footer, variant = 'modal', size = 'md' }: DialogProps) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (open && !el.open) el.showModal();
    if (!open && el.open) el.close();
  }, [open]);

  return (
    <dialog
      ref={ref}
      className={`dialog dialog--${variant} dialog--${size}`}
      aria-labelledby={titleId}
      onClose={onClose}
      onCancel={(e) => {
        e.preventDefault();
        onClose();
      }}
      onMouseDown={(e) => {
        if (e.target === ref.current) onClose(); // Klick auf den abgedunkelten Hintergrund
      }}
    >
      {open ? (
        <div className="dialog__panel">
          <header className="dialog__header">
            <h2 className="dialog__title" id={titleId}>
              {title}
            </h2>
            <button type="button" className="icon-btn" onClick={onClose} aria-label="Schließen">
              <Icon name="close" />
            </button>
          </header>
          <div className="dialog__body">{children}</div>
          {footer ? <footer className="dialog__footer">{footer}</footer> : null}
        </div>
      ) : null}
    </dialog>
  );
}

interface ConfirmProps {
  open: boolean;
  title: ReactNode;
  children: ReactNode;
  confirmLabel: string;
  danger?: boolean;
  busy?: boolean;
  error?: string | null;
  onConfirm: () => void;
  onClose: () => void;
}

export function ConfirmDialog({ open, title, children, confirmLabel, danger, busy, error, onConfirm, onClose }: ConfirmProps) {
  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={title}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            Abbrechen
          </Button>
          <Button variant={danger ? 'danger' : 'primary'} onClick={onConfirm} busy={busy}>
            {confirmLabel}
          </Button>
        </>
      }
    >
      {children}
      {error ? (
        <p className="form-error" role="alert">
          {error}
        </p>
      ) : null}
    </Dialog>
  );
}
