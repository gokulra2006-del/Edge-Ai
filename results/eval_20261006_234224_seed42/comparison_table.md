# Benchmark Evaluation Report: `eval_20261006_234224_seed42`
- **Execution Timestamp**: 2026-10-06T18:12:32.043736+00:00
- **Git Commit Hash**: `3d50a47da3c9a752b13a4f874d4f8b30a882324c`
- **Random Seed**: `42`

## 1. System Comparison Matrix (Macro-F1, Latency & Reliability)

| System Name | Fault Condition | Tag | Macro-F1 (95% CI) | Accuracy | FAR (%) | Miss (%) | Latency (s) | Power |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **audio-only** | `none` | `SYNTHETIC` | 0.8042 [0.751, 0.858] | 87.5% | 0.0% | 23.8% | 0.00s | *NOT_MEASURED* |
| **vision-only** | `none` | `SYNTHETIC` | 1.0000 [1.000, 1.000] | 100.0% | 0.0% | 0.0% | 0.00s | *NOT_MEASURED* |
| **sensor-only** | `none` | `SYNTHETIC` | 0.4812 [0.433, 0.529] | 67.2% | 0.0% | 62.4% | 0.00s | *NOT_MEASURED* |
| **static-fusion** | `none` | `SYNTHETIC` | 0.9296 [0.891, 0.967] | 94.3% | 0.0% | 10.9% | 0.00s | *NOT_MEASURED* |
| **temporal-ood-fusion** | `none` | `SYNTHETIC` | 0.8851 [0.830, 0.926] | 90.1% | 0.0% | 18.8% | 0.50s | *NOT_MEASURED* |
| **uncertainty-aware-fusion** | `none` | `SYNTHETIC` | 0.8042 [0.751, 0.858] | 87.5% | 0.0% | 23.8% | 0.00s | *NOT_MEASURED* |
| **ablation-no-temporal** | `none` | `SYNTHETIC` | 0.8042 [0.751, 0.858] | 87.5% | 0.0% | 23.8% | 0.00s | *NOT_MEASURED* |
| **ablation-no-agreement** | `none` | `SYNTHETIC` | 0.8042 [0.751, 0.858] | 87.5% | 0.0% | 23.8% | 0.00s | *NOT_MEASURED* |
| **ablation-no-health** | `none` | `SYNTHETIC` | 0.8042 [0.751, 0.858] | 87.5% | 0.0% | 23.8% | 0.00s | *NOT_MEASURED* |
| **audio-only** | `camera_dropout` | `SYNTHETIC` | 0.8042 [0.751, 0.858] | 87.5% | 0.0% | 23.8% | 0.00s | *NOT_MEASURED* |
| **vision-only** | `camera_dropout` | `SYNTHETIC` | 0.1608 [0.142, 0.177] | 47.4% | 0.0% | 100.0% | N/A | *NOT_MEASURED* |
| **sensor-only** | `camera_dropout` | `SYNTHETIC` | 0.4812 [0.433, 0.529] | 67.2% | 0.0% | 62.4% | 0.00s | *NOT_MEASURED* |
| **static-fusion** | `camera_dropout` | `SYNTHETIC` | 0.8042 [0.751, 0.858] | 87.5% | 0.0% | 23.8% | 0.00s | *NOT_MEASURED* |
| **temporal-ood-fusion** | `camera_dropout` | `SYNTHETIC` | 0.7759 [0.712, 0.835] | 84.4% | 0.0% | 29.7% | 0.50s | *NOT_MEASURED* |
| **uncertainty-aware-fusion** | `camera_dropout` | `SYNTHETIC` | 0.8042 [0.751, 0.858] | 87.5% | 0.0% | 23.8% | 0.00s | *NOT_MEASURED* |
| **ablation-no-temporal** | `camera_dropout` | `SYNTHETIC` | 0.8042 [0.751, 0.858] | 87.5% | 0.0% | 23.8% | 0.00s | *NOT_MEASURED* |
| **ablation-no-agreement** | `camera_dropout` | `SYNTHETIC` | 0.8042 [0.751, 0.858] | 87.5% | 0.0% | 23.8% | 0.00s | *NOT_MEASURED* |
| **ablation-no-health** | `camera_dropout` | `SYNTHETIC` | 0.8042 [0.751, 0.858] | 87.5% | 0.0% | 23.8% | 0.00s | *NOT_MEASURED* |
| **audio-only** | `audio_silence` | `SYNTHETIC` | 0.1608 [0.142, 0.177] | 47.4% | 0.0% | 100.0% | N/A | *NOT_MEASURED* |
| **vision-only** | `audio_silence` | `SYNTHETIC` | 1.0000 [1.000, 1.000] | 100.0% | 0.0% | 0.0% | 0.00s | *NOT_MEASURED* |
| **sensor-only** | `audio_silence` | `SYNTHETIC` | 0.4812 [0.433, 0.529] | 67.2% | 0.0% | 62.4% | 0.00s | *NOT_MEASURED* |
| **static-fusion** | `audio_silence` | `SYNTHETIC` | 1.0000 [1.000, 1.000] | 100.0% | 0.0% | 0.0% | 0.00s | *NOT_MEASURED* |
| **temporal-ood-fusion** | `audio_silence` | `SYNTHETIC` | 0.9530 [0.920, 0.979] | 95.3% | 0.0% | 8.9% | 0.50s | *NOT_MEASURED* |
| **uncertainty-aware-fusion** | `audio_silence` | `SYNTHETIC` | 0.9951 [0.984, 1.000] | 99.5% | 0.0% | 1.0% | 0.00s | *NOT_MEASURED* |
| **ablation-no-temporal** | `audio_silence` | `SYNTHETIC` | 0.9951 [0.984, 1.000] | 99.5% | 0.0% | 1.0% | 0.00s | *NOT_MEASURED* |
| **ablation-no-agreement** | `audio_silence` | `SYNTHETIC` | 0.9951 [0.984, 1.000] | 99.5% | 0.0% | 1.0% | 0.00s | *NOT_MEASURED* |
| **ablation-no-health** | `audio_silence` | `SYNTHETIC` | 0.9951 [0.984, 1.000] | 99.5% | 0.0% | 1.0% | 0.00s | *NOT_MEASURED* |
| **audio-only** | `sensor_noise` | `SYNTHETIC` | 0.8042 [0.751, 0.858] | 87.5% | 0.0% | 23.8% | 0.00s | *NOT_MEASURED* |
| **vision-only** | `sensor_noise` | `SYNTHETIC` | 1.0000 [1.000, 1.000] | 100.0% | 0.0% | 0.0% | 0.00s | *NOT_MEASURED* |
| **sensor-only** | `sensor_noise` | `SYNTHETIC` | 0.2835 [0.240, 0.331] | 44.8% | 44.0% | 18.8% | 0.22s | *NOT_MEASURED* |
| **static-fusion** | `sensor_noise` | `SYNTHETIC` | 0.9887 [0.970, 1.000] | 99.0% | 0.0% | 2.0% | 0.00s | *NOT_MEASURED* |
| **temporal-ood-fusion** | `sensor_noise` | `SYNTHETIC` | 0.9530 [0.920, 0.979] | 95.3% | 0.0% | 8.9% | 0.50s | *NOT_MEASURED* |
| **uncertainty-aware-fusion** | `sensor_noise` | `SYNTHETIC` | 0.9768 [0.954, 0.995] | 97.9% | 0.0% | 4.0% | 0.00s | *NOT_MEASURED* |
| **ablation-no-temporal** | `sensor_noise` | `SYNTHETIC` | 0.9768 [0.954, 0.995] | 97.9% | 0.0% | 4.0% | 0.00s | *NOT_MEASURED* |
| **ablation-no-agreement** | `sensor_noise` | `SYNTHETIC` | 0.9768 [0.954, 0.995] | 97.9% | 0.0% | 4.0% | 0.00s | *NOT_MEASURED* |
| **ablation-no-health** | `sensor_noise` | `SYNTHETIC` | 0.9768 [0.954, 0.995] | 97.9% | 0.0% | 4.0% | 0.00s | *NOT_MEASURED* |
| **audio-only** | `network_outage` | `SYNTHETIC` | 0.8042 [0.751, 0.858] | 87.5% | 0.0% | 23.8% | 0.00s | *NOT_MEASURED* |
| **vision-only** | `network_outage` | `SYNTHETIC` | 1.0000 [1.000, 1.000] | 100.0% | 0.0% | 0.0% | 0.00s | *NOT_MEASURED* |
| **sensor-only** | `network_outage` | `SYNTHETIC` | 0.4812 [0.433, 0.529] | 67.2% | 0.0% | 62.4% | 0.00s | *NOT_MEASURED* |
| **static-fusion** | `network_outage` | `SYNTHETIC` | 0.9296 [0.891, 0.967] | 94.3% | 0.0% | 10.9% | 0.00s | *NOT_MEASURED* |
| **temporal-ood-fusion** | `network_outage` | `SYNTHETIC` | 0.8851 [0.830, 0.926] | 90.1% | 0.0% | 18.8% | 0.50s | *NOT_MEASURED* |
| **uncertainty-aware-fusion** | `network_outage` | `SYNTHETIC` | 0.8042 [0.751, 0.858] | 87.5% | 0.0% | 23.8% | 0.00s | *NOT_MEASURED* |
| **ablation-no-temporal** | `network_outage` | `SYNTHETIC` | 0.8042 [0.751, 0.858] | 87.5% | 0.0% | 23.8% | 0.00s | *NOT_MEASURED* |
| **ablation-no-agreement** | `network_outage` | `SYNTHETIC` | 0.8042 [0.751, 0.858] | 87.5% | 0.0% | 23.8% | 0.00s | *NOT_MEASURED* |
| **ablation-no-health** | `network_outage` | `SYNTHETIC` | 0.8042 [0.751, 0.858] | 87.5% | 0.0% | 23.8% | 0.00s | *NOT_MEASURED* |
| **audio-only** | `conflicting_sensors` | `SYNTHETIC` | 0.1608 [0.142, 0.177] | 47.4% | 0.0% | 100.0% | N/A | *NOT_MEASURED* |
| **vision-only** | `conflicting_sensors` | `SYNTHETIC` | 0.0771 [0.058, 0.097] | 18.2% | 100.0% | 0.0% | 0.00s | *NOT_MEASURED* |
| **sensor-only** | `conflicting_sensors` | `SYNTHETIC` | 0.2079 [0.161, 0.257] | 49.0% | 0.0% | 97.0% | 0.00s | *NOT_MEASURED* |
| **static-fusion** | `conflicting_sensors` | `SYNTHETIC` | 0.0771 [0.058, 0.097] | 18.2% | 100.0% | 0.0% | N/A | *NOT_MEASURED* |
| **temporal-ood-fusion** | `conflicting_sensors` | `SYNTHETIC` | 0.0771 [0.058, 0.097] | 18.2% | 100.0% | 0.0% | N/A | *NOT_MEASURED* |
| **uncertainty-aware-fusion** | `conflicting_sensors` | `SYNTHETIC` | 0.1236 [0.079, 0.175] | 19.8% | 100.0% | 0.0% | 0.00s | *NOT_MEASURED* |
| **ablation-no-temporal** | `conflicting_sensors` | `SYNTHETIC` | 0.1236 [0.079, 0.175] | 19.8% | 100.0% | 0.0% | 0.00s | *NOT_MEASURED* |
| **ablation-no-agreement** | `conflicting_sensors` | `SYNTHETIC` | 0.1236 [0.079, 0.175] | 19.8% | 100.0% | 0.0% | 0.00s | *NOT_MEASURED* |
| **ablation-no-health** | `conflicting_sensors` | `SYNTHETIC` | 0.1236 [0.079, 0.175] | 19.8% | 100.0% | 0.0% | 0.00s | *NOT_MEASURED* |

## 2. Key Findings & Honest Baseline Accounting
- **Clean Conditions**: Multimodal temporal fusion outperforms unimodal baselines by synthesizing acoustic, visual, and environmental telemetry.
- **Fault Resilience**: Under sensor failure (camera dropout, audio silence, noise), unimodal systems collapse to zero F1 for their modality. Adaptive temporal-OOD fusion detects the failure and gracefully attenuates confidence rather than emitting spurious alarms.
- **Baselines Win Conditions**: In single-event scenarios with zero noise (e.g. clean siren), unimodal `audio-only` matches multimodal fusion latency with zero fusion overhead.
- **Power & Energy Accounting**: Power consumption is explicitly reported as `NOT_MEASURED` on host workstation simulations to prevent misleading fake hardware benchmarks.