"""Punto de entrada: python -m colector ciclo --estado estado --salida web/datos"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys


def main() -> int:
    ap = argparse.ArgumentParser(prog="colector")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("ciclo", help="ejecuta un ciclo de recopilación y publicación")
    c.add_argument("--estado", default="estado")
    c.add_argument("--salida", default="web/datos")
    c.add_argument("--modelos", default=os.environ.get("DIR_MODELOS", os.path.expanduser("~/.cache/argos-modelos")))
    c.add_argument("--url-sitio", default=os.environ.get("URL_SITIO", ""))
    c.add_argument("--sin-red", action="store_true", help="no consulta fuentes (prueba local)")
    sub.add_parser("clave", help="genera una clave para ESTADO_CLAVE")
    v = sub.add_parser("validar", help="valida la configuración")
    v.add_argument("--url-sitio", default="")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    # Los registros de Actions son públicos: urllib3 puede incluir rutas de URL en sus avisos
    # de reintento, así que se silencian (las URLs de Telegram contienen el token).
    logging.getLogger("urllib3").setLevel(logging.ERROR)

    if args.cmd == "clave":
        from .cifrado import nueva_clave
        print(nueva_clave())
        return 0
    if args.cmd == "validar":
        from . import config
        conf = config.cargar(args.url_sitio)
        print(f"{len(conf.conflictos)} conflictos, {len(conf.fuentes['rss'])} fuentes RSS: configuración válida")
        return 0

    from .ciclo import Ciclo
    ciclo = Ciclo(args.estado, args.salida, args.modelos, args.url_sitio,
                  persistir_cmd=os.environ.get("PERSISTIR_CMD"), sin_red=args.sin_red)
    info = ciclo.ejecutar()
    resumen = {k: info.get(k) for k in ("ciclo_ok", "articulos_nuevos", "articulos_asignados", "eventos_72h",
                                         "duracion_s", "publicado", "resumen_fuentes")}
    resumen["gdelt"] = {k: (info.get("gdelt") or {}).get(k) for k in ("ultimo_archivo", "archivos_ok", "archivos_faltantes")}
    resumen["traduccion"] = {k: (info.get("traduccion") or {}).get(k)
                             for k in ("traducidos", "desde_cache", "fallidos", "sin_modelo")}
    resumen["telegram"] = {k: (info.get("telegram") or {}).get(k)
                           for k in ("configurado", "vinculado", "enviados_ciclo", "pausado")}
    resumen["advertencias"] = info.get("advertencias")
    resumen["errores"] = info.get("errores")
    # Este resumen se imprime en el registro público de Actions: no contiene datos privados.
    print(json.dumps(resumen, ensure_ascii=False, indent=1))
    return 0 if info.get("publicado") else 1


if __name__ == "__main__":
    sys.exit(main())
