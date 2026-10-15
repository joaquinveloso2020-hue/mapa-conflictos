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
