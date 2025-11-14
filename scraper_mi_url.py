"""
Scraper CDP configurado para tu URL específica de Idealista
Ejecuta este script después de abrir Chrome con start_chrome_debug.bat
"""

import time
import json
import re
from datetime import datetime
from typing import List, Optional
from dataclasses import dataclass, asdict

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from bs4 import BeautifulSoup


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


# URL objetivo
URL_IDEALISTA = "https://www.idealista.com/areas/venta-viviendas/?shape=%28%28gdh%7DFywmFs_NqcLa_Bwsi%40sxIkgUmEqvdA%7CkN%7BbH%60t%5CceIltPxpNdfDh%7DLvrB%60og%40re%40n%7Be%40cnNbdf%40ch%5Bl%60R%29%29"


class ScraperPersonalizado:
    
    def __init__(self, modo_debug=False):
        self.driver = None
        self.viviendas = []
        self.modo_debug = modo_debug
        self.resultados = []
    
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
    
    def navegar_a_url(self):
        """Navega a la URL de búsqueda"""
        print(f"\n[*] Navegando a la URL de búsqueda...")
        print(f"    {URL_IDEALISTA[:80]}...")
        
        self.driver.get(URL_IDEALISTA)
        print("[*] Esperando carga de página...")
        time.sleep(5)
        
        # Verificar si hay bloqueo
        if "datadome" in self.driver.page_source.lower() or "bloqueado" in self.driver.page_source.lower():
            print("\n[!] ADVERTENCIA: Parece que DataDome bloqueó el acceso")
            print("    Resuelve el CAPTCHA manualmente en el navegador si aparece")
            input("\n    Presiona Enter cuando hayas resuelto el CAPTCHA...")
        
        # Scroll para cargar contenido
        print("[*] Haciendo scroll...")
        for i in range(5):
            self.driver.execute_script(f"window.scrollTo(0, {300 * (i + 1)});")
            time.sleep(0.5)
        
        time.sleep(2)
    
    def filtrar_listado_particulares(self, paginas=None):
        """Filtra viviendas que NO tienen logo de inmobiliaria en el listado
        
        Si paginas=None, procesa todas las páginas disponibles automáticamente
        """
        print(f"\n🔍 Filtrando listado en busca de particulares...")
        if paginas is None:
            print("    Modo: TODAS LAS PÁGINAS (hasta detectar el final)")
        else:
            print(f"    Modo: {paginas} página(s)")
        
        posibles_particulares = []
        pagina_actual = 1
        url_base_sin_pagina = self.driver.current_url.split('?')[0].replace('/pagina-1', '').replace('/pagina-2', '').replace('/pagina-3', '').replace('/pagina-4', '').replace('/pagina-5', '').replace('/pagina-6', '').replace('/pagina-7', '').replace('/pagina-8', '').replace('/pagina-9', '')
        parametros = '?' + self.driver.current_url.split('?')[1] if '?' in self.driver.current_url else ''
        
        while True:
            # Si se especificó un límite de páginas, respetarlo
            if paginas is not None and pagina_actual > paginas:
                print(f"\n[*] Límite de {paginas} página(s) alcanzado")
                break
            
            print(f"\n📄 Procesando página {pagina_actual}...")
            
            # Construir URL de la página actual
            if pagina_actual == 1:
                url_pagina = url_base_sin_pagina + parametros
            else:
                url_pagina = f"{url_base_sin_pagina}/pagina-{pagina_actual}{parametros}"
            
            if self.modo_debug:
                print(f"    [DEBUG] URL: {url_pagina[:80]}...")
            
            # Navegar a la página
            self.driver.get(url_pagina)
            time.sleep(3)
            
            # Detectar si nos redirigió a página-1 (significa que llegamos al final)
            url_actual = self.driver.current_url
            # Verificar si contiene exactamente 'pagina-1' y no pagina-10, pagina-11, etc.
            if pagina_actual > 1:
                # Buscar pagina-1 seguido de ? o final de URL
                if re.search(r'pagina-1(\?|$)', url_actual):
                    print(f"\n✅ Detectado final del listado (redirigió a página-1)")
                    break
            
            # Scroll para cargar contenido
            for i in range(5):
                self.driver.execute_script(f"window.scrollTo(0, {300 * (i + 1)});")
                time.sleep(0.5)
            
            time.sleep(2)
            
            # Parsear con BeautifulSoup
            soup = BeautifulSoup(self.driver.page_source, 'html.parser')
            
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
                        
                        titulo = link.get('title', 'Sin título')
                        
                        posibles_particulares.append({
                            'id': element_id,
                            'url': url_detalle,
                            'titulo': titulo
                        })
                        
                        posibles_en_esta_pagina += 1
                        
                        if self.modo_debug:
                            print(f"      [DEBUG] ✓ Posible particular: ID {element_id}")
            
            print(f"✅ Posibles particulares en esta página: {posibles_en_esta_pagina}")
            
            # Incrementar contador
            pagina_actual += 1
            
            # Pausa entre páginas
            time.sleep(2)
        
        print(f"\n📊 RESUMEN DEL FILTRADO:")
        print(f"    Páginas procesadas: {pagina_actual - 1}")
        print(f"    TOTAL posibles particulares: {len(posibles_particulares)}")
        return posibles_particulares
    
    def verificar_es_particular(self, url):
        """Verifica en el detalle si realmente es un particular"""
        if self.modo_debug:
            print(f"      [DEBUG] Verificando: {url[:60]}...")
        
        try:
            self.driver.get(url)
            time.sleep(3)
            
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
            
            # Teléfono - hacer click en el botón para revelarlo
            telefono = None
            try:
                # Buscar el botón "Ver teléfono"
                ver_telefono_btn = self.driver.find_element(By.CLASS_NAME, 'see-phones-btn')
                if ver_telefono_btn:
                    # Hacer click para revelar el teléfono
                    ver_telefono_btn.click()
                    time.sleep(1)  # Esperar a que se muestre el teléfono
                    
                    # Ahora buscar el teléfono revelado
                    try:
                        telefono_elem = self.driver.find_element(By.CLASS_NAME, 'hidden-contact-phones_formatted-phone')
                        if telefono_elem:
                            # Obtener el span con el texto del teléfono
                            telefono_span = telefono_elem.find_element(By.CLASS_NAME, 'hidden-contact-phones_text')
                            if telefono_span:
                                telefono = telefono_span.text.strip()
                                if self.modo_debug:
                                    print(f"      [DEBUG] Teléfono obtenido: {telefono}")
                    except:
                        if self.modo_debug:
                            print(f"      [DEBUG] No se pudo obtener el teléfono revelado")
            except:
                if self.modo_debug:
                    print(f"      [DEBUG] No se encontró botón 'Ver teléfono'")
            
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
                fecha_scraping=datos['fecha_scraping']
            )
            
        except Exception as e:
            print(f"      [!] Error extrayendo datos: {e}")
            return None
    
    def scrapear_con_filtrado(self, paginas=None):
        """Método NUEVO: Scrapea usando el filtrado de dos etapas
        
        Si paginas=None, procesa todas las páginas disponibles
        """
        print("\n" + "="*70)
        print("🏠 SCRAPER CON FILTRADO - SOLO PARTICULARES")
        print("="*70)
        
        # Paso 1: Filtrar en el listado
        posibles = self.filtrar_listado_particulares(paginas)
        
        if not posibles:
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
            
            # Pausa entre viviendas
            if idx < len(posibles):
                time.sleep(2)
        
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
            
            # Guardar progreso
            self.guardar(todas, f"viviendas_pagina_{pagina}.json")
            
            if pagina < max_paginas:
                # Buscar botón siguiente
                try:
                    next_btn = self.driver.find_element(By.XPATH, "//a[contains(@class, 'icon-arrow-right-after')]")
                    print(f"\n[*] Navegando a página {pagina + 1}...")
                    next_btn.click()
                    time.sleep(5)
                except:
                    print(f"\n[!] No se encontró botón 'siguiente'. Terminando.")
                    break
        
        return todas
    
    def guardar(self, viviendas: List[Vivienda], filename: str):
        """Guarda en JSON"""
        # Separar por tipo
        particulares = [v for v in viviendas if v.anunciante == "Particular"]
        inmobiliarias = [v for v in viviendas if v.anunciante == "Inmobiliaria"]
        
        data = {
            'timestamp': datetime.now().isoformat(),
            'url': URL_IDEALISTA,
            'total': len(viviendas),
            'particulares': len(particulares),
            'inmobiliarias': len(inmobiliarias),
            'viviendas': {
                'todas': [asdict(v) for v in viviendas],
                'solo_particulares': [asdict(v) for v in particulares],
                'solo_inmobiliarias': [asdict(v) for v in inmobiliarias]
            }
        }
        
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        print(f"\n[OK] Guardado en: {filename}")
        print(f"     Total: {len(viviendas)} | Particulares: {len(particulares)} | Inmobiliarias: {len(inmobiliarias)}")
    
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
    
    scraper = ScraperPersonalizado(modo_debug=debug)
    
    # Conectar
    if not scraper.conectar_chrome():
        return
    
    # Preguntar qué hacer
    print("\n[?] OPCIONES:")
    print("    1. Navegar automáticamente a tu URL y scrapear CON FILTRADO (recomendado)")
    print("    2. Ya estoy en la página, scrapear CON FILTRADO")
    print("    3. Ya estoy en la página, scrapear sin filtrado (método antiguo)")
    
    opcion = input("\nElige (1, 2 o 3): ").strip()
    
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
    
    # Scrapear según opción elegida
    if num_paginas is None:
        print(f"[*] Iniciando scraping de TODAS las páginas...")
    else:
        print(f"[*] Iniciando scraping de {num_paginas} página(s)...")
    
    if opcion == "3":
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
        viviendas = scraper.scrapear_con_filtrado(num_paginas)
    
    if not viviendas:
        print("\n[!] No se encontraron viviendas")
        return
    
    # Guardar resultado final
    filename = f"viviendas_idealista_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
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
