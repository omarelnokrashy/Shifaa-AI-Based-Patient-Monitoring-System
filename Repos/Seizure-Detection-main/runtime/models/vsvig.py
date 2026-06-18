"""
VSViG.py
========
Core model file.  Contains:

    Original VSViG components (weight-compatible with published checkpoints):
        InterPartMR, IntraPartMR, Stem, Stem_pe, Grapher, Part_3DCNN, STViG

    ProtoGCN enhancement components (Liu et al., 2025, arXiv:2411.18941):
        MotionTopologyEnhancement   — §3.3, Eq.(5–7)
        PrototypeReconstructionNetwork — §3.2, Eq.(3–4)
        ClassSpecificContrastiveLoss   — §3.4, Eq.(8–9)

    Factory functions:
        VSViG_base()           — original model (use with published weights)
        VSViG_light()          — lightweight variant
        VSViG_ProtoGCN_base()  — VSViG + all three ProtoGCN modules

ProtoGCN hyperparameters (paper Fig. 3 optimal values):
    npro=100, λ=0.3, K=8, d=256, α=0.9, τ=0.125
"""

import math
import os
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from timm.models.registry import register_model


def _load_dynamic_point_order():
    deployment_root = Path(__file__).resolve().parents[2]
    project_root = deployment_root.parent
    candidates = [
        os.environ.get("DY_POINT_ORDER", ""),
        deployment_root / "model_weights" / "dy_point_order.pt",
        project_root / "weights" / "vsvig" / "dy_point_order.pt",
        Path("weights/vsvig/dy_point_order.pt"),
    ]
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate)
        if path.exists():
            return torch.load(str(path), weights_only=True)
    raise FileNotFoundError("Could not locate dy_point_order.pt for VSViG runtime inference.")


# ══════════════════════════════════════════════════════════════════════════════
# Original VSViG building blocks (unchanged — preserves weight compatibility)
# ══════════════════════════════════════════════════════════════════════════════

class InterPartMR(nn.Module):
    """Inter-partition max-relative graph convolution."""
    def __init__(self, out_channels):
        super().__init__()
        self.nn = nn.Sequential(
            nn.Conv2d(out_channels * 2, out_channels * 2, 1, groups=4),
            nn.BatchNorm2d(out_channels * 2),
            nn.ReLU())

    def forward(self, x):
        B, C, P, _ = x.shape
        tmp_x = x
        x_i   = x.repeat(1, 1, 1, P)
        x_j   = x_i.clone()
        for k in range(P):
            x_j[:, :, :, k] = x_i[:, :, k, k].unsqueeze(-1).repeat(1, 1, P)
        relative = x_j - x_i
        for part in range(5):
            tmp = relative.clone()
            tmp[:, :, :, part * 3:(part + 1) * 3] -= 1e4
            tmp_x_j, _ = torch.max(tmp, -1, keepdim=True)
            tmp_x[:, :, part * 3:(part + 1) * 3, :] = \
                tmp_x_j[:, :, part * 3:(part + 1) * 3, :]
        return self.nn(torch.cat([x, tmp_x], 1))


class IntraPartMR(nn.Module):
    """Intra-partition max-relative graph convolution."""
    def __init__(self, out_channels):
        super().__init__()
        self.nn = nn.Sequential(
            nn.Conv2d(out_channels * 2, out_channels * 2, 1, groups=4),
            nn.BatchNorm2d(out_channels * 2),
            nn.ReLU())

    def forward(self, x):
        B, C, P, _ = x.shape
        tmp_x = x.clone()
        x_i   = x.repeat(1, 1, 1, P)
        x_j   = x_i.clone()
        for k in range(P):
            x_j[:, :, :, k] = x_i[:, :, k, k].unsqueeze(-1).repeat(1, 1, P)
        relative = x_j - x_i
        part = 1
        for point in range(P):
            tmp_x_j, _ = torch.max(
                relative[:, :, point, (part - 1) * 3 + 1:part * 3 + 1],
                -1, keepdim=True)
            tmp_x[:, :, point, :] = tmp_x_j
            if (point + 1) % 3 == 0:
                part += 1
        return self.nn(torch.cat([x, tmp_x], 1))


class Stem(nn.Module):
    """Patch embedding: (B,T,P,C,H,W) → (B,T,P,C_out)."""
    def __init__(self, input_dim=3, output_dim=None, patch_size=32):
        super().__init__()
        self.stem = nn.Sequential(
            nn.Conv2d(input_dim, output_dim, kernel_size=patch_size,
                      stride=patch_size),
            nn.BatchNorm2d(output_dim))

    def forward(self, x):
        B, T, P, C, H, W = x.shape
        x = self.stem(x.view(-1, C, H, W))
        return x.view(B, T, P, x.shape[1])


class Stem_pe(nn.Module):
    """Positional embedding stem: maps (x,y,conf) to channel space."""
    def __init__(self, input_dim=3, output_dim=None, patch_size=32):
        super().__init__()
        self.stem = nn.Sequential(
            nn.Conv2d(input_dim, output_dim, kernel_size=1),
            nn.BatchNorm2d(output_dim))

    def forward(self, x):
        B, T, P, C = x.shape
        x = self.stem(x.view(-1, C, 1, 1))
        return x.view(B, T, P, x.shape[1])


class Grapher(nn.Module):
    """Spatial graph convolution block (inter + intra partition)."""
    def __init__(self, in_channels, out_channels):
        super().__init__()
        self.fc1 = nn.Sequential(
            nn.Conv2d(in_channels, out_channels, 1), nn.BatchNorm2d(out_channels))
        self.fc2 = nn.Sequential(
            nn.Conv2d(out_channels * 2, in_channels, 1), nn.BatchNorm2d(in_channels))
        self.fc3 = nn.Sequential(
            nn.Conv2d(in_channels, out_channels, 1), nn.BatchNorm2d(out_channels))
        self.fc4 = nn.Sequential(
            nn.Conv2d(out_channels * 2, in_channels, 1), nn.BatchNorm2d(in_channels))
        self.InterPartMR = InterPartMR(out_channels)
        self.IntraPartMR = IntraPartMR(out_channels)
        self.act         = nn.ReLU()
        self.dropout     = nn.Dropout(p=0.5)

    def forward(self, x):
        B, T, C, P, _ = x.shape
        x   = x.view(-1, C, P, 1)
        res = x
        x   = self.InterPartMR(self.fc1(x))
        x   = self.act(self.fc2(x) + res)
        x   = self.IntraPartMR(self.fc3(x))
        x   = self.act(self.fc4(x) + res)
        return x.view(B, T, C, P, 1)


class Part_3DCNN(nn.Module):
    """Temporal graph convolution block with dynamic partition shuffle."""
    def __init__(self, in_channels, out_channels, stride=1,
                 dynamic=False, dynamic_point_order=None,
                 SEED=None, expansion=4):
        super().__init__()
        self.expansion = expansion
        self.conv1 = nn.Sequential(
            nn.Conv3d(in_channels, out_channels, 1),
            nn.BatchNorm3d(out_channels), nn.ReLU())
        self.conv2 = nn.Sequential(
            nn.Conv3d(out_channels, out_channels, (3, 3, 1),
                      stride=stride, padding=1, padding_mode='replicate'),
            nn.BatchNorm3d(out_channels), nn.ReLU())
        self.conv3 = nn.Sequential(
            nn.Conv3d(out_channels, out_channels * expansion, 1),
            nn.BatchNorm3d(out_channels * expansion), nn.ReLU())
        self.downsample = nn.Sequential(
            nn.Conv3d(in_channels, out_channels * expansion, 1, stride=stride),
            nn.BatchNorm3d(out_channels * expansion))
        self.act    = nn.ReLU()
        self.dynamic = dynamic
        self.dynamic_point_order = dynamic_point_order
        self.SEED   = SEED

    def dynamic_trans(self, x):
        B, C, T, P, _ = x.shape
        x = x.view(-1, P)
        raw   = list(np.arange(15))
        order = self.dynamic_point_order[self.SEED]
        x[:, raw] = x[:, order]
        return x.view(B, C, T, P, 1)

    def forward(self, x):
        B, T, C, P, _ = x.shape
        x = x.transpose(1, 2).contiguous()
        if self.dynamic:
            x = self.dynamic_trans(x)
        res = x
        x   = self.conv1(x)
        x   = self.conv2(x)[:, :, :, :, 1].unsqueeze(-1)
        x   = self.conv3(x)
        x   = self.act(self.downsample(res) + x)
        return x.transpose(1, 2).contiguous()


# ══════════════════════════════════════════════════════════════════════════════
# ProtoGCN components
# ══════════════════════════════════════════════════════════════════════════════

class MotionTopologyEnhancement(nn.Module):
    """
    MTE module — ProtoGCN §3.3, Eq.(5–7).

    Computes two topology matrices from joint features and adds them to
    the backbone's universal topology A0:
        Aintra = ϕ(HQ · HK^T)            intra-sample joint correlation
        Ainter = ϕ(T1(HQ) − T2(HK))      inter-sample joint distinction
        A_enhanced = A0 + Aintra + Ainter

    Returns A_enh of shape (B*T, P, P) to be used downstream.
    """
    def __init__(self, in_channels: int, K: int = 8):
        super().__init__()
        self.K      = K
        C_prime     = max(1, in_channels // K)
        self.WQ     = nn.Linear(in_channels, C_prime * K, bias=False)
        self.WK     = nn.Linear(in_channels, C_prime * K, bias=False)
        self.act    = nn.ReLU()

    def forward(self, H: torch.Tensor) -> torch.Tensor:
        # H: (B, T, C, P, 1)
        B, T, C, P, _ = H.shape
        h  = H.squeeze(-1).permute(0, 1, 3, 2).contiguous().view(B * T, P, C)
        HQ = self.WQ(h)   # (BT, P, C')
        HK = self.WK(h)
        A_intra = self.act(torch.bmm(HQ, HK.transpose(1, 2)))          # (BT,P,P)
        HQ_exp  = HQ.unsqueeze(2).expand(-1, -1, P, -1)
        HK_exp  = HK.unsqueeze(1).expand(-1, P, -1, -1)
        A_inter = self.act((HQ_exp - HK_exp).mean(dim=-1))              # (BT,P,P)
        return A_intra + A_inter


class PrototypeReconstructionNetwork(nn.Module):
    """
    PRN module — ProtoGCN §3.2, Eq.(3–4).

    Memory module:  W_memory ∈ R^(npro × C)  — learnable prototype bank
    Addressing:     R = softmax(X · W_query^T)
    Reconstruction: Z = R · W_memory

    npro=100 is the ablation-optimal value (paper Fig. 3).
    """
    def __init__(self, feature_dim: int, npro: int = 100):
        super().__init__()
        self.W_memory = nn.Parameter(torch.empty(npro, feature_dim))
        self.W_query  = nn.Parameter(torch.empty(npro, feature_dim))
        nn.init.kaiming_uniform_(self.W_memory, a=math.sqrt(5))
        nn.init.kaiming_uniform_(self.W_query,  a=math.sqrt(5))

    def forward(self, X: torch.Tensor) -> torch.Tensor:
        # X: (B, N², C)  →  Z: (B, N², C)
        R = torch.softmax(X @ self.W_query.T, dim=-1)   # (B, N², npro)
        return R @ self.W_memory                         # (B, N², C)


class ClassSpecificContrastiveLoss(nn.Module):
    """
    CSCL module — ProtoGCN §3.4, Eq.(8–9), adapted for regression labels.

    VSViG uses continuous labels [0,1].  We binarise them for CSCL:
        label < 0.3  → interictal (class 0)
        label > 0.7  → ictal      (class 1)
        0.3–0.7      → transition (excluded — ambiguous class membership)

    Momentum memory bank tracks class centroids (α=0.9).
    Contrastive temperature τ=0.125.
    Combined loss weight λ=0.3 (set in train.py).
    """
    ICTAL_LO = 0.3
    ICTAL_HI = 0.7

    def __init__(self, feature_dim: int, d: int = 256,
                 alpha: float = 0.9, temperature: float = 0.125):
        super().__init__()
        self.alpha       = alpha
        self.temperature = temperature
        self.projector   = nn.Sequential(
            nn.Linear(feature_dim, d), nn.ReLU(), nn.Linear(d, d))
        self.register_buffer('memory_bank',
                             F.normalize(torch.randn(2, d), dim=-1))

    @torch.no_grad()
    def _update_memory(self, f: torch.Tensor, labels: torch.Tensor):
        for cls in range(2):
            mask = (labels < self.ICTAL_LO) if cls == 0 else (labels > self.ICTAL_HI)
            if mask.sum() == 0:
                continue
            fk = F.normalize(f[mask].mean(0), dim=-1)
            self.memory_bank[cls] = F.normalize(
                self.alpha * self.memory_bank[cls] + (1 - self.alpha) * fk, dim=-1)

    def forward(self, Z: torch.Tensor, labels: torch.Tensor) -> torch.Tensor:
        # Z: (B, N², C),  labels: (B,)
        f     = F.normalize(self.projector(Z.mean(1)), dim=-1)   # (B, d)
        inter = labels < self.ICTAL_LO
        ictal = labels > self.ICTAL_HI
        valid = inter | ictal
        if valid.sum() == 0:
            return torch.tensor(0.0, device=Z.device, requires_grad=True)
        self._update_memory(f.detach(), labels)
        logits  = (f[valid] @ self.memory_bank.T) / self.temperature
        cls_ids = ictal[valid].long()
        return F.cross_entropy(logits, cls_ids)


class MultiStreamPoseEmbedding(nn.Module):
    """
    Early fusion for joint, bone, and motion keypoint streams.

    The visual patch stream remains unchanged, so published VSViG weights still
    load with strict=False. The fused output keeps the original (x, y, conf)
    dimensionality expected by Stem_pe.
    """
    def __init__(self, channels: int = 3):
        super().__init__()
        # Parent index per 15-joint VSViG point after preprocessing reorder.
        self.register_buffer(
            "bone_parent",
            torch.tensor([0, 0, 1, 0, 3, 4, 5, 3, 7, 8, 3, 10, 11, 0, 13],
                         dtype=torch.long),
            persistent=False,
        )
        self.proj = nn.Linear(channels * 3, channels)
        self.norm = nn.Identity()
        self.reset_parameters()

    def reset_parameters(self) -> None:
        nn.init.zeros_(self.proj.weight)
        nn.init.zeros_(self.proj.bias)
        eye = torch.eye(3, dtype=self.proj.weight.dtype)
        self.proj.weight.data[:, :3] = eye

    def forward(self, kpts: torch.Tensor) -> torch.Tensor:
        # kpts: (B, T, P=15, C=3)
        if kpts is None:
            return None
        joint = kpts
        bone = joint - joint[:, :, self.bone_parent, :]
        motion = torch.zeros_like(joint)
        motion[:, 1:] = joint[:, 1:] - joint[:, :-1]
        return self.norm(self.proj(torch.cat([joint, bone, motion], dim=-1)))


# ══════════════════════════════════════════════════════════════════════════════
# STViG — main network (original + optional ProtoGCN path)
# ══════════════════════════════════════════════════════════════════════════════

class STViG(nn.Module):
    def __init__(self, opt):
        super().__init__()
        self.pos_emb   = opt.pos_emb
        self.use_proto = getattr(opt, 'use_proto', False)

        ch4stem = (output_channels := opt.output_channels)[0]
        if opt.pos_emb == 'add':
            ch4stem = output_channels[0] - 3

        self.stem    = Stem(input_dim=3, output_dim=ch4stem)
        self.stem_pe = Stem_pe(input_dim=3, output_dim=ch4stem)
        self.pose_fusion = MultiStreamPoseEmbedding(channels=3)

        in_ch    = output_channels[0]
        backbone = []
        for stage, n_layers in enumerate(opt.num_layer):
            if stage > 0:
                backbone += [
                    Grapher(in_ch, output_channels[stage]),
                    Part_3DCNN(stride=(2, 1, 1), in_channels=in_ch,
                               out_channels=output_channels[stage],
                               dynamic=opt.dynamic,
                               dynamic_point_order=opt.dynamic_point_order,
                               expansion=opt.expansion,
                               SEED=stage * n_layers + layers),
                ]
                in_ch = output_channels[stage] * opt.expansion
            for layers in range(n_layers):
                backbone += [
                    Grapher(in_ch, output_channels[stage]),
                    Part_3DCNN(in_channels=in_ch,
                               out_channels=output_channels[stage],
                               dynamic=opt.dynamic,
                               dynamic_point_order=opt.dynamic_point_order,
                               expansion=opt.expansion,
                               SEED=stage * n_layers + layers),
                ]
                if stage == 0:
                    in_ch = output_channels[stage] * opt.expansion

        self.backbone = nn.Sequential(*backbone)
        final_C       = output_channels[-1] * opt.expansion   # 384 for base

        # Standard head (always built for weight-file compatibility)
        self.fc = nn.Sequential(
            nn.Conv2d(final_C, 256, 1), nn.BatchNorm2d(256), nn.ReLU(),
            nn.Conv2d(256, 1, 1))

        # ProtoGCN additions
        if self.use_proto:
            npro       = getattr(opt, 'npro', 100)
            K          = getattr(opt, 'K',    8)
            d          = getattr(opt, 'd',    256)
            self.mte   = MotionTopologyEnhancement(final_C, K=K)
            self.prn   = PrototypeReconstructionNetwork(final_C, npro=npro)
            self.cscl  = ClassSpecificContrastiveLoss(final_C, d=d)
            self.fc_proto = nn.Sequential(
                nn.Linear(final_C * 2, 256), nn.ReLU(),
                nn.Dropout(0.3), nn.Linear(256, 1))

        self._init_weights()

    def _init_weights(self):
        for m in self.modules():
            if isinstance(m, (nn.Conv2d, nn.Conv3d)):
                nn.init.kaiming_normal_(m.weight)
                m.weight.requires_grad = True
                if m.bias is not None:
                    m.bias.data.zero_()
                    m.bias.requires_grad = True
            elif isinstance(m, (nn.BatchNorm2d, nn.BatchNorm3d)):
                nn.init.constant_(m.weight, 1.0)
                nn.init.constant_(m.bias,   0.0)

    def _pe(self, x, kpts):
        kpts = self.pose_fusion(kpts)
        if self.pos_emb == 'stem':
            return x + self.stem_pe(kpts)
        if self.pos_emb == 'add':
            return torch.cat((x, kpts), dim=-1)
        return x   # 'no' or 'learn'

    def _topology_matrix(self, feat: torch.Tensor) -> torch.Tensor:
        """Build X ∈ R^(B, N², C) from backbone output."""
        B, T, C, P, _ = feat.shape
        f = feat.squeeze(-1).mean(dim=1)               # (B, C, P)
        A = torch.einsum('bci,bcj->bcij', f, f)        # (B, C, P, P)
        return A.permute(0, 2, 3, 1).contiguous().view(B, P * P, C)

    def forward(self, inputs, kpts=None, labels=None):
        """
        inputs : (B, T=30, P=15, C=3, H=32, W=32)
        kpts   : (B, T=30, P=15, C=3)  — positional embedding
        labels : (B,) float — regression labels; needed only during
                              ProtoGCN training to compute CSCL loss

        Returns:
            probability (B,)                         — inference / plain VSViG
            (probability (B,), l_cscl scalar)        — ProtoGCN training
        """
        x = self._pe(self.stem(inputs), kpts)          # (B,T,P,C)
        B, T, P, C = x.shape
        x = x.transpose(2, 3).contiguous().view(B, T, C, P, 1)
        x = self.backbone(x)                           # (B,T',C',P,1)
        B, T, C, P, _ = x.shape

        # Global average pool → standard head
        gap = F.adaptive_avg_pool2d(
            x.transpose(1, 2).contiguous().view(B, C, T, P), 1)  # (B,C,1,1)

        if not self.use_proto:
            return torch.sigmoid(self.fc(gap).squeeze(-1).squeeze(-1).squeeze(-1))

        # ── ProtoGCN path ──────────────────────────────────────────────────
        X = self._topology_matrix(x)                   # (B, P², C)
        Z = self.prn(X)                                # (B, P², C)
        fused = torch.cat([gap.squeeze(-1).squeeze(-1),
                           Z.mean(dim=1)], dim=1)      # (B, 2C)
        prob  = torch.sigmoid(self.fc_proto(fused).squeeze(-1))

        if self.training and labels is not None:
            return prob, self.cscl(Z, labels)
        return prob


# ══════════════════════════════════════════════════════════════════════════════
# Factory functions
# ══════════════════════════════════════════════════════════════════════════════

class VSViGJointsOnly(nn.Module):
    """Ablation model: keypoints only, no RGB patches."""
    def __init__(self):
        super().__init__()
        self.mlp = nn.Sequential(
            nn.Linear(15 * 3, 256), nn.ReLU(),
            nn.Linear(256, 128), nn.ReLU(),
            nn.Linear(128, 1), nn.Sigmoid(),
        )

    def forward(self, inputs, kpts=None, labels=None):
        if kpts is None:
            raise ValueError("VSViGJointsOnly requires kpts input")
        x = kpts.reshape(kpts.shape[0], kpts.shape[1], -1)
        x = x.mean(dim=1)
        return self.mlp(x).squeeze(-1)


@register_model
def VSViG_joints_only(pretrained=False, **kwargs):
    return VSViGJointsOnly()


@register_model
def VSViG_base(pretrained=False, **kwargs):
    """Original VSViG-base.  Weight-compatible with published VSViG-base.pth."""
    class Opt:
        dynamic = 1
        num_layer = [2, 2, 6, 2]
        output_channels = [24, 48, 96, 192]
        dynamic_point_order = _load_dynamic_point_order()
        expansion = 2
        pos_emb   = 'stem'
        use_proto = False
    return STViG(Opt())


@register_model
def VSViG_light(pretrained=False, **kwargs):
    """Original VSViG-light."""
    class Opt:
        dynamic = 1
        num_layer = [2, 2, 6, 2]
        output_channels = [12, 24, 48, 96]
        dynamic_point_order = _load_dynamic_point_order()
        expansion = 2
        pos_emb   = 'stem'
        use_proto = False
    return STViG(Opt())


@register_model
def VSViG_ProtoGCN_base(pretrained=False, **kwargs):
    """
    VSViG-base + ProtoGCN (MTE + PRN + CSCL).

    Training usage:
        model = VSViG_ProtoGCN_base()
        prob, l_cscl = model(patches, kpts, labels=labels)
        loss = huber(prob, labels) + 0.3 * l_cscl   # λ=0.3

    Inference usage:
        prob = model(patches, kpts)   # no labels → no CSCL, returns prob only
    """
    class Opt:
        dynamic = 1
        num_layer = [2, 2, 6, 2]
        output_channels = [24, 48, 96, 192]
        dynamic_point_order = _load_dynamic_point_order()
        expansion = 2
        pos_emb   = 'stem'
        use_proto = True
        npro = 100   # memory capacity (paper Fig. 3 optimal)
        K    = 8     # MTE attention heads
        d    = 256   # contrastive projection dimension
    return STViG(Opt())
