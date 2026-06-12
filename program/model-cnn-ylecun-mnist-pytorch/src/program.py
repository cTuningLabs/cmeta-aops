import argparse
import json
import os
import sys
import time

# SHould not be moved after torch - fails
_import_start = time.time()
from datasets import load_dataset
import_time_datasets = time.time() - _import_start

_import_start = time.time()
import torch
import torch.nn as nn
import torch.nn.functional as F

from torch.utils.data import DataLoader
import_time_torch = time.time() - _import_start

_import_start = time.time()
from torchvision import transforms
import_time_torchvision = time.time() - _import_start


class SimpleMNISTCNN(nn.Module):
    def __init__(self):
        super().__init__()

        self.conv1 = nn.Conv2d(1, 16, 3)
        self.conv2 = nn.Conv2d(16, 32, 3)

        self.fc1 = nn.Linear(32 * 5 * 5, 128)
        self.fc2 = nn.Linear(128, 10)

    def forward(self, x):

        x = F.relu(self.conv1(x))
        x = F.max_pool2d(x, 2)

        x = F.relu(self.conv2(x))
        x = F.max_pool2d(x, 2)

        x = x.view(x.size(0), -1)

        x = F.relu(self.fc1(x))
        x = self.fc2(x)

        return x


def get_args():
    parser = argparse.ArgumentParser(
        description="Train, test or run a simple MNIST CNN"
    )

    parser.add_argument(
        "--mode",
        choices=["train", "test", "run"],
        default="train",
        help=(
            "train: train and save a model; "
            "test: load a saved model and evaluate on the test dataset; "
            "run: load a saved model and infer the class of a single --image"
        )
    )

    parser.add_argument(
        "--image",
        default=None,
        help="Path to a PNG/JPG image to classify (required for --mode run)"
    )

    parser.add_argument(
        "--train-dataset-path",
        default="./mnist/train-00000-of-00001.parquet",
        help="Path to train parquet file"
    )

    parser.add_argument(
        "--test-dataset-path",
        default="./mnist/test8-00000-of-00001.parquet",
        help="Path to test parquet file"
    )

    parser.add_argument(
        "--train-batch",
        type=int,
        default=64,
        help="Training batch size"
    )

    parser.add_argument(
        "--test-batch",
        type=int,
        default=256,
        help="Test batch size"
    )

    parser.add_argument(
        "--output-model",
        default="mnist_cnn.pt",
        help="Output model path"
    )

    parser.add_argument(
        "--epochs",
        type=int,
        default=3,
        help="Number of training epochs"
    )

    return parser.parse_args()


transform = transforms.Compose([
    transforms.ToTensor(),
    transforms.Normalize((0.1307,), (0.3081,))
])


def preprocess(batch):
    batch["image"] = [transform(image) for image in batch["image"]]
    return batch


def get_model_size_mb(model):
    num_bytes = sum(p.numel() * p.element_size() for p in model.parameters())
    return num_bytes / (1024 ** 2)


def reset_peak_memory(device):
    if device == 'cuda':
        torch.cuda.reset_peak_memory_stats()
    elif device == 'xpu':
        torch.xpu.reset_peak_memory_stats()


def get_peak_memory_cpu_mb():
    if sys.platform == 'win32':
        import ctypes
        from ctypes import wintypes

        class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        ctypes.windll.kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        ctypes.windll.psapi.GetProcessMemoryInfo.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(PROCESS_MEMORY_COUNTERS),
            wintypes.DWORD,
        ]
        ctypes.windll.psapi.GetProcessMemoryInfo.restype = wintypes.BOOL

        counters = PROCESS_MEMORY_COUNTERS()
        counters.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS)
        ok = ctypes.windll.psapi.GetProcessMemoryInfo(
            ctypes.windll.kernel32.GetCurrentProcess(),
            ctypes.byref(counters),
            counters.cb
        )
        if not ok:
            return None
        return counters.PeakWorkingSetSize / (1024 ** 2)
    else:
        import resource
        ru_maxrss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        if sys.platform == 'darwin':
            return ru_maxrss / (1024 ** 2)
        return ru_maxrss / 1024


def get_peak_memory_mb(device):
    if device == 'cpu':
        return get_peak_memory_cpu_mb()
    elif device == 'cuda':
        return torch.cuda.max_memory_allocated() / (1024 ** 2)
    elif device == 'xpu':
        return torch.xpu.max_memory_allocated() / (1024 ** 2)
    elif device == 'mps':
        return torch.mps.driver_allocated_memory() / (1024 ** 2)
    return None


def get_device():
    # Check top device from cMeta
    cmeta_targets = os.environ.get('CMETA_TARGETS', '').split(',')

    device = 'cpu'
    if 'xpu' in cmeta_targets:
        device = 'xpu'
    elif 'cuda' in cmeta_targets:
        device = 'cuda'
    elif 'rocm' in cmeta_targets:
        device = 'cuda'
    elif 'metal' in cmeta_targets:
        device = 'mps'

    return device


def build_loaders(args, include_train):
    """Load the parquet dataset and build the requested DataLoaders.

    Returns (train_loader, test_loader); train_loader is None when
    include_train is False (e.g. in test mode only the test split is needed).
    """
    data_files = {"test": args.test_dataset_path}
    if include_train:
        data_files["train"] = args.train_dataset_path

    dataset = load_dataset("parquet", data_files=data_files)

    test_ds = dataset["test"].with_transform(preprocess)
    test_loader = DataLoader(
        test_ds,
        batch_size=args.test_batch,
        shuffle=False
    )

    train_loader = None
    if include_train:
        train_ds = dataset["train"].with_transform(preprocess)
        train_loader = DataLoader(
            train_ds,
            batch_size=args.train_batch,
            shuffle=True
        )

    return train_loader, test_loader


def load_model(model_path, device):
    if not os.path.exists(model_path):
        sys.exit(f"ERROR: model file not found: {model_path}")

    model = SimpleMNISTCNN().to(device)
    model.load_state_dict(torch.load(model_path, map_location=device))
    model.eval()

    return model


def evaluate(model, loader, device, criterion):
    """Run the model over a loader and return (total_loss, accuracy)."""
    model.eval()

    total_loss = 0.0
    correct = 0
    total = 0

    with torch.no_grad():

        for batch in loader:

            images = batch["image"].to(device)
            labels = batch["label"].to(device)

            logits = model(images)

            loss = criterion(logits, labels)
            total_loss += loss.item()

            preds = logits.argmax(dim=1)

            correct += (preds == labels).sum().item()
            total += labels.size(0)

    accuracy = correct / total if total > 0 else 0.0

    return total_loss, accuracy


def save_stats(results):
    stats_path = "tmp-cmeta-program-stats.json"
    with open(stats_path, "w") as f:
        json.dump(results, f, indent=2)

    print('')
    print(f"Stats saved to: {stats_path}")


def base_results(args, device):
    return {
        "mode": args.mode,
        "import_time": {
            "datasets": import_time_datasets,
            "torch": import_time_torch,
            "torchvision": import_time_torchvision,
        },
        "configuration": {
            "train_dataset_path": args.train_dataset_path,
            "test_dataset_path": args.test_dataset_path,
            "train_batch": args.train_batch,
            "test_batch": args.test_batch,
            "output_model": args.output_model,
            "epochs": args.epochs,
        },
        "device": device,
    }


def train(args, device):

    print('')
    print("Configuration:")
    print(f"  train dataset : {args.train_dataset_path}")
    print(f"  test dataset  : {args.test_dataset_path}")
    print(f"  train batch   : {args.train_batch}")
    print(f"  test batch    : {args.test_batch}")
    print(f"  output model  : {args.output_model}")

    results = base_results(args, device)
    results["epochs"] = []

    train_loader, test_loader = build_loaders(args, include_train=True)

    model = SimpleMNISTCNN().to(device)

    model_size_mb = get_model_size_mb(model)

    print('')
    print(f"Model size: {model_size_mb:.2f} MB")

    results["model_size_mb"] = model_size_mb

    optimizer = torch.optim.Adam(
        model.parameters(),
        lr=1e-3
    )

    criterion = nn.CrossEntropyLoss()

    reset_peak_memory(device)

    print ('')
    for epoch in range(args.epochs):

        epoch_start = time.time()

        model.train()

        running_loss = 0.0

        for batch in train_loader:

            images = batch["image"].to(device)
            labels = batch["label"].to(device)

            optimizer.zero_grad()

            logits = model(images)

            loss = criterion(logits, labels)

            loss.backward()
            optimizer.step()

            running_loss += loss.item()

        _, accuracy = evaluate(model, test_loader, device, criterion)

        epoch_time = time.time() - epoch_start

        print(
            f"Epoch {epoch + 1}/{args.epochs} "
            f"loss={running_loss:.4f} "
            f"accuracy={accuracy:.4f} "
            f"time={epoch_time:.2f}s"
        )

        results["epochs"].append({
            "epoch": epoch + 1,
            "loss": running_loss,
            "accuracy": accuracy,
            "time_seconds": epoch_time,
        })

    torch.save(
        model.state_dict(),
        args.output_model
    )

    peak_memory_mb = get_peak_memory_mb(device)

    print('')
    if peak_memory_mb is not None:
        print(f"Peak training memory ({device}): {peak_memory_mb:.2f} MB")
    else:
        print(f"Peak training memory: not tracked on '{device}' device")

    results["peak_training_memory_mb"] = peak_memory_mb

    print ('')
    print(f"Model saved to: {args.output_model}")

    save_stats(results)


def test(args, device):

    print('')
    print("Configuration:")
    print(f"  test dataset  : {args.test_dataset_path}")
    print(f"  test batch    : {args.test_batch}")
    print(f"  input model   : {args.output_model}")

    results = base_results(args, device)

    _, test_loader = build_loaders(args, include_train=False)

    model = load_model(args.output_model, device)

    model_size_mb = get_model_size_mb(model)
    results["model_size_mb"] = model_size_mb

    criterion = nn.CrossEntropyLoss()

    eval_start = time.time()
    loss, accuracy = evaluate(model, test_loader, device, criterion)
    eval_time = time.time() - eval_start

    print('')
    print(
        f"Test loss={loss:.4f} "
        f"accuracy={accuracy:.4f} "
        f"time={eval_time:.2f}s"
    )

    results["test"] = {
        "loss": loss,
        "accuracy": accuracy,
        "time_seconds": eval_time,
    }

    save_stats(results)


def run(args, device):
    from PIL import Image

    if not args.image:
        sys.exit("ERROR: --image is required for --mode run")
    if not os.path.exists(args.image):
        sys.exit(f"ERROR: image file not found: {args.image}")

    print('')
    print("Configuration:")
    print(f"  input model   : {args.output_model}")
    print(f"  image         : {args.image}")

    results = base_results(args, device)

    model = load_model(args.output_model, device)

    # MNIST samples are 28x28 grayscale; coerce arbitrary PNG/JPG input to match.
    image = Image.open(args.image).convert("L").resize((28, 28))
    tensor = transform(image).unsqueeze(0).to(device)

    with torch.no_grad():
        logits = model(tensor)
        probs = F.softmax(logits, dim=1)

    predicted_class = int(logits.argmax(dim=1).item())
    confidence = float(probs[0, predicted_class].item())

    print('')
    print(f"Predicted class: {predicted_class}")
    print(f"Confidence     : {confidence:.4f}")

    results["inference"] = {
        "image": args.image,
        "predicted_class": predicted_class,
        "confidence": confidence,
        "probabilities": probs[0].tolist(),
    }

    save_stats(results)


def main():

    args = get_args()

    print("Import time:")
    print(f"  datasets   : {import_time_datasets:.2f}s")
    print(f"  torch      : {import_time_torch:.2f}s")
    print(f"  torchvision: {import_time_torchvision:.2f}s")

    device = get_device()

    print('')
    print(f"Mode: {args.mode}")
    print(f"Using device: {device}")

    if args.mode == "train":
        train(args, device)
    elif args.mode == "test":
        test(args, device)
    elif args.mode == "run":
        run(args, device)


if __name__ == "__main__":
    main()
