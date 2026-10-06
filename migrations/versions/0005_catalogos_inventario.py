"""facturación en línea: clientes, productos, inventario y logo

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-04 15:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('emisores', sa.Column('facturacion_web', sa.Boolean(), nullable=False, server_default='true'))
    op.add_column('emisores', sa.Column('logo', sa.LargeBinary(), nullable=True))
    op.add_column('emisores', sa.Column('logo_tipo', sa.String(length=20), nullable=True))

    op.create_table('clientes',
    sa.Column('id', sa.UUID(as_uuid=False), nullable=False),
    sa.Column('emisor_id', sa.UUID(as_uuid=False), nullable=False),
    sa.Column('tipo_identificacion', sa.String(length=2), nullable=False),
    sa.Column('numero_identificacion', sa.String(length=20), nullable=False),
    sa.Column('nombre', sa.String(length=100), nullable=False),
    sa.Column('nombre_comercial', sa.String(length=80), nullable=True),
    sa.Column('correo', sa.String(length=160), nullable=True),
    sa.Column('telefono', sa.String(length=20), nullable=True),
    sa.Column('codigo_actividad', sa.String(length=6), nullable=True),
    sa.Column('provincia', sa.String(length=1), nullable=True),
    sa.Column('canton', sa.String(length=2), nullable=True),
    sa.Column('distrito', sa.String(length=2), nullable=True),
    sa.Column('otras_senas', sa.String(length=250), nullable=True),
    sa.Column('notas', sa.Text(), nullable=True),
    sa.Column('activo', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['emisor_id'], ['emisores.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('emisor_id', 'numero_identificacion', name='uq_cliente_emisor_identificacion')
    )
    op.create_index(op.f('ix_clientes_emisor_id'), 'clientes', ['emisor_id'], unique=False)

    op.create_table('productos',
    sa.Column('id', sa.UUID(as_uuid=False), nullable=False),
    sa.Column('emisor_id', sa.UUID(as_uuid=False), nullable=False),
    sa.Column('codigo', sa.String(length=20), nullable=False),
    sa.Column('codigo_cabys', sa.String(length=13), nullable=False),
    sa.Column('descripcion', sa.String(length=200), nullable=False),
    sa.Column('unidad_medida', sa.String(length=15), nullable=False),
    sa.Column('es_servicio', sa.Boolean(), nullable=False),
    sa.Column('precio_unitario', sa.Numeric(precision=18, scale=5), nullable=False),
    sa.Column('codigo_tarifa_iva', sa.String(length=2), nullable=False),
    sa.Column('costo_unitario', sa.Numeric(precision=18, scale=5), nullable=True),
    sa.Column('controla_inventario', sa.Boolean(), nullable=False),
    sa.Column('existencia', sa.Numeric(precision=18, scale=3), nullable=False),
    sa.Column('existencia_minima', sa.Numeric(precision=18, scale=3), nullable=True),
    sa.Column('activo', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['emisor_id'], ['emisores.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('emisor_id', 'codigo', name='uq_producto_emisor_codigo')
    )
    op.create_index(op.f('ix_productos_emisor_id'), 'productos', ['emisor_id'], unique=False)

    op.create_table('movimientos_inventario',
    sa.Column('id', sa.UUID(as_uuid=False), nullable=False),
    sa.Column('emisor_id', sa.UUID(as_uuid=False), nullable=False),
    sa.Column('producto_id', sa.UUID(as_uuid=False), nullable=False),
    sa.Column('fecha', sa.DateTime(timezone=True), nullable=True),
    sa.Column('tipo', sa.String(length=12), nullable=False),
    sa.Column('cantidad', sa.Numeric(precision=18, scale=3), nullable=False),
    sa.Column('existencia_resultante', sa.Numeric(precision=18, scale=3), nullable=False),
    sa.Column('costo_unitario', sa.Numeric(precision=18, scale=5), nullable=True),
    sa.Column('factura_id', sa.UUID(as_uuid=False), nullable=True),
    sa.Column('nota', sa.String(length=300), nullable=True),
    sa.Column('usuario', sa.String(length=200), nullable=True),
    sa.ForeignKeyConstraint(['emisor_id'], ['emisores.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['factura_id'], ['facturas.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['producto_id'], ['productos.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_movimientos_inventario_emisor_id'), 'movimientos_inventario', ['emisor_id'], unique=False)
    op.create_index(op.f('ix_movimientos_inventario_producto_id'), 'movimientos_inventario', ['producto_id'], unique=False)
    op.create_index(op.f('ix_movimientos_inventario_fecha'), 'movimientos_inventario', ['fecha'], unique=False)
    op.create_index(op.f('ix_movimientos_inventario_factura_id'), 'movimientos_inventario', ['factura_id'], unique=False)


def downgrade():
    op.drop_table('movimientos_inventario')
    op.drop_table('productos')
    op.drop_table('clientes')
    op.drop_column('emisores', 'logo_tipo')
    op.drop_column('emisores', 'logo')
    op.drop_column('emisores', 'facturacion_web')
