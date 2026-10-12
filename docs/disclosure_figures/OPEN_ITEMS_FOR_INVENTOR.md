# Open items for the inventor

1. Provide real Raspberry Pi 4 wiring photographs, power measurements, sensor readout logs and actuator test logs. The pinout is **configuration-consistent**, not physically validated.
2. Confirm the exact MQ-2 voltage divider. The configuration comment says 10 kOhm upper and 20 kOhm lower resistors but also says the ratio is 1/3; those resistor values produce 2/3. Correct the circuit, configuration and disclosure after measurement.
3. Confirm that the optional LCD stays disabled. Its code maps GPIO26, physical pin 37, although the disclosed circuit reserves that pin as unused.
4. Supply original result logs for entries described as `REAL_HARDWARE` in `RESULTS.md`. Its limitations section describes Windows host measurements under Pi-like constraints.
5. Confirm whether the evidence exporter has an actual linked hash chain, digital signing and persisted `REPLAY_VERIFIED` state. Current disclosure marks these as partial/proposed.
6. Confirm the exact model artifacts and evaluation data provenance; keep the synthetic profile `RESEARCH_ONLY` until a real-world evaluation supports another status.
7. Confirm inventors, ownership, first public disclosure date, target jurisdictions, emergency-service/traffic-authority agreements and privacy retention policy.
8. Have a patent attorney perform a comprehensive novelty, inventive-step, claim-scope and freedom-to-operate search before filing.
9. Decide and implement the proposed rule that reduces response permissions specifically when connectivity is lost; the current outbox preserves local operation but is not evidence of that permission rule.
