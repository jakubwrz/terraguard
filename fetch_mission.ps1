param (
    [string]$ArduinoHost = "cookie.local",
    [string]$Username = "arduino"
)

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "   TerraGuard: Fetch Mission Telemetry & Photos from Rover" -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

$candidates = @($ArduinoHost, "192.168.2.116", "cookie.local", "arduino.local") | Select-Object -Unique
$target = $null
foreach ($cand in $candidates) {
    if (Test-Connection -ComputerName $cand -Count 1 -Quiet -ErrorAction SilentlyContinue) {
        $target = $cand
        break
    }
}
if (-not $target) { $target = "cookie.local" }

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$missionsDir = Join-Path $scriptDir "missions"
$datasetDir  = Join-Path $scriptDir "dataset"

New-Item -ItemType Directory -Force -Path $missionsDir | Out-Null
New-Item -ItemType Directory -Force -Path $datasetDir  | Out-Null

Write-Host "[+] Target rover: $Username@$target" -ForegroundColor Green
Write-Host "[+] Local destination: $scriptDir" -ForegroundColor White

Write-Host "`n[1/3] Downloading missions from ~/terraguard/python/missions/..." -ForegroundColor Yellow
scp -o StrictHostKeyChecking=no -r "$Username@$target`:~/terraguard/python/missions/*" $missionsDir

Write-Host "`n[2/3] Downloading training photos from ~/terraguard/python/dataset/ and ~/dataset/..." -ForegroundColor Yellow
scp -o StrictHostKeyChecking=no -r "$Username@$target`:~/terraguard/python/dataset/*" $datasetDir
scp -o StrictHostKeyChecking=no -r "$Username@$target`:~/dataset/*" $datasetDir

Write-Host "`n[3/3] Checking downloaded files..." -ForegroundColor Yellow
$missions = Get-ChildItem -Path $missionsDir -Recurse -Filter "*.json" -ErrorAction SilentlyContinue
$photos   = Get-ChildItem -Path $scriptDir -Recurse -Filter "*.jpg" -ErrorAction SilentlyContinue

Write-Host "    Found $($missions.Count) mission/telemetry JSON files." -ForegroundColor Cyan
foreach ($m in $missions | Select-Object -Last 10) {
    Write-Host "      - $($m.FullName.Replace($scriptDir, ''))" -ForegroundColor Gray
}

Write-Host "    Found $($photos.Count) JPG photos." -ForegroundColor Cyan
foreach ($p in $photos | Select-Object -Last 10) {
    Write-Host "      - $($p.FullName.Replace($scriptDir, ''))" -ForegroundColor Gray
}

if ($missions.Count -gt 0) {
    Write-Host "`n[+] Generating interactive satellite mission map..." -ForegroundColor Green
    python (Join-Path $scriptDir "uno_q_linux\visualize_mission.py")
} else {
    Write-Host "`n[!] No mission files were retrieved." -ForegroundColor Yellow
}
