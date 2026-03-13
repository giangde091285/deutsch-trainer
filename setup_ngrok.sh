#!/bin/bash

# 🇩🇪 Deutsch Trainer - Ngrok Setup Script
# This script helps install ngrok for internet sharing

echo "🔗 Setting up ngrok for worldwide access..."
echo

# Check if ngrok is already installed
if command -v ngrok &> /dev/null; then
    echo "✅ Ngrok is already installed!"
    ngrok version
    echo
    echo "🚀 You can now run:"
    echo "   python deutsch_trainer.py --ngrok"
    exit 0
fi

echo "📥 Ngrok not found. Installing..."

# Detect OS
if [[ "$OSTYPE" == "linux-gnu"* ]]; then
    # Linux
    echo "🐧 Detected Linux"

    # Check architecture
    ARCH=$(uname -m)
    if [[ "$ARCH" == "x86_64" ]]; then
        NGROK_URL="https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-linux-amd64.tgz"
    elif [[ "$ARCH" == "aarch64" ]] || [[ "$ARCH" == "arm64" ]]; then
        NGROK_URL="https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-linux-arm64.tgz"
    else
        echo "❌ Unsupported architecture: $ARCH"
        echo "💡 Please download manually from: https://ngrok.com/download"
        exit 1
    fi

    # Download and install
    echo "📥 Downloading ngrok..."
    curl -sSL "$NGROK_URL" -o /tmp/ngrok.tgz

    echo "📦 Extracting..."
    tar -xzf /tmp/ngrok.tgz -C /tmp/

    echo "📂 Installing to /usr/local/bin..."
    sudo mv /tmp/ngrok /usr/local/bin/
    sudo chmod +x /usr/local/bin/ngrok

    # Cleanup
    rm -f /tmp/ngrok.tgz

elif [[ "$OSTYPE" == "darwin"* ]]; then
    # macOS
    echo "🍎 Detected macOS"

    if command -v brew &> /dev/null; then
        echo "🍺 Installing via Homebrew..."
        brew install ngrok/ngrok/ngrok
    else
        echo "❌ Homebrew not found"
        echo "💡 Install Homebrew first or download ngrok manually:"
        echo "   https://ngrok.com/download"
        exit 1
    fi

elif [[ "$OSTYPE" == "msys" ]] || [[ "$OSTYPE" == "win32" ]]; then
    # Windows
    echo "🪟 Detected Windows"
    echo "💡 Please download ngrok manually from:"
    echo "   https://ngrok.com/download"
    echo "   Then extract to your PATH or current directory"
    exit 1

else
    echo "❌ Unknown OS: $OSTYPE"
    echo "💡 Please download manually from: https://ngrok.com/download"
    exit 1
fi

# Verify installation
if command -v ngrok &> /dev/null; then
    echo
    echo "✅ Ngrok installed successfully!"
    ngrok version
    echo
    echo "🔐 Next steps:"
    echo "   1. Sign up free: https://dashboard.ngrok.com/signup"
    echo "   2. Get your auth token: https://dashboard.ngrok.com/get-started/your-authtoken"
    echo "   3. Configure: ngrok config add-authtoken YOUR_TOKEN"
    echo "   4. Run app: python deutsch_trainer.py --ngrok"
    echo
    echo "🎉 Then share the ngrok URL with friends worldwide!"
else
    echo "❌ Installation failed"
    echo "💡 Please try manual installation: https://ngrok.com/download"
    exit 1
fi