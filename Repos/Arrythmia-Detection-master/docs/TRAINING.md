# Training

Training scripts are in `scripts/`.

## Binary Model

```bash
python scripts/train_fixed_split_binary_all.py ^
  --epochs 80 ^
  --batch-size 64 ^
  --patience 10 ^
  --output-dir models/binary_normal_abnormal ^
  --device cuda ^
  --num-workers 0
```

The final binary run was continued from epoch 50 to epoch 80. The best validation checkpoint was epoch 78.

## Abnormal Subtype Model

```bash
python scripts/train_fixed_split_abnormal_all.py ^
  --epochs 50 ^
  --batch-size 64 ^
  --patience 10 ^
  --output-dir models/abnormal_subtype ^
  --device cuda ^
  --num-workers 0
```

The abnormal subtype run early-stopped at epoch 35. The best validation checkpoint was epoch 25.

## Optimization

Both models use:

```text
Optimizer: AdamW
Learning rate: 0.001
Weight decay: 0.0001
Scheduler: ReduceLROnPlateau
Scheduler mode: maximize validation macro F1
Scheduler factor: 0.5
Scheduler patience: 3
Minimum LR: 1e-6
Gradient clipping: max norm 1.0
Loss: weighted CrossEntropyLoss
Sampler: WeightedRandomSampler
```

## Class Balancing

Class imbalance is handled in two places:

1. `WeightedRandomSampler` balances training batches by sampling minority classes more often.
2. `CrossEntropyLoss(weight=...)` gives minority classes larger loss weights.

The class weight formula is:

```text
class_weight = total_train_samples / (num_classes * class_count)
```

## Saved Artifacts

Each model folder contains:

```text
checkpoints/best.pt
checkpoints/last.pt
logs/epoch_logs.csv
logs/epoch_logs.jsonl
results/test_metrics.json
results/test_confusion_matrix.csv
results/test_per_class.csv
results/test_predictions.csv
splits/split_indices.npz
splits/split_manifest.csv
splits/split_summary.json
splits/group_summary.json
```
