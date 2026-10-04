"""Run the trained synthetic models on a WAV file and/or image without actuating hardware."""
import argparse
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--audio', type=Path)
    parser.add_argument('--image', type=Path)
    args = parser.parse_args()
    if not args.audio and not args.image:
        parser.error('Supply --audio and/or --image')
    os.environ['EDGE_AI_MODEL_PROFILE'] = 'synthetic'
    import torch
    torch.set_num_threads(4)
    output = {'profile':'synthetic', 'real_world_validated':False}
    if args.audio:
        from src.modules.audio_ai.classifier import AudioClassifier
        output['audio'] = asdict(AudioClassifier().predict_file(args.audio))
    if args.image:
        from src.modules.vision_ai.detector import VisionDetector
        output['vision'] = asdict(VisionDetector().predict_image(str(args.image)))
    print(json.dumps(output, indent=2))


if __name__ == '__main__':
    main()
