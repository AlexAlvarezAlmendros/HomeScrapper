#!/usr/bin/env -S /home/poio/Documentos/GIT/HomeScrapper/.venv/bin/python
"""
Script para verificar si los anuncios de los JSON siguen activos.
Visita cada URL y comprueba si el anuncio sigue publicado.
Las URLs descatalogadas se guardan en un JSON y se envían a la API.
"""

import os
import re
import json
import glob
import time
import random
import shutil
import signal
import subprocess
import urllib.request
import requests
from datetime import datetime

try:
    from playwright.sync_api import sync_playwright as _sync_playwright
except ModuleNotFoundError:
    _sync_playwright = None


# ─── Sesión Playwright para Fotocasa (CDP + Chrome externo) ─────────────────

# Puerto del Chrome real lanzado por start_chrome_debug.sh (perfil persistente).
# Ese Chrome tiene cookies/historial reales que bypasan Reese84 sin captcha.
CHROME_DEBUG_PORT = 9222
# Puerto de respaldo si lanzamos nuestro propio Chromium sin perfil
CHROME_FALLBACK_PORT = 9225
CHROMIUM_PATH = os.path.expanduser(
    '~/.cache/ms-playwright/chromium-1091/chrome-linux/chrome'
)


def _chrome_debug_disponible(port: int = CHROME_DEBUG_PORT) -> bool:
    """Comprueba si hay un Chrome con CDP escuchando en el puerto dado."""
    import socket
    try:
        with socket.create_connection(('localhost', port), timeout=1):
            return True
    except OSError:
        return False


class PlaywrightFotocasaSession:
    """Conecta al Chrome real del usuario (start_chrome_debug.sh, puerto 9222).

    Ese Chrome usa un perfil persistente con cookies y historial humanos,
    lo que bypasa el anti-bot Reese84 de Fotocasa sin necesitar resolver
    captchas.  Si el Chrome real no está disponible, lanza un Chromium
    de respaldo (sin perfil, puede ser bloqueado).
    """

    def __init__(self):
        self._playwright = None
        self._browser = None
        self._chrome_process = None   # solo si lanzamos nosotros el Chromium
        self._owns_process = False    # True solo si lo hemos lanzado nosotros
        self.page = None
        self._port_used = None

    def __enter__(self):
        if _sync_playwright is None:
            raise RuntimeError(
                "playwright no está instalado en el entorno Python activo.\n"
                "Ejecuta con el venv: .venv/bin/python verificar_anuncios.py\n"
                "O instala: pip install playwright && playwright install chromium"
            )

        self._playwright = _sync_playwright().start()

        if _chrome_debug_disponible(CHROME_DEBUG_PORT):
            # ── Opción A (preferida): conectar al Chrome real del usuario ──
            print(f"\n🌐 Conectando al Chrome real (puerto {CHROME_DEBUG_PORT})...")
            self._browser = self._playwright.chromium.connect_over_cdp(
                f'http://localhost:{CHROME_DEBUG_PORT}'
            )
            self._port_used = CHROME_DEBUG_PORT
            self._owns_process = False
            print("   ✅ Conectado al Chrome con perfil real (Reese84 bypasado).")
        else:
            # ── Opción B (respaldo): lanzar Chromium propio ──
            print(
                f"\n⚠️  Chrome real (puerto {CHROME_DEBUG_PORT}) no disponible.\n"
                f"   Lanza start_chrome_debug.sh primero para evitar captchas.\n"
                f"   Usando Chromium de respaldo (puerto {CHROME_FALLBACK_PORT})..."
            )
            self._chrome_process = subprocess.Popen(
                [
                    CHROMIUM_PATH,
                    f'--remote-debugging-port={CHROME_FALLBACK_PORT}',
                    '--no-sandbox',
                    '--disable-blink-features=AutomationControlled',
                    '--disable-infobars',
                    '--lang=es-ES',
                    '--window-size=1366,768',
                    '--no-first-run',
                    '--no-default-browser-check',
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            time.sleep(2)
            self._browser = self._playwright.chromium.connect_over_cdp(
                f'http://localhost:{CHROME_FALLBACK_PORT}'
            )
            self._port_used = CHROME_FALLBACK_PORT
            self._owns_process = True
            print(f"   Chrome de respaldo PID: {self._chrome_process.pid}")

        # Obtener o crear página
        contexts = self._browser.contexts
        ctx = (
            contexts[0]
            if contexts
            else self._browser.new_context(
                viewport={'width': 1366, 'height': 768},
                locale='es-ES',
                timezone_id='Europe/Madrid',
            )
        )
        pages = ctx.pages
        self.page = pages[0] if pages else ctx.new_page()
        self.page.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        # Navegar a fotocasa.es UNA SOLA VEZ para tener el contexto correcto
        # (mismo origen = las cookies se envían en los fetch() posteriores).
        _asegurar_contexto_fotocasa(self.page)
        return self

    def __exit__(self, *args):
        # Usamos BaseException (no solo Exception) para capturar también
        # KeyboardInterrupt que pueda llegar durante el cleanup de Playwright.
        #
        # NO llamamos browser.close() cuando no somos dueños del proceso:
        # el Chrome real sigue corriendo y browser.close() sobre un event-loop
        # roto (tras Ctrl+C) genera el traceback de coroutine never awaited.
        if self._owns_process:
            # Chromium de respaldo: cerrar browser y parar playwright
            try:
                if self._browser:
                    self._browser.close()
            except BaseException:
                pass
        # Siempre parar el runtime de playwright
        try:
            if self._playwright:
                self._playwright.stop()
        except BaseException:
            pass
        # Solo matar el proceso si lo lanzamos nosotros
        if self._owns_process:
            try:
                if self._chrome_process and self._chrome_process.poll() is None:
                    os.killpg(os.getpgid(self._chrome_process.pid), signal.SIGTERM)
            except BaseException:
                pass
            print("   Chromium de respaldo cerrado.")
        else:
            print(f"   Desconectado del Chrome real (sigue corriendo en :{self._port_used}).")


# ─── Detección de anuncios descatalogados ─────────────────────────────────────

def verificar_url_idealista(url: str, session) -> bool:
    """Comprueba si un anuncio de Idealista sigue activo.
    
    Retorna True si sigue activo, False si está descatalogado.
    Usa Playwright (CDP) si está disponible para evitar el bloqueo de Cloudflare.
    """
    if isinstance(session, PlaywrightFotocasaSession):
        return _verificar_idealista_playwright(url, session.page)
    # Fallback requests
    try:
        headers_extra = {
            'Referer': 'https://www.idealista.com/venta-viviendas/',
            'Sec-Fetch-Site': 'same-origin',
        }
        resp = session.get(url, timeout=15, allow_redirects=True,
                           headers=headers_extra)
        
        # 404 / 410 = eliminado definitivamente
        if resp.status_code in (404, 410):
            return False
        
        # Redirige fuera de /inmueble/ = eliminado
        if '/inmueble/' not in resp.url:
            return False

        # Bloqueo anti-bot (Imperva 403/999/503 con página de challenge)
        if resp.status_code in (403, 503, 999):
            # No podemos confirmar — asumimos activo para no dar falsos negativos
            return True
        
        # Buscar señales de anuncio no disponible en el HTML
        html = resp.text.lower()
        señales_descatalogado = [
            'deactivated-detail',                              # Clase CSS única de Idealista para anuncios de baja
            'lo sentimos, este anuncio ya no está publicado',  # Título exacto del bloque deactivated
            'este anuncio ya no está publicado',              # Variante corta
            'el anunciante lo dio de baja',                    # Texto del párrafo de baja
            'este inmueble ya no está disponible',
            'el anuncio que buscas ya no está disponible',
            'anuncio no disponible',
            'listing-not-found',
        ]
        
        for señal in señales_descatalogado:
            if señal in html:
                return False
        
        return True
        
    except requests.exceptions.RequestException:
        # Error de conexión — no podemos confirmar, asumimos activo
        return True


def verificar_url_fotocasa(url: str, session) -> bool:
    """Comprueba si un anuncio de Fotocasa sigue activo.

    Retorna True si sigue activo, False si está descatalogado.

    Fotocasa usa Reese84 anti-bot que bloquea requests.  Usa Playwright
    via CDP (PlaywrightFotocasaSession) para navegación real que permite
    detectar el redirect a propertyNotFound en viviendas descatalogadas.
    """
    if isinstance(session, PlaywrightFotocasaSession):
        return _verificar_fotocasa_playwright(url, session.page, session._port_used)
    # Fallback requests (muy probable que esté bloqueado por Reese84)
    return _verificar_fotocasa_requests(url)


def _asegurar_contexto_portal(page, portal: str, force: bool = False) -> None:
    """Navega al portal correcto si la pestaña no está ya en ese dominio.
    Llama a _asegurar_contexto_fotocasa o _asegurar_contexto_idealista según el portal.
    """
    if portal == 'fotocasa':
        _asegurar_contexto_fotocasa(page, force=force)
    elif portal == 'idealista':
        _asegurar_contexto_idealista(page, force=force)


def _asegurar_contexto_fotocasa(page, force: bool = False) -> None:
    """Navega a fotocasa.es si la pestaña no está ya en ese dominio.

    Necesario para que los fetch() posteriores sean same-origin y tengan
    acceso a las cookies de sesión. Solo se ejecuta una vez al inicio.
    Si force=True, navega aunque ya esté en fotocasa.es (p.ej. tras un bloqueo).
    """
    try:
        current = page.url
        if force or 'fotocasa.es' not in current:
            print("   Navegando a fotocasa.es para (re)establecer contexto...")
            from playwright.sync_api import TimeoutError as PWTimeoutError
            try:
                page.goto('https://www.fotocasa.es/es/', timeout=20000,
                          wait_until='domcontentloaded')
            except PWTimeoutError:
                pass  # partial load es suficiente para tener las cookies
            print("   Contexto fotocasa.es listo.")
    except Exception:
        pass


def _asegurar_contexto_idealista(page, force: bool = False) -> None:
    """Navega a idealista.com si la pestaña no está ya en ese dominio.

    Necesario para que los fetch() posteriores sean same-origin y tengan
    acceso a las cookies de sesión. Evita el bloqueo de Cloudflare.
    Si force=True, navega aunque ya esté en idealista.com.
    """
    try:
        current = page.url
        if force or 'idealista.com' not in current:
            print("   Navegando a idealista.com para establecer contexto...")
            from playwright.sync_api import TimeoutError as PWTimeoutError
            try:
                page.goto('https://www.idealista.com/', timeout=25000,
                          wait_until='domcontentloaded')
            except PWTimeoutError:
                pass
            print("   Contexto idealista.com listo.")
    except Exception:
        pass


_JS_FETCH_IDEALISTA = """
    async (url) => {
        try {
            const resp = await fetch(url, {
                method: 'GET',
                credentials: 'include',
                redirect: 'follow'
            });
            if (!resp.ok && resp.status === 404) return 'NOTFOUND:';
            // Lee primeros 8KB — suficiente para encontrar deactivated-detail
            const chunks = [];
            const reader = resp.body.getReader();
            let bytesRead = 0;
            while (bytesRead < 8192) {
                const { done, value } = await reader.read();
                if (done) break;
                chunks.push(value);
                bytesRead += value.length;
            }
            reader.cancel();
            let total = 0;
            for (const c of chunks) total += c.length;
            const combined = new Uint8Array(total);
            let offset = 0;
            for (const c of chunks) { combined.set(c, offset); offset += c.length; }
            const html = new TextDecoder().decode(combined).toLowerCase();
            if (html.includes('deactivated-detail') ||
                html.includes('este anuncio ya no est') ||
                html.includes('el anunciante lo dio de baja')) {
                return 'DEACTIVATED:';
            }
            // Bloqueo Cloudflare: challenge JS
            if (html.includes('please enable js') ||
                html.includes('var dd=') ||
                html.includes('_cf_chl')) {
                return 'BLOCKED:';
            }
            return 'OK:';
        } catch(e) {
            return 'FETCH_ERROR:' + e.toString();
        }
    }
"""


def _verificar_idealista_playwright(url: str, page) -> bool:
    """Verifica URL de Idealista usando fetch() desde el contexto del navegador.

    Retorna True si activa, False si descatalogada.
    """
    max_reintentos = 3
    for intento in range(max_reintentos):
        try:
            result = page.evaluate(_JS_FETCH_IDEALISTA, url)
        except Exception:
            return True

        if not result or result.startswith('FETCH_ERROR'):
            return True

        if result == 'NOTFOUND:':
            return False

        if result == 'DEACTIVATED:':
            return False

        if result == 'BLOCKED:':
            print(f"\n  🚫 Fetch bloqueado por Cloudflare en Idealista "
                  f"(intento {intento + 1}/{max_reintentos})")
            # Navegar a la home para que el usuario vea el captcha
            try:
                from playwright.sync_api import TimeoutError as PWTimeoutError
                page.goto('https://www.idealista.com/', timeout=25000,
                          wait_until='domcontentloaded')
            except Exception:
                pass
            _esperar_captcha_resuelto(0)  # cdp_port no usado en la nueva versión
            _asegurar_contexto_idealista(page, force=True)
            time.sleep(random.uniform(5, 10))
            continue

        if result == 'OK:':
            return True

        return True  # respuesta inesperada → conservador

    print("  ⚠️  Reintentos agotados para esta URL — marcando como activa.")
    return True


def _cdp_page_title(cdp_port: int) -> str:
    """Obtiene el título de la pestaña activa vía CDP HTTP.

    Usa el endpoint HTTP estándar del protocolo Chrome DevTools:
    GET http://localhost:{port}/json  → lista de pestañas con title, url, type...

    Es un GET HTTP plano: no pasa por el event loop ni los greenlets de
    Playwright, por lo que no puede causar 'Execution context was destroyed'.
    """
    try:
        with urllib.request.urlopen(
            f'http://localhost:{cdp_port}/json', timeout=2
        ) as resp:
            tabs = json.loads(resp.read())
        for tab in tabs:
            if tab.get('type') == 'page':
                return tab.get('title', '')
    except Exception:
        pass
    return ''


def _es_captcha_fotocasa(cdp_port: int) -> bool:
    """Detecta si la pestaña activa muestra el captcha/anti-bot de Fotocasa."""
    return 'SENTIMOS LA INTERRUPCI' in _cdp_page_title(cdp_port)


def _esperar_captcha_resuelto(cdp_port: int) -> None:
    """Pausa hasta que el usuario resuelva el captcha/anti-bot de Fotocasa.

    El navegador estará en la homepage de fotocasa.es.
    Si Reese84 está activo, mostrará ahí el captcha o la pantalla de bloqueo.
    Espera a que el usuario pulse Enter para continuar.
    """
    print('\n' + '!'*70)
    print('  🔒 BLOQUEO ANTI-BOT — Fotocasa ha detectado el scraper.')
    print('  🖥️  Mira el navegador Chrome:')
    print('       → Si ves un captcha o aviso: resuélvelo')
    print('       → Si ves fotocasa.es cargado normalmente: ya está listo')
    print('  👉  Pulsa ENTER aquí cuando fotocasa.es cargue sin bloqueo.')
    print('!'*70)
    try:
        input('  ▶  Pulsa ENTER para continuar... ')
    except KeyboardInterrupt:
        print('\n  ⏹️  Interrumpido por el usuario.\n')
        raise
    print('  ✅ Continuando...\n')


_JS_FETCH_CHECK = """
    async (url) => {
        try {
            const resp = await fetch(url, {
                method: 'GET',
                credentials: 'include',
                redirect: 'follow'
            });
            // Lee los primeros 2KB para detectar la pรกgina de bloqueo Reese84
            // IMPORTANTE: 'relibrary' y 'Reese84' aparecen en TODAS las pรกginas
            // de fotocasa (es el script anti-bot incluido siempre), NO son indicadores
            // de bloqueo. Solo 'SENTIMOS' y 'onProtectionInitialized' son exclusivos
            // de la pรกgina de bloqueo real.
            const chunks = [];
            const reader = resp.body.getReader();
            let bytesRead = 0;
            while (bytesRead < 2048) {
                const { done, value } = await reader.read();
                if (done) break;
                chunks.push(value);
                bytesRead += value.length;
            }
            reader.cancel();
            const combined = new Uint8Array(bytesRead);
            let offset = 0;
            for (const chunk of chunks) {
                combined.set(chunk.slice(0, Math.min(chunk.length, bytesRead - offset)), offset);
                offset += chunk.length;
            }
            const start = new TextDecoder().decode(combined);
            const blocked = start.includes('SENTIMOS') ||
                            start.includes('onProtectionInitialized');
            return (blocked ? 'BLOCKED:' : 'OK:') + resp.url;
        } catch(e) {
            return 'FETCH_ERROR:' + e.toString();
        }
    }
"""


def _verificar_fotocasa_playwright(url: str, page, cdp_port: int) -> bool:
    """Verifica URL de Fotocasa usando fetch() desde el contexto del navegador.

    En lugar de navegar la pestaña (page.goto), ejecuta un fetch() JavaScript
    dentro del contexto de la página ya cargada en fotocasa.es. Esto:
      - Usa las cookies reales del navegador (mismo origen).
      - No dispara Reese84 (no hay navegación visible).
      - Sigue los redirects HTTP y devuelve la URL final.
      - Detecta bloqueos leyendo los primeros bytes del body.
    """
    max_reintentos = 3
    for intento in range(max_reintentos):
        try:
            result = page.evaluate(_JS_FETCH_CHECK, url)
        except Exception:
            return True  # error inesperado → asumir activa

        if not result or result.startswith('FETCH_ERROR'):
            # Error de red — no podemos confirmar, tratamos como activa
            return True

        if result.startswith('BLOCKED:'):
            print(f"\n  🚫 Fetch bloqueado por anti-bot de Fotocasa "
                  f"(intento {intento + 1}/{max_reintentos})")
            # Navegar a la HOME de fotocasa (no al URL bloqueado — ese lanza el
            # bucle JS de Reese84 que recarga infinitamente sin mostrar captcha)
            try:
                from playwright.sync_api import TimeoutError as PWTimeoutError
                page.goto('https://www.fotocasa.es/es/', timeout=25000,
                          wait_until='domcontentloaded')
            except Exception:
                pass
            _esperar_captcha_resuelto(cdp_port)
            # Re-establecer contexto tras la espera
            _asegurar_contexto_fotocasa(page, force=True)
            time.sleep(random.uniform(5, 10))
            continue  # reintentar el mismo URL

        # result empieza por 'OK:'
        final_url = result[3:]
        final_url_lower = final_url.lower()

        if 'propertynotfound' in final_url_lower:
            return False
        if '/vivienda/' in url.lower() and '/viviendas/' in final_url_lower:
            return False
        id_match = re.search(r'/([0-9]{6,})/d', url)
        if id_match and id_match.group(1) in final_url:
            return True
        return False

    # Todos los reintentos agotados → asumir activa (conservador)
    print("  ⚠️  Reintentos agotados para esta URL — marcando como activa.")
    return True


def _verificar_fotocasa_requests(url: str) -> bool:
    """Fallback: verifica URL de Fotocasa con requests (puede ser bloqueado)."""
    try:
        with requests.Session() as s:
            s.headers.update({
                'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 '
                              '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,'
                          'image/avif,image/webp,*/*;q=0.8',
                'Accept-Language': 'es-ES,es;q=0.9',
                'Accept-Encoding': 'gzip, deflate, br',
                'Connection': 'close',
            })
            resp = s.get(url, timeout=15, allow_redirects=True)
        if resp.status_code == 404:
            return False
        final_url = resp.url.lower()
        if 'propertynotfound' in final_url:
            return False
        if '/vivienda/' in url.lower() and '/viviendas/' in final_url:
            return False
        id_match = re.search(r'/([0-9]{6,})/d', url)
        if id_match and id_match.group(1) in final_url:
            return True
        return False
    except requests.exceptions.RequestException:
        return True

def cargar_todos_los_json(directorio: str = ".") -> list:
    """Carga todos los JSON de viviendas del directorio.
    
    Retorna lista de dicts: [{archivo, portal, ubicacion, url, viviendas}]
    """
    archivos = sorted(glob.glob(os.path.join(directorio, "viviendas_*.json")))
    datos = []
    
    for archivo in archivos:
        try:
            with open(archivo, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            nombre = os.path.basename(archivo)
            if nombre.startswith("viviendas_idealista_"):
                portal = "idealista"
            elif nombre.startswith("viviendas_fotocasa_"):
                portal = "fotocasa"
            else:
                portal = "desconocido"
            
            viviendas = data.get('viviendas', [])
            if viviendas:
                datos.append({
                    'archivo': archivo,
                    'portal': portal,
                    'ubicacion': data.get('ubicacion', ''),
                    'url_busqueda': data.get('url', ''),
                    'viviendas': viviendas,
                })
                
        except Exception as e:
            print(f"⚠️  Error leyendo {archivo}: {e}")
    
    return datos


# ─── Carga de API key ────────────────────────────────────────────────────────

def cargar_api_key() -> str:
    """Lee INMOCAPT_API_KEY desde .env o variable de entorno."""
    api_key = os.environ.get('INMOCAPT_API_KEY', '')
    if api_key:
        return api_key
    
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


def cargar_config_api() -> dict:
    """Carga la config de la API desde config.json."""
    try:
        config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.json')
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        return config.get('api', {})
    except:
        return {}


# ─── Envío a la API ───────────────────────────────────────────────────────────

def enviar_descatalogadas(urls_por_ubicacion: dict):
    """Envía las URLs descatalogadas a la API para que se marquen.
    
    urls_por_ubicacion: {ubicacion: [url1, url2, ...]}
    """
    api_config = cargar_config_api()
    api_key = cargar_api_key()
    
    base_url = api_config.get('url', '').replace('/upload', '/delist')  # endpoint de baja
    
    if not base_url or not api_key:
        print("\n⚠️  API no configurada — los resultados se guardaron solo en JSON local")
        return
    
    print(f"\n{'='*70}")
    print("☁️  ENVIANDO DESCATALOGADAS A LA API")
    print(f"{'='*70}")
    
    for ubicacion, urls in urls_por_ubicacion.items():
        if not urls:
            continue
        
        payload = {
            'timestamp': datetime.now().isoformat(),
            'ubicacion': ubicacion,
            'urls_descatalogadas': urls,
            'total': len(urls),
        }
        
        try:
            response = requests.post(
                base_url,
                headers={
                    'X-API-Key': api_key,
                    'Content-Type': 'application/json',
                },
                json=payload,
                timeout=30,
            )
            
            if response.status_code == 200:
                print(f"  ✅ {ubicacion}: {len(urls)} URLs enviadas correctamente")
            else:
                print(f"  ❌ {ubicacion}: Error {response.status_code} — {response.text[:100]}")
        except Exception as e:
            print(f"  ⚠️  {ubicacion}: Error de conexión — {e}")


# ─── Rotación de VPN (ProtonVPN) ──────────────────────────────────────────────

def detectar_protonvpn() -> bool:
    """Comprueba si protonvpn está instalado."""
    return shutil.which('protonvpn') is not None


def rotar_vpn() -> bool:
    """Desconecta y reconecta ProtonVPN a un servidor aleatorio.
    
    Retorna True si la reconexión fue exitosa.
    """
    print("\n🔄 Rotando VPN (ProtonVPN)...")
    
    try:
        # Desconectar
        subprocess.run(['protonvpn', 'disconnect'], capture_output=True, timeout=30)
        time.sleep(3)
        
        # Intentar con país aleatorio (plan de pago)
        paises = ['ES', 'FR', 'DE', 'IT', 'NL', 'PT', 'BE', 'CH']
        pais = random.choice(paises)
        result = subprocess.run(
            ['protonvpn', 'connect', '--country', pais],
            capture_output=True, text=True, timeout=60
        )
        
        if result.returncode == 0:
            print(f"   ✅ Conectado a ProtonVPN (país {pais})")
            time.sleep(2)
            return True
        
        # Plan gratuito: sin opción de país
        print(f"   ℹ️  Conectando a servidor FREE disponible...")
        result = subprocess.run(
            ['protonvpn', 'connect'],
            capture_output=True, text=True, timeout=60
        )
        
        if result.returncode == 0:
            print(f"   ✅ Conectado a ProtonVPN (servidor FREE)")
            time.sleep(2)
            return True
        
        print(f"   ❌ No se pudo reconectar: {result.stderr[:100]}")
        return False
        
    except subprocess.TimeoutExpired:
        print("   ❌ Timeout al conectar con ProtonVPN")
        return False
    except Exception as e:
        print(f"   ❌ Error VPN: {e}")
        return False


def obtener_ip_actual() -> str:
    """Obtiene la IP pública actual."""
    try:
        resp = requests.get('https://api.ipify.org', timeout=10)
        return resp.text.strip()
    except:
        return 'desconocida'


# ─── Proceso principal ────────────────────────────────────────────────────────

def crear_sesion(portal: str) -> requests.Session:
    """Crea una sesión HTTP con headers similares a un navegador."""
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 '
                      '(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,'
                  'image/avif,image/webp,image/apng,*/*;q=0.8,'
                  'application/signed-exchange;v=b3;q=0.7',
        'Accept-Language': 'es-ES,es;q=0.9,en;q=0.8',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
        'sec-ch-ua': '"Chromium";v="122", "Not(A:Brand";v="24", "Google Chrome";v="122"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"Linux"',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'none',
        'Sec-Fetch-User': '?1',
        'DNT': '1',
        'Cache-Control': 'max-age=0',
    })
    if portal == 'idealista':
        # Warmup: visita la home para obtener cookies de sesión de Imperva
        try:
            session.get('https://www.idealista.com/', timeout=10, allow_redirects=True)
        except Exception:
            pass
    return session


def verificar_json(datos_json: dict, session: requests.Session, usar_vpn: bool = False,
                   peticiones_para_rotar: int = 50, contador_global: dict = None) -> list:
    """Verifica todas las URLs de un JSON. Retorna lista de URLs descatalogadas.
    
    Args:
        usar_vpn: Si True, rota la VPN cada N peticiones
        peticiones_para_rotar: Número de peticiones entre rotaciones
        contador_global: Dict mutable {'count': int} para llevar la cuenta entre JSONs
    """
    portal = datos_json['portal']
    viviendas = datos_json['viviendas']
    ubicacion = datos_json['ubicacion']
    verificar = verificar_url_idealista if portal == 'idealista' else verificar_url_fotocasa
    
    if contador_global is None:
        contador_global = {'count': 0}
    
    descatalogadas = []
    total = len(viviendas)
    errores_consecutivos = 0
    
    for i, vivienda in enumerate(viviendas, 1):
        url = vivienda.get('url', '')
        if not url:
            continue
        
        # Rotación de VPN cada N peticiones
        contador_global['count'] += 1
        if usar_vpn and contador_global['count'] % peticiones_para_rotar == 0:
            print(f"\n    🔄 Rotando VPN tras {contador_global['count']} peticiones...")
            if rotar_vpn():
                # Recrear sesión con nueva IP
                if not isinstance(session, PlaywrightFotocasaSession):
                    session.cookies.clear()
                ip = obtener_ip_actual()
                print(f"    🌐 Nueva IP: {ip}")
                errores_consecutivos = 0
        
        titulo = vivienda.get('titulo', 'Sin título')[:50]
        activo = verificar(url, session)
        
        if activo:
            print(f"    [{i}/{total}] ✅ {titulo}...")
            errores_consecutivos = 0
        else:
            print(f"    [{i}/{total}] ❌ DESCATALOGADO: {titulo}...")
            descatalogadas.append(url)
        
        # Si hay muchos errores seguidos, posible bloqueo → rotar VPN
        # (detectamos bloqueo si hay 5+ "descatalogados" consecutivos, raro en condiciones normales)
        if usar_vpn and errores_consecutivos >= 5:
            print(f"\n    ⚠️  {errores_consecutivos} errores consecutivos — posible bloqueo, rotando VPN...")
            rotar_vpn()
            if not isinstance(session, PlaywrightFotocasaSession):
                session.cookies.clear()
            ip = obtener_ip_actual()
            print(f"    🌐 Nueva IP: {ip}")
            errores_consecutivos = 0
        
        # Delay entre peticiones — lo suficiente para no activar el rate-limit de Fotocasa
        time.sleep(random.uniform(2.0, 4.0))
    
    return descatalogadas


def main():
    directorio = os.path.dirname(os.path.abspath(__file__))
    
    print("="*70)
    print("  VERIFICADOR DE ANUNCIOS ACTIVOS")
    print("  Comprueba si las viviendas siguen publicadas")
    print("="*70)
    
    # Cargar todos los JSON
    datos = cargar_todos_los_json(directorio)
    
    if not datos:
        print("\n❌ No se encontraron archivos viviendas_*.json")
        return
    
    total_viviendas = sum(len(d['viviendas']) for d in datos)
    total_archivos = len(datos)
    
    print(f"\n📂 {total_archivos} archivos JSON encontrados")
    print(f"🏠 {total_viviendas} viviendas totales a verificar")
    
    # Menú de selección
    print(f"\n{'─'*40}")
    print("Selecciona qué verificar:")
    print("  1. Solo Idealista")
    print("  2. Solo Fotocasa")
    print("  3. Todos")
    print(f"{'─'*40}")
    
    opcion = input("\nOpción [3]: ").strip() or "3"
    
    if opcion == "1":
        datos = [d for d in datos if d['portal'] == 'idealista']
    elif opcion == "2":
        datos = [d for d in datos if d['portal'] == 'fotocasa']
    
    if not datos:
        print("❌ No hay archivos para el portal seleccionado")
        return
    
    total_viviendas = sum(len(d['viviendas']) for d in datos)
    
    # ─── Opción de VPN ────────────────────────────────────────────────
    usar_vpn = False
    peticiones_para_rotar = 50
    
    if detectar_protonvpn():
        print(f"\n🔒 ProtonVPN detectado")
        ip_actual = obtener_ip_actual()
        print(f"   IP actual: {ip_actual}")
        vpn_input = input("\n¿Usar rotación de VPN? [S/n]: ").strip().lower()
        usar_vpn = vpn_input != 'n'
        
        if usar_vpn:
            rotar_cada = input(f"Rotar cada N peticiones [{peticiones_para_rotar}]: ").strip()
            if rotar_cada.isdigit() and int(rotar_cada) > 0:
                peticiones_para_rotar = int(rotar_cada)
            print(f"   🔄 Rotación cada {peticiones_para_rotar} peticiones")
    else:
        print("\nℹ️  ProtonVPN no detectado — sin rotación de IP")
    
    print(f"\n🔍 Verificando {total_viviendas} viviendas de {len(datos)} archivos...\n")
    
    # Procesar cada JSON
    todas_descatalogadas = []        # lista global [{url, ubicacion, portal, titulo}]
    urls_por_ubicacion = {}          # {ubicacion: [urls]}
    contador_global = {'count': 0}   # contador compartido entre JSONs

    # Playwright/CDP para todos los portales (Fotocasa=Reese84, Idealista=Cloudflare)
    playwright_ctx = PlaywrightFotocasaSession()
    session_playwright = playwright_ctx.__enter__()

    try:
        for i, datos_json in enumerate(datos, 1):
            portal = datos_json['portal']
            ubicacion = datos_json['ubicacion']
            n_viviendas = len(datos_json['viviendas'])
            archivo = os.path.basename(datos_json['archivo'])
            
            print(f"\n{'─'*70}")
            print(f"  [{i}/{len(datos)}] {ubicacion} ({portal}) — {n_viviendas} viviendas")
            print(f"  Archivo: {archivo}")
            if usar_vpn:
                print(f"  🌐 Peticiones totales: {contador_global['count']}")
            print(f"{'─'*70}")
            
            # Asegurar que la pestaña esté en el dominio correcto antes de verificar
            _asegurar_contexto_portal(session_playwright.page, portal)
            session = session_playwright
            descatalogadas = verificar_json(
                datos_json, session,
                usar_vpn=usar_vpn,
                peticiones_para_rotar=peticiones_para_rotar,
                contador_global=contador_global,
            )
            
            if descatalogadas:
                urls_por_ubicacion[ubicacion] = descatalogadas
                for url in descatalogadas:
                    # Buscar título original
                    titulo = ''
                    for v in datos_json['viviendas']:
                        if v.get('url') == url:
                            titulo = v.get('titulo', '')
                            break
                    todas_descatalogadas.append({
                        'url': url,
                        'ubicacion': ubicacion,
                        'portal': portal,
                        'titulo': titulo,
                    })
                print(f"\n  🗑️  {len(descatalogadas)} descatalogadas en {ubicacion}")
            else:
                print(f"\n  ✅ Todas activas en {ubicacion}")
            
            # Pausa entre archivos
            if i < len(datos):
                pausa = random.uniform(3, 6)
                print(f"\n  ⏳ Pausa de {pausa:.0f}s antes del siguiente...")
                time.sleep(pausa)
    
    except KeyboardInterrupt:
        print("\n\n⚠️  Verificación interrumpida por el usuario")
    finally:
        if playwright_ctx:
            playwright_ctx.__exit__(None, None, None)
    
    # ─── Resumen ──────────────────────────────────────────────────────────
    print(f"\n\n{'='*70}")
    print("📊 RESUMEN DE VERIFICACIÓN")
    print(f"{'='*70}")
    print(f"  Viviendas verificadas:   {total_viviendas}")
    print(f"  Descatalogadas:          {len(todas_descatalogadas)}")
    print(f"  Activas:                 {total_viviendas - len(todas_descatalogadas)}")
    
    if not todas_descatalogadas:
        print("\n✅ Todos los anuncios siguen activos")
        return
    
    # Desglose por ubicación
    print(f"\n  Desglose:")
    for ubi, urls in urls_por_ubicacion.items():
        print(f"    • {ubi}: {len(urls)} descatalogadas")
    
    # ─── Guardar JSON de descatalogadas ───────────────────────────────────
    output_file = os.path.join(directorio, "viviendas_descatalogadas.json")
    
    output_data = {
        'timestamp': datetime.now().isoformat(),
        'total': len(todas_descatalogadas),
        'urls': [d['url'] for d in todas_descatalogadas],
        'detalle': todas_descatalogadas,
    }
    
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)
    
    print(f"\n💾 Guardado en: {output_file}")
    print(f"   {len(todas_descatalogadas)} URLs descatalogadas")
    
    # ─── Enviar a la API ──────────────────────────────────────────────────
    enviar = input("\n¿Enviar descatalogadas a la API? [S/n]: ").strip().lower()
    if enviar != 'n':
        enviar_descatalogadas(urls_por_ubicacion)
    
    print("\n✅ Verificación completada")


if __name__ == "__main__":
    main()
