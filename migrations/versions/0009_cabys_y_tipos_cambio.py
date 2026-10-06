"""catálogo CABYS local y tipo de cambio diario

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-06 20:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = '0009'
down_revision = '0008'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('cabys',
    sa.Column('codigo', sa.String(length=13), nullable=False),
    sa.Column('descripcion', sa.Text(), nullable=False),
    sa.Column('impuesto', sa.Numeric(precision=5, scale=2), nullable=False),
    sa.Column('categorias', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('busqueda', sa.Text(), nullable=False),
    sa.Column('busqueda_categorias', sa.Text(), nullable=False),
    sa.Column('actualizado_en', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('codigo')
    )
    op.create_table('tipos_cambio',
    sa.Column('fecha', sa.Date(), nullable=False),
    sa.Column('usd_compra', sa.Numeric(precision=12, scale=4), nullable=True),
    sa.Column('usd_venta', sa.Numeric(precision=12, scale=4), nullable=True),
    sa.Column('eur_colones', sa.Numeric(precision=12, scale=4), nullable=True),
    sa.Column('eur_dolares', sa.Numeric(precision=12, scale=6), nullable=True),
    sa.Column('actualizado_en', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('fecha')
    )


def downgrade():
    op.drop_table('tipos_cambio')
    op.drop_table('cabys')
