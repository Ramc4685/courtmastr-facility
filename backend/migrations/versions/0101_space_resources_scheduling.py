"""build module 2 (lane space): resources (groups, resource tree, links, availability windows), scheduling
(settings, reservation categories and types, series, bookings, booking resources, resource holds with the
exclusion constraint of ADR 0004, blackouts, sessions) and the session slice of programs (enrollment,
attendance, waitlist_entry). Also the staff_user.linked_resource_id foreign key (data-model-core 9.8).

Generated from the models, then completed by hand: plain types and enable_rls() per table.

Revision ID: 0101
Revises: 0002
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.core.db.rls import enable_rls

revision = "0101"
down_revision = "0203"

TENANT_TABLES = (
    "blackout",
    "reservation_category",
    "resource_group",
    "scheduling_settings",
    "reservation_type",
    "resource",
    "availability_window",
    "resource_link",
    "booking_series",
    "booking_series_rule",
    "booking",
    "booking_series_run",
    "booking_resource",
    "resource_hold",
    "session",
    "enrollment",
    "attendance",
    "waitlist_entry",
)


def upgrade() -> None:
    # Every new tenant-owned table must call enable_rls("<table>") (append_only=True for ledgers and logs).
    op.create_table('blackout',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('location_id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('during', postgresql.TSTZRANGE(), nullable=False),
    sa.Column('scope', sa.Text(), server_default=sa.text("'all'"), nullable=False),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("scope IN ('all', 'online_only')", name=op.f('ck_blackout_scope')),
    sa.CheckConstraint('NOT isempty(during)', name=op.f('ck_blackout_during')),
    sa.ForeignKeyConstraint(['tenant_id', 'location_id'], ['location.tenant_id', 'location.id'], name=op.f('fk_blackout_location_id_location'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_blackout_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_blackout')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_blackout_tenant_id_id'))
    )
    op.create_index('ix_blackout_span', 'blackout', ['tenant_id', 'location_id', 'during'], unique=False, postgresql_using='gist')
    op.create_table('reservation_category',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('location_id', sa.Uuid(), nullable=False),
    sa.Column('parent_id', sa.Uuid(), nullable=True),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('sort_order', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['tenant_id', 'location_id'], ['location.tenant_id', 'location.id'], name=op.f('fk_reservation_category_location_id_location'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'parent_id'], ['reservation_category.tenant_id', 'reservation_category.id'], name=op.f('fk_reservation_category_parent_id_reservation_category'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_reservation_category_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_reservation_category')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_reservation_category_tenant_id_id'))
    )
    op.create_index(op.f('ix_reservation_category_location_id'), 'reservation_category', ['tenant_id', 'location_id'], unique=False)
    op.create_index(op.f('ix_reservation_category_parent_id'), 'reservation_category', ['tenant_id', 'parent_id'], unique=False)
    op.create_index('uq_reservation_category_name', 'reservation_category', ['tenant_id', 'location_id', 'parent_id', 'name'], unique=True, postgresql_where=sa.text('is_active'), postgresql_nulls_not_distinct=True)
    op.create_table('resource_group',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('location_id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('sort_order', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['tenant_id', 'location_id'], ['location.tenant_id', 'location.id'], name=op.f('fk_resource_group_location_id_location'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_resource_group_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_resource_group')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_resource_group_tenant_id_id'))
    )
    op.create_index(op.f('ix_resource_group_location_id'), 'resource_group', ['tenant_id', 'location_id'], unique=False)
    op.create_index('uq_resource_group_name', 'resource_group', ['tenant_id', 'location_id', 'name'], unique=True, postgresql_where=sa.text('is_active'))
    op.create_table('scheduling_settings',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('location_id', sa.Uuid(), nullable=True),
    sa.Column('default_buffer_before_min', sa.SmallInteger(), server_default=sa.text('0'), nullable=False),
    sa.Column('default_buffer_after_min', sa.SmallInteger(), server_default=sa.text('0'), nullable=False),
    sa.Column('drag_drop_default', sa.Text(), server_default=sa.text("'ask'"), nullable=False),
    sa.Column('calendar_slot_min', sa.SmallInteger(), server_default=sa.text('15'), nullable=False),
    sa.Column('checkout_hold_min', sa.SmallInteger(), server_default=sa.text('10'), nullable=False),
    sa.Column('max_series_occurrences', sa.Integer(), server_default=sa.text('2000'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("drag_drop_default IN ('ask', 'reschedule', 'move_enrollment')", name=op.f('ck_scheduling_settings_drag_drop_default')),
    sa.CheckConstraint('calendar_slot_min IN (5, 10, 15, 20, 30, 60)', name=op.f('ck_scheduling_settings_calendar_slot')),
    sa.CheckConstraint('checkout_hold_min BETWEEN 5 AND 30', name=op.f('ck_scheduling_settings_checkout_hold')),
    sa.CheckConstraint('default_buffer_before_min BETWEEN 0 AND 240 AND default_buffer_after_min BETWEEN 0 AND 240', name=op.f('ck_scheduling_settings_buffers')),
    sa.CheckConstraint('max_series_occurrences BETWEEN 1 AND 2000', name=op.f('ck_scheduling_settings_max_series')),
    sa.ForeignKeyConstraint(['tenant_id', 'location_id'], ['location.tenant_id', 'location.id'], name=op.f('fk_scheduling_settings_location_id_location'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_scheduling_settings_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_scheduling_settings')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_scheduling_settings_tenant_id_id'))
    )
    op.create_index('uq_scheduling_settings', 'scheduling_settings', ['tenant_id', 'location_id'], unique=True, postgresql_nulls_not_distinct=True)
    op.create_table('reservation_type',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('location_id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('is_schedulable', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('is_sellable', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('revenue_category_id', sa.Uuid(), nullable=True),
    sa.Column('reservation_category_id', sa.Uuid(), nullable=True),
    sa.Column('default_capacity', sa.Integer(), server_default=sa.text('1'), nullable=False),
    sa.Column('default_duration_min', sa.Integer(), nullable=True),
    sa.Column('default_allows_free_booking', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('color', sa.Text(), nullable=True),
    sa.Column('uses_default_buffer', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('buffer_before_min', sa.SmallInteger(), server_default=sa.text('0'), nullable=False),
    sa.Column('buffer_after_min', sa.SmallInteger(), server_default=sa.text('0'), nullable=False),
    sa.Column('is_self_bookable_default', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('sort_order', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("color ~ '^#[0-9a-f]{6}$'", name=op.f('ck_reservation_type_color')),
    sa.CheckConstraint('buffer_before_min BETWEEN 0 AND 240 AND buffer_after_min BETWEEN 0 AND 240', name=op.f('ck_reservation_type_buffers')),
    sa.CheckConstraint('default_capacity >= 0', name=op.f('ck_reservation_type_capacity')),
    sa.CheckConstraint('default_duration_min IS NULL OR default_duration_min > 0', name=op.f('ck_reservation_type_duration')),
    sa.ForeignKeyConstraint(['tenant_id', 'location_id'], ['location.tenant_id', 'location.id'], name=op.f('fk_reservation_type_location_id_location'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'reservation_category_id'], ['reservation_category.tenant_id', 'reservation_category.id'], name=op.f('fk_reservation_type_reservation_category_id_reservation_category'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'revenue_category_id'], ['revenue_category.tenant_id', 'revenue_category.id'], name=op.f('fk_reservation_type_revenue_category_id_revenue_category'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_reservation_type_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_reservation_type')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_reservation_type_tenant_id_id'))
    )
    op.create_index('ix_reservation_type_order', 'reservation_type', ['tenant_id', 'location_id', 'sort_order'], unique=False)
    op.create_index(op.f('ix_reservation_type_reservation_category_id'), 'reservation_type', ['tenant_id', 'reservation_category_id'], unique=False)
    op.create_index(op.f('ix_reservation_type_revenue_category_id'), 'reservation_type', ['tenant_id', 'revenue_category_id'], unique=False)
    op.create_index('uq_reservation_type_name', 'reservation_type', ['tenant_id', 'location_id', 'name'], unique=True, postgresql_where=sa.text('is_active'))
    op.create_table('resource',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('location_id', sa.Uuid(), nullable=False),
    sa.Column('resource_group_id', sa.Uuid(), nullable=False),
    sa.Column('parent_id', sa.Uuid(), nullable=True),
    sa.Column('kind', sa.Text(), nullable=False),
    sa.Column('external_ref', sa.Text(), nullable=True),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('public_name', sa.Text(), nullable=True),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('sort_order', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('is_online_bookable', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('counts_toward_plan', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('status', sa.Text(), server_default=sa.text("'active'"), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("(kind = 'virtual_room') = (external_ref IS NOT NULL)", name=op.f('ck_resource_external_ref')),
    sa.CheckConstraint("btrim(name) <> ''", name=op.f('ck_resource_name')),
    sa.CheckConstraint("kind = 'venue' OR parent_id IS NULL", name=op.f('ck_resource_trainer_flat')),
    sa.CheckConstraint("kind IN ('venue', 'trainer', 'virtual_room')", name=op.f('ck_resource_kind')),
    sa.CheckConstraint("status IN ('active', 'archived')", name=op.f('ck_resource_status')),
    sa.CheckConstraint('parent_id <> id', name=op.f('ck_resource_not_own_parent')),
    sa.ForeignKeyConstraint(['tenant_id', 'location_id'], ['location.tenant_id', 'location.id'], name=op.f('fk_resource_location_id_location'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'parent_id'], ['resource.tenant_id', 'resource.id'], name=op.f('fk_resource_parent_id_resource'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'resource_group_id'], ['resource_group.tenant_id', 'resource_group.id'], name=op.f('fk_resource_resource_group_id_resource_group'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_resource_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_resource')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_resource_tenant_id_id'))
    )
    op.create_index('ix_resource_group_order', 'resource', ['tenant_id', 'location_id', 'resource_group_id', 'sort_order'], unique=False)
    op.create_index(op.f('ix_resource_location_id'), 'resource', ['tenant_id', 'location_id'], unique=False)
    op.create_index(op.f('ix_resource_parent_id'), 'resource', ['tenant_id', 'parent_id'], unique=False)
    op.create_index('uq_resource_name', 'resource', ['tenant_id', 'location_id', 'parent_id', 'name'], unique=True, postgresql_where=sa.text("status = 'active'"), postgresql_nulls_not_distinct=True)
    op.create_table('availability_window',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('location_id', sa.Uuid(), nullable=False),
    sa.Column('resource_id', sa.Uuid(), nullable=False),
    sa.Column('starts_on', sa.Date(), nullable=False),
    sa.Column('ends_on', sa.Date(), nullable=True),
    sa.Column('weekdays', postgresql.ARRAY(sa.SmallInteger()), nullable=False),
    sa.Column('interval_weeks', sa.SmallInteger(), server_default=sa.text('1'), nullable=False),
    sa.Column('start_time', sa.Time(), nullable=False),
    sa.Column('end_time', sa.Time(), nullable=False),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('end_time > start_time', name=op.f('ck_availability_window_times')),
    sa.CheckConstraint('ends_on IS NULL OR ends_on >= starts_on', name=op.f('ck_availability_window_dates')),
    sa.CheckConstraint('interval_weeks BETWEEN 1 AND 8', name=op.f('ck_availability_window_interval')),
    sa.CheckConstraint('weekdays <@ ARRAY[1,2,3,4,5,6,7]::smallint[] AND cardinality(weekdays) > 0', name=op.f('ck_availability_window_weekdays')),
    sa.ForeignKeyConstraint(['tenant_id', 'location_id'], ['location.tenant_id', 'location.id'], name=op.f('fk_availability_window_location_id_location'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'resource_id'], ['resource.tenant_id', 'resource.id'], name=op.f('fk_availability_window_resource_id_resource'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_availability_window_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_availability_window')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_availability_window_tenant_id_id'))
    )
    op.create_index(op.f('ix_availability_window_location_id'), 'availability_window', ['tenant_id', 'location_id'], unique=False)
    op.create_index('ix_availability_window_resource', 'availability_window', ['tenant_id', 'resource_id', 'starts_on'], unique=False)
    op.create_table('resource_link',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('from_resource_id', sa.Uuid(), nullable=False),
    sa.Column('to_resource_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('from_resource_id <> to_resource_id', name=op.f('ck_resource_link_distinct')),
    sa.ForeignKeyConstraint(['tenant_id', 'from_resource_id'], ['resource.tenant_id', 'resource.id'], name=op.f('fk_resource_link_from_resource_id_resource'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id', 'to_resource_id'], ['resource.tenant_id', 'resource.id'], name=op.f('fk_resource_link_to_resource_id_resource'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_resource_link_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_resource_link')),
    sa.UniqueConstraint('tenant_id', 'from_resource_id', 'to_resource_id', name='uq_resource_link'),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_resource_link_tenant_id_id'))
    )
    op.create_index(op.f('ix_resource_link_to_resource_id'), 'resource_link', ['tenant_id', 'to_resource_id'], unique=False)
    op.create_table('booking_series',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('location_id', sa.Uuid(), nullable=False),
    sa.Column('kind', sa.Text(), nullable=False),
    sa.Column('label', sa.Text(), nullable=True),
    sa.Column('created_by_staff_user_id', sa.Uuid(), nullable=True),
    sa.Column('occurrence_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("kind IN ('session', 'rental', 'block', 'game')", name=op.f('ck_booking_series_kind')),
    sa.ForeignKeyConstraint(['tenant_id', 'created_by_staff_user_id'], ['staff_user.tenant_id', 'staff_user.id'], name=op.f('fk_booking_series_created_by_staff_user_id_staff_user'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'location_id'], ['location.tenant_id', 'location.id'], name=op.f('fk_booking_series_location_id_location'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_booking_series_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_booking_series')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_booking_series_tenant_id_id'))
    )
    op.create_index(op.f('ix_booking_series_created_by_staff_user_id'), 'booking_series', ['tenant_id', 'created_by_staff_user_id'], unique=False)
    op.create_index(op.f('ix_booking_series_location_id'), 'booking_series', ['tenant_id', 'location_id'], unique=False)
    op.create_table('booking_series_rule',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('booking_series_id', sa.Uuid(), nullable=False),
    sa.Column('sequence', sa.Integer(), nullable=False),
    sa.Column('pattern', sa.Text(), nullable=False),
    sa.Column('interval_count', sa.SmallInteger(), server_default=sa.text('1'), nullable=False),
    sa.Column('weekdays', postgresql.ARRAY(sa.SmallInteger()), nullable=True),
    sa.Column('month_week', sa.SmallInteger(), nullable=True),
    sa.Column('start_on', sa.Date(), nullable=False),
    sa.Column('start_time', sa.Time(), nullable=False),
    sa.Column('end_time', sa.Time(), nullable=False),
    sa.Column('end_day_offset', sa.SmallInteger(), server_default=sa.text('0'), nullable=False),
    sa.Column('range_type', sa.Text(), nullable=False),
    sa.Column('occurrence_limit', sa.Integer(), nullable=True),
    sa.Column('until_on', sa.Date(), nullable=True),
    sa.Column('template', postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), nullable=False),
    sa.Column('status', sa.Text(), server_default=sa.text("'pending'"), nullable=False),
    sa.Column('requested_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('created_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('conflict_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('results', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'"), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("(range_type = 'count' AND occurrence_limit > 0 AND until_on IS NULL) OR (range_type = 'until' AND until_on >= start_on AND occurrence_limit IS NULL)", name=op.f('ck_booking_series_rule_range')),
    sa.CheckConstraint("pattern <> 'weekly' OR cardinality(weekdays) > 0", name=op.f('ck_booking_series_rule_weekly')),
    sa.CheckConstraint("pattern IN ('single', 'daily', 'weekly', 'monthly_by_date', 'monthly_by_weekday', 'yearly')", name=op.f('ck_booking_series_rule_pattern')),
    sa.CheckConstraint("range_type IN ('count', 'until')", name=op.f('ck_booking_series_rule_range_type')),
    sa.CheckConstraint("status IN ('pending', 'generating', 'completed', 'failed')", name=op.f('ck_booking_series_rule_status')),
    sa.CheckConstraint('end_day_offset > 0 OR end_time > start_time', name=op.f('ck_booking_series_rule_span')),
    sa.CheckConstraint('end_day_offset BETWEEN 0 AND 6', name=op.f('ck_booking_series_rule_end_day_offset')),
    sa.CheckConstraint('interval_count >= 1', name=op.f('ck_booking_series_rule_interval')),
    sa.ForeignKeyConstraint(['tenant_id', 'booking_series_id'], ['booking_series.tenant_id', 'booking_series.id'], name=op.f('fk_booking_series_rule_booking_series_id_booking_series'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_booking_series_rule_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_booking_series_rule')),
    sa.UniqueConstraint('tenant_id', 'booking_series_id', 'sequence', name='uq_booking_series_rule'),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_booking_series_rule_tenant_id_id'))
    )
    op.create_table('booking',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('location_id', sa.Uuid(), nullable=False),
    sa.Column('booking_number', sa.Integer(), nullable=False),
    sa.Column('booking_series_id', sa.Uuid(), nullable=True),
    sa.Column('booking_series_rule_id', sa.Uuid(), nullable=True),
    sa.Column('occurrence_index', sa.Integer(), nullable=True),
    sa.Column('occurrence_on', sa.Date(), nullable=False),
    sa.Column('local_start_time', sa.Time(), nullable=False),
    sa.Column('duration_min', sa.Integer(), nullable=False),
    sa.Column('kind', sa.Text(), nullable=False),
    sa.Column('block_kind', sa.Text(), nullable=True),
    sa.Column('reservation_type_id', sa.Uuid(), nullable=True),
    sa.Column('client_id', sa.Uuid(), nullable=True),
    sa.Column('title', sa.Text(), server_default=sa.text("''"), nullable=False),
    sa.Column('public_title', sa.Text(), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('starts_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('ends_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('buffer_before_min', sa.SmallInteger(), server_default=sa.text('0'), nullable=False),
    sa.Column('buffer_after_min', sa.SmallInteger(), server_default=sa.text('0'), nullable=False),
    sa.Column('status', sa.Text(), server_default=sa.text("'confirmed'"), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('cancelled_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('cancel_reason', sa.Text(), nullable=True),
    sa.Column('created_via', sa.Text(), nullable=False),
    sa.Column('created_by_staff_user_id', sa.Uuid(), nullable=True),
    sa.Column('source_context', sa.Text(), nullable=True),
    sa.Column('source_type', sa.Text(), nullable=True),
    sa.Column('source_id', sa.Uuid(), nullable=True),
    sa.Column('version', sa.Integer(), server_default=sa.text('1'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("(kind = 'block') = (block_kind IS NOT NULL)", name=op.f('ck_booking_block')),
    sa.CheckConstraint("(status = 'cancelled') = (cancelled_at IS NOT NULL)", name=op.f('ck_booking_cancelled')),
    sa.CheckConstraint("(status = 'tentative') = (expires_at IS NOT NULL)", name=op.f('ck_booking_tentative')),
    sa.CheckConstraint("block_kind IN ('floor_shift', 'instruction', 'unpaid', 'unavailable')", name=op.f('ck_booking_block_kind')),
    sa.CheckConstraint("cancel_reason IN ('staff', 'client', 'hold_expired', 'payment_failed', 'series_edit', 'other')", name=op.f('ck_booking_cancel_reason')),
    sa.CheckConstraint("created_via IN ('staff', 'portal', 'mobile', 'api', 'system')", name=op.f('ck_booking_created_via')),
    sa.CheckConstraint("kind = 'session' OR reservation_type_id IS NULL", name=op.f('ck_booking_type_only_on_session')),
    sa.CheckConstraint("kind IN ('session', 'rental', 'block', 'game')", name=op.f('ck_booking_kind')),
    sa.CheckConstraint("status IN ('tentative', 'confirmed', 'cancelled')", name=op.f('ck_booking_status')),
    sa.CheckConstraint('(source_context IS NULL) = (source_id IS NULL)', name=op.f('ck_booking_source')),
    sa.CheckConstraint('booking_series_rule_id IS NULL OR occurrence_index IS NOT NULL', name=op.f('ck_booking_occurrence')),
    sa.CheckConstraint('buffer_before_min BETWEEN 0 AND 240 AND buffer_after_min BETWEEN 0 AND 240', name=op.f('ck_booking_buffers')),
    sa.CheckConstraint('duration_min > 0', name=op.f('ck_booking_duration')),
    sa.CheckConstraint('ends_at > starts_at', name=op.f('ck_booking_span')),
    sa.ForeignKeyConstraint(['tenant_id', 'booking_series_id'], ['booking_series.tenant_id', 'booking_series.id'], name=op.f('fk_booking_booking_series_id_booking_series'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'booking_series_rule_id'], ['booking_series_rule.tenant_id', 'booking_series_rule.id'], name=op.f('fk_booking_booking_series_rule_id_booking_series_rule'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'client_id'], ['client.tenant_id', 'client.id'], name=op.f('fk_booking_client_id_client'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'created_by_staff_user_id'], ['staff_user.tenant_id', 'staff_user.id'], name=op.f('fk_booking_created_by_staff_user_id_staff_user'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'location_id'], ['location.tenant_id', 'location.id'], name=op.f('fk_booking_location_id_location'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'reservation_type_id'], ['reservation_type.tenant_id', 'reservation_type.id'], name=op.f('fk_booking_reservation_type_id_reservation_type'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_booking_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_booking')),
    sa.UniqueConstraint('tenant_id', 'booking_number', name='uq_booking_number'),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_booking_tenant_id_id'))
    )
    op.create_index('ix_booking_client', 'booking', ['tenant_id', 'client_id', 'starts_at'], unique=False, postgresql_where=sa.text('client_id IS NOT NULL'))
    op.create_index(op.f('ix_booking_created_by_staff_user_id'), 'booking', ['tenant_id', 'created_by_staff_user_id'], unique=False)
    op.create_index('ix_booking_expiring', 'booking', ['expires_at'], unique=False, postgresql_where=sa.text("status = 'tentative'"))
    op.create_index('ix_booking_location_day', 'booking', ['tenant_id', 'location_id', 'occurrence_on', 'id'], unique=False)
    op.create_index('ix_booking_series', 'booking', ['tenant_id', 'booking_series_id', 'starts_at'], unique=False, postgresql_where=sa.text('booking_series_id IS NOT NULL'))
    op.create_index('ix_booking_source', 'booking', ['tenant_id', 'source_context', 'source_type', 'source_id'], unique=False, postgresql_where=sa.text('source_id IS NOT NULL'))
    op.create_index('ix_booking_span', 'booking', ['tenant_id', 'location_id', sa.literal_column("tstzrange(starts_at, ends_at, '[)')")], unique=False, postgresql_using='gist', postgresql_where=sa.text("status <> 'cancelled'"))
    op.create_index('ix_booking_type', 'booking', ['tenant_id', 'reservation_type_id', 'starts_at'], unique=False, postgresql_where=sa.text('reservation_type_id IS NOT NULL'))
    op.create_index('uq_booking_series_rule_occurrence', 'booking', ['tenant_id', 'booking_series_rule_id', 'occurrence_index'], unique=True, postgresql_where=sa.text('booking_series_rule_id IS NOT NULL'))
    op.create_table('booking_series_run',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('booking_series_id', sa.Uuid(), nullable=False),
    sa.Column('booking_series_rule_id', sa.Uuid(), nullable=True),
    sa.Column('kind', sa.Text(), nullable=False),
    sa.Column('status', sa.Text(), server_default=sa.text("'pending'"), nullable=False),
    sa.Column('command', postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), nullable=False),
    sa.Column('requested_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('ok_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('conflict_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('results', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'"), nullable=False),
    sa.Column('requested_by_staff_user_id', sa.Uuid(), nullable=True),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("kind IN ('generate', 'edit', 'cancel', 'preview')", name=op.f('ck_booking_series_run_kind')),
    sa.CheckConstraint("status IN ('pending', 'running', 'completed', 'failed')", name=op.f('ck_booking_series_run_status')),
    sa.ForeignKeyConstraint(['tenant_id', 'booking_series_id'], ['booking_series.tenant_id', 'booking_series.id'], name=op.f('fk_booking_series_run_booking_series_id_booking_series'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id', 'booking_series_rule_id'], ['booking_series_rule.tenant_id', 'booking_series_rule.id'], name=op.f('fk_booking_series_run_booking_series_rule_id_booking_series_rule'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id', 'requested_by_staff_user_id'], ['staff_user.tenant_id', 'staff_user.id'], name=op.f('fk_booking_series_run_requested_by_staff_user_id_staff_user'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_booking_series_run_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_booking_series_run')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_booking_series_run_tenant_id_id'))
    )
    op.create_index(op.f('ix_booking_series_run_booking_series_id'), 'booking_series_run', ['tenant_id', 'booking_series_id'], unique=False)
    op.create_index(op.f('ix_booking_series_run_booking_series_rule_id'), 'booking_series_run', ['tenant_id', 'booking_series_rule_id'], unique=False)
    op.create_index(op.f('ix_booking_series_run_requested_by_staff_user_id'), 'booking_series_run', ['tenant_id', 'requested_by_staff_user_id'], unique=False)
    op.create_table('booking_resource',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('booking_id', sa.Uuid(), nullable=False),
    sa.Column('resource_id', sa.Uuid(), nullable=False),
    sa.Column('role', sa.Text(), server_default=sa.text("'additional'"), nullable=False),
    sa.Column('sort_order', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("role IN ('primary', 'additional')", name=op.f('ck_booking_resource_role')),
    sa.ForeignKeyConstraint(['tenant_id', 'booking_id'], ['booking.tenant_id', 'booking.id'], name=op.f('fk_booking_resource_booking_id_booking'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id', 'resource_id'], ['resource.tenant_id', 'resource.id'], name=op.f('fk_booking_resource_resource_id_resource'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_booking_resource_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_booking_resource')),
    sa.UniqueConstraint('tenant_id', 'booking_id', 'resource_id', name='uq_booking_resource'),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_booking_resource_tenant_id_id'))
    )
    op.create_index(op.f('ix_booking_resource_resource_id'), 'booking_resource', ['tenant_id', 'resource_id'], unique=False)
    op.create_index('uq_booking_resource_primary', 'booking_resource', ['tenant_id', 'booking_id'], unique=True, postgresql_where=sa.text("role = 'primary'"))
    op.create_table('resource_hold',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('resource_id', sa.Uuid(), nullable=False),
    sa.Column('booking_id', sa.Uuid(), nullable=False),
    sa.Column('during', postgresql.TSTZRANGE(), nullable=False),
    sa.Column('origin', sa.Text(), nullable=False),
    sa.Column('source_resource_id', sa.Uuid(), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    postgresql.ExcludeConstraint((sa.column('tenant_id'), '='), (sa.column('resource_id'), '='), (sa.column('during'), '&&'), using='gist', name='ex_resource_hold_overlap'),
    sa.CheckConstraint("origin IN ('booked', 'linked', 'descendant')", name=op.f('ck_resource_hold_origin')),
    sa.CheckConstraint('NOT isempty(during) AND lower_inc(during) AND NOT upper_inc(during) AND NOT lower_inf(during) AND NOT upper_inf(during)', name=op.f('ck_resource_hold_during')),
    sa.ForeignKeyConstraint(['tenant_id', 'booking_id'], ['booking.tenant_id', 'booking.id'], name=op.f('fk_resource_hold_booking_id_booking'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id', 'resource_id'], ['resource.tenant_id', 'resource.id'], name=op.f('fk_resource_hold_resource_id_resource'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'source_resource_id'], ['resource.tenant_id', 'resource.id'], name=op.f('fk_resource_hold_source_resource_id_resource'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_resource_hold_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_resource_hold')),
    sa.UniqueConstraint('tenant_id', 'booking_id', 'resource_id', name='uq_resource_hold_booking_resource'),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_resource_hold_tenant_id_id'))
    )
    op.create_index('ix_resource_hold_expires_at', 'resource_hold', ['expires_at'], unique=False, postgresql_where=sa.text('expires_at IS NOT NULL'))
    op.create_index(op.f('ix_resource_hold_source_resource_id'), 'resource_hold', ['tenant_id', 'source_resource_id'], unique=False)
    op.create_table('session',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('location_id', sa.Uuid(), nullable=False),
    sa.Column('booking_id', sa.Uuid(), nullable=False),
    sa.Column('capacity', sa.Integer(), nullable=False),
    sa.Column('booked_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('is_self_bookable', sa.Boolean(), nullable=False),
    sa.Column('allows_free_booking', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('direct_link_token', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('booked_count >= 0 AND booked_count <= capacity', name=op.f('ck_session_booked_within_capacity')),
    sa.CheckConstraint('capacity >= 0', name=op.f('ck_session_capacity')),
    sa.ForeignKeyConstraint(['tenant_id', 'booking_id'], ['booking.tenant_id', 'booking.id'], name=op.f('fk_session_booking_id_booking'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id', 'location_id'], ['location.tenant_id', 'location.id'], name=op.f('fk_session_location_id_location'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_session_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_session')),
    sa.UniqueConstraint('tenant_id', 'booking_id', name='uq_session_booking'),
    sa.UniqueConstraint('tenant_id', 'direct_link_token', name='uq_session_direct_link'),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_session_tenant_id_id'))
    )
    op.create_index('ix_session_self_bookable', 'session', ['tenant_id', 'location_id', 'is_self_bookable'], unique=False, postgresql_where=sa.text('is_self_bookable'))
    op.create_table('enrollment',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('location_id', sa.Uuid(), nullable=False),
    sa.Column('client_id', sa.Uuid(), nullable=False),
    sa.Column('target_kind', sa.Text(), server_default=sa.text("'session'"), nullable=False),
    sa.Column('session_id', sa.Uuid(), nullable=True),
    sa.Column('status', sa.Text(), server_default=sa.text("'enrolled'"), nullable=False),
    sa.Column('pricing', sa.Text(), nullable=False),
    sa.Column('channel', sa.Text(), nullable=False),
    sa.Column('enrolled_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('cancelled_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('cancel_kind', sa.Text(), nullable=True),
    sa.Column('cancel_reason', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("(status = 'cancelled') = (cancelled_at IS NOT NULL)", name=op.f('ck_enrollment_cancel')),
    sa.CheckConstraint("cancel_kind IN ('early', 'late', 'staff_removed', 'session_cancelled', 'hold_expired', 'demoted_to_waitlist', 'payment_refunded', 'client_merged')", name=op.f('ck_enrollment_cancel_kind')),
    sa.CheckConstraint("channel IN ('staff', 'portal', 'mobile', 'public_link', 'kiosk', 'api', 'waitlist', 'roster_invite')", name=op.f('ck_enrollment_channel')),
    sa.CheckConstraint("pricing IN ('fee', 'entitlement', 'free')", name=op.f('ck_enrollment_pricing')),
    sa.CheckConstraint("status IN ('pending', 'enrolled', 'cancelled')", name=op.f('ck_enrollment_status')),
    sa.CheckConstraint("target_kind = 'session' AND session_id IS NOT NULL", name=op.f('ck_enrollment_target')),
    sa.ForeignKeyConstraint(['tenant_id', 'client_id'], ['client.tenant_id', 'client.id'], name=op.f('fk_enrollment_client_id_client'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'location_id'], ['location.tenant_id', 'location.id'], name=op.f('fk_enrollment_location_id_location'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'session_id'], ['session.tenant_id', 'session.id'], name=op.f('fk_enrollment_session_id_session'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_enrollment_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_enrollment')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_enrollment_tenant_id_id'))
    )
    op.create_index('ix_enrollment_client', 'enrollment', ['tenant_id', 'client_id', 'status', 'id'], unique=False)
    op.create_index(op.f('ix_enrollment_location_id'), 'enrollment', ['tenant_id', 'location_id'], unique=False)
    op.create_index('ix_enrollment_session_roster', 'enrollment', ['tenant_id', 'session_id', 'status', 'id'], unique=False)
    op.create_index('uq_enrollment_session_client', 'enrollment', ['tenant_id', 'session_id', 'client_id'], unique=True, postgresql_where=sa.text("status IN ('pending', 'enrolled') AND target_kind = 'session'"))
    op.create_table('attendance',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('enrollment_id', sa.Uuid(), nullable=False),
    sa.Column('session_id', sa.Uuid(), nullable=False),
    sa.Column('client_id', sa.Uuid(), nullable=False),
    sa.Column('status', sa.Text(), nullable=False),
    sa.Column('source', sa.Text(), server_default=sa.text("'staff'"), nullable=False),
    sa.Column('marked_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('marked_by_staff_user_id', sa.Uuid(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("source IN ('staff', 'check_in', 'kiosk', 'video_join', 'api')", name=op.f('ck_attendance_source')),
    sa.CheckConstraint("status IN ('attended', 'no_show', 'excused')", name=op.f('ck_attendance_status')),
    sa.ForeignKeyConstraint(['tenant_id', 'client_id'], ['client.tenant_id', 'client.id'], name=op.f('fk_attendance_client_id_client'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'enrollment_id'], ['enrollment.tenant_id', 'enrollment.id'], name=op.f('fk_attendance_enrollment_id_enrollment'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id', 'marked_by_staff_user_id'], ['staff_user.tenant_id', 'staff_user.id'], name=op.f('fk_attendance_marked_by_staff_user_id_staff_user'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'session_id'], ['session.tenant_id', 'session.id'], name=op.f('fk_attendance_session_id_session'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_attendance_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_attendance')),
    sa.UniqueConstraint('tenant_id', 'enrollment_id', 'session_id', name='uq_attendance_enrollment_session'),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_attendance_tenant_id_id'))
    )
    op.create_index('ix_attendance_client', 'attendance', ['tenant_id', 'client_id', 'marked_at'], unique=False)
    op.create_index(op.f('ix_attendance_marked_by_staff_user_id'), 'attendance', ['tenant_id', 'marked_by_staff_user_id'], unique=False)
    op.create_index('ix_attendance_session', 'attendance', ['tenant_id', 'session_id', 'status'], unique=False)
    op.create_table('waitlist_entry',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('location_id', sa.Uuid(), nullable=False),
    sa.Column('client_id', sa.Uuid(), nullable=False),
    sa.Column('target_kind', sa.Text(), server_default=sa.text("'session'"), nullable=False),
    sa.Column('session_id', sa.Uuid(), nullable=True),
    sa.Column('status', sa.Text(), server_default=sa.text("'waiting'"), nullable=False),
    sa.Column('mode', sa.Text(), nullable=False),
    sa.Column('queued_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('channel', sa.Text(), nullable=False),
    sa.Column('promoted_enrollment_id', sa.Uuid(), nullable=True),
    sa.Column('removed_reason', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("channel IN ('staff', 'portal', 'mobile', 'public_link', 'kiosk', 'api', 'waitlist', 'roster_invite')", name=op.f('ck_waitlist_entry_channel')),
    sa.CheckConstraint("mode IN ('manual', 'auto_promote', 'open_offer')", name=op.f('ck_waitlist_entry_mode')),
    sa.CheckConstraint("status IN ('waiting', 'offered', 'promoted', 'expired', 'removed')", name=op.f('ck_waitlist_entry_status')),
    sa.CheckConstraint("target_kind = 'session' AND session_id IS NOT NULL", name=op.f('ck_waitlist_entry_target')),
    sa.ForeignKeyConstraint(['tenant_id', 'client_id'], ['client.tenant_id', 'client.id'], name=op.f('fk_waitlist_entry_client_id_client'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'location_id'], ['location.tenant_id', 'location.id'], name=op.f('fk_waitlist_entry_location_id_location'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'promoted_enrollment_id'], ['enrollment.tenant_id', 'enrollment.id'], name=op.f('fk_waitlist_entry_promoted_enrollment_id_enrollment'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'session_id'], ['session.tenant_id', 'session.id'], name=op.f('fk_waitlist_entry_session_id_session'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_waitlist_entry_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_waitlist_entry')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_waitlist_entry_tenant_id_id'))
    )
    op.create_index(op.f('ix_waitlist_entry_client_id'), 'waitlist_entry', ['tenant_id', 'client_id'], unique=False)
    op.create_index(op.f('ix_waitlist_entry_location_id'), 'waitlist_entry', ['tenant_id', 'location_id'], unique=False)
    op.create_index(op.f('ix_waitlist_entry_promoted_enrollment_id'), 'waitlist_entry', ['tenant_id', 'promoted_enrollment_id'], unique=False)
    op.create_index('ix_waitlist_entry_session_queue', 'waitlist_entry', ['tenant_id', 'session_id', 'status', 'queued_at', 'id'], unique=False)
    op.create_index('uq_waitlist_entry_session_client', 'waitlist_entry', ['tenant_id', 'session_id', 'client_id'], unique=True, postgresql_where=sa.text("status IN ('waiting', 'offered')"))
    op.create_foreign_key(op.f('fk_staff_user_linked_resource_id_resource'), 'staff_user', 'resource', ['tenant_id', 'linked_resource_id'], ['tenant_id', 'id'], ondelete='RESTRICT')
    for table in TENANT_TABLES:
        enable_rls(table)


def downgrade() -> None:
    op.drop_constraint(op.f('fk_staff_user_linked_resource_id_resource'), 'staff_user', type_='foreignkey')
    op.drop_index('uq_waitlist_entry_session_client', table_name='waitlist_entry', postgresql_where=sa.text("status IN ('waiting', 'offered')"))
    op.drop_index('ix_waitlist_entry_session_queue', table_name='waitlist_entry')
    op.drop_index(op.f('ix_waitlist_entry_promoted_enrollment_id'), table_name='waitlist_entry')
    op.drop_index(op.f('ix_waitlist_entry_location_id'), table_name='waitlist_entry')
    op.drop_index(op.f('ix_waitlist_entry_client_id'), table_name='waitlist_entry')
    op.drop_table('waitlist_entry')
    op.drop_index('ix_attendance_session', table_name='attendance')
    op.drop_index(op.f('ix_attendance_marked_by_staff_user_id'), table_name='attendance')
    op.drop_index('ix_attendance_client', table_name='attendance')
    op.drop_table('attendance')
    op.drop_index('uq_enrollment_session_client', table_name='enrollment', postgresql_where=sa.text("status IN ('pending', 'enrolled') AND target_kind = 'session'"))
    op.drop_index('ix_enrollment_session_roster', table_name='enrollment')
    op.drop_index(op.f('ix_enrollment_location_id'), table_name='enrollment')
    op.drop_index('ix_enrollment_client', table_name='enrollment')
    op.drop_table('enrollment')
    op.drop_index('ix_session_self_bookable', table_name='session', postgresql_where=sa.text('is_self_bookable'))
    op.drop_table('session')
    op.drop_index(op.f('ix_resource_hold_source_resource_id'), table_name='resource_hold')
    op.drop_index('ix_resource_hold_expires_at', table_name='resource_hold', postgresql_where=sa.text('expires_at IS NOT NULL'))
    op.drop_table('resource_hold')
    op.drop_index('uq_booking_resource_primary', table_name='booking_resource', postgresql_where=sa.text("role = 'primary'"))
    op.drop_index(op.f('ix_booking_resource_resource_id'), table_name='booking_resource')
    op.drop_table('booking_resource')
    op.drop_index(op.f('ix_booking_series_run_requested_by_staff_user_id'), table_name='booking_series_run')
    op.drop_index(op.f('ix_booking_series_run_booking_series_rule_id'), table_name='booking_series_run')
    op.drop_index(op.f('ix_booking_series_run_booking_series_id'), table_name='booking_series_run')
    op.drop_table('booking_series_run')
    op.drop_index('uq_booking_series_rule_occurrence', table_name='booking', postgresql_where=sa.text('booking_series_rule_id IS NOT NULL'))
    op.drop_index('ix_booking_type', table_name='booking', postgresql_where=sa.text('reservation_type_id IS NOT NULL'))
    op.drop_index('ix_booking_span', table_name='booking', postgresql_using='gist', postgresql_where=sa.text("status <> 'cancelled'"))
    op.drop_index('ix_booking_source', table_name='booking', postgresql_where=sa.text('source_id IS NOT NULL'))
    op.drop_index('ix_booking_series', table_name='booking', postgresql_where=sa.text('booking_series_id IS NOT NULL'))
    op.drop_index('ix_booking_location_day', table_name='booking')
    op.drop_index('ix_booking_expiring', table_name='booking', postgresql_where=sa.text("status = 'tentative'"))
    op.drop_index(op.f('ix_booking_created_by_staff_user_id'), table_name='booking')
    op.drop_index('ix_booking_client', table_name='booking', postgresql_where=sa.text('client_id IS NOT NULL'))
    op.drop_table('booking')
    op.drop_table('booking_series_rule')
    op.drop_index(op.f('ix_booking_series_location_id'), table_name='booking_series')
    op.drop_index(op.f('ix_booking_series_created_by_staff_user_id'), table_name='booking_series')
    op.drop_table('booking_series')
    op.drop_index(op.f('ix_resource_link_to_resource_id'), table_name='resource_link')
    op.drop_table('resource_link')
    op.drop_index('ix_availability_window_resource', table_name='availability_window')
    op.drop_index(op.f('ix_availability_window_location_id'), table_name='availability_window')
    op.drop_table('availability_window')
    op.drop_index('uq_resource_name', table_name='resource', postgresql_where=sa.text("status = 'active'"), postgresql_nulls_not_distinct=True)
    op.drop_index(op.f('ix_resource_parent_id'), table_name='resource')
    op.drop_index(op.f('ix_resource_location_id'), table_name='resource')
    op.drop_index('ix_resource_group_order', table_name='resource')
    op.drop_table('resource')
    op.drop_index('uq_reservation_type_name', table_name='reservation_type', postgresql_where=sa.text('is_active'))
    op.drop_index(op.f('ix_reservation_type_revenue_category_id'), table_name='reservation_type')
    op.drop_index(op.f('ix_reservation_type_reservation_category_id'), table_name='reservation_type')
    op.drop_index('ix_reservation_type_order', table_name='reservation_type')
    op.drop_table('reservation_type')
    op.drop_index('uq_scheduling_settings', table_name='scheduling_settings', postgresql_nulls_not_distinct=True)
    op.drop_table('scheduling_settings')
    op.drop_index('uq_resource_group_name', table_name='resource_group', postgresql_where=sa.text('is_active'))
    op.drop_index(op.f('ix_resource_group_location_id'), table_name='resource_group')
    op.drop_table('resource_group')
    op.drop_index('uq_reservation_category_name', table_name='reservation_category', postgresql_where=sa.text('is_active'), postgresql_nulls_not_distinct=True)
    op.drop_index(op.f('ix_reservation_category_parent_id'), table_name='reservation_category')
    op.drop_index(op.f('ix_reservation_category_location_id'), table_name='reservation_category')
    op.drop_table('reservation_category')
    op.drop_index('ix_blackout_span', table_name='blackout', postgresql_using='gist')
    op.drop_table('blackout')
