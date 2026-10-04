"""
Module 2: Acoustic AI Classifier.
Loads the trained EdgeAcousticNet model (PyTorch) or operates in simulated mode.
Classes: ambulance, firetruck, police, traffic, glass_breaking, car_horn, crash.
"""
from pathlib import Path
from typing import Dict, Any, Optional
import numpy as np
import torch
import torch.nn as nn
from src.core.data_models import AudioPrediction
from src.modules.logging.logger import LOGGER
from src.config.model_profile import model_profile

BASE_DIR = Path(__file__).resolve().parents[3]
DEFAULT_MODEL_PATH = BASE_DIR / "models" / "acoustic_emergency_net.pt"


class EdgeAcousticNet(nn.Module):
    def __init__(self, num_classes=6):
        super().__init__()
        self.conv = nn.Sequential(
            nn.Conv2d(1, 16, kernel_size=3, padding=1),
            nn.BatchNorm2d(16),
            nn.ReLU(),
            nn.MaxPool2d(2, 2),
            nn.Conv2d(16, 32, kernel_size=3, padding=1),
            nn.BatchNorm2d(32),
            nn.ReLU(),
            nn.MaxPool2d(2, 2),
            nn.Conv2d(32, 64, kernel_size=3, padding=1),
            nn.BatchNorm2d(64),
            nn.ReLU(),
            nn.AdaptiveAvgPool2d((4, 4))
        )
        self.fc = nn.Sequential(
            nn.Linear(64 * 4 * 4, 48),
            nn.ReLU(),
            nn.Dropout(0.3),
            nn.Linear(48, num_classes)
        )

    def forward(self, x):
        feat = self.conv(x)
        feat = feat.view(feat.size(0), -1)
        return self.fc(feat)


class AudioClassifier:
    def __init__(self, model_path: Optional[str] = None):
        self.model_path = Path(model_path) if model_path else model_profile()['audio']
        self.model = None
        self.preprocessing = None
        self.label_mapping = {}
        self.classes = ["ambulance", "firetruck", "police", "traffic", "glass_breaking", "car_horn"]
        self._load_model()

    def _load_model(self):
        if self.model_path.exists():
            try:
                checkpoint = torch.load(str(self.model_path), map_location="cpu", weights_only=True)
                self.classes = checkpoint.get("classes", self.classes)
                self.preprocessing = checkpoint.get('preprocessing')
                self.label_mapping = checkpoint.get('label_mapping', {})
                self.model = EdgeAcousticNet(num_classes=len(self.classes))
                self.model.load_state_dict(checkpoint["model_state_dict"])
                self.model.eval()
                LOGGER.info(f"AudioClassifier: Successfully loaded trained weights from {self.model_path.name} (Classes: {self.classes})")
            except Exception as e:
                if model_profile()['name'] != 'legacy':
                    raise RuntimeError(f'Unable to load configured acoustic model: {self.model_path}') from e
                LOGGER.warning(f"AudioClassifier: Failed loading weights ({e}), falling back to interface mode.")
                self.model = None
        else:
            if model_profile()['name'] != 'legacy':
                raise FileNotFoundError(self.model_path)
            LOGGER.info("AudioClassifier: No weights file found; operating in software interface mode.")

    def predict_tensor(self, spec_tensor: torch.Tensor) -> AudioPrediction:
        """Runs PyTorch inference on spectrogram tensor: [1, 1, 128, 63]."""
        if (not isinstance(spec_tensor, torch.Tensor) or spec_tensor.ndim != 4
                or spec_tensor.shape[:2] != (1, 1) or not torch.isfinite(spec_tensor).all()):
            raise ValueError('Expected a finite spectrogram batch with shape [1, 1, frequency, time]')
        if self.preprocessing and tuple(spec_tensor.shape[2:]) != (128, 126):
            raise ValueError('Spectrogram shape does not match checkpoint preprocessing')
        if self.model is None:
            return AudioPrediction(class_name="traffic", confidence=0.85)

        with torch.no_grad():
            logits = self.model(spec_tensor)
            probs = torch.softmax(logits, dim=1).squeeze(0)
            pred_idx = probs.argmax().item()
            conf = probs[pred_idx].item()
            cname = self.label_mapping.get(self.classes[pred_idx], self.classes[pred_idx])

        return AudioPrediction(class_name=cname, confidence=round(conf, 4))

    def predict_file(self, path) -> AudioPrediction:
        return self.predict_tensor(self.features_for_file(path))

    def features_for_file(self, path):
        if self.preprocessing:
            from src.modules.audio_ai.features import file_features
            return file_features(path, self.preprocessing)
        # Legacy checkpoint was trained using this transform; retain its architecture.
        from src.training.train_acoustic_model import load_wav_as_tensor, compute_spectrogram
        if not Path(path).is_file():
            raise FileNotFoundError(path)
        return compute_spectrogram(load_wav_as_tensor(str(path))).unsqueeze(0)

    def predict_pcm(self, pcm_bytes: bytes, sample_rate: int = 16000) -> AudioPrediction:
        """Runs EdgeAcousticNet inference directly on raw 16-bit PCM bytes from microphone."""
        if self.preprocessing:
            from src.modules.audio_ai.features import pcm_features
            return self.predict_tensor(pcm_features(pcm_bytes, sample_rate, self.preprocessing))
        if not pcm_bytes or self.model is None:
            return AudioPrediction(class_name="traffic", confidence=0.85)
        try:
            import scipy.signal
            samples = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32)
            if len(samples) == 0:
                return AudioPrediction(class_name="traffic", confidence=0.85)
            max_val = np.max(np.abs(samples)) or 1.0
            samples = samples / max_val

            target_len = 32000
            if len(samples) < target_len:
                samples = np.pad(samples, (0, target_len - len(samples)), mode="constant")
            else:
                samples = samples[:target_len]

            f, t, Zxx = scipy.signal.stft(samples, nperseg=512, noverlap=256)
            mag = np.log1p(np.abs(Zxx))
            spec = scipy.signal.resample(mag[:128, :], 64, axis=1)
            if spec.shape[0] < 128:
                spec = np.pad(spec, ((0, 128 - spec.shape[0]), (0, 0)), mode="edge")
            else:
                spec = spec[:128, :]

            s_min, s_max = spec.min(), spec.max()
            if (s_max - s_min) > 0:
                spec = (spec - s_min) / (s_max - s_min)

            tensor = torch.from_numpy(spec.astype(np.float32)).unsqueeze(0).unsqueeze(0)
            return self.predict_tensor(tensor)
        except Exception as e:
            LOGGER.debug(f"PCM spectrogram conversion error: {e}")
            return AudioPrediction(class_name="traffic", confidence=0.85)

    def predict(self, prediction_dict: Dict[str, Any]) -> AudioPrediction:
        """Accepts standardized dictionary and returns typed AudioPrediction."""
        cname = prediction_dict.get("class", "traffic")
        conf = float(prediction_dict.get("confidence", 0.80))
        return AudioPrediction(class_name=cname, confidence=conf)
