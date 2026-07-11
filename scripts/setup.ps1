[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Repo = Split-Path -Parent $PSScriptRoot
$HomeDir = if ($env:INFO_COLLECTOR_HOME) {
    [System.IO.Path]::GetFullPath($env:INFO_COLLECTOR_HOME)
}
else {
    [Environment]::GetFolderPath("UserProfile")
}
$Spool = Join-Path $HomeDir ".info-collector"
$BinDir = Join-Path $Spool "bin"
$NativeHostDir = Join-Path $Spool "native-host"
$FlowBin = Join-Path $BinDir "translate-flow.py"
$HostBin = Join-Path $BinDir "info-collector-host.py"
$CompatBin = Join-Path $BinDir "info_collector_platform.py"
$ConfigPath = Join-Path $Spool "config.json"
$FlowsPath = Join-Path $Spool "flows.json"
$HostName = "com.pi.info_collector"
$ExtensionId = "fmdbamjmoabmcggjfgeopaijnbjkjbhm"


function Write-Utf8NoBom {
    param([string]$Path, [string]$Content)
    $encoding = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, $Content, $encoding)
}


function Read-JsonMap {
    param([string]$Path)
    $map = @{}
    if (-not (Test-Path -LiteralPath $Path)) {
        return $map
    }
    try {
        $obj = Get-Content -Raw -Encoding UTF8 -LiteralPath $Path | ConvertFrom-Json
        foreach ($prop in $obj.PSObject.Properties) {
            $map[$prop.Name] = $prop.Value
        }
    }
    catch {
        Write-Warning ("无法读取 {0}，将使用新配置：{1}" -f $Path, $_.Exception.Message)
    }
    return $map
}


function Test-PythonCandidate {
    param(
        [string]$Command,
        [string[]]$PrefixArgs = @()
    )
    try {
        $lines = @(& $Command @PrefixArgs -c 'import sys; print(sys.executable)' 2>$null)
        if ($LASTEXITCODE -ne 0 -or $lines.Count -eq 0) {
            return $null
        }
        $resolved = [string]$lines[-1]
        if (-not (Test-Path -LiteralPath $resolved)) {
            return $null
        }
        & $resolved -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)' 2>$null
        if ($LASTEXITCODE -ne 0) {
            return $null
        }
        return (Resolve-Path -LiteralPath $resolved).Path
    }
    catch {
        return $null
    }
}


function Resolve-PythonExecutable {
    if ($env:INFO_COLLECTOR_PYTHON) {
        $found = Test-PythonCandidate -Command $env:INFO_COLLECTOR_PYTHON
        if ($found) { return $found }
        throw "INFO_COLLECTOR_PYTHON 指向的 Python 不可用：$($env:INFO_COLLECTOR_PYTHON)"
    }

    $launchers = @(
        @{ Command = "py"; Args = @("-3") },
        @{ Command = "python"; Args = @() },
        @{ Command = "python3"; Args = @() }
    )
    foreach ($item in $launchers) {
        $cmd = Get-Command $item.Command -ErrorAction SilentlyContinue
        if ($cmd) {
            $found = Test-PythonCandidate -Command $cmd.Source -PrefixArgs $item.Args
            if ($found) { return $found }
        }
    }

    $patterns = @()
    if ($env:LOCALAPPDATA) {
        $patterns += Join-Path $env:LOCALAPPDATA "Programs\Python\Python*\python.exe"
    }
    if ($env:ProgramFiles) {
        $patterns += Join-Path $env:ProgramFiles "Python*\python.exe"
    }
    foreach ($pattern in $patterns) {
        foreach ($candidate in Get-ChildItem -Path $pattern -File -ErrorAction SilentlyContinue) {
            $found = Test-PythonCandidate -Command $candidate.FullName
            if ($found) { return $found }
        }
    }

    throw "未找到 Python 3.9+。请安装 Python 3，并勾选 Add Python to PATH；或设置 INFO_COLLECTOR_PYTHON 为 python.exe 的绝对路径。"
}


function Read-Secret {
    param([string]$Prompt)
    $secure = Read-Host -Prompt $Prompt -AsSecureString
    if ($secure.Length -eq 0) { return "" }
    $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try {
        return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr)
    }
    finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr)
    }
}


Write-Host "== 1/5 检测 Python"
$PythonExe = Resolve-PythonExecutable
Write-Host "   Python: $PythonExe"

Write-Host "== 2/5 创建本机目录"
foreach ($dir in @(
    $Spool,
    (Join-Path $Spool "outbox"),
    (Join-Path $Spool "inbox"),
    (Join-Path $Spool "inbox\processed"),
    (Join-Path $Spool "state"),
    $BinDir,
    $NativeHostDir
)) {
    New-Item -ItemType Directory -Path $dir -Force | Out-Null
}

Copy-Item -LiteralPath (Join-Path $Repo "flows\translate-claude-api.py") -Destination $FlowBin -Force
Copy-Item -LiteralPath (Join-Path $Repo "host\info_collector_host.py") -Destination $HostBin -Force
Copy-Item -LiteralPath (Join-Path $Repo "info_collector_platform.py") -Destination $CompatBin -Force

Write-Host "== 3/5 配置翻译引擎"
$config = Read-JsonMap -Path $ConfigPath
$engine = [string]$env:INFO_COLLECTOR_ENGINE
if (-not $engine) {
    $existingProvider = [string]$config["provider"]
    if ($existingProvider -eq "anthropic") {
        $engine = "claude"
        Write-Host "   保留现有 Anthropic 配置"
    }
    elseif ($existingProvider -eq "deepseek") {
        $engine = "deepseek"
        Write-Host "   保留现有 DeepSeek 配置"
    }
    else {
        Write-Host "   1) DeepSeek（默认）"
        Write-Host "   2) Claude / Anthropic"
        Write-Host "   3) 暂不配置翻译"
        $choice = Read-Host "   输入 1、2 或 3"
        switch ($choice) {
            "2" { $engine = "claude" }
            "3" { $engine = "skip" }
            default { $engine = "deepseek" }
        }
    }
}
$engine = $engine.Trim().ToLowerInvariant()
if ($engine -notin @("deepseek", "claude", "skip")) {
    throw "INFO_COLLECTOR_ENGINE 必须是 deepseek、claude 或 skip"
}

if ($engine -ne "skip") {
    $provider = if ($engine -eq "claude") { "anthropic" } else { "deepseek" }
    $defaultModel = if ($provider -eq "anthropic") { "claude-opus-4-8" } else { "deepseek-v4-flash" }
    $defaultBaseUrl = if ($provider -eq "anthropic") { "https://api.anthropic.com" } else { "https://api.deepseek.com" }

    $apiKey = [string]$env:INFO_COLLECTOR_API_KEY
    if (-not $apiKey -and $config.ContainsKey("apiKey")) {
        $apiKey = [string]$config["apiKey"]
    }
    if (-not $apiKey) {
        $apiKey = Read-Secret "   粘贴 API Key（输入不可见，直接回车可稍后配置）"
    }

    $outputDir = [string]$env:INFO_COLLECTOR_OUTPUT_DIR
    if (-not $outputDir -and $config.ContainsKey("outputDir")) {
        $outputDir = [string]$config["outputDir"]
    }
    if (-not $outputDir) {
        $defaultOutput = Join-Path $HomeDir "Documents\InfoCollector"
        $answer = Read-Host "   译文目录（默认 $defaultOutput）"
        $outputDir = if ($answer) { $answer } else { $defaultOutput }
    }
    $outputDir = [Environment]::ExpandEnvironmentVariables($outputDir)
    New-Item -ItemType Directory -Path $outputDir -Force | Out-Null

    $model = [string]$env:INFO_COLLECTOR_MODEL
    if (-not $model -and [string]$config["provider"] -eq $provider) {
        $model = [string]$config["model"]
    }
    if (-not $model) { $model = $defaultModel }

    $baseUrl = [string]$env:INFO_COLLECTOR_BASE_URL
    if (-not $baseUrl -and [string]$config["provider"] -eq $provider) {
        $baseUrl = [string]$config["baseUrl"]
    }
    if (-not $baseUrl) { $baseUrl = $defaultBaseUrl }

    $config["provider"] = $provider
    $config["apiKey"] = $apiKey
    $config["model"] = $model
    $config["baseUrl"] = $baseUrl.TrimEnd("/")
    $config["outputDir"] = (Resolve-Path -LiteralPath $outputDir).Path
    Write-Utf8NoBom -Path $ConfigPath -Content ($config | ConvertTo-Json -Depth 10)

    $flows = Read-JsonMap -Path $FlowsPath
    $flows["translate"] = [ordered]@{
        command = @($PythonExe, $FlowBin, "--manual")
        lockFile = (Join-Path $Spool "state\translate.lock")
        intervalSeconds = $null
        label = "manual"
    }
    Write-Utf8NoBom -Path $FlowsPath -Content ($flows | ConvertTo-Json -Depth 10)
    Write-Host "   已配置 $provider / $model"
}
else {
    Write-Host "   已跳过翻译配置；Native Host 仍会安装"
}

Write-Host "== 4/5 注册 Chrome Native Messaging Host"
$wrapperPath = Join-Path $NativeHostDir "info-collector-host.bat"
$escapedPython = $PythonExe.Replace("%", "%%")
$wrapper = "@echo off`r`n`"$escapedPython`" `"%~dp0..\bin\info-collector-host.py`" %*`r`n"
Write-Utf8NoBom -Path $wrapperPath -Content $wrapper

$manifestPath = Join-Path $NativeHostDir "$HostName.json"
$manifest = [ordered]@{
    name = $HostName
    description = "Info Collector file bridge"
    path = $wrapperPath
    type = "stdio"
    allowed_origins = @("chrome-extension://$ExtensionId/")
}
Write-Utf8NoBom -Path $manifestPath -Content ($manifest | ConvertTo-Json -Depth 5)

$registryPath = "HKCU:\Software\Google\Chrome\NativeMessagingHosts\$HostName"
if ($env:INFO_COLLECTOR_SKIP_REGISTRATION -eq "1") {
    Write-Host "   测试模式：已跳过注册表写入"
}
else {
    New-Item -Path $registryPath -Force | Out-Null
    Set-Item -Path $registryPath -Value $manifestPath
    Write-Host "   已注册 $registryPath"
}

Write-Host "== 5/5 完成"
Write-Host ""
Write-Host "Chrome 扩展目录：$Repo\extension"
Write-Host "扩展 ID 应为：$ExtensionId"
Write-Host "安装或重装 Host 后，请完全退出并重新打开 Chrome。"
Write-Host ""
Write-Host "自检命令："
Write-Host "  & `"$PythonExe`" `"$FlowBin`" --check"
Write-Host "Native Host ping："
Write-Host "  & `"$PythonExe`" `"$Repo\scripts\check-native-host.py`""
