import json
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

import pyogrio


class ParseError(Exception):
    """Raised when an uploaded file can't be read as a supported geospatial file."""


@dataclass
class ParsedFeature:
    index: int
    layer: str
    geometry_type: str | None
    geometry: dict | None  # GeoJSON, in the file's original CRS
    crs: str
    properties: dict


@dataclass
class ParsedFile:
    crs: str
    features: list[ParsedFeature] = field(default_factory=list)


def _safe_extract(zip_path: Path, dest: Path) -> None:
    """Extract a zip, rejecting entries that would escape `dest` (zip-slip)."""
    dest = dest.resolve()
    try:
        with zipfile.ZipFile(zip_path) as zf:
            for member in zf.infolist():
                if not (dest / member.filename).resolve().is_relative_to(dest):
                    raise ParseError("Zip contains unsafe file paths.")
            zf.extractall(dest)
    except zipfile.BadZipFile as exc:
        raise ParseError("File is not a valid zip archive.") from exc


def _crs_label(crs) -> str:
    epsg = crs.to_epsg()
    return f"EPSG:{epsg}" if epsg else crs.to_string()


def _read_layers(path: Path) -> list[tuple[str, object]]:
    """Read every non-empty layer. KML creates one layer per folder."""
    try:
        layer_names = [str(row[0]) for row in pyogrio.list_layers(path)]
        layers = []
        for name in layer_names:
            # force_2d drops KML altitude (Z) values; we only measure in 2D
            gdf = pyogrio.read_dataframe(path, layer=name, force_2d=True)
            if not gdf.empty:
                layers.append((name, gdf))
        return layers
    except ParseError:
        raise
    except Exception as exc:
        raise ParseError(f"Could not read geospatial data: {exc}") from exc


def _layer_features(layer: str, gdf, start_index: int) -> list[ParsedFeature]:
    if gdf.crs is None:
        raise ParseError(
            f"Layer '{layer}' has no CRS defined (is the .prj file missing?)."
        )
    crs = _crs_label(gdf.crs)
    # to_json handles NaN -> null and timestamps -> strings for us
    collection = json.loads(gdf.to_json(drop_id=True))
    features = []
    for offset, feat in enumerate(collection["features"]):
        geom = feat.get("geometry")
        features.append(
            ParsedFeature(
                index=start_index + offset,
                layer=layer,
                geometry_type=geom["type"] if geom else None,
                geometry=geom,
                crs=crs,
                properties=feat.get("properties") or {},
            )
        )
    return features


def parse_file(path: Path) -> ParsedFile:
    suffix = path.suffix.lower()

    if suffix == ".kml":
        layers = _read_layers(path)
    elif suffix == ".zip":
        with tempfile.TemporaryDirectory() as tmp:
            _safe_extract(path, Path(tmp))
            shp_files = sorted(
                p
                for p in Path(tmp).rglob("*.shp")
                if "__MACOSX" not in p.parts and not p.name.startswith("._")
            )
            if not shp_files:
                raise ParseError("No .shp file found inside the zip.")
            layers = []
            for shp in shp_files:
                layers.extend(_read_layers(shp))  # must read before tmp dir is deleted
    else:
        raise ParseError("Unsupported file type. Upload a .zip (Shapefile) or a .kml.")

    if not layers:
        raise ParseError("The file contains no features.")

    features: list[ParsedFeature] = []
    for name, gdf in layers:
        features.extend(_layer_features(name, gdf, start_index=len(features)))

    crs_set = {f.crs for f in features}
    file_crs = crs_set.pop() if len(crs_set) == 1 else "MIXED"
    return ParsedFile(crs=file_crs, features=features)