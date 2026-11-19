@echo off
cd /d "%~dp0"
if not exist "node_modules" (
    echo Dependencias do Node ausentes. Execute npm install primeiro.
    pause
    exit /b 1
)
npm run dev
