"""Entry point del Actor de Apify (solo inferencia)."""
from __future__ import annotations

import os

from apify import Actor
from scipy.spatial import cKDTree

from .ETL import download_bytes, read_csv_flexible
from .preprocessing import (
    agregar_distancia_delitos,
    limpiar_delitos,
    limpiar_luminarias,
)
from .tooling_business import (
    MODELO_URL_POR_DEFECTO,
    cargar_modelo,
    construir_grilla_futura,
    formatear_salida,
    predecir,
)


async def main() -> None:
    async with Actor:
        inp = await Actor.get_input() or {}

        csv_delitos_ref = inp.get("csv_delitos_url") or inp.get("csv_1_url")
        csv_luminarias_ref = inp.get("csv_luminarias_url") or inp.get("csv_2_url")
        modelo_ref = (
            inp.get("modelo_url")
            or os.getenv("MODELO_HURTO_URL")
            or MODELO_URL_POR_DEFECTO
        )
        n_lat = max(2, int(inp.get("n_lat", 10)))
        n_lon = max(2, int(inp.get("n_lon", 10)))
        max_dist = float(inp.get("max_dist_delito_m", 700))

        if not csv_delitos_ref or not csv_luminarias_ref:
            raise ValueError(
                "Faltan 'csv_delitos_url' o 'csv_luminarias_url' en el input del Actor."
            )

        Actor.log.info("Descargando modelo...")
        modelo, features = cargar_modelo(download_bytes(modelo_ref))

        Actor.log.info("Descargando y leyendo los dos CSV...")
        df_delitos = read_csv_flexible(download_bytes(csv_delitos_ref))
        df_luminarias = read_csv_flexible(download_bytes(csv_luminarias_ref))

        Actor.log.info("Limpiando datasets...")
        df_base = limpiar_delitos(df_delitos)
        lum = limpiar_luminarias(df_luminarias)
        if lum.empty:
            raise ValueError("El CSV de luminarias no tiene coordenadas validas.")

        tree = cKDTree(lum[["lat", "lng"]].values)
        df_base = agregar_distancia_delitos(df_base, tree)

        Actor.log.info(f"Construyendo grilla (n_lat={n_lat}, n_lon={n_lon}, max_dist={max_dist})...")
        df_futuro = construir_grilla_futura(df_base, tree, n_lat, n_lon, max_dist)
        df_futuro = df_futuro.dropna(subset=features).copy()
        if df_futuro.empty:
            raise ValueError("La grilla futura quedo vacia. Revisa los CSV de entrada.")

        Actor.log.info(f"Calculando probabilidades sobre {len(df_futuro)} filas...")
        df_futuro = predecir(df_futuro, modelo, features)

        records = formatear_salida(df_futuro)
        await Actor.push_data(records)
        Actor.log.info(f"Listo: se guardaron {len(records)} registros en el dataset de Apify.")
