"""Cross-Joint classifier definition used by the deployable runtime."""

from __future__ import annotations

from runtime.utils.paths import PROJECT_ROOT

import sys

VENDOR_PATH = PROJECT_ROOT / "vendor" / "joint-attention-seizure-detection"
if str(VENDOR_PATH) not in sys.path:
    sys.path.insert(0, str(VENDOR_PATH))

from seizure_classifier.models import JointTransformerClassifier as _VendorJointTransformerClassifier


class JointTransformerClassifier(_VendorJointTransformerClassifier):
    """Compatibility wrapper for the locally trained CJ checkpoints.

    The deployment worker historically constructed this class with
    ``d_model=768`` to mean "incoming ViViT token dimension". The vendor class
    names that parameter ``token_dim`` and uses a 256-dim internal transformer,
    which is what the saved checkpoint tensors expect.
    """

    def __init__(self, d_model: int = 768, n_joints: int = 14, dropout: float = 0.5, use_cls_token: bool = False):
        super().__init__(
            token_dim=d_model,
            d_model=256,
            nhead=8,
            num_layers=4,
            dropout=dropout,
            use_cls_token=use_cls_token,
        )
        self.n_joints = n_joints
