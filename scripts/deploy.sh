#!/usr/bin/env bash
# Deploy Sift to AWS with the SAM CLI (macOS/Linux).
# Prereqs: AWS CLI configured (`aws configure`) and SAM CLI installed.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "Building..."
sam build

echo "Deploying (guided on first run)..."
sam deploy --guided \
  --stack-name sift-agent \
  --capabilities CAPABILITY_IAM \
  --resolve-s3
