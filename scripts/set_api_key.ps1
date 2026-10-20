# 安全写入 DeepSeek API Key 到项目根目录 .env
# 用法：在项目根目录执行
#   powershell -ExecutionPolicy Bypass -File scripts\set_api_key.ps1
# 输入时不回显，密钥不会出现在命令行历史中。

$ErrorActionPreference = "Stop"
$envPath = Join-Path (Split-Path -Parent $PSScriptRoot) ".env"

Write-Host "请先在 https://platform.deepseek.com/api_keys 创建新的 API Key。"
$secure = Read-Host "粘贴新的 DeepSeek API Key（输入不回显）" -AsSecureString
$bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
try {
    $key = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
}
finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
}

$key = $key.Trim()
if (-not $key) {
    Write-Error "未输入密钥，已取消。"
}
if (-not $key.StartsWith("sk-")) {
    Write-Error "密钥格式不正确：应以 sk- 开头。"
}

$lines = @()
if (Test-Path -LiteralPath $envPath) {
    $lines = [System.IO.File]::ReadAllLines($envPath, [System.Text.Encoding]::UTF8)
}

$found = $false
$updated = foreach ($line in $lines) {
    if ($line -match "^\s*DEEPSEEK_API_KEY\s*=") {
        if (-not $found) {
            "DEEPSEEK_API_KEY=$key"
            $found = $true
        }
        continue
    }
    $line
}
if (-not $found) {
    $updated = @($updated) + "DEEPSEEK_API_KEY=$key"
}

$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllLines($envPath, [string[]]$updated, $utf8NoBom)
Write-Host "已写入 $envPath（DEEPSEEK_API_KEY）"
Write-Host "请重启后端服务后再试；不要把这个密钥写进 configs/forge/forge.yaml 或提交到 Git。"
