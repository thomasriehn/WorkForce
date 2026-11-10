"""Skalierungsmessung auf AUSDRÜCKLICH SYNTHETISCHEN Daten (siehe ``workforce synthetic load``).

Misst die wichtigsten Such- und Kartenabfragen (Median aus mehreren Durchläufen, warmer Cache) und gibt
Hardware- sowie Datenbankeckdaten aus. Aufruf in einer eigenen Datenbank:

    WF_DATABASE_URL=… uv run python scripts/benchmark.py [--runs 5]
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import time
from dataclasses import replace
from datetime import timedelta

from sqlalchemy import text as sql

from workforce.db import session_scope
from workforce.pipeline import aggregate
from workforce.search import analytics
from workforce.search.query import Filters


def cpu_model() -> str:
    try:
        for line in open("/proc/cpuinfo", encoding="utf-8"):
            if line.startswith("model name"):
                return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return platform.processor() or "unbekannt"


def mem_gb() -> float:
    try:
        for line in open("/proc/meminfo", encoding="utf-8"):
            if line.startswith("MemTotal"):
                return round(int(line.split()[1]) / 1024 / 1024, 1)
    except OSError:
        pass
    return 0.0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=5)
    args = ap.parse_args()
    base = Filters(include_synthetic=True, kind_group="jobs")
    with session_scope() as db:
        ref = analytics.reference_date(db)
        kreis = db.execute(sql("SELECT k FROM (SELECT unnest(kreis_keys) k FROM posting_version) x GROUP BY k ORDER BY count(*) DESC LIMIT 1")).scalar_one()
        one_id = db.execute(sql("SELECT id FROM merged_posting WHERE is_synthetic ORDER BY id LIMIT 1 OFFSET 5000")).scalar_one()
        cases = {
            "Suche: Freitext („pflegefachkraft“), Seite 1": lambda: analytics.search_postings(db, replace(base, q="pflegefachkraft")),
            "Suche: Freitext + Merkmal (UND) + Kreis": lambda: analytics.search_postings(db, replace(base, q="softwareentwicklung", features=["skill:python"], kreise=[kreis])),
            "Suche: Phrase/ODER/Ausschluss": lambda: analytics.search_postings(db, replace(base, q='"systemadministration linux" ODER jurist -vergaberecht')),
            "Suche: zwei Merkmale (UND), nur verlangt": lambda: analytics.search_postings(db, replace(base, features=["skill:sql", "qual:bachelor"], features_required_only=False)),
            "Suche: ohne Filter, Seite 200 (Sortierung erstmals beobachtet)": lambda: analytics.search_postings(db, base, page=200),
            "Suche: ähnliche Schreibweisen (Trigram)": lambda: analytics.search_postings(db, replace(base, q="pflegefachkraft", fuzzy=True)),
            "Summen (Bezugsbasis, ungefiltert)": lambda: analytics.totals(db, base),
            "Karte: Kennzahlen je Kreis, ungefiltert": lambda: analytics.map_metrics(db, base),
            "Karte: Kennzahlen je Kreis mit Freitext + Merkmal": lambda: analytics.map_metrics(db, replace(base, q="pflegefachkraft", features=["exp:berufserfahrung"])),
            "Karte: Stichtag vor 30 Tagen (historische Versionen)": lambda: analytics.map_metrics(db, replace(base, as_of=ref - timedelta(days=30))),
            "Karte: Veränderung 30 Tage (zwei Stichtage + Vergleichbarkeit)": lambda: analytics.map_change(db, base, 30),
            "Zeitreihe 60 Tage, gefiltert (live, 45 Stützstellen)": lambda: analytics.timeseries(db, replace(base, features=["skill:python"]), ref - timedelta(days=59), ref),
            "Zeitreihe 60 Tage, ungefiltert (hier live berechnet; im Betrieb aus Tagesaggregaten)": lambda: analytics.timeseries(db, base, ref - timedelta(days=59), ref),
            "Facetten (häufige Berufe/Merkmale/Arbeitgeber) für einen Kreis": lambda: analytics.facets(db, replace(base, kreise=[kreis])),
            "CSV-Export 10.000 Zeilen": lambda: analytics.export_rows(db, replace(base, q="sachbearbeitung OR pflegefachkraft OR jurist"), limit=10_000),
            "Anzeigendetail (Kernabfragen)": lambda: db.execute(sql("SELECT * FROM merged_posting mp JOIN posting_version pv ON pv.id = mp.current_version_id WHERE mp.id = :i"), {"i": one_id}).all(),
        }
        counts = db.execute(sql(
            "SELECT (SELECT count(*) FROM source_posting) sp, (SELECT count(*) FROM merged_posting) mp, (SELECT count(*) FROM posting_version) pv, "
            "(SELECT count(*) FROM observation) obs, (SELECT count(*) FROM posting_location) loc, (SELECT count(*) FROM activity_period) ap, "
            "(SELECT count(*) FROM region WHERE level = 'district') districts")).mappings().one()
        sizes = db.execute(sql("SELECT relname, pg_size_pretty(pg_total_relation_size(c.oid)) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                               "WHERE n.nspname = 'public' AND relkind = 'r' ORDER BY pg_total_relation_size(c.oid) DESC LIMIT 6")).all()
        settings = dict(db.execute(sql("SELECT name, setting || coalesce(unit, '') FROM pg_settings WHERE name IN ('shared_buffers','work_mem','effective_cache_size','max_parallel_workers_per_gather')")).all())
        t0 = time.perf_counter()
        agg = aggregate.compute_day(db, ref, include_synthetic=True)
        db.commit()
        agg_s = time.perf_counter() - t0
        t0 = time.perf_counter()
        aggregate.compute_range(db, ref - timedelta(days=59), ref, include_synthetic=True)
        agg_range_s = time.perf_counter() - t0
        results = {}
        for name, fn in cases.items():
            fn()  # Aufwärmen
            times = []
            for _ in range(args.runs):
                t = time.perf_counter()
                fn()
                times.append((time.perf_counter() - t) * 1000)
            results[name] = {"median_ms": round(statistics.median(times), 1), "max_ms": round(max(times), 1)}
        out = {
            "hinweis": "SYNTHETISCHE Daten – keine echten Anzeigen",
            "hardware": {"cpu": cpu_model(), "kerne": os.cpu_count(), "ram_gb": mem_gb(), "os": platform.platform()},
            "postgres": {"version": db.execute(sql("SHOW server_version")).scalar_one(), **settings},
            "datenmenge": dict(counts), "groesste_tabellen": {r[0]: r[1] for r in sizes},
            "aggregate": {"ein_tag_s": round(agg_s, 2), "zeilen_je_tag": agg, "sechzig_tage_s": round(agg_range_s, 1)},
            "abfragen": results,
        }
    print(json.dumps(out, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
