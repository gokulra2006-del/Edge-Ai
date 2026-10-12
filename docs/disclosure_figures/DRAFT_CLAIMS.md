# Draft claims for attorney review

1. A system for assessing an urban emergency, comprising: an edge node (100) receiving time-stamped observations from at least two different sensor modalities (110); a modality inference stage (120) producing event candidates; a fusion and risk engine (130) calculating an event risk from confidence, temporal consistency, sensor agreement and sensor health; an availability and conflict engine (140) reducing the event risk or requiring human review upon a missing or conflicting modality; a safety contract (150) associating a proposed response with a required operator role; an operator interface (160) receiving an authorization for the proposed response; and an incident store (180) recording the observations, calculation, proposed response and authorization in an evidence package verifiable by an evidence verifier (190).

2. The system of claim 1, wherein the edge node (100) continues local assessment when a communication link is unavailable and places a record for later transmission in an offline outbox (230).

3. The system of claim 1, wherein the fusion and risk engine (130) applies a cap to the event risk when a sensor of the sensor inputs (110) fails.

4. The system of claim 3, wherein an event candidate whose unadjusted confidence exceeds a review threshold is presented for human review after the cap lowers the event risk below an alert threshold.

5. The system of claim 1, wherein the availability and conflict engine (140) computes a matrix of candidate outcomes under removal of respective sensor modalities.

6. The system of claim 5, wherein mutually inconsistent event classes cause a HUMAN_REVIEW outcome.

7. The system of claim 1, wherein the safety contract (150) prevents an external emergency-service request until the operator interface (160) records approval by a commander role.

8. The system of claim 7, wherein a viewer role has no authority to approve an actuator or external notification.

9. The system of claim 1, wherein the evidence package includes a manifest with a digest for each included file, a model identifier, an assurance state and an operator-action timeline.

10. The system of claim 9, wherein the evidence verifier (190) recomputes the digests and marks the package as invalid upon mismatch.

11. The system of claim 1, further comprising a replay engine (200) that re-evaluates stored incident inputs in an isolated execution context without issuing a physical actuator command.

12. The system of claim 11, wherein the replay engine (200) tests a counterfactual sensor dropout and compares a resulting proposed response with a recorded response.

13. The system of claim 1, wherein a drift monitor (210) generates a review record and a model review queue (220) requires a human decision before promotion of a replacement model.

14. The system of claim 1, wherein the edge node (100) is a Raspberry Pi 4 and the sensor inputs (110) include an I2S microphone, a USB camera, an I2C inertial sensor and an ADC-coupled gas sensor.

15. The system of claim 14, wherein an analog output of the gas sensor is attenuated before entering a 3.3 V powered ADC and is not connected directly to a GPIO input.

16. The system of claim 14, wherein a servo driven by the response interface (170) receives power from a 5 V source sharing a ground with the edge node (100).

17. A method of assessing an urban emergency, comprising receiving, at an edge node (100), time-stamped observations from different sensor modalities (110); generating event candidates with a modality inference stage (120); calculating a risk using a fusion and risk engine (130) and a sensor-availability assessment by an availability and conflict engine (140); downgrading the risk or requiring human review upon sensor failure or conflict; producing a proposed response governed by a safety contract (150); receiving role-authorized approval through an operator interface (160) before executing the response; and storing an incident record and a verifiable evidence package in an incident store (180).

18. The method of claim 17, further comprising recording a model identifier and an applicable usage restriction with each stored prediction.

19. The method of claim 17, further comprising placing an incident message in an offline outbox (230) while a network connection is unavailable.

20. The method of claim 17, further comprising using a replay engine (200) to compare a recorded decision with a counterfactual decision produced after removal of one sensor modality.

21. A non-transitory computer-readable medium storing instructions that, when executed by an edge node (100), cause the edge node (100) to perform the method of claim 17.

22. The medium of claim 21, wherein the instructions further cause the edge node (100) to verify file digests in the evidence package using an evidence verifier (190).
