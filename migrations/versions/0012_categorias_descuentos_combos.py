"""categorías de productos, descuentos automáticos y combos

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-27 15:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = '0012'
down_revision = '0011'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('categorias',
    sa.Column('id', postgresql.UUID(as_uuid=False), nullable=False),
    sa.Column('emisor_id', postgresql.UUID(as_uuid=False), nullable=False),
    sa.Column('nombre', sa.String(length=60), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['emisor_id'], ['emisores.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('emisor_id', 'nombre', name='uq_categoria_emisor_nombre')
    )
    op.create_index(op.f('ix_categorias_emisor_id'), 'categorias', ['emisor_id'], unique=False)

    op.add_column('productos', sa.Column('categoria_id', postgresql.UUID(as_uuid=False), nullable=True))
    op.add_column('productos', sa.Column('es_combo', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.alter_column('productos', 'es_combo', server_default=None)
    op.create_foreign_key('fk_productos_categoria_id', 'productos', 'categorias', ['categoria_id'], ['id'], ondelete='SET NULL')
    op.create_index(op.f('ix_productos_categoria_id'), 'productos', ['categoria_id'], unique=False)

    op.create_table('combo_componentes',
    sa.Column('id', postgresql.UUID(as_uuid=False), nullable=False),
    sa.Column('combo_id', postgresql.UUID(as_uuid=False), nullable=False),
    sa.Column('producto_id', postgresql.UUID(as_uuid=False), nullable=False),
    sa.Column('cantidad', sa.Numeric(precision=18, scale=3), nullable=False),
    sa.ForeignKeyConstraint(['combo_id'], ['productos.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['producto_id'], ['productos.id']),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_combo_componentes_combo_id'), 'combo_componentes', ['combo_id'], unique=False)

    op.create_table('descuentos',
    sa.Column('id', postgresql.UUID(as_uuid=False), nullable=False),
    sa.Column('emisor_id', postgresql.UUID(as_uuid=False), nullable=False),
    sa.Column('nombre', sa.String(length=100), nullable=False),
    sa.Column('tipo', sa.String(length=10), nullable=False),
    sa.Column('valor', sa.Numeric(precision=18, scale=5), nullable=False),
    sa.Column('alcance', sa.String(length=10), nullable=False),
    sa.Column('categoria_id', postgresql.UUID(as_uuid=False), nullable=True),
    sa.Column('producto_id', postgresql.UUID(as_uuid=False), nullable=True),
    sa.Column('cantidad_minima', sa.Numeric(precision=18, scale=3), nullable=True),
    sa.Column('codigo_descuento', sa.String(length=2), nullable=False),
    sa.Column('desde', sa.Date(), nullable=True),
    sa.Column('hasta', sa.Date(), nullable=True),
    sa.Column('activo', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['emisor_id'], ['emisores.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['categoria_id'], ['categorias.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['producto_id'], ['productos.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_descuentos_emisor_id'), 'descuentos', ['emisor_id'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_descuentos_emisor_id'), table_name='descuentos')
    op.drop_table('descuentos')
    op.drop_index(op.f('ix_combo_componentes_combo_id'), table_name='combo_componentes')
    op.drop_table('combo_componentes')
    op.drop_index(op.f('ix_productos_categoria_id'), table_name='productos')
    op.drop_constraint('fk_productos_categoria_id', 'productos', type_='foreignkey')
    op.drop_column('productos', 'es_combo')
    op.drop_column('productos', 'categoria_id')
    op.drop_index(op.f('ix_categorias_emisor_id'), table_name='categorias')
    op.drop_table('categorias')
