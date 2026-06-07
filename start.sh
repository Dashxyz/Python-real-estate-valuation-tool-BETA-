#!/bin/bash

echo "🏡 Starting Homelytics..."

# Pull latest code from GitHub
echo "📥 Pulling latest code..."
git pull

# Ask for API key securely
echo ""
read -sp "🔑 Paste your Gemini API key: " GOOGLE_AI_API_KEY
echo ""
export GOOGLE_AI_API_KEY

# Set environment variables
export GRADIO_ANALYTICS_ENABLED=false
export HF_HUB_OFFLINE=1

# Ask which version to run
echo ""
echo "Which version do you want to run?"
echo "1) Homelytics US"
echo "2) Homelytics Pakistan"
read -p "Enter 1 or 2: " choice

if [ "$choice" == "1" ]; then
    echo "🇺🇸 Starting Homelytics US..."
    python3 Homelytics_US.py
elif [ "$choice" == "2" ]; then
    echo "🇵🇰 Starting Homelytics Pakistan..."
    python3 Homelytics_PK.py
else
    echo "Invalid choice. Please enter 1 or 2."
fi
