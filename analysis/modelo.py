"""Pronóstico a un mes del hurto de automotores y motocicletas por municipio.

Consume la tabla features_motos de la base SQLite que deja el pipeline, de
modo que demuestra que el producto de la carga sirve para modelar.

Diseño (Entregas 1 y 2):
  universo   275 municipios con >= 1 hecho mensual promedio en 2018-2024
  partición  entrenamiento 2012-01 a 2024-12; prueba 2025-01 a 2026-07
  líneas base estacional ingenua (mismo mes del año anterior, lag_12) y
             persistencia (mes anterior, lag_1)
  modelo     árboles con potenciación (HistGradientBoosting, pérdida Poisson)

Escribe docs/resultados_modelo.json, docs/figs/fig6_pronostico.png y la
tabla predicciones_motos en la base.

Uso:
    python analysis/modelo.py
"""
import argparse
import json
import pathlib
import sqlite3

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

VARIABLES = [f"lag_{L}" for L in range(1, 13)] + [
    "media_movil_3", "media_movil_12", "mes_del_anio", "dias_mes", "festivos",
    "log_poblacion", "flag_pandemia"]


def metricas(y, p):
    e = p - y
    return {"MAE": round(float(np.abs(e).mean()), 2),
            "RMSE": round(float(np.sqrt((e ** 2).mean())), 2),
            "WAPE_%": round(float(np.abs(e).sum() / y.sum() * 100), 1),
            "sesgo_%": round(float(e.sum() / y.sum() * 100), 1)}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="data/delitos.db")
    ap.add_argument("--salida", default="docs")
    a = ap.parse_args(argv)
    salida = pathlib.Path(a.salida)
    (salida / "figs").mkdir(parents=True, exist_ok=True)

    con = sqlite3.connect(a.base)
    f = pd.read_sql("SELECT * FROM features_motos WHERE universo_denso = 1", con, dtype={"cod_mpio": str})
    f["log_poblacion"] = np.log1p(f["poblacion"])
    ent, pru = f[f["particion"] == "entrenamiento"], f[f["particion"] == "prueba"].copy()

    modelo = HistGradientBoostingRegressor(loss="poisson", max_iter=400, learning_rate=0.05,
                                           max_leaf_nodes=31, min_samples_leaf=40, random_state=42)
    modelo.fit(ent[VARIABLES], ent["y"])
    pru["pred_modelo"] = modelo.predict(pru[VARIABLES])
    pru["pred_estacional"] = pru["lag_12"]
    pru["pred_persistencia"] = pru["lag_1"]

    res = {"municipios": int(f["cod_mpio"].nunique()),
           "filas_entrenamiento": len(ent), "filas_prueba": len(pru),
           "meses_prueba": f"{pru['mes'].min()} a {pru['mes'].max()}",
           "hechos_prueba": int(pru["y"].sum())}
    sin_dic = pru["flag_dic_atipico"] == 0
    for nombre, col in [("estacional", "pred_estacional"), ("persistencia", "pred_persistencia"),
                        ("modelo", "pred_modelo")]:
        res[nombre] = metricas(pru["y"].values, pru[col].values)
        res[nombre + "_sin_dic_2025"] = metricas(pru.loc[sin_dic, "y"].values, pru.loc[sin_dic, col].values)
    (salida / "resultados_modelo.json").write_text(json.dumps(res, ensure_ascii=False, indent=2))

    pru[["cod_mpio", "mes", "y", "pred_estacional", "pred_persistencia", "pred_modelo"]] \
        .to_sql("predicciones_motos", con, index=False, if_exists="replace")
    con.commit()
    con.close()

    t = pru.groupby("mes")[["y", "pred_estacional", "pred_persistencia", "pred_modelo"]].sum()
    fig, ax = plt.subplots(figsize=(10, 3.4))
    x = pd.PeriodIndex(t.index, freq="M").to_timestamp()
    ax.plot(x, t["y"], color="k", lw=2, label="Observado")
    ax.plot(x, t["pred_estacional"], ls=":", label="Línea base estacional")
    ax.plot(x, t["pred_persistencia"], ls="--", label="Línea base de persistencia")
    ax.plot(x, t["pred_modelo"], label="Modelo (HistGradientBoosting)")
    ax.set_title(f"Hurto de automotores y motos, {res['municipios']} municipios: total mensual en el periodo de prueba")
    ax.legend(fontsize=8, frameon=False)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(salida / "figs" / "fig6_pronostico.png", dpi=160)
    print(json.dumps(res, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
