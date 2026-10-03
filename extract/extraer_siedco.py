"""Extracción parametrizada desde la API Socrata de datos.gov.co.

Descarga, sin transformar, los conjuntos delictivos de la Policía Nacional
(SIEDCO) y la tabla DIVIPOLA. Cada corrida deja un CSV crudo por conjunto y
un manifiesto con el conteo que reporta la API, las filas descargadas, el md5
y la fecha de la última actualización del conjunto, para trazar el origen.

Uso:
    python extract/extraer_siedco.py                  # los cinco conjuntos
    python extract/extraer_siedco.py --conjuntos motos vif
"""
import argparse
import csv
import gzip
import datetime as dt
import hashlib
import io
import json
import pathlib
import time

import requests

BASE = "https://www.datos.gov.co"

# Identificadores verificados en el catálogo de datos.gov.co.
# Tres conjuntos distintos se publican con el nombre idéntico
# «Reporte Hurto por Modalidades Policía Nacional»: 9vha-vh9n, 6sqw-8cg5 y
# d4fr-sbn2. Por eso se referencian por identificador y no por nombre.
CONJUNTOS = {
    "motos": {"id": "9vha-vh9n", "desc": "Hurto de automotores y motocicletas"},
    "abigeato": {"id": "d4fr-sbn2", "desc": "Hurto abigeato, piratería terrestre y entidades financieras"},
    "sexuales": {"id": "fpe5-yrmw", "desc": "Delitos sexuales"},
    "vif": {"id": "vuyt-mqpw", "desc": "Violencia intrafamiliar"},
    "divipola": {"id": "gdxc-w37w", "desc": "DIVIPOLA - códigos de municipios (DANE)"},
}


def _get(url, params, intentos=5):
    for i in range(intentos):
        try:
            r = requests.get(url, params=params, timeout=180)
            r.raise_for_status()
            return r
        except requests.RequestException:
            if i == intentos - 1:
                raise
            time.sleep(5 * (i + 1))


def conteo_api(ident):
    r = _get(f"{BASE}/resource/{ident}.json", {"$select": "count(*)"})
    return int(r.json()[0]["count"])


def metadatos(ident):
    d = _get(f"{BASE}/api/views/{ident}.json", {}).json()
    upd = d.get("rowsUpdatedAt")
    return {
        "nombre": d.get("name"),
        "publicador": d.get("attribution"),
        "actualizado": dt.datetime.fromtimestamp(upd, dt.timezone.utc).isoformat() if upd else None,
        "columnas": {c["fieldName"]: c["dataTypeName"] for c in d.get("columns", [])},
    }


def extraer(alias, salida, pagina):
    ident = CONJUNTOS[alias]["id"]
    meta = metadatos(ident)
    esperado = conteo_api(ident)
    destino = salida / f"{alias}_{ident}.csv.gz"
    md5 = hashlib.md5()
    filas, offset, encabezado = 0, 0, None
    with gzip.open(destino, "wt", newline="", encoding="utf-8") as f:
        escritor = csv.writer(f)
        while True:
            r = _get(
                f"{BASE}/resource/{ident}.csv",
                {"$limit": pagina, "$offset": offset, "$order": ":id"},
            )
            lector = csv.reader(io.StringIO(r.content.decode("utf-8")))
            cab = next(lector)
            if encabezado is None:
                encabezado = cab
                escritor.writerow(cab)
                md5.update((",".join(cab) + "\n").encode())
            n = 0
            for fila in lector:
                escritor.writerow(fila)
                md5.update((",".join(fila) + "\n").encode())
                n += 1
            filas += n
            offset += pagina
            print(f"  {alias}: {filas:,} / {esperado:,}", flush=True)
            if n < pagina:
                break
    return {
        "alias": alias,
        "id": ident,
        "descripcion": CONJUNTOS[alias]["desc"],
        "url": f"{BASE}/resource/{ident}",
        "archivo": destino.name,
        "filas_api": esperado,
        "filas_descargadas": filas,
        "coinciden": filas == esperado,
        "md5_contenido": md5.hexdigest(),
        "extraido_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        **meta,
    }


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--conjuntos", nargs="+", default=list(CONJUNTOS), choices=list(CONJUNTOS))
    ap.add_argument("--salida", default="data/raw")
    ap.add_argument("--pagina", type=int, default=50000)
    a = ap.parse_args(argv)
    salida = pathlib.Path(a.salida)
    salida.mkdir(parents=True, exist_ok=True)
    manifiesto = salida / "manifiesto_socrata.json"
    registro = json.loads(manifiesto.read_text()) if manifiesto.exists() else {}
    for alias in a.conjuntos:
        registro[alias] = extraer(alias, salida, a.pagina)
        manifiesto.write_text(json.dumps(registro, ensure_ascii=False, indent=2))
    print(f"Manifiesto: {manifiesto}")


if __name__ == "__main__":
    main()
