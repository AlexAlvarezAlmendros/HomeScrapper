#!/bin/bash
# Script para iniciar el scraper de Fotocasa con Chromium (Playwright)
# NO necesita Chrome instalado - usa Chromium de Playwright

cd "$(dirname "$0")"

echo "=================================================="
echo "   FOTOCASA SCRAPER - Chromium (Playwright)"
echo "=================================================="
echo ""

# Activar entorno virtual si existe
if [ -d ".venv" ]; then
    source .venv/bin/activate
    echo "[✓] Entorno virtual activado"
fi

echo "[*] Iniciando scraper..."
echo ""

python3 fotocasa_scraper_firefox.py

echo ""
echo "[*] Scraper finalizado"
