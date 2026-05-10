# packaging/build_release.ps1 — Windows
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
pip install -e "..[dev]"
pyinstaller --clean -y nettest.spec
Write-Host "Built dist\nettest.exe"
