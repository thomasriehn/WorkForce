"""Synthetische Entwicklungsdaten für die Oberfläche – ausschließlich für die Datenbank ``wf_front_dev``.

Nicht Teil des Builds. Erzeugt frei erfundene Kreise (einfache Polygone), Ortsreferenz, einige KldB-Klassen,
Kontextstatistik und – über die echte Erfassungspipeline mit einem Fake-Adapter (kein Netzwerk) – einige
Dutzend frei erfundene Anzeigen samt Historie. Alles ist als „synthetisch“ benannt.

Aufruf (aus dem Verzeichnis ``backend``):

    WF_DATABASE_URL=postgresql+psycopg://workforce:devpass@127.0.0.1:55432/wf_front_dev \
    WF_ENV=development WF_CRAWLER_CONTACT=https://example.invalid/kontakt \
    uv run python ../frontend/scripts/seed_synthetic.py            # anlegen
    … seed_synthetic.py --reset                                    # löschen und neu anlegen
    … seed_synthetic.py --purge                                    # nur löschen (leere Zustände prüfen)
"""
from __future__ import annotations

import hashlib
import os
import random
import sys
from datetime import date, timedelta
from decimal import Decimal

sys.path.insert(0, os.getcwd())

from sqlalchemy import text as sql  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402

ALLOWED_DB = "wf_front_dev"
url = make_url(os.environ.get("WF_DATABASE_URL", ""))
if url.database != ALLOWED_DB:
    sys.exit(f"Abbruch: Dieses Skript schreibt nur in die Datenbank {ALLOWED_DB!r} (gesetzt: {url.database!r}).")
os.environ.setdefault("WF_CRAWLER_CONTACT", "https://example.invalid/kontakt")
os.environ.setdefault("WF_ENV", "development")
os.environ.setdefault("WF_LOG_LEVEL", "WARNING")

from tests.helpers import FakeAdapter, posting, run_scan  # noqa: E402
from workforce import db as wf_db  # noqa: E402
from workforce.crawl.fetcher import BlockedError  # noqa: E402
from workforce.models import SearchScope, Source  # noqa: E402
from workforce.normalize.text import fold, normalize_title  # noqa: E402
from workforce.pipeline import aggregate  # noqa: E402
from workforce.pipeline.run import local_today  # noqa: E402
from workforce.sources.base import RawLocation  # noqa: E402

RNG = random.Random(20261110)
STAND = date(2026, 1, 1)
NOTE = "Synthetische Testgeometrie für die Oberflächenentwicklung – keine amtlichen Grenzen"

DATA_TABLES = [
    "posting_event", "observation", "posting_scope", "activity_period", "merge_link", "merge_candidate", "merge_block", "posting_feature",
    "posting_location", "scan_error", "scan_task", "daily_aggregate", "timeline_note", "ops_warning", "job", "stat_value", "stat_release",
    "stat_indicator", "stat_dataset", "region", "geo_place", "postal_code", "occupation_title", "kldb_class", "employer",
]

STATES = [("98", "Musterland Nord (synthetisch)"), ("99", "Musterland Süd (synthetisch)")]
# (Schlüssel, Name, Art, Ort, PLZ, Einwohner des Ortes)
DISTRICTS = [
    ("98001", "Musterstadt-Nord", "Kreisfreie Stadt", "Nordmusterstadt", "98101", 410_000),
    ("98002", "Beispielkreis Aue", "Landkreis", "Auenbeispiel", "98201", 38_000),
    ("98003", "Testkreis Birkenhöhe", "Landkreis", "Birkentest", "98301", 22_000),
    ("98004", "Probekreis Elbtal", "Landkreis", "Elbprobe", "98401", 61_000),
    ("98005", "Musterkreis Fichtenau", "Landkreis", "Fichtenmuster", "98501", 17_500),
    ("98006", "Beispielstadt-West", "Kreisfreie Stadt", "Westbeispielstadt", "98601", 205_000),
    ("99001", "Musterstadt-Süd", "Kreisfreie Stadt", "Südmusterstadt", "99101", 530_000),
    ("99002", "Testkreis Hügelland", "Landkreis", "Hügeltest", "99201", 29_000),
    ("99003", "Beispielkreis Isarwinkel", "Landkreis", "Isarbeispiel", "99301", 44_000),
    ("99004", "Probekreis Jurahöhe", "Landkreis", "Juraprobe", "99401", 12_800),
    ("99005", "Musterkreis Kiefernwald", "Landkreis", "Kiefernmuster", "99501", 26_300),
    ("99006", "Testkreis Lechfeld", "Landkreis", "Lechtest", "99601", 73_000),
]

KLDB = [
    ("4", 1, "Naturwissenschaft, Geografie und Informatik"), ("43", 2, "Informatik-, Informations- und Kommunikationstechnologieberufe"),
    ("434", 3, "Softwareentwicklung und Programmierung"), ("4341", 4, "Berufe in der Softwareentwicklung"), ("43414", 5, "Berufe in der Softwareentwicklung – Experte"),
    ("7", 1, "Unternehmensorganisation, Buchhaltung, Recht und Verwaltung"), ("73", 2, "Berufe in Recht und Verwaltung"),
    ("732", 3, "Verwaltung"), ("7320", 4, "Berufe in der öffentlichen Verwaltung"), ("73202", 5, "Berufe in der öffentlichen Verwaltung – Fachkraft"),
    ("73203", 5, "Berufe in der öffentlichen Verwaltung – Spezialist"),
    ("8", 1, "Gesundheit, Soziales, Lehre und Erziehung"), ("81", 2, "Medizinische Gesundheitsberufe"), ("813", 3, "Gesundheits- und Krankenpflege, Rettungsdienst und Geburtshilfe"),
    ("8130", 4, "Berufe in der Gesundheits- und Krankenpflege"), ("81302", 5, "Berufe in der Gesundheits- und Krankenpflege – Fachkraft"),
    ("83", 2, "Erziehung, soziale und hauswirtschaftliche Berufe, Theologie"), ("831", 3, "Erziehung, Sozialarbeit, Heilerziehungspflege"),
    ("8311", 4, "Berufe in der Kinderbetreuung und -erziehung"), ("83112", 5, "Berufe in der Kinderbetreuung und -erziehung – Fachkraft"),
    ("3", 1, "Bau, Architektur, Vermessung und Gebäudetechnik"), ("31", 2, "Bauplanungs-, Architektur- und Vermessungsberufe"),
    ("311", 3, "Bauplanung und -überwachung, Architektur"), ("3110", 4, "Berufe in der Bauplanung und -überwachung"), ("31104", 5, "Berufe in der Bauplanung und -überwachung – Experte"),
]
TITLES = [
    ("Softwareentwickler", "43414"), ("Softwareentwicklerin", "43414"), ("Verwaltungsfachangestellter", "73202"), ("Verwaltungsfachangestellte", "73202"),
    ("Sachbearbeiter", "73202"), ("Sachbearbeiterin", "73202"), ("Verwaltungsfachwirt", "73203"), ("Pflegefachkraft", "81302"), ("Pflegefachfrau", "81302"),
    ("Pflegefachmann", "81302"), ("Gesundheits- und Krankenpfleger", "81302"), ("Erzieher", "83112"), ("Erzieherin", "83112"), ("Bauingenieur", "31104"),
    ("Bauingenieurin", "31104"),
]

EMPLOYERS = [
    "Stadtverwaltung Nordmusterstadt (synthetisch)", "Kreisverwaltung Auenbeispiel (synthetisch)", "Musterklinikum Süd gGmbH (synthetisch)",
    "Beispiel Software GmbH (synthetisch)", "Landesamt für Testwesen (synthetisch)", "Kita-Zweckverband Hügeltest (synthetisch)",
]
# (Titel, Art, Beschreibung für die regelbasierte Merkmalserkennung, Arbeitgeberindex)
TEMPLATES = [
    ("Sachbearbeiter (m/w/d) Bürgerservice", None, "Sie verfügen über eine abgeschlossene Berufsausbildung als Verwaltungsfachangestellte. Berufserfahrung ist von Vorteil. Führerschein Klasse B erforderlich.", 0),
    ("Verwaltungsfachwirt (m/w/d) Finanzen", None, "Voraussetzung ist der Abschluss als Verwaltungsfachwirt oder der Angestelltenlehrgang II. Mehrjährige Berufserfahrung wird vorausgesetzt. Gute Deutschkenntnisse in Wort und Schrift.", 1),
    ("Softwareentwickler (m/w/d) Fachverfahren", None, "Abgeschlossenes Studium der Informatik (Bachelor) oder vergleichbar. Sehr gute Kenntnisse in Python und SQL erforderlich. Englischkenntnisse sind wünschenswert. Keine Berufserfahrung erforderlich.", 3),
    ("Pflegefachkraft (m/w/d) Intensivstation", None, "Abgeschlossene Ausbildung als Pflegefachfrau oder Pflegefachmann. Berufserfahrung in der Intensivpflege erwünscht. Bereitschaft zu Schichtdienst.", 2),
    ("Erzieher (m/w/d) Kindertagesstätte", None, "Staatlich anerkannte Erzieherin oder Erzieher. Erweitertes Führungszeugnis erforderlich. Deutschkenntnisse auf Niveau C1.", 5),
    ("Bauingenieur (m/w/d) Tiefbau", None, "Abgeschlossenes Hochschulstudium (Master) im Bauingenieurwesen. Führerschein Klasse B erforderlich. Kenntnisse in AutoCAD von Vorteil.", 4),
    ("Referent (m/w/d) Digitalisierung", None, "Wissenschaftlicher Hochschulabschluss (Master). Erfahrung im Projektmanagement. Sehr gute Englischkenntnisse.", 4),
    ("Ausbildung Verwaltungsfachangestellte (m/w/d) 2027", "ausbildung", "Mittlerer Schulabschluss. Gute Deutschkenntnisse.", 0),
    ("Duales Studium Public Management (B.A.)", "duales_studium", "Allgemeine Hochschulreife oder Fachhochschulreife.", 1),
    ("Praktikum Softwareentwicklung (m/w/d)", "praktikum", "Laufendes Studium der Informatik. Kenntnisse in Python wünschenswert.", 3),
]


def reset(db) -> None:
    db.execute(sql("UPDATE merged_posting SET primary_source_posting_id = NULL, current_version_id = NULL"))
    db.execute(sql("UPDATE source_posting SET current_version_id = NULL, merged_posting_id = NULL"))
    db.execute(sql("TRUNCATE " + ", ".join(DATA_TABLES) + ", posting_version, source_posting, merged_posting, scan_run RESTART IDENTITY CASCADE"))
    db.execute(sql("DELETE FROM search_scope WHERE source_id IN (SELECT id FROM source WHERE key LIKE 'synth_%')"))
    db.execute(sql("DELETE FROM source WHERE key LIKE 'synth_%'"))
    db.commit()


def grid() -> dict[str, tuple[str, float, float]]:
    """4 × 3 Zellen mit leicht versetzten gemeinsamen Eckpunkten (lückenlos, ohne Überlappung)."""
    cols, rows = 4, 3
    lon0, lon1, lat0, lat1 = 7.4, 12.6, 48.6, 52.8
    vx: dict[tuple[int, int], tuple[float, float]] = {}
    for i in range(cols + 1):
        for j in range(rows + 1):
            jx = RNG.uniform(-0.28, 0.28) if 0 < i < cols else RNG.uniform(-0.08, 0.08)
            jy = RNG.uniform(-0.22, 0.22) if 0 < j < rows else RNG.uniform(-0.06, 0.06)
            vx[(i, j)] = (lon0 + (lon1 - lon0) * i / cols + jx, lat0 + (lat1 - lat0) * j / rows + jy)
    # Reihenfolge: Nord (98…) oben, Süd (99…) unten
    cells = [(i, j) for j in (2, 1, 0) for i in range(cols)]
    out: dict[str, tuple[str, float, float]] = {}
    for (key, *_), (i, j) in zip(DISTRICTS, cells, strict=True):
        ring = [vx[(i, j)], vx[(i + 1, j)], vx[(i + 1, j + 1)], vx[(i, j + 1)], vx[(i, j)]]
        wkt = "MULTIPOLYGON(((" + ", ".join(f"{x:.5f} {y:.5f}" for x, y in ring) + ")))"
        cx = sum(p[0] for p in ring[:4]) / 4
        cy = sum(p[1] for p in ring[:4]) / 4
        out[key] = (wkt, cx, cy)
    return out


def seed_reference(db) -> None:
    for key, name in STATES:
        db.execute(sql("INSERT INTO region (country, level, key, name, type_label, gebietsstand, is_current, source_note) VALUES ('DE','state',:k,:n,'Land',:g,true,:s)"),
                   {"k": key, "n": name, "g": STAND, "s": NOTE})
    cells = grid()
    for key, name, typ, town, plz, pop in DISTRICTS:
        wkt, cx, cy = cells[key]
        db.execute(sql(
            "INSERT INTO region (country, level, key, name, type_label, parent_key, gebietsstand, is_current, geom, geom_simple, centroid, area_km2, source_note) "
            "VALUES ('DE','district',:k,:n,:t,:p,:g,true, ST_GeomFromText(:w,4326), ST_GeomFromText(:w,4326), ST_Centroid(ST_GeomFromText(:w,4326)), "
            "ST_Area(ST_GeomFromText(:w,4326)::geography)/1e6, :s)"), {"k": key, "n": name, "t": typ, "p": key[:2], "g": STAND, "w": wkt, "s": NOTE})
        db.execute(sql(
            "INSERT INTO geo_place (country, name, name_norm, kind, ags, kreis_key, state_key, postal_code, population, lat, lon, gebietsstand, source_note) "
            "VALUES ('DE',:n,:nn,'municipality',:a,:k,:st,:plz,:pop,:lat,:lon,:g,:s)"),
            {"n": town, "nn": fold(town), "a": key + "000", "k": key, "st": key[:2], "plz": plz, "pop": pop, "lat": round(cy, 5), "lon": round(cx, 5), "g": STAND, "s": NOTE})
        db.execute(sql("INSERT INTO postal_code (country, plz, ags, kreis_key, place_name, source_note) VALUES ('DE',:p,:a,:k,:n,:s)"),
                   {"p": plz, "a": key + "000", "k": key, "n": town, "s": NOTE})
    for code, level, name in KLDB:
        db.execute(sql("INSERT INTO kldb_class (code, level, name, version) VALUES (:c,:l,:n,'KldB 2010/2020 Auszug')"), {"c": code, "l": level, "n": name})
    for title, code in TITLES:
        db.execute(sql("INSERT INTO occupation_title (title, title_norm, kldb_code, origin) VALUES (:t,:n,:c,'synonym_local') ON CONFLICT DO NOTHING"),
                   {"t": title, "n": normalize_title(title), "c": code})
    db.commit()


def seed_stats(db, today: date) -> None:
    db.execute(sql(
        "INSERT INTO stat_dataset (key, name, publisher, dataset_code, landing_url, licence, licence_url, attribution, update_cycle, notes) VALUES "
        "('synth_bevoelkerung','Bevölkerung nach Altersgruppen (synthetisch)','Testamt für Statistik (synthetisch)','SYN-12411','https://example.invalid/bevoelkerung',"
        "'Datenlizenz Deutschland – Namensnennung – Version 2.0','https://www.govdata.de/dl-de/by-2-0','© Testamt für Statistik (synthetisch), frei erfundene Werte','yearly',NULL),"
        "('synth_arbeitsmarkt','Arbeitsmarkt nach Kreisen (synthetisch)','Testagentur für Arbeit (synthetisch)','SYN-AM-KREIS','https://example.invalid/arbeitsmarkt',"
        "'Nutzung mit Quellenangabe',NULL,'Quelle: Testagentur für Arbeit (synthetisch), frei erfundene Werte','monthly',NULL)"))
    db.execute(sql(
        "INSERT INTO stat_indicator (key, name, definition, unit, population_group, dataset_key) VALUES "
        "('bev_15_bis_unter_65','Bevölkerung 15 bis unter 65 Jahre','Einwohnerinnen und Einwohner im Alter von 15 bis unter 65 Jahren am Stichtag.','Personen','Wohnbevölkerung','synth_bevoelkerung'),"
        "('bev_gesamt','Bevölkerung insgesamt','Einwohnerinnen und Einwohner am Stichtag.','Personen','Wohnbevölkerung','synth_bevoelkerung'),"
        "('arbeitslose','Arbeitslose (Bestand)','Registrierte Arbeitslose im Berichtsmonat.','Personen','registrierte Arbeitslose (SGB II und III)','synth_arbeitsmarkt'),"
        "('arbeitsuchende','Arbeitsuchende (Bestand)','Gemeldete Arbeitsuchende im Berichtsmonat – eine andere, größere Gruppe als die Arbeitslosen.','Personen','gemeldete Arbeitsuchende','synth_arbeitsmarkt'),"
        "('arbeitslosenquote','Arbeitslosenquote','Arbeitslose bezogen auf alle zivilen Erwerbspersonen.','Prozent','zivile Erwerbspersonen','synth_arbeitsmarkt')"))

    def release(dataset: str, period_key: str, start: date | None, end: date, revision: int, current: bool, published: date | None, method: str) -> int:
        return db.execute(sql(
            "INSERT INTO stat_release (dataset_key, period_key, period_start, period_end, revision, is_current, published_on, file_name, file_sha256, gebietsstand, import_method, row_count, notes) "
            "VALUES (:d,:pk,:ps,:pe,:r,:c,:pub,:fn,:sha,:g,:m,0,'Synthetischer Datenstand für die Oberflächenentwicklung') RETURNING id"),
            {"sha": hashlib.sha256(f"{dataset}|{period_key}|{revision}".encode()).hexdigest(), "d": dataset, "pk": period_key, "ps": start, "pe": end, "r": revision, "c": current, "pub": published, "fn": f"{dataset}_{period_key}_r{revision}.csv", "g": STAND, "m": method}).scalar_one()

    def value(rel: int, ind: str, level: str, key: str, val: float | None, status: str = "ok", raw: str | None = None) -> None:
        db.execute(sql("INSERT INTO stat_value (release_id, indicator_key, region_level, region_key, value, value_status, raw_value, gebietsstand) VALUES (:r,:i,:l,:k,:v,:s,:raw,:g)"),
                   {"r": rel, "i": ind, "l": level, "k": key, "v": val, "s": status, "raw": raw, "g": STAND})

    pop_rel = release("synth_bevoelkerung", "2025-12-31", None, date(2025, 12, 31), 1, True, date(2026, 6, 20), "auto")
    pops: dict[str, int] = {}
    for key, _name, _typ, _town, _plz, pop in DISTRICTS:
        total = int(pop * RNG.uniform(1.3, 2.2))
        pops[key] = int(total * RNG.uniform(0.60, 0.66))
        if key == "99004":  # unterdrückter Wert: bleibt Fehlwert, nie 0
            value(pop_rel, "bev_15_bis_unter_65", "district", key, None, "suppressed", ".")
        elif key == "98005":  # gar kein Wert geliefert
            pass
        else:
            value(pop_rel, "bev_15_bis_unter_65", "district", key, pops[key])
        value(pop_rel, "bev_gesamt", "district", key, total)
    for st, _ in STATES:
        value(pop_rel, "bev_15_bis_unter_65", "state", st, sum(v for k, v in pops.items() if k.startswith(st)))

    month_end = (today.replace(day=1) - timedelta(days=1))
    prev_end = (month_end.replace(day=1) - timedelta(days=1))
    rels = [
        release("synth_arbeitsmarkt", prev_end.strftime("%Y-%m"), prev_end.replace(day=1), prev_end, 1, True, prev_end + timedelta(days=3), "auto"),
        release("synth_arbeitsmarkt", month_end.strftime("%Y-%m"), month_end.replace(day=1), month_end, 1, False, month_end + timedelta(days=2), "auto"),
        release("synth_arbeitsmarkt", month_end.strftime("%Y-%m"), month_end.replace(day=1), month_end, 2, True, None, "manual"),
    ]
    for n, rel in enumerate(rels):
        for key, *_ in DISTRICTS:
            alo = int(pops[key] * RNG.uniform(0.025, 0.07)) + n * 13
            if key == "98003" and n == 2:
                value(rel, "arbeitslose", "district", key, None, "suppressed", "*")
            elif key == "99005":
                value(rel, "arbeitslose", "district", key, 0, "zero", "0")
            else:
                value(rel, "arbeitslose", "district", key, alo)
            value(rel, "arbeitsuchende", "district", key, int(alo * RNG.uniform(1.6, 2.1)))
            value(rel, "arbeitslosenquote", "district", key, round(RNG.uniform(2.4, 9.8), 1))
        for st, _ in STATES:
            value(rel, "arbeitslose", "state", st, int(sum(v for k, v in pops.items() if k.startswith(st)) * 0.05))
            value(rel, "arbeitsuchende", "state", st, int(sum(v for k, v in pops.items() if k.startswith(st)) * 0.09))
    db.execute(sql("UPDATE stat_release r SET row_count = (SELECT count(*) FROM stat_value v WHERE v.release_id = r.id)"))
    db.commit()


def make_source(db, key: str, name: str, segment: str) -> SearchScope:
    src = Source(key=key, name=name, domain=f"{key.replace('_', '-')}.example.invalid", entry_url=f"https://{key.replace('_', '-')}.example.invalid/",
                 segment=segment, allowed_domains=[f"{key.replace('_', '-')}.example.invalid"], config_status="active", access_method="html_list_jsonld",
                 status_reason="Synthetische Testquelle – wird nie über das Netz abgerufen.", legal_notes="Frei erfundene Quelle für die Entwicklung der Oberfläche.",
                 attribution="Synthetische Testdaten", request_interval_seconds=0, max_pages_per_run=50, max_details_per_run=0)
    db.add(src)
    db.flush()
    scope = SearchScope(source_id=src.id, key="alle", version=1, name="Alle Anzeigen (synthetisch)", params={}, mode="full", is_active=True)
    db.add(scope)
    db.commit()
    return scope


class Pool:
    """Verwaltet die frei erfundenen Anzeigen einer Testquelle über die Tage."""

    def __init__(self, prefix: str, domain: str):
        self.prefix, self.domain, self.n, self.items = prefix, domain, 0, {}

    def new(self, day: date, *, shared_ref: str | None = None, template: int | None = None):
        self.n += 1
        t = TEMPLATES[template if template is not None else RNG.randrange(len(TEMPLATES))]
        title, kind, desc, emp = t
        key = f"{self.prefix}{self.n:04d}"
        towns = [d for d in DISTRICTS]
        # Großstädte bekommen mehr Anzeigen – so entstehen sichtbare Schwerpunkte
        weights = [max(1.0, d[5] / 30_000) for d in towns]
        k = RNG.choices([1, 1, 1, 1, 2, 3], k=1)[0]
        chosen = []
        while len(chosen) < k:
            d = RNG.choices(towns, weights=weights, k=1)[0]
            if d not in chosen:
                chosen.append(d)
        locs = [RawLocation(locality=d[3], postal_code=d[4], country="DE", raw=f"{d[4]} {d[3]}") for d in chosen]
        roll = RNG.random()
        remote = None
        if roll < 0.06:
            locs = [RawLocation(locality="bundesweit", country="DE", raw="bundesweit (remote)")]
            remote = "remote"
        elif roll < 0.12:
            locs.append(RawLocation(locality="Unbekanntenhausen an der Nirgend", country="DE", raw="Unbekanntenhausen an der Nirgend"))
        elif roll < 0.16:
            locs = [RawLocation(locality="Unbekanntenhausen an der Nirgend", country="DE", raw="Unbekanntenhausen")]
        elif roll < 0.19:
            locs = [RawLocation(locality="Wien", country="AT", raw="Wien, Österreich")]
        elif roll < 0.22:
            locs = []
        elif roll < 0.40:
            remote = "hybrid"
        elif roll < 0.75:
            remote = "onsite"
        kw = {}
        if remote:
            kw["remote_type"] = remote
        if kind:
            kw["kind"] = kind
        wt = RNG.choice([["vollzeit"], ["vollzeit"], ["teilzeit"], ["vollzeit", "teilzeit"], []])
        if wt:
            kw["working_time"] = wt
        ct = RNG.choice(["unbefristet", "unbefristet", "befristet", None])
        if ct:
            kw["contract_term"] = ct
        sal = RNG.random()
        if sal < 0.25:
            kw.update(salary_min=Decimal("3200"), salary_max=Decimal("4100"), salary_currency="EUR", salary_period="MONTH", salary_origin="employer", salary_text="EG 9b TVöD")
        elif sal < 0.35:
            kw.update(salary_min=Decimal("41000"), salary_max=Decimal("52000"), salary_currency="EUR", salary_period="YEAR", salary_origin="portal_estimate")
        elif sal < 0.45:
            kw.update(salary_text="A 11 LBesG", salary_origin="employer")
        if RNG.random() < 0.6:
            kw["date_posted"] = day - timedelta(days=RNG.randrange(0, 9))
        if RNG.random() < 0.5:
            kw["apply_until"] = day + timedelta(days=RNG.randrange(10, 40))
        p = posting(key, title=title, employer=EMPLOYERS[emp], place=None, description=desc, reference=shared_ref or f"{self.prefix.upper()}-{2026}-{self.n:04d}",
                    domain=self.domain, **kw)
        p.locations = locs
        p.raw_payload = {**p.raw_payload, "locs": [loc.raw for loc in locs]}
        self.items[key] = p
        return p

    def pages(self, size: int = 20):
        vals = list(self.items.values())
        return [vals[i:i + size] for i in range(0, len(vals), size)] or [[]]


def seed_postings(db, today: date) -> None:
    alpha = make_source(db, "synth_alpha", "Testportal Alpha (synthetisch)", "Öffentlicher Dienst – frei erfundene Anzeigen")
    beta = make_source(db, "synth_beta", "Testportal Beta (synthetisch)", "Allgemeiner Stellenmarkt – frei erfundene Anzeigen")
    a, b = Pool("a", "synth-alpha.example.invalid"), Pool("b", "synth-beta.example.invalid")
    start = today - timedelta(days=45)
    for i in range(len(TEMPLATES)):
        a.new(start, template=i)
    for _ in range(38):
        a.new(start)
    beta_start = today - timedelta(days=18)
    for offset in range(46):
        day = start + timedelta(days=offset)
        if offset > 0:
            for _ in range(RNG.choice([0, 1, 1, 2, 3])):
                a.new(day)
            for _ in range(RNG.choice([0, 0, 1, 1, 2])):
                if len(a.items) > 30:
                    a.items.pop(RNG.choice(list(a.items)))
            if offset % 9 == 0:  # fachliche Inhaltsänderung
                key = RNG.choice(list(a.items))
                p = a.items[key]
                p.title = p.title.replace("(m/w/d)", "(m/w/d) – Bewerbungsfrist verlängert") if "verlängert" not in p.title else p.title
                p.apply_until = day + timedelta(days=30)
                p.raw_payload = {**p.raw_payload, "t": p.title, "apply": str(p.apply_until)}
        if offset == 33:
            pass  # Datenlücke: an diesem Tag läuft Alpha nicht
        elif offset == 25:
            run_scan(db, alpha, day, FakeAdapter(a.pages()[:1], complete=False))  # unvollständiger Lauf
        else:
            run_scan(db, alpha, day, FakeAdapter(a.pages()))
        if day >= beta_start:
            if day == beta_start:
                shared = [p for p in a.items.values()][:7]
                for p in shared:  # dieselbe Ausschreibung auf beiden Portalen: gleicher Arbeitgeber + gleiche Stellenreferenz
                    q = b.new(day, shared_ref=p.reference)
                    q.title, q.employer_name, q.locations, q.kind = p.title, p.employer_name, p.locations, p.kind
                    q.description_text = p.description_text
                    q.raw_payload = {**q.raw_payload, "t": q.title, "e": q.employer_name}
                for _ in range(16):
                    b.new(day)
            else:
                for _ in range(RNG.choice([0, 1, 2])):
                    b.new(day)
                if RNG.random() < 0.4 and len(b.items) > 15:
                    b.items.pop(RNG.choice(list(b.items)))
            if day == today - timedelta(days=4):
                def blocked(i: int) -> None:
                    raise BlockedError("HTTP 403 (synthetisch simuliert)", url="https://synth-beta.example.invalid/liste", status=403)

                run_scan(db, beta, day, FakeAdapter(b.pages(), behaviour=blocked))
            else:
                run_scan(db, beta, day, FakeAdapter(b.pages()))
    db.commit()


def seed_ops(db, today: date) -> None:
    beta_id = db.execute(sql("SELECT id FROM source WHERE key = 'synth_beta'")).scalar_one()
    db.execute(sql("INSERT INTO ops_warning (kind, dedupe_key, source_id, message) VALUES ('blocked', 'synth:blocked:beta', :s, "
                   "'Testportal Beta (synthetisch): Lauf blockiert (HTTP 403). Keine Umgehung – bitte Quelle prüfen.')"), {"s": beta_id})
    db.execute(sql("INSERT INTO job (kind, payload, status, priority, attempts, started_at, finished_at, result) VALUES "
                   "('aggregate', '{}', 'done', 100, 1, now() - interval '2 hours', now() - interval '119 minutes', '{\"rows\": 312}'), "
                   "('maintenance', '{}', 'failed', 100, 1, now() - interval '5 hours', now() - interval '299 minutes', NULL)"))
    db.execute(sql("UPDATE job SET last_error = 'Synthetischer Beispiel-Fehler: Zeitüberschreitung bei der Statusfortschreibung' WHERE kind = 'maintenance'"))
    db.commit()
    aggregate.compute_range(db, today - timedelta(days=45), today)
    db.commit()


def main() -> None:
    session = wf_db.session_factory()()
    try:
        # Schutz: nie echte Daten anfassen. Sobald nicht-synthetische Regionen, Statistiken oder Anzeigen vorhanden sind, bricht das Skript ab.
        foreign = session.execute(sql(
            "SELECT (SELECT count(*) FROM region WHERE source_note IS DISTINCT FROM :note) "
            "+ (SELECT count(*) FROM source_posting sp JOIN source s ON s.id = sp.source_id WHERE s.key NOT LIKE 'synth\\_%') "
            "+ (SELECT count(*) FROM stat_dataset WHERE key NOT LIKE 'synth\\_%') + (SELECT count(*) FROM scan_run r JOIN source s ON s.id = r.source_id WHERE s.key NOT LIKE 'synth\\_%')"),
            {"note": NOTE}).scalar_one()
        if foreign:
            sys.exit("Abbruch: Die Datenbank enthält nicht-synthetische Regionen, Statistiken, Läufe oder Anzeigen – dieses Skript würde sie löschen.")
        exists = session.execute(sql("SELECT 1 FROM source WHERE key LIKE 'synth_%' LIMIT 1")).first() or session.execute(sql("SELECT 1 FROM region LIMIT 1")).first()
        purge = "--purge" in sys.argv
        if exists and not purge and "--reset" not in sys.argv:
            sys.exit("Synthetische Daten sind bereits vorhanden. --reset erzeugt sie neu, --purge löscht sie nur.")
        if exists:
            reset(session)
        if purge:
            print("Synthetische Daten gelöscht.")
            return
        today = local_today()
        seed_reference(session)
        seed_stats(session, today)
        seed_postings(session, today)
        seed_ops(session, today)
        counts = session.execute(sql(
            "SELECT (SELECT count(*) FROM merged_posting), (SELECT count(*) FROM source_posting), (SELECT count(*) FROM scan_run), (SELECT count(*) FROM region), "
            "(SELECT count(*) FROM merge_candidate), (SELECT count(*) FROM posting_event)")).one()
        print(f"Fertig: {counts[0]} zusammengeführte Anzeigen, {counts[1]} Quellanzeigen, {counts[2]} Läufe, {counts[3]} Regionen, {counts[4]} Dublettenkandidaten, {counts[5]} Ereignisse.")
    finally:
        session.close()


if __name__ == "__main__":
    main()
