# Model Assurance Layer

The dashboard now attaches an evidence record to every live response at `GET /api/live` and exposes the same record at `GET /api/assurance`. It makes the system's model selection, prediction confidence, held-out class reliability, and data source visible where an operator makes decisions.

For the supplied generated-data profile, the service reports `RESEARCH_ONLY` and asks for operator confirmation. This is intentional: confidence from a model trained on procedurally generated samples is not proof of field performance. The layer never changes an actuator command or rule threshold.

Each modality has a readiness label:

- `SUPPORTED`: held-out F1 at least 0.80.
- `CAUTION`: held-out F1 from 0.60 to 0.79.
- `REVIEW_REQUIRED`: held-out F1 below 0.60.
- `UNMEASURED`: no compatible class-level evaluation is available.

The current generated-data evaluation labels acoustic siren recognition as supported, while bus and motorcycle recognition require review. Those limits are surfaced in the UI instead of being hidden behind a single model-confidence number.

This provides a research contribution suitable for the project report: a **provenance-aware, class-conditional human review gate for multi-modal edge incident detection**. To evaluate it with real data, collect field recordings and images from the deployed camera and microphone positions, split by location/time rather than individual sample, rerun the existing training scripts, and revise the profile only after those held-out measurements are available.
