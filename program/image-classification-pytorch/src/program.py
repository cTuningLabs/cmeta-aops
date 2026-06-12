#!/usr/bin/env python3
"""
Image Classifier using PyTorch + Hugging Face Hub
Usage:
  python classify.py <image> <model> <classes_file> [-v]

Arguments:
  image          Path to a .jpg or .png image
  model          Hugging Face model ID  OR  local path to a model directory / .pt file
  classes_file   Path to a text file with one class label per line
  -v             (optional) Show top-5 predictions with probabilities

Examples:
  # From Hugging Face Hub (downloaded to current directory):
  python classify.py cat.jpg google/vit-base-patch16-224 imagenet_classes.txt -v

  # From a local model directory (e.g. previously downloaded):
  python classify.py cat.jpg ./my_models/vit-base imagenet_classes.txt -v

  # From a raw PyTorch checkpoint file:
  python classify.py cat.jpg ./my_models/resnet.pt imagenet_classes.txt -v
"""

import argparse
import sys
import os
from pathlib import Path

import torch
import torch.nn.functional as F
from PIL import Image
from torchvision import transforms
from huggingface_hub import snapshot_download


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


def get_transform(image_size: int = 224) -> transforms.Compose:
    """Standard ImageNet-style pre-processing."""
    return transforms.Compose([
        transforms.Resize(image_size + 32),          # slight over-size then crop
        transforms.CenterCrop(image_size),
        transforms.ToTensor(),
        transforms.Normalize(
            mean=[0.485, 0.456, 0.406],
            std=[0.229, 0.224, 0.225],
        ),
    ])


def load_model(model_id: str, local_dir: str = ".") -> torch.nn.Module:
    """
    Load a model from either:
      - a local directory or .pt/.pth file path, OR
      - a Hugging Face Hub model ID (downloaded into `local_dir`)
    """
    local_path = Path(model_id)

    # ---- Local path: directory with config/weights, or a raw checkpoint ---- #
    if local_path.exists():
        if local_path.is_file() and local_path.suffix.lower() in (".pt", ".pth", ".bin"):
            print(f"[INFO] Loading raw PyTorch checkpoint from local file: {local_path}")
            model = torch.load(str(local_path), map_location="cpu", weights_only=False)
            model.eval()
            return model, "torch"
        elif local_path.is_dir():
            print(f"[INFO] Loading model from local directory: {local_path}")
            model_dir = str(local_path)
        else:
            sys.exit(f"[ERROR] Local path exists but is not a directory or .pt/.pth/.bin file: {local_path}")
    # ---- Hugging Face Hub model ID ----------------------------------------- #
    else:
        print(f"[INFO] Fetching model '{model_id}' from Hugging Face Hub …")
        model_dir = snapshot_download(repo_id=model_id, local_dir=local_dir)
        print(f"[INFO] Model stored at: {model_dir}")

    # Try transformers AutoModelForImageClassification first (covers ViT, Swin,
    # ConvNeXt, EfficientNet via timm bridge, etc.)
    try:
        from transformers import AutoModelForImageClassification, AutoConfig
        config = AutoConfig.from_pretrained(model_dir)
        model = AutoModelForImageClassification.from_pretrained(
            model_dir, config=config, ignore_mismatched_sizes=True
        )
        model.eval()
        print("[INFO] Loaded via transformers AutoModelForImageClassification.")
        return model, "transformers"
    except Exception:
        pass

    # Fallback: plain torch checkpoint (.pt / .pth / .bin)
    for ext in ("*.pt", "*.pth", "*.bin"):
        hits = list(Path(model_dir).glob(ext))
        if hits:
            ckpt_path = hits[0]
            print(f"[INFO] Loading raw PyTorch checkpoint: {ckpt_path}")
            model = torch.load(ckpt_path, map_location="cpu")
            model.eval()
            return model, "torch"

    sys.exit("[ERROR] Could not load model. "
             "Ensure the repo contains a transformers config or a .pt/.pth/.bin file.")


def run_inference(model, model_type: str, image_path: str, classes: list[str],
                  device: torch.device) -> torch.Tensor:
    """
    Run a forward pass and return a 1-D probability tensor (length = num_classes).
    """
    img = Image.open(image_path).convert("RGB")

    if model_type == "transformers":
        # Try the fast AutoImageProcessor path first
        try:
            from transformers import AutoImageProcessor
            processor = AutoImageProcessor.from_pretrained(model.config._name_or_path
                                                           if hasattr(model, "config") else ".")
            inputs = processor(images=img, return_tensors="pt").to(device)
            with torch.no_grad():
                logits = model(**inputs).logits
        except Exception:
            # Fallback to manual torchvision transforms
            tensor = get_transform()(img).unsqueeze(0).to(device)
            with torch.no_grad():
                out = model(tensor)
                logits = out.logits if hasattr(out, "logits") else out
    else:
        tensor = get_transform()(img).unsqueeze(0).to(device)
        with torch.no_grad():
            logits = model(tensor)

    probs = F.softmax(logits.squeeze(), dim=-1)

    # If the model head has a different number of outputs than our class list,
    # truncate or warn gracefully.
    if probs.shape[0] != len(classes):
        print(f"[WARN] Model outputs {probs.shape[0]} logits but class file has "
              f"{len(classes)} labels. Truncating to the smaller of the two.")
        n = min(probs.shape[0], len(classes))
        probs = probs[:n]
        classes[:] = classes[:n]

    return probs


def print_results(probs: torch.Tensor, classes: list[str], verbose: bool) -> None:
    top_k = 5 if verbose else 1
    top_probs, top_indices = torch.topk(probs, k=min(top_k, len(classes)))

    top1_label = classes[top_indices[0].item()]
    top1_prob  = top_probs[0].item() * 100

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
        description="Classify an image using a Hugging Face model.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("image",   help="Path to a JPG or PNG image")
    parser.add_argument("model",   help="HF model ID (e.g. google/vit-base-patch16-224) OR local path to a model dir / .pt file")
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
    # Check top device from cMeta
    cmeta_targets = os.environ.get('CMETA_TARGETS').split(',')

    device = 'cpu'
    if 'xpu' in cmeta_targets:
        device = 'xpu'
    elif 'cuda' in cmeta_targets:
        device = 'cuda'
    elif 'rocm' in cmeta_targets:
        device = 'cuda'
    elif 'metal' in cmeta_targets:
        device = 'mps'
    elif 'xpu' in cmeta_targets:
        device = 'xpu'

    print(f"[INFO] Using device: {device}")

    classes = load_classes(str(classes_path))
    print(f"[INFO] Loaded {len(classes)} class labels.")

    model, model_type = load_model(args.model, local_dir=".")
    model.to(device)

    # --- Inference --------------------------------------------------------- #
    print(f"[INFO] Running inference on '{image_path}' …")
    probs = run_inference(model, model_type, str(image_path), classes, device)

    print_results(probs, classes, args.verbose)


if __name__ == "__main__":
    main()
