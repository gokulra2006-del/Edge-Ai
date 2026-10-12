# SENTINEL-AI disclosure revision log

The reviewed DOCX is a copy. The supplied disclosure and faculty reference were not edited. The faculty's numbered table and headings are retained; Annexes A-F supply evidence, claims and figures.

- Recast the inventive concept as one reliability-gated, offline multimodal decision and response combination with verifiable evidence.
- Added six feature assessments with `IMPLEMENTED`, `PARTIAL` or `PROPOSED` boundaries and code pointers.
- Replaced generic prior-art assertions with three identified patents, publication dates, URLs and a limited comparison. US20250166434A1 is a particularly close multimodal accident-analysis reference. This is a preliminary search only.
- Added a 129-word abstract, shorter title, keywords, three independent claims and 19 dependent claims.
- Added preferred and proposed alternative embodiments, reference numerals and six additional figures.
- Reconciled claims of validation with the source results: the cited model metrics are `SYNTHETIC`; the physical Raspberry Pi build has not been verified by the records inspected.
- Added pin/configuration audit, MQ-2 divider discrepancy, optional LCD/GPIO26 conflict, privacy and deployment constraints.

## Source checks

- `src/config/hardware_config.py`
- `src/modules/decision/uncertainty_fusion.py`
- `src/modules/decision/sensor_availability_matrix.py`
- `src/modules/autonomous_response/safety_contract.py`
- `src/modules/incident_management/replay_engine.py`
- `src/modules/assurance/drift_monitor.py`
- `docs/research/EXPERIMENTS.md` and `docs/research/RESULTS.md`
- Google Patents: US20250166434A1, US7864071B2, US9685080B2

## Render status

The DOCX structure and embedded image dimensions were checked. The bundled workspace has no `soffice.exe`, so PDF export and page-image inspection could not be completed here. In Word, inspect the pages containing the original section 12 drawings, Annex A's feature table, Annex B's comparison table, Annex C's claims, and all six pages/positions of Annex D's figures. Confirm no split image, overflow or orphaned caption before submission.
