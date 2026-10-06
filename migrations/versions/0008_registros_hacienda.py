"""datos públicos de Hacienda guardados localmente

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-06 18:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = '0008'
down_revision = '0007'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('registros_hacienda',
    sa.Column('id', sa.UUID(as_uuid=False), nullable=False),
    sa.Column('tipo', sa.String(length=20), nullable=False),
    sa.Column('clave', sa.String(length=60), nullable=False),
    sa.Column('ruta', sa.String(length=80), nullable=False),
    sa.Column('parametros', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('encontrado', sa.Boolean(), nullable=False),
    sa.Column('datos', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('actualizado_en', sa.DateTime(timezone=True), nullable=False),
    sa.Column('usado_en', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tipo', 'clave', name='uq_registro_hacienda')
    )
    op.create_index(op.f('ix_registros_hacienda_actualizado_en'), 'registros_hacienda', ['actualizado_en'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_registros_hacienda_actualizado_en'), table_name='registros_hacienda')
    op.drop_table('registros_hacienda')
