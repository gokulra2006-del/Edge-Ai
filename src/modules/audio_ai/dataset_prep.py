"""
Audio AI Step 1: Dataset Preparation Script
============================================
Beginner Explanation:
---------------------
Computers cannot directly "hear" sound. Sound waves in audio files are continuous vibrations.
In this script, we:
1. Load audio recordings (.wav) from sireNNet and ESC-50 using Librosa.
2. Standardize sample rate to 16,000 Hz (16 kHz is optimal for edge devices).
3. Standardize duration to 2.0 seconds (32,000 audio samples).
4. Convert audio waves into a "Mel-Spectrogram": a 2D heat-map image showing which sound
   frequencies are loud at each millisecond in time.
5. Save the prepared data into train, validation, and test splits in a fast .npz file.
"""
import os
import sys
import random
import csv
from pathlib import Path
import numpy as np
import librosa

BASE_DIR = Path(__file__).resolve().parents[3]
DATA_OUT_PATH = BASE_DIR / "data" / "audio_processed.npz"

# Canonical target emergency audio classes
CLASSES = [
    "normal_traffic",
    "ambulance_siren",
    "firetruck_siren",
    "police_siren",
    "breaking_glass",
    "car_horn"
]
TARGET_SR = 16000          # 16 kHz sample rate
DURATION_SEC = 2.0         # 2 seconds window
TOTAL_SAMPLES = int(TARGET_SR * DURATION_SEC)  # 32,000 raw audio samples
N_MELS = 64                # Number of frequency bands
N_FFT = 1024
HOP_LENGTH = 512           # Yields ~63 time frames


def extract_mel_spectrogram(file_path: str) -> np.ndarray:
    """
    Loads audio with Librosa, pads/trims to 2.0s, and computes Log-Mel Spectrogram [64, 63].
    """
    try:
        # 1. Load audio with librosa (automatically converts stereo to mono and resamples)
        y, sr = librosa.load(file_path, sr=TARGET_SR, mono=True)

        # 2. Pad with silence if too short, or trim if too long
        if len(y) < TOTAL_SAMPLES:
            y = np.pad(y, (0, TOTAL_SAMPLES - len(y)), mode="constant")
        else:
            y = y[:TOTAL_SAMPLES]

        # 3. Compute Mel Spectrogram using Librosa
        mel_spec = librosa.feature.melspectrogram(
            y=y,
            sr=TARGET_SR,
            n_fft=N_FFT,
            hop_length=HOP_LENGTH,
            n_mels=N_MELS,
            fmin=50,
            fmax=7500
        )

        # 4. Convert power to decibels (log scale, matching human hearing)
        log_mel = librosa.power_to_db(mel_spec, ref=np.max)

        # 5. Normalize values between 0.0 and 1.0
        norm_mel = (log_mel - log_mel.min()) / (log_mel.max() - log_mel.min() + 1e-6)

        return norm_mel.astype(np.float32)
    except Exception as e:
        print(f"Error processing {file_path}: {e}")
        return np.zeros((N_MELS, 63), dtype=np.float32)


def collect_sound_files():
    """Gathers all audio file paths from sireNNet and ESC-50 datasets."""
    file_list = []

    # 1. sireNNet Dataset
    siren_map = {
        "traffic": "normal_traffic",
        "ambulance": "ambulance_siren",
        "firetruck": "firetruck_siren",
        "police": "police_siren"
    }
    siren_base = BASE_DIR / "sireNNet" / "sireNNet"
    if not siren_base.exists():
        siren_base = BASE_DIR / "sireNNet"

    for src_folder, target_class in siren_map.items():
        cdir = siren_base / src_folder
        if cdir.exists():
            class_idx = CLASSES.index(target_class)
            for f in cdir.glob("*.wav"):
                file_list.append((str(f), class_idx))

    # 2. ESC-50 Dataset (Breaking glass & Car horn)
    esc_map = {
        "glass_breaking": "breaking_glass",
        "car_horn": "car_horn"
    }
    esc_csv = list((BASE_DIR / "ESC-50-master").glob("**/esc50.csv"))
    if esc_csv:
        csv_file = esc_csv[0]
        audio_dir = csv_file.parent.parent / "audio"
        with open(csv_file, "r", encoding="utf-8") as fl:
            reader = csv.DictReader(fl)
            for r in reader:
                cat = r["category"]
                if cat in esc_map:
                    target_class = esc_map[cat]
                    class_idx = CLASSES.index(target_class)
                    fpath = audio_dir / r["filename"]
                    if fpath.exists():
                        file_list.append((str(fpath), class_idx))

    random.seed(42)
    random.shuffle(file_list)
    return file_list


def prepare_dataset():
    print("=" * 65)
    print("STEP 1: AUDIO DATASET PREPARATION (Librosa Mel-Spectrograms)")
    print("=" * 65)

    files = collect_sound_files()
    print(f"Discovered {len(files)} sound files across {len(CLASSES)} classes: {CLASSES}")

    # Process all files
    X = []
    y = []
    print("Extracting features with Librosa...")
    for idx, (fpath, label) in enumerate(files):
        mel = extract_mel_spectrogram(fpath)
        X.append(mel)
        y.append(label)
        if (idx + 1) % 350 == 0 or (idx + 1) == len(files):
            print(f"  Processed {idx + 1}/{len(files)} audio recordings")

    X = np.array(X, dtype=np.float32)  # Shape: [N, 64, 63]
    y = np.array(y, dtype=np.int64)

    # 70% Train, 15% Validation, 15% Test
    n_total = len(X)
    n_train = int(0.70 * n_total)
    n_val = int(0.15 * n_total)

    X_train, y_train = X[:n_train], y[:n_train]
    X_val, y_val = X[n_train:n_train + n_val], y[n_train:n_train + n_val]
    X_test, y_test = X[n_train + n_val:], y[n_train + n_val:]

    print(f"\nDataset Splits Created:")
    print(f"  Train:      {len(X_train)} samples")
    print(f"  Validation: {len(X_val)} samples")
    print(f"  Test:       {len(X_test)} samples")
    print(f"  Feature Shape per sample: {X_train[0].shape} (Frequency bands x Time frames)")

    DATA_OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        DATA_OUT_PATH,
        X_train=X_train, y_train=y_train,
        X_val=X_val, y_val=y_val,
        X_test=X_test, y_test=y_test,
        classes=np.array(CLASSES)
    )
    print(f"\nPrepared dataset saved to: {DATA_OUT_PATH} ({os.path.getsize(DATA_OUT_PATH) / (1024*1024):.2f} MB)")
    print("Dataset preparation complete!")


if __name__ == "__main__":
    prepare_dataset()
