#!/bin/bash
# Build the React frontend and output to src/web/frontend_dist/

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
FRONTEND_DIR="$PROJECT_ROOT/frontend"

echo "Building frontend..."
cd "$FRONTEND_DIR"

# Install dependencies if needed
if [ ! -d "node_modules" ]; then
    echo "Installing dependencies..."
    npm install
fi

# Generate TypeScript types from OpenAPI (optional, requires backend running)
# Uncomment the following line if you want to generate types:
# npm run generate-types

# Build the frontend
npm run build

echo "Frontend built successfully to src/web/frontend_dist/"
echo "Run 'python -m src.web.auto_dashboard' to start the server."
