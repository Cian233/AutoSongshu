#!/bin/bash

# AutoSongshu Docker Deployment Script (Linux/macOS)

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$( dirname "$SCRIPT_DIR" )"

# Check if .env exists
if [ ! -f "$PROJECT_ROOT/.env" ]; then
    echo "Creating .env from .env.example..."
    cp "$PROJECT_ROOT/.env.example" "$PROJECT_ROOT/.env"
    echo "WARNING: Please edit .env and set your AUTOSONGSHU_MODEL_API_KEY and other settings!"
fi

# Create necessary directories
DIRS=("data" "artifacts" "configs" "skills")
for DIR in "${DIRS[@]}"; do
    if [ ! -d "$PROJECT_ROOT/$DIR" ]; then
        echo "Creating $DIR directory..."
        mkdir -p "$PROJECT_ROOT/$DIR"
    fi
done

# Run docker-compose
echo "Starting AutoSongshu via Docker Compose..."
cd "$SCRIPT_DIR"
docker-compose up --build -d

echo -e "\nAutoSongshu is starting!"
echo "You can access the Web UI at: http://localhost:8000"
echo "To view logs, run: docker-compose logs -f"
