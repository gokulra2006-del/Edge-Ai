"""Audit and safely merge the supplied independent ZIP parts; never run bundled code."""
import argparse
import csv
import hashlib
import json
import random
import shutil
import zipfile
from collections import Counter
from pathlib import Path

import numpy as np
import soundfile as sf
import yaml
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]


def digest(data):
    return hashlib.sha256(data).hexdigest()


def safe_path(root, name):
    target = (root / name).resolve()
    if not target.is_relative_to(root.resolve()) or ':' in name or '\\' in name:
        raise ValueError(f'Unsafe archive path: {name}')
    return target


def prepare(downloads, output, seed=42):
    if (output/'audit.json').exists():
        previous = json.loads((output/'audit.json').read_text())
        if previous['seed'] != seed:
            raise ValueError('Use a fresh output directory when changing the split seed')
    output.mkdir(parents=True, exist_ok=True)
    raw = output / 'raw'
    report = {'seed': seed, 'provenance': 'procedurally generated synthetic data',
              'archives': [], 'duplicate_archives': [], 'duplicate_members': 0,
              'redundant_split_archive': 'acoustic_emergency_audio.z01 + .zip: independent acoustic parts used instead',
              'datasets': {}}
    archive_hashes, members = {}, {}
    for prefix, count in [('acoustic', 6), ('fire_smoke', 7), ('vehicle', 7)]:
        for part in range(1, count + 1):
            name = f'{prefix}_part{part:02d}_of{count:02d}.zip'
            source = downloads / name
            sha = digest(source.read_bytes())
            report['archives'].append({'name': name, 'sha256': sha})
            archive_hashes[name] = sha
            for duplicate in sorted(downloads.glob(name[:-4] + '_*.zip')):
                if digest(duplicate.read_bytes()) != sha:
                    raise ValueError(f'Conflicting archive copy: {duplicate}')
                report['duplicate_archives'].append(duplicate.name)
            with zipfile.ZipFile(source) as archive:
                for info in archive.infolist():
                    if info.is_dir():
                        continue
                    target = safe_path(raw, info.filename)
                    blob = archive.read(info)  # verifies CRC
                    content_hash = digest(blob)
                    if info.filename in members:
                        if members[info.filename] != content_hash:
                            raise ValueError(f'Conflicting member: {info.filename}')
                        report['duplicate_members'] += 1
                        continue
                    members[info.filename] = content_hash
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(blob)
    audio_root = raw / 'acoustic_emergency_audio'
    with (audio_root / 'labels.csv').open(newline='') as handle:
        reader = csv.DictReader(handle)
        columns = reader.fieldnames
        audio_rows = list(reader)
    records, hashes, invalid, duplicates = [], {}, [], []
    for row in audio_rows:
        try:
            path = safe_path(audio_root, row['filepath'])
            samples, sr = sf.read(path, dtype='float32', always_2d=True)
            if not row['label'] or len(samples) == 0 or not np.isfinite(samples).all():
                raise ValueError('Missing label, empty or nonfinite audio')
            if sr != int(row['sample_rate']) or abs(len(samples)/sr - float(row['duration_s'])) > 1/sr:
                raise ValueError('Audio metadata mismatch')
            sha = digest(samples.tobytes())
            if sha in hashes:
                if hashes[sha] != row['label']:
                    raise ValueError('Conflicting duplicate labels')
                duplicates.append(row['filepath'])
                continue
            hashes[sha] = row['label']
            records.append({'path': path.relative_to(output).as_posix(), 'label': row['label'],
                            'sha256': sha, 'sample_rate': sr, 'channels': samples.shape[1],
                            'duration_s': len(samples)/sr, 'peak': float(np.abs(samples).max())})
        except (ValueError, OSError, RuntimeError) as exc:
            invalid.append({'row': row, 'error': str(exc)})
    classes = sorted({r['label'] for r in records})
    rng = random.Random(seed)
    for label in classes:
        subset = [r for r in records if r['label'] == label]
        rng.shuffle(subset)
        n = len(subset)
        for i, row in enumerate(subset):
            row['split'] = 'train' if i < int(n*.7) else ('val' if i < int(n*.85) else 'test')
    report['datasets']['audio'] = {'columns': columns, 'samples': len(records), 'classes': classes,
        'class_distribution': dict(Counter(r['label'] for r in records)), 'invalid': invalid,
        'duplicates': duplicates, 'split_counts': dict(Counter(r['split'] for r in records)),
        'sample_rates': sorted({r['sample_rate'] for r in records}),
        'durations_s': sorted({r['duration_s'] for r in records}),
        'peak_range': [min(r['peak'] for r in records), max(r['peak'] for r in records)]}
    (output/'audio_manifest.json').write_text(json.dumps(records, indent=2))
    for domain, folder in [('fire_smoke', 'fire_smoke_vision'), ('vehicle', 'vehicle_detection_vision')]:
        source_root = raw / folder
        metadata = yaml.safe_load((source_root/'data.yaml').read_text())
        names = metadata['names']
        rows, seen, bad, duplicate = [], {}, [], []
        for image_path in sorted((source_root/'images').glob('*/*')):
            label_path = source_root/'labels'/image_path.parent.name/(image_path.stem+'.txt')
            try:
                with Image.open(image_path) as image:
                    image.load()
                    pixels = np.asarray(image.convert('RGB'))
                boxes = []
                for line in label_path.read_text().splitlines():
                    values = [float(v) for v in line.split()]
                    if len(values) != 5 or not np.isfinite(values).all():
                        raise ValueError('Invalid YOLO row')
                    cls, x, y, w, h = values
                    if cls != int(cls) or not 0 <= cls < len(names) or not 0 < w <= 1 or not 0 < h <= 1:
                        raise ValueError('Invalid class/box size')
                    if min(x-w/2,y-h/2) < -1e-5 or max(x+w/2,y+h/2) > 1.00001:
                        raise ValueError('Box outside image')
                    boxes.append(values)
                sha = digest(pixels.tobytes())
                if sha in seen:
                    if seen[sha] != boxes:
                        raise ValueError('Conflicting duplicate labels')
                    duplicate.append(str(image_path))
                    continue
                seen[sha] = boxes
                rows.append({'source': image_path.relative_to(output).as_posix(),
                             'label_source': label_path.relative_to(output).as_posix(),
                             'sha256': sha, 'boxes': boxes, 'size': list(pixels.shape),
                             'split': image_path.parent.name})
            except (ValueError, OSError) as exc:
                bad.append({'path': str(image_path), 'error': str(exc)})
        # Keep supplied train untouched; divide the original validation pool before any training.
        # Stratify on presence of classes, including background images.
        signatures = sorted({tuple(sorted({int(b[0]) for b in r['boxes']})) for r in rows if r['split']=='val'})
        for signature in signatures:
            pool = [r for r in rows if r['split']=='val' and tuple(sorted({int(b[0]) for b in r['boxes']}))==signature]
            rng.shuffle(pool)
            for r in pool[len(pool)//2:]:
                r['split'] = 'test'
        dest = output/domain
        for row in rows:
            # Original train/val filenames overlap, so preserve their origin in the new name.
            origin = Path(row['source'])
            name = origin.parent.name + '_' + origin.name
            target = dest/'images'/row['split']/name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(output/row['source'], target)
            label_target = dest/'labels'/row['split']/(Path(name).stem+'.txt')
            label_target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(output/row['label_source'], label_target)
            row['path'] = target.relative_to(output).as_posix()
        config = {'path': dest.resolve().as_posix(), 'train':'images/train', 'val':'images/val',
                  'test':'images/test', 'names': names, 'nc': len(names)}
        (dest/'data.yaml').write_text(yaml.safe_dump(config, sort_keys=False))
        (output/f'{domain}_manifest.json').write_text(json.dumps(rows, indent=2))
        report['datasets'][domain] = {'samples':len(rows), 'classes': names, 'invalid':bad,
            'duplicates':duplicate, 'split_counts':dict(Counter(r['split'] for r in rows)),
            'box_distribution':dict(Counter(names[int(b[0])] for r in rows for b in r['boxes'])),
            'background_images':sum(not r['boxes'] for r in rows),
            'image_shapes': sorted({tuple(r['size']) for r in rows}),
            'per_split_boxes':{sp:dict(Counter(names[int(b[0])] for r in rows if r['split']==sp for b in r['boxes'])) for sp in ['train','val','test']}}
    report['leakage_checks'] = 'Decoded-content SHA256 deduplication before splitting; disjoint hashes per modality. No source recording groups exist: samples independently generated. Same-generator distribution is NOT real-world validation.'
    (output/'audit.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--downloads', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=ROOT/'data/new_dataset')
    parser.add_argument('--seed', type=int, default=42)
    args = parser.parse_args()
    prepare(args.downloads, args.output, args.seed)
