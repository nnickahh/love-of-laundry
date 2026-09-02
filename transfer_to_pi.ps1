# Automated Transfer Script to Raspberry Pi 5
param(
    [Parameter(Mandatory=$false)]
    [string]$PiIP,
    
    [Parameter(Mandatory=$false)]
    [string]$PiUser = "pi",
    
    [Parameter(Mandatory=$false)]
    [string]$RemoteDir = "~/laundry_vision"
)

$ProjectPath = "D:\Institute of Technichal Education - LoL"

if (-not (Test-Path $ProjectPath)) {
    $ProjectPath = $PSScriptRoot
}

Set-Location -Path $ProjectPath

if (-not $PiIP) {
    Write-Host "=========================================" -ForegroundColor Cyan
    Write-Host " Raspberry Pi 5 File Transfer Helper" -ForegroundColor Cyan
    Write-Host "=========================================" -ForegroundColor Cyan
    $inputIP = Read-Host "Enter Raspberry Pi IP address [default: 172.20.97.215]"
    $PiIP = if ([string]::IsNullOrWhiteSpace($inputIP)) { "172.20.97.215" } else { $inputIP }
    $inputUser = Read-Host "Enter Raspberry Pi username [default: nick]"
    $PiUser = if ([string]::IsNullOrWhiteSpace($inputUser)) { "nick" } else { $inputUser }
}

if ([string]::IsNullOrWhiteSpace($PiIP)) {
    Write-Host "Error: No IP address provided." -ForegroundColor Red
    exit 1
}

Write-Host "`n[1/4] Connecting to $PiUser@$PiIP and preparing directories..." -ForegroundColor Yellow

ssh -o ConnectTimeout=8 "$PiUser@$PiIP" "mkdir -p $RemoteDir/runs/detect/deepfashion_phase2/weights $RemoteDir/runs/detect/garment_inspector_v2/weights $RemoteDir/edge/static/captures $RemoteDir/assets"
if ($LASTEXITCODE -ne 0) {
    Write-Host "Error: Could not connect to Raspberry Pi via SSH. Please verify IP, username, and SSH enabled." -ForegroundColor Red
    exit 1
}

Write-Host "`n[2/4] Copying model files (DeepFashion Phase 2 & Garment Inspector)..." -ForegroundColor Green
if (Test-Path "$ProjectPath\runs\detect\deepfashion_phase2\weights\best.onnx") {
    scp "$ProjectPath\runs\detect\deepfashion_phase2\weights\best.onnx" "$PiUser@${PiIP}:$RemoteDir/runs/detect/deepfashion_phase2/weights/"
}
if (Test-Path "$ProjectPath\runs\detect\deepfashion_phase2\weights\best.pt") {
    scp "$ProjectPath\runs\detect\deepfashion_phase2\weights\best.pt" "$PiUser@${PiIP}:$RemoteDir/runs/detect/deepfashion_phase2/weights/"
}
if (Test-Path "$ProjectPath\runs\detect\garment_inspector_v2\weights\best.hef") {
    scp "$ProjectPath\runs\detect\garment_inspector_v2\weights\best.hef" "$PiUser@${PiIP}:$RemoteDir/runs/detect/garment_inspector_v2/weights/"
}
if (Test-Path "$ProjectPath\runs\detect\garment_inspector_v2\weights\best.onnx") {
    scp "$ProjectPath\runs\detect\garment_inspector_v2\weights\best.onnx" "$PiUser@${PiIP}:$RemoteDir/runs/detect/garment_inspector_v2/weights/"
}
if (Test-Path "$ProjectPath\runs\detect\garment_inspector_v2\weights\best.pt") {
    scp "$ProjectPath\runs\detect\garment_inspector_v2\weights\best.pt" "$PiUser@${PiIP}:$RemoteDir/runs/detect/garment_inspector_v2/weights/"
}

Write-Host "`n[3/4] Copying edge application, shared models & assets..." -ForegroundColor Green
scp -r "$ProjectPath\edge" "$PiUser@${PiIP}:$RemoteDir/"
if (Test-Path "$ProjectPath\shared") {
    scp -r "$ProjectPath\shared" "$PiUser@${PiIP}:$RemoteDir/"
}
if (Test-Path "$ProjectPath\scripts") {
    scp -r "$ProjectPath\scripts" "$PiUser@${PiIP}:$RemoteDir/"
}
if (Test-Path "$ProjectPath\assets") {
    scp -r "$ProjectPath\assets" "$PiUser@${PiIP}:$RemoteDir/"
}
if (Test-Path "$ProjectPath\test_onnx.py") {
    scp "$ProjectPath\test_onnx.py" "$PiUser@${PiIP}:$RemoteDir/"
}
if (Test-Path "$ProjectPath\requirements.txt") {
    scp "$ProjectPath\requirements.txt" "$PiUser@${PiIP}:$RemoteDir/"
}
if (Test-Path "$ProjectPath\start_edge.sh") {
    scp "$ProjectPath\start_edge.sh" "$PiUser@${PiIP}:$RemoteDir/"
}

Write-Host "`n[4/4] Setting execute permissions on Raspberry Pi..." -ForegroundColor Green
ssh "$PiUser@$PiIP" "chmod +x $RemoteDir/start_edge.sh $RemoteDir/scripts/setup_swap.sh 2>/dev/null"

Write-Host "`n========================================================" -ForegroundColor Cyan
Write-Host " Transfer Complete! All files loaded onto Raspberry Pi 5." -ForegroundColor Green
Write-Host "========================================================" -ForegroundColor Cyan
Write-Host " Next steps on your Raspberry Pi:" -ForegroundColor Yellow
Write-Host "   1. ssh $PiUser@$PiIP" -ForegroundColor White
Write-Host "   2. cd $RemoteDir" -ForegroundColor White
Write-Host "   3. sudo ./scripts/setup_swap.sh  # Setup virtual memory (first time only)" -ForegroundColor White
Write-Host "   4. sudo reboot                   # Reboot to apply swap settings" -ForegroundColor White
Write-Host "   5. python3 test_onnx.py           # Test model inference speed" -ForegroundColor White
Write-Host "   6. ./start_edge.sh                # Start live inspection server" -ForegroundColor White
Write-Host "========================================================`n" -ForegroundColor Cyan

