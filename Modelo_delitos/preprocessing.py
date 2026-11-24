"""Limpieza de datasets y calculo de distancias a luminarias."""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

# IMPORTANTE: el modelo se entreno con distancias calculadas como
# (distancia en grados) * 111000. Se mantiene la misma convencion para que
# los valores de la grilla futura sean comparables con los del entrenamiento.
METROS_POR_GRADO = 111000


def limpiar_delitos(df_delitos: pd.DataFrame) -> pd.DataFrame:
    df = df_delitos.copy()

    df["Latitud"] = pd.to_numeric(df["Latitud"], errors="coerce")
    df["Longitud"] = pd.to_numeric(df["Longitud"], errors="coerce")
    df["Fecha"] = pd.to_datetime(df["Fecha"], errors="coerce")
    df["Franja Horaria"] = pd.to_numeric(df["Franja Horaria"], errors="coerce")
    df["es_noche"] = df["Franja Horaria"].apply(
        lambda x: 1 if pd.notnull(x) and (x >= 20 or x <= 6) else 0
    )

    # Normalizacion de Comuna (ej. 'COMUNA 4' -> 4.0)
    if df["Comuna"].dtype == object or pd.api.types.is_string_dtype(df["Comuna"]):
        df["Comuna"] = (
            df["Comuna"].astype(str).str.extract(r"(\d+)")[0].astype(float)
        )
    else:
        df["Comuna"] = pd.to_numeric(df["Comuna"], errors="coerce")
    return df


def limpiar_luminarias(df_luminarias: pd.DataFrame) -> pd.DataFrame:
    lum = df_luminarias.copy()
    for col in ("lat", "lng"):
        lum[col] = pd.to_numeric(
            lum[col].astype(str).str.replace(",", ".", regex=False),
            errors="coerce",
        )
    return lum.dropna(subset=["lat", "lng"])


def distancia_a_luminaria(
    tree: cKDTree, lats: np.ndarray, lons: np.ndarray
) -> np.ndarray:
    """Distancia (convencion del entrenamiento) a la luminaria mas cercana."""
    distancias, _ = tree.query(np.column_stack([lats, lons]), k=1)
    return distancias * METROS_POR_GRADO


def agregar_distancia_delitos(df: pd.DataFrame, tree: cKDTree) -> pd.DataFrame:
    df = df.copy()
    df["distancia_luminaria_cercana_m"] = np.nan
    mask = df["Latitud"].notna() & df["Longitud"].notna()
    if mask.any():
        df.loc[mask, "distancia_luminaria_cercana_m"] = distancia_a_luminaria(
            tree, df.loc[mask, "Latitud"].values, df.loc[mask, "Longitud"].values
        )
    return df
