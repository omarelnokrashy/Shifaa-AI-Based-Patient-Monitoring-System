"""
ECG Hybrid Deep Learning Model
================================
Architecture:
                         ┌─────────────────────────────────────┐
    ECG Signal (T×C) ──► │  CNN → BiLSTM → Self-Attention       │──► main_ctx (256-d)
                         └─────────────────────────────────────┘         │
                                                                          ▼
    QRS 7-dim feats ───► │  QRS Auxiliary MLP Branch            │──► aux_ctx  (64-d)
    (Lead II)            └─────────────────────────────────────┘         │
                                                                          ▼
                                                               Gated Feature Fusion
                                                                          │
                                                                          ▼
                                                               Dense Head → Softmax

QRS Auxiliary Branch motivation:
    The 7 Pan-Tompkins rhythm statistics give the model hard-wired
    discriminating power over the two hardest classes:

    IAVB  → prolonged PR, normal RR regularity (low RR_CV, normal std_RR)
    AF    → irregular RR → high RR_CV (>> 0.10) and high std_RR

    Gated Fusion learns to up-weight the auxiliary signal when the
    waveform branch is uncertain, and to down-weight it when the CNN/BiLSTM
    context is already decisive.

Frameworks: PyTorch
"""

import torch
import torch.nn as nn
import torch.nn.functional as F
import numpy as np
from typing import Optional, Tuple


# ---------------------------------------------------------------------------
# Waveform branch sub-modules
# ---------------------------------------------------------------------------

class ConvBlock(nn.Module):
    """Conv1D → BatchNorm → ReLU → MaxPool → Dropout"""

    def __init__(self, in_channels: int, out_channels: int,
                 kernel_size: int = 5, pool_size: int = 2,
                 dropout: float = 0.2):
        super().__init__()
        self.block = nn.Sequential(
            nn.Conv1d(in_channels, out_channels, kernel_size,
                      padding=kernel_size // 2),
            nn.BatchNorm1d(out_channels),
            nn.ReLU(inplace=True),
            nn.MaxPool1d(pool_size),
            nn.Dropout(dropout),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.block(x)


class CNNEncoder(nn.Module):
    """
    Stacked 1-D CNN encoder.
    Input : (batch, n_leads, timesteps)
    Output: (batch, T', out_channels[-1])  — ready for BiLSTM
    """

    def __init__(self, in_channels: int = 1,
                 out_channels: tuple = (32, 64, 128),
                 kernel_sizes: tuple = (7, 5, 3),
                 pool_sizes: tuple = (2, 2, 2),
                 dropout: float = 0.2):
        super().__init__()
        layers, ch = [], in_channels
        for out_ch, ks, ps in zip(out_channels, kernel_sizes, pool_sizes):
            layers.append(ConvBlock(ch, out_ch, ks, ps, dropout))
            ch = out_ch
        self.cnn = nn.Sequential(*layers)
        self.out_channels = ch

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = self.cnn(x)          # (batch, C, T')
        return x.permute(0, 2, 1)  # (batch, T', C)


class BiLSTMEncoder(nn.Module):
    """
    Bidirectional LSTM.
    Input : (batch, T', input_size)
    Output: (batch, T', 2 * hidden_size)
    """

    def __init__(self, input_size: int, hidden_size: int = 128,
                 num_layers: int = 2, dropout: float = 0.3):
        super().__init__()
        self.bilstm = nn.LSTM(
            input_size=input_size,
            hidden_size=hidden_size,
            num_layers=num_layers,
            batch_first=True,
            bidirectional=True,
            dropout=dropout if num_layers > 1 else 0.0,
        )
        self.out_size = hidden_size * 2

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        out, _ = self.bilstm(x)
        return out


class SelfAttention(nn.Module):
    """
    Scaled dot-product self-attention.
    Returns:
        context      : (batch, d_model) — time-pooled representation
        attn_weights : (batch, T')      — per-step weights for XAI
    """

    def __init__(self, d_model: int):
        super().__init__()
        self.query = nn.Linear(d_model, d_model)
        self.key   = nn.Linear(d_model, d_model)
        self.value = nn.Linear(d_model, d_model)
        self.scale = d_model ** 0.5
        self.norm  = nn.LayerNorm(d_model)

    def forward(self, x: torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor]:
        Q, K, V = self.query(x), self.key(x), self.value(x)
        scores   = torch.bmm(Q, K.transpose(1, 2)) / self.scale  # (B, T, T)
        weights  = F.softmax(scores, dim=-1)
        context  = self.norm(torch.bmm(weights, V) + x)          # residual
        attn_w   = weights.mean(dim=1)                            # (B, T)
        return context.mean(dim=1), attn_w                        # (B, d), (B, T)


# ---------------------------------------------------------------------------
# QRS Auxiliary Branch
# ---------------------------------------------------------------------------

class QRSAuxBranch(nn.Module):
    """
    Three-layer MLP that encodes the 7-dim Pan-Tompkins feature vector
    into a dense representation that is later fused with the waveform context.

    Architecture:
        Input (7) → Linear(32) → BN → GELU → Dropout
                  → Linear(64) → BN → GELU → Dropout
                  → Linear(aux_out_dim)                  [no activation — goes to fusion]

    Design choices:
        - GELU activation: smoother than ReLU, works better on small feature spaces
        - BatchNorm after each linear: stabilises training despite the tiny
          input dimensionality and large variation in raw feature scales
          (mean_RR ≈ 0.8 s   vs   mean_HR_bpm ≈ 75 — orders of magnitude apart)
        - No final activation: the fusion gate handles non-linearity

    Args:
        in_dim      : input feature dimensionality (default 7)
        hidden_dim  : width of intermediate layers (default 64)
        aux_out_dim : output embedding size, should match or be a fraction
                      of the main branch context size (default 64)
        dropout     : regularisation dropout rate
    """

    def __init__(self, in_dim: int = 7, hidden_dim: int = 64,
                 aux_out_dim: int = 64, dropout: float = 0.3):
        super().__init__()
        self.mlp = nn.Sequential(
            # Layer 1: expand from raw 7-d
            nn.Linear(in_dim, hidden_dim // 2),
            nn.BatchNorm1d(hidden_dim // 2),
            nn.GELU(),
            nn.Dropout(dropout),

            # Layer 2: full hidden width
            nn.Linear(hidden_dim // 2, hidden_dim),
            nn.BatchNorm1d(hidden_dim),
            nn.GELU(),
            nn.Dropout(dropout),

            # Layer 3: project to aux embedding
            nn.Linear(hidden_dim, aux_out_dim),
        )
        self.out_dim = aux_out_dim

    def forward(self, qrs7: torch.Tensor) -> torch.Tensor:
        """
        Args:
            qrs7 : (batch, 7) — mean_RR, std_RR, mean_QRS_amp, std_QRS_amp,
                                mean_HR_bpm, RR_CV, beats_per_sec
        Returns:
            (batch, aux_out_dim)
        """
        return self.mlp(qrs7)


# ---------------------------------------------------------------------------
# Gated Feature Fusion
# ---------------------------------------------------------------------------

class GatedFusion(nn.Module):
    """
    Learns a soft gate that blends the waveform context and the QRS auxiliary
    embedding, allowing the network to up-weight the auxiliary signal when
    the waveform branch is uncertain (e.g. subtle IAVB or noisy AF trace).

    Mechanism:
        combined = concat(main_ctx, aux_ctx)              (B, main+aux)
        gate     = sigmoid( W_g · combined + b_g )       (B, main+aux)
        fused    = gate  ⊙  combined                     (B, main+aux)
        out      = LayerNorm( fused )                     (B, main+aux)

    The gating is element-wise: each dimension of the combined vector has its
    own learned "confidence" weight.  During early training the gate starts
    near 0.5 (sigmoid of near-zero weights), providing a gradient path to
    both branches simultaneously.

    Args:
        main_dim : dimensionality of the waveform attention context
        aux_dim  : dimensionality of the QRS auxiliary embedding
    """

    def __init__(self, main_dim: int, aux_dim: int):
        super().__init__()
        combined_dim   = main_dim + aux_dim
        self.gate      = nn.Linear(combined_dim, combined_dim)
        self.norm      = nn.LayerNorm(combined_dim)
        self.out_dim   = combined_dim

    def forward(self, main_ctx: torch.Tensor,
                aux_ctx: torch.Tensor) -> torch.Tensor:
        """
        Args:
            main_ctx : (batch, main_dim) — from Self-Attention pooling
            aux_ctx  : (batch, aux_dim)  — from QRS MLP branch

        Returns:
            fused : (batch, main_dim + aux_dim)
        """
        combined = torch.cat([main_ctx, aux_ctx], dim=-1)  # (B, main+aux)
        gate     = torch.sigmoid(self.gate(combined))       # (B, main+aux) ∈ (0,1)
        fused    = self.norm(gate * combined)               # gated + normalised
        return fused


# ---------------------------------------------------------------------------
# Full Model
# ---------------------------------------------------------------------------

class ECGClassifier(nn.Module):
    """
    Dual-branch ECG classifier:

        Branch A (waveform)  : CNN → BiLSTM → Self-Attention  → main_ctx
        Branch B (auxiliary) : QRS 7-dim MLP                  → aux_ctx
        Fusion               : Gated Feature Fusion           → fused
        Head                 : Dense → Dropout → Softmax

    Args:
        n_leads        : ECG input channels (leads)
        n_classes      : number of arrhythmia classes
        cnn_channels   : progressive channel widths for CNN blocks
        cnn_kernels    : kernel sizes for each CNN block
        bilstm_hidden  : hidden size per direction in BiLSTM
        bilstm_layers  : BiLSTM depth
        fc_units       : dense head hidden width
        dropout        : shared dropout probability
        qrs_aux_dim    : QRS auxiliary branch output size (set 0 to disable)

    Forward inputs:
        signal   : (batch, timesteps, n_leads)   — preprocessed ECG
        qrs7     : (batch, 7) or None            — Pan-Tompkins feature vector

    Forward outputs:
        logits       : (batch, n_classes)
        attn_weights : (batch, T')               — for XAI / Grad-CAM
    """

    QRS_AUX_IN = 7   # fixed Pan-Tompkins feature vector length

    def __init__(
        self,
        n_leads: int = 12,
        n_classes: int = 5,
        cnn_channels: tuple = (32, 64, 128),
        cnn_kernels: tuple = (7, 5, 3),
        bilstm_hidden: int = 128,
        bilstm_layers: int = 2,
        fc_units: int = 256,
        dropout: float = 0.3,
        qrs_aux_dim: int = 64,    # 0 = disabled; 64 = default auxiliary output size
    ):
        super().__init__()
        self.use_aux = qrs_aux_dim > 0

        # ── Branch A: Waveform ────────────────────────────────────────────
        self.cnn = CNNEncoder(
            in_channels=n_leads,
            out_channels=cnn_channels,
            kernel_sizes=cnn_kernels,
            dropout=dropout,
        )
        self.bilstm = BiLSTMEncoder(
            input_size=self.cnn.out_channels,
            hidden_size=bilstm_hidden,
            num_layers=bilstm_layers,
            dropout=dropout,
        )
        self.attention = SelfAttention(d_model=self.bilstm.out_size)
        main_dim = self.bilstm.out_size   # 256 with defaults

        # ── Branch B: QRS Auxiliary MLP ──────────────────────────────────
        if self.use_aux:
            self.qrs_aux = QRSAuxBranch(
                in_dim=self.QRS_AUX_IN,
                hidden_dim=64,
                aux_out_dim=qrs_aux_dim,
                dropout=dropout,
            )
            self.fusion = GatedFusion(main_dim=main_dim, aux_dim=qrs_aux_dim)
            head_in = self.fusion.out_dim
        else:
            head_in = main_dim

        # ── Classification head ───────────────────────────────────────────
        self.classifier = nn.Sequential(
            nn.Linear(head_in, fc_units),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(fc_units, fc_units // 2),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(fc_units // 2, n_classes),
        )

        self._init_weights()

    # ------------------------------------------------------------------

    def _init_weights(self):
        for m in self.modules():
            if isinstance(m, nn.Conv1d):
                nn.init.kaiming_normal_(m.weight, mode="fan_out", nonlinearity="relu")
                if m.bias is not None:
                    nn.init.zeros_(m.bias)
            elif isinstance(m, nn.Linear):
                nn.init.xavier_uniform_(m.weight)
                nn.init.zeros_(m.bias)

    # ------------------------------------------------------------------

    def forward(
        self,
        signal: torch.Tensor,
        qrs7: Optional[torch.Tensor] = None,
    ) -> Tuple[torch.Tensor, torch.Tensor]:
        """
        Args:
            signal : (batch, timesteps, n_leads)
            qrs7   : (batch, 7) — Pan-Tompkins feature vector, or None

        Returns:
            logits       : (batch, n_classes)
            attn_weights : (batch, T')
        """
        # ── Branch A ─────────────────────────────────────────────────────
        x = self.cnn(signal.permute(0, 2, 1))      # (B, T', cnn_ch)
        x = self.bilstm(x)                          # (B, T', 2*hidden)
        main_ctx, attn = self.attention(x)           # (B, main_dim), (B, T')

        # ── Branch B + Fusion ────────────────────────────────────────────
        if self.use_aux and qrs7 is not None:
            aux_ctx = self.qrs_aux(qrs7)             # (B, aux_dim)
            fused   = self.fusion(main_ctx, aux_ctx) # (B, main+aux)
        else:
            fused = main_ctx

        # ── Head ─────────────────────────────────────────────────────────
        logits = self.classifier(fused)              # (B, n_classes)
        return logits, attn

    # ------------------------------------------------------------------

    def predict_proba(self, signal: torch.Tensor,
                      qrs7: Optional[torch.Tensor] = None) -> np.ndarray:
        """Softmax probabilities → numpy (batch, n_classes)."""
        self.eval()
        with torch.no_grad():
            logits, _ = self.forward(signal, qrs7)
        return F.softmax(logits, dim=-1).cpu().numpy()

    def predict(self, signal: torch.Tensor,
                qrs7: Optional[torch.Tensor] = None) -> np.ndarray:
        """Argmax class index → numpy (batch,)."""
        return np.argmax(self.predict_proba(signal, qrs7), axis=-1)

    def gate_weights(self, signal: torch.Tensor,
                     qrs7: torch.Tensor) -> np.ndarray:
        """
        Expose the gating coefficients for a batch — useful for inspecting
        how much weight the model places on each branch dimension.

        Returns:
            gate : (batch, main_dim + aux_dim) values in (0, 1)
        """
        if not self.use_aux:
            raise RuntimeError("Auxiliary branch is disabled (qrs_aux_dim=0).")
        self.eval()
        with torch.no_grad():
            x = self.cnn(signal.permute(0, 2, 1))
            x = self.bilstm(x)
            main_ctx, _ = self.attention(x)
            aux_ctx  = self.qrs_aux(qrs7)
            combined = torch.cat([main_ctx, aux_ctx], dim=-1)
            gate     = torch.sigmoid(self.fusion.gate(combined))
        return gate.cpu().numpy()


# ---------------------------------------------------------------------------
# Training utilities
# ---------------------------------------------------------------------------

class FocalLoss(nn.Module):
    """
    Focal Loss — down-weights easy examples, useful for imbalanced ECG sets.
    L_focal = −α_t (1 − p_t)^γ  log(p_t)
    """

    def __init__(self, gamma: float = 2.0, alpha: Optional[torch.Tensor] = None,
                 reduction: str = "mean"):
        super().__init__()
        self.gamma = gamma
        self.alpha = alpha
        self.reduction = reduction

    def forward(self, inputs: torch.Tensor, targets: torch.Tensor) -> torch.Tensor:
        ce    = F.cross_entropy(inputs, targets, weight=self.alpha, reduction="none")
        focal = (1 - torch.exp(-ce)) ** self.gamma * ce
        return focal.mean() if self.reduction == "mean" else focal.sum()


def build_model(
    n_leads: int = 12,
    n_classes: int = 5,
    qrs_aux_dim: int = 64,
    device: str = "cpu",
) -> ECGClassifier:
    """
    Factory — builds the dual-branch model and moves it to `device`.

    Args:
        n_leads     : number of ECG leads
        n_classes   : arrhythmia classes
        qrs_aux_dim : auxiliary branch output width (0 = disable)
        device      : "cpu" | "cuda"
    """
    model = ECGClassifier(
        n_leads=n_leads,
        n_classes=n_classes,
        cnn_channels=(32, 64, 128),
        cnn_kernels=(7, 5, 3),
        bilstm_hidden=128,
        bilstm_layers=2,
        fc_units=256,
        dropout=0.3,
        qrs_aux_dim=qrs_aux_dim,
    ).to(device)
    return model


def count_parameters(model: nn.Module) -> int:
    """Total number of trainable parameters."""
    return sum(p.numel() for p in model.parameters() if p.requires_grad)