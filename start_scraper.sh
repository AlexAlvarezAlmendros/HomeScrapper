#!/bin/bash
# Script para ejecutar HomeScraperIdealista.py
# Asegúrate de haber ejecutado start_chrome_debug.sh primero

echo ""
echo "============================================================"
echo "  HomeScrapper - Idealista Property Scraper"
echo "============================================================"
echo ""
echo "[!] IMPORTANTE: Asegúrate de haber ejecutado primero:"
echo "    ./start_chrome_debug.sh"
echo ""
echo "    Y estar en la página de Idealista con tu búsqueda"
echo ""
echo "============================================================"
echo ""
read -p "Presiona Enter para continuar..."

# Activar entorno virtual y ejecutar scraper
source .venv/bin/activate
python HomeScraperIdealista.py

echo ""
echo "============================================================"
echo "  Scraping completado"
echo "============================================================"
echo ""
read -p "Presiona Enter para salir..."
