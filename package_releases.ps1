$Version = "1.0.0"

$ReleaseRoot = "release"

# Stop any running ESG Builder processes
Write-Host "Checking for running ESG Builder processes..."
$processes = Get-Process -Name "*ESG_Builder*" -ErrorAction SilentlyContinue
if ($processes) {
    Write-Host "Stopping running ESG Builder processes..."
    $processes | Stop-Process -Force
    Start-Sleep -Seconds 2
}

# Clean up release directory
if (Test-Path $ReleaseRoot) {
    Remove-Item $ReleaseRoot -Recurse -Force
}

New-Item -ItemType Directory -Path $ReleaseRoot | Out-Null

# Function to compress with retry
function Compress-WithRetry {
    param (
        [string]$Path,
        [string]$DestinationPath,
        [int]$MaxRetries = 3
    )
    
    $attempt = 0
    while ($attempt -lt $MaxRetries) {
        try {
            Write-Host "Compressing $Path..."
            Compress-Archive -Path $Path -DestinationPath $DestinationPath -Force
            Write-Host "Successfully created $DestinationPath"
            return $true
        }
        catch {
            $attempt++
            if ($attempt -lt $MaxRetries) {
                Write-Host "Attempt $attempt failed. Waiting 3 seconds before retry..."
                Start-Sleep -Seconds 3
            }
            else {
                Write-Host "Failed to compress after $MaxRetries attempts: $_" -ForegroundColor Red
                return $false
            }
        }
    }
}

# Package each application
Compress-WithRetry `
    -Path "dist\Food_Agri_ESG_Builder\*" `
    -DestinationPath "$ReleaseRoot\Food_Agri_ESG_Builder_$Version.zip"

Compress-WithRetry `
    -Path "dist\Transport_Logistics_ESG_Builder\*" `
    -DestinationPath "$ReleaseRoot\Transport_Logistics_ESG_Builder_$Version.zip"

Compress-WithRetry `
    -Path "dist\Public_ESG_Builder\*" `
    -DestinationPath "$ReleaseRoot\Public_ESG_Builder_$Version.zip"

Write-Host "`nRelease packages created in $ReleaseRoot\"