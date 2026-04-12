#!/bin/bash
cd "$(dirname "$0")"
npm install --prefer-offline
npm run build
echo "Build complete. Output in dist/"
