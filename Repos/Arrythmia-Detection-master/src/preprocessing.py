"""
ECG Preprocessing Pipeline
===========================
Handles: filtering, normalization, segmentation, padding/truncation,
         QRS detection (Pan-Tompkins variant), and ECG-to-image conversion.

QRS Auxiliary Features (7-dim, Lead II):
    Extracted by extract_qrs7_features() for the auxiliary MLP branch.
    These rhythm-level statistics give the model explicit discriminating
    power over IAVB (prolonged PR → altered beat geometry) and AF (chaotic
    RR → high RR_CV and std_RR).

    Feature index map:
        0  mean_RR        Mean RR interval (seconds)
        1  std_RR         Standard deviation of RR (HRV proxy)
        2  mean_QRS_amp   Mean R-peak amplitude
        3  std_QRS_amp    Std of R-peak amplitudes (beat consistency)
        4  mean_HR_bpm    Heart rate in BPM  (= 60 / mean_RR)
        5  RR_CV          Coefficient of variation  std_RR / mean_RR
                          → near-zero for regular rhythms, high for AF
        6  beats_per_sec  Total beats / recording duration
"""

import numpy as np
from scipy.signal import butter, filtfilt, iirnotch, find_peaks
from scipy.ndimage import uniform_filter1d
import warnings
warnings.filterwarnings("ignore")

# Canonical feature names for logging / XAI display
QRS7_FEATURE_NAMES = [
    "mean_RR",
    "std_RR",
    "mean_QRS_amp",
    "std_QRS_amp",
    "mean_HR_bpm",
    "RR_CV",
    "beats_per_sec",
]


# ---------------------------------------------------------------------------
# 1. Filtering
# ---------------------------------------------------------------------------

def bandpass_filter(signal: np.ndarray, lowcut: float = 0.5, highcut: float = 40.0,
                    fs: float = 360.0, order: int = 4) -> np.ndarray:
    """
    Bandpass Butterworth filter.
    Removes baseline wander (< 0.5 Hz) and high-frequency noise (> 40 Hz).

    Args:
        signal : 1-D ECG array
        lowcut : lower cutoff frequency (Hz)
        highcut: upper cutoff frequency (Hz)
        fs     : sampling frequency (Hz)
        order  : filter order

    Returns:
        Filtered signal (same shape as input)
    """
    nyquist = 0.5 * fs
    low = lowcut / nyquist
    high = highcut / nyquist
    b, a = butter(order, [low, high], btype="band")
    return filtfilt(b, a, signal)


def notch_filter(signal: np.ndarray, freq: float = 50.0,
                 fs: float = 360.0, quality: float = 30.0) -> np.ndarray:
    """
    IIR notch filter to remove powerline interference (50 Hz or 60 Hz).

    Args:
        signal : 1-D ECG array
        freq   : powerline frequency to remove (Hz)
        fs     : sampling frequency (Hz)
        quality: quality factor (higher = narrower notch)

    Returns:
        Filtered signal
    """
    w0 = freq / (fs / 2)
    b, a = iirnotch(w0, quality)
    return filtfilt(b, a, signal)


def full_filter_pipeline(signal: np.ndarray, fs: float = 360.0,
                         powerline_freq: float = 50.0) -> np.ndarray:
    """
    Complete filtering pipeline:
      1. Bandpass  0.5–40 Hz  (baseline wander + HF noise)
      2. Notch     50/60 Hz   (powerline interference)

    Args:
        signal        : raw 1-D ECG
        fs            : sampling frequency (Hz)
        powerline_freq: 50 (Europe) or 60 (US/Americas) Hz

    Returns:
        Clean filtered signal
    """
    signal = bandpass_filter(signal, lowcut=0.5, highcut=40.0, fs=fs)
    signal = notch_filter(signal, freq=powerline_freq, fs=fs)
    return signal


# ---------------------------------------------------------------------------
# 2. Normalization
# ---------------------------------------------------------------------------

def z_score_normalize(signal: np.ndarray) -> np.ndarray:
    """
    Z-score normalization: x' = (x - μ) / σ
    Preferred for ECG — robust, stabilizes gradients.
    Returns zero array if std is 0.
    """
    mu = np.mean(signal)
    sigma = np.std(signal)
    if sigma == 0:
        return np.zeros_like(signal)
    return (signal - mu) / sigma


def minmax_normalize(signal: np.ndarray, feature_range: tuple = (-1, 1)) -> np.ndarray:
    """
    Min-max normalization to [a, b].
    """
    s_min, s_max = np.min(signal), np.max(signal)
    if s_max == s_min:
        return np.zeros_like(signal)
    a, b = feature_range
    return a + (signal - s_min) * (b - a) / (s_max - s_min)


# ---------------------------------------------------------------------------
# 3. Pan-Tompkins QRS Detector
# ---------------------------------------------------------------------------

def detect_qrs(signal: np.ndarray, fs: float = 360.0) -> dict:
    """
    Simplified Pan-Tompkins algorithm.

    Steps:
      1. Bandpass 5–15 Hz
      2. Differentiate
      3. Square
      4. Moving-window integration
      5. Peak detection with adaptive threshold
      6. R, Q, S peak localisation

    Args:
        signal : 1-D ECG signal (single lead)
        fs     : sampling frequency (Hz)

    Returns:
        dict with keys: 'r_peaks', 'q_peaks', 's_peaks' (arrays of indices)
    """
    # --- Step 1: bandpass 5-15 Hz ---
    nyq = 0.5 * fs
    b, a = butter(2, [5.0 / nyq, 15.0 / nyq], btype="band")
    filtered = filtfilt(b, a, signal)

    # --- Step 2: derivative ---
    diff_sig = np.diff(filtered, prepend=filtered[0])

    # --- Step 3: square ---
    squared = diff_sig ** 2

    # --- Step 4: moving-window integration (150 ms window) ---
    win = int(0.150 * fs)
    integrated = uniform_filter1d(squared, size=win)

    # --- Step 5: normalise & detect peaks ---
    sig_range = integrated.max() - integrated.min()
    if sig_range == 0:
        return {"r_peaks": np.array([]), "q_peaks": np.array([]), "s_peaks": np.array([])}
    normalised = (integrated - integrated.min()) / sig_range

    min_distance = int(fs * 0.2)          # 200 ms refractory period
    candidate_peaks, _ = find_peaks(normalised, distance=min_distance, height=0.5)

    # --- Step 6: R, Q, S localisation ---
    r_peaks, q_peaks, s_peaks = [], [], []
    search_r = int(fs / 5)
    search_qs = int(fs / 4)

    for cp in candidate_peaks:
        # R = max in ± search_r window
        lo = max(0, cp - search_r)
        hi = min(len(signal), cp + search_r)
        r = lo + int(np.argmax(signal[lo:hi]))
        r_peaks.append(r)

        # Q = min before R
        lo_q = max(0, r - search_qs)
        q = lo_q + int(np.argmin(signal[lo_q:r])) if r > lo_q else r
        q_peaks.append(q)

        # S = min after R
        hi_s = min(len(signal), r + search_qs)
        s = r + int(np.argmin(signal[r:hi_s])) if hi_s > r else r
        s_peaks.append(s)

    return {
        "r_peaks": np.array(r_peaks),
        "q_peaks": np.array(q_peaks),
        "s_peaks": np.array(s_peaks),
    }


def extract_qrs_features(signal: np.ndarray, r_peaks: np.ndarray,
                          fs: float = 360.0) -> np.ndarray:
    """
    Extract per-beat QRS interval features:
      [rr_interval, qrs_duration, r_amplitude, q_amplitude, s_amplitude]

    Args:
        signal  : 1-D ECG
        r_peaks : R-peak indices from detect_qrs()
        fs      : sampling frequency

    Returns:
        Feature matrix of shape (n_beats, 5)
    """
    features = []
    rr_intervals = np.diff(r_peaks) / fs  # in seconds

    for i, r in enumerate(r_peaks):
        rr = rr_intervals[i - 1] if i > 0 else (rr_intervals[0] if len(rr_intervals) > 0 else 0.0)

        win = int(fs / 4)
        lo = max(0, r - win)
        hi = min(len(signal), r + win)
        segment = signal[lo:hi]

        q_amp = float(np.min(segment[:len(segment)//2])) if len(segment) >= 2 else 0.0
        s_amp = float(np.min(segment[len(segment)//2:])) if len(segment) >= 2 else 0.0
        r_amp = float(signal[r])

        # QRS duration: between Q trough and S trough (approx)
        qrs_dur = (2 * win) / fs

        features.append([rr, qrs_dur, r_amp, q_amp, s_amp])

    return np.array(features, dtype=np.float32)


def extract_qrs7_features(signal: np.ndarray, fs: float = 500.0,
                           eps: float = 1e-8) -> np.ndarray:
    """
    Extract the 7-dimensional Pan-Tompkins auxiliary feature vector from a
    single-lead (Lead II) ECG recording.

    This vector is designed to give the QRS auxiliary branch hard-coded
    discriminating power over the two hardest classes:

        IAVB  — First-Degree AV Block
                Prolonged PR interval distorts beat geometry → low std_QRS_amp
                but normal RR_CV (regular rhythm).

        AF    — Atrial Fibrillation
                Chaotic, irregular RR intervals → very high RR_CV (> ~0.10)
                and high std_RR, while mean_HR_bpm is often elevated.

    Feature vector (index → name):
        0  mean_RR        Mean RR interval (s) — overall rhythm speed
        1  std_RR         Std of RR intervals  — heart-rate variability (HRV)
        2  mean_QRS_amp   Mean R-peak amplitude — ventricular force
        3  std_QRS_amp    Std of R-peak amplitudes — beat consistency
        4  mean_HR_bpm    60 / mean_RR          — heart rate
        5  RR_CV          std_RR / mean_RR      — normalised irregularity
                          (near-zero for NSR/SB/STach, > 0.10 for AF)
        6  beats_per_sec  n_beats / duration    — global rate

    Args:
        signal : 1-D filtered + normalised ECG from Lead II (or best lead)
        fs     : sampling frequency (Hz)
        eps    : small constant to avoid division by zero

    Returns:
        features : float32 array of shape (7,)
                   All-zeros if fewer than 2 beats are detected.
    """
    qrs = detect_qrs(signal, fs=fs)
    r_peaks = qrs["r_peaks"]

    if len(r_peaks) < 2:
        return np.zeros(7, dtype=np.float32)

    # --- RR intervals ---
    rr_intervals = np.diff(r_peaks).astype(np.float64) / fs   # seconds

    mean_RR      = float(np.mean(rr_intervals))
    std_RR       = float(np.std(rr_intervals))

    # --- Amplitude statistics ---
    r_amps       = signal[r_peaks].astype(np.float64)
    mean_QRS_amp = float(np.mean(r_amps))
    std_QRS_amp  = float(np.std(r_amps))

    # --- Derived features ---
    mean_HR_bpm  = 60.0 / (mean_RR + eps)
    RR_CV        = std_RR / (mean_RR + eps)          # coefficient of variation

    duration_sec = len(signal) / fs
    beats_per_sec = len(r_peaks) / (duration_sec + eps)

    features = np.array([
        mean_RR,
        std_RR,
        mean_QRS_amp,
        std_QRS_amp,
        mean_HR_bpm,
        RR_CV,
        beats_per_sec,
    ], dtype=np.float32)

    return features


# ---------------------------------------------------------------------------
# 4. Segmentation
# ---------------------------------------------------------------------------

def beat_segmentation(signal: np.ndarray, r_peaks: np.ndarray,
                       before: int = 100, after: int = 200) -> np.ndarray:
    """
    Extract fixed-length segments centred (roughly) on each R peak.

    Args:
        signal  : 1-D ECG
        r_peaks : R-peak indices
        before  : samples before R peak
        after   : samples after R peak

    Returns:
        Array of shape (n_beats, before + after)
    """
    segments = []
    seg_len = before + after
    for r in r_peaks:
        lo = r - before
        hi = r + after
        if lo < 0 or hi > len(signal):
            continue
        segments.append(signal[lo:hi])
    return np.array(segments, dtype=np.float32) if segments else np.empty((0, seg_len), dtype=np.float32)


def whole_signal_segmentation(signal: np.ndarray, window_sec: float = 10.0,
                               fs: float = 360.0, step_sec: float = None) -> np.ndarray:
    """
    Sliding-window segmentation of a full ECG recording.

    Args:
        signal     : 1-D ECG
        window_sec : window length in seconds
        fs         : sampling frequency
        step_sec   : step size in seconds (defaults to window_sec → non-overlapping)

    Returns:
        Array of shape (n_windows, window_samples)
    """
    win_len = int(window_sec * fs)
    step_len = int((step_sec or window_sec) * fs)
    segments = []
    start = 0
    while start + win_len <= len(signal):
        segments.append(signal[start:start + win_len])
        start += step_len
    return np.array(segments, dtype=np.float32) if segments else np.empty((0, win_len), dtype=np.float32)


# ---------------------------------------------------------------------------
# 5. Padding / Truncation
# ---------------------------------------------------------------------------

def pad_or_truncate(signal: np.ndarray, target_len: int,
                    pad_value: float = 0.0) -> np.ndarray:
    """
    Make signal exactly `target_len` samples long.
    Truncates from the end or zero-pads on the right.

    Args:
        signal     : 1-D array
        target_len : desired length
        pad_value  : value used for padding (default 0)

    Returns:
        1-D array of length target_len
    """
    if len(signal) >= target_len:
        return signal[:target_len]
    pad_width = target_len - len(signal)
    return np.pad(signal, (0, pad_width), constant_values=pad_value)


def pad_batch(signals: list, target_len: int = None, pad_value: float = 0.0) -> np.ndarray:
    """
    Pad/truncate a list of variable-length signals to a common length.

    Args:
        signals    : list of 1-D arrays
        target_len : if None, uses the max length in the list
        pad_value  : padding constant

    Returns:
        Array of shape (n_signals, target_len)
    """
    if target_len is None:
        target_len = max(len(s) for s in signals)
    return np.array([pad_or_truncate(s, target_len, pad_value) for s in signals], dtype=np.float32)


# ---------------------------------------------------------------------------
# 6. Full Preprocessing Pipeline
# ---------------------------------------------------------------------------

class ECGPreprocessor:
    """
    End-to-end preprocessing for a single ECG recording (one lead).

    Usage:
        preprocessor = ECGPreprocessor(fs=360, target_len=3600)
        result = preprocessor.process(raw_signal)
        # result["signal"]       → clean, normalised, padded signal  (3600,)
        # result["qrs"]          → QRS peak indices dict
        # result["qrs_features"] → per-beat feature matrix  (n_beats, 5)
    """

    def __init__(self, fs: float = 360.0, target_len: int = 3600,
                 powerline_freq: float = 50.0, normalization: str = "zscore"):
        """
        Args:
            fs             : sampling frequency (Hz)
            target_len     : output signal length (samples)
            powerline_freq : 50 or 60 Hz
            normalization  : "zscore" | "minmax"
        """
        self.fs = fs
        self.target_len = target_len
        self.powerline_freq = powerline_freq
        self.normalization = normalization

    def process(self, signal: np.ndarray) -> dict:
        """
        Full pipeline: filter → normalise → detect QRS → pad/truncate.

        Returns dict with keys:
            "signal"       : preprocessed 1-D array  (target_len,)
            "qrs"          : {"r_peaks", "q_peaks", "s_peaks"}
            "qrs_features" : ndarray  (n_beats, 5)
        """
        # 1. Filter
        clean = full_filter_pipeline(signal, fs=self.fs, powerline_freq=self.powerline_freq)

        # 2. Normalise
        if self.normalization == "zscore":
            norm = z_score_normalize(clean)
        else:
            norm = minmax_normalize(clean)

        # 3. QRS detection (on the normalised signal)
        qrs = detect_qrs(norm, fs=self.fs)

        # 4. Per-beat QRS features  (n_beats × 5)
        qrs_features = (extract_qrs_features(norm, qrs["r_peaks"], fs=self.fs)
                        if len(qrs["r_peaks"]) > 0 else np.zeros((0, 5), dtype=np.float32))

        # 5. Recording-level 7-dim auxiliary feature vector
        qrs7 = extract_qrs7_features(norm, fs=self.fs)

        # 6. Pad / truncate
        final = pad_or_truncate(norm, self.target_len)

        return {
            "signal":        final,
            "qrs":           qrs,
            "qrs_features":  qrs_features,   # (n_beats, 5)
            "qrs7_features": qrs7,           # (7,)  ← auxiliary branch input
        }


class MultiLeadECGPreprocessor:
    """
    Applies ECGPreprocessor independently to each of C leads.

    The 7-dim QRS auxiliary feature vector is extracted from Lead II
    (index 1 in standard 12-lead order: I, II, III, aVR, aVL, aVF, V1-V6).
    If fewer than 2 leads are present, lead 0 is used instead.

    Usage:
        prep = MultiLeadECGPreprocessor(fs=500, n_leads=12, target_len=5000)
        result = prep.process(raw_ecg_12lead)   # raw_ecg_12lead: (T, 12)
        result["signals"]       → (5000, 12)
        result["qrs"]           → list of 12 QRS dicts
        result["qrs7_features"] → (7,)  ← from Lead II, for auxiliary branch
    """

    # Standard 12-lead index for Lead II
    LEAD_II_IDX = 1

    def __init__(self, fs: float = 500.0, n_leads: int = 12,
                 target_len: int = 5000, lead_ii_idx: int = LEAD_II_IDX,
                 **kwargs):
        self.n_leads     = n_leads
        self.lead_ii_idx = min(lead_ii_idx, n_leads - 1)
        self.preprocessors = [ECGPreprocessor(fs=fs, target_len=target_len, **kwargs)
                               for _ in range(n_leads)]

    def process(self, ecg: np.ndarray) -> dict:
        """
        Args:
            ecg : array of shape (T, n_leads)

        Returns:
            dict with:
                "signals"       : (target_len, n_leads)
                "qrs"           : list of n_leads QRS dicts
                "qrs_features"  : list of n_leads per-beat feature matrices
                "qrs7_features" : (7,) recording-level auxiliary features from Lead II
        """
        assert ecg.ndim == 2 and ecg.shape[1] == self.n_leads, \
            f"Expected shape (T, {self.n_leads}), got {ecg.shape}"

        signals, qrs_list, feat_list = [], [], []
        for ch in range(self.n_leads):
            result = self.preprocessors[ch].process(ecg[:, ch])
            signals.append(result["signal"])
            qrs_list.append(result["qrs"])
            feat_list.append(result["qrs_features"])

        # Auxiliary 7-dim features from Lead II (most reliable for rhythm)
        lead_ii_result = self.preprocessors[self.lead_ii_idx].process(
            ecg[:, self.lead_ii_idx]
        )

        return {
            "signals":       np.stack(signals, axis=-1),   # (target_len, n_leads)
            "qrs":           qrs_list,
            "qrs_features":  feat_list,
            "qrs7_features": lead_ii_result["qrs7_features"],  # (7,)
        }