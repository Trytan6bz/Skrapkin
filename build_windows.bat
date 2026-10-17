@echo off
REM Builds dist\LeadScraper.exe. Run this on a Windows PC with Python 3.10+ installed (python.org).
setlocal
cd /d "%~dp0"

python -m venv .venv-win || goto :fail
call .venv-win\Scripts\activate.bat || goto :fail
python -m pip install --upgrade pip || goto :fail
python -m pip install -r requirements.txt pyinstaller || goto :fail

pyinstaller --noconfirm --clean --onefile --windowed --name LeadScraper ^
  --collect-all phonenumbers --collect-submodules dns ^
  run_gui.py || goto :fail

echo.
echo Done. Your program is at: %~dp0dist\LeadScraper.exe
exit /b 0

:fail
echo.
echo Build failed. See the messages above.
exit /b 1
