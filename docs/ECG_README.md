# Arrhythmia Models

This repository-style folder contains the final ECG arrhythmia models, training code, evaluation outputs, split manifests, and preprocessing metadata.

The final system is a two-stage cascade:

1. **Binary screening model**
   - Task: `Normal` vs `Abnormal`
   - Classes: `Normal`, `Abnormal`
   - Datasets: PTB-XL, CINC2020, CODE-15
   - Checkpoint: `models/binary_normal_abnormal/checkpoints/best.pt`

2. **Abnormal subtype model**
   - Task: classify abnormal ECGs only
   - Classes: `AF`, `IAVB`, `SB`, `STach`
   - Datasets: PTB-XL, CINC2020, CODE-15
   - Checkpoint: `models/abnormal_subtype/checkpoints/best.pt`

## Final Test Results

### Binary Normal vs Abnormal

| Metric | Value |
|---|---:|
| Accuracy | 96.10% |
| Macro F1 | 93.42% |
| Weighted F1 | 96.15% |
| Cohen Kappa | 86.85% |
| MCC | 86.92% |
| Macro AUROC OvR | 98.26% |

Confusion matrix:

| | Pred Normal | Pred Abnormal |
|---|---:|---:|
| True Normal | 15830 | 501 |
| True Abnormal | 272 | 3202 |

### Abnormal Subtype Classifier

| Metric | Value |
|---|---:|
| Accuracy | 94.92% |
| Macro F1 | 94.71% |
| Weighted F1 | 94.94% |
| Cohen Kappa | 93.12% |
| MCC | 93.13% |
| Macro AUROC OvR | 99.43% |

Per-class F1:

| Class | F1 |
|---|---:|
| AF | 95.13% |
| IAVB | 92.27% |
| SB | 94.96% |
| STach | 96.46% |

## Repository Structure

```text
Final_Arrhythmia_Models/
  README.md
  requirements.txt
  .gitignore
  docs/
    DATASETS.md
    MODEL_ARCHITECTURE.md
    TRAINING.md
  src/
    model.py
    preprocessing.py
    evaluate.py
    xai.py
  scripts/
    inference_cascade.py
    train_fixed_split.py
    train_fixed_split_binary_all.py
    train_fixed_split_abnormal_all.py
  models/
    binary_normal_abnormal/
      checkpoints/
      logs/
      results/
      splits/
      MODEL_CARD.md
    abnormal_subtype/
      checkpoints/
      logs/
      results/
      splits/
      MODEL_CARD.md
  data/
    preprocessing_metadata/
      ptbxl/
      cinc2020/
      code15/
```

## Installation

```bash
pip install -r requirements.txt
```

The checkpoints were trained with CUDA using Anaconda Python and PyTorch.

## Inference

Use the cascade helper:

```bash
python scripts/inference_cascade.py --input path/to/ecg.npy
```

Expected input format:

```text
(5000, 12) float32 ECG after preprocessing
```

Or use `src/preprocessing.py` to preprocess raw 12-lead ECG arrays before inference.

## Reproducibility

Training used fixed train/validation/test splits, not cross-validation. Split manifests are included under each model's `splits/` folder.

Leakage controls:

- PTB-XL records duplicated inside CINC2020 were grouped by the same PTB-XL id.
- CODE-15 records were grouped by `patient_id`.
- Groups do not cross train/validation/test.

## Notes

Large preprocessed signal arrays are not included in this final folder. The folder includes metadata, splits, results, source code, and checkpoints needed to understand and reuse the final trained models.
