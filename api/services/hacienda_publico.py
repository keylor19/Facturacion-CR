"""
Servicios públicos de Hacienda (https://api.hacienda.go.cr, no requieren
credenciales). Las respuestas se cachean en Redis.

  /fe/ae?identificacion=              situación tributaria y actividades económicas
  /fe/ex?autorizacion=                datos de una exoneración (AL-XXXXXXXX-XX)
  /fe/cabys?q= | ?codigo=             catálogo CABYS (con su tarifa de IVA)
  /fe/agropecuario?identificacion=    productores agropecuarios registrados en el MAG
  /fe/pesca?identificacion=           productores de pesca y acuicultura (INCOPESCA)
  /indicadores/tc                     tipo de cambio del dólar (compra/venta) y del euro
  /indicadores/tc/dolar/historico     tipo de cambio diario del dólar entre dos fechas

Políticas de uso de Hacienda: 20 solicitudes/s en ráfaga y 10/s sostenidas por
IP; si se superan, bloquea la IP 10 minutos (HTTP 429). Como todas las empresas
salen por la IP de este servidor:
  - se limita a LIMITE_POR_SEGUNDO solicitudes por segundo entre todos los procesos;
  - se cachean también los "no encontrado", para no repetir consultas de
    identificaciones inexistentes;
  - ante un 429 se dejan de enviar consultas durante el bloqueo (solo caché).

⚠️ El formato de estas respuestas lo define Hacienda y puede cambiar; se
devuelven tal cual, salvo el tipo de cambio que se normaliza.
"""
import logging
import re
import time
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

import redis
import requests
from sqlalchemy import delete, func, select, or_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import SQLAlchemyError

from api.models.database import Cliente, Emisor, RegistroHacienda, SessionLocal, TipoCambioDiario, gen_uuid, utcnow
from api.services import catalogo_cabys
from api.services.cache import obtener_json, guardar_json, redis_client
from config.settings import get_settings

logger = logging.getLogger(__name__)

LIMITE_POR_SEGUNDO = 8          # por debajo de las 10/s sostenidas que permite Hacienda
BLOQUEO_429 = 600               # Hacienda bloquea la IP 10 minutos
TTL_NO_ENCONTRADO = 3600
CLAVE_BLOQUEO = "hp:bloqueo"
NO_ENCONTRADO = {"__no_encontrado__": True}
PATRON_AUTORIZACION = re.compile(r"AL-\d{8}-\d{2}", re.IGNORECASE)


class HaciendaPublicoError(Exception):
    def __init__(self, message, status_code=502):
        super().__init__(message)
        self.status_code = status_code


def _esperar_turno() -> None:
    """Limitador global (Redis) de solicitudes por segundo hacia Hacienda."""
    try:
        r = redis_client()
        for _ in range(20):
            segundo = int(time.time())
            clave = f"hp:rl:{segundo}"
            n = r.incr(clave)
            if n == 1:
                r.expire(clave, 2)
            if n <= LIMITE_POR_SEGUNDO:
                return
            time.sleep(max(0.05, segundo + 1 - time.time()))
    except redis.RedisError:
        return  # sin Redis no se limita (no se bloquea la operación)
    raise HaciendaPublicoError("Demasiadas consultas a Hacienda en este momento; intente en unos segundos", 503)


def _solicitar(url: str, params: dict) -> requests.Response:
    """Una solicitud con un reintento controlado ante fallas temporales (no ante 429)."""
    for intento in range(2):
        _esperar_turno()
        try:
            resp = requests.get(url, params=params, timeout=15)
        except requests.RequestException as exc:
            if intento:
                raise HaciendaPublicoError(f"No se pudo contactar a Hacienda: {exc}") from exc
        else:
            if resp.status_code not in (502, 503, 504) or intento:
                return resp
        time.sleep(1)
    raise HaciendaPublicoError("No se pudo contactar a Hacienda")  # pragma: no cover


def _consultar_hacienda(path: str, params: dict, cache_key: str, ttl: int):
    """Consulta directa a Hacienda (sin caché ni datos guardados)."""
    if obtener_json(CLAVE_BLOQUEO):
        raise HaciendaPublicoError(
            "Hacienda bloqueó temporalmente las consultas por exceso de solicitudes; se reanudan en unos minutos", 503)

    resp = _solicitar(get_settings().HACIENDA_PUBLIC_API.rstrip("/") + path, params)
    if resp.status_code == 429:
        guardar_json(CLAVE_BLOQUEO, True, BLOQUEO_429)
        logger.error("Hacienda respondió 429: se suspenden las consultas públicas %s s", BLOQUEO_429)
        raise HaciendaPublicoError("Hacienda limitó las consultas (429); intente en unos minutos", status_code=503)
    if resp.status_code == 404:
        guardar_json(cache_key, NO_ENCONTRADO, min(ttl, TTL_NO_ENCONTRADO))
        raise HaciendaPublicoError("No encontrado en Hacienda", status_code=404)
    if resp.status_code == 400:
        raise HaciendaPublicoError("Hacienda indica que el dato consultado no es válido", status_code=422)
    if resp.status_code != 200:
        raise HaciendaPublicoError(f"Hacienda no está disponible en este momento (HTTP {resp.status_code})")
    try:
        data = resp.json()
    except ValueError as exc:
        raise HaciendaPublicoError("Respuesta inválida de Hacienda") from exc
    # Algunos servicios responden HTTP 200 con el error en el cuerpo
    if isinstance(data, dict) and (data.get("status") == 404 or data.get("code") == 404):
        guardar_json(cache_key, NO_ENCONTRADO, min(ttl, TTL_NO_ENCONTRADO))
        raise HaciendaPublicoError("No encontrado en Hacienda", status_code=404)
    if isinstance(data, dict) and (data.get("status") == 400 or data.get("code") == 400):
        raise HaciendaPublicoError("Hacienda indica que el dato consultado no es válido", status_code=422)
    guardar_json(cache_key, data, ttl)
    return data


# --- Datos guardados en la base de datos ----------------------------------------
# Prefijo de la clave de caché -> tipo de registro que se guarda (el resto no se guarda:
# búsquedas de texto en CABYS e histórico del tipo de cambio).
PERSISTENTES = (("hp:cabys:c:", "cabys", 86400), ("hp:ae:", "ae", 3600), ("hp:ex:", "ex", 3600),
                ("hp:agropecuario:", "agropecuario", 3600), ("hp:pesca:", "pesca", 3600), ("hp:tc", "tc", 3600))


def _registro_de(cache_key: str):
    for prefijo, tipo, _ in PERSISTENTES:
        if tipo == "tc" and cache_key == prefijo:
            return tipo, "actual"
        if tipo != "tc" and cache_key.startswith(prefijo):
            return tipo, cache_key[len(prefijo):]
    return None


def _clave_cache(tipo: str, clave: str) -> tuple[str, int]:
    prefijo, _, ttl = next(p for p in PERSISTENTES if p[1] == tipo)
    return (prefijo if tipo == "tc" else prefijo + clave), ttl


def _vigencia(tipo: str, encontrado: bool) -> timedelta:
    if tipo == "tc":
        return timedelta(hours=1)
    if not encontrado:
        return timedelta(days=1)   # alguien puede inscribirse: se reintenta antes
    return timedelta(days=get_settings().DIAS_ACTUALIZAR_HACIENDA)


def _leer_local(tipo: str, clave: str) -> dict | None:
    try:
        with SessionLocal() as s:
            r = s.scalar(select(RegistroHacienda).where(RegistroHacienda.tipo == tipo, RegistroHacienda.clave == clave))
            if r is None:
                return None
            if utcnow() - r.usado_en > timedelta(days=1):
                r.usado_en = utcnow()
                s.commit()
            return {"encontrado": r.encontrado, "datos": r.datos, "actualizado_en": r.actualizado_en}
    except SQLAlchemyError as exc:
        logger.warning("No se pudo leer el registro local de Hacienda %s/%s: %s", tipo, clave, exc)
        return None


def _guardar_local(tipo: str, clave: str, ruta: str, params: dict, encontrado: bool, datos) -> None:
    ahora = utcnow()
    valores = {"ruta": ruta, "parametros": params, "encontrado": encontrado, "datos": datos, "actualizado_en": ahora}
    try:
        with SessionLocal() as s:
            s.execute(pg_insert(RegistroHacienda)
                      .values(id=gen_uuid(), tipo=tipo, clave=clave, usado_en=ahora, **valores)
                      .on_conflict_do_update(constraint="uq_registro_hacienda", set_=valores))
            s.commit()
    except SQLAlchemyError as exc:
        logger.warning("No se pudo guardar el registro local de Hacienda %s/%s: %s", tipo, clave, exc)


def _get(path: str, params: dict, cache_key: str, ttl: int, forzar: bool = False):
    """
    Orden de consulta: caché (Redis) -> datos guardados vigentes -> Hacienda.
    Si Hacienda no responde (caída, límite o bloqueo) se devuelven los datos
    guardados aunque estén desactualizados, marcados con "_respaldo_local".
    forzar=True consulta siempre a Hacienda (actualización periódica).
    """
    if not forzar:
        cached = obtener_json(cache_key)
        if cached == NO_ENCONTRADO:
            raise HaciendaPublicoError("No encontrado en Hacienda", status_code=404)
        if cached is not None:
            return cached
    registro = _registro_de(cache_key)
    local = _leer_local(*registro) if registro and not forzar else None
    if local and utcnow() - local["actualizado_en"] < _vigencia(registro[0], local["encontrado"]):
        if not local["encontrado"]:
            guardar_json(cache_key, NO_ENCONTRADO, TTL_NO_ENCONTRADO)
            raise HaciendaPublicoError("No encontrado en Hacienda", status_code=404)
        guardar_json(cache_key, local["datos"], ttl)
        return local["datos"]

    try:
        data = _consultar_hacienda(path, params, cache_key, ttl)
    except HaciendaPublicoError as exc:
        if exc.status_code == 404:
            if registro:
                _guardar_local(*registro, path, params, False, None)
            raise
        if local and exc.status_code != 422:
            return _respaldo(local, exc, registro)
        raise
    if registro:
        _guardar_local(*registro, path, params, True, data)
    return data


def _respaldo(local: dict, exc: HaciendaPublicoError, registro):
    """Hacienda no responde: se sigue trabajando con lo guardado."""
    logger.warning("Hacienda no respondió (%s); se usan los datos guardados de %s/%s", exc, *registro)
    if not local["encontrado"]:
        raise HaciendaPublicoError("No encontrado en Hacienda", status_code=404)
    datos = local["datos"]
    if isinstance(datos, dict):
        datos = {**datos, "_respaldo_local": {"actualizado_en": local["actualizado_en"].isoformat(), "motivo": str(exc)}}
    return datos


def actualizar_registros(limite: int | None = None, pausa: float = 0.5) -> dict:
    """
    Tarea periódica: vuelve a consultar en Hacienda los registros con más de
    DIAS_ACTUALIZAR_HACIENDA días y precarga las cédulas de clientes y empresas
    que aún no están guardadas. Va despacio (pausa entre consultas) para dejar
    margen a las consultas de los usuarios y se detiene si Hacienda limita.
    """
    settings = get_settings()
    limite = limite or settings.LOTE_ACTUALIZACION_HACIENDA
    ahora = utcnow()
    with SessionLocal() as s:
        cedulas = set(s.scalars(select(Cliente.numero_identificacion)).all())
        cedulas |= set(s.scalars(select(Emisor.numero_identificacion)).all())
        guardadas = set(s.scalars(select(RegistroHacienda.clave).where(RegistroHacienda.tipo == "ae")).all())
        tareas = [("ae", c, "/fe/ae", {"identificacion": c}) for c in sorted(cedulas - guardadas)
                  if re.fullmatch(r"\d{9,12}", c)]
        vencidos = s.execute(
            select(RegistroHacienda.tipo, RegistroHacienda.clave, RegistroHacienda.ruta, RegistroHacienda.parametros)
            .where(RegistroHacienda.tipo.notin_(("tc", "sistema")),
                   or_(RegistroHacienda.actualizado_en < ahora - timedelta(days=settings.DIAS_ACTUALIZAR_HACIENDA),
                       (RegistroHacienda.encontrado.is_(False)) & (RegistroHacienda.actualizado_en < ahora - timedelta(days=1))))
            .order_by(RegistroHacienda.actualizado_en).limit(limite)).all()
        tareas += [tuple(v) for v in vencidos]
        # Limpieza: lo que nadie consulta hace un año (o "no encontrados" sin uso en 90 días)
        s.execute(delete(RegistroHacienda).where(RegistroHacienda.tipo != "sistema", or_(
            RegistroHacienda.usado_en < ahora - timedelta(days=365),
            (RegistroHacienda.encontrado.is_(False)) & (RegistroHacienda.usado_en < ahora - timedelta(days=90)))))
        s.commit()

    resultado = {"actualizados": 0, "no_encontrados": 0, "errores": 0, "detenido": False}
    for tipo, clave, ruta, params in tareas[:limite]:
        cache_key, ttl = _clave_cache(tipo, clave)
        try:
            _get(ruta, params, cache_key, ttl, forzar=True)
            resultado["actualizados"] += 1
        except HaciendaPublicoError as exc:
            if exc.status_code == 404:
                resultado["no_encontrados"] += 1
            elif exc.status_code == 503:
                resultado["detenido"] = True   # límite o bloqueo de Hacienda: se sigue mañana
                break
            else:
                resultado["errores"] += 1
        time.sleep(pausa)
    return resultado


def verificar_muestra_cabys(cantidad: int = 30, pausa: float = 0.5) -> dict:
    """
    Red de seguridad del catálogo CABYS local: compara una muestra al azar con
    Hacienda. Si un código cambió (IVA o descripción) se corrige; si Hacienda ya
    no lo tiene, se borra. En un año se revisa todo el catálogo varias veces.
    """
    from api.models.database import CodigoCabys
    resultado = {"revisados": 0, "corregidos": 0, "eliminados": 0, "detenido": False}
    try:
        with SessionLocal() as s:
            muestra = s.scalars(select(CodigoCabys).order_by(func.random()).limit(cantidad)).all()
            locales = {c.codigo: (c.descripcion, Decimal(c.impuesto)) for c in muestra}
    except SQLAlchemyError:
        return resultado
    for codigo, (descripcion, impuesto) in locales.items():
        try:
            data = _get("/fe/cabys", {"codigo": codigo}, f"hp:cabys:c:{codigo}", ttl=86400, forzar=True)
        except HaciendaPublicoError as exc:
            if exc.status_code == 503:
                resultado["detenido"] = True
                break
            continue
        resultado["revisados"] += 1
        lista = data if isinstance(data, list) else (data or {}).get("cabys", [])
        oficial = next((x for x in lista if str(x.get("codigo")) == codigo), None)
        if oficial is None:
            with SessionLocal() as s:
                s.execute(delete(CodigoCabys).where(CodigoCabys.codigo == codigo))
                s.commit()
            resultado["eliminados"] += 1
            logger.warning("CABYS %s ya no existe en Hacienda: eliminado del catálogo local", codigo)
        elif (Decimal(str(oficial.get("impuesto"))) != impuesto
              or str(oficial.get("descripcion", "")).strip() != descripcion):
            catalogo_cabys.guardar_resultados([oficial])
            resultado["corregidos"] += 1
            logger.warning("CABYS %s cambió en Hacienda (IVA %s -> %s): corregido", codigo, impuesto, oficial.get("impuesto"))
        time.sleep(pausa)
    return resultado


def _identificacion(identificacion: str) -> str:
    if not re.fullmatch(r"\d{9,12}", identificacion or ""):
        raise HaciendaPublicoError("Identificación inválida: 9 a 12 dígitos, sin guiones", status_code=422)
    return identificacion


def contribuyente(identificacion: str) -> dict:
    """Nombre, tipo de identificación, régimen, situación tributaria y actividades."""
    _identificacion(identificacion)
    return _get("/fe/ae", {"identificacion": identificacion}, f"hp:ae:{identificacion}", ttl=3600)


def exoneracion(autorizacion: str) -> dict:
    autorizacion = (autorizacion or "").strip().upper()
    if not PATRON_AUTORIZACION.fullmatch(autorizacion):
        raise HaciendaPublicoError("Número de autorización inválido: formato AL-XXXXXXXX-XX", status_code=422)
    return _get("/fe/ex", {"autorizacion": autorizacion}, f"hp:ex:{autorizacion}", ttl=3600)


MAX_CABYS_DESCRITOS = 40  # cada código es una consulta (cacheada un día): se limita para no saturar a Hacienda


def exoneracion_con_cabys(autorizacion: str) -> dict:
    """
    Exoneración más la descripción y tarifa de los CABYS que autoriza. Si la
    exoneración no trae lista (poseeCabys = false), cubre cualquier CABYS.
    """
    ex = dict(exoneracion(autorizacion))
    codigos = [str(c) for c in (ex.get("cabys") or [])]
    detalle = []
    for i, codigo in enumerate(codigos):
        item = {"codigo": codigo, "descripcion": None, "impuesto": None}
        if i < MAX_CABYS_DESCRITOS:
            try:
                encontrado = cabys(codigo=codigo)
                lista = encontrado if isinstance(encontrado, list) else (encontrado or {}).get("cabys", [])
                c = next((x for x in lista if str(x.get("codigo")) == codigo), None)
                if c:
                    item.update(descripcion=c.get("descripcion"), impuesto=c.get("impuesto"))
            except HaciendaPublicoError as exc:
                if exc.status_code == 503:  # bloqueo o límite: no seguir consultando
                    break
        detalle.append(item)
    detalle += [{"codigo": c, "descripcion": None, "impuesto": None} for c in codigos[len(detalle):]]
    ex["cabys_detalle"] = detalle
    ex["aplica_a_todo"] = not codigos
    return ex


def exoneraciones_no_aplicables(productos) -> list[str]:
    """
    Líneas con exoneración AL-XXXXXXXX-XX cuyo CABYS no está en la lista que
    autoriza Hacienda. Si Hacienda no responde no se bloquea (lista vacía).
    """
    problemas = []
    for i, p in enumerate(productos, start=1):
        exo = getattr(p, "exoneracion", None)
        if not exo or not PATRON_AUTORIZACION.fullmatch(exo.numero_documento.strip()):
            continue
        try:
            ex = exoneracion(exo.numero_documento)
        except HaciendaPublicoError as exc:
            if exc.status_code == 404:
                problemas.append(f"línea {i}: la exoneración {exo.numero_documento} no existe en Hacienda")
            continue
        autorizados = [str(c) for c in (ex.get("cabys") or [])]
        if autorizados and p.codigo_cabys not in autorizados:
            problemas.append(f"línea {i}: el CABYS {p.codigo_cabys} no está contemplado en la exoneración "
                             f"{exo.numero_documento.upper()}")
    return problemas


def cabys(texto: str | None = None, codigo: str | None = None, top: int = 20):
    if codigo:
        if not re.fullmatch(r"\d{13}", codigo):
            raise HaciendaPublicoError("Código CABYS inválido: 13 dígitos", status_code=422)
        # 1) catálogo local; 2) Hacienda (por si el catálogo local está desactualizado)
        local = catalogo_cabys.por_codigo(codigo)
        if local:
            return local
        data = _get("/fe/cabys", {"codigo": codigo}, f"hp:cabys:c:{codigo}", ttl=86400)
        catalogo_cabys.guardar_resultados(data if isinstance(data, list) else (data or {}).get("cabys"))
        return data
    if not texto or len(texto.strip()) < 3:
        raise HaciendaPublicoError("Indique al menos 3 caracteres para buscar", status_code=422)
    texto = texto.strip()[:100]
    # Con el catálogo oficial importado se busca solo localmente (sin consultar a Hacienda)
    if catalogo_cabys.completo():
        local = catalogo_cabys.buscar(texto, top)
        if local is not None:
            return local
    try:
        data = _get("/fe/cabys", {"q": texto, "top": top}, f"hp:cabys:q:{texto.lower()}:{top}", ttl=86400)
    except HaciendaPublicoError as exc:
        local = catalogo_cabys.buscar(texto, top) if exc.status_code in (502, 503) else None
        if local and local["cabys"]:
            return {**local, "_respaldo_local": {"motivo": str(exc)}}
        raise
    catalogo_cabys.guardar_resultados(data if isinstance(data, list) else (data or {}).get("cabys"))
    return data


def cabys_inexistentes(codigos: list[str]) -> list[str]:
    """
    Códigos que NO existen en el catálogo CABYS. Si el servicio de Hacienda no
    responde, se asume que existen (no se bloquea la facturación por una caída).
    """
    faltantes = []
    for codigo in dict.fromkeys(codigos):
        try:
            resultado = cabys(codigo=codigo)
        except HaciendaPublicoError as exc:
            if exc.status_code in (404, 422):
                faltantes.append(codigo)
            else:
                logger.warning("No se pudo validar el CABYS %s: %s", codigo, exc)
            continue
        lista = resultado if isinstance(resultado, list) else (resultado or {}).get("cabys", [])
        if not any(str(c.get("codigo")) == codigo for c in lista):
            faltantes.append(codigo)
    return faltantes


def productor(identificacion: str) -> dict:
    """
    Registro como productor agropecuario (MAG) y de pesca/acuicultura (INCOPESCA).
    Se usa para la tarifa reducida de insumos agropecuarios y de pesca.
    """
    _identificacion(identificacion)
    resultado = {}
    for nombre, path in (("agropecuario", "/fe/agropecuario"), ("pesca", "/fe/pesca")):
        try:
            resultado[nombre] = _get(path, {"identificacion": identificacion}, f"hp:{nombre}:{identificacion}", ttl=3600)
        except HaciendaPublicoError as exc:
            if exc.status_code != 404:
                raise
            resultado[nombre] = None
    resultado["registrado"] = bool(resultado["agropecuario"] or resultado["pesca"])
    return resultado


def tipos_de_cambio() -> dict:
    """Dólar (compra y venta) y euro en una sola consulta."""
    data = _get("/indicadores/tc", {}, "hp:tc", ttl=3600)
    dolar = (data or {}).get("dolar") or {}
    euro = (data or {}).get("euro") or {}
    resultado = {
        "USD": {"compra": (dolar.get("compra") or {}).get("valor"), "venta": (dolar.get("venta") or {}).get("valor"),
                "fecha": (dolar.get("venta") or {}).get("fecha")},
        "EUR": {"colones": euro.get("colones"), "dolares": euro.get("dolares"), "fecha": euro.get("fecha")},
    }
    if not (isinstance(data, dict) and data.get("_respaldo_local")):
        _guardar_tipo_cambio_del_dia(resultado)
    return resultado


def _decimal(valor):
    try:
        return Decimal(str(valor)) if valor is not None else None
    except InvalidOperation:
        return None


def _guardar_dia(fecha_iso, **columnas) -> None:
    """Guarda (o completa) el tipo de cambio de un día en el histórico propio."""
    try:
        dia = date.fromisoformat(str(fecha_iso)[:10])
    except ValueError:
        return
    columnas = {k: v for k, v in columnas.items() if v is not None}
    if not columnas:
        return
    columnas["actualizado_en"] = utcnow()
    try:
        with SessionLocal() as s:
            s.execute(pg_insert(TipoCambioDiario).values(fecha=dia, **columnas)
                      .on_conflict_do_update(index_elements=["fecha"], set_=columnas))
            s.commit()
    except SQLAlchemyError as exc:
        logger.warning("No se pudo guardar el tipo de cambio del %s: %s", dia, exc)


def _guardar_tipo_cambio_del_dia(tc: dict) -> None:
    # Una vez por hora como máximo (esta función se llama en cada factura en moneda extranjera)
    marca = f"hp:tcg:{tc['USD']['fecha']}:{tc['EUR']['fecha']}"
    if obtener_json(marca):
        return
    _guardar_dia(tc["USD"]["fecha"], usd_compra=_decimal(tc["USD"]["compra"]), usd_venta=_decimal(tc["USD"]["venta"]))
    _guardar_dia(tc["EUR"]["fecha"], eur_colones=_decimal(tc["EUR"]["colones"]), eur_dolares=_decimal(tc["EUR"]["dolares"]))
    guardar_json(marca, True, 3600)


def tipo_cambio_en_fecha(moneda: str, dia: date) -> Decimal:
    """
    Tipo de cambio de un día anterior (facturas de contingencia con fecha atrasada):
    del histórico propio, o del histórico de Hacienda; si no hay, el vigente.
    """
    moneda = moneda.upper()
    columna = TipoCambioDiario.usd_venta if moneda == "USD" else TipoCambioDiario.eur_colones

    def buscar():
        try:
            with SessionLocal() as s:
                return s.scalar(select(columna).where(columna.isnot(None), TipoCambioDiario.fecha <= dia,
                                                      TipoCambioDiario.fecha >= dia - timedelta(days=7))
                                .order_by(TipoCambioDiario.fecha.desc()).limit(1))
        except SQLAlchemyError:
            return None

    valor = buscar()
    if valor is None and moneda == "USD":
        try:
            tipo_cambio_historico(dia, dia)
            valor = buscar()
        except HaciendaPublicoError:
            pass
    if valor is not None and valor > 0:
        return Decimal(valor)
    logger.warning("Sin tipo de cambio %s del %s; se usa el vigente", moneda, dia)
    return tipo_cambio(moneda)


def tipo_cambio(moneda: str) -> Decimal:
    """Tipo de cambio de referencia (venta) en colones para USD o EUR."""
    moneda = moneda.upper()
    if moneda not in ("USD", "EUR"):
        raise HaciendaPublicoError(f"Hacienda no publica tipo de cambio para {moneda}; indique tipo_cambio", 422)
    tc = tipos_de_cambio()
    valor = tc["USD"]["venta"] if moneda == "USD" else tc["EUR"]["colones"]
    try:
        resultado = Decimal(str(valor))
    except (InvalidOperation, TypeError) as exc:
        raise HaciendaPublicoError("Hacienda devolvió un tipo de cambio inválido") from exc
    if resultado <= 0:
        raise HaciendaPublicoError("Hacienda devolvió un tipo de cambio inválido")
    return resultado


def tipo_cambio_historico(desde: date, hasta: date):
    """Tipo de cambio diario del dólar entre dos fechas (máximo 366 días)."""
    if desde > hasta:
        raise HaciendaPublicoError("La fecha inicial debe ser anterior a la final", 422)
    if (hasta - desde).days > 366:
        raise HaciendaPublicoError("Consulte como máximo un año", 422)
    if hasta > date.today():
        raise HaciendaPublicoError("No hay tipo de cambio para fechas futuras", 422)

    def propios():
        try:
            with SessionLocal() as s:
                return s.scalars(select(TipoCambioDiario).where(
                    TipoCambioDiario.fecha.between(desde, hasta), TipoCambioDiario.usd_venta.isnot(None))
                    .order_by(TipoCambioDiario.fecha)).all()
        except SQLAlchemyError:
            return []

    def formato(filas):
        return [{"fecha": f.fecha.isoformat(), "compra": _numero(f.usd_compra), "venta": _numero(f.usd_venta)}
                for f in filas]

    # 1) Histórico propio (se guarda cada día); 2) si faltan días, el histórico de Hacienda
    filas = propios()
    if len(filas) == (hasta - desde).days + 1:
        return formato(filas)
    ttl = 86400 * 7 if hasta < date.today() else 3600   # los días cerrados no cambian
    try:
        data = _get("/indicadores/tc/dolar/historico", {"d": desde.isoformat(), "h": hasta.isoformat()},
                    f"hp:tch:{desde}:{hasta}", ttl=ttl)
    except HaciendaPublicoError:
        if filas:
            return formato(filas)   # Hacienda no responde: lo que haya guardado
        raise
    for x in _filas_historico(data):
        _guardar_dia(x["fecha"], usd_compra=x["compra"], usd_venta=x["venta"])
    return formato(propios()) or data


def _numero(valor):
    return float(valor) if valor is not None else None


def _filas_historico(data) -> list[dict]:
    """Interpreta el histórico de Hacienda (lista de días con fecha, compra y venta)."""
    if isinstance(data, dict):
        data = data.get("historico") or data.get("datos") or data.get("dolar") or []
    filas = []
    for x in data if isinstance(data, list) else []:
        if not isinstance(x, dict) or not x.get("fecha"):
            continue
        compra, venta = x.get("compra"), x.get("venta")
        compra = compra.get("valor") if isinstance(compra, dict) else compra
        venta = venta.get("valor") if isinstance(venta, dict) else venta
        filas.append({"fecha": x["fecha"], "compra": _decimal(compra), "venta": _decimal(venta)})
    return filas
