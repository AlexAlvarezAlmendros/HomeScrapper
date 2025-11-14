@echo off
REM Script para ejecutar HomeScraperIdealista.py
REM Asegúrate de haber ejecutado start_chrome_debug.bat primero

echo.
echo ============================================================
echo   HomeScrapper - Idealista Property Scraper
echo ============================================================
echo.
echo [!] IMPORTANTE: Asegurate de haber ejecutado primero:
echo     start_chrome_debug.bat
echo.
echo     Y estar en la pagina de Idealista con tu busqueda
echo.
echo ============================================================
echo.
pause

REM Activar entorno virtual y ejecutar scraper
call .venv\Scripts\activate.bat
python HomeScraperIdealista.py

echo.
echo ============================================================
echo   Scraping completado
echo ============================================================
echo.
pause
