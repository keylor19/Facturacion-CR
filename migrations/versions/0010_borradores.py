"""proformas y documentos preliminares

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-26 18:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = '0010'
down_revision = '0009'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('borradores',
    sa.Column('id', postgresql.UUID(as_uuid=False), nullable=False),
    sa.Column('emisor_id', postgresql.UUID(as_uuid=False), nullable=False),
    sa.Column('clase', sa.String(length=10), nullable=False),
    sa.Column('numero', sa.Integer(), nullable=True),
    sa.Column('tipo_documento', sa.String(length=2), nullable=False),
    sa.Column('receptor_nombre', sa.String(length=200), nullable=True),
    sa.Column('receptor_identificacion', sa.String(length=20), nullable=True),
    sa.Column('receptor_correo', sa.String(length=160), nullable=True),
    sa.Column('moneda', sa.String(length=3), nullable=False),
    sa.Column('monto_impuesto', sa.Numeric(precision=18, scale=5), nullable=True),
    sa.Column('monto_total', sa.Numeric(precision=18, scale=5), nullable=True),
    sa.Column('datos', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('vence', sa.Date(), nullable=True),
    sa.Column('estado', sa.String(length=10), nullable=False),
    sa.Column('factura_id', postgresql.UUID(as_uuid=False), nullable=True),
    sa.Column('creado_por', sa.String(length=200), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['emisor_id'], ['emisores.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['factura_id'], ['facturas.id']),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('emisor_id', 'clase', 'numero', name='uq_borrador_numero')
    )
    op.create_index(op.f('ix_borradores_emisor_id'), 'borradores', ['emisor_id'], unique=False)
    op.create_index(op.f('ix_borradores_created_at'), 'borradores', ['created_at'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_borradores_created_at'), table_name='borradores')
    op.drop_index(op.f('ix_borradores_emisor_id'), table_name='borradores')
    op.drop_table('borradores')
