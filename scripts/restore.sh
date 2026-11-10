#!/usr/bin/env bash
# Wiederherstellung einer Sicherung von scripts/backup.sh.
#   scripts/restore.sh --verify  <Sicherungsverzeichnis>   Probe-Restore in eine FRISCHE Testdatenbank + Vergleich der Zeilenzahlen (ändert nichts am Betrieb)
#   scripts/restore.sh --replace <Sicherungsverzeichnis>   ersetzt die Betriebsdatenbank und das Volume app-data (Dienste werden angehalten)
set -euo pipefail
cd "$(dirname "$0")/.."
MODE="${1:-}"; SRC="${2:-}"
[ -n "${MODE}" ] && [ -d "${SRC}" ] || { echo "Aufruf: $0 --verify|--replace <Sicherungsverzeichnis>"; exit 2; }
# shellcheck disable=SC1091
set -a; . ./.env; set +a
DB="${POSTGRES_DB:-workforce}"; DBUSER="${POSTGRES_USER:-workforce}"
( cd "${SRC}" && sha256sum --check --quiet SHA256SUMS ) || { echo "Prüfsummen stimmen nicht – Abbruch."; exit 1; }
psql_db() { docker compose exec -T db psql -v ON_ERROR_STOP=1 -U "${DBUSER}" "$@"; }

counts() {  # Zeilenzahlen einer Datenbank im Format von rowcounts.tsv
  docker compose exec -T db psql -U "${DBUSER}" -d "$1" -At -F $'\t' -c "
    SELECT 'schema_version', (SELECT version_num FROM alembic_version)
    UNION ALL SELECT 'source', count(*)::text FROM source UNION ALL SELECT 'search_scope', count(*)::text FROM search_scope
    UNION ALL SELECT 'scan_run', count(*)::text FROM scan_run UNION ALL SELECT 'source_posting', count(*)::text FROM source_posting
    UNION ALL SELECT 'merged_posting', count(*)::text FROM merged_posting UNION ALL SELECT 'posting_version', count(*)::text FROM posting_version
    UNION ALL SELECT 'observation', count(*)::text FROM observation UNION ALL SELECT 'posting_event', count(*)::text FROM posting_event
    UNION ALL SELECT 'region', count(*)::text FROM region UNION ALL SELECT 'geo_place', count(*)::text FROM geo_place
    UNION ALL SELECT 'stat_release', count(*)::text FROM stat_release UNION ALL SELECT 'stat_value', count(*)::text FROM stat_value
    UNION ALL SELECT 'app_user', count(*)::text FROM app_user UNION ALL SELECT 'saved_search', count(*)::text FROM saved_search ORDER BY 1;"
}

restore_into() {  # $1 = Zieldatenbank (wird frisch angelegt)
  psql_db -d postgres -c "DROP DATABASE IF EXISTS \"$1\" WITH (FORCE)" -c "CREATE DATABASE \"$1\" OWNER \"${DBUSER}\""
  docker compose exec -T db pg_restore -U "${DBUSER}" -d "$1" --no-owner --no-privileges --exit-on-error < "${SRC}/workforce_db.dump"
}

case "${MODE}" in
  --verify)
    TEST_DB="${DB}_restoretest"
    echo "Probe-Restore in frische Datenbank ${TEST_DB} …"
    restore_into "${TEST_DB}"
    counts "${TEST_DB}" > /tmp/wf_restore_counts.tsv
    if diff -u "${SRC}/rowcounts.tsv" /tmp/wf_restore_counts.tsv; then
      echo "OK: Zeilenzahlen und Schemaversion der wiederhergestellten Datenbank stimmen mit der Sicherung überein."
    else
      echo "FEHLER: Abweichungen zwischen Sicherung und Wiederherstellung (siehe oben)."; exit 1
    fi
    docker compose exec -T db psql -U "${DBUSER}" -d "${TEST_DB}" -At -c "SELECT 'PostGIS ' || postgis_version(), 'Kreise mit Geometrie: ' || (SELECT count(*) FROM region WHERE geom IS NOT NULL)"
    tar -tzf "${SRC}/app_data.tar.gz" > /dev/null && echo "OK: Archiv der Referenzdateien ist lesbar ($(tar -tzf "${SRC}/app_data.tar.gz" | wc -l) Einträge)."
    echo "Die Testdatenbank ${TEST_DB} bleibt zur Ansicht bestehen. Entfernen: docker compose exec db dropdb -U ${DBUSER} ${TEST_DB}"
    ;;
  --replace)
    read -r -p "Betriebsdatenbank ${DB} und Volume app-data werden ERSETZT. Fortfahren? (ja/nein) " a; [ "${a}" = "ja" ] || exit 1
    docker compose stop web worker scheduler
    restore_into "${DB}"
    docker compose run --rm --no-deps -T --user 0 --entrypoint sh web -c 'rm -rf /data/* && tar -C /data -xzf - && chown -R 10001:10001 /data' < "${SRC}/app_data.tar.gz"
    docker compose up -d
    echo "Wiederherstellung abgeschlossen. Bitte Anmeldung, Quellenverwaltung und Karte prüfen."
    ;;
  *) echo "Unbekannter Modus ${MODE}"; exit 2 ;;
esac
