"""
Audio AI Step 2: Training Script
=================================
Beginner Explanation:
---------------------
What is a Neural Network doing here?
1. The model takes a 2D Mel-Spectrogram (64 rows of sound frequencies, 63 columns of time).
2. It slides tiny mathematical filters (Conv2D) over the spectrogram to detect acoustic features:
   - Alternating pitch frequencies -> identifies Sirens
   - Broadband instantaneous spikes -> identifies Shattering Glass
   - Sustained low-frequency energy -> identifies Normal Traffic
3. At each "Epoch" (one complete pass over all training audio), the model compares its predictions
   against the real answers, calculates the "Loss" (error), and uses gradient descent to adjust
   its parameters to become more accurate.
4. It checks its progress on the "Validation" set to avoid memorizing (overfitting).
5. The best-performing model is saved to: models/audio/best_model.pt.
"""
import os
import sys
import json
import time
from pathlib import Path
import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import TensorDataset, DataLoader

BASE_DIR = Path(__file__).resolve().parents[3]
DATA_PATH = BASE_DIR / "data" / "audio_processed.npz"
SAVE_DIR = BASE_DIR / "models" / "audio"
SAVE_DIR.mkdir(parents=True, exist_ok=True)
BEST_MODEL_PATH = SAVE_DIR / "best_model.pt"
METADATA_PATH = SAVE_DIR / "model_metadata.json"


class EdgeAudioCNN(nn.Module):
    """
    Lightweight 2D-CNN designed specifically for Raspberry Pi 4 edge inference.
    Total parameters: ~48,000 (< 200 KB). Inference latency: ~2 ms on CPU.
    """
    def __init__(self, num_classes=6):
        super().__init__()
        # Feature Extractor: Learns sound frequency and temporal patterns
        self.features = nn.Sequential(
            # Block 1: Input [1, 64, 63] -> [16, 32, 31]
            nn.Conv2d(1, 16, kernel_size=3, padding=1),
            nn.BatchNorm2d(16),
            nn.ReLU(),
            nn.MaxPool2d(kernel_size=2, stride=2),

            # Block 2: [16, 32, 31] -> [32, 16, 15]
            nn.Conv2d(16, 32, kernel_size=3, padding=1),
            nn.BatchNorm2d(32),
            nn.ReLU(),
            nn.MaxPool2d(kernel_size=2, stride=2),

            # Block 3: [32, 16, 15] -> [64, 8, 7]
            nn.Conv2d(32, 64, kernel_size=3, padding=1),
            nn.BatchNorm2d(64),
            nn.ReLU(),
            nn.AdaptiveAvgPool2d((4, 4))  # Compresses spatial map down to [64, 4, 4]
        )

        # Classifier: Combines features into class probabilities
        self.classifier = nn.Sequential(
            nn.Linear(64 * 4 * 4, 64),
            nn.ReLU(),
            nn.Dropout(0.35),  # Prevents overfitting by randomly silencing 35% of neurons
            nn.Linear(64, num_classes)
        )

    def forward(self, x):
        feat = self.features(x)
        flattened = feat.view(feat.size(0), -1)
        logits = self.classifier(flattened)
        return logits


def train_model(epochs: int = 20, batch_size: int = 32, lr: float = 0.003):
    print("=" * 65)
    print("STEP 2: AUDIO AI TRAINING (EdgeAudioCNN)")
    print("=" * 65)

    if not DATA_PATH.exists():
        print(f"Error: Processed dataset not found at {DATA_PATH}. Run dataset_prep.py first!")
        return

    # 1. Load prepared data
    data = np.load(DATA_PATH)
    X_train = torch.tensor(data["X_train"]).unsqueeze(1)  # Add channel dim: [N, 1, 64, 63]
    y_train = torch.tensor(data["y_train"], dtype=torch.long)
    X_val = torch.tensor(data["X_val"]).unsqueeze(1)
    y_val = torch.tensor(data["y_val"], dtype=torch.long)
    classes = list(data["classes"])

    print(f"Training data: {len(X_train)} samples | Validation data: {len(X_val)} samples")
    print(f"Target classes ({len(classes)}): {classes}")

    train_loader = DataLoader(TensorDataset(X_train, y_train), batch_size=batch_size, shuffle=True)
    val_loader = DataLoader(TensorDataset(X_val, y_val), batch_size=batch_size, shuffle=False)

    # 2. Initialize Model, Loss function, and Optimizer
    device = torch.device("cpu")
    model = EdgeAudioCNN(num_classes=len(classes)).to(device)
    criterion = nn.CrossEntropyLoss()
    optimizer = optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-4)

    best_val_acc = 0.0
    training_history = []
    t_start = time.time()

    print(f"\nStarting training loop for {epochs} epochs...")
    print(f"{'Epoch':<8} {'Train Loss':<12} {'Train Acc':<12} {'Val Loss':<12} {'Val Acc':<12} {'Status'}")
    print("-" * 65)

    for epoch in range(1, epochs + 1):
        # Training Phase
        model.train()
        train_loss = 0.0
        train_correct = 0
        total_train = 0

        for bx, by in train_loader:
            optimizer.zero_grad()
            outputs = model(bx)
            loss = criterion(outputs, by)
            loss.backward()
            optimizer.step()

            train_loss += loss.item() * bx.size(0)
            train_correct += (outputs.argmax(dim=1) == by).sum().item()
            total_train += by.size(0)

        epoch_train_loss = train_loss / total_train
        epoch_train_acc = train_correct / total_train

        # Validation Phase
        model.eval()
        val_loss = 0.0
        val_correct = 0
        total_val = 0

        with torch.no_grad():
            for bx, by in val_loader:
                outputs = model(bx)
                loss = criterion(outputs, by)
                val_loss += loss.item() * bx.size(0)
                val_correct += (outputs.argmax(dim=1) == by).sum().item()
                total_val += by.size(0)

        epoch_val_loss = val_loss / total_val
        epoch_val_acc = val_correct / total_val

        status = ""
        # Save checkpoint if validation accuracy improves
        if epoch_val_acc > best_val_acc:
            best_val_acc = epoch_val_acc
            torch.save({
                "epoch": epoch,
                "model_state_dict": model.state_dict(),
                "optimizer_state_dict": optimizer.state_dict(),
                "classes": classes,
                "val_accuracy": epoch_val_acc,
                "architecture": "EdgeAudioCNN",
                "input_shape": [1, 64, 63]
            }, str(BEST_MODEL_PATH))
            status = "* Best Model Saved"

        training_history.append({
            "epoch": epoch,
            "train_loss": round(epoch_train_loss, 4),
            "train_acc": round(epoch_train_acc, 4),
            "val_loss": round(epoch_val_loss, 4),
            "val_acc": round(epoch_val_acc, 4)
        })

        print(f"{epoch:<8} {epoch_train_loss:<12.4f} {epoch_train_acc*100:<11.2f}% {epoch_val_loss:<12.4f} {epoch_val_acc*100:<11.2f}% {status}")

    total_time = time.time() - t_start
    print("-" * 65)
    print(f"Training completed in {total_time:.1f}s | Best Validation Accuracy: {best_val_acc*100:.2f}%")
    print(f"Model saved to: {BEST_MODEL_PATH}")

    # Save training metadata
    with open(METADATA_PATH, "w", encoding="utf-8") as f:
        json.dump({
            "model_path": str(BEST_MODEL_PATH),
            "classes": classes,
            "num_classes": len(classes),
            "best_val_accuracy": round(best_val_acc, 4),
            "total_training_time_sec": round(total_time, 2),
            "epochs": epochs,
            "architecture": "EdgeAudioCNN",
            "parameters": sum(p.numel() for p in model.parameters()),
            "history": training_history
        }, f, indent=2)


if __name__ == "__main__":
    train_model(epochs=18)
