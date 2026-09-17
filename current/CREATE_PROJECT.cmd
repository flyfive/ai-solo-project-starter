@echo off
setlocal
chcp 65001 >nul
set "SCRIPT_DIR=%~dp0"
py -3 -c "import sys; assert sys.version_info >= (3,11)" >nul 2>nul
if %errorlevel%==0 (
  set "PYTHON_CMD=py -3"
  goto :run
)
python3 -c "import sys; assert sys.version_info >= (3,11)" >nul 2>nul
if %errorlevel%==0 (
  set "PYTHON_CMD=python3"
  goto :run
)
python -c "import sys; assert sys.version_info >= (3,11)" >nul 2>nul
if %errorlevel%==0 (
  set "PYTHON_CMD=python"
  goto :run
)
echo ERROR: Python 3.11 or newer was not found.
exit /b 2
:run
%PYTHON_CMD% "%SCRIPT_DIR%starter.py" init
set "EXIT_CODE=%errorlevel%"
:done
pause
exit /b %EXIT_CODE%
