#!/bin/bash
# Script para iniciar Chrome en modo debugging (Linux)
# Para usar con HomeScraper.py (Multi-Portal)

echo ""
echo "========================================================"
echo "  INICIADOR DE CHROME CON DEBUGGING HABILITADO"
echo "  Para usar con HomeScraper.py (Multi-Portal)"
echo "========================================================"
echo ""

# Crear directorio para el perfil si no existe
PROFILE_DIR="$HOME/selenium_chrome_profile"
if [ ! -d "$PROFILE_DIR" ]; then
    echo "Creando directorio para perfil de Chrome..."
    mkdir -p "$PROFILE_DIR"
fi

echo ""
echo "Abriendo Chrome con debugging en puerto 9222..."
echo ""
echo "IMPORTANTE:"
echo "  - NO cierres este Chrome manualmente"
echo "  - Opcion A: Deja que el scraper navegue por ti (recomendado)"
echo "  - Opcion B: Navega manualmente al portal (Idealista, Fotocasa, etc.)"
echo "  - Resuelve cualquier CAPTCHA que aparezca"
echo "  - Luego ejecuta: ./start_scraper.sh o python HomeScraper.py"
echo ""

# Intentar encontrar Chrome/Chromium
CHROME=""

if command -v google-chrome &> /dev/null; then
    CHROME="google-chrome"
elif command -v google-chrome-stable &> /dev/null; then
    CHROME="google-chrome-stable"
elif command -v chromium-browser &> /dev/null; then
    CHROME="chromium-browser"
elif command -v chromium &> /dev/null; then
    CHROME="chromium"
elif [ -f "/usr/bin/google-chrome" ]; then
    CHROME="/usr/bin/google-chrome"
elif [ -f "/usr/bin/chromium-browser" ]; then
    CHROME="/usr/bin/chromium-browser"
elif [ -f "/snap/bin/chromium" ]; then
    CHROME="/snap/bin/chromium"
fi

if [ -z "$CHROME" ]; then
    echo "ERROR: No se encontró Chrome ni Chromium instalado."
    echo ""
    echo "Instala Chrome o Chromium:"
    echo "  Ubuntu/Debian: sudo apt install chromium-browser"
    echo "  O descarga Chrome: https://www.google.com/chrome/"
    echo ""
    exit 1
fi

echo "Usando: $CHROME"
echo ""

# Iniciar Chrome con debugging y opciones anti-detección
$CHROME \
    --remote-debugging-port=9222 \
    --user-data-dir="$PROFILE_DIR" \
    --no-first-run \
    --disable-default-apps \
    --disable-popup-blocking \
    --disable-infobars \
    --lang=es-ES \
    --window-size=1920,1080 \
    2>/dev/null &

echo "Chrome iniciado. Puedes minimizar esta terminal."
echo "Presiona Ctrl+C para cerrar Chrome cuando termines."
echo ""

# Esperar a que el usuario cierre
wait
