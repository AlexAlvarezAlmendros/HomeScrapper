"""
Scraper específico para Fotocasa
Hereda de BaseScraper e implementa lógica específica del portal

NOTA: Fotocasa permite extraer TODO desde el listado, no hace falta entrar al detalle
"""

import re
import time
import random
from typing import List, Optional
from datetime import datetime
from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By

from base_scraper import BaseScraper, Vivienda


class FotocasaScraper(BaseScraper):
    """Scraper específico para el portal Fotocasa"""
    
    def __init__(self, modo_debug=False, usar_rotacion_ip=False, vpn_provider=None, search_url=None):
        super().__init__(modo_debug, usar_rotacion_ip, vpn_provider)
        self.search_url = search_url or "https://www.fotocasa.es/es/comprar/viviendas/barcelona/capital/todas-las-zonas/l"
    
    def get_portal_name(self) -> str:
        return "Fotocasa"
    
    def get_search_url(self) -> str:
        return self.search_url
    
    def es_particular(self, html_texto: str) -> tuple[bool, str]:
        """
        Detecta si es particular usando señales específicas de Fotocasa
        En Fotocasa es muy fácil: buscar la imagen particular_user_icon.svg o el texto "Anunciante particular"
        """
        texto = html_texto.lower()
        
        # Señal 1: Imagen específica de particular
        if 'particular_user_icon.svg' in texto:
            if self.modo_debug:
                print(f"      [DEBUG] ✓ Detectado por icono de particular")
            return True, "Particular"
        
        # Señal 2: Texto explícito
        if 'anunciante  particular' in texto or 'anunciante particular' in texto:
            if self.modo_debug:
                print(f"      [DEBUG] ✓ Detectado por texto 'Anunciante particular'")
            return True, "Particular"
        
        # Si no tiene ninguna señal de particular, es profesional
        if self.modo_debug:
            print(f"      [DEBUG] ✗ No se encontraron señales de particular")
        return False, "Profesional"
    
    def extraer_vivienda(self, articulo) -> Optional[Vivienda]:
        """Extrae datos de un artículo de Fotocasa directamente desde el listado"""
        try:
            # Verificar primero si es particular
            es_part, tipo_anunciante = self.es_particular(str(articulo))
            
            # Si no es particular, saltar
            if not es_part:
                return None
            
            # Título y URL - Buscar el enlace principal
            link = articulo.find('a', {'data-panot-component': 'link-box-link'})
            if not link:
                # Buscar enlace alternativo
                link = articulo.find('a', href=lambda x: x and '/d' in x)
            
            if not link:
                return None
            
            # Extraer título
            titulo_elem = link.find('strong')
            if titulo_elem:
                titulo_completo = link.get_text(strip=True)
                titulo = titulo_completo
            else:
                titulo = link.get_text(strip=True)
            
            # URL
            url = link.get('href', '')
            if url and not url.startswith('http'):
                url = f"https://www.fotocasa.es{url}"
            
            # Precio - buscar en el div con text-display-3
            precio_elem = articulo.find('div', class_='text-display-3')
            if not precio_elem:
                precio_elem = articulo.find('span', string=lambda x: x and '€' in str(x))
            precio = precio_elem.get_text(strip=True) if precio_elem else "N/A"
            
            # Ubicación - puede estar en varios lugares
            ubicacion = "N/A"
            # Buscar en el título después del tipo de vivienda
            if 'en ' in titulo:
                try:
                    ubicacion = titulo.split('en ', 1)[1].strip()
                except:
                    pass
            
            # Características (habitaciones, baños, metros) - buscar en la lista ul
            habitaciones = None
            metros = None
            banos = None
            
            caracteristicas_ul = articulo.find('ul', class_=lambda x: x and 'text-body-1' in x)
            if caracteristicas_ul:
                items = caracteristicas_ul.find_all('li', class_='inline')
                for item in items:
                    texto = item.get_text(strip=True).lower()
                    if 'hab' in texto:
                        habitaciones = texto.replace('·', '').strip()
                    elif 'baño' in texto:
                        banos = texto.replace('·', '').strip()
                    elif 'm²' in texto or 'm2' in texto:
                        metros = texto.replace('·', '').strip()
            
            # Teléfono - buscar el enlace tel:
            telefono = None
            tel_link = articulo.find('a', href=lambda x: x and x.startswith('tel:'))
            if tel_link:
                telefono = tel_link.get('href').replace('tel:', '').strip()
                if self.modo_debug:
                    print(f"      [DEBUG] Teléfono encontrado: {telefono}")
            
            # Descripción oculta (puede estar en un <p class="hidden">)
            descripcion = None
            desc_elem = articulo.find('p', class_='hidden')
            if desc_elem:
                descripcion = desc_elem.get_text(strip=True)
            
            # Construir ubicación más completa si tenemos más info
            if habitaciones or metros:
                detalles = f"{habitaciones or ''} {metros or ''}".strip()
            else:
                detalles = ""
            
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
                portal="Fotocasa",
                telefono=telefono  # Fotocasa tiene teléfono en listado
            )
            
        except Exception as e:
            if self.modo_debug:
                print(f"[DEBUG] Error extrayendo vivienda: {e}")
            return None
    
    def scrapear_pagina(self) -> List[Vivienda]:
        """Scrapea los anuncios de particulares de la página actual"""
        viviendas = []
        
        try:
            # Esperar a que cargue el contenido
            time.sleep(random.uniform(2, 4))
            
            # Verificar si hay captcha
            if self.detectar_captcha():
                print("    ⚠️  Captcha detectado. Esperando resolución manual...")
                input("    Presiona Enter cuando hayas resuelto el captcha...")
            
            # Obtener el HTML de la página
            soup = BeautifulSoup(self.driver.page_source, 'html.parser')
            
            # Buscar artículos de anuncios
            # Fotocasa usa <article> con atributos data-*
            articulos = soup.find_all('article', attrs={'data-testid': lambda x: x and 'listing-card' in str(x)})
            if not articulos:
                # Intentar selector alternativo
                articulos = soup.find_all('article', class_=lambda x: x and '@container' in str(x))
            if not articulos:
                # Otro intento
                articulos = soup.find_all('article', class_='re-Card')
            if not articulos:
                articulos = soup.find_all('div', class_='re-Card')
            if not articulos:
                # Selector más general
                articulos = soup.find_all('article')
            
            print(f"    📋 Encontrados {len(articulos)} anuncios en la página")
            
            for i, articulo in enumerate(articulos, 1):
                if self.modo_debug:
                    print(f"      [DEBUG] Procesando anuncio {i}/{len(articulos)}")
                
                vivienda = self.extraer_vivienda(articulo)
                if vivienda:
                    viviendas.append(vivienda)
                    if self.modo_debug:
                        print(f"      ✅ PARTICULAR: {vivienda.titulo[:50]}...")
                else:
                    if self.modo_debug:
                        print(f"      ⏭️  Anuncio descartado (no es particular o error)")
                
                # Pequeño delay entre anuncios para parecer humano
                if i % 5 == 0:
                    time.sleep(random.uniform(0.5, 1.5))
            
            print(f"    ✅ {len(viviendas)} viviendas de particulares encontradas en esta página\n")
            
        except Exception as e:
            print(f"    ❌ Error scrapeando página: {e}")
            if self.modo_debug:
                import traceback
                traceback.print_exc()
        
        return viviendas
    
    def filtrar_listado_particulares(self, paginas=None):
        """
        Filtra anuncios de particulares en Fotocasa.
        A diferencia de Idealista, NO necesita visitar detalle ya que todo está en el listado.
        """
        print("\n[FOTOCASA: FILTRADO DE PARTICULARES EN LISTADO]")
        print("="*70)
        
        paginas_procesadas = 0
        todas_viviendas = []
        continuar = True
        
        # Obtener URL base y parámetros
        url_base = self.driver.current_url.split('?')[0]
        parametros = '?' + self.driver.current_url.split('?')[1] if '?' in self.driver.current_url else ''
        
        # Limpiar URL base de paginación existente (quitar /2, /3, etc.)
        url_base = re.sub(r'/\d+$', '', url_base)
        
        # Asegurar que termina en /l
        if not url_base.endswith('/l'):
            if url_base.endswith('/'):
                url_base += 'l'
            else:
                url_base += '/l'
        
        if self.modo_debug:
            print(f"[DEBUG] URL base: {url_base}")
            print(f"[DEBUG] Parámetros: {parametros}")
        
        while continuar:
            paginas_procesadas += 1
            
            if paginas is not None and paginas_procesadas > paginas:
                print(f"\n[*] Alcanzado límite de {paginas} páginas")
                break
            
            print(f"\n--- Página {paginas_procesadas} ---")
            
            # Construir URL de la página actual
            if paginas_procesadas == 1:
                url_pagina = url_base + parametros
            else:
                # Formato: /l/2, /l/3, etc.
                url_pagina = f"{url_base}/{paginas_procesadas}{parametros}"
            
            if self.modo_debug:
                print(f"[DEBUG] URL página {paginas_procesadas}: {url_pagina}")
            
            # Navegar a la página
            try:
                self._navegar_con_reintentos(url_pagina)
                time.sleep(random.uniform(2, 4))
                self.incrementar_contador_peticiones()
            except Exception as e:
                print(f"❌ Error navegando a página {paginas_procesadas}: {e}")
                break
            
            # Verificar si llegamos a una página sin resultados
            soup = BeautifulSoup(self.driver.page_source, 'html.parser')
            no_results = soup.find('h3', class_='re-SearchNoResults-title')
            if no_results and 'ooops' in no_results.text.lower():
                print(f"\n✅ Detectado final del listado (página sin resultados)")
                break
            
            # scrapear_pagina ya filtra y retorna solo particulares
            viviendas = self.scrapear_pagina()
            
            # Si no hay viviendas, probablemente llegamos al final
            if not viviendas and paginas_procesadas > 1:
                print(f"\n✅ No se encontraron más viviendas. Final del listado.")
                break
            
            todas_viviendas.extend(viviendas)
            
            print(f"[*] Total acumulado de particulares: {len(todas_viviendas)}")
            
            # Delay entre páginas
            self.delay_aleatorio('pagina')
        
        print(f"\n[RESUMEN FINAL]")
        print(f"  Páginas procesadas: {paginas_procesadas}")
        print(f"  Total particulares encontrados: {len(todas_viviendas)}")
        print("="*70)
        
        return todas_viviendas
    
    def scrapear_con_filtrado(self, paginas=None):
        """Método principal de scraping con filtrado en listado"""
        return self.filtrar_listado_particulares(paginas)
