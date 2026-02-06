@echo off
REM Script LEGACY para ejecutar solo Idealista con HomeScraperIdealista.py
REM Si quieres el nuevo sistema multi-portal, usa: start_scraper.bat

echo.
echo ============================================================
echo   HomeScraper - Idealista SOLO (Version Legacy)
echo ============================================================
echo.
echo [!] NOTA: Este es el script antiguo (solo Idealista)
echo     Para el nuevo sistema multi-portal, usa: start_scraper.bat
echo.
echo [!] IMPORTANTE: Asegurate de haber ejecutado primero:
echo     start_chrome_debug.bat
echo.
echo     Y estar en la pagina de Idealista con tu busqueda
echo.
echo ============================================================
echo.
pause

REM Activar entorno virtual y ejecutar scraper legacy
call .venv\Scripts\activate.bat
python HomeScraperIdealista.py

echo.
echo ============================================================
echo   Scraping completado
echo ============================================================
echo.
pause
