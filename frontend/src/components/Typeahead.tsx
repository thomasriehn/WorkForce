import { type KeyboardEvent, type ReactNode, useEffect, useId, useRef, useState } from 'react';
import { errorMessage, isAbortError } from '../api/client';

export interface TypeaheadOption<T> {
  id: string;
  label: string;
  hint?: string;
  value: T;
  disabled?: boolean;
}

interface Props<T> {
  label: string;
  placeholder?: string;
  hint?: ReactNode;
  minChars?: number;
  /** Liefert Vorschläge zur Eingabe; das Signal bricht überholte Anfragen ab. */
  search: (term: string, signal: AbortSignal) => Promise<TypeaheadOption<T>[]>;
  onSelect: (option: TypeaheadOption<T>) => void;
  emptyText?: string;
  hideLabel?: boolean;
}

/** Eingabefeld mit Vorschlagsliste (ARIA-Combobox, per Tastatur bedienbar). */
export function Typeahead<T>({ label, placeholder, hint, minChars = 2, search, onSelect, emptyText = 'Keine Treffer', hideLabel }: Props<T>) {
  const inputId = useId();
  const listId = useId();
  const [term, setTerm] = useState('');
  const [open, setOpen] = useState(false);
  const [options, setOptions] = useState<TypeaheadOption<T>[]>([]);
  const [active, setActive] = useState(-1);
  const [status, setStatus] = useState<'idle' | 'loading' | 'done' | 'error'>('idle');
  const [error, setError] = useState('');
  const rootRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef(search);
  searchRef.current = search;

  useEffect(() => {
    const trimmed = term.trim();
    if (trimmed.length < minChars) {
      setOptions([]);
      setStatus('idle');
      return;
    }
    const controller = new AbortController();
    setStatus('loading');
    const timer = window.setTimeout(() => {
      searchRef
        .current(trimmed, controller.signal)
        .then((result) => {
          if (controller.signal.aborted) return;
          setOptions(result);
          setActive(result.findIndex((o) => !o.disabled));
          setStatus('done');
        })
        .catch((err: unknown) => {
          if (controller.signal.aborted || isAbortError(err)) return;
          setOptions([]);
          setError(errorMessage(err));
          setStatus('error');
        });
    }, 220);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [term, minChars]);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', onDown);
    return () => document.removeEventListener('mousedown', onDown);
  }, [open]);

  const choose = (option: TypeaheadOption<T>) => {
    if (option.disabled) return;
    onSelect(option);
    setTerm('');
    setOptions([]);
    setOpen(false);
    setStatus('idle');
  };

  const move = (dir: 1 | -1) => {
    if (!options.length) return;
    let i = active;
    for (let n = 0; n < options.length; n += 1) {
      i = (i + dir + options.length) % options.length;
      if (!options[i]?.disabled) break;
    }
    setActive(i);
  };

  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setOpen(true);
      move(1);
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      move(-1);
    } else if (e.key === 'Enter') {
      const option = options[active];
      if (open && option) {
        e.preventDefault();
        choose(option);
      }
    } else if (e.key === 'Escape') {
      if (open) {
        e.preventDefault();
        setOpen(false);
      }
    }
  };

  const showList = open && term.trim().length >= minChars;

  return (
    <div className="field typeahead" ref={rootRef}>
      <label className={hideLabel ? 'visually-hidden' : 'field__label'} htmlFor={inputId}>
        {label}
      </label>
      <input
        id={inputId}
        className="input"
        type="text"
        role="combobox"
        autoComplete="off"
        spellCheck={false}
        aria-expanded={showList}
        aria-controls={listId}
        aria-autocomplete="list"
        aria-activedescendant={showList && active >= 0 ? `${listId}-${active}` : undefined}
        placeholder={placeholder}
        value={term}
        onChange={(e) => {
          setTerm(e.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onKeyDown={onKeyDown}
      />
      {hint ? <p className="field__hint">{hint}</p> : null}
      <ul className="typeahead__list" id={listId} role="listbox" aria-label={label} hidden={!showList}>
        {status === 'loading' ? <li className="typeahead__info">Vorschläge werden geladen …</li> : null}
        {status === 'error' ? <li className="typeahead__info typeahead__info--error">{error}</li> : null}
        {status === 'done' && options.length === 0 ? <li className="typeahead__info">{emptyText}</li> : null}
        {status === 'done'
          ? options.map((o, i) => (
              <li
                key={o.id}
                id={`${listId}-${i}`}
                role="option"
                aria-selected={i === active}
                aria-disabled={o.disabled || undefined}
                className={`typeahead__option${i === active ? ' is-active' : ''}${o.disabled ? ' is-disabled' : ''}`}
                onMouseEnter={() => setActive(i)}
                onMouseDown={(e) => {
                  e.preventDefault();
                  choose(o);
                }}
              >
                <span>{o.label}</span>
                {o.hint ? <span className="typeahead__hint">{o.hint}</span> : null}
              </li>
            ))
          : null}
      </ul>
    </div>
  );
}
