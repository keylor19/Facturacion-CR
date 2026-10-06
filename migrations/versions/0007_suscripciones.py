"""alquiler de servicios por período (suscripciones)

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-04 18:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = '0007'
down_revision = '0006'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('suscripciones',
    sa.Column('id', sa.UUID(as_uuid=False), nullable=False),
    sa.Column('emisor_id', sa.UUID(as_uuid=False), nullable=False),
    sa.Column('servicio', sa.String(length=20), nullable=False),
    sa.Column('desde', sa.DateTime(timezone=True), nullable=False),
    sa.Column('hasta', sa.DateTime(timezone=True), nullable=False),
    sa.Column('meses', sa.Integer(), nullable=False),
    sa.Column('precio', sa.Numeric(precision=18, scale=2), nullable=False),
    sa.Column('moneda', sa.String(length=3), nullable=False),
    sa.Column('referencia_pago', sa.String(length=100), nullable=True),
    sa.Column('notas', sa.Text(), nullable=True),
    sa.Column('anulada', sa.Boolean(), nullable=False),
    sa.Column('creado_por', sa.String(length=200), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['emisor_id'], ['emisores.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_suscripciones_emisor_id'), 'suscripciones', ['emisor_id'], unique=False)
    op.create_index(op.f('ix_suscripciones_hasta'), 'suscripciones', ['hasta'], unique=False)
    op.create_index(op.f('ix_suscripciones_created_at'), 'suscripciones', ['created_at'], unique=False)


def downgrade():
    op.drop_table('suscripciones')
