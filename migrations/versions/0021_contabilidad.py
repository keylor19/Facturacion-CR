"""Módulo de contabilidad para contadores: catálogo de cuentas, asientos y empresas que solo llevan contabilidad

Revision ID: 0021
Revises: 0020
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("usuarios", sa.Column("es_contador", sa.Boolean(), nullable=False, server_default="false"))
    op.add_column("emisores", sa.Column("solo_contabilidad", sa.Boolean(), nullable=False, server_default="false"))
    op.add_column("emisores", sa.Column("contador_id", postgresql.UUID(as_uuid=False),
                                        sa.ForeignKey("usuarios.id", ondelete="SET NULL", name="fk_emisores_contador")))
    op.add_column("facturas", sa.Column("importada", sa.Boolean(), nullable=False, server_default="false"))

    op.create_table(
        "cuentas_contables",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("emisor_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("emisores.id", ondelete="CASCADE"), nullable=False),
        sa.Column("codigo", sa.String(30), nullable=False),
        sa.Column("nombre", sa.String(150), nullable=False),
        sa.Column("tipo", sa.String(10), nullable=False),
        sa.Column("acepta_movimientos", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("clave_sistema", sa.String(30)),
        sa.Column("activa", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("emisor_id", "codigo", name="uq_cuenta_emisor_codigo"),
    )
    op.create_index("ix_cuentas_contables_emisor_id", "cuentas_contables", ["emisor_id"])

    op.create_table(
        "asientos",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("emisor_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("emisores.id", ondelete="CASCADE"), nullable=False),
        sa.Column("numero", sa.Integer(), nullable=False),
        sa.Column("fecha", sa.Date(), nullable=False),
        sa.Column("descripcion", sa.String(300), nullable=False),
        sa.Column("origen", sa.String(15), nullable=False, server_default="manual"),
        sa.Column("documento_ref", sa.String(80)),
        sa.Column("editado", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("anulado", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("creado_por", sa.String(200)),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("emisor_id", "numero", name="uq_asiento_numero"),
    )
    op.create_index("ix_asientos_emisor_fecha", "asientos", ["emisor_id", "fecha"])
    op.create_index("uq_asiento_documento", "asientos", ["emisor_id", "documento_ref"], unique=True,
                    postgresql_where=sa.text("documento_ref IS NOT NULL"))

    op.create_table(
        "asiento_lineas",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("asiento_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("asientos.id", ondelete="CASCADE"), nullable=False),
        sa.Column("cuenta_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("cuentas_contables.id"), nullable=False),
        sa.Column("debe", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("haber", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("detalle", sa.String(200)),
    )
    op.create_index("ix_asiento_lineas_asiento_id", "asiento_lineas", ["asiento_id"])
    op.create_index("ix_asiento_lineas_cuenta_id", "asiento_lineas", ["cuenta_id"])

    op.create_table(
        "periodos_cerrados",
        sa.Column("emisor_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("emisores.id", ondelete="CASCADE"), nullable=False),
        sa.Column("mes", sa.Date(), nullable=False),
        sa.Column("cerrado_por", sa.String(200)),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.PrimaryKeyConstraint("emisor_id", "mes"),
    )


def downgrade() -> None:
    op.drop_table("periodos_cerrados")
    op.drop_table("asiento_lineas")
    op.drop_table("asientos")
    op.drop_table("cuentas_contables")
    op.drop_column("facturas", "importada")
    op.drop_column("emisores", "contador_id")
    op.drop_column("emisores", "solo_contabilidad")
    op.drop_column("usuarios", "es_contador")
