from dataclasses import dataclass
from functools import lru_cache

from pyproj import CRS, Transformer
from shapely.geometry import shape
from shapely.ops import transform

from app.services.parser import ParsedFeature

WGS84 = "EPSG:4326"
MAX_UTM_LAT = 84.0  # UTM is undefined near the poles

AREA_TYPES = {"Polygon", "MultiPolygon"}
LINE_TYPES = {"LineString", "MultiLineString"}
POINT_TYPES = {"Point", "MultiPoint"}


class MeasurementError(Exception):
    """A feature can't be measured; message is safe to show to API clients."""


@dataclass
class Measurement:
    feature_index: int
    geometry_type: str | None
    status: str  # MEASURED | NOT_REQUIRED | UNSUPPORTED | FAILED
    area_m2: float | None = None
    length_m: float | None = None
    projected_crs: str | None = None
    message: str | None = None


@lru_cache(maxsize=256)
def _transformer(src: str, dst: str) -> Transformer:
    return Transformer.from_crs(
        CRS.from_user_input(src), CRS.from_user_input(dst), always_xy=True
    )


def _reproject(geom, src: str, dst: str):
    return transform(_transformer(src, dst).transform, geom)


def utm_epsg_for(lon: float, lat: float) -> int:
    """EPSG code of the WGS84 UTM zone containing (lon, lat)."""
    if abs(lat) > MAX_UTM_LAT:
        raise MeasurementError("Feature is too close to a pole for UTM projection.")
    zone = min(int((lon + 180) // 6) + 1, 60)
    return (32600 if lat >= 0 else 32700) + zone


def measure_feature(feature: ParsedFeature) -> Measurement:
    kind = feature.geometry_type
    base = {"feature_index": feature.index, "geometry_type": kind}

    if feature.geometry is None:
        return Measurement(**base, status="UNSUPPORTED", message="Feature has no geometry.")
    if kind in POINT_TYPES:
        return Measurement(**base, status="NOT_REQUIRED")
    if kind not in AREA_TYPES | LINE_TYPES:
        return Measurement(
            **base, status="UNSUPPORTED", message=f"Measurement not supported for {kind}."
        )

    try:
        geom = shape(feature.geometry)
        if geom.is_empty:
            raise MeasurementError("Geometry is empty.")
        if kind in AREA_TYPES and not geom.is_valid:
            raise MeasurementError("Invalid polygon (e.g. self-intersecting).")

        # 1. Normalise to WGS84 so we can locate the feature on the globe
        wgs84 = _reproject(geom, feature.crs, WGS84)
        centroid = wgs84.centroid

        # 2. Pick the UTM zone for this feature and project into it (metres)
        utm = f"EPSG:{utm_epsg_for(centroid.x, centroid.y)}"
        projected = _reproject(wgs84, WGS84, utm)

        # 3. Measure in the projected CRS
        if kind in AREA_TYPES:
            return Measurement(**base, status="MEASURED", area_m2=projected.area, projected_crs=utm)
        return Measurement(**base, status="MEASURED", length_m=projected.length, projected_crs=utm)

    except MeasurementError as exc:
        return Measurement(**base, status="FAILED", message=str(exc))
    except Exception as exc:  # one bad feature must never take down the whole file
        return Measurement(**base, status="FAILED", message=f"Measurement failed: {exc}")


def measure_all(features: list[ParsedFeature]) -> list[Measurement]:
    return [measure_feature(f) for f in features]