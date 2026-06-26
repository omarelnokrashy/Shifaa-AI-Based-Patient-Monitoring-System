#include "seizure_gate.hpp"

#include <onnxruntime_cxx_api.h>
#include <opencv2/opencv.hpp>

#include <algorithm>
#include <array>
#include <deque>
#include <fstream>
#include <filesystem>
#include <iostream>
#include <numeric>
#include <optional>
#include <string>
#include <chrono>

#define NOMINMAX
#include <windows.h>
#include <mutex>
#include <thread>
#include <atomic>

#include <vector>

namespace {

struct Args {
    std::string command = "check";
    std::filesystem::path repo_root = std::filesystem::current_path().parent_path();
    std::filesystem::path source;
    std::filesystem::path output_csv;
    std::filesystem::path output_video;
    int max_frames = 0;
    double vsvig_sample_fps = 6.0;
    int inference_stride = 15;
    std::string pipe_name = "\\\\.\\pipe\\seizure_vivit_tokens";
    double max_cj_age_sec = seizure::CJ_MAX_AGE_SEC;
    double min_kpt_conf = 0.1;
    int warmup_runs = 3;
    bool display = false;
    bool freeze_kpts = false;
    bool freeze_rgb = false;
    std::string cj_head_onnx_path = "model_weights/cj_final.onnx";
    std::string vsvig_onnx_path = "model_weights/vsvig_protogcn.onnx";
    std::string pose_onnx_path = "model_weights/pose.onnx";
    std::string pose_normalization = "imagenet";
};

Args parse_args(int argc, char** argv) {
    Args args;
    for (int i = 2; i < argc; ++i) {
        if (std::string(argv[i]) == "--root" && i + 1 < argc) {
            args.repo_root = argv[i + 1];
        }
    }
    
    std::ifstream config_file((args.repo_root / "configs" / "default.yaml").string());
    if (config_file.is_open()) {
        std::string line;
        while (std::getline(config_file, line)) {
            auto pos = line.find(":");
            if (pos != std::string::npos && line.find("#") != 0) {
                std::string k = line.substr(0, pos);
                std::string v = line.substr(pos + 1);
                k.erase(0, k.find_first_not_of(" \t"));
                k.erase(k.find_last_not_of(" \t") + 1);
                v.erase(0, v.find_first_not_of(" \t"));
                v.erase(v.find_last_not_of(" \t\r\n") + 1);
                
                if (k == "vsvig_onnx_path") args.vsvig_onnx_path = v;
                else if (k == "cj_head_onnx_path") args.cj_head_onnx_path = v;
                else if (k == "pose_onnx_path") args.pose_onnx_path = v;
                else if (k == "pose_normalization") args.pose_normalization = v;
                else if (k == "vsvig_sample_fps") args.vsvig_sample_fps = std::stod(v);
                else if (k == "inference_stride") args.inference_stride = std::stoi(v);
                else if (k == "warmup_runs") args.warmup_runs = std::stoi(v);
            }
        }
    } else {
        std::cerr << "Warning: Could not open configs/default.yaml\n";
    }

    if (argc > 1) {
        args.command = argv[1];
    }
    for (int i = 2; i < argc; ++i) {
        const std::string key = argv[i];
        if (key == "--root" && i + 1 < argc) {
            args.repo_root = argv[++i];
        } else if (key == "--source" && i + 1 < argc) {
            args.source = argv[++i];
        } else if (key == "--output-csv" && i + 1 < argc) {
            args.output_csv = argv[++i];
        } else if (key == "--output-video" && i + 1 < argc) {
            args.output_video = argv[++i];
        } else if (key == "--max-frames" && i + 1 < argc) {
            args.max_frames = std::stoi(argv[++i]);
        } else if (key == "--vsvig-sample-fps" && i + 1 < argc) {
            args.vsvig_sample_fps = std::stod(argv[++i]);
        } else if (key == "--inference-stride" && i + 1 < argc) {
            args.inference_stride = std::stoi(argv[++i]);
        } else if (key == "--pipe-name" && i + 1 < argc) {
            args.pipe_name = argv[++i];
        } else if (key == "--max-cj-age-sec" && i + 1 < argc) {
            args.max_cj_age_sec = std::stod(argv[++i]);
        } else if (key == "--min-kpt-conf" && i + 1 < argc) {
            args.min_kpt_conf = std::stod(argv[++i]);
        } else if (key == "--warmup-runs" && i + 1 < argc) {
            args.warmup_runs = std::stoi(argv[++i]);
        } else if (key == "--display") {
            args.display = true;
        } else if (key == "--vsvig-onnx-path" && i + 1 < argc) {
            args.vsvig_onnx_path = argv[++i];
        } else if (key == "--cj-head-onnx-path" && i + 1 < argc) {
            args.cj_head_onnx_path = argv[++i];
        } else if (key == "--pose-onnx-path" && i + 1 < argc) {
            args.pose_onnx_path = argv[++i];
        } else if (key == "--pose-normalization" && i + 1 < argc) {
            args.pose_normalization = argv[++i];
        } else if (key == "--freeze-kpts") {
            args.freeze_kpts = true;
        } else if (key == "--freeze-rgb") {
            args.freeze_rgb = true;
        }
    }
    return args;
}

void print_help(const char* exe) {
    std::cout
        << "Usage: " << exe << " check --root <seizure_detection_dir>\n"
        << "       " << exe << " run --root <seizure_detection_dir> --source <video>\n\n"
        << "       " << exe << " smoke --root <seizure_detection_dir> --source <video>\n\n"
        << "       " << exe << " cj-head-smoke --root <seizure_detection_dir>\n\n"
        << "Options for run:\n"
        << "       --vsvig-sample-fps <fps>    VSViG patch collection cadence, default 6.0\n"
        << "       --inference-stride <frames> VSViG decision cadence, default 15\n\n"
        << "       --max-cj-age-sec <seconds>  Max video-time CJ staleness before waiting, default 5.5\n\n"
        << "       --warmup-runs <n>           ONNX warm-up iterations excluded from FPS, default 3\n"
        << "       --cj-head-onnx-path <path>  CJ head ONNX path relative to root\n"
        << "       --vsvig-onnx-path <path>    VSViG ONNX path relative to root\n"
        << "       --pose-onnx-path <path>     OpenPose ONNX path relative to root\n"
        << "       --pose-normalization <mode> OpenPose input mode: imagenet or openpose\n"
        << "       --display                   Show a live OpenCV inference window with overlays\n\n"
        << "       --output-video <path>       Save an MP4 copy with the live inference overlay\n\n"
        << "This executable is the native C++ runtime boundary. The clinical\n"
        << "decision layer is implemented and validated, but model inference\n"
        << "requires OpenCV C++ libraries, ONNX Runtime C++ development files,\n"
        << "and exported ONNX models for OpenPose, VSViG, and CJ/ViViT.\n";
}

std::vector<const char*> raw_names(const std::vector<Ort::AllocatedStringPtr>& names) {
    std::vector<const char*> out;
    out.reserve(names.size());
    for (const auto& name : names) {
        out.push_back(name.get());
    }
    return out;
}

std::vector<Ort::AllocatedStringPtr> input_names(Ort::Session& session, Ort::AllocatorWithDefaultOptions& allocator) {
    std::vector<Ort::AllocatedStringPtr> names;
    const std::size_t count = session.GetInputCount();
    names.reserve(count);
    for (std::size_t i = 0; i < count; ++i) {
        names.emplace_back(session.GetInputNameAllocated(i, allocator));
    }
    return names;
}

std::vector<Ort::AllocatedStringPtr> output_names(Ort::Session& session, Ort::AllocatorWithDefaultOptions& allocator) {
    std::vector<Ort::AllocatedStringPtr> names;
    const std::size_t count = session.GetOutputCount();
    names.reserve(count);
    for (std::size_t i = 0; i < count; ++i) {
        names.emplace_back(session.GetOutputNameAllocated(i, allocator));
    }
    return names;
}

std::vector<float> preprocess_openpose_frame(
    const cv::Mat& frame_bgr,
    int input_height,
    int& out_w,
    int& out_h,
    const std::string& normalization_mode
) {
    const double scale = static_cast<double>(input_height) / static_cast<double>(frame_bgr.rows);
    out_w = std::max(1, static_cast<int>(std::round(frame_bgr.cols * scale)));
    out_h = input_height;
    cv::Mat resized;
    cv::resize(frame_bgr, resized, cv::Size(out_w, out_h), 0.0, 0.0, cv::INTER_LINEAR);

    std::vector<float> chw(static_cast<std::size_t>(3 * out_h * out_w));
    const float means[3] = {0.485f, 0.456f, 0.406f};
    const float stds[3] = {0.229f, 0.224f, 0.225f};
    const bool use_openpose_normalization = normalization_mode == "openpose";

    for (int y = 0; y < out_h; ++y) {
        const auto* row = resized.ptr<cv::Vec3b>(y);
        for (int x = 0; x < out_w; ++x) {
            for (int c = 0; c < 3; ++c) {
                const std::size_t idx = static_cast<std::size_t>(c * out_h * out_w + y * out_w + x);
                const float pixel = static_cast<float>(row[x][c]);
                chw[idx] = use_openpose_normalization
                    ? (pixel / 128.0f - 1.0f)
                    : (pixel / 255.0f - means[c]) / stds[c];
            }
        }
    }
    return chw;
}

struct Keypoint {
    float x = 0.0f;
    float y = 0.0f;
    float c = 0.0f;
};

std::vector<Keypoint> extract_openpose_keypoints(
    const std::vector<Ort::Value>& outputs,
    int frame_w,
    int frame_h,
    double min_conf
) {
    std::vector<Keypoint> kpts(18);
    if (outputs.size() < 2) {
        return kpts;
    }
    const Ort::Value& heatmap_value = outputs[outputs.size() - 2];
    const auto info = heatmap_value.GetTensorTypeAndShapeInfo();
    const auto shape = info.GetShape();
    if (shape.size() != 4 || shape[0] != 1 || shape[1] < 18) {
        return kpts;
    }

    const int channels = static_cast<int>(shape[1]);
    const int h = static_cast<int>(shape[2]);
    const int w = static_cast<int>(shape[3]);
    const float* data = heatmap_value.GetTensorData<float>();
    const int target_w = std::max(1, static_cast<int>(std::round(frame_w / 8.0)));
    const int target_h = std::max(1, static_cast<int>(std::round(frame_h / 8.0)));

    for (int c = 0; c < std::min(18, channels); ++c) {
        cv::Mat channel(h, w, CV_32F, const_cast<float*>(data + static_cast<std::size_t>(c * h * w)));
        cv::Mat resized;
        cv::resize(channel, resized, cv::Size(target_w, target_h), 0.0, 0.0, cv::INTER_CUBIC);
        double max_val = 0.0;
        cv::Point max_loc;
        cv::minMaxLoc(resized, nullptr, &max_val, nullptr, &max_loc);
        if (max_val >= min_conf) {
            kpts[c] = Keypoint{
                static_cast<float>(max_loc.x * 8.0),
                static_cast<float>(max_loc.y * 8.0),
                static_cast<float>(max_val)
            };
        }
    }
    return kpts;
}

cv::Mat gaussian_kernel_3ch(int size, double sigma_scale) {
    cv::Mat kernel(size, size, CV_64F);
    const double sigma = size * sigma_scale;
    const double center = (size - 1) / 2.0;
    const double pi = std::acos(-1.0);
    for (int y = 0; y < size; ++y) {
        for (int x = 0; x < size; ++x) {
            const double dx = x - center;
            const double dy = y - center;
            double val = (1.0 / (2.0 * pi * sigma * sigma)) * 
                         std::exp(-((dx * dx) + (dy * dy)) / (2.0 * sigma * sigma));
            kernel.at<double>(y, x) = val;
        }
    }
    cv::Scalar sum_val = cv::sum(kernel);
    kernel /= sum_val[0];
    
    double min_val = 0.0;
    double max_val = 0.0;
    cv::minMaxLoc(kernel, &min_val, &max_val);
    kernel = (kernel - min_val) / std::max(1e-12, max_val - min_val);
    std::vector<cv::Mat> channels = {kernel, kernel, kernel};
    cv::Mat merged;
    cv::merge(channels, merged);
    return merged;
}

cv::Mat normalize_frame_255(const cv::Mat& frame_bgr) {
    cv::Mat f32;
    frame_bgr.convertTo(f32, CV_32FC3);
    std::vector<cv::Mat> channels;
    cv::split(f32, channels);
    double min_val = 0.0;
    double max_val = 0.0;
    double global_min = std::numeric_limits<double>::infinity();
    double global_max = -std::numeric_limits<double>::infinity();
    for (const auto& ch : channels) {
        cv::minMaxLoc(ch, &min_val, &max_val);
        global_min = std::min(global_min, min_val);
        global_max = std::max(global_max, max_val);
    }
    if (global_max <= global_min) {
        return f32;
    }
    return (f32 - static_cast<float>(global_min)) * static_cast<float>(255.0 / (global_max - global_min));
}

std::vector<float> extract_vsvig_patches(const cv::Mat& frame_bgr, const std::vector<Keypoint>& kpts) {
    constexpr int kernel_size = 128;
    constexpr int out_size = 32;
    const int selected[15] = {0, 15, 14, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13};
    const cv::Mat kernel = gaussian_kernel_3ch(kernel_size, 0.3);
    const cv::Mat norm = normalize_frame_255(frame_bgr);
    cv::Mat padded = cv::Mat::zeros(frame_bgr.rows + kernel_size * 2, frame_bgr.cols + kernel_size * 2, CV_32FC3);
    norm.copyTo(padded(cv::Rect(kernel_size, kernel_size, frame_bgr.cols, frame_bgr.rows)));

    std::vector<float> patches(static_cast<std::size_t>(15 * out_size * out_size * 3), 0.0f);
    for (int p = 0; p < 15; ++p) {
        const Keypoint& kp = kpts[selected[p]];
        const int xc = static_cast<int>(kp.x);
        const int yc = static_cast<int>(kp.y);
        const int x1 = static_cast<int>(xc + 0.5 * kernel_size);
        const int y1 = static_cast<int>(yc + 0.5 * kernel_size);
        if (x1 < 0 || y1 < 0 || x1 + kernel_size >= padded.cols || y1 + kernel_size >= padded.rows) {
            continue;
        }
        cv::Mat window = padded(cv::Rect(x1, y1, kernel_size, kernel_size));
        cv::Mat window_f64;
        window.convertTo(window_f64, CV_64FC3);
        cv::Mat weighted;
        cv::multiply(window_f64, kernel, weighted);
        cv::Mat resized;
        cv::resize(weighted, resized, cv::Size(out_size, out_size), 0.0, 0.0, cv::INTER_LINEAR);
        for (int y = 0; y < out_size; ++y) {
            const auto* row = resized.ptr<cv::Vec3d>(y);
            for (int x = 0; x < out_size; ++x) {
                for (int c = 0; c < 3; ++c) {
                    const std::size_t idx = static_cast<std::size_t>(((p * out_size + y) * out_size + x) * 3 + c);
                    patches[idx] = static_cast<float>(row[x][c]);
                }
            }
        }
    }
    return patches;
}

std::array<Keypoint, 15> reorder_kpts_for_vsvig(const std::vector<Keypoint>& kpts) {
    const int order[15] = {0, 15, 14, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13};
    std::array<Keypoint, 15> out{};
    for (int i = 0; i < 15; ++i) {
        out[i] = kpts[order[i]];
    }
    return out;
}

double sigmoid(double value) {
    if (!std::isfinite(value)) {
        return 0.0;
    }
    if (value >= 0.0) {
        const double z = std::exp(-value);
        return 1.0 / (1.0 + z);
    }
    const double z = std::exp(value);
    return z / (1.0 + z);
}

int smoke_native_runtime(const Args& args) {
    if (args.source.empty()) {
        std::cerr << "smoke requires --source <video>\n";
        return 1;
    }

    const auto pose_onnx = args.repo_root / args.pose_onnx_path;
    const auto vsvig_onnx = args.repo_root / args.vsvig_onnx_path;

    cv::VideoCapture cap(args.source.string());
    if (!cap.isOpened()) {
        std::cerr << "OpenCV could not open source: " << args.source.string() << "\n";
        return 1;
    }
    cv::Mat frame;
    if (!cap.read(frame) || frame.empty()) {
        std::cerr << "OpenCV could not read first frame.\n";
        return 1;
    }
    std::cout << "OpenCV source opened: " << frame.cols << "x" << frame.rows
              << " fps=" << cap.get(cv::CAP_PROP_FPS) << "\n";

    Ort::Env env(ORT_LOGGING_LEVEL_WARNING, "seizure_runtime_cpp");
    Ort::SessionOptions options;
    options.SetGraphOptimizationLevel(GraphOptimizationLevel::ORT_ENABLE_EXTENDED);
    Ort::AllocatorWithDefaultOptions allocator;
    Ort::MemoryInfo memory = Ort::MemoryInfo::CreateCpu(OrtArenaAllocator, OrtMemTypeDefault);

    Ort::Session pose_session(env, pose_onnx.c_str(), options);
    auto pose_inputs = input_names(pose_session, allocator);
    auto pose_outputs = output_names(pose_session, allocator);
    auto pose_input_raw = raw_names(pose_inputs);
    auto pose_output_raw = raw_names(pose_outputs);

    int pose_w = 0;
    int pose_h = 0;
    auto pose_data = preprocess_openpose_frame(frame, 256, pose_w, pose_h, args.pose_normalization);
    std::vector<int64_t> pose_shape = {1, 3, pose_h, pose_w};
    Ort::Value pose_tensor = Ort::Value::CreateTensor<float>(
        memory,
        pose_data.data(),
        pose_data.size(),
        pose_shape.data(),
        pose_shape.size()
    );
    auto pose_result = pose_session.Run(
        Ort::RunOptions{nullptr},
        pose_input_raw.data(),
        &pose_tensor,
        1,
        pose_output_raw.data(),
        pose_output_raw.size()
    );
    std::cout << "OpenPose ONNX ran: outputs=" << pose_result.size() << "\n";

    Ort::Session vsvig_session(env, vsvig_onnx.c_str(), options);
    auto vsvig_inputs = input_names(vsvig_session, allocator);
    auto vsvig_outputs = output_names(vsvig_session, allocator);
    auto vsvig_input_raw = raw_names(vsvig_inputs);
    auto vsvig_output_raw = raw_names(vsvig_outputs);

    std::vector<float> patches(static_cast<std::size_t>(1 * 30 * 15 * 3 * 32 * 32), 0.0f);
    std::vector<float> kpts(static_cast<std::size_t>(1 * 30 * 15 * 3), 0.0f);
    std::vector<int64_t> patches_shape = {1, 30, 15, 3, 32, 32};
    std::vector<int64_t> kpts_shape = {1, 30, 15, 3};
    Ort::Value patches_tensor = Ort::Value::CreateTensor<float>(
        memory,
        patches.data(),
        patches.size(),
        patches_shape.data(),
        patches_shape.size()
    );
    Ort::Value kpts_tensor = Ort::Value::CreateTensor<float>(
        memory,
        kpts.data(),
        kpts.size(),
        kpts_shape.data(),
        kpts_shape.size()
    );
    std::array<Ort::Value, 2> vsvig_tensors = {std::move(patches_tensor), std::move(kpts_tensor)};
    auto vsvig_result = vsvig_session.Run(
        Ort::RunOptions{nullptr},
        vsvig_input_raw.data(),
        vsvig_tensors.data(),
        vsvig_tensors.size(),
        vsvig_output_raw.data(),
        vsvig_output_raw.size()
    );
    float vsvig_prob = vsvig_result.front().GetTensorMutableData<float>()[0];
    std::cout << "VSViG ONNX ran: probability=" << vsvig_prob << "\n";
    return 0;
}

int run_vsvig_openpose_native(const Args& args) {
    if (args.source.empty()) {
        std::cerr << "run requires --source <video>\n";
        return 1;
    }
    const auto pose_onnx = args.repo_root / args.pose_onnx_path;
    const auto vsvig_onnx = args.repo_root / args.vsvig_onnx_path;

    cv::VideoCapture cap(args.source.string());
    if (!cap.isOpened()) {
        std::cerr << "OpenCV could not open source: " << args.source.string() << "\n";
        return 1;
    }
    const double fps = cap.get(cv::CAP_PROP_FPS) > 0.0 ? cap.get(cv::CAP_PROP_FPS) : 30.0;
    const double vsvig_sample_fps = args.vsvig_sample_fps > 0.0 ? args.vsvig_sample_fps : 6.0;
    const int vsvig_sample_step = std::max(1, static_cast<int>(std::round(fps / vsvig_sample_fps)));
    const int inference_stride = std::max(1, args.inference_stride);
    cv::VideoWriter overlay_writer;
    if (!args.output_video.empty()) {
        const int source_w = static_cast<int>(cap.get(cv::CAP_PROP_FRAME_WIDTH));
        const int source_h = static_cast<int>(cap.get(cv::CAP_PROP_FRAME_HEIGHT));
        std::filesystem::create_directories(args.output_video.parent_path());
        overlay_writer.open(
            args.output_video.string(),
            cv::VideoWriter::fourcc('m', 'p', '4', 'v'),
            fps,
            cv::Size(source_w, source_h));
        if (!overlay_writer.isOpened()) {
            std::cerr << "OpenCV could not open output video: " << args.output_video.string() << "\n";
            return 1;
        }
    }

    Ort::Env env(ORT_LOGGING_LEVEL_WARNING, "seizure_runtime_cpp_run");
    Ort::SessionOptions pose_options;
    pose_options.SetGraphOptimizationLevel(GraphOptimizationLevel::ORT_ENABLE_EXTENDED);
    
    OrtCUDAProviderOptions cuda_options{};
    cuda_options.device_id = 0;
    pose_options.AppendExecutionProvider_CUDA(cuda_options);
    
    Ort::SessionOptions vsvig_options;
    vsvig_options.SetGraphOptimizationLevel(GraphOptimizationLevel::ORT_ENABLE_EXTENDED);
    
    OrtTensorRTProviderOptions trt_options{};
    trt_options.device_id = 0;
    trt_options.trt_engine_cache_enable = 1;
    trt_options.trt_engine_cache_path = "runtime_outputs/tensorrt_cache";
    trt_options.trt_fp16_enable = 1;
    //vsvig_options.AppendExecutionProvider_TensorRT(trt_options);
    vsvig_options.AppendExecutionProvider_CUDA(cuda_options);
    
    Ort::AllocatorWithDefaultOptions allocator;
    Ort::MemoryInfo memory = Ort::MemoryInfo::CreateCpu(OrtArenaAllocator, OrtMemTypeDefault);
    std::cerr << "Initializing pose_session...\n";
    Ort::Session pose_session(env, pose_onnx.c_str(), pose_options);
    std::cerr << "Initializing vsvig_session...\n";
    Ort::Session vsvig_session(env, vsvig_onnx.c_str(), vsvig_options);
    std::cerr << "Sessions initialized successfully!\n";
    auto pose_inputs = input_names(pose_session, allocator);
    auto pose_outputs = output_names(pose_session, allocator);
    auto pose_input_raw = raw_names(pose_inputs);
    auto pose_output_raw = raw_names(pose_outputs);
    auto vsvig_inputs = input_names(vsvig_session, allocator);
    auto vsvig_outputs = output_names(vsvig_session, allocator);
    auto vsvig_input_raw = raw_names(vsvig_inputs);
    auto vsvig_output_raw = raw_names(vsvig_outputs);

    if (args.warmup_runs > 0) {
        cv::Mat warmup_frame;
        if (cap.read(warmup_frame)) {
            int pose_w = 0;
            int pose_h = 0;
            auto pose_data = preprocess_openpose_frame(warmup_frame, 256, pose_w, pose_h, args.pose_normalization);
            std::vector<int64_t> pose_shape = {1, 3, pose_h, pose_w};
            std::vector<float> patches(static_cast<std::size_t>(1 * 30 * 15 * 3 * 32 * 32), 0.0f);
            std::vector<float> kpts(static_cast<std::size_t>(1 * 30 * 15 * 3), 0.0f);
            std::vector<int64_t> patches_shape = {1, 30, 15, 3, 32, 32};
            std::vector<int64_t> kpts_shape = {1, 30, 15, 3};

            for (int i = 0; i < args.warmup_runs; ++i) {
                Ort::Value pose_tensor = Ort::Value::CreateTensor<float>(
                    memory, pose_data.data(), pose_data.size(), pose_shape.data(), pose_shape.size());
                (void)pose_session.Run(
                    Ort::RunOptions{nullptr}, pose_input_raw.data(), &pose_tensor, 1,
                    pose_output_raw.data(), pose_output_raw.size());

                Ort::Value patches_tensor = Ort::Value::CreateTensor<float>(
                    memory, patches.data(), patches.size(), patches_shape.data(), patches_shape.size());
                Ort::Value kpts_tensor = Ort::Value::CreateTensor<float>(
                    memory, kpts.data(), kpts.size(), kpts_shape.data(), kpts_shape.size());
                std::array<Ort::Value, 2> tensors = {std::move(patches_tensor), std::move(kpts_tensor)};
                (void)vsvig_session.Run(
                    Ort::RunOptions{nullptr}, vsvig_input_raw.data(), tensors.data(), tensors.size(),
                    vsvig_output_raw.data(), vsvig_output_raw.size());
            }
            cap.set(cv::CAP_PROP_POS_FRAMES, 0);
            std::cerr << "ONNX warm-up complete: " << args.warmup_runs << " iterations\n";
        }
    }

    std::ofstream csv;
    std::ofstream kpt_csv;
    std::ofstream cj_telemetry_csv;
    if (!args.output_csv.empty()) {
        csv.open(args.output_csv);
        csv << "frame,time_sec,status,seizure_signal,seizure_source,current_risk,cj_prob,cj_age_sec,alert_latched\n";

        std::filesystem::path cj_telemetry_path = args.output_csv;
        cj_telemetry_path.replace_filename(cj_telemetry_path.stem().string() + "_cj_telemetry.csv");
        cj_telemetry_csv.open(cj_telemetry_path);
        if (cj_telemetry_csv.is_open()) {
            cj_telemetry_csv << "segment_end_sec,token_build_ms,vivit_ms,onnx_ms,gate_receive_sec,cj_age_sec,cj_prob\n";
        }
        
        std::string kpt_csv_path = args.output_csv.string();
        size_t pos = kpt_csv_path.rfind(".csv");
        if (pos != std::string::npos) {
            kpt_csv_path.replace(pos, 4, "_kpts.csv");
        } else {
            kpt_csv_path += "_kpts.csv";
        }
        kpt_csv.open(kpt_csv_path);
        if (kpt_csv.is_open()) {
            kpt_csv << "frame,time_sec";
            for (int i = 0; i < 15; ++i) {
                kpt_csv << ",kp" << i << "_x,kp" << i << "_y,kp" << i << "_c";
            }
            kpt_csv << "\n";
        }
    }

    // Profiling stats
    double total_pose_ms = 0.0;
    int count_pose = 0;
    double total_vsvig_ms = 0.0;
    int count_vsvig = 0;
    double total_patch_ms = 0.0;
    double total_gate_ms = 0.0;
    int count_gate = 0;
    const auto run_start = std::chrono::steady_clock::now();
    bool display_enabled = args.display;

    struct CjIpcResult {
        std::mutex mtx;
        struct Sample {
            double prob = 0.0;
            double time_sec = 0.0;
            double token_build_ms = 0.0;
            double vivit_ms = 0.0;
            double onnx_ms = 0.0;
        };
        std::deque<Sample> pending;
        std::optional<double> active_prob;
        double active_time_sec = 0.0;
        double total_cj_ms = 0.0;
        int count_cj = 0;
    };
    auto cj_result = std::make_shared<CjIpcResult>();
    auto stop_ipc = std::make_shared<std::atomic<bool>>(false);

    std::thread ipc_thread([args, cj_result, stop_ipc]() {
        const auto cj_head_onnx = args.repo_root / args.cj_head_onnx_path;
        if (!std::filesystem::exists(cj_head_onnx)) return;

        Ort::Env env(ORT_LOGGING_LEVEL_WARNING, "cj_ipc");
        Ort::SessionOptions options;
        options.SetGraphOptimizationLevel(GraphOptimizationLevel::ORT_ENABLE_EXTENDED);
        Ort::AllocatorWithDefaultOptions allocator;
        Ort::MemoryInfo memory = Ort::MemoryInfo::CreateCpu(OrtArenaAllocator, OrtMemTypeDefault);
#ifdef _WIN32
        try {
            Ort::Session session_test(env, cj_head_onnx.wstring().c_str(), options);
        } catch (const std::exception& e) {
            std::cerr << "ONNX IPC Session Exception: " << e.what() << "\n";
            std::exit(1);
        }
        Ort::Session session(env, cj_head_onnx.wstring().c_str(), options);
#else
        Ort::Session session(env, cj_head_onnx.string().c_str(), options);
#endif
        auto input_names_alloc = input_names(session, allocator);
        auto output_names_alloc = output_names(session, allocator);
        auto input_raw = raw_names(input_names_alloc);
        auto output_raw = raw_names(output_names_alloc);

        HANDLE hPipe = CreateNamedPipeA(
            args.pipe_name.c_str(),
            PIPE_ACCESS_INBOUND,
            PIPE_TYPE_MESSAGE | PIPE_READMODE_MESSAGE | PIPE_WAIT,
            1, 65536, 65536, 0, NULL
        );
        if (hPipe == INVALID_HANDLE_VALUE) return;
        
        while (!(*stop_ipc)) {
            BOOL connected = ConnectNamedPipe(hPipe, NULL) ? TRUE : (GetLastError() == ERROR_PIPE_CONNECTED);
            if (connected) {
                while (!(*stop_ipc)) {
                    struct {
                        char magic[4];
                        double time_sec;
                        double token_build_ms;
                        double vivit_ms;
                        float tokens[14 * 768];
                        float pos[14 * 30 * 3];
                    } payload;
                    
                    DWORD bytesRead = 0;
                    BOOL success = ReadFile(hPipe, &payload, sizeof(payload), &bytesRead, NULL);
                    if (!success || bytesRead != sizeof(payload)) break;
                    if (strncmp(payload.magic, "VIVT", 4) != 0) break;
                    
                    std::vector<int64_t> tokens_shape = {1, 14, 768};
                    std::vector<int64_t> pos_shape = {1, 14, 30, 3};
                    Ort::Value tokens_tensor = Ort::Value::CreateTensor<float>(
                        memory, payload.tokens, 14*768, tokens_shape.data(), tokens_shape.size());
                    Ort::Value pos_tensor = Ort::Value::CreateTensor<float>(
                        memory, payload.pos, 14*30*3, pos_shape.data(), pos_shape.size());
                    std::array<Ort::Value, 2> tensors = {std::move(tokens_tensor), std::move(pos_tensor)};
                    
                    auto t0 = std::chrono::high_resolution_clock::now();
                    auto result = session.Run(
                        Ort::RunOptions{nullptr}, input_raw.data(), tensors.data(), tensors.size(),
                        output_raw.data(), output_raw.size()
                    );
                    auto t1 = std::chrono::high_resolution_clock::now();
                    const float prob = result.front().GetTensorMutableData<float>()[0];
                    const double onnx_ms = std::chrono::duration<double, std::milli>(t1 - t0).count();
                    
                    {
                        std::lock_guard<std::mutex> lock(cj_result->mtx);
                        cj_result->pending.push_back({
                            prob,
                            payload.time_sec,
                            payload.token_build_ms,
                            payload.vivit_ms,
                            onnx_ms
                        });
                        cj_result->total_cj_ms += onnx_ms;
                        cj_result->count_cj++;
                    }
                }
                DisconnectNamedPipe(hPipe);
            }
        }
        CloseHandle(hPipe);
    });

    std::deque<std::vector<float>> patch_buf;
    std::deque<std::array<Keypoint, 15>> kpt_buf;

    seizure::SeizureGate gate(seizure::Mode::monitor);

    cv::Mat frame;
    cv::Mat first_frame;
    int frame_idx = 0;
    double current_risk = 0.0;
    std::vector<Keypoint> last_kpts(18);
    while (cap.read(frame)) {
        ++frame_idx;
        const double time_sec = frame_idx / fps;
        if (frame_idx % 100 == 0) { std::cout << "Processing frame " << frame_idx << std::endl; }
        if (args.max_frames > 0 && frame_idx > args.max_frames) {
            break;
        }

        // Throttle file replay so the gate cannot outrun the asynchronous CJ producer.
        if (time_sec > 6.0) {
            while (!(*stop_ipc)) {
                double current_cj_time = 0.0;
                {
                    std::lock_guard<std::mutex> lock(cj_result->mtx);
                    current_cj_time = cj_result->active_time_sec;
                    if (!cj_result->pending.empty()) {
                        current_cj_time = std::max(current_cj_time, cj_result->pending.back().time_sec);
                    }
                }
                if (time_sec - current_cj_time <= args.max_cj_age_sec) break;
                std::this_thread::sleep_for(std::chrono::milliseconds(10));
            }
        }

        const bool run_vsvig_sample = frame_idx % vsvig_sample_step == 0 || patch_buf.empty();
        if (run_vsvig_sample) {
            int pose_w = 0;
            int pose_h = 0;
            auto pose_data = preprocess_openpose_frame(frame, 256, pose_w, pose_h, args.pose_normalization);
            std::vector<int64_t> pose_shape = {1, 3, pose_h, pose_w};
            Ort::Value pose_tensor = Ort::Value::CreateTensor<float>(
                memory, pose_data.data(), pose_data.size(), pose_shape.data(), pose_shape.size());
            auto t0 = std::chrono::high_resolution_clock::now();
            auto pose_result = pose_session.Run(
                Ort::RunOptions{nullptr}, pose_input_raw.data(), &pose_tensor, 1,
                pose_output_raw.data(), pose_output_raw.size());
            auto t1 = std::chrono::high_resolution_clock::now();
            total_pose_ms += std::chrono::duration<double, std::milli>(t1 - t0).count();
            count_pose++;
            
            if (!args.freeze_kpts || frame_idx <= vsvig_sample_step) {
                last_kpts = extract_openpose_keypoints(pose_result, frame.cols, frame.rows, args.min_kpt_conf);
            }
            
            auto reordered_kpts = reorder_kpts_for_vsvig(last_kpts);
            if (kpt_csv.is_open()) {
                kpt_csv << frame_idx << "," << time_sec;
                for (int i = 0; i < 15; ++i) {
                    kpt_csv << "," << reordered_kpts[i].x << "," << reordered_kpts[i].y << "," << reordered_kpts[i].c;
                }
                kpt_csv << "\n";
            }
            
            if (args.freeze_rgb && frame_idx <= vsvig_sample_step) {
                first_frame = frame.clone();
            }
            const cv::Mat& rgb_source = args.freeze_rgb ? first_frame : frame;
            
            patch_buf.push_back(extract_vsvig_patches(rgb_source, last_kpts));
            kpt_buf.push_back(reordered_kpts);
            if (patch_buf.size() > 30) {
                patch_buf.pop_front();
                kpt_buf.pop_front();
            }
        }

        if (frame_idx % inference_stride == 0 && patch_buf.size() == 30 && kpt_buf.size() == 30) {
            auto t0_pack = std::chrono::high_resolution_clock::now();
            std::vector<float> patches(static_cast<std::size_t>(1 * 30 * 15 * 3 * 32 * 32), 0.0f);
            std::vector<float> kpts(static_cast<std::size_t>(1 * 30 * 15 * 3), 0.0f);
            for (int t = 0; t < 30; ++t) {
                const auto& patch = patch_buf[static_cast<std::size_t>(t)];
                for (int p = 0; p < 15; ++p) {
                    for (int y = 0; y < 32; ++y) {
                        for (int x = 0; x < 32; ++x) {
                            for (int c = 0; c < 3; ++c) {
                                const std::size_t src = static_cast<std::size_t>(((p * 32 + y) * 32 + x) * 3 + c);
                                const std::size_t dst = static_cast<std::size_t>((((((t * 15 + p) * 3 + c) * 32 + y) * 32) + x));
                                patches[dst] = patch[src];
                            }
                        }
                    }
                    const auto& kp = kpt_buf[static_cast<std::size_t>(t)][p];
                    const std::size_t base = static_cast<std::size_t>(((t * 15 + p) * 3));
                    kpts[base + 0] = kp.x;
                    kpts[base + 1] = kp.y;
                    kpts[base + 2] = kp.c;
                }
            }
            auto t1_pack = std::chrono::high_resolution_clock::now();
            total_patch_ms += std::chrono::duration<double, std::milli>(t1_pack - t0_pack).count();

            std::vector<int64_t> patches_shape = {1, 30, 15, 3, 32, 32};
            std::vector<int64_t> kpts_shape = {1, 30, 15, 3};
            Ort::Value patches_tensor = Ort::Value::CreateTensor<float>(
                memory, patches.data(), patches.size(), patches_shape.data(), patches_shape.size());
            Ort::Value kpts_tensor = Ort::Value::CreateTensor<float>(
                memory, kpts.data(), kpts.size(), kpts_shape.data(), kpts_shape.size());
            std::array<Ort::Value, 2> tensors = {std::move(patches_tensor), std::move(kpts_tensor)};
            auto t0 = std::chrono::high_resolution_clock::now();
            auto outputs = vsvig_session.Run(
                Ort::RunOptions{nullptr}, vsvig_input_raw.data(), tensors.data(), tensors.size(),
                vsvig_output_raw.data(), vsvig_output_raw.size());
            auto t1 = std::chrono::high_resolution_clock::now();
            total_vsvig_ms += std::chrono::duration<double, std::milli>(t1 - t0).count();
            count_vsvig++;
            double logit = static_cast<double>(outputs.front().GetTensorMutableData<float>()[0]);
            current_risk = sigmoid(logit);
        }


        std::optional<double> cj_prob;
        std::optional<double> cj_age_sec;
        std::vector<CjIpcResult::Sample> activated_cj_samples;
        {
            std::lock_guard<std::mutex> lock(cj_result->mtx);
            constexpr double CJ_FUTURE_TOLERANCE_SEC = 1e-6;
            while (!cj_result->pending.empty() &&
                   cj_result->pending.front().time_sec <= time_sec + CJ_FUTURE_TOLERANCE_SEC) {
                const auto sample = cj_result->pending.front();
                cj_result->pending.pop_front();
                cj_result->active_prob = sample.prob;
                cj_result->active_time_sec = sample.time_sec;
                activated_cj_samples.push_back(sample);
            }
            cj_prob = cj_result->active_prob;
            if (cj_result->active_time_sec > 0.0) {
                cj_age_sec = time_sec - cj_result->active_time_sec;
            }
        }
        if (cj_telemetry_csv.is_open()) {
            for (const auto& sample : activated_cj_samples) {
                const double age_sec = time_sec - sample.time_sec;
                cj_telemetry_csv
                    << sample.time_sec << ","
                    << sample.token_build_ms << ","
                    << sample.vivit_ms << ","
                    << sample.onnx_ms << ","
                    << time_sec << ","
                    << age_sec << ","
                    << sample.prob << "\n";
            }
        }

        auto t0_gate = std::chrono::high_resolution_clock::now();
        seizure::FrameResult result = gate.decide_from_signals(
            frame_idx,
            time_sec,
            current_risk,
            cj_prob,
            cj_age_sec
        );
        auto t1_gate = std::chrono::high_resolution_clock::now();
        total_gate_ms += std::chrono::duration<double, std::milli>(t1_gate - t0_gate).count();
        count_gate++;
        if (csv.is_open()) {
            csv << frame_idx << "," << time_sec << "," << seizure::status_str(result.status) << ","
                << result.seizure_signal << "," << result.seizure_source << ","
                << current_risk << ","
                << (cj_prob ? std::to_string(*cj_prob) : "") << "," 
                << (cj_age_sec ? std::to_string(*cj_age_sec) : "") << ","
                << (result.alert_latched ? 1 : 0) << "\n";
        }

        if (display_enabled || overlay_writer.isOpened()) {
            cv::Mat view = frame.clone();
            const bool is_seizure = result.status == seizure::Status::seizure;
            const cv::Scalar status_color =
                is_seizure ? cv::Scalar(0, 0, 255) :
                result.status == seizure::Status::initialising ? cv::Scalar(0, 215, 255) :
                cv::Scalar(0, 200, 0);
            cv::rectangle(view, cv::Rect(0, 0, std::min(view.cols, 560), 146), cv::Scalar(0, 0, 0), cv::FILLED);
            cv::putText(view, "Clinical mode: MONITOR",
                        cv::Point(16, 32), cv::FONT_HERSHEY_SIMPLEX, 0.75, cv::Scalar(255, 255, 255), 2, cv::LINE_AA);
            cv::putText(view, "Gate score: " + std::to_string(result.seizure_signal).substr(0, 6),
                        cv::Point(16, 66), cv::FONT_HERSHEY_SIMPLEX, 0.75, cv::Scalar(255, 255, 255), 2, cv::LINE_AA);
            cv::putText(view, "Source: " + result.seizure_source,
                        cv::Point(16, 100), cv::FONT_HERSHEY_SIMPLEX, 0.75, cv::Scalar(255, 255, 255), 2, cv::LINE_AA);
            cv::putText(view, "Seizure: " + std::string(is_seizure ? "YES" : "NO"),
                        cv::Point(16, 134), cv::FONT_HERSHEY_SIMPLEX, 0.75, status_color, 2, cv::LINE_AA);
            if (overlay_writer.isOpened()) {
                overlay_writer.write(view);
            }
            if (display_enabled) {
                cv::imshow("Seizure Detection Live Inference", view);
                const int key = cv::waitKey(1);
                if (key == 27 || key == 'q' || key == 'Q') {
                    display_enabled = false;
                    cv::destroyWindow("Seizure Detection Live Inference");
                }
            }
        }
    }
    if (overlay_writer.isOpened()) {
        overlay_writer.release();
    }
    *stop_ipc = true;
    // We don't join ipc_thread here safely if it's blocked in ConnectNamedPipe, so we detach.
    ipc_thread.detach();
    std::cout << "Native OpenPose+VSViG run complete: frames=" << frame_idx
              << " csv=" << (args.output_csv.empty() ? "(off)" : args.output_csv.string()) << "\n";
    std::cout << "--- PROFILING C++ ---\n";
    const auto run_end = std::chrono::steady_clock::now();
    const double elapsed_sec = std::chrono::duration<double>(run_end - run_start).count();
    std::cout << "Steady elapsed wall time: " << elapsed_sec << " sec\n";
    std::cout << "Steady-state Processing FPS: " << (elapsed_sec > 0.0 ? frame_idx / elapsed_sec : 0.0) << "\n";
    std::cout << "OpenPose mean: " << (count_pose > 0 ? total_pose_ms / count_pose : 0.0) << " ms\n";
    std::cout << "VSViG Patch mean: " << (count_vsvig > 0 ? total_patch_ms / count_vsvig : 0.0) << " ms\n";
    std::cout << "VSViG TRT mean: " << (count_vsvig > 0 ? total_vsvig_ms / count_vsvig : 0.0) << " ms\n";
    
    double final_cj_ms = 0;
    int final_cj_count = 0;
    {
        std::lock_guard<std::mutex> lock(cj_result->mtx);
        final_cj_ms = cj_result->total_cj_ms;
        final_cj_count = cj_result->count_cj;
    }
    std::cout << "CJ Head mean: " << (final_cj_count > 0 ? final_cj_ms / final_cj_count : 0.0) << " ms\n";
    std::cout << "Gate mean: " << (count_gate > 0 ? total_gate_ms / count_gate : 0.0) << " ms\n";
    if (display_enabled) {
        cv::destroyWindow("Seizure Detection Live Inference");
    }
    
    if (!std::filesystem::exists(args.repo_root / args.cj_head_onnx_path)) {
        std::cout << "CJ native inference: unavailable until " << (args.repo_root / args.cj_head_onnx_path).string() << " exists.\n";
    }
    return 0;
}

int smoke_cj_head_native(const Args& args) {
    const auto cj_head_onnx = args.repo_root / args.cj_head_onnx_path;
    if (!std::filesystem::exists(cj_head_onnx)) {
        std::cerr << "missing CJ head ONNX: " << cj_head_onnx.string() << "\n";
        return 1;
    }

    Ort::Env env(ORT_LOGGING_LEVEL_WARNING, "seizure_runtime_cpp_cj_head");
    Ort::SessionOptions options;
    options.SetGraphOptimizationLevel(GraphOptimizationLevel::ORT_ENABLE_EXTENDED);
    Ort::AllocatorWithDefaultOptions allocator;
    Ort::MemoryInfo memory = Ort::MemoryInfo::CreateCpu(OrtArenaAllocator, OrtMemTypeDefault);
    Ort::Session session(env, cj_head_onnx.c_str(), options);
    auto inputs = input_names(session, allocator);
    auto outputs = output_names(session, allocator);
    auto input_raw = raw_names(inputs);
    auto output_raw = raw_names(outputs);

    std::vector<float> tokens(static_cast<std::size_t>(1 * 14 * 768), 0.01f);
    std::vector<float> pos(static_cast<std::size_t>(1 * 14 * 30 * 3), 0.0f);
    for (int j = 0; j < 14; ++j) {
        for (int t = 0; t < 30; ++t) {
            const std::size_t base = static_cast<std::size_t>(((j * 30 + t) * 3));
            pos[base + 0] = static_cast<float>(j * 10);
            pos[base + 1] = static_cast<float>(t * 2);
            pos[base + 2] = static_cast<float>(j);
        }
    }
    std::vector<int64_t> tokens_shape = {1, 14, 768};
    std::vector<int64_t> pos_shape = {1, 14, 30, 3};
    Ort::Value tokens_tensor = Ort::Value::CreateTensor<float>(
        memory, tokens.data(), tokens.size(), tokens_shape.data(), tokens_shape.size());
    Ort::Value pos_tensor = Ort::Value::CreateTensor<float>(
        memory, pos.data(), pos.size(), pos_shape.data(), pos_shape.size());
    std::array<Ort::Value, 2> tensors = {std::move(tokens_tensor), std::move(pos_tensor)};
    auto result = session.Run(
        Ort::RunOptions{nullptr},
        input_raw.data(),
        tensors.data(),
        tensors.size(),
        output_raw.data(),
        output_raw.size()
    );
    const float prob = result.front().GetTensorMutableData<float>()[0];
    std::cout << "CJ head ONNX ran: probability=" << prob << "\n";
    std::cout << "Note: this is head-only native inference; ViViT token extraction is still external.\n";
    return 0;
}

}  // namespace

int main(int argc, char** argv) {
    const Args args = parse_args(argc, argv);

    if (args.command == "help" || args.command == "--help" || args.command == "-h") {
        print_help(argc > 0 ? argv[0] : "seizure_runtime_cpp");
        return 0;
    }

    if (args.command == "check") {
        return 0;
    }

    if (args.command == "run") {
        return run_vsvig_openpose_native(args);
    }

    if (args.command == "smoke") {
        return smoke_native_runtime(args);
    }

    if (args.command == "cj-head-smoke") {
        return smoke_cj_head_native(args);
    }

    print_help(argc > 0 ? argv[0] : "seizure_runtime_cpp");
    return 1;
}
