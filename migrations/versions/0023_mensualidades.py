"""Mensualidades: servicios contratados por cada cliente y su factura mensual

Revision ID: 0023
Revises: 0022
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ajustes_ventas", sa.Column("precio_contabilidad_mensual", sa.Numeric(18, 2)))
    op.add_column("ajustes_ventas", sa.Column("precio_contador_mensual", sa.Numeric(18, 2)))
    op.add_column("ajustes_ventas", sa.Column("dias_para_pagar", sa.Integer(), nullable=False, server_default="10"))
    op.create_table(
        "contrataciones",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("cliente", sa.String(40), nullable=False),        # e:<emisor_id> o u:<usuario_id>
        sa.Column("emisor_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("emisores.id", ondelete="CASCADE")),
        sa.Column("usuario_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("usuarios.id", ondelete="CASCADE")),
        sa.Column("servicio", sa.String(20), nullable=False),
        sa.Column("precio", sa.Numeric(18, 2), nullable=False),
        sa.Column("moneda", sa.String(3), nullable=False, server_default="CRC"),
        sa.Column("desde", sa.Date(), nullable=False),
        sa.Column("hasta", sa.Date()),
        sa.Column("gratis_hasta", sa.Date()),
        sa.Column("creado_por", sa.String(200)),
        sa.Column("created_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_contrataciones_cliente", "contrataciones", ["cliente", "servicio"])
    op.create_table(
        "cobros_mensuales",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("cliente", sa.String(40), nullable=False),
        sa.Column("emisor_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("emisores.id", ondelete="CASCADE")),
        sa.Column("usuario_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("usuarios.id", ondelete="CASCADE")),
        sa.Column("periodo", sa.Date(), nullable=False),
        sa.Column("lineas", postgresql.JSONB(), nullable=False),
        sa.Column("total", sa.Numeric(18, 2), nullable=False),
        sa.Column("moneda", sa.String(3), nullable=False, server_default="CRC"),
        sa.Column("emitido", sa.Date(), nullable=False),
        sa.Column("vence", sa.Date(), nullable=False),
        sa.Column("estado", sa.String(10), nullable=False, server_default="PENDIENTE"),
        sa.Column("referencia_pago", sa.String(100)),
        sa.Column("reportado_en", sa.DateTime(timezone=True)),
        sa.Column("pagado_en", sa.DateTime(timezone=True)),
        sa.Column("confirmado_por", sa.String(200)),
        sa.Column("factura_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("facturas.id", ondelete="SET NULL")),
        sa.Column("comprobante_error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("cliente", "periodo", name="uq_cobro_cliente_periodo"),
    )
    op.create_index("ix_cobros_mensuales_estado", "cobros_mensuales", ["estado"])


def downgrade() -> None:
    op.drop_table("cobros_mensuales")
    op.drop_table("contrataciones")
    for c in ("dias_para_pagar", "precio_contador_mensual", "precio_contabilidad_mensual"):
        op.drop_column("ajustes_ventas", c)
