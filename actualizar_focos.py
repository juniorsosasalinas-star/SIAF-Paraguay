
import csv
import io
import json
import os
import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# ==========================================
# SIAF PARAGUAY
# Consulta de focos de calor NASA FIRMS
# ==========================================

# Leer la clave desde GitHub Secrets
CLAVE = os.environ.get("NASA_FIRMS_MAP_KEY", "").strip()

if not CLAVE:
    raise RuntimeError(
        "Falta el secreto NASA_FIRMS_MAP_KEY"
    )

# Comprobar que no contenga espacios ni caracteres inválidos
if not re.fullmatch(r"[A-Za-z0-9_-]+", CLAVE):
    raise RuntimeError(
        "NASA_FIRMS_MAP_KEY contiene caracteres inválidos. "
        "Revisar el secreto configurado en GitHub."
    )

# Rectángulo aproximado de Paraguay.
# Pendiente: filtrado por límites nacionales.
AREA = "-62.7,-27.7,-54.2,-19.2"

# Fuentes satelitales NASA FIRMS
FUENTES = [
    "VIIRS_SNPP_NRT",
    "VIIRS_NOAA20_NRT",
    "VIIRS_NOAA21_NRT",
    "MODIS_NRT"
]

detecciones = []
errores = []

# ==========================================
# CONSULTAR NASA FIRMS
# ==========================================

for fuente in FUENTES:

    url = (
        "https://firms.modaps.eosdis.nasa.gov/api/"
        f"area/csv/{CLAVE}/{fuente}/{AREA}/1"
    )

    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "SIAF-Paraguay/1.0"
            }
        )

        with urllib.request.urlopen(
            req, timeout=60
        ) as respuesta:
            contenido = respuesta.read().decode("utf-8-sig")

        lector = csv.DictReader(io.StringIO(contenido))

        if (
            not lector.fieldnames
            or "latitude" not in lector.fieldnames
            or "longitude" not in lector.fieldnames
        ):
            raise ValueError(
                "Respuesta CSV no válida de NASA FIRMS"
            )

        contador = 0

        for fila in lector:
            try:
                lat = float(fila["latitude"])
                lon = float(fila["longitude"])
            except (ValueError, TypeError):
                continue

            detecciones.append({
                "lat": lat,
                "lon": lon,
                "fecha": fila.get("acq_date", ""),
                "hora_utc": fila.get("acq_time", ""),
                "frp": fila.get("frp", ""),
                "confianza": fila.get("confidence", ""),
                "satelite": fila.get("satellite", ""),
                "fuente": fuente
            })

            contador += 1

        print(
            f"{fuente}: consulta correcta - "
            f"{contador} detecciones"
        )

    except Exception as error:
        errores.append(f"{fuente}: {error}")
        print(f"Error en {fuente}: {error}")

# ==========================================
# CONTROL DE ERRORES
# ==========================================

# No publicar datos incompletos si falla una fuente
if errores:
    raise RuntimeError(
        "No se completaron todas las consultas: "
        + "; ".join(errores)
    )

# ==========================================
# GENERAR ARCHIVO JSON
# ==========================================

salida = {
    "actualizado_utc": datetime.now(
        timezone.utc
    ).isoformat(),
    "area": "Paraguay y zonas limítrofes (consulta preliminar)",
    "total_detecciones": len(detecciones),
    "detecciones": detecciones
}

Path("datos").mkdir(exist_ok=True)

with open(
    "datos/focos.json",
    "w",
    encoding="utf-8"
) as archivo:
    json.dump(
        salida,
        archivo,
        ensure_ascii=False,
        indent=2
    )

print(
    f"Archivo generado correctamente: "
    f"{len(detecciones)} detecciones"
)
