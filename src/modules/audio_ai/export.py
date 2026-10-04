"""
Audio AI Step 6: Model Export Script
====================================
Beginner Explanation:
---------------------
Why export the model?
While PyTorch (.pt) is great for training on a laptop/Colab, edge devices like
the Raspberry Pi 4 benefit from optimized deployment formats:
1. TorchScript (.torchscript): Packages the neural network architecture AND weights together
   into a single compiled binary that runs without needing the original Python class definitions.
2. ONNX (.onnx): Universal format compatible with ONNX Runtime, OpenVINO, and NCNN for
   hardware acceleration on ARM CPUs.
"""
import os
import sys
from pathlib import Path
import torch

BASE_DIR = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(BASE_DIR))
MODEL_PATH = BASE_DIR / "models" / "audio" / "best_model.pt"
EXPORT_DIR = BASE_DIR / "models" / "audio"
TORCHSCRIPT_PATH = EXPORT_DIR / "model.torchscript"
ONNX_PATH = EXPORT_DIR / "model.onnx"

from src.modules.audio_ai.train import EdgeAudioCNN


def export_models():
    print("=" * 65)
    print("STEP 6: EDGE MODEL EXPORT (TorchScript & ONNX)")
    print("=" * 65)

    if not MODEL_PATH.exists():
        print(f"Error: Model not found at {MODEL_PATH}")
        return

    checkpoint = torch.load(str(MODEL_PATH), map_location="cpu", weights_only=False)
    classes = checkpoint["classes"]
    model = EdgeAudioCNN(num_classes=len(classes))
    model.load_state_dict(checkpoint["model_state_dict"])
    model.eval()

    # Dummy input matching the Mel-Spectrogram dimensions: [Batch=1, Channel=1, Mels=64, Frames=63]
    dummy_input = torch.randn(1, 1, 64, 63, dtype=torch.float32)

    # 1. Export to TorchScript
    print("Exporting to TorchScript (optimized for PyTorch C++ / Edge)...")
    traced_script_module = torch.jit.trace(model, dummy_input)
    traced_script_module.save(str(TORCHSCRIPT_PATH))
    ts_size_kb = os.path.getsize(TORCHSCRIPT_PATH) / 1024
    print(f"  -> Saved TorchScript: {TORCHSCRIPT_PATH.name} ({ts_size_kb:.1f} KB)")

    # 2. Export to ONNX
    print("Exporting to ONNX (Open Neural Network Exchange)...")
    try:
        torch.onnx.export(
            model,
            dummy_input,
            str(ONNX_PATH),
            export_params=True,
            opset_version=14,
            do_constant_folding=True,
            input_names=["spectrogram_input"],
            output_names=["logits_output"],
            dynamic_axes={"spectrogram_input": {0: "batch_size"}, "logits_output": {0: "batch_size"}}
        )
        onnx_size_kb = os.path.getsize(ONNX_PATH) / 1024
        print(f"  -> Saved ONNX:        {ONNX_PATH.name} ({onnx_size_kb:.1f} KB)")
    except Exception as e:
        print(f"  -> ONNX export note: {e}")

    print("\nExport Summary:")
    print(f"  Base PyTorch:  {MODEL_PATH} ({os.path.getsize(MODEL_PATH) / 1024:.1f} KB)")
    print(f"  TorchScript:   {TORCHSCRIPT_PATH} ({ts_size_kb:.1f} KB)")
    if ONNX_PATH.exists():
        print(f"  ONNX Edge:     {ONNX_PATH} ({os.path.getsize(ONNX_PATH) / 1024:.1f} KB)")
    print("Model export complete!")


if __name__ == "__main__":
    export_models()
