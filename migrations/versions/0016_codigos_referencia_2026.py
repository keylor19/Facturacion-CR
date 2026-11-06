"""códigos de referencia de noviembre 2026: referencia y período fiscal de cada comprobante

Revision ID: 0016
Revises: 0015
Create Date: 2026-11-04 12:00:00.000000

Anexos y Estructuras 4.4 (actualización del 22-04-2026, obligatoria desde el
01-11-2026): las notas con código 13 o 14 llevan su efecto contable al mes del
comprobante que modifican. Se guarda el código y la clave de la primera
referencia y el mes (período fiscal) de cada comprobante; los existentes se
calculan desde el JSON original.
"""
from alembic import op
import sqlalchemy as sa


revision = '0016'
down_revision = '0015'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('facturas', sa.Column('codigo_referencia', sa.String(length=2), nullable=True))
    op.add_column('facturas', sa.Column('referencia_clave', sa.String(length=50), nullable=True))
    op.add_column('facturas', sa.Column('periodo_fiscal', sa.Date(), nullable=True))
    op.create_index('ix_facturas_referencia_clave', 'facturas', ['referencia_clave'])
    op.create_index('ix_facturas_periodo_fiscal', 'facturas', ['periodo_fiscal'])

    # Comprobantes con referencias (notas, contingencia, compra...)
    op.execute("""
        UPDATE facturas
           SET codigo_referencia = json_original->'referencias'->0->>'codigo',
               referencia_clave = left(json_original->'referencias'->0->>'numero', 50)
         WHERE tipo_documento <> '10' AND jsonb_typeof(json_original->'referencias') = 'array'
    """)
    # Recibos de pago: se emitían con el código 04 citando la factura de origen
    op.execute("""
        UPDATE facturas SET codigo_referencia = '04', referencia_clave = json_original->>'factura_origen'
         WHERE tipo_documento = '10'
    """)
    op.execute("""
        UPDATE facturas
           SET periodo_fiscal = CASE
               WHEN tipo_documento IN ('02', '03') AND codigo_referencia IN ('13', '14')
                    AND json_original->'referencias'->0->>'fecha_emision' IS NOT NULL
               THEN date_trunc('month', ((json_original->'referencias'->0->>'fecha_emision')::timestamptz)
                                        AT TIME ZONE 'America/Costa_Rica')::date
               ELSE date_trunc('month', fecha_emision AT TIME ZONE 'America/Costa_Rica')::date
           END
    """)


def downgrade():
    op.drop_index('ix_facturas_periodo_fiscal', table_name='facturas')
    op.drop_index('ix_facturas_referencia_clave', table_name='facturas')
    op.drop_column('facturas', 'periodo_fiscal')
    op.drop_column('facturas', 'referencia_clave')
    op.drop_column('facturas', 'codigo_referencia')
