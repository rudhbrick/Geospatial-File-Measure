import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Feature, UploadedFile
from app.schemas import FeatureResult, FileInfo, FileMeasurements, MeasurementOut
from app.services.measurements import measure_all
from app.services.parser import ParseError, parse_file

router = APIRouter(prefix="/api/files", tags=["files"])

MAX_UPLOAD_BYTES = 50 * 1024 * 1024
ALLOWED_SUFFIXES = {".zip", ".kml"}


def _reject(db: Session, record: UploadedFile, code: int, message: str):
    record.status = "FAILED"
    record.error = message
    db.commit()
    raise HTTPException(status_code=code, detail={"id": record.id, "error": message})


def _get_or_404(db: Session, file_id: str) -> UploadedFile:
    record = db.get(UploadedFile, file_id)
    if record is None:
        raise HTTPException(status_code=404, detail="File not found.")
    return record


@router.post("/", response_model=FileInfo, status_code=201)
def upload_file(file: UploadFile = File(...), db: Session = Depends(get_db)):
    filename = Path(file.filename or "").name
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(
            status_code=415,
            detail="Unsupported file type. Upload a .zip (Shapefile) or a .kml.",
        )

    record = UploadedFile(filename=filename)
    db.add(record)
    db.commit()

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / f"upload{suffix}"
        size = 0
        with path.open("wb") as out:
            while chunk := file.file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    _reject(db, record, 413, "File too large (limit 50 MB).")
                out.write(chunk)
        try:
            parsed = parse_file(path)
        except ParseError as exc:
            _reject(db, record, 422, str(exc))

    for feat, m in zip(parsed.features, measure_all(parsed.features)):
        record.features.append(
            Feature(
                feature_index=feat.index,
                layer=feat.layer,
                geometry_type=feat.geometry_type,
                geometry=feat.geometry,
                crs=feat.crs,
                properties=feat.properties,
                measurement_status=m.status,
                area_m2=m.area_m2,
                length_m=m.length_m,
                projected_crs=m.projected_crs,
                message=m.message,
            )
        )
    record.crs = parsed.crs
    record.feature_count = len(parsed.features)
    record.status = "COMPLETED"
    db.commit()
    return record


@router.get("/{file_id}/", response_model=FileInfo)
def get_file(file_id: str, db: Session = Depends(get_db)):
    return _get_or_404(db, file_id)


@router.get("/{file_id}/measurements/", response_model=FileMeasurements)
def get_measurements(file_id: str, db: Session = Depends(get_db)):
    record = _get_or_404(db, file_id)
    if record.status != "COMPLETED":
        raise HTTPException(status_code=409, detail=f"File status is {record.status}.")
    return FileMeasurements(
        file_id=record.id,
        status=record.status,
        feature_count=record.feature_count,
        features=[
            FeatureResult(
                feature_index=f.feature_index,
                layer=f.layer,
                geometry_type=f.geometry_type,
                crs=f.crs,
                properties=f.properties,
                geometry=f.geometry,
                measurement=MeasurementOut(
                    status=f.measurement_status,
                    area_m2=f.area_m2,
                    length_m=f.length_m,
                    projected_crs=f.projected_crs,
                    message=f.message,
                ),
            )
            for f in record.features
        ],
    )