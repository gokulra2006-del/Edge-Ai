"""Explicit model profiles keep synthetic experiments separate from legacy weights."""
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def model_profile():
    name = os.environ.get('EDGE_AI_MODEL_PROFILE', 'legacy')
    if name == 'legacy':
        return {'name': name, 'synthetic': False,
                'audio': ROOT/'models/acoustic_emergency_net.pt',
                'vision': [ROOT/'models/vision/fire_smoke_best.pt']}
    if name != 'synthetic':
        raise ValueError(f'Unknown EDGE_AI_MODEL_PROFILE: {name}')
    manifest = ROOT/'models/new_dataset/profile.json'
    config = json.loads(manifest.read_text())
    return {**config, 'audio': ROOT/config['audio'],
            'vision': [ROOT/p for p in config['vision']]}
