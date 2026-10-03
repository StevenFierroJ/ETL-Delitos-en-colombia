"""EDA y análisis de calidad sobre los extractos crudos.

Lee lo que dejaron extraer_siedco.py y descargar_poblacion.py, no modifica
data/raw y escribe:
    docs/metricas_eda.json   cifras del EDA (Entrega 2)
    docs/figs/fig*.png       figuras

Uso:
    python analysis/eda.py
"""
import argparse
import difflib
import json
import pathlib
import re
import unicodedata

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

CONJ = {
    "motos": ("motos_9vha-vh9n.csv.gz", "Hurto automotores y motos"),
    "abigeato": ("abigeato_d4fr-sbn2.csv.gz", "Abigeato, piratería, ent. fin."),
    "sexuales": ("sexuales_fpe5-yrmw.csv.gz", "Delitos sexuales"),
    "vif": ("vif_vuyt-mqpw.csv.gz", "Violencia intrafamiliar"),
}
COLORES = {"motos": "#1f4e79", "abigeato": "#7f7f7f", "sexuales": "#c55a11", "vif": "#548235"}
FAMILIA_ARMA_BLANCA = ["ARMA BLANCA / CORTOPUNZANTE", "CORTANTES", "CORTOPUNZANTES", "PUNZANTES", "ARMAS BLANCAS"]


def norm(s):
    s = re.sub(r"\(CT\)", "", str(s))
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().upper()
    return " ".join(re.sub(r"[^A-Z ]", " ", s).split())


def cargar(raw):
    datos = {}
    for k, (f, _) in CONJ.items():
        d = pd.read_csv(raw / f, dtype=str, keep_default_na=False)
        d["n"] = d["cantidad"].astype(int)
        d["fecha"] = pd.to_datetime(d["fecha_hecho"], format="%d/%m/%Y", errors="coerce")
        d["mes"] = d["fecha"].dt.to_period("M")
        d["c5"] = d["codigo_dane"].str[:5]
        datos[k] = d
    dv = pd.read_csv(raw / "divipola_gdxc-w37w.csv.gz", dtype=str)
    p1 = pd.read_excel(raw / "DCD-area-proypoblacion-Mun-2005-2017_VP.xlsx", header=11, dtype={"MPIO": str})
    p2 = pd.read_excel(raw / "PPED-AreaMun-2018-2042_VP.xlsx", sheet_name="PobMunicipalxÁrea",
                       header=7, dtype={"MPIO": str}).dropna(subset=["MPIO"])
    p1 = p1[p1["ÁREA GEOGRÁFICA"] == "Total"].rename(columns={"Población": "pob"})[["MPIO", "AÑO", "pob"]]
    p2 = p2[p2["ÁREA GEOGRÁFICA"] == "Total"].rename(columns={"TOTAL": "pob"})[["MPIO", "AÑO", "pob"]]
    p1["AÑO"], p2["AÑO"] = p1["AÑO"].astype(int), p2["AÑO"].astype(int)
    return datos, dv, p1, p2


def perfil(datos):
    m = {}
    for k, d in datos.items():
        anual = d.groupby(d["fecha"].dt.year)["n"].sum()
        m[k] = {
            "filas": len(d),
            "eventos": int(d["n"].sum()),
            "cantidad_max": int(d["n"].max()),
            "fechas_no_parseables": int(d["fecha"].isna().sum()),
            "fecha_min": str(d["fecha"].min().date()),
            "fecha_max": str(d["fecha"].max().date()),
            "duplicados_exactos": int(d.drop(columns=["n", "fecha", "mes", "c5"]).duplicated().sum()),
            "pct_no_reportado_arma": round(100 * (d["armas_medios"] == "NO REPORTADO").mean(), 2),
            "pct_genero_vacio": round(100 * (d["genero"] == "").mean(), 2),
            "pct_genero_no_reporta": round(100 * (d["genero"] == "NO REPORTA").mean(), 2),
            "pct_etario_vacio": round(100 * (d["grupo_etario"] == "").mean(), 2),
            "etiquetas_arma": int(d["armas_medios"].nunique()),
            "etiquetas_familia_arma_blanca": int(d["armas_medios"].isin(FAMILIA_ARMA_BLANCA[1:]).sum()),
            "pct_dia_1": round(100 * (d["fecha"].dt.day == 1).mean(), 2),
            "pct_codigo_centro_poblado": round(100 * (d["codigo_dane"].str[5:] != "000").mean(), 2),
            "codigos8_distintos": int(d["codigo_dane"].nunique()),
            "anual": {int(a): int(v) for a, v in anual.items()},
        }
    return m


def cruce_territorial(datos, dv):
    dvn = dv.assign(n_=dv["nom_mpio"].map(norm)).set_index("cod_mpio")
    todo = pd.concat([d[["departamento", "municipio", "c5", "n"]] for d in datos.values()])
    u = todo.groupby(["departamento", "municipio", "c5"])["n"].agg(["size"]).reset_index()
    u = u.join(dvn[["n_", "dpto", "tipo_municipio"]], on="c5")

    def estado(r):
        if pd.isna(r["n_"]):
            return "codigo_inexistente"
        a, b = set(norm(r["municipio"]).split()), set(r["n_"].split())
        if a and (a <= b or b <= a):
            return "ok"
        if r["tipo_municipio"] == "Área no municipalizada":
            return "anm_con_nombre_de_capital"
        # Grafía distinta si la mayor subcadena común cubre >= 80 % del nombre
        # de origen (Mompós / Santa Cruz de Mompox, Tolú Viejo / Toluviejo).
        x, y = norm(r["municipio"]).replace(" ", ""), r["n_"].replace(" ", "")
        comun = difflib.SequenceMatcher(None, x, y).find_longest_match(0, len(x), 0, len(y)).size
        return "grafia_distinta" if comun / max(len(x), 1) >= 0.8 else "codigo_de_otro_municipio"

    u["estado"] = u.apply(estado, axis=1)
    res = u.groupby("estado")["size"].agg(["count", "sum"])
    return {e: {"combinaciones": int(r["count"]), "filas": int(r["sum"])} for e, r in res.iterrows()}, u


def poblacion(p1, p2, dv):
    a = p1[p1["AÑO"] == 2017].set_index("MPIO")["pob"]
    b = p2[p2["AÑO"] == 2018].set_index("MPIO")["pob"]
    r = (b / a).dropna()
    ceros = p2[p2["pob"] == 0].groupby("MPIO")["AÑO"].agg(["min", "max"])
    return {
        "municipios_2005_2017": int(p1["MPIO"].nunique()),
        "municipios_2018_2042": int(p2["MPIO"].nunique()),
        "municipios_divipola": int(dv["cod_mpio"].nunique()),
        "solo_en_2018_2042_vs_2005_2017": sorted(set(p2["MPIO"]) - set(p1["MPIO"])),
        "solo_en_2018_2042_vs_divipola": sorted(set(p2["MPIO"]) - set(dv["cod_mpio"])),
        "empalme_2017_2018_mediana": round(float(r.median()), 3),
        "empalme_2017_2018_p5_p95": [round(float(r.quantile(.05)), 3), round(float(r.quantile(.95)), 3)],
        "empalme_cambio_mayor_10pct": int((abs(r - 1) > 0.10).sum()),
        "poblacion_cero": {k: [int(v["min"]), int(v["max"])] for k, v in ceros.iterrows()},
        "municipios_menos_10k_2024": int((p2[p2["AÑO"] == 2024]["pob"] < 10000).sum()),
    }


def panel(d, desde="2018-01", hasta="2025-12", universo=None):
    """Panel municipio-mes completo: las combinaciones sin registro se llenan con 0."""
    x = d[(d["mes"] >= desde) & (d["mes"] <= hasta)].groupby(["c5", "mes"])["n"].sum()
    meses = pd.period_range(desde, hasta, freq="M")
    idx = pd.MultiIndex.from_product([universo, meses], names=["c5", "mes"])
    return x.reindex(idx, fill_value=0)


def figuras(datos, m, u, p2, dv, salida):
    figs = salida / "figs"
    figs.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update({"font.size": 9, "axes.spines.top": False, "axes.spines.right": False})
    extra = {}

    # Fig 1: series anuales (2010-2025) y mensual nacional de motos
    fig, ax = plt.subplots(1, 2, figsize=(10, 3.4))
    for k in CONJ:
        s = pd.Series(m[k]["anual"]).loc[2010:2025]
        ax[0].plot(s.index, s / s.loc[2018] * 100, marker="o", ms=3, color=COLORES[k], label=CONJ[k][1])
    ax[0].axhline(100, color="k", lw=.5, ls=":")
    ax[0].set_title("Eventos anuales, índice 2018 = 100")
    ax[0].legend(fontsize=7, frameon=False)
    mm = datos["motos"].groupby("mes")["n"].sum()
    mm = mm[mm.index <= "2026-07"]
    ax[1].plot(mm.index.to_timestamp(), mm.values, color=COLORES["motos"], lw=1)
    ax[1].axvspan(pd.Timestamp("2020-03-20"), pd.Timestamp("2020-08-31"), color="grey", alpha=.25)
    ax[1].set_title("Hurto de automotores y motos: eventos por mes (nacional)")
    fig.tight_layout()
    fig.savefig(figs / "fig1_series.png", dpi=180)
    plt.close(fig)

    # Fig 2: faltantes codificados y día del mes
    fig, ax = plt.subplots(1, 2, figsize=(10, 3.2))
    cols = ["pct_no_reportado_arma", "pct_genero_vacio", "pct_etario_vacio"]
    et = ["Arma/medio\n«NO REPORTADO»", "Género vacío", "Grupo etario\nvacío"]
    mat = np.array([[m[k][c] for c in cols] for k in CONJ])
    im = ax[0].imshow(mat, cmap="Oranges", aspect="auto")
    ax[0].set_xticks(range(3), et)
    ax[0].set_yticks(range(4), [CONJ[k][1] for k in CONJ])
    for i in range(4):
        for j in range(3):
            ax[0].text(j, i, f"{mat[i, j]:.1f}%", ha="center", va="center", fontsize=8,
                           color="white" if mat[i, j] > 12 else "black")
    ax[0].set_title("Faltantes por conjunto (% de filas)")
    for k in ["sexuales", "motos"]:
        dd = datos[k]["fecha"].dt.day.value_counts(normalize=True).sort_index() * 100
        ax[1].plot(dd.index, dd.values, marker="o", ms=3, color=COLORES[k], label=CONJ[k][1])
    ax[1].axhline(100 / 30.4, color="k", lw=.5, ls=":")
    ax[1].set_title("Distribución por día del mes (% de filas)")
    ax[1].set_xlabel("Día")
    ax[1].legend(fontsize=7, frameon=False)
    fig.tight_layout()
    fig.savefig(figs / "fig2_faltantes_dia.png", dpi=180)
    plt.close(fig)

    # Fig 3: concentración territorial y distribución de conteos municipio-mes
    universo = sorted(dv["cod_mpio"])
    fig, ax = plt.subplots(1, 2, figsize=(10, 3.2))
    for k in CONJ:
        t = datos[k].groupby("c5")["n"].sum().reindex(universo, fill_value=0).sort_values(ascending=False)
        c = t.cumsum() / t.sum() * 100
        ax[0].plot(np.arange(1, len(c) + 1), c.values, color=COLORES[k], label=CONJ[k][1])
        extra.setdefault("municipios_80pct", {})[k] = int((c < 80).sum() + 1)
        extra.setdefault("top5_pct", {})[k] = round(float(t.head(5).sum() / t.sum() * 100), 1)
    ax[0].set_xscale("log")
    ax[0].set_xlabel("Municipios ordenados por volumen (escala log)")
    ax[0].set_ylabel("% acumulado de eventos")
    ax[0].set_title("Concentración territorial 2010-2026")
    ax[0].legend(fontsize=7, frameon=False)
    pm = panel(datos["motos"], universo=universo)
    extra["panel_motos"] = {
        "celdas": int(len(pm)),
        "pct_ceros": round(float((pm == 0).mean() * 100), 1),
        "media": round(float(pm.mean()), 2),
        "varianza": round(float(pm.var()), 1),
        "p99": float(pm.quantile(.99)),
        "max": int(pm.max()),
    }
    vals = pm.values
    bins = [0, 1, 2, 3, 5, 10, 20, 50, 100, 200, 500, 1000, 2000]
    h, _ = np.histogram(vals, bins=bins)
    ax[1].bar(range(len(h)), h / len(vals) * 100, color=COLORES["motos"])
    ax[1].set_yscale("log")
    ax[1].set_ylabel("% de celdas (escala log)")
    ax[1].set_xticks(range(len(h)), ["0", "1", "2", "3-4", "5-9", "10-19", "20-49", "50-99",
                                     "100-199", "200-499", "500-999", "1000+"], rotation=45, fontsize=7)
    ax[1].set_title("Hurto de automotores y motos: eventos por municipio-mes\n(panel completo 2018-2025, % de celdas)")
    fig.tight_layout()
    fig.savefig(figs / "fig3_concentracion.png", dpi=180)
    plt.close(fig)

    # Fig 4: tasa por 100.000 frente a población (2024)
    pob = p2[p2["AÑO"] == 2024].set_index("MPIO")["pob"]
    ev = datos["motos"][datos["motos"]["fecha"].dt.year == 2024].groupby("c5")["n"].sum()
    t = pd.DataFrame({"pob": pob, "ev": ev}).fillna({"ev": 0})
    t = t[t["pob"] > 0]
    t["tasa"] = t["ev"] / t["pob"] * 1e5
    fig, ax = plt.subplots(figsize=(10, 3.2))
    ax.scatter(t["pob"], t["tasa"], s=6, alpha=.5, color=COLORES["motos"])
    xs = np.logspace(np.log10(t["pob"].min()), 7, 200)
    ax.plot(xs, 1e5 / xs, color="k", lw=.7, ls="--", label="Tasa que produce un solo evento")
    ax.set_ylim(-15, 560)
    ax.legend(fontsize=7, frameon=False)
    ax.set_xscale("log")
    ax.set_xlabel("Población 2024 (escala log)")
    ax.set_ylabel("Tasa por 100.000 hab.")
    ax.set_title("Hurto de automotores y motos 2024: tasa municipal frente a población")
    fig.tight_layout()
    fig.savefig(figs / "fig4_tasas.png", dpi=180)
    plt.close(fig)
    peq = t[t["pob"] < 10000]
    extra["tasas_2024_motos"] = {
        "mediana": round(float(t["tasa"].median()), 1),
        "p99": round(float(t["tasa"].quantile(.99)), 1),
        "max": round(float(t["tasa"].max()), 1),
        "max_municipio": t["tasa"].idxmax(),
        "max_municipio_pob": int(t.loc[t["tasa"].idxmax(), "pob"]),
        "max_municipio_eventos": int(t.loc[t["tasa"].idxmax(), "ev"]),
        "pct_ceros_menos_10k": round(float((peq["ev"] == 0).mean() * 100), 1),
    }

    # Fig 5: estacionalidad y dependencia temporal (motos)
    mm = datos["motos"].groupby("mes")["n"].sum()
    mm = mm[(mm.index >= "2011-01") & (mm.index <= "2025-12") & (mm.index.year != 2020)]
    rel = mm / mm.groupby(mm.index.year).transform("mean")
    perf = rel.groupby(rel.index.month).mean() * 100
    fig, ax = plt.subplots(1, 2, figsize=(10, 3.2))
    ax[0].bar(perf.index, perf.values, color=COLORES["motos"])
    ax[0].axhline(100, color="k", lw=.5, ls=":")
    ax[0].set_ylim(85, 110)
    ax[0].set_xticks(range(1, 13))
    ax[0].set_title("Perfil mensual (media del año = 100), 2011-2025 sin 2020")
    pmu = pm.unstack("mes")
    grandes = pmu[pmu.sum(axis=1) >= 8 * 12]  # al menos 1 evento/mes en promedio
    lags = range(1, 13)
    # Correlación dentro de municipio: se resta la media de cada municipio para
    # que el nivel (Bogotá siempre alto) no infle la dependencia temporal.
    z = np.log1p(grandes)
    z = z.sub(z.mean(axis=1), axis=0)
    corr = []
    for L in lags:
        a = z.iloc[:, L:].values.ravel()
        b = z.iloc[:, :-L].values.ravel()
        corr.append(np.corrcoef(a, b)[0, 1])
    ax[1].bar(list(lags), corr, color=COLORES["motos"])
    ax[1].set_ylim(0, max(corr) * 1.15)
    ax[1].set_xticks(list(lags))
    ax[1].set_title(f"Correlación con el rezago, dentro de municipio\n({len(grandes)} municipios con >= 1 evento/mes en promedio)")
    ax[1].set_xlabel("Rezago (meses)")
    fig.tight_layout()
    fig.savefig(figs / "fig5_estacionalidad.png", dpi=180)
    plt.close(fig)
    extra["estacionalidad_motos"] = {int(k): round(float(v), 1) for k, v in perf.items()}
    extra["autocorrelacion_motos"] = {"municipios": int(len(grandes)),
                                      **{f"lag{L}": round(float(c), 3) for L, c in zip(lags, corr)}}

    # Caída de 2020 y saltos de nivel
    extra["abril_2020_vs_2019_pct"] = {
        k: round(float(datos[k].groupby("mes")["n"].sum()[pd.Period("2020-04")] /
                       datos[k].groupby("mes")["n"].sum()[pd.Period("2019-04")] * 100 - 100), 1)
        for k in CONJ}
    return extra


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default="data/raw")
    ap.add_argument("--salida", default="docs")
    a = ap.parse_args()
    raw, salida = pathlib.Path(a.raw), pathlib.Path(a.salida)
    salida.mkdir(parents=True, exist_ok=True)
    datos, dv, p1, p2 = cargar(raw)
    met = {"perfil": perfil(datos)}
    met["territorial"], u = cruce_territorial(datos, dv)
    u.to_csv(salida / "cruce_territorial.csv", index=False)
    met["poblacion"] = poblacion(p1, p2, dv)
    met["figuras"] = figuras(datos, met["perfil"], u, p2, dv, salida)
    met["manifiestos"] = {
        "socrata": json.loads((raw / "manifiesto_socrata.json").read_text()),
        "dane": json.loads((raw / "manifiesto_dane.json").read_text()),
    }
    (salida / "metricas_eda.json").write_text(json.dumps(met, ensure_ascii=False, indent=2, default=str))
    print(json.dumps({k: v for k, v in met.items() if k != "manifiestos"}, ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    main()
