# model_weights — Seizure Detection ONNX Models

This directory is the **service-local** location for seizure detection model files
when running scripts directly (e.g., `evaluate_segments.py`, `evaluate_runtime.py`,
or the C++ executable standalone).

## In the monorepo (default layout)

All model files are stored at the **repository root** under `models/seizure/`:

```
Medical-History-Chatbot/
└── models/
    └── seizure/
        ├── pose.onnx          ← OpenPose skeleton extractor
        ├── pose.onnx.data
        ├── pose.pth           ← PyTorch fallback for pose model
        ├── vsvig_protogcn.onnx
        ├── vsvig_protogcn.onnx.data
        ├── cj_final.onnx
        └── cj_final.onnx.data
```

The evaluation scripts (`evaluate_segments.py`, `evaluate_runtime.py`) and the
`configs/default.yaml` automatically resolve model paths from `../../models/seizure/`
when run from the `services/seizure_detection/` directory. **You do not need to copy
or symlink anything** when using the standard monorepo setup.

## Standalone / custom layout

If you run the C++ executable **directly** (without `--root`) or copy this service
out of the monorepo, place the model files directly in this directory:

```
services/seizure_detection/model_weights/
├── pose.onnx
├── pose.onnx.data
├── pose.pth
├── vsvig_protogcn.onnx
├── vsvig_protogcn.onnx.data
├── cj_final.onnx
└── cj_final.onnx.data
```

You can create a junction (Windows) instead of copying:
```powershell
# From the services/seizure_detection/ directory:
cmd /c mklink /J model_weights ..\..\models\seizure
```
