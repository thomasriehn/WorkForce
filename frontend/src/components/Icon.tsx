/** Kleine, lokal eingebettete Strichsymbole (keine Icon-Schrift, keine externen Anfragen). */

const PATHS = {
  dashboard: 'M4 4h7v9H4zM13 4h7v5h-7zM13 11h7v9h-7zM4 15h7v5H4z',
  search: 'M11 4a7 7 0 1 0 0 14a7 7 0 0 0 0-14zM20 20l-4-4',
  map: 'M9 4L3 6v14l6-2l6 2l6-2V4l-6 2zM9 4v14M15 6v14',
  region: 'M12 21s7-6.2 7-11a7 7 0 1 0-14 0c0 4.8 7 11 7 11zM12 12.5a2.5 2.5 0 1 0 0-5a2.5 2.5 0 0 0 0 5z',
  posting: 'M7 3h7l5 5v13H7zM14 3v5h5M10 13h6M10 17h6',
  sources: 'M4 6c0-1.7 3.6-3 8-3s8 1.3 8 3s-3.6 3-8 3s-8-1.3-8-3zM4 6v6c0 1.7 3.6 3 8 3s8-1.3 8-3V6M4 12v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6',
  book: 'M5 4h10a3 3 0 0 1 3 3v13H8a3 3 0 0 1-3-3zM5 17a3 3 0 0 1 3-3h10M9 8h5',
  menu: 'M4 7h16M4 12h16M4 17h16',
  close: 'M6 6l12 12M18 6L6 18',
  external: 'M14 4h6v6M20 4l-9 9M18 14v5H5V6h5',
  chevronDown: 'M6 9l6 6l6-6',
  chevronRight: 'M9 6l6 6l-6 6',
  chevronLeft: 'M15 6l-6 6l6 6',
  info: 'M12 3a9 9 0 1 0 0 18a9 9 0 0 0 0-18zM12 11v6M12 7.5v.5',
  help: 'M12 3a9 9 0 1 0 0 18a9 9 0 0 0 0-18zM9.5 9.5a2.5 2.5 0 1 1 3.5 2.3c-.7.4-1 1-1 1.7M12 17v.5',
  filter: 'M4 5h16l-6 7.5V19l-4-2v-4.5z',
  download: 'M12 4v11M7 11l5 5l5-5M5 20h14',
  check: 'M5 12.5l4.5 4.5L19 7.5',
  alert: 'M12 4l9 16H3zM12 10v4.5M12 17.5v.5',
  user: 'M12 12a4 4 0 1 0 0-8a4 4 0 0 0 0 8zM4.5 20a7.5 7.5 0 0 1 15 0',
  logout: 'M10 4H5v16h5M15 8l4 4l-4 4M19 12H9',
  save: 'M5 4h11l3 3v13H5zM8 4v5h7V4M8 20v-6h8v6',
  trash: 'M5 7h14M10 7V4h4v3M7 7l1 13h8l1-13M10 11v6M14 11v6',
  refresh: 'M19 6v5h-5M5 18v-5h5M18.5 11A7 7 0 0 0 6 8.5M5.5 13A7 7 0 0 0 18 15.5',
  play: 'M7 5l12 7l-12 7z',
  pause: 'M8 5v14M16 5v14',
  stop: 'M6 6h12v12H6z',
  plus: 'M12 5v14M5 12h14',
  clock: 'M12 3a9 9 0 1 0 0 18a9 9 0 0 0 0-18zM12 7v5l3.5 2',
  table: 'M4 5h16v14H4zM4 10h16M4 15h16M10 5v14',
  layers: 'M12 4l9 5l-9 5l-9-5zM3 14l9 5l9-5',
  dot: 'M12 9a3 3 0 1 0 0 6a3 3 0 0 0 0-6z',
  cross: 'M7 7l10 10M17 7L7 17',
  minus: 'M6 12h12',
  upload: 'M12 20V9M7 13l5-5l5 5M5 4h14',
  link: 'M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1',
  split: 'M12 3v6M12 9c0 4-6 4-6 9M12 9c0 4 6 4 6 9M4 18l2 2l2-2M16 18l2 2l2-2',
} as const;

export type IconName = keyof typeof PATHS;

interface Props {
  name: IconName;
  size?: number;
  className?: string;
  /** Nur setzen, wenn das Symbol allein Bedeutung trägt; sonst bleibt es für Vorleseprogramme verborgen. */
  title?: string;
}

export function Icon({ name, size = 18, className, title }: Props) {
  return (
    <svg
      className={className ? `icon ${className}` : 'icon'}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden={title ? undefined : true}
      role={title ? 'img' : undefined}
      focusable="false"
    >
      {title ? <title>{title}</title> : null}
      <path d={PATHS[name]} />
    </svg>
  );
}
