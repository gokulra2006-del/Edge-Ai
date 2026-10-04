"""Train the existing EdgeAcousticNet and two YOLO11n models; evaluate held-out data."""
import argparse
import copy
import hashlib
import json
import os
import random
import shutil
import time
from pathlib import Path

import numpy as np
import torch
from sklearn.metrics import classification_report, confusion_matrix
from torch.utils.data import DataLoader, TensorDataset

from src.modules.audio_ai.classifier import EdgeAcousticNet
from src.modules.audio_ai.features import DEFAULT_FEATURES, file_features

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT/'data/new_dataset'
OUT = ROOT/'models/new_dataset'


def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2))


def train_audio(args):
    rows = json.loads((DATA/'audio_manifest.json').read_text())
    classes = sorted({r['label'] for r in rows})
    # Semantic aliases only: a generic siren cannot identify the responder subtype.
    aliases = {'ambient':'traffic', 'horn':'car_horn', 'crash':'crash', 'siren':'siren'}
    if set(classes) != set(aliases):
        raise ValueError('Review class mapping for changed dataset labels')
    features = torch.cat([file_features(DATA/r['path']) for r in rows])
    targets = torch.tensor([classes.index(r['label']) for r in rows])
    loaders = {}
    for split in ['train','val','test']:
        indices = [i for i,r in enumerate(rows) if r['split']==split]
        loaders[split] = DataLoader(TensorDataset(features[indices],targets[indices]),
                                   batch_size=args.batch, shuffle=split=='train', num_workers=0)
    model = EdgeAcousticNet(len(classes))
    train_targets = loaders['train'].dataset.tensors[1]
    counts = torch.bincount(train_targets, minlength=len(classes))
    weights = len(train_targets)/(len(classes)*counts.float())
    criterion = torch.nn.CrossEntropyLoss(weight=weights)
    optimizer = torch.optim.AdamW(model.parameters(), lr=.001, weight_decay=1e-4)
    best_loss, best_state, best_epoch, stale = float('inf'), None, 0, 0
    history = []
    start = time.time()
    for epoch in range(1,args.audio_epochs+1):
        metrics = {'epoch':epoch}
        for split in ['train','val']:
            model.train(split=='train')
            loss_sum = correct = total = 0
            with torch.set_grad_enabled(split=='train'):
                for x,y in loaders[split]:
                    logits = model(x)
                    loss = criterion(logits,y)
                    if split=='train':
                        optimizer.zero_grad()
                        loss.backward()
                        optimizer.step()
                    loss_sum += loss.item()*len(y)
                    correct += int((logits.argmax(1)==y).sum())
                    total += len(y)
            metrics[split+'_loss'] = loss_sum/total
            metrics[split+'_accuracy'] = correct/total
        history.append(metrics)
        print(json.dumps(metrics), flush=True)
        if metrics['val_loss'] < best_loss - 1e-5:
            best_loss = metrics['val_loss']
            best_state = copy.deepcopy(model.state_dict())
            best_epoch, stale = epoch, 0
        else:
            stale += 1
        if stale >= args.patience:
            break
    model.load_state_dict(best_state)
    model.eval()
    predictions, actual = [], []
    with torch.inference_mode():
        for x,y in loaders['test']:
            predictions.extend(model(x).argmax(1).tolist())
            actual.extend(y.tolist())
    report = classification_report(actual,predictions,labels=list(range(len(classes))),
                                   target_names=classes,output_dict=True,zero_division=0)
    report['confusion_matrix'] = confusion_matrix(actual,predictions).tolist()
    report['classes'] = classes
    report['evaluation_domain'] = 'synthetic held-out recordings, not real-world validation'
    config = {'seed':args.seed,'epochs_requested':args.audio_epochs,'epochs_run':len(history),
              'batch_size':args.batch,'learning_rate':.001,'optimizer':'AdamW','weight_decay':1e-4,
              'early_stopping_patience':args.patience,'best_epoch':best_epoch,
              'class_weights':weights.tolist(),'preprocessing':DEFAULT_FEATURES,
              'history':history,'elapsed_seconds':time.time()-start,'threads':args.threads}
    OUT.mkdir(parents=True, exist_ok=True)
    torch.save({'model_state_dict':best_state,'classes':classes,'label_mapping':aliases,
                'preprocessing':DEFAULT_FEATURES,'architecture':'EdgeAcousticNet',
                'synthetic':True,'training_config':config},OUT/'audio.pt')
    save_json(OUT/'audio_evaluation.json',report)
    save_json(OUT/'audio_training.json',config)
    print('AUDIO TEST',json.dumps(report),flush=True)


def train_vision(domain,args):
    yolo_config = ROOT / 'logs' / 'ultralytics'
    matplotlib_config = ROOT / 'logs' / 'matplotlib'
    yolo_config.mkdir(parents=True, exist_ok=True)
    matplotlib_config.mkdir(parents=True, exist_ok=True)
    os.environ['YOLO_CONFIG_DIR'] = str(yolo_config)
    os.environ['MPLCONFIGDIR'] = str(matplotlib_config)
    from ultralytics import YOLO
    # Base COCO weights have never seen the newly created synthetic holdout.
    model = YOLO(str(ROOT/'yolo11n.pt'))
    model.train(data=str(DATA/domain/'data.yaml'), epochs=args.vision_epochs,
                imgsz=args.imgsz,batch=args.batch,device='cpu',workers=0,seed=args.seed,
                deterministic=True,patience=args.patience,optimizer='AdamW',lr0=.001,
                freeze=10,project=str(OUT/'runs'),name=f'{domain}_cpu',exist_ok=False,
                mosaic=0.0,close_mosaic=0,plots=True,amp=False)
    best = Path(model.trainer.best)
    shutil.copyfile(best,OUT/f'{domain}.pt')
    candidate = YOLO(str(OUT/f'{domain}.pt'))
    result = candidate.val(data=str(DATA/domain/'data.yaml'),split='test',imgsz=args.imgsz,
                           batch=args.batch,device='cpu',workers=0,plots=True,
                           project=str(OUT/'runs'),name=domain+'_test')
    per_class = []
    for index, cls in enumerate(result.box.ap_class_index):
        p,r,ap50,ap = result.box.class_result(index)
        per_class.append({'class':candidate.names[int(cls)],'precision':float(p),'recall':float(r),
                          'f1':float(2*p*r/(p+r)) if p+r else 0.0,
                          'mAP50':float(ap50),'mAP50_95':float(ap)})
    report = {'metrics':{k:float(v) for k,v in result.results_dict.items()},
              'per_class':per_class,'confusion_matrix':result.confusion_matrix.matrix.tolist(),
              'evaluation_domain':'synthetic held-out images, not real-world validation',
              'classes':candidate.names,'imgsz':args.imgsz,'results_dir':str(result.save_dir)}
    save_json(OUT/f'{domain}_evaluation.json',report)
    print(domain.upper()+' TEST '+json.dumps(report),flush=True)


def finalize(args):
    expected = ['audio.pt','fire_smoke.pt','vehicle.pt']
    if not all((OUT/p).exists() for p in expected):
        return
    save_json(OUT/'profile.json',{'name':'synthetic','synthetic':True,
              'audio':'models/new_dataset/audio.pt',
              'vision':['models/new_dataset/fire_smoke.pt','models/new_dataset/vehicle.pt'],
              'imgsz':args.imgsz,'confidence_threshold':.35,
              'usage':'Synthetic demonstration/augmentation; not validated for physical emergency response.',
              'sha256':{p:hashlib.sha256((OUT/p).read_bytes()).hexdigest() for p in expected}})
    shutil.copyfile(DATA/'audit.json',OUT/'dataset_audit.json')
    import importlib.metadata
    save_json(OUT/'environment.json', {
        'packages': {name:importlib.metadata.version(name) for name in
                     ['torch','torchvision','ultralytics','numpy','scipy','scikit-learn','soundfile','Pillow']},
        'manifest_sha256': {domain:hashlib.sha256((DATA/f'{domain}_manifest.json').read_bytes()).hexdigest()
                           for domain in ['audio','fire_smoke','vehicle']},
        'base_yolo_sha256': hashlib.sha256((ROOT/'yolo11n.pt').read_bytes()).hexdigest()})


if __name__=='__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--domain',choices=['audio','fire_smoke','vehicle','all'],default='all')
    parser.add_argument('--audio-epochs',type=int,default=25)
    parser.add_argument('--vision-epochs',type=int,default=3)
    parser.add_argument('--patience',type=int,default=6)
    parser.add_argument('--batch',type=int,default=16)
    parser.add_argument('--imgsz',type=int,default=160)
    parser.add_argument('--threads',type=int,default=4)
    parser.add_argument('--seed',type=int,default=42)
    args=parser.parse_args()
    random.seed(args.seed); np.random.seed(args.seed); torch.manual_seed(args.seed)
    torch.set_num_threads(args.threads)
    torch.use_deterministic_algorithms(True)
    if args.domain in ['audio','all']:
        train_audio(args)
    for domain in ['fire_smoke','vehicle']:
        if args.domain in [domain,'all']:
            train_vision(domain,args)
    finalize(args)
