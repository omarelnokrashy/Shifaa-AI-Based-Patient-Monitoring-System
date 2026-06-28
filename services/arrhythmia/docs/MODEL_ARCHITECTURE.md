# Model Architecture

The model is a dual-branch ECG classifier implemented in `src/model.py`.

## Inputs

```text
signal: (batch, 5000, 12)
qrs7:   (batch, 7)
```

The signal is a 10-second, 12-lead ECG standardized to 500 Hz.

The QRS auxiliary vector contains:

```text
mean_RR
std_RR
mean_QRS_amp
std_QRS_amp
mean_HR_bpm
RR_CV
beats_per_sec
```

## Waveform Branch

```text
Conv1D block 1: 12 -> 32 channels, kernel 7
Conv1D block 2: 32 -> 64 channels, kernel 5
Conv1D block 3: 64 -> 128 channels, kernel 3
BiLSTM: hidden size 128, 2 layers, bidirectional
Self-attention pooling
```

Each convolutional block uses:

```text
Conv1d
BatchNorm1d
ReLU
MaxPool1d
Dropout
```

## QRS Auxiliary Branch

```text
Linear 7 -> 32
BatchNorm
GELU
Dropout
Linear 32 -> 64
BatchNorm
GELU
Dropout
Linear 64 -> 64
```

## Fusion and Classifier

The waveform context and QRS context are combined through gated fusion. The classifier head is:

```text
Linear fused_dim -> 256
GELU
Dropout
Linear 256 -> 128
GELU
Dropout
Linear 128 -> n_classes
```

Final parameter counts:

- Binary model: 1,120,930 trainable parameters
- Abnormal subtype model: 1,121,188 trainable parameters
