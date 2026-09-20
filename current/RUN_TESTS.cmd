@echo off
setlocal
set "SCRIPT_DIR=%~dp0"
set "PYTHONDONTWRITEBYTECODE=1"

py -3 -c "import sys; assert sys.version_info >= (3,11)" >nul 2>nul
if not errorlevel 1 goto :run_py

python3 -c "import sys; assert sys.version_info >= (3,11)" >nul 2>nul
if not errorlevel 1 goto :run_python3

python -c "import sys; assert sys.version_info >= (3,11)" >nul 2>nul
if not errorlevel 1 goto :run_python

echo ERROR: Python 3.11 or newer was not found. 1>&2
exit /b 2

:run_py
py -3 -B "%SCRIPT_DIR%run_tests.py" %*
exit /b %errorlevel%

:run_python3
python3 -B "%SCRIPT_DIR%run_tests.py" %*
exit /b %errorlevel%

:run_python
python -B "%SCRIPT_DIR%run_tests.py" %*
exit /b %errorlevel%
