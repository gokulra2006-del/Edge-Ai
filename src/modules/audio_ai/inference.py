"""
Audio AI Step 5: Inference Script
==================================
Beginner Explanation:
---------------------
This script is what runs in real time on the edge node / Raspberry Pi 4:
1. An audio file (.wav) or live microphone buffer is passed in.
2. Librosa converts the sound wave into a Mel-Spectrogram in real-time.
3. The trained EdgeAudioCNN model processes the spectrogram in ~2 milliseconds.
4. It outputs the predicted class (e.g. "ambulance_siren") and confidence score (e.g. 96.4%).
"""
import sys
import time
from pathlib import Path
import numpy as np
import torch
import librosa

BASE_DIR = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(BASE_DIR))
MODEL_PATH = BASE_DIR / "models" / "audio" / "best_model.pt"

from src.modules.audio_ai.train import EdgeAudioCNN
from src.modules.audio_ai.dataset_prep import extract_mel_spectrogram


class AudioInferenceEngine:
    def __init__(self, model_path: Path = MODEL_PATH):
        self.model_path = model_path
        self.classes = []
        self.model = None
        self._load()

    def _load(self):
        if not self.model_path.exists():
            raise FileNotFoundError(f"Model file not found at {self.model_path}")

        checkpoint = torch.load(str(self.model_path), map_location="cpu", weights_only=False)
        self.classes = checkpoint["classes"]
        self.model = EdgeAudioCNN(num_classes=len(self.classes))
        self.model.load_state_dict(checkpoint["model_state_dict"])
        self.model.eval()

    def predict_file(self, wav_path: str):
        """
        Runs complete inference pipeline on a single WAV file.
        Returns: predicted_class, confidence, probability_dict, latency_ms
        """
        t0 = time.perf_counter()

        # 1. Feature Extraction (Librosa Mel-Spectrogram)
        mel_spec = extract_mel_spectrogram(wav_path)
        input_tensor = torch.tensor(mel_spec).unsqueeze(0).unsqueeze(0)  # Shape: [1, 1, 64, 63]

        # 2. Model Forward Pass
        with torch.no_grad():
            logits = self.model(input_tensor)
            probabilities = torch.softmax(logits, dim=1).squeeze(0).numpy()

        latency_ms = (time.perf_counter() - t0) * 1000.0

        # 3. Format Output
        pred_idx = int(np.argmax(probabilities))
        pred_class = self.classes[pred_idx]
        confidence = float(probabilities[pred_idx])

        all_probs = {self.classes[i]: round(float(probabilities[i]), 4) for i in range(len(self.classes))}

        return {
            "predicted_class": pred_class,
            "confidence": round(confidence, 4),
            "probabilities": all_probs,
            "latency_ms": round(latency_ms, 2)
        }


def main():
    print("=" * 65)
    print("STEP 5: AUDIO AI INFERENCE TEST")
    print("=" * 65)

    engine = AudioInferenceEngine()
    print(f"Loaded model: {MODEL_PATH.name} (Supported classes: {engine.classes})")

    # Pick sample files to test live
    sample_files = [
        ("Ambulance Siren", list((BASE_DIR / "sireNNet").glob("**/sound_1.wav"))),
        ("Firetruck Siren", list((BASE_DIR / "sireNNet").glob("**/sound_201.wav"))),
        ("Police Siren", list((BASE_DIR / "sireNNet").glob("**/sound_601.wav"))),
        ("Normal Traffic", list((BASE_DIR / "sireNNet").glob("**/sound_401.wav"))),
        ("Breaking Glass", list((BASE_DIR / "ESC-50-master").glob("**/1-100038-A-14.wav")))
    ]

    for label, files in sample_files:
        if files:
            target_wav = str(files[0])
            result = engine.predict_file(target_wav)
            print(f"\nTesting: {label} ({files[0].name})")
            print(f"  -> Prediction:  {result['predicted_class'].upper()}")
            print(f"  -> Confidence:  {result['confidence'] * 100:.2f}%")
            print(f"  -> Latency:     {result['latency_ms']:.2f} ms (Audio feature extraction + inference)")
            print(f"  -> Distribution: {result['probabilities']}")


if __name__ == "__main__":
    main()
