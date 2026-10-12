"""Create an evidence-bound copy of the faculty-format SENTINEL-AI disclosure."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from docx import Document
from docx.shared import Inches, Pt
from docx.enum.text import WD_ALIGN_PARAGRAPH

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / 'docs/disclosure_figures/SENTINEL_AI_Invention_Disclosure_Complete.docx'
OUT = ROOT / 'docs/disclosure_figures/SENTINEL_AI_Invention_Disclosure_Reviewed.docx'
ASSETS = ROOT / 'docs/disclosure_figures/reviewed'
ASSETS.mkdir(parents=True, exist_ok=True)

REFS = [
 ('P1','US20250166434A1','Multi-modal model for traffic accident analysis','2025-05-22','https://patents.google.com/patent/US20250166434A1/en','Uses aligned multimodal data and edge processing for accident analysis; the reviewed claims do not identify the same sensor-failure response-permission contract with an operator approval boundary.'),
 ('P2','US7864071B2','Emergency vehicle traffic signal preemption system','2011-01-04','https://patents.google.com/patent/US7864071B2/en','Vehicle transponder, intersection status and warnings govern preemption; the present concept addresses local incident evidence and reliability-based review.'),
 ('P3','US9685080B2','Traffic light preemption management system','2017-06-20','https://patents.google.com/patent/US9685080B2/en','Manages traffic preemption using vehicle signals and intersection monitoring; the present concept adds explicit risk accounting and verifiable incident evidence.'),
]

ELEMENTS = [(100,'edge node'),(110,'sensor inputs'),(120,'modality inference'),(130,'fusion and risk engine'),(140,'availability and conflict engine'),(150,'safety contract'),(160,'operator interface'),(170,'response interface'),(180,'incident store'),(190,'evidence verifier'),(200,'replay engine'),(210,'drift monitor'),(220,'model review queue'),(230,'offline outbox')]

FEATURES = [
 ('Uncertainty-aware fusion','IMPLEMENTED','A failing sensor can inflate an apparent emergency score.','Engine (130) multiplies bounded event, temporal, agreement, health and calibration factors; penalty and failure caps downgrade output.','Risk falls or routes to review when evidence degrades.','src/modules/decision/uncertainty_fusion.py'),
 ('Role-gated response contract','IMPLEMENTED','A model output must not directly cause external dispatch.','Contract (150) records proposed actions and required roles; interface (160) requires authorized approval before execution.','Provides a traceable human authorization boundary.','src/modules/autonomous_response/safety_contract.py'),
 ('Sensor availability and conflict matrix','IMPLEMENTED','Contradictory modalities can create false certainty.','Engine (140) evaluates missing/faulted modalities and maps conflict to HUMAN_REVIEW.','Makes degraded and conflicting outcomes visible.','src/modules/decision/sensor_availability_matrix.py'),
 ('Deterministic sandbox replay','PARTIAL','An incident decision must be independently inspectable.','Replay engine (200) re-evaluates stored step inputs under faults without live actuation.','Allows counterfactual checking; equivalence to physical sensor timing remains unverified.','src/modules/incident_management/replay_engine.py'),
 ('Drift and governed feedback','PARTIAL','Model behavior can change after deployment.','Drift monitor (210), feedback records and review queue (220) support human model assessment.','Provides a review path; continuous production retraining is not established.','src/modules/assurance/drift_monitor.py'),
 ('Tamper-evident evidence package','PARTIAL','Incident evidence can be altered after capture.','Store (180) and verifier (190) export SHA-256 manifests; chain or replay-verified status requires separate confirmation.','Detects modified package files; full signed chain of custody is proposed.','src/modules/database/governed_store.py; src/modules/reporting/evidence_verifier.py'),
]

CLAIMS = [
 '1. A system for assessing an urban emergency, comprising: an edge node (100) receiving time-stamped observations from at least two different sensor modalities (110); a modality inference stage (120) producing event candidates; a fusion and risk engine (130) calculating an event risk from confidence, temporal consistency, sensor agreement and sensor health; an availability and conflict engine (140) reducing the event risk or requiring human review upon a missing or conflicting modality; a safety contract (150) associating a proposed response with a required operator role; an operator interface (160) receiving an authorization for the proposed response; and an incident store (180) recording the observations, calculation, proposed response and authorization in an evidence package verifiable by an evidence verifier (190).',
 '2. The system of claim 1, wherein the edge node (100) continues local assessment when a communication link is unavailable and places a record for later transmission in an offline outbox (230).',
 '3. The system of claim 1, wherein the fusion and risk engine (130) applies a cap to the event risk when a sensor of the sensor inputs (110) fails.',
 '4. The system of claim 3, wherein an event candidate whose unadjusted confidence exceeds a review threshold is presented for human review after the cap lowers the event risk below an alert threshold.',
 '5. The system of claim 1, wherein the availability and conflict engine (140) computes a matrix of candidate outcomes under removal of respective sensor modalities.',
 '6. The system of claim 5, wherein mutually inconsistent event classes cause a HUMAN_REVIEW outcome.',
 '7. The system of claim 1, wherein the safety contract (150) prevents an external emergency-service request until the operator interface (160) records approval by a commander role.',
 '8. The system of claim 7, wherein a viewer role has no authority to approve an actuator or external notification.',
 '9. The system of claim 1, wherein the evidence package includes a manifest with a digest for each included file, a model identifier, an assurance state and an operator-action timeline.',
 '10. The system of claim 9, wherein the evidence verifier (190) recomputes the digests and marks the package as invalid upon mismatch.',
 '11. The system of claim 1, further comprising a replay engine (200) that re-evaluates stored incident inputs in an isolated execution context without issuing a physical actuator command.',
 '12. The system of claim 11, wherein the replay engine (200) tests a counterfactual sensor dropout and compares a resulting proposed response with a recorded response.',
 '13. The system of claim 1, wherein a drift monitor (210) generates a review record and a model review queue (220) requires a human decision before promotion of a replacement model.',
 '14. The system of claim 1, wherein the edge node (100) is a Raspberry Pi 4 and the sensor inputs (110) include an I2S microphone, a USB camera, an I2C inertial sensor and an ADC-coupled gas sensor.',
 '15. The system of claim 14, wherein an analog output of the gas sensor is attenuated before entering a 3.3 V powered ADC and is not connected directly to a GPIO input.',
 '16. The system of claim 14, wherein a servo driven by the response interface (170) receives power from a 5 V source sharing a ground with the edge node (100).',
 '17. A method of assessing an urban emergency, comprising receiving, at an edge node (100), time-stamped observations from different sensor modalities (110); generating event candidates with a modality inference stage (120); calculating a risk using a fusion and risk engine (130) and a sensor-availability assessment by an availability and conflict engine (140); downgrading the risk or requiring human review upon sensor failure or conflict; producing a proposed response governed by a safety contract (150); receiving role-authorized approval through an operator interface (160) before executing the response; and storing an incident record and a verifiable evidence package in an incident store (180).',
 '18. The method of claim 17, further comprising recording a model identifier and an applicable usage restriction with each stored prediction.',
 '19. The method of claim 17, further comprising placing an incident message in an offline outbox (230) while a network connection is unavailable.',
 '20. The method of claim 17, further comprising using a replay engine (200) to compare a recorded decision with a counterfactual decision produced after removal of one sensor modality.',
 '21. A non-transitory computer-readable medium storing instructions that, when executed by an edge node (100), cause the edge node (100) to perform the method of claim 17.',
 '22. The medium of claim 21, wherein the instructions further cause the edge node (100) to verify file digests in the evidence package using an evidence verifier (190).',
]

def set_text(cell, value):
    cell.text = value
    for p in cell.paragraphs:
        for r in p.runs: r.font.name='Arial'; r.font.size=Pt(9)

def heading(doc, value):
    p=doc.add_paragraph(); r=p.add_run(value); r.bold=True; r.font.name='Arial'; r.font.size=Pt(14)
    return p

def section_content(table, number, value):
    for i,row in enumerate(table.rows[:-1]):
        if row.cells[0].text.strip().rstrip('.') == str(number):
            set_text(table.rows[i+1].cells[1], value)
            return

def fnt(n,bold=False):
    p=Path('C:/Windows/Fonts/arialbd.ttf' if bold else 'C:/Windows/Fonts/arial.ttf')
    return ImageFont.truetype(str(p),n) if p.exists() else ImageFont.load_default()

def figure(name,title,nodes,arrows):
    im=Image.new('RGB',(1600,680),'white'); d=ImageDraw.Draw(im)
    d.text((50,35),title,font=fnt(38,True),fill='#14283d')
    for ident,x,y,w,h,label in nodes:
        d.rounded_rectangle((x,y,x+w,y+h),18,fill='#e9f1f8',outline='#23608b',width=4)
        d.multiline_text((x+18,y+20),f'{ident}  {label}',font=fnt(23,True),fill='#14283d',spacing=8)
    for x1,y1,x2,y2 in arrows:
        d.line((x1,y1,x2,y2),fill='#23608b',width=5)
        d.polygon([(x2,y2),(x2-15,y2-10),(x2-15,y2+10)],fill='#23608b')
    p=ASSETS/name; im.save(p,dpi=(180,180)); return p

def figures():
    layouts=[
      ('system_blocks.png','System blocks',[(100,55,165,250,110,'Edge node'),(110,355,165,250,110,'Sensors'),(130,655,165,250,110,'Risk engine'),(150,955,165,250,110,'Safety contract'),(180,1255,165,250,110,'Incident store')],[(305,220,355,220),(605,220,655,220),(905,220,955,220),(1205,220,1255,220)]),
      ('response_flow.png','Emergency response flow',[(120,55,165,250,110,'Inference'),(140,355,165,250,110,'Check conflict'),(150,655,165,250,110,'Propose plan'),(160,955,165,250,110,'Human approval'),(170,1255,165,250,110,'Permitted action')],[(305,220,355,220),(605,220,655,220),(905,220,955,220),(1205,220,1255,220)]),
      ('fusion_risk.png','Fusion and explicit risk factors',[(110,55,165,250,110,'Sensor inputs'),(120,355,165,250,110,'Candidates'),(130,655,165,250,110,'Bounded factors'),(140,955,165,250,110,'Failure/conflict'),(160,1255,165,250,110,'Review output')],[(305,220,355,220),(605,220,655,220),(905,220,955,220),(1205,220,1255,220)]),
      ('safety_states.png','Response plan and safety contract states',[(150,55,165,250,110,'Proposed'),(150,355,165,250,110,'Role check'),(160,655,165,250,110,'Approved'),(170,955,165,250,110,'Executed'),(180,1255,165,250,110,'Audited')],[(305,220,355,220),(605,220,655,220),(905,220,955,220),(1205,220,1255,220)]),
      ('evidence_chain.png','Evidence package and verification',[(180,55,165,250,110,'Incident'),(180,355,165,250,110,'Files/manifest'),(190,655,165,250,110,'SHA-256 verify'),(200,955,165,250,110,'Sandbox replay'),(230,1255,165,250,110,'Offline outbox')],[(305,220,355,220),(605,220,655,220),(905,220,955,220),(1205,220,1255,220)]),
      ('drift_loop.png','Drift and governed model review',[(210,55,165,250,110,'Drift monitor'),(180,355,165,250,110,'Feedback'),(220,655,165,250,110,'Review queue'),(160,955,165,250,110,'Human decision'),(120,1255,165,250,110,'Model registry')],[(305,220,355,220),(605,220,655,220),(905,220,955,220),(1205,220,1255,220)]),
    ]
    return [(title,figure(name,title,nodes,arr)) for name,title,nodes,arr in layouts]

def main():
    doc=Document(SRC); table=doc.tables[0]
    title='Reliability-Gated Multimodal Edge Emergency Detection and Governed Response'
    section_content(table,1,title)
    concept=('Core inventive combination: an offline-first multimodal edge emergency detector in which confidence and permitted response decrease as sensor, connectivity or model reliability decreases, while each decision is linked to verifiable incident evidence. Sensor and model restrictions and local offline persistence have code support; explicit permission degradation solely because connectivity fails is a PROPOSED embodiment. Physical end-to-end junction deployment remains unverified.\n\nAbstract: An edge node receives time-stamped acoustic, visual and environmental observations at an urban location. A fusion engine forms an emergency candidate and calculates risk from confidence, temporal consistency, sensor agreement, device health and model assurance. Sensor failure or conflicting evidence lowers the risk or routes the candidate to human review. A safety contract converts a candidate response into role-constrained actions, with operator approval required before external emergency-service contact. The node stores incident decisions and evidence locally during network loss and can synchronize records later. A manifest and digest verifier detect changes to exported files. A sandbox replay function supports counterfactual examination without activating field outputs. This arrangement aims to make emergency response both resilient and auditable; field accuracy and safety remain to be established.\n\nKeywords: edge AI, emergency detection, multimodal fusion, risk degradation, operator approval, evidence verification, offline incident store.')
    section_content(table,2,concept)
    section_content(table,5,'Closest reviewed references are P1-P3 below. This is a targeted preliminary search, not a freedom-to-operate or exhaustive novelty opinion.\n'+'\n'.join(f'{a}: {b}, {c}, published {d}. {f} {e}' for a,b,c,d,e,f in REFS))
    section_content(table,6,'The apparent gap is the joint technical control of risk and response permissions under sensor/model/connectivity degradation, tied to a verifiable incident record. Individual elements such as preemption, camera monitoring and alarm generation are known. Whether the full combination is patentable remains for counsel to assess against a wider search.')
    section_content(table,9,'The potential inventive contribution is the one combination stated in section 2. Feature-by-feature implementation status, problem, mechanism and effect are in Annex A. Features marked PARTIAL must not be characterized as fully field validated.')
    section_content(table,15,'Stored research results are in docs/research/RESULTS.md and results/*.json. The reported 6A clean Macro-F1 of 0.8851 is tagged SYNTHETIC; the reported 6D ten-of-ten replay agreement is tagged SYNTHETIC. These are laboratory software results, not field accuracy. RESULTS.md labels 6F and 6I as hardware validated but also states that Pi resource benchmarking ran on a Windows x86_64 host with Pi-like constraints; until primary device logs are supplied, this disclosure does not claim REAL_HARDWARE validation. No physical response-time or electrical measurement is asserted.')
    section_content(table,20,'Potential claim scope is expressed in Annex C as three independent claims and dependent fallbacks. These are drafting candidates, not an opinion on novelty, inventive step, enablement or freedom to operate.')
    section_content(table,28,'Provisional TRL 4: components and integrated software have laboratory and synthetic scenario testing. The repository does not supply a verified physical Pi 4 end-to-end test record for the assembled sensors, actuator circuit and municipal workflow. TRL 5 should be considered only after a representative physical junction-model demonstration with retained test logs.')
    section_content(table,29,'See Annexes A-F for technical status, figures, claims, audit, open items and attorney review. The hardware pinout is configuration-consistent, not physically validated. External emergency-service contact is operator approved. Synthetic models carry RESEARCH_ONLY restrictions.')
    doc.add_page_break(); heading(doc,'Annex A  Feature status and technical effect')
    ft=doc.add_table(rows=1,cols=4); ft.style='Table Grid'
    for c,h in zip(ft.rows[0].cells,['Feature and status','Problem','Mechanism','Technical effect / code']): c.text=h
    for name,status,problem,mechanism,effect,code in FEATURES:
        cells=ft.add_row().cells
        for c,v in zip(cells,[f'{name}\n{status}',problem,mechanism,f'{effect}\n{code}']): c.text=v
    heading(doc,'Annex B  Prior art comparison')
    pt=doc.add_table(rows=1,cols=4); pt.style='Table Grid'
    for c,h in zip(pt.rows[0].cells,['Reference','Detection / control focus','Reliability-gated permission','Evidence / replay']): c.text=h
    for r in REFS:
        cells=pt.add_row().cells; cells[0].text=f'{r[0]} {r[1]}'; cells[1].text=r[2]; cells[2].text='Not identified in reviewed disclosure'; cells[3].text='Not identified in reviewed disclosure'
    cells=pt.add_row().cells
    for c,v in zip(cells,['SENTINEL-AI','Multimodal incident assessment','Implemented/partial as Annex A','Digest package implemented; chain/replay status partial']): c.text=v
    doc.add_paragraph('Reference details: '+'; '.join(f'{a} {b}, {c}, {d}, {e}' for a,b,c,d,e,_ in REFS))
    heading(doc,'Annex C  Draft claims')
    for claim in CLAIMS: doc.add_paragraph(claim,style='Normal')
    heading(doc,'Annex D  Reference numerals and figures')
    doc.add_paragraph('; '.join(f'{n} {label}' for n,label in ELEMENTS)+'. Every numeral used in the following figures is defined here and appears in the claim text or Annex A.')
    for caption,p in figures():
        q=doc.add_paragraph(); q.alignment=WD_ALIGN_PARAGRAPH.CENTER; q.add_run().add_picture(str(p),width=Inches(6.7))
        q=doc.add_paragraph(caption); q.alignment=WD_ALIGN_PARAGRAPH.CENTER
    heading(doc,'Annex E  Embodiments and implementation boundaries')
    doc.add_paragraph('Preferred embodiment (configuration-consistent): Raspberry Pi 4 Model B (100); DHT22, GY-87/MPU6050, ADS1115 with MQ-2, INMP441, NEO-6M and USB webcam (110); LEDs, 3-pin buzzer and SG90 (170). SQLite/WAL store (180) and outbox (230) preserve local records. Commander, Operator, Engineer and Viewer roles are distinct. The MQ-2 AO requires an attenuator before ADS1115 A0; the servo uses a suitable 5 V source and common ground; GPIO26, physical pin 37, remains unused in this embodiment. Physical wiring and safe actuation require bench verification.')
    doc.add_paragraph('Proposed alternative embodiments: an equivalent edge board, different microphones/cameras/IMUs, wired or wireless transport, another transactional local database, or replacement inference models may be used if the reliability degradation, role authorization and evidence-verification functions are retained. These alternatives have not been validated in the current prototype.')
    heading(doc,'Annex F  Consistency audit and open items')
    for line in [
      'Pinout: DHT22 GPIO4/physical 7; I2C GPIO2/3/physical 3/5; I2S GPIO18/19/20/physical 12/35/38; GPS RX/TX GPIO15/14/physical 10/8; LEDs GPIO5/6/13/physical 29/31/33; buzzer GPIO16/physical 36; servo GPIO12/physical 32. These match src/config/hardware_config.py.',
      'Conflict: hardware_config.py contains an optional LCD mapping on GPIO26/physical 37 although enable_lcd=False. The disclosed build requires that LCD mapping remain disabled or be removed.',
      'Conflict: MQ-2 divider comment says 10 kOhm top / 20 kOhm bottom while asserting a 1/3 ratio; those resistor values yield 2/3. Select a physically tested divider and update code, diagram and bill of materials.',
      'Evidence: per-file SHA-256 verification is supported; a linked hash chain, signing, and a persisted REPLAY_VERIFIED status require confirmation or implementation.',
      'Connectivity: local operation and an outbox are implemented, but response-permission degradation triggered solely by loss of connectivity is a proposed embodiment.',
      'Validation: RESULTS.md contains contradictory hardware labels. Obtain actual Pi test logs, wiring photos, power measurements and physical actuator safety tests before describing the prototype as hardware validated.',
      'Commercialization: intended settings include municipal control rooms, campus intersections and industrial roads. Deployment must assess privacy retention, local traffic authority approval, emergency-service agreements, electrical isolation, environmental sealing, maintenance and costed BOM. No market-size number is asserted.'
    ]: doc.add_paragraph('• '+line)
    doc.core_properties.title=title
    doc.save(OUT)
    (OUT.parent/'DRAFT_CLAIMS.md').write_text('# Draft claims for attorney review\n\n'+'\n\n'.join(CLAIMS)+'\n',encoding='utf-8')
    print(OUT)

if __name__=='__main__': main()
