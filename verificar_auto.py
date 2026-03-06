#!/usr/bin/env -S /home/poio/Documentos/GIT/HomeScrapper/.venv/bin/python
"""
Script automático para verificar periódicamente si los anuncios siguen activos.

Diseñado para ejecutarse en cron/systemd timer sin intervención manual.
Comprueba todas las viviendas de los JSON y genera un JSON con las descatalogadas.

Uso:
    # Verificar todo (idealista + fotocasa)
    ./verificar_auto.py

    # Solo idealista, con envío a API
    ./verificar_auto.py --portal idealista --send-api

    # Solo fotocasa, delay más alto
    ./verificar_auto.py --portal fotocasa --delay 3.0

    # Ejecutar con log
    ./verificar_auto.py 2>&1 | tee -a /var/log/homescraper_verify.log

Cron ejemplo (cada día a las 04:00):
    0 4 * * * cd /home/poio/Documentos/GIT/HomeScrapper && .venv/bin/python verificar_auto.py --send-api >> logs/verificar.log 2>&1
"""

import os
import re
import sys
import json
import glob
import time
import shutil
import random
import signal
import logging
import argparse
import subprocess
import urllib.request
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from datetime import datetime

try:
    from playwright.sync_api import sync_playwright as _sync_playwright
    from playwright.sync_api import TimeoutError as PWTimeoutError
except ModuleNotFoundError:
    _sync_playwright = None
    PWTimeoutError = None

try:
    import requests
except ModuleNotFoundError:
    requests = None

# ─── Configuración ────────────────────────────────────────────────────────────

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CHROME_DEBUG_PORT = 9222
CHROME_FALLBACK_PORT = 9225
CHROMIUM_PATH = os.path.expanduser(
    '~/.cache/ms-playwright/chromium-1091/chrome-linux/chrome'
)

# Delays entre peticiones (segundos).
# Cloudflare detecta ráfagas rápidas; necesitamos simular navegación humana.
DELAY_IDEALISTA = (1.5, 3.5)    # API interna — parece rápida pero Cloudflare vigila
DELAY_FOTOCASA  = (2.5, 5.0)    # Reese84 anti-bot, necesita calma
DELAY_ENTRE_ARCHIVOS = (5, 12)  # Pausa entre archivos JSON

# Pausa larga cada N peticiones para simular "descanso humano"
BATCH_SIZE = 25                  # cada 25 peticiones
BATCH_PAUSE = (15, 30)           # pausa de 15-30s

# Máximo de reintentos ante bloqueo
MAX_REINTENTOS = 3

# Refrescar la página cada N evaluate() para evitar heap growth de Playwright
# (Playwright GC-colecta el page object tras miles de evaluate() acumulados)
REFRESH_PAGE_EVERY = 50

# Guardar resultados intermedios cada N archivos procesados
SAVE_EVERY_N_FILES = 5

# Espera máxima para que se resuelva el captcha Cloudflare (segundos)
CLOUDFLARE_WAIT_MAX = 300        # 5 minutos
# VPN: peticiones con VPN activa / sin VPN (ciclo)
VPN_ON_REQUESTS  = 30            # hacer N peticiones con VPN conectada
VPN_OFF_REQUESTS = 20            # hacer N peticiones sin VPN (IP real)
VPN_COUNTRIES = ['ES', 'FR', 'DE', 'IT', 'NL', 'PT', 'BE', 'CH', 'SE', 'PL', 'CZ', 'RO']


# ─── Rotación ProtonVPN ───────────────────────────────────────────────────────────────

class ProtonVPNRotator:
    """Cicla ProtonVPN: ON durante N peticiones, OFF durante M, repite.

    Cada vez que se conecta, elige un país aleatorio diferente al anterior.
    Solo se usa para Idealista (Cloudflare). Fotocasa usa el Chrome real
    con cookies que no necesitan VPN.
    """

    def __init__(self, on_requests: int = VPN_ON_REQUESTS,
                 off_requests: int = VPN_OFF_REQUESTS):
        self.on_requests = on_requests
        self.off_requests = off_requests
        self._contador = 0                # peticiones desde último cambio
        self._vpn_activa = False
        self._ultimo_pais = None
        self._enabled = self._detectar_protonvpn()
        if not self._enabled:
            log.warning('ProtonVPN CLI no detectado — rotación VPN desactivada.')

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def vpn_activa(self) -> bool:
        return self._vpn_activa

    @staticmethod
    def _detectar_protonvpn() -> bool:
        return shutil.which('protonvpn') is not None

    def obtener_ip(self) -> str:
        """IP pública actual."""
        try:
            if requests:
                r = requests.get('https://api.ipify.org', timeout=10)
                return r.text.strip()
            with urllib.request.urlopen('https://api.ipify.org', timeout=10) as r:
                return r.read().decode().strip()
        except Exception:
            return 'desconocida'

    def conectar(self) -> bool:
        """Conecta VPN. Con plan de pago elige país aleatorio, con free usa lo disponible."""
        if not self._enabled:
            return False

        log.info('VPN: Conectando...')
        try:
            # Desconectar primero si estaba conectada
            if self._vpn_activa:
                subprocess.run(['protonvpn', 'disconnect'],
                               capture_output=True, timeout=30)
                time.sleep(2)

            # Intentar con país aleatorio (plan de pago)
            paises_disponibles = [p for p in VPN_COUNTRIES if p != self._ultimo_pais]
            pais = random.choice(paises_disponibles) if paises_disponibles else random.choice(VPN_COUNTRIES)

            result = subprocess.run(
                ['protonvpn', 'connect', '--country', pais],
                capture_output=True, text=True, timeout=60
            )
            if result.returncode == 0:
                self._vpn_activa = True
                self._ultimo_pais = pais
                self._contador = 0
                time.sleep(3)
                ip = self.obtener_ip()
                log.info('VPN: Conectado a %s — IP: %s', pais, ip)
                return True

            # Fallback: plan gratuito (sin country ni random)
            log.debug('VPN: --country no disponible, conectando con servidor free...')
            result = subprocess.run(
                ['protonvpn', 'connect'],
                capture_output=True, text=True, timeout=60
            )
            if result.returncode == 0:
                self._vpn_activa = True
                self._ultimo_pais = 'FREE'
                self._contador = 0
                time.sleep(3)
                ip = self.obtener_ip()
                log.info('VPN: Conectado (free) — IP: %s', ip)
                return True

            log.error('VPN: No se pudo conectar: %s', result.stderr[:200])
            return False

        except subprocess.TimeoutExpired:
            log.error('VPN: Timeout al conectar')
            return False
        except Exception as e:
            log.error('VPN: Error: %s', e)
            return False

    def desconectar(self) -> bool:
        """Desconecta VPN."""
        if not self._enabled or not self._vpn_activa:
            return True

        log.info('VPN: Desconectando...')
        try:
            subprocess.run(['protonvpn', 'disconnect'],
                           capture_output=True, timeout=30)
            self._vpn_activa = False
            self._contador = 0
            time.sleep(2)
            ip = self.obtener_ip()
            log.info('VPN: Desconectado — IP real: %s', ip)
            return True
        except Exception as e:
            log.error('VPN: Error al desconectar: %s', e)
            return False

    def tick(self) -> None:
        """Llamar después de cada petición. Gestiona el ciclo ON/OFF automáticamente."""
        if not self._enabled:
            return

        self._contador += 1

        if self._vpn_activa:
            # Estamos en fase VPN ON — ¿toca apagar?
            if self._contador >= self.on_requests:
                log.info('VPN: Ciclo ON completado (%d peticiones) — desconectando...',
                         self._contador)
                self.desconectar()
                # Pausa al cambiar de IP para no levantar sospechas
                pausa = random.uniform(5, 12)
                log.info('VPN: Pausa de %.0fs tras cambio de IP...', pausa)
                time.sleep(pausa)
        else:
            # Estamos en fase VPN OFF — ¿toca encender?
            if self._contador >= self.off_requests:
                log.info('VPN: Ciclo OFF completado (%d peticiones) — conectando...',
                         self._contador)
                self.conectar()
                # Pausa al cambiar de IP
                pausa = random.uniform(5, 12)
                log.info('VPN: Pausa de %.0fs tras cambio de IP...', pausa)
                time.sleep(pausa)

    def cleanup(self) -> None:
        """Desconectar VPN al terminar el script (resistente a Ctrl+C)."""
        if self._vpn_activa:
            try:
                self.desconectar()
            except (KeyboardInterrupt, SystemExit):
                # Forzar desconexión aunque el usuario pulse Ctrl+C
                try:
                    subprocess.run(['protonvpn', 'disconnect'],
                                   capture_output=True, timeout=10)
                except Exception:
                    pass
            except Exception:
                pass

# ─── Logging ──────────────────────────────────────────────────────────────────

log = logging.getLogger('verificar_auto')


def configurar_logging(verbose: bool = False):
    """Configura logging con formato timestamp para cron."""
    nivel = logging.DEBUG if verbose else logging.INFO
    fmt = '%(asctime)s [%(levelname)s] %(message)s'
    logging.basicConfig(
        level=nivel,
        format=fmt,
        datefmt='%Y-%m-%d %H:%M:%S',
        stream=sys.stdout,
    )


# ─── Utilidades ───────────────────────────────────────────────────────────────

def chrome_debug_disponible(port: int = CHROME_DEBUG_PORT) -> bool:
    """Comprueba si hay un Chrome con CDP escuchando en el puerto dado."""
    import socket
    try:
        with socket.create_connection(('localhost', port), timeout=1):
            return True
    except OSError:
        return False


def cargar_api_key() -> str:
    """Lee INMOCAPT_API_KEY desde .env o variable de entorno."""
    api_key = os.environ.get('INMOCAPT_API_KEY', '')
    if api_key:
        return api_key
    env_path = os.path.join(SCRIPT_DIR, '.env')
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
        config_path = os.path.join(SCRIPT_DIR, 'config.json')
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        return config.get('api', {})
    except Exception:
        return {}


def cargar_todos_los_json(directorio: str = None) -> list:
    """Carga todos los JSON de viviendas del directorio.

    Retorna lista de dicts: [{archivo, portal, ubicacion, url_busqueda, viviendas}]
    """
    if directorio is None:
        directorio = SCRIPT_DIR
    archivos = sorted(glob.glob(os.path.join(directorio, 'viviendas_*.json')))
    datos = []

    for archivo in archivos:
        nombre = os.path.basename(archivo)
        # No cargar el fichero de descatalogadas
        if nombre == 'viviendas_descatalogadas.json':
            continue
        try:
            with open(archivo, 'r', encoding='utf-8') as f:
                data = json.load(f)

            if nombre.startswith('viviendas_idealista_'):
                portal = 'idealista'
            elif nombre.startswith('viviendas_fotocasa_'):
                portal = 'fotocasa'
            else:
                portal = 'desconocido'

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
            log.warning('Error leyendo %s: %s', archivo, e)

    return datos


# ─── Sesión Playwright CDP ────────────────────────────────────────────────────

class CDPSession:
    """Conecta al Chrome real (puerto 9222) o lanza Chromium de respaldo.

    Gestiona la conexión CDP para verificar URLs en contexto de navegador
    real, evitando bloqueos de Cloudflare (Idealista) y Reese84 (Fotocasa).
    """

    def __init__(self):
        self._playwright = None
        self._browser = None
        self._chrome_process = None
        self._owns_process = False
        self.page = None
        self._port_used = None
        self._current_portal = None  # 'idealista' | 'fotocasa'
        self._eval_count = 0          # contador de evaluate() para refresh periódico

    def __enter__(self):
        if _sync_playwright is None:
            raise RuntimeError(
                'playwright no está instalado. '
                'Ejecuta: pip install playwright && playwright install chromium'
            )

        self._playwright = _sync_playwright().start()

        if chrome_debug_disponible(CHROME_DEBUG_PORT):
            log.info('Conectando al Chrome real (puerto %d)...', CHROME_DEBUG_PORT)
            self._browser = self._playwright.chromium.connect_over_cdp(
                f'http://localhost:{CHROME_DEBUG_PORT}'
            )
            self._port_used = CHROME_DEBUG_PORT
            self._owns_process = False
            log.info('Conectado al Chrome con perfil real.')
        else:
            log.warning(
                'Chrome real (puerto %d) no disponible. '
                'Lanza start_chrome_debug.sh para evitar captchas.',
                CHROME_DEBUG_PORT,
            )
            if not os.path.isfile(CHROMIUM_PATH):
                raise RuntimeError(
                    f'Chromium no encontrado en {CHROMIUM_PATH}. '
                    'Ejecuta: playwright install chromium'
                )
            log.info('Lanzando Chromium de respaldo (puerto %d)...', CHROME_FALLBACK_PORT)
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
            log.info('Chromium de respaldo PID: %d', self._chrome_process.pid)

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
        return self

    def __exit__(self, *args):
        if self._owns_process:
            try:
                if self._browser:
                    self._browser.close()
            except BaseException:
                pass
        try:
            if self._playwright:
                self._playwright.stop()
        except BaseException:
            pass
        if self._owns_process:
            try:
                if self._chrome_process and self._chrome_process.poll() is None:
                    os.killpg(os.getpgid(self._chrome_process.pid), signal.SIGTERM)
            except BaseException:
                pass
            log.info('Chromium de respaldo cerrado.')
        else:
            log.info('Desconectado del Chrome real (sigue corriendo en :%d).', self._port_used)

    def asegurar_contexto(self, portal: str, force: bool = False) -> None:
        """Navega al dominio del portal si la pestaña no está ya allí."""
        if not force and self._current_portal == portal:
            return
        if portal == 'fotocasa':
            self._navegar_fotocasa(force)
        elif portal == 'idealista':
            self._navegar_idealista(force)
        self._current_portal = portal

    def _esta_bloqueado_cloudflare(self) -> bool:
        """Detecta si la pestaña muestra un challenge de Cloudflare."""
        try:
            html = self.page.content()[:3000].lower()
            return ('var dd=' in html or '_cf_chl' in html or
                    'please enable js' in html or 'just a moment' in html or
                    'challenge-platform' in html)
        except Exception:
            return False

    def esperar_desbloqueo_cloudflare(self, portal: str = 'idealista') -> bool:
        """Espera a que Cloudflare se desbloquee (el usuario resuelve el captcha
        en el navegador, o Cloudflare lo auto-resuelve tras el JS challenge).

        Retorna True si se desbloquea, False si timeout.
        """
        if not self._esta_bloqueado_cloudflare():
            return True

        log.warning('Cloudflare challenge detectado. Esperando resolución '
                    '(max %ds)...', CLOUDFLARE_WAIT_MAX)
        log.warning('Si ves un captcha en el navegador Chrome, resuélvelo manualmente.')

        inicio = time.time()
        while time.time() - inicio < CLOUDFLARE_WAIT_MAX:
            time.sleep(5)
            if not self._esta_bloqueado_cloudflare():
                log.info('Cloudflare desbloqueado tras %.0fs.',
                         time.time() - inicio)
                # Dar tiempo extra para que las cookies se establezcan
                time.sleep(3)
                return True
            elapsed = int(time.time() - inicio)
            if elapsed % 30 == 0:
                log.info('  Esperando desbloqueo... (%ds/%ds)', elapsed, CLOUDFLARE_WAIT_MAX)

        log.error('Timeout esperando desbloqueo Cloudflare (%ds).', CLOUDFLARE_WAIT_MAX)
        return False

    def _navegar_fotocasa(self, force: bool = False) -> None:
        try:
            current = self.page.url
            if force or 'fotocasa.es' not in current:
                log.info('Navegando a fotocasa.es para establecer contexto...')
                try:
                    self.page.goto('https://www.fotocasa.es/es/', timeout=20000,
                                   wait_until='domcontentloaded')
                except Exception:
                    pass
                log.info('Contexto fotocasa.es listo.')
        except Exception:
            pass

    def _navegar_idealista(self, force: bool = False) -> None:
        try:
            current = self.page.url
            if force or 'idealista.com' not in current:
                log.info('Navegando a idealista.com para establecer contexto...')
                try:
                    self.page.goto('https://www.idealista.com/', timeout=25000,
                                   wait_until='domcontentloaded')
                except Exception:
                    pass
                # Comprobar si Cloudflare nos bloquea al entrar
                if self._esta_bloqueado_cloudflare():
                    self.esperar_desbloqueo_cloudflare('idealista')
                log.info('Contexto idealista.com listo.')
        except Exception:
            pass

    # ── Gestión de heap / page refresh ──────────────────────────────

    def refresh_page(self) -> None:
        """Navega a about:blank para liberar contextos JS acumulados.

        Cada page.evaluate()/page.goto() crea un execution context en V8 que
        Playwright rastrea internamente. Tras decenas de llamadas, el heap crece
        hasta que Playwright GC-colecta el object → crash o bloqueo.
        Navegar a about:blank destruye todos esos contextos de golpe.
        """
        log.info('Refrescando pagina para liberar memoria JS '
                 '(eval_count=%d)...', self._eval_count)

        def _do_blank():
            self.page.goto('about:blank', timeout=10000, wait_until='load')

        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(_do_blank)
                future.result(timeout=15)  # timeout externo de seguridad
            time.sleep(1)
        except FuturesTimeout:
            log.warning('refresh_page: timeout — la pagina ya esta bloqueada, '
                        'intentando recuperar...')
            self._recover_page()
            return
        except Exception as e:
            log.debug('Error en refresh_page: %s', e)
        self._eval_count = 0
        self._current_portal = None  # forzar re-navegación al portal

    def maybe_refresh(self) -> None:
        """Refresca la página si hemos superado el umbral de evaluate()."""
        if self._eval_count >= REFRESH_PAGE_EVERY:
            self.refresh_page()

    def _recover_page(self) -> bool:
        """Recupera la conexión tras GC/crash de Playwright.

        Cuando Playwright GC-colecta el page object, toda la conexión interna
        queda corrupta: ctx.new_page() se cuelga indefinidamente.
        La ÚNICA solución fiable es destruir la instancia de Playwright
        completa y reconectar desde cero vía CDP.
        """
        log.warning('Intentando recuperar conexion completa (playwright restart)...')

        # 1. Cerrar la conexión Playwright actual (sin tocar Chrome)
        try:
            if self._browser:
                self._browser.close()
        except Exception:
            pass
        try:
            if self._playwright:
                self._playwright.stop()
        except Exception:
            pass
        self._browser = None
        self._playwright = None
        self.page = None
        time.sleep(2)

        # 2. Crear nueva instancia de Playwright y reconectar CDP
        #    Usamos un thread con timeout para evitar cuelgues
        port = self._port_used or CHROME_DEBUG_PORT

        def _reconnect():
            pw = _sync_playwright().start()
            browser = pw.chromium.connect_over_cdp(
                f'http://localhost:{port}'
            )
            contexts = browser.contexts
            ctx = (
                contexts[0] if contexts
                else browser.new_context(
                    viewport={'width': 1366, 'height': 768},
                    locale='es-ES',
                    timezone_id='Europe/Madrid',
                )
            )
            pages = ctx.pages
            page = pages[0] if pages else ctx.new_page()
            page.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', "
                "{get: () => undefined})"
            )
            return pw, browser, page

        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(_reconnect)
                pw, browser, page = future.result(timeout=30)

            self._playwright = pw
            self._browser = browser
            self.page = page
            self._eval_count = 0
            self._current_portal = None
            log.info('Reconexion CDP completa exitosa.')
            return True

        except FuturesTimeout:
            log.error('Reconexion CDP: timeout de 30s — Chrome no responde.')
            return False
        except Exception as e:
            log.error('Reconexion CDP fallida: %s', e)
            return False

    def safe_goto(self, url: str, timeout_ms: int = 30000,
                  wait_until: str = 'domcontentloaded'):
        """page.goto() con timeout externo para evitar bloqueos por heap GC.

        Cuando Playwright GC-colecta el page object, page.goto() NO lanza
        excepción — simplemente se bloquea para siempre esperando una respuesta
        que nunca llega. Este wrapper ejecuta goto() en un thread con timeout
        de Python, de forma que si tarda más de (timeout_ms + 5s) se aborta.

        Raises:
            RuntimeError si se detecta heap GC o timeout externo.
            Exception para otros errores de navegación.
        """
        self.maybe_refresh()

        outer_timeout = (timeout_ms / 1000) + 8  # segundos

        def _do_goto():
            return self.page.goto(url, timeout=timeout_ms, wait_until=wait_until)

        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(_do_goto)
                result = future.result(timeout=outer_timeout)
            self._eval_count += 5  # goto = ~5 contextos JS
            return result
        except FuturesTimeout:
            raise RuntimeError(
                f'safe_goto: timeout externo ({outer_timeout:.0f}s) — '
                'possible heap GC'
            )
        except Exception as e:
            err_msg = str(e).lower()
            is_heap = (
                'has been collected' in err_msg or
                'unbounded heap growth' in err_msg or
                ('has no attribute' in err_msg and '_object' in err_msg) or
                'cannot switch to a different thread' in err_msg
            )
            if is_heap:
                raise RuntimeError(
                    f'safe_goto: heap GC detectado: {str(e)[:100]}'
                ) from e
            raise  # otros errores (timeout playwright, red, etc.) → propagar

    def safe_evaluate(self, js_code: str, arg=None):
        """page.evaluate() con refresh preventivo y recuperación ante GC.

        Args:
            js_code: código JavaScript a evaluar
            arg: argumento a pasar al JS (opcional)

        Returns:
            Resultado de la evaluación, o None si falla irrecuperablemente.

        Raises:
            RuntimeError: si no se puede recuperar la página.
        """
        # Refresh preventivo
        self.maybe_refresh()

        for intento in range(3):
            try:
                if arg is not None:
                    result = self.page.evaluate(js_code, arg)
                else:
                    result = self.page.evaluate(js_code)
                self._eval_count += 1
                return result
            except Exception as e:
                err_msg = str(e).lower()
                is_gc_error = (
                    'has been collected' in err_msg or
                    'unbounded heap growth' in err_msg or
                    ('has no attribute' in err_msg and '_object' in err_msg) or
                    'target page, context or browser has been closed' in err_msg
                )
                is_thread_error = (
                    'cannot switch to a different thread' in err_msg or
                    'which happens to have exited' in err_msg
                )
                if is_gc_error or is_thread_error:
                    log.warning('Error de conexion en evaluate (intento %d/3): %s',
                                intento + 1, str(e)[:120])
                    if self._recover_page():
                        # Re-navegar al portal antes de reintentar
                        self._current_portal = None
                        time.sleep(2)
                        continue
                    else:
                        raise RuntimeError(
                            'No se pudo recuperar la pagina tras error de heap/thread'
                        ) from e
                else:
                    # Error no relacionado con GC — propagar
                    raise

        raise RuntimeError('safe_evaluate: 3 intentos fallidos')


# ─── JavaScript para verificación ─────────────────────────────────────────────

# Idealista: usa API /adContactInfoForDetail.ajax (fiable) + fallback HTML
# NOTA: /detail/{id}/datalayer devuelve adId incluso para anuncios descatalogados
#       así que NO es fiable. adContactInfo devuelve result:ERROR para descatalogados.
_JS_FETCH_IDEALISTA = """
    async (url) => {
        try {
            const match = url.match(/\\/inmueble\\/(\\d+)/);
            if (!match) return 'NO_ID:';
            const id = match[1];

            // MÉTODO 1: /adContactInfoForDetail.ajax (FIABLE)
            // Activo   → {"result":"OK","data":{...}}
            // Baja     → {"result":"ERROR","data":null}
            try {
                const r1 = await fetch(
                    'https://www.idealista.com/es/ajax/listingController/adContactInfoForDetail.ajax?adId=' + id,
                    { method: 'GET', credentials: 'include' }
                );
                if (r1.ok) {
                    const t = await r1.text();
                    if (t.includes('"result":"ERROR"')) return 'NOTFOUND_API:';
                    if (t.includes('"result":"OK"')) return 'OK_API:';
                }
            } catch(e) {}

            // MÉTODO 2: HTML fallback
            const resp = await fetch(url, {
                method: 'GET', credentials: 'include', redirect: 'follow'
            });
            if (!resp.ok && resp.status === 404) return 'NOTFOUND:';
            const chunks = [];
            const reader = resp.body.getReader();
            let bytes = 0;
            while (bytes < 8192) {
                const { done, value } = await reader.read();
                if (done) break;
                chunks.push(value);
                bytes += value.length;
            }
            reader.cancel();
            let total = 0;
            for (const c of chunks) total += c.length;
            const combined = new Uint8Array(total);
            let off = 0;
            for (const c of chunks) { combined.set(c, off); off += c.length; }
            const html = new TextDecoder().decode(combined).toLowerCase();
            if (html.includes('deactivated-detail') ||
                html.includes('este anuncio ya no est') ||
                html.includes('el anunciante lo dio de baja')) return 'DEACTIVATED:';
            if (html.includes('please enable js') ||
                html.includes('var dd=') ||
                html.includes('_cf_chl')) return 'BLOCKED:';
            return 'OK:';
        } catch(e) {
            return 'FETCH_ERROR:' + e.toString();
        }
    }
"""

# Fotocasa: ya no usa fetch JS — usa page.goto() directa (ver verificar_fotocasa)
# Reese84 bloquea fetch() pero la navegación real del browser pasa siempre.


# ─── Funciones de verificación ─────────────────────────────────────────────────

def verificar_idealista(url: str, page, cdp_session=None) -> bool:
    """Verifica URL de Idealista via API. Retorna True=activa, False=descatalogada."""
    for intento in range(MAX_REINTENTOS):
        try:
            if cdp_session:
                cdp_session.asegurar_contexto('idealista')
                result = cdp_session.safe_evaluate(_JS_FETCH_IDEALISTA, url)
            else:
                result = page.evaluate(_JS_FETCH_IDEALISTA, url)
        except RuntimeError as e:
            # Error irrecuperable (heap/thread) — pausar para captcha manual
            log.error('Error de conexion irrecuperable: %s', e)
            log.warning('=' * 60)
            log.warning('ATENCION: La conexion con el navegador se ha roto.')
            log.warning('Posible captcha de Cloudflare pendiente.')
            log.warning('1. Revisa el navegador Chrome y resuelve el captcha')
            log.warning('2. Pulsa ENTER aqui para continuar')
            log.warning('=' * 60)
            try:
                input('>>> Pulsa ENTER cuando hayas resuelto el captcha... ')
            except EOFError:
                # Si estamos en un entorno sin stdin (cron), esperar y reintentar
                log.warning('Sin terminal interactivo — esperando %ds...', CLOUDFLARE_WAIT_MAX)
                time.sleep(CLOUDFLARE_WAIT_MAX)
            # Reconectar tras la pausa
            if cdp_session and cdp_session._recover_page():
                log.info('Conexion recuperada tras pausa manual.')
                cdp_session._current_portal = None
                cdp_session.asegurar_contexto('idealista', force=True)
                time.sleep(3)
                continue  # reintentar esta URL
            else:
                log.error('No se pudo reconectar — marcando como activa (conservador).')
                return True
        except Exception as e:
            log.debug('Error evaluando JS para %s: %s', url, e)
            return True  # conservador

        log.debug('Idealista %s → %s', url.split('/')[-2], result[:40] if result else 'None')

        if not result or result.startswith('FETCH_ERROR'):
            log.debug('Fetch error para %s: %s', url, result)
            return True

        if result in ('NOTFOUND:', 'NOTFOUND_API:', 'DEACTIVATED:'):
            return False

        if result in ('OK_API:', 'OK:', 'NO_ID:'):
            return True

        if result == 'BLOCKED:':
            log.warning('Bloqueado por Cloudflare (intento %d/%d)',
                        intento + 1, MAX_REINTENTOS)
            # Navegar a la home para exponer el challenge al usuario
            try:
                page.goto('https://www.idealista.com/', timeout=25000,
                          wait_until='domcontentloaded')
            except Exception:
                pass
            # Esperar a que Cloudflare se resuelva (manual o auto JS challenge)
            if cdp_session and cdp_session.esperar_desbloqueo_cloudflare('idealista'):
                log.info('Cloudflare resuelto, reintentando...')
                time.sleep(random.uniform(3, 6))
                continue
            else:
                # Sin cdp_session o timeout: backoff exponencial
                wait = random.uniform(30, 60) * (intento + 1)
                log.warning('Esperando %.0fs antes de reintentar...', wait)
                time.sleep(wait)
                continue

        return True  # respuesta inesperada → conservador

    log.warning('Reintentos agotados para %s — marcando como activa.', url)
    return True


def _fotocasa_esta_bloqueada(page) -> bool:
    """Comprueba si la página actual muestra un challenge Reese84."""
    try:
        html = page.content()[:4000]
    except Exception:
        return False
    return ('LO SENTIMOS' in html or
            'SENTIMOS' in html or
            'onProtectionInitialized' in html or
            'challenge-platform' in html.lower())


def _fotocasa_esperar_challenge(page, max_wait: int = 20) -> bool:
    """Espera a que el challenge Reese84 se resuelva solo.

    Fotocasa usa un JS challenge que normalmente se auto-resuelve en 3-10s.
    Retorna True si se desbloqueó, False si sigue bloqueado tras max_wait.
    """
    inicio = time.time()
    while time.time() - inicio < max_wait:
        time.sleep(3)
        if not _fotocasa_esta_bloqueada(page):
            return True
    return False


def verificar_fotocasa(url: str, page, cdp_session=None) -> bool:
    """Verifica URL de Fotocasa via navegación directa (page.goto).

    Reese84 bloquea las peticiones fetch() programáticas, pero la navegación
    real del browser pasa el anti-bot casi siempre. Si aparece el challenge
    JS, esperamos a que se auto-resuelva (normalmente 3-10s).

    Retorna True=activa, False=descatalogada.
    """
    for intento in range(MAX_REINTENTOS):
        # Refresh preventivo para evitar heap growth (igual que safe_evaluate)
        if cdp_session:
            cdp_session.maybe_refresh()

        try:
            if cdp_session:
                cdp_session.safe_goto(url)
            else:
                page.goto(url, timeout=30000, wait_until='domcontentloaded')
        except RuntimeError as e:
            # Heap GC o timeout externo — intentar recuperación automática
            log.warning('Error de heap en goto (intento %d/%d): %s',
                        intento + 1, MAX_REINTENTOS, str(e)[:100])
            if cdp_session and cdp_session._recover_page():
                log.info('Conexion recuperada automaticamente.')
                cdp_session._current_portal = None
                page = cdp_session.page
                time.sleep(2)
                continue
            # Recuperación automática falló — pedir intervención manual
            log.warning('=' * 60)
            log.warning('ATENCION: La conexion con el navegador se ha roto.')
            log.warning('1. Revisa el navegador Chrome')
            log.warning('2. Pulsa ENTER aqui para continuar')
            log.warning('=' * 60)
            try:
                input('>>> Pulsa ENTER para continuar... ')
            except EOFError:
                time.sleep(60)
            if cdp_session and cdp_session._recover_page():
                cdp_session._current_portal = None
                page = cdp_session.page
                time.sleep(3)
                continue
            return True
        except Exception as e:
            log.debug('Error goto para %s: %s', url, e)
            return True

        # Breve espera para que la página cargue (NO networkidle, puede colgar)
        time.sleep(2)

        # Si hay challenge Reese84, darle tiempo para resolver automáticamente
        if _fotocasa_esta_bloqueada(page):
            log.debug('Challenge Reese84 detectado, esperando auto-resolución...')
            if _fotocasa_esperar_challenge(page, max_wait=25):
                log.debug('Challenge Reese84 resuelto automáticamente.')
            else:
                log.warning('Bloqueado por Reese84 (intento %d/%d) — '
                            'refrescando tokens...', intento + 1, MAX_REINTENTOS)
                try:
                    if cdp_session:
                        cdp_session.safe_goto('https://www.fotocasa.es/es/',
                                              timeout_ms=20000)
                    else:
                        page.goto('https://www.fotocasa.es/es/', timeout=20000,
                                  wait_until='domcontentloaded')
                except Exception:
                    pass
                time.sleep(5)
                if _fotocasa_esta_bloqueada(page):
                    _fotocasa_esperar_challenge(page, max_wait=25)
                time.sleep(random.uniform(3, 6))
                continue

        # Comprobar URL final tras redirects + posible resolución de challenge
        try:
            final_url = page.url.lower()
        except Exception:
            return True

        # Descatalogada: redirige a /propertynotfound o a listado genérico
        if 'propertynotfound' in final_url:
            return False
        if '/vivienda/' in url.lower() and '/viviendas/' in final_url:
            return False

        # Si la URL final contiene el ID original → activa
        id_match = re.search(r'/([0-9]{6,})/d', url)
        if id_match and id_match.group(1) in final_url:
            return True

        # Chequear contenido HTML como fallback
        try:
            html_check = page.content()[:5000].lower()
        except Exception:
            return True

        if 'propertynotfound' in html_check or 'no encontrado' in html_check:
            return False

        # Llegamos aquí = probablemente activa
        return True

    log.warning('Reintentos agotados para %s — marcando como activa.', url)
    return True


# ─── Envío a API ──────────────────────────────────────────────────────────────

def enviar_descatalogadas(urls_por_ubicacion: dict) -> bool:
    """Envía las URLs descatalogadas a la API. Retorna True si todo OK."""
    if requests is None:
        log.error('requests no instalado — no se puede enviar a la API.')
        return False

    api_config = cargar_config_api()
    api_key = cargar_api_key()
    base_url = api_config.get('url', '').replace('/upload', '/delist')

    if not base_url or not api_key:
        log.warning('API no configurada (url=%s, key=%s) — solo JSON local.',
                     bool(base_url), bool(api_key))
        return False

    log.info('Enviando descatalogadas a la API (%s)...', base_url)
    exito = True

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
                log.info('  API OK: %s — %d URLs enviadas', ubicacion, len(urls))
            else:
                log.error('  API ERROR: %s — HTTP %d: %s',
                          ubicacion, response.status_code, response.text[:200])
                exito = False
        except Exception as e:
            log.error('  API ERROR: %s — %s', ubicacion, e)
            exito = False

    return exito


# ─── Limpieza de JSONs (eliminar descatalogadas de los fuentes) ───────────────

def limpiar_archivo_json(archivo: str, urls_descatalogadas: set) -> int:
    """Elimina viviendas descatalogadas de UN archivo JSON fuente.

    Se llama inmediatamente después de procesar cada archivo, para que
    las descatalogadas se borren al momento (no al final del script).

    Args:
        archivo: ruta al archivo JSON fuente
        urls_descatalogadas: set de URLs a eliminar

    Returns:
        Número de viviendas eliminadas.
    """
    if not urls_descatalogadas:
        return 0

    try:
        with open(archivo, 'r', encoding='utf-8') as f:
            data = json.load(f)

        antes = len(data.get('viviendas', []))
        data['viviendas'] = [
            v for v in data.get('viviendas', [])
            if v.get('url', '') not in urls_descatalogadas
        ]
        despues = len(data['viviendas'])
        eliminadas = antes - despues

        if eliminadas > 0:
            data['total'] = despues
            with open(archivo, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            log.info('  Limpiado %s: %d viviendas eliminadas (%d restantes)',
                     os.path.basename(archivo), eliminadas, despues)

        return eliminadas

    except Exception as e:
        log.error('  Error limpiando %s: %s', archivo, e)
        return 0


def guardar_progreso_intermedio(output_file: str, todas_descatalogadas: list,
                                no_merge: bool = False) -> None:
    """Guarda resultados intermedios a disco para no perder progreso ante crash.

    Se llama periódicamente durante la ejecución (cada SAVE_EVERY_N_FILES archivos).
    Fusiona con descatalogadas previas igual que el guardado final.
    """
    descatalogadas_previas = []
    if not no_merge and os.path.isfile(output_file):
        try:
            with open(output_file, 'r', encoding='utf-8') as f:
                prev = json.load(f)
            descatalogadas_previas = prev.get('detalle', [])
        except Exception:
            pass

    urls_existentes = {d['url'] for d in descatalogadas_previas}
    nuevas = [d for d in todas_descatalogadas if d['url'] not in urls_existentes]
    todas_merged = descatalogadas_previas + nuevas

    output_data = {
        'timestamp': datetime.now().isoformat(),
        'total': len(todas_merged),
        'nuevas_esta_ejecucion': len(nuevas),
        'parcial': True,  # marca de que es guardado intermedio
        'urls': [d['url'] for d in todas_merged],
        'detalle': todas_merged,
    }

    os.makedirs(os.path.dirname(output_file) or '.', exist_ok=True)
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)

    log.info('Progreso intermedio guardado: %s (%d total, %d nuevas)',
             output_file, len(todas_merged), len(nuevas))


# ─── Bucle principal ──────────────────────────────────────────────────────────

def ejecutar_verificacion(args) -> int:
    """Ejecuta la verificación completa. Retorna exit code (0=OK, 1=error, 2=con descatalogadas)."""

    # Cargar datos
    datos = cargar_todos_los_json(SCRIPT_DIR)

    if not datos:
        log.error('No se encontraron archivos viviendas_*.json en %s', SCRIPT_DIR)
        return 1

    # Filtrar por portal
    if args.portal != 'todos':
        datos = [d for d in datos if d['portal'] == args.portal]
        if not datos:
            log.error('No hay archivos para el portal "%s"', args.portal)
            return 1

    total_archivos = len(datos)
    total_viviendas = sum(len(d['viviendas']) for d in datos)
    portales_presentes = sorted(set(d['portal'] for d in datos))

    log.info('=' * 60)
    log.info('VERIFICACION AUTOMATICA DE ANUNCIOS')
    log.info('=' * 60)
    log.info('Archivos JSON: %d', total_archivos)
    log.info('Viviendas totales: %d', total_viviendas)
    log.info('Portales: %s', ', '.join(portales_presentes))
    log.info('Delay configurado: %.1f-%.1fs (idealista) / %.1f-%.1fs (fotocasa)',
             args.delay_idealista_min, args.delay_idealista_max,
             args.delay_fotocasa_min, args.delay_fotocasa_max)

    # Ordenar: primero idealista (API rápida), luego fotocasa (más lenta)
    datos.sort(key=lambda d: 0 if d['portal'] == 'idealista' else 1)

    # Resultados
    todas_descatalogadas = []              # [{url, ubicacion, portal, titulo}]
    urls_por_ubicacion = {}                # {ubicacion: [urls]}
    descatalogadas_por_archivo = {}        # {ruta: set(urls)}
    stats = {
        'verificadas': 0,
        'activas': 0,
        'descatalogadas': 0,
        'errores': 0,
    }

    # Inicializar VPN si se ha pedido
    vpn = None
    if args.vpn:
        vpn = ProtonVPNRotator(
            on_requests=args.vpn_on,
            off_requests=args.vpn_off,
        )
        if vpn.enabled:
            ip_actual = vpn.obtener_ip()
            log.info('VPN: Rotación activada — ciclo ON=%d / OFF=%d peticiones',
                     args.vpn_on, args.vpn_off)
            log.info('VPN: IP actual: %s', ip_actual)
            # Conectar VPN desde el inicio
            vpn.conectar()
        else:
            vpn = None

    # Conectar al navegador
    log.info('Conectando al navegador via CDP...')
    cdp = CDPSession()
    cdp.__enter__()

    try:
        for i, datos_json in enumerate(datos, 1):
            portal = datos_json['portal']
            ubicacion = datos_json['ubicacion']
            viviendas = datos_json['viviendas']
            archivo = datos_json['archivo']
            n_viviendas = len(viviendas)
            nombre_archivo = os.path.basename(archivo)

            log.info('-' * 60)
            log.info('[%d/%d] %s (%s) — %d viviendas [%s]',
                     i, total_archivos, ubicacion, portal, n_viviendas, nombre_archivo)

            # Cambiar contexto de portal si necesario
            cdp.asegurar_contexto(portal)

            verificar_fn = verificar_idealista if portal == 'idealista' else verificar_fotocasa
            delay_range = (
                (args.delay_idealista_min, args.delay_idealista_max)
                if portal == 'idealista'
                else (args.delay_fotocasa_min, args.delay_fotocasa_max)
            )

            desc_archivo = []
            peticiones_archivo = 0

            for j, vivienda in enumerate(viviendas, 1):
                url = vivienda.get('url', '')
                if not url:
                    continue

                # Pausa larga cada BATCH_SIZE peticiones (simular humano)
                peticiones_archivo += 1
                if peticiones_archivo > 1 and peticiones_archivo % BATCH_SIZE == 0:
                    pausa_batch = random.uniform(*BATCH_PAUSE)
                    log.info('  Pausa anti-deteccion de %.0fs tras %d peticiones...',
                             pausa_batch, peticiones_archivo)
                    time.sleep(pausa_batch)
                    # Re-verificar que no nos han bloqueado durante la pausa
                    if cdp._esta_bloqueado_cloudflare():
                        cdp.esperar_desbloqueo_cloudflare(portal)

                titulo = vivienda.get('titulo', 'Sin título')[:60]

                try:
                    activo = verificar_fn(url, cdp.page, cdp_session=cdp)
                except RuntimeError as e:
                    # Ultimo recurso: la reconexion fallo incluso tras pausa manual
                    log.error('  [%d/%d] ERROR irrecuperable: %s', j, n_viviendas, e)
                    log.warning('Marcando vivienda como activa (conservador) y continuando.')
                    stats['errores'] += 1
                    activo = True

                stats['verificadas'] += 1

                if activo:
                    stats['activas'] += 1
                    if args.verbose:
                        log.debug('  [%d/%d] OK: %s', j, n_viviendas, titulo)
                    else:
                        # Mostrar progreso cada 10 viviendas activas
                        if j % 10 == 0:
                            log.info('  [%d/%d] progreso... (%d desc hasta ahora)',
                                     j, n_viviendas, len(desc_archivo))
                else:
                    stats['descatalogadas'] += 1
                    log.info('  [%d/%d] DESCATALOGADA: %s', j, n_viviendas, titulo)
                    desc_archivo.append(url)
                    todas_descatalogadas.append({
                        'url': url,
                        'ubicacion': ubicacion,
                        'portal': portal,
                        'titulo': vivienda.get('titulo', ''),
                    })

                # Rotación VPN (solo Idealista)
                if vpn and portal == 'idealista':
                    vpn.tick()
                    # Tras cambio de IP, re-establecer contexto del portal
                    # porque Cloudflare puede requerir nuevo handshake
                    if vpn._contador == 0:  # acaba de cambiar
                        cdp.asegurar_contexto('idealista', force=True)

                # Delay entre peticiones (con jitter humano)
                base_delay = random.uniform(*delay_range)
                # Añadir jitter extra aleatorio (a veces más lento, como un humano)
                if random.random() < 0.15:  # 15% de las veces, pausa extra
                    base_delay += random.uniform(2, 5)
                time.sleep(base_delay)

            if desc_archivo:
                urls_por_ubicacion.setdefault(ubicacion, []).extend(desc_archivo)
                descatalogadas_por_archivo[archivo] = set(desc_archivo)
                log.info('  >> %d descatalogadas en %s', len(desc_archivo), ubicacion)
                # Eliminar descatalogadas del JSON fuente inmediatamente
                limpiar_archivo_json(archivo, set(desc_archivo))
            else:
                log.info('  >> Todas activas en %s', ubicacion)

            # Guardado intermedio cada SAVE_EVERY_N_FILES archivos
            if i % SAVE_EVERY_N_FILES == 0 and todas_descatalogadas:
                output_file_tmp = os.path.join(args.output_dir, 'viviendas_descatalogadas.json')
                guardar_progreso_intermedio(output_file_tmp, todas_descatalogadas,
                                            no_merge=args.no_merge)

            # Pausa entre archivos
            if i < total_archivos:
                pausa = random.uniform(*DELAY_ENTRE_ARCHIVOS)
                log.debug('Pausa de %.0fs antes del siguiente archivo...', pausa)
                time.sleep(pausa)

    except KeyboardInterrupt:
        log.warning('Verificacion interrumpida por el usuario (SIGINT)')
        # Guardar progreso antes de salir
        if todas_descatalogadas:
            output_file_tmp = os.path.join(args.output_dir, 'viviendas_descatalogadas.json')
            log.info('Guardando progreso antes de salir...')
            guardar_progreso_intermedio(output_file_tmp, todas_descatalogadas,
                                        no_merge=args.no_merge)
    except Exception as e:
        log.error('Error inesperado durante la verificacion: %s', e, exc_info=True)
        stats['errores'] += 1
        # Guardar progreso ante crash
        if todas_descatalogadas:
            output_file_tmp = os.path.join(args.output_dir, 'viviendas_descatalogadas.json')
            log.info('Guardando progreso tras error...')
            guardar_progreso_intermedio(output_file_tmp, todas_descatalogadas,
                                        no_merge=args.no_merge)
    finally:
        cdp.__exit__(None, None, None)
        # Desconectar VPN al terminar
        if vpn:
            vpn.cleanup()

    # ─── Resumen ──────────────────────────────────────────────────────
    log.info('=' * 60)
    log.info('RESUMEN DE VERIFICACION')
    log.info('=' * 60)
    log.info('Viviendas verificadas: %d / %d', stats['verificadas'], total_viviendas)
    log.info('Activas:               %d', stats['activas'])
    log.info('Descatalogadas:        %d', stats['descatalogadas'])
    if stats['errores']:
        log.info('Errores:               %d', stats['errores'])

    # ─── Guardar JSON de descatalogadas ───────────────────────────────
    output_file = os.path.join(args.output_dir, 'viviendas_descatalogadas.json')

    # Cargar descatalogadas previas para no perder historial
    descatalogadas_previas = []
    if not args.no_merge and os.path.isfile(output_file):
        try:
            with open(output_file, 'r', encoding='utf-8') as f:
                prev = json.load(f)
            descatalogadas_previas = prev.get('detalle', [])
            log.info('Descatalogadas previas cargadas: %d', len(descatalogadas_previas))
        except Exception:
            pass

    # Merge: previas + nuevas, sin duplicados (por URL)
    urls_existentes = {d['url'] for d in descatalogadas_previas}
    nuevas = [d for d in todas_descatalogadas if d['url'] not in urls_existentes]
    todas_merged = descatalogadas_previas + nuevas

    output_data = {
        'timestamp': datetime.now().isoformat(),
        'total': len(todas_merged),
        'nuevas_esta_ejecucion': len(nuevas),
        'urls': [d['url'] for d in todas_merged],
        'detalle': todas_merged,
    }

    os.makedirs(args.output_dir, exist_ok=True)
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)

    log.info('Guardado: %s (%d total, %d nuevas)',
             output_file, len(todas_merged), len(nuevas))

    # ─── Enviar a API ─────────────────────────────────────────────────
    if args.send_api and urls_por_ubicacion:
        enviar_descatalogadas(urls_por_ubicacion)

    # ─── Código de salida ─────────────────────────────────────────────
    if stats['errores'] > 0:
        return 1
    if stats['descatalogadas'] > 0:
        return 2  # éxito pero con descatalogadas encontradas
    return 0


# ─── CLI ──────────────────────────────────────────────────────────────────────

def parse_args():
    parser = argparse.ArgumentParser(
        description='Verificador automático de anuncios inmobiliarios. '
                    'Comprueba si las viviendas de los JSON siguen activas.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos:
  %(prog)s                           # Verificar todo
  %(prog)s --portal idealista        # Solo Idealista
  %(prog)s --portal idealista --vpn  # Idealista con rotación VPN
  %(prog)s --vpn --vpn-on 25 --vpn-off 15  # VPN: 25 con, 15 sin, repite
  %(prog)s --send-api                # Enviar a API (limpieza automática)
  %(prog)s --verbose                 # Modo debug
  %(prog)s --dry-run                 # Solo mostrar qué se haría

Códigos de salida:
  0 = Todo OK, ninguna descatalogada
  1 = Error durante la ejecución
  2 = OK pero se encontraron viviendas descatalogadas
""",
    )
    parser.add_argument(
        '--portal', choices=['idealista', 'fotocasa', 'todos'],
        default='todos',
        help='Portal a verificar (default: todos)',
    )
    parser.add_argument(
        '--send-api', action='store_true',
        help='Enviar descatalogadas a la API de InmoCapt',
    )
    parser.add_argument(
        '--no-merge', action='store_true',
        help='No fusionar con descatalogadas previas (sobreescribir)',
    )
    parser.add_argument(
        '--output-dir', default=SCRIPT_DIR,
        help='Directorio de salida para viviendas_descatalogadas.json',
    )
    parser.add_argument(
        '--delay-idealista', type=float, default=None,
        help='Delay medio entre peticiones Idealista en segundos (default: 2.5)',
    )
    parser.add_argument(
        '--delay-fotocasa', type=float, default=None,
        help='Delay medio entre peticiones Fotocasa en segundos (default: 3.7)',
    )
    parser.add_argument(
        '-v', '--verbose', action='store_true',
        help='Modo verbose (mostrar cada vivienda activa)',
    )
    parser.add_argument(
        '--dry-run', action='store_true',
        help='Solo mostrar qué se haría, sin verificar',
    )

    # ── VPN ──
    vpn_group = parser.add_argument_group('VPN (ProtonVPN)', 'Rotación de IP via ProtonVPN para Idealista')
    vpn_group.add_argument(
        '--vpn', action='store_true',
        help='Activar rotación de VPN (ProtonVPN CLI) para Idealista',
    )
    vpn_group.add_argument(
        '--vpn-on', type=int, default=VPN_ON_REQUESTS,
        help=f'Peticiones con VPN conectada antes de desconectar (default: {VPN_ON_REQUESTS})',
    )
    vpn_group.add_argument(
        '--vpn-off', type=int, default=VPN_OFF_REQUESTS,
        help=f'Peticiones sin VPN antes de reconectar (default: {VPN_OFF_REQUESTS})',
    )

    args = parser.parse_args()

    # Calcular rangos de delay
    if args.delay_idealista is not None:
        d = args.delay_idealista
        args.delay_idealista_min = max(0.1, d * 0.6)
        args.delay_idealista_max = d * 1.4
    else:
        args.delay_idealista_min, args.delay_idealista_max = DELAY_IDEALISTA

    if args.delay_fotocasa is not None:
        d = args.delay_fotocasa
        args.delay_fotocasa_min = max(0.5, d * 0.6)
        args.delay_fotocasa_max = d * 1.4
    else:
        args.delay_fotocasa_min, args.delay_fotocasa_max = DELAY_FOTOCASA

    return args


def main():
    args = parse_args()
    configurar_logging(verbose=args.verbose)

    log.info('Inicio: %s', datetime.now().strftime('%Y-%m-%d %H:%M:%S'))

    if args.dry_run:
        datos = cargar_todos_los_json(SCRIPT_DIR)
        if args.portal != 'todos':
            datos = [d for d in datos if d['portal'] == args.portal]
        total = sum(len(d['viviendas']) for d in datos)
        log.info('[DRY-RUN] Se verificarian %d viviendas de %d archivos', total, len(datos))
        for d in datos:
            log.info('  %s (%s): %d viviendas',
                     d['ubicacion'], d['portal'], len(d['viviendas']))
        return 0

    exit_code = ejecutar_verificacion(args)
    log.info('Fin: %s — exit code %d', datetime.now().strftime('%Y-%m-%d %H:%M:%S'), exit_code)
    return exit_code


if __name__ == '__main__':
    sys.exit(main())
