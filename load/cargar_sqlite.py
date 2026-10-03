"""Carga: de data/processed a una base SQLite (data/delitos.db).

Modo de carga: reemplazo completo en cada corrida. Cada corte de la fuente
se reconstruye entero y el manifiesto de extracción queda en la tabla
manifiesto, de modo que la base siempre corresponde a un corte identificable.

La tabla de hechos a nivel de registro (hechos_unificados, 1,8 millones de
filas) no se carga: queda en data/processed como .csv.gz. La base guarda el
panel agregado, que es lo que consume el análisis.

Uso:
    python load/cargar_sqlite.py
"""
import argparse
import json
import pathlib
import sqlite3

import pandas as pd

TABLAS = {
    "dim_municipio": ("dim_municipio.csv", ["cod_mpio"]),
    "poblacion_anual": ("poblacion_anual.csv", ["cod_mpio", "anio"]),
    "delitos_municipio_mes": ("delitos_municipio_mes.csv.gz", ["cod_mpio", "mes"]),
    "features_motos": ("features_motos.csv.gz", ["cod_mpio", "mes"]),
    "validaciones": ("validaciones.csv", None),
}
TEXTO = {"cod_mpio": str, "cod_dpto": str, "mes": str}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--processed", default="data/processed")
    ap.add_argument("--raw", default="data/raw")
    ap.add_argument("--destino", default="data/delitos.db")
    a = ap.parse_args(argv)
    proc, destino = pathlib.Path(a.processed), pathlib.Path(a.destino)
    if destino.exists():
        destino.unlink()
    con = sqlite3.connect(destino)
    for tabla, (archivo, llave) in TABLAS.items():
        df = pd.read_csv(proc / archivo, dtype=TEXTO)
        df.to_sql(tabla, con, index=False)
        if llave:
            con.execute(f"CREATE UNIQUE INDEX ix_{tabla} ON {tabla} ({', '.join(llave)})")
        n = con.execute(f"SELECT COUNT(*) FROM {tabla}").fetchone()[0]
        estado = "ok" if n == len(df) else "DIFERENCIA"
        print(f"{tabla:24} archivo {len(df):>9,}  base {n:>9,}  {estado}")
    con.execute("""
        CREATE VIEW v_tasas_100k AS
        SELECT d.cod_mpio, d.mes, p.poblacion,
               d.hechos_motos    * 1e5 / NULLIF(p.poblacion, 0) AS tasa_motos,
               d.hechos_abigeato * 1e5 / NULLIF(p.poblacion, 0) AS tasa_abigeato,
               d.hechos_sexuales * 1e5 / NULLIF(p.poblacion, 0) AS tasa_sexuales,
               d.hechos_vif      * 1e5 / NULLIF(p.poblacion, 0) AS tasa_vif
        FROM delitos_municipio_mes d
        LEFT JOIN poblacion_anual p
               ON p.cod_mpio = d.cod_mpio AND p.anio = CAST(substr(d.mes, 1, 4) AS INTEGER)""")
    filas = []
    for nombre in ["manifiesto_socrata.json", "manifiesto_dane.json"]:
        for alias, m in json.loads((pathlib.Path(a.raw) / nombre).read_text()).items():
            filas.append({"alias": alias, "fuente": nombre.split("_")[1].split(".")[0],
                          "detalle": json.dumps({k: v for k, v in m.items() if k != "columnas"}, ensure_ascii=False)})
    pd.DataFrame(filas).to_sql("manifiesto", con, index=False)
    con.commit()
    con.execute("VACUUM")
    con.close()
    print(f"Base: {destino} ({destino.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
