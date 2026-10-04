"""
Audio AI Step 3: Validation Script
===================================
Beginner Explanation:
---------------------
Before trusting a trained model, we must validate that:
1. The checkpoint file loads correctly without errors.
2. The neural network architecture matches the expected weight tensor shapes.
3. The model achieves the recorded accuracy on the held-out validation dataset.
"""
import sys
from pathlib import Path
import numpy as np
import torch
from torch.utils.data import TensorDataset, DataLoader

BASE_DIR = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(BASE_DIR))
DATA_PATH = BASE_DIR / "data" / "audio_processed.npz"
MODEL_PATH = BASE_DIR / "models" / "audio" / "best_model.pt"

# Import model architecture
from src.modules.audio_ai.train import EdgeAudioCNN


def validate():
    print("=" * 65)
    print("STEP 3: AUDIO MODEL CHECKPOINT VALIDATION")
    print("=" * 65)

    if not MODEL_PATH.exists():
        print(f"Error: Model not found at {MODEL_PATH}. Run train.py first!")
        return False

    # 1. Load Checkpoint
    checkpoint = torch.load(str(MODEL_PATH), map_location="cpu", weights_only=False)
    classes = checkpoint["classes"]
    epoch_saved = checkpoint.get("epoch", "N/A")
    saved_val_acc = checkpoint.get("val_accuracy", 0.0)

    print(f"Loaded Checkpoint: {MODEL_PATH.name}")
    print(f"  - Saved at Epoch: {epoch_saved}")
    print(f"  - Target Classes: {classes}")
    print(f"  - Expected Validation Accuracy: {saved_val_acc * 100:.2f}%")

    # 2. Re-instantiate Architecture
    model = EdgeAudioCNN(num_classes=len(classes))
    model.load_state_dict(checkpoint["model_state_dict"])
    model.eval()

    total_params = sum(p.numel() for p in model.parameters())
    print(f"  - Model Parameters: {total_params:,} (~{total_params * 4 / 1024:.1f} KB in float32)")

    # 3. Test on Validation Split
    data = np.load(DATA_PATH)
    X_val = torch.tensor(data["X_val"]).unsqueeze(1)
    y_val = torch.tensor(data["y_val"], dtype=torch.long)

    val_loader = DataLoader(TensorDataset(X_val, y_val), batch_size=32, shuffle=False)

    correct = 0
    total = 0
    with torch.no_grad():
        for bx, by in val_loader:
            preds = model(bx).argmax(dim=1)
            correct += (preds == by).sum().item()
            total += by.size(0)

    recalculated_acc = correct / total
    print(f"\nRecalculated Validation Accuracy: {recalculated_acc * 100:.2f}%")

    if abs(recalculated_acc - saved_val_acc) < 0.001:
        print("[PASS] Model weights and validation metrics are 100% verified!")
        return True
    else:
        print("[WARN] Slight discrepancy between checkpoint metadata and recalculated accuracy.")
        return False


if __name__ == "__main__":
    validate()
