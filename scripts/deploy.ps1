# Deploy Sift to AWS with the SAM CLI (Windows PowerShell).
# Prereqs: AWS CLI configured (`aws configure`) and SAM CLI installed.
#   winget install Amazon.SAM-CLI     (or see README)
$ErrorActionPreference = "Stop"

Push-Location $PSScriptRoot\..
try {
    Write-Host "Building..." -ForegroundColor Cyan
    sam build

    Write-Host "Deploying (guided on first run)..." -ForegroundColor Cyan
    sam deploy --guided `
        --stack-name sift-agent `
        --capabilities CAPABILITY_IAM `
        --resolve-s3
}
finally {
    Pop-Location
}
