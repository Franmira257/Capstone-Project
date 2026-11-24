"""Logica de negocio del Actor: grilla futura, carga del modelo, inferencia y salida."""
from __future__ import annotations

import pickle
from itertools import product

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

from .preprocessing import METROS_POR_GRADO, distancia_a_luminaria

DEFAULT_FEATURES = [
    "Comuna",
    "Latitud",
    "Longitud",
    "Franja Horaria",
    "distancia_luminaria_cercana_m",
]

# Modelo en Google Drive (no se sube al actor porque pesa mucho)
MODELO_URL_POR_DEFECTO = (
    "https://drive.google.com/file/d/1gOj5V6kXqd0sYSIQsAbty4KMU_zzK_OG/view?usp=sharing"
)

COLUMNAS_GRILLA = [
    "Latitud",
    "Longitud",
    "Franja Horaria",
    "Comuna",
    "distancia_luminaria_cercana_m",
]


def construir_grilla_futura(
    df: pd.DataFrame,
    tree: cKDTree,
    n_lat: int = 10,
    n_lon: int = 10,
    max_dist_delito_m: float = 700,
) -> pd.DataFrame:
    """Arma una grilla de puntos por comuna x 24 horas.

    - La distancia a la luminaria se calcula para CADA punto de la grilla.
    - Los limites de cada comuna usan percentiles 1-99 para ignorar coordenadas erroneas.
    - Se descartan los puntos a mas de `max_dist_delito_m` metros de cualquier
      delito real de esa comuna. Con 0 se desactiva el filtro.
    """
    validos = df.dropna(subset=["Comuna", "Latitud", "Longitud"])
    horas = np.arange(24)
    bloques = []

    for comuna, g in validos.groupby("Comuna"):
        lat_min, lat_max = g["Latitud"].quantile([0.01, 0.99])
        lon_min, lon_max = g["Longitud"].quantile([0.01, 0.99])

        lats = np.linspace(lat_min, lat_max, n_lat)
        lons = np.linspace(lon_min, lon_max, n_lon)
        puntos = np.array(list(product(lats, lons)))

        if max_dist_delito_m and max_dist_delito_m > 0 and len(g) > 0:
            tree_delitos = cKDTree(g[["Latitud", "Longitud"]].values)
            d, _ = tree_delitos.query(puntos, k=1)
            puntos = puntos[d * METROS_POR_GRADO <= max_dist_delito_m]

        if len(puntos) == 0:
            continue

        dist = distancia_a_luminaria(tree, puntos[:, 0], puntos[:, 1])
        n = len(puntos)
        bloques.append(
            pd.DataFrame({
                "Latitud": np.repeat(puntos[:, 0], len(horas)),
                "Longitud": np.repeat(puntos[:, 1], len(horas)),
                "Franja Horaria": np.tile(horas, n),
                "Comuna": comuna,
                "distancia_luminaria_cercana_m": np.repeat(dist, len(horas)),
            })
        )

    if not bloques:
        return pd.DataFrame(columns=COLUMNAS_GRILLA)
    return pd.concat(bloques, ignore_index=True)


def cargar_modelo(raw: bytes):
    """Deserializa el modelo. Devuelve (modelo, features)."""
    loaded = pickle.loads(raw)
    if isinstance(loaded, dict) and "model" in loaded:
        return loaded["model"], loaded.get("features", DEFAULT_FEATURES)
    return loaded, DEFAULT_FEATURES


def predecir(df: pd.DataFrame, modelo, features: list[str]) -> pd.DataFrame:
    df = df.copy()
    df["probabilidad_hurto_futura"] = modelo.predict_proba(df[features])[:, 1]
    return df


def formatear_salida(df: pd.DataFrame) -> list[dict]:
    """Redondea, castea y convierte a lista de dicts lista para push_data."""
    df = df.copy()
    df["Comuna"] = df["Comuna"].astype(int)
    df["Franja Horaria"] = df["Franja Horaria"].astype(int)
    df["Latitud"] = df["Latitud"].round(6)
    df["Longitud"] = df["Longitud"].round(6)
    df["distancia_luminaria_cercana_m"] = df["distancia_luminaria_cercana_m"].round(1)
    df["probabilidad_hurto_futura"] = df["probabilidad_hurto_futura"].round(4)

    df = df.replace([np.inf, -np.inf], np.nan)
    return df.where(pd.notnull(df), None).to_dict(orient="records")
