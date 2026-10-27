"""punto de venta: cajas, movimientos de efectivo y caja de cada factura

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-27 09:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = '0011'
down_revision = '0010'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('cajas',
    sa.Column('id', postgresql.UUID(as_uuid=False), nullable=False),
    sa.Column('emisor_id', postgresql.UUID(as_uuid=False), nullable=False),
    sa.Column('sucursal', sa.Integer(), nullable=False),
    sa.Column('terminal', sa.Integer(), nullable=False),
    sa.Column('estado', sa.String(length=10), nullable=False),
    sa.Column('monto_apertura', sa.Numeric(precision=18, scale=2), nullable=False),
    sa.Column('abierta_por', sa.String(length=200), nullable=True),
    sa.Column('abierta_en', sa.DateTime(timezone=True), nullable=False),
    sa.Column('monto_contado', sa.Numeric(precision=18, scale=2), nullable=True),
    sa.Column('cerrada_por', sa.String(length=200), nullable=True),
    sa.Column('cerrada_en', sa.DateTime(timezone=True), nullable=True),
    sa.Column('notas', sa.Text(), nullable=True),
    sa.Column('resumen', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.ForeignKeyConstraint(['emisor_id'], ['emisores.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_cajas_emisor_id'), 'cajas', ['emisor_id'], unique=False)
    op.create_index(op.f('ix_cajas_abierta_en'), 'cajas', ['abierta_en'], unique=False)
    op.create_index('uq_caja_abierta', 'cajas', ['emisor_id', 'sucursal', 'terminal'], unique=True,
                    postgresql_where=sa.text("estado = 'ABIERTA'"))
    op.create_table('movimientos_caja',
    sa.Column('id', postgresql.UUID(as_uuid=False), nullable=False),
    sa.Column('caja_id', postgresql.UUID(as_uuid=False), nullable=False),
    sa.Column('tipo', sa.String(length=10), nullable=False),
    sa.Column('monto', sa.Numeric(precision=18, scale=2), nullable=False),
    sa.Column('motivo', sa.String(length=200), nullable=False),
    sa.Column('usuario', sa.String(length=200), nullable=True),
    sa.Column('fecha', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['caja_id'], ['cajas.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_movimientos_caja_caja_id'), 'movimientos_caja', ['caja_id'], unique=False)
    op.add_column('facturas', sa.Column('caja_id', postgresql.UUID(as_uuid=False), nullable=True))
    op.create_foreign_key('fk_facturas_caja_id', 'facturas', 'cajas', ['caja_id'], ['id'])
    op.create_index(op.f('ix_facturas_caja_id'), 'facturas', ['caja_id'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_facturas_caja_id'), table_name='facturas')
    op.drop_constraint('fk_facturas_caja_id', 'facturas', type_='foreignkey')
    op.drop_column('facturas', 'caja_id')
    op.drop_index(op.f('ix_movimientos_caja_caja_id'), table_name='movimientos_caja')
    op.drop_table('movimientos_caja')
    op.drop_index('uq_caja_abierta', table_name='cajas')
    op.drop_index(op.f('ix_cajas_abierta_en'), table_name='cajas')
    op.drop_index(op.f('ix_cajas_emisor_id'), table_name='cajas')
    op.drop_table('cajas')
