"""
Scraper CDP configurado para tu URL específica de Idealista
Ejecuta este script después de abrir Chrome con start_chrome_debug.bat
"""

import os
import time
import json
import re
import random
import subprocess
import shutil
from datetime import datetime
from typing import List, Optional
from dataclasses import dataclass, asdict

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, NoAlertPresentException, UnexpectedAlertPresentException
from bs4 import BeautifulSoup


# ============== CONFIGURACIÓN ANTI-DETECCIÓN ==============
# Número de peticiones antes de cambiar IP (si usas proxy/VPN)
PETICIONES_ANTES_CAMBIO_IP = 15

# Delays aleatorios entre peticiones (en segundos)
DELAY_MIN_ENTRE_PAGINAS = 3
DELAY_MAX_ENTRE_PAGINAS = 7
DELAY_MIN_ENTRE_DETALLES = 2
DELAY_MAX_ENTRE_DETALLES = 5

# Delay adicional largo cada X peticiones para parecer más humano
PETICIONES_ANTES_PAUSA_LARGA = 10
PAUSA_LARGA_MIN = 15
PAUSA_LARGA_MAX = 30

# Configuración de VPN automática
# Opciones: 'nordvpn', 'expressvpn', 'protonvpn', 'surfshark', 'windscribe', 'manual', None
VPN_PROVIDER = None  # Se configura en tiempo de ejecución
# ===========================================================


@dataclass
class Vivienda:
    titulo: str
    precio: str
    ubicacion: str
    habitaciones: Optional[str]
    metros: Optional[str]
    url: str
    descripcion: Optional[str]
    anunciante: str
    fecha_scraping: str
    telefono: Optional[str] = None


# URL objetivo
URL_IDEALISTA = "https://www.idealista.com/venta-viviendas/barcelona/anoia/"


class ScraperPersonalizado:
    
    def __init__(self, modo_debug=False, usar_rotacion_ip=False, vpn_provider=None):
        self.driver = None
        self.viviendas = []
        self.modo_debug = modo_debug
        self.resultados = []
        
        # Contadores para anti-detección
        self.peticiones_realizadas = 0
        self.peticiones_desde_ultima_pausa = 0
        self.usar_rotacion_ip = usar_rotacion_ip
        self.vpn_provider = vpn_provider  # 'nordvpn', 'expressvpn', 'protonvpn', 'surfshark', 'windscribe', 'manual'
    
    def detectar_vpn_instalada(self):
        """Detecta qué VPN está instalada en el sistema"""
        vpns = {
            'nordvpn': 'nordvpn',
            'expressvpn': 'expressvpn', 
            'protonvpn': 'protonvpn',  # Comando actualizado (antes era protonvpn-cli)
            'surfshark': 'surfshark',
            'windscribe': 'windscribe'
        }
        
        detectadas = []
        for nombre, comando in vpns.items():
            if shutil.which(comando):
                detectadas.append(nombre)
        
        return detectadas
    
    def cambiar_vpn_automatico(self):
        """Cambia la conexión VPN automáticamente según el proveedor"""
        if not self.vpn_provider or self.vpn_provider == 'manual':
            return False
        
        print(f"\n🔄 Cambiando servidor VPN ({self.vpn_provider})...")
        
        try:
            if self.vpn_provider == 'nordvpn':
                # NordVPN: desconectar y reconectar a servidor aleatorio
                subprocess.run(['nordvpn', 'disconnect'], capture_output=True, timeout=30)
                time.sleep(2)
                # Conectar a países europeos aleatorios (mejor para Idealista España)
                paises = ['Spain', 'France', 'Germany', 'Italy', 'Netherlands', 'Portugal', 'Belgium']
                pais = random.choice(paises)
                result = subprocess.run(['nordvpn', 'connect', pais], capture_output=True, text=True, timeout=60)
                if 'connected' in result.stdout.lower() or result.returncode == 0:
                    print(f"   ✅ Conectado a NordVPN ({pais})")
                    return True
                    
            elif self.vpn_provider == 'expressvpn':
                # ExpressVPN
                subprocess.run(['expressvpn', 'disconnect'], capture_output=True, timeout=30)
                time.sleep(2)
                locations = ['Spain', 'France', 'Germany', 'Italy', 'Netherlands']
                location = random.choice(locations)
                result = subprocess.run(['expressvpn', 'connect', location], capture_output=True, text=True, timeout=60)
                if result.returncode == 0:
                    print(f"   ✅ Conectado a ExpressVPN ({location})")
                    return True
                    
            elif self.vpn_provider == 'protonvpn':
                # ProtonVPN (compatible con plan gratuito y de pago)
                subprocess.run(['protonvpn', 'disconnect'], capture_output=True, timeout=30)
                time.sleep(3)
                
                # Primero intentar con país aleatorio (solo funciona en plan de pago)
                paises = ['ES', 'FR', 'DE', 'IT', 'NL', 'PT', 'BE', 'CH']
                pais = random.choice(paises)
                result = subprocess.run(['protonvpn', 'connect', '--country', pais], capture_output=True, text=True, timeout=60)
                
                if result.returncode == 0:
                    print(f"   ✅ Conectado a ProtonVPN (país {pais})")
                    return True
                
                # Si falla (plan gratuito), usar conexión básica sin elegir servidor
                # El plan free solo permite 'protonvpn connect' sin opciones
                print(f"   ℹ️  Plan gratuito detectado, conectando a servidor FREE disponible...")
                result = subprocess.run(['protonvpn', 'connect'], capture_output=True, text=True, timeout=60)
                
                if result.returncode == 0:
                    # Extraer info del servidor del output
                    servidor_info = "servidor FREE"
                    if 'Connected to' in result.stdout:
                        try:
                            servidor_info = result.stdout.split('Connected to')[1].split('.')[0].strip()
                        except:
                            pass
                    print(f"   ✅ Conectado a ProtonVPN ({servidor_info})")
                    return True
                    
            elif self.vpn_provider == 'surfshark':
                # Surfshark
                subprocess.run(['surfshark', 'disconnect'], capture_output=True, timeout=30)
                time.sleep(2)
                result = subprocess.run(['surfshark', 'connect'], capture_output=True, text=True, timeout=60)
                if result.returncode == 0:
                    print(f"   ✅ Conectado a Surfshark")
                    return True
                    
            elif self.vpn_provider == 'windscribe':
                # Windscribe - usar ruta completa en Windows
                windscribe_cli = r'C:\Program Files\Windscribe\windscribe-cli.exe'
                
                # Desconectar primero
                subprocess.run([windscribe_cli, 'disconnect'], capture_output=True, timeout=30)
                time.sleep(3)
                
                # Ubicaciones disponibles en plan gratuito (europeas para mejor latencia con Idealista)
                # Nota: Las ubicaciones gratuitas varían, "best" siempre funciona
                ubicaciones = ['best', 'Paris', 'Amsterdam', 'Frankfurt', 'Zurich', 'London']
                ubicacion = random.choice(ubicaciones)
                
                result = subprocess.run([windscribe_cli, 'connect', ubicacion], capture_output=True, text=True, timeout=60)
                
                # Verificar conexión
                time.sleep(3)
                status = subprocess.run([windscribe_cli, 'status'], capture_output=True, text=True, timeout=30)
                
                if 'Conectado' in status.stdout or 'Connected' in status.stdout:
                    # Extraer nombre del servidor
                    servidor = ubicacion
                    if 'Conectado:' in status.stdout:
                        try:
                            servidor = status.stdout.split('Conectado:')[1].split('\n')[0].strip()
                        except:
                            pass
                    print(f"   ✅ Conectado a Windscribe ({servidor})")
                    return True
                else:
                    print(f"   ⚠️ No se pudo conectar")
            
            print(f"   ⚠️ No se pudo cambiar automáticamente")
            return False
            
        except subprocess.TimeoutExpired:
            print(f"   ⚠️ Timeout al cambiar VPN")
            return False
        except FileNotFoundError:
            print(f"   ⚠️ CLI de {self.vpn_provider} no encontrado")
            return False
        except Exception as e:
            print(f"   ⚠️ Error: {e}")
            return False
    
    def delay_aleatorio(self, tipo='pagina'):
        """Aplica un delay aleatorio para parecer más humano"""
        if tipo == 'pagina':
            delay = random.uniform(DELAY_MIN_ENTRE_PAGINAS, DELAY_MAX_ENTRE_PAGINAS)
        else:  # detalle
            delay = random.uniform(DELAY_MIN_ENTRE_DETALLES, DELAY_MAX_ENTRE_DETALLES)
        
        if self.modo_debug:
            print(f"      [DEBUG] Delay aleatorio: {delay:.1f}s")
        
        time.sleep(delay)
    
    def incrementar_contador_peticiones(self):
        """Incrementa contadores y gestiona pausas/cambios de IP"""
        self.peticiones_realizadas += 1
        self.peticiones_desde_ultima_pausa += 1
        
        # Pausa larga periódica para parecer más humano
        if self.peticiones_desde_ultima_pausa >= PETICIONES_ANTES_PAUSA_LARGA:
            pausa = random.uniform(PAUSA_LARGA_MIN, PAUSA_LARGA_MAX)
            print(f"\n☕ Pausa de {pausa:.0f}s para evitar detección (petición #{self.peticiones_realizadas})...")
            time.sleep(pausa)
            self.peticiones_desde_ultima_pausa = 0
        
        # Verificar si hay que cambiar IP
        if self.usar_rotacion_ip and self.peticiones_realizadas % PETICIONES_ANTES_CAMBIO_IP == 0:
            self.solicitar_cambio_ip()
    
    def solicitar_cambio_ip(self):
        """Cambia la IP automáticamente o pide al usuario que lo haga"""
        print("\n" + "="*70)
        print("🔄 CAMBIO DE IP")
        print("="*70)
        print(f"\n📊 Peticiones realizadas: {self.peticiones_realizadas}")
        
        # Intentar cambio automático si hay VPN configurada
        if self.vpn_provider and self.vpn_provider != 'manual':
            if self.cambiar_vpn_automatico():
                # Esperar a que la nueva conexión se estabilice
                print("   ⏳ Esperando 10s para estabilizar conexión...")
                time.sleep(10)
                print("[OK] IP cambiada automáticamente. Continuando...\n")
                return
            else:
                print("\n   ⚠️ Cambio automático falló. Cambia manualmente.")
        
        # Modo manual
        print("\n🌐 OPCIONES PARA CAMBIAR TU IP:")
        print("")
        print("   OPCIÓN 1 - VPN:")
        print("   • Desconecta y reconecta tu VPN a otro servidor")
        print("   • O usa la función 'cambiar servidor' de tu VPN")
        print("")
        print("   OPCIÓN 2 - Proxy en Chrome:")
        print("   • Cambia el proxy en la configuración de Chrome")
        print("   • O usa una extensión de proxy rotativo")
        print("")
        print("   OPCIÓN 3 - Router (si tienes IP dinámica):")
        print("   • Reinicia tu router para obtener nueva IP")
        print("")
        print("   OPCIÓN 4 - Continuar sin cambiar:")
        print("   • Puedes continuar, pero hay más riesgo de captcha")
        print("")
        print("⏳ El scraper está PAUSADO...")
        print("="*70)
        
        input("\n>>> Presiona Enter cuando hayas cambiado la IP (o para continuar)... ")
        print("[OK] Continuando con el scraping...\n")
    
    def detectar_captcha(self):
        """Detecta si hay un captcha en la página actual y pausa hasta que se resuelva
        
        Retorna True si se detectó y resolvió un captcha, False si no había captcha
        """
        page_source = self.driver.page_source
        page_source_lower = page_source.lower()
        current_url = self.driver.current_url.lower()
        
        captcha_detectado = False
        razon_deteccion = ""
        
        # 1. Verificar si la URL es claramente de captcha (más fiable)
        url_captcha_signals = ['geo.captcha-delivery.com', 'datadome.co', '/challenge', '/blocked']
        for signal in url_captcha_signals:
            if signal in current_url:
                captcha_detectado = True
                razon_deteccion = f"URL de captcha: {signal}"
                break
        
        # 2. Verificar si estamos en una página de DataDome (el captcha más común de Idealista)
        if not captcha_detectado:
            # DataDome muestra una página específica con estos elementos
            datadome_signals = [
                '<title>Pardon Our Interruption</title>',
                'geo.captcha-delivery.com',
                'dd.datadome.co',
                'datadome.co/captcha',
                'Please complete the security check',
                'Por favor, completa la verificación de seguridad'
            ]
            for signal in datadome_signals:
                if signal.lower() in page_source_lower:
                    captcha_detectado = True
                    razon_deteccion = f"DataDome detectado: {signal[:40]}"
                    break
        
        # 3. Verificar si hay un iframe de captcha visible
        if not captcha_detectado:
            iframe_captcha_signals = [
                'iframe[src*="captcha"]',
                'iframe[src*="recaptcha"]',
                'iframe[src*="hcaptcha"]',
                'g-recaptcha',
                'h-captcha'
            ]
            for signal in iframe_captcha_signals:
                # Buscar el elemento real, no solo texto
                if signal.startswith('iframe'):
                    if 'recaptcha' in page_source_lower and '<iframe' in page_source_lower and 'src="https://www.google.com/recaptcha' in page_source:
                        captcha_detectado = True
                        razon_deteccion = "reCAPTCHA iframe detectado"
                        break
                elif signal == 'g-recaptcha':
                    if 'class="g-recaptcha"' in page_source or "class='g-recaptcha'" in page_source:
                        captcha_detectado = True
                        razon_deteccion = "reCAPTCHA widget detectado"
                        break
                elif signal == 'h-captcha':
                    if 'class="h-captcha"' in page_source or "class='h-captcha'" in page_source:
                        captcha_detectado = True
                        razon_deteccion = "hCaptcha widget detectado"
                        break
        
        # 4. Verificar si la página está completamente vacía o bloqueada
        if not captcha_detectado:
            # Solo marcar como captcha si NO hay contenido de Idealista Y estamos en una URL extraña
            tiene_contenido_idealista = (
                'idealista.com' in current_url and
                ('class="item-link"' in page_source or 
                 'class="main-info__title"' in page_source or
                 'class="item "' in page_source or
                 'article class="item' in page_source_lower)
            )
            
            pagina_bloqueada = (
                'idealista.com' not in current_url and
                'access denied' in page_source_lower and
                len(page_source) < 5000  # Páginas de bloqueo suelen ser pequeñas
            )
            
            if pagina_bloqueada:
                captcha_detectado = True
                razon_deteccion = "Página de acceso denegado"
        
        if captcha_detectado:
            print("\n" + "="*70)
            print("⚠️  CAPTCHA DETECTADO")
            print("="*70)
            if self.modo_debug:
                print(f"    [DEBUG] Razón: {razon_deteccion}")
            print("\n🔒 Se ha detectado un captcha o verificación de seguridad.")
            print("\n📋 INSTRUCCIONES:")
            print("    1. Ve al navegador Chrome")
            print("    2. Completa el captcha manualmente")
            print("    3. Espera a que cargue la página de Idealista")
            print("    4. Vuelve aquí y presiona Enter")
            print("\n⏳ El scraper está PAUSADO esperando tu acción...")
            print("="*70)
            
            input("\n>>> Presiona Enter cuando hayas resuelto el captcha... ")
            
            # Dar tiempo para que la página cargue después del captcha
            print("\n[*] Verificando que el captcha se haya resuelto...")
            time.sleep(3)
            
            # Verificar si todavía hay captcha (recursivo)
            if self.detectar_captcha():
                return True  # Ya se manejó en la llamada recursiva
            
            print("[OK] ¡Captcha resuelto! Continuando con el scraping...\n")
            return True
        
        return False
    
    def conectar_chrome(self):
        """Conecta a Chrome abierto con debugging"""
        print("\n[*] Conectando a Chrome...")
        
        try:
            options = Options()
            options.add_experimental_option("debuggerAddress", "127.0.0.1:9222")
            
            self.driver = webdriver.Chrome(options=options)
            print(f"[OK] Conectado - URL actual: {self.driver.current_url[:80]}...")
            return True
            
        except Exception as e:
            print(f"[ERROR] No se pudo conectar: {e}")
            print("\n[!] SOLUCION:")
            print("    1. Ejecuta: start_chrome_debug.bat")
            print("    2. Espera a que Chrome se abra")
            print("    3. Vuelve a ejecutar este script")
            return False
    
    @staticmethod
    def _obtener_ruta_json_persistente(ubicacion: str, portal: str = "idealista") -> str:
        """Devuelve la ruta del JSON persistente para una ubicación.
        Ejemplo: viviendas_idealista_Igualada.json
        """
        ubicacion_limpia = ubicacion.replace(' ', '_').replace('/', '-')
        return f"viviendas_{portal}_{ubicacion_limpia}.json"
    
    @staticmethod
    def _cargar_json_existente(ruta_json: str) -> dict:
        """Carga el JSON existente y devuelve {data, urls_conocidas}.
        Si no existe, devuelve estructura vacía."""
        if not os.path.exists(ruta_json):
            return {'data': None, 'urls_conocidas': set()}
        
        try:
            with open(ruta_json, 'r', encoding='utf-8') as f:
                data = json.load(f)
            urls = {v['url'] for v in data.get('viviendas', []) if 'url' in v}
            print(f"\n📂 JSON existente cargado: {ruta_json}")
            print(f"   {len(urls)} viviendas ya registradas")
            return {'data': data, 'urls_conocidas': urls}
        except Exception as e:
            print(f"\n⚠️  Error leyendo {ruta_json}: {e}")
            return {'data': None, 'urls_conocidas': set()}
    
    @staticmethod
    def _asegurar_orden_fecha_idealista(url: str) -> str:
        """Asegura que la URL de Idealista ordena por fecha de publicación descendente."""
        param = 'ordenado-por=fecha-publicacion-desc'
        if param in url:
            return url
        if '?' in url:
            return f"{url}&{param}"
        else:
            return f"{url}?{param}"
    
    def navegar_a_url(self, url: str = None):
        """Navega a la URL de búsqueda"""
        target_url = url or URL_IDEALISTA
        print(f"\n[*] Navegando a la URL de búsqueda...")
        print(f"    {target_url[:80]}...")
        
        self.driver.get(target_url)
        print("[*] Esperando carga de página...")
        self.delay_aleatorio('pagina')
        self.incrementar_contador_peticiones()
        
        # Verificar si hay captcha
        self.detectar_captcha()
        
        # Scroll para cargar contenido (con delays aleatorios)
        print("[*] Haciendo scroll...")
        for i in range(5):
            self.driver.execute_script(f"window.scrollTo(0, {300 * (i + 1)});")
            time.sleep(random.uniform(0.3, 0.8))
        
        time.sleep(random.uniform(1, 2))
    
    def filtrar_listado_particulares(self, paginas=None, urls_conocidas=None):
        """Filtra viviendas que NO tienen logo de inmobiliaria en el listado
        
        Si paginas=None, procesa todas las páginas disponibles automáticamente.
        Si urls_conocidas contiene URLs, se detiene al encontrar un anuncio ya conocido
        (el listado se asume ordenado por fecha descendente).
        """
        print(f"\n🔍 Filtrando listado en busca de particulares...")
        if paginas is None:
            print("    Modo: TODAS LAS PÁGINAS (hasta detectar el final)")
        else:
            print(f"    Modo: {paginas} página(s)")
        
        if urls_conocidas:
            print(f"    📂 URLs ya conocidas: {len(urls_conocidas)} (se parará al encontrar una)")
        
        posibles_particulares = []
        pagina_actual = 1
        encontrado_conocido = False
        
        # Limpiar URL base: quitar parámetros, extensión .htm y paginación existente
        url_base = self.driver.current_url.split('?')[0]
        parametros = '?' + self.driver.current_url.split('?')[1] if '?' in self.driver.current_url else ''
        
        # Quitar .htm si existe
        url_base = re.sub(r'\.htm$', '', url_base)
        
        # Quitar /pagina-X si existe
        url_base = re.sub(r'/pagina-\d+', '', url_base)
        
        # Asegurar que termina sin barra
        url_base = url_base.rstrip('/')
        
        while True:
            # Si se especificó un límite de páginas, respetarlo
            if paginas is not None and pagina_actual > paginas:
                print(f"\n[*] Límite de {paginas} página(s) alcanzado")
                break
            
            print(f"\n📄 Procesando página {pagina_actual}...")
            
            # Construir URL de la página actual
            if pagina_actual == 1:
                url_pagina = f"{url_base}/{parametros}" if parametros else f"{url_base}/"
            else:
                url_pagina = f"{url_base}/pagina-{pagina_actual}.htm{parametros}"
            
            if self.modo_debug:
                print(f"    [DEBUG] URL: {url_pagina[:80]}...")
            
            # Navegar a la página
            self.driver.get(url_pagina)
            self.delay_aleatorio('pagina')
            self.incrementar_contador_peticiones()
            
            # Verificar si hay captcha después de navegar
            self.detectar_captcha()
            
            # Detectar si nos redirigió a página-1 (significa que llegamos al final)
            url_actual = self.driver.current_url
            # Verificar si contiene exactamente 'pagina-1' y no pagina-10, pagina-11, etc.
            if pagina_actual > 1:
                # Buscar pagina-1 seguido de ? o / o final de URL
                if re.search(r'pagina-1(\?|/|$)', url_actual):
                    print(f"\n✅ Detectado final del listado (redirigió a página-1)")
                    break
                
                # También verificar si la URL NO contiene pagina-{numero_actual}
                # Esto indica que Idealista nos redirigió a una página anterior
                if not re.search(rf'pagina-{pagina_actual}(\?|/|$|\.htm)', url_actual):
                    # Extraer qué página estamos realmente
                    match_pagina = re.search(r'pagina-(\d+)', url_actual)
                    if match_pagina:
                        pagina_real = int(match_pagina.group(1))
                        print(f"\n✅ Detectado final: pedimos página {pagina_actual}, redirigió a página {pagina_real}")
                    else:
                        print(f"\n✅ Detectado final: pedimos página {pagina_actual}, redirigió a página 1")
                    break
            
            # Scroll para cargar contenido (con delays aleatorios)
            for i in range(5):
                self.driver.execute_script(f"window.scrollTo(0, {300 * (i + 1)});")
                time.sleep(random.uniform(0.3, 0.8))
            
            time.sleep(random.uniform(1, 2))
            
            # Parsear con BeautifulSoup
            soup = BeautifulSoup(self.driver.page_source, 'html.parser')
            
            # Verificar si hay mensaje de "sin resultados"
            sin_resultados = soup.find('div', class_='empty-results') or \
                           soup.find('div', class_='listing-empty') or \
                           soup.find('p', string=re.compile(r'no.*encontr|sin.*resultado', re.I))
            if sin_resultados:
                print(f"\n✅ Detectado final: página sin resultados")
                break
            
            # Buscar todos los artículos de viviendas
            articulos = soup.find_all('article', class_='item')
            
            if not articulos:
                print("[!] No se encontraron artículos")
                if pagina_actual == 1:
                    # Si es la primera página y no hay artículos, es un error
                    break
                else:
                    # Si es una página posterior, probablemente llegamos al final
                    print("[*] Posiblemente llegamos al final del listado")
                    break
            
            # Verificar si estamos en la última página usando el paginador
            paginacion = soup.find('div', class_='pagination')
            if paginacion and pagina_actual > 1:
                # Buscar el botón "siguiente"
                btn_siguiente = paginacion.find('a', class_='icon-arrow-right-after')
                if not btn_siguiente:
                    print(f"\n✅ Detectado final: no hay botón 'siguiente' en página {pagina_actual}")
                    # Procesar esta página pero no continuar después
                    es_ultima_pagina = True
                else:
                    es_ultima_pagina = False
            else:
                es_ultima_pagina = False
            
            print(f"📊 Total artículos encontrados: {len(articulos)}")
            
            # Filtrar los que NO tienen logo de inmobiliaria
            posibles_en_esta_pagina = 0
            for articulo in articulos:
                # Buscar si tiene logo de marca/empresa
                tiene_logo = articulo.find('picture', class_='logo-branding')
                
                if not tiene_logo:
                    # Es posible particular - extraer ID y URL
                    element_id = articulo.get('data-element-id')
                    link = articulo.find('a', class_='item-link')
                    
                    if element_id and link:
                        url_detalle = link.get('href', '')
                        if url_detalle and not url_detalle.startswith('http'):
                            url_detalle = "https://www.idealista.com" + url_detalle
                        
                        # Comprobar si este anuncio ya está en el JSON
                        if urls_conocidas and url_detalle in urls_conocidas:
                            print(f"\n🛑 Anuncio ya conocido encontrado: {url_detalle[:60]}...")
                            print("    Deteniendo búsqueda (los siguientes ya están registrados)")
                            encontrado_conocido = True
                            break
                        
                        titulo = link.get('title', 'Sin título')
                        
                        posibles_particulares.append({
                            'id': element_id,
                            'url': url_detalle,
                            'titulo': titulo
                        })
                        
                        posibles_en_esta_pagina += 1
                        
                        if self.modo_debug:
                            print(f"      [DEBUG] ✓ Posible particular: ID {element_id}")
                else:
                    # Es una inmobiliaria, PERO debemos verificar si su URL ya está en conocidas
                    # para saber si hemos llegado a la zona de anuncios ya procesados
                    link = articulo.find('a', class_='item-link')
                    if link and urls_conocidas:
                        url_detalle = link.get('href', '')
                        if url_detalle and not url_detalle.startswith('http'):
                            url_detalle = "https://www.idealista.com" + url_detalle
                        # Solo paramos cuando hayamos encontrado al menos UNA vivienda conocida
                        # Los anuncios de inmobiliaria no están en el JSON, así que no usamos
                        # su URL para parar. Solo los de particulares.
            
            if encontrado_conocido:
                break
            
            print(f"✅ Posibles particulares en esta página: {posibles_en_esta_pagina}")
            
            # Si detectamos que es la última página, salir después de procesar
            if es_ultima_pagina:
                print(f"\n✅ Última página procesada ({pagina_actual})")
                break
            
            # Incrementar contador
            pagina_actual += 1
        
        print(f"\n📊 RESUMEN DEL FILTRADO:")
        print(f"    Páginas procesadas: {pagina_actual}")
        print(f"    TOTAL posibles particulares nuevos: {len(posibles_particulares)}")
        if encontrado_conocido:
            print(f"    🛑 Se detuvo al encontrar un anuncio ya registrado")
        return posibles_particulares
    
    def verificar_es_particular(self, url):
        """Verifica en el detalle si realmente es un particular"""
        if self.modo_debug:
            print(f"      [DEBUG] Verificando: {url[:60]}...")
        
        try:
            self.driver.get(url)
            self.delay_aleatorio('detalle')
            self.incrementar_contador_peticiones()
            
            # Verificar si hay captcha después de navegar al detalle
            self.detectar_captcha()
            
            # Parsear la página
            soup = BeautifulSoup(self.driver.page_source, 'html.parser')
            
            # Buscar el div professional-name
            prof_name = soup.find('div', class_='professional-name')
            
            if prof_name:
                # Buscar el div con class="name"
                name_div = prof_name.find('div', class_='name')
                
                if name_div:
                    texto = name_div.get_text(strip=True)
                    
                    if self.modo_debug:
                        print(f"      [DEBUG] Tipo anunciante: {texto}")
                    
                    # Si dice "Particular" es un particular
                    if 'Particular' in texto:
                        return True, 'Particular'
                    else:
                        return False, texto
            
            return False, 'no_identificado'
            
        except Exception as e:
            print(f"      [!] Error verificando {url}: {e}")
            return False, 'error'
    
    def extraer_datos_vivienda_detalle(self, url):
        """Extrae todos los datos de una vivienda desde la página de detalle"""
        try:
            soup = BeautifulSoup(self.driver.page_source, 'html.parser')
            
            datos = {
                'url': url,
                'fecha_scraping': datetime.now().isoformat()
            }
            
            # Título - Está en span.main-info__title-main
            titulo = soup.find('span', class_='main-info__title-main')
            if titulo:
                datos['titulo'] = titulo.get_text(strip=True)
            else:
                # Fallback: intentar con h1
                titulo = soup.find('h1', class_='main-info__title-main')
                if titulo:
                    datos['titulo'] = titulo.get_text(strip=True)
            
            # Precio
            precio = soup.find('span', class_='info-data-price')
            if precio:
                datos['precio'] = precio.get_text(strip=True)
            
            # Ubicación/Dirección
            direccion = soup.find('span', class_='main-info__title-minor')
            if direccion:
                datos['ubicacion'] = direccion.get_text(strip=True)
            
            # Características principales (habitaciones, metros)
            habitaciones = None
            metros = None
            
            # Buscar el div info-features que contiene los spans
            info_features = soup.find('div', class_='info-features')
            if info_features:
                # Obtener todos los spans dentro de info-features
                spans = info_features.find_all('span', recursive=False)
                for span in spans:
                    texto = span.get_text(strip=True)
                    if 'm²' in texto or 'm2' in texto:
                        metros = texto
                    elif 'hab.' in texto:
                        habitaciones = texto
            
            datos['habitaciones'] = habitaciones
            datos['metros'] = metros
            
            # Descripción
            descripcion = soup.find('div', class_='comment')
            if descripcion:
                datos['descripcion'] = descripcion.get_text(strip=True)
            
            # Anunciante
            datos['anunciante'] = 'Particular'
            
            # Teléfono - hacer click en el botón "Llamar" para revelarlo
            telefono = self._extraer_telefono_detalle()
            if telefono:
                datos['telefono'] = telefono
            
            return Vivienda(
                titulo=datos.get('titulo', 'N/A'),
                precio=datos.get('precio', 'N/A'),
                ubicacion=datos.get('ubicacion', 'N/A'),
                habitaciones=habitaciones,
                metros=metros,
                url=url,
                descripcion=datos.get('descripcion'),
                anunciante='Particular',
                fecha_scraping=datos['fecha_scraping'],
                telefono=telefono
            )
            
        except Exception as e:
            print(f"      [!] Error extrayendo datos: {e}")
            return None
    
    def _extraer_telefono_detalle(self) -> Optional[str]:
        """
        Extrae el teléfono de la página de detalle de Idealista.
        
        Estrategia multicapa:
        1. Verificar si ya hay un enlace tel: visible
        2. Inyectar interceptores (setAttribute, href setter, XHR, fetch, MutationObserver)
        3. Hacer clic JS en el botón "Llamar"
        4. Esperar y comprobar todas las fuentes de datos
        5. Segundo clic si el primero solo prepara el botón
        6. Llamada directa a API de Idealista como último recurso
        7. Validación estricta final: nunca devolver texto sin >= 7 dígitos
        """
        telefono = None
        
        try:
            # ── Paso 1: ¿Ya hay un enlace tel: visible? ──
            try:
                tel_links = self.driver.find_elements(By.CSS_SELECTOR, "a[href^='tel:']")
                for tel_link in tel_links:
                    href = tel_link.get_attribute('href')
                    if href and href.startswith('tel:') and len(href) > 6:
                        telefono = href.replace('tel:', '').strip()
                        if self.modo_debug:
                            print(f"      [DEBUG] ✓ Teléfono ya visible: {telefono}")
                        return self._validar_telefono_final(telefono)
            except:
                pass
            
            # ── Paso 2: Buscar el botón de teléfono ──
            phone_selectors = [
                "a.phone-number._mobilePhone",
                "a.phone-number.icon-phone-outline",
                "a.phone-number.icon-phone-fill",
                "a.item-clickable-phone",
                "a.see-phones-btn",
                "button.phone-btn",
                "[data-testid='phone-btn']",
            ]
            
            phone_button = None
            for selector in phone_selectors:
                try:
                    phone_button = self.driver.find_element(By.CSS_SELECTOR, selector)
                    if self.modo_debug:
                        print(f"      [DEBUG] Botón encontrado con: {selector}")
                    break
                except NoSuchElementException:
                    continue
            
            if not phone_button:
                if self.modo_debug:
                    print("      [DEBUG] No se encontró botón de teléfono")
                return None
            
            # Scroll al botón para que sea visible
            self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", phone_button)
            time.sleep(0.5)
            
            # ── Paso 3: Inyectar interceptores comprehensivos ──
            # Esto captura el número de teléfono desde MÚLTIPLES fuentes antes de 
            # que el navegador pueda intentar navegar a tel: (que causa error en Linux)
            self.driver.execute_script("""
                window.__capturedPhone = null;
                window.__phoneAjaxResponse = null;
                
                // A) Override setAttribute para interceptar href='tel:...'
                if (!window.__origSetAttribute) {
                    window.__origSetAttribute = Element.prototype.setAttribute;
                    Element.prototype.setAttribute = function(name, value) {
                        if (name === 'href' && value && typeof value === 'string' && value.startsWith('tel:')) {
                            window.__capturedPhone = value;
                            return; // NO establecer el href - previene navegación tel:
                        }
                        return window.__origSetAttribute.call(this, name, value);
                    };
                }
                
                // B) Override HTMLAnchorElement.href property setter
                if (!window.__hrefOverridden) {
                    window.__hrefOverridden = true;
                    var desc = Object.getOwnPropertyDescriptor(HTMLAnchorElement.prototype, 'href');
                    if (desc && desc.set) {
                        window.__origHrefSet = desc.set;
                        window.__origHrefGet = desc.get;
                        Object.defineProperty(HTMLAnchorElement.prototype, 'href', {
                            set: function(val) {
                                if (val && typeof val === 'string' && val.startsWith('tel:')) {
                                    window.__capturedPhone = val;
                                    return; // NO navegar
                                }
                                window.__origHrefSet.call(this, val);
                            },
                            get: function() { return window.__origHrefGet.call(this); },
                            configurable: true
                        });
                    }
                }
                
                // C) Interceptar XHR para capturar respuesta AJAX con teléfono
                if (!window.__xhrIntercepted) {
                    window.__xhrIntercepted = true;
                    var OrigOpen = XMLHttpRequest.prototype.open;
                    var OrigSend = XMLHttpRequest.prototype.send;
                    
                    XMLHttpRequest.prototype.open = function(method, url) {
                        this.__reqUrl = url;
                        return OrigOpen.apply(this, arguments);
                    };
                    
                    XMLHttpRequest.prototype.send = function() {
                        var xhr = this;
                        this.addEventListener('load', function() {
                            if (xhr.__reqUrl) {
                                var u = xhr.__reqUrl.toLowerCase();
                                if (u.includes('phone') || u.includes('contact') || 
                                    u.includes('getphones') || u.includes('telefon')) {
                                    window.__phoneAjaxResponse = xhr.responseText;
                                }
                                // Capturar CUALQUIER respuesta que contenga tel:+34
                                if (xhr.responseText && xhr.responseText.includes('tel:')) {
                                    window.__phoneAjaxResponse = xhr.responseText;
                                }
                            }
                        });
                        return OrigSend.apply(this, arguments);
                    };
                }
                
                // D) Interceptar fetch API
                if (!window.__fetchIntercepted) {
                    window.__fetchIntercepted = true;
                    var origFetch = window.fetch;
                    window.fetch = function(input, init) {
                        var url = (typeof input === 'string') ? input : (input && input.url ? input.url : '');
                        return origFetch.apply(this, arguments).then(function(response) {
                            if (url) {
                                var lower = url.toLowerCase();
                                if (lower.includes('phone') || lower.includes('contact') || 
                                    lower.includes('getphones') || lower.includes('telefon')) {
                                    response.clone().text().then(function(text) {
                                        window.__phoneAjaxResponse = text;
                                    });
                                }
                            }
                            return response;
                        });
                    };
                }
                
                // E) MutationObserver para cambios DOM
                if (window.__telObserver) {
                    try { window.__telObserver.disconnect(); } catch(e) {}
                }
                window.__telObserver = new MutationObserver(function(mutations) {
                    mutations.forEach(function(m) {
                        if (m.type === 'attributes' && m.attributeName === 'href') {
                            var href = m.target.getAttribute('href');
                            if (href && href.startsWith('tel:')) {
                                window.__capturedPhone = href;
                                m.target.removeAttribute('href');
                            }
                        }
                        if (m.type === 'childList') {
                            m.addedNodes.forEach(function(node) {
                                if (node.nodeType !== 1) return;
                                var els = [node];
                                if (node.querySelectorAll) {
                                    els = els.concat(Array.from(node.querySelectorAll('a[href^="tel:"]')));
                                }
                                els.forEach(function(el) {
                                    if (el.tagName === 'A') {
                                        var h = el.getAttribute('href');
                                        if (h && h.startsWith('tel:')) {
                                            window.__capturedPhone = h;
                                            el.removeAttribute('href');
                                        }
                                    }
                                });
                            });
                        }
                        // Observar también cambios de texto que contengan teléfonos
                        if (m.type === 'childList' || m.type === 'characterData') {
                            var target = m.target;
                            if (target && target.textContent) {
                                var match = target.textContent.match(/(\+34[\s]?[6789]\d{2}[\s]?\d{3}[\s]?\d{3})/);
                                if (!match) match = target.textContent.match(/([6789]\d{2}[\s]?\d{2}[\s]?\d{2}[\s]?\d{2})/);
                                if (match && !window.__capturedPhone) {
                                    window.__capturedPhone = 'tel:' + match[1];
                                }
                            }
                        }
                    });
                });
                window.__telObserver.observe(document.body, {
                    attributes: true, childList: true, subtree: true,
                    characterData: true, attributeFilter: ['href']
                });
                
                // F) Interceptor de clics en fase de captura
                if (window.__telClickHandler) {
                    document.removeEventListener('click', window.__telClickHandler, true);
                }
                window.__telClickHandler = function(e) {
                    var a = e.target.closest ? e.target.closest('a') : e.target;
                    if (a && a.getAttribute) {
                        var href = a.getAttribute('href');
                        if (href && href.startsWith('tel:')) {
                            window.__capturedPhone = href;
                            e.preventDefault();
                            e.stopPropagation();
                            e.stopImmediatePropagation();
                            a.removeAttribute('href');
                        }
                    }
                };
                document.addEventListener('click', window.__telClickHandler, true);
            """)
            
            if self.modo_debug:
                print("      [DEBUG] Interceptores inyectados, haciendo clic...")
            
            # ── Paso 4: Primer clic usando JavaScript ──
            telefono = self._hacer_clic_y_capturar(phone_button)
            
            # ── Paso 5: Segundo clic si el primero no devolvió teléfono ──
            # Idealista a veces necesita dos clics: primero carga datos, segundo revela
            if not telefono:
                if self.modo_debug:
                    print("      [DEBUG] Primer clic sin resultado, intentando segundo clic...")
                time.sleep(1)
                # Re-buscar el botón (puede haber sido reemplazado por AJAX)
                phone_button2 = None
                for selector in phone_selectors:
                    try:
                        phone_button2 = self.driver.find_element(By.CSS_SELECTOR, selector)
                        break
                    except NoSuchElementException:
                        continue
                if phone_button2:
                    telefono = self._hacer_clic_y_capturar(phone_button2)
            
            # ── Paso 6: Último recurso - llamada directa a API de Idealista ──
            if not telefono:
                telefono = self._intentar_api_telefono_directa()
            
            # ── Limpieza de interceptores ──
            try:
                self.driver.execute_script("""
                    if (window.__telObserver) window.__telObserver.disconnect();
                    if (window.__telClickHandler) {
                        document.removeEventListener('click', window.__telClickHandler, true);
                    }
                    // Restaurar setAttribute
                    if (window.__origSetAttribute) {
                        Element.prototype.setAttribute = window.__origSetAttribute;
                        window.__origSetAttribute = null;
                    }
                    // Restaurar href setter
                    if (window.__origHrefSet) {
                        Object.defineProperty(HTMLAnchorElement.prototype, 'href', {
                            set: window.__origHrefSet,
                            get: window.__origHrefGet,
                            configurable: true
                        });
                        window.__origHrefSet = null;
                    }
                """)
            except:
                pass
                    
        except UnexpectedAlertPresentException:
            try:
                alert = self.driver.switch_to.alert
                alert_text = alert.text
                alert.accept()
                telefono = self._extraer_telefono_de_texto(alert_text)
                if self.modo_debug and telefono:
                    print(f"      [DEBUG] ✓ Teléfono del alert inesperado: {telefono}")
            except:
                pass
                
        except Exception as e:
            if self.modo_debug:
                print(f"      [DEBUG] Error extrayendo teléfono: {e}")
        
        # ── Paso 7: Validación final estricta ──
        return self._validar_telefono_final(telefono)
    
    def _hacer_clic_y_capturar(self, phone_button) -> Optional[str]:
        """Hace clic en el botón de teléfono y comprueba todas las fuentes de captura."""
        try:
            # Dispatch eventos completos de ratón (mousedown, mouseup, click)
            # Algunos frameworks solo escuchan mousedown/pointerdown, no click
            self.driver.execute_script("""
                var btn = arguments[0];
                var rect = btn.getBoundingClientRect();
                var x = rect.left + rect.width / 2;
                var y = rect.top + rect.height / 2;
                
                ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click'].forEach(function(type) {
                    var evt = new MouseEvent(type, {
                        bubbles: true, cancelable: true, view: window,
                        clientX: x, clientY: y,
                        button: 0, buttons: 1
                    });
                    btn.dispatchEvent(evt);
                });
            """, phone_button)
        except UnexpectedAlertPresentException:
            try:
                alert = self.driver.switch_to.alert
                alert_text = alert.text
                alert.accept()
                telefono = self._extraer_telefono_de_texto(alert_text)
                if telefono:
                    if self.modo_debug:
                        print(f"      [DEBUG] ✓ Teléfono del alert: {telefono}")
                    return telefono
            except:
                pass
        except Exception as e:
            if self.modo_debug:
                print(f"      [DEBUG] Error en clic: {e}")
        
        # Esperar y comprobar todas las fuentes de captura
        for intento in range(8):
            time.sleep(0.5)
            
            # A) Teléfono capturado por interceptores (setAttribute, href setter, Observer, click)
            captured = self.driver.execute_script("return window.__capturedPhone;")
            if captured:
                telefono = captured.replace('tel:', '').strip()
                if self.modo_debug:
                    print(f"      [DEBUG] ✓ Teléfono capturado por interceptor: {telefono}")
                return self._validar_telefono_final(telefono)
            
            # B) Respuesta AJAX interceptada
            ajax_resp = self.driver.execute_script("return window.__phoneAjaxResponse;")
            if ajax_resp:
                telefono = self._extraer_telefono_de_texto(ajax_resp)
                if telefono:
                    if self.modo_debug:
                        print(f"      [DEBUG] ✓ Teléfono del AJAX: {telefono}")
                    return telefono
            
            # C) Enlaces tel: en el DOM
            try:
                tel_links = self.driver.find_elements(By.CSS_SELECTOR, "a[href^='tel:']")
                for tl in tel_links:
                    href = tl.get_attribute('href')
                    if href and href.startswith('tel:') and len(href) > 6:
                        telefono = href.replace('tel:', '').strip()
                        if self.modo_debug:
                            print(f"      [DEBUG] ✓ Teléfono del href DOM: {telefono}")
                        return self._validar_telefono_final(telefono)
            except:
                pass
            
            # D) Texto visible que parezca teléfono (después de esperar un poco)
            if intento >= 3:
                try:
                    # Buscar cualquier elemento que contenga un número de teléfono visible
                    phone_text = self.driver.execute_script("""
                        // Buscar en spans y enlaces cerca del botón de teléfono
                        var selectors = [
                            'span.hidden-contact-phones_text',
                            '.phone-number span',
                            '.see-phones-btn span',
                            '.phone-details span',
                            'a.phone-number'
                        ];
                        for (var i = 0; i < selectors.length; i++) {
                            var els = document.querySelectorAll(selectors[i]);
                            for (var j = 0; j < els.length; j++) {
                                var text = els[j].textContent.trim();
                                // Solo devolver si tiene al menos 7 dígitos
                                var digits = text.replace(/[^0-9]/g, '');
                                if (digits.length >= 7) {
                                    return text;
                                }
                            }
                        }
                        return null;
                    """)
                    if phone_text:
                        telefono = self._extraer_telefono_de_texto(phone_text)
                        if telefono:
                            if self.modo_debug:
                                print(f"      [DEBUG] ✓ Teléfono del texto visible: {telefono}")
                            return telefono
                except:
                    pass
        
        if self.modo_debug:
            print("      [DEBUG] No se pudo capturar teléfono tras clic")
        return None
    
    def _intentar_api_telefono_directa(self) -> Optional[str]:
        """Intenta obtener el teléfono directamente de la API de Idealista."""
        try:
            current_url = self.driver.current_url
            # Extraer ID del inmueble de la URL: /inmueble/12345678/
            id_match = re.search(r'/inmueble/(\d+)', current_url)
            if not id_match:
                id_match = re.search(r'/(\d{6,})/', current_url)
            
            if not id_match:
                if self.modo_debug:
                    print("      [DEBUG] No se pudo extraer ID del inmueble de la URL")
                return None
            
            prop_id = id_match.group(1)
            if self.modo_debug:
                print(f"      [DEBUG] Intentando API directa para inmueble {prop_id}...")
            
            # Probar varios endpoints conocidos de Idealista
            phone_response = self.driver.execute_script("""
                var id = arguments[0];
                var endpoints = [
                    '/es/ajax/ads/' + id + '/contact/phones',
                    '/ajax/listingController/phoneAction.ajax?adId=' + id,
                    '/ajax/ads/' + id + '/phones',
                    '/es/ajax/listingController/phoneAction.ajax?adId=' + id
                ];
                for (var i = 0; i < endpoints.length; i++) {
                    try {
                        var xhr = new XMLHttpRequest();
                        xhr.open('GET', endpoints[i], false);
                        xhr.setRequestHeader('X-Requested-With', 'XMLHttpRequest');
                        xhr.send();
                        if (xhr.status === 200 && xhr.responseText && xhr.responseText.length > 2) {
                            return {url: endpoints[i], status: xhr.status, body: xhr.responseText};
                        }
                    } catch(e) {}
                    // Intentar también con POST
                    try {
                        var xhr2 = new XMLHttpRequest();
                        xhr2.open('POST', endpoints[i], false);
                        xhr2.setRequestHeader('X-Requested-With', 'XMLHttpRequest');
                        xhr2.setRequestHeader('Content-Type', 'application/x-www-form-urlencoded');
                        xhr2.send();
                        if (xhr2.status === 200 && xhr2.responseText && xhr2.responseText.length > 2) {
                            return {url: endpoints[i], status: xhr2.status, body: xhr2.responseText};
                        }
                    } catch(e) {}
                }
                return null;
            """, prop_id)
            
            if phone_response and phone_response.get('body'):
                body = phone_response['body']
                if self.modo_debug:
                    print(f"      [DEBUG] API respondió ({phone_response.get('url')}): {body[:200]}")
                
                # Intentar extraer teléfono del JSON o texto de respuesta
                telefono = self._extraer_telefono_de_texto(body)
                if telefono:
                    if self.modo_debug:
                        print(f"      [DEBUG] ✓ Teléfono de API directa: {telefono}")
                    return telefono
                
                # Intentar parsear como JSON
                try:
                    import json
                    data = json.loads(body)
                    # Buscar recursivamente campos que parezcan teléfono
                    telefono = self._buscar_telefono_en_json(data)
                    if telefono:
                        if self.modo_debug:
                            print(f"      [DEBUG] ✓ Teléfono de API JSON: {telefono}")
                        return telefono
                except:
                    pass
                    
        except Exception as e:
            if self.modo_debug:
                print(f"      [DEBUG] Error en API directa: {e}")
        
        return None
    
    def _buscar_telefono_en_json(self, data) -> Optional[str]:
        """Busca recursivamente un teléfono en una estructura JSON."""
        if isinstance(data, str):
            return self._extraer_telefono_de_texto(data)
        elif isinstance(data, dict):
            for key, value in data.items():
                key_lower = key.lower()
                if 'phone' in key_lower or 'telefon' in key_lower or 'tel' == key_lower or 'mobile' in key_lower:
                    if isinstance(value, str):
                        telefono = self._extraer_telefono_de_texto(value)
                        if not telefono:
                            # Puede ser directamente el número
                            digitos = re.sub(r'[^\d]', '', value)
                            if len(digitos) >= 7:
                                return value.strip()
                        return telefono
                # Recurrir en valores
                result = self._buscar_telefono_en_json(value)
                if result:
                    return result
        elif isinstance(data, list):
            for item in data:
                result = self._buscar_telefono_en_json(item)
                if result:
                    return result
        return None
    
    def _validar_telefono_final(self, telefono: Optional[str]) -> Optional[str]:
        """
        Validación final estricta: NUNCA devolver texto que no sea un teléfono real.
        Requiere al menos 7 dígitos para considerarlo un número válido.
        """
        if not telefono:
            return None
        
        digitos = re.sub(r'[^\d]', '', telefono)
        if len(digitos) < 7:
            if self.modo_debug:
                print(f"      [DEBUG] ✗ Rechazado (no es teléfono): '{telefono}' ({len(digitos)} dígitos)")
            return None
        
        return telefono

    def _extraer_telefono_de_texto(self, texto: str) -> Optional[str]:
        """Extrae un número de teléfono de un texto usando regex"""
        if not texto:
            return None
        
        phone_patterns = [
            r'\+34[\s]?[6789]\d{2}[\s]?\d{3}[\s]?\d{3}',  # +34 6XX XXX XXX
            r'[6789]\d{2}[\s]?\d{2}[\s]?\d{2}[\s]?\d{2}',  # 6XX XX XX XX
            r'[6789]\d{2}[\s]?\d{3}[\s]?\d{3}',            # 6XX XXX XXX
            r'\d{3}[\s]?\d{3}[\s]?\d{3}',                  # XXX XXX XXX
            r'\d{9}',                                        # 9 dígitos seguidos
        ]
        
        for pattern in phone_patterns:
            match = re.search(pattern, texto)
            if match:
                return match.group(0).strip()
        
        return None
    
    def scrapear_con_filtrado(self, paginas=None, ubicacion=None):
        """Método NUEVO: Scrapea usando el filtrado de dos etapas
        
        Si paginas=None, procesa todas las páginas disponibles.
        Carga el JSON persistente de la ubicación y para al encontrar un anuncio ya conocido.
        """
        print("\n" + "="*70)
        print("🏠 SCRAPER CON FILTRADO - SOLO PARTICULARES")
        print("="*70)
        
        # Cargar JSON existente para esta ubicación
        urls_conocidas = set()
        if ubicacion:
            ruta_json = self._obtener_ruta_json_persistente(ubicacion)
            json_existente = self._cargar_json_existente(ruta_json)
            urls_conocidas = json_existente['urls_conocidas']
            if not urls_conocidas:
                print("    📋 No hay datos previos, se hará búsqueda completa")
        
        # Paso 1: Filtrar en el listado (pasando URLs conocidas)
        posibles = self.filtrar_listado_particulares(paginas, urls_conocidas=urls_conocidas)
        
        if not posibles:
            if urls_conocidas:
                print("\n✅ No hay viviendas nuevas desde la última búsqueda")
            else:
                print("\n❌ No se encontraron posibles particulares")
            return []
        
        # Paso 2: Verificar cada uno en detalle
        print(f"\n🔎 Verificando {len(posibles)} viviendas en detalle...")
        print("="*70)
        
        confirmados = 0
        todas_viviendas = []
        
        for idx, vivienda_info in enumerate(posibles, 1):
            print(f"\n[{idx}/{len(posibles)}] Verificando ID {vivienda_info['id']}...")
            print(f"    {vivienda_info['titulo'][:60]}...")
            
            es_particular, tipo = self.verificar_es_particular(vivienda_info['url'])
            
            if es_particular:
                print(f"    ✅ CONFIRMADO: Particular")
                
                # Extraer datos completos (ya estamos en la página de detalle)
                vivienda = self.extraer_datos_vivienda_detalle(vivienda_info['url'])
                
                if vivienda:
                    todas_viviendas.append(vivienda)
                    confirmados += 1
                    
                    # Mostrar resumen
                    print(f"       📍 {vivienda.ubicacion}")
                    print(f"       💰 {vivienda.precio}")
                    if vivienda.habitaciones or vivienda.metros:
                        print(f"       🏠 {vivienda.habitaciones or 'N/A'} | {vivienda.metros or 'N/A'}")
            else:
                print(f"    ❌ No es particular: {tipo}")
        
        # Resumen final
        print("\n" + "="*70)
        print("📊 RESUMEN FINAL")
        print("="*70)
        print(f"Posibles particulares (listado): {len(posibles)}")
        print(f"Confirmados como particulares:   {confirmados}")
        print(f"Descartados (empresas):          {len(posibles) - confirmados}")
        
        return todas_viviendas
    
    def es_particular(self, html_texto: str) -> tuple[bool, str]:
        """
        Detecta si es particular usando múltiples señales
        Retorna: (es_particular: bool, tipo: str)
        """
        texto = html_texto.lower()
        
        # Puntuación para determinar tipo
        score = 0
        
        # === SEÑALES DE PARTICULAR (suma puntos) ===
        
        # Palabras clave fuertes (+3 puntos cada una)
        palabras_particular_fuertes = [
            'particular',
            'propietario',
            'dueño directo',
            'vendo mi piso',
            'vendo mi casa',
            'sin comisión',
            'sin intermediarios',
            'trato directo',
            'abstenerse agencias',
            'no agencias'
        ]
        for palabra in palabras_particular_fuertes:
            if palabra in texto:
                score += 3
                if self.modo_debug:
                    print(f"      [DEBUG] +3 por '{palabra}'")
        
        # Palabras clave medias (+2 puntos)
        palabras_particular_medias = [
            'vendo',
            'vendedor',
            'contacto directo',
            'llamar al propietario'
        ]
        for palabra in palabras_particular_medias:
            if palabra in texto:
                score += 2
                if self.modo_debug:
                    print(f"      [DEBUG] +2 por '{palabra}'")
        
        # === SEÑALES DE INMOBILIARIA (resta puntos) ===
        
        # Palabras clave muy fuertes (-4 puntos cada una)
        palabras_inmobiliaria_fuertes = [
            'inmobiliaria',
            'agencia',
            'real estate',
            'professional',
            'red inmobiliaria',
            'grupo inmobiliario',
            'consultoría inmobiliaria',
            'franquicia',
            'remax',
            'century 21',
            'engel',
            'tecnocasa',
            'comprarcasa',
            'donpiso'
        ]
        for palabra in palabras_inmobiliaria_fuertes:
            if palabra in texto:
                score -= 4
                if self.modo_debug:
                    print(f"      [DEBUG] -4 por '{palabra}'")
        
        # Palabras medias (-2 puntos)
        palabras_inmobiliaria_medias = [
            'honorarios',
            'comisión del',
            'nuestros servicios',
            'visítenos',
            'cartera de',
            'profesional del sector',
            'años de experiencia',
            'equipo de profesionales'
        ]
        for palabra in palabras_inmobiliaria_medias:
            if palabra in texto:
                score -= 2
                if self.modo_debug:
                    print(f"      [DEBUG] -2 por '{palabra}'")
        
        # === ANÁLISIS DE CLASES CSS ===
        
        # Idealista marca con clases específicas
        if 'professional-contact' in texto:
            score -= 5
            if self.modo_debug:
                print(f"      [DEBUG] -5 por clase 'professional-contact'")
        
        if 'professional-logo' in texto:
            score -= 5
            if self.modo_debug:
                print(f"      [DEBUG] -5 por clase 'professional-logo'")
        
        if 'owner-contact' in texto or 'particular-contact' in texto:
            score += 5
            if self.modo_debug:
                print(f"      [DEBUG] +5 por clase de particular")
        
        # === ANÁLISIS DEL NOMBRE DEL ANUNCIANTE ===
        
        # Buscar el nombre del anunciante en el HTML
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html_texto, 'html.parser')
        
        # Buscar diferentes selectores donde aparece el anunciante
        anunciante_elem = (
            soup.find('div', class_='advertiser-name') or
            soup.find('span', class_='professional-name') or
            soup.find('div', class_='item-multimedia-container')
        )
        
        if anunciante_elem:
            nombre_anunciante = anunciante_elem.get_text(strip=True).lower()
            
            # Si el nombre parece una empresa
            if any(palabra in nombre_anunciante for palabra in ['s.l.', 's.a.', 'inmobiliaria', 'properties', 'homes', 'real estate']):
                score -= 6
                if self.modo_debug:
                    print(f"      [DEBUG] -6 por nombre empresarial: {nombre_anunciante[:30]}")
            
            # Si parece nombre de persona
            elif len(nombre_anunciante.split()) <= 3 and nombre_anunciante.replace(' ', '').isalpha():
                score += 3
                if self.modo_debug:
                    print(f"      [DEBUG] +3 por nombre personal: {nombre_anunciante}")
        
        # === DECISIÓN FINAL ===
        
        if self.modo_debug:
            print(f"      [DEBUG] Score final: {score}")
        
        if score >= 3:
            return True, "Particular"
        elif score <= -3:
            return False, "Inmobiliaria"
        else:
            # Zona gris - revisar manualmente
            return False, "Desconocido" if score == 0 else f"Incierto (score: {score})"
    
    def extraer_vivienda(self, articulo) -> Optional[Vivienda]:
        """Extrae datos de un artículo"""
        try:
            # Título y URL
            link = articulo.find('a', class_='item-link')
            if not link:
                return None
            
            titulo = link.get_text(strip=True)
            url = link.get('href', '')
            if url and not url.startswith('http'):
                url = f"https://www.idealista.com{url}"
            
            # Precio
            precio_elem = articulo.find('span', class_='item-price')
            precio = precio_elem.get_text(strip=True) if precio_elem else "N/A"
            
            # Ubicación
            ubicacion_elem = articulo.find('span', class_='item-detail')
            ubicacion = ubicacion_elem.get_text(strip=True) if ubicacion_elem else "N/A"
            
            # Detalles (habitaciones, metros)
            detalles = articulo.find_all('span', class_='item-detail')
            habitaciones = None
            metros = None
            
            for detalle in detalles:
                texto = detalle.get_text(strip=True)
                if 'hab' in texto.lower():
                    habitaciones = texto
                elif 'm²' in texto or 'm2' in texto:
                    metros = texto
            
            # Descripción
            desc_elem = articulo.find('div', class_='item-description')
            descripcion = desc_elem.get_text(strip=True) if desc_elem else None
            
            # Determinar tipo de anunciante
            es_part, tipo_anunciante = self.es_particular(str(articulo))
            
            return Vivienda(
                titulo=titulo,
                precio=precio,
                ubicacion=ubicacion,
                habitaciones=habitaciones,
                metros=metros,
                url=url,
                descripcion=descripcion,
                anunciante=tipo_anunciante,
                fecha_scraping=datetime.now().isoformat()
            )
            
        except Exception as e:
            print(f"[DEBUG] Error extrayendo vivienda: {e}")
            return None
    
    def scrapear_pagina(self) -> List[Vivienda]:
        """Scrapea la página actual"""
        print("\n[*] Analizando página...")
        
        soup = BeautifulSoup(self.driver.page_source, 'html.parser')
        
        # Buscar artículos
        articulos = soup.find_all('article', class_='item')
        
        if not articulos:
            print("[!] No se encontraron artículos con selector 'article.item'")
            # Intentar selector alternativo
            articulos = soup.find_all('div', class_='item-info-container')
            print(f"[*] Intentando selector alternativo: {len(articulos)} encontrados")
        
        print(f"[*] Total de anuncios encontrados: {len(articulos)}")
        
        viviendas = []
        particulares_count = 0
        inmobiliarias_count = 0
        
        for idx, articulo in enumerate(articulos, 1):
            vivienda = self.extraer_vivienda(articulo)
            if vivienda:
                viviendas.append(vivienda)
                
                if vivienda.anunciante == "Particular":
                    particulares_count += 1
                    print(f"  [{idx}] PARTICULAR: {vivienda.titulo[:60]}...")
                    print(f"       {vivienda.precio} - {vivienda.ubicacion[:40]}")
                elif vivienda.anunciante == "Inmobiliaria":
                    inmobiliarias_count += 1
        
        print(f"\n[RESUMEN]")
        print(f"  Total anuncios: {len(viviendas)}")
        print(f"  Particulares: {particulares_count}")
        print(f"  Inmobiliarias: {inmobiliarias_count}")
        
        return viviendas
    
    def scrapear_multiples_paginas(self, max_paginas: int = 3):
        """Scrapea múltiples páginas"""
        todas = []
        
        for pagina in range(1, max_paginas + 1):
            print(f"\n{'='*70}")
            print(f"PAGINA {pagina}/{max_paginas}")
            print(f"{'='*70}")
            
            viviendas = self.scrapear_pagina()
            todas.extend(viviendas)
            
            if pagina < max_paginas:
                # Buscar botón siguiente
                try:
                    next_btn = self.driver.find_element(By.XPATH, "//a[contains(@class, 'icon-arrow-right-after')]")
                    print(f"\n[*] Navegando a página {pagina + 1}...")
                    next_btn.click()
                    self.delay_aleatorio('pagina')
                    self.incrementar_contador_peticiones()
                    
                    # Verificar si hay captcha después de navegar
                    self.detectar_captcha()
                except:
                    print(f"\n[!] No se encontró botón 'siguiente'. Terminando en página {pagina}.")
                    break
        
        return todas
    
    def guardar(self, viviendas: List[Vivienda], ubicacion: str, url_scrapeada: str, filename: str = None):
        """Guarda en JSON persistente por ubicación, fusionando con datos existentes.
        
        Los nuevos registros se añaden al principio (más recientes primero).
        Si no hay viviendas nuevas, no modifica el archivo.
        """
        # Solo guardar particulares
        particulares_nuevos = [v for v in viviendas if v.anunciante == "Particular"]
        
        # Determinar ruta del archivo
        if not filename:
            filename = self._obtener_ruta_json_persistente(ubicacion)
        
        # Cargar datos existentes
        viviendas_existentes = []
        if os.path.exists(filename):
            try:
                with open(filename, 'r', encoding='utf-8') as f:
                    data_existente = json.load(f)
                viviendas_existentes = data_existente.get('viviendas', [])
                print(f"\n📂 Cargando JSON existente: {len(viviendas_existentes)} registros previos")
            except Exception as e:
                print(f"\n⚠️  Error leyendo JSON existente: {e}")
        
        # Fusionar: nuevos al principio, existentes después (sin duplicados)
        urls_nuevas = {asdict(v)['url'] for v in particulares_nuevos}
        
        # Filtrar existentes que no estén duplicados con los nuevos
        existentes_filtrados = [v for v in viviendas_existentes if v.get('url') not in urls_nuevas]
        
        # Combinar: nuevos primero + existentes después
        todas_viviendas = [asdict(v) for v in particulares_nuevos] + existentes_filtrados
        
        data = {
            'timestamp': datetime.now().isoformat(),
            'ubicacion': ubicacion,
            'url': url_scrapeada,
            'total': len(todas_viviendas),
            'viviendas': todas_viviendas
        }
        
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        print(f"\n[OK] Guardado en: {filename}")
        print(f"     Nuevos añadidos: {len(particulares_nuevos)}")
        print(f"     Total registros: {len(todas_viviendas)}")
        return filename
    
    def mostrar_resumen(self, viviendas: List[Vivienda]):
        """Muestra resumen final"""
        particulares = [v for v in viviendas if v.anunciante == "Particular"]
        
        print(f"\n{'='*70}")
        print(f"RESUMEN FINAL: {len(particulares)} VIVIENDAS DE PARTICULARES")
        print(f"{'='*70}\n")
        
        for i, v in enumerate(particulares[:20], 1):
            print(f"{i}. {v.titulo}")
            print(f"   Precio: {v.precio}")
            print(f"   Ubicacion: {v.ubicacion}")
            if v.habitaciones or v.metros:
                print(f"   Detalles: {v.habitaciones or ''} {v.metros or ''}")
            print(f"   URL: {v.url}")
            print()
        
        if len(particulares) > 20:
            print(f"... y {len(particulares) - 20} particulares más\n")


def cargar_urls_idealista(config_file: str = "config.json") -> list:
    """Carga las URLs de Idealista desde config.json"""
    try:
        with open(config_file, 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        if 'idealista' in config and 'urls' in config['idealista']:
            return config['idealista']['urls']
        return []
    except:
        return []


def main():
    print("""
    ╔══════════════════════════════════════════════════════╗
    ║   SCRAPER PERSONALIZADO - TU BÚSQUEDA IDEALISTA     ║
    ║   Método CDP (Chrome DevTools Protocol)            ║
    ║   + FILTRADO DE PARTICULARES                        ║
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
    
    # Preguntar por modo debug
    print("\n[?] ¿Activar modo DEBUG?")
    print("    (Mostrará cómo se detecta cada particular)")
    debug = input("    s/n (Enter = no): ").strip().lower() == 's'
    
    # Preguntar por rotación de IP
    print("\n[?] ¿Activar ROTACIÓN DE IP?")
    print("    (Te avisará cada cierto tiempo para cambiar IP y evitar captchas)")
    print("    Recomendado si usas VPN, proxy, o tienes IP dinámica")
    usar_rotacion = input("    s/n (Enter = no): ").strip().lower() == 's'
    
    vpn_provider = None
    if usar_rotacion:
        print(f"\n[OK] Rotación de IP activada (cada {PETICIONES_ANTES_CAMBIO_IP} peticiones)")
        
        # Detectar VPNs instaladas
        scraper_temp = ScraperPersonalizado()
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
    
    scraper = ScraperPersonalizado(modo_debug=debug, usar_rotacion_ip=usar_rotacion, vpn_provider=vpn_provider)
    
    # Conectar
    if not scraper.conectar_chrome():
        return
    
    # Cargar URLs de config.json
    urls_config = cargar_urls_idealista()
    url_seleccionada = None
    ubicacion_seleccionada = "Manual"
    
    # Preguntar qué hacer
    print("\n[?] OPCIONES:")
    print("    1. Seleccionar URL de config.json y scrapear CON FILTRADO (recomendado)")
    print("    2. Introducir URL manualmente y scrapear CON FILTRADO")
    print("    3. Ya estoy en la página, scrapear CON FILTRADO")
    print("    4. Ya estoy en la página, scrapear sin filtrado (método antiguo)")
    
    opcion = input("\nElige (1, 2, 3 o 4): ").strip()
    
    if opcion == "1":
        if not urls_config:
            print("\n[!] No hay URLs en config.json. Usando método manual.")
            opcion = "2"
        else:
            print("\nURLs disponibles:")
            for i, item in enumerate(urls_config, 1):
                print(f"    {i}. {item.get('nombre', 'Sin nombre')}")
            
            seleccion = input("\nSelecciona número: ").strip()
            try:
                idx = int(seleccion) - 1
                if 0 <= idx < len(urls_config):
                    url_seleccionada = ScraperPersonalizado._asegurar_orden_fecha_idealista(urls_config[idx]['url'])
                    ubicacion_seleccionada = urls_config[idx].get('nombre', 'Sin nombre')
                    print(f"\n[OK] Seleccionado: {ubicacion_seleccionada}")
                    print(f"    📅 Ordenado por fecha de publicación (más recientes primero)")
                    scraper.navegar_a_url(url_seleccionada)
                else:
                    print("[!] Índice inválido")
                    return
            except:
                print("[!] Selección inválida")
                return
    
    if opcion == "2":
        url_manual = input("\nIntroduce la URL de Idealista: ").strip()
        ubicacion_seleccionada = input("Nombre/ubicación para esta búsqueda: ").strip() or "Manual"
        url_seleccionada = ScraperPersonalizado._asegurar_orden_fecha_idealista(url_manual)
        print(f"    📅 Ordenado por fecha de publicación (más recientes primero)")
        scraper.navegar_a_url(url_seleccionada)
    
    # Si ya está en la página (opciones 3 o 4), obtener URL actual
    if opcion in ["3", "4"]:
        url_seleccionada = scraper.driver.current_url
        ubicacion_seleccionada = input("\nNombre/ubicación para esta búsqueda: ").strip() or "Manual"
    
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
    
    # Scrapear según opción elegida
    if num_paginas is None:
        print(f"[*] Iniciando scraping de TODAS las páginas...")
    else:
        print(f"[*] Iniciando scraping de {num_paginas} página(s)...")
    
    if opcion == "4":
        # Método antiguo (sin filtrado)
        print("\n[!] Usando método antiguo (detecta particulares por palabras clave)")
        # El método antiguo requiere un número específico
        if num_paginas is None:
            num_paginas = 10  # Default para método antiguo
            print(f"    Limitando a {num_paginas} páginas para método antiguo")
        
        if num_paginas == 1:
            viviendas = scraper.scrapear_pagina()
        else:
            viviendas = scraper.scrapear_multiples_paginas(num_paginas)
    else:
        # Método nuevo (con filtrado de dos etapas)
        print("\n[!] Usando método con FILTRADO (verifica en detalle)")
        viviendas = scraper.scrapear_con_filtrado(num_paginas, ubicacion=ubicacion_seleccionada)
    
    if not viviendas:
        print("\n[!] No se encontraron viviendas")
        return
    
    # Guardar resultado final
    scraper.guardar(viviendas, ubicacion=ubicacion_seleccionada, url_scrapeada=url_seleccionada)
    
    # Mostrar resumen
    scraper.mostrar_resumen(viviendas)
    
    print("\n[OK] Scraping completado!")
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
