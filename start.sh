#!/bin/bash

echo "🏡 Starting Homelytics..."

# Pull latest code from GitHub
echo "📥 Pulling latest code..."
git stash
git pull

# Install ALL dependencies
echo "📦 Installing all dependencies (this may take a minute)..."
pip install -q --force-reinstall \
    google-generativeai \
    gradio==3.50.2 \
    pillow \
    geopy \
    ddgs \
    fastapi==0.99.1 \
    uvicorn==0.22.0 \
    huggingface_hub==0.19.4 \
    httpx==0.24.1 \
    pydantic \
    aiofiles \
    python-multipart \
    requests \
    numpy

echo "✅ Dependencies installed."

# Set ALL environment variables
export GRADIO_ANALYTICS_ENABLED=false
export HF_HUB_OFFLINE=1
export GRADIO_SERVER_NAME=0.0.0.0

# Ask for API key securely (won't show on screen)
echo ""
read -sp "🔑 Paste your Gemini API key and press Enter: " GOOGLE_AI_API_KEY
echo ""
export GOOGLE_AI_API_KEY

if [ -z "$GOOGLE_AI_API_KEY" ]; then
    echo "❌ No API key entered. Exiting."
    exit 1
fi

echo "✅ API key set."

# Ask which version to run
echo ""
echo "Which version do you want to run?"
echo "1) Homelytics US 🇺🇸"
echo "2) Homelytics Pakistan 🇵🇰"
read -p "Enter 1 or 2: " choice

if [ "$choice" == "1" ]; then
    echo "🇺🇸 Starting Homelytics US..."
    python3 Homelytics_US.py
elif [ "$choice" == "2" ]; then
    echo "🇵🇰 Starting Homelytics Pakistan..."
    python3 Homelytics_PK.py
else
    echo "❌ Invalid choice. Please enter 1 or 2."
    exit 1
fi
