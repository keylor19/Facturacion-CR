"""
Roles de los usuarios de una empresa en el panel web y lo que cada uno puede hacer.

- dueno: todo lo de su empresa, incluidos sus usuarios.
- contador (se muestra como «Administrativo»): facturas, notas y anulaciones, cobros y facturas
  de proveedores. No toca precios, inventario, punto de venta ni la configuración.
- cajero: vende (factura, tiquete, punto de venta) y cobra. No anula ni ve reportes.

- contador_externo: el contador que lleva la contabilidad; es un usuario aparte (es_contador)
  que solo entra a la contabilidad de las empresas que tiene a cargo.

La contabilidad la ven solo el dueño de la empresa y los contadores que la llevan: ni los
demás usuarios de la empresa, ni los administradores del servicio, ni las API keys. Fuera de
eso, administradores y API keys tienen todos los permisos.
"""

ROLES = {"dueno": "Dueño", "contador": "Administrativo", "cajero": "Cajero", "contador_externo": "Contador"}

DESCRIPCION = {
    "emitir": "emitir comprobantes",
    "anular": "anular comprobantes o emitir notas de crédito y débito",
    "cobrar": "registrar pagos de facturas a crédito",
    "reportes": "ver reportes",
    "recepcion": "manejar facturas de proveedores",
    "pos": "usar el punto de venta",
    "catalogo": "cambiar productos, precios, descuentos o inventario",
    "clientes": "registrar clientes",
    "configuracion": "cambiar la configuración de la empresa",
    "usuarios": "administrar los usuarios de la empresa",
    "contabilidad": "ver y llevar la contabilidad (solo el dueño de la empresa y su contador)",
}

PERMISOS = {
    "dueno": frozenset(DESCRIPCION),
    "contador": frozenset({"emitir", "anular", "cobrar", "reportes", "recepcion", "clientes"}),
    "cajero": frozenset({"emitir", "cobrar", "pos", "clientes"}),
    # Contador externo: solo la contabilidad de las empresas que tiene a cargo
    "contador_externo": frozenset({"contabilidad"}),
}


def tiene(rol: str | None, permiso: str) -> bool:
    return permiso in PERMISOS.get(rol or "dueno", frozenset())


def de_rol(rol: str | None) -> list[str]:
    return sorted(PERMISOS.get(rol or "dueno", frozenset()))
