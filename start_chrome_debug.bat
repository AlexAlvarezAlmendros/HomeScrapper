@echo off
echo ========================================================
echo  INICIADOR DE CHROME CON DEBUGGING HABILITADO
echo  Para usar con scraper_cdp.py
echo ========================================================
echo.

REM Crear directorio para el perfil si no existe
if not exist "C:\selenium\ChromeProfile" (
    echo Creando directorio para perfil de Chrome...
    mkdir "C:\selenium\ChromeProfile"
)

echo.
echo Abriendo Chrome con debugging en puerto 9222...
echo.
echo IMPORTANTE:
echo - NO cierres este Chrome manualmente
echo - Navega a Idealista y busca viviendas
echo - Resuelve cualquier CAPTCHA que aparezca
echo - Luego ejecuta: python scraper_cdp.py
echo.

REM Intentar encontrar Chrome en ubicaciones comunes
set CHROME=""

if exist "C:\Program Files\Google\Chrome\Application\chrome.exe" (
    set CHROME="C:\Program Files\Google\Chrome\Application\chrome.exe"
)

if exist "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe" (
    set CHROME="C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
)

if exist "%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe" (
    set CHROME="%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"
)

if %CHROME%=="" (
    echo ERROR: No se encontro Chrome en las ubicaciones habituales
    echo.
    echo Por favor, ejecuta manualmente:
    echo "RUTA_A_CHROME\chrome.exe" --remote-debugging-port=9222 --user-data-dir="C:\selenium\ChromeProfile"
    pause
    exit /b 1
)

echo Chrome encontrado en: %CHROME%
echo.

REM Abrir Chrome con debugging
start "" %CHROME% --remote-debugging-port=9222 --user-data-dir="C:\selenium\ChromeProfile"

echo.
echo Chrome abierto con debugging habilitado
echo.
echo Ahora:
echo 1. Ve al Chrome que se abrio
echo 2. Navega a: https://www.idealista.com/venta-viviendas/madrid/
echo 3. Busca las viviendas que quieras
echo 4. Cuando estes listo, ejecuta: python scraper_cdp.py
echo.
pause
