#pragma once

#include "seizure_gate.hpp"

#include <algorithm>
#include <cmath>
#include <fstream>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <vector>

namespace seizure {

inline std::vector<std::string> split_csv_line(const std::string& line) {
    std::vector<std::string> out;
    std::string field;
    bool in_quotes = false;
    for (char ch : line) {
        if (ch == '"') {
            in_quotes = !in_quotes;
            continue;
        }
        if (ch == ',' && !in_quotes) {
            out.push_back(field);
            field.clear();
            continue;
        }
        field.push_back(ch);
    }
    out.push_back(field);
    return out;
}

inline double parse_double(const std::string& text) {
    if (text.empty()) {
        return std::numeric_limits<double>::quiet_NaN();
    }
    try {
        return std::stod(text);
    } catch (...) {
        return std::numeric_limits<double>::quiet_NaN();
    }
}

inline bool parse_bool(const std::string& text) {
    return text == "1" || text == "true" || text == "TRUE" || text == "True";
}

struct AlertRow {
    int frame = -1;
    double time_sec = 0.0;
    std::string status;
    std::string seizure_source;
    double seizure_signal = 0.0;
    double current_risk = 0.0;
    double cj_prob = std::numeric_limits<double>::quiet_NaN();
    double cj_age_sec = std::numeric_limits<double>::quiet_NaN();
    bool alert_latched = false;
};

inline std::vector<AlertRow> load_alert_csv(const std::string& path) {
    std::ifstream file(path);
    if (!file.is_open()) {
        throw std::runtime_error("Cannot open CSV: " + path);
    }

    std::string header_line;
    if (!std::getline(file, header_line)) {
        throw std::runtime_error("Empty CSV: " + path);
    }

    const auto headers = split_csv_line(header_line);
    std::unordered_map<std::string, std::size_t> index;
    for (std::size_t i = 0; i < headers.size(); ++i) {
        index[headers[i]] = i;
    }

    auto get = [&](const std::vector<std::string>& row, const std::string& name) -> std::string {
        const auto it = index.find(name);
        if (it == index.end() || it->second >= row.size()) {
            return "";
        }
        return row[it->second];
    };

    std::vector<AlertRow> rows;
    std::string line;
    while (std::getline(file, line)) {
        if (line.empty()) {
            continue;
        }
        const auto cells = split_csv_line(line);
        AlertRow row;
        row.frame = static_cast<int>(parse_double(get(cells, "frame")));
        row.time_sec = parse_double(get(cells, "time_sec"));
        row.status = get(cells, "status");
        row.seizure_source = get(cells, "seizure_source");
        row.seizure_signal = parse_double(get(cells, "seizure_signal"));
        row.current_risk = parse_double(get(cells, "current_risk"));
        row.cj_prob = parse_double(get(cells, "cj_prob"));
        row.cj_age_sec = parse_double(get(cells, "cj_age_sec"));
        row.alert_latched = parse_bool(get(cells, "alert_latched"));
        rows.push_back(row);
    }
    return rows;
}

struct ReplayResult {
    int frame = -1;
    double time_sec = 0.0;
    Status cpp_status = Status::initialising;
    double cpp_score = 0.0;
    std::string cpp_source;
    bool cpp_latched = false;
    std::string py_status;
    double py_score = 0.0;
    std::string py_source;
    bool py_latched = false;
    bool status_match = false;
    bool source_match = false;
    bool latch_match = false;
    double score_delta = 0.0;
};



inline std::vector<ReplayResult> replay(
    const std::vector<AlertRow>& rows,
    Mode mode = Mode::monitor,
    double threshold_override = std::numeric_limits<double>::quiet_NaN(),
    bool verbose = false
) {
    SeizureGate gate(mode, threshold_override);
    std::vector<ReplayResult> results;
    results.reserve(rows.size());

    for (const auto& row : rows) {
        const std::optional<double> cj_prob = finite_optional(row.cj_prob);
        const std::optional<double> cj_age = finite_optional(row.cj_age_sec);

        FrameResult frame = gate.decide_from_signals(
            row.frame,
            row.time_sec,
            row.current_risk,
            cj_prob,
            cj_age
        );

        ReplayResult result;
        result.frame = row.frame;
        result.time_sec = row.time_sec;
        result.cpp_status = frame.status;
        result.cpp_score = frame.seizure_signal;
        result.cpp_source = frame.seizure_source;
        result.cpp_latched = frame.alert_latched;
        result.py_status = row.status;
        result.py_score = row.seizure_signal;
        result.py_source = row.seizure_source;
        result.py_latched = row.alert_latched;
        result.status_match = status_str(frame.status) == row.status;
        result.source_match = row.seizure_source.empty() || frame.seizure_source == row.seizure_source;
        result.latch_match = frame.alert_latched == row.alert_latched;
        result.score_delta = std::abs(frame.seizure_signal - row.seizure_signal);
        results.push_back(result);

        if (verbose && (!result.status_match || result.score_delta > 1e-6 || !result.source_match || !result.latch_match)) {
            std::cout << "mismatch frame=" << row.frame
                      << " t=" << row.time_sec
                      << " py_status=" << row.status
                      << " cpp_status=" << status_str(frame.status)
                      << " py_score=" << row.seizure_signal
                      << " cpp_score=" << frame.seizure_signal
                      << " py_source=" << row.seizure_source
                      << " cpp_source=" << frame.seizure_source
                      << " py_latch=" << row.alert_latched
                      << " cpp_latch=" << frame.alert_latched
                      << "\n";
        }
    }
    return results;
}

struct ReplaySummary {
    int total_frames = 0;
    int status_matches = 0;
    int source_matches = 0;
    int latch_matches = 0;
    double status_accuracy = 0.0;
    double source_accuracy = 0.0;
    double latch_accuracy = 0.0;
    double mean_score_delta = 0.0;
    double max_score_delta = 0.0;
};

inline ReplaySummary summarise(const std::vector<ReplayResult>& results) {
    ReplaySummary summary;
    summary.total_frames = static_cast<int>(results.size());
    double score_delta_sum = 0.0;
    for (const auto& result : results) {
        if (result.status_match) {
            ++summary.status_matches;
        }
        if (result.source_match) {
            ++summary.source_matches;
        }
        if (result.latch_match) {
            ++summary.latch_matches;
        }
        score_delta_sum += result.score_delta;
        summary.max_score_delta = std::max(summary.max_score_delta, result.score_delta);
    }
    if (summary.total_frames > 0) {
        summary.status_accuracy = static_cast<double>(summary.status_matches) / summary.total_frames;
        summary.source_accuracy = static_cast<double>(summary.source_matches) / summary.total_frames;
        summary.latch_accuracy = static_cast<double>(summary.latch_matches) / summary.total_frames;
        summary.mean_score_delta = score_delta_sum / summary.total_frames;
    }
    return summary;
}

struct SeizureAnnotation {
    std::string video_id;
    double eeg_onset_sec = 0.0;
    double clinical_onset_sec = 0.0;
};

struct ClinicalMetrics {
    std::string video_id;
    double first_alert_sec = -1.0;
    bool detected = false;
    double leo_sec = 0.0;
    double lco_sec = 0.0;
};

inline ClinicalMetrics evaluate_clinical(
    const std::vector<AlertRow>& rows,
    const SeizureAnnotation& annotation
) {
    ClinicalMetrics metrics;
    metrics.video_id = annotation.video_id;

    for (const auto& row : rows) {
        if (row.time_sec >= annotation.eeg_onset_sec) {
            break;
        }
    }

    for (const auto& row : rows) {
        if (row.time_sec >= annotation.eeg_onset_sec && row.status == "SEIZURE") {
            metrics.detected = true;
            metrics.first_alert_sec = row.time_sec;
            metrics.leo_sec = row.time_sec - annotation.eeg_onset_sec;
            metrics.lco_sec = row.time_sec - annotation.clinical_onset_sec;
            break;
        }
    }

    return metrics;
}

inline void print_clinical_report(const ClinicalMetrics& metrics, const SeizureAnnotation& annotation) {
    std::cout << "--- Clinical report: " << metrics.video_id << " ---\n";
    std::cout << "  EEG onset          : " << annotation.eeg_onset_sec << " s\n";
    std::cout << "  Clinical onset     : " << annotation.clinical_onset_sec << " s\n";
    if (metrics.detected) {
        std::cout << "  First alert        : " << metrics.first_alert_sec << " s\n";
        std::cout << "  LEO                : " << metrics.leo_sec << " s\n";
        std::cout << "  LCO                : " << metrics.lco_sec << " s\n";
    } else {
        std::cout << "  First alert        : NOT DETECTED\n";
    }
}

}  // namespace seizure
