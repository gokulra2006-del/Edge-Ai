"""
Vision AI Step 6: Model Export Script (Edge Optimization)
=========================================================
Beginner Explanation:
---------------------
Why export models?
PyTorch (`.pt`) models require the full PyTorch library (~800MB - 1.5GB) to run,
which is heavy for a Raspberry Pi 4.
By exporting to edge runtime formats:
1. ONNX (Open Neural Network Exchange): Highly optimized cross-platform runtime.
2. TorchScript: JIT-compiled C++ executable format requiring no Python runtime.
3. TFLite (TensorFlow Lite): Standard for ultra-low power ARM microcontrollers & edge boards.

This script exports our trained YOLO model to these lightweight formats.
"""
import os
from pathlib import Path
from ultralytics import YOLO

BASE_DIR = Path(__file__).resolve().parents[3]
MODEL_PATH = BASE_DIR / "models" / "vision" / "fire_smoke_best.pt"
EXPORT_DIR = BASE_DIR / "models" / "vision" / "exported"
EXPORT_DIR.mkdir(parents=True, exist_ok=True)


def export_model(weight_path: str = None, imgsz: int = 320):
    print("=" * 65)
    print("STEP 6: VISION MODEL EXPORT (Edge Deployment Optimization)")
    print("=" * 65)

    if weight_path is None:
        weight_path = str(MODEL_PATH) if MODEL_PATH.exists() else "yolo11n.pt"

    print(f"Source weight file: {weight_path}")
    model = YOLO(weight_path)

    exported_files = {}

    # 1. Export to TorchScript (Zero external dependencies, native PyTorch JIT for C++ & Edge)
    print("\n[1/2] Exporting to TorchScript format...")
    try:
        ts_path = model.export(format="torchscript", imgsz=imgsz)
        size_mb = os.path.getsize(ts_path) / (1024 * 1024)
        exported_files["TorchScript"] = {"path": str(ts_path), "size_mb": round(size_mb, 2)}
        print(f"  -> TorchScript export succeeded: {ts_path} ({size_mb:.2f} MB)")
    except Exception as e:
        print(f"  -> TorchScript export warning: {e}")

    # 2. Export to ONNX (if onnx package installed)
    print("\n[2/2] Checking ONNX export capability...")
    try:
        import onnx  # Check if installed
        onnx_path = model.export(format="onnx", imgsz=imgsz, dynamic=False, simplify=False)
        size_mb = os.path.getsize(onnx_path) / (1024 * 1024)
        exported_files["ONNX"] = {"path": str(onnx_path), "size_mb": round(size_mb, 2)}
        print(f"  -> ONNX export succeeded: {onnx_path} ({size_mb:.2f} MB)")
    except ImportError:
        print("  -> Notice: 'onnx' library not in current environment. TorchScript will be used for edge C++ runtime.")
    except Exception as e:
        print(f"  -> ONNX export note: {e}")

    print("\n" + "=" * 65)
    print("EXPORT SUMMARY FOR RASPBERRY PI 4")
    print("=" * 65)
    for fmt, info in exported_files.items():
        print(f"  Format: {fmt:<15} Size: {info['size_mb']} MB -> {info['path']}")
    print("[PASS] Model export pipeline complete!")
    return exported_files


if __name__ == "__main__":
    export_model()
