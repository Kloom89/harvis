@echo off
cd /d "%~dp0"
REM python CON consola (el claude-agent-sdk no spawnea bajo pythonw:
REM WinError 50) pero kloom.py la ESCONDE al arrancar si el HUD esta activo.
REM /min minimiza el flash del primer segundo.
start "KLOOM OS" /min ".venv\Scripts\python.exe" kloom.py %*
