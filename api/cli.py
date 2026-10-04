"""
Utilidades de línea de comandos.

  python -m api.cli generar-master-key
  python -m api.cli crear-api-key --nombre "Contador" --admin
  python -m api.cli crear-api-key --nombre "POS tienda 1" --emisor <emisor_id>
  python -m api.cli descargar-xsd [--destino xsd]
  python -m api.cli crear-usuario --email contador@x.cr --nombre "Ana" --admin
"""
import argparse
import os
import sys

# XSD oficiales publicados por Hacienda y esquema de firma del W3C
URL_XSD_HACIENDA = "https://www.hacienda.go.cr/docs/{nombre}_V4.4.xsd.xml"
URL_XMLDSIG = "https://www.w3.org/TR/xmldsig-core/xmldsig-core-schema.xsd"
XSD_OFICIALES = [
    "FacturaElectronica", "TiqueteElectronico", "NotaCreditoElectronica", "NotaDebitoElectronica",
    "FacturaElectronicaCompra", "FacturaElectronicaExportacion", "MensajeReceptor", "MensajeHacienda",
]


def descargar_xsd(destino: str) -> None:
    import requests

    os.makedirs(destino, exist_ok=True)
    for nombre in XSD_OFICIALES:
        resp = requests.get(URL_XSD_HACIENDA.format(nombre=nombre), timeout=60)
        resp.raise_for_status()
        if b"<xs:schema" not in resp.content[:2000]:
            raise RuntimeError(f"La descarga de {nombre} no es un XSD")
        # Los XSD importan la firma con una ruta relativa: se apunta al archivo local
        contenido = resp.content.replace(b'schemaLocation="../../xmldsig-core-schema.xsd"',
                                         b'schemaLocation="xmldsig-core-schema.xsd"')
        with open(os.path.join(destino, f"{nombre}_V4.4.xsd"), "wb") as f:
            f.write(contenido)
        print(f"  {nombre}_V4.4.xsd")
    resp = requests.get(URL_XMLDSIG, timeout=60)
    resp.raise_for_status()
    with open(os.path.join(destino, "xmldsig-core-schema.xsd"), "wb") as f:
        f.write(resp.content)
    print("  xmldsig-core-schema.xsd")


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m api.cli")
    sub = parser.add_subparsers(dest="comando", required=True)

    sub.add_parser("generar-master-key", help="Genera un valor para MASTER_KEY")

    p = sub.add_parser("crear-api-key", help="Crea una API key (se muestra una sola vez)")
    p.add_argument("--nombre", required=True)
    grupo = p.add_mutually_exclusive_group(required=True)
    grupo.add_argument("--admin", action="store_true", help="Llave de administrador (todos los emisores)")
    grupo.add_argument("--emisor", help="ID del emisor al que queda restringida")

    p = sub.add_parser("descargar-xsd", help="Descarga los XSD oficiales v4.4 de hacienda.go.cr")
    p.add_argument("--destino", default="xsd")

    p = sub.add_parser("crear-usuario", help="Crea un usuario del panel web (pide la contraseña)")
    p.add_argument("--email", required=True)
    p.add_argument("--nombre", required=True)
    grupo = p.add_mutually_exclusive_group(required=True)
    grupo.add_argument("--admin", action="store_true", help="Contador/administrador: todas las empresas")
    grupo.add_argument("--emisor", help="ID de la empresa a la que queda restringido")

    p = sub.add_parser("reiniciar-2fa", help="Quita la verificación en dos pasos de un usuario (perdió el teléfono)")
    p.add_argument("--email", required=True)

    args = parser.parse_args(argv)

    if args.comando == "reiniciar-2fa":
        from sqlalchemy import select
        from api.models.database import SessionLocal, Usuario
        from api.services import auditoria, usuarios

        db = SessionLocal()
        try:
            u = db.scalar(select(Usuario).where(Usuario.email == args.email.strip().lower()))
            if u is None:
                print("Usuario no encontrado", file=sys.stderr)
                return 1
            usuarios.reiniciar_2fa(db, u)
            usuarios.cerrar_todas(db, u.id)
            auditoria.registrar(db, "usuario.2fa_reiniciada", actor="consola del servidor", detalle=u.email)
        finally:
            db.close()
        print(f"Verificación en dos pasos reiniciada para {args.email}; la configurará de nuevo al ingresar.")
        return 0

    if args.comando == "crear-usuario":
        import getpass
        from api.models.database import Emisor, SessionLocal
        from api.services.usuarios import crear_usuario

        password = getpass.getpass("Contraseña (mínimo 10 caracteres): ")
        if len(password) < 10 or password != getpass.getpass("Repita la contraseña: "):
            print("La contraseña no coincide o es muy corta", file=sys.stderr)
            return 1
        db = SessionLocal()
        try:
            if args.emisor and db.get(Emisor, args.emisor) is None:
                print("Emisor no encontrado", file=sys.stderr)
                return 1
            u = crear_usuario(db, args.email, args.nombre, password, bool(args.admin), args.emisor)
        finally:
            db.close()
        print(f"Usuario creado: {u.email}. Ingrese al panel en /panel/")
        return 0

    if args.comando == "descargar-xsd":
        print(f"Descargando XSD oficiales en {args.destino}/ ...")
        descargar_xsd(args.destino)
        print("Listo. Configure XSD_DIR para validar cada comprobante antes de enviarlo.")
        return 0

    if args.comando == "generar-master-key":
        from api.services.cifrado import generar_master_key
        print(generar_master_key())
        return 0

    if args.comando == "crear-api-key":
        from api.models.database import Emisor, SessionLocal
        from api.security import crear_api_key

        db = SessionLocal()
        try:
            if args.emisor and db.get(Emisor, args.emisor) is None:
                print("Emisor no encontrado", file=sys.stderr)
                return 1
            registro, llave = crear_api_key(db, args.nombre, bool(args.admin), args.emisor)
        finally:
            db.close()
        print(f"API key creada (id {registro.id}). Guárdela ahora, no se volverá a mostrar:\n{llave}")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
