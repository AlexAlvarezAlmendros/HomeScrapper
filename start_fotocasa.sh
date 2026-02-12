#!/bin/bash
# Script para ejecutar el scraper de Fotocasa con anti-detección
# NO necesita Chrome en modo debugging - usa su propio navegador

echo ""
echo "============================================================"
echo "  Fotocasa Scraper - Anti-Detección"
echo "  Usando undetected-chromedriver"
echo "============================================================"
echo ""
echo "[!] IMPORTANTE:"
echo "    Este scraper abre su propio navegador Chrome"
echo "    NO necesitas ejecutar start_chrome_debug.sh"
echo ""
echo "[*] El navegador se abrirá automáticamente"
echo "    Si aparece un captcha, resuélvelo manualmente"
echo ""
echo "============================================================"
echo ""
read -p "Presiona Enter para continuar..."

# Activar entorno virtual y ejecutar scraper
source .venv/bin/activate
python fotocasa_scraper_uc.py

echo ""
echo "============================================================"
echo "  Scraping completado"
echo "============================================================"
echo ""
read -p "Presiona Enter para salir..."
