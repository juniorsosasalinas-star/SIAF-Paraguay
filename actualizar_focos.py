
import csv
import io
import json
import math
import os
import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# ==========================================
# SIAF PARAGUAY
# Monitoreo satelital NASA FIRMS
# Filtrado por límites nacionales
# ==========================================

CLAVE = os.environ.get("NASA_FIRMS_MAP_KEY", "").strip()

if not CLAVE:
    raise RuntimeError("Falta el secreto NASA_FIRMS_MAP_KEY")

if not re.fullmatch(r"[A-Za-z0-9_-]+", CLAVE):
    raise RuntimeError("NASA_FIRMS_MAP_KEY contiene caracteres inválidos")

AREA = "-62.7,-27.7,-54.2,-19.2"

FUENTES = [
    "VIIRS_SNPP_NRT",
    "VIIRS_NOAA20_NRT",
    "VIIRS_NOAA21_NRT",
    "MODIS_NRT"
]

RUTA_LIMITES = Path("paraguay.geojson")
RUTA_SALIDA = Path("datos/focos.json")

# ==========================================
# LEER LÍMITES DE PARAGUAY
# ==========================================

if not RUTA_LIMITES.exists():
    raise FileNotFoundError(
        "No se encontró paraguay.geojson en la carpeta principal"
    )

with RUTA_LIMITES.open("r", encoding="utf-8-sig") as archivo:
    geojson = json.load(archivo)


def extraer_poligonos(objeto):
    tipo = objeto.get("type")

    if tipo == "FeatureCollection":
        resultado = []
        for feature in objeto.get("features", []):
            resultado.extend(extraer_poligonos(feature))
        return resultado

    if tipo == "Feature":
        return extraer_poligonos(objeto.get("geometry") or {})

    if tipo == "GeometryCollection":
        resultado = []
        for geometria in objeto.get("geometries", []):
            resultado.extend(extraer_poligonos(geometria))
        return resultado

    if tipo == "Polygon":
        return [objeto["coordinates"]]

    if tipo == "MultiPolygon":
        return objeto["coordinates"]

    raise ValueError(f"Geometría no compatible: {tipo}")


poligonos = extraer_poligonos(geojson)

if not poligonos:
    raise RuntimeError("El GeoJSON no contiene polígonos válidos")

print(f"Polígonos cargados: {len(poligonos)}")


# ==========================================
# FUNCIONES GEOGRÁFICAS
# ==========================================

def punto_en_segmento(x, y, x1, y1, x2, y2):
    tolerancia = 1e-10

    cruz = (x - x1) * (y2 - y1) - (y - y1) * (x2 - x1)

    if abs(cruz) > tolerancia:
        return False

    return (
        min(x1, x2) - tolerancia <= x <= max(x1, x2) + tolerancia
        and min(y1, y2) - tolerancia <= y <= max(y1, y2) + tolerancia
    )


def punto_en_anillo(lon, lat, anillo):
    dentro = False

    for i in range(len(anillo)):
        x1, y1 = anillo[i]
        x2, y2 = anillo[(i + 1) % len(anillo)]

        if punto_en_segmento(lon, lat, x1, y1, x2, y2):
            return True, True

        if (y1 > lat) != (y2 > lat):
            interseccion = x1 + (
                (lat - y1) * (x2 - x1) / (y2 - y1)
            )

            if lon < interseccion:
                dentro = not dentro

    return dentro, False


def dentro_de_paraguay(lat, lon):
    for poligono in poligonos:
        if not poligono:
            continue

        dentro, borde = punto_en_anillo(
            lon, lat, poligono[0]
        )

        if borde:
            return True

        if not dentro:
            continue

        en_hueco = False

        for hueco in poligono[1:]:
            dentro_hueco, borde_hueco = punto_en_anillo(
                lon, lat, hueco
            )

            if borde_hueco:
                return True

            if dentro_hueco:
                en_hueco = True
                break

        if not en_hueco:
            return True

    return False


# ==========================================
# CONSULTAR NASA FIRMS
# ==========================================

detecciones = []
errores = []
total_consultado = 0

for fuente in FUENTES:
    url = (
        "https://firms.modaps.eosdis.nasa.gov/api/"
        f"area/csv/{CLAVE}/{fuente}/{AREA}/1"
    )

    try:
        solicitud = urllib.request.Request(
            url,
            headers={"User-Agent": "SIAF-Paraguay/1.0"}
        )

        with urllib.request.urlopen(
            solicitud, timeout=60
        ) as respuesta:
            contenido = respuesta.read().decode("utf-8-sig")

        lector = csv.DictReader(io.StringIO(contenido))

        if not lector.fieldnames or not {
            "latitude", "longitude"
        }.issubset(lector.fieldnames):
            raise ValueError("Respuesta CSV inválida de NASA FIRMS")

        consultados = 0
        nacionales = 0

        for fila in lector:
            try:
                lat = float(fila["latitude"])
                lon = float(fila["longitude"])
            except (ValueError, TypeError):
                continue

            if not math.isfinite(lat) or not math.isfinite(lon):
                continue

            consultados += 1

            if not dentro_de_paraguay(lat, lon):
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

            nacionales += 1

        total_consultado += consultados

        print(
            f"{fuente}: {consultados} consultadas, "
            f"{nacionales} dentro de Paraguay"
        )

    except Exception as error:
        errores.append(f"{fuente}: {error}")
        print(f"Error en {fuente}: {error}")


# ==========================================
# CONTROL DE ERRORES
# ==========================================

if errores:
    raise RuntimeError(
        "No se completaron todas las consultas: "
        + "; ".join(errores)
    )


# ==========================================
# GENERAR JSON FILTRADO
# ==========================================

salida = {
    "actualizado_utc": datetime.now(timezone.utc).isoformat(),
    "area": "República del Paraguay",
    "filtro_geografico": "paraguay.geojson",
    "total_consultado": total_consultado,
    "total_detecciones": len(detecciones),
    "detecciones": detecciones
}

RUTA_SALIDA.parent.mkdir(parents=True, exist_ok=True)

archivo_temporal = RUTA_SALIDA.with_suffix(".json.tmp")

with archivo_temporal.open("w", encoding="utf-8") as archivo:
    json.dump(salida, archivo, ensure_ascii=False, indent=2)

archivo_temporal.replace(RUTA_SALIDA)

print("====================================")
print("SIAF PARAGUAY")
print(f"Detecciones consultadas: {total_consultado}")
print(f"Detecciones en Paraguay: {len(detecciones)}")
print("Archivo generado: datos/focos.json")
print("====================================")
