@echo off
chcp 949 >nul
title Cross-Check AI Server
cd /d "%~dp0"

set USE_TF=0
set USE_FLAX=0
set KMP_DUPLICATE_LIB_OK=TRUE
set OMP_NUM_THREADS=1
set PYTHONIOENCODING=utf-8
set LLM_TIMEOUT_SEC=5
set MAX_LLM_NODES_PER_TREE=1
set PRELOAD_EMBEDDING=0
set OCR_ENGINE=auto
set EASY_OCR_LANGS=ko,en
set EASY_OCR_GPU=0

echo.
echo ============================================================
echo   Cross-Check AI  FastAPI Server
echo   URL : http://127.0.0.1:8000
echo   STOP: Ctrl+C
echo ============================================================
echo.

for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8000 " ^| findstr "LISTENING"') do (
    echo [INFO] Killing existing process on port 8000 ^(PID %%a^)...
    taskkill /F /PID %%a >nul 2>^&1
)

echo [INFO] Starting uvicorn...
"C:\ProgramData\Anaconda3\python.exe" -B -m uvicorn api.server:app --host 127.0.0.1 --port 8000

echo.
echo [INFO] Server stopped. Press any key to close.
pause >nul
