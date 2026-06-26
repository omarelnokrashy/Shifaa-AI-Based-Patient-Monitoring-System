# Datasets

The final models were trained on labeled samples from:

- PTB-XL
- CINC2020
- CODE-15

MIT-BIH was not included in the final training because the available preprocessed MIT-BIH records did not have compatible record-level labels for the target classes.

## Target Labels

Five source labels were used during preprocessing:

```text
0 = NSR
1 = AF
2 = IAVB
3 = SB
4 = STach
```

The final binary model maps:

```text
Normal   = NSR
Abnormal = AF, IAVB, SB, STach
```

The abnormal subtype model removes `NSR` and classifies:

```text
AF, IAVB, SB, STach
```

## Split Strategy

Both final models use fixed train/validation/test splits.

Data leakage controls:

- PTB-XL samples duplicated inside CINC2020 are assigned the same group id.
- CODE-15 samples are grouped by `patient_id`.
- Groups are split atomically, so no group appears in more than one split.

## Preprocessing Metadata

The folder `data/preprocessing_metadata/` contains `classes.txt` and `metadata.csv` files for each source dataset. The raw and preprocessed signal arrays are intentionally not duplicated here because they are very large.
