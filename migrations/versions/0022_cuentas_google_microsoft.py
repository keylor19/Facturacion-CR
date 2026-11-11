"""Cuentas propias con Google o Microsoft e inscripción en dos pasos (cuenta y luego empresa)

Revision ID: 0022
Revises: 0021
"""
import sqlalchemy as sa
from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("usuarios", sa.Column("oauth_proveedor", sa.String(20)))
    op.add_column("usuarios", sa.Column("oauth_sub", sa.String(255)))
    op.create_index("uq_usuario_oauth", "usuarios", ["oauth_proveedor", "oauth_sub"], unique=True,
                    postgresql_where=sa.text("oauth_sub IS NOT NULL"))
    # La cuenta se crea primero; la empresa se inscribe después (o nunca, si es un contador)
    op.alter_column("registros", "emisor_id", nullable=True)
    # El servicio funciona por autoservicio: la inscripción en línea queda abierta
    op.alter_column("ajustes_ventas", "autoregistro", server_default="true")
    op.execute("UPDATE ajustes_ventas SET autoregistro = true")


def downgrade() -> None:
    op.alter_column("ajustes_ventas", "autoregistro", server_default="false")
    op.alter_column("registros", "emisor_id", nullable=False)
    op.drop_index("uq_usuario_oauth", table_name="usuarios")
    op.drop_column("usuarios", "oauth_sub")
    op.drop_column("usuarios", "oauth_proveedor")
