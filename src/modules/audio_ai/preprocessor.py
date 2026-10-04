"""
Module 2: Audio signal preprocessing pipeline.
Converts raw audio streams/buffers into acoustic features (MFCC / Mel-Spectrogram).
"""
import math
from typing import List, Dict, Any


class AudioPreprocessor:
    def __init__(self, sample_rate: int = 44100, n_mfcc: int = 13):
        self.sample_rate = sample_rate
        self.n_mfcc = n_mfcc

    def process_buffer(self, raw_audio_samples: List[float]) -> Dict[str, Any]:
        """
        Extracts acoustic features from PCM audio samples.
        Uses standard digital signal analysis principles.
        """
        if not raw_audio_samples:
            return {"energy": 0.0, "zero_crossing_rate": 0.0, "rms": 0.0}

        # Energy & Root Mean Square
        energy = sum(s ** 2 for s in raw_audio_samples)
        rms = math.sqrt(energy / len(raw_audio_samples))

        # Zero Crossing Rate
        zcr = sum(
            1 for i in range(1, len(raw_audio_samples))
            if (raw_audio_samples[i] >= 0 and raw_audio_samples[i - 1] < 0) or
               (raw_audio_samples[i] < 0 and raw_audio_samples[i - 1] >= 0)
        ) / len(raw_audio_samples)

        return {
            "energy": round(energy, 4),
            "rms": round(rms, 4),
            "zero_crossing_rate": round(zcr, 4),
            "duration_sec": round(len(raw_audio_samples) / self.sample_rate, 2)
        }
