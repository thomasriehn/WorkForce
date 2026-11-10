"""Dubletten, Zählregeln, Filterkonsistenz und Vergleichbarkeit (Abnahme 4, 7, 8, 9) – synthetische Daten."""
from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta

from sqlalchemy import func, select

from workforce.models import MergeCandidate, MergedPosting, MergeLink, PostingEvent, SourcePosting
from workforce.pipeline import dedup
from workforce.search import analytics
from workforce.search.query import Filters
from workforce.sources.base import RawLocation

from .helpers import FakeAdapter, make_regions, make_source, posting, run_scan

D0 = date(2026, 11, 2)


def loc(name: str, plz: str | None = None) -> RawLocation:
    return RawLocation(locality=name, postal_code=plz, country="DE", raw=name)


def n(db, model, *where):
    return db.execute(select(func.count()).select_from(model).where(*where)).scalar_one()


def test_same_ad_on_two_portals_counts_once(db):
    """Abnahme 4: dieselbe Anzeige auf zwei Portalen zählt deutschlandweit einmal; beide Quellverweise bleiben."""
    make_regions(db)
    _, s1 = make_source(db, "portal_a", domain="a.example")
    _, s2 = make_source(db, "portal_b", domain="b.example")
    run_scan(db, s1, D0, FakeAdapter([[posting("a1", "Sachbearbeiter*in Vergabe (m/w/d)", "Stadt Musterstadt", reference="MS-2026-17", domain="a.example")]]))
    run_scan(db, s2, D0, FakeAdapter([[posting("b9", "Sachbearbeiter/in Vergabe", "Stadt Musterstadt", reference="MS-2026-17", domain="b.example")]]))
    db.expire_all()
    assert n(db, SourcePosting) == 2 and n(db, MergedPosting) == 1
    mp = db.execute(select(MergedPosting)).scalar_one()
    assert mp.member_count == 2 and len(mp.source_ids) == 2
    link = db.execute(select(MergeLink).where(MergeLink.reason == "employer_reference")).scalar_one()
    assert float(link.confidence) == 0.95 and link.rule_version == "dedup-1"
    assert analytics.totals(db, Filters())["total"] == 1
    urls = db.execute(select(SourcePosting.original_url).order_by(SourcePosting.id)).scalars().all()
    assert urls == ["https://a.example/jobs/a1", "https://b.example/jobs/b9"]
    # die zweite Veröffentlichung ist kein neuer Bedarf
    assert n(db, PostingEvent, PostingEvent.event_type == "first_seen") == 1
    assert n(db, PostingEvent, PostingEvent.event_type == "additional_source") == 1
    # verschwindet die Anzeige auf Portal A, bleibt die zusammengeführte Anzeige aktiv, solange Portal B sie zeigt
    for i in range(1, 4):
        run_scan(db, s1, D0 + timedelta(days=i), FakeAdapter([[posting("zz", "Andere Stelle", "Anderer Arbeitgeber", domain="a.example")]]))
        run_scan(db, s2, D0 + timedelta(days=i), FakeAdapter([[posting("b9", "Sachbearbeiter/in Vergabe", "Stadt Musterstadt", reference="MS-2026-17", domain="b.example")]]))
    db.expire_all()
    assert db.execute(select(SourcePosting.status).where(SourcePosting.source_key == "a1")).scalar_one() == "presumed_removed"
    assert db.get(MergedPosting, mp.id).status == "active"
    assert n(db, PostingEvent, PostingEvent.event_type == "left_stock", PostingEvent.merged_posting_id == mp.id) == 0


def test_similar_but_distinct_postings_stay_separate(db):
    """Abnahme 4: ähnliche echte Ausschreibungen (Niederlassungen, Vermittler, nur ähnlicher Titel) werden nicht unbegründet vereinigt."""
    make_regions(db)
    _, s1 = make_source(db, "portal_a", domain="a.example")
    _, s2 = make_source(db, "portal_b", domain="b.example")
    run_scan(db, s1, D0, FakeAdapter([[
        posting("n1", "Pflegefachkraft (m/w/d)", "Klinikverbund Test", place="Musterstadt", domain="a.example"),
        posting("v1", "Lagerhelfer (m/w/d)", "Zeitarbeit Muster GmbH", place="Musterstadt", domain="a.example"),
        posting("t1", "Softwareentwickler Java (m/w/d)", "IT Haus Test", place="Musterstadt", domain="a.example"),
    ]]))
    run_scan(db, s2, D0, FakeAdapter([[
        posting("n2", "Pflegefachkraft (m/w/d)", "Klinikverbund Test", place="Südheim", domain="b.example"),  # andere Niederlassung
        posting("v2", "Lagerhelfer (m/w/d)", "Zeitarbeit Muster GmbH", place="Musterstadt", domain="b.example"),  # Personalvermittler
        posting("t2", "Softwareentwickler Java Backend (m/w/d)", "IT Haus Test", place="Musterstadt", domain="b.example"),  # nur ähnlicher Titel
        posting("x2", "Softwareentwickler Java (m/w/d)", "Ganz Andere Firma", place="Musterstadt", domain="b.example"),  # anderer Arbeitgeber
    ]]))
    db.expire_all()
    assert n(db, MergedPosting) == 7  # nichts wurde automatisch vereinigt
    reasons = set(db.execute(select(MergeCandidate.reason)).scalars().all())
    assert any("agency" in r for r in reasons)  # Vermittler: nur als unsicherer Kandidat vorgemerkt
    assert n(db, MergeCandidate, MergeCandidate.state == "open") >= 1


def test_merge_is_reversible_and_republication_is_not_new(db):
    make_regions(db)
    _, s1 = make_source(db, "portal_a", domain="a.example")
    _, s2 = make_source(db, "portal_b", domain="b.example")
    a = posting("a1", "Bauingenieur (m/w/d)", "Kreis Beispiel", place="Beispielhausen", domain="a.example")
    b = posting("b1", "Bauingenieur (m/w/d)", "Kreis Beispiel", place="Beispielhausen", domain="b.example")
    run_scan(db, s1, D0, FakeAdapter([[a]]))
    run_scan(db, s2, D0, FakeAdapter([[b]]))
    db.expire_all()
    assert n(db, MergedPosting) == 1  # R3: Arbeitgeber + Titel + gleiche Kreismenge
    sp_b = db.execute(select(SourcePosting).where(SourcePosting.source_key == "b1")).scalar_one()
    dedup.split_member(db, sp_b.id, "tester")
    db.commit()
    assert n(db, MergedPosting) == 2 and n(db, MergeLink, MergeLink.is_active.is_(False)) == 1
    # erneuter Lauf darf die manuell getrennten Anzeigen nicht wieder vereinigen
    run_scan(db, s2, D0 + timedelta(days=1), FakeAdapter([[b]]))
    db.expire_all()
    assert n(db, MergedPosting) == 2
    # Wiederveröffentlichung: alte Anzeige fällt weg, neue Quell-ID mit gleicher Referenz erscheint
    _, s3 = make_source(db, "portal_c", domain="c.example")
    old = posting("c1", "Erzieher (m/w/d)", "Kita Verbund Test", reference="KV-77", place="Musterstadt", domain="c.example")
    run_scan(db, s3, D0, FakeAdapter([[old, posting("c0", "Platzhalter", "Sonstige", domain="c.example")]]))
    for i in range(1, 4):
        run_scan(db, s3, D0 + timedelta(days=i), FakeAdapter([[posting("c0", "Platzhalter", "Sonstige", domain="c.example")]]))
    new = posting("c2", "Erzieher (m/w/d)", "Kita Verbund Test", reference="KV-77", place="Musterstadt", domain="c.example")
    before = n(db, MergedPosting)
    run_scan(db, s3, D0 + timedelta(days=5), FakeAdapter([[new, posting("c0", "Platzhalter", "Sonstige", domain="c.example")]]))
    db.expire_all()
    assert n(db, MergedPosting) == before  # keine neue zusammengeführte Anzeige
    assert n(db, PostingEvent, PostingEvent.event_type == "republication") == 1


def _counting_fixture(db):
    make_regions(db)
    _, scope = make_source(db)
    ps = [
        posting("one", "Einzelstandort", "AG Eins", place="Musterstadt"),                         # k=1 → 1,0 in 91001
        posting("two", "Zwei Standorte", "AG Zwei", place=None),                                    # k=2 → je 0,5
        posting("part", "Teilweise ungeklärt", "AG Drei", place=None),                              # 1 Ort bekannt, 1 unbekannt
        posting("unk", "Unbekannter Ort", "AG Vier", place="Nirgendwo-Phantasia"),                  # ungeklärt
        posting("rem", "Remote bundesweit", "AG Fünf", place=None, remote_type="remote"),           # deutschlandweit remote
        posting("hyb", "Hybrid mit Ort", "AG Sechs", place="Südheim", remote_type="hybrid"),        # hybrid → belegter Ort
        posting("amb", "Mehrdeutiger Ortsname", "AG Sieben", place="Neustadt"),                     # Neustadt ×2 → nicht zuordnen
        posting("plz", "Mehrdeutig mit PLZ", "AG Acht", place="Neustadt", plz="92100"),             # PLZ entscheidet → 92001
        posting("azubi", "Ausbildung zum Verwaltungsfachangestellten (m/w/d)", "AG Neun", place="Musterstadt"),
    ]
    ps[1].locations = [loc("Musterstadt"), loc("Beispielhausen")]
    ps[2].locations = [loc("Musterstadt"), loc("Unbekanntdorf-Xyz")]
    ps[4].locations = [RawLocation(locality="Deutschland", country="DE", raw="Deutschland")]
    for p in ps:
        p.raw_payload = {"k": p.source_key}
    run_scan(db, scope, D0, FakeAdapter([ps]))
    db.expire_all()
    return scope


def test_counting_rules_multi_location_remote_unresolved(db):
    """Abnahme 8: Mehrfachstandorte, Remote-Angebote und ungeklärte Orte folgen den dokumentierten Zählregeln."""
    _counting_fixture(db)
    f = Filters(kind_group="jobs")
    m = analytics.map_metrics(db, f)
    by = {r["key"]: r for r in m["regions"]}
    # 91001: one (1,0) + two (0,5) anteilig; unterschiedliche Anzeigen: one, two, part
    assert by["91001"]["weighted"] == 1.5 and by["91001"]["distinct"] == 3
    assert by["91002"]["weighted"] == 0.5 and by["91002"]["distinct"] == 1
    assert by["92001"]["weighted"] == 2.0 and by["92001"]["distinct"] == 2  # hyb + plz
    t = m["totals"]
    assert t["total"] == 8  # deutschlandweit jede Anzeige einmal (Ausbildung ist getrennt)
    assert t["geo"] == {"resolved": 4, "partial": 1, "unresolved": 2, "remote_nationwide": 1, "foreign": 0, "none": 0}
    # die anteilige Karte summiert sich genau auf die vollständig zugeordneten Anzeigen
    assert m["weighted_sum"] == t["geo"]["resolved"] == 4
    # regionale Zahlen „unterschiedliche Anzeigen“ sind nicht addierbar (6 > 5 Anzeigen mit Kreisbezug)
    assert sum(r["distinct"] for r in m["regions"]) == 6
    # Ausbildung wird getrennt von regulären Stellen ausgewertet
    assert analytics.totals(db, Filters(kind_group="ausbildung"))["total"] == 1
    assert analytics.totals(db, Filters(kind_group="all"))["total"] == 9


def test_filters_apply_identically_to_list_map_and_chart(db):
    """Abnahme 9: Stichwort-, Qualifikations- und Regionsfilter wirken konsistent auf Liste, Karte und Diagramm."""
    make_regions(db)
    _, scope = make_source(db)
    req = "Ihr Profil\n- Python erforderlich\n- Abgeschlossenes Studium (Bachelor) erforderlich"
    opt = "Ihr Profil\n- Python ist von Vorteil"
    none = "Ihr Profil\n- Keine Python-Kenntnisse erforderlich\n- Führerschein Klasse B erforderlich"
    ps = [
        posting("p1", "Datenanalyst (m/w/d)", "Amt A", place="Musterstadt", description=req),
        posting("p2", "Datenanalyst (m/w/d)", "Amt B", place="Beispielhausen", description=opt),
        posting("p3", "Fahrer (m/w/d)", "Amt C", place="Musterstadt", description=none),
        posting("p4", "Datenanalyst Statistik", "Amt D", place=None, description=req),
    ]
    ps[3].locations = [loc("Musterstadt"), loc("Südheim")]
    run_scan(db, scope, D0, FakeAdapter([ps]))
    db.expire_all()
    cases = [
        Filters(q="Datenanalyst"), Filters(features=["skill:python"]), Filters(features=["skill:python"], features_required_only=True),
        Filters(q="datenanalyst -statistik"), Filters(features=["skill:python", "qual:bachelor"], features_mode="and"),
        Filters(features=["license:fs_b", "qual:bachelor"], features_mode="or"), Filters(q='"Datenanalyst Statistik" ODER Fahrer'),
    ]
    expected = [3, 3, 2, 2, 2, 3, 2]
    for f, exp in zip(cases, expected, strict=True):
        lst = analytics.search_postings(db, f)
        assert lst["total"] == exp, f
        tot = analytics.totals(db, f)
        assert tot["total"] == exp
        m = analytics.map_metrics(db, f)
        assert m["totals"]["total"] == exp
        ts = analytics.timeseries(db, f, D0, D0)
        assert ts["points"][-1]["stock"] == exp  # Diagramm: Bestand am Stichtag = Trefferzahl
        for region in m["regions"]:
            # Kreisfilter in der Liste = „unterschiedliche Anzeigen mit Bezug zum Kreis“ der Karte
            assert analytics.search_postings(db, replace(f, kreise=[region["key"]]))["total"] == region["distinct"]
        # Stichtagsabfrage für heute entspricht dem aktuellen Bestand
        assert analytics.totals(db, replace(f, as_of=D0))["total"] == exp
    # „Keine Python-Kenntnisse erforderlich“ zählt nicht als Python-Anforderung
    ids = {i["id"] for i in analytics.search_postings(db, Filters(features=["skill:python"]))["items"]}
    p3 = db.execute(select(SourcePosting.merged_posting_id).where(SourcePosting.source_key == "p3")).scalar_one()
    assert p3 not in ids


def test_new_source_and_scope_change_do_not_fake_growth(db):
    """Abnahme 7: neue Quellen und geänderte Suchbereiche erzeugen keinen unkommentierten Trendanstieg."""
    make_regions(db)
    src_a, sa = make_source(db, "portal_a", domain="a.example")
    base = [posting(f"a{i}", f"Stelle A{i}", f"AG A{i}", place="Musterstadt", domain="a.example") for i in range(4)]
    for i in range(0, 8):
        extra = [posting("a_neu", "Neue Stelle", "AG Neu", place="Musterstadt", domain="a.example")] if i >= 5 else []
        run_scan(db, sa, D0 + timedelta(days=i), FakeAdapter([base + extra]))
    # am 8. Tag kommt eine neue Quelle mit 20 Anzeigen hinzu
    src_b, sb = make_source(db, "portal_b", domain="b.example")
    newsrc = [posting(f"b{i}", f"Stelle B{i}", f"AG B{i}", place="Beispielhausen", domain="b.example") for i in range(20)]
    d7 = D0 + timedelta(days=7)
    run_scan(db, sb, d7, FakeAdapter([newsrc]))
    db.expire_all()
    ch = analytics.map_change(db, Filters(), 7)
    assert ch["basis"]["comparable_sources"] == [src_a.id]
    assert any("neue Quelle" in e["reason"] for e in ch["basis"]["excluded"])
    assert ch["total"]["now"] == 5 and ch["total"]["then"] == 4 and ch["total"]["abs"] == 1  # ohne die 20 der neuen Quelle
    by = {r["key"]: r for r in ch["regions"]}
    assert "91002" not in by  # Kreis der neuen Quelle taucht im Vergleich nicht als „Wachstum“ auf
    assert any("Bestandsaufnahme" in nn["message"] for nn in ch["basis"]["notes"])
    ts = analytics.timeseries(db, Filters(), D0, d7)
    pts = {p["date"]: p for p in ts["points"]}
    # Bestandsaufnahmen (Erstläufe) sind keine Welle neuer Anzeigen
    assert pts[D0.isoformat()]["first_seen"] == 0 and pts[D0.isoformat()]["baseline"] == 4
    assert pts[d7.isoformat()]["first_seen"] == 0 and pts[d7.isoformat()]["baseline"] == 20
    assert pts[(D0 + timedelta(days=5)).isoformat()]["first_seen"] == 1  # die echte Neuerscheinung
    # geänderter Suchbereich: neue Version ⇒ Vergleich über den Wechsel ausgeschlossen
    from workforce.sources.manage import new_scope_version

    sa2 = new_scope_version(db, src_a, "alle", name="Alle (erweitert)", params={"erweitert": True}, mode="full", page_budget=None, note=None, username="tester")
    db.commit()
    d8 = D0 + timedelta(days=8)
    wider = base + [posting(f"w{i}", f"Zusatz {i}", f"AG W{i}", place="Musterstadt", domain="a.example") for i in range(10)]
    r = run_scan(db, sa2, d8, FakeAdapter([wider]))
    assert r.is_baseline
    run_scan(db, sb, d8, FakeAdapter([newsrc]))
    db.expire_all()
    ch2 = analytics.map_change(db, Filters(), 7)
    reasons = {e["source_id"]: e["reason"] for e in ch2["basis"]["excluded"]}
    assert "Suchbereich" in reasons[src_a.id] and not ch2["basis"]["comparable"]
    assert ch2["total"] is None and "Kein Vergleich" in ch2["message"]
    pts2 = {p["date"]: p for p in analytics.timeseries(db, Filters(), D0, d8)["points"]}
    assert pts2[d8.isoformat()]["first_seen"] == 0 and pts2[d8.isoformat()]["baseline"] == 10


def test_change_with_zero_base_reports_absolute_only(db):
    make_regions(db)
    _, scope = make_source(db)
    keep = [posting("k", "Bleibt", "AG", place="Musterstadt")]
    for i in range(0, 8):
        extra = [posting("neu", "Neu im Südkreis", "AG Süd", place="Südheim")] if i >= 3 else []
        run_scan(db, scope, D0 + timedelta(days=i), FakeAdapter([keep + extra]))
    db.expire_all()
    ch = analytics.map_change(db, Filters(), 7)
    by = {r["key"]: r for r in ch["regions"]}
    assert by["92001"]["then"] == 0 and by["92001"]["abs"] == 1 and by["92001"]["pct"] is None and "Ausgangswert 0" in by["92001"]["pct_note"]
    assert by["91001"]["pct"] == 0.0
    # ohne Bevölkerungsnenner wird kein Quotient gebildet
    assert all(r["rate_per_1000"] is None for r in analytics.map_metrics(db, Filters())["regions"])


def test_current_stock_equals_snapshot_of_today_even_on_the_day_an_ad_leaves(db):
    """Aktueller Bestand (Status) und Stichtagsbestand von heute (Zeiträume) sind dieselbe Bezugsbasis."""
    from workforce.models import SourcePosting as SP
    from workforce.pipeline.status import leave_stock

    make_regions(db)
    _, scope = make_source(db)
    run_scan(db, scope, D0, FakeAdapter([[posting("x1", "Erste", "AG", place="Musterstadt"), posting("x2", "Zweite", "AG B", place="Musterstadt")]]))
    d1 = D0 + timedelta(days=1)
    run_scan(db, scope, d1, FakeAdapter([[posting("x1", "Erste", "AG", place="Musterstadt"), posting("x2", "Zweite", "AG B", place="Musterstadt")]]))
    sp = db.execute(select(SP).where(SP.source_key == "x2")).scalar_one()
    leave_stock(db, sp, "ended", "Ablaufhinweis der Quelle (Test)", d1, end_date=d1)  # heute gesehen und heute als beendet festgestellt
    db.commit()
    assert analytics.totals(db, Filters())["total"] == 1
    assert analytics.totals(db, Filters(as_of=d1))["total"] == 1
    assert analytics.totals(db, Filters(as_of=D0))["total"] == 2  # gestern zählte sie noch
    assert analytics.timeseries(db, Filters(), D0, d1)["points"][-1]["stock"] == 1


def test_daily_aggregates_are_reproducible_and_match_live_figures(db):
    """Tagesaggregate lassen sich aus der Historie neu berechnen und stimmen mit den Live-Auswertungen überein."""
    from sqlalchemy import text as sql

    from workforce.pipeline import aggregate

    _counting_fixture(db)
    d1 = D0 + timedelta(days=1)
    _, scope2 = make_source(db, "zweite", domain="z.example")
    run_scan(db, scope2, d1, FakeAdapter([[posting("z1", "Zusatz", "AG Z", place="Beispielhausen", domain="z.example")]]))
    for _ in range(2):  # zweimal rechnen = identisches Ergebnis (ersetzen statt anhängen)
        aggregate.compute_range(db, D0, d1)
    rows = {(r[0], r[1], r[2]): r for r in db.execute(sql("SELECT agg_date, region_key, kind_group, weighted_count, distinct_count, first_seen_count, observed_count, dedup_rule_version, basis FROM daily_aggregate")).all()}
    live = {r["key"]: r for r in analytics.map_metrics(db, Filters(as_of=D0))["regions"]}
    for key, r in live.items():
        agg = rows[(D0, key, "jobs")]
        assert float(agg[3]) == r["weighted"] and agg[4] == r["distinct"]
    all_d0 = rows[(D0, "__ALL__", "jobs")]
    assert all_d0[4] == 8 and all_d0[5] == 0 and all_d0[6] == 8 and all_d0[7] == "dedup-1"  # Bestandsaufnahme: keine „neuen“
    assert rows[(D0, "__PARTIAL__", "jobs")][4] == 1 and rows[(D0, "__REMOTE__", "jobs")][4] == 1 and rows[(D0, "__UNRESOLVED__", "jobs")][4] == 2
    assert rows[(d1, "__ALL__", "jobs")][4] == 9 and rows[(D0, "__ALL__", "ausbildung")][4] == 1
    assert any(v["complete"] for v in all_d0[8].values())  # Bezugsbasis (Quellen/Suchbereichsversionen) ist am Aggregat vermerkt
    # ungefilterte Zeitreihe nutzt die Aggregate und liefert dieselben Bestandszahlen wie die Live-Abfrage
    fast = [p["stock"] for p in analytics.timeseries(db, Filters(), D0, d1)["points"]]
    assert fast == [8, 9] == [analytics.totals(db, Filters(as_of=d))["total"] for d in (D0, d1)]


def test_short_place_names_resolve_only_when_unambiguous(db):
    """Kurznamen amtlicher Ortsnamen („Frankfurt“ → „Frankfurt am Main“) werden nur bei eindeutiger Lage zugeordnet."""
    from sqlalchemy import text as sql

    from workforce.geo.matcher import GeoMatcher
    from workforce.normalize.text import fold

    make_regions(db)
    for name, ags, kreis, plz, pop in (("Musterfurt am Fluss", "91001900", "91001", "91099", 700000), ("Musterfurt (Tal)", "92001900", "92001", "92099", 60000),
                                        ("Einzigheim, Hansestadt", "91002900", "91002", "91299", 20000), ("Stein-Musterheim", "92001901", "92001", "92098", 900)):
        db.execute(sql("INSERT INTO geo_place (country, name, name_norm, kind, ags, kreis_key, state_key, postal_code, population, lat, lon) "
                       "VALUES ('DE', :n, :nn, 'municipality', :a, :k, :s, :p, :pop, 50.5, 10.5)"), {"n": name, "nn": fold(name), "a": ags, "k": kreis, "s": kreis[:2], "p": plz, "pop": pop})
        db.execute(sql("INSERT INTO postal_code (country, plz, ags, kreis_key, place_name) VALUES ('DE', :p, :a, :k, :n)"), {"p": plz, "a": ags, "k": kreis, "n": name})
    db.commit()
    g = GeoMatcher(db)
    amb = g.match(loc("Musterfurt"))
    assert amb.kreis_key is None and amb.method == "ambiguous_name"  # zwei Orte, kein Hinweis ⇒ ungeklärt statt geraten
    with_plz = g.match(loc("Musterfurt", "92099"))
    assert with_plz.kreis_key == "92001" and "short_name" in with_plz.method and with_plz.point_origin == "place_centroid"
    with_state = g.match(RawLocation(locality="Musterfurt", region=None, country="DE", postal_code="91099"))
    assert with_state.kreis_key == "91001"
    single = g.match(loc("Einzigheim"))
    assert single.kreis_key == "91002" and float(single.confidence) < 0.9  # eindeutig, aber als Kurzname mit Abschlag
    assert g.match(loc("Stein")).kreis_key is None  # „Stein-Musterheim“ ist kein Namenszusatz von „Stein“
    assert g.match(loc("Einzigheim, Hansestadt")).method == "place_name"  # exakter amtlicher Name bleibt der Normalfall
