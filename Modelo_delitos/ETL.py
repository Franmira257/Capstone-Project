"""Extraccion: descarga de archivos (Drive o URL directa) y lectura de CSV."""
from __future__ import annotations

import io
import os
import re
import urllib.request

import gdown
import pandas as pd


def extract_drive_id(val: str) -> str | None:
    """Devuelve el File ID si es un ID o un enlace de Google Drive."""
    val = val.strip()
    if re.fullmatch(r"[A-Za-z0-9_-]{15,}", val):
        return val
    match = re.search(r"/d/([A-Za-z0-9_-]+)", val) or re.search(
        r"[?&]id=([A-Za-z0-9_-]+)", val
    )
    return match.group(1) if match else None


def download_bytes(url_or_id: str) -> bytes:
    """Descarga un archivo (Drive por ID/enlace, o cualquier URL directa)."""
    file_id = extract_drive_id(url_or_id)

    if file_id:
        tmp_path = f"/tmp/drive_{file_id}.bin"
        result = gdown.download(id=file_id, output=tmp_path, quiet=True)
        if not result or not os.path.exists(tmp_path):
            raise ValueError(
                f"No se pudo descargar el archivo de Drive (ID {file_id}). "
                "Verifica que este compartido como 'Cualquier persona con el enlace'."
            )
        with open(tmp_path, "rb") as f:
            raw = f.read()
        os.remove(tmp_path)
    else:
        req = urllib.request.Request(
            url_or_id.strip(), headers={"User-Agent": "Mozilla/5.0"}
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            raw = resp.read()

    if raw[:200].lstrip().lower().startswith((b"<!doctype html", b"<html")):
        raise ValueError(
            "La descarga devolvio una pagina HTML en vez del archivo. "
            "Revisa los permisos de uso compartido en Google Drive."
        )
    return raw


def read_csv_flexible(raw_bytes: bytes) -> pd.DataFrame:
    """Lee CSV probando separador coma o punto y coma y codificacion UTF-8 / Latin-1."""
    for enc in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            text = raw_bytes.decode(enc)
            first_line = text.splitlines()[0] if text.splitlines() else ""
            sep = ";" if first_line.count(";") > first_line.count(",") else ","
            return pd.read_csv(io.StringIO(text), sep=sep, low_memory=False)
        except Exception:
            continue
    return pd.read_csv(io.BytesIO(raw_bytes), low_memory=False)
