#!/usr/bin/env python3
"""
Scraper de inmuebles de una agencia/profesional de Idealista.

Extrae todos los inmuebles publicados por una agencia concreta,
visitando la página del profesional y cada ficha de detalle.

Prioriza la extracción de datos desde APIs internas y datos embebidos
(utag_data, JSON-LD, __NEXT_DATA__) antes de recurrir a scraping HTML.

REQUISITOS:
  1. Chrome abierto en modo debug (puerto 9222):
       ./start_chrome_debug.sh
  2. Playwright instalado:
       pip install playwright && playwright install chromium

USO:
  python scraper_agencia_idealista.py
  python scraper_agencia_idealista.py --url https://www.idealista.com/pro/finquestrimar/
  python scraper_agencia_idealista.py --debug
  python scraper_agencia_idealista.py --output viviendas_agencia.json
"""

import os
import re
import sys
import json
import time
import random
import signal
import socket
import subprocess
from datetime import datetime
from typing import Optional
from urllib.parse import urljoin

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeoutError
except ImportError:
    print("❌ Playwright no instalado. Ejecuta: pip install playwright && playwright install chromium")
    sys.exit(1)

try:
    from bs4 import BeautifulSoup
except ImportError:
    print("❌ BeautifulSoup no instalado. Ejecuta: pip install beautifulsoup4")
    sys.exit(1)


# ─── Configuración ──────────────────────────────────────────────────────────

CHROME_DEBUG_PORT = 9222
CHROME_FALLBACK_PORT = 9225
CHROMIUM_PATH = os.path.expanduser(
    '~/.cache/ms-playwright/chromium-1091/chrome-linux/chrome'
)

# URL por defecto de la agencia
AGENCY_URL = "https://www.idealista.com/pro/finquestrimar/"

# Delays anti-detección (segundos)
DELAY_MIN_PAGINA = 3
DELAY_MAX_PAGINA = 6
DELAY_MIN_DETALLE = 2
DELAY_MAX_DETALLE = 4
PAUSA_LARGA_CADA = 12          # Cada N peticiones, pausa larga
PAUSA_LARGA_MIN = 12
PAUSA_LARGA_MAX = 25


# ─── Utilidades ─────────────────────────────────────────────────────────────

def chrome_disponible(port: int) -> bool:
    try:
        with socket.create_connection(('localhost', port), timeout=1):
            return True
    except OSError:
        return False


def delay(tipo='pagina'):
    """Espera aleatoria para parecer humano."""
    if tipo == 'pagina':
        t = random.uniform(DELAY_MIN_PAGINA, DELAY_MAX_PAGINA)
    else:
        t = random.uniform(DELAY_MIN_DETALLE, DELAY_MAX_DETALLE)
    time.sleep(t)


def limpiar_texto(texto: str) -> str:
    """Limpia espacios duplicados y saltos de línea."""
    if not texto:
        return ""
    return re.sub(r'\s+', ' ', texto).strip()


# ─── Clase principal ────────────────────────────────────────────────────────

class AgencyScraperIdealista:
    """Scraper que extrae todos los inmuebles de una agencia en Idealista."""

    def __init__(self, agency_url: str = AGENCY_URL, debug: bool = False):
        self.agency_url = agency_url.rstrip('/')
        self.debug = debug
        self._pw = None
        self._browser = None
        self._page = None
        self._chrome_process = None
        self._owns_process = False
        self.peticiones = 0
        self.inmuebles = []

    # ── Conexión ────────────────────────────────────────────────────────

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
            print(f"⚠️  Chrome real no disponible en puerto {CHROME_DEBUG_PORT}.")
            if os.path.exists(CHROMIUM_PATH):
                print(f"   Lanzando Chromium de respaldo en puerto {CHROME_FALLBACK_PORT}...")
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
            else:
                print("❌ No se encontró Chrome ni Chromium de Playwright.")
                print("   Ejecuta: ./start_chrome_debug.sh")
                sys.exit(1)

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

    # ── Navegación con anti-detección ───────────────────────────────────

    def _navegar(self, url: str, wait_until='domcontentloaded', timeout=30000):
        """Navega a una URL con control de rate-limit."""
        self.peticiones += 1

        # Pausa larga periódica
        if self.peticiones > 1 and self.peticiones % PAUSA_LARGA_CADA == 0:
            pausa = random.uniform(PAUSA_LARGA_MIN, PAUSA_LARGA_MAX)
            print(f"   ☕ Pausa anti-detección: {pausa:.0f}s (petición #{self.peticiones})")
            time.sleep(pausa)

        try:
            self._page.goto(url, wait_until=wait_until, timeout=timeout)
        except PWTimeoutError:
            print(f"   ⚠️  Timeout al cargar {url[:80]}... continuando")

        # Scroll suave para activar carga perezosa
        self._scroll_suave()

    def _scroll_suave(self):
        """Hace scroll suave como un usuario humano."""
        try:
            for i in range(4):
                self._page.evaluate(f"window.scrollTo(0, {350 * (i + 1)})")
                time.sleep(random.uniform(0.3, 0.7))
            time.sleep(random.uniform(0.5, 1.0))
        except Exception:
            pass

    def _detectar_captcha(self) -> bool:
        """Detecta captcha y pide intervención manual."""
        try:
            url = self._page.url.lower()
            html = self._page.content().lower()
        except Exception:
            return False

        signals = [
            'geo.captcha-delivery.com', 'datadome.co', '/challenge',
            'pardon our interruption', 'security check',
            'verificación de seguridad',
        ]
        if any(s in url or s in html for s in signals):
            print("\n" + "=" * 60)
            print("🤖 CAPTCHA DETECTADO")
            print("=" * 60)
            print("   Resuelve el captcha en el navegador Chrome.")
            input("   Pulsa Enter cuando esté resuelto... ")
            print("   ✅ Continuando.\n")
            return True
        return False

    # ── Extracción del listado de la agencia ────────────────────────────

    def obtener_urls_inmuebles(self) -> list[str]:
        """Navega por todas las páginas del listado de la agencia y recopila URLs."""
        urls = []
        pagina = 1

        while True:
            if pagina == 1:
                url_pagina = f"{self.agency_url}/"
            else:
                url_pagina = f"{self.agency_url}/pagina-{pagina}.htm"

            print(f"\n📄 Listado página {pagina}: {url_pagina}")
            self._navegar(url_pagina)
            delay('pagina')
            self._detectar_captcha()

            # Intentar extraer URLs desde utag_data (API interna embebida)
            urls_pagina = self._extraer_urls_utag_data()

            if not urls_pagina:
                # Fallback: parsear HTML
                urls_pagina = self._extraer_urls_html()

            if not urls_pagina:
                if pagina == 1:
                    print("   ⚠️  No se encontraron inmuebles en la primera página.")
                    print("   Verifica la URL y que Chrome muestra la página correctamente.")
                break

            nuevas = [u for u in urls_pagina if u not in urls]
            if not nuevas:
                print(f"   ✅ Fin del listado (URLs repetidas en página {pagina})")
                break

            urls.extend(nuevas)
            print(f"   ✅ {len(nuevas)} inmuebles encontrados (total: {len(urls)})")

            # Comprobar si existe enlace a página siguiente
            if not self._hay_pagina_siguiente():
                print(f"   ✅ Fin del listado (no hay página siguiente)")
                break

            pagina += 1

        print(f"\n📊 Total URLs de inmuebles recopiladas: {len(urls)}")
        return urls

    def _extraer_urls_utag_data(self) -> list[str]:
        """Extrae URLs de inmuebles desde utag_data (variable JS embebida)."""
        try:
            data = self._page.evaluate("""
                () => {
                    if (typeof utag_data !== 'undefined' && utag_data.list && utag_data.list.ads) {
                        return utag_data.list.ads.map(ad => ({
                            id: ad.adId,
                            url: '/inmueble/' + ad.adId + '/'
                        }));
                    }
                    return null;
                }
            """)
            if data:
                urls = [f"https://www.idealista.com{item['url']}" for item in data]
                if self.debug:
                    print(f"   [DEBUG] utag_data: {len(urls)} inmuebles via API interna")
                return urls
        except Exception as e:
            if self.debug:
                print(f"   [DEBUG] utag_data no disponible: {e}")
        return []

    def _extraer_urls_html(self) -> list[str]:
        """Extrae URLs de inmuebles desde el HTML parseado."""
        try:
            html = self._page.content()
            soup = BeautifulSoup(html, 'html.parser')
            urls = []

            # Selector principal: article.item > a.item-link
            for article in soup.find_all('article', class_='item'):
                link = article.find('a', class_='item-link')
                if link and link.get('href'):
                    href = link['href']
                    if not href.startswith('http'):
                        href = f"https://www.idealista.com{href}"
                    urls.append(href)

            # Selector alternativo: cualquier enlace a /inmueble/
            if not urls:
                for a in soup.find_all('a', href=re.compile(r'/inmueble/\d+')):
                    href = a['href']
                    if not href.startswith('http'):
                        href = f"https://www.idealista.com{href}"
                    if href not in urls:
                        urls.append(href)

            if self.debug:
                print(f"   [DEBUG] HTML parser: {len(urls)} inmuebles")
            return urls
        except Exception as e:
            if self.debug:
                print(f"   [DEBUG] Error parseando HTML: {e}")
        return []

    def _hay_pagina_siguiente(self) -> bool:
        """Comprueba si existe un enlace de paginación a la página siguiente."""
        try:
            siguiente = self._page.query_selector('a.icon-arrow-right-after, a.next, li.next a')
            return siguiente is not None
        except Exception:
            return False

    # ── Extracción de detalle de un inmueble ────────────────────────────

    def extraer_detalle(self, url: str) -> Optional[dict]:
        """Extrae todos los datos de un inmueble desde su página de detalle.

        Estrategia por capas:
          1. JSON-LD (schema.org) – datos estructurados muy fiables
          2. utag_data / variables JS embebidas
          3. HTML parsing con BeautifulSoup
        """
        try:
            self._navegar(url)
            delay('detalle')
            self._detectar_captcha()

            html = self._page.content()
            soup = BeautifulSoup(html, 'html.parser')

            inmueble = {
                'url': url,
                'titulo': None,
                'precio': None,
                'descripcion': None,
                'habitaciones': None,
                'banos': None,
                'garajes': None,
                'metros_cuadrados': None,
                'ubicacion': None,
                'tipo_inmueble': None,
                'estado': None,           # obra nueva / buen estado / a reformar
                'caracteristicas': [],
                'imagenes': [],
                'fecha_scraping': datetime.now().isoformat(),
            }

            # ── Capa 1: JSON-LD ──
            self._extraer_json_ld(soup, inmueble)

            # ── Capa 2: utag_data / estado JS ──
            self._extraer_datos_js(inmueble)

            # ── Capa 3: HTML parsing (complementa / sobreescribe si faltan datos) ──
            self._extraer_datos_html(soup, inmueble)

            # ── Imágenes (siempre desde HTML/JS) ──
            self._extraer_imagenes(soup, inmueble)

            # Limpieza final
            for key in ('titulo', 'descripcion', 'ubicacion', 'tipo_inmueble', 'estado'):
                if inmueble[key]:
                    inmueble[key] = limpiar_texto(str(inmueble[key]))

            return inmueble

        except Exception as e:
            print(f"   ❌ Error extrayendo {url[:60]}: {e}")
            if self.debug:
                import traceback
                traceback.print_exc()
            return None

    # ── Capa 1: JSON-LD ─────────────────────────────────────────────────

    def _extraer_json_ld(self, soup: BeautifulSoup, inmueble: dict):
        """Extrae datos de scripts JSON-LD (schema.org)."""
        scripts = soup.find_all('script', type='application/ld+json')
        for script in scripts:
            try:
                data = json.loads(script.string)
                if isinstance(data, list):
                    for item in data:
                        self._procesar_jsonld_item(item, inmueble)
                else:
                    self._procesar_jsonld_item(data, inmueble)
            except (json.JSONDecodeError, TypeError):
                continue

    def _procesar_jsonld_item(self, data: dict, inmueble: dict):
        """Procesa un bloque JSON-LD individual."""
        if not isinstance(data, dict):
            return

        tipo = data.get('@type', '')

        # Tipo Residence / Apartment / House / RealEstateListing / Product
        if tipo in ('Residence', 'Apartment', 'House', 'SingleFamilyResidence',
                     'RealEstateListing', 'Product') or 'floorSize' in data:
            if data.get('name') and not inmueble['titulo']:
                inmueble['titulo'] = data['name']

            if data.get('description') and not inmueble['descripcion']:
                inmueble['descripcion'] = data['description']

            # Precio
            offers = data.get('offers') or data.get('offer')
            if offers:
                if isinstance(offers, list):
                    offers = offers[0]
                if isinstance(offers, dict):
                    price = offers.get('price') or offers.get('priceSpecification', {}).get('price')
                    if price and not inmueble['precio']:
                        inmueble['precio'] = str(price)

            # Superficie
            floor_size = data.get('floorSize')
            if floor_size and not inmueble['metros_cuadrados']:
                if isinstance(floor_size, dict):
                    inmueble['metros_cuadrados'] = floor_size.get('value')
                else:
                    inmueble['metros_cuadrados'] = str(floor_size)

            # Habitaciones
            rooms = data.get('numberOfRooms')
            if rooms and not inmueble['habitaciones']:
                inmueble['habitaciones'] = str(rooms)

            # Dirección / ubicación
            address = data.get('address')
            if address and not inmueble['ubicacion']:
                if isinstance(address, dict):
                    parts = [address.get('streetAddress', ''),
                             address.get('addressLocality', ''),
                             address.get('addressRegion', '')]
                    inmueble['ubicacion'] = ', '.join(p for p in parts if p)
                else:
                    inmueble['ubicacion'] = str(address)

            # Imágenes
            images = data.get('image') or data.get('photo')
            if images:
                if isinstance(images, str):
                    images = [images]
                elif isinstance(images, list):
                    images = [
                        (img.get('contentUrl') or img.get('url') or img)
                        if isinstance(img, dict) else str(img)
                        for img in images
                    ]
                for img in images:
                    if img and img not in inmueble['imagenes']:
                        inmueble['imagenes'].append(str(img))

    # ── Capa 2: datos JS embebidos ──────────────────────────────────────

    def _extraer_datos_js(self, inmueble: dict):
        """Extrae datos de variables JavaScript embebidas en la página."""
        try:
            # utag_data tiene datos como precio, tipología, ubicación, etc.
            utag = self._page.evaluate("""
                () => {
                    if (typeof utag_data !== 'undefined') {
                        return JSON.parse(JSON.stringify(utag_data));
                    }
                    return null;
                }
            """)
            if utag:
                if self.debug:
                    print(f"   [DEBUG] utag_data keys: {list(utag.keys())[:15]}")

                if not inmueble['precio']:
                    price = utag.get('adPrice') or utag.get('price')
                    if price:
                        inmueble['precio'] = str(price)

                # Tipo de inmueble (tipología)
                typology = utag.get('typology') or utag.get('adTypology')
                if typology and not inmueble['tipo_inmueble']:
                    tipo_map = {
                        '1': 'Piso', '2': 'Casa', '3': 'Ático',
                        '4': 'Dúplex', '5': 'Estudio', '6': 'Chalet',
                        '7': 'Loft', '8': 'Finca rústica', '9': 'Local',
                        '10': 'Oficina', '11': 'Garaje', '12': 'Trastero',
                        '13': 'Terreno', '14': 'Edificio',
                    }
                    inmueble['tipo_inmueble'] = tipo_map.get(str(typology), str(typology))

        except Exception as e:
            if self.debug:
                print(f"   [DEBUG] Error extrayendo utag_data: {e}")

        # __NEXT_DATA__ (si Idealista usa Next.js en algún momento)
        try:
            next_data = self._page.evaluate("""
                () => {
                    const el = document.getElementById('__NEXT_DATA__');
                    if (el) return JSON.parse(el.textContent);
                    if (window.__NEXT_DATA__) return window.__NEXT_DATA__;
                    return null;
                }
            """)
            if next_data and next_data.get('props', {}).get('pageProps'):
                props = next_data['props']['pageProps']
                if self.debug:
                    print(f"   [DEBUG] __NEXT_DATA__ pageProps keys: {list(props.keys())[:15]}")
                # Extraer lo que haya disponible
                ad = props.get('ad') or props.get('property') or {}
                if isinstance(ad, dict):
                    if ad.get('rooms') and not inmueble['habitaciones']:
                        inmueble['habitaciones'] = str(ad['rooms'])
                    if ad.get('bathrooms') and not inmueble['banos']:
                        inmueble['banos'] = str(ad['bathrooms'])
                    if ad.get('size') and not inmueble['metros_cuadrados']:
                        inmueble['metros_cuadrados'] = str(ad['size'])
        except Exception:
            pass

    # ── Capa 3: HTML parsing ────────────────────────────────────────────

    def _extraer_datos_html(self, soup: BeautifulSoup, inmueble: dict):
        """Extrae datos del HTML de la página de detalle."""

        # ── Título ──
        if not inmueble['titulo']:
            for selector in ['h1.main-info__title-main', 'span.main-info__title-main',
                             'h1[class*="title"]']:
                elem = soup.select_one(selector)
                if elem:
                    inmueble['titulo'] = elem.get_text(strip=True)
                    break

        # ── Precio ──
        if not inmueble['precio']:
            elem = soup.select_one('span.info-data-price')
            if elem:
                inmueble['precio'] = elem.get_text(strip=True)

        # ── Ubicación ──
        if not inmueble['ubicacion']:
            elem = soup.select_one('span.main-info__title-minor')
            if elem:
                inmueble['ubicacion'] = elem.get_text(strip=True)

        # ── Descripción ──
        if not inmueble['descripcion']:
            elem = soup.select_one('div.comment div.adCommentsLanguage p, div.comment p, div.comment')
            if elem:
                inmueble['descripcion'] = elem.get_text(strip=True)

        # ── Detalles numéricos (habitaciones, baños, metros, etc.) ──
        self._extraer_detalles_info_features(soup, inmueble)

        # ── Tipo de inmueble (desde el título si no se obtuvo antes) ──
        if not inmueble['tipo_inmueble'] and inmueble['titulo']:
            titulo_lower = inmueble['titulo'].lower()
            tipos = [
                ('piso', 'Piso'), ('ático', 'Ático'), ('atico', 'Ático'),
                ('casa', 'Casa'), ('chalet', 'Chalet'), ('dúplex', 'Dúplex'),
                ('duplex', 'Dúplex'), ('estudio', 'Estudio'), ('loft', 'Loft'),
                ('local', 'Local comercial'), ('oficina', 'Oficina'),
                ('garaje', 'Garaje'), ('trastero', 'Trastero'),
                ('terreno', 'Terreno'), ('finca', 'Finca rústica'),
                ('apartamento', 'Apartamento'), ('adosado', 'Adosado'),
                ('pareado', 'Pareado'),
            ]
            for keyword, tipo in tipos:
                if keyword in titulo_lower:
                    inmueble['tipo_inmueble'] = tipo
                    break

        # ── Estado del inmueble ──
        self._extraer_estado(soup, inmueble)

        # ── Características ──
        self._extraer_caracteristicas(soup, inmueble)

    def _extraer_detalles_info_features(self, soup: BeautifulSoup, inmueble: dict):
        """Extrae hab., baños, metros, garaje de la sección info-features."""

        # Método principal: info-features con spans
        container = soup.select_one('div.info-features')
        if container:
            spans = container.find_all('span')
            for span in spans:
                texto = span.get_text(strip=True).lower()

                if 'hab' in texto:
                    nums = re.findall(r'\d+', texto)
                    if nums and not inmueble['habitaciones']:
                        inmueble['habitaciones'] = nums[0]

                elif 'baño' in texto or 'bano' in texto:
                    nums = re.findall(r'\d+', texto)
                    if nums and not inmueble['banos']:
                        inmueble['banos'] = nums[0]

                elif 'm²' in texto or 'm2' in texto or 'superficie' in texto:
                    nums = re.findall(r'[\d.,]+', texto)
                    if nums and not inmueble['metros_cuadrados']:
                        inmueble['metros_cuadrados'] = nums[0].replace('.', '').replace(',', '.')

        # Método alternativo: buscar en details-property / details-property_features
        for section in soup.select('div.details-property, div.details-property_features, ul.details-property_features'):
            items = section.find_all('li')
            for li in items:
                texto = li.get_text(strip=True).lower()

                if 'habitaci' in texto or 'dormitorio' in texto:
                    nums = re.findall(r'\d+', texto)
                    if nums and not inmueble['habitaciones']:
                        inmueble['habitaciones'] = nums[0]

                if 'baño' in texto or 'bano' in texto:
                    nums = re.findall(r'\d+', texto)
                    if nums and not inmueble['banos']:
                        inmueble['banos'] = nums[0]

                if 'garaje' in texto or 'parking' in texto or 'plaza de garaje' in texto:
                    nums = re.findall(r'\d+', texto)
                    if nums and not inmueble['garajes']:
                        inmueble['garajes'] = nums[0]
                    elif not inmueble['garajes']:
                        inmueble['garajes'] = '1'  # Mencionado pero sin número

                if ('m²' in texto or 'm2' in texto) and 'construid' in texto:
                    nums = re.findall(r'[\d.,]+', texto)
                    if nums and not inmueble['metros_cuadrados']:
                        inmueble['metros_cuadrados'] = nums[0].replace('.', '').replace(',', '.')

        # Buscar garaje también en la sección de características generales
        if not inmueble['garajes']:
            all_text = soup.get_text().lower()
            if 'plaza de garaje incluida' in all_text or 'garaje incluido' in all_text:
                inmueble['garajes'] = '1'
            elif 'parking incluido' in all_text:
                inmueble['garajes'] = '1'

    def _extraer_estado(self, soup: BeautifulSoup, inmueble: dict):
        """Extrae el estado del inmueble: obra nueva, buen estado, a reformar."""
        if inmueble['estado']:
            return

        # Buscar en details-property
        for section in soup.select('div.details-property, ul.details-property_features'):
            items = section.find_all('li')
            for li in items:
                texto = li.get_text(strip=True).lower()
                if 'obra nueva' in texto or 'a estrenar' in texto:
                    inmueble['estado'] = 'Obra nueva'
                    return
                elif 'buen estado' in texto:
                    inmueble['estado'] = 'Buen estado'
                    return
                elif 'a reformar' in texto or 'para reformar' in texto or 'necesita reforma' in texto:
                    inmueble['estado'] = 'A reformar'
                    return
                elif 'reformado' in texto or 'recién reformado' in texto:
                    inmueble['estado'] = 'Reformado'
                    return
                elif 'segunda mano' in texto:
                    inmueble['estado'] = 'Segunda mano'
                    return

        # Fallback: buscar en toda la página con patrones conocidos
        all_text = soup.get_text().lower()
        estados = [
            ('obra nueva', 'Obra nueva'),
            ('a estrenar', 'Obra nueva'),
            ('buen estado', 'Buen estado'),
            ('a reformar', 'A reformar'),
            ('para reformar', 'A reformar'),
            ('necesita reforma', 'A reformar'),
            ('reformado', 'Reformado'),
            ('segunda mano/buen estado', 'Buen estado'),
            ('segunda mano / buen estado', 'Buen estado'),
        ]
        for pattern, estado in estados:
            if pattern in all_text:
                inmueble['estado'] = estado
                return

    def _extraer_caracteristicas(self, soup: BeautifulSoup, inmueble: dict):
        """Extrae la lista de características del inmueble."""
        caracteristicas = set()

        # Sección details-property_features
        for section in soup.select('div.details-property, div.details-property_features, '
                                    'ul.details-property_features'):
            items = section.find_all('li')
            for li in items:
                texto = li.get_text(strip=True)
                if texto and len(texto) > 2:
                    caracteristicas.add(texto)

        # Sección info-features (resumen superior)
        for span in soup.select('div.info-features span'):
            texto = span.get_text(strip=True)
            if texto and len(texto) > 2:
                caracteristicas.add(texto)

        # Sección de "equipamiento" o "extras"
        for section in soup.select('div.details-property_features ul, div.extrasAndAmenities ul'):
            for li in section.find_all('li'):
                texto = li.get_text(strip=True)
                if texto and len(texto) > 2:
                    caracteristicas.add(texto)

        inmueble['caracteristicas'] = sorted(caracteristicas)

    # ── Imágenes ────────────────────────────────────────────────────────

    def _extraer_imagenes(self, soup: BeautifulSoup, inmueble: dict):
        """Extrae URLs de imágenes del inmueble."""
        imagenes = set(inmueble.get('imagenes', []))

        # Método 1 (JS): Capturar URLs de imágenes desde el carrusel / multimedia
        try:
            imgs_js = self._page.evaluate("""
                () => {
                    const urls = new Set();

                    // Imágenes del carrusel principal
                    document.querySelectorAll(
                        'img[src*="img3.idealista.com"], img[src*="img4.idealista.com"], ' +
                        'img[data-src*="img3.idealista.com"], img[data-src*="img4.idealista.com"], ' +
                        'img[src*="idealista.com/thumbs"], img[data-src*="idealista.com/thumbs"], ' +
                        'picture source[srcset*="idealista.com"]'
                    ).forEach(el => {
                        const src = el.getAttribute('src') || el.getAttribute('data-src') ||
                                    el.getAttribute('srcset');
                        if (src) {
                            // Si es srcset, coger la URL principal
                            const url = src.split(',')[0].trim().split(' ')[0];
                            if (url && url.startsWith('http')) urls.add(url);
                        }
                    });

                    // div con background-image
                    document.querySelectorAll('[style*="idealista.com"]').forEach(el => {
                        const match = el.style.backgroundImage?.match(/url\\("?([^"\\)]+)"?\\)/);
                        if (match && match[1]) urls.add(match[1]);
                    });

                    // Intentar _jsGalleryImages (variable interna de Idealista)
                    if (window._jsGalleryImages) {
                        window._jsGalleryImages.forEach(img => {
                            if (img.src) urls.add(img.src);
                            if (img.originalSrc) urls.add(img.originalSrc);
                        });
                    }

                    return Array.from(urls);
                }
            """)
            if imgs_js:
                for url in imgs_js:
                    # Intentar obtener la versión de mayor resolución
                    url_hd = self._url_imagen_alta_res(url)
                    imagenes.add(url_hd)
        except Exception as e:
            if self.debug:
                print(f"   [DEBUG] Error extrayendo imágenes JS: {e}")

        # Método 2 (HTML): Parsear con BeautifulSoup
        for img in soup.find_all('img'):
            src = img.get('src') or img.get('data-src') or ''
            if 'idealista.com' in src and '/thumbs/' in src:
                imagenes.add(self._url_imagen_alta_res(src))

        # Método 3: meta og:image
        og_img = soup.find('meta', property='og:image')
        if og_img and og_img.get('content'):
            imagenes.add(og_img['content'])

        inmueble['imagenes'] = sorted(imagenes)

    @staticmethod
    def _url_imagen_alta_res(url: str) -> str:
        """Intenta convertir un thumbnail a la imagen de mayor resolución."""
        # Idealista usa patrones como /thumbs/5/X/Y/Z/foto.jpg
        # Reemplazar resoluciones conocidas de bajo por alto
        url = re.sub(r'/thumbs/\d+/', '/thumbs/5/', url)
        # Quitar parámetros de tamaño si los hay
        url = re.sub(r'\?.*$', '', url)
        return url

    # ── Ejecución principal ─────────────────────────────────────────────

    def ejecutar(self) -> list[dict]:
        """Ejecuta el scraping completo de la agencia."""
        print("=" * 70)
        print(f"  🏢 SCRAPER DE AGENCIA IDEALISTA")
        print(f"  URL: {self.agency_url}")
        print(f"  Fecha: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        print("=" * 70)

        # Paso 1: Obtener listado de inmuebles
        print(f"\n📋 PASO 1: Recopilando listado de inmuebles...")
        urls = self.obtener_urls_inmuebles()

        if not urls:
            print("\n❌ No se encontraron inmuebles. Verifica la URL y el navegador.")
            return []

        # Paso 2: Extraer detalle de cada inmueble
        print(f"\n📋 PASO 2: Extrayendo detalle de {len(urls)} inmuebles...\n")
        for i, url in enumerate(urls, 1):
            print(f"  [{i}/{len(urls)}] {url[:70]}...")
            inmueble = self.extraer_detalle(url)
            if inmueble:
                self.inmuebles.append(inmueble)
                titulo = inmueble.get('titulo', '?')[:50]
                precio = inmueble.get('precio', '?')
                hab = inmueble.get('habitaciones', '-')
                m2 = inmueble.get('metros_cuadrados', '-')
                imgs = len(inmueble.get('imagenes', []))
                print(f"           ✅ {titulo} | {precio}€ | {hab} hab | {m2} m² | {imgs} imgs")
            else:
                print(f"           ❌ No se pudo extraer")

        print(f"\n{'=' * 70}")
        print(f"  📊 RESUMEN")
        print(f"  Inmuebles extraídos: {len(self.inmuebles)} de {len(urls)}")
        print(f"{'=' * 70}")

        return self.inmuebles

    def guardar_json(self, filepath: str):
        """Guarda los inmuebles en un archivo JSON."""
        data = {
            'agencia_url': self.agency_url,
            'timestamp': datetime.now().isoformat(),
            'total': len(self.inmuebles),
            'inmuebles': self.inmuebles,
        }
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"\n💾 Guardado en: {filepath}")
        print(f"   {len(self.inmuebles)} inmuebles")


# ─── CLI ────────────────────────────────────────────────────────────────────

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Scraper de inmuebles de una agencia profesional en Idealista"
    )
    parser.add_argument(
        '--url', '-u',
        default=AGENCY_URL,
        help=f'URL de la página de la agencia (default: {AGENCY_URL})'
    )
    parser.add_argument(
        '--output', '-o',
        default=None,
        help='Ruta del archivo JSON de salida (default: viviendas_agencia_<nombre>.json)'
    )
    parser.add_argument(
        '--debug', '-d',
        action='store_true',
        help='Activar modo debug con información extra'
    )

    args = parser.parse_args()

    # Generar nombre de archivo de salida si no se especificó
    if not args.output:
        # Extraer nombre de la agencia de la URL
        match = re.search(r'/pro/([^/]+)', args.url)
        nombre_agencia = match.group(1) if match else 'desconocida'
        args.output = f"viviendas_agencia_{nombre_agencia}.json"

    scraper = AgencyScraperIdealista(agency_url=args.url, debug=args.debug)

    try:
        scraper.connect()
        scraper.ejecutar()

        if scraper.inmuebles:
            scraper.guardar_json(args.output)
        else:
            print("\n⚠️  No se obtuvieron inmuebles, no se genera archivo.")

    except KeyboardInterrupt:
        print("\n\n⚠️  Interrumpido por el usuario.")
        if scraper.inmuebles:
            print(f"   Guardando {len(scraper.inmuebles)} inmuebles obtenidos hasta ahora...")
            scraper.guardar_json(args.output)
    except Exception as e:
        print(f"\n❌ Error inesperado: {e}")
        import traceback
        traceback.print_exc()
        if scraper.inmuebles:
            print(f"   Guardando {len(scraper.inmuebles)} inmuebles obtenidos hasta ahora...")
            scraper.guardar_json(args.output)
    finally:
        scraper.close()

    print("\n✅ Finalizado.")


if __name__ == "__main__":
    main()
