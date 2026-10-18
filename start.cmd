@echo off
setlocal
cd /d "%~dp0"

if not exist "dist\Sts2Copilot\Sts2Copilot.exe" (
  echo [StS2 Copilot] dist\Sts2Copilot\Sts2Copilot.exe not found.
  echo Publish first:
  echo   tools\dotnet\dotnet.exe publish src\Sts2Copilot.App\Sts2Copilot.App.csproj -c Release -r win-x64 --self-contained true -o dist\Sts2Copilot
  pause
  exit /b 1
)

start "" "dist\Sts2Copilot\Sts2Copilot.exe"
