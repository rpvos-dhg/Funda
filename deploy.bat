@echo off
REM Deploy de pwa/ folder naar GitHub Pages.
REM Gebruik: na funda_zoek.py, of in Task Scheduler als 2e action.

cd /d "C:\Users\remco\OneDrive\Documents\Claude\Projects\Financien"

git add pwa/
git diff --cached --quiet
if %errorlevel% equ 0 (
    echo Geen wijzigingen om te pushen.
    exit /b 0
)

git commit -m "auto: rapport %DATE% %TIME%"
git push

echo [%DATE% %TIME%] Pushed pwa/ naar GitHub.
