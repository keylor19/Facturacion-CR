"""recepción automática de facturas de proveedores por correo (IMAP)

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-27 11:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = '0013'
down_revision = '0012'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('buzones_correo',
    sa.Column('id', postgresql.UUID(as_uuid=False), nullable=False),
    sa.Column('emisor_id', postgresql.UUID(as_uuid=False), nullable=False),
    sa.Column('servidor', sa.String(length=200), nullable=False),
    sa.Column('puerto', sa.Integer(), nullable=False),
    sa.Column('usuario', sa.String(length=200), nullable=False),
    sa.Column('password_cifrado', sa.LargeBinary(), nullable=False),
    sa.Column('carpeta', sa.String(length=200), nullable=False),
    sa.Column('activo', sa.Boolean(), nullable=False),
    sa.Column('uid_validity', sa.BigInteger(), nullable=True),
    sa.Column('ultimo_uid', sa.BigInteger(), nullable=True),
    sa.Column('ultima_revision', sa.DateTime(timezone=True), nullable=True),
    sa.Column('ultimo_error', sa.Text(), nullable=True),
    sa.Column('documentos_importados', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['emisor_id'], ['emisores.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('emisor_id')
    )
    op.add_column('documentos_recibidos', sa.Column('origen', sa.String(length=10), nullable=False, server_default='manual'))
    op.alter_column('documentos_recibidos', 'origen', server_default=None)


def downgrade():
    op.drop_column('documentos_recibidos', 'origen')
    op.drop_table('buzones_correo')
