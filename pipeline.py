"""Orquesta el pipeline completo: extract -> transform -> load.

Uso:
    python pipeline.py                 # descarga todo de nuevo y reconstruye
    python pipeline.py --sin-descarga  # reutiliza data/raw (mismo corte)
"""
import argparse
import sys
import time

sys.path[:0] = ["extract", "transform", "load"]
import cargar_sqlite      # noqa: E402
import descargar_poblacion  # noqa: E402
import extraer_siedco     # noqa: E402
import transformar        # noqa: E402


def etapa(nombre, funcion):
    t = time.time()
    print(f"\n=== {nombre} ===", flush=True)
    funcion([])
    print(f"--- {nombre}: {time.time() - t:.0f} s", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sin-descarga", action="store_true")
    a = ap.parse_args()
    if not a.sin_descarga:
        etapa("Extract: API Socrata (Policía Nacional, DIVIPOLA)", extraer_siedco.main)
        etapa("Extract: proyecciones de población DANE", descargar_poblacion.main)
    etapa("Transform", transformar.main)
    etapa("Load: SQLite", cargar_sqlite.main)


if __name__ == "__main__":
    main()
