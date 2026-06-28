// ---------------------------------------------------------------------------
// seizure_gate_replay.cpp — CLI entry point
//
// Subcommands:
//   test                  run unit tests
//   replay   --csv PATH   replay a Python alert CSV through the C++ gate
//                         and report status accuracy + score delta
//   evaluate --csv PATH --eeg T --clinical T
//                         compute LEO/LCO from the CSV
//   bench                 micro-benchmark the gate core (10M frames)
//
// Build (Linux/macOS):
//   g++ -std=c++17 -O2 -Iinclude src/main.cpp -o seizure_gate_replay
//
// Build (Windows MSVC):
//   cl /std:c++17 /O2 /Iinclude src\main.cpp /Fe:seizure_gate_replay.exe
//
// Build (CMake):
//   cmake -S . -B build && cmake --build build --config Release
// ---------------------------------------------------------------------------

#include "seizure_gate.hpp"
#include "seizure_gate_tests.hpp"
#include "csv_replay.hpp"

#include <iostream>
#include <string>
#include <vector>
#include <chrono>
#include <cstring>
#include <cmath>
#include <iomanip>
#include <limits>

// ---------------------------------------------------------------------------
// Simple argument parser
// ---------------------------------------------------------------------------
struct Args {
    std::string subcommand;
    std::string csv_path;
    double      eeg_onset      = 0.0;
    double      clinical_onset = 17.0;
    std::string video_id       = "video";
    std::string mode_str       = "monitor";
    double      threshold      = std::numeric_limits<double>::quiet_NaN();
    bool        verbose        = false;
};

static Args parse_args(int argc, char** argv) {
    Args a;
    if (argc < 2) { a.subcommand = "help"; return a; }
    a.subcommand = argv[1];
    for (int i = 2; i < argc; ++i) {
        std::string arg = argv[i];
        if ((arg == "--csv" || arg == "--scores") && i+1 < argc)
            a.csv_path = argv[++i];
        else if (arg == "--eeg" && i+1 < argc)
            a.eeg_onset = std::stod(argv[++i]);
        else if (arg == "--clinical" && i+1 < argc)
            a.clinical_onset = std::stod(argv[++i]);
        else if (arg == "--video-id" && i+1 < argc)
            a.video_id = argv[++i];
        else if (arg == "--mode" && i+1 < argc)
            a.mode_str = argv[++i];
        else if (arg == "--threshold" && i+1 < argc)
            a.threshold = std::stod(argv[++i]);
        else if (arg == "--verbose" || arg == "-v")
            a.verbose = true;
    }
    return a;
}

static seizure::Mode parse_mode(const std::string& s) {
    if (s == "safety")    return seizure::Mode::safety;
    return seizure::Mode::monitor;
}

// ---------------------------------------------------------------------------
// Subcommand: bench — raw gate throughput
// ---------------------------------------------------------------------------
static int cmd_bench() {
    using namespace seizure;
    using clock = std::chrono::high_resolution_clock;

    constexpr int N = 10'000'000;
    SeizureGate g(Mode::monitor);

    // Pre-fill: one CJ result and some AP
    g.push_cj(0.35, 0.0);
    for (int i = 0; i < 18; ++i) g.push_vsvig(0.1, i * 0.167);

    auto t0 = clock::now();
    volatile double sink = 0.0;   // prevent dead-code elimination
    for (int i = 0; i < N; ++i) {
        double t = 30.0 + i * (1.0/30.0);
        // Simulate 5-FPS VSViG cadence
        if (i % 6 == 0) g.push_vsvig(0.08, t);
        // Simulate CJ every 5s (150 frames @ 30fps)
        if (i % 150 == 0) g.push_cj(0.30 + (i % 5) * 0.04, t);
        auto r = g.decide(i, t);
        sink += r.seizure_signal;
    }
    auto t1 = clock::now();

    double elapsed_ms = std::chrono::duration<double, std::milli>(t1-t0).count();
    double fps = N / (elapsed_ms / 1000.0);

    std::cout << std::fixed << std::setprecision(1);
    std::cout << "bench: " << N << " frames in " << elapsed_ms << " ms\n";
    std::cout << "throughput: " << fps << " frames/sec\n";
    std::cout << "(gate-only, no model inference — this is the clinical math overhead)\n";
    std::cout << "(sink=" << sink << " to prevent dead-code elimination)\n";
    return 0;
}

// ---------------------------------------------------------------------------
// Subcommand: replay
// ---------------------------------------------------------------------------
static int cmd_replay(const Args& a) {
    if (a.csv_path.empty()) {
        std::cerr << "replay requires --csv PATH\n";
        return 1;
    }

    std::cout << "Loading CSV: " << a.csv_path << "\n";
    std::vector<seizure::AlertRow> rows;
    try {
        rows = seizure::load_alert_csv(a.csv_path);
    } catch (const std::exception& e) {
        std::cerr << "Error: " << e.what() << "\n";
        return 1;
    }
    std::cout << "Loaded " << rows.size() << " rows\n";

    auto mode = parse_mode(a.mode_str);
    auto results = seizure::replay(rows, mode, a.threshold, a.verbose);
    auto summary = seizure::summarise(results);

    std::cout << std::fixed << std::setprecision(4);
    std::cout << "\nReplay summary (mode=" << a.mode_str << ")\n";
    if (std::isfinite(a.threshold))
        std::cout << "  threshold      : " << a.threshold << "\n";
    std::cout << "  total frames   : " << summary.total_frames << "\n";
    std::cout << "  status matches : " << summary.status_matches << "\n";
    std::cout << "  status accuracy: " << summary.status_accuracy * 100.0 << " %\n";
    std::cout << "  source accuracy: " << summary.source_accuracy * 100.0 << " %\n";
    std::cout << "  latch accuracy : " << summary.latch_accuracy * 100.0 << " %\n";
    std::cout << "  mean |Δscore|  : " << summary.mean_score_delta << "\n";
    std::cout << "  max  |Δscore|  : " << summary.max_score_delta << "\n";

    // Count SEIZURE rows in Python CSV vs C++ replay
    int py_seizure = 0, cpp_seizure = 0;
    for (const auto& r : results) {
        if (r.py_status == "SEIZURE") ++py_seizure;
        if (r.cpp_status == seizure::Status::seizure) ++cpp_seizure;
    }
    std::cout << "  python SEIZURE rows  : " << py_seizure << "\n";
    std::cout << "  c++    SEIZURE rows  : " << cpp_seizure << "\n";

    return 0;
}

// ---------------------------------------------------------------------------
// Subcommand: evaluate
// ---------------------------------------------------------------------------
static int cmd_evaluate(const Args& a) {
    if (a.csv_path.empty()) {
        std::cerr << "evaluate requires --csv PATH\n";
        return 1;
    }

    std::vector<seizure::AlertRow> rows;
    try {
        rows = seizure::load_alert_csv(a.csv_path);
    } catch (const std::exception& e) {
        std::cerr << "Error: " << e.what() << "\n";
        return 1;
    }

    seizure::SeizureAnnotation ann;
    ann.video_id           = a.video_id;
    ann.eeg_onset_sec      = a.eeg_onset;
    ann.clinical_onset_sec = a.clinical_onset;

    auto m = seizure::evaluate_clinical(rows, ann);
    seizure::print_clinical_report(m, ann);
    return 0;
}

// ---------------------------------------------------------------------------
// Help
// ---------------------------------------------------------------------------
static void print_help(const char* prog) {
    std::cout << "Usage: " << prog << " <subcommand> [options]\n\n";
    std::cout << "Subcommands:\n";
    std::cout << "  test\n";
    std::cout << "      Run unit tests for the C++ gate core.\n\n";
    std::cout << "  replay --csv PATH [--mode safety|monitor] [-v]\n";
    std::cout << "      Replay a Python alert CSV through the C++ gate.\n";
    std::cout << "      Prints status accuracy and score delta vs Python.\n\n";
    std::cout << "  evaluate --csv PATH --eeg T --clinical T [--video-id ID]\n";
    std::cout << "      Compute LEO, LCO\n";
    std::cout << "      a Python alert CSV given a ground-truth annotation.\n\n";
    std::cout << "  bench\n";
    std::cout << "      Micro-benchmark the gate core (10M frames, no models).\n\n";
    std::cout << "Examples:\n";
    std::cout << "  " << prog << " test\n";
    std::cout << "  " << prog << " replay --csv runtime_outputs/pat10_Sz1P_monitor_fixed_final_alerts.csv --mode monitor\n";
    std::cout << "  " << prog << " evaluate --csv runtime_outputs/pat10_Sz1P_monitor_fixed_final_alerts.csv \\\n";
    std::cout << "             --eeg 0.0 --clinical 17.0 --video-id pat10_Sz1P\n";
    std::cout << "  " << prog << " bench\n";
}

// ---------------------------------------------------------------------------
// main
// ---------------------------------------------------------------------------
int main(int argc, char** argv) {
    auto a = parse_args(argc, argv);

    if (a.subcommand == "test") {
        int failures = seizure::tests::run_tests();
        return failures > 0 ? 1 : 0;
    }

    if (a.subcommand == "replay")
        return cmd_replay(a);

    if (a.subcommand == "evaluate")
        return cmd_evaluate(a);

    if (a.subcommand == "bench")
        return cmd_bench();

    print_help(argc > 0 ? argv[0] : "seizure_gate_replay");
    return a.subcommand == "help" ? 0 : 1;
}
