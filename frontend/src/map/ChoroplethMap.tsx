import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import markerIcon2x from 'leaflet/dist/images/marker-icon-2x.png';
import markerIcon from 'leaflet/dist/images/marker-icon.png';
import markerShadow from 'leaflet/dist/images/marker-shadow.png';
import { useEffect, useRef } from 'react';
import type { KreiseGeoJson, KreisProperties } from '../api/types';
import { MAP_SELECTED, NEWBASE_PATTERN_ID, NODATA_PATTERN_ID } from '../lib/viz';

export interface RegionStyle {
  fill: string;
  /** „keine Daten“ bzw. „Ausgangswert 0“ werden als Schraffur gezeichnet, nie als Farbe der Skala. */
  pattern: null | 'nodata' | 'newbase';
  lowCount: boolean;
}

export interface MapCenter {
  lat: number;
  lon: number;
  radiusKm: number;
  label: string;
}

// Leaflets Standardmarke aus dem eigenen Paket (gebündelt, keine externen Bilder).
const centerIcon = L.icon({
  iconUrl: markerIcon,
  iconRetinaUrl: markerIcon2x,
  shadowUrl: markerShadow,
  iconSize: [25, 41],
  iconAnchor: [12, 41],
  tooltipAnchor: [14, -26],
  shadowSize: [41, 41],
});

interface Props {
  geojson: KreiseGeoJson;
  /** Angenäherter Mittelpunkt und Radius einer Umkreissuche (falls gesetzt). */
  center?: MapCenter | null;
  styleOf: (key: string) => RegionStyle;
  selected: string[];
  onSelect: (key: string) => void;
  /** Baut den Inhalt des Tooltips als DOM-Knoten (nur textContent – nie HTML aus API-Texten). */
  tooltipFor: (key: string, props: KreisProperties) => HTMLElement;
  label: string;
}

const SVG_NS = 'http://www.w3.org/2000/svg';
const BORDER = '#8f9aab';

function ensurePatterns(map: L.Map): void {
  const svg = map.getPanes().overlayPane.querySelector('svg');
  if (!svg || svg.querySelector(`#${NODATA_PATTERN_ID}`)) return;
  const defs = document.createElementNS(SVG_NS, 'defs');
  const make = (id: string, angle: number, background: string, line: string) => {
    const pattern = document.createElementNS(SVG_NS, 'pattern');
    pattern.setAttribute('id', id);
    pattern.setAttribute('patternUnits', 'userSpaceOnUse');
    pattern.setAttribute('width', '7');
    pattern.setAttribute('height', '7');
    pattern.setAttribute('patternTransform', `rotate(${angle})`);
    const rect = document.createElementNS(SVG_NS, 'rect');
    rect.setAttribute('width', '7');
    rect.setAttribute('height', '7');
    rect.setAttribute('fill', background);
    const stroke = document.createElementNS(SVG_NS, 'line');
    stroke.setAttribute('x1', '0');
    stroke.setAttribute('y1', '0');
    stroke.setAttribute('x2', '0');
    stroke.setAttribute('y2', '7');
    stroke.setAttribute('stroke', line);
    stroke.setAttribute('stroke-width', '2.4');
    pattern.append(rect, stroke);
    defs.append(pattern);
  };
  make(NODATA_PATTERN_ID, 45, '#ffffff', '#b4bcc8');
  make(NEWBASE_PATTERN_ID, -45, '#fbe3e0', '#d9534f');
  svg.prepend(defs);
}

function pathStyle(style: RegionStyle, selected: boolean): L.PathOptions {
  const fillColor = style.pattern === 'nodata' ? `url(#${NODATA_PATTERN_ID})` : style.pattern === 'newbase' ? `url(#${NEWBASE_PATTERN_ID})` : style.fill;
  if (selected) return { fillColor, fillOpacity: 1, color: MAP_SELECTED, weight: 3.2, opacity: 1, dashArray: undefined };
  if (style.lowCount) return { fillColor, fillOpacity: 1, color: MAP_SELECTED, weight: 1.3, opacity: 0.9, dashArray: '3 3' };
  return { fillColor, fillOpacity: 1, color: BORDER, weight: 0.6, opacity: 0.9, dashArray: undefined };
}

/**
 * Kreiskarte ohne Hintergrundkacheln: gezeichnet werden nur die lokal ausgelieferten Kreisgrenzen.
 * Leaflet übernimmt Zoom, Verschieben und Tooltips; es werden keine externen Anfragen gestellt.
 */
export function ChoroplethMap({ geojson, styleOf, selected, onSelect, tooltipFor, label, center }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const layerRef = useRef<L.GeoJSON | null>(null);
  const mapRef = useRef<L.Map | null>(null);
  const latest = useRef({ styleOf, selected, onSelect, tooltipFor });
  latest.current = { styleOf, selected, onSelect, tooltipFor };

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const map = L.map(el, {
      attributionControl: false,
      zoomControl: true,
      zoomSnap: 0.25,
      zoomDelta: 0.5,
      minZoom: 4,
      maxZoom: 11,
      scrollWheelZoom: false,
      renderer: L.svg({ padding: 0.5 }),
    });
    map.zoomControl.setPosition('topright');
    // Mausrad zoomt erst, wenn die Karte den Fokus hat – so bleibt das Blättern der Seite ungestört.
    map.on('focus', () => map.scrollWheelZoom.enable());
    map.on('blur', () => map.scrollWheelZoom.disable());

    // Eigener Tooltip außerhalb des Kartenrahmens: Leaflets Tooltips würden am Kartenrand abgeschnitten.
    const tip = document.createElement('div');
    tip.className = 'map-tip';
    tip.setAttribute('role', 'tooltip');
    tip.hidden = true;
    document.body.append(tip);
    const placeTip = (e: L.LeafletMouseEvent) => {
      const { clientX, clientY } = e.originalEvent;
      const w = tip.offsetWidth;
      const h = tip.offsetHeight;
      let x = clientX + 18;
      if (x + w > window.innerWidth - 8) x = clientX - w - 18;
      let y = clientY + 18;
      if (y + h > window.innerHeight - 8) y = clientY - h - 18;
      tip.style.left = `${Math.max(8, x)}px`;
      tip.style.top = `${Math.max(8, y)}px`;
    };
    map.on('movestart zoomstart', () => {
      tip.hidden = true;
    });

    const keyOf = (l: L.Layer): string => ((l as L.Path & { feature?: GeoJSON.Feature }).feature?.properties as KreisProperties | undefined)?.key ?? '';

    const layer = L.geoJSON(geojson, {
      style: (feature) => {
        const key = (feature?.properties as KreisProperties | undefined)?.key ?? '';
        return pathStyle(latest.current.styleOf(key), latest.current.selected.includes(key));
      },
      onEachFeature: (feature, l) => {
        const props = feature.properties as KreisProperties;
        const path = l as L.Path;
        path.on('click', (e) => {
          if ((e.originalEvent as PointerEvent).pointerType === 'touch') tip.hidden = true; // Details stehen dann im Feld „Ausgewählter Kreis“
          latest.current.onSelect(props.key);
        });
        path.on('mouseover', (e) => {
          tip.replaceChildren(latest.current.tooltipFor(props.key, props));
          tip.hidden = false;
          placeTip(e);
          if (!latest.current.selected.includes(props.key)) path.setStyle({ weight: 2.2, color: MAP_SELECTED, dashArray: undefined });
          path.bringToFront();
        });
        path.on('mousemove', placeTip);
        path.on('mouseout', () => {
          tip.hidden = true;
          const key = keyOf(path);
          path.setStyle(pathStyle(latest.current.styleOf(key), latest.current.selected.includes(key)));
          layer.eachLayer((other) => {
            if (latest.current.selected.includes(keyOf(other))) (other as L.Path).bringToFront();
          });
        });
      },
    }).addTo(map);

    const bounds = layer.getBounds();
    if (bounds.isValid()) {
      map.fitBounds(bounds, { padding: [10, 10] });
      map.setMaxBounds(bounds.pad(0.6));
    }
    ensurePatterns(map);
    layerRef.current = layer;
    mapRef.current = map;

    const observer = new ResizeObserver(() => {
      map.invalidateSize();
    });
    observer.observe(el);

    return () => {
      observer.disconnect();
      tip.remove();
      layerRef.current = null;
      mapRef.current = null;
      map.remove();
    };
  }, [geojson]);

  // Farben und Hervorhebung nachführen, ohne die Karte neu aufzubauen (Ausschnitt und Zoom bleiben erhalten).
  useEffect(() => {
    const layer = layerRef.current;
    const map = mapRef.current;
    if (!layer || !map) return;
    ensurePatterns(map);
    const front: L.Path[] = [];
    layer.eachLayer((l) => {
      const path = l as L.Path & { feature?: GeoJSON.Feature };
      const key = (path.feature?.properties as KreisProperties | undefined)?.key ?? '';
      const isSelected = selected.includes(key);
      path.setStyle(pathStyle(styleOf(key), isSelected));
      if (isSelected) front.push(path);
    });
    for (const path of front) path.bringToFront();
  }, [styleOf, selected]);

  const centerKey = center ? `${center.lat}|${center.lon}|${center.radiusKm}|${center.label}` : '';
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !center) return;
    const group = L.layerGroup([
      L.circle([center.lat, center.lon], { radius: center.radiusKm * 1000, color: MAP_SELECTED, weight: 1.5, dashArray: '6 4', fill: false, interactive: false }),
      L.marker([center.lat, center.lon], { icon: centerIcon, keyboard: false, alt: center.label }).bindTooltip(center.label, { className: 'center-tip' }),
    ]).addTo(map);
    return () => {
      group.remove();
    };
    // centerKey fasst die Felder von `center` zusammen (das Objekt selbst wechselt bei jedem Rendern).
  }, [centerKey, geojson]);

  return <div ref={containerRef} className="map-canvas" role="application" aria-label={label} />;
}
