"""
Hardware Driver: INMP441 I2S MEMS Omnidirectional Microphone.
==============================================================
Physical Interface: Raspberry Pi I2S Audio Bus

Connections:
- VDD -> 3.3V
- GND -> GND
- SCK (Serial Clock)     = GPIO 18 / Physical Pin 12
- WS  (Word Select)      = GPIO 19 / Physical Pin 35
- SD  (Serial Data)      = GPIO 20 / Physical Pin 38
- L/R -> GND (selects Left Channel)

This is I2S, NOT a normal GPIO input. The Raspberry Pi kernel must have
the I2S overlay enabled for the INMP441 to appear as an ALSA audio device.

Required Raspberry Pi Configuration (/boot/config.txt):
    dtparam=i2s=on
    # If using a specific I2S sound card overlay:
    # dtoverlay=i2s-mmap
    # dtoverlay=googlevoicehat-soundcard   (or equivalent I2S overlay)

After enabling, reboot and verify with: arecord -l
The INMP441 should appear as an ALSA capture device.

Only ONE INMP441 is configured. The second module is NOT active.
"""
import logging
import math
import os
import random
import struct
import time
import wave
from typing import Any, Dict, Optional
from src.modules.hardware.base_driver import BaseHardwareDriver, DriverStatus

logger = logging.getLogger("EdgeAI")

# Audio parameters for INMP441
SAMPLE_RATE = 16000     # 16 kHz sample rate
CHANNELS = 1            # Mono (L/R pin tied to GND = left channel)
SAMPLE_WIDTH = 2        # 16-bit (2 bytes per sample)
CHUNK_SIZE = 1024       # Frames per buffer


class INMP441Driver(BaseHardwareDriver):
    """
    I2S MEMS microphone driver with real audio capture and RMS level metering.
    """

    def __init__(self):
        super().__init__("INMP441_I2S", "Acoustic_MEMS_Microphone")
        self._pyaudio = None
        self._stream = None
        self._input_device_index = None
        self._last_rms = 0.0
        self._last_db = 0.0
        self.initialize()

    def initialize(self) -> bool:
        """Detects I2S audio input device."""
        try:
            import pyaudio
            self._pyaudio = pyaudio.PyAudio()

            # Scan for I2S or default input device
            best_device = None
            for i in range(self._pyaudio.get_device_count()):
                info = self._pyaudio.get_device_info_by_index(i)
                if info.get("maxInputChannels", 0) > 0:
                    name = info.get("name", "").lower()
                    # Prefer I2S-specific devices
                    if any(k in name for k in ("i2s", "inmp", "snd_rpi")):
                        best_device = i
                        break
                    # Fall back to any capture device
                    if best_device is None:
                        best_device = i

            if best_device is not None:
                self._input_device_index = best_device
                device_name = self._pyaudio.get_device_info_by_index(best_device).get("name", "unknown")
                logger.info(f"[INMP441] Audio input device found: [{best_device}] {device_name}")
                self.status = DriverStatus.ONLINE
                self.is_simulated = False
                self.error_message = None
                return True
            else:
                self.error_message = "No audio input device found. Check I2S overlay in /boot/config.txt"

        except ImportError:
            self.error_message = (
                "pyaudio not installed. Install with:\n"
                "  sudo apt install portaudio19-dev\n"
                "  pip install pyaudio"
            )
        except Exception as e:
            self.error_message = f"I2S microphone ALSA interface error: {e}"

        self.status = DriverStatus.NOT_DETECTED
        self.is_simulated = True
        return False

    def _open_stream(self):
        """Opens an audio capture stream (lazy initialization)."""
        if self._stream is not None:
            return True

        if self._pyaudio is None or self._input_device_index is None:
            return False

        try:
            import pyaudio
            self._stream = self._pyaudio.open(
                format=pyaudio.paInt16,
                channels=CHANNELS,
                rate=SAMPLE_RATE,
                input=True,
                input_device_index=self._input_device_index,
                frames_per_buffer=CHUNK_SIZE,
            )
            return True
        except Exception as e:
            self.error_message = f"Failed to open audio stream: {e}"
            self.status = DriverStatus.DEGRADED
            return False

    def _compute_rms(self, audio_data: bytes) -> float:
        """Computes RMS amplitude from raw PCM16 audio bytes."""
        if not audio_data:
            return 0.0

        # Unpack 16-bit signed integers
        num_samples = len(audio_data) // SAMPLE_WIDTH
        if num_samples == 0:
            return 0.0

        fmt = f"<{num_samples}h"  # Little-endian, signed short
        try:
            samples = struct.unpack(fmt, audio_data[:num_samples * SAMPLE_WIDTH])
            # Compute RMS
            sum_sq = sum(s * s for s in samples)
            rms = math.sqrt(sum_sq / num_samples)
            return rms
        except Exception:
            return 0.0

    def capture_audio(self, duration_seconds: float = 0.5) -> Optional[bytes]:
        """
        Captures raw PCM audio for the specified duration.

        Returns:
            Raw PCM bytes (16-bit signed, mono, 16kHz) or None on failure.
        """
        if self.is_simulated:
            return None

        if not self._open_stream():
            return None

        try:
            frames = []
            num_chunks = int(SAMPLE_RATE / CHUNK_SIZE * duration_seconds)
            for _ in range(max(1, num_chunks)):
                data = self._stream.read(CHUNK_SIZE, exception_on_overflow=False)
                frames.append(data)
            return b"".join(frames)
        except Exception as e:
            self.failure_count += 1
            self.error_message = f"Audio capture error: {e}"
            self.status = DriverStatus.DEGRADED
            return None

    def save_test_wav(self, filepath: str, duration_seconds: float = 2.0) -> bool:
        """
        Captures audio and saves it as a WAV file for testing.

        Args:
            filepath: Output WAV file path
            duration_seconds: Recording duration

        Returns:
            True if saved successfully
        """
        audio_data = self.capture_audio(duration_seconds)
        if audio_data is None:
            return False

        try:
            os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)
            with wave.open(filepath, "wb") as wf:
                wf.setnchannels(CHANNELS)
                wf.setsampwidth(SAMPLE_WIDTH)
                wf.setframerate(SAMPLE_RATE)
                wf.writeframes(audio_data)
            logger.info(f"[INMP441] Test WAV saved: {filepath} ({duration_seconds}s)")
            return True
        except Exception as e:
            self.error_message = f"WAV save error: {e}"
            return False

    def read(self) -> Dict[str, Any]:
        """Reads current audio level (RMS and dB)."""
        self.read_count += 1
        now = time.time()
        now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))

        if not self.is_simulated:
            audio_data = self.capture_audio(0.1)  # Short 100ms capture for level metering
            if audio_data:
                rms = self._compute_rms(audio_data)
                self._last_rms = rms
                # Convert to approximate dB (relative to full scale 32768)
                if rms > 0:
                    self._last_db = round(20 * math.log10(rms / 32768.0) + 96, 1)  # ~96dB dynamic range for 16-bit
                else:
                    self._last_db = 0.0
                self.last_read_time = now

                return {
                    "rms_amplitude": round(rms, 1),
                    "level_db": self._last_db,
                    "sample_rate_hz": SAMPLE_RATE,
                    "interface": "I2S_GPIO18_19_20",
                    "timestamp": now_iso,
                    "quality": {
                        "status": DriverStatus.ONLINE.value,
                        "is_simulated": False,
                        "source": "physical_inmp441_i2s"
                    }
                }
            else:
                self.failure_count += 1

        # Simulation Mode
        noise = random.uniform(-1.5, 2.5)
        sim_rms = round(500.0 + noise * 100, 1)
        sim_db = round(20 * math.log10(max(1, sim_rms) / 32768.0) + 96, 1)
        return {
            "rms_amplitude": sim_rms,
            "level_db": sim_db,
            "sample_rate_hz": SAMPLE_RATE,
            "interface": "I2S_GPIO18_19_20",
            "timestamp": now_iso,
            "quality": {
                "status": DriverStatus.SIMULATED.value,
                "is_simulated": True,
                "source": "simulated_inmp441"
            }
        }

    def cleanup(self):
        """Closes audio stream and PyAudio."""
        if self._stream:
            try:
                self._stream.stop_stream()
                self._stream.close()
            except Exception:
                pass
            self._stream = None

        if self._pyaudio:
            try:
                self._pyaudio.terminate()
            except Exception:
                pass
            self._pyaudio = None
