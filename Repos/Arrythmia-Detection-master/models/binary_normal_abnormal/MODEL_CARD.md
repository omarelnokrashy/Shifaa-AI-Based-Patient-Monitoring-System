# Model Card: Binary Normal vs Abnormal

## Task

Classify 12-lead ECG records as:

```text
0 = Normal
1 = Abnormal
```

`Abnormal` includes `AF`, `IAVB`, `SB`, and `STach`.

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
| Accuracy | 96.10% |
| Macro F1 | 93.42% |
| Weighted F1 | 96.15% |
| Cohen Kappa | 86.85% |
| MCC | 86.92% |
| Macro AUROC OvR | 98.26% |

## Confusion Matrix

| | Pred Normal | Pred Abnormal |
|---|---:|---:|
| True Normal | 15830 | 501 |
| True Abnormal | 272 | 3202 |

## Intended Use

This model is the first stage of the cascade. It screens ECGs into normal and abnormal categories. If abnormal, pass the same ECG to the abnormal subtype classifier.
