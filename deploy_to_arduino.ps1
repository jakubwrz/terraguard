<#
.SYNOPSIS
    Deploys TerraGuard code directly from PC to Arduino Uno Q over Wi-Fi / SSH.
    No flash drives needed.
#>

param (
    [string]$ArduinoHost = "cookie.local",
    [string]$Username = "arduino"
)

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "   TerraGuard Direct Deploy -> Arduino Uno Q" -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

# Test ping or connection
Write-Host "`n[1/3] Testing connection to $Username..." -ForegroundColor Yellow

$pingSuccess = $false
$candidates = @($ArduinoHost, "cookie.local", "arduino.local") | Select-Object -Unique

foreach ($cand in $candidates) {
    try {
        $addrs = [System.Net.Dns]::GetHostAddresses($cand) | Where-Object { $_.AddressFamily -eq [System.Net.Sockets.AddressFamily]::InterNetwork }
        if ($addrs -and $addrs.Count -gt 0) {
            $ArduinoHost = $addrs[0].IPAddressToString
            $pingSuccess = $true
            break
        }
    } catch {
        try {
            $ping = Test-Connection -ComputerName $cand -Count 1 -Quiet -ErrorAction SilentlyContinue
            if ($ping) {
                $ArduinoHost = $cand
                $pingSuccess = $true
                break
            }
        } catch {}
    }
}

if (-not $pingSuccess) {
    Write-Host "[!] Could not reach 'cookie.local' or 'arduino.local' automatically." -ForegroundColor Yellow
    $manualIP = Read-Host "Enter the Arduino Uno Q IP address (check Wi-Fi settings on Arduino, e.g. 192.168.1.50)"
    if ([string]::IsNullOrWhiteSpace($manualIP)) {
        Write-Host "Aborted." -ForegroundColor Red
        exit 1
    }
    $ArduinoHost = $manualIP.Trim()
}

Write-Host "[+] Target: $Username@$ArduinoHost" -ForegroundColor Green

# Create remote directories
Write-Host "`n[2/3] Syncing files to Arduino (~/terraguard)..." -ForegroundColor Yellow
$remoteDir = "~/terraguard"
ssh -o StrictHostKeyChecking=no "$Username@$ArduinoHost" "mkdir -p $remoteDir/python $remoteDir/sketch $remoteDir/missions"

if ($LASTEXITCODE -ne 0) {
    Write-Host "[!] SSH connection failed. Make sure SSH is enabled on the Uno Q and password is correct." -ForegroundColor Red
    exit 1
}

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

# Copy Python files
Write-Host "  -> Uploading Linux Python stack..."
scp -o StrictHostKeyChecking=no -r "$scriptDir\uno_q_linux\*" "$Username@$ArduinoHost`:$remoteDir/python/"

# Copy Sketch files
Write-Host "  -> Uploading STM32/Zephyr Sketch..."
scp -o StrictHostKeyChecking=no -r "$scriptDir\uno_q_stm32\*" "$Username@$ArduinoHost`:$remoteDir/sketch/"

# Copy Motor Test files
Write-Host "  -> Uploading Safe Motor Test Diagnostic Tool..."
ssh -o StrictHostKeyChecking=no "$Username@$ArduinoHost" "mkdir -p $remoteDir/motor_test"
scp -o StrictHostKeyChecking=no -r "$scriptDir\uno_q_motor_test\*" "$Username@$ArduinoHost`:$remoteDir/motor_test/"

# Copy ONNX model to the Python directory (same dir as vision.py)
Write-Host "  -> Uploading ONNX terrain classification model..."
scp -o StrictHostKeyChecking=no "$scriptDir\models\wildfire_model.onnx" "$Username@$ArduinoHost`:$remoteDir/python/wildfire_model.onnx"

# Ensure onnxruntime is installed on the Arduino
# Clean up stale legacy routes that had 5.6M meter GPS jump
Write-Host "  -> Purging old route files with legacy GPS jump coordinates..."
ssh -o StrictHostKeyChecking=no "$Username@$ArduinoHost" "rm -f $remoteDir/missions/latest_route.json $remoteDir/python/missions/latest_route.json ~/missions/latest_route.json"

Write-Host "`n[3/3] Deployment complete!" -ForegroundColor Green
Write-Host "----------------------------------------------------------"
Write-Host "Files are located on the Arduino at: ~/terraguard"
Write-Host "To connect to the rover via SSH:"
Write-Host "   ssh $Username@$ArduinoHost" -ForegroundColor Cyan
Write-Host "To flash the STM32 sketch and run the rover:"
Write-Host "   bash ~/terraguard/python/build_and_run.sh" -ForegroundColor Cyan
Write-Host "Or to run just the Python service directly:"
Write-Host "   python3 ~/terraguard/python/main.py" -ForegroundColor Cyan
Write-Host "----------------------------------------------------------"
