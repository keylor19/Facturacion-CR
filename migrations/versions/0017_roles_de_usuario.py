"""Rol del usuario de una empresa: dueño, contador o cajero

Revision ID: 0017
Revises: 0016
"""
import sqlalchemy as sa
from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("usuarios", sa.Column("rol", sa.String(20), nullable=False, server_default="dueno"))


def downgrade() -> None:
    op.drop_column("usuarios", "rol")
