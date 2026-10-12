"""Package the repository's existing audio and vision datasets without modifying them."""
from pathlib import Path
from collections import Counter
from datetime import datetime, timezone
import json, zipfile

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "exports"
OUT.mkdir(exist_ok=True)
ZIP = OUT / "sentinel_ai_existing_dataset_bundle.zip"
sources = [(ROOT / "data" / "audio_dataset", "audio_dataset"), (ROOT / "data" / "new_dataset", "vision_dataset")]
files = []
for src, arc_root in sources:
    for p in src.rglob("*"):
        if p.is_file(): files.append((p, f"{arc_root}/{p.relative_to(src).as_posix()}"))
manifest = {
    "bundle": "SENTINEL-AI existing dataset bundle",
    "created_utc": datetime.now(timezone.utc).isoformat(),
    "source_policy": "Copied from existing repository data; source files were not modified.",
    "audio": {"source": "data/audio_dataset", "classes": sorted({p.parent.name for p,_ in files if _.startswith("audio_dataset/")}), "files": sum(1 for _,a in files if a.startswith("audio_dataset/"))},
    "vision": {"source": "data/new_dataset", "subsets": sorted({a.split('/')[1] for _,a in files if a.startswith('vision_dataset/') and len(a.split('/')) > 1}), "files": sum(1 for _,a in files if a.startswith("vision_dataset/"))},
    "phases": {"phase_1_audio": "Audio classes are determined from existing directory names; inspect labels before training.", "phase_2_vision": "Existing vision data is packaged as fire_smoke, vehicle and raw; accident, obstacle, Traffic-Net and CNR-EXT are not claimed unless present.", "phase_3_sensor": "No large external sensor dataset is included; physical sensor evidence is runtime data."},
    "notes": ["Synthetic/research data must remain labeled according to the project model registry.", "MQ-2 values are raw ADC/context unless calibrated.", "Run the existing dataset preparation scripts before training."],
}
readme = """SENTINEL-AI EXISTING DATASET BUNDLE\n\nThis archive contains only data already present in the Edge-AI repository.\n\nContents:\n- audio_dataset/: existing audio class folders used by the audio preparation pipeline.\n- vision_dataset/: existing data/new_dataset contents (fire_smoke, vehicle and raw).\n- DATASET_MANIFEST.json: provenance and counts.\n\nPhase guidance:\n1. Audio: clean/verify, combine, split, train, evaluate, then test INMP441 live inference.\n2. Vision: use the existing fire_smoke and vehicle data for camera verification. Accident, road-obstacle, Traffic-Net and CNR-EXT data were not found in the repository and are not invented here.\n3. Sensors: MPU6050, DHT22, MQ-2 and GPS provide runtime physical evidence; no external bulk dataset is required.\n\nThe archive does not contain credentials, model weights or generated databases.\n"""
with zipfile.ZipFile(ZIP, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as z:
    z.writestr("README_DATASET_BUNDLE.txt", readme)
    z.writestr("DATASET_MANIFEST.json", json.dumps(manifest, indent=2))
    for p, arc in files: z.write(p, arc)
print(json.dumps({"zip": str(ZIP), "files": len(files), "bytes": ZIP.stat().st_size}))
