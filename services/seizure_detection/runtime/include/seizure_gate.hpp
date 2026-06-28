#pragma once

#include <algorithm>
#include <cmath>
#include <deque>
#include <limits>
#include <optional>
#include <string>
#include <utility>

namespace seizure {

constexpr double GATE_UPPER_BOUND = 0.50;
constexpr double GATE_LOWER_BOUND = 0.20;
constexpr double GATE_ALPHA = 0.30;
constexpr double ALERT_HOLD_SEC = 30.0;
constexpr double CJ_MAX_AGE_SEC = 5.5;
constexpr double CJ_MAX_AGE_NORMAL = CJ_MAX_AGE_SEC;
constexpr double CJ_MAX_AGE_ALERT = CJ_MAX_AGE_SEC;

constexpr double THRESHOLD_SAFETY = 0.88;
constexpr double THRESHOLD_MONITOR = 0.49;
constexpr double THRESHOLD_HELD_OUT = 0.3081087228480716;

enum class Mode { safety, monitor };
enum class Status { initialising, normal, seizure };

inline double threshold_for(Mode mode) {
    switch (mode) {
        case Mode::safety:
            return THRESHOLD_SAFETY;
        default:
            return THRESHOLD_MONITOR;
    }
}

inline const char* status_str(Status status) {
    switch (status) {
        case Status::initialising:
            return "INITIALISING";
        case Status::seizure:
            return "SEIZURE";
        default:
            return "NORMAL";
    }
}

inline bool finite(double value) {
    return std::isfinite(value);
}

inline std::optional<double> finite_optional(double value) {
    return finite(value) ? std::optional<double>(value) : std::nullopt;
}

struct GateDecision {
    double score = 0.0;
    std::string source = "INITIALISING";
};

inline GateDecision series_gate(
    std::optional<double> cj_prob,
    double vsvig_prob
) {
    if (!cj_prob.has_value()) {
        return {0.0, "CJ_PENDING"};
    }

    const double cj = std::clamp(*cj_prob, 0.0, 1.0);
    const double vsvig = std::clamp(vsvig_prob, 0.0, 1.0);

    if (cj >= GATE_UPPER_BOUND) {
        return {cj, "CJ"};
    }
    if (cj >= GATE_LOWER_BOUND) {
        return {std::max(0.0, GATE_ALPHA * cj + (1.0 - GATE_ALPHA) * vsvig), "BLEND"};
    }
    return {cj, "CJ_LOW"};
}

class AlertLatch {
public:
    explicit AlertLatch(double hold_sec = ALERT_HOLD_SEC) : hold_sec_(hold_sec) {}

    Status update(double score, double threshold, double now_sec, bool warmed_up) {
        if (!warmed_up) {
            alert_latched_ = false;
            return Status::initialising;
        }

        const bool raw_alarm = score >= threshold;
        if (raw_alarm) {
            hold_until_sec_ = std::max(hold_until_sec_, now_sec + hold_sec_);
            alert_latched_ = now_sec <= hold_until_sec_;
            return Status::seizure;
        }

        if (now_sec <= hold_until_sec_) {
            alert_latched_ = true;
            return Status::seizure;
        }

        alert_latched_ = false;
        return Status::normal;
    }

    bool is_latched() const {
        return alert_latched_;
    }

    bool active_at(double now_sec) const {
        return now_sec <= hold_until_sec_;
    }

    void reset() {
        hold_until_sec_ = -1.0;
        alert_latched_ = false;
    }

private:
    double hold_sec_;
    double hold_until_sec_ = -1.0;
    bool alert_latched_ = false;
};

struct FrameResult {
    int frame = 0;
    double time_sec = 0.0;
    Status status = Status::initialising;
    double seizure_signal = 0.0;
    std::string seizure_source = "INITIALISING";
    double current_risk = 0.0;
    double cj_prob = std::numeric_limits<double>::quiet_NaN();
    double cj_age_sec = std::numeric_limits<double>::quiet_NaN();
    bool alert_latched = false;
};

class SeizureGate {
public:
    explicit SeizureGate(Mode mode = Mode::monitor, double custom_threshold = quiet_nan())
        : mode_(mode),
          threshold_(finite(custom_threshold) ? custom_threshold : threshold_for(mode)) {}

    void set_mode(Mode mode) {
        mode_ = mode;
        threshold_ = threshold_for(mode);
    }

    void set_threshold(double threshold) {
        if (finite(threshold)) {
            threshold_ = threshold;
        }
    }

    double threshold() const {
        return threshold_;
    }

    void push_vsvig(double probability, double time_sec) {
        (void)time_sec;
        if (!finite(probability)) {
            return;
        }
        current_risk_ = std::max(0.0, probability);
    }

    void push_cj(double probability, double delivered_time_sec) {
        if (!finite(probability) || !finite(delivered_time_sec)) {
            return;
        }
        cj_prob_ = std::clamp(probability, 0.0, 1.0);
        cj_delivered_time_sec_ = delivered_time_sec;
        cj_seen_ = true;
    }

    FrameResult decide(int frame_idx, double time_sec) {
        std::optional<double> cj_age_sec;
        if (cj_seen_) {
            cj_age_sec = std::max(0.0, time_sec - cj_delivered_time_sec_);
        }
        return decide_from_signals(
            frame_idx,
            time_sec,
            current_risk_,
            cj_seen_ ? std::optional<double>(cj_prob_) : std::nullopt,
            cj_age_sec
        );
    }

    FrameResult decide_from_signals(
        int frame_idx,
        double time_sec,
        double current_risk,
        std::optional<double> cj_prob,
        std::optional<double> cj_age_sec
    ) {
        if (cj_prob.has_value() && cj_age_sec.has_value()) {
            cj_seen_for_alert_ = true;
        }

        GateDecision decision = series_gate(cj_prob, current_risk);

        Status status = latch_.update(decision.score, threshold_, time_sec, cj_seen_for_alert_);
        bool alert_latched = latch_.is_latched();
        std::string source = decision.source;
        double signal = decision.score;

        if (!cj_seen_for_alert_) {
            source = "INITIALISING";
            signal = 0.0;
            status = Status::initialising;
            alert_latched = false;
        }

        last_status_ = status;

        return FrameResult{
            frame_idx,
            time_sec,
            status,
            signal,
            source,
            current_risk,
            cj_prob.value_or(quiet_nan()),
            cj_age_sec.value_or(quiet_nan()),
            alert_latched
        };
    }

    void reset() {
        latch_.reset();
        cj_seen_ = false;
        cj_seen_for_alert_ = false;
        current_risk_ = 0.0;
        cj_prob_ = quiet_nan();
        cj_delivered_time_sec_ = -1.0;
        last_status_ = Status::initialising;
    }

private:
    static double quiet_nan() {
        return std::numeric_limits<double>::quiet_NaN();
    }

    Mode mode_;
    double threshold_;
    AlertLatch latch_;
    bool cj_seen_ = false;
    bool cj_seen_for_alert_ = false;
    double current_risk_ = 0.0;
    double cj_prob_ = quiet_nan();
    double cj_delivered_time_sec_ = -1.0;
    Status last_status_ = Status::initialising;
};

}  // namespace seizure
