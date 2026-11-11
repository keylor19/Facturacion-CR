"""Usuarios con acceso a varias empresas (el contador que atiende a muchos clientes)

Revision ID: 0020
Revises: 0019
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "usuario_empresas",
        sa.Column("usuario_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False),
        sa.Column("emisor_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("emisores.id", ondelete="CASCADE"), nullable=False),
        sa.Column("rol", sa.String(20), nullable=False, server_default="contador"),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.PrimaryKeyConstraint("usuario_id", "emisor_id"),
    )
    op.create_index("ix_usuario_empresas_emisor_id", "usuario_empresas", ["emisor_id"])


def downgrade() -> None:
    op.drop_table("usuario_empresas")
