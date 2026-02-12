"""
HomeScraper - Scraper Multi-Portal de Viviendas
Soporta múltiples portales inmobiliarios de forma escalable
"""

import json
import os
import time
import random
from datetime import datetime
from scraper_factory import ScraperFactory
from base_scraper import PETICIONES_ANTES_CAMBIO_IP


def cargar_config():
    """Carga la configuración de URLs desde config.json"""
    config_path = os.path.join(os.path.dirname(__file__), 'config.json')
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"[ERROR] No se encontró el archivo config.json")
        return None
    except json.JSONDecodeError as e:
        print(f"[ERROR] Error parseando config.json: {e}")
        return None


def seleccionar_url(portal, config):
    """Permite al usuario seleccionar una URL del portal.
    
    Returns:
        - Un dict {'url': ..., 'nombre': ...} para una sola URL
        - Una lista de dicts para modo batch (todas)
        - None si hay error
    """
    if portal not in config:
        print(f"[ERROR] Portal '{portal}' no encontrado en config.json")
        return None
    
    urls_disponibles = config[portal].get('urls', [])
    
    if not urls_disponibles:
        print(f"[ERROR] No hay URLs configuradas para {portal}")
        return None
    
    if len(urls_disponibles) == 1:
        url_data = urls_disponibles[0]
        print(f"\n[*] URL: {url_data['nombre']}")
        print(f"    {url_data.get('descripcion', '')}")
        return {'url': url_data['url'], 'nombre': url_data['nombre']}
    
    # Mostrar menú de selección
    print(f"\n{'='*70}")
    print(f"SELECCIÓN DE ZONA - {portal.upper()}")
    print('='*70)
    print("\nZonas disponibles:")
    
    for idx, url_data in enumerate(urls_disponibles, 1):
        print(f"  {idx}. {url_data['nombre']}")
        if url_data.get('descripcion'):
            print(f"     → {url_data['descripcion']}")
    
    print(f"\n  0. TODAS las zonas (modo batch automático)")
    
    print()
    while True:
        seleccion = input(f"Elige una zona (0-{len(urls_disponibles)}, 0 = todas): ").strip()
        
        if seleccion == '0' or seleccion.lower() == 'todas':
            print(f"\n[OK] Modo BATCH: se procesarán las {len(urls_disponibles)} zonas secuencialmente")
            return [{'url': u['url'], 'nombre': u['nombre']} for u in urls_disponibles]
        
        try:
            idx = int(seleccion) - 1
            if 0 <= idx < len(urls_disponibles):
                url_data = urls_disponibles[idx]
                print(f"\n[OK] Zona seleccionada: {url_data['nombre']}")
                return {'url': url_data['url'], 'nombre': url_data['nombre']}
            else:
                print(f"[!] Por favor, elige un número entre 0 y {len(urls_disponibles)}")
        except ValueError:
            print("[!] Por favor, introduce un número válido")


def scrapear_idealista_batch(urls_list, debug, usar_rotacion, vpn_provider, num_paginas):
    """Procesa todas las URLs de Idealista secuencialmente via CDP."""
    from idealista_scraper import IdealistaScraper
    
    scraper = IdealistaScraper(
        modo_debug=debug,
        usar_rotacion_ip=usar_rotacion,
        vpn_provider=vpn_provider
    )
    
    if not scraper.conectar_chrome():
        return
    
    total = len(urls_list)
    for i, item in enumerate(urls_list, 1):
        url = item['url']
        nombre = item['nombre']
        
        print(f"\n\n{'#'*70}")
        print(f"  [{i}/{total}] PROCESANDO: {nombre}")
        print(f"  🔗 {url[:80]}...")
        print(f"{'#'*70}")
        
        # Configurar URL del scraper
        scraper.search_url = url
        
        # Navegar a la URL
        print(f"\n[*] Navegando a {nombre}...")
        scraper.navegar_a_url()
        
        # Scrapear con filtrado (usa JSON persistente por ubicación)
        viviendas = scraper.scrapear_con_filtrado(num_paginas, ubicacion=nombre)
        
        if viviendas:
            # Guardar en JSON persistente por ubicación
            filename = IdealistaScraper._obtener_ruta_json_persistente(nombre)
            scraper.guardar(viviendas, filename, ubicacion=nombre, url_scrapeada=url)
            scraper.mostrar_resumen(viviendas)
        else:
            print(f"\n⚠️  No se encontraron viviendas nuevas de particulares en {nombre}")
        
        if i < total:
            delay = random.uniform(8, 15)
            print(f"\n⏳ Esperando {delay:.0f}s antes de la siguiente zona...")
            time.sleep(delay)
    
    print(f"\n\n{'='*70}")
    print(f"  ✅ BATCH COMPLETADO: {total} zonas procesadas")
    print(f"{'='*70}")


def scrapear_fotocasa_batch(urls_list, debug, num_paginas):
    """Procesa todas las URLs de Fotocasa secuencialmente via Playwright."""
    from fotocasa_scraper_firefox import FotocasaScraperFirefox
    
    scraper = FotocasaScraperFirefox(modo_debug=debug)
    
    if not scraper.iniciar_navegador():
        return
    
    total = len(urls_list)
    try:
        for i, item in enumerate(urls_list, 1):
            url = FotocasaScraperFirefox._asegurar_orden_fecha_fotocasa(item['url'])
            nombre = item['nombre']
            
            print(f"\n\n{'#'*70}")
            print(f"  [{i}/{total}] PROCESANDO: {nombre}")
            print(f"  📅 Ordenado por fecha de publicación (más recientes primero)")
            print(f"{'#'*70}")
            
            viviendas = scraper.scrapear(url, num_paginas, ubicacion=nombre)
            
            if viviendas:
                scraper.guardar_resultados(viviendas, ubicacion=nombre, url_scrapeada=url)
            else:
                print(f"\n⚠️  No se encontraron viviendas nuevas de particulares en {nombre}")
            
            if i < total:
                delay = random.uniform(5, 10)
                print(f"\n⏳ Esperando {delay:.0f}s antes de la siguiente zona...")
                time.sleep(delay)
    finally:
        scraper.cerrar_navegador()
    
    print(f"\n\n{'='*70}")
    print(f"  ✅ BATCH COMPLETADO: {total} zonas procesadas")
    print(f"{'='*70}")


def main():
    print("""
    ╔══════════════════════════════════════════════════════╗
    ║        HOME SCRAPER - MULTI PORTAL                   ║
    ║   Scraping de viviendas de particulares             ║
    ║   Método CDP (Chrome DevTools Protocol)             ║
    ╚══════════════════════════════════════════════════════╝
    """)
    
    print("\n[!] INSTRUCCIONES RAPIDAS:")
    print("    1. Si NO has abierto Chrome con debugging:")
    print("       -> Ejecuta: start_chrome_debug.bat")
    print("       -> Espera a que Chrome se abra")
    print()
    print("    2. Si YA tienes Chrome abierto con debugging:")
    print("       -> Continúa presionando Enter")
    print()
    
    input("Presiona Enter para continuar...")
    
    # Cargar configuración
    config = cargar_config()
    if not config:
        return
    
    # ============== SELECCIÓN DE PORTAL ==============
    print("\n" + "="*70)
    print("SELECCIÓN DE PORTAL")
    print("="*70)
    
    portales = ScraperFactory.get_available_portals()
    
    print("\nPortales disponibles:")
    for idx, portal in enumerate(portales, 1):
        info = ScraperFactory.get_portal_info(portal)
        num_urls = len(config.get(portal, {}).get('urls', []))
        print(f"  {idx}. {info['name']} ({num_urls} zona(s) configurada(s))")
    
    print()
    portal_seleccionado = None
    while not portal_seleccionado:
        seleccion = input(f"Elige un portal (1-{len(portales)}): ").strip()
        
        try:
            idx = int(seleccion) - 1
            if 0 <= idx < len(portales):
                portal_seleccionado = portales[idx]
            else:
                print(f"[!] Por favor, elige un número entre 1 y {len(portales)}")
        except ValueError:
            print("[!] Por favor, introduce un número válido")
    
    info_portal = ScraperFactory.get_portal_info(portal_seleccionado)
    print(f"\n[OK] Portal seleccionado: {info_portal['name']}")
    
    # ============== SELECCIÓN DE URL ==============
    seleccion_url = seleccionar_url(portal_seleccionado, config)
    if not seleccion_url:
        return
    
    is_batch = isinstance(seleccion_url, list)
    
    # ============== CONFIGURACIÓN COMÚN ==============
    
    # Modo debug
    print("\n[?] ¿Activar modo DEBUG?")
    print("    (Mostrará cómo se detecta cada particular)")
    debug = input("    s/n (Enter = no): ").strip().lower() == 's'
    
    # Número de páginas
    print("\n[?] ¿Cuántas páginas quieres scrapear por zona?")
    print("    (Deja vacío o escribe 'todas' para procesar todas las páginas)")
    num_paginas_input = input("    Número (Enter = todas): ").strip().lower()
    
    if num_paginas_input == '' or num_paginas_input == 'todas' or num_paginas_input == 'all':
        num_paginas = None
        print("\n[*] Modo: TODAS LAS PÁGINAS (hasta detectar el final)")
    else:
        try:
            num_paginas = int(num_paginas_input)
            print(f"\n[*] Modo: {num_paginas} página(s) por zona")
        except:
            num_paginas = None
            print("\n[*] Valor no válido, usando modo: TODAS LAS PÁGINAS")
    
    # ============== FOTOCASA: ANTI-DETECCIÓN ==============
    if portal_seleccionado == 'fotocasa':
        print("\n" + "="*70)
        print("⚠️  AVISO: Fotocasa tiene detección anti-bot muy agresiva")
        print("="*70)
        print("\n[?] ¿Qué método quieres usar?")
        print("    1. Playwright Chromium (anti-detección) - RECOMENDADO")
        print("       → Abre su propio navegador")
        print("       → No necesita Chrome en modo debugging")
        print("       → Mayor probabilidad de éxito")
        print("")
        print("    2. Método CDP (Chrome debugging)")
        print("       → Usa Chrome ya abierto")
        print("       → Puede ser bloqueado fácilmente")
        print("")
        
        metodo = input("Elige método (1 o 2, Enter = 1): ").strip()
        
        if metodo != "2":
            print("\n[*] Usando Playwright Chromium...")
            
            if is_batch:
                scrapear_fotocasa_batch(seleccion_url, debug, num_paginas)
            else:
                scrapear_fotocasa_batch([seleccion_url], debug, num_paginas)
            
            print("\n✅ Scraping completado")
            input("\nPresiona Enter para salir...")
            return
    
    # ============== IDEALISTA / FOTOCASA CDP ==============
    
    # Rotación de IP (solo para CDP)
    print("\n[?] ¿Activar ROTACIÓN DE IP?")
    print("    (Te avisará cada cierto tiempo para cambiar IP y evitar captchas)")
    print("    Recomendado si usas VPN, proxy, o tienes IP dinámica")
    usar_rotacion = input("    s/n (Enter = no): ").strip().lower() == 's'
    
    vpn_provider = None
    if usar_rotacion:
        print(f"\n[OK] Rotación de IP activada (cada {PETICIONES_ANTES_CAMBIO_IP} peticiones)")
        
        from idealista_scraper import IdealistaScraper
        scraper_temp = IdealistaScraper()
        vpns_detectadas = scraper_temp.detectar_vpn_instalada()
        
        print("\n[?] ¿Quieres cambio de VPN AUTOMÁTICO?")
        print("    (Requiere tener una VPN con CLI instalada)")
        print("")
        
        if vpns_detectadas:
            print(f"    ✅ VPNs detectadas en tu sistema: {', '.join(vpns_detectadas)}")
        else:
            print("    ⚠️ No se detectaron VPNs con CLI instaladas")
            print("    (NordVPN, ExpressVPN, ProtonVPN, Surfshark, Windscribe)")
        
        print("")
        print("    Opciones:")
        print("    1. NordVPN (automático)")
        print("    2. ExpressVPN (automático)")
        print("    3. ProtonVPN (automático)")
        print("    4. Surfshark (automático)")
        print("    5. Windscribe (automático)")
        print("    6. Manual (te avisará para cambiar tú)")
        print("")
        
        vpn_opcion = input("    Elige (1-6, Enter = manual): ").strip()
        
        vpn_map = {
            '1': 'nordvpn',
            '2': 'expressvpn', 
            '3': 'protonvpn',
            '4': 'surfshark',
            '5': 'windscribe',
            '6': 'manual'
        }
        
        vpn_provider = vpn_map.get(vpn_opcion, 'manual')
        
        if vpn_provider != 'manual':
            print(f"\n[OK] VPN automática configurada: {vpn_provider}")
            print("    El scraper cambiará de servidor automáticamente")
        else:
            print("\n[OK] Modo manual: te avisará cuando debas cambiar IP")
    
    # ============== MODO BATCH O INDIVIDUAL ==============
    
    if is_batch and portal_seleccionado == 'idealista':
        # Batch mode para Idealista via CDP
        scrapear_idealista_batch(seleccion_url, debug, usar_rotacion, vpn_provider, num_paginas)
        print("\n✅ Scraping completado!")
        print("\n[!] El navegador Chrome sigue abierto. NO lo cierres si quieres seguir usándolo.")
        return
    
    # ============== MODO INDIVIDUAL (compatibilidad) ==============
    
    if is_batch:
        urls_list = seleccion_url
    else:
        urls_list = [seleccion_url]
    
    search_url = urls_list[0]['url']
    nombre = urls_list[0]['nombre']
    
    try:
        scraper = ScraperFactory.create_scraper(
            portal_seleccionado,
            modo_debug=debug,
            usar_rotacion_ip=usar_rotacion,
            vpn_provider=vpn_provider,
            search_url=search_url
        )
    except ValueError as e:
        print(f"\n[ERROR] {e}")
        return
    
    # ============== CONECTAR CHROME ==============
    
    if not scraper.conectar_chrome():
        return
    
    # ============== NAVEGACIÓN Y SCRAPING ==============
    
    print("\n[?] OPCIONES:")
    print("    1. Navegar automáticamente a la URL y scrapear")
    print("    2. Ya estoy en la página, scrapear directamente")
    
    opcion = input("\nElige (1 o 2): ").strip()
    
    if opcion == "1":
        scraper.navegar_a_url()
    
    # Scrapear
    print(f"\n[*] Iniciando scraping de {info_portal['name']}...")
    viviendas = scraper.scrapear_con_filtrado(num_paginas, ubicacion=nombre)
    
    if not viviendas:
        print("\n[!] No se encontraron viviendas de particulares")
        return
    
    # ============== GUARDAR Y MOSTRAR RESULTADOS ==============
    
    portal_name = info_portal['name'].lower().replace(' ', '_')
    filename = f"viviendas_{portal_name}_{nombre.replace(' ', '_').replace('/', '-')}.json"
    scraper.guardar(viviendas, filename, ubicacion=nombre, url_scrapeada=search_url)
    
    scraper.mostrar_resumen(viviendas)
    
    print("\n[OK] Scraping completado!")
    print(f"[OK] Archivo: {filename}")
    print("\n[!] El navegador Chrome sigue abierto. NO lo cierres si quieres seguir usándolo.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n[!] Interrumpido por el usuario")
    except Exception as e:
        print(f"\n[ERROR] {e}")
        import traceback
        traceback.print_exc()
