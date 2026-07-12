$ErrorActionPreference = "Stop"

$root = [IO.Path]::GetFullPath((Split-Path -Parent $MyInvocation.MyCommand.Path))
$venv = Join-Path $root ".venv"
$python = Join-Path $venv "Scripts\python.exe"
$pipTemp = Join-Path $root ".pip-tmp"

function Assert-PlainChild([string]$path) {
    $full = [IO.Path]::GetFullPath($path)
    $prefix = $root.TrimEnd([IO.Path]::DirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
    if (-not $full.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Path escapes benchmark root: $full"
    }
    $current = $full
    while ($true) {
        if (Test-Path -LiteralPath $current) {
            $item = Get-Item -LiteralPath $current -Force
            if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw "Reparse points are not allowed: $current"
            }
        }
        if ([String]::Equals($current, $root, [StringComparison]::OrdinalIgnoreCase)) { break }
        $current = Split-Path -Parent $current
    }
}

function Assert-NoReparseTree([string]$path) {
    if (-not (Test-Path -LiteralPath $path)) { return }
    $pending = New-Object 'System.Collections.Generic.Stack[string]'
    $pending.Push([IO.Path]::GetFullPath($path))
    while ($pending.Count -gt 0) {
        $directory = $pending.Pop()
        foreach ($child in Get-ChildItem -LiteralPath $directory -Force) {
            if (($child.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw "Reparse points are not allowed: $($child.FullName)"
            }
            if ($child.PSIsContainer) { $pending.Push($child.FullName) }
        }
    }
}

Assert-PlainChild $venv
Assert-PlainChild $pipTemp

if (Test-Path -LiteralPath $pipTemp) {
    Remove-Item -LiteralPath $pipTemp -Recurse -Force
}
New-Item -ItemType Directory -Path $pipTemp | Out-Null
$oldTemp = $env:TEMP
$oldTmp = $env:TMP
try {
    $env:TEMP = $pipTemp
    $env:TMP = $pipTemp
    if (-not (Test-Path -LiteralPath $python)) {
        Get-Command py -ErrorAction Stop | Out-Null
        & py -3.13 -m venv $venv
        if ($LASTEXITCODE -ne 0) { throw "Python venv creation failed with exit code $LASTEXITCODE" }
    }
    Assert-PlainChild $python
    Assert-NoReparseTree $venv
    & $python -m pip --isolated install --no-cache-dir --quiet --disable-pip-version-check -r (Join-Path $root "requirements.lock.txt")
    if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed with exit code $LASTEXITCODE" }
}
finally {
    $env:TEMP = $oldTemp
    $env:TMP = $oldTmp
    if (Test-Path -LiteralPath $pipTemp) {
        Remove-Item -LiteralPath $pipTemp -Recurse -Force
    }
}

$env:PYTHONHASHSEED = "0"
$env:OMP_NUM_THREADS = "1"
$env:OPENBLAS_NUM_THREADS = "1"
$env:MKL_NUM_THREADS = "1"
$env:NUMEXPR_NUM_THREADS = "1"

& $python (Join-Path $root "benchmark.py")
exit $LASTEXITCODE
