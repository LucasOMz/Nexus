@echo off
REM reset.bat — zera os dados do sistema (banco + fotos + anexos).
REM Chama o reset.ps1 contornando a politica de execucao de scripts.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0reset.ps1" %*
echo.
pause
