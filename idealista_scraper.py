"""
Scraper específico para Idealista
Hereda de BaseScraper e implementa lógica específica del portal
"""

import re
import time
import random
from typing import List, Optional
from datetime import datetime
from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

from base_scraper import BaseScraper, Vivienda


class IdealistaScraper(BaseScraper):
    """Scraper específico para el portal Idealista"""
    
    def __init__(self, modo_debug=False, usar_rotacion_ip=False, vpn_provider=None, search_url=None):
        super().__init__(modo_debug, usar_rotacion_ip, vpn_provider)
        self.search_url = search_url or "https://www.idealista.com/venta-viviendas/barcelona/anoia/"
    
    def get_portal_name(self) -> str:
        return "Idealista"
    
    def get_search_url(self) -> str:
        return self.search_url
    
    def es_particular(self, html_texto: str) -> tuple[bool, str]:
        """
        Detecta si es particular usando múltiples señales específicas de Idealista
        Retorna: (es_particular: bool, tipo: str)
        """
        texto = html_texto.lower()
        score = 0
        
        # Palabras clave fuertes de particular (+3 puntos)
        palabras_particular_fuertes = [
            'particular', 'propietario', 'dueño directo', 'vendo mi piso',
            'vendo mi casa', 'sin comisión', 'sin intermediarios', 'trato directo',
            'abstenerse agencias', 'no agencias'
        ]
        for palabra in palabras_particular_fuertes:
            if palabra in texto:
                score += 3
                if self.modo_debug:
                    print(f"      [DEBUG] +3 por '{palabra}'")
        
        # Palabras clave medias de particular (+2 puntos)
        palabras_particular_medias = ['vendo', 'vendedor', 'contacto directo', 'llamar al propietario']
        for palabra in palabras_particular_medias:
            if palabra in texto:
                score += 2
                if self.modo_debug:
                    print(f"      [DEBUG] +2 por '{palabra}'")
        
        # Palabras clave fuertes de inmobiliaria (-4 puntos)
        palabras_inmobiliaria_fuertes = [
            'inmobiliaria', 'agencia', 'real estate', 'professional',
            'red inmobiliaria', 'grupo inmobiliario', 'consultoría inmobiliaria',
            'franquicia', 'remax', 'century 21', 'engel', 'tecnocasa',
            'comprarcasa', 'donpiso'
        ]
        for palabra in palabras_inmobiliaria_fuertes:
            if palabra in texto:
                score -= 4
                if self.modo_debug:
                    print(f"      [DEBUG] -4 por '{palabra}'")
        
        # Palabras medias de inmobiliaria (-2 puntos)
        palabras_inmobiliaria_medias = [
            'honorarios', 'comisión del', 'nuestros servicios', 'visítenos',
            'cartera de', 'profesional del sector', 'años de experiencia',
            'equipo de profesionales'
        ]
        for palabra in palabras_inmobiliaria_medias:
            if palabra in texto:
                score -= 2
                if self.modo_debug:
                    print(f"      [DEBUG] -2 por '{palabra}'")
        
        # Clases CSS específicas de Idealista
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
        
        # Análisis del nombre del anunciante
        soup = BeautifulSoup(html_texto, 'html.parser')
        anunciante_elem = (
            soup.find('div', class_='advertiser-name') or
            soup.find('span', class_='professional-name') or
            soup.find('div', class_='item-multimedia-container')
        )
        
        if anunciante_elem:
            nombre_anunciante = anunciante_elem.get_text(strip=True).lower()
            
            if any(palabra in nombre_anunciante for palabra in ['s.l.', 's.a.', 'inmobiliaria', 'properties', 'homes', 'real estate']):
                score -= 6
                if self.modo_debug:
                    print(f"      [DEBUG] -6 por nombre empresarial: {nombre_anunciante[:30]}")
            
            elif len(nombre_anunciante.split()) <= 3 and nombre_anunciante.replace(' ', '').isalpha():
                score += 3
                if self.modo_debug:
                    print(f"      [DEBUG] +3 por nombre personal: {nombre_anunciante}")
        
        if self.modo_debug:
            print(f"      [DEBUG] Score final: {score}")
        
        if score >= 3:
            return True, "Particular"
        elif score <= -3:
            return False, "Inmobiliaria"
        else:
            return False, "Desconocido" if score == 0 else f"Incierto (score: {score})"
    
    def extraer_vivienda(self, articulo) -> Optional[Vivienda]:
        """Extrae datos de un artículo de Idealista"""
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
                fecha_scraping=datetime.now().isoformat(),
                portal="Idealista",
                telefono=None  # No disponible en listado
            )
            
        except Exception as e:
            if self.modo_debug:
                print(f"[DEBUG] Error extrayendo vivienda: {e}")
            return None
    
    def scrapear_pagina(self) -> List[Vivienda]:
        """Scrapea la página actual de Idealista"""
        print("\n[*] Analizando página de Idealista...")
        
        soup = BeautifulSoup(self.driver.page_source, 'html.parser')
        
        # Buscar artículos
        articulos = soup.find_all('article', class_='item')
        
        if not articulos:
            print("[!] No se encontraron artículos con selector 'article.item'")
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
        
        print(f"\n[RESUMEN PÁGINA]")
        print(f"  Total anuncios: {len(viviendas)}")
        print(f"  Particulares: {particulares_count}")
        print(f"  Inmobiliarias: {inmobiliarias_count}")
        
        return viviendas
    
    def verificar_es_particular(self, url):
        """Verifica en el detalle si realmente es un particular (método original)"""
        try:
            if self.modo_debug:
                print(f"      [DEBUG] Verificando: {url[:60]}...")
            
            self._navegar_con_reintentos(url)
            self.delay_aleatorio('detalle')
            self.incrementar_contador_peticiones()
            
            # Verificar si hay captcha
            self.detectar_captcha()
            
            # Parsear la página
            soup = BeautifulSoup(self.driver.page_source, 'html.parser')
            
            # Buscar el div sticky-contact-user-info (selector correcto de Idealista)
            contact_info = soup.find('div', class_='sticky-contact-user-info')
            
            if contact_info:
                # Buscar el div con class="name"
                name_div = contact_info.find('div', class_='name')
                
                if name_div:
                    texto = name_div.get_text(strip=True)
                    
                    if self.modo_debug:
                        print(f"      [DEBUG] Tipo anunciante: {texto}")
                    
                    # Si dice "Particular" es un particular
                    if 'Particular' in texto:
                        return True, 'Particular'
                    else:
                        return False, texto
            
            # Fallback: intentar selector alternativo (por si cambia la estructura)
            prof_name = soup.find('div', class_='professional-name')
            if prof_name:
                name_div = prof_name.find('div', class_='name')
                if name_div:
                    texto = name_div.get_text(strip=True)
                    if self.modo_debug:
                        print(f"      [DEBUG] Tipo anunciante (selector alternativo): {texto}")
                    if 'Particular' in texto:
                        return True, 'Particular'
                    else:
                        return False, texto
            
            return False, 'no_identificado'
            
        except Exception as e:
            print(f"      [!] Error verificando: {e}")
            return False, 'error'
    
    def extraer_datos_vivienda_detalle(self, url):
        """Extrae datos completos de una vivienda desde su página de detalle"""
        try:
            # Si ya estamos en la URL, no navegar de nuevo
            if self.driver.current_url != url:
                self._navegar_con_reintentos(url)
                self.delay_aleatorio('detalle')
            
            soup = BeautifulSoup(self.driver.page_source, 'html.parser')
            
            # Título
            titulo_elem = soup.find('h1', class_='main-info__title-main')
            if not titulo_elem:
                titulo_elem = soup.find('span', class_='main-info__title-main')
            titulo = titulo_elem.get_text(strip=True) if titulo_elem else "Sin título"
            
            # Precio
            precio_elem = soup.find('span', class_='info-data-price')
            precio = precio_elem.get_text(strip=True) if precio_elem else "N/A"
            
            # Ubicación
            ubicacion_elem = soup.find('span', class_='main-info__title-minor')
            ubicacion = ubicacion_elem.get_text(strip=True) if ubicacion_elem else "N/A"
            
            # Detalles
            habitaciones = None
            metros = None
            
            detalles_container = soup.find('div', class_='info-features')
            if detalles_container:
                caracteristicas = detalles_container.find_all('span', class_='info-data-name')
                for car in caracteristicas:
                    texto = car.get_text(strip=True).lower()
                    valor_elem = car.find_next_sibling('span', class_='info-data-value')
                    if valor_elem:
                        valor = valor_elem.get_text(strip=True)
                        if 'hab' in texto:
                            habitaciones = valor
                        elif 'm²' in texto or 'superficie' in texto:
                            metros = valor
            
            # Descripción
            descripcion_elem = soup.find('div', class_='comment')
            descripcion = descripcion_elem.get_text(strip=True) if descripcion_elem else None
            
            # Teléfono - Hacer clic en el botón para revelarlo
            telefono = None
            try:
                # Buscar el botón de teléfono
                phone_button = self.driver.find_element(By.CSS_SELECTOR, "a.phone-number._mobilePhone, a.icon-phone-fill")
                
                if self.modo_debug:
                    print("      [DEBUG] Botón de teléfono encontrado, haciendo clic...")
                
                # Scroll al botón para asegurarse que es visible
                self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", phone_button)
                time.sleep(0.5)
                
                # Hacer clic en el botón
                phone_button.click()
                
                # Esperar a que aparezca el número (puede tardar un momento)
                time.sleep(1)
                
                # Intentar extraer el número del botón actualizado o de elementos que aparecen
                try:
                    # Opción 1: El número puede aparecer en el href del enlace
                    phone_link = WebDriverWait(self.driver, 3).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, "a.phone-number[href^='tel:'], a._mobilePhone[href^='tel:']"))
                    )
                    href = phone_link.get_attribute('href')
                    if href and href.startswith('tel:'):
                        telefono = href.replace('tel:', '').strip()
                        if self.modo_debug:
                            print(f"      [DEBUG] ✓ Teléfono extraído: {telefono}")
                except TimeoutException:
                    # Opción 2: El número puede aparecer en el texto del botón
                    phone_text = phone_button.text.strip()
                    if phone_text and phone_text != 'Llamar' and len(phone_text) > 5:
                        telefono = phone_text
                        if self.modo_debug:
                            print(f"      [DEBUG] ✓ Teléfono extraído del texto: {telefono}")
                    else:
                        # Opción 3: Buscar en spans dentro del botón
                        phone_spans = phone_button.find_elements(By.TAG_NAME, 'span')
                        for span in phone_spans:
                            span_text = span.text.strip()
                            if span_text and span_text != 'Llamar' and len(span_text) > 5:
                                telefono = span_text
                                if self.modo_debug:
                                    print(f"      [DEBUG] ✓ Teléfono extraído de span: {telefono}")
                                break
                
            except NoSuchElementException:
                if self.modo_debug:
                    print("      [DEBUG] No se encontró botón de teléfono")
            except Exception as e:
                if self.modo_debug:
                    print(f"      [DEBUG] Error extrayendo teléfono: {e}")
            
            # Tipo de anunciante
            _, tipo_anunciante = self.es_particular(str(soup))
            
            return Vivienda(
                titulo=titulo,
                precio=precio,
                ubicacion=ubicacion,
                habitaciones=habitaciones,
                metros=metros,
                url=url,
                descripcion=descripcion,
                anunciante=tipo_anunciante,
                fecha_scraping=datetime.now().isoformat(),
                portal="Idealista",
                telefono=telefono
            )
            
        except Exception as e:
            print(f"    ⚠️ Error extrayendo datos: {e}")
            return None
    
    def filtrar_listado_particulares(self, paginas=None):
        """Filtra viviendas que NO tienen logo de inmobiliaria en el listado (método original)"""
        if not self.driver:
            print("[ERROR] Driver no inicializado")
            return []
        
        print(f"\n🔍 [ETAPA 1: FILTRADO EN LISTADO]")
        print("="*70)
        
        if paginas is None:
            print("    Modo: TODAS LAS PÁGINAS (hasta detectar el final)")
        else:
            print(f"    Modo: {paginas} página(s)")
        
        posibles_particulares = []
        pagina_actual = 1
        articulos_vistos_ids = set()  # Para detectar páginas repetidas
        primer_articulo_id = None  # ID del primer artículo de la página 1
        
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
            self._navegar_con_reintentos(url_pagina)
            self.delay_aleatorio('pagina')
            self.incrementar_contador_peticiones()
            
            # Verificar si hay captcha
            self.detectar_captcha()
            
            # Detectar si nos redirigió a página-1 (significa que llegamos al final)
            url_actual = self.driver.current_url
            if pagina_actual > 1:
                # Buscar pagina-1 seguido de ? o final de URL
                if re.search(r'pagina-1(\?|$)', url_actual):
                    print(f"\n✅ Detectado final del listado (redirigió a página-1)")
                    break
                
                # Verificar si la URL actual no contiene el número de página esperado
                # Esto puede indicar que la página no existe y nos redirigió
                pagina_en_url = re.search(r'pagina-(\d+)', url_actual)
                if pagina_en_url:
                    numero_en_url = int(pagina_en_url.group(1))
                    if numero_en_url < pagina_actual:
                        print(f"\n✅ Detectado final del listado (URL muestra página {numero_en_url}, esperábamos {pagina_actual})")
                        break
                elif not url_actual.endswith('/'):
                    # Si estamos en página > 1 pero la URL no tiene /pagina-X, llegamos al final
                    print(f"\n✅ Detectado final del listado (URL sin paginación en página {pagina_actual})")
                    break
            
            # Scroll para cargar contenido
            for i in range(5):
                self.driver.execute_script(f"window.scrollTo(0, {300 * (i + 1)});")
                time.sleep(random.uniform(0.3, 0.8))
            time.sleep(random.uniform(1, 2))
            
            # Parsear con BeautifulSoup
            soup = BeautifulSoup(self.driver.page_source, 'html.parser')
            
            # Buscar todos los artículos
            articulos = soup.find_all('article', class_='item')
            
            if not articulos:
                print("[!] No se encontraron artículos")
                if pagina_actual == 1:
                    break
                else:
                    print("[*] Posiblemente llegamos al final del listado")
                    break
            
            print(f"📊 Total artículos encontrados: {len(articulos)}")
            
            # Obtener el ID del primer artículo
            primer_articulo_actual = articulos[0].get('data-element-id') if articulos else None
            
            # VERIFICACIÓN CRÍTICA: Si el primer artículo coincide con el de la página 1, volvimos al inicio
            if pagina_actual == 1:
                primer_articulo_id = primer_articulo_actual
                if self.modo_debug:
                    print(f"      [DEBUG] Primer artículo de página 1: {primer_articulo_id}")
            elif pagina_actual > 1 and primer_articulo_actual == primer_articulo_id:
                print(f"\n✅ Detectado final del listado (primer artículo repetido: {primer_articulo_actual})")
                print(f"    → La página {pagina_actual} muestra los mismos resultados que la página 1")
                break
            
            # Analizar el componente de paginación para verificar control
            try:
                paginacion_div = soup.find('div', class_='pagination')
                if paginacion_div:
                    # Extraer todos los números de página disponibles
                    enlaces_pagina = paginacion_div.find_all('a', href=re.compile(r'/pagina-\d+\.htm'))
                    numeros_pagina = []
                    for enlace in enlaces_pagina:
                        match = re.search(r'/pagina-(\d+)\.htm', enlace.get('href', ''))
                        if match:
                            numeros_pagina.append(int(match.group(1)))
                    
                    # También buscar enlace a página 1 (sin /pagina-X)
                    enlace_pag1 = paginacion_div.find('a', href=re.compile(r'^[^#]+(?<!pagina-\d)\.htm$|/$'))
                    if enlace_pag1:
                        numeros_pagina.append(1)
                    
                    if numeros_pagina:
                        max_pagina_disponible = max(numeros_pagina)
                        if self.modo_debug:
                            print(f"      [DEBUG] Páginas disponibles en paginación: {sorted(set(numeros_pagina))}")
                            print(f"      [DEBUG] Máxima página disponible: {max_pagina_disponible}")
                        
                        # Si estamos intentando acceder a una página mayor que la máxima, terminamos
                        if pagina_actual > max_pagina_disponible:
                            print(f"\n✅ Detectado final del listado (página {pagina_actual} > máxima disponible {max_pagina_disponible})")
                            break
                    
                    # Verificar si existe botón "Siguiente"
                    boton_siguiente = paginacion_div.find('li', class_='next')
                    if not boton_siguiente:
                        print(f"\n✅ Detectado final del listado (no existe botón 'Siguiente' en paginación)")
                        pagina_actual += 1
                        break
                    
                    if self.modo_debug:
                        print(f"      [DEBUG] Paginación HTML: {paginacion_div}")
            except Exception as e:
                if self.modo_debug:
                    print(f"      [DEBUG] Error analizando paginación: {str(e)}")
            
            # Verificar si estamos viendo artículos repetidos (indica que llegamos al final)
            articulos_actuales_ids = set()
            for art in articulos:
                art_id = art.get('data-element-id')
                if art_id:
                    articulos_actuales_ids.add(art_id)
            
            # Si todos los artículos ya los vimos antes, llegamos al final
            if pagina_actual > 1 and articulos_actuales_ids and articulos_actuales_ids.issubset(articulos_vistos_ids):
                print(f"\n✅ Detectado final del listado (todos los artículos ya fueron vistos)")
                break
            
            # Agregar los IDs actuales a la lista de vistos
            articulos_vistos_ids.update(articulos_actuales_ids)
            
            # Filtrar los que NO tienen logo de inmobiliaria
            posibles_en_esta_pagina = 0
            for articulo in articulos:
                # CLAVE: Buscar si tiene logo de marca/empresa
                tiene_logo = articulo.find('picture', class_='logo-branding')
                
                if not tiene_logo:
                    # Es posible particular - extraer ID y URL
                    element_id = articulo.get('data-element-id')
                    link = articulo.find('a', class_='item-link')
                    
                    if element_id and link:
                        url_detalle = link.get('href', '')
                        if url_detalle and not url_detalle.startswith('http'):
                            url_detalle = "https://www.idealista.com" + url_detalle
                        
                        titulo = link.get('title', 'Sin título')
                        
                        posibles_particulares.append({
                            'id': element_id,
                            'url': url_detalle,
                            'titulo': titulo
                        })
                        
                        posibles_en_esta_pagina += 1
                        
                        if self.modo_debug:
                            print(f"      [DEBUG] ✓ Posible particular: ID {element_id} - {titulo[:50]}")
            
            print(f"✅ Posibles particulares en esta página: {posibles_en_esta_pagina}")
            
            # Incrementar contador
            pagina_actual += 1
        
        print(f"\n{'='*70}")
        print(f"[RESUMEN ETAPA 1]")
        print(f"  Páginas procesadas: {pagina_actual - 1}")
        print(f"  Posibles particulares detectados: {len(posibles_particulares)}")
        print(f"{'='*70}")
        
        if not posibles_particulares:
            print("\n[!] No se encontraron posibles particulares en el listado")
            return []
        
        # ETAPA 2: Verificación en detalle
        print(f"\n[ETAPA 2: VERIFICACIÓN EN DETALLE]")
        print("="*70)
        print(f"Verificando {len(posibles_particulares)} anuncios...\n")
        
        confirmados = 0
        todas_viviendas = []
        
        for idx, vivienda_info in enumerate(posibles_particulares, 1):
            print(f"\n[{idx}/{len(posibles_particulares)}] Verificando ID {vivienda_info['id']}...")
            print(f"    {vivienda_info['titulo'][:60]}...")
            
            es_particular, tipo = self.verificar_es_particular(vivienda_info['url'])
            
            if es_particular:
                print(f"    ✅ CONFIRMADO: Particular")
                
                vivienda = self.extraer_datos_vivienda_detalle(vivienda_info['url'])
                
                if vivienda:
                    todas_viviendas.append(vivienda)
                    confirmados += 1
                    
                    print(f"       📍 {vivienda.ubicacion}")
                    print(f"       💰 {vivienda.precio}")
                    if vivienda.habitaciones or vivienda.metros:
                        print(f"       🏠 {vivienda.habitaciones or 'N/A'} | {vivienda.metros or 'N/A'}")
            else:
                print(f"    ❌ No es particular: {tipo}")
        
        print("\n" + "="*70)
        print("📊 RESUMEN FINAL")
        print("="*70)
        print(f"Posibles particulares (listado): {len(posibles_particulares)}")
        print(f"Confirmados como particulares:   {confirmados}")
        print(f"Descartados (empresas):          {len(posibles_particulares) - confirmados}")
        
        return todas_viviendas
    
    def scrapear_con_filtrado(self, paginas=None):
        """Método principal de scraping con filtrado de dos etapas"""
        return self.filtrar_listado_particulares(paginas)
