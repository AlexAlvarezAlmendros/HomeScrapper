#!/bin/bash
# Script unificado para ejecutar scrapers de viviendas
# Idealista: requiere Chrome con debugging (start_chrome_debug.sh)
# Fotocasa: usa Playwright con Chromium (no requiere Chrome externo)

clear
echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║       HomeScraper - Scraper Unificado de Viviendas       ║"
echo "║       Particulares de Idealista y Fotocasa               ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""
echo "  ¿Qué portal quieres scrapear?"
echo ""
echo "    1. Idealista  (requiere Chrome con debugging)"
echo "    2. Fotocasa   (usa Playwright - automático)"
echo "    3. Salir"
echo ""
echo "============================================================"
echo ""

read -p "  Elige una opción (1-3): " opcion

case $opcion in
    1)
        echo ""
        echo "============================================================"
        echo "  IDEALISTA - Método CDP (Chrome DevTools Protocol)"
        echo "============================================================"
        echo ""
        echo "[!] IMPORTANTE: Asegúrate de haber ejecutado primero:"
        echo "    ./start_chrome_debug.sh"
        echo ""
        read -p "Presiona Enter para continuar..."
        
        # Activar entorno virtual y ejecutar scraper Idealista
        source .venv/bin/activate
        python idealista_scraper.py
        ;;
    2)
        echo ""
        echo "============================================================"
        echo "  FOTOCASA - Método Playwright (Chromium automático)"
        echo "============================================================"
        echo ""
        echo "[*] No requiere Chrome externo, Playwright lo maneja."
        echo ""
        read -p "Presiona Enter para continuar..."
        
        # Activar entorno virtual y ejecutar scraper Fotocasa
        source .venv/bin/activate
        python fotocasa_scraper_firefox.py
        ;;
    3)
        echo ""
        echo "Saliendo..."
        exit 0
        ;;
    *)
        echo ""
        echo "[!] Opción no válida. Saliendo..."
        exit 1
        ;;
esac

echo ""
echo "============================================================"
echo "  Scraping completado"
echo "============================================================"
echo ""
read -p "Presiona Enter para salir..."
