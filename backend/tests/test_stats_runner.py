"""Öffentliche Schnittstelle der Statistik-Importe: Stammdaten, Übersicht, automatischer Abruf (ohne echtes Netz).

Alle „Webseiten“ in diesen Tests sind kleine, hier erzeugte HTML-Schnipsel im Aufbau der offiziellen Seiten; der
Abruf läuft über ``httpx.MockTransport``. Es findet kein Zugriff auf echte Hosts statt.
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import text as sql

from workforce.config import get_settings
from workforce.crawl.fetcher import (
    BlockedError,
    Fetcher,
    FetchError,
    RobotsDisallowed,
    RobotsStore,
    TargetForbidden,
)
from workforce.stats import discovery, genesis_ui, runner
from workforce.stats.catalog import DATASET_BY_KEY, DATASETS, INDICATORS
from workforce.stats.runner import ImportProblem, describe, run_imports, seed_reference

from .fixtures.stats import synthetic as syn
from .fixtures.stats.synthetic import small_thresholds  # noqa: F401 – pytest-Fixture

ROBOTS_OK = "User-agent: *\nAllow: /\n"
MONTH = date(2024, 3, 1)
GV = DATASET_BY_KEY["gv_isys"]
VG = DATASET_BY_KEY["vg250"]
GV_PUB = "https://www.destatis.de/DE/Themen/Laender-Regionen/Regionales/Gemeindeverzeichnis/Administrativ/Archiv/GVAuszugQ/AuszugGV1QAktuell.html"
GV_FILE = GV_PUB.replace(".html", ".xlsx") + "?__blob=publicationFile&v=7"
VG_FILE = "https://daten.gdz.bkg.bund.de/produkte/vg/vg250_ebenen_1231/aktuell/vg250_12-31.utm32s.gpkg.ebenen.zip"
GV_LANDING_HTML = f"""<html><body><!-- SYNTHETISCHE TESTSEITE im Aufbau der Destatis-Themenseite -->
<a class="RichTextIntLink Publication" href="/DE/Themen/Laender-Regionen/Regionales/Gemeindeverzeichnis/Administrativ/Archiv/GVAuszugQ/AuszugGV4QAktuell.html">31.12.2023</a>
<a class="RichTextIntLink Publication" title="Alle politisch selbständigen Gemeinden am 31.03.2024 (1. Quartal 2024)" href="{GV_PUB}">31.03.2024</a>
<a href="/DE/Themen/Laender-Regionen/Regionales/Gemeindeverzeichnis/Administrativ/Archiv/GVAuszugJ/31122023_Auszug_GV.html">31.12.2023</a>
</body></html>"""
GV_PUB_HTML = f"""<html><body><!-- SYNTHETISCH --><ul><li class="download"><p>
<a href="{GV_FILE.replace('&', '&amp;')}" title="Öffnet im neuen Fenster" class="downloadLink" target="_blank">Herunterladen <span>(xlsx, 1kB)</span></a>
</p></li></ul></body></html>"""
VG_HTML = f"""<html><body><!-- SYNTHETISCHE TESTSEITE im Aufbau der BKG-Produktseite -->
<p>Aktualitätsstand: 31.12.2023</p>
Änderung vom 05.06.2024<br><ul><li>Datenaktualisierung Stand 31.12.2023</li><li>sonstiges</li></ul>
Änderung vom 08.09.2023<br><ul><li>Datenaktualisierung Stand 31.12.2022</li></ul>
<div class="link-item"><a class="download" href="https://daten.gdz.bkg.bund.de/produkte/vg/vg250_ebenen_1231/aktuell/vg250_12-31.utm32s.shape.ebenen.zip">shape</a></div>
<div class="link-item"><a class="download" href=" \t{VG_FILE}">Stand: 31.12., Georeferenzierung: UTM32s, Format: geopackage Inhalt: Ebenen (ZIP, 1 kB)</a></div>
</body></html>"""


@pytest.fixture(autouse=True)
def _data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "data_dir", tmp_path / "data")


def install_http(monkeypatch: pytest.MonkeyPatch, handler: Callable[[httpx.Request], httpx.Response]) -> list[httpx.Request]:
    """Ersetzt den Netzabruf der Importe durch einen lokalen Handler und protokolliert alle Anfragen."""
    calls: list[httpx.Request] = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text=ROBOTS_OK)
        return handler(request)

    def factory(spec: Any, settings: Any, robots: RobotsStore) -> Fetcher:
        return Fetcher(spec.hosts, interval_seconds=0, settings=settings.model_copy(update={"http_max_retries": 0}),
                       robots_store=robots, transport=httpx.MockTransport(wrapped), sleep=lambda s: None)

    monkeypatch.setattr(runner, "make_fetcher", factory)
    return calls


def paths(calls: list[httpx.Request], host: str | None = None) -> list[str]:
    return [c.url.path.rsplit("/", 1)[-1] for c in calls if host is None or c.url.host == host]


# --------------------------------------------------------------------------------------------------------
# Stammdaten und Übersicht
# --------------------------------------------------------------------------------------------------------
def test_seed_reference_is_idempotent_and_describe(db):
    seed_reference(db)
    seed_reference(db)
    db.commit()
    assert db.execute(sql("SELECT count(*) FROM stat_dataset")).scalar() == len(DATASETS) == 6
    assert db.execute(sql("SELECT count(*) FROM stat_indicator")).scalar() == len(INDICATORS) == 9
    ds = {r["key"]: r for r in db.execute(sql("SELECT * FROM stat_dataset")).mappings()}
    assert all(d["licence"] and d["licence_url"] and d["attribution"] and d["landing_url"] and d["notes"] for d in ds.values())
    assert "dl-de/by-2-0" in ds["vg250"]["licence"] and "Jahr des letzten Datenbezugs" in ds["vg250"]["attribution"]
    assert "keine offene Datenlizenz" in ds["ba_berufe"]["licence"] and "gewerbliche" in ds["ba_berufe"]["licence"]
    assert "Genesis-Online" in ds["bevoelkerung_kreise_alter"]["attribution"] and "by-2-0" in ds["bevoelkerung_kreise_alter"]["attribution"]
    ind = {r["key"]: r for r in db.execute(sql("SELECT * FROM stat_indicator")).mappings()}
    assert ind["arbeitslose"]["unit"] == "Personen" and ind["arbeitslosenquote_alle_zivilen_ep"]["unit"] == "%"
    assert "zivilen Erwerbspersonen" in ind["arbeitslosenquote_alle_zivilen_ep"]["definition"]
    assert "Eigene Berechnung aus den Altersgruppen" in ind["bev_15_bis_unter_65"]["definition"]
    assert ind["arbeitsuchende_beruf"]["dataset_key"] == "ba_berufe" and ind["bev_altersgruppe"]["population_group"]

    info = {d["key"]: d for d in describe()}
    assert list(info) == ["vg250", "gv_isys", "kldb2010", "ba_arbeitslose_kreise", "ba_berufe", "bevoelkerung_kreise_alter"]
    assert info["vg250"]["auto_enabled"] is True and info["vg250"]["last_release"] is None
    for key in ("kldb2010", "ba_arbeitslose_kreise", "ba_berufe"):
        assert info[key]["auto_enabled"] is True and info[key]["auto_disabled_reason"] is None
    assert all(d["discovery"] and d["publisher"] and d["name"] and d["manual_file"] for d in info.values())


# --------------------------------------------------------------------------------------------------------
# Auffinden auf den offiziellen Seiten (Seitenaufbau nachgestellt)
# --------------------------------------------------------------------------------------------------------
def _ba_item(href: str, text: str) -> str:
    return (f'<div class="c-teaser-search-result statisticdocument"><h3 class="c-teaser-search-result__header">'
            f'<a class="c-teaser-search-result__title" href="{href}" target="blank">\n {text}</a></h3></div>')


def test_discovery_parsers_on_synthetic_pages():
    base = "https://statistik.arbeitsagentur.de/Statistikdaten/Detail"
    kreise_html = "<html><body>" + _ba_item(
        f"{base}/Aktuell/iiia4/gemeinde-arbeitslose-quoten/arbeitslose-quoten-dlk-0-zip.zip?__blob=publicationFile&amp;v=3",
        "März 2024 –  Deutschland, Länder und Kreise (Aktuelle Ausgabe)") + _ba_item(
        f"{base}/202312/iiia4/gemeinde-arbeitslose-quoten/arbeitslose-quoten-dlk-0-202312-zip.zip?__blob=publicationFile&amp;v=1",
        "Dezember 2023 – Deutschland, Länder und Kreise") + "</body></html>"
    c = discovery.ba_kreise(kreise_html, DATASET_BY_KEY["ba_arbeitslose_kreise"].landing_url)
    assert c.url.endswith("arbeitslose-quoten-dlk-0-zip.zip?__blob=publicationFile&v=3") and c.period_hint == "März 2024"
    assert c.name == "arbeitslose-quoten-dlk-0-zip.zip"
    with pytest.raises(ImportProblem, match="nicht eindeutig gefunden"):
        discovery.ba_kreise(kreise_html.replace("(Aktuelle Ausgabe)", ""), "https://statistik.arbeitsagentur.de/x")

    def berufe(yyyymm: str, label: str) -> str:
        return _ba_item(f"{base}/{yyyymm}/iiia4/berufe-heft-kldb2010/berufe-heft-kldb2010-dwol-0-{yyyymm}-xlsx.xlsx?__blob=publicationFile&amp;v=1", label)

    html = berufe("202402", "Februar 2024 – Deutschland, West/Ost und Länder") + berufe("202403", "März 2024 – Deutschland, West/Ost und Länder")
    c = discovery.ba_berufe(html, DATASET_BY_KEY["ba_berufe"].landing_url)
    assert "/202403/" in c.url and c.period_hint == "2024-03"  # jüngster Monat laut Datei-URL, nie eine geratene URL
    with pytest.raises(ImportProblem, match="unterschiedliche Monate"):
        discovery.ba_berufe(berufe("202403", "Februar 2024 – Deutschland, West/Ost und Länder"), "https://statistik.arbeitsagentur.de/x")
    with pytest.raises(ImportProblem, match="kein Verweis"):
        discovery.ba_berufe("<html></html>", "https://statistik.arbeitsagentur.de/x")

    c = discovery.vg250(VG_HTML, VG.landing_url)
    assert (c.url, c.period_hint, c.published_on) == (VG_FILE, "31.12.2023", date(2024, 6, 5))
    with pytest.raises(ImportProblem, match="Aktualitätsstand"):
        discovery.vg250(VG_HTML.replace("Aktualitätsstand", "Stand"), VG.landing_url)
    with pytest.raises(ImportProblem, match="geopackage"):
        discovery.vg250(VG_HTML.replace("gpkg", "gdb"), VG.landing_url)

    url, stand = discovery.gv_isys_publication_page(GV_LANDING_HTML, GV.landing_url)
    assert (url, stand) == (GV_PUB, date(2024, 3, 31))  # der Platz mit dem jüngsten Datum, nicht der erste
    assert discovery.gv_isys_file(GV_PUB_HTML, GV_PUB, stand).url == GV_FILE
    with pytest.raises(ImportProblem):
        discovery.gv_isys_file("<a class='downloadLink' href='/x.pdf'>x</a>", GV_PUB)

    kl = "https://statistik.arbeitsagentur.de/DE/Statischer-Content/Grundlagen/Klassifikationen/Klassifikation-der-Berufe/KldB2010-Fassung2020/Systematik-Verzeichnisse/Generische-Publikationen"
    html = (f'<main><a class="download FTxlsx" href="{kl}/Systematisches-Verzeichnis-KldB-2020.xlsx?__blob=publicationFile&amp;v=1">S</a>'
            f'<a class="download FTxlsx" href="{kl}/Alphabetisches-Verzeichnis-Berufsbenennungen.xlsx?__blob=publicationFile&amp;v=2">A</a>'
            f'<a class="download FTxls" href="{kl}/Berufssektoren-und-Segmente-KldB2010-ueF2020.xls?__blob=publicationFile&amp;v=1">B</a></main>')
    found = discovery.kldb(html, DATASET_BY_KEY["kldb2010"].landing_url)
    assert [c.slot for c in found] == ["systematik", "alphabet"] and found[1].url.endswith("v=2")


# --------------------------------------------------------------------------------------------------------
# run_imports
# --------------------------------------------------------------------------------------------------------
def test_ba_datasets_are_skipped_when_explicitly_disabled(db, monkeypatch):
    monkeypatch.setattr(get_settings(), "stats_ba_auto", False)
    calls = install_http(monkeypatch, lambda r: httpx.Response(500))
    res = run_imports(["ba_arbeitslose_kreise", "ba_berufe", "kldb2010"])
    assert set(res) == {"ba_arbeitslose_kreise", "ba_berufe", "kldb2010"}
    for key, r in res.items():
        assert r["status"] == "skipped"
        assert "statistik.arbeitsagentur.de" in r["reason"] and "WF_STATS_BA_AUTO=false" in r["reason"]
        assert DATASET_BY_KEY[key].landing_url in r["reason"] and "importiert werden" in r["reason"]
    assert calls == []  # es wurde nichts abgerufen
    assert run_imports(["gibt_es_nicht"])["gibt_es_nicht"]["status"] == "failed"


def test_auto_import_discovers_downloads_and_respects_conditional_get(db, tmp_path, monkeypatch, small_thresholds):  # noqa: F811
    gv_file = syn.gv_isys_xlsx(tmp_path / "SYNTHETISCH_gv.xlsx", date(2024, 3, 31), [
        {"ags": "91001000", "name": "Testhausen, Stadt", "pop": 100, "plz": "99001", "lon": "8,5", "lat": "51,4"}]).read_bytes()
    vg_file = syn.vg250_gpkg(tmp_path / "SYNTHETISCH_vg.zip", as_zip=True).read_bytes()
    state = {"vg_page_status": 200}

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url == VG.landing_url:
            return httpx.Response(state["vg_page_status"], text=VG_HTML)
        if url == VG_FILE:
            if request.headers.get("if-none-match") == '"vg-1"':
                return httpx.Response(304)
            return httpx.Response(200, content=vg_file, headers={"ETag": '"vg-1"', "Last-Modified": "Wed, 05 Jun 2024 10:00:00 GMT"})
        if url == GV.landing_url:
            return httpx.Response(200, text=GV_LANDING_HTML)
        if url == GV_PUB:
            return httpx.Response(200, text=GV_PUB_HTML)
        if url == GV_FILE:
            if request.headers.get("if-none-match") == '"gv-1"':
                return httpx.Response(304)
            return httpx.Response(200, content=gv_file, headers={"ETag": '"gv-1"'})
        return httpx.Response(404)

    calls = install_http(monkeypatch, handler)
    beats: list[int] = []
    res = run_imports(["vg250", "gv_isys"], heartbeat=lambda: beats.append(1))
    assert res["vg250"]["status"] == "imported" and res["vg250"]["period_key"] == "2023-12-31" and res["vg250"]["import_method"] == "auto"
    assert res["gv_isys"]["status"] == "imported" and res["gv_isys"]["places_enriched"] == 1
    assert len(beats) >= 4
    rel = {r["dataset_key"]: r for r in db.execute(sql("SELECT * FROM stat_release")).mappings()}
    assert rel["vg250"]["file_url"] == VG_FILE and rel["vg250"]["import_method"] == "auto"
    assert rel["vg250"]["published_on"] == date(2024, 6, 5)  # nur weil die Produktseite das Datum der Datenaktualisierung nennt
    assert rel["gv_isys"]["file_url"] == GV_FILE and rel["gv_isys"]["published_on"] is None
    assert paths(calls, "www.destatis.de") == ["robots.txt", "_inhalt.html", "AuszugGV1QAktuell.html", "AuszugGV1QAktuell.xlsx"]
    assert all("WorkForceBot" in c.headers["user-agent"] for c in calls)
    info = {d["key"]: d for d in describe()}
    assert info["vg250"]["last_release"]["period_key"] == "2023-12-31" and info["vg250"]["last_release"]["revision"] == 1
    assert info["vg250"]["last_check"]["last_status"] == "imported"

    # zweiter Lauf (ausdrücklich angefordert): Seiten werden geprüft, die Dateien aber nur bedingt abgerufen → 304
    calls.clear()
    res = run_imports(["vg250", "gv_isys"])
    assert res["vg250"]["status"] == "unchanged" and "304" in res["vg250"]["message"]
    assert res["gv_isys"]["status"] == "unchanged"
    assert [c.headers.get("if-none-match") for c in calls if str(c.url) in (VG_FILE, GV_FILE)] == ['"vg-1"', '"gv-1"']
    assert db.execute(sql("SELECT count(*) FROM stat_release")).scalar() == 2

    # geplanter Lauf (ohne Auswahl): selten erscheinende Datensätze werden nicht täglich geprüft; BA bleibt aus
    monkeypatch.setattr(get_settings(), "stats_ba_auto", False)
    calls.clear()
    monkeypatch.setattr(genesis_ui, "export_flat_csv", lambda *a, **k: (_ for _ in ()).throw(genesis_ui.UiError("kein Browser im Test")))
    res = run_imports()
    assert list(res) == ["vg250", "gv_isys", "kldb2010", "ba_arbeitslose_kreise", "ba_berufe", "bevoelkerung_kreise_alter"]
    assert res["vg250"]["status"] == "skipped" and "höchstens alle 7 Tage" in res["vg250"]["reason"]
    assert res["gv_isys"]["status"] == "unchanged" and res["ba_berufe"]["status"] == "skipped"
    assert res["bevoelkerung_kreise_alter"]["status"] == "failed"
    assert not [c for c in calls if c.url.host.endswith("bkg.bund.de") or c.url.host.endswith("arbeitsagentur.de")]


def test_one_failing_dataset_does_not_stop_the_others(db, tmp_path, monkeypatch, small_thresholds):  # noqa: F811
    gv_file = syn.gv_isys_xlsx(tmp_path / "SYNTHETISCH_gv.xlsx", date(2024, 3, 31), [
        {"ags": "91001000", "name": "Testhausen, Stadt", "pop": 100, "plz": "99001", "lon": "8,5", "lat": "51,4"}]).read_bytes()

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url == VG.landing_url:
            return httpx.Response(200, text="<html>Seite umgebaut</html>")  # Verweis fehlt → Prüfproblem
        if url == GV.landing_url:
            return httpx.Response(200, text=GV_LANDING_HTML)
        if url == GV_PUB:
            return httpx.Response(200, text=GV_PUB_HTML)
        if url == GV_FILE:
            return httpx.Response(200, content=gv_file)
        return httpx.Response(404)

    install_http(monkeypatch, handler)
    monkeypatch.setattr(genesis_ui, "export_flat_csv", lambda *a, **k: (_ for _ in ()).throw(genesis_ui.UiError("Oberfläche nicht erreichbar (Test)")))
    res = run_imports(["vg250", "gv_isys", "bevoelkerung_kreise_alter"])
    assert res["vg250"]["status"] == "failed" and "nicht eindeutig gefunden" in res["vg250"]["error"]
    assert res["gv_isys"]["status"] == "imported"
    assert res["bevoelkerung_kreise_alter"]["status"] == "failed" and "GENESIS-Online" in res["bevoelkerung_kreise_alter"]["error"]
    assert "Regionaldatenbank" in res["bevoelkerung_kreise_alter"]["error"]  # beide Wege wurden versucht
    assert db.execute(sql("SELECT dataset_key FROM stat_release")).scalars().all() == ["gv_isys"]
    state = db.execute(sql("SELECT value FROM app_state WHERE key = 'stats_import:vg250'")).scalar()
    assert state["last_status"] == "failed" and "last_success_at" not in state


def test_ba_auto_by_default_and_no_hammering_on_429(db, tmp_path, monkeypatch):
    assert get_settings().stats_ba_auto is True
    spec = DATASET_BY_KEY["ba_berufe"]
    file_url = ("https://statistik.arbeitsagentur.de/Statistikdaten/Detail/202403/iiia4/berufe-heft-kldb2010/"
                "berufe-heft-kldb2010-dwol-0-202403-xlsx.xlsx?__blob=publicationFile&v=1")
    page = "<html><body><!-- SYNTHETISCH -->" + _ba_item(file_url.replace("&", "&amp;"), "März 2024 – Deutschland, West/Ost und Länder") + "</body></html>"
    data = syn.ba_berufe_xlsx(tmp_path / "SYNTHETISCH_berufe.xlsx", MONTH).read_bytes()
    mode = {"blocked": True}

    def handler(request: httpx.Request) -> httpx.Response:
        if mode["blocked"]:
            return httpx.Response(429, text="Im Moment registrieren wir zu viele Zugriffe")
        if str(request.url) == spec.landing_url:
            return httpx.Response(200, text=page)
        if str(request.url) == file_url:
            return httpx.Response(200, content=data, headers={"ETag": '"b1"'})
        return httpx.Response(404)

    calls = install_http(monkeypatch, handler)
    res = run_imports(["ba_berufe"])
    assert res["ba_berufe"]["status"] == "blocked" and "nicht weiter nachgefasst" in res["ba_berufe"]["error"]
    assert paths(calls) == ["robots.txt", "Einzelheftsuche_Formular.html"]  # genau ein Versuch, kein Nachfassen
    assert db.execute(sql("SELECT count(*) FROM stat_release")).scalar() == 0
    # nach einer Sperre wird der Host eine halbe Stunde lang gar nicht mehr angefragt – auch nicht für andere BA-Datensätze
    mode["blocked"] = False
    calls.clear()
    res = run_imports(["ba_berufe", "ba_arbeitslose_kreise"])
    assert {r["status"] for r in res.values()} == {"skipped"} and "nicht erneut" in res["ba_berufe"]["reason"]
    assert calls == []
    db.execute(sql("UPDATE app_state SET value = jsonb_set(value, '{blocked_until}', '\"2000-01-01T00:00:00+00:00\"') "
                   "WHERE key = 'stats_import:host:statistik.arbeitsagentur.de'"))
    db.commit()
    res = run_imports(["ba_berufe"])
    assert res["ba_berufe"]["status"] == "imported" and res["ba_berufe"]["period_key"] == "2024-03"
    assert res["ba_berufe"]["page_period_hint"] == "2024-03" and res["ba_berufe"]["file_url"] == file_url
    assert paths(calls) == ["Einzelheftsuche_Formular.html", "berufe-heft-kldb2010-dwol-0-202403-xlsx.xlsx"]  # eine Seite + eine Datei
    rel = db.execute(sql("SELECT import_method, file_url, published_on FROM stat_release")).one()
    assert rel == ("auto", file_url, None)


def test_population_auto_uses_ui_export_and_falls_back(db, tmp_path, monkeypatch, small_thresholds):  # noqa: F811
    install_http(monkeypatch, lambda r: httpx.Response(404))
    regions = {"01901": ("Testkreis Alpha (synthetisch)", syn.age_cells(100))}
    used: list[str] = []

    def fake_export(source, dest_dir, settings, fetcher, heartbeat=None):
        used.append(source.key)
        if source.key == "genesis" and fail_primary["on"]:
            raise genesis_ui.UiError("GENESIS-Online: Wartungsfenster (Test)")
        layout = "regio" if source.key == "regionalstatistik" else "genesis"
        stichtag = date(2024, 12, 31) if source.key == "regionalstatistik" and fail_primary["newer"] else date(2023, 12, 31)
        name = f"{source.table_code}_de_flat.zip"
        return syn.genesis_flat(dest_dir / name, stichtag, regions, layout=layout), name

    fail_primary = {"on": False, "newer": False}
    monkeypatch.setattr(genesis_ui, "export_flat_csv", fake_export)
    res = run_imports(["bevoelkerung_kreise_alter"])["bevoelkerung_kreise_alter"]
    assert res["status"] == "imported" and res["source"] == "genesis" and res["period_key"] == "2023-12-31" and used == ["genesis"]
    assert res["file_url"] == "https://genesis.destatis.de/datenbank/online/table/12411-0017/table-toolbar"
    assert db.execute(sql("SELECT import_method, file_url, published_on FROM stat_release")).one() == ("auto", res["file_url"], None)
    # erneuter Abruf derselben Tabelle: gleiche Zeilen → kein neuer Datenstand
    assert run_imports(["bevoelkerung_kreise_alter"])["bevoelkerung_kreise_alter"]["status"] == "unchanged"

    # Hauptquelle gestört, Ausweichquelle liefert denselben Stichtag → nichts übernehmen (keine Scheinrevision)
    fail_primary["on"] = True
    used.clear()
    res = run_imports(["bevoelkerung_kreise_alter"])["bevoelkerung_kreise_alter"]
    assert used == ["genesis", "regionalstatistik"] and res["status"] == "unchanged" and res["source"] == "regionalstatistik"
    assert db.execute(sql("SELECT count(*) FROM stat_release")).scalar() == 1
    # Ausweichquelle hat einen neueren Stichtag → wird importiert und als Ausweichquelle vermerkt
    fail_primary["newer"] = True
    res = run_imports(["bevoelkerung_kreise_alter"])["bevoelkerung_kreise_alter"]
    assert res["status"] == "imported" and res["source"] == "regionalstatistik" and res["period_key"] == "2024-12-31"
    assert any("Ausweichquelle" in w for w in res["warnings"])
    notes = db.execute(sql("SELECT notes FROM stat_release WHERE period_key = '2024-12-31'")).scalar()
    assert "Regionaldatenbank" in notes and "12411-02-03-4" in notes


def test_real_fetcher_settings_are_polite():
    s = get_settings()
    ba = runner.make_fetcher(DATASET_BY_KEY["ba_berufe"], s, RobotsStore())
    gv = runner.make_fetcher(GV, s, RobotsStore())
    try:
        # BA: nur der eigene Host, mindestens 30 s Abstand, kein Nachfassen nach 429/5xx
        assert ba.allowed_domains == ("statistik.arbeitsagentur.de",) and ba.interval >= 30 and ba.settings.http_max_retries == 0
        assert gv.allowed_domains == ("www.destatis.de",) and gv.interval == s.stats_request_interval_seconds >= 5
        assert gv.settings.http_max_retries == 1 and "WorkForceBot" in gv.settings.user_agent
    finally:
        ba.close()
        gv.close()
    for d in DATASETS:  # jede Landing-Page liegt auf einem erlaubten Host des Datensatzes
        assert httpx.URL(d.landing_url).host in d.hosts


def test_robots_policy_for_ui_export(monkeypatch):
    def make(status: int, body: str = "") -> Fetcher:
        return Fetcher(("genesis.destatis.de",), interval_seconds=0, settings=get_settings().model_copy(update={"http_max_retries": 0}),
                       transport=httpx.MockTransport(lambda r: httpx.Response(status, text=body)), sleep=lambda s: None)

    assert genesis_ui.robots_policy(make(404), "genesis.destatis.de").allowed("/datenbank/online/table/x", "WorkForceBot")
    assert not genesis_ui.robots_policy(make(503), "genesis.destatis.de").allowed("/datenbank/online/table/x", "WorkForceBot")
    pol = genesis_ui.robots_policy(make(200, "User-agent: *\nDisallow: /genesis/api/\n"), "genesis.destatis.de")
    assert pol.allowed("/datenbank/online/table/12411-0017/table-toolbar", "WorkForceBot")
    assert not pol.allowed("/genesis/api/rest/tables/12411-0017/download/ffcsv/de", "WorkForceBot")
    assert [s.host for s in genesis_ui.SOURCES] == ["genesis.destatis.de", "www.regionalstatistik.de"]


# --------------------------------------------------------------------------------------------------------
# Fetcher.download
# --------------------------------------------------------------------------------------------------------
def _fetcher(handler: Callable[[httpx.Request], httpx.Response], **settings: Any) -> Fetcher:
    return Fetcher(("daten.example", "www.example"), interval_seconds=0, transport=httpx.MockTransport(handler), sleep=lambda s: None,
                   settings=get_settings().model_copy(update={"http_max_retries": 0, **settings}))


def test_fetcher_download_streams_to_file_with_same_politeness_rules(tmp_path):
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        path = request.url.path
        if path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /privat/\n")
        if path == "/datei.zip":
            if request.headers.get("if-none-match") == '"e1"':
                return httpx.Response(304, headers={"ETag": '"e1"'})
            return httpx.Response(200, content=b"x" * 5000, headers={"ETag": '"e1"', "Last-Modified": "Mon, 01 Jan 2024 00:00:00 GMT"})
        if path == "/umleitung":
            return httpx.Response(302, headers={"Location": "https://daten.example/datei.zip"})
        if path == "/fremd":
            return httpx.Response(302, headers={"Location": "https://boese.invalid/datei.zip"})
        if path == "/zu-viele":
            return httpx.Response(429)
        if path == "/verboten":
            return httpx.Response(403)
        return httpx.Response(404)

    f = _fetcher(handler)
    dest = tmp_path / "ziel" / "datei.zip"
    dest.parent.mkdir()
    res = f.download("https://daten.example/datei.zip", dest)
    assert res.status == 200 and dest.read_bytes() == b"x" * 5000 and res.headers["etag"] == '"e1"' and res.content == b""
    assert list(dest.parent.iterdir()) == [dest]  # keine Teil-Datei bleibt liegen
    assert [r.url.path for r in seen] == ["/robots.txt", "/datei.zip"] and "WorkForceBot" in seen[1].headers["user-agent"]
    # bedingter Abruf
    other = tmp_path / "ziel" / "unveraendert.zip"
    res = f.download("https://daten.example/datei.zip", other, if_none_match='"e1"')
    assert res.not_modified and res.status == 304 and not other.exists()
    # geprüfte Weiterleitung innerhalb der erlaubten Domains – und Abbruch bei fremdem Ziel
    assert f.download("https://www.example/umleitung", other).status == 200 and other.read_bytes() == b"x" * 5000
    with pytest.raises(TargetForbidden):
        f.download("https://www.example/fremd", tmp_path / "ziel" / "fremd.zip")
    with pytest.raises(TargetForbidden):
        f.download("https://boese.invalid/datei.zip", tmp_path / "ziel" / "fremd.zip")
    # Größenbegrenzung, robots.txt, Sperrsignale; 404 wird als Ergebnis ohne Datei geliefert
    with pytest.raises(FetchError, match="maximale Größe"):
        f.download("https://daten.example/datei.zip", tmp_path / "ziel" / "gross.zip", max_bytes=1000)
    with pytest.raises(RobotsDisallowed):
        f.download("https://daten.example/privat/datei.zip", tmp_path / "ziel" / "privat.zip")
    with pytest.raises(BlockedError):
        f.download("https://daten.example/zu-viele", tmp_path / "ziel" / "x.zip")
    with pytest.raises(BlockedError):
        f.download("https://daten.example/verboten", tmp_path / "ziel" / "x.zip")
    assert f.download("https://daten.example/fehlt.zip", tmp_path / "ziel" / "fehlt.zip").status == 404
    assert sorted(p.name for p in dest.parent.iterdir()) == ["datei.zip", "unveraendert.zip"]
    f.close()
    # Standardgrenze kommt aus der Konfiguration (WF_STATS_MAX_DOWNLOAD_BYTES)
    small = _fetcher(handler, stats_max_download_bytes=100)
    with pytest.raises(FetchError, match="maximale Größe"):
        small.download("https://daten.example/datei.zip", tmp_path / "ziel" / "gross.zip")
    small.close()
