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

    # Solo fotocasa, delay más alto, sin eliminar de JSONs
    ./verificar_auto.py --portal fotocasa --delay 3.0 --no-clean

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
import random
import signal
import logging
import argparse
import subprocess
import urllib.request
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

# Delays entre peticiones (segundos). Idealista API es rápida, Fotocasa necesita más.
DELAY_IDEALISTA = (0.3, 0.8)    # API interna, muy rápida
DELAY_FOTOCASA  = (2.0, 4.0)    # Reese84 anti-bot, necesita calma
DELAY_ENTRE_ARCHIVOS = (3, 6)   # Pausa entre archivos JSON

# Máximo de reintentos ante bloqueo
MAX_REINTENTOS = 3

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
                log.info('Contexto idealista.com listo.')
        except Exception:
            pass


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

# Fotocasa: fetch con redirect:follow y comprobar URL final
_JS_FETCH_FOTOCASA = """
    async (url) => {
        try {
            const resp = await fetch(url, {
                method: 'GET', credentials: 'include', redirect: 'follow'
            });
            const chunks = [];
            const reader = resp.body.getReader();
            let bytes = 0;
            while (bytes < 2048) {
                const { done, value } = await reader.read();
                if (done) break;
                chunks.push(value);
                bytes += value.length;
            }
            reader.cancel();
            const combined = new Uint8Array(bytes);
            let off = 0;
            for (const c of chunks) {
                combined.set(c.slice(0, Math.min(c.length, bytes - off)), off);
                off += c.length;
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


# ─── Funciones de verificación ─────────────────────────────────────────────────

def verificar_idealista(url: str, page) -> bool:
    """Verifica URL de Idealista via API. Retorna True=activa, False=descatalogada."""
    for intento in range(MAX_REINTENTOS):
        try:
            result = page.evaluate(_JS_FETCH_IDEALISTA, url)
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
            log.warning('Bloqueado por Cloudflare (intento %d/%d) — esperando...',
                        intento + 1, MAX_REINTENTOS)
            # En modo automático no podemos resolver captcha manualmente;
            # esperamos un tiempo y reintentamos, esperando que se desbloquee.
            try:
                page.goto('https://www.idealista.com/', timeout=25000,
                          wait_until='domcontentloaded')
            except Exception:
                pass
            time.sleep(random.uniform(15, 30))
            continue

        return True  # respuesta inesperada → conservador

    log.warning('Reintentos agotados para %s — marcando como activa.', url)
    return True


def verificar_fotocasa(url: str, page) -> bool:
    """Verifica URL de Fotocasa via redirect check. Retorna True=activa, False=descatalogada."""
    for intento in range(MAX_REINTENTOS):
        try:
            result = page.evaluate(_JS_FETCH_FOTOCASA, url)
        except Exception as e:
            log.debug('Error evaluando JS para %s: %s', url, e)
            return True

        if not result or result.startswith('FETCH_ERROR'):
            log.debug('Fetch error para %s: %s', url, result)
            return True

        if result.startswith('BLOCKED:'):
            log.warning('Bloqueado por Reese84 (intento %d/%d) — esperando...',
                        intento + 1, MAX_REINTENTOS)
            try:
                page.goto('https://www.fotocasa.es/es/', timeout=25000,
                          wait_until='domcontentloaded')
            except Exception:
                pass
            time.sleep(random.uniform(15, 30))
            continue

        # result = 'OK:{final_url}'
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

def limpiar_descatalogadas_de_json(datos: list, descatalogadas_por_archivo: dict) -> int:
    """Elimina las viviendas descatalogadas de los JSON originales.

    Args:
        datos: lista de datos cargados con cargar_todos_los_json()
        descatalogadas_por_archivo: {ruta_archivo: set(urls_descatalogadas)}

    Returns:
        Número total de viviendas eliminadas.
    """
    total_eliminadas = 0

    for datos_json in datos:
        archivo = datos_json['archivo']
        urls_desc = descatalogadas_por_archivo.get(archivo, set())
        if not urls_desc:
            continue

        try:
            with open(archivo, 'r', encoding='utf-8') as f:
                data = json.load(f)

            antes = len(data.get('viviendas', []))
            data['viviendas'] = [
                v for v in data.get('viviendas', [])
                if v.get('url', '') not in urls_desc
            ]
            despues = len(data['viviendas'])
            eliminadas = antes - despues

            if eliminadas > 0:
                data['total'] = despues
                with open(archivo, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                log.info('  Limpiado %s: %d viviendas eliminadas (%d restantes)',
                         os.path.basename(archivo), eliminadas, despues)
                total_eliminadas += eliminadas

        except Exception as e:
            log.error('  Error limpiando %s: %s', archivo, e)

    return total_eliminadas


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

            for j, vivienda in enumerate(viviendas, 1):
                url = vivienda.get('url', '')
                if not url:
                    continue

                titulo = vivienda.get('titulo', 'Sin título')[:60]
                activo = verificar_fn(url, cdp.page)
                stats['verificadas'] += 1

                if activo:
                    stats['activas'] += 1
                    if args.verbose:
                        log.debug('  [%d/%d] OK: %s', j, n_viviendas, titulo)
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

                # Delay entre peticiones
                time.sleep(random.uniform(*delay_range))

            if desc_archivo:
                urls_por_ubicacion.setdefault(ubicacion, []).extend(desc_archivo)
                descatalogadas_por_archivo[archivo] = set(desc_archivo)
                log.info('  >> %d descatalogadas en %s', len(desc_archivo), ubicacion)
            else:
                log.info('  >> Todas activas en %s', ubicacion)

            # Pausa entre archivos
            if i < total_archivos:
                pausa = random.uniform(*DELAY_ENTRE_ARCHIVOS)
                log.debug('Pausa de %.0fs antes del siguiente archivo...', pausa)
                time.sleep(pausa)

    except KeyboardInterrupt:
        log.warning('Verificacion interrumpida por el usuario (SIGINT)')
    except Exception as e:
        log.error('Error inesperado durante la verificacion: %s', e, exc_info=True)
        stats['errores'] += 1
    finally:
        cdp.__exit__(None, None, None)

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

    # ─── Limpiar viviendas descatalogadas de los JSONs fuente ─────────
    if args.clean and todas_descatalogadas:
        log.info('Limpiando viviendas descatalogadas de los JSON fuente...')
        eliminadas = limpiar_descatalogadas_de_json(datos, descatalogadas_por_archivo)
        log.info('Total eliminadas de JSONs fuente: %d', eliminadas)

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
  %(prog)s --send-api --clean        # Enviar a API y limpiar JSONs
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
        '--clean', action='store_true',
        help='Eliminar viviendas descatalogadas de los JSON fuente',
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
        help='Delay medio entre peticiones Idealista en segundos (default: 0.5)',
    )
    parser.add_argument(
        '--delay-fotocasa', type=float, default=None,
        help='Delay medio entre peticiones Fotocasa en segundos (default: 3.0)',
    )
    parser.add_argument(
        '-v', '--verbose', action='store_true',
        help='Modo verbose (mostrar cada vivienda activa)',
    )
    parser.add_argument(
        '--dry-run', action='store_true',
        help='Solo mostrar qué se haría, sin verificar',
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
