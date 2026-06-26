# Model Card: Abnormal Subtype Classifier

## Task

Classify abnormal 12-lead ECG records into:

```text
0 = AF
1 = IAVB
2 = SB
3 = STach
```

Normal ECG samples are not part of this model's training or evaluation.

## Datasets

- PTB-XL
- CINC2020
- CODE-15

## Checkpoints

- Best checkpoint: `checkpoints/best.pt`
- Last checkpoint: `checkpoints/last.pt`

The best checkpoint was selected by validation macro F1.

## Test Metrics

| Metric | Value |
|---|---:|
| Accuracy | 94.92% |
| Macro F1 | 94.71% |
| Weighted F1 | 94.94% |
| Cohen Kappa | 93.12% |
| MCC | 93.13% |
| Macro AUROC OvR | 99.43% |

## Per-Class F1

| Class | F1 |
|---|---:|
| AF | 95.13% |
| IAVB | 92.27% |
| SB | 94.96% |
| STach | 96.46% |

## Confusion Matrix

| | Pred AF | Pred IAVB | Pred SB | Pred STach |
|---|---:|---:|---:|---:|
| True AF | 1065 | 31 | 7 | 22 |
| True IAVB | 11 | 609 | 16 | 5 |
| True SB | 12 | 31 | 688 | 4 |
| True STach | 26 | 8 | 3 | 926 |

## Intended Use

This model is the second stage of the cascade. It should be used only after the binary model predicts abnormal ECG.
