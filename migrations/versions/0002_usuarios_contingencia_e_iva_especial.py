"""usuarios, contingencia e iva especial

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-23 15:01:53.907766
"""
from alembic import op
import sqlalchemy as sa


revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade():
    # Las columnas NOT NULL nuevas llevan server_default para no fallar con datos existentes
    op.create_table('usuarios',
    sa.Column('id', sa.UUID(as_uuid=False), nullable=False),
    sa.Column('email', sa.String(length=160), nullable=False),
    sa.Column('nombre', sa.String(length=100), nullable=False),
    sa.Column('password_hash', sa.String(length=300), nullable=False),
    sa.Column('es_admin', sa.Boolean(), nullable=False),
    sa.Column('emisor_id', sa.UUID(as_uuid=False), nullable=True),
    sa.Column('activo', sa.Boolean(), nullable=False),
    sa.Column('intentos_fallidos', sa.Integer(), nullable=False),
    sa.Column('bloqueado_hasta', sa.DateTime(timezone=True), nullable=True),
    sa.Column('ultimo_login', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['emisor_id'], ['emisores.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('email')
    )
    op.create_index(op.f('ix_usuarios_emisor_id'), 'usuarios', ['emisor_id'], unique=False)
    op.create_table('sesiones',
    sa.Column('id', sa.UUID(as_uuid=False), nullable=False),
    sa.Column('usuario_id', sa.UUID(as_uuid=False), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('expira', sa.DateTime(timezone=True), nullable=False),
    sa.Column('ip', sa.String(length=64), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['usuario_id'], ['usuarios.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('token_hash')
    )
    op.create_index(op.f('ix_sesiones_usuario_id'), 'sesiones', ['usuario_id'], unique=False)
    op.add_column('emisores', sa.Column('registro_fiscal_8707', sa.String(length=12), nullable=True))
    op.add_column('facturas', sa.Column('situacion', sa.String(length=1), nullable=False, server_default='1'))
    op.add_column('facturas', sa.Column('total_no_sujeto', sa.Numeric(precision=18, scale=5), nullable=False, server_default='0'))
    op.add_column('facturas', sa.Column('total_iva_devuelto', sa.Numeric(precision=18, scale=5), nullable=False, server_default='0'))
    op.add_column('facturas_detalles', sa.Column('impuesto_asumido', sa.Numeric(precision=18, scale=5), nullable=False, server_default='0'))
    # ### end Alembic commands ###


def downgrade():
    # Las columnas NOT NULL nuevas llevan server_default para no fallar con datos existentes
    op.drop_column('facturas_detalles', 'impuesto_asumido')
    op.drop_column('facturas', 'total_iva_devuelto')
    op.drop_column('facturas', 'total_no_sujeto')
    op.drop_column('facturas', 'situacion')
    op.drop_column('emisores', 'registro_fiscal_8707')
    op.drop_index(op.f('ix_sesiones_usuario_id'), table_name='sesiones')
    op.drop_table('sesiones')
    op.drop_index(op.f('ix_usuarios_emisor_id'), table_name='usuarios')
    op.drop_table('usuarios')
    # ### end Alembic commands ###
