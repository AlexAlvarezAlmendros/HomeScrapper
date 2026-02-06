"""
HomeScraper - Scraper Multi-Portal de Viviendas
Soporta múltiples portales inmobiliarios de forma escalable
"""

import json
import os
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
    """Permite al usuario seleccionar una URL del portal"""
    if portal not in config:
        print(f"[ERROR] Portal '{portal}' no encontrado en config.json")
        return None
    
    urls_disponibles = config[portal].get('urls', [])
    
    if not urls_disponibles:
        print(f"[ERROR] No hay URLs configuradas para {portal}")
        return None
    
    if len(urls_disponibles) == 1:
        # Si solo hay una URL, usarla automáticamente
        url_data = urls_disponibles[0]
        print(f"\n[*] URL: {url_data['nombre']}")
        print(f"    {url_data.get('descripcion', '')}")
        return url_data['url']
    
    # Mostrar menú de selección
    print(f"\n{'='*70}")
    print(f"SELECCIÓN DE ZONA - {portal.upper()}")
    print('='*70)
    print("\nZonas disponibles:")
    
    for idx, url_data in enumerate(urls_disponibles, 1):
        print(f"  {idx}. {url_data['nombre']}")
        if url_data.get('descripcion'):
            print(f"     → {url_data['descripcion']}")
    
    print()
    while True:
        seleccion = input(f"Elige una zona (1-{len(urls_disponibles)}): ").strip()
        
        try:
            idx = int(seleccion) - 1
            if 0 <= idx < len(urls_disponibles):
                url_data = urls_disponibles[idx]
                print(f"\n[OK] Zona seleccionada: {url_data['nombre']}")
                return url_data['url']
            else:
                print(f"[!] Por favor, elige un número entre 1 y {len(urls_disponibles)}")
        except ValueError:
            print("[!] Por favor, introduce un número válido")


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
        # Contar cuántas URLs tiene configuradas
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
    search_url = seleccionar_url(portal_seleccionado, config)
    if not search_url:
        return
    
    print(f"[*] URL: {search_url}")
    
    # ============== CONFIGURACIÓN ==============
    
    # Modo debug
    print("\n[?] ¿Activar modo DEBUG?")
    print("    (Mostrará cómo se detecta cada particular)")
    debug = input("    s/n (Enter = no): ").strip().lower() == 's'
    
    # Rotación de IP
    print("\n[?] ¿Activar ROTACIÓN DE IP?")
    print("    (Te avisará cada cierto tiempo para cambiar IP y evitar captchas)")
    print("    Recomendado si usas VPN, proxy, o tienes IP dinámica")
    usar_rotacion = input("    s/n (Enter = no): ").strip().lower() == 's'
    
    vpn_provider = None
    if usar_rotacion:
        print(f"\n[OK] Rotación de IP activada (cada {PETICIONES_ANTES_CAMBIO_IP} peticiones)")
        
        # Detectar VPNs instaladas (usar IdealistaScraper temporalmente)
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
    
    # ============== CREAR SCRAPER ==============
    
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
    
    # Preguntar cuántas páginas
    print("\n[?] ¿Cuántas páginas quieres scrapear?")
    print("    (Deja vacío o escribe 'todas' para procesar todas las páginas)")
    num_paginas_input = input("    Número (Enter = todas): ").strip().lower()
    
    # Determinar número de páginas
    if num_paginas_input == '' or num_paginas_input == 'todas' or num_paginas_input == 'all':
        num_paginas = None
        print("\n[*] Modo: TODAS LAS PÁGINAS (hasta detectar el final)")
    else:
        try:
            num_paginas = int(num_paginas_input)
            num_paginas = min(num_paginas, 50)  # Máximo 50 por seguridad
            print(f"\n[*] Modo: {num_paginas} página(s)")
        except:
            num_paginas = None
            print("\n[*] Valor no válido, usando modo: TODAS LAS PÁGINAS")
    
    # Scrapear
    print(f"\n[*] Iniciando scraping de {info_portal['name']}...")
    viviendas = scraper.scrapear_con_filtrado(num_paginas)
    
    if not viviendas:
        print("\n[!] No se encontraron viviendas de particulares")
        return
    
    # ============== GUARDAR Y MOSTRAR RESULTADOS ==============
    
    portal_name = info_portal['name'].lower().replace(' ', '_')
    filename = f"viviendas_{portal_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    scraper.guardar(viviendas, filename)
    
    # Mostrar resumen
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
