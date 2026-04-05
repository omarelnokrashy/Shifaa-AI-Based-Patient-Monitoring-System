# 01 — Project Overview

## 1.1 Title

**Patient Monitoring System: Seizure Detection Module** — A Video-Based, Spatiotemporal AI System for Real-Time Epileptic Seizure Detection

---

## 1.2 Abstract

This project presents an AI-driven, non-invasive patient monitoring system designed to detect the onset of epileptic seizures in clinical settings. The architecture relies on a **Video Swin-Vision Graph Network (VSViG)**. By extracting 2D skeleton keypoints combined with localized visual joint patches, the system processes live video feeds to track human movement and outputs continuous clinical risk probabilities, eliminating the need for cumbersome and restrictive EEG equipment.

---

## 1.3 Motivation

Continuous monitoring of high-risk epilepsy patients traditionally relies on Electroencephalograms (EEGs). However, EEGs are cumbersome, restrict patient movement, and cause discomfort, making long-term continuous monitoring challenging.

While video-based alternatives exist, many state-of-the-art approaches (such as those using dense Optical Flow or full-frame 3D convolutions) are too computationally heavy for real-world hospital edge devices. This project replaces invasive sensors with a highly efficient, privacy-preserving AI camera system that focuses strictly on skeletal movement and localized visual context, ensuring real-time performance on standard hospital hardware.

---

## 1.4 Objectives

| # | Objective |
|---|-----------|
| 1 | Provide a non-invasive, continuous video monitoring solution for epilepsy patients without wearable sensors |
| 2 | Extract robust human skeleton data dynamically from clinical video feeds |
| 3 | Utilize localized visual patch extraction to retain crucial context while bypassing heavy full-frame processing |
| 4 | Train the neural network using Huber Loss to prevent noisy pose estimations from crashing the learning process |
| 5 | Achieve real-time inference with low latency on standard edge/hospital hardware (RTX 5060) |
| 6 | Provide a live clinical dashboard with continuous risk scoring (0.0 to 1.0) and visual alerts |

---

## 1.5 Key Features

### 🦴 Lightweight Feature Extraction

- **Lightweight OpenPose:** Processes the video stream to extract 18 core skeletal joints per frame using a MobileNet backbone.
- **Visual Patching:** Rather than analyzing the entire RGB frame, the system extracts localized 32x32 RGB Gaussian patches strictly around the detected joints to capture muscle clenching and micro-expressions.

### 🧠 Core AI Pipeline (VSViG)

- **Spatiotemporal Graphing:** The Video Swin-Vision Graph Network maps the connections and velocity changes between the extracted joints over a continuous 30-frame temporal window.
- **Continuous Regression:** Outputs a continuous risk score (0% to 100%) mapping to the exponential progression of a clinical seizure, rather than a volatile binary classification.

### 🚨 Real-Time Clinical Alerting

- **Threshold-Based Alerts:** If the instantaneous regression score crosses the 0.50 (50%) threshold, the interface triggers a visual warning.
- **Live UI Overlay:** Uses OpenCV to draw a dynamic risk progress bar and project a red `"!! SEIZURE ALERT !!"` warning directly onto the patient feed for nursing staff.

### 🏥 Architectural Explorations

- **The MICCAI Baseline:** The team evaluated the GESTURES architecture (MICCAI), which used Two-Stream I3D networks and dense Optical Flow.
- **The Pivot:** The MICCAI approach was deemed unrealistic for live deployment due to massive computational overhead. The project successfully pivoted to the skeleton-anchored VSViG approach to ensure edge-device compatibility.

---

## 1.6 Technology Stack

| Layer | Technology | Version |
|-------|------------|---------|
| Hardware Environment | NVIDIA RTX 5060 GPU | — |
| AI Framework | PyTorch (JIT Enabled) | 2.6 |
| Compute Backend | CUDA | 12.4 |
| Pose Estimation | Lightweight OpenPose (MobileNet) | — |
| Neural Network | VSViG (Video Swin-Vision Graph) | — |
| Computer Vision & UI | OpenCV | 4.x |
| Data Processing | NumPy + Pandas | — |
| Training Metrics | Scikit-Learn | — |

---

## 1.7 Academic Contributions

1. **Edge-Optimized Spatiotemporal Tracking:** Demonstrating that skeleton-anchored visual patch extraction (VSViG) provides a highly viable, low-latency alternative to the computationally prohibitive dense optical flow methods (e.g., MICCAI GESTURES) for real-time medical anomaly detection.
2. **Optimized Loss Landscape for Clinical Video:** Implementing **Huber Loss (Smooth L1)** as the training objective to specifically handle the volatile and noisy nature of OpenPose estimations in hospital beds, allowing the model to smoothly converge while evaluating human-readable accuracy via RMSE (38.5%).
3. **Continuous Risk Trajectory:** Shifting seizure detection from a standard binary classification task to a continuous probability regression model, better reflecting the gradual clinical onset of neurological events.
