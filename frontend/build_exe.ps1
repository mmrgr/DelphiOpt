$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$PyInstaller = "D:\各种软件\新建文件夹\Scripts\pyinstaller.exe"
$BuildPython = "D:\各种软件\新建文件夹\python.exe"

if (-not (Test-Path -LiteralPath $PyInstaller)) {
    $PyInstaller = (Get-Command pyinstaller -ErrorAction Stop).Source
}
if (Test-Path -LiteralPath $BuildPython) {
    & $BuildPython (Join-Path $PSScriptRoot "make_icon.py")
} else {
    python (Join-Path $PSScriptRoot "make_icon.py")
}

$Icon = Join-Path $PSScriptRoot "assets\delphiopt.ico"
$Dist = Join-Path $Root "dist"
$Build = Join-Path $Root "build\desktop"
$Spec = Join-Path $Root "build"
$Data = @(
    "--add-data", "$Root\examples;examples",
    "--add-data", "$Root\configs;configs",
    "--add-data", "$Root\docs;docs",
    "--add-data", "$Root\analysis;analysis",
    "--add-data", "$Root\README.md;."
)
$Arguments = @(
    "--noconfirm", "--clean", "--onefile", "--windowed", "--name", "DelphiOpt",
    "--icon", $Icon, "--paths", (Join-Path $Root "src"), "--paths", $Root,
    "--distpath", $Dist, "--workpath", $Build, "--specpath", $Spec
) + $Data + (Join-Path $PSScriptRoot "delphiopt_desktop.py")

& $PyInstaller @Arguments
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed with exit code $LASTEXITCODE"
}
Write-Output (Join-Path $Dist "DelphiOpt.exe")
