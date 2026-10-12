# Safe Raspberry Pi hardware integration brief

Work on the existing `Edge-AI` repository. Add real Raspberry Pi 4 support incrementally without replacing or redesigning the existing dashboard.

## Non-negotiable preservation rules

1. Work in a branch or a copy. Preserve the current working tree and all existing dashboard files.
2. Before editing, inventory the current dashboard routes, HTML/JS assets, API response shapes, roles, database tables, simulation mode, model registry, assurance pages and response-plan pages.
3. Do not rewrite `src/modules/dashboard/app.py`, dashboard front-end assets, or shared response schemas unless a compatibility-preserving adapter is impossible. Prefer new modules and small integration hooks.
4. Existing URLs, API methods, JSON keys, role permissions, login behavior, simulation mode, system-health view, model-assurance view, incident logs, datasets, charts and response-plan view must continue to work.
5. Do not remove or rename existing features. Do not replace trained models. Do not change the GPIO map.
6. Run the existing test suite before and after each integration phase. A failure blocks the next phase.

## Current target hardware

Raspberry Pi 4 Model B with DHT22, GY-87/MPU6050, ADS1115, MQ-2, INMP441, NEO-6M GPS, USB camera, three LEDs, buzzer and SG90 servo. The LCD is disabled. GPIO26/physical pin 37 remains unused.

Use the existing authoritative configuration in `src/config/hardware_config.py`. Do not create a second pin registry. Treat the wiring as configuration-consistent until physical test logs are imported.

## Required architecture

Add a `HardwareMode` boundary with three explicit states:

- `simulation`: current mock/synthetic behavior, with no GPIO access.
- `hardware`: physical drivers only; missing sensor values must be reported as unavailable, never fabricated.
- `hybrid_diagnostic`: physical self-check and dashboard telemetry, with no emergency actuation unless explicitly enabled.

Keep the current dashboard as the presentation layer. Hardware drivers publish the existing telemetry/event schema through an adapter or event bus. The dashboard must not import GPIO, ALSA, serial, I2C or camera-driver implementation details.

Add only these bounded modules where missing:

- `src/modules/hardware/mode.py`
- `src/modules/hardware/physical_adapters.py`
- `src/modules/hardware/self_check.py`
- `src/modules/hardware/audio_stream.py`
- `src/modules/hardware/telemetry_adapter.py`
- `src/modules/hardware/actuator_adapter.py`

Reuse existing `hardware_hub`, `stream_service`, sensor drivers, `run_rpi_node.py`, dashboard streamer, safety policy and database repository whenever they already provide the needed behavior.

## Functional rules

The INMP441 is the primary audio detector. Keep the existing audio model and preprocessing unless inspection proves incompatibility. Verify the model sample rate, feature shape and class map before connecting live audio. Do not assume six labels match the model metadata.

Every non-normal audio event requests camera verification. MPU6050 impact evidence is added only for crash/impact candidates. DHT22 and MQ-2 are context and severity evidence. MQ-2 AO must pass through the documented divider into ADS1115 A0 and must never connect directly to a Pi GPIO. Do not report MQ-2 PPM without calibration.

GPS loss must produce `GPS FIX UNAVAILABLE` while the rest of the pipeline continues. No startup wait for a satellite fix.

Keep the existing sensor-fusion, safety-contract, role-permission, assurance and evidence pipeline. AI may propose a response; only the existing authorized role may approve it. Synthetic or `RESEARCH_ONLY` models cannot authorize physical actuation or dispatch.

## Dashboard compatibility contract

Before changing code, capture the current response keys for `/api/hardware`, `/api/hardware/mode`, health, assurance, incidents, response plans, telemetry and logs. New fields may be added, but existing fields must remain present with the same types. Keep the existing port and startup command unless a compatibility alias is provided.

Add a small mode indicator to the existing dashboard only if it can be done without changing its layout or removing existing cards. It must show `SIMULATION`, `HARDWARE`, or `HYBRID_DIAGNOSTIC`, plus a clear data provenance label. Do not auto-switch modes based on a missing device.

## Self-check and safety

Provide a diagnostic command that reports I2C, MPU6050, ADS1115, DHT22, INMP441, camera, GPS UART, LEDs, buzzer and servo status. GPS no-fix is a warning, not a process failure. All drivers need cleanup on Ctrl+C. Servo power must be a suitable 5 V source with common ground. Keep GPIO26 unused.

## Delivery phases

1. Audit only: report reusable modules, dashboard contracts, model compatibility and unresolved hardware risks. Make no edits.
2. Add mode boundary and self-check. Run regression tests and simulation smoke test.
3. Add physical sensor adapters and telemetry bridge. Run import checks without hardware and simulation tests.
4. Add hardware actuator adapter behind the existing safety policy. Require explicit diagnostic enablement.
5. Run physical validation on the Pi and import signed results as `REAL_HARDWARE`. Do not relabel synthetic or host measurements.

Stop after each phase and report files changed, tests before/after, API compatibility, and open physical-test items. Do not start the next phase without review.

## Required final commands

Use only commands that exist in the repository. At minimum document the actual commands for:

- dashboard simulation
- hardware self-check
- hardware mode
- simulation mode
- regression tests

The final report must state what was reused, what was added, what was not implemented, model class compatibility, exact GPIO mapping, dashboard compatibility results and the physical tests still required.
