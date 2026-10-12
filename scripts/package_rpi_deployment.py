"""Build a Raspberry Pi deployment archive from the current project."""
from pathlib import Path
from datetime import datetime, timezone
import zipfile, json

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'exports'; OUT.mkdir(exist_ok=True)
ZIP=OUT/'sentinel_ai_raspberry_pi_deployment.zip'
include_dirs=['src','scripts/pi','scripts/hardware_diagnostic.py','scripts/test_hardware_sensors.py','scripts/run_rpi_node.py','docs','deploy']
include_files=['requirements.txt','requirements-optional.txt','requirements-training.txt','.env.example','pytest.ini','simulation_v1.py','START_EDGE_AI_DASHBOARD.bat']
model_files=['models/acoustic_emergency_net.pt','models/acoustic_metrics.json','models/audio/best_model.pt','models/audio/model.torchscript','models/audio/model_metadata.json','models/vision/fire_smoke_best.pt','models/vision/fire_smoke_best.torchscript','models/vision/evaluation_report.json','models/new_dataset/profile.json','models/new_dataset/audio_evaluation.json','models/new_dataset/fire_smoke_evaluation.json','models/new_dataset/vehicle_evaluation.json']
files=[]
for item in include_dirs:
 p=ROOT/item
 if p.is_file(): files.append((p,p.as_posix()))
 elif p.exists():
  for f in p.rglob('*'):
   if f.is_file(): files.append((f,f.relative_to(ROOT).as_posix()))
for item in include_files+model_files:
 p=ROOT/item
 if p.exists(): files.append((p,p.relative_to(ROOT).as_posix()))
exclude_parts={'.git','.venv','__pycache__','.pytest_cache','data','results','logs','recordings','evidence','exports','runs','test_tmp'}
files=[x for x in files if not any(part in exclude_parts for part in Path(x[1]).parts) and not x[1].endswith(('.db','.db-shm','.db-wal','.zip'))]
seen=set(); files=[x for x in files if not (x[1] in seen or seen.add(x[1]))]
readme='''SENTINEL-AI Raspberry Pi deployment package\n\n1. Copy this archive to the Raspberry Pi and extract it.\n2. From the extracted project directory create a virtual environment.\n3. Install requirements.txt and the Raspberry Pi requirements referenced by scripts/pi.\n4. Enable I2C and UART with raspi-config; connect the hardware using docs/HARDWARE_WIRING.md.\n5. Run: python scripts/hardware_diagnostic.py\n6. Run: python scripts/test_hardware_sensors.py\n7. Start the dashboard using the existing documented command.\n8. Start the physical node with: python scripts/run_rpi_node.py\n\nThis package preserves simulation mode. Use the diagnostic output to confirm each physical device before enabling actuation. The MQ-2 must use the documented voltage divider; the SG90 needs a suitable 5 V supply and common ground; GPIO26/physical pin 37 remains unused. Do not copy training datasets into this deployment package.\n\nModel status: model files are included where present, but the project registry restrictions apply. Synthetic models remain RESEARCH_ONLY until physical validation and approval.\n'''
manifest={'created_utc':datetime.now(timezone.utc).isoformat(),'package':'SENTINEL-AI Raspberry Pi deployment','files':len(files),'excluded':['data/ training datasets','results/ logs/ development databases','.git and virtual environments'],'models_included':[a for _,a in files if a.startswith('models/')]}
with zipfile.ZipFile(ZIP,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
 z.writestr('README_PI_DEPLOYMENT.txt',readme); z.writestr('DEPLOYMENT_MANIFEST.json',json.dumps(manifest,indent=2))
 for p,a in files: z.write(p,a)
print(json.dumps({'zip':str(ZIP),'files':len(files),'bytes':ZIP.stat().st_size}))
