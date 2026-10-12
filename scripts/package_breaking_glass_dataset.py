"""Build a labelled glass-breaking augmentation package from existing WAV files."""
from array import array
from pathlib import Path
import csv
import json
import math
import random
import wave
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data" / "audio_dataset" / "breaking_glass"
OUT = ROOT / "exports" / "sentinel_ai_breaking_glass_training.zip"
STAGE = ROOT / "exports" / "breaking_glass_training_stage"


def read_wav(path):
    with wave.open(str(path), "rb") as w:
        if w.getnchannels() != 1 or w.getsampwidth() != 2:
            raise ValueError(f"Expected mono 16-bit PCM WAV: {path}")
        return w.getframerate(), array("h", w.readframes(w.getnframes()))


def write_wav(path, rate, samples):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
        w.writeframes(samples.tobytes())


def transform(samples, mode, seed):
    rng = random.Random(seed)
    values = list(samples)
    if mode == "gain_low": factor = 0.72; noise = 0
    elif mode == "gain_high": factor = 1.28; noise = 0
    elif mode == "noise": factor = 1.0; noise = 900
    else: factor = 1.0; noise = 0
    shift = int(len(values) * 0.017) if mode == "shift" else 0
    if shift: values = values[shift:] + [0] * shift
    out = array("h")
    for value in values:
        sample = value * factor + (rng.gauss(0, noise) if noise else 0)
        out.append(max(-32768, min(32767, int(sample))))
    return out


def main():
    files = sorted(SOURCE.glob("*.wav"))
    if not files:
        raise SystemExit(f"No WAV files found in {SOURCE}")
    if STAGE.exists():
        for p in sorted(STAGE.rglob("*"), reverse=True):
            if p.is_file(): p.unlink()
            elif p.is_dir(): p.rmdir()
    (STAGE / "original").mkdir(parents=True, exist_ok=True)
    (STAGE / "augmented").mkdir(parents=True, exist_ok=True)
    rows = []
    modes = ("gain_low", "gain_high", "noise", "shift")
    for source in files:
        rate, samples = read_wav(source)
        original = STAGE / "original" / source.name
        original.write_bytes(source.read_bytes())
        rows.append([str(original.relative_to(STAGE)), "breaking_glass", "REAL_DATASET", source.name, "original"])
        for index, mode in enumerate(modes):
            target = STAGE / "augmented" / f"{source.stem}__{mode}.wav"
            write_wav(target, rate, transform(samples, mode, index + len(source.name)),)
            rows.append([str(target.relative_to(STAGE)), "breaking_glass", "SYNTHETIC_AUGMENTATION", source.name, mode])
    with (STAGE / "labels.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f); writer.writerow(["file", "label", "provenance", "source_file", "transform"]); writer.writerows(rows)
    manifest = {"class": "breaking_glass", "original_files": len(files), "augmented_files": len(files) * len(modes), "total_files": len(rows), "augmentation": list(modes), "warning": "Augmented files are SYNTHETIC_AUGMENTATION and must not be counted as independent real-world test data."}
    (STAGE / "DATASET_MANIFEST.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as z:
        for p in STAGE.rglob("*"):
            if p.is_file(): z.write(p, p.relative_to(STAGE).as_posix())
    print(json.dumps({"zip": str(OUT), **manifest}, indent=2))


if __name__ == "__main__": main()
