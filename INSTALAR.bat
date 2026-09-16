@echo off
cd /d "%~dp0"

echo Preparando o CortaVideo...
echo.

where py >nul 2>nul
if errorlevel 1 (
    echo Python nao foi encontrado neste computador.
    echo Instale o Python e depois execute este arquivo novamente.
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    py -m venv .venv
)

.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install imageio-ffmpeg
winget install --id Gyan.FFmpeg -e --accept-package-agreements --accept-source-agreements

echo.
echo Instalacao concluida!
echo Agora use o arquivo ABRIR CORTAVIDEO.bat
pause