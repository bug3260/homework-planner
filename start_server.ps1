# 暑假作业小管家 - 局域网手机访问启动脚本
$ErrorActionPreference = 'Continue'
$port = 8000
$root = $PSScriptRoot

Write-Host ''
Write-Host '========================================'
Write-Host '  暑假作业小管家 - 手机打开 + 自动同步'
Write-Host '========================================'
Write-Host '手机要和这台电脑连同一个 WiFi。'
Write-Host '然后手机 Chrome 打开下面其中一个网址：'
Write-Host ''

$cfg = Get-NetIPConfiguration -ErrorAction SilentlyContinue | Where-Object { $_.NetAdapter.Status -eq 'Up' -and $_.IPv4DefaultGateway -and -not $_.NetAdapter.Virtual }
$ips = @($cfg | ForEach-Object { $_.IPv4Address.IPAddress } | Where-Object { $_ -and $_ -notlike '169.254.*' } | Select-Object -Unique)
if ($ips.Count -eq 0) {
  $ips = @(Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' -and $_.InterfaceAlias -notlike '*Loopback*' } |
    Select-Object -ExpandProperty IPAddress -Unique)
}

if ($ips.Count -eq 0) {
  Write-Host '（没有找到局域网地址，请先让电脑连上 WiFi）' -ForegroundColor Yellow
} else {
  foreach ($ip in $ips) {
    Write-Host ("  手机打开: http://{0}:{1}" -f $ip, $port) -ForegroundColor Green
  }
}
Write-Host ("  电脑自己看: http://127.0.0.1:{0}" -f $port)
Write-Host ''

# 端口占用检查
$occupied = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
if ($occupied) {
  Write-Host ("端口 {0} 已被占用。请先关掉之前留下的黑色小窗口，再重新双击启动。" -f $port) -ForegroundColor Red
  exit 1
}

# 防火墙放行（需要管理员权限；失败也不影响电脑本地访问）
$ruleName = '暑假作业小管家-8000'
$rule = Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue
if (-not $rule) {
  try {
    New-NetFirewallRule -DisplayName $ruleName -Direction Inbound -Action Allow -Protocol TCP -LocalPort $port -Profile Private,Public -ErrorAction Stop | Out-Null
    Write-Host '已自动放行防火墙端口 8000。' -ForegroundColor Green
  } catch {
    Write-Host '没能自动放行防火墙（当前不是管理员身份）。' -ForegroundColor Yellow
    Write-Host '手机打不开时：右键「启动本地服务器.bat」选"以管理员身份运行"，' -ForegroundColor Yellow
    Write-Host '或在 Windows 防火墙弹窗里勾选"专用网络"并点"允许访问"。' -ForegroundColor Yellow
  }
} else {
  Write-Host '防火墙端口 8000 已放行。' -ForegroundColor Green
}
Write-Host ''

# 找 python
$python = $null
foreach ($cmd in @('python','py')) {
  if (Get-Command $cmd -ErrorAction SilentlyContinue) { $python = $cmd; break }
}
if (-not $python) {
  Write-Host '找不到 Python，请先安装 Python（官网 python.org）。' -ForegroundColor Red
  exit 1
}

Write-Host '手机打不开时按顺序检查：' -ForegroundColor Cyan
Write-Host '  1. 手机和电脑在同一个 WiFi（路由器若开了"AP 隔离"会互相找不到）' -ForegroundColor Cyan
Write-Host '  2. 防火墙是否放行（见上面提示）' -ForegroundColor Cyan
Write-Host '  3. 网址要输 http:// 开头，不是 https' -ForegroundColor Cyan
Write-Host ''
Write-Host '使用期间不要关掉这个窗口，按 Ctrl+C 结束。' -ForegroundColor Cyan
Write-Host '========================================'
Write-Host ''

& $python (Join-Path $root 'server.py') $port
