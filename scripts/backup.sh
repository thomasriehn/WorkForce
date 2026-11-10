#!/usr/bin/env bash
# Vollständige Sicherung von WorkForce:
#   1. PostgreSQL-Dump (Schema + Daten, konsistenter Snapshot über pg_dump – KEINE Kopie des laufenden Datenverzeichnisses)
#   2. Referenz-/Quelldateien aus dem Volume app-data (heruntergeladene Statistik- und Geodateien, Exporte)
#   3. Konfiguration (.env, compose.yaml, deploy/) – enthält Secrets, daher nur für root lesbar
# Aufruf im Projektverzeichnis:  scripts/backup.sh [Zielverzeichnis]     (Standard: ./backups)
set -euo pipefail
cd "$(dirname "$0")/.."
DEST="${1:-./backups}"
TS="$(date -u +%Y%m%dT%H%M%SZ)"
OUT="${DEST}/${TS}"
umask 077
mkdir -p "${OUT}"
# shellcheck disable=SC1091
set -a; . ./.env; set +a
DB="${POSTGRES_DB:-workforce}"; DBUSER="${POSTGRES_USER:-workforce}"

echo "[1/4] Datenbank-Dump (${DB}) …"
docker compose exec -T db pg_dump -U "${DBUSER}" -d "${DB}" --format=custom --compress=6 --no-owner --no-privileges > "${OUT}/workforce_db.dump"
docker compose exec -T db pg_restore --list < "${OUT}/workforce_db.dump" > "${OUT}/workforce_db.toc"   # Lesbarkeitsprüfung des Dumps
docker compose exec -T db psql -U "${DBUSER}" -d "${DB}" -At -F $'\t' -f - > "${OUT}/rowcounts.tsv" <<'SQL'
SELECT 'schema_version', (SELECT version_num FROM alembic_version)
UNION ALL SELECT 'source', count(*)::text FROM source
UNION ALL SELECT 'search_scope', count(*)::text FROM search_scope
UNION ALL SELECT 'scan_run', count(*)::text FROM scan_run
UNION ALL SELECT 'source_posting', count(*)::text FROM source_posting
UNION ALL SELECT 'merged_posting', count(*)::text FROM merged_posting
UNION ALL SELECT 'posting_version', count(*)::text FROM posting_version
UNION ALL SELECT 'observation', count(*)::text FROM observation
UNION ALL SELECT 'posting_event', count(*)::text FROM posting_event
UNION ALL SELECT 'region', count(*)::text FROM region
UNION ALL SELECT 'geo_place', count(*)::text FROM geo_place
UNION ALL SELECT 'stat_release', count(*)::text FROM stat_release
UNION ALL SELECT 'stat_value', count(*)::text FROM stat_value
UNION ALL SELECT 'app_user', count(*)::text FROM app_user
UNION ALL SELECT 'saved_search', count(*)::text FROM saved_search
ORDER BY 1;
SQL

echo "[2/4] Referenz- und Quelldateien (Volume app-data) …"
docker compose run --rm --no-deps -T --entrypoint tar web -C /data -czf - . > "${OUT}/app_data.tar.gz"

echo "[3/4] Konfiguration …"
tar -czf "${OUT}/config.tar.gz" .env compose.yaml $( [ -d deploy ] && echo deploy )

echo "[4/4] Prüfsummen …"
( cd "${OUT}" && sha256sum workforce_db.dump app_data.tar.gz config.tar.gz rowcounts.tsv > SHA256SUMS )
echo "Sicherung abgeschlossen: ${OUT}"
ls -lh "${OUT}"
