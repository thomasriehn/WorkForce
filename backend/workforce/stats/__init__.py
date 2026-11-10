"""Importer für amtliche Regionalstatistik, Geodaten und die Berufsklassifikation.

Öffentliche Schnittstelle: :mod:`workforce.stats.runner` (``describe``, ``seed_reference``, ``run_imports``,
``import_file``, ``ImportProblem``).

Grundsätze (für alle Datensätze gleich):

* Ein Datenstand (``stat_release``) je Datensatz und Berichtszeitraum; der Berichtszeitraum stammt immer aus
  der Datei, nie aus dem Abrufdatum. Dieselbe Datei erneut zu importieren ändert nichts; eine andere Datei für
  denselben Zeitraum wird als neue Revision gespeichert, die alte bleibt mit allen Werten erhalten.
* Fehlwerte bleiben Fehlwerte: Zeichen wie ``*``, ``x``, ``.`` oder ``...`` werden nie zu 0, es wird nichts
  interpoliert oder aufgefüllt. Der Originaltext der Zelle steht in ``raw_value``.
* Vor dem Schreiben wird die Datei vollständig geprüft; bei Abweichungen wird nichts geschrieben
  (:class:`~workforce.stats.common.ImportProblem`, eine Transaktion je Datei).
* Netzabrufe laufen ausschließlich über :class:`workforce.crawl.fetcher.Fetcher` (robots.txt, Abrufabstand,
  Domainbeschränkung) – bzw. für die beiden GENESIS-Oberflächen über einen Browser, der nur die öffentliche
  Download-Schaltfläche bedient und alle fremden Hosts blockiert.
"""
