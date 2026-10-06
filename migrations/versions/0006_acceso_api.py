"""módulo de conexión por API activable por empresa

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-04 17:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('emisores', sa.Column('acceso_api', sa.Boolean(), nullable=False, server_default='true'))


def downgrade():
    op.drop_column('emisores', 'acceso_api')
