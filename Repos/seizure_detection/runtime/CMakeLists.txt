cmake_minimum_required(VERSION 3.16)
project(seizure_gate_deploy CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

set(SEIZURE_ROOT "${CMAKE_CURRENT_LIST_DIR}/..")
set(SEIZURE_THIRD_PARTY "${SEIZURE_ROOT}/third_party")
set(ORT_ROOT "${SEIZURE_THIRD_PARTY}/onnxruntime")
set(VCPKG_X64 "${SEIZURE_THIRD_PARTY}/vcpkg_installed/x64-windows")

# ---------------------------------------------------------------------------
# Release by default when building from command line without -DCMAKE_BUILD_TYPE
# ---------------------------------------------------------------------------
if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE Release CACHE STRING "Build type" FORCE)
endif()

# ---------------------------------------------------------------------------
# Compiler flags
# ---------------------------------------------------------------------------
if(MSVC)
  add_compile_options(/W4 /WX /utf-8)
else()
  add_compile_options(-Wall -Wextra -O2)
endif()

# ---------------------------------------------------------------------------
# Main executable
# ---------------------------------------------------------------------------
add_executable(seizure_gate_replay
    src/main.cpp
)

target_include_directories(seizure_gate_replay PRIVATE include)

add_executable(seizure_runtime_cpp
    src/full_runtime.cpp
)

target_include_directories(seizure_runtime_cpp PRIVATE
    include
    "${ORT_ROOT}/include"
    "${VCPKG_X64}/include/opencv4"
)

target_link_libraries(seizure_runtime_cpp PRIVATE
    "${ORT_ROOT}/lib/onnxruntime.lib"
    "${VCPKG_X64}/lib/opencv_core4.lib"
    "${VCPKG_X64}/lib/opencv_imgproc4.lib"
    "${VCPKG_X64}/lib/opencv_imgcodecs4.lib"
    "${VCPKG_X64}/lib/opencv_videoio4.lib"
    "${VCPKG_X64}/lib/opencv_highgui4.lib"
)

target_compile_definitions(seizure_runtime_cpp PRIVATE SEIZURE_NATIVE_DEPS=1)

add_custom_command(TARGET seizure_runtime_cpp POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E copy_if_different
        "${ORT_ROOT}/lib/onnxruntime.dll"
        "$<TARGET_FILE_DIR:seizure_runtime_cpp>/onnxruntime.dll"
    COMMAND ${CMAKE_COMMAND} -E copy_if_different
        "${ORT_ROOT}/lib/onnxruntime_providers_shared.dll"
        "$<TARGET_FILE_DIR:seizure_runtime_cpp>/onnxruntime_providers_shared.dll"
    COMMAND ${CMAKE_COMMAND} -E copy_if_different
        "${ORT_ROOT}/lib/onnxruntime_providers_cuda.dll"
        "$<TARGET_FILE_DIR:seizure_runtime_cpp>/onnxruntime_providers_cuda.dll"
    COMMAND ${CMAKE_COMMAND} -E copy_if_different
        "${ORT_ROOT}/lib/onnxruntime_providers_tensorrt.dll"
        "$<TARGET_FILE_DIR:seizure_runtime_cpp>/onnxruntime_providers_tensorrt.dll"
    COMMAND ${CMAKE_COMMAND} -E copy_directory
        "${VCPKG_X64}/bin"
        "$<TARGET_FILE_DIR:seizure_runtime_cpp>"
)

# ---------------------------------------------------------------------------
# Install target (optional — copies to build/bin)
# ---------------------------------------------------------------------------
install(TARGETS seizure_gate_replay seizure_runtime_cpp DESTINATION bin)

# ---------------------------------------------------------------------------
# CTest integration — wraps 'test' subcommand
# ---------------------------------------------------------------------------
enable_testing()
add_test(NAME unit_tests COMMAND seizure_gate_replay test)
