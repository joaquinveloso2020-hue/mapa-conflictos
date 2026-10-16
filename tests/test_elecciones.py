"""Pruebas del calendario electoral (datos FICTICIOS, solo pruebas: fechas y fuentes inventadas
con la misma sintaxis que los artículos de Wikipedia; nunca se publican)."""
import json
import os
from datetime import datetime, timedelta, timezone

import pytest

from colector import elecciones as el
from colector.config import DIR_RECURSOS
from tests.fakes import Respuesta, SesionFalsa

PAGINA_PRUEBA_2026 = """{{Short description|[PRUEBA]}}
{{Infobox election
| map_caption = Prueba
}}
==September==
* 13 September: [[Elections in Sweden|Sweden]], [[2026 Swedish general election|Parliament]]<ref>{{cite web|url=https://prueba.example/suecia}}</ref>

==October==
* 3 October: [[Elections in Latvia|Latvia]], [[2026 Latvian parliamentary election|Parliament]]<ref name="Letonia">{{cite web |title=Prueba |url=https://prueba.example/letonia |date=2026}}</ref>
* 20 October:
** [[Elections in Brazil|Brazil]], [[2026 Brazilian general election|President (1st round), Chamber of Deputies and Senate]]<ref name=":0" />
** ''[[Politics of Transnistria|Transnistria]], [[2026 Transnistrian presidential election|President]]''
* 14–15 October: [[Elections in the Czech Republic|Czech Republic]], [[2026 Czech Senate election|Senate (1st round)]]
* 25 October:
** [[Elections in Bulgaria|Bulgaria]], [[2026 Bulgarian presidential election|President]]<ref name="Letonia" />
* 30 October – 1 November: [[Elections in the Gambia|Gambia]], [[2026 Gambian presidential election|President]]

==November==
* November: [[Estonia]], [[Next Estonian parliamentary election|Parliament]]
* 3 November: [[Elections in the United States|United States]], [[2026 United States House of Representatives elections|House of Representatives]] and [[2026 United States Senate elections|Senate]]<ref name=":0">{{cite web|url=https://prueba.example/fuente-0}}</ref>
* Early November: [[Elections in Fiji|Fiji]], [[2026 Fijian constitutional referendum|Constitutional referendum]]
<!--==Unknown date==
* [[Elections in Chile|Chile]], [[Oculto|Parliament]]-->
==Unknown date==
* [[Elections in Italy|Italy]], [[Next Italian general election|Chamber of Deputies and Senate]]

==Indirect elections==
* 16 March, 18 June, and 16 October: [[Elections in India|India]], [[2026 Rajya Sabha elections|Council of States]]

==See also==
* [[2026 local electoral calendar]]
"""

AHORA = datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def paises():
    with open(os.path.join(DIR_RECURSOS, "paises.json"), encoding="utf-8") as f:
        return json.load(f)["paises"]


def test_parsea_las_variantes_del_calendario():
    e = el.parsear(PAGINA_PRUEBA_2026, 2026)
    por = {(x["pais_en"], x.get("fecha")): x for x in e}
    # Fecha y elección en el mismo renglón, con fuente citada.
    assert por[("Latvia", "2026-10-03")]["fuentes"] == ["https://prueba.example/letonia"]
    # Renglones anidados bajo una fecha; la referencia con nombre se resuelve aunque se defina después.
    brasil = por[("Brazil", "2026-10-20")]
    assert brasil["cargos_en"] == "President (1st round), Chamber of Deputies and Senate"
    assert brasil["fuentes"] == ["https://prueba.example/fuente-0"]
    assert por[("Bulgaria", "2026-10-25")]["fuentes"] == ["https://prueba.example/letonia"]
    # Territorio (en cursiva en el artículo).
    assert por[("Transnistria", "2026-10-20")]["territorio"] is True
    # Rangos de días, también entre meses.
    assert por[("Czech Republic", "2026-10-14")]["fin"] == "2026-10-15"
    assert por[("Gambia", "2026-10-30")]["fin"] == "2026-11-01"
    # Solo el mes, o un texto sin día dentro de la sección del mes.
    assert por[("Estonia", "2026-11-01")]["precision"] == "mes"
    fiyi = por[("Fiji", "2026-11-01")]
    assert fiyi["precision"] == "mes" and fiyi["texto_fecha"] == "Early November"
    # Dos enlaces de cargos en el mismo renglón.
    assert por[("United States", "2026-11-03")]["cargos_en"] == "House of Representatives and Senate"
    # Sección sin fecha y elecciones indirectas con varias fechas.
    assert por[("Italy", None)]["precision"] == "anio"
    india = [x for x in e if x["pais_en"] == "India"]
    assert [x["fecha"] for x in india] == ["2026-03-16", "2026-06-18", "2026-10-16"]
    assert all(x["indirecta"] for x in india)
    # Lo comentado y lo que está después de "See also" no se toma.
    assert not any(x["pais_en"] in ("Chile",) for x in e)
    assert not any("local" in x["cargos_en"] for x in e)


def test_publicables_horizonte_paises_y_traduccion(paises):
    cache = {"anios": {"2026": {"titulo": "2026 national electoral calendar", "entradas": el.parsear(PAGINA_PRUEBA_2026, 2026)}},
             "ultimo_ok": AHORA.isoformat()}
    doc = el.documento(cache, paises, AHORA)
    lista = doc["elecciones"]
    paises_lista = [x["pais"] for x in lista]
    # Las pasadas no se publican; la de dos días que termina hoy, sí.
    assert "SWE" not in paises_lista and "LVA" not in paises_lista
    assert "CZE" in paises_lista
    # Nombres del artículo que no coinciden con la base de países.
    assert "GMB" in paises_lista and "USA" in paises_lista
    # Un territorio que no está en el mapa se publica sin país y se informa.
    assert doc["sin_ubicar"] == ["Transnistria"]
    brasil = next(x for x in lista if x["pais"] == "BRA")
    assert brasil["cargos"] == "Presidente (1.ª vuelta), Cámara de Diputados y Senado"
    assert brasil["tipos"] == ["ejecutivo", "legislativo"]
    assert brasil["articulo"] == "https://en.wikipedia.org/wiki/2026_Brazilian_general_election"
    # Orden por fecha; las de fecha desconocida al final.
    fechas = [x["fecha"] for x in lista if x["fecha"]]
    assert fechas == sorted(fechas) and lista[-1]["precision"] == "anio"
    assert len({x["id"] for x in lista}) == len(lista)
    # Más allá del horizonte no se publica.
    doc2 = el.documento(cache, paises, AHORA - timedelta(days=400))
    assert not any(x["pais"] == "USA" for x in doc2["elecciones"])


# Mismo formato que el calendario real de 2027: la elección aparece con fecha y otra vez en "Unknown date".
PAGINA_DUPLICADOS_2027 = """==January==
* 30 January: [[Elections in Brazil|Brazil]], [[2027 Prueba election|President (1st round)]]
* January: [[Elections in Peru|Peru]], [[2027 Prueba Peru election|Congress]]<ref>{{cite web|url=https://prueba.example/peru-mes}}</ref>
* 12 January: [[Elections in Peru|Peru]], [[2027 Prueba Peru election|Congress]]
==February==
* 27 February: [[Elections in Brazil|Brazil]], [[2027 Prueba election|President (2nd round)]]
* February: [[Elections in Chile|Chile]], [[2027 Prueba Chile election|Senate]]
* 4 February: [[Elections in Chile|Chile]], [[2027 Prueba Chile election|Senate]]
* 18 February: [[Elections in Chile|Chile]], [[2027 Prueba Chile election|Senate]]
==September==
* 28 September: [[Elections in Slovakia|Slovakia]], [[Next Slovak parliamentary election|Parliament]]<ref>{{cite web|url=https://prueba.example/eslovaquia-fecha}}</ref>
==Unknown date==
* [[Elections in Slovakia|Slovakia]], [[Next Slovak parliamentary election|Parliament]]<ref>{{cite web|url=https://prueba.example/eslovaquia-sin-fecha}}</ref>
* [[Elections in Brazil|Brazil]], [[2027 Prueba election|President (2nd round)]]
* [[Elections in Peru|Peru]], [[2027 Prueba Peru election|Congress]]
* [[Elections in India|India]], [[2027 Rajya Sabha elections|Council of States]]
* [[Elections in Italy|Italy]], [[Next Italian general election|Chamber of Deputies and Senate]]
==Indirect elections==
* 3 April, 9 May: [[Elections in India|India]], [[2027 Rajya Sabha elections|Council of States]]
"""


def _doc_con(paginas: dict, ahora=AHORA, paises_base=None):
    cache = {"anios": {str(a): {"titulo": f"{a} national electoral calendar", "entradas": el.parsear(t, a)}
                       for a, t in paginas.items()}, "ultimo_ok": ahora.isoformat()}
    return el.documento(cache, paises_base, ahora), cache


def test_no_duplica_la_misma_eleccion_con_y_sin_fecha(paises):
    doc, cache = _doc_con({2027: PAGINA_DUPLICADOS_2027}, paises_base=paises)
    lista = doc["elecciones"]
    por_pais = lambda iso: [x for x in lista if x["pais"] == iso]
    # Eslovaquia: una sola entrada, la de día, con sus fuentes primero y la de la entrada omitida después.
    svk = por_pais("SVK")
    assert len(svk) == 1
    assert svk[0]["precision"] == "dia" and svk[0]["fecha"] == "2027-09-28"
    assert svk[0]["id"] == "svk-2027-09-28-parliament"
    assert svk[0]["fuentes"] == ["https://prueba.example/eslovaquia-fecha", "https://prueba.example/eslovaquia-sin-fecha"]
    assert svk[0]["articulo"] == "https://en.wikipedia.org/wiki/Next_Slovak_parliamentary_election"
    # Mes, día y "fecha desconocida" del mismo proceso: queda la de día, con la fuente que solo citaba la de mes.
    per = por_pais("PER")
    assert [(x["precision"], x["fecha"]) for x in per] == [("dia", "2027-01-12")]
    assert per[0]["fuentes"] == ["https://prueba.example/peru-mes"]
    # Distintas vueltas no se fusionan entre sí; la 2.ª vuelta sin fecha se absorbe en la 2.ª vuelta con fecha.
    bra = por_pais("BRA")
    assert [(x["cargos_en"], x["fecha"]) for x in bra] == [("President (1st round)", "2027-01-30"),
                                                           ("President (2nd round)", "2027-02-27")]
    # Si el mes podría ser cualquiera de dos fechas, no se adivina: se conservan las tres entradas.
    assert [(x["precision"], x["fecha"]) for x in por_pais("CHL")] == [
        ("mes", "2027-02-01"), ("dia", "2027-02-04"), ("dia", "2027-02-18")]
    # Indirectas con varias fechas: no se fusionan entre sí ni con la directa "sin fecha" del mismo órgano.
    ind = por_pais("IND")
    assert sorted((x["indirecta"], x["fecha"] or "") for x in ind) == [(False, ""), (True, "2027-04-03"), (True, "2027-05-09")]
    # Sin pares: Italia queda igual.
    assert [x["precision"] for x in por_pais("ITA")] == ["anio"]
    assert doc["duplicados_omitidos"] == 4
    assert len({x["id"] for x in lista}) == len(lista)
    # La caché conserva lo que publicó Wikipedia, sin las fuentes agregadas.
    crudas = [x for x in cache["anios"]["2027"]["entradas"] if x["pais_en"] == "Slovakia"]
    assert len(crudas) == 2 and crudas[0]["fuentes"] == ["https://prueba.example/eslovaquia-fecha"]


def test_duplicado_con_la_fecha_precisa_fuera_del_horizonte(paises):
    # Hoy es 15/10/2026: el 28/9/2027 queda dentro de los 365 días, pero con un horizonte más corto la entrada
    # con fecha se recorta y la de "fecha desconocida" no debe reaparecer sola como si fuera otra elección.
    original = el.HORIZONTE_DIAS
    try:
        el.HORIZONTE_DIAS = 200
        doc, _ = _doc_con({2027: PAGINA_DUPLICADOS_2027}, paises_base=paises)
    finally:
        el.HORIZONTE_DIAS = original
    assert not any(x["pais"] == "SVK" for x in doc["elecciones"])


def test_territorio_sin_mapa_conserva_ficha_y_enlaces(paises):
    doc, _ = _doc_con({2026: PAGINA_PRUEBA_2026}, paises_base=paises)
    tr = next(x for x in doc["elecciones"] if x["pais_en"] == "Transnistria")
    assert tr["pais"] is None and tr["territorio"] is True
    assert tr["pais_nombre"] == "Transnistria" and tr["id"] == "transnistria-2026-10-20-president"
    assert tr["articulo"] == "https://en.wikipedia.org/wiki/2026_Transnistrian_presidential_election"
    assert tr["calendario"] == "https://en.wikipedia.org/wiki/2026_national_electoral_calendar"
    assert tr["cargos"] == "Presidente"


def _respuesta(texto, revid=1):
    return Respuesta(200, js={"parse": {"title": "2026 national electoral calendar", "revid": revid, "wikitext": texto}})


def test_actualizar_cache_fallos_y_pagina_inexistente():
    s = SesionFalsa()
    s.rutas[el.url_api(2026)] = _respuesta(PAGINA_PRUEBA_2026)
    s.rutas[el.url_api(2027)] = Respuesta(200, js={"error": {"code": "missingtitle"}})
    cache = {}
    inf = el.actualizar(cache, s, AHORA)
    assert inf["consultado"] and not inf["errores"]
    assert "2026" in cache["anios"] and "2027" not in cache["anios"]
    assert cache["ultimo_ok"] == AHORA.isoformat()
    # Dentro de las 6 horas no se vuelve a consultar.
    pedidos = len(s.pedidos)
    assert not el.actualizar(cache, s, AHORA + timedelta(hours=2))["consultado"]
    assert len(s.pedidos) == pedidos
    # Si Wikipedia falla, se conserva el calendario anterior y se reintenta en una hora.
    s.fallos[el.url_api(2026)] = 503
    t = AHORA + timedelta(hours=7)
    inf = el.actualizar(cache, s, t)
    assert inf["errores"] and cache["anios"]["2026"]["entradas"]
    assert cache["ultimo_ok"] == AHORA.isoformat()
    assert not el.actualizar(cache, s, t + timedelta(minutes=30))["consultado"]
    assert el.actualizar(cache, s, t + timedelta(minutes=61))["consultado"]
