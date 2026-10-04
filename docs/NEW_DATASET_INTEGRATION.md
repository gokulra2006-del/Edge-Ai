# Supplied dataset integration

## Repository findings

The application is a Python edge-sensor and emergency-response system. `src/core/data_models.py`
defines the prediction contracts. `src/rpi/app/main.py` reads camera frames and PCM microphone
buffers, calls `AudioClassifier` and `VisionDetector`, then sends predictions to the rule engine.
The separate simulation orchestrator consumes already-classified sensor packets. The existing
HTTP dashboard serves static HTML/CSS/JavaScript and JSON telemetry; it is not a React app.
Its frontend consumes `/api/live`, `/api/events`, and `/api/datasets/catalog`.

There are two existing acoustic CNN pipelines: the live application's `EdgeAcousticNet`
(`models/acoustic_emergency_net.pt`) and the separate `EdgeAudioCNN` experiment under
`src/modules/audio_ai/train.py` (`models/audio/best_model.pt`). They have different feature
transforms and classifier heads. The new pipeline reuses **EdgeAcousticNet**, including its
three convolution blocks, adaptive pooling, 48-unit hidden layer, and dropout. It does not
overwrite either legacy checkpoint. The original live microphone and dataset feeder used
a transform different from the original acoustic trainer; the new checkpoint instead carries
an explicit preprocessing contract shared by training, WAV inference, and PCM inference.

The original vision path loaded only `models/vision/fire_smoke_best.pt`, despite indexing
vehicle datasets. The new profile runs two YOLO11n detectors and combines their results.
Fire/smoke detections take priority when selecting the primary class. The existing
`AudioPrediction`, `VisionPrediction`, JSON field names, simulation modes, and frontend remain.
The standalone `sentinel_rpi_package` directory and ZIP are older deployment snapshots and
are not the working source tree; they are not overwritten by this integration.

## Dataset and provenance

The supplied README and generator source identify the data as **procedurally generated**.
Generator code was inspected as data and was not executed. These datasets are useful for
pipeline tests and synthetic demonstrations; their metrics do not establish performance on
real recordings, CCTV, or physical emergency-response hardware.

The independent ZIP parts contain:

| Domain | Samples | Labels | Input |
|---|---:|---|---|
| Acoustic | 920 | ambient, crash, horn, siren; 230 each | 16 kHz, mono, four-second WAV |
| Fire/smoke | 1,440 | fire, smoke | 640 × 640 JPEG and YOLO boxes |
| Vehicle | 1,400 | car, truck, bus, motorcycle | 640 × 640 JPEG and YOLO boxes |

Acoustic metadata columns are `filepath,label,duration_s,sample_rate`. Vision labels have
five numeric fields: `class_id x_center y_center width height`, with normalized coordinates.
Class names are read from the actual CSV/YAML. There is no tabular numerical target/scaler.
The split `.z01`/`.zip` acoustic archive is redundant with the six independently readable
acoustic ZIP parts; the latter are the ingestion source. `_1.zip` copies are hash-checked
against their corresponding original and excluded from sample counts.

Preparation verifies ZIP CRCs, refuses unsafe member paths and conflicting overlapping files,
decodes every WAV and image, checks finite samples and audio metadata, validates every YOLO
class/coordinate, and removes decoded-content duplicates before splitting. Invalid samples
are quarantined in the audit instead of silently becoming zero features. Archive SHA-256s,
sample hashes, manifests, class counts, invalid records, and split counts are saved.

Audio splits are stratified 70/15/15 using seed 42. The supplied vision training sets are
retained; the original validation pools are divided into validation and test sets stratified
by class-presence signature, before training. No model selection uses the test set. These
independently generated samples have no recording/video group identifier. Content hashing
prevents exact duplicate leakage but cannot turn a same-generator test into an external-domain
test. Images containing different domains lack complete cross-domain annotations, so their
label files are not merged into one detector's training set.

## Preprocessing and label mapping

New acoustic preprocessing is `src/modules/audio_ai/features.py`: decode to float32; average
stereo channels; polyphase resample to 16 kHz; pad/crop to four seconds; peak normalize;
Hann STFT with FFT size 512 and hop 512; retain 128 frequency bins; log power; per-clip min/max
normalization. Output is `[1, 1, 128, 126]`. No population statistic is fit to validation/test.
Four seconds retain randomly placed crash events that a two-second crop could discard.
The checkpoint stores the full transform configuration and label mapping. Unsupported transform
versions fail explicitly. Empty, malformed, and nonfinite input are rejected.

Labels map `ambient → traffic`, `horn → car_horn`, `crash → crash`, `siren → siren`.
Generic siren is recognized by the existing emergency-vehicle rules; it is never relabeled as
an ambulance, firetruck, or police subtype. Legacy profile still supports its original labels.

YOLO handles letterboxing, RGB conversion, tensor scaling, and training augmentation through
the same Ultralytics implementation used for inference. Training and inference use 320 pixels.
Metadata preserves the image size and model label dictionaries. Bounding boxes returned to the
application remain pixel-coordinate `xyxy` boxes in the original image.

## Training and artifacts

Run from the repository root using a standard CPython virtual environment (not MSYS Python):

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-training.txt
.\.venv\Scripts\python.exe -m src.training.prepare_new_dataset --downloads C:\Users\gokul\Downloads
.\.venv\Scripts\python.exe -m src.training.train_new_dataset --domain all
```

The CNN trains from scratch with AdamW, learning rate 0.001, weight decay 0.0001, batch 16,
up to 25 epochs, and validation-loss early stopping (patience 6). Class weights are calculated
only from the training split (equal for this balanced dataset). Seed 42 controls Python,
NumPy, PyTorch, and YOLO; deterministic algorithms and four CPU threads are requested.
Best validation weights are selected, then the held-out test set is evaluated once.

Each YOLO11n starts from the existing base `yolo11n.pt` COCO checkpoint, not an old checkpoint
that might have seen a related holdout. Default configuration is AdamW, initial LR 0.001,
batch 16, 320 pixels, 12 epochs, patience 6, and the first 10 layers frozen. Mosaic is disabled
to retain the generated scenes. Native YOLO class and box losses are used; the audit records
vehicle imbalance and evaluation reports per-class precision, recall, F1 and AP.

`models/new_dataset/` contains `audio.pt`, `fire_smoke.pt`, `vehicle.pt`, the profile manifest,
training/evaluation JSON and a compact dataset audit. Full manifests and extracted samples
are under `data/new_dataset/`; YOLO histories, best/last weights and confusion-matrix plots
are under `models/new_dataset/runs/`. Large generated data, temporary wheels, virtual environments,
and intermediate runs are ignored. There was no `.git` directory in the supplied workspace;
no commit or remote publication is performed.

## Run the integrated application

```powershell
.\.venv\Scripts\python.exe scripts/run_synthetic_demo.py --port 8080
```

Open http://127.0.0.1:8080. This launcher selects `EDGE_AI_MODEL_PROFILE=synthetic` before any
model singleton is imported, binds locally, and disables Firebase cloud writes. Dashboard
scenario inputs use actual held-out sample predictions with this profile. The dataset catalog
identifies synthetic data explicitly. Scenario sensors remain simulated; predictions are not
a claim that a real emergency was observed. Starting the original application normally retains
`EDGE_AI_MODEL_PROFILE=legacy` and the original checkpoints. Restart the process after changing
profiles because model objects are cached.

To infer from real file inputs without actuating hardware:

```powershell
.\.venv\Scripts\python.exe scripts/predict_new_dataset.py --audio C:\path\clip.wav --image C:\path\frame.jpg
```

`AudioClassifier.predict_pcm` accepts signed little-endian 16-bit mono PCM and an explicit
sample rate. Use a four-second window for the new model. Short clips are padded; long clips
are cropped to the first four seconds. The existing Pi loop captures shorter buffers, so
synthetic models are not enabled for that loop by default. Field validation and a rolling
four-second audio buffer would be needed before considering physical deployment.

The existing `/api/deep_rules/evaluate` accepts local audio/image paths in `raw_audio` and
`raw_image`. It returns the unchanged decision structure with actual model filenames. Bad JSON,
invalid input types, missing files and decoding errors return HTTP 400 instead of generating
a simulated prediction. This remains a local operator API, not a public upload service.

The separate legacy acoustic dashboard still uses its own `EdgeAudioCNN` checkpoint and metrics;
use the main application or the new inference CLI for the new model.

## Verification and limits

```powershell
.\.venv\Scripts\python.exe -m pytest src/tests/test_new_dataset.py -q
```

Tests cover file/PCM feature equality, resampling, silence, invalid/missing/nonfinite inputs,
archive path traversal, disjoint split hashes, model reload and a new-process restart, both
vision models, raw-file inference through the HTTP rule API, and serving existing frontend
assets. Actual hardware and browser rendering are separate from these software checks.

## Recorded run: 2026-10-04

The CPU-only training run used seed 42, four Torch CPU threads, batch size 16, and no GPU.
Audio completed 25 epochs. Each YOLO11n detector completed three epochs at 160 pixels; these
short settings were selected so training could complete on the available 12th-generation Intel
mobile CPU with approximately 1.5 GB of free memory. The exact settings, package versions,
dataset manifests, weights, and checksums are retained in `models/new_dataset/`.

| Model and held-out test set | Result |
|---|---|
| EdgeAcousticNet, 140 WAV clips | Accuracy 1.000; macro F1 1.000; every class 35/35 |
| YOLO11n fire/smoke, 131 images / 211 boxes | Precision 0.878; recall 0.766; mAP@50 0.837; mAP@50–95 0.433 |
| Fire | Precision 0.917; recall 0.863; F1 0.889; mAP@50 0.940 |
| Smoke | Precision 0.840; recall 0.670; F1 0.745; mAP@50 0.734 |
| YOLO11n vehicles, 128 images / 388 boxes | Precision 0.711; recall 0.693; mAP@50 0.650; mAP@50–95 0.472 |
| Car | Precision 0.838; recall 0.882; F1 0.860; mAP@50 0.916 |
| Truck | Precision 0.573; recall 0.861; F1 0.688; mAP@50 0.686 |
| Bus | Precision 0.433; recall 0.905; F1 0.586; mAP@50 0.657 |
| Motorcycle | Precision 1.000; recall 0.126; F1 0.224; mAP@50 0.339 |

The vehicle model's motorcycle recall is too low for operational use. The generated data's
fixed visual style also makes all metrics optimistic for that generator and unsuitable as a
field-performance claim. Add varied, labeled real camera imagery and retrain at a larger image
size for more epochs before any physical deployment.
