"""
Parseo de XML endurecido: sin entidades externas, sin DTD y sin acceso a red
(protección contra XXE y "billion laughs"). Usar SIEMPRE esto para parsear
XML, especialmente el que viene de fuera (respuestas de Hacienda, callbacks).
"""
from lxml import etree


def parser_seguro() -> etree.XMLParser:
    return etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        load_dtd=False,
        dtd_validation=False,
        huge_tree=False,
        remove_blank_text=False,
    )


def parsear(xml: str | bytes) -> etree._Element:
    if isinstance(xml, str):
        xml = xml.encode("utf-8")
    return etree.fromstring(xml, parser_seguro())
