# Сборка исполняемого приложения (Windows). Требуется: pip install -r requirements-dev.txt
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

Write-Host "Каталог проекта: $root"

pyinstaller --noconfirm --clean `
    --name "AudioVisualization" `
    --onedir `
    --windowed `
    "main.py" `
    --add-data "resources/styles_classic.qss;resources" `
    --add-data "resources/styles_glass.qss;resources" `
    --collect-all PyQt6 `
    --hidden-import soundcard `
    --hidden-import soundcard.mediafoundation `
    --hidden-import ui.image_import_edit_dialog `
    --hidden-import app.paths

Write-Host ""
Write-Host "Готово. Запуск: dist\AudioVisualization\AudioVisualization.exe"
