"""Cuentas por cobrar (abonos y recordatorios) y facturación recurrente

Revision ID: 0018
Revises: 0017
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("emisores", sa.Column("recordar_cobros", sa.Boolean(), nullable=False, server_default="false"))
    op.create_table(
        "abonos",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("emisor_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("emisores.id", ondelete="CASCADE"), nullable=False),
        sa.Column("factura_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("facturas.id", ondelete="CASCADE"), nullable=False),
        sa.Column("fecha", sa.Date(), nullable=False),
        sa.Column("monto", sa.Numeric(18, 5), nullable=False),
        sa.Column("medio_pago", sa.String(2), nullable=False, server_default="04"),
        sa.Column("referencia", sa.String(100)),
        sa.Column("nota", sa.String(250)),
        sa.Column("registrado_por", sa.String(200)),
        sa.Column("anulado", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_abonos_emisor_id", "abonos", ["emisor_id"])
    op.create_index("ix_abonos_factura_id", "abonos", ["factura_id"])
    op.create_table(
        "facturas_recurrentes",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("emisor_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("emisores.id", ondelete="CASCADE"), nullable=False),
        sa.Column("nombre", sa.String(120), nullable=False),
        sa.Column("datos", postgresql.JSONB(), nullable=False),
        sa.Column("frecuencia", sa.String(10), nullable=False, server_default="mensual"),
        sa.Column("proxima", sa.Date(), nullable=False),
        sa.Column("hasta", sa.Date()),
        sa.Column("activa", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("emitidas", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("ultima_factura_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("facturas.id", ondelete="SET NULL")),
        sa.Column("ultimo_error", sa.Text()),
        sa.Column("creada_por", sa.String(200)),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_facturas_recurrentes_emisor_id", "facturas_recurrentes", ["emisor_id"])
    op.create_index("ix_facturas_recurrentes_proxima", "facturas_recurrentes", ["proxima"])


def downgrade() -> None:
    op.drop_table("facturas_recurrentes")
    op.drop_table("abonos")
    op.drop_column("emisores", "recordar_cobros")
