"""
Scraper de Fotocasa usando Playwright con Chromium
Chromium de Playwright tiene mejor anti-detección que Chrome normal

NO necesita Chrome instalado - usa Chromium de Playwright
"""

import os
import re
import time
import random
import json
import subprocess
import signal
from typing import List, Optional, Tuple
from datetime import datetime
from dataclasses import dataclass, asdict

from playwright.sync_api import sync_playwright, Page, Browser
from bs4 import BeautifulSoup


# ============== CONFIGURACIÓN ==============
DELAY_MIN_PAGINAS = 1
DELAY_MAX_PAGINAS = 2
DELAY_SCROLL = 0.3
PAUSA_CADA_N_PAGINAS = 10
PAUSA_LARGA_MIN = 5
PAUSA_LARGA_MAX = 8
CDP_PORT = 9223
CHROMIUM_PATH = os.path.expanduser('~/.cache/ms-playwright/chromium-1091/chrome-linux/chrome')
# ===========================================


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


class FotocasaScraperFirefox:
    """Scraper de Fotocasa usando Playwright con Firefox"""
    
    def __init__(self, modo_debug=False, headless=False):
        self.playwright = None
        self.browser: Browser = None
        self.page: Page = None
        self.chrome_process = None  # Proceso Chrome externo
        self.modo_debug = modo_debug
        self.headless = headless
        self.viviendas = []
        self.paginas_sin_pausa = 0
    
    @staticmethod
    def _obtener_ruta_json_persistente(ubicacion: str) -> str:
        """Devuelve la ruta del JSON persistente para una ubicación.
        Ejemplo: viviendas_fotocasa_Igualada.json
        """
        ubicacion_limpia = ubicacion.replace(' ', '_').replace('/', '-')
        return f"viviendas_fotocasa_{ubicacion_limpia}.json"
    
    @staticmethod
    def _cargar_json_existente(ruta_json: str) -> dict:
        """Carga el JSON existente y devuelve {data, urls_conocidas}."""
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
    def _asegurar_orden_fecha_fotocasa(url: str) -> str:
        """Asegura que la URL de Fotocasa ordena por fecha de publicación."""
        param = 'sortType=publicationDate'
        if param in url:
            return url
        if '?' in url:
            return f"{url}&{param}"
        else:
            return f"{url}?{param}"
    
    def _inyectar_antideteccion(self):
        """Inyecta scripts anti-detección en la página actual."""
        self.page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
            Object.defineProperty(navigator, 'plugins', {
                get: () => [1, 2, 3, 4, 5]
            });
            const originalQuery = window.navigator.permissions.query;
            window.navigator.permissions.query = (parameters) => (
                parameters.name === 'notifications' ?
                Promise.resolve({ state: Notification.permission }) :
                originalQuery(parameters)
            );
        """)
        # También inyectar en la página actual (no solo futuras navegaciones)
        try:
            self.page.evaluate("""
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                });
            """)
        except:
            pass
    
    def _lanzar_chrome_externo(self):
        """Lanza Chrome como proceso externo con CDP habilitado."""
        args = [
            CHROMIUM_PATH,
            f'--remote-debugging-port={CDP_PORT}',
            '--no-sandbox',
            '--disable-blink-features=AutomationControlled',
            '--disable-infobars',
            '--lang=es-ES',
            '--window-size=1366,768',
            '--no-first-run',
            '--no-default-browser-check',
        ]
        if self.headless:
            args.append('--headless=new')
        
        self.chrome_process = subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            preexec_fn=os.setsid  # Grupo de proceso propio para poder matar todo
        )
        # Esperar a que Chrome inicie y abra el puerto CDP
        time.sleep(2)
        print(f"      Chrome lanzado (PID: {self.chrome_process.pid}, CDP: :{CDP_PORT})")
    
    def _conectar_playwright(self):
        """Conecta una instancia de Playwright al Chrome externo via CDP."""
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.connect_over_cdp(f'http://localhost:{CDP_PORT}')
        
        # Usar el contexto y página existentes del navegador
        contexts = self.browser.contexts
        if contexts:
            context = contexts[0]
            pages = context.pages
            if pages:
                self.page = pages[0]
            else:
                self.page = context.new_page()
        else:
            context = self.browser.new_context(
                viewport={'width': 1366, 'height': 768},
                locale='es-ES',
                timezone_id='Europe/Madrid',
            )
            self.page = context.new_page()
        
        self._inyectar_antideteccion()
    
    def iniciar_navegador(self):
        """Inicia Chrome externo + conecta Playwright via CDP."""
        print("\n🌐 Iniciando Chrome con CDP...")
        
        try:
            self._lanzar_chrome_externo()
            self._conectar_playwright()
            
            print("✅ Chrome + Playwright CDP iniciado correctamente")
            return True
            
        except Exception as e:
            print(f"❌ Error iniciando navegador: {e}")
            return False
    
    def _es_error_heap(self, error) -> bool:
        """Detecta si el error es por garbage collection o corrupción interna de Playwright."""
        msg = str(error)
        return ('has been collected' in msg or 'unbounded heap' in msg 
                or "_object" in msg or "object has no attribute" in msg)
    
    def reconectar_playwright(self, url_actual: str = None) -> bool:
        """Desconecta y reconecta Playwright al MISMO Chrome (preserva sesión/cookies).
        
        Chrome sigue corriendo como proceso externo, solo se recicla la conexión
        de Playwright que se corrompe después de muchas páginas.
        """
        print("      🔄 Reconectando Playwright al Chrome existente...")
        try:
            # 1. Matar la conexión Playwright corrupta (Chrome sigue vivo)
            try:
                self.browser.close()
            except:
                pass
            try:
                self.playwright.stop()
            except:
                pass
            self.playwright = None
            self.browser = None
            self.page = None
            
            time.sleep(1)
            
            # 2. Reconectar al mismo Chrome
            self._conectar_playwright()
            
            # 3. Navegar a la URL
            if url_actual:
                self.page.goto(url_actual, wait_until='domcontentloaded', timeout=90000)
                time.sleep(random.uniform(2, 4))
            
            print("      ✅ Playwright reconectado correctamente")
            return True
        except Exception as e:
            print(f"      ⚠️  Error reconectando: {e}")
            # Si falla reconectar, intentar matar Chrome y relanzar todo
            print("      🔄 Relanzando Chrome completo...")
            try:
                self._matar_chrome()
                time.sleep(2)
                self._lanzar_chrome_externo()
                self._conectar_playwright()
                if url_actual:
                    self.page.goto(url_actual, wait_until='domcontentloaded', timeout=90000)
                    time.sleep(random.uniform(3, 5))
                # Puede haber CAPTCHA tras relanzar
                if self.verificar_bloqueo():
                    print("      ⚠️  CAPTCHA tras relanzar Chrome!")
                    print("      🔄 Resuelve el captcha en el navegador.")
                    input("      Presiona Enter cuando esté listo...")
                print("      ✅ Chrome relanzado correctamente")
                return True
            except Exception as e2:
                print(f"      ❌ Error relanzando Chrome: {e2}")
                return False
    
    # Alias para compatibilidad
    def renovar_pagina(self, url_actual: str = None) -> bool:
        return self.reconectar_playwright(url_actual)
    
    def recrear_pagina(self, url_actual: str = None) -> bool:
        return self.reconectar_playwright(url_actual)
    
    def _matar_chrome(self):
        """Mata el proceso Chrome externo."""
        if self.chrome_process:
            try:
                os.killpg(os.getpgid(self.chrome_process.pid), signal.SIGTERM)
                self.chrome_process.wait(timeout=5)
            except:
                try:
                    os.killpg(os.getpgid(self.chrome_process.pid), signal.SIGKILL)
                except:
                    pass
            self.chrome_process = None
    
    def cerrar_navegador(self):
        """Cierra Playwright y el Chrome externo"""
        try:
            if self.browser:
                self.browser.close()
        except:
            pass
        try:
            if self.playwright:
                self.playwright.stop()
        except:
            pass
        self._matar_chrome()
        print("🔒 Navegador cerrado")
    
    def scroll_humano(self):
        """Hace scroll rápido para cargar todo el contenido lazy-loaded.
        Usa keyboard (End/Home) como método principal.
        Lanza excepción si falla (para que el reintento recree la página)."""
        try:
            for _ in range(12):
                self.page.keyboard.press("PageDown")
                time.sleep(0.15)
            self.page.keyboard.press("End")
            time.sleep(0.3)
            self.page.keyboard.press("Home")
            time.sleep(0.3)
        except Exception as e:
            if self._es_error_heap(e) or "_object" in str(e):
                # Error crítico: propagar para que el reintento recree la página
                raise
            if self.modo_debug:
                print(f"      [DEBUG] Error en scroll: {e}")
    
    def delay_aleatorio(self):
        """Delay aleatorio entre páginas"""
        delay = random.uniform(DELAY_MIN_PAGINAS, DELAY_MAX_PAGINAS)
        if self.modo_debug:
            print(f"      [DEBUG] Esperando {delay:.1f}s...")
        time.sleep(delay)
    
    def pausa_larga(self):
        """Pausa larga para evitar detección"""
        pausa = random.uniform(PAUSA_LARGA_MIN, PAUSA_LARGA_MAX)
        print(f"\n    ☕ Pausa anti-detección de {pausa:.0f}s...")
        time.sleep(pausa)
    
    def es_particular(self, articulo_html: str) -> bool:
        """Detecta si es particular buscando el texto exacto"""
        # Buscar exactamente: "Anunciante  particular" (con dos espacios)
        if 'Anunciante  particular' in articulo_html or 'Anunciante particular' in articulo_html:
            return True
        return False
    
    def verificar_sin_resultados(self) -> bool:
        """Verifica si la página muestra 'sin resultados' - MUY específico"""
        try:
            # Buscar el div específico de sin resultados
            no_results = self.page.evaluate("document.querySelectorAll('div.re-SearchNoResults').length")
            if no_results > 0:
                if self.modo_debug:
                    print("      [DEBUG] Detectado div.re-SearchNoResults")
                return True
            
            # Buscar título específico del mensaje de error
            titulo_error = self.page.evaluate("document.querySelectorAll('h3.re-SearchNoResults-title').length")
            if titulo_error > 0:
                if self.modo_debug:
                    print("      [DEBUG] Detectado h3.re-SearchNoResults-title")
                return True
            
            return False
        except Exception as e:
            if self._es_error_heap(e):
                raise
            if self.modo_debug:
                print(f"      [DEBUG] Error en verificar_sin_resultados: {e}")
            return False
    
    def verificar_hay_resultados(self) -> bool:
        """Verifica si la página tiene resultados de viviendas"""
        try:
            # Buscar el contenedor de resultados
            seccion_count = self.page.evaluate("document.querySelectorAll('section.re-SearchResult').length")
            if seccion_count > 0:
                if self.modo_debug:
                    print(f"      [DEBUG] Encontrada section.re-SearchResult")
                return True
            
            # O buscar artículos directamente
            articulos_count = self.page.evaluate("document.querySelectorAll('article').length")
            if articulos_count > 0:
                if self.modo_debug:
                    print(f"      [DEBUG] Encontrados {articulos_count} artículos")
                return True
            
            if self.modo_debug:
                print("      [DEBUG] No se encontraron resultados ni artículos")
            return False
        except Exception as e:
            if self._es_error_heap(e):
                raise
            if self.modo_debug:
                print(f"      [DEBUG] Error en verificar_hay_resultados: {e}")
            return False
    
    def obtener_total_paginas(self) -> int:
        """Obtiene el número total de páginas desde el paginador de Fotocasa.
        
        El paginador usa <nav data-panot-component="pagination"> con botones
        <li data-panot-component="pagination-button"> que tienen <a data-index="N">.
        El último botón numérico (mayor data-index) indica el total de páginas.
        """
        try:
            # Scroll progresivo hasta el final para forzar lazy-loading del paginador
            for _ in range(5):
                self.page.evaluate("window.scrollBy(0, window.innerHeight)")
                time.sleep(1)
            # Scroll final al fondo absoluto
            self.page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(2)
            
            # Debug: mostrar si existe el nav en el DOM
            content = self.page.content()
            if 'data-panot-component="pagination"' in content:
                print("      🔍 DEBUG: nav pagination encontrado en el DOM")
            else:
                print("      🔍 DEBUG: nav pagination NO está en el DOM")
                # Intentar un último scroll más agresivo
                self.page.evaluate("""
                    async () => {
                        const delay = ms => new Promise(r => setTimeout(r, ms));
                        for (let i = 0; i < 10; i++) {
                            window.scrollBy(0, 500);
                            await delay(300);
                        }
                        window.scrollTo(0, document.body.scrollHeight);
                    }
                """)
                time.sleep(3)
                content = self.page.content()
                if 'data-panot-component="pagination"' in content:
                    print("      🔍 DEBUG: nav pagination encontrado tras scroll agresivo")
                else:
                    print("      🔍 DEBUG: nav pagination sigue sin aparecer")
            
            # Método 1: Buscar directamente en el HTML con BeautifulSoup (más fiable)
            soup = BeautifulSoup(content, 'html.parser')
            nav = soup.find('nav', attrs={'data-panot-component': 'pagination'})
            if not nav:
                nav = soup.find('nav', attrs={'aria-label': 'Paginación'})
            
            if nav:
                max_pagina = 1
                # Buscar todos los <a> con data-index dentro del nav
                for a_tag in nav.find_all('a', attrs={'data-index': True}):
                    try:
                        idx = a_tag.get('data-index', '')
                        if idx.isdigit():
                            num = int(idx)
                            if num > max_pagina:
                                max_pagina = num
                    except:
                        continue
                
                # Fallback: buscar por aria-label "Página N"
                if max_pagina <= 1:
                    import re
                    for a_tag in nav.find_all('a', attrs={'aria-label': True}):
                        label = a_tag.get('aria-label', '')
                        m = re.search(r'Página\s+(\d+)', label)
                        if m:
                            num = int(m.group(1))
                            if num > max_pagina:
                                max_pagina = num
                
                # Fallback: texto numérico de los botones
                if max_pagina <= 1:
                    for a_tag in nav.find_all('a'):
                        texto = a_tag.get_text(strip=True)
                        if texto.isdigit():
                            num = int(texto)
                            if num > max_pagina:
                                max_pagina = num
                
                if max_pagina > 1:
                    print(f"      📊 Paginador encontrado: {max_pagina} páginas")
                    self.page.evaluate("window.scrollTo(0, 0)")
                    time.sleep(0.5)
                    return max_pagina
            
            # Método 2: Buscar con regex en el HTML crudo como último recurso
            import re
            # Buscar data-index="N" dentro de pagination
            indices = re.findall(r'data-index="(\d+)"', content)
            if indices:
                max_pagina = max(int(i) for i in indices)
                if max_pagina > 1:
                    print(f"      📊 Paginador (regex): {max_pagina} páginas")
                    self.page.evaluate("window.scrollTo(0, 0)")
                    time.sleep(0.5)
                    return max_pagina
            
            # Sin paginador - sin límite, el scraper parará cuando no haya resultados
            print("      ℹ️  No se encontró paginador, se seguirá hasta no encontrar más resultados")
            return 999
            
        except Exception as e:
            print(f"      ⚠️  Error leyendo páginas: {e}, se seguirá hasta no encontrar más resultados")
            return 999
    
    def verificar_bloqueo(self) -> bool:
        """Verifica si hay bloqueo real (DataDome, Cloudflare, etc)"""
        try:
            page_source = self.page.content().lower()
            
            # Solo señales muy específicas de bloqueo real
            bloqueo_signals = [
                'access denied',
                'captcha-delivery',
                'datadome',
                'unusual traffic',
                'too many requests',
                'verify you are human',
                'sentimos la interrupción',
                'blocked by',
                'ray id',  # Cloudflare
            ]
            
            for signal in bloqueo_signals:
                if signal in page_source:
                    if self.modo_debug:
                        print(f"      [DEBUG] Bloqueo detectado: {signal}")
                    return True
            
            return False
        except Exception as e:
            if self._es_error_heap(e):
                raise
            return False  # En caso de error, asumir que no hay bloqueo
    
    def extraer_vivienda(self, articulo) -> Optional[Vivienda]:
        """Extrae datos de un artículo HTML"""
        try:
            articulo_html = str(articulo)
            
            # Verificar si es particular
            if not self.es_particular(articulo_html):
                return None
            
            # Título y URL desde h3 > a[data-panot-component="link-box-link"]
            h3 = articulo.find('h3', class_=lambda x: x and 'text-subhead' in x)
            if not h3:
                return None
            
            link = h3.find('a', {'data-panot-component': 'link-box-link'})
            if not link:
                return None
            
            titulo = link.get_text(strip=True)
            url = link.get('href', '')
            if url and not url.startswith('http'):
                url = f"https://www.fotocasa.es{url}"
            
            # Precio desde div.flex.items-center.gap-mdp.text-display-3 > span
            precio = "N/A"
            precio_div = articulo.find('div', class_=lambda x: x and 'text-display-3' in x)
            if precio_div:
                precio_span = precio_div.find('span')
                if precio_span:
                    precio = precio_span.get_text(strip=True)
            
            # Ubicación (extraer de título después de "en ")
            ubicacion = "N/A"
            if ' en ' in titulo:
                try:
                    ubicacion = titulo.split(' en ', 1)[1].strip()
                except:
                    pass
            
            # Características desde ul.text-body-1 > li
            habitaciones = None
            metros = None
            banos = None
            
            caracteristicas_ul = articulo.find('ul', class_=lambda x: x and 'text-body-1' in x and 'break-words' in x)
            if caracteristicas_ul:
                items = caracteristicas_ul.find_all('li', class_='inline')
                for item in items:
                    texto = item.get_text(strip=True).lower().replace('·', '').strip()
                    if 'hab' in texto:
                        habitaciones = texto
                    elif 'baño' in texto:
                        banos = texto
                    elif 'm²' in texto or 'm2' in texto:
                        metros = texto
            
            # Teléfono desde a[href^="tel:"]
            telefono = None
            tel_link = articulo.find('a', href=lambda x: x and str(x).startswith('tel:'))
            if tel_link:
                telefono = tel_link.get('href', '').replace('tel:', '').strip()
            
            # Descripción opcional (metros + baños si existen)
            descripcion_parts = []
            if banos:
                descripcion_parts.append(banos)
            descripcion = ', '.join(descripcion_parts) if descripcion_parts else None
            
            return Vivienda(
                titulo=titulo,
                precio=precio,
                ubicacion=ubicacion,
                habitaciones=habitaciones,
                metros=metros,
                url=url,
                descripcion=descripcion,
                anunciante="Particular",
                fecha_scraping=datetime.now().isoformat(),
                telefono=telefono
            )
            
        except Exception as e:
            if self.modo_debug:
                print(f"      [DEBUG] Error extrayendo vivienda: {e}")
            return None
    
    def _scrapear_pagina_interno(self, urls_conocidas=None) -> Tuple[List[Vivienda], bool]:
        """Lógica interna de scraping de una página (sin reintentos)."""
        viviendas = []
        encontrado_conocido = False
        
        # Scroll rápido para cargar todo el contenido lazy-loaded
        self.scroll_humano()
        
        # Obtener HTML
        html_content = self.page.content()
        
        # Debug: guardar HTML si está activado
        if self.modo_debug:
            with open('debug_fotocasa.html', 'w', encoding='utf-8') as f:
                f.write(html_content)
            print("      [DEBUG] HTML guardado en debug_fotocasa.html")
        
        # Parsear con BeautifulSoup
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # Buscar el contenedor principal de resultados
        contenedor = soup.find('section', {'class': 're-SearchResult'})
        
        if not contenedor:
            articulos = soup.find_all('article', class_=lambda x: x and '@container' in x)
        else:
            articulos = contenedor.find_all('article', class_=lambda x: x and '@container' in x)
        
        if not articulos:
            articulos = soup.find_all('article')
        
        total_anuncios = len(articulos)
        particulares_count = 0
        
        for articulo in articulos:
            vivienda = self.extraer_vivienda(articulo)
            if vivienda:
                if urls_conocidas and vivienda.url in urls_conocidas:
                    print(f"\n    🛑 Anuncio ya conocido: {vivienda.titulo[:50]}...")
                    print("       Deteniendo búsqueda (los siguientes ya están registrados)")
                    encontrado_conocido = True
                    break
                
                viviendas.append(vivienda)
                particulares_count += 1
                
                if self.modo_debug:
                    print(f"      ✅ PARTICULAR: {vivienda.titulo[:50]}... - {vivienda.precio}")
        
        print(f"    📋 {total_anuncios} anuncios, {particulares_count} particulares")
        
        if viviendas:
            for v in viviendas:
                print(f"      🏠 {v.precio} | {v.ubicacion}")
                if v.telefono:
                    print(f"         📞 {v.telefono}")
        
        print(f"    ✅ {len(viviendas)} particulares encontrados\n")
        
        return viviendas, encontrado_conocido

    def scrapear_pagina(self, urls_conocidas=None) -> Tuple[List[Vivienda], bool]:
        """Scrapea la página actual con 3 reintentos (recarga la página si falla).
        
        Retorna (viviendas_nuevas, encontrado_conocido).
        """
        for intento in range(3):
            try:
                return self._scrapear_pagina_interno(urls_conocidas)
            except Exception as e:
                print(f"    ⚠️  Error en intento {intento + 1}/3: {e}")
                # Siempre intentar obtener URL actual antes de cualquier acción
                url_actual = None
                try:
                    url_actual = self.page.url
                except:
                    pass
                
                if intento < 2:
                    if self._es_error_heap(e):
                        print(f"    🔄 Objeto corrupto, renovando página...")
                        self.renovar_pagina(url_actual)
                        time.sleep(2)
                    else:
                        print(f"    🔄 Recargando página e intentando de nuevo...")
                        try:
                            self.page.reload(wait_until='domcontentloaded', timeout=60000)
                            time.sleep(random.uniform(2, 4))
                        except Exception as reload_err:
                            print(f"    ⚠️  Error recargando: {reload_err}, renovando...")
                            self.renovar_pagina(url_actual)
                else:
                    # Último intento: recrear contexto completo como última opción
                    print(f"    ❌ Falló tras 3 intentos, recreando contexto completo...")
                    self.recrear_pagina(url_actual)
                    time.sleep(2)
        
        return [], False
    
    def construir_url_pagina(self, url_base: str, pagina: int) -> str:
        """Construye la URL para una página específica"""
        if pagina == 1:
            return url_base
        
        # Fotocasa usa formato: /l/N?... o añade /N antes de ?
        if '?' in url_base:
            partes = url_base.split('?', 1)
            # Verificar si ya tiene número de página
            if partes[0].endswith('/l'):
                return f"{partes[0]}/{pagina}?{partes[1]}"
            elif '/l/' in partes[0] and partes[0][-1].isdigit():
                # Reemplazar número existente
                base = partes[0].rsplit('/', 1)[0]
                return f"{base}/{pagina}?{partes[1]}"
            else:
                return f"{partes[0]}/{pagina}?{partes[1]}"
        else:
            if url_base.endswith('/l'):
                return f"{url_base}/{pagina}"
            else:
                return f"{url_base}/{pagina}"
    
    def _navegar_siguiente_pagina_interno(self, url_base: str, pagina_siguiente: int) -> bool:
        """Lógica interna de navegación a siguiente página (sin reintentos)."""
        url_siguiente = self.construir_url_pagina(url_base, pagina_siguiente)
        print(f"      📍 URL: {url_siguiente[:100]}...")
        
        self.page.goto(url_siguiente, wait_until='domcontentloaded', timeout=60000)
        
        # Esperar a que aparezca contenido con múltiples selectores
        selectores = [
            'article',
            'a[href*="/inmueble/"]',
            'nav[data-panot-component="pagination"]',
            'div.re-SearchNoResults',
        ]
        contenido_encontrado = False
        for selector in selectores:
            try:
                self.page.wait_for_selector(selector, timeout=15000)
                contenido_encontrado = True
                if self.modo_debug:
                    print(f"      [DEBUG] Contenido detectado: {selector}")
                break
            except:
                continue
        
        if not contenido_encontrado:
            time.sleep(3)
            for selector in selectores:
                try:
                    self.page.wait_for_selector(selector, timeout=10000)
                    contenido_encontrado = True
                    break
                except:
                    continue
        
        time.sleep(random.uniform(1, 2))
        
        # Verificar si llegamos a página sin resultados
        if self.verificar_sin_resultados():
            print("      ⚠️  Fin del listado (sin más resultados)")
            return False
        
        # Verificar que hay contenido de viviendas
        articulos = self.page.evaluate("document.querySelectorAll('article').length")
        links_inmueble = self.page.evaluate("document.querySelectorAll('a[href*=\"/inmueble/\"]').length")
        if articulos > 0:
            print(f"      ✅ Página {pagina_siguiente} cargada ({articulos} artículos)")
            return True
        elif links_inmueble > 0:
            print(f"      ✅ Página {pagina_siguiente} cargada ({links_inmueble} inmuebles)")
            return True
        
        print(f"      ⚠️  Página {pagina_siguiente} sin artículos detectados, continuando...")
        return True

    def navegar_siguiente_pagina(self, url_base: str, pagina_siguiente: int) -> bool:
        """Navega a la siguiente página con 3 reintentos si falla."""
        url_destino = self.construir_url_pagina(url_base, pagina_siguiente)
        for intento in range(3):
            try:
                return self._navegar_siguiente_pagina_interno(url_base, pagina_siguiente)
            except Exception as e:
                print(f"      ⚠️  Error navegando (intento {intento + 1}/3): {e}")
                if intento < 2:
                    if self._es_error_heap(e):
                        print(f"      🔄 Objeto corrupto, renovando página...")
                        self.renovar_pagina(url_destino)
                        time.sleep(2)
                    else:
                        print(f"      🔄 Reintentando en 3s...")
                        time.sleep(3)
                        try:
                            self.page.reload(wait_until='domcontentloaded', timeout=60000)
                            time.sleep(2)
                        except:
                            self.renovar_pagina(url_destino)
                else:
                    print(f"      ❌ Error navegando tras 3 intentos, recreando contexto completo...")
                    self.recrear_pagina(url_destino)
                    time.sleep(2)
                    return False
        return False
    
    def scrapear(self, url: str, paginas: Optional[int] = None, ubicacion: str = None) -> List[Vivienda]:
        """Método principal de scraping.
        
        Si ubicacion se proporciona, carga el JSON persistente y para al encontrar
        un anuncio ya conocido (el listado se asume ordenado por fecha descendente).
        """
        print("\n" + "="*70)
        print("  FOTOCASA SCRAPER (Chromium - Playwright)")
        print("="*70)
        
        # Cargar URLs conocidas del JSON persistente
        urls_conocidas = set()
        if ubicacion:
            ruta_json = self._obtener_ruta_json_persistente(ubicacion)
            json_existente = self._cargar_json_existente(ruta_json)
            urls_conocidas = json_existente['urls_conocidas']
            if not urls_conocidas:
                print("    📋 No hay datos previos, se hará búsqueda completa")
        
        todas_viviendas = []
        paginas_procesadas = 1
        self.paginas_sin_pausa = 0
        
        print(f"\n🔗 URL: {url}")
        print(f"📄 Páginas: {'Todas' if paginas is None else paginas}")
        print()
        
        # Navegar a la primera página con reintentos
        print("--- Página 1 ---")
        navegacion_exitosa = False
        for intento in range(3):
            try:
                print(f"    Navegando (intento {intento + 1}/3)...")
                self.page.goto(url, wait_until='domcontentloaded', timeout=90000)
                time.sleep(random.uniform(3, 5))
                navegacion_exitosa = True
                break
            except Exception as e:
                print(f"    ⚠️ Intento {intento + 1} falló: {e}")
                if self._es_error_heap(e):
                    print("    🔄 Objeto corrupto, renovando página...")
                    self.renovar_pagina(url)
                    navegacion_exitosa = True
                    break
                if intento < 2:
                    print("    Reintentando...")
                    time.sleep(2)
        
        if not navegacion_exitosa:
            print("❌ No se pudo navegar después de 3 intentos")
            print("    Prueba a resolver el captcha manualmente si aparece")
            input("    Presiona Enter cuando la página cargue...")
            try:
                self.page.wait_for_load_state('domcontentloaded', timeout=30000)
            except:
                pass
        
        # Esperar a que cargue el contenido
        print("    Esperando contenido...")
        try:
            self.page.wait_for_selector('article, a[href*="/inmueble/"], div.re-SearchNoResults', timeout=20000)
            print("    ✅ Contenido detectado")
        except Exception as e:
            print(f"    ⚠️  Timeout esperando contenido: {e}")
            if self._es_error_heap(e):
                self.renovar_pagina(url)
        
        # Dar tiempo extra para que cargue JavaScript dinámico
        time.sleep(2)
        
        # Scroll para activar carga lazy
        try:
            self.page.evaluate("window.scrollTo(0, 500)")
        except:
            pass
        time.sleep(1)
        
        # Guardar HTML para debug (siempre en primera carga para diagnóstico)
        try:
            html_content = self.page.content()
            with open('debug_pagina1.html', 'w', encoding='utf-8') as f:
                f.write(html_content)
            print("    📁 HTML guardado en debug_pagina1.html")
        except Exception as e:
            if self._es_error_heap(e):
                self.renovar_pagina(url)
            print(f"    📁 No se pudo guardar HTML debug")
        
        # Contar elementos para diagnóstico (usando JS para evitar bloqueos)
        try:
            article_count = self.page.evaluate("document.querySelectorAll('article').length")
            no_results_count = self.page.evaluate("document.querySelectorAll('div.re-SearchNoResults').length")
            print(f"    📊 Diagnóstico: articles={article_count}, noResults={no_results_count}")
        except Exception as e:
            if self._es_error_heap(e):
                self.renovar_pagina(url)
            print(f"    📊 Diagnóstico no disponible")
        
        # PRIMERO verificar si HAY resultados (positivo)
        if self.verificar_hay_resultados():
            print("    ✅ Página con viviendas detectada")
        else:
            # Si no hay resultados visibles, verificar si es página de error
            if self.verificar_sin_resultados():
                print("    ⚠️  No hay resultados para esta búsqueda")
                return todas_viviendas
            
            # Ni resultados ni error claro - preguntar
            print("    ⚠️  No se detectaron viviendas en la página")
            print("    📁 Revisa debug_pagina1.html para ver qué cargó")
            
            # Preguntar al usuario
            respuesta = input("    ¿La página muestra viviendas? Continuar? (s/n): ").strip().lower()
            if respuesta != 's':
                return todas_viviendas
        
        # Obtener total de páginas disponibles
        total_paginas = self.obtener_total_paginas()
        print(f"    📊 Total páginas disponibles: {total_paginas}")
        
        # Si se especificó un límite, usar el menor
        if paginas:
            paginas_a_scrapear = min(paginas, total_paginas)
        else:
            paginas_a_scrapear = total_paginas
        
        print(f"    📄 Páginas a procesar: {paginas_a_scrapear}")
        
        while paginas_procesadas <= paginas_a_scrapear:
            
            # Pausa larga periódica
            self.paginas_sin_pausa += 1
            if self.paginas_sin_pausa >= PAUSA_CADA_N_PAGINAS:
                self.pausa_larga()
                self.paginas_sin_pausa = 0
            
            # Verificar bloqueo
            try:
                if self.verificar_bloqueo():
                    print("    ⚠️  Posible bloqueo detectado!")
                    print("    🔄 Resuelve el captcha en el navegador.")
                    input("    Presiona Enter cuando esté listo...")
            except Exception as e:
                if self._es_error_heap(e):
                    print(f"    🔄 Objeto corrupto detectado, renovando página...")
                    url_actual = self.construir_url_pagina(url, paginas_procesadas)
                    self.renovar_pagina(url_actual)
                    time.sleep(2)
            
            # Verificar si hay resultados
            try:
                if self.verificar_sin_resultados():
                    print("    ⚠️  Página sin resultados. Fin del listado.")
                    break
            except Exception as e:
                if self._es_error_heap(e):
                    print(f"    🔄 Objeto corrupto detectado, renovando página...")
                    url_actual = self.construir_url_pagina(url, paginas_procesadas)
                    self.renovar_pagina(url_actual)
                    time.sleep(2)
            
            # Scrapear página actual
            viviendas, encontrado_conocido = self.scrapear_pagina(urls_conocidas=urls_conocidas)
            
            todas_viviendas.extend(viviendas)
            print(f"[*] Total acumulado: {len(todas_viviendas)}")
            
            # Si 0 resultados, verificar si es CAPTCHA/bloqueo
            if not viviendas and not encontrado_conocido:
                if self.verificar_bloqueo():
                    print("    ⚠️  CAPTCHA/bloqueo detectado en esta página!")
                    print("    🔄 Resuelve el captcha en el navegador.")
                    input("    Presiona Enter cuando esté listo...")
                    # Reintentar la página actual
                    viviendas_retry, encontrado_retry = self.scrapear_pagina(urls_conocidas=urls_conocidas)
                    todas_viviendas.extend(viviendas_retry)
                    print(f"[*] Total acumulado: {len(todas_viviendas)}")
                    if encontrado_retry:
                        encontrado_conocido = True
            
            # Si encontramos un anuncio ya conocido, paramos
            if encontrado_conocido:
                if todas_viviendas:
                    print(f"\n🛑 Se encontraron {len(todas_viviendas)} viviendas nuevas antes del conocido")
                else:
                    print(f"\n✅ No hay viviendas nuevas desde la última búsqueda")
                break
            
            # Verificar si hay más páginas
            if paginas_procesadas >= paginas_a_scrapear:
                print(f"\n✅ Completadas {paginas_procesadas} páginas")
                break
            
            # Reconexión preventiva cada 15 páginas (solo recicla conexión Playwright, Chrome sigue vivo)
            if paginas_procesadas > 0 and paginas_procesadas % 15 == 0:
                print(f"\n    🔄 Reconexión preventiva de Playwright (cada 15 páginas)...")
                url_actual = None
                try:
                    url_actual = self.page.url
                except:
                    pass
                self.reconectar_playwright(url_actual)
                time.sleep(2)
            
            # Delay antes de cambiar de página
            delay_pagina = random.uniform(1, 2)
            time.sleep(delay_pagina)
            
            # Navegar a siguiente página
            paginas_procesadas += 1
            print(f"\n--- Página {paginas_procesadas} ---")
            
            if not self.navegar_siguiente_pagina(url, paginas_procesadas):
                print("    ⚠️  No se pudo cargar la página. Fin del listado.")
                break
        
        print(f"\n{'='*70}")
        print(f"  RESUMEN: {len(todas_viviendas)} particulares encontrados")
        print(f"{'='*70}\n")
        
        return todas_viviendas
    
    def guardar_resultados(self, viviendas: List[Vivienda], ubicacion: str, url_scrapeada: str, filename: str = None):
        """Guarda en JSON persistente por ubicación, fusionando con datos existentes.
        
        Los nuevos registros se añaden al principio (más recientes primero).
        """
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
        urls_nuevas = {asdict(v)['url'] for v in viviendas}
        existentes_filtrados = [v for v in viviendas_existentes if v.get('url') not in urls_nuevas]
        todas_viviendas = [asdict(v) for v in viviendas] + existentes_filtrados
        
        data = {
            "timestamp": datetime.now().isoformat(),
            "ubicacion": ubicacion,
            "url": url_scrapeada,
            "total": len(todas_viviendas),
            "viviendas": todas_viviendas
        }
        
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        print(f"💾 Resultados guardados en: {filename}")
        print(f"   Nuevos añadidos: {len(viviendas)}")
        print(f"   Total registros: {len(todas_viviendas)}")
        
        # Subir a la API
        self._subir_a_api(data)
        
        return filename
    
    @staticmethod
    def _subir_a_api(data: dict, config_file: str = "config.json"):
        """Sube los datos a la API de InmoCapt."""
        try:
            import requests
        except ImportError:
            print("\n⚠️  requests no instalado, no se puede subir a la API")
            return
        
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                config = json.load(f)
            api_config = config.get('api', {})
        except:
            return
        
        if not api_config.get('auto_upload', False):
            return
        
        api_url = api_config.get('url', '')
        # Leer API key de .env o variable de entorno
        api_key = os.environ.get('INMOCAPT_API_KEY', '')
        if not api_key:
            env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
            try:
                with open(env_path, 'r') as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith('#') or '=' not in line:
                            continue
                        key, _, value = line.partition('=')
                        if key.strip() == 'INMOCAPT_API_KEY':
                            api_key = value.strip()
                            break
            except FileNotFoundError:
                pass
        
        if not api_url or not api_key:
            print("\n⚠️  API no configurada (falta url en config.json o INMOCAPT_API_KEY en .env)")
            return
        
        create = api_config.get('create_if_not_exists', True)
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
        except Exception as e:
            print(f"\n☁️  API [{ubicacion}]: ⚠️ Error: {e}")


def cargar_urls_fotocasa(config_file: str = "config.json") -> list:
    """Carga las URLs de Fotocasa desde config.json"""
    try:
        with open(config_file, 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        if 'fotocasa' in config and 'urls' in config['fotocasa']:
            return config['fotocasa']['urls']
        return []
    except:
        return []


def main():
    print("""
    ╔══════════════════════════════════════════════════════╗
    ║     FOTOCASA SCRAPER - Playwright                    ║
    ║     Usando Chromium (anti-detección)                 ║
    ╚══════════════════════════════════════════════════════╝
    """)
    
    # Modo debug
    print("[?] ¿Activar modo DEBUG?")
    debug = input("    s/n (Enter = no): ").strip().lower() == 's'
    
    # Cargar URLs de config
    urls_config = cargar_urls_fotocasa()
    urls_a_procesar = []  # Lista de {'url': ..., 'nombre': ...}
    
    # Modo no interactivo por argumentos
    import sys
    if len(sys.argv) > 1:
        # Uso: python fotocasa_scraper_firefox.py [indice] [paginas]
        # Ej: python fotocasa_scraper_firefox.py 1 3   (primera URL, 3 páginas)
        idx = int(sys.argv[1]) - 1
        paginas = int(sys.argv[2]) if len(sys.argv) > 2 else 3
        debug = "--debug" in sys.argv or "-d" in sys.argv
        
        if urls_config and 0 <= idx < len(urls_config):
            item = urls_config[idx]
            urls_a_procesar = [{'url': FotocasaScraperFirefox._asegurar_orden_fecha_fotocasa(item['url']), 'nombre': item.get('nombre', 'Sin nombre')}]
            print(f"\n[*] Modo no-interactivo: {item.get('nombre', 'URL')}, {paginas} página(s)")
        else:
            print(f"Índice inválido. Hay {len(urls_config)} URLs disponibles.")
            return
    elif urls_config:
        print(f"\n[*] URLs encontradas en config.json: {len(urls_config)}")
        print("\n[?] ¿Qué quieres hacer?")
        print("    1. Usar URLs de config.json")
        print("    2. Introducir URL manualmente")
        
        opcion = input("\nElige (1 o 2): ").strip()
        
        if opcion == "1":
            print("\nURLs disponibles:")
            for i, item in enumerate(urls_config, 1):
                print(f"    {i}. {item.get('nombre', 'Sin nombre')}")
            
            seleccion = input("\nSelecciona número (o 'todas'): ").strip()
            
            if seleccion.lower() == 'todas':
                urls_a_procesar = [{'url': item['url'], 'nombre': item.get('nombre', 'Sin nombre')} for item in urls_config]
            else:
                try:
                    idx = int(seleccion) - 1
                    item = urls_config[idx]
                    urls_a_procesar = [{'url': item['url'], 'nombre': item.get('nombre', 'Sin nombre')}]
                except:
                    print("Selección inválida")
                    return
        else:
            url = input("\nIntroduce la URL de Fotocasa: ").strip()
            nombre = input("Nombre/ubicación para esta búsqueda: ").strip() or "Manual"
            urls_a_procesar = [{'url': url, 'nombre': nombre}]
    else:
        url = input("\nIntroduce la URL de Fotocasa: ").strip()
        nombre = input("Nombre/ubicación para esta búsqueda: ").strip() or "Manual"
        urls_a_procesar = [{'url': url, 'nombre': nombre}]
    
    # Número de páginas
    print("\n[?] ¿Cuántas páginas por búsqueda?")
    num_input = input("    (Enter = todas): ").strip()
    paginas = None if not num_input or num_input.lower() == 'todas' else int(num_input)
    
    # Iniciar scraper
    scraper = FotocasaScraperFirefox(modo_debug=debug)
    
    if not scraper.iniciar_navegador():
        return
    
    try:
        for i, item in enumerate(urls_a_procesar, 1):
            url = FotocasaScraperFirefox._asegurar_orden_fecha_fotocasa(item['url'])
            nombre = item['nombre']
            
            print(f"\n\n{'='*70}")
            print(f"  PROCESANDO: {nombre} ({i}/{len(urls_a_procesar)})")
            print(f"  📅 Ordenado por fecha de publicación (más recientes primero)")
            print(f"{'='*70}")
            
            viviendas = scraper.scrapear(url, paginas, ubicacion=nombre)
            
            # Guardar resultados de esta URL
            if viviendas:
                scraper.guardar_resultados(viviendas, ubicacion=nombre, url_scrapeada=url)
            else:
                print(f"\n⚠️  No se encontraron viviendas nuevas de particulares en {nombre}")
                # Subir JSON existente a la API igualmente
                ruta_json = scraper._obtener_ruta_json_persistente(nombre)
                if os.path.exists(ruta_json):
                    try:
                        with open(ruta_json, 'r', encoding='utf-8') as f:
                            data_existente = json.load(f)
                        print(f"☁️  Subiendo JSON existente ({data_existente.get('total', 0)} registros) a la API...")
                        FotocasaScraperFirefox._subir_a_api(data_existente)
                    except Exception as e:
                        print(f"⚠️  Error al leer JSON existente para subir: {e}")
            
            if i < len(urls_a_procesar):
                print("\n⏳ Esperando antes de la siguiente URL...")
                time.sleep(random.uniform(5, 10))
        
    finally:
        scraper.cerrar_navegador()
    
    print("\n✅ Scraping completado")
    input("\nPresiona Enter para salir...")


if __name__ == "__main__":
    main()
