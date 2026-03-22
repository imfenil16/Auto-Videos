# Fallback stitching script — use if FFmpeg wasn't found during Blender run
# Run this AFTER generate_video.py has finished rendering all frames

$rendersDir = "$PSScriptRoot\renders"

# Check FFmpeg
if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    Write-Host "ERROR: FFmpeg not found. Install it from https://ffmpeg.org/download.html" -ForegroundColor Red
    Write-Host "  Or install via: winget install Gyan.FFmpeg" -ForegroundColor Yellow
    exit 1
}

$softValues = @(0, 10, 25, 50, 80, 100)
$clipPaths = @()

foreach ($soft in $softValues) {
    $clipDir = Join-Path $rendersDir ("soft_{0:D3}" -f $soft)
    $clipVideo = Join-Path $rendersDir ("clip_{0:D3}.mp4" -f $soft)
    $clipPaths += $clipVideo

    Write-Host "Encoding clip: Soft $soft%..."
    ffmpeg -y -framerate 30 -i "$clipDir\frame_%04d.png" `
        -c:v libx264 -pix_fmt yuv420p -crf 18 $clipVideo 2>$null
}

# Create concat list
$concatFile = Join-Path $rendersDir "concat_list.txt"
$clipPaths | ForEach-Object { "file '$_'" } | Set-Content $concatFile

# Concatenate
$finalOutput = Join-Path $rendersDir "final_output.mp4"
Write-Host "Concatenating all clips..."
ffmpeg -y -f concat -safe 0 -i $concatFile -c copy $finalOutput 2>$null

Write-Host "`nDone! Final video: $finalOutput" -ForegroundColor Green
