"""Transformación: de data/raw a data/processed.

Implementa las transformaciones justificadas en la Entrega 2:
  T1  unión de los cuatro conjuntos delictivos con un esquema común
  T2  conteo por suma de cantidad, sin deduplicar
  T3  conversión de fecha (texto dd/mm/aaaa) y agregación mensual
  T4  llave territorial: código de 5 dígitos, DIVIPOLA como maestra y
      corrección por nombre de los códigos inválidos o de otro municipio
  T5  homologación de arma/medio y faltantes explícitos
  T6  población anual unificada (2005-2017 + 2018-2042)
  T7  panel completo municipio-mes con ceros explícitos
  T8  marcas de quiebre, variables derivadas y partición temporal
Cada paso deja su conteo en validaciones.csv para trazar origen y destino.

Uso:
    python transform/transformar.py
"""
import argparse
import calendar
import difflib
import pathlib
import re
import unicodedata

import holidays
import numpy as np
import pandas as pd

CONJUNTOS = {
    "motos": ("motos_9vha-vh9n.csv.gz", "tipo_de_hurto"),
    "abigeato": ("abigeato_d4fr-sbn2.csv.gz", "tipo_de_hurto"),
    "sexuales": ("sexuales_fpe5-yrmw.csv.gz", "delito"),
    "vif": ("vif_vuyt-mqpw.csv.gz", None),
}
ARMA_BLANCA = {"CORTANTES", "CORTOPUNZANTES", "PUNZANTES", "ARMAS BLANCAS"}
MES_INICIO, MES_FIN = "2010-01", "2026-07"
INICIO_MODELO = "2012-01"   # los 12 rezagos quedan enteros después del salto de 2011
FIN_ENTRENAMIENTO = "2024-12"

validaciones = []


def registrar(etapa, verificacion, valor, nota=""):
    validaciones.append({"etapa": etapa, "verificacion": verificacion, "valor": valor, "nota": nota})


def norm(s):
    s = re.sub(r"\(CT\)", "", "" if pd.isna(s) else str(s))
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().upper()
    return " ".join(re.sub(r"[^A-Z ]", " ", s).split())


def coincide(nombre_origen, nombre_divipola):
    a, b = set(nombre_origen.split()), set(nombre_divipola.split())
    if a and (a <= b or b <= a):
        return True
    x, y = nombre_origen.replace(" ", ""), nombre_divipola.replace(" ", "")
    comun = difflib.SequenceMatcher(None, x, y).find_longest_match(0, len(x), 0, len(y)).size
    return comun / max(len(x), 1) >= 0.8


# ---------------------------------------------------------------- DIVIPOLA
def dim_municipio(raw):
    dv = pd.read_csv(raw / "divipola_gdxc-w37w.csv.gz", dtype=str)
    dim = pd.DataFrame({
        "cod_mpio": dv["cod_mpio"],
        "municipio": dv["nom_mpio"],
        "cod_dpto": dv["cod_dpto"],
        "departamento": dv["dpto"],
        "tipo": dv["tipo_municipio"],
        "latitud": dv["latitud"].str.replace(",", ".").astype(float),
        "longitud": dv["longitud"].str.replace(",", ".").astype(float),
    })
    dim["nombre_norm"] = dim["municipio"].map(norm)
    registrar("T4", "municipios en DIVIPOLA", len(dim))
    return dim


# ---------------------------------------------------------------- T1-T5
def unir_conjuntos(raw):
    partes = []
    for alias, (archivo, col_delito) in CONJUNTOS.items():
        d = pd.read_csv(raw / archivo, dtype=str, keep_default_na=False)
        registrar("T1", f"filas crudas {alias}", len(d))
        partes.append(pd.DataFrame({
            "conjunto": alias,
            "delito": d[col_delito] if col_delito else "VIOLENCIA INTRAFAMILIAR",
            "fecha_hecho": d["fecha_hecho"],
            "codigo_dane": d["codigo_dane"],
            "departamento_origen": d["departamento"],
            "municipio_origen": d["municipio"],
            "arma_medio": d["armas_medios"],
            "genero": d["genero"],
            "grupo_etario": d["grupo_etario"],
            "cantidad": d["cantidad"].astype(int),
        }))
    h = pd.concat(partes, ignore_index=True)
    for alias, g in h.groupby("conjunto"):
        registrar("T2", f"hechos crudos (suma de cantidad) {alias}", int(g["cantidad"].sum()),
                  "se conservan las filas repetidas")
    # T3 fecha
    h["fecha"] = pd.to_datetime(h["fecha_hecho"], format="%d/%m/%Y", errors="coerce")
    registrar("T3", "fechas no convertibles", int(h["fecha"].isna().sum()))
    h["mes"] = h["fecha"].dt.to_period("M").astype(str)
    # T5 categorías y faltantes
    variantes = h["arma_medio"].isin(ARMA_BLANCA)
    registrar("T5", "filas con rótulo minoritario de arma blanca homologado", int(variantes.sum()))
    h.loc[variantes, "arma_medio"] = "ARMA BLANCA / CORTOPUNZANTE"
    falt_gen = h["genero"].isin(["", "NO REPORTA"])
    falt_eta = h["grupo_etario"] == ""
    registrar("T5", "género vacío o NO REPORTA convertido a nulo", int(falt_gen.sum()))
    registrar("T5", "grupo etario vacío convertido a nulo", int(falt_eta.sum()))
    h["genero"] = h["genero"].where(~falt_gen)
    h["grupo_etario"] = h["grupo_etario"].where(~falt_eta)
    return h


def llave_territorial(h, dim):
    h["cod_mpio"] = h["codigo_dane"].str[:5]
    nombres = dim.set_index("cod_mpio")["nombre_norm"]
    tipos = dim.set_index("cod_mpio")["tipo"]
    combos = h[["departamento_origen", "municipio_origen", "cod_mpio"]].drop_duplicates().copy()
    combos["n_origen"] = combos["municipio_origen"].map(norm)
    combos["n_divipola"] = combos["cod_mpio"].map(nombres)
    combos["tipo"] = combos["cod_mpio"].map(tipos)

    def estado(r):
        if pd.isna(r["n_divipola"]):
            return "codigo_inexistente"
        if coincide(r["n_origen"], r["n_divipola"]):
            return "ok"
        if r["tipo"] == "Área no municipalizada":
            return "anm_con_nombre_de_capital"
        return "codigo_de_otro_municipio"

    combos["estado"] = combos.apply(estado, axis=1)
    # departamento de origen -> código de departamento, por moda entre los registros válidos
    ok = combos[combos["estado"] == "ok"]
    dpto = ok.assign(cd=ok["cod_mpio"].str[:2]).groupby("departamento_origen")["cd"].agg(lambda s: s.mode()[0])

    def corregir(r):
        if r["estado"] not in ("codigo_inexistente", "codigo_de_otro_municipio"):
            return r["cod_mpio"]
        cand = dim[(dim["cod_dpto"] == dpto.get(r["departamento_origen"])) &
                   dim["nombre_norm"].map(lambda n: bool(r["n_origen"]) and coincide(r["n_origen"], n))]
        return cand["cod_mpio"].iloc[0] if len(cand) == 1 else None

    combos["cod_corregido"] = combos.apply(corregir, axis=1)
    h = h.merge(combos[["departamento_origen", "municipio_origen", "cod_mpio", "estado", "cod_corregido"]],
                on=["departamento_origen", "municipio_origen", "cod_mpio"], how="left")
    for e, g in h.groupby("estado"):
        registrar("T4", f"filas con estado territorial {e}", len(g))
    corr = h["estado"].isin(["codigo_inexistente", "codigo_de_otro_municipio"])
    registrar("T4", "filas con código corregido por nombre", int((corr & h["cod_corregido"].notna()).sum()))
    sin_llave = h["cod_corregido"].isna()
    registrar("T4", "filas descartadas por no tener municipio identificable", int(sin_llave.sum()),
              "; ".join(sorted(set(h.loc[sin_llave, "codigo_dane"] + " " + h.loc[sin_llave, "departamento_origen"]))))
    h = h[~sin_llave].copy()
    h["cod_mpio"] = h["cod_corregido"]
    return h.drop(columns=["cod_corregido"])


# ---------------------------------------------------------------- T6
def poblacion(raw, dim):
    p1 = pd.read_excel(raw / "DCD-area-proypoblacion-Mun-2005-2017_VP.xlsx", header=11, dtype={"MPIO": str})
    p2 = pd.read_excel(raw / "PPED-AreaMun-2018-2042_VP.xlsx", sheet_name="PobMunicipalxÁrea",
                       header=7, dtype={"MPIO": str}).dropna(subset=["MPIO"])
    p1 = p1[p1["ÁREA GEOGRÁFICA"] == "Total"].rename(columns={"Población": "poblacion"})
    p2 = p2[p2["ÁREA GEOGRÁFICA"] == "Total"].rename(columns={"TOTAL": "poblacion"})
    p = pd.concat([p1[["MPIO", "AÑO", "poblacion"]], p2[["MPIO", "AÑO", "poblacion"]]])
    p = p.rename(columns={"MPIO": "cod_mpio", "AÑO": "anio"})
    p["anio"] = p["anio"].astype(int)
    p["poblacion"] = p["poblacion"].astype(int)
    fuera = sorted(set(p["cod_mpio"]) - set(dim["cod_mpio"]))
    registrar("T6", "códigos de población fuera de DIVIPOLA (excluidos)", len(fuera), ", ".join(fuera))
    p = p[p["cod_mpio"].isin(dim["cod_mpio"])]
    registrar("T6", "municipio-año con población 0", int((p["poblacion"] == 0).sum()),
              ", ".join(sorted(p.loc[p["poblacion"] == 0, "cod_mpio"].unique())))
    registrar("T6", "filas de población anual", len(p))
    return p.sort_values(["cod_mpio", "anio"]).reset_index(drop=True)


# ---------------------------------------------------------------- T7
def panel(h, dim, pob):
    meses = pd.period_range(MES_INICIO, MES_FIN, freq="M").astype(str)
    idx = pd.MultiIndex.from_product([dim["cod_mpio"], meses, list(CONJUNTOS)],
                                     names=["cod_mpio", "mes", "conjunto"])
    agg = h.groupby(["cod_mpio", "mes", "conjunto"])["cantidad"].sum()
    p = agg.reindex(idx, fill_value=0).rename("hechos").reset_index()
    p["anio"] = p["mes"].str[:4].astype(int)
    p = p.merge(pob, on=["cod_mpio", "anio"], how="left")
    p["tasa_100k"] = np.where(p["poblacion"] > 0, p["hechos"] / p["poblacion"] * 1e5, np.nan)
    registrar("T7", "celdas del panel municipio-mes-conjunto", len(p))
    registrar("T7", "celdas sin registro rellenadas con 0", int(len(p) - len(agg)))
    for c in CONJUNTOS:
        registrar("T7", f"hechos en el panel {c}", int(p.loc[p["conjunto"] == c, "hechos"].sum()))
    return p.drop(columns=["anio"])


# ---------------------------------------------------------------- T8
def variables_modelo(p):
    y = p[p["conjunto"] == "motos"].pivot(index="cod_mpio", columns="mes", values="hechos")
    pobw = p[p["conjunto"] == "motos"].pivot(index="cod_mpio", columns="mes", values="poblacion")
    largo = []
    rezagos = {L: y.shift(L, axis=1) for L in range(1, 13)}
    mm3 = y.shift(1, axis=1).T.rolling(3).mean().T
    mm12 = y.shift(1, axis=1).T.rolling(12).mean().T
    meses = [m for m in y.columns if m >= INICIO_MODELO]
    fest = holidays.Colombia(years=range(2010, 2027))
    n_fest = pd.Series([d.strftime("%Y-%m") for d in fest]).value_counts()
    for m in meses:
        per = pd.Period(m, "M")
        f = pd.DataFrame({"cod_mpio": y.index, "mes": m, "y": y[m].values})
        for L in range(1, 13):
            f[f"lag_{L}"] = rezagos[L][m].values
        f["media_movil_3"] = mm3[m].values
        f["media_movil_12"] = mm12[m].values
        f["mes_del_anio"] = per.month
        f["dias_mes"] = calendar.monthrange(per.year, per.month)[1]
        f["festivos"] = int(n_fest.get(m, 0))
        f["poblacion"] = pobw[m].values
        f["flag_pandemia"] = int("2020-03" <= m <= "2020-08")
        f["flag_dic_atipico"] = int(m in ("2024-12", "2025-12"))
        f["particion"] = "entrenamiento" if m <= FIN_ENTRENAMIENTO else "prueba"
        largo.append(f)
    f = pd.concat(largo, ignore_index=True)
    # universo denso: definido solo con datos de entrenamiento (2018-2024) para no filtrar información de la prueba
    ref = p[(p["conjunto"] == "motos") & (p["mes"] >= "2018-01") & (p["mes"] <= FIN_ENTRENAMIENTO)]
    media = ref.groupby("cod_mpio")["hechos"].mean()
    densos = set(media[media >= 1].index)
    f["universo_denso"] = f["cod_mpio"].isin(densos).astype(int)
    registrar("T8", "municipios del universo denso (>= 1 hecho/mes promedio en 2018-2024)", len(densos))
    registrar("T8", "filas de variables para el modelo", len(f), f"meses {INICIO_MODELO} a {MES_FIN}")
    return f


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default="data/raw")
    ap.add_argument("--salida", default="data/processed")
    a = ap.parse_args(argv)
    raw, out = pathlib.Path(a.raw), pathlib.Path(a.salida)
    out.mkdir(parents=True, exist_ok=True)
    validaciones.clear()

    dim = dim_municipio(raw)
    h = llave_territorial(unir_conjuntos(raw), dim)
    for alias, g in h.groupby("conjunto"):
        registrar("T4", f"hechos tras la llave territorial {alias}", int(g["cantidad"].sum()))
    cols = ["conjunto", "delito", "fecha", "mes", "cod_mpio", "codigo_dane", "estado",
            "arma_medio", "genero", "grupo_etario", "cantidad"]
    h = h.rename(columns={"estado": "estado_territorial"})
    cols[cols.index("estado")] = "estado_territorial"
    h["fecha"] = h["fecha"].dt.strftime("%Y-%m-%d")
    h[cols].to_csv(out / "hechos_unificados.csv.gz", index=False)

    pob = poblacion(raw, dim)
    p = panel(h, dim, pob)
    f = variables_modelo(p)

    dim.drop(columns=["nombre_norm"]).to_csv(out / "dim_municipio.csv", index=False)
    pob.to_csv(out / "poblacion_anual.csv", index=False)
    # Salida en formato ancho: una fila por municipio-mes y una columna por conjunto.
    # La población y la tasa no se repiten aquí: viven en poblacion_anual y en la vista de la base.
    w = (p.pivot(index=["cod_mpio", "mes"], columns="conjunto", values="hechos")
          [list(CONJUNTOS)].add_prefix("hechos_").reset_index())
    registrar("T7", "filas municipio-mes (formato ancho)", len(w))
    w.to_csv(out / "delitos_municipio_mes.csv.gz", index=False)
    f.to_csv(out / "features_motos.csv.gz", index=False)
    pd.DataFrame(validaciones).to_csv(out / "validaciones.csv", index=False)
    print(pd.DataFrame(validaciones).to_string(index=False))


if __name__ == "__main__":
    main()
