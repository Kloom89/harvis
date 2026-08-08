@echo off
cd /d "%~dp0"
REM Sin este guard, un clone recien bajado abre una ventana que se cierra
REM sola (start /min) y el usuario no ve ningun error.
if not exist ".venv\Scripts\python.exe" (
  echo No virtualenv found. Set it up first:
  echo.
  echo     python -m venv .venv
  echo     .venv\Scripts\pip install -r requirements.txt
  echo     .venv\Scripts\python.exe doctor.py
  echo.
  pause
  exit /b 1
)
REM python CON consola (el claude-agent-sdk no spawnea bajo pythonw:
REM WinError 50) pero kloom.py la ESCONDE al arrancar si el HUD esta activo.
REM /min minimiza el flash del primer segundo.
start "KLOOM OS" /min ".venv\Scripts\python.exe" kloom.py %*
