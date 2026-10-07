import pytest

from app.services.measurements import (
    MeasurementError,
    measure_all,
    measure_feature,
    utm_epsg_for,
)
from app.services.parser import ParsedFeature


def feat(index, geom_type, geometry):
    return ParsedFeature(
        index=index, layer="t", geometry_type=geom_type,
        geometry=geometry, crs="EPSG:4326", properties={},
    )


GOOD = {"type": "Polygon", "coordinates": [[(77, 12), (77.01, 12), (77.01, 12.01), (77, 12)]]}
BOWTIE = {"type": "Polygon", "coordinates": [[(0, 0), (1, 1), (1, 0), (0, 1), (0, 0)]]}
COLLECTION = {"type": "GeometryCollection", "geometries": [{"type": "Point", "coordinates": [77, 12]}]}


def test_geometry_collection_is_unsupported_not_a_crash():
    m = measure_feature(feat(0, "GeometryCollection", COLLECTION))
    assert m.status == "UNSUPPORTED"
    assert "GeometryCollection" in m.message


def test_missing_geometry_is_unsupported():
    assert measure_feature(feat(0, None, None)).status == "UNSUPPORTED"


def test_invalid_polygon_fails_with_message():
    m = measure_feature(feat(0, "Polygon", BOWTIE))
    assert m.status == "FAILED"
    assert "Invalid" in m.message


def test_one_bad_feature_does_not_block_the_others():
    results = measure_all([
        feat(0, "Polygon", GOOD),
        feat(1, "Polygon", BOWTIE),
        feat(2, "GeometryCollection", COLLECTION),
        feat(3, "Polygon", GOOD),
    ])
    assert [r.status for r in results] == ["MEASURED", "FAILED", "UNSUPPORTED", "MEASURED"]
    assert results[0].area_m2 == pytest.approx(results[3].area_m2)


def test_utm_zone_selection():
    assert utm_epsg_for(77.59, 12.97) == 32643    # northern hemisphere
    assert utm_epsg_for(-58.4, -34.6) == 32721    # southern hemisphere
    assert utm_epsg_for(180.0, 0.0) == 32660      # zone clamps at 60


def test_polar_feature_is_rejected():
    with pytest.raises(MeasurementError):
        utm_epsg_for(10, 85)