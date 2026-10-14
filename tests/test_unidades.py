"""Pruebas unitarias con datos ficticios (solo pruebas)."""
from datetime import datetime, timezone

import pytest

from colector import config, urls
from colector.agrupacion import estado_corroboracion
from colector.clasificacion import Prefiltro, clasificar, marcas
from colector.fuente_gdelt import franjas, parsear_eventos, parsear_gkg
from colector.geografia import Geografia, ubicar_articulo
from colector.texto import Buscador, normalizar, titulo_normalizado_para_copias
from tests.fakes import fila_evento, fila_gkg


@pytest.fixture(scope="module")
def conf():
    return config.cargar("https://ejemplo.github.io/mapa-conflictos/")


def test_url_canonica_quita_seguimiento_y_amp():
    a = urls.canonica("https://www.example.com/news/story/amp?utm_source=x&id=3#frag")
    b = urls.canonica("http://m.example.com/news/story?id=3")
    assert a == b == "https://example.com/news/story?id=3"
    assert urls.dominio("https://news.bbc.co.uk/x") == "bbc.co.uk"


def test_buscador_siglas_prefijos_y_acentos():
    b = Buscador(["RSF", "ataque*", "Sudán"])
    t = "Las RSF lanzaron ataques en Sudan"
    assert set(b.encontrar(t, normalizar(t))) == {"RSF", "ataque*", "Sudán"}
    t2 = "rsf es una ONG"  # sigla en minúsculas no coincide
    assert "RSF" not in b.encontrar(t2, normalizar(t2))


def test_clasifica_sudan_y_no_sudan_del_sur(conf):
    a = {"titulo": "[PRUEBA] Drone strike kills 12 in El Obeid, Sudan", "via": "rss"}
    assert [r["id"] for r in clasificar(a, conf)][0] == "sudan"
    b = {"titulo": "[PRUEBA] South Sudan army clashes with SPLA-IO in Upper Nile", "via": "rss"}
    ids = [r["id"] for r in clasificar(b, conf)]
    assert "sudan-del-sur" in ids and "sudan" not in ids


def test_clasifica_disputas_y_requiere_vocabulario(conf):
    a = {"titulo": "[PRUEBA] Argentina pide arbitraje por Malvinas", "via": "rss"}
    assert clasificar(a, conf)[0]["id"] == "malvinas"
    b = {"titulo": "[PRUEBA] Taiwan chipmaker reports record earnings", "via": "rss"}
    assert "taiwan" not in [r["id"] for r in clasificar(b, conf)]
    c = {"titulo": "[PRUEBA] Chinese coast guard vessels near Taiwan", "via": "rss"}
    assert "taiwan" in [r["id"] for r in clasificar(c, conf)]


def test_lugar_gdelt_solo_no_alcanza(conf):
    """En la prueba real, asignar por país mencionado en GDELT generaba ruido: ya no alcanza."""
    a = {"titulo": "[PRUEBA] Headline without names", "via": "gdelt", "vias": ["gdelt"],
         "temas": ["ARMEDCONFLICT", "KILL"], "paises_mencionados": ["SDN", "TCD"]}
    assert clasificar(a, conf) == []


def test_ruido_observado_en_la_primera_prueba_real(conf):
    # Titulares (traducidos) que la primera ejecución real asignó mal; no deben asignarse.
    ruido = [
        "Huracán Simón tiene en alerta a los horticultores de Culiacán y Navolato",
        "El Telégrafo - Tráfico colapsado en Guayaquil este 14 de octubre por fallas en semáforos",
        "Lista de destinos de American Airlines está seguro de que te golpee",
        "Shell to invest in new gas field off Nigeria",
        # Segunda revisión con datos reales (14/10/2026)
        "TRAGEDIJA KOD GRUDA: Mladić (19) iz Širokog Brijega poginuo u teškoj prometnoj nesreći",
        "Extienden una semana la castración gratuita en Nuestras Malvinas",
        "Robo de un celular y una tablet dejó a un hombre herido con arma de fuego en Bogotá",
        "Tormentas severas matan a 1 en Grecia",
        "Floods kill 20 in Sudan as rains hit Khartoum",
        "Tribal clashes in Papua New Guinea highlands kill 12",
    ]
    for t in ruido:
        assert clasificar({"titulo": t, "via": "rss"}, conf) == [], t
    assert clasificar({"titulo": "Houthis Vow More Attacks After Strike on Aramco HQ", "via": "rss"}, conf)[0]["id"] == "yemen"
    assert clasificar({"titulo": "Ofensiva russa deixa 600 mil ucranianos sem eletricidade", "via": "rss",
                       "titulo_es": "Ofensiva rusa deja 600.000 ucranianos sin electricidad"}, conf)[0]["id"] == "ucrania-rusia"
    # Un término fuerte asigna aunque el titular hable de un desastre.
    assert clasificar({"titulo": "Floods kill 20 in Sudan's Darfur camps", "via": "rss"}, conf)[0]["id"] == "sudan"
    assert clasificar({"titulo": "Chile evalúa fabricar fragatas británicas mientras crece la tensión por Malvinas",
                       "via": "rss"}, conf)[0]["id"] == "malvinas"


def test_marcas_titular(conf):
    m = marcas({"titulo": "[PRUEBA] Army denies claims of attack, reportedly 5 dead"}, conf)
    assert m["desmentido"] and m["preliminar"]


def test_parseo_gkg_y_eventos(conf):
    ts = "20261013120000"
    lug = "4#El Obeid, North Kordofan, Sudan#SU#SU00##13.18#30.21#-123#100"
    gkg = fila_gkg("https://ejemplo-prueba.org/a1", "[PRUEBA] Clashes in El Obeid", "ARMEDCONFLICT;KILL", lug, ts)
    otra = fila_gkg("https://ejemplo-prueba.org/a2", "[PRUEBA] Weather report", "", "", ts)
    arts, total, inval = parsear_gkg(gkg + "\n" + otra + "\n", conf.fips_a_iso, Prefiltro(conf), False)
    assert total == 2 and inval == 0 and len(arts) == 1
    a = arts[0]
    assert a["pub"].startswith("2026-10-13T12:00") and a["visto_gdelt"] and a["paises_mencionados"] == ["SDN"]
    ev = fila_evento("https://ejemplo-prueba.org/a1", "SU", 4, "El Obeid, Sudan", 13.18, 30.21)
    geo, desc, _ = parsear_eventos(ev + "\n", conf.fips_a_iso)
    g = geo[urls.clave("https://ejemplo-prueba.org/a1")]
    assert g["pais"] == "SDN" and g["precision"] == "ciudad" and g["fecha_hecho"] == "2026-10-13"
    assert "SDN" in desc


def test_franjas_solapadas():
    ahora = datetime(2026, 10, 13, 12, 10, tzinfo=timezone.utc)
    f = franjas(ahora, 1)
    assert f[0] == "20261013120000" and f[-1] == "20261013111500" and len(f) == 4


def test_geolocalizacion_no_inventa_coordenadas(conf):
    g = Geografia(conf.paises)
    a = {"titulo": "[PRUEBA] Fighting reported in Sudan", "paises_mencionados": []}
    lugar = ubicar_articulo(a, None, {"SDN"}, g)
    assert lugar["precision"] == "pais" and lugar["coord"] is None
    b = {"titulo": "[PRUEBA] Drone strike hits Kharkiv", "paises_mencionados": []}
    lugar_b = ubicar_articulo(b, None, {"UKR", "RUS"}, g)
    assert lugar_b["precision"] in ("ciudad", "provincia") and lugar_b["coord"]


def test_copias_de_cable_cuentan_una_vez(conf):
    c = conf.conflicto("sudan")
    t = titulo_normalizado_para_copias("[PRUEBA] Sudan army retakes town - Reuters")
    arts = [
        {"k": "1", "origen": "agencia:Reuters", "titulo_copia": t, "pub": "2026-10-13T10:00:00+00:00"},
        {"k": "2", "origen": "medio:Diario A", "titulo_copia": t, "pub": "2026-10-13T10:05:00+00:00"},
        {"k": "3", "origen": "medio:Diario B", "titulo_copia": t, "pub": "2026-10-13T10:06:00+00:00"},
    ]
    r = estado_corroboracion({}, arts, c)
    assert r["fuentes_independientes"] == 1 and r["estado"] == "preliminar"


def test_declaracion_de_parte_no_corrobora(conf):
    c = conf.conflicto("ucrania-rusia")
    arts = [{"k": "1", "origen": "medio:kremlin.ru", "fuente_estatal_de": "RUS", "fuente_estatal_tipo": "oficial",
             "titulo_copia": "a", "pub": "2026-10-13T10:00:00+00:00"},
            {"k": "2", "origen": "medio:TASS", "fuente_estatal_de": "RUS", "fuente_estatal_tipo": "estatal",
             "titulo_copia": "b", "pub": "2026-10-13T10:01:00+00:00"}]
    r = estado_corroboracion({}, arts, c)
    assert r["estado"] == "declaracion_parte" and r["fuentes_independientes"] == 0
    arts.append({"k": "3", "origen": "medio:Kyiv Independent", "fuente_estatal_de": "UKR",
                 "fuente_estatal_tipo": "oficial", "titulo_copia": "c", "pub": "2026-10-13T10:02:00+00:00"})
    assert estado_corroboracion({}, arts, c)["contrapuestas"]


def test_varias_fuentes_independientes(conf):
    c = conf.conflicto("sudan")
    arts = [{"k": str(i), "origen": f"medio:M{i}", "titulo_copia": f"t{i}", "pub": "2026-10-13T10:00:00+00:00"}
            for i in range(3)]
    r = estado_corroboracion({}, arts, c)
    assert r["estado"] == "varias_fuentes" and r["fuentes_independientes"] == 3


def test_clave_derivada_del_token_es_estable_y_valida():
    from colector.cifrado import cifrar, derivar_clave, descifrar
    k1, k2 = derivar_clave("123:abc"), derivar_clave("123:abc")
    assert k1 == k2 and k1 != derivar_clave("123:otro")
    assert descifrar(cifrar({"x": 1}, k1), k2) == {"x": 1}


def test_tokenizador_bpe_ida_y_vuelta(tmp_path):
    from colector.traduccion import _TokenizadorBPE
    codigos = tmp_path / "bpe.model"
    codigos.write_text("#version: 0.2\nh e\nhe l\nl o</w>\n", encoding="utf-8")
    t = _TokenizadorBPE(str(codigos), "en", "es")
    piezas = t.codificar("hello, world")
    assert "@@" in " ".join(piezas)
    assert t.decodificar(piezas) == "hello, world"
