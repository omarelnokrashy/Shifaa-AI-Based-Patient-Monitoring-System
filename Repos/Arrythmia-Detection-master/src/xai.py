"""
Explainable AI (XAI) for ECG Classification
=============================================
Three complementary explanation methods:
    1. Grad-CAM  — gradient-weighted class activation map (CNN-based)
    2. SHAP      — Shapley additive explanations (feature/time-step importance)
    3. LIME      — local interpretable model-agnostic explanations

All methods produce per-time-step importance scores that can be plotted
directly on the ECG waveform.
"""

import numpy as np
import torch
import torch.nn.functional as F
from typing import Optional, List, Tuple
import warnings
warnings.filterwarnings("ignore")


# ---------------------------------------------------------------------------
# 1. Grad-CAM for 1-D CNN
# ---------------------------------------------------------------------------

class GradCAM1D:
    """
    Grad-CAM adapted for 1-D CNN layers.

    Registers forward + backward hooks on the target Conv1d layer to
    capture activations and gradients, then computes:

        L_c = ReLU( Σ_k  α_k^c · A^k )

    where α_k^c = GAP(∂y_c / ∂A^k)

    Usage:
        grad_cam = GradCAM1D(model, target_layer=model.cnn.cnn[-1].block[0])
        heatmap  = grad_cam.explain(signal_tensor, class_idx=2)
        # heatmap: 1-D array of shape (timesteps,)
    """

    def __init__(self, model: torch.nn.Module, target_layer: torch.nn.Module):
        self.model = model
        self.target_layer = target_layer
        self._activations: Optional[torch.Tensor] = None
        self._gradients:   Optional[torch.Tensor] = None
        self._hooks: List = []
        self._register_hooks()

    def _register_hooks(self):
        def fwd_hook(module, input, output):
            self._activations = output.detach()

        def bwd_hook(module, grad_in, grad_out):
            self._gradients = grad_out[0].detach()

        self._hooks.append(self.target_layer.register_forward_hook(fwd_hook))
        self._hooks.append(self.target_layer.register_full_backward_hook(bwd_hook))

    def remove_hooks(self):
        for h in self._hooks:
            h.remove()
        self._hooks.clear()

    def explain(
        self,
        signal: torch.Tensor,
        class_idx: Optional[int] = None,
        qrs_feats: Optional[torch.Tensor] = None,
    ) -> np.ndarray:
        """
        Compute Grad-CAM heatmap for a single ECG sample.

        Args:
            signal    : (1, timesteps, n_leads) — batch size MUST be 1
            class_idx : class to explain; if None, uses predicted class
            qrs_feats : (1, qrs_feat_dim) — optional

        Returns:
            heatmap   : 1-D numpy array interpolated to (timesteps,)
        """
        self.model.eval()
        signal = signal.requires_grad_(True)

        logits, _ = self.model(signal, qrs_feats)

        if class_idx is None:
            class_idx = int(logits.argmax(dim=-1).item())

        self.model.zero_grad()
        score = logits[0, class_idx]
        score.backward()

        # α_k = GAP over time dimension of gradients
        # activations / gradients shape: (1, channels, T')
        grads = self._gradients          # (1, C, T')
        acts  = self._activations        # (1, C, T')

        alpha = grads.mean(dim=-1, keepdim=True)   # (1, C, 1)
        cam   = (alpha * acts).sum(dim=1)          # (1, T')
        cam   = F.relu(cam).squeeze(0)             # (T',)
        cam   = cam.cpu().numpy()

        # Normalise to [0, 1]
        if cam.max() > 0:
            cam = cam / cam.max()

        # Interpolate back to original signal length
        original_len = signal.shape[1]
        heatmap = np.interp(
            np.linspace(0, len(cam) - 1, original_len),
            np.arange(len(cam)),
            cam,
        )
        return heatmap


# ---------------------------------------------------------------------------
# 2. SHAP — DeepSHAP / KernelSHAP for time-series
# ---------------------------------------------------------------------------

class ECGDeepSHAP:
    """
    Gradient × Input approximation of SHAP values for time-series.
    (Full DeepSHAP requires the `shap` library; this is a fast built-in
    alternative that gives comparable results for sequential models.)

    The SHAP value for each time step t is approximated as:
        φ_t ≈ (x_t - x̄_t) · ∂ŷ_c / ∂x_t

    This is also known as Integrated Gradients when baseline is zero.

    Usage:
        explainer = ECGDeepSHAP(model)
        shap_vals = explainer.explain(signal, class_idx=1, n_steps=50)
        # shap_vals: (timesteps, n_leads)
    """

    def __init__(self, model: torch.nn.Module,
                 baseline: Optional[torch.Tensor] = None):
        self.model = model
        self.baseline = baseline   # If None, zero baseline is used

    def explain(
        self,
        signal: torch.Tensor,
        class_idx: Optional[int] = None,
        qrs_feats: Optional[torch.Tensor] = None,
        n_steps: int = 50,
    ) -> np.ndarray:
        """
        Integrated Gradients approximation of SHAP values.

        Args:
            signal    : (1, timesteps, n_leads)
            class_idx : class to explain; None → predicted class
            qrs_feats : optional QRS features
            n_steps   : number of interpolation steps

        Returns:
            attributions : (timesteps, n_leads) — signed importance per time step
        """
        self.model.eval()

        baseline = (self.baseline if self.baseline is not None
                    else torch.zeros_like(signal))

        if class_idx is None:
            with torch.no_grad():
                logits, _ = self.model(signal, qrs_feats)
            class_idx = int(logits.argmax(dim=-1).item())

        # Accumulate gradients along interpolated path
        integrated_grads = torch.zeros_like(signal)

        for step in range(n_steps):
            alpha = step / (n_steps - 1)
            interp = baseline + alpha * (signal - baseline)
            interp = interp.detach().requires_grad_(True)

            logits, _ = self.model(interp, qrs_feats)
            score = logits[0, class_idx]
            score.backward()

            integrated_grads += interp.grad.detach()

        # Final attribution: (x - x̄) · avg_grad
        delta = signal - baseline
        attributions = delta * integrated_grads / n_steps  # (1, T, C)
        attributions = attributions.squeeze(0).cpu().numpy()  # (T, C)
        return attributions

    def feature_importance(self, attributions: np.ndarray) -> np.ndarray:
        """
        Aggregate per-time-step importance across all leads.
        Returns 1-D array of shape (timesteps,).
        """
        return np.abs(attributions).mean(axis=-1)


# ---------------------------------------------------------------------------
# 3. LIME — Local Interpretable Model-Agnostic Explanations
# ---------------------------------------------------------------------------

class ECGLIME:
    """
    LIME for 1-D ECG signals.

    Strategy:
      1. Divide the ECG into `n_segments` non-overlapping segments.
      2. Generate `n_samples` perturbed versions by randomly masking segments
         (replaced with baseline, typically zeros or segment mean).
      3. Score each perturbed sample through the model.
      4. Fit a weighted linear model on the binary mask → score mapping.
      5. The linear model coefficients give segment-level importance.

    Usage:
        lime = ECGLIME(model, n_segments=20, n_samples=200)
        importance = lime.explain(signal, class_idx=1)
        # importance: 1-D array of shape (timesteps,)
    """

    def __init__(
        self,
        model: torch.nn.Module,
        n_segments: int = 20,
        n_samples: int = 200,
        baseline_strategy: str = "zero",   # "zero" | "mean" | "noise"
        kernel_width: float = 0.25,
        device: str = "cpu",
    ):
        self.model = model
        self.n_segments = n_segments
        self.n_samples = n_samples
        self.baseline_strategy = baseline_strategy
        self.kernel_width = kernel_width
        self.device = device

    def _get_baseline(self, segment: np.ndarray) -> np.ndarray:
        if self.baseline_strategy == "zero":
            return np.zeros_like(segment)
        elif self.baseline_strategy == "mean":
            return np.full_like(segment, segment.mean())
        else:  # noise
            return np.random.normal(0, segment.std() * 0.1, segment.shape)

    def _kernel_weight(self, distance: float) -> float:
        """Exponential similarity kernel."""
        return np.exp(-(distance ** 2) / (self.kernel_width ** 2))

    def explain(
        self,
        signal: torch.Tensor,
        class_idx: Optional[int] = None,
        qrs_feats: Optional[torch.Tensor] = None,
    ) -> np.ndarray:
        """
        Explain a single ECG prediction with LIME.

        Args:
            signal    : (1, timesteps, n_leads)
            class_idx : class to explain; None → predicted class
            qrs_feats : optional QRS features

        Returns:
            importance : 1-D array of shape (timesteps,) normalised to [-1, 1]
        """
        self.model.eval()

        sig_np = signal.squeeze(0).cpu().numpy()   # (T, C)
        T, C   = sig_np.shape
        seg_len = T // self.n_segments

        # Segment boundaries
        boundaries = [(i * seg_len, min((i + 1) * seg_len, T))
                      for i in range(self.n_segments)]

        # Get predicted class
        if class_idx is None:
            with torch.no_grad():
                logits, _ = self.model(signal, qrs_feats)
            class_idx = int(logits.argmax(dim=-1).item())

        # Build perturbation dataset
        masks    = np.random.randint(0, 2, size=(self.n_samples, self.n_segments))
        scores   = np.zeros(self.n_samples)
        weights  = np.zeros(self.n_samples)

        for i, mask in enumerate(masks):
            perturbed = sig_np.copy()
            for j, (lo, hi) in enumerate(boundaries):
                if mask[j] == 0:   # segment is OFF
                    perturbed[lo:hi] = self._get_baseline(sig_np[lo:hi])

            # Score with model
            inp = torch.tensor(perturbed, dtype=torch.float32).unsqueeze(0).to(self.device)
            with torch.no_grad():
                logits, _ = self.model(inp, qrs_feats)
            prob = F.softmax(logits, dim=-1)[0, class_idx].item()
            scores[i] = prob

            # Distance from all-ON mask
            dist = float(np.sum(mask == 0)) / self.n_segments
            weights[i] = self._kernel_weight(dist)

        # Weighted least squares: mask → score
        W   = np.diag(weights)
        X   = masks.astype(np.float64)
        y   = scores.astype(np.float64)
        XtW = X.T @ W
        try:
            coef = np.linalg.solve(XtW @ X + 1e-6 * np.eye(self.n_segments), XtW @ y)
        except np.linalg.LinAlgError:
            coef = np.linalg.lstsq(XtW @ X, XtW @ y, rcond=None)[0]

        # Map segment coefficients back to time axis
        importance_time = np.zeros(T)
        for j, (lo, hi) in enumerate(boundaries):
            importance_time[lo:hi] = coef[j]

        # Normalise to [-1, 1]
        max_abs = np.abs(importance_time).max()
        if max_abs > 0:
            importance_time /= max_abs

        return importance_time


# ---------------------------------------------------------------------------
# Convenience wrapper — run all three XAI methods
# ---------------------------------------------------------------------------

class ECGExplainer:
    """
    Unified interface to run Grad-CAM, SHAP, and LIME on one ECG sample.

    Usage:
        explainer = ECGExplainer(model, target_conv_layer=model.cnn.cnn[-1].block[0])
        explanations = explainer.explain(signal, class_idx=2)
        # explanations["gradcam"]  → (T,)
        # explanations["shap"]     → (T, C)
        # explanations["lime"]     → (T,)
        # explanations["class_idx"]→ int
        # explanations["class_probs"] → (n_classes,)
    """

    def __init__(
        self,
        model: torch.nn.Module,
        target_conv_layer: torch.nn.Module,
        n_lime_segments: int = 20,
        n_lime_samples: int = 300,
        n_shap_steps: int = 50,
        device: str = "cpu",
    ):
        self.model  = model
        self.device = device
        self.grad_cam = GradCAM1D(model, target_conv_layer)
        self.shap     = ECGDeepSHAP(model)
        self.lime     = ECGLIME(model, n_lime_segments, n_lime_samples, device=device)

    def explain(
        self,
        signal: torch.Tensor,
        class_idx: Optional[int] = None,
        qrs_feats: Optional[torch.Tensor] = None,
    ) -> dict:
        """
        Run all three XAI methods.

        Args:
            signal    : (1, timesteps, n_leads)
            class_idx : target class; None → predicted class
            qrs_feats : optional QRS features

        Returns:
            dict with keys: gradcam, shap, lime, class_idx, class_probs
        """
        self.model.eval()

        # Predicted class and probabilities
        with torch.no_grad():
            logits, attn = self.model(signal, qrs_feats)
        probs = F.softmax(logits, dim=-1).squeeze(0).cpu().numpy()
        if class_idx is None:
            class_idx = int(np.argmax(probs))

        # Grad-CAM
        try:
            gc = self.grad_cam.explain(signal.clone(), class_idx, qrs_feats)
        except Exception as e:
            gc = np.zeros(signal.shape[1])
            print(f"[GradCAM] Warning: {e}")

        # SHAP (Integrated Gradients)
        try:
            shap_vals = self.shap.explain(signal.clone(), class_idx, qrs_feats)
        except Exception as e:
            shap_vals = np.zeros((signal.shape[1], signal.shape[2]))
            print(f"[SHAP] Warning: {e}")

        # LIME
        try:
            lime_vals = self.lime.explain(signal.clone(), class_idx, qrs_feats)
        except Exception as e:
            lime_vals = np.zeros(signal.shape[1])
            print(f"[LIME] Warning: {e}")

        return {
            "gradcam":     gc,
            "shap":        shap_vals,
            "lime":        lime_vals,
            "attn":        attn.squeeze(0).cpu().numpy(),
            "class_idx":   class_idx,
            "class_probs": probs,
        }
