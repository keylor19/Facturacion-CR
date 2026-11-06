"""panel web opcional (apagado por defecto) y datos para los avisos comerciales

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-27 16:00:00.000000

Las empresas existentes conservan su valor actual de facturacion_web; solo
las nuevas nacen sin panel web.
"""
from alembic import op
import sqlalchemy as sa


revision = '0015'
down_revision = '0014'
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column('emisores', 'facturacion_web', server_default=sa.false())
    op.add_column('ajustes_ventas', sa.Column('instrucciones_pago', sa.Text(), nullable=True))
    op.add_column('ajustes_ventas', sa.Column('contacto_ventas', sa.String(length=200), nullable=True))
    op.add_column('ajustes_ventas', sa.Column('correo_avisos', sa.String(length=160), nullable=True))


def downgrade():
    op.drop_column('ajustes_ventas', 'correo_avisos')
    op.drop_column('ajustes_ventas', 'contacto_ventas')
    op.drop_column('ajustes_ventas', 'instrucciones_pago')
    op.alter_column('emisores', 'facturacion_web', server_default=sa.true())
