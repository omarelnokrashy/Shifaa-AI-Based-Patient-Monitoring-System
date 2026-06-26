@echo off
setlocal

set "VSDEV=C:\Program Files\Microsoft Visual Studio\2022\Community\Common7\Tools\VsDevCmd.bat"
set "CMAKE=C:\Program Files\Microsoft Visual Studio\2022\Community\Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe"

if not exist "%VSDEV%" (
  echo Visual Studio developer command prompt not found: %VSDEV%
  exit /b 1
)

if not exist "%CMAKE%" (
  echo CMake not found: %CMAKE%
  exit /b 1
)

call "%VSDEV%" -arch=x64
if errorlevel 1 exit /b %errorlevel%

"%CMAKE%" -S "%~dp0." -B "%~dp0build" -G Ninja -DCMAKE_BUILD_TYPE=Release
if errorlevel 1 exit /b %errorlevel%

"%CMAKE%" --build "%~dp0build" --config Release
if errorlevel 1 exit /b %errorlevel%

"%~dp0build\seizure_gate_replay.exe" test
if errorlevel 1 exit /b %errorlevel%

"%CMAKE%" --build "%~dp0build" --target test
if errorlevel 1 exit /b %errorlevel%

"%~dp0build\seizure_gate_replay.exe" bench
if errorlevel 1 exit /b %errorlevel%
