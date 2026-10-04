"""Regression checks for real model loading, preprocessing parity and API contracts."""
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import urllib.error
import urllib.request
import wave

import numpy as np
import pytest
import torch

from src.modules.audio_ai.features import DEFAULT_FEATURES, file_features, pcm_features, waveform_features
from src.training.prepare_new_dataset import safe_path

ROOT = Path(__file__).resolve().parents[2]


def test_file_pcm_feature_parity(tmp_path):
    pcm = (np.sin(np.arange(64000)*.12)*20000).astype('<i2').tobytes()
    path = tmp_path/'tone.wav'
    with wave.open(str(path),'wb') as handle:
        handle.setnchannels(1); handle.setsampwidth(2); handle.setframerate(16000)
        handle.writeframes(pcm)
    assert torch.equal(file_features(path), pcm_features(pcm))
    assert file_features(path).shape == (1,1,128,126)


@pytest.mark.parametrize('data', [b'',b'1',None])
def test_invalid_pcm(data):
    with pytest.raises(ValueError):
        pcm_features(data)


@pytest.mark.parametrize('samples,sr', [([],16000),([np.nan],16000),([np.inf],16000),([1],0)])
def test_invalid_waveforms(samples,sr):
    with pytest.raises(ValueError):
        waveform_features(samples,sr)


def test_resampling_and_silence():
    assert torch.isfinite(waveform_features(np.zeros(48000),48000)).all()
    a=waveform_features(np.sin(np.arange(64000)*2*np.pi*500/16000),16000)
    b=waveform_features(np.sin(np.arange(192000)*2*np.pi*500/48000),48000)
    assert torch.mean(torch.abs(a-b)) < .03


def test_zip_traversal(tmp_path):
    for path in ['../outside.wav','C:/outside.wav','..\\outside.wav']:
        with pytest.raises(ValueError):
            safe_path(tmp_path,path)


def test_manifest_splits_are_disjoint():
    for domain in ['audio','fire_smoke','vehicle']:
        path=ROOT/f'data/new_dataset/{domain}_manifest.json'
        if not path.exists():
            pytest.skip('Run dataset preparation first')
        rows=json.loads(path.read_text())
        groups={s:{r['sha256'] for r in rows if r['split']==s} for s in ['train','val','test']}
        assert all(groups.values())
        assert not groups['train'] & groups['val']
        assert not groups['train'] & groups['test']
        assert not groups['val'] & groups['test']


@pytest.fixture
def trained_profile(monkeypatch):
    if not (ROOT/'models/new_dataset/profile.json').exists():
        pytest.skip('Train all models first')
    monkeypatch.setenv('EDGE_AI_MODEL_PROFILE','synthetic')
    monkeypatch.setenv('FIREBASE_DATABASE_URL','')
    torch.set_num_threads(4)


def test_trained_audio_reload(trained_profile):
    from src.modules.audio_ai.classifier import AudioClassifier
    rows=json.loads((ROOT/'data/new_dataset/audio_manifest.json').read_text())
    classifier=AudioClassifier()
    assert classifier.preprocessing == DEFAULT_FEATURES
    for label in ['ambient','crash','horn','siren']:
        row=next(r for r in rows if r['split']=='test' and r['label']==label)
        file=ROOT/'data/new_dataset'/row['path']
        with wave.open(str(file),'rb') as handle:
            pcm=handle.readframes(handle.getnframes())
        result=classifier.predict_file(file)
        assert result == classifier.predict_pcm(pcm)
        assert 0 <= result.confidence <= 1
        assert AudioClassifier().predict_file(file)==result
    command=[sys.executable,'scripts/predict_new_dataset.py','--audio',str(file)]
    restarted=subprocess.run(command,cwd=ROOT,capture_output=True,text=True,check=True)
    assert '"profile": "synthetic"' in restarted.stdout
    assert '"class_name": "siren"' in restarted.stdout


def test_trained_vision_and_invalid_input(trained_profile):
    from src.modules.vision_ai.detector import VisionDetector
    detector=VisionDetector()
    for domain in ['fire_smoke','vehicle']:
        file=next((ROOT/f'data/new_dataset/{domain}/images/test').glob('*.jpg'))
        result=detector.predict_image(str(file))
        assert 0 <= result.confidence <= 1
        assert isinstance(result.bounding_boxes,list)
        for box in result.bounding_boxes:
            assert len(box['box'])==4
    for invalid in [None,np.zeros((0,0,3),dtype=np.uint8),str(ROOT/'missing.jpg')]:
        with pytest.raises(ValueError):
            detector.predict_image(invalid)


def test_api_raw_files_and_invalid_payload(trained_profile):
    # A dedicated process prevents already-imported legacy singletons from hiding profile issues.
    code = '''
import json,threading,urllib.request,urllib.error
from http.server import HTTPServer
from pathlib import Path
from src.modules.dashboard.app import DashboardHandler
from src.modules.decision_engine.deep_rule_engine import DEEP_RULE_ENGINE
root=Path.cwd()
server=HTTPServer(('127.0.0.1',0),DashboardHandler)
thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
url=f'http://127.0.0.1:{server.server_port}'
try:
    rows=json.loads((root/'data/new_dataset/audio_manifest.json').read_text())
    row=next(r for r in rows if r['split']=='test' and r['label']=='siren')
    image=next((root/'data/new_dataset/vehicle/images/test').glob('*.jpg'))
    payload={'raw_audio':str(root/'data/new_dataset'/row['path']),'raw_image':str(image)}
    req=urllib.request.Request(url+'/api/deep_rules/evaluate',data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'})
    result=json.load(urllib.request.urlopen(req))
    assert result['deep_learning']['acoustic_model']['weights']=='audio.pt'
    assert result['deep_learning']['acoustic_model']['predicted_class']=='siren'
    assert result['event']=='EMERGENCY_VEHICLE'
    assert 'vehicle.pt' in result['deep_learning']['vision_model']['weights']
    catalog=json.load(urllib.request.urlopen(url+'/api/datasets/catalog'))
    assert catalog['model_profile']=='synthetic'
    from src.modules.dashboard.app import STREAMER
    STREAMER._generate_and_sync_cycle()
    live=json.load(urllib.request.urlopen(url+'/api/live'))
    assert live['telemetry']['deep_learning']['acoustic_model']['weights']=='audio.pt'
    assert live['telemetry']['audio_prediction']['dataset']=='Synthetic supplied dataset'
    assert live['assurance']['status']=='RESEARCH_ONLY'
    assert live['assurance']['operator_confirmation_required'] is True
    assurance=json.load(urllib.request.urlopen(url+'/api/assurance'))
    assert assurance['profile']=='synthetic'
    assert len(assurance['modalities'])==2
    html=urllib.request.urlopen(url+'/').read().decode()
    assert 'app.js' in html
    js=urllib.request.urlopen(url+'/app.js').read().decode()
    assert '/api/live' in js
    for body in [b'{',b'[]',b'{"raw_audio":"missing.wav"}',b'{"raw_image":123}']:
        try:
            urllib.request.urlopen(urllib.request.Request(url+'/api/deep_rules/evaluate',data=body))
            raise AssertionError('Invalid payload accepted')
        except urllib.error.HTTPError as exc:
            assert exc.code==400
    print('Raw files -> models -> rules -> HTTP JSON and existing frontend assets: PASS')
finally:
    server.shutdown(); server.server_close(); thread.join()
'''
    result=subprocess.run([sys.executable,'-c',code],cwd=ROOT,env=os.environ.copy(),capture_output=True,text=True,timeout=180)
    assert result.returncode==0,result.stdout+result.stderr
