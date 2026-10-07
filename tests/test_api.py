import io
import zipfile
from pathlib import Path

import geopandas as gpd
import pytest
from pyproj import Geod
from shapely.geometry import Polygon, shape

DATA = Path(__file__).parent / "data"
GEOD = Geod(ellps="WGS84")
TOLERANCE = 0.005  # UTM distortion is ~0.12% here; allow 0.5%


def upload(client, name, content, mime="application/octet-stream"):
    return client.post("/api/files/", files={"file": (name, content, mime)})


def upload_sample_kml(client):
    return upload(client, "sample.kml", (DATA / "sample.kml").read_bytes())


def zip_shapefile(gdf, tmp_path, drop_prj=False) -> bytes:
    gdf.to_file(tmp_path / "layer.shp")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for f in tmp_path.iterdir():
            if drop_prj and f.suffix == ".prj":
                continue
            zf.write(f, f.name)
    return buf.getvalue()


def by_type(features, geometry_type):
    return next(f for f in features if f["geometry_type"] == geometry_type)


# ---------- upload + file info ----------

def test_upload_kml(client):
    r = upload_sample_kml(client)
    assert r.status_code == 201
    body = r.json()
    assert body["feature_count"] == 3
    assert body["crs"] == "EPSG:4326"
    assert body["status"] == "COMPLETED"
    assert body["filename"] == "sample.kml"


def test_upload_shapefile_zip(client):
    r = upload(client, "s.zip", (DATA / "sample_shapefile.zip").read_bytes())
    assert r.status_code == 201
    assert r.json()["feature_count"] == 3


def test_get_file_info(client):
    file_id = upload_sample_kml(client).json()["id"]
    r = client.get(f"/api/files/{file_id}/")
    assert r.status_code == 200
    assert r.json()["id"] == file_id
    assert r.json()["status"] == "COMPLETED"


# ---------- measurements ----------

def test_polygon_area_matches_geodesic(client):
    file_id = upload_sample_kml(client).json()["id"]
    features = client.get(f"/api/files/{file_id}/measurements/").json()["features"]
    poly = by_type(features, "Polygon")
    expected = abs(GEOD.geometry_area_perimeter(shape(poly["geometry"]))[0])
    m = poly["measurement"]
    assert m["status"] == "MEASURED"
    assert m["projected_crs"] == "EPSG:32643"  # Bengaluru -> UTM zone 43N
    assert m["area_m2"] == pytest.approx(expected, rel=TOLERANCE)


def test_line_length_matches_geodesic(client):
    file_id = upload_sample_kml(client).json()["id"]
    features = client.get(f"/api/files/{file_id}/measurements/").json()["features"]
    line = by_type(features, "LineString")
    expected = GEOD.geometry_length(shape(line["geometry"]))
    assert line["measurement"]["length_m"] == pytest.approx(expected, rel=TOLERANCE)


def test_point_needs_no_measurement(client):
    file_id = upload_sample_kml(client).json()["id"]
    features = client.get(f"/api/files/{file_id}/measurements/").json()["features"]
    m = by_type(features, "Point")["measurement"]
    assert m["status"] == "NOT_REQUIRED"
    assert m["area_m2"] is None and m["length_m"] is None


def test_projected_input_crs_is_handled(client, tmp_path):
    """A file already in UTM metres: a 1000 m square must measure ~1,000,000 m2."""
    square = Polygon([(500000, 1434000), (501000, 1434000), (501000, 1435000), (500000, 1435000)])
    gdf = gpd.GeoDataFrame({"name": ["sq"]}, geometry=[square], crs="EPSG:32643")
    r = upload(client, "utm.zip", zip_shapefile(gdf, tmp_path))
    assert r.status_code == 201
    assert r.json()["crs"] == "EPSG:32643"
    file_id = r.json()["id"]
    m = client.get(f"/api/files/{file_id}/measurements/").json()["features"][0]["measurement"]
    assert m["area_m2"] == pytest.approx(1_000_000, rel=1e-4)


# ---------- validation / errors ----------

def test_rejects_unsupported_extension(client):
    r = upload(client, "notes.txt", b"hello", "text/plain")
    assert r.status_code == 415


def test_rejects_corrupt_zip(client):
    r = upload(client, "bad.zip", b"this is not a zip")
    assert r.status_code == 422


def test_rejects_zip_without_shp(client):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("readme.txt", "no shapefile here")
    r = upload(client, "empty.zip", buf.getvalue())
    assert r.status_code == 422
    assert "No .shp" in r.json()["detail"]["error"]


def test_rejects_shapefile_missing_prj(client, tmp_path):
    gdf = gpd.GeoDataFrame(
        {"name": ["a"]}, geometry=[Polygon([(77, 12), (77.01, 12), (77.01, 12.01)])], crs="EPSG:4326"
    )
    r = upload(client, "noprj.zip", zip_shapefile(gdf, tmp_path, drop_prj=True))
    assert r.status_code == 422
    assert "no CRS" in r.json()["detail"]["error"]


def test_failed_upload_is_recorded(client):
    detail = upload(client, "bad.zip", b"nope").json()["detail"]
    info = client.get(f"/api/files/{detail['id']}/")
    assert info.json()["status"] == "FAILED"
    assert info.json()["error"]
    assert client.get(f"/api/files/{detail['id']}/measurements/").status_code == 409


def test_unknown_id_returns_404(client):
    assert client.get("/api/files/doesnotexist/").status_code == 404
    assert client.get("/api/files/doesnotexist/measurements/").status_code == 404