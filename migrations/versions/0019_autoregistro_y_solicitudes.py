"""Inscripción propia con prueba gratis y solicitudes de compra pagadas por SINPE o transferencia

Revision ID: 0019
Revises: 0018
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ajustes_ventas", sa.Column("autoregistro", sa.Boolean(), nullable=False, server_default="false"))
    op.add_column("ajustes_ventas", sa.Column("prueba_documentos", sa.Integer(), nullable=False, server_default="20"))
    op.add_column("ajustes_ventas", sa.Column("prueba_dias", sa.Integer(), nullable=False, server_default="15"))
    op.add_column("ajustes_ventas", sa.Column("precio_web_mensual", sa.Numeric(18, 2)))
    op.add_column("ajustes_ventas", sa.Column("moneda_web", sa.String(3), nullable=False, server_default="CRC"))
    op.create_table(
        "registros",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("emisor_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("emisores.id", ondelete="CASCADE"), nullable=False),
        sa.Column("usuario_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False),
        sa.Column("expira", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confirmado", sa.DateTime(timezone=True)),
        sa.Column("ip", sa.String(45)),
        sa.Column("created_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "solicitudes_compra",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("emisor_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("emisores.id", ondelete="CASCADE"), nullable=False),
        sa.Column("plan_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("planes.id", ondelete="SET NULL")),
        sa.Column("documentos", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("meses_web", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("monto", sa.Numeric(18, 2), nullable=False),
        sa.Column("moneda", sa.String(3), nullable=False, server_default="CRC"),
        sa.Column("medio_pago", sa.String(2), nullable=False, server_default="06"),
        sa.Column("referencia", sa.String(100), nullable=False),
        sa.Column("comprobante", sa.LargeBinary()),
        sa.Column("comprobante_tipo", sa.String(40)),
        sa.Column("estado", sa.String(10), nullable=False, server_default="PENDIENTE"),
        sa.Column("motivo", sa.String(300)),
        sa.Column("solicitada_por", sa.String(200)),
        sa.Column("resuelta_por", sa.String(200)),
        sa.Column("resuelta_en", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_solicitudes_compra_emisor_id", "solicitudes_compra", ["emisor_id"])
    op.create_index("ix_solicitudes_compra_estado", "solicitudes_compra", ["estado"])


def downgrade() -> None:
    op.drop_table("solicitudes_compra")
    op.drop_table("registros")
    for columna in ("moneda_web", "precio_web_mensual", "prueba_dias", "prueba_documentos", "autoregistro"):
        op.drop_column("ajustes_ventas", columna)
