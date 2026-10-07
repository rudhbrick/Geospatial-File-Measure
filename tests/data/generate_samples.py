import math
import shutil
import tempfile
from pathlib import Path

import geopandas as gpd
from shapely.geometry import LineString, Polygon

OUT = Path(__file__).parent
LAT, LON = 12.9716, 77.5946  # arbitrary test location

# Degrees that equal ~1 km at this latitude
dlat = 1 / 110.574
dlon = 1 / (111.320 * math.cos(math.radians(LAT)))

square = Polygon([
    (LON, LAT), (LON + dlon, LAT),
    (LON + dlon, LAT + dlat), (LON, LAT + dlat), (LON, LAT),
])
triangle = Polygon([
    (LON + 0.02, LAT), (LON + 0.03, LAT), (LON + 0.025, LAT + 0.01),
])
line = LineString([(LON, LAT), (LON + dlon, LAT)])  # ~1 km long

# --- KML: polygon, line, point (point carries altitude on purpose) ---
def ring(poly):
    return " ".join(f"{x},{y},0" for x, y in poly.exterior.coords)

kml = f"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2"><Document>
  <Placemark><name>square_1km</name>
    <Polygon><outerBoundaryIs><LinearRing><coordinates>{ring(square)}</coordinates></LinearRing></outerBoundaryIs></Polygon>
  </Placemark>
  <Placemark><name>line_1km</name>
    <LineString><coordinates>{" ".join(f"{x},{y},0" for x, y in line.coords)}</coordinates></LineString>
  </Placemark>
  <Placemark><name>marker</name>
    <Point><coordinates>{LON},{LAT},920</coordinates></Point>
  </Placemark>
</Document></kml>"""
(OUT / "sample.kml").write_text(kml, encoding="utf-8")

# --- Shapefile zip: one shapefile per geometry type ---
with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    gpd.GeoDataFrame(
        {"name": ["square_1km", "triangle"]}, geometry=[square, triangle], crs="EPSG:4326"
    ).to_file(tmp / "polygons.shp")
    gpd.GeoDataFrame(
        {"name": ["line_1km"]}, geometry=[line], crs="EPSG:4326"
    ).to_file(tmp / "lines.shp")
    shutil.make_archive(str(OUT / "sample_shapefile"), "zip", tmp)

print("Created sample.kml and sample_shapefile.zip in", OUT)