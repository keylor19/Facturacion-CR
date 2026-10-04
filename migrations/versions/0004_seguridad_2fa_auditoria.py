"""seguridad: verificación en dos pasos y bitácora de auditoría

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-04 10:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('usuarios', sa.Column('totp_secreto_cifrado', sa.LargeBinary(), nullable=True))
    op.add_column('usuarios', sa.Column('totp_activo', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('usuarios', sa.Column('totp_ultimo_paso', sa.BigInteger(), nullable=True))

    op.create_table('auditoria',
    sa.Column('id', sa.UUID(as_uuid=False), nullable=False),
    sa.Column('fecha', sa.DateTime(timezone=True), nullable=True),
    sa.Column('actor', sa.String(length=200), nullable=False),
    sa.Column('accion', sa.String(length=60), nullable=False),
    sa.Column('emisor_id', sa.UUID(as_uuid=False), nullable=True),
    sa.Column('detalle', sa.Text(), nullable=True),
    sa.Column('ip', sa.String(length=64), nullable=True),
    sa.ForeignKeyConstraint(['emisor_id'], ['emisores.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_auditoria_fecha'), 'auditoria', ['fecha'], unique=False)
    op.create_index(op.f('ix_auditoria_accion'), 'auditoria', ['accion'], unique=False)
    op.create_index(op.f('ix_auditoria_emisor_id'), 'auditoria', ['emisor_id'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_auditoria_emisor_id'), table_name='auditoria')
    op.drop_index(op.f('ix_auditoria_accion'), table_name='auditoria')
    op.drop_index(op.f('ix_auditoria_fecha'), table_name='auditoria')
    op.drop_table('auditoria')
    op.drop_column('usuarios', 'totp_ultimo_paso')
    op.drop_column('usuarios', 'totp_activo')
    op.drop_column('usuarios', 'totp_secreto_cifrado')
