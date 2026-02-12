"""
Clase base abstracta para scrapers de portales inmobiliarios
Proporciona funcionalidad común anti-detección, rotación de IP y estructura base
"""

import os
import json
import time
import random
import subprocess
import shutil
import urllib.request
from abc import ABC, abstractmethod
from typing import List, Optional, Any
from dataclasses import dataclass, asdict
from datetime import datetime

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.common.exceptions import WebDriverException, TimeoutException


# ============== CONFIGURACIÓN ANTI-DETECCIÓN ==============
PETICIONES_ANTES_CAMBIO_IP = 15
DELAY_MIN_ENTRE_PAGINAS = 3
DELAY_MAX_ENTRE_PAGINAS = 7
DELAY_MIN_ENTRE_DETALLES = 2
DELAY_MAX_ENTRE_DETALLES = 5
PETICIONES_ANTES_PAUSA_LARGA = 10
PAUSA_LARGA_MIN = 15
PAUSA_LARGA_MAX = 30
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
    portal: str  # Nuevo campo para identificar el portal
    telefono: Optional[str] = None  # Nuevo campo para el teléfono


class BaseScraper(ABC):
    """Clase base abstracta para scrapers de portales inmobiliarios"""
    
    def __init__(self, modo_debug=False, usar_rotacion_ip=False, vpn_provider=None):
        self.driver: Optional[WebDriver] = None
        self.viviendas = []
        self.modo_debug = modo_debug
        self.resultados = []
        
        # Contadores para anti-detección
        self.peticiones_realizadas = 0
        self.peticiones_desde_ultima_pausa = 0
        self.usar_rotacion_ip = usar_rotacion_ip
        self.vpn_provider = vpn_provider
    
    @abstractmethod
    def get_portal_name(self) -> str:
        """Retorna el nombre del portal (e.g., 'Idealista', 'Fotocasa')"""
        pass
    
    @abstractmethod
    def get_search_url(self) -> str:
        """Retorna la URL de búsqueda del portal"""
        pass
    
    @abstractmethod
    def extraer_vivienda(self, articulo: Any) -> Optional[Vivienda]:
        """Extrae los datos de una vivienda del HTML. Debe ser implementado por cada portal."""
        pass
    
    @abstractmethod
    def scrapear_pagina(self) -> List[Vivienda]:
        """Scrapea una página completa. Debe ser implementado por cada portal."""
        pass
    
    @abstractmethod
    def es_particular(self, html_texto: str) -> tuple[bool, str]:
        """Determina si un anuncio es de particular. Debe ser implementado por cada portal."""
        pass
    
    @abstractmethod
    def scrapear_con_filtrado(self, paginas: Optional[int] = None) -> List[Vivienda]:
        """Método principal de scraping con filtrado. Debe ser implementado por cada portal."""
        pass
    
    # ============== MÉTODOS COMUNES ==============
    
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
                subprocess.run(['nordvpn', 'disconnect'], capture_output=True, timeout=30)
                time.sleep(2)
                paises = ['Spain', 'France', 'Germany', 'Italy', 'Netherlands', 'Portugal', 'Belgium']
                pais = random.choice(paises)
                result = subprocess.run(['nordvpn', 'connect', pais], capture_output=True, text=True, timeout=60)
                if 'connected' in result.stdout.lower() or result.returncode == 0:
                    print(f"   ✅ Conectado a NordVPN ({pais})")
                    return True
                    
            elif self.vpn_provider == 'expressvpn':
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
                subprocess.run(['surfshark', 'disconnect'], capture_output=True, timeout=30)
                time.sleep(2)
                result = subprocess.run(['surfshark', 'connect'], capture_output=True, text=True, timeout=60)
                if result.returncode == 0:
                    print(f"   ✅ Conectado a Surfshark")
                    return True
                    
            elif self.vpn_provider == 'windscribe':
                windscribe_cli = r'C:\Program Files\Windscribe\windscribe-cli.exe'
                subprocess.run([windscribe_cli, 'disconnect'], capture_output=True, timeout=30)
                time.sleep(3)
                ubicaciones = ['best', 'Paris', 'Amsterdam', 'Frankfurt', 'Zurich', 'London']
                ubicacion = random.choice(ubicaciones)
                result = subprocess.run([windscribe_cli, 'connect', ubicacion], capture_output=True, text=True, timeout=60)
                time.sleep(3)
                status = subprocess.run([windscribe_cli, 'status'], capture_output=True, text=True, timeout=30)
                
                if 'Conectado' in status.stdout or 'Connected' in status.stdout:
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
    
    def _verificar_conectividad(self):
        """Verifica si hay conectividad a internet"""
        try:
            # Intentar conectar a un servidor confiable
            urllib.request.urlopen('http://www.google.com', timeout=5)
            return True
        except:
            try:
                # Segundo intento con otra URL
                urllib.request.urlopen('http://www.cloudflare.com', timeout=5)
                return True
            except:
                return False
    
    def delay_aleatorio(self, tipo='pagina'):
        """Aplica un delay aleatorio para parecer más humano"""
        if tipo == 'pagina':
            delay = random.uniform(DELAY_MIN_ENTRE_PAGINAS, DELAY_MAX_ENTRE_PAGINAS)
        else:
            delay = random.uniform(DELAY_MIN_ENTRE_DETALLES, DELAY_MAX_ENTRE_DETALLES)
        
        if self.modo_debug:
            print(f"      [DEBUG] Delay aleatorio: {delay:.1f}s")
        
        time.sleep(delay)
    
    def incrementar_contador_peticiones(self):
        """Incrementa contadores y gestiona pausas/cambios de IP"""
        self.peticiones_realizadas += 1
        self.peticiones_desde_ultima_pausa += 1
        
        if self.peticiones_desde_ultima_pausa >= PETICIONES_ANTES_PAUSA_LARGA:
            pausa = random.uniform(PAUSA_LARGA_MIN, PAUSA_LARGA_MAX)
            print(f"\n☕ Pausa de {pausa:.0f}s para evitar detección (petición #{self.peticiones_realizadas})...")
            time.sleep(pausa)
            self.peticiones_desde_ultima_pausa = 0
        
        if self.usar_rotacion_ip and self.peticiones_realizadas % PETICIONES_ANTES_CAMBIO_IP == 0:
            self.solicitar_cambio_ip()
    
    def solicitar_cambio_ip(self):
        """Cambia la IP automáticamente o pide al usuario que lo haga"""
        print("\n" + "="*70)
        print("🔄 CAMBIO DE IP")
        print("="*70)
        print(f"\n📊 Peticiones realizadas: {self.peticiones_realizadas}")
        
        if self.vpn_provider and self.vpn_provider != 'manual':
            if self.cambiar_vpn_automatico():
                print("   ⏳ Esperando 10s para estabilizar conexión...")
                time.sleep(10)
                print("[OK] IP cambiada automáticamente. Continuando...\n")
                return
            else:
                print("\n   ⚠️ Cambio automático falló. Cambia manualmente.")
        
        print("\n🌐 OPCIONES PARA CAMBIAR TU IP:")
        print("   OPCIÓN 1 - VPN: Desconecta y reconecta a otro servidor")
        print("   OPCIÓN 2 - Proxy: Cambia el proxy en Chrome")
        print("   OPCIÓN 3 - Router: Reinicia tu router (si tienes IP dinámica)")
        print("   OPCIÓN 4 - Continuar sin cambiar (más riesgo de captcha)")
        print("\n⏳ El scraper está PAUSADO...")
        print("="*70)
        
        input("\n>>> Presiona Enter cuando hayas cambiado la IP (o para continuar)... ")
        print("[OK] Continuando con el scraping...\n")
    
    def manejar_error_conexion(self, error):
        """Maneja errores de conexión causados por firewall de VPN o problemas de red"""
        error_msg = str(error).lower()
        
        # Detectar tipos de errores de conexión
        errores_conexion = [
            'err_name_not_resolved',
            'err_connection_refused',
            'err_connection_timed_out',
            'err_connection_reset',
            'err_network_changed',
            'err_internet_disconnected',
            'no internet',
            'network error'
        ]
        
        es_error_conexion = any(err in error_msg for err in errores_conexion)
        
        if es_error_conexion:
            print("\n" + "="*70)
            print("🔌 ERROR DE CONEXIÓN DETECTADO")
            print("="*70)
            print("\n[!] El scraper no puede conectarse a internet")
            print("\n📋 Causas comunes:")
            print("   • Firewall de VPN bloqueando tras cambio de servidor")
            print("   • VPN desconectada pero firewall activo")
            print("   • Problemas de red temporales")
            print("   • DNS no resuelve nombres")
            
            # Intentar reconexión automática si hay VPN configurada
            if self.vpn_provider and self.vpn_provider != 'manual':
                print("\n🔄 INTENTANDO RECONEXIÓN AUTOMÁTICA DE VPN...")
                print("="*70)
                
                max_intentos_vpn = 3
                for intento in range(max_intentos_vpn):
                    print(f"\n[Intento {intento + 1}/{max_intentos_vpn}] Reconectando VPN...")
                    
                    if self.cambiar_vpn_automatico():
                        print("✅ VPN reconectada exitosamente")
                        print("⏳ Esperando estabilización de la conexión...")
                        time.sleep(10)  # Esperar a que la conexión se estabilice
                        
                        # Verificar conectividad
                        if self._verificar_conectividad():
                            print("✅ Conectividad verificada correctamente")
                            print("\n[OK] Reintentando operación...\n")
                            return True  # Reintentar la operación
                        else:
                            print("⚠️  La VPN se conectó pero aún hay problemas de red")
                            if intento < max_intentos_vpn - 1:
                                print("Intentando con otro servidor...")
                                time.sleep(5)
                                continue
                    else:
                        print(f"❌ Fallo en la reconexión (intento {intento + 1}/{max_intentos_vpn})")
                        if intento < max_intentos_vpn - 1:
                            time.sleep(5)
                            continue
                
                print("\n❌ No se pudo reconectar automáticamente después de varios intentos")
                print("\n🔧 INTERVENCIÓN MANUAL REQUERIDA:")
            else:
                print("\n🔧 SOLUCIONES:")
            
            print("   1. Desconecta completamente la VPN")
            print("   2. Verifica que tienes conexión a internet (abre un navegador)")
            print("   3. Reconecta la VPN si es necesario")
            print("   4. Espera 10-20 segundos para estabilizar")
            print("\n⏸️  El scraper está PAUSADO hasta que resuelvas el problema")
            print("="*70)
            
            while True:
                respuesta = input("\n>>> ¿Has resuelto el problema? (s/n): ").lower().strip()
                if respuesta in ['s', 'si', 'sí', 'yes', 'y']:
                    print("\n[OK] Reintentando conexión...\n")
                    return True  # Reintentar
                elif respuesta in ['n', 'no']:
                    print("\n[!] Tómate tu tiempo. El scraper seguirá esperando...")
                    continue
                else:
                    print("[!] Por favor responde 's' o 'n'")
        
        return False
    
    def detectar_captcha(self):
        """Detecta si hay un captcha en la página actual"""
        if not self.driver:
            return False
        
        page_source = self.driver.page_source.lower()
        current_url = self.driver.current_url.lower()
        
        captcha_detectado = False
        razon_deteccion = ""
        
        # Señales comunes de captcha en URL
        url_captcha_signals = ['geo.captcha-delivery.com', 'datadome.co', '/challenge', '/blocked']
        for signal in url_captcha_signals:
            if signal in current_url:
                captcha_detectado = True
                razon_deteccion = f"URL de captcha: {signal}"
                break
        
        # Señales de DataDome
        if not captcha_detectado:
            datadome_signals = [
                'pardon our interruption',
                'geo.captcha-delivery.com',
                'datadome.co/captcha',
                'security check',
                'verificación de seguridad'
            ]
            for signal in datadome_signals:
                if signal in page_source:
                    captcha_detectado = True
                    razon_deteccion = f"DataDome detectado"
                    break
        
        if captcha_detectado:
            print("\n" + "="*70)
            print("🤖 CAPTCHA DETECTADO")
            print("="*70)
            print(f"Razón: {razon_deteccion}")
            print("\n[!] Por favor, resuelve el captcha manualmente en el navegador Chrome")
            print("[!] El scraper esperará hasta que lo completes...")
            print("="*70)
            
            input("\n>>> Presiona Enter cuando hayas resuelto el captcha... ")
            print("[OK] Continuando...\n")
            return True
        
        return False
    
    def conectar_chrome(self):
        """Conecta al Chrome en modo debug"""
        try:
            chrome_options = Options()
            chrome_options.add_experimental_option("debuggerAddress", "127.0.0.1:9222")
            
            print("[*] Conectando al Chrome en modo debug...")
            self.driver = webdriver.Chrome(options=chrome_options)
            print("[OK] Conectado correctamente!")
            return True
            
        except Exception as e:
            print(f"\n[ERROR] No se pudo conectar: {e}")
            print("\n[!] Asegúrate de:")
            print("    1. Ejecutar: start_chrome_debug.bat")
            print("    2. Esperar a que Chrome se abra")
            print("    3. Volver a intentar este script")
            return False
    
    def navegar_a_url(self):
        """Navega a la URL del portal con manejo de errores de conexión"""
        if not self.driver:
            print("[ERROR] Driver no inicializado")
            return
        
        url = self.get_search_url()
        print(f"\n[*] Navegando a {self.get_portal_name()}...")
        print(f"[*] URL: {url}")
        
        max_reintentos = 3
        for intento in range(max_reintentos):
            try:
                self.driver.get(url)
                return  # Éxito
            except WebDriverException as e:
                if self.manejar_error_conexion(e):
                    # Usuario dice que resolvió el problema, reintentar
                    if intento < max_reintentos - 1:
                        print(f"[*] Reintento {intento + 1}/{max_reintentos}...")
                        time.sleep(2)
                        continue
                    else:
                        print("\n[ERROR] No se pudo establecer conexión después de varios intentos")
                        raise
                else:
                    # No es error de conexión, propagar el error
                    raise
        
        print("[OK] Página cargada!")
        print("[!] Si hay captcha, resuélvelo manualmente antes de continuar")
        input("Presiona Enter cuando estés listo para comenzar el scraping... ")
        
        self.detectar_captcha()
    
    def _navegar_con_reintentos(self, url: str, max_reintentos: int = 3):
        """
        Método auxiliar para navegar a una URL con manejo de errores de conexión
        Usar este método en lugar de driver.get() directamente
        """
        for intento in range(max_reintentos):
            try:
                self.driver.get(url)
                return True  # Éxito
            except WebDriverException as e:
                if self.manejar_error_conexion(e):
                    # Usuario dice que resolvió el problema, reintentar
                    if intento < max_reintentos - 1:
                        print(f"[*] Reintento {intento + 1}/{max_reintentos}...")
                        time.sleep(2)
                        continue
                    else:
                        print("\n[ERROR] No se pudo establecer conexión después de varios intentos")
                        raise
                else:
                    # No es error de conexión, propagar el error
                    raise
        return False
    
    def guardar(self, viviendas: List[Vivienda], filename: str, ubicacion: str = None, url_scrapeada: str = None):
        """Guarda en JSON persistente, fusionando con datos existentes.
        
        Los nuevos registros se añaden al principio (más recientes primero).
        """
        import json
        
        # Cargar datos existentes
        viviendas_existentes = []
        if os.path.exists(filename):
            try:
                with open(filename, 'r', encoding='utf-8') as f:
                    data_existente = json.load(f)
                # Soportar ambos formatos: lista directa o dict con 'viviendas'
                if isinstance(data_existente, list):
                    viviendas_existentes = data_existente
                elif isinstance(data_existente, dict):
                    viviendas_existentes = data_existente.get('viviendas', [])
                print(f"\n📂 Cargando JSON existente: {len(viviendas_existentes)} registros previos")
            except Exception as e:
                print(f"\n⚠️  Error leyendo JSON existente: {e}")
        
        # Fusionar: nuevos al principio, existentes después (sin duplicados)
        nuevos = [asdict(v) for v in viviendas]
        urls_nuevas = {v['url'] for v in nuevos if 'url' in v}
        existentes_filtrados = [v for v in viviendas_existentes if v.get('url') not in urls_nuevas]
        todas_viviendas = nuevos + existentes_filtrados
        
        data = {
            'timestamp': datetime.now().isoformat(),
            'ubicacion': ubicacion or '',
            'url': url_scrapeada or '',
            'total': len(todas_viviendas),
            'viviendas': todas_viviendas
        }
        
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        print(f"\n[OK] Datos guardados en: {filename}")
        print(f"     Nuevos añadidos: {len(nuevos)}")
        print(f"     Total registros: {len(todas_viviendas)}")
        
        # Subir a la API si está configurado
        self.subir_a_api(data)
    
    @staticmethod
    def _cargar_api_key() -> str:
        """Lee la API key de INMOCAPT_API_KEY desde .env o variables de entorno."""
        # Primero intentar variable de entorno
        api_key = os.environ.get('INMOCAPT_API_KEY', '')
        if api_key:
            return api_key
        # Leer de .env
        env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
        try:
            with open(env_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line.startswith('#') or '=' not in line:
                        continue
                    key, _, value = line.partition('=')
                    if key.strip() == 'INMOCAPT_API_KEY':
                        return value.strip()
        except FileNotFoundError:
            pass
        return ''
    
    @staticmethod
    def cargar_config_api(config_file: str = "config.json") -> dict:
        """Carga la configuración de la API desde config.json"""
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                config = json.load(f)
            return config.get('api', {})
        except:
            return {}
    
    @staticmethod
    def subir_a_api(data: dict, config_file: str = "config.json"):
        """Sube los datos a la API de InmoCapt.
        
        Lee la configuración de api.url, api.auto_upload y api.create_if_not_exists
        desde config.json. La API key se lee de la variable INMOCAPT_API_KEY en .env.
        """
        try:
            import requests
        except ImportError:
            print("\n⚠️  requests no instalado, no se puede subir a la API")
            return
        
        config = BaseScraper.cargar_config_api(config_file)
        
        if not config.get('auto_upload', False):
            return
        
        api_url = config.get('url', '')
        api_key = BaseScraper._cargar_api_key()
        
        if not api_url or not api_key:
            print("\n⚠️  API no configurada (falta url en config.json o INMOCAPT_API_KEY en .env)")
            return
        
        create = config.get('create_if_not_exists', True)
        ubicacion = data.get('ubicacion', 'Sin nombre')
        
        try:
            url = f"{api_url}?createIfNotExists=true" if create else api_url
            
            response = requests.post(
                url,
                headers={
                    'X-API-Key': api_key,
                    'Content-Type': 'application/json',
                },
                json=data,
                timeout=30,
            )
            
            if response.status_code == 200:
                result = response.json()
                stats = result.get('stats', {})
                print(f"\n☁️  API [{ubicacion}]: ✅ añadidas={stats.get('added', 0)} | ⏭️ omitidas={stats.get('skipped', 0)} | lista={'nueva' if result.get('listCreated') else 'existente'}")
            else:
                print(f"\n☁️  API [{ubicacion}]: ❌ Error {response.status_code}: {response.text[:100]}")
        except requests.exceptions.Timeout:
            print(f"\n☁️  API [{ubicacion}]: ⚠️ Timeout (30s)")
        except Exception as e:
            print(f"\n☁️  API [{ubicacion}]: ⚠️ Error: {e}")
    
    def mostrar_resumen(self, viviendas: List[Vivienda]):
        """Muestra un resumen de las viviendas encontradas"""
        print("\n" + "="*70)
        print(f"RESUMEN DE SCRAPING - {self.get_portal_name()}")
        print("="*70)
        print(f"\n📊 Total de viviendas encontradas: {len(viviendas)}")
        
        if not viviendas:
            return
        
        particulares = [v for v in viviendas if v.anunciante.lower() == "particular"]
        profesionales = [v for v in viviendas if v.anunciante.lower() != "particular"]
        
        print(f"   • Particulares: {len(particulares)}")
        print(f"   • Profesionales/Inmobiliarias: {len(profesionales)}")
        
        if particulares:
            print(f"\n🏠 VIVIENDAS DE PARTICULARES (primeras 20):")
            print("="*70)
            for i, v in enumerate(particulares[:20], 1):
                print(f"\n{i}. {v.titulo}")
                print(f"   💰 {v.precio} | 📍 {v.ubicacion}")
                if v.habitaciones:
                    print(f"   🛏️ {v.habitaciones} | 📏 {v.metros}")
                print(f"   🔗 {v.url}")
            
            if len(particulares) > 20:
                print(f"\n... y {len(particulares) - 20} particulares más")
