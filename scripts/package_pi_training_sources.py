"""Package the datasets directly supported by the current SENTINEL-AI trainers."""
from datetime import datetime, timezone
from pathlib import Path
import json
import zipfile


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "exports" / "sentinel_ai_pi_training_sources.zip"

# These sources match the classes and YOLO layouts consumed by the current code.
SOURCES = (
    ("audio_dataset", ROOT / "data" / "audio_dataset", "Audio classes used by audio_ai/dataset_prep.py"),
    ("fire_smoke_yolo", ROOT / "FIRE n SMOKE DETECTION.v1i.yolov11", "Fire/smoke YOLO source used by vision_ai/dataset_prep.py"),
    ("vehicles_yolo", ROOT / "vehicles.v2-release.yolov11", "Vehicle YOLO source used by vision_ai/dataset_prep.py"),
)


def main() -> None:
    entries: list[tuple[Path, str]] = []
    sources = []
    for name, folder, purpose in SOURCES:
        if not folder.is_dir():
            raise FileNotFoundError(f"Required dataset is missing: {folder}")
        files = [path for path in folder.rglob("*") if path.is_file()]
        entries.extend((path, f"datasets/{name}/{path.relative_to(folder).as_posix()}") for path in files)
        sources.append({"directory": name, "source": str(folder.relative_to(ROOT)), "files": len(files), "bytes": sum(path.stat().st_size for path in files), "purpose": purpose})

    manifest = {
        "bundle": "SENTINEL-AI Pi training sources",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "provenance": "Existing labelled sources already in the Edge-AI workspace.",
        "required_for_live_inference": False,
        "usage": "Training, validation, and reproducible dataset preparation only.",
        "sources": sources,
        "excluded_for_separate_audit": [
            "ESC-50-master and sireNNet: class mapping and licensing must be verified before merge.",
            "Road_Obstacle_Detection, CNR-EXT-Patches-150x150, PennFudanPed: need a separate model/configuration before live use.",
        ],
    }
    readme = """SENTINEL-AI PI TRAINING SOURCES\n\nThis is the focused dataset package for the current project trainers. It contains audio classes, fire/smoke YOLO data, and vehicle YOLO data already present in the project. It is not needed to run live inference on the Raspberry Pi; use the deployment ZIP for that.\n\nExtract into a separate training-data directory. Do not overwrite the project data directory. Keep each source separate until class IDs and dataset YAML paths are reviewed. Do not claim accuracy or real-hardware validation from this archive alone.\n"""
    with zipfile.ZipFile(OUTPUT, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("README.txt", readme)
        archive.writestr("DATASET_MANIFEST.json", json.dumps(manifest, indent=2))
        for source, target in entries:
            archive.write(source, target)
    print(json.dumps({"zip": str(OUTPUT), "files": len(entries), "bytes": OUTPUT.stat().st_size, "sources": sources}, indent=2))


if __name__ == "__main__":
    main()
