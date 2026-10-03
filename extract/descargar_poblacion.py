"""Descarga de las proyecciones de población municipal del DANE.

El DANE no publica estas series por API: se descargan los XLSX del sitio
oficial. La serie delictiva empieza en 2010, así que se necesitan dos
archivos con formatos distintos: 2005-2017 (retroproyección) y 2018-2042
(actualización post-COVID, julio de 2025). El manifiesto guarda URL, tamaño,
md5 y fecha de descarga de cada uno.

Uso:
    python extract/descargar_poblacion.py
"""
import argparse
import datetime as dt
import hashlib
import json
import pathlib

import requests

BASE = "https://www.dane.gov.co/files/censo2018/proyecciones-de-poblacion/Municipal"
ARCHIVOS = {
    "pob_2005_2017": "DCD-area-proypoblacion-Mun-2005-2017_VP.xlsx",
    "pob_2018_2042": "PPED-AreaMun-2018-2042_VP.xlsx",
}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--salida", default="data/raw")
    a = ap.parse_args(argv)
    salida = pathlib.Path(a.salida)
    salida.mkdir(parents=True, exist_ok=True)
    registro = {}
    for alias, nombre in ARCHIVOS.items():
        url = f"{BASE}/{nombre}"
        r = requests.get(url, timeout=300, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        (salida / nombre).write_bytes(r.content)
        registro[alias] = {
            "url": url,
            "archivo": nombre,
            "bytes": len(r.content),
            "md5": hashlib.md5(r.content).hexdigest(),
            "descargado_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        }
        print(f"{alias}: {len(r.content):,} bytes")
    (salida / "manifiesto_dane.json").write_text(json.dumps(registro, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
