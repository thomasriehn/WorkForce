"""Initiales Schema (WorkForce 0.1): Quellen, Läufe, Anzeigen, Regionen, Statistik, Jobs.

Revision ID: 0001
Revises: 
Create Date: 2026-11-10 21:58:54.463870
"""
from alembic import op
import sqlalchemy as sa
from geoalchemy2 import Geometry
from sqlalchemy.dialects import postgresql

revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute("CREATE EXTENSION IF NOT EXISTS unaccent")
    op.create_table('app_state',
    sa.Column('key', sa.String(length=80), nullable=False),
    sa.Column('value', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('key')
    )
    op.create_table('app_user',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('username', sa.String(length=80), nullable=False),
    sa.Column('password_hash', sa.Text(), nullable=False),
    sa.Column('role', sa.String(length=16), nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('failed_logins', sa.Integer(), server_default='0', nullable=False),
    sa.Column('locked_until', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("role IN ('admin','reader')", name='ck_user_role'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('username')
    )
    op.create_table('audit_log',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('username', sa.String(length=80), nullable=True),
    sa.Column('action', sa.String(length=80), nullable=False),
    sa.Column('details', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_audit_log_at'), 'audit_log', ['at'], unique=False)
    op.create_table('daily_aggregate',
    sa.Column('agg_date', sa.Date(), nullable=False),
    sa.Column('region_key', sa.String(length=16), nullable=False),
    sa.Column('kind_group', sa.String(length=16), nullable=False),
    sa.Column('weighted_count', sa.Numeric(precision=14, scale=4), nullable=False),
    sa.Column('distinct_count', sa.Integer(), nullable=False),
    sa.Column('first_seen_count', sa.Integer(), nullable=False),
    sa.Column('changed_count', sa.Integer(), nullable=False),
    sa.Column('left_count', sa.Integer(), nullable=False),
    sa.Column('observed_count', sa.Integer(), nullable=False),
    sa.Column('basis', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('dedup_rule_version', sa.String(length=32), nullable=False),
    sa.Column('classifier_version', sa.String(length=32), nullable=False),
    sa.Column('geo_rule_version', sa.String(length=32), nullable=False),
    sa.Column('aggregate_version', sa.String(length=32), nullable=False),
    sa.Column('computed_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('agg_date', 'region_key', 'kind_group')
    )
    op.create_table('employer',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('name_norm', sa.Text(), nullable=False),
    sa.Column('is_staffing_agency', sa.Boolean(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('name_norm')
    )
    op.create_table('feature',
    sa.Column('key', sa.String(length=80), nullable=False),
    sa.Column('type', sa.String(length=20), nullable=False),
    sa.Column('label', sa.Text(), nullable=False),
    sa.Column('synonyms', postgresql.ARRAY(sa.Text()), server_default='{}', nullable=False),
    sa.Column('rule_version', sa.String(length=32), nullable=False),
    sa.PrimaryKeyConstraint('key')
    )
    op.create_index(op.f('ix_feature_type'), 'feature', ['type'], unique=False)
    op.create_table('fetch_cache',
    sa.Column('url_hash', sa.String(length=64), nullable=False),
    sa.Column('url', sa.Text(), nullable=False),
    sa.Column('etag', sa.Text(), nullable=True),
    sa.Column('last_modified', sa.Text(), nullable=True),
    sa.Column('fetched_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('status_code', sa.Integer(), nullable=True),
    sa.PrimaryKeyConstraint('url_hash')
    )
    op.create_table('geo_place',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('country', sa.String(length=2), nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('name_norm', sa.Text(), nullable=False),
    sa.Column('kind', sa.String(length=16), nullable=False),
    sa.Column('ags', sa.String(length=8), nullable=True),
    sa.Column('kreis_key', sa.String(length=5), nullable=True),
    sa.Column('state_key', sa.String(length=2), nullable=True),
    sa.Column('postal_code', sa.String(length=5), nullable=True),
    sa.Column('population', sa.Integer(), nullable=True),
    sa.Column('lat', sa.Numeric(precision=9, scale=6), nullable=True),
    sa.Column('lon', sa.Numeric(precision=9, scale=6), nullable=True),
    sa.Column('gebietsstand', sa.Date(), nullable=True),
    sa.Column('source_note', sa.Text(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_geo_place_kreis_key'), 'geo_place', ['kreis_key'], unique=False)
    op.create_index(op.f('ix_geo_place_name_norm'), 'geo_place', ['name_norm'], unique=False)
    op.create_index(op.f('ix_geo_place_postal_code'), 'geo_place', ['postal_code'], unique=False)
    op.create_index('ix_place_name_trgm', 'geo_place', ['name_norm'], unique=False, postgresql_using='gin', postgresql_ops={'name_norm': 'gin_trgm_ops'})
    op.create_table('job',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('kind', sa.String(length=32), nullable=False),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('status', sa.String(length=12), nullable=False),
    sa.Column('priority', sa.Integer(), nullable=False),
    sa.Column('dedupe_key', sa.String(length=160), nullable=True),
    sa.Column('lock_key', sa.String(length=160), nullable=True),
    sa.Column('run_after', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('attempts', sa.Integer(), server_default='0', nullable=False),
    sa.Column('max_attempts', sa.Integer(), server_default='3', nullable=False),
    sa.Column('locked_by', sa.String(length=80), nullable=True),
    sa.Column('heartbeat_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('checkpoint', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('result', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('last_error', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("status IN ('queued', 'running', 'done', 'failed', 'cancelled')", name='ck_job_status'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_job_queue', 'job', ['status', 'priority', 'run_after'], unique=False)
    op.create_index('uq_job_dedupe_open', 'job', ['dedupe_key'], unique=True, postgresql_where=sa.text("status IN ('queued','running')"))
    op.create_table('kldb_class',
    sa.Column('code', sa.String(length=5), nullable=False),
    sa.Column('level', sa.SmallInteger(), nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('version', sa.String(length=24), nullable=False),
    sa.PrimaryKeyConstraint('code')
    )
    op.create_table('merged_posting',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('primary_source_posting_id', sa.Integer(), nullable=True),
    sa.Column('current_version_id', sa.Integer(), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('first_seen_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('first_seen_date', sa.Date(), nullable=False),
    sa.Column('first_seen_baseline', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_seen_date', sa.Date(), nullable=False),
    sa.Column('member_count', sa.Integer(), server_default='1', nullable=False),
    sa.Column('source_ids', postgresql.ARRAY(sa.Integer()), server_default='{}', nullable=False),
    sa.Column('dedup_rule_version', sa.String(length=32), nullable=True),
    sa.Column('is_synthetic', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status IN ('active', 'not_reobserved', 'presumed_removed', 'ended', 'stale')", name='ck_merged_status'),
    sa.ForeignKeyConstraint(['current_version_id'], ['posting_version.id'], name='fk_merged_current_version', ondelete='SET NULL', use_alter=True),
    sa.ForeignKeyConstraint(['primary_source_posting_id'], ['source_posting.id'], name='fk_merged_primary_sp', ondelete='SET NULL', use_alter=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_merged_posting_current_version_id'), 'merged_posting', ['current_version_id'], unique=False)
    op.create_index(op.f('ix_merged_posting_first_seen_date'), 'merged_posting', ['first_seen_date'], unique=False)
    op.create_index(op.f('ix_merged_posting_status'), 'merged_posting', ['status'], unique=False)
    op.create_index('ix_merged_source_ids', 'merged_posting', ['source_ids'], unique=False, postgresql_using='gin')
    op.create_table('occupation_title',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('title', sa.Text(), nullable=False),
    sa.Column('title_norm', sa.Text(), nullable=False),
    sa.Column('kldb_code', sa.String(length=5), nullable=False),
    sa.Column('origin', sa.String(length=24), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('title_norm', 'kldb_code', name='uq_occupation_title')
    )
    op.create_index(op.f('ix_occupation_title_kldb_code'), 'occupation_title', ['kldb_code'], unique=False)
    op.create_index(op.f('ix_occupation_title_title_norm'), 'occupation_title', ['title_norm'], unique=False)
    op.create_index('ix_occupation_title_trgm', 'occupation_title', ['title_norm'], unique=False, postgresql_using='gin', postgresql_ops={'title_norm': 'gin_trgm_ops'})
    op.create_table('postal_code',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('country', sa.String(length=2), nullable=False),
    sa.Column('plz', sa.String(length=5), nullable=False),
    sa.Column('ags', sa.String(length=8), nullable=True),
    sa.Column('kreis_key', sa.String(length=5), nullable=False),
    sa.Column('place_name', sa.Text(), nullable=True),
    sa.Column('source_note', sa.Text(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('country', 'plz', 'ags', 'kreis_key', name='uq_postal_code')
    )
    op.create_index(op.f('ix_postal_code_plz'), 'postal_code', ['plz'], unique=False)
    op.create_geospatial_table('region',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('country', sa.String(length=2), nullable=False),
    sa.Column('level', sa.String(length=12), nullable=False),
    sa.Column('key', sa.String(length=12), nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('type_label', sa.Text(), nullable=True),
    sa.Column('parent_key', sa.String(length=12), nullable=True),
    sa.Column('gebietsstand', sa.Date(), nullable=False),
    sa.Column('is_current', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('geom', Geometry(geometry_type='MULTIPOLYGON', srid=4326, dimension=2, spatial_index=False, from_text='ST_GeomFromEWKT', name='geometry'), nullable=True),
    sa.Column('geom_simple', Geometry(geometry_type='MULTIPOLYGON', srid=4326, dimension=2, spatial_index=False, from_text='ST_GeomFromEWKT', name='geometry'), nullable=True),
    sa.Column('centroid', Geometry(geometry_type='POINT', srid=4326, dimension=2, spatial_index=False, from_text='ST_GeomFromEWKT', name='geometry'), nullable=True),
    sa.Column('area_km2', sa.Numeric(precision=12, scale=3), nullable=True),
    sa.Column('source_note', sa.Text(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('country', 'level', 'key', 'gebietsstand', name='uq_region_key_stand')
    )
    op.create_geospatial_index('idx_region_geom', 'region', ['geom'], unique=False, postgresql_using='gist', postgresql_ops={})
    op.create_index('ix_region_current', 'region', ['country', 'level', 'key'], unique=False, postgresql_where=sa.text('is_current'))
    op.create_table('robots_cache',
    sa.Column('host', sa.String(length=200), nullable=False),
    sa.Column('fetched_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('status_code', sa.Integer(), nullable=True),
    sa.Column('body', sa.Text(), nullable=True),
    sa.PrimaryKeyConstraint('host')
    )
    op.create_table('source',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('key', sa.String(length=64), nullable=False),
    sa.Column('name', sa.String(length=160), nullable=False),
    sa.Column('domain', sa.String(length=160), nullable=False),
    sa.Column('entry_url', sa.Text(), nullable=True),
    sa.Column('country', sa.String(length=2), server_default='DE', nullable=False),
    sa.Column('segment', sa.Text(), nullable=True),
    sa.Column('is_career_page', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('access_method', sa.String(length=64), nullable=True),
    sa.Column('adapter_key', sa.String(length=64), nullable=True),
    sa.Column('adapter_version', sa.String(length=32), nullable=True),
    sa.Column('allowed_domains', postgresql.ARRAY(sa.Text()), server_default='{}', nullable=False),
    sa.Column('terms_url', sa.Text(), nullable=True),
    sa.Column('robots_url', sa.Text(), nullable=True),
    sa.Column('legal_checked_on', sa.Date(), nullable=True),
    sa.Column('legal_notes', sa.Text(), nullable=True),
    sa.Column('attribution', sa.Text(), nullable=True),
    sa.Column('config_status', sa.String(length=24), server_default='candidate', nullable=False),
    sa.Column('status_reason', sa.Text(), nullable=True),
    sa.Column('request_interval_seconds', sa.Numeric(precision=6, scale=2), server_default='3.0', nullable=False),
    sa.Column('max_pages_per_run', sa.Integer(), server_default='400', nullable=False),
    sa.Column('max_details_per_run', sa.Integer(), server_default='500', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("config_status IN ('candidate', 'active', 'disabled', 'permission_required')", name='ck_source_config_status'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('key')
    )
    op.create_table('stat_dataset',
    sa.Column('key', sa.String(length=64), nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('publisher', sa.Text(), nullable=False),
    sa.Column('dataset_code', sa.Text(), nullable=True),
    sa.Column('landing_url', sa.Text(), nullable=True),
    sa.Column('licence', sa.Text(), nullable=True),
    sa.Column('licence_url', sa.Text(), nullable=True),
    sa.Column('attribution', sa.Text(), nullable=True),
    sa.Column('update_cycle', sa.String(length=16), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.PrimaryKeyConstraint('key')
    )
    op.create_table('ops_warning',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('kind', sa.String(length=32), nullable=False),
    sa.Column('dedupe_key', sa.String(length=160), nullable=False),
    sa.Column('source_id', sa.Integer(), nullable=True),
    sa.Column('message', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['source_id'], ['source.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('uq_warning_open', 'ops_warning', ['dedupe_key'], unique=True, postgresql_where=sa.text('resolved_at IS NULL'))
    op.create_table('saved_search',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('params', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['app_user.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'name', name='uq_saved_search_user_name')
    )
    op.create_index(op.f('ix_saved_search_user_id'), 'saved_search', ['user_id'], unique=False)
    op.create_table('search_scope',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('source_id', sa.Integer(), nullable=False),
    sa.Column('key', sa.String(length=80), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('params', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('mode', sa.String(length=16), server_default='full', nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('page_budget', sa.Integer(), nullable=True),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('retired_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("mode IN ('full', 'new_only')", name='ck_scope_mode'),
    sa.ForeignKeyConstraint(['source_id'], ['source.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('source_id', 'key', 'version', name='uq_scope_source_key_version')
    )
    op.create_index(op.f('ix_search_scope_source_id'), 'search_scope', ['source_id'], unique=False)
    op.create_index('uq_scope_one_active', 'search_scope', ['source_id', 'key'], unique=True, postgresql_where=sa.text('is_active'))
    op.create_table('stat_indicator',
    sa.Column('key', sa.String(length=64), nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('definition', sa.Text(), nullable=True),
    sa.Column('unit', sa.String(length=32), nullable=False),
    sa.Column('population_group', sa.Text(), nullable=True),
    sa.Column('dataset_key', sa.String(length=64), nullable=True),
    sa.ForeignKeyConstraint(['dataset_key'], ['stat_dataset.key'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('key')
    )
    op.create_table('stat_release',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('dataset_key', sa.String(length=64), nullable=False),
    sa.Column('period_key', sa.String(length=32), nullable=False),
    sa.Column('period_start', sa.Date(), nullable=True),
    sa.Column('period_end', sa.Date(), nullable=False),
    sa.Column('revision', sa.Integer(), nullable=False),
    sa.Column('is_current', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('published_on', sa.Date(), nullable=True),
    sa.Column('retrieved_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('file_url', sa.Text(), nullable=True),
    sa.Column('file_name', sa.Text(), nullable=True),
    sa.Column('file_sha256', sa.String(length=64), nullable=False),
    sa.Column('stored_path', sa.Text(), nullable=True),
    sa.Column('gebietsstand', sa.Date(), nullable=True),
    sa.Column('import_method', sa.String(length=16), nullable=False),
    sa.Column('row_count', sa.Integer(), server_default='0', nullable=False),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.ForeignKeyConstraint(['dataset_key'], ['stat_dataset.key'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('dataset_key', 'period_key', 'file_sha256', name='uq_release_period_checksum'),
    sa.UniqueConstraint('dataset_key', 'period_key', 'revision', name='uq_release_period_revision')
    )
    op.create_index(op.f('ix_stat_release_dataset_key'), 'stat_release', ['dataset_key'], unique=False)
    op.create_index('uq_release_current', 'stat_release', ['dataset_key', 'period_key'], unique=True, postgresql_where=sa.text('is_current'))
    op.create_table('timeline_note',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('note_date', sa.Date(), nullable=False),
    sa.Column('kind', sa.String(length=32), nullable=False),
    sa.Column('source_id', sa.Integer(), nullable=True),
    sa.Column('message', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['source_id'], ['source.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('note_date', 'kind', 'source_id', 'message', name='uq_timeline_note')
    )
    op.create_index(op.f('ix_timeline_note_note_date'), 'timeline_note', ['note_date'], unique=False)
    op.create_table('user_session',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('csrf_token', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['app_user.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('token_hash')
    )
    op.create_index(op.f('ix_user_session_user_id'), 'user_session', ['user_id'], unique=False)
    op.create_table('scan_run',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('source_id', sa.Integer(), nullable=False),
    sa.Column('scope_id', sa.Integer(), nullable=False),
    sa.Column('scope_key', sa.String(length=80), nullable=False),
    sa.Column('scope_version', sa.Integer(), nullable=False),
    sa.Column('logical_date', sa.Date(), nullable=False),
    sa.Column('trigger', sa.String(length=16), nullable=False),
    sa.Column('mode', sa.String(length=16), nullable=False),
    sa.Column('is_test', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('is_baseline', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('page_limit', sa.Integer(), nullable=True),
    sa.Column('parser_version', sa.String(length=32), nullable=True),
    sa.Column('classifier_version', sa.String(length=32), nullable=True),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('status_detail', sa.Text(), nullable=True),
    sa.Column('control', sa.String(length=16), nullable=True),
    sa.Column('list_complete', sa.Boolean(), nullable=True),
    sa.Column('detail_complete', sa.Boolean(), nullable=True),
    sa.Column('attempts', sa.Integer(), server_default='0', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('window_start', sa.DateTime(timezone=True), nullable=True),
    sa.Column('window_end', sa.DateTime(timezone=True), nullable=True),
    sa.Column('pages_fetched', sa.Integer(), server_default='0', nullable=False),
    sa.Column('requests_made', sa.Integer(), server_default='0', nullable=False),
    sa.Column('partitions_total', sa.Integer(), server_default='0', nullable=False),
    sa.Column('partitions_done', sa.Integer(), server_default='0', nullable=False),
    sa.Column('reported_total', sa.Integer(), nullable=True),
    sa.Column('ids_found', sa.Integer(), server_default='0', nullable=False),
    sa.Column('postings_extracted', sa.Integer(), server_default='0', nullable=False),
    sa.Column('postings_new', sa.Integer(), server_default='0', nullable=False),
    sa.Column('postings_changed', sa.Integer(), server_default='0', nullable=False),
    sa.Column('details_fetched', sa.Integer(), server_default='0', nullable=False),
    sa.Column('details_pending', sa.Integer(), server_default='0', nullable=False),
    sa.Column('error_count', sa.Integer(), server_default='0', nullable=False),
    sa.Column('coverage', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('status_applied', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.CheckConstraint("status IN ('queued', 'running', 'paused', 'complete', 'partial', 'blocked', 'failed', 'cancelled')", name='ck_run_status'),
    sa.CheckConstraint("trigger IN ('scheduled', 'catchup', 'manual', 'test')", name='ck_run_trigger'),
    sa.ForeignKeyConstraint(['scope_id'], ['search_scope.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['source_id'], ['source.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_run_source_date', 'scan_run', ['source_id', 'logical_date'], unique=False)
    op.create_index(op.f('ix_scan_run_logical_date'), 'scan_run', ['logical_date'], unique=False)
    op.create_index(op.f('ix_scan_run_scope_id'), 'scan_run', ['scope_id'], unique=False)
    op.create_index(op.f('ix_scan_run_source_id'), 'scan_run', ['source_id'], unique=False)
    op.create_index(op.f('ix_scan_run_status'), 'scan_run', ['status'], unique=False)
    op.create_index('uq_run_scope_day', 'scan_run', ['scope_id', 'logical_date'], unique=True, postgresql_where=sa.text('NOT is_test'))
    op.create_table('stat_value',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('release_id', sa.Integer(), nullable=False),
    sa.Column('indicator_key', sa.String(length=64), nullable=False),
    sa.Column('region_level', sa.String(length=12), nullable=False),
    sa.Column('region_key', sa.String(length=12), nullable=False),
    sa.Column('region_name', sa.Text(), nullable=True),
    sa.Column('gebietsstand', sa.Date(), nullable=True),
    sa.Column('dim_key', sa.String(length=64), server_default='', nullable=False),
    sa.Column('dim_label', sa.Text(), nullable=True),
    sa.Column('classification_version', sa.String(length=24), nullable=True),
    sa.Column('value', sa.Numeric(precision=18, scale=4), nullable=True),
    sa.Column('value_status', sa.String(length=16), nullable=False),
    sa.Column('raw_value', sa.Text(), nullable=True),
    sa.CheckConstraint("value_status IN ('ok', 'zero', 'suppressed', 'unknown', 'not_available', 'not_collected')", name='ck_stat_value_status'),
    sa.ForeignKeyConstraint(['indicator_key'], ['stat_indicator.key'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['release_id'], ['stat_release.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('release_id', 'indicator_key', 'region_level', 'region_key', 'dim_key', name='uq_stat_value')
    )
    op.create_index('ix_stat_value_lookup', 'stat_value', ['indicator_key', 'region_level', 'region_key'], unique=False)
    op.create_index(op.f('ix_stat_value_release_id'), 'stat_value', ['release_id'], unique=False)
    op.create_table('scan_task',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('run_id', sa.Integer(), nullable=False),
    sa.Column('kind', sa.String(length=16), nullable=False),
    sa.Column('partition_key', sa.String(length=200), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('status_detail', sa.Text(), nullable=True),
    sa.Column('checkpoint', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('pages_fetched', sa.Integer(), server_default='0', nullable=False),
    sa.Column('ids_found', sa.Integer(), server_default='0', nullable=False),
    sa.Column('reported_total', sa.Integer(), nullable=True),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['run_id'], ['scan_run.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('run_id', 'kind', 'partition_key', name='uq_task_run_kind_partition')
    )
    op.create_index(op.f('ix_scan_task_run_id'), 'scan_task', ['run_id'], unique=False)
    op.create_table('source_posting',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('source_id', sa.Integer(), nullable=False),
    sa.Column('source_key', sa.String(length=200), nullable=False),
    sa.Column('original_url', sa.Text(), nullable=False),
    sa.Column('canonical_url', sa.Text(), nullable=True),
    sa.Column('employer_id', sa.Integer(), nullable=True),
    sa.Column('merged_posting_id', sa.Integer(), nullable=True),
    sa.Column('current_version_id', sa.Integer(), nullable=True),
    sa.Column('first_seen_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('first_seen_date', sa.Date(), nullable=False),
    sa.Column('first_seen_run_id', sa.Integer(), nullable=True),
    sa.Column('first_seen_baseline', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_seen_date', sa.Date(), nullable=False),
    sa.Column('last_detail_check_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('detail_due', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('list_hash', sa.String(length=64), nullable=True),
    sa.Column('raw_hash', sa.String(length=64), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('status_reason', sa.Text(), nullable=True),
    sa.Column('status_changed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('gone_confirmations', sa.Integer(), server_default='0', nullable=False),
    sa.Column('gone_last_date', sa.Date(), nullable=True),
    sa.Column('is_synthetic', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.CheckConstraint("status IN ('active', 'not_reobserved', 'presumed_removed', 'ended', 'stale')", name='ck_sp_status'),
    sa.ForeignKeyConstraint(['current_version_id'], ['posting_version.id'], name='fk_sp_current_version', ondelete='SET NULL', use_alter=True),
    sa.ForeignKeyConstraint(['employer_id'], ['employer.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['first_seen_run_id'], ['scan_run.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['merged_posting_id'], ['merged_posting.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['source_id'], ['source.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('source_id', 'source_key', name='uq_sp_source_key')
    )
    op.create_index(op.f('ix_source_posting_employer_id'), 'source_posting', ['employer_id'], unique=False)
    op.create_index(op.f('ix_source_posting_merged_posting_id'), 'source_posting', ['merged_posting_id'], unique=False)
    op.create_index(op.f('ix_source_posting_source_id'), 'source_posting', ['source_id'], unique=False)
    op.create_index(op.f('ix_source_posting_status'), 'source_posting', ['status'], unique=False)
    op.create_index('ix_sp_canonical_url', 'source_posting', ['canonical_url'], unique=False)
    op.create_index('ix_sp_detail_due', 'source_posting', ['source_id'], unique=False, postgresql_where=sa.text('detail_due'))
    op.create_table('activity_period',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('source_posting_id', sa.Integer(), nullable=False),
    sa.Column('start_date', sa.Date(), nullable=False),
    sa.Column('end_date', sa.Date(), nullable=True),
    sa.Column('end_reason', sa.String(length=20), nullable=True),
    sa.ForeignKeyConstraint(['source_posting_id'], ['source_posting.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_period_dates', 'activity_period', ['start_date', 'end_date'], unique=False)
    op.create_index('ix_period_sp', 'activity_period', ['source_posting_id', 'start_date'], unique=False)
    op.create_index('uq_period_open', 'activity_period', ['source_posting_id'], unique=True, postgresql_where=sa.text('end_date IS NULL'))
    op.create_table('merge_block',
    sa.Column('a_source_posting_id', sa.Integer(), nullable=False),
    sa.Column('b_source_posting_id', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.String(length=80), nullable=True),
    sa.ForeignKeyConstraint(['a_source_posting_id'], ['source_posting.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['b_source_posting_id'], ['source_posting.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('a_source_posting_id', 'b_source_posting_id')
    )
    op.create_table('merge_candidate',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('a_source_posting_id', sa.Integer(), nullable=False),
    sa.Column('b_source_posting_id', sa.Integer(), nullable=False),
    sa.Column('reason', sa.String(length=60), nullable=False),
    sa.Column('score', sa.Numeric(precision=4, scale=3), nullable=False),
    sa.Column('rule_version', sa.String(length=32), nullable=False),
    sa.Column('state', sa.String(length=12), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('decided_by', sa.String(length=80), nullable=True),
    sa.ForeignKeyConstraint(['a_source_posting_id'], ['source_posting.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['b_source_posting_id'], ['source_posting.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('a_source_posting_id', 'b_source_posting_id', name='uq_merge_candidate_pair')
    )
    op.create_index(op.f('ix_merge_candidate_a_source_posting_id'), 'merge_candidate', ['a_source_posting_id'], unique=False)
    op.create_index(op.f('ix_merge_candidate_b_source_posting_id'), 'merge_candidate', ['b_source_posting_id'], unique=False)
    op.create_table('merge_link',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('merged_posting_id', sa.Integer(), nullable=False),
    sa.Column('source_posting_id', sa.Integer(), nullable=False),
    sa.Column('matched_source_posting_id', sa.Integer(), nullable=True),
    sa.Column('reason', sa.String(length=40), nullable=False),
    sa.Column('confidence', sa.Numeric(precision=4, scale=3), nullable=False),
    sa.Column('rule_version', sa.String(length=32), nullable=False),
    sa.Column('decided_by', sa.String(length=80), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('undone_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('undone_by', sa.String(length=80), nullable=True),
    sa.ForeignKeyConstraint(['matched_source_posting_id'], ['source_posting.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['merged_posting_id'], ['merged_posting.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['source_posting_id'], ['source_posting.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_merge_link_merged_posting_id'), 'merge_link', ['merged_posting_id'], unique=False)
    op.create_index(op.f('ix_merge_link_source_posting_id'), 'merge_link', ['source_posting_id'], unique=False)
    op.create_index('uq_merge_link_active', 'merge_link', ['source_posting_id'], unique=True, postgresql_where=sa.text('is_active'))
    op.create_table('posting_scope',
    sa.Column('source_posting_id', sa.Integer(), nullable=False),
    sa.Column('scope_id', sa.Integer(), nullable=False),
    sa.Column('first_run_id', sa.Integer(), nullable=True),
    sa.Column('last_seen_run_id', sa.Integer(), nullable=True),
    sa.Column('last_seen_date', sa.Date(), nullable=False),
    sa.Column('missed_complete_runs', sa.Integer(), server_default='0', nullable=False),
    sa.ForeignKeyConstraint(['first_run_id'], ['scan_run.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['last_seen_run_id'], ['scan_run.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['scope_id'], ['search_scope.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['source_posting_id'], ['source_posting.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('source_posting_id', 'scope_id')
    )
    op.create_index('ix_posting_scope_scope', 'posting_scope', ['scope_id', 'missed_complete_runs'], unique=False)
    op.create_table('posting_version',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('source_posting_id', sa.Integer(), nullable=False),
    sa.Column('version_no', sa.Integer(), nullable=False),
    sa.Column('change_kind', sa.String(length=16), nullable=False),
    sa.Column('detail_level', sa.String(length=8), nullable=False),
    sa.Column('content_hash', sa.String(length=64), nullable=False),
    sa.Column('raw_hash', sa.String(length=64), nullable=True),
    sa.Column('parser_version', sa.String(length=32), nullable=False),
    sa.Column('classifier_version', sa.String(length=32), nullable=False),
    sa.Column('geo_rule_version', sa.String(length=32), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('run_id', sa.Integer(), nullable=True),
    sa.Column('valid_from', sa.Date(), nullable=False),
    sa.Column('valid_to', sa.Date(), nullable=True),
    sa.Column('title', sa.Text(), nullable=False),
    sa.Column('title_norm', sa.Text(), nullable=False),
    sa.Column('employer_name', sa.Text(), nullable=True),
    sa.Column('employer_norm', sa.Text(), nullable=True),
    sa.Column('reference', sa.Text(), nullable=True),
    sa.Column('employer_url', sa.Text(), nullable=True),
    sa.Column('is_agency', sa.Boolean(), nullable=True),
    sa.Column('kind', sa.String(length=20), nullable=False),
    sa.Column('employment_types', postgresql.ARRAY(sa.Text()), server_default='{}', nullable=False),
    sa.Column('working_time', postgresql.ARRAY(sa.Text()), server_default='{}', nullable=False),
    sa.Column('contract_term', sa.String(length=16), nullable=True),
    sa.Column('remote_type', sa.String(length=16), nullable=True),
    sa.Column('occupation_label', sa.Text(), nullable=True),
    sa.Column('occupation_field', sa.Text(), nullable=True),
    sa.Column('kldb_code', sa.String(length=5), nullable=True),
    sa.Column('kldb_source', sa.String(length=24), nullable=True),
    sa.Column('kldb_confidence', sa.Numeric(precision=4, scale=3), nullable=True),
    sa.Column('requirement_level', sa.SmallInteger(), nullable=True),
    sa.Column('salary_min', sa.Numeric(precision=12, scale=2), nullable=True),
    sa.Column('salary_max', sa.Numeric(precision=12, scale=2), nullable=True),
    sa.Column('salary_currency', sa.String(length=3), nullable=True),
    sa.Column('salary_period', sa.String(length=8), nullable=True),
    sa.Column('salary_origin', sa.String(length=20), nullable=True),
    sa.Column('salary_text', sa.Text(), nullable=True),
    sa.Column('date_posted', sa.Date(), nullable=True),
    sa.Column('apply_until', sa.Date(), nullable=True),
    sa.Column('valid_through', sa.Date(), nullable=True),
    sa.Column('excerpts', postgresql.ARRAY(sa.Text()), server_default='{}', nullable=False),
    sa.Column('quality', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('kreis_keys', postgresql.ARRAY(sa.Text()), server_default='{}', nullable=False),
    sa.Column('state_keys', postgresql.ARRAY(sa.Text()), server_default='{}', nullable=False),
    sa.Column('loc_total', sa.Integer(), server_default='0', nullable=False),
    sa.Column('loc_unresolved', sa.Integer(), server_default='0', nullable=False),
    sa.Column('geo_class', sa.String(length=20), server_default='none', nullable=False),
    sa.Column('feature_keys', postgresql.ARRAY(sa.Text()), server_default='{}', nullable=False),
    sa.Column('feature_required_keys', postgresql.ARRAY(sa.Text()), server_default='{}', nullable=False),
    sa.Column('search_a', sa.Text(), server_default='', nullable=False),
    sa.Column('search_b', sa.Text(), server_default='', nullable=False),
    sa.Column('search_c', sa.Text(), server_default='', nullable=False),
    sa.Column('tsv', postgresql.TSVECTOR(), sa.Computed("setweight(to_tsvector('simple', search_a), 'A') || setweight(to_tsvector('german', search_a), 'A') || setweight(to_tsvector('simple', search_b), 'B') || setweight(to_tsvector('simple', search_c), 'C') || setweight(to_tsvector('german', search_c), 'C')", persisted=True), nullable=False),
    sa.CheckConstraint("change_kind IN ('initial', 'enrichment', 'content', 'parser', 'mixed')", name='ck_version_change_kind'),
    sa.CheckConstraint("geo_class IN ('resolved', 'partial', 'unresolved', 'remote_nationwide', 'foreign', 'none')", name='ck_version_geo_class'),
    sa.ForeignKeyConstraint(['run_id'], ['scan_run.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['source_posting_id'], ['source_posting.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('source_posting_id', 'version_no', name='uq_version_sp_no')
    )
    op.create_index(op.f('ix_posting_version_kldb_code'), 'posting_version', ['kldb_code'], unique=False)
    op.create_index('ix_version_emp_title', 'posting_version', ['employer_norm', 'title_norm'], unique=False)
    op.create_index('ix_version_employer_trgm', 'posting_version', ['search_b'], unique=False, postgresql_using='gin', postgresql_ops={'search_b': 'gin_trgm_ops'})
    op.create_index('ix_version_employer_url', 'posting_version', ['employer_url'], unique=False, postgresql_where=sa.text('employer_url IS NOT NULL'))
    op.create_index('ix_version_features', 'posting_version', ['feature_keys'], unique=False, postgresql_using='gin')
    op.create_index('ix_version_kreise', 'posting_version', ['kreis_keys'], unique=False, postgresql_using='gin')
    op.create_index('ix_version_reference', 'posting_version', ['employer_norm', 'reference'], unique=False, postgresql_where=sa.text('reference IS NOT NULL'))
    op.create_index('ix_version_sp_valid', 'posting_version', ['source_posting_id', 'valid_from'], unique=False)
    op.create_index('ix_version_states', 'posting_version', ['state_keys'], unique=False, postgresql_using='gin')
    op.create_index('ix_version_title_trgm', 'posting_version', ['search_a'], unique=False, postgresql_using='gin', postgresql_ops={'search_a': 'gin_trgm_ops'})
    op.create_index('ix_version_tsv', 'posting_version', ['tsv'], unique=False, postgresql_using='gin')
    op.create_index('ix_version_valid_from', 'posting_version', ['valid_from', 'change_kind'], unique=False)
    op.create_table('scan_error',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('run_id', sa.Integer(), nullable=False),
    sa.Column('task_id', sa.Integer(), nullable=True),
    sa.Column('at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('kind', sa.String(length=32), nullable=False),
    sa.Column('url', sa.Text(), nullable=True),
    sa.Column('message', sa.Text(), nullable=True),
    sa.ForeignKeyConstraint(['run_id'], ['scan_run.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['task_id'], ['scan_task.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_scan_error_at'), 'scan_error', ['at'], unique=False)
    op.create_index(op.f('ix_scan_error_run_id'), 'scan_error', ['run_id'], unique=False)
    op.create_table('observation',
    sa.Column('run_id', sa.Integer(), nullable=False),
    sa.Column('source_posting_id', sa.Integer(), nullable=False),
    sa.Column('version_id', sa.Integer(), nullable=True),
    sa.Column('seen_list', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('seen_detail', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('observed_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['run_id'], ['scan_run.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['source_posting_id'], ['source_posting.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['version_id'], ['posting_version.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('run_id', 'source_posting_id')
    )
    op.create_index('ix_observation_sp', 'observation', ['source_posting_id', 'run_id'], unique=False)
    op.create_table('posting_event',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('event_date', sa.Date(), nullable=False),
    sa.Column('effective_date', sa.Date(), nullable=False),
    sa.Column('event_type', sa.String(length=24), nullable=False),
    sa.Column('merged_posting_id', sa.Integer(), nullable=True),
    sa.Column('source_posting_id', sa.Integer(), nullable=True),
    sa.Column('version_id', sa.Integer(), nullable=True),
    sa.Column('run_id', sa.Integer(), nullable=True),
    sa.Column('baseline', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('details', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.ForeignKeyConstraint(['merged_posting_id'], ['merged_posting.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['run_id'], ['scan_run.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['source_posting_id'], ['source_posting.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['version_id'], ['posting_version.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_event_type_date', 'posting_event', ['event_type', 'effective_date'], unique=False)
    op.create_index(op.f('ix_posting_event_merged_posting_id'), 'posting_event', ['merged_posting_id'], unique=False)
    op.create_index(op.f('ix_posting_event_source_posting_id'), 'posting_event', ['source_posting_id'], unique=False)
    op.create_table('posting_feature',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('version_id', sa.Integer(), nullable=False),
    sa.Column('feature_key', sa.String(length=80), nullable=False),
    sa.Column('type', sa.String(length=20), nullable=False),
    sa.Column('label', sa.Text(), nullable=False),
    sa.Column('polarity', sa.String(length=12), nullable=False),
    sa.Column('origin', sa.String(length=24), nullable=False),
    sa.Column('rule_version', sa.String(length=32), nullable=False),
    sa.Column('confidence', sa.Numeric(precision=4, scale=3), nullable=True),
    sa.Column('evidence', sa.Text(), nullable=True),
    sa.Column('detail', sa.Text(), nullable=True),
    sa.CheckConstraint("polarity IN ('required', 'desired', 'negated', 'unclear')", name='ck_feature_polarity'),
    sa.ForeignKeyConstraint(['version_id'], ['posting_version.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_posting_feature_feature_key'), 'posting_feature', ['feature_key'], unique=False)
    op.create_index(op.f('ix_posting_feature_version_id'), 'posting_feature', ['version_id'], unique=False)
    op.create_geospatial_table('posting_location',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('version_id', sa.Integer(), nullable=False),
    sa.Column('ordinal', sa.SmallInteger(), nullable=False),
    sa.Column('raw_text', sa.Text(), nullable=True),
    sa.Column('locality', sa.Text(), nullable=True),
    sa.Column('postal_code', sa.String(length=10), nullable=True),
    sa.Column('region_text', sa.Text(), nullable=True),
    sa.Column('country', sa.String(length=2), nullable=True),
    sa.Column('kreis_key', sa.String(length=5), nullable=True),
    sa.Column('state_key', sa.String(length=2), nullable=True),
    sa.Column('ags', sa.String(length=8), nullable=True),
    sa.Column('gebietsstand', sa.Date(), nullable=True),
    sa.Column('match_method', sa.String(length=32), nullable=False),
    sa.Column('precision', sa.String(length=20), nullable=False),
    sa.Column('confidence', sa.Numeric(precision=4, scale=3), nullable=True),
    sa.Column('point', Geometry(geometry_type='POINT', srid=4326, dimension=2, spatial_index=False, from_text='ST_GeomFromEWKT', name='geometry'), nullable=True),
    sa.Column('point_origin', sa.String(length=20), nullable=True),
    sa.ForeignKeyConstraint(['version_id'], ['posting_version.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_geospatial_index('idx_posting_location_point', 'posting_location', ['point'], unique=False, postgresql_using='gist', postgresql_ops={})
    op.create_index(op.f('ix_posting_location_kreis_key'), 'posting_location', ['kreis_key'], unique=False)
    op.create_index(op.f('ix_posting_location_version_id'), 'posting_location', ['version_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_posting_location_version_id'), table_name='posting_location')
    op.drop_index(op.f('ix_posting_location_kreis_key'), table_name='posting_location')
    op.drop_geospatial_index('idx_posting_location_point', table_name='posting_location', postgresql_using='gist', column_name='point')
    op.drop_geospatial_table('posting_location')
    op.drop_index(op.f('ix_posting_feature_version_id'), table_name='posting_feature')
    op.drop_index(op.f('ix_posting_feature_feature_key'), table_name='posting_feature')
    op.drop_table('posting_feature')
    op.drop_index(op.f('ix_posting_event_source_posting_id'), table_name='posting_event')
    op.drop_index(op.f('ix_posting_event_merged_posting_id'), table_name='posting_event')
    op.drop_index('ix_event_type_date', table_name='posting_event')
    op.drop_table('posting_event')
    op.drop_index('ix_observation_sp', table_name='observation')
    op.drop_table('observation')
    op.drop_index(op.f('ix_scan_error_run_id'), table_name='scan_error')
    op.drop_index(op.f('ix_scan_error_at'), table_name='scan_error')
    op.drop_table('scan_error')
    op.drop_index('ix_version_valid_from', table_name='posting_version')
    op.drop_index('ix_version_tsv', table_name='posting_version', postgresql_using='gin')
    op.drop_index('ix_version_title_trgm', table_name='posting_version', postgresql_using='gin', postgresql_ops={'search_a': 'gin_trgm_ops'})
    op.drop_index('ix_version_states', table_name='posting_version', postgresql_using='gin')
    op.drop_index('ix_version_sp_valid', table_name='posting_version')
    op.drop_index('ix_version_reference', table_name='posting_version', postgresql_where=sa.text('reference IS NOT NULL'))
    op.drop_index('ix_version_kreise', table_name='posting_version', postgresql_using='gin')
    op.drop_index('ix_version_features', table_name='posting_version', postgresql_using='gin')
    op.drop_index('ix_version_employer_url', table_name='posting_version', postgresql_where=sa.text('employer_url IS NOT NULL'))
    op.drop_index('ix_version_employer_trgm', table_name='posting_version', postgresql_using='gin', postgresql_ops={'search_b': 'gin_trgm_ops'})
    op.drop_index('ix_version_emp_title', table_name='posting_version')
    op.drop_index(op.f('ix_posting_version_kldb_code'), table_name='posting_version')
    op.drop_table('posting_version')
    op.drop_index('ix_posting_scope_scope', table_name='posting_scope')
    op.drop_table('posting_scope')
    op.drop_index('uq_merge_link_active', table_name='merge_link', postgresql_where=sa.text('is_active'))
    op.drop_index(op.f('ix_merge_link_source_posting_id'), table_name='merge_link')
    op.drop_index(op.f('ix_merge_link_merged_posting_id'), table_name='merge_link')
    op.drop_table('merge_link')
    op.drop_index(op.f('ix_merge_candidate_b_source_posting_id'), table_name='merge_candidate')
    op.drop_index(op.f('ix_merge_candidate_a_source_posting_id'), table_name='merge_candidate')
    op.drop_table('merge_candidate')
    op.drop_table('merge_block')
    op.drop_index('uq_period_open', table_name='activity_period', postgresql_where=sa.text('end_date IS NULL'))
    op.drop_index('ix_period_sp', table_name='activity_period')
    op.drop_index('ix_period_dates', table_name='activity_period')
    op.drop_table('activity_period')
    op.drop_index('ix_sp_detail_due', table_name='source_posting', postgresql_where=sa.text('detail_due'))
    op.drop_index('ix_sp_canonical_url', table_name='source_posting')
    op.drop_index(op.f('ix_source_posting_status'), table_name='source_posting')
    op.drop_index(op.f('ix_source_posting_source_id'), table_name='source_posting')
    op.drop_index(op.f('ix_source_posting_merged_posting_id'), table_name='source_posting')
    op.drop_index(op.f('ix_source_posting_employer_id'), table_name='source_posting')
    op.drop_table('source_posting')
    op.drop_index(op.f('ix_scan_task_run_id'), table_name='scan_task')
    op.drop_table('scan_task')
    op.drop_index(op.f('ix_stat_value_release_id'), table_name='stat_value')
    op.drop_index('ix_stat_value_lookup', table_name='stat_value')
    op.drop_table('stat_value')
    op.drop_index('uq_run_scope_day', table_name='scan_run', postgresql_where=sa.text('NOT is_test'))
    op.drop_index(op.f('ix_scan_run_status'), table_name='scan_run')
    op.drop_index(op.f('ix_scan_run_source_id'), table_name='scan_run')
    op.drop_index(op.f('ix_scan_run_scope_id'), table_name='scan_run')
    op.drop_index(op.f('ix_scan_run_logical_date'), table_name='scan_run')
    op.drop_index('ix_run_source_date', table_name='scan_run')
    op.drop_table('scan_run')
    op.drop_index(op.f('ix_user_session_user_id'), table_name='user_session')
    op.drop_table('user_session')
    op.drop_index(op.f('ix_timeline_note_note_date'), table_name='timeline_note')
    op.drop_table('timeline_note')
    op.drop_index('uq_release_current', table_name='stat_release', postgresql_where=sa.text('is_current'))
    op.drop_index(op.f('ix_stat_release_dataset_key'), table_name='stat_release')
    op.drop_table('stat_release')
    op.drop_table('stat_indicator')
    op.drop_index('uq_scope_one_active', table_name='search_scope', postgresql_where=sa.text('is_active'))
    op.drop_index(op.f('ix_search_scope_source_id'), table_name='search_scope')
    op.drop_table('search_scope')
    op.drop_index(op.f('ix_saved_search_user_id'), table_name='saved_search')
    op.drop_table('saved_search')
    op.drop_index('uq_warning_open', table_name='ops_warning', postgresql_where=sa.text('resolved_at IS NULL'))
    op.drop_table('ops_warning')
    op.drop_table('stat_dataset')
    op.drop_table('source')
    op.drop_table('robots_cache')
    op.drop_index('ix_region_current', table_name='region', postgresql_where=sa.text('is_current'))
    op.drop_geospatial_index('idx_region_geom', table_name='region', postgresql_using='gist', column_name='geom')
    op.drop_geospatial_table('region')
    op.drop_index(op.f('ix_postal_code_plz'), table_name='postal_code')
    op.drop_table('postal_code')
    op.drop_index('ix_occupation_title_trgm', table_name='occupation_title', postgresql_using='gin', postgresql_ops={'title_norm': 'gin_trgm_ops'})
    op.drop_index(op.f('ix_occupation_title_title_norm'), table_name='occupation_title')
    op.drop_index(op.f('ix_occupation_title_kldb_code'), table_name='occupation_title')
    op.drop_table('occupation_title')
    op.drop_index('ix_merged_source_ids', table_name='merged_posting', postgresql_using='gin')
    op.drop_index(op.f('ix_merged_posting_status'), table_name='merged_posting')
    op.drop_index(op.f('ix_merged_posting_first_seen_date'), table_name='merged_posting')
    op.drop_index(op.f('ix_merged_posting_current_version_id'), table_name='merged_posting')
    op.drop_table('merged_posting')
    op.drop_table('kldb_class')
    op.drop_index('uq_job_dedupe_open', table_name='job', postgresql_where=sa.text("status IN ('queued','running')"))
    op.drop_index('ix_job_queue', table_name='job')
    op.drop_table('job')
    op.drop_index('ix_place_name_trgm', table_name='geo_place', postgresql_using='gin', postgresql_ops={'name_norm': 'gin_trgm_ops'})
    op.drop_index(op.f('ix_geo_place_postal_code'), table_name='geo_place')
    op.drop_index(op.f('ix_geo_place_name_norm'), table_name='geo_place')
    op.drop_index(op.f('ix_geo_place_kreis_key'), table_name='geo_place')
    op.drop_table('geo_place')
    op.drop_table('fetch_cache')
    op.drop_index(op.f('ix_feature_type'), table_name='feature')
    op.drop_table('feature')
    op.drop_table('employer')
    op.drop_table('daily_aggregate')
    op.drop_index(op.f('ix_audit_log_at'), table_name='audit_log')
    op.drop_table('audit_log')
    op.drop_table('app_user')
    op.drop_table('app_state')
