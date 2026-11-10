"""Ausdrücklich SYNTHETISCHE Daten für Skalierungstests (keine echten Anzeigen, keine echten Arbeitgeber).

Wird nie automatisch geladen. Alle Zeilen sind über ``is_synthetic`` bzw. die Quelle
``synthetic_benchmark`` gekennzeichnet und in der Oberfläche standardmäßig ausgeblendet.
Für aussagekräftige Messungen eine eigene Datenbank verwenden (siehe docs/tests.md).
"""
from __future__ import annotations

import time
from datetime import timedelta
from typing import Any

from sqlalchemy import text as sql

from .config import CLASSIFIER_VERSION, DEDUP_RULE_VERSION, GEO_RULE_VERSION, get_settings
from .db import session_scope
from .pipeline.run import local_today

SOURCE_KEY = "synthetic_benchmark"
TITLES = ["Sachbearbeitung Haushalt", "Softwareentwicklung Java", "Pflegefachkraft Station", "Bauingenieurwesen Tiefbau", "Erzieher Kindertagesstätte",
          "Systemadministration Linux", "Verwaltungsfachangestellte Bürgeramt", "Elektroniker Betriebstechnik", "Datenanalyse Statistik", "Projektleitung Digitalisierung",
          "Sozialarbeit Jugendhilfe", "Buchhaltung Kreiskasse", "Fachinformatiker Systemintegration", "Gärtner Grünflächenamt", "Jurist Vergaberecht",
          "Lehrkraft Berufsschule", "Ingenieur Umweltschutz", "Kraftfahrer Bauhof", "Referent Öffentlichkeitsarbeit", "Techniker Gebäudemanagement"]
FEATURES = ["skill:python", "skill:java", "skill:sql", "skill:ms_office", "skill:sap", "qual:bachelor", "qual:master", "qual:berufsausbildung",
            "exp:berufserfahrung", "lang:en", "license:fs_b", "skill:vergaberecht", "skill:haushaltsrecht", "skill:linux", "skill:projektmanagement", "skill:pflege"]


def load(postings: int = 100_000, days: int = 30, seed: int = 42) -> dict[str, Any]:
    """Erzeugt ``postings`` synthetische Quellanzeigen mit täglichen Beobachtungen über ``days`` Tage."""
    s = get_settings()
    if s.env == "production" and not s.allow_demo_data:
        raise SystemExit("Im Produktionsmodus werden synthetische Daten nur mit WF_ALLOW_DEMO_DATA=true geladen.")
    t0 = time.monotonic()
    today = local_today()
    start = today - timedelta(days=days - 1)
    with session_scope() as db:
        if db.execute(sql("SELECT 1 FROM source WHERE key = :k"), {"k": SOURCE_KEY}).first():
            raise SystemExit("Synthetische Daten sind bereits vorhanden – zuerst `workforce synthetic purge --confirm-synthetic` ausführen.")
        db.execute(sql("SELECT setseed(:s)"), {"s": (seed % 1000) / 1000.0})
        kreise = db.execute(sql("SELECT key FROM region WHERE level = 'district' AND is_current ORDER BY key")).scalars().all()
        if not kreise:
            kreise = [f"9{i:04d}" for i in range(1, 401)]  # ohne importierte Grenzen: erfundene Schlüssel
        src_id = db.execute(sql(
            "INSERT INTO source (key, name, domain, segment, config_status, status_reason, allowed_domains) VALUES "
            "(:k, 'SYNTHETISCH – Skalierungstest (keine echten Anzeigen)', 'synthetic.invalid', 'synthetische Testdaten', 'disabled', "
            "'Synthetische Daten für den Skalierungstest; wird nie gescannt.', '{}') RETURNING id"), {"k": SOURCE_KEY}).scalar_one()
        scope_id = db.execute(sql("INSERT INTO search_scope (source_id, key, version, name, params, mode, is_active) VALUES (:s, 'synthetic', 1, 'synthetisch', '{}', 'full', false) RETURNING id"),
                              {"s": src_id}).scalar_one()
        db.execute(sql(
            "INSERT INTO scan_run (source_id, scope_id, scope_key, scope_version, logical_date, trigger, mode, is_test, is_baseline, status, list_complete, detail_complete, "
            "parser_version, classifier_version, started_at, finished_at, status_applied, status_detail) "
            "SELECT :s, :sc, 'synthetic', 1, d::date, 'manual', 'full', false, d::date = :start, 'complete', true, true, 'synthetic-1', :cv, d, d + interval '10 min', true, 'synthetischer Lauf' "
            "FROM generate_series(CAST(:start AS timestamp), CAST(:today AS timestamp), interval '1 day') d"),
            {"s": src_id, "sc": scope_id, "start": start, "today": today, "cv": CLASSIFIER_VERSION})
        db.execute(sql("CREATE TEMP TABLE syn ON COMMIT DROP AS SELECT g AS n, "
                       "CASE WHEN random() < 0.55 THEN 0 ELSE floor(random() * :days)::int END AS first_off, "
                       "random() < 0.12 AS removed, floor(random() * :ntitles)::int AS ti, floor(random() * 4000)::int AS emp, "
                       "floor(random() * :nk)::int AS k1, floor(random() * :nk)::int AS k2, random() AS r, floor(random() * 16)::int AS f1, floor(random() * 16)::int AS f2, floor(random() * 16)::int AS f3 "
                       "FROM generate_series(1, :n) g"), {"n": postings, "days": days, "ntitles": len(TITLES), "nk": len(kreise)})
        db.execute(sql("UPDATE syn SET removed = false WHERE first_off >= :days - 4"), {"days": days})  # Wegfall braucht drei Folgescans
        db.execute(sql("ALTER TABLE syn ADD COLUMN last_off int"))
        db.execute(sql("UPDATE syn SET last_off = CASE WHEN removed THEN first_off + floor(random() * (:days - first_off - 4))::int ELSE :days - 1 END"), {"days": days})
        common = {"src": src_id, "start": start, "titles": TITLES, "kreise": list(kreise), "feats": FEATURES}
        db.execute(sql(
            "INSERT INTO source_posting (source_id, source_key, original_url, canonical_url, first_seen_at, first_seen_date, first_seen_baseline, last_seen_at, last_seen_date, detail_due, "
            "status, status_reason, is_synthetic) SELECT :src, 'syn-' || n, 'https://synthetic.invalid/anzeige/' || n, 'https://synthetic.invalid/anzeige/' || n, "
            ":start + first_off * interval '1 day', :start + first_off, first_off = 0, :start + last_off * interval '1 day', :start + last_off, false, "
            "CASE WHEN removed THEN 'presumed_removed' ELSE 'active' END, 'synthetisch', true FROM syn ORDER BY n"), common)
        db.execute(sql(
            "INSERT INTO posting_version (source_posting_id, version_no, change_kind, detail_level, content_hash, parser_version, classifier_version, geo_rule_version, valid_from, "
            "title, title_norm, employer_name, employer_norm, kind, working_time, contract_term, remote_type, kldb_code, kreis_keys, state_keys, loc_total, loc_unresolved, geo_class, "
            "feature_keys, feature_required_keys, search_a, search_b, search_c, quality) "
            "SELECT sp.id, 1, 'initial', 'detail', md5(sp.source_key), 'synthetic-1', :cv, :gv, sp.first_seen_date, "
            "(CAST(:titles AS text[]))[ti + 1] || ' (m/w/d) SYN-' || n, lower((CAST(:titles AS text[]))[ti + 1]), 'Synthetischer Arbeitgeber ' || emp, 'synthetischer arbeitgeber ' || emp, "
            "CASE WHEN r < 0.06 THEN 'ausbildung' WHEN r < 0.09 THEN 'praktikum' ELSE 'job' END, CASE WHEN r < 0.3 THEN ARRAY['teilzeit','vollzeit'] ELSE ARRAY['vollzeit'] END, "
            "CASE WHEN r < 0.25 THEN 'befristet' WHEN r < 0.7 THEN 'unbefristet' END, CASE WHEN r > 0.97 THEN 'remote' WHEN r > 0.8 THEN 'hybrid' END, NULL, "
            "CASE WHEN r > 0.97 THEN '{}'::text[] WHEN r > 0.9 AND k1 <> k2 THEN ARRAY[(CAST(:kreise AS text[]))[least(k1, k2) + 1], (CAST(:kreise AS text[]))[greatest(k1, k2) + 1]] ELSE ARRAY[(CAST(:kreise AS text[]))[k1 + 1]] END, "
            "CASE WHEN r > 0.97 THEN '{}'::text[] ELSE ARRAY[left((CAST(:kreise AS text[]))[k1 + 1], 2)] END, CASE WHEN r > 0.97 THEN 0 WHEN r > 0.9 AND k1 <> k2 THEN 2 ELSE 1 END, 0, "
            "CASE WHEN r > 0.97 THEN 'remote_nationwide' ELSE 'resolved' END, "
            "(SELECT array_agg(DISTINCT x ORDER BY x) FROM unnest(ARRAY[(CAST(:feats AS text[]))[f1 + 1], (CAST(:feats AS text[]))[f2 + 1], (CAST(:feats AS text[]))[f3 + 1]]) x), "
            "ARRAY[(CAST(:feats AS text[]))[f1 + 1]], lower((CAST(:titles AS text[]))[ti + 1]) || ' syn ' || n, 'synthetischer arbeitgeber ' || emp, "
            "replace((CAST(:feats AS text[]))[f1 + 1], ':', ' ') || ' ' || replace((CAST(:feats AS text[]))[f2 + 1], ':', ' '), '{\"synthetic\": true}'::jsonb "
            "FROM syn JOIN source_posting sp ON sp.source_id = :src AND sp.source_key = 'syn-' || syn.n"), {**common, "cv": CLASSIFIER_VERSION, "gv": GEO_RULE_VERSION})
        db.execute(sql("UPDATE source_posting sp SET current_version_id = pv.id FROM posting_version pv WHERE pv.source_posting_id = sp.id AND sp.source_id = :src"), common)
        # zusammengeführte Anzeigen (hier 1:1) direkt mit Zeiger auf ihre Quellanzeige anlegen
        db.execute(sql(
            "INSERT INTO merged_posting (primary_source_posting_id, current_version_id, status, first_seen_at, first_seen_date, first_seen_baseline, last_seen_at, last_seen_date, "
            "member_count, source_ids, dedup_rule_version, is_synthetic) SELECT sp.id, sp.current_version_id, sp.status, sp.first_seen_at, sp.first_seen_date, sp.first_seen_baseline, "
            "sp.last_seen_at, sp.last_seen_date, 1, ARRAY[:src]::int[], :dv, true FROM source_posting sp WHERE sp.source_id = :src"), {**common, "dv": DEDUP_RULE_VERSION})
        db.execute(sql("UPDATE source_posting sp SET merged_posting_id = mp.id FROM merged_posting mp WHERE mp.primary_source_posting_id = sp.id AND mp.is_synthetic AND sp.source_id = :src"), common)
        db.execute(sql("INSERT INTO merge_link (merged_posting_id, source_posting_id, reason, confidence, rule_version, decided_by) "
                       "SELECT merged_posting_id, id, 'singleton', 1.0, :dv, 'synthetic' FROM source_posting WHERE source_id = :src"), {**common, "dv": DEDUP_RULE_VERSION})
        db.execute(sql("INSERT INTO posting_location (version_id, ordinal, raw_text, locality, country, kreis_key, state_key, match_method, precision, confidence) "
                       "SELECT pv.id, o.ord - 1, 'synthetischer Ort', 'Synthetikstadt ' || o.k, 'DE', o.k, left(o.k, 2), 'synthetic', 'district', 1.0 "
                       "FROM posting_version pv JOIN source_posting sp ON sp.id = pv.source_posting_id AND sp.source_id = :src, unnest(pv.kreis_keys) WITH ORDINALITY AS o(k, ord)"), common)
        db.execute(sql("INSERT INTO activity_period (source_posting_id, start_date, end_date, end_reason) "
                       "SELECT id, first_seen_date, CASE WHEN status = 'active' THEN NULL ELSE last_seen_date END, CASE WHEN status = 'active' THEN NULL ELSE status END "
                       "FROM source_posting WHERE source_id = :src"), common)
        db.execute(sql("INSERT INTO posting_scope (source_posting_id, scope_id, last_seen_date, missed_complete_runs) SELECT id, :sc, last_seen_date, CASE WHEN status = 'active' THEN 0 ELSE 3 END "
                       "FROM source_posting WHERE source_id = :src"), {**common, "sc": scope_id})
        db.execute(sql("INSERT INTO posting_event (event_date, effective_date, event_type, merged_posting_id, source_posting_id, version_id, baseline) "
                       "SELECT first_seen_date, first_seen_date, 'first_seen', merged_posting_id, id, current_version_id, first_seen_baseline FROM source_posting WHERE source_id = :src"), common)
        db.execute(sql("INSERT INTO posting_event (event_date, effective_date, event_type, merged_posting_id, source_posting_id, details) "
                       "SELECT last_seen_date + 3, last_seen_date + 1, 'left_stock', merged_posting_id, id, '{\"status\": \"presumed_removed\"}'::jsonb FROM source_posting "
                       "WHERE source_id = :src AND status <> 'active'"), common)
        obs = db.execute(sql(
            "INSERT INTO observation (run_id, source_posting_id, version_id, seen_list, seen_detail, observed_at) "
            "SELECT r.id, sp.id, sp.current_version_id, true, false, r.started_at FROM source_posting sp "
            "JOIN scan_run r ON r.source_id = :src AND r.logical_date BETWEEN sp.first_seen_date AND sp.last_seen_date WHERE sp.source_id = :src"), common).rowcount
    with session_scope() as db:
        db.execute(sql("ANALYZE"))
        counts = db.execute(sql(
            "SELECT (SELECT count(*) FROM source_posting WHERE is_synthetic) AS source_postings, (SELECT count(*) FROM merged_posting WHERE is_synthetic) AS merged_postings, "
            "(SELECT count(*) FROM observation o JOIN scan_run r ON r.id = o.run_id JOIN source s ON s.id = r.source_id WHERE s.key = :k) AS observations, "
            "pg_size_pretty(pg_database_size(current_database())) AS database_size"), {"k": SOURCE_KEY}).mappings().one()
    return {"synthetic": True, "days": days, "seconds": round(time.monotonic() - t0, 1), "observations_inserted": obs, **dict(counts)}


def purge() -> dict[str, Any]:
    """Entfernt alle synthetischen Daten wieder vollständig."""
    with session_scope() as db:
        src = db.execute(sql("SELECT id FROM source WHERE key = :k"), {"k": SOURCE_KEY}).scalar_one_or_none()
        mp = db.execute(sql("DELETE FROM merged_posting WHERE is_synthetic")).rowcount
        sp = db.execute(sql("DELETE FROM source_posting WHERE is_synthetic")).rowcount
        if src is not None:
            db.execute(sql("DELETE FROM scan_run WHERE source_id = :s"), {"s": src})
            db.execute(sql("DELETE FROM source WHERE id = :s"), {"s": src})
        db.execute(sql("DELETE FROM daily_aggregate"))
    return {"purged_merged": mp, "purged_source_postings": sp, "note": "Tagesaggregate wurden geleert und sollten mit `workforce aggregate` neu berechnet werden."}
