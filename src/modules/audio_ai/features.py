"""Versioned acoustic transform shared by new training, files, and live PCM."""
from math import gcd
import numpy as np
import soundfile as sf
import torch
from scipy.signal import resample_poly

DEFAULT_FEATURES = {'version': 1, 'sample_rate': 16000, 'duration_s': 4.0,
                    'n_fft': 512, 'hop_length': 512, 'frequency_bins': 128,
                    'transform': 'log_power_stft', 'normalization': 'per_clip_minmax'}


def waveform_features(samples, sample_rate, config=None):
    config = config or DEFAULT_FEATURES
    if config != DEFAULT_FEATURES:
        raise ValueError('Unsupported acoustic preprocessing configuration')
    samples = np.asarray(samples, dtype=np.float32)
    if samples.ndim == 2:
        samples = samples.mean(axis=1)
    if samples.ndim != 1 or not len(samples) or not np.isfinite(samples).all():
        raise ValueError('Expected nonempty finite mono/stereo audio')
    if not isinstance(sample_rate, (int, np.integer)) or sample_rate <= 0:
        raise ValueError('sample_rate must be a positive integer')
    target = config['sample_rate']
    if sample_rate != target:
        factor = gcd(int(sample_rate), target)
        samples = resample_poly(samples, target//factor, int(sample_rate)//factor)
    length = int(target * config['duration_s'])
    samples = np.pad(samples[:length], (0, max(0, length-len(samples))))
    peak = np.abs(samples).max()
    if peak > 0:
        samples = samples / peak
    x = torch.from_numpy(samples.copy())
    spectrum = torch.stft(x, n_fft=config['n_fft'], hop_length=config['hop_length'],
                          window=torch.hann_window(config['n_fft']), return_complex=True)
    power = spectrum[:config['frequency_bins']].abs().square()
    feature = 10 * torch.log10(power + 1e-6)
    feature = (feature-feature.min())/(feature.max()-feature.min()).clamp_min(1e-6)
    return feature.unsqueeze(0).unsqueeze(0)


def file_features(path, config=None):
    samples, sr = sf.read(str(path), dtype='float32', always_2d=True)
    return waveform_features(samples, sr, config)


def pcm_features(pcm_bytes, sample_rate=16000, config=None):
    if not isinstance(pcm_bytes, bytes) or not pcm_bytes or len(pcm_bytes) % 2:
        raise ValueError('Expected nonempty little-endian signed 16-bit mono PCM')
    samples = np.frombuffer(pcm_bytes, dtype='<i2').astype(np.float32)/32768
    return waveform_features(samples, sample_rate, config)
