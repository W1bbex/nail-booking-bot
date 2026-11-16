"""initial_schema

Revision ID: 98ce06d83553
Revises: 
Create Date: 2026-11-15 16:02:53.738968

"""
from typing import Sequence, Union

from alembic import context, op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '98ce06d83553'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _create_full_schema() -> None:
    op.create_table(
        'users',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('telegram_id', sa.BigInteger(), nullable=False),
        sa.Column('full_name', sa.String(length=160), nullable=False),
        sa.Column('phone', sa.String(length=40), nullable=True),
        sa.Column('role', sa.String(length=32), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_users_telegram_id', 'users', ['telegram_id'], unique=True)

    op.create_table(
        'masters',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('full_name', sa.String(length=120), nullable=False),
        sa.Column('specialization', sa.String(length=200), nullable=False),
        sa.Column('experience_years', sa.Integer(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('telegram_username', sa.String(length=80), nullable=True),
        sa.Column('telegram_id', sa.BigInteger(), nullable=True),
        sa.Column('archived_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_masters_telegram_id', 'masters', ['telegram_id'], unique=False)

    op.create_table(
        'services',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('category', sa.String(length=80), nullable=False),
        sa.Column('name', sa.String(length=160), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('duration_minutes', sa.Integer(), nullable=False),
        sa.Column('price', sa.Float(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('archived_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table(
        'bookings',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('client_user_id', sa.Integer(), nullable=False),
        sa.Column('master_id', sa.Integer(), nullable=False),
        sa.Column('service_id', sa.Integer(), nullable=False),
        sa.Column('booking_date', sa.Date(), nullable=False),
        sa.Column('start_time', sa.Time(), nullable=False),
        sa.Column('end_time', sa.Time(), nullable=False),
        sa.Column('price', sa.Float(), nullable=False),
        sa.Column('status', sa.String(length=32), nullable=False),
        sa.Column('is_any_master', sa.Boolean(), nullable=False),
        sa.Column('declined_master_ids', sa.String(length=255), nullable=True),
        sa.Column('assignment_deadline', sa.DateTime(), nullable=True),
        sa.Column('client_reassign_deadline', sa.DateTime(), nullable=True),
        sa.Column('client_name', sa.String(length=160), nullable=False),
        sa.Column('client_phone', sa.String(length=40), nullable=False),
        sa.Column('comment', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('confirmed_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['client_user_id'], ['users.id']),
        sa.ForeignKeyConstraint(['master_id'], ['masters.id']),
        sa.ForeignKeyConstraint(['service_id'], ['services.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_bookings_client_user_id', 'bookings', ['client_user_id'], unique=False)
    op.create_index('ix_bookings_master_id', 'bookings', ['master_id'], unique=False)
    op.create_index('ix_bookings_service_id', 'bookings', ['service_id'], unique=False)
    op.create_index('ix_bookings_booking_date', 'bookings', ['booking_date'], unique=False)
    op.create_index('ix_bookings_start_time', 'bookings', ['start_time'], unique=False)
    op.create_index('ix_bookings_end_time', 'bookings', ['end_time'], unique=False)
    op.create_index('ix_bookings_status', 'bookings', ['status'], unique=False)
    op.create_index(
        'idx_unique_active_master_slot',
        'bookings',
        ['master_id', 'booking_date', 'start_time'],
        unique=True,
        sqlite_where=sa.text("status IN ('pending', 'confirmed', 'awaiting_client_choice')"),
        postgresql_where=sa.text("status IN ('pending', 'confirmed', 'awaiting_client_choice')"),
    )

    op.create_table(
        'blocked_intervals',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('master_id', sa.Integer(), nullable=False),
        sa.Column('booking_date', sa.Date(), nullable=False),
        sa.Column('start_time', sa.Time(), nullable=False),
        sa.Column('end_time', sa.Time(), nullable=False),
        sa.Column('reason', sa.String(length=160), nullable=True),
        sa.ForeignKeyConstraint(['master_id'], ['masters.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_blocked_intervals_master_id', 'blocked_intervals', ['master_id'], unique=False)
    op.create_index('ix_blocked_intervals_booking_date', 'blocked_intervals', ['booking_date'], unique=False)

    op.create_table(
        'booking_messages',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('booking_id', sa.Integer(), nullable=False),
        sa.Column('chat_id', sa.BigInteger(), nullable=False),
        sa.Column('message_id', sa.Integer(), nullable=False),
        sa.Column('kind', sa.String(length=32), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['booking_id'], ['bookings.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_booking_messages_booking_id', 'booking_messages', ['booking_id'], unique=False)
    op.create_index('ix_booking_messages_chat_id', 'booking_messages', ['chat_id'], unique=False)


def _upgrade_legacy_schema(inspector) -> None:
    existing_tables = set(inspector.get_table_names())
    if 'booking_messages' not in existing_tables:
        op.create_table(
            'booking_messages',
            sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
            sa.Column('booking_id', sa.Integer(), nullable=False),
            sa.Column('chat_id', sa.BigInteger(), nullable=False),
            sa.Column('message_id', sa.Integer(), nullable=False),
            sa.Column('kind', sa.String(length=32), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(['booking_id'], ['bookings.id']),
            sa.PrimaryKeyConstraint('id'),
        )
        with op.batch_alter_table('booking_messages', schema=None) as batch_op:
            batch_op.create_index(batch_op.f('ix_booking_messages_booking_id'), ['booking_id'], unique=False)
            batch_op.create_index(batch_op.f('ix_booking_messages_chat_id'), ['chat_id'], unique=False)

    booking_cols = {c['name'] for c in inspector.get_columns('bookings')}
    booking_indexes = {idx['name'] for idx in inspector.get_indexes('bookings')}
    with op.batch_alter_table('bookings', schema=None) as batch_op:
        if 'price' not in booking_cols:
            batch_op.add_column(sa.Column('price', sa.Float(), nullable=False, server_default='0'))
        if 'is_any_master' not in booking_cols:
            batch_op.add_column(sa.Column('is_any_master', sa.Boolean(), nullable=False, server_default=sa.text('0')))
        if 'declined_master_ids' not in booking_cols:
            batch_op.add_column(sa.Column('declined_master_ids', sa.String(length=255), nullable=True))
        if 'assignment_deadline' not in booking_cols:
            batch_op.add_column(sa.Column('assignment_deadline', sa.DateTime(), nullable=True))
        if 'client_reassign_deadline' not in booking_cols:
            batch_op.add_column(sa.Column('client_reassign_deadline', sa.DateTime(), nullable=True))
        if 'idx_unique_active_master_slot' not in booking_indexes:
            batch_op.create_index(
                'idx_unique_active_master_slot',
                ['master_id', 'booking_date', 'start_time'],
                unique=True,
                sqlite_where=sa.text("status IN ('pending', 'confirmed', 'awaiting_client_choice')"),
                postgresql_where=sa.text("status IN ('pending', 'confirmed', 'awaiting_client_choice')"),
            )

    master_cols = {c['name'] for c in inspector.get_columns('masters')}
    master_indexes = {idx['name'] for idx in inspector.get_indexes('masters')}
    with op.batch_alter_table('masters', schema=None) as batch_op:
        if 'telegram_username' not in master_cols:
            batch_op.add_column(sa.Column('telegram_username', sa.String(length=80), nullable=True))
        if 'telegram_id' not in master_cols:
            batch_op.add_column(sa.Column('telegram_id', sa.BigInteger(), nullable=True))
        if 'archived_at' not in master_cols:
            batch_op.add_column(sa.Column('archived_at', sa.DateTime(), nullable=True))
        if batch_op.f('ix_masters_telegram_id') not in master_indexes:
            batch_op.create_index(batch_op.f('ix_masters_telegram_id'), ['telegram_id'], unique=False)

    service_cols = {c['name'] for c in inspector.get_columns('services')}
    with op.batch_alter_table('services', schema=None) as batch_op:
        if 'archived_at' not in service_cols:
            batch_op.add_column(sa.Column('archived_at', sa.DateTime(), nullable=True))

    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.alter_column(
            'telegram_id',
            existing_type=sa.INTEGER(),
            type_=sa.BigInteger(),
            existing_nullable=False,
        )


def upgrade() -> None:
    """Upgrade schema."""
    if context.is_offline_mode():
        _create_full_schema()
        return

    inspector = sa.inspect(op.get_bind())
    if 'users' not in set(inspector.get_table_names()):
        _create_full_schema()
    else:
        _upgrade_legacy_schema(inspector)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_booking_messages_chat_id', table_name='booking_messages')
    op.drop_index('ix_booking_messages_booking_id', table_name='booking_messages')
    op.drop_table('booking_messages')

    op.drop_index('ix_blocked_intervals_booking_date', table_name='blocked_intervals')
    op.drop_index('ix_blocked_intervals_master_id', table_name='blocked_intervals')
    op.drop_table('blocked_intervals')

    op.drop_index('idx_unique_active_master_slot', table_name='bookings')
    op.drop_index('ix_bookings_status', table_name='bookings')
    op.drop_index('ix_bookings_end_time', table_name='bookings')
    op.drop_index('ix_bookings_start_time', table_name='bookings')
    op.drop_index('ix_bookings_booking_date', table_name='bookings')
    op.drop_index('ix_bookings_service_id', table_name='bookings')
    op.drop_index('ix_bookings_master_id', table_name='bookings')
    op.drop_index('ix_bookings_client_user_id', table_name='bookings')
    op.drop_table('bookings')

    op.drop_table('services')

    op.drop_index('ix_masters_telegram_id', table_name='masters')
    op.drop_table('masters')

    op.drop_index('ix_users_telegram_id', table_name='users')
    op.drop_table('users')
