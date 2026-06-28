"""
Python ViViT IPC Server
-----------------------
Reads a video, extracts ViViT tokens and joint positions, and streams them
to a Windows Named Pipe for the C++ runtime to consume.
"""

import argparse
import os
import struct
import sys
import time

# Add DLL directories for Windows DLL resolution
if sys.platform == 'win32':
    for p in [r"C:\python\Lib\site-packages\torch\lib", r"C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.2\bin"]:
        if os.path.exists(p):
            try:
                os.add_dll_directory(p)
            except Exception:
                pass

# Prevent transformers from trying to load torchaudio, which fails due to dynamic link mismatch
import importlib.util
_orig_find_spec = importlib.util.find_spec
importlib.util.find_spec = lambda name, package=None: None if name == 'torchaudio' else _orig_find_spec(name, package)

from collections import deque
from pathlib import Path

import cv2
import numpy as np
import torch

os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.utils.pose import get_openpose_keypoints, load_pose_model, map_crop_kpts_to_frame
from runtime.utils.logger import get_logger
from runtime.utils.tubelet_builder import build_tubelets
from runtime.utils.paths import PROJECT_ROOT

logger = get_logger(__name__)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, help="Video source")
    parser.add_argument("--pipe-name", default=r"\\.\pipe\seizure_vivit_tokens", help="Named pipe path")
    parser.add_argument("--pose-weights", default="../../models/seizure/pose.pth")
    parser.add_argument("--vivit-name", default="google/vivit-b-16x2-kinetics400")
    parser.add_argument("--sample-fps", type=float, default=6.0)
    parser.add_argument("--slide-sec", type=float, default=5.0, help="Fixed seconds between CJ windows")
    args = parser.parse_args()

    # Connect to named pipe created by C++ runtime
    # Add a retry loop for up to 600 seconds to allow C++ to start up and compile TRT engine
    import time
    pipe = None
    for _ in range(600):
        try:
            pipe = open(args.pipe_name, "wb")
            break
        except FileNotFoundError:
            time.sleep(1)
            
    if pipe is None:
        print(f"Failed to connect to pipe after 600 seconds.")
        return 1
        
    print("Connected to pipe!")

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    pose_model = load_pose_model(args.pose_weights, device)

    # Load ViViT
    vendor_path = ROOT.parent.parent / "third_party" / "joint-attention-seizure-detection"
    if str(vendor_path) not in sys.path:
        sys.path.insert(0, str(vendor_path))
    print("VENDOR PATH:", vendor_path)
    print("SYS PATH:", sys.path)
    from seizure_classifier.models import VivitModel, vivit_joint_tokens_forward_chunked, compute_joint_padding_mask

    vivit = VivitModel.from_pretrained(
        args.vivit_name,
        local_files_only=True,
        use_safetensors=False,
    ).to(device).eval()

    cap = cv2.VideoCapture(args.source)
    if not cap.isOpened():
        logger.error(f"Could not open source {args.source}")
        return 1

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    vsvig_sample_step = max(1, int(round(fps / args.sample_fps)))
    frame_idx = 0
    seg_frames = []
    
    total_vivit_ms = 0.0
    count_vivit = 0
    
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        frame_idx += 1
        time_sec = frame_idx / fps

        if frame_idx % vsvig_sample_step == 0:
            crop_kpts = get_openpose_keypoints(pose_model, frame, device)
            kpts18 = map_crop_kpts_to_frame(crop_kpts, (0, 0, frame.shape[1], frame.shape[0])).astype(np.float32)
            seg_frames.append({
                "frame": frame.copy(),
                "skeleton": {"keypoints": kpts18},
                "t": time_sec
            })

        if len(seg_frames) >= 30:
            segment = seg_frames[:30]
            slide_sec = args.slide_sec
            slide_samples = max(1, int(round(max(slide_sec, 1.0 / max(args.sample_fps, 0.1)) * args.sample_fps)))
            seg_frames = seg_frames[slide_samples:]
            
            logger.info(f"Processing segment at {time_sec:.2f}s slide={slide_sec:.2f}s")
            t0_build = time.perf_counter()
            tubelets, pos = build_tubelets(segment, n_joints=14, patch_size=120, sample_fps=args.sample_fps)
            t1_build = time.perf_counter()
            token_build_ms = (t1_build - t0_build) * 1000.0
            
            with torch.no_grad(), torch.autocast(device_type=str(device), enabled=(str(device) == "cuda"), dtype=torch.float16):
                tubelets = tubelets.to(device)
                pos = pos.to(device)
                
                t0_vivit = time.time()
                tokens = vivit_joint_tokens_forward_chunked(
                    tubelets=tubelets,
                    vivit_model=vivit,
                    num_frames=32,
                    out_size=224,
                    pool="cls",
                    enforce_model_num_frames=True,
                    joint_chunk=14,
                    move_chunk_to_device=True,
                )
                t1_vivit = time.time()
                total_vivit_ms += (t1_vivit - t0_vivit) * 1000.0
                count_vivit += 1
                
            # tokens: (1, 14, 768), pos: (1, 14, 30, 3)
            tokens_np = tokens.cpu().numpy().astype(np.float32)
            pos_np = pos.cpu().numpy().astype(np.float32)

            # Serialize: 
            # 1. magic header "VIVT" (4 bytes)
            # 2. time_sec / token_build_ms / vivit_ms (3 doubles, 24 bytes)
            # 3. tokens (14*768 floats, 43008 bytes)
            # 4. pos (14*30*3 floats, 5040 bytes)
            vivit_ms = (t1_vivit - t0_vivit) * 1000.0
            payload = struct.pack("4s d d d", b"VIVT", time_sec, token_build_ms, vivit_ms)
            payload += tokens_np.tobytes()
            payload += pos_np.tobytes()
            
            try:
                pipe.write(payload)
                pipe.flush()
                logger.info(f"Wrote {len(payload)} bytes to pipe")
            except Exception as e:
                logger.error(f"Pipe write failed: {e}")
                break

    print("--- PROFILING PYTHON ---")
    print(f"ViViT mean: {(total_vivit_ms / count_vivit if count_vivit > 0 else 0.0):.2f} ms")
    sys.stdout.flush()

    pipe.close()
    return 0

if __name__ == "__main__":
    sys.exit(main())
