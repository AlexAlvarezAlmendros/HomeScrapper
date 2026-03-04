#!/usr/bin/env python3
"""
Script para interceptar y descubrir las APIs internas de Idealista y Fotocasa.

Usa Playwright para navegar a un anuncio y capturar todas las peticiones
XHR/fetch que hace el frontend, filtrando las que devuelven JSON.

REQUISITOS:
  1. Tener Chrome abierto con start_chrome_debug.sh (puerto 9222)
  2. Ejecutar: .venv/bin/python interceptar_apis.py

USO:
  python interceptar_apis.py idealista https://www.idealista.com/inmueble/12345678/
  python interceptar_apis.py fotocasa https://www.fotocasa.es/es/comprar/vivienda/.../12345678/d
  python interceptar_apis.py ambos     # Intercepta URLs de ejemplo para ambos portales
"""

import os
import sys
import json
import time
import signal
import subprocess
import socket
from datetime import datetime
from urllib.parse import urlparse

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeoutError
except ImportError:
    print("❌ Playwright no instalado. Ejecuta: pip install playwright && playwright install chromium")
    sys.exit(1)


# ─── Configuración ──────────────────────────────────────────────────────────

CHROME_DEBUG_PORT = 9222
CHROME_FALLBACK_PORT = 9225
CHROMIUM_PATH = os.path.expanduser(
    '~/.cache/ms-playwright/chromium-1091/chrome-linux/chrome'
)

# Carpeta donde guardar las APIs interceptadas
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "api_intercepts")


def chrome_disponible(port: int) -> bool:
    try:
        with socket.create_connection(('localhost', port), timeout=1):
            return True
    except OSError:
        return False


class APIInterceptor:
    """Intercepta peticiones HTTP que hace el frontend de un portal."""

    def __init__(self):
        self._pw = None
        self._browser = None
        self._page = None
        self._chrome_process = None
        self._owns_process = False
        self.captured_requests = []
        self.captured_responses = []

    def connect(self):
        """Conecta al Chrome real o lanza uno de respaldo."""
        self._pw = sync_playwright().start()

        if chrome_disponible(CHROME_DEBUG_PORT):
            print(f"✅ Conectando al Chrome real (puerto {CHROME_DEBUG_PORT})...")
            self._browser = self._pw.chromium.connect_over_cdp(
                f'http://localhost:{CHROME_DEBUG_PORT}'
            )
            self._owns_process = False
        else:
            print(f"⚠️  Chrome real no disponible. Ejecuta start_chrome_debug.sh primero.")
            print(f"   Lanzando Chromium de respaldo...")
            self._chrome_process = subprocess.Popen(
                [CHROMIUM_PATH,
                 f'--remote-debugging-port={CHROME_FALLBACK_PORT}',
                 '--no-sandbox', '--disable-blink-features=AutomationControlled',
                 '--lang=es-ES', '--window-size=1400,900'],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            time.sleep(2)
            self._browser = self._pw.chromium.connect_over_cdp(
                f'http://localhost:{CHROME_FALLBACK_PORT}'
            )
            self._owns_process = True

        # Obtener página
        contexts = self._browser.contexts
        ctx = contexts[0] if contexts else self._browser.new_context(
            viewport={'width': 1400, 'height': 900}, locale='es-ES')
        pages = ctx.pages
        self._page = pages[0] if pages else ctx.new_page()

    def close(self):
        try:
            if self._owns_process and self._browser:
                self._browser.close()
        except Exception:
            pass
        try:
            if self._pw:
                self._pw.stop()
        except Exception:
            pass
        if self._owns_process and self._chrome_process:
            try:
                os.killpg(os.getpgid(self._chrome_process.pid), signal.SIGTERM)
            except Exception:
                pass

    def interceptar_navegacion(self, url: str, esperar_segundos: int = 10) -> list:
        """
        Navega a una URL e intercepta todas las peticiones de red.
        
        Captura:
        - Peticiones XHR/Fetch (las que usa el frontend para cargar datos)
        - Respuestas JSON
        - Headers de las peticiones (para saber qué auth necesitan)
        """
        self.captured_requests = []
        self.captured_responses = []

        page = self._page

        def on_request(request):
            """Callback para cada petición que hace el navegador."""
            try:
                rtype = request.resource_type
                # Nos interesan: xhr, fetch, document (no images, fonts, etc.)
                if rtype in ('xhr', 'fetch', 'document', 'script'):
                    try:
                        post_data = request.post_data if request.method == 'POST' else None
                    except Exception:
                        post_data = '[binary/gzip data]'
                    entry = {
                        'url': request.url,
                        'method': request.method,
                        'resource_type': rtype,
                        'headers': dict(request.headers),
                        'post_data': post_data,
                    }
                    self.captured_requests.append(entry)
            except Exception:
                pass

        def on_response(response):
            """Callback para cada respuesta."""
            request = response.request
            rtype = request.resource_type
            if rtype in ('xhr', 'fetch', 'document'):
                content_type = response.headers.get('content-type', '')
                is_json = 'json' in content_type or 'javascript' in content_type

                entry = {
                    'url': response.url,
                    'status': response.status,
                    'content_type': content_type,
                    'is_json': is_json,
                    'resource_type': rtype,
                    'headers': dict(response.headers),
                    'body_preview': None,
                }

                # Intentar leer el body si es JSON
                if is_json:
                    try:
                        body = response.text()
                        if len(body) > 5000:
                            entry['body_preview'] = body[:5000] + '... [TRUNCATED]'
                        else:
                            entry['body_preview'] = body
                        # Intentar parsear como JSON
                        try:
                            entry['body_json'] = json.loads(body)
                        except json.JSONDecodeError:
                            entry['body_json'] = None
                    except Exception:
                        entry['body_preview'] = '[ERROR READING BODY]'

                self.captured_responses.append(entry)

        # Registrar listeners
        page.on('request', on_request)
        page.on('response', on_response)

        print(f"\n🌐 Navegando a: {url}")
        print(f"   Interceptando peticiones durante {esperar_segundos}s...\n")

        try:
            page.goto(url, wait_until='domcontentloaded', timeout=30000)
        except PWTimeoutError:
            print("   ⚠️ Timeout al cargar, pero seguimos capturando...")

        # Esperar para capturar peticiones lazy/deferred
        print(f"   Esperando {esperar_segundos}s para capturar peticiones diferidas...")
        time.sleep(esperar_segundos)

        # Scroll down para activar lazy loading
        print("   Haciendo scroll para activar lazy loading...")
        page.evaluate("window.scrollTo(0, document.body.scrollHeight / 2)")
        time.sleep(2)
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        time.sleep(3)

        # Desregistrar listeners
        page.remove_listener('request', on_request)
        page.remove_listener('response', on_response)

        return self.captured_responses

    def analizar_resultados(self, portal: str) -> dict:
        """Analiza las respuestas capturadas y clasifica las APIs encontradas."""
        
        apis_json = []
        apis_html = []
        otras = []

        for resp in self.captured_responses:
            url = resp['url']
            parsed = urlparse(url)
            
            # Ignorar tracking/analytics/ads
            dominios_ignorar = [
                'google', 'facebook', 'doubleclick', 'analytics',
                'adsystem', 'criteo', 'hotjar', 'segment', 'sentry',
                'newrelic', 'datadome', 'akamai', 'cloudfront',
                'googlesyndication', 'googletagmanager', 'googleapis.com/maps',
            ]
            if any(d in parsed.hostname for d in dominios_ignorar if parsed.hostname):
                continue

            entry = {
                'url': url,
                'status': resp['status'],
                'content_type': resp['content_type'],
                'resource_type': resp['resource_type'],
                'is_json': resp.get('is_json', False),
            }

            if resp.get('is_json'):
                entry['body_preview'] = resp.get('body_preview', '')[:2000]
                apis_json.append(entry)
            elif 'html' in resp.get('content_type', ''):
                apis_html.append(entry)
            else:
                otras.append(entry)

        result = {
            'portal': portal,
            'timestamp': datetime.now().isoformat(),
            'total_captured': len(self.captured_responses),
            'apis_json': apis_json,
            'apis_html': apis_html,
            'total_json': len(apis_json),
            'total_html': len(apis_html),
        }

        return result

    def extraer_next_data(self, url: str) -> dict | None:
        """Extrae __NEXT_DATA__ del HTML ya cargado en la página."""
        try:
            next_data = self._page.evaluate("""
                () => {
                    const el = document.getElementById('__NEXT_DATA__');
                    if (el) return el.textContent;
                    // Buscar también en window.__NEXT_DATA__
                    if (window.__NEXT_DATA__) return JSON.stringify(window.__NEXT_DATA__);
                    return null;
                }
            """)
            if next_data:
                return json.loads(next_data)
        except Exception as e:
            print(f"   ⚠️  Error extrayendo __NEXT_DATA__: {e}")
        return None

    def extraer_datos_pagina(self) -> dict:
        """Extrae datos embebidos en la página actual (state, config, etc.)."""
        datos = {}
        try:
            # __INITIAL_STATE__ (usado por React)
            result = self._page.evaluate("""
                () => {
                    if (window.__INITIAL_STATE__) return JSON.stringify(window.__INITIAL_STATE__);
                    return null;
                }
            """)
            if result:
                datos['__INITIAL_STATE__'] = json.loads(result)
        except Exception:
            pass

        try:
            # JSON-LD (schema.org) - datos estructurados del anuncio
            result = self._page.evaluate("""
                () => {
                    const scripts = document.querySelectorAll('script[type="application/ld+json"]');
                    if (scripts.length === 0) return null;
                    return Array.from(scripts).map(s => s.textContent);
                }
            """)
            if result:
                datos['json_ld'] = [json.loads(r) for r in result if r]
        except Exception:
            pass

        try:
            # Título y meta tags
            result = self._page.evaluate("""
                () => {
                    const title = document.title;
                    const description = document.querySelector('meta[name="description"]')?.content;
                    const canonical = document.querySelector('link[rel="canonical"]')?.href;
                    return { title, description, canonical };
                }
            """)
            datos['meta'] = result
        except Exception:
            pass

        return datos


def imprimir_apis_encontradas(resultado: dict):
    """Imprime un resumen de las APIs JSON encontradas."""
    portal = resultado['portal']
    apis = resultado['apis_json']

    print(f"\n{'='*80}")
    print(f"  📡 APIs JSON detectadas en {portal.upper()}")
    print(f"  Total peticiones capturadas: {resultado['total_captured']}")
    print(f"  Endpoints JSON: {resultado['total_json']}")
    print(f"{'='*80}\n")

    if not apis:
        print("  ❌ No se detectaron endpoints JSON.\n")
        print("  Esto puede significar:")
        print("  - El portal inyecta los datos en __NEXT_DATA__ (embebido en HTML)")
        print("  - El anti-bot bloqueó las peticiones")
        print("  - Se necesita interacción para disparar las llamadas API\n")
        return

    for i, api in enumerate(apis, 1):
        print(f"  [{i}] {api['resource_type'].upper()} {api['status']}")
        print(f"      URL: {api['url'][:120]}")
        print(f"      Content-Type: {api['content_type']}")
        if api.get('body_preview'):
            preview = api['body_preview'][:300].replace('\n', ' ')
            print(f"      Preview: {preview}...")
        print()


def guardar_resultados(resultado: dict, url_original: str):
    """Guarda los resultados de la interceptación en un archivo JSON."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    portal = resultado['portal']
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"intercept_{portal}_{ts}.json"
    filepath = os.path.join(OUTPUT_DIR, filename)

    output = {
        **resultado,
        'url_original': url_original,
    }

    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"💾 Resultados guardados en: {filepath}")
    return filepath


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    portal = sys.argv[1].lower()

    # URLs de ejemplo por defecto
    urls_ejemplo = {
        'idealista': 'https://www.idealista.com/inmueble/110752095/',
        'fotocasa': 'https://www.fotocasa.es/es/comprar/vivienda/igualada/calefaccion-terraza-ascensor-patio-amueblado/188765462/d',
    }

    if portal == 'ambos':
        # Interceptar ambos portales
        portales = ['idealista', 'fotocasa']
        urls = {p: urls_ejemplo[p] for p in portales}
    elif portal in ('idealista', 'fotocasa'):
        url = sys.argv[2] if len(sys.argv) > 2 else urls_ejemplo[portal]
        portales = [portal]
        urls = {portal: url}
    else:
        print(f"❌ Portal '{portal}' no reconocido. Usa: idealista, fotocasa, ambos")
        sys.exit(1)

    interceptor = APIInterceptor()

    try:
        interceptor.connect()

        for p in portales:
            url = urls[p]
            print(f"\n{'#'*80}")
            print(f"  INTERCEPTANDO: {p.upper()}")
            print(f"  URL: {url}")
            print(f"{'#'*80}")

            # Interceptar navegación
            interceptor.interceptar_navegacion(url, esperar_segundos=8)

            # Analizar
            resultado = interceptor.analizar_resultados(p)

            # Imprimir resumen
            imprimir_apis_encontradas(resultado)

            # Extraer __NEXT_DATA__ si existe
            next_data = interceptor.extraer_next_data(url)
            if next_data:
                print(f"\n  📦 __NEXT_DATA__ encontrado!")
                if 'props' in next_data:
                    props = next_data['props']
                    if 'pageProps' in props:
                        page_props = props['pageProps']
                        print(f"     Keys en pageProps: {list(page_props.keys())[:20]}")
                        for key in page_props:
                            value = page_props[key]
                            if isinstance(value, dict):
                                print(f"     📋 pageProps.{key}: {list(value.keys())[:15]}")
                            elif isinstance(value, list) and len(value) > 0:
                                print(f"     📋 pageProps.{key}: lista con {len(value)} elementos")

                resultado['__NEXT_DATA__'] = {
                    'found': True,
                    'keys': list(next_data.keys()),
                    'buildId': next_data.get('buildId'),
                }
                if 'props' in next_data and 'pageProps' in next_data['props']:
                    resultado['__NEXT_DATA__']['pageProps_keys'] = list(
                        next_data['props']['pageProps'].keys()
                    )
            else:
                print(f"\n  ℹ️  No se encontró __NEXT_DATA__ embebido")
                resultado['__NEXT_DATA__'] = {'found': False}

            # Extraer datos embebidos (JSON-LD, __INITIAL_STATE__, meta)
            datos_pagina = interceptor.extraer_datos_pagina()
            if datos_pagina:
                if datos_pagina.get('json_ld'):
                    print(f"\n  📋 JSON-LD (schema.org) encontrado: {len(datos_pagina['json_ld'])} bloques")
                    for i, ld in enumerate(datos_pagina['json_ld']):
                        if isinstance(ld, dict):
                            print(f"     [{i+1}] @type: {ld.get('@type', '?')} — keys: {list(ld.keys())[:10]}")
                if datos_pagina.get('meta'):
                    meta = datos_pagina['meta']
                    print(f"\n  🏷️  Meta: title='{(meta.get('title') or '')[:60]}'")
                if datos_pagina.get('__INITIAL_STATE__'):
                    state = datos_pagina['__INITIAL_STATE__']
                    print(f"\n  📦 __INITIAL_STATE__ encontrado! Keys: {list(state.keys())[:15]}")
                resultado['datos_pagina'] = {
                    k: v if k != '__INITIAL_STATE__' else {'keys': list(v.keys())[:20]}
                    for k, v in datos_pagina.items()
                }

            # Guardar
            filepath = guardar_resultados(resultado, url)

            if p != portales[-1]:
                print(f"\n⏳ Pausa de 5s antes del siguiente portal...")
                time.sleep(5)

    except KeyboardInterrupt:
        print("\n\n⚠️  Interrumpido por el usuario")
    finally:
        interceptor.close()

    print(f"\n✅ Interceptación completada. Revisa los archivos en {OUTPUT_DIR}/")


if __name__ == "__main__":
    main()
