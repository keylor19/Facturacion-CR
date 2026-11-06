"""comprobante electrónico por cada venta de paquetes y mensualidades

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-27 13:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = '0014'
down_revision = '0013'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('ajustes_ventas',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('emisor_ventas_id', postgresql.UUID(as_uuid=False), nullable=True),
    sa.Column('codigo_cabys', sa.String(length=13), nullable=True),
    sa.Column('codigo_tarifa_iva', sa.String(length=2), nullable=False),
    sa.Column('precio_incluye_iva', sa.Boolean(), nullable=False),
    sa.Column('tipo_comprobante', sa.String(length=2), nullable=False),
    sa.Column('medio_pago', sa.String(length=2), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['emisor_ventas_id'], ['emisores.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    for tabla in ('paquetes', 'suscripciones'):
        op.add_column(tabla, sa.Column('factura_id', postgresql.UUID(as_uuid=False), nullable=True))
        op.add_column(tabla, sa.Column('comprobante_error', sa.Text(), nullable=True))
        op.create_foreign_key(f'fk_{tabla}_factura_id', tabla, 'facturas', ['factura_id'], ['id'], ondelete='SET NULL')


def downgrade():
    for tabla in ('paquetes', 'suscripciones'):
        op.drop_constraint(f'fk_{tabla}_factura_id', tabla, type_='foreignkey')
        op.drop_column(tabla, 'comprobante_error')
        op.drop_column(tabla, 'factura_id')
    op.drop_table('ajustes_ventas')
