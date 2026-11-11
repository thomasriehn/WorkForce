"""Stammdaten der Statistik-Datensätze und Kennzahlen (Lizenz, Quellenangabe, Definitionen).

Die Texte zu Lizenz und Quellenangabe folgen den Angaben der Herausgeber (Impressum der Dateien, Nutzungsbedingungen,
Lizenzseiten; geprüft am 10.11.2026). Die BA-Statistik stellt ihre Daten **nicht** unter eine offene Lizenz.
"""
from __future__ import annotations

from dataclasses import dataclass

BA_HOST = "statistik.arbeitsagentur.de"
BA_LICENCE = (
    "© Statistik der Bundesagentur für Arbeit – keine offene Datenlizenz. Laut Impressum der Dateien: Informationen "
    "dürfen gespeichert und (auch auszugsweise) mit Quellenangabe weitergegeben, vervielfältigt und verbreitet werden; "
    "die Inhalte dürfen nicht verändert oder verfälscht werden; eigene Berechnungen sind erlaubt, aber als solche "
    "kenntlich zu machen; bei Zugänglichmachung im Internet soll auf die Homepage der Statistik der BA verlinkt werden; "
    "die Nutzung für gewerbliche Zwecke (ausgenommen Presse, Rundfunk und Fernsehen, wissenschaftliche Publikationen) "
    "bedarf der Genehmigung der Statistik der Bundesagentur für Arbeit.")
KLDB_LICENCE = (
    "© Statistik der Bundesagentur für Arbeit – keine offene Datenlizenz. Systematisches Verzeichnis (Impressum 2020): "
    "Speichern und Weitergabe mit Quellenangabe erlaubt, Inhalte dürfen nicht verändert werden, eigene Berechnungen sind "
    "zu kennzeichnen, gewerbliche Nutzung (außer Presse, Rundfunk und Fernsehen, Wissenschaft) nur mit Genehmigung. "
    "Alphabetisches Verzeichnis (Impressum 2026): „Daten und Tabellen dürfen uneingeschränkt verwendet werden. "
    "Informationen dürfen (auch auszugsweise) gespeichert und mit Quellenangabe weitergegeben, vervielfältigt und "
    "verbreitet werden. Die Inhalte dürfen nicht verändert oder verfälscht werden. Eigene Berechnungen sind erlaubt, "
    "jedoch als solche kenntlich zu machen.“ Bei Veröffentlichung im Internet soll auf die Homepage der Statistik der BA "
    "verlinkt werden.")
BA_LICENCE_URL = ("https://statistik.arbeitsagentur.de/DE/Statischer-Content/Servicebereich-Navigation/"
                  "Hinweise-Quellenangabe-Zitierung.pdf?__blob=publicationFile&v=1")
BA_AUTO_NOTE = (
    "Automatischer Abruf ist standardmäßig aktiv (WF_STATS_BA_AUTO=true) und benötigt WF_CRAWLER_CONTACT. "
    "Mit WF_STATS_BA_AUTO=false abschaltbar; manueller Dateiimport bleibt verfügbar. "
    "Die allgemeinen Nutzungsbedingungen der BA (Nr. 2a (3)) und die Nutzungshinweise der Statistik sind zu beachten.")
DL_DE = "Datenlizenz Deutschland – Namensnennung – Version 2.0 (dl-de/by-2-0)"
DL_DE_URL = "https://www.govdata.de/dl-de/by-2-0"


@dataclass(frozen=True)
class Dataset:
    key: str
    name: str
    publisher: str
    dataset_code: str | None
    landing_url: str
    licence: str
    licence_url: str
    attribution: str
    update_cycle: str
    notes: str
    hosts: tuple[str, ...]          # erlaubte Hosts für den automatischen Abruf
    discovery: str                  # wie die neueste Datei gefunden wird (für die Oberfläche)
    min_check_days: int = 1         # Mindestabstand geplanter Prüfungen
    file_hint: str = ""             # welche Datei beim manuellen Import erwartet wird

    @property
    def ba_host(self) -> bool:
        return any(h == BA_HOST or h.endswith("." + BA_HOST) for h in self.hosts)


@dataclass(frozen=True)
class Indicator:
    key: str
    name: str
    unit: str
    dataset_key: str
    definition: str
    population_group: str | None = None


DATASETS: tuple[Dataset, ...] = (
    Dataset(
        key="vg250",
        name="Verwaltungsgebiete 1:250 000, Stand 31.12. (VG250)",
        publisher="Bundesamt für Kartographie und Geodäsie (BKG)",
        dataset_code="vg250_ebenen_1231",
        landing_url=("https://gdz.bkg.bund.de/index.php/default/digitale-geodaten/verwaltungsgebiete/"
                     "verwaltungsgebiete-1-250-000-stand-31-12-vg250-31-12.html"),
        licence=DL_DE,
        licence_url=DL_DE_URL,
        attribution=("© BKG ({jahr}) dl-de/by-2-0 (Daten verändert), Datenquellen: "
                     "https://sgx.geodatenzentrum.de/web_public/gdz/datenquellen/datenquellen_vg_nuts.pdf"),
        update_cycle="yearly",
        notes=("Länder- und Kreisgrenzen sowie Gemeinden (Ortsreferenz). Nur Landflächen (Geofaktor GF = 4); Geometrien "
               "nach WGS 84 transformiert und für die Karte vereinfacht (Veränderungshinweis im Quellenvermerk). "
               "Bei der Darstellung auf einer Webseite sind „BKG“ mit https://www.bkg.bund.de und „dl-de/by-2-0“ mit "
               "https://www.govdata.de/dl-de/by-2-0 zu verlinken. Jahr im Quellenvermerk = Jahr des letzten Datenbezugs. "
               "Gemeindekoordinaten sind ein Punkt auf der Gemeindefläche (angenäherter Ortsmittelpunkt). Die Variante "
               "VG250-EW (mit Einwohnerzahlen, Attribut EWZ) wird beim manuellen Import ebenfalls verstanden."),
        hosts=("gdz.bkg.bund.de", "daten.gdz.bkg.bund.de"),
        discovery=("Produktseite des BKG: Direktdownload-Link „…/aktuell/vg250_12-31.utm32s.gpkg.ebenen.zip“ und Angabe "
                   "„Aktualitätsstand“; Abruf nur, wenn sich die Datei geändert hat (ETag/Last-Modified)."),
        min_check_days=7,
        file_hint="ZIP „vg250_12-31.utm32s.gpkg.ebenen.zip“ oder die enthaltene Datei DE_VG250.gpkg",
    ),
    Dataset(
        key="gv_isys",
        name="Gemeindeverzeichnis GV-ISys: Alle politisch selbständigen Gemeinden mit ausgewählten Merkmalen (Quartalsausgabe)",
        publisher="Statistisches Bundesamt (Destatis)",
        dataset_code="GV-ISys Auszug GV (Quartal)",
        landing_url="https://www.destatis.de/DE/Themen/Laender-Regionen/Regionales/Gemeindeverzeichnis/_inhalt.html",
        licence=("© Statistisches Bundesamt (Destatis) – Vervielfältigung und Verbreitung, auch auszugsweise, mit "
                 "Quellenangabe gestattet; Änderungen und Auszüge sind kenntlich zu machen."),
        licence_url="https://www.destatis.de/DE/Service/Impressum/copyright-allgemein.html",
        attribution=("Quelle: Gemeindeverzeichnis-Informationssystem GV-ISys, Alle politisch selbständigen Gemeinden mit "
                     "ausgewählten Merkmalen (Quartalsausgabe), Statistisches Bundesamt (Destatis); Auszug, eigene Darstellung"),
        update_cycle="quarterly",
        notes=("Ergänzt die Ortsreferenz um Einwohnerzahl und Postleitzahl. Einschränkung: Die Datei nennt je Gemeinde nur "
               "die PLZ des Verwaltungssitzes – weitere Postleitzahlen einer Gemeinde und Ortsteile fehlen; die "
               "PLZ-Zuordnung ist daher unvollständig. Der Gebietsstand ist meist jünger als der der Kreisgeometrien; "
               "Einträge mit Kreisschlüsseln außerhalb des geladenen Gebietsstands werden nicht übernommen, sondern gemeldet. "
               "Koordinaten stammen laut Destatis aus dem DLM250 des BKG und werden nur genutzt, wo VG250 keine liefert."),
        hosts=("www.destatis.de",),
        discovery=("Themenseite „Gemeindeverzeichnis“: Verweis auf die Quartalsausgabe mit dem jüngsten Datum, dort der "
                   "Download-Link „…AuszugGV<n>QAktuell.xlsx?__blob=publicationFile&v=…“."),
        min_check_days=1,
        file_hint="XLSX „AuszugGV<n>QAktuell.xlsx“",
    ),
    Dataset(
        key="kldb2010",
        name="Klassifikation der Berufe 2010 – überarbeitete Fassung 2020 (systematisches und alphabetisches Verzeichnis)",
        publisher="Bundesagentur für Arbeit, Statistik",
        dataset_code="KldB 2010/2020",
        landing_url=("https://statistik.arbeitsagentur.de/DE/Navigation/Grundlagen/Klassifikationen/"
                     "Klassifikation-der-Berufe/KldB2010-Fassung2020/Systematik-Verzeichnisse/Systematik-Verzeichnisse-Nav.html"),
        licence=KLDB_LICENCE,
        licence_url=BA_LICENCE_URL,
        attribution=("Quelle: Statistik der Bundesagentur für Arbeit, Klassifikation der Berufe 2010 – überarbeitete Fassung "
                     "2020 (systematisches Verzeichnis; alphabetisches Verzeichnis der Berufsbenennungen); "
                     "https://statistik.arbeitsagentur.de"),
        update_cycle="irregular",
        notes=("Systematik (1- bis 5-Steller) und Berufsbenennungen für die Zuordnung von Anzeigentiteln. Die Zuordnung "
               "einer Anzeige zu einem Schlüssel ist eine eigene, regelbasierte Auswertung. " + BA_AUTO_NOTE),
        hosts=(BA_HOST,),
        discovery=("Seite „KldB 2010 – überarbeitete Fassung 2020 / Systematik und Verzeichnisse“: Download-Verweise auf "
                   "„Systematisches-Verzeichnis-KldB-2020.xlsx“ und „Alphabetisches-Verzeichnis-Berufsbenennungen.xlsx“; "
                   "der Stand wird dem Erstellungsdatum in der Datei entnommen."),
        min_check_days=7,
        file_hint="XLSX des systematischen oder des alphabetischen Verzeichnisses (einzeln importieren)",
    ),
    Dataset(
        key="ba_arbeitslose_kreise",
        name="Arbeitslose und Arbeitslosenquoten – Deutschland, Länder, Kreise und Gemeinden (Zeitreihe Monats- und Jahreszahlen)",
        publisher="Statistik der Bundesagentur für Arbeit",
        dataset_code="gemeinde-arbeitslose-quoten",
        landing_url=("https://statistik.arbeitsagentur.de/SiteGlobals/Forms/Suche/Einzelheftsuche/"
                     "Einzelheftsuche_Formular.html?nn=37528&pageNo=0&queryResultId=null&submit=Suchen"
                     "&topic_f=gemeinde-arbeitslose-quoten"),
        licence=BA_LICENCE,
        licence_url=BA_LICENCE_URL,
        attribution=("Quelle: Statistik der Bundesagentur für Arbeit, Arbeitslose und Arbeitslosenquoten – Deutschland, "
                     "Länder, Kreise und Gemeinden (Zeitreihe Monats- und Jahreszahlen); https://statistik.arbeitsagentur.de"),
        update_cycle="monthly",
        notes=("Übernommen wird je Monatsausgabe nur der Berichtsmonat (Rechtskreis insgesamt) für Deutschland, Länder und "
               "Kreise; Gebietsstand = Datenstand der Ausgabe. Das Produkt enthält keine Arbeitsuchenden; ein öffentliches "
               "Kreisprodukt mit Arbeitsuchenden ließ sich nicht belegen. Arbeitsuchende für Deutschland und die Länder "
               "liefert der Datensatz „Arbeitsmarkt nach Berufen“ (Zeile Insgesamt). "
               "Zeichen: * anonymisiert, x keine Quote veröffentlicht (unter 15.000 zivile Erwerbspersonen), … Angabe "
               "fällt später an. " + BA_AUTO_NOTE),
        hosts=(BA_HOST,),
        discovery=("Ergebnisliste der Einzelheftsuche: erster Eintrag „(Aktuelle Ausgabe)“ mit Verweis auf "
                   "„…/Aktuell/iiia4/gemeinde-arbeitslose-quoten/arbeitslose-quoten-dlk-0-zip.zip“; der Berichtsmonat wird "
                   "aus der Datei gelesen."),
        min_check_days=1,
        file_hint="ZIP „arbeitslose-quoten-dlk-0-zip.zip“ (enthält beide Arbeitsmappen)",
    ),
    Dataset(
        key="ba_berufe",
        name="Arbeitsmarkt nach Berufen (KldB 2010) – Deutschland, West/Ost und Länder (Monatszahlen)",
        publisher="Statistik der Bundesagentur für Arbeit",
        dataset_code="berufe-heft-kldb2010",
        landing_url=("https://statistik.arbeitsagentur.de/SiteGlobals/Forms/Suche/Einzelheftsuche_Formular.html"
                     "?topic_f=berufe-heft-kldb2010"),
        licence=BA_LICENCE,
        licence_url=BA_LICENCE_URL,
        attribution=("Quelle: Statistik der Bundesagentur für Arbeit, Arbeitsmarkt nach Berufen (KldB 2010) – Deutschland, "
                     "West/Ost und Länder (Monatszahlen); https://statistik.arbeitsagentur.de"),
        update_cycle="monthly",
        notes=("Das Produkt gibt es nur für Deutschland, West/Ost und die Länder – nicht für Kreise (Kreisdaten nach Berufen "
               "gibt die BA nur als Sonderauswertung ab). Es werden keine Kreiswerte geschätzt oder verteilt. Übernommen: "
               "Bestand im Berichtsmonat für Deutschland und die 16 Länder; Insgesamt, Berufshauptgruppen (2-Steller) und "
               "Berufsgruppen (3-Steller) über alle Anforderungsniveaus sowie Berufsgattungen (5-Steller, ohne Helfer). "
               "Die Arbeitsuchenden der Zeile „Insgesamt“ stehen zusätzlich als Kennzahl „Arbeitsuchende“ bereit. "
               "Die Liste der Berufe ist je Region unvollständig (nur Kategorien mit ausreichender Fallzahl). Zeichen: "
               "* anonymisiert, x nicht sinnvoll, - nichts vorhanden (echter Nullwert). " + BA_AUTO_NOTE),
        hosts=(BA_HOST,),
        discovery=("Ergebnisliste der Einzelheftsuche: erster Eintrag (jüngster Monat) mit Verweis auf "
                   "„…/<JJJJMM>/iiia4/berufe-heft-kldb2010/berufe-heft-kldb2010-dwol-0-<JJJJMM>-xlsx.xlsx“."),
        min_check_days=1,
        file_hint="XLSX „berufe-heft-kldb2010-dwol-0-<JJJJMM>-xlsx.xlsx“",
    ),
    Dataset(
        key="bevoelkerung_kreise_alter",
        name="Bevölkerung: Kreise, Stichtag, Altersgruppen (Fortschreibung des Bevölkerungsstandes, Tabelle 12411-0017)",
        publisher="Statistisches Bundesamt (Destatis), GENESIS-Online",
        dataset_code="12411-0017",
        landing_url="https://genesis.destatis.de/datenbank/online/table/12411-0017/table-toolbar",
        licence=DL_DE,
        licence_url=DL_DE_URL,
        attribution=("Datenquelle: Statistisches Bundesamt (Destatis), Genesis-Online, Tabelle 12411-0017 "
                     "(https://genesis.destatis.de/datenbank/online/table/12411-0017); Datenlizenz by-2-0 "
                     "(www.govdata.de/dl-de/by-2-0); eigene Berechnung/eigene Darstellung"),
        update_cycle="yearly",
        notes=("Bevölkerungsstand am 31.12. nach 17 Altersgruppen je Kreis. „Bevölkerung 15 bis unter 65 Jahre“ ist eine "
               "eigene Berechnung aus den Altersgruppen und wird nur gespeichert, wenn die Gruppen den Bereich lückenlos "
               "abdecken und kein benötigter Wert fehlt. Ausweichquelle bei Störung: Regionaldatenbank Deutschland, Tabelle "
               "12411-02-03-4 (https://www.regionalstatistik.de/datenbank/online/table/12411-02-03-4) – dann lautet die "
               "Quellenangabe „Datenquelle: Statistische Ämter des Bundes und der Länder, Deutschland, Regionaldatenbank "
               "Deutschland, Tabelle 12411-02-03-4; Datenlizenz Deutschland – Namensnennung – Version 2.0 "
               "(www.govdata.de/dl-de/by-2-0); eigene Berechnung“; welche Quelle ein Datenstand hat, steht in dessen Vermerk. "
               "Die Tabellen führen auch aufgelöste Kreise (dort „-“ = am Stichtag nicht vorhanden). Abrufdatum = "
               "„abgerufen am“ des Datenstands; ein Veröffentlichungsdatum nennen die Tabellen nicht."),
        hosts=("genesis.destatis.de", "www.regionalstatistik.de"),
        discovery=("Öffentliche Tabellenansicht (JavaScript-Anwendung) wird im Browser geöffnet: Schaltfläche „Download“ → "
                   "„CSV (Flat)“ für den voreingestellten jüngsten Stichtag. Keine Anmeldung, keine API. Ausweichweg: "
                   "dieselbe Oberfläche der Regionaldatenbank Deutschland (Tabelle 12411-02-03-4)."),
        min_check_days=7,
        file_hint="ZIP oder CSV des Exports „CSV (Flat)“ (12411-0017_de_flat.zip bzw. 12411-02-03-4_de_flat.zip)",
    ),
)

_ALO_DEF = (
    "Arbeitslose sind laut BA-Statistik Personen, die vorübergehend nicht in einem Beschäftigungsverhältnis stehen oder nur "
    "eine weniger als 15 Stunden wöchentlich umfassende Beschäftigung ausüben, eine versicherungspflichtige, mindestens "
    "15 Stunden wöchentlich umfassende Beschäftigung suchen, den Vermittlungsbemühungen zur Verfügung stehen, in Deutschland "
    "wohnen, mindestens 15 Jahre alt sind und die Altersgrenze für den Renteneintritt noch nicht erreicht haben und sich "
    "persönlich arbeitslos gemeldet haben (§ 16 SGB III, für das SGB II sinngemäß).")
_ASU_DEF = (
    "Arbeitsuchende sind laut BA-Statistik Personen, die eine versicherungspflichtige, mindestens 15 Stunden wöchentlich "
    "umfassende Beschäftigung suchen, sich wegen der Vermittlung bei einer Agentur für Arbeit oder einem Jobcenter gemeldet "
    "haben und die angestrebte Tätigkeit ausüben können und dürfen – auch wenn sie bereits beschäftigt oder selbständig sind "
    "(§ 15 SGB III). Sie umfassen arbeitslose und nichtarbeitslose Arbeitsuchende und sind damit eine andere, größere Gruppe "
    "als die Arbeitslosen.")
_BERUF_NOTE = (
    " Gliederung nach dem Zielberuf (KldB 2010, überarbeitete Fassung 2020): dim_key = '' für alle Berufe, 2-/3-Steller über "
    "alle Anforderungsniveaus, 5-Steller = Berufsgattung. Nur Deutschland und Länder; die Liste der Berufe ist je Region "
    "unvollständig.")

INDICATORS: tuple[Indicator, ...] = (
    Indicator("arbeitslose", "Arbeitslose (Bestand)", "Personen", "ba_arbeitslose_kreise",
              "Bestand an Arbeitslosen im Berichtsmonat, Rechtskreise SGB III und SGB II zusammen. " + _ALO_DEF
              + " Arbeitslose sind nicht mit Arbeitsuchenden gleichzusetzen.",
              "Arbeitslose (registriert bei Agentur für Arbeit oder Jobcenter)"),
    Indicator("arbeitslosenquote_alle_zivilen_ep", "Arbeitslosenquote bezogen auf alle zivilen Erwerbspersonen", "%",
              "ba_arbeitslose_kreise",
              "Arbeitslose in Prozent aller zivilen Erwerbspersonen (Rechtskreis insgesamt), wie von der BA-Statistik "
              "veröffentlicht – keine eigene Berechnung. Für Regionen mit weniger als 15.000 zivilen Erwerbspersonen "
              "veröffentlicht die BA keine Quote (Status „nicht verfügbar“).",
              "alle zivilen Erwerbspersonen (Bezugsgröße der BA)"),
    Indicator("arbeitsuchende", "Arbeitsuchende (Bestand)", "Personen", "ba_berufe",
              "Bestand an Arbeitsuchenden im Berichtsmonat (alle Zielberufe; Zeile „Insgesamt“ des Hefts „Arbeitsmarkt nach "
              "Berufen“). " + _ASU_DEF + " Verfügbar nur für Deutschland und die Länder: Ein öffentliches Kreisprodukt mit "
              "Arbeitsuchenden ließ sich nicht belegen; es werden keine Kreiswerte geschätzt oder aus Landeswerten verteilt.",
              "Arbeitsuchende (arbeitslos und nichtarbeitslos)"),
    Indicator("arbeitslose_beruf", "Arbeitslose nach Zielberuf (Bestand)", "Personen", "ba_berufe",
              "Bestand an Arbeitslosen im Berichtsmonat nach dem Zielberuf. " + _ALO_DEF + _BERUF_NOTE,
              "Arbeitslose nach Zielberuf"),
    Indicator("arbeitsuchende_beruf", "Arbeitsuchende nach Zielberuf (Bestand)", "Personen", "ba_berufe",
              "Bestand an Arbeitsuchenden (arbeitslose und nichtarbeitslose Arbeitsuchende) im Berichtsmonat nach dem "
              "Zielberuf. " + _ASU_DEF + _BERUF_NOTE,
              "Arbeitsuchende nach Zielberuf"),
    Indicator("gemeldete_stellen_beruf", "Gemeldete Arbeitsstellen nach Beruf (Bestand)", "Stellen", "ba_berufe",
              "Bestand der den Agenturen für Arbeit und gemeinsamen Einrichtungen zur Besetzung gemeldeten Arbeitsstellen "
              "(sozialversicherungspflichtig, geringfügig oder sonstige; vorgesehene Beschäftigungsdauer über sieben "
              "Kalendertage) im Berichtsmonat; regionale Zuordnung nach dem Arbeitsort. Nur der BA gemeldete Stellen – "
              "nicht das gesamte Stellenangebot." + _BERUF_NOTE,
              "der BA gemeldete Arbeitsstellen"),
    Indicator("bev_gesamt", "Bevölkerung insgesamt (Stichtag 31.12.)", "Personen", "bevoelkerung_kreise_alter",
              "Bevölkerungsstand am Stichtag laut Fortschreibung des Bevölkerungsstandes (ab 2022 auf Grundlage des "
              "Zensus 2022), alle Altersgruppen.",
              "Bevölkerung am Hauptwohnsitz"),
    Indicator("bev_altersgruppe", "Bevölkerung nach Altersgruppen (Stichtag 31.12.)", "Personen", "bevoelkerung_kreise_alter",
              "Bevölkerungsstand am Stichtag je Altersgruppe. dim_key = Altersgrenzen in Jahren, z. B. 015-018 für "
              "„15 bis unter 18 Jahre“, 075-UM für „75 Jahre und mehr“; dim_label = Bezeichnung der Quelle.",
              "Bevölkerung der jeweiligen Altersgruppe"),
    Indicator("bev_15_bis_unter_65", "Bevölkerung 15 bis unter 65 Jahre (eigene Berechnung)", "Personen",
              "bevoelkerung_kreise_alter",
              "Eigene Berechnung aus den Altersgruppen der Tabelle „Bevölkerung: Kreise, Stichtag, Altersgruppen“: Summe "
              "der Gruppen von „15 bis unter 18 Jahre“ bis „60 bis unter 65 Jahre“. Der Wert wird nur gespeichert, wenn "
              "die vorhandenen Altersgruppen den Bereich 15 bis unter 65 Jahre lückenlos und überschneidungsfrei abdecken "
              "und keiner der benötigten Werte fehlt oder gesperrt ist; sonst fehlt er. Dient als Nenner für "
              "Anzeigen je 1.000 Einwohner im erwerbsfähigen Alter.",
              "Bevölkerung im Alter von 15 bis unter 65 Jahren"),
)

DATASET_BY_KEY = {d.key: d for d in DATASETS}
