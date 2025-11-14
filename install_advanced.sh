#!/bin/bash

# Script de instalación para el scraper avanzado

echo "Instalando dependencias avanzadas para evasión de DataDome..."

# Actualizar pip
pip install --upgrade pip

# Instalar dependencias principales
pip install -r requirements_advanced.txt

# Instalar playwright browsers
playwright install chromium firefox webkit

# Instalar herramientas adicionales para Linux/Mac
if [[ "$OSTYPE" == "linux-gnu"* ]]; then
    sudo apt-get update
    sudo apt-get install -y \
        chromium-browser \
        firefox \
        xvfb \
        libgconf-2-4 \
        libatk1.0-0 \
        libatk-bridge2.0-0 \
        libgtk-3-0 \
        libgbm-dev \
        libnss3-dev \
        libxss1 \
        libasound2
elif [[ "$OSTYPE" == "darwin"* ]]; then
    brew install --cask chromium
    brew install --cask firefox
fi

echo "✅ Instalación completada"