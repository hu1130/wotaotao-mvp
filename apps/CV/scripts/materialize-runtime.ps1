param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("server", "client")]
    [string]$Role,

    [Parameter(Mandatory = $true)]
    [string]$Destination,

    [switch]$Force,
    [switch]$IncludeEnvironment
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$SharedRoot = Join-Path $RepoRoot "shared_runtime"
$RoleDirectory = if ($Role -eq "server") { "server_deploy" } else { "client_deploy" }
$RoleRoot = Join-Path $RepoRoot $RoleDirectory
$DestinationRoot = [System.IO.Path]::GetFullPath($Destination)

function Write-MaterializeLog([string]$Message) {
    Write-Host "[materialize-runtime] $Message" -ForegroundColor Cyan
}

function Assert-SafeDestination([string]$Path) {
    $protected = @(
        [System.IO.Path]::GetFullPath($RepoRoot),
        [System.IO.Path]::GetFullPath($SharedRoot),
        [System.IO.Path]::GetFullPath($RoleRoot)
    )
    $root = [System.IO.Path]::GetPathRoot($Path)
    if ($Path -eq $root) {
        throw "Refusing to materialize into a filesystem root: $Path"
    }
    foreach ($item in $protected) {
        if ($Path.Equals($item, [System.StringComparison]::OrdinalIgnoreCase)) {
            throw "Refusing to overwrite source directory: $Path"
        }
        $prefix = $Path.TrimEnd('\') + '\'
        if ($item.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)) {
            throw "Refusing to use a destination that contains source directory: $Path"
        }
    }
}

function Test-ExcludedPath([string]$RelativePath) {
    $normalized = $RelativePath.Replace('\', '/')
    if ($normalized.StartsWith("core/gesture/data/", [System.StringComparison]::OrdinalIgnoreCase)) {
        return $true
    }
    $segments = $RelativePath -split '[\\/]'
    $excludedDirectories = @(
        ".git",
        ".venv",
        "__pycache__",
        "cache",
        "logs",
        "node_modules",
        "employees",
        "knowledge_base",
        "unknown_visitors"
    )
    foreach ($segment in $segments) {
        if ($excludedDirectories -contains $segment) {
            return $true
        }
    }
    $leaf = $segments[-1]
    if ($leaf -match '\.py[co]$' -or $leaf -match '\.(log|tmp|pid)$') {
        return $true
    }
    if (-not $IncludeEnvironment -and $leaf -match '^\.env(\.|$)' -and $leaf -notmatch '\.example$') {
        return $true
    }
    return $false
}

function Copy-Layer([string]$SourceRoot, [string]$TargetRoot, [string]$LayerName) {
    $copied = 0
    Get-ChildItem -LiteralPath $SourceRoot -File -Recurse -Force | ForEach-Object {
        $relative = $_.FullName.Substring($SourceRoot.Length).TrimStart('\')
        if (Test-ExcludedPath $relative) {
            return
        }
        $target = Join-Path $TargetRoot $relative
        $targetParent = Split-Path -Parent $target
        New-Item -ItemType Directory -Force -Path $targetParent | Out-Null
        Copy-Item -LiteralPath $_.FullName -Destination $target -Force
        $copied++
    }
    Write-MaterializeLog "$LayerName layer copied: $copied files"
}

Assert-SafeDestination $DestinationRoot
if (Test-Path -LiteralPath $DestinationRoot) {
    if (-not $Force) {
        throw "Destination already exists; pass -Force to replace it: $DestinationRoot"
    }
    Write-MaterializeLog "Removing verified destination: $DestinationRoot"
    Remove-Item -LiteralPath $DestinationRoot -Recurse -Force
}

New-Item -ItemType Directory -Force -Path $DestinationRoot | Out-Null
Write-MaterializeLog "Role=$Role destination=$DestinationRoot"
if ($Role -eq "server") {
    $sharedDestination = Join-Path $DestinationRoot "shared_runtime"
    $roleDestination = Join-Path $DestinationRoot "server_deploy"
    New-Item -ItemType Directory -Force -Path $sharedDestination, $roleDestination | Out-Null
    Copy-Layer $SharedRoot $sharedDestination "shared"
    Copy-Layer $RoleRoot $roleDestination $Role
} else {
    Copy-Layer $SharedRoot $DestinationRoot "shared"
    Copy-Layer $RoleRoot $DestinationRoot $Role
}
Write-MaterializeLog "Runtime materialized successfully: $DestinationRoot"
