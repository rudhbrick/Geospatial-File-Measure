from datetime import datetime

from pydantic import BaseModel, ConfigDict


class FileInfo(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    filename: str
    feature_count: int
    crs: str | None
    status: str
    created_at: datetime
    error: str | None = None


class MeasurementOut(BaseModel):
    status: str  # MEASURED | NOT_REQUIRED | UNSUPPORTED | FAILED
    area_m2: float | None = None
    length_m: float | None = None
    projected_crs: str | None = None
    message: str | None = None


class FeatureResult(BaseModel):
    feature_index: int
    layer: str
    geometry_type: str | None
    crs: str
    properties: dict
    geometry: dict | None
    measurement: MeasurementOut


class FileMeasurements(BaseModel):
    file_id: str
    status: str
    feature_count: int
    features: list[FeatureResult]