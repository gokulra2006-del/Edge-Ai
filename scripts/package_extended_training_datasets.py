"""Create one provenance-labelled extended training dataset archive from local sources."""
from pathlib import Path
from datetime import datetime, timezone
import json
import zipfile

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "exports"
OUT.mkdir(exist_ok=True)
ZIP_PATH = OUT / "sentinel_ai_extended_training_dataset.zip"

SOURCES = [
    ("audio_project", ROOT / "data" / "audio_dataset", "Existing project audio classes used by the audio pipeline."),
    ("audio_sirennet", ROOT / "sireNNet", "Additional siren-oriented source data; labels must be audited before merging."),
    ("audio_esc50", ROOT / "ESC-50-master", "Environmental sound source data; map only verified labels to project classes."),
    ("vision_project", ROOT / "data" / "new_dataset", "Current project fire/smoke, vehicle and raw vision data."),
    ("vision_fire_smoke", ROOT / "FIRE n SMOKE DETECTION.v1i.yolov11", "YOLO-format fire and smoke source data."),
    ("vision_vehicles", ROOT / "vehicles.v2-release.yolov11", "YOLO-format vehicle source data used by the current vision preparation script."),
    ("vision_road_obstacles", ROOT / "Road_Obstacle_Detection.v1i.yolov11", "Road-obstacle source data for a proposed future verification model."),
    ("vision_context_patches", ROOT / "CNR-EXT-Patches-150x150", "Image-patch context source data; proposed research use only."),
    ("vision_pedestrians", ROOT / "PennFudanPed", "Pedestrian context source data; proposed research use only."),
]

files = []
summary = []
for archive_name, source, purpose in SOURCES:
    if not source.exists():
        summary.append({"archive_directory": archive_name, "source": str(source), "included": False, "reason": "not found"})
        continue
    source_files = [p for p in source.rglob("*") if p.is_file()]
    for p in source_files:
        files.append((p, f"datasets/{archive_name}/{p.relative_to(source).as_posix()}"))
    summary.append({"archive_directory": archive_name, "source": str(source.relative_to(ROOT)), "included": True, "files": len(source_files), "bytes": sum(p.stat().st_size for p in source_files), "purpose": purpose})

readme = """SENTINEL-AI EXTENDED TRAINING DATASET\n\nThis archive was assembled only from datasets already present in the Edge-AI workspace. It is intended for training, evaluation and research preparation. It is not required for live Raspberry Pi inference because deployment uses trained model files.\n\nRecommended use:\n1. Keep every source directory separate during first audit.\n2. Read its own README/licence/provenance files before training.\n3. Verify audio labels and normalise sample rate before merging classes.\n4. Verify YOLO labels and class maps before merging visual datasets.\n5. Create subject/source-separated train, validation and test splits to reduce data leakage.\n6. Mark generated or transformed samples SYNTHETIC. Do not call results REAL_HARDWARE unless collected from the physical Pi deployment.\n\nCurrent pipeline support:\n- Audio project data is supported by src/modules/audio_ai/dataset_prep.py.\n- Fire/smoke and vehicles.v2-release are supported by src/modules/vision_ai/dataset_prep.py.\n- Road obstacles, CNR context patches and pedestrian data are additional research data. A model/training configuration must be added before they are used in live verification.\n\nDo not use the archive to overwrite data directories. Extract it into a separate training-data folder.\n"""
manifest = {
    "bundle": "SENTINEL-AI extended training dataset",
    "created_utc": datetime.now(timezone.utc).isoformat(),
    "archive_policy": "Existing local sources only; no labels, files or performance claims were invented.",
    "sources": summary,
    "total_files": len(files),
    "required_for_live_pi_inference": False,
    "storage_note": "Allow at least 12 GB free space on the target computer or Raspberry Pi before extracting.",
}

# Most source material is already compressed media. Stored ZIP entries are much faster and avoid needless CPU load.
with zipfile.ZipFile(ZIP_PATH, "w", compression=zipfile.ZIP_STORED) as archive:
    archive.writestr("README_EXTENDED_DATASET.txt", readme)
    archive.writestr("DATASET_MANIFEST.json", json.dumps(manifest, indent=2))
    for path, archive_path in files:
        archive.write(path, archive_path)

print(json.dumps({"zip": str(ZIP_PATH), "files": len(files), "bytes": ZIP_PATH.stat().st_size, "sources": summary}, indent=2))
