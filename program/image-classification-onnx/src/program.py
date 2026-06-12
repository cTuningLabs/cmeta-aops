#!/usr/bin/env python3
"""
Image Classifier using ONNX Runtime
Usage:
  python classify.py <image> <model> <classes_file> [-v]

Arguments:
  image          Path to a .jpg or .png image
  model          Path to an .onnx file  OR  a directory containing one
  classes_file   Path to a text file with one class label per line
  -v             (optional) Show top-5 predictions with probabilities

Examples:
  # From a local .onnx file:
  python classify.py cat.jpg ./models/resnet50.onnx imagenet_classes.txt -v

  # From a directory containing an .onnx model:
  python classify.py cat.jpg ./models/vit-base imagenet_classes.txt -v
"""

import argparse
import os
import sys
from pathlib import Path

import numpy as np
from PIL import Image
import onnxruntime as ort


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def load_classes(path: str) -> list[str]:
    """Read class labels – one per line, blank lines and # comments ignored."""
    classes = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                classes.append(line)
    if not classes:
        sys.exit(f"[ERROR] No class labels found in '{path}'")
    return classes


def get_transform(img: Image.Image, image_size: int = 224) -> np.ndarray:
    """Standard ImageNet-style pre-processing returning a NCHW float32 tensor."""
    mean = np.array([0.485, 0.456, 0.406], dtype=np.float32)
    std  = np.array([0.229, 0.224, 0.225], dtype=np.float32)

    # Resize (slight over-size) then center crop
    resize = image_size + 32
    img = img.resize((resize, resize), Image.BILINEAR)

    left = (resize - image_size) // 2
    top  = (resize - image_size) // 2
    img = img.crop((left, top, left + image_size, top + image_size))

    arr = np.asarray(img, dtype=np.float32) / 255.0   # HWC, [0, 1]
    arr = (arr - mean) / std                           # normalize
    arr = np.transpose(arr, (2, 0, 1))                 # CHW
    arr = np.expand_dims(arr, axis=0)                  # NCHW
    return np.ascontiguousarray(arr, dtype=np.float32)


def select_providers() -> list[str]:
    """
    Pick ONNX Runtime execution providers based on cMeta's selected compute
    targets, always falling back to the CPU provider.
    """
    cmeta_targets = os.environ.get('CMETA_TARGETS', '').split(',')

    preferred = []
    if 'cuda' in cmeta_targets:
        preferred.append('CUDAExecutionProvider')
    if 'rocm' in cmeta_targets:
        preferred.append('ROCMExecutionProvider')
    if 'xpu' in cmeta_targets:
        preferred.append('OpenVINOExecutionProvider')
    if 'metal' in cmeta_targets:
        preferred.append('CoreMLExecutionProvider')

    available = ort.get_available_providers()
    providers = [p for p in preferred if p in available]
    if 'CPUExecutionProvider' not in providers:
        providers.append('CPUExecutionProvider')

    return providers


def load_model(model_id: str):
    """
    Load an ONNX model from either:
      - a local .onnx file path, OR
      - a directory containing one or more .onnx files (first match is used)
    """
    local_path = Path(model_id)

    if not local_path.exists():
        sys.exit(f"[ERROR] Model path not found: {local_path}")

    if local_path.is_file():
        if local_path.suffix.lower() != ".onnx":
            sys.exit(f"[ERROR] Model file is not an .onnx file: {local_path}")
        onnx_path = local_path
        print(f"[INFO] Loading ONNX model from local file: {onnx_path}")
    else:
        # Search recursively: HF ONNX exports often live in an "onnx/" subfolder.
        # Prefer the plain "model.onnx" over quantized variants (model_q4.onnx, etc.).
        hits = sorted(local_path.rglob("*.onnx"))
        if not hits:
            sys.exit(f"[ERROR] No .onnx file found in model directory: {local_path}")
        onnx_path = next((h for h in hits if h.name == "model.onnx"), hits[0])
        print(f"[INFO] Loading ONNX model from local directory: {onnx_path}")

    providers = select_providers()
    session = ort.InferenceSession(str(onnx_path), providers=providers)
    print(f"[INFO] Active execution providers: {session.get_providers()}")

    return session


def _model_image_size(session, default: int = 224) -> int:
    """Read the expected square input size from the model, fall back to default."""
    try:
        shape = session.get_inputs()[0].shape   # e.g. [N, 3, 224, 224]
        h = shape[-2]
        if isinstance(h, int) and h > 0:
            return h
    except Exception:
        pass
    return default


def run_inference(session, image_path: str, classes: list[str]) -> np.ndarray:
    """
    Run a forward pass and return a 1-D probability array (length = num_classes).
    """
    img = Image.open(image_path).convert("RGB")

    image_size = _model_image_size(session)
    tensor = get_transform(img, image_size)

    input_name = session.get_inputs()[0].name
    outputs = session.run(None, {input_name: tensor})

    logits = np.asarray(outputs[0]).squeeze()

    # Numerically-stable softmax
    logits = logits - np.max(logits)
    exp = np.exp(logits)
    probs = exp / np.sum(exp)

    # If the model head has a different number of outputs than our class list,
    # truncate or warn gracefully.
    if probs.shape[0] != len(classes):
        print(f"[WARN] Model outputs {probs.shape[0]} logits but class file has "
              f"{len(classes)} labels. Truncating to the smaller of the two.")
        n = min(probs.shape[0], len(classes))
        probs = probs[:n]
        classes[:] = classes[:n]

    return probs


def print_results(probs: np.ndarray, classes: list[str], verbose: bool) -> None:
    top_k = 5 if verbose else 1
    k = min(top_k, len(classes))
    top_indices = np.argsort(probs)[::-1][:k]
    top_probs = probs[top_indices]

    top1_label = classes[int(top_indices[0])]
    top1_prob  = float(top_probs[0]) * 100

    print()
    print("=" * 50)
    print(f"  Top-1 Prediction : {top1_label}")
    print(f"  Confidence       : {top1_prob:.2f}%")
    print("=" * 50)

    if verbose:
        print("\n  Top-5 Predictions:")
        print("  " + "-" * 40)
        for rank, (idx, prob) in enumerate(
            zip(top_indices.tolist(), top_probs.tolist()), start=1
        ):
            bar = "█" * int(prob * 30)
            print(f"  {rank}. {classes[idx]:<25} {prob*100:6.2f}%  {bar}")
        print()


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Classify an image using an ONNX model.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("image",   help="Path to a JPG or PNG image")
    parser.add_argument("model",   help="Path to an .onnx file OR a directory containing one")
    parser.add_argument("classes", help="Text file with one class label per line")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Show top-5 predictions with probabilities")
    args = parser.parse_args()

    # --- Validate inputs --------------------------------------------------- #
    image_path = Path(args.image)
    if not image_path.exists():
        sys.exit(f"[ERROR] Image not found: {image_path}")
    if image_path.suffix.lower() not in (".jpg", ".jpeg", ".png"):
        sys.exit("[ERROR] Image must be a .jpg/.jpeg or .png file.")

    classes_path = Path(args.classes)
    if not classes_path.exists():
        sys.exit(f"[ERROR] Classes file not found: {classes_path}")

    # --- Setup ------------------------------------------------------------- #
    classes = load_classes(str(classes_path))
    print(f"[INFO] Loaded {len(classes)} class labels.")

    session = load_model(args.model)

    # --- Inference --------------------------------------------------------- #
    print(f"[INFO] Running inference on '{image_path}' …")
    probs = run_inference(session, str(image_path), classes)

    print_results(probs, classes, args.verbose)


if __name__ == "__main__":
    main()
