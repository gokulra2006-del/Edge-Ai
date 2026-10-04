"""
Audio AI Step 4: Evaluation Script
===================================
Beginner Explanation:
---------------------
How do we know the model works on completely unseen real-world audio?
We test it against the "Test Set" (15% of our audio that was completely locked away
during both training and validation).

In this script, we calculate:
1. Accuracy: Total correct predictions / total sounds.
2. Precision: When the model predicts "siren", what percentage were actually sirens?
3. Recall: Out of all actual sirens, how many did the model successfully catch?
4. F1-Score: Harmonic mean balancing Precision and Recall.
5. Confusion Matrix: A grid showing exactly which sound was confused with which.
6. False Positive Rate (FPR): Frequency of false alarms triggered when no emergency occurred.
7. Inference Latency: Time in milliseconds to classify one audio buffer on CPU.
"""
import sys
import json
import time
from pathlib import Path
import numpy as np
import torch
from torch.utils.data import TensorDataset, DataLoader

BASE_DIR = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(BASE_DIR))
DATA_PATH = BASE_DIR / "data" / "audio_processed.npz"
MODEL_PATH = BASE_DIR / "models" / "audio" / "best_model.pt"
REPORT_PATH = BASE_DIR / "models" / "audio" / "evaluation_report.json"

from src.modules.audio_ai.train import EdgeAudioCNN


def evaluate():
    print("=" * 65)
    print("STEP 4: INDEPENDENT TEST EVALUATION & METRIC AUDIT")
    print("=" * 65)

    if not MODEL_PATH.exists():
        print(f"Error: Model not found at {MODEL_PATH}")
        return

    checkpoint = torch.load(str(MODEL_PATH), map_location="cpu", weights_only=False)
    classes = checkpoint["classes"]
    num_classes = len(classes)

    model = EdgeAudioCNN(num_classes=num_classes)
    model.load_state_dict(checkpoint["model_state_dict"])
    model.eval()

    # Load Test Data
    data = np.load(DATA_PATH)
    X_test = torch.tensor(data["X_test"]).unsqueeze(1)
    y_test = torch.tensor(data["y_test"], dtype=torch.long)

    print(f"Evaluating model on {len(X_test)} completely unseen test recordings...")

    test_loader = DataLoader(TensorDataset(X_test, y_test), batch_size=32, shuffle=False)

    all_preds = []
    with torch.no_grad():
        for bx, _ in test_loader:
            out = model(bx)
            all_preds.extend(out.argmax(dim=1).numpy())

    all_preds = np.array(all_preds)
    y_test_np = y_test.numpy()

    # 1. Confusion Matrix
    conf_matrix = np.zeros((num_classes, num_classes), dtype=int)
    for t, p in zip(y_test_np, all_preds):
        conf_matrix[t, p] += 1

    total_samples = len(y_test_np)

    # 2. Per-Class Precision, Recall, F1, FPR
    per_class_metrics = {}
    f1_list = []

    print(f"\n{'Class Name':<18} {'Precision':<11} {'Recall':<11} {'F1-Score':<11} {'FPR':<11} {'Support':<8}")
    print("-" * 72)

    for i, cname in enumerate(classes):
        tp = conf_matrix[i, i]
        fp = conf_matrix[:, i].sum() - tp
        fn = conf_matrix[i, :].sum() - tp
        tn = total_samples - (tp + fp + fn)
        support = int(conf_matrix[i, :].sum())

        prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        rec = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = 2 * (prec * rec) / (prec + rec) if (prec + rec) > 0 else 0.0
        fpr = fp / (fp + tn) if (fp + tn) > 0 else 0.0
        f1_list.append(f1)

        per_class_metrics[cname] = {
            "precision": round(float(prec), 4),
            "recall": round(float(rec), 4),
            "f1_score": round(float(f1), 4),
            "false_positive_rate": round(float(fpr), 4),
            "support": support
        }
        print(f"{cname:<18} {prec*100:<10.2f}% {rec*100:<10.2f}% {f1*100:<10.2f}% {fpr*100:<10.2f}% {support:<8}")

    overall_accuracy = (all_preds == y_test_np).mean()
    macro_f1 = np.mean(f1_list)

    print("-" * 72)
    print(f"Overall Test Accuracy: {overall_accuracy * 100:.2f}% | Macro F1: {macro_f1 * 100:.2f}%\n")

    # 3. Print Formatted Confusion Matrix
    print("Confusion Matrix (Rows = Actual, Columns = Predicted):")
    header = "             " + "".join([f"{c[:7]:>9}" for c in classes])
    print(header)
    for i, cname in enumerate(classes):
        row_str = f"{cname[:12]:<13} " + "".join([f"{conf_matrix[i, j]:>9}" for j in range(num_classes)])
        print(row_str)

    # 4. Measure Real Single-Sample Inference Latency
    sample_input = X_test[0:1]  # Shape [1, 1, 64, 63]
    # Warmup
    for _ in range(10):
        _ = model(sample_input)

    latencies = []
    for _ in range(100):
        t0 = time.perf_counter()
        _ = model(sample_input)
        latencies.append((time.perf_counter() - t0) * 1000.0)  # Convert to ms

    avg_latency_ms = float(np.mean(latencies))
    p95_latency_ms = float(np.percentile(latencies, 95))

    print(f"\nInference Latency (CPU Single Sample):")
    print(f"  Average Latency: {avg_latency_ms:.2f} ms")
    print(f"  95th Percentile: {p95_latency_ms:.2f} ms")
    print(f"  Throughput:      {1000.0 / avg_latency_ms:.1f} audio buffers / second")

    # 5. Save Full JSON Evaluation Report
    report = {
        "model_file": str(MODEL_PATH),
        "overall_accuracy": round(float(overall_accuracy), 4),
        "macro_f1": round(float(macro_f1), 4),
        "latency_ms": {
            "average": round(avg_latency_ms, 2),
            "p95": round(p95_latency_ms, 2)
        },
        "confusion_matrix": conf_matrix.tolist(),
        "per_class_metrics": per_class_metrics,
        "classes": classes
    }

    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    print(f"\nFull evaluation report saved to: {REPORT_PATH}")
    return report


if __name__ == "__main__":
    evaluate()
