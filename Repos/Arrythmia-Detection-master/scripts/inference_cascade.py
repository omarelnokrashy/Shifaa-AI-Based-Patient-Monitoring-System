import argparse
import sys
from pathlib import Path

import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from model import build_model  # noqa: E402


BINARY_CLASSES = ["Normal", "Abnormal"]
ABNORMAL_CLASSES = ["AF", "IAVB", "SB", "STach"]


def load_checkpoint(model, path, device):
    checkpoint = torch.load(path, map_location=device)
    model.load_state_dict(checkpoint["model_state_dict"])
    model.eval()
    return model


def predict(model, signal, qrs7, class_names, device):
    with torch.no_grad():
        signal_t = torch.tensor(signal[None], dtype=torch.float32, device=device)
        qrs_t = torch.tensor(qrs7[None], dtype=torch.float32, device=device)
        logits, _ = model(signal_t, qrs_t)
        probs = torch.softmax(logits, dim=-1).cpu().numpy()[0]
    pred_idx = int(probs.argmax())
    return {
        "class_id": pred_idx,
        "class_name": class_names[pred_idx],
        "probabilities": {name: float(probs[i]) for i, name in enumerate(class_names)},
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="Path to preprocessed ECG .npy shaped (5000, 12).")
    parser.add_argument("--qrs7", default=None, help="Optional QRS feature .npy shaped (7,). Defaults to zeros.")
    parser.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    args = parser.parse_args()

    device = torch.device(args.device)
    signal = np.load(args.input).astype(np.float32)
    if signal.shape != (5000, 12):
        raise ValueError(f"Expected signal shape (5000, 12), got {signal.shape}")

    if args.qrs7:
        qrs7 = np.load(args.qrs7).astype(np.float32)
    else:
        qrs7 = np.zeros(7, dtype=np.float32)
    if qrs7.shape != (7,):
        raise ValueError(f"Expected qrs7 shape (7,), got {qrs7.shape}")

    binary_model = build_model(n_leads=12, n_classes=2, qrs_aux_dim=64, device=str(device))
    binary_model = load_checkpoint(
        binary_model,
        ROOT / "models" / "binary_normal_abnormal" / "checkpoints" / "best.pt",
        device,
    )
    binary_result = predict(binary_model, signal, qrs7, BINARY_CLASSES, device)

    output = {"binary": binary_result}
    if binary_result["class_name"] == "Abnormal":
        abnormal_model = build_model(n_leads=12, n_classes=4, qrs_aux_dim=64, device=str(device))
        abnormal_model = load_checkpoint(
            abnormal_model,
            ROOT / "models" / "abnormal_subtype" / "checkpoints" / "best.pt",
            device,
        )
        output["abnormal_subtype"] = predict(abnormal_model, signal, qrs7, ABNORMAL_CLASSES, device)

    print(output)


if __name__ == "__main__":
    main()
