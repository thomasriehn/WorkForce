"""Regelbasierte, lokal ausführbare Extraktion von Anforderungen (kein externer KI-Dienst).

Getrennt werden: formaler Abschluss (``qual``), Erfahrung (``exp``), Kenntnisse (``skill``), Sprachen
(``lang``), Zertifikate (``cert``) und Berechtigungen (``license``). Je Fundstelle wird die **Polarität**
bestimmt: ausdrücklich verlangt, erwünscht, verneint oder unklar. „Keine Berufserfahrung erforderlich“
wird als *verneint* gespeichert und nie als verlangte Berufserfahrung indexiert.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from ..config import CLASSIFIER_VERSION
from .text import sanitize_evidence, short_evidence


@dataclass
class ExtractedFeature:
    key: str
    type: str
    label: str
    polarity: str
    origin: str
    confidence: float
    evidence: str | None = None
    detail: str | None = None


# (Schlüssel, Bezeichnung, Regex auf vorbereitetem Kleinbuchstaben-Text, Synonyme für die Suche)
_D = [
    # --- formale Abschlüsse -------------------------------------------------------------------------
    ("qual:berufsausbildung", "Abgeschlossene Berufsausbildung",
     r"abgeschlossene[nrs]?\s+(?:[\wäöüß\-/]+\s+){0,4}?(?:berufs)?ausbildung|\bberufsausbildung\b|abgeschlossene\s+lehre|\bberufsabschluss\b",
     ["Lehre", "Berufsabschluss"]),
    ("qual:meister", "Meister", r"\bmeister(?:brief|titel|prüfung|abschluss|in)?\b(?!\s*data)", ["Meisterbrief"]),
    ("qual:techniker", "Staatlich geprüfte/r Techniker/in", r"staatlich\s+geprüfte[rn]?\s+techniker|\btechnikerabschluss\b|techniker(?:in)?\s*\(staatl", []),
    ("qual:bachelor", "Bachelor / FH-Abschluss",
     r"\bbachelor\b|\bb\.\s?(?:sc|a|eng)\b\.?|\bfh-?abschluss\b|fachhochschul(?:abschluss|studium|diplom)|diplom\s*\(fh\)", ["B.Sc.", "B.A.", "FH"]),
    ("qual:master", "Master / Universitätsdiplom",
     r"\bmaster(?:abschluss|studium|niveau)?\b(?!\s*(?:data|daten))|\bm\.\s?(?:sc|a|eng)\b\.?|uni(?:versitäts)?-?diplom|wissenschaftliche[rsn]?\s+hochschul(?:abschluss|studium|bildung)"
     r"|universitäts(?:abschluss|studium)|\bstaatsexamen\b",
     ["M.Sc.", "M.A.", "Diplom (Univ.)", "Staatsexamen"]),
    ("qual:studium", "Hochschulstudium (allgemein)",
     r"abgeschlossene[sn]?\s+(?:[\wäöüß\-/().,]+\s+){0,6}?studium|\bhochschul(?:abschluss|studium)\b|\bstudienabschluss\b|akademische[rn]?\s+abschluss",
     ["Studium", "Hochschulabschluss"]),
    ("qual:promotion", "Promotion", r"\bpromotion\b|\bdoktortitel\b|\bph\.?\s?d\b|\bpromoviert", ["PhD", "Doktor"]),
    ("qual:laufbahn_md", "Laufbahnbefähigung mittlerer Dienst", r"laufbahnbefähigung[^.\n]{0,60}mittleren|laufbahn\s+des\s+mittleren", []),
    ("qual:laufbahn_gd", "Laufbahnbefähigung gehobener Dienst", r"laufbahnbefähigung[^.\n]{0,60}gehobenen|laufbahn\s+des\s+gehobenen", []),
    ("qual:laufbahn_hd", "Laufbahnbefähigung höherer Dienst", r"laufbahnbefähigung[^.\n]{0,60}höheren|laufbahn\s+des\s+höheren", []),
    ("qual:verwaltungslehrgang", "Verwaltungs-/Angestelltenlehrgang", r"(?:verwaltungs|angestellten)lehrgang\s*(?:i{1,2}|1|2)\b|beschäftigtenlehrgang", ["AL I", "AL II"]),
    ("qual:verwaltungsfachangestellte", "Verwaltungsfachangestellte/r", r"verwaltungsfachangestellte", ["VFA"]),
    ("qual:verwaltungsfachwirt", "Verwaltungsfachwirt/in", r"verwaltungsfachwirt", []),
    # --- Erfahrung ------------------------------------------------------------------------------------
    ("exp:berufserfahrung", "Berufserfahrung",
     r"berufserfahrung(?:en)?|\bberufspraxis\b|praxiserfahrung|einschlägige[rn]?\s+erfahrung|mehrjährige[rn]?\s+erfahrung|berufliche[rn]?\s+erfahrung", ["Berufspraxis"]),
    ("exp:fuehrung", "Führungserfahrung", r"führungserfahrung|leitungserfahrung|erfahrung\s+in\s+der\s+(?:mitarbeiter|personal)führung|personalverantwortung", []),
    # --- Sprachen -------------------------------------------------------------------------------------
    ("lang:de", "Deutschkenntnisse", r"deutsch(?:e[rn]?)?\s*(?:sprach)?kenntnisse|deutsch(?:e[rn]?)?\s+sprache|deutsch\s+in\s+wort|sprachniveau[^.\n]{0,30}deutsch|deutsch[^.\n]{0,25}\b(?:[bc][12])\b", ["Deutsch"]),
    ("lang:en", "Englischkenntnisse", r"englisch(?:e[rn]?)?\s*(?:sprach)?kenntnisse|englisch(?:e[rn]?)?\s+sprache|englisch\s+in\s+wort|business\s+english|verhandlungssichere[sn]?\s+englisch|gute[sn]?\s+englisch|fluent\s+(?:in\s+)?english|englisch[^.\n]{0,25}\b(?:[bc][12])\b", ["Englisch", "English"]),
    ("lang:fr", "Französischkenntnisse", r"französisch(?:e[rn]?)?\s*(?:sprach)?kenntnisse|französisch\s+in\s+wort|gute[sn]?\s+französisch", ["Französisch"]),
    # --- Berechtigungen -------------------------------------------------------------------------------
    ("license:fs_b", "Führerschein Klasse B", r"(?:führerschein|fahrerlaubnis)(?:\s+der)?(?:\s+klasse)?\s*(?:b|3|iii)\b|pkw-?führerschein|führerscheinklasse\s*b\b", ["Fahrerlaubnis B", "Pkw-Führerschein"]),
    ("license:fs_c", "Führerschein Klasse C/CE", r"(?:führerschein|fahrerlaubnis)(?:\s+der)?(?:\s+klasse)?\s*c1?e?\b|lkw-?führerschein|führerscheinklasse\s*c", ["Lkw-Führerschein"]),
    ("license:stapler", "Staplerschein", r"staplerschein|flurfördermittelschein|gabelstaplerschein", []),
    ("license:sue", "Sicherheitsüberprüfung", r"sicherheitsüberprüfung|\bsü\s?[123]\b|\bsüg\b", ["SÜ"]),
    # --- Zertifikate ----------------------------------------------------------------------------------
    ("cert:itil", "ITIL", r"\bitil\b", []),
    ("cert:prince2", "PRINCE2", r"\bprince\s?2\b", []),
    ("cert:pmp", "PMP", r"\bpmp\b|project\s+management\s+professional", []),
    ("cert:scrum", "Scrum-Zertifikat", r"scrum\s*master|product\s*owner|\b(?:csm|psm|cspo)\b", ["Scrum Master"]),
    ("cert:aevo", "Ausbildereignung (AEVO)", r"ausbildereignung|\baevo\b|ada-?schein", ["AdA"]),
    ("cert:cissp", "CISSP", r"\bcissp\b", []),
    ("cert:ccna", "Cisco CCNA/CCNP", r"\bccn[ap]\b", []),
    ("cert:bsi_grundschutz", "BSI IT-Grundschutz", r"it-?grundschutz", []),
    ("cert:iso27001", "ISO 27001", r"iso(?:/iec)?\s?27001", []),
    # --- Kenntnisse: IT -------------------------------------------------------------------------------
    ("skill:cpp", "C++", r"(?<![a-z0-9])c\+\+(?![a-z0-9+])|\bcplusplus\b", ["C++"]),
    ("skill:csharp", "C#", r"(?<![a-z0-9])c#(?![a-z0-9])|\bc\s?sharp\b", ["C#"]),
    ("skill:dotnet", ".NET", r"(?<![a-z0-9])(?:asp)?\.net\b|\bdotnet\b", [".NET", "dotnet"]),
    ("skill:java", "Java", r"\bjava\b(?!\s*script)", []),
    ("skill:javascript", "JavaScript", r"\bjavascript\b|\bnode\.?js\b", ["JS", "Node.js"]),
    ("skill:typescript", "TypeScript", r"\btypescript\b", []),
    ("skill:python", "Python", r"\bpython\b", []),
    ("skill:sql", "SQL / Datenbanken", r"\bsql\b|\bpostgresql\b|\bmysql\b|\boracle[- ]datenbank|\bmariadb\b|relationale[rn]?\s+datenbank", ["PostgreSQL", "MySQL"]),
    ("skill:php", "PHP", r"\bphp\b", []),
    ("skill:rust", "Rust", r"\brust\b(?=[^.\n]{0,40}(?:programm|entwickl|sprache))|\brust-?entwickl", []),
    ("skill:kotlin", "Kotlin", r"\bkotlin\b", []),
    ("skill:abap", "SAP ABAP", r"\babap\b", []),
    ("skill:sap", "SAP", r"\bsap\b", ["S/4HANA"]),
    ("skill:linux", "Linux", r"\blinux\b|\bunix\b", ["Unix"]),
    ("skill:windows_server", "Windows Server / Active Directory", r"windows[- ]server|active\s+directory", ["AD"]),
    ("skill:docker", "Docker / Container", r"\bdocker\b|\bcontainer(?:isierung|technologie)", []),
    ("skill:kubernetes", "Kubernetes", r"\bkubernetes\b|\bk8s\b|\bopenshift\b", ["K8s"]),
    ("skill:cloud", "Cloud (AWS/Azure/GCP)", r"\baws\b|\bazure\b|google\s+cloud|\bgcp\b|cloud-?(?:plattform|architektur|infrastruktur|technologie)", ["AWS", "Azure"]),
    ("skill:git", "Git", r"\bgit(?:lab|hub)?\b", ["GitLab", "GitHub"]),
    ("skill:cicd", "CI/CD", r"\bci/cd\b|\bcicd\b|continuous\s+(?:integration|delivery)|\bjenkins\b", []),
    ("skill:react", "React", r"\breact(?:\.?js)?\b", []),
    ("skill:angular", "Angular", r"\bangular\b", []),
    ("skill:vue", "Vue.js", r"\bvue(?:\.?js)?\b", []),
    ("skill:netzwerk", "Netzwerktechnik", r"netzwerk(?:technik|administration|infrastruktur|kenntnisse)|\btcp/ip\b|\bfirewall", []),
    ("skill:it_sicherheit", "IT-Sicherheit", r"it-?sicherheit|informationssicherheit|cyber-?security|cybersicherheit", ["Informationssicherheit"]),
    ("skill:ml", "Machine Learning / KI", r"machine\s+learning|maschinelle[sn]?\s+lernen|künstliche[rn]?\s+intelligenz|\bdeep\s+learning\b", ["KI", "AI"]),
    ("skill:data_analysis", "Datenanalyse / Statistik", r"datenanalyse|statistische[rn]?\s+(?:methoden|auswertung|verfahren)|\bstatistikkenntnisse|data\s+science|\bspss\b|\bstata\b", ["Statistik"]),
    ("skill:bi", "Business Intelligence", r"power\s?bi|\btableau\b|business\s+intelligence|\bqlik", ["Power BI", "Tableau"]),
    ("skill:gis", "GIS", r"\bgis\b|\barcgis\b|\bqgis\b|geoinformationssystem", ["ArcGIS", "QGIS"]),
    ("skill:cad", "CAD", r"\bcad\b|\bautocad\b|\bcatia\b|\bsolidworks\b|\binventor\b", ["AutoCAD"]),
    ("skill:sps", "SPS-Programmierung", r"\bsps\b|tia[- ]portal|\bsimatic\b|\bstep\s?7\b", ["TIA Portal"]),
    # --- Kenntnisse: Büro, Verwaltung, Recht, Wirtschaft -----------------------------------------------
    ("skill:ms_office", "MS Office", r"ms[- ]office|microsoft[- ]office|office-?(?:anwendungen|paket|programme|kenntnisse)|\bms\s?365\b|microsoft\s?365", ["Office", "Word"]),
    ("skill:excel", "Excel", r"\bexcel\b", []),
    ("skill:datev", "DATEV", r"\bdatev\b", []),
    ("skill:buchhaltung", "Buchhaltung / Rechnungswesen", r"buchhaltung|buchführung|rechnungswesen|bilanzierung|\bhgb\b|\bifrs\b", ["Rechnungswesen"]),
    ("skill:controlling", "Controlling", r"\bcontrolling\b", []),
    ("skill:haushaltsrecht", "Haushaltsrecht", r"haushaltsrecht|haushalts-?,?\s*kassen-?\s*und\s*rechnungswesen|\bbho\b|\blho\b|doppik|kameralistik", ["BHO", "Doppik"]),
    ("skill:vergaberecht", "Vergaberecht", r"vergaberecht|vergabeverfahren|\bvgv\b|\buvgo\b|\bvob\b", ["VgV", "UVgO"]),
    ("skill:verwaltungsrecht", "Verwaltungsrecht", r"verwaltungsrecht|verwaltungsverfahrensgesetz|\bvwvfg\b", []),
    ("skill:datenschutz", "Datenschutz (DSGVO)", r"datenschutz(?:recht|kenntnisse|grundverordnung)?\b|\bdsgvo\b|\bgdpr\b", ["DSGVO"]),
    ("skill:arbeitsrecht", "Arbeits-/Tarifrecht", r"arbeitsrecht|tarifrecht|\btvöd\b[^.\n]{0,30}kenntnisse|kenntnisse[^.\n]{0,30}\btv-?[öl]d?\b", ["TVöD"]),
    ("skill:projektmanagement", "Projektmanagement", r"projektmanagement|projektleitungserfahrung|projekterfahrung", []),
    ("skill:agil", "Agile Methoden", r"\bagile[nr]?\s+(?:methoden|arbeitsweise|vorgehens|softwareentwicklung)|\bscrum\b|\bkanban\b", ["Scrum", "Kanban"]),
    ("skill:qm", "Qualitätsmanagement", r"qualitätsmanagement|\biso\s?9001\b|\bsix\s+sigma\b", ["ISO 9001"]),
    ("skill:pflege", "Pflegefachliche Qualifikation", r"pflegefach(?:kraft|mann|frau)|gesundheits-\s*und\s*krankenpfleg|altenpfleger|examinierte[rn]?\s+(?:pflege|kranken|alten)", ["Krankenpflege", "Altenpflege"]),
    ("skill:paedagogik", "Pädagogische Qualifikation", r"\berzieher(?:in)?\b|sozialpädagog|soziale[rn]?\s+arbeit|staatliche\s+anerkennung", ["Erzieher", "Soziale Arbeit"]),
    ("skill:elektro", "Elektrotechnik", r"elektrotechnik|elektroniker|elektrofachkraft|elektroinstallateur", ["Elektroniker"]),
    ("skill:bau", "Bauwesen / HOAI", r"bauingenieur|\bhoai\b|bauleitung|bautechnik|hochbau|tiefbau", ["HOAI", "Bauleitung"]),
    ("skill:umwelt", "Umwelt / Nachhaltigkeit", r"umweltrecht|umweltschutz|nachhaltigkeits(?:management|berichterstattung)|klimaschutz(?:management)?|erneuerbare[rn]?\s+energien|immissionsschutz|naturschutz", ["Klimaschutz", "Nachhaltigkeit"]),
]

FEATURES: list[tuple[str, str, str, re.Pattern[str], list[str]]] = [
    (key, key.split(":", 1)[0], label, re.compile(rx, re.I), syn) for key, label, rx, syn in _D
]

_NEG = re.compile(
    r"\b(?:kein|keine|keinen|keiner|keinerlei|ohne)\b[^.\n;]{0,70}?(?:erforderlich|notwendig|nötig|vorausgesetzt|voraussetzung|verlangt|benötigt|zwingend|bedingung)"
    r"|\bnicht\s+(?:zwingend\s+|unbedingt\s+)?(?:erforderlich|notwendig|nötig|vorausgesetzt|voraussetzung|benötigt)"
    r"|\bauch\s+ohne\b|\b(?:quer|berufs)einsteiger\w*\s+(?:sind\s+)?(?:herzlich\s+)?willkommen|\bnot\s+required\b",
    re.I,
)
_NEG_BEFORE = re.compile(r"\b(?:kein|keine|keinen|keiner|keinerlei|ohne|auch\s+ohne)\s+(?:[\wäöüß\-]+\s+){0,3}$", re.I)
_DESIRED = re.compile(
    r"wünschenswert|von\s+vorteil|vorteilhaft|idealerweise|ideal\s+wäre|gerne\s+gesehen|gern\s+gesehen|nice[- ]to[- ]have|wäre\s+(?:ein\s+)?plus"
    r"|\boptional\b|\berwünscht|\bbevorzugt\b|hilfreich|von\s+nutzen|\bplus(?:punkt)?\b|freuen\s+wir\s+uns|im\s+idealfall|\bgerne\b|a\s+plus\b|preferred",
    re.I,
)
_REQUIRED = re.compile(
    r"erforderlich|zwingend|voraussetzung|vorausgesetzt|setzen\s+wir\s+voraus|notwendig|unabdingbar|unerlässlich|\bmuss\b|\bmüssen\b"
    r"|erwarten\s+wir|wir\s+erwarten|sie\s+verfügen|du\s+verfügst|sie\s+haben|du\s+hast|sie\s+besitzen|bringen\s+sie\s+mit|bringst\s+du\s+mit"
    r"|sie\s+bringen|du\s+bringst|nachweis|abgeschlossen|\brequired\b|must[- ]have|\bmindestens\b",
    re.I,
)
_HEAD_REQ = re.compile(
    r"^(?:\W*)(?:ihr|dein|das|unser)?\s*(?:anforderungs)?profil\b|anforderungen|voraussetzungen|was\s+(?:sie|du)\s+mitbring|das\s+bring(?:en|st)\s+(?:sie|du)\s+mit"
    r"|qualifikation(?:en)?\b|wir\s+erwarten|das\s+zeichnet\s+(?:sie|dich)\s+aus|sie\s+bringen\s+mit|must[- ]haves?|ihre\s+kompetenzen|das\s+erwarten\s+wir|requirements",
    re.I,
)
_HEAD_DESIRED = re.compile(r"wünschenswert|von\s+vorteil|nice[- ]to[- ]have|pluspunkte|darüber\s+hinaus\s+freuen|idealerweise", re.I)
_HEAD_OFFER = re.compile(r"wir\s+bieten|unser\s+angebot|das\s+bieten\s+wir|benefits|ihre\s+vorteile|deine\s+vorteile|was\s+wir\s+(?:ihnen\s+|dir\s+)?bieten|das\s+erwartet\s+(?:sie|dich)\s+bei\s+uns|we\s+offer", re.I)
_HEAD_TASKS = re.compile(r"(?:ihre|deine|die)\s+aufgaben|aufgabengebiet|aufgabenschwerpunkte|tätigkeiten|ihr\s+aufgabenbereich|das\s+erwartet\s+(?:sie|dich)\b|your\s+tasks|responsibilities", re.I)
_YEARS = re.compile(r"(?:mindestens|mind\.|min\.|wenigstens)?\s*(\d{1,2}|ein|zwei|drei|vier|fünf|mehr)(?:\s*(?:-|bis)\s*(\d{1,2}))?\s*(?:\+\s*)?jahr", re.I)
_LEVEL = re.compile(r"\b([abc][12])\b|verhandlungssicher|fließend|sehr\s+gut|gute|grundkenntnisse|muttersprach", re.I)
_PRIORITY = {"required": 3, "desired": 2, "negated": 1, "unclear": 0}


def prepare(text: str) -> str:
    """Kleinschreibung unter Erhalt der Zeichenpositionen (für Belegauszüge aus dem Originaltext)."""
    low = text.lower()
    return low if len(low) == len(text) else "".join(ch.lower() if len(ch.lower()) == 1 else ch for ch in text)


def _sentence_bounds(text: str, start: int, end: int) -> tuple[int, int]:
    left = max(text.rfind("\n", 0, start), text.rfind(". ", 0, start), text.rfind("; ", 0, start))
    left = 0 if left < 0 else left + 1
    rights = [p for p in (text.find("\n", end), text.find(". ", end), text.find("; ", end)) if p >= 0]
    return left, (min(rights) if rights else len(text))


def _sections(text: str) -> list[tuple[int, str]]:
    """Abschnittswechsel anhand kurzer Überschriftenzeilen: [(Offset, Abschnitt)]."""
    marks: list[tuple[int, str]] = [(0, "unknown")]
    pos = 0
    for line in text.split("\n"):
        stripped = line.strip(" :-–•*\t")
        is_bullet = line.lstrip()[:1] in ("-", "–", "•", "*", "·", "‣")
        # Überschriften sind kurz, keine Aufzählungspunkte und enden nicht als Satz
        if 2 < len(stripped) <= 70 and not is_bullet and not stripped.endswith((".", ",", ";")):
            if _HEAD_DESIRED.search(stripped) and len(stripped) <= 45:
                marks.append((pos, "desired"))
            elif _HEAD_REQ.search(stripped):
                marks.append((pos, "req"))
            elif _HEAD_OFFER.search(stripped):
                marks.append((pos, "offer"))
            elif _HEAD_TASKS.search(stripped):
                marks.append((pos, "tasks"))
        pos += len(line) + 1
    return marks


def _section_at(marks: list[tuple[int, str]], offset: int) -> str:
    cur = "unknown"
    for pos, name in marks:
        if pos <= offset:
            cur = name
        else:
            break
    return cur


def classify_polarity(text: str, start: int, end: int, section: str) -> str:
    left, right = _sentence_bounds(text, start, end)
    sentence = text[left:right]
    rel_start = start - left
    negated = bool(_NEG.search(sentence)) or bool(_NEG_BEFORE.search(sentence[:rel_start]))
    desired = bool(_DESIRED.search(sentence))
    if negated and not desired:
        return "negated"
    if desired:
        return "desired"
    if _REQUIRED.search(sentence):
        return "required"
    if section == "req":
        return "required"
    if section == "desired":
        return "desired"
    return "unclear"


def extract_features(
    description: str | None,
    *,
    title: str | None = None,
    hints: dict[str, Any] | None = None,
    store_evidence: bool = True,
) -> list[ExtractedFeature]:
    """Extrahiert Merkmale aus (flüchtigem) Anzeigentext, Titel und strukturierten Hinweisen."""
    best: dict[str, ExtractedFeature] = {}

    def consider(f: ExtractedFeature) -> None:
        cur = best.get(f.key)
        if cur is None or _PRIORITY[f.polarity] > _PRIORITY[cur.polarity]:
            best[f.key] = f

    if description:
        text = prepare(description)
        marks = _sections(text)
        for key, ftype, label, rx, _syn in FEATURES:
            for m in rx.finditer(text):
                section = _section_at(marks, m.start())
                pol = classify_polarity(text, m.start(), m.end(), section)
                detail = None
                left, right = _sentence_bounds(text, m.start(), m.end())
                sentence = text[left:right]
                if key == "exp:berufserfahrung":
                    ym = _YEARS.search(sentence)
                    if ym and pol != "negated":
                        detail = ym.group(0).strip()
                elif ftype == "lang":
                    lm = _LEVEL.search(sentence)
                    if lm:
                        detail = lm.group(0).strip()
                conf = 0.9 if pol in ("required", "negated") and section in ("req", "unknown") else 0.7
                if pol == "unclear":
                    conf = 0.5
                ev = sanitize_evidence(short_evidence(description, m.start(), m.end())) if store_evidence else None
                consider(ExtractedFeature(key, ftype, label, pol, "rule_text", conf, ev, detail))
    for hint_key, hint_val in (hints or {}).items():
        blob = prepare(str(hint_val))
        pol = "unclear" if hint_key in ("skills", "responsibilities") else "required"
        for key, ftype, label, rx, _syn in FEATURES:
            if rx.search(blob):
                consider(ExtractedFeature(key, ftype, label, pol, "jsonld", 0.7, None, None))
    if title:
        t = prepare(title)
        for key, ftype, label, rx, _syn in FEATURES:
            if ftype in ("skill", "cert") and key not in best and rx.search(t):
                consider(ExtractedFeature(key, ftype, label, "unclear", "rule_title", 0.5, None, None))
    return sorted(best.values(), key=lambda f: f.key)


def feature_dictionary() -> list[dict[str, Any]]:
    return [
        {"key": key, "type": ftype, "label": label, "synonyms": syn, "rule_version": CLASSIFIER_VERSION}
        for key, ftype, label, _rx, syn in FEATURES
    ]


# --- Beschäftigungsmerkmale ------------------------------------------------------------------------
_KIND_RULES = [
    ("duales_studium", re.compile(r"duale[sn]?\s+studi|dual(?:e[rn]?)?\s+student|\bdh-?stud", re.I)),
    ("ausbildung", re.compile(r"\bausbildung\s+(?:zum|zur|als|im|in\s+der)\b|\bauszubildende|\bazubi\b|ausbildungsplatz|berufsausbildung\s+(?:zum|zur)", re.I)),
    ("praktikum", re.compile(r"\bpraktik(?:um|ant|a)\b|\bpflichtpraktik|\binternship\b", re.I)),
    ("trainee", re.compile(r"\btrainee\b|traineeprogramm|\bvolontariat\b|referendariat", re.I)),
    ("werkstudent", re.compile(r"werkstudent|studentische\s+(?:hilfskraft|aushilfe|mitarbeit)|\bshk\b", re.I)),
    ("abschlussarbeit", re.compile(r"abschlussarbeit|bachelorarbeit|masterarbeit|\bthesis\b", re.I)),
    ("minijob", re.compile(r"\bminijob\b|geringfügig|\b(?:520|538|556|603)\s?[-€]?\s?(?:euro|€)?-?(?:job|basis)", re.I)),
]
_AGENCY = re.compile(
    r"personaldienstleist|zeitarbeit|arbeitnehmerüberlassung|personalvermittlung|personalberatung|personalservice|recruiting\s+gmbh"
    r"|im\s+auftrag\s+(?:unseres|eines)\s+(?:kunden|mandanten)|für\s+unseren\s+(?:kunden|mandanten)|unser\s+(?:kunde|mandant)\b"
    r"|\b(?:randstad|adecco|manpower|hays|persona\s+service|dis\s+ag|tempton|piening|orizon|avitea|akut\.?\s?med|gi\s+group|unique\s+personal)\b",
    re.I,
)
_REMOTE_FULL = re.compile(r"100\s?%\s*(?:remote|home-?office|mobil)|vollständig\s+remote|fully\s+remote|remote[- ]first|deutschlandweit\s+(?:remote|im\s+home-?office)|ortsunabhängig", re.I)
_REMOTE_HYBRID = re.compile(r"home-?office|mobile[sn]?\s+arbeit|mobil\s+zu\s+arbeiten|\bhybrid|telearbeit|\bremote\b", re.I)
_ONSITE = re.compile(r"kein\s+home-?office|präsenzpflicht|ausschließlich\s+vor\s+ort|nur\s+vor\s+ort", re.I)


def classify_kind(title: str, given: str | None = None) -> str:
    if given:
        return given
    for kind, rx in _KIND_RULES:
        if rx.search(title or ""):
            return kind
    return "job"


def classify_employment(title: str, text: str | None) -> dict[str, Any]:
    """Arbeitszeit, Befristung und Remote-Status aus Titel/Text; Unbekanntes bleibt unbekannt."""
    blob = f"{title or ''}\n{text or ''}"
    out: dict[str, Any] = {"working_time": [], "contract_term": None, "remote_type": None}
    if re.search(r"\bvollzeit\b|\bfull[- ]?time\b|voll-\s*(?:oder|und|/)\s*teilzeit", blob, re.I):
        out["working_time"].append("vollzeit")
    if re.search(r"\bteilzeit|\bpart[- ]?time\b", blob, re.I):
        out["working_time"].append("teilzeit")
    if re.search(r"\bunbefristet", blob, re.I):
        out["contract_term"] = "unbefristet"
    elif re.search(r"(?<!un)befristet|\bbefristung\b", blob, re.I):
        out["contract_term"] = "befristet"
    if _ONSITE.search(blob):
        out["remote_type"] = "onsite"
    elif _REMOTE_FULL.search(blob):
        out["remote_type"] = "remote"
    elif _REMOTE_HYBRID.search(blob):
        out["remote_type"] = "hybrid"
    return out


def detect_agency(employer: str | None, text: str | None) -> bool | None:
    """True bei deutlichen Hinweisen auf Personalvermittlung/Zeitarbeit, sonst None (unbekannt)."""
    if employer and _AGENCY.search(employer):
        return True
    if text and _AGENCY.search(text[:1500]):
        return True
    return None
