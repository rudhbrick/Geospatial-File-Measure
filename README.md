# Geospatial File Measurement API

A FastAPI service that accepts a Shapefile (zipped) or KML file, extracts every
feature, and returns area (polygons) and length (lines) measured in metres.

## Setup

Requires Python 3.10+ (developed on 3.13).

```bash
git clone https://github.com/rudhbrick/Geospatial-File-Measure.git
cd Geospatial-File-Measure
python -m venv .venv
# Windows: .venv\Scripts\activate    Mac/Linux: source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

The API runs at http://127.0.0.1:8000 and interactive docs are at `/docs`.
A SQLite database (`geo_files.db`) is created on first start.

### Tests

```bash
pytest -v
```

Sample fixtures live in `tests/data/` and can be regenerated with
`python tests/data/generate_samples.py`.

## API

### `POST /api/files/`
Upload a `.kml` or a `.zip` containing a Shapefile (multipart field `file`).

```bash
curl -X POST http://127.0.0.1:8000/api/files/ -F "file=@tests/data/sample.kml"
```
```json
{
  "id": "8d94cb6a40e6467cb34a72aced1d639e",
  "filename": "sample.kml",
  "feature_count": 3,
  "crs": "EPSG:4326",
  "status": "COMPLETED",
  "created_at": "2026-10-07T07:51:54.610229Z",
  "error": null
}
```

| Status | Meaning |
|---|---|
| 201 | Processed and stored |
| 413 | File larger than 50 MB |
| 415 | Not a `.zip` or `.kml` |
| 422 | Unreadable file, no `.shp` in zip, or no CRS defined |

Rejected files with a 422 or 413 are stored with `status: FAILED` and an
error message, retrievable via the endpoint below.

### `GET /api/files/{id}/`
Returns the same object as the upload response. 404 if the id is unknown.

### `GET /api/files/{id}/measurements/`
Returns every feature with its geometry, CRS, properties and measurement.
Returns 409 if the file did not process successfully.

```json
{
  "file_id": "8d94cb6a40e6467cb34a72aced1d639e",
  "status": "COMPLETED",
  "feature_count": 3,
  "features": [
    {
      "feature_index": 0,
      "layer": "upload",
      "geometry_type": "Polygon",
      "crs": "EPSG:4326",
      "properties": {"Name": "square_1km"},
      "geometry": {"type": "Polygon", "coordinates": ["..."]},
      "measurement": {
        "status": "MEASURED",
        "area_m2": 1001823.71,
        "length_m": null,
        "projected_crs": "EPSG:32643",
        "message": null
      }
    }
  ]
}
```

Measurement `status` values: `MEASURED`, `NOT_REQUIRED` (points),
`UNSUPPORTED` (e.g. GeometryCollection, missing geometry) and `FAILED`
(e.g. invalid polygon). `message` explains the last two.

## Architecture

```
app/
  main.py            app setup, router, table creation on startup
  api/files.py       the three endpoints
  services/parser.py       file -> features (no HTTP, no DB)
  services/measurements.py features -> measurements (no HTTP, no DB)
  models.py          SQLAlchemy tables: files, features
  schemas.py         Pydantic response models
  database.py        engine and session
```

**File-processing flow.** The upload is streamed to a temporary file (with a
50 MB cap). Zips are extracted after checking every entry path for zip-slip,
then each `.shp` is read; KML layers (one per folder) are all read. Geometry is
read with pyogrio, with altitude values dropped (`force_2d`). Each feature
keeps its geometry as GeoJSON in its original CRS, plus its own CRS label and
attributes. Features and measurements are then stored.

**Measurement flow.** For each feature: reproject to WGS84, take the centroid,
choose the UTM zone for that centroid, reproject into it, and compute
`area` or `length` in metres. Points are skipped. Anything unsupported or
failing is recorded on that feature and never stops the rest.

**CRS handling.** Measurements never use degrees. The zone is chosen per
feature rather than per file, so a file spanning several zones is still
measured in the right zone for each feature. Files already in a projected CRS
go through the same path, via WGS84. A file with no CRS is rejected, because
guessing one would silently produce wrong numbers.

## Design decisions

- **Per-feature UTM instead of one fixed CRS.** A fixed CRS is only accurate
  near its own region. Alternative considered: direct geodesic calculation with
  `pyproj.Geod`, which is exact on the ellipsoid. I kept projection-based
  measurement because the brief asks for it, and use `Geod` in the tests as an
  independent reference.
- **Measured accuracy.** On the test fixture, the UTM area is about 0.12%
  above the geodesic area. UTM preserves angles, not area; an equal-area
  projection centred on each feature would remove that error.
- **Synchronous processing, measured at upload and stored.** Simple and keeps
  the GET endpoints cheap. Trade-off: a very large file blocks its request.
  Endpoints are plain `def`, so FastAPI runs them in a threadpool and other
  requests are not blocked.
- **SQLite + SQLAlchemy.** Zero setup for reviewers. Swapping to PostgreSQL
  only needs a different `DATABASE_URL`.
- **Reject instead of repair.** Missing CRS and invalid polygons are reported,
  not guessed or auto-fixed, because repairing can change the area.
- **Per-feature failure handling.** A bad feature gets `FAILED` or
  `UNSUPPORTED` with a message; the other features are unaffected.
- **Tests compare against `pyproj.Geod`** rather than hardcoded numbers, with a
  0.5% tolerance that covers UTM distortion.

## Known limitations

- The `layer` field for KML shows the temporary file name, not the folder name.
- Features within 84° of a pole are rejected (UTM is undefined there).
- A single feature spanning several UTM zones has larger distortion.
- The measurements response always includes full geometry and is not paginated.
- Not covered by tests: the 50 MB limit and multi-folder KML files.

## Learnings

[WRITE THIS IN YOUR OWN WORDS: 3 to 5 sentences. Suggested topics: what you
learned about CRS and why degrees can't be measured; the UTM distortion you
measured against the geodesic reference; the zip-slip risk; and anything that
broke while you built it.]

## Future scope

- Background processing (task queue) for large files, with polling on status
- Pagination and optional geometry in the measurements response
- Equal-area projection or geodesic measurement option for exact areas
- GeoPackage and GeoJSON support
- Correct layer names for KML folders
- Dockerfile and CI to run the tests
