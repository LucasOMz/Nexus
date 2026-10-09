@echo off
REM run.bat — sobe o sistema com um duplo-clique (Windows).
REM Chama o run.ps1 contornando a politica de execucao de scripts.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run.ps1" %*
echo.
echo Servidor encerrado.
pause
