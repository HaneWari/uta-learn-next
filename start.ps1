# Uta Learn Next — 一键启动（由 dev.cmd 调用）
# Native commands returning non-zero must not abort the script, so the
# preference stays at Continue and exit codes are checked explicitly.
$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$rebuild = $args -contains "--rebuild"

function Say($msg, $color = "Gray") { Write-Host "  $msg" -ForegroundColor $color }
function Fail($msg) {
  Write-Host ""
  Write-Host "  [X] $msg" -ForegroundColor Red
  Write-Host ""
  Read-Host "按回车退出"
  exit 1
}

Write-Host ""
Write-Host "  Uta Learn Next " -ForegroundColor Yellow
Write-Host "  ----------------------------------------"
Write-Host ""

# ---------------------------------------------------------------- python ----
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
  Fail "没找到 python。请先安装 Python 3.12+ 并勾选 Add to PATH：https://www.python.org/downloads/"
}

# ------------------------------------------------------------ 依赖检查 ----
Say "[1/3] 检查 Python 依赖..."
$probe = 'import fastapi, uvicorn, fugashi, httpx, numpy, PIL'
python -c $probe 2>$null
if ($LASTEXITCODE -ne 0) {
  Say "首次运行，正在安装基础依赖（需要几分钟）..." Yellow
  python -m pip install --quiet -e "backend[speech,export]"
  if ($LASTEXITCODE -ne 0) { Fail "依赖安装失败，请检查网络后重试。" }
  python -c $probe 2>$null
  if ($LASTEXITCODE -ne 0) { Fail "依赖装上了但导入失败，请手动执行：python -m pip install -e backend[speech,export]" }
}

python -c "import faster_whisper" 2>$null
if ($LASTEXITCODE -ne 0) {
  Say "[!] 没装 faster-whisper：搜索歌词和生成都能用，" DarkYellow
  Say "    但「上传音频 + 粘贴歌词」的自动对齐会不可用。" DarkYellow
  Say "    需要时执行：python -m pip install faster-whisper" DarkYellow
}

if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
  Say "[!] 没找到 ffmpeg：上传的音频无法解码，自动对齐会失败。" DarkYellow
}

# --------------------------------------------------------------- 前端 ----
Say "[2/3] 检查前端页面..."
$needBuild = $rebuild -or -not (Test-Path "frontend\dist\index.html")

if ($needBuild) {
  if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    Fail "没找到 npm，无法构建前端页面。请安装 Node.js 18+：https://nodejs.org/"
  }
  if (-not (Test-Path "frontend\node_modules")) {
    Say "安装前端依赖（需要几分钟）..." Yellow
    Push-Location frontend
    npm install
    $code = $LASTEXITCODE
    Pop-Location
    if ($code -ne 0) { Fail "npm install 失败。" }
  }
  Say "构建前端页面..." Yellow
  Push-Location frontend
  npm run build
  $code = $LASTEXITCODE
  Pop-Location
  if ($code -ne 0 -or -not (Test-Path "frontend\dist\index.html")) { Fail "前端构建失败。" }
}

# --------------------------------------------------------------- 启动 ----
Say "[3/3] 启动服务..."

# 端口已被占用就当作已经开着了
function Test-PortOpen($port) {
  try {
    $client = New-Object System.Net.Sockets.TcpClient
    $client.Connect("127.0.0.1", $port)
    $ok = $client.Connected
    $client.Close()
    return $ok
  } catch {
    return $false
  }
}

if (Test-PortOpen 8000) {
  Say "8000 端口已在运行，直接打开页面。" Green
  Start-Process "http://localhost:8000/"
  Write-Host ""
  Read-Host "按回车退出"
  exit 0
}

Write-Host ""
Say "地址： http://localhost:8000/" Green
Say "关闭这个窗口即停止服务。"
Write-Host ""

Start-Process "http://localhost:8000/"
Set-Location backend
python -m uvicorn main:app --host 0.0.0.0 --port 8000

Write-Host ""
Say "服务已停止。"
Read-Host "按回车退出"
