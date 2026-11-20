@echo off
REM Builds "Smash Night.exe" - the in-process host for smash_night.py (see
REM launcher.py / build_exe.py). It needs smash_night.py, setup.bat and .venv
REM next to it; it runs setup.bat itself when .venv is missing.
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" call setup.bat
".venv\Scripts\python.exe" build_exe.py
if errorlevel 1 (echo Build failed. & exit /b 1)
