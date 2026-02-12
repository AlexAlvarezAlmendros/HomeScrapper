"""
Scraper específico para Idealista
Hereda de BaseScraper e implementa lógica específica del portal
"""

import os
import re
import json
import time
import random
from typing import List, Optional
from datetime import datetime
from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, NoAlertPresentException, UnexpectedAlertPresentException

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
    
    @staticmethod
    def _obtener_ruta_json_persistente(ubicacion: str) -> str:
        """Devuelve la ruta del JSON persistente para una ubicación."""
        ubicacion_limpia = ubicacion.replace(' ', '_').replace('/', '-')
        return f"viviendas_idealista_{ubicacion_limpia}.json"
    
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
    def _asegurar_orden_fecha_idealista(url: str) -> str:
        """Asegura que la URL ordena por fecha de publicación descendente."""
        param = 'ordenado-por=fecha-publicacion-desc'
        if param in url:
            return url
        if '?' in url:
            return f"{url}&{param}"
        else:
            return f"{url}?{param}"
    
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
    
    def _extraer_telefono_detalle(self) -> Optional[str]:
        """
        Extrae el teléfono de la página de detalle de Idealista.
        
        Estrategia multicapa:
        1. Verificar si ya hay un enlace tel: visible
        2. Inyectar interceptores (setAttribute, href setter, XHR, fetch, MutationObserver)
        3. Hacer clic JS en el botón "Llamar"
        4. Esperar y comprobar todas las fuentes de datos
        5. Segundo clic si el primero solo prepara el botón
        6. Llamada directa a API de Idealista como último recurso
        7. Validación estricta final: nunca devolver texto sin >= 7 dígitos
        """
        telefono = None
        
        try:
            # ── Paso 1: ¿Ya hay un enlace tel: visible? ──
            try:
                tel_links = self.driver.find_elements(By.CSS_SELECTOR, "a[href^='tel:']")
                for tel_link in tel_links:
                    href = tel_link.get_attribute('href')
                    if href and href.startswith('tel:') and len(href) > 6:
                        telefono = href.replace('tel:', '').strip()
                        if self.modo_debug:
                            print(f"      [DEBUG] ✓ Teléfono ya visible: {telefono}")
                        return self._validar_telefono_final(telefono)
            except:
                pass
            
            # ── Paso 2: Buscar el botón de teléfono ──
            phone_selectors = [
                "a.phone-number._mobilePhone",
                "a.phone-number.icon-phone-outline",
                "a.phone-number.icon-phone-fill",
                "a.item-clickable-phone",
                "a.see-phones-btn",
                "button.phone-btn",
                "[data-testid='phone-btn']",
            ]
            
            phone_button = None
            for selector in phone_selectors:
                try:
                    phone_button = self.driver.find_element(By.CSS_SELECTOR, selector)
                    if self.modo_debug:
                        print(f"      [DEBUG] Botón encontrado con: {selector}")
                    break
                except NoSuchElementException:
                    continue
            
            if not phone_button:
                if self.modo_debug:
                    print("      [DEBUG] No se encontró botón de teléfono")
                return None
            
            # Scroll al botón
            self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", phone_button)
            time.sleep(0.5)
            
            # ── Paso 3: Inyectar interceptores comprehensivos ──
            self.driver.execute_script("""
                window.__capturedPhone = null;
                window.__phoneAjaxResponse = null;
                
                // A) Override setAttribute
                if (!window.__origSetAttribute) {
                    window.__origSetAttribute = Element.prototype.setAttribute;
                    Element.prototype.setAttribute = function(name, value) {
                        if (name === 'href' && value && typeof value === 'string' && value.startsWith('tel:')) {
                            window.__capturedPhone = value;
                            return;
                        }
                        return window.__origSetAttribute.call(this, name, value);
                    };
                }
                
                // B) Override href property setter
                if (!window.__hrefOverridden) {
                    window.__hrefOverridden = true;
                    var desc = Object.getOwnPropertyDescriptor(HTMLAnchorElement.prototype, 'href');
                    if (desc && desc.set) {
                        window.__origHrefSet = desc.set;
                        window.__origHrefGet = desc.get;
                        Object.defineProperty(HTMLAnchorElement.prototype, 'href', {
                            set: function(val) {
                                if (val && typeof val === 'string' && val.startsWith('tel:')) {
                                    window.__capturedPhone = val;
                                    return;
                                }
                                window.__origHrefSet.call(this, val);
                            },
                            get: function() { return window.__origHrefGet.call(this); },
                            configurable: true
                        });
                    }
                }
                
                // C) Interceptar XHR
                if (!window.__xhrIntercepted) {
                    window.__xhrIntercepted = true;
                    var OrigOpen = XMLHttpRequest.prototype.open;
                    var OrigSend = XMLHttpRequest.prototype.send;
                    XMLHttpRequest.prototype.open = function(method, url) {
                        this.__reqUrl = url;
                        return OrigOpen.apply(this, arguments);
                    };
                    XMLHttpRequest.prototype.send = function() {
                        var xhr = this;
                        this.addEventListener('load', function() {
                            if (xhr.__reqUrl) {
                                var u = xhr.__reqUrl.toLowerCase();
                                if (u.includes('phone') || u.includes('contact') || 
                                    u.includes('getphones') || u.includes('telefon')) {
                                    window.__phoneAjaxResponse = xhr.responseText;
                                }
                                if (xhr.responseText && xhr.responseText.includes('tel:')) {
                                    window.__phoneAjaxResponse = xhr.responseText;
                                }
                            }
                        });
                        return OrigSend.apply(this, arguments);
                    };
                }
                
                // D) Interceptar fetch
                if (!window.__fetchIntercepted) {
                    window.__fetchIntercepted = true;
                    var origFetch = window.fetch;
                    window.fetch = function(input, init) {
                        var url = (typeof input === 'string') ? input : (input && input.url ? input.url : '');
                        return origFetch.apply(this, arguments).then(function(response) {
                            if (url) {
                                var lower = url.toLowerCase();
                                if (lower.includes('phone') || lower.includes('contact') || 
                                    lower.includes('getphones') || lower.includes('telefon')) {
                                    response.clone().text().then(function(text) {
                                        window.__phoneAjaxResponse = text;
                                    });
                                }
                            }
                            return response;
                        });
                    };
                }
                
                // E) MutationObserver
                if (window.__telObserver) {
                    try { window.__telObserver.disconnect(); } catch(e) {}
                }
                window.__telObserver = new MutationObserver(function(mutations) {
                    mutations.forEach(function(m) {
                        if (m.type === 'attributes' && m.attributeName === 'href') {
                            var href = m.target.getAttribute('href');
                            if (href && href.startsWith('tel:')) {
                                window.__capturedPhone = href;
                                m.target.removeAttribute('href');
                            }
                        }
                        if (m.type === 'childList') {
                            m.addedNodes.forEach(function(node) {
                                if (node.nodeType !== 1) return;
                                var els = [node];
                                if (node.querySelectorAll) {
                                    els = els.concat(Array.from(node.querySelectorAll('a[href^="tel:"]')));
                                }
                                els.forEach(function(el) {
                                    if (el.tagName === 'A') {
                                        var h = el.getAttribute('href');
                                        if (h && h.startsWith('tel:')) {
                                            window.__capturedPhone = h;
                                            el.removeAttribute('href');
                                        }
                                    }
                                });
                            });
                        }
                        if (m.type === 'childList' || m.type === 'characterData') {
                            var target = m.target;
                            if (target && target.textContent) {
                                var match = target.textContent.match(/(\\+34[\\s]?[6789]\\d{2}[\\s]?\\d{3}[\\s]?\\d{3})/);
                                if (!match) match = target.textContent.match(/([6789]\\d{2}[\\s]?\\d{2}[\\s]?\\d{2}[\\s]?\\d{2})/);
                                if (match && !window.__capturedPhone) {
                                    window.__capturedPhone = 'tel:' + match[1];
                                }
                            }
                        }
                    });
                });
                window.__telObserver.observe(document.body, {
                    attributes: true, childList: true, subtree: true,
                    characterData: true, attributeFilter: ['href']
                });
                
                // F) Click interceptor
                if (window.__telClickHandler) {
                    document.removeEventListener('click', window.__telClickHandler, true);
                }
                window.__telClickHandler = function(e) {
                    var a = e.target.closest ? e.target.closest('a') : e.target;
                    if (a && a.getAttribute) {
                        var href = a.getAttribute('href');
                        if (href && href.startsWith('tel:')) {
                            window.__capturedPhone = href;
                            e.preventDefault();
                            e.stopPropagation();
                            e.stopImmediatePropagation();
                            a.removeAttribute('href');
                        }
                    }
                };
                document.addEventListener('click', window.__telClickHandler, true);
            """)
            
            if self.modo_debug:
                print("      [DEBUG] Interceptores inyectados, haciendo clic...")
            
            # ── Paso 4: Primer clic ──
            telefono = self._hacer_clic_y_capturar(phone_button)
            
            # ── Paso 5: Segundo clic si necesario ──
            if not telefono:
                if self.modo_debug:
                    print("      [DEBUG] Primer clic sin resultado, intentando segundo clic...")
                time.sleep(1)
                phone_button2 = None
                for selector in phone_selectors:
                    try:
                        phone_button2 = self.driver.find_element(By.CSS_SELECTOR, selector)
                        break
                    except NoSuchElementException:
                        continue
                if phone_button2:
                    telefono = self._hacer_clic_y_capturar(phone_button2)
            
            # ── Paso 6: API directa ──
            if not telefono:
                telefono = self._intentar_api_telefono_directa()
            
            # Limpieza
            try:
                self.driver.execute_script("""
                    if (window.__telObserver) window.__telObserver.disconnect();
                    if (window.__telClickHandler) document.removeEventListener('click', window.__telClickHandler, true);
                    if (window.__origSetAttribute) { Element.prototype.setAttribute = window.__origSetAttribute; window.__origSetAttribute = null; }
                    if (window.__origHrefSet) {
                        Object.defineProperty(HTMLAnchorElement.prototype, 'href', { set: window.__origHrefSet, get: window.__origHrefGet, configurable: true });
                        window.__origHrefSet = null;
                    }
                """)
            except:
                pass
                    
        except UnexpectedAlertPresentException:
            try:
                alert = self.driver.switch_to.alert
                alert_text = alert.text
                alert.accept()
                telefono = self._extraer_telefono_de_texto(alert_text)
                if self.modo_debug and telefono:
                    print(f"      [DEBUG] ✓ Teléfono del alert inesperado: {telefono}")
            except:
                pass
                
        except Exception as e:
            if self.modo_debug:
                print(f"      [DEBUG] Error extrayendo teléfono: {e}")
        
        return self._validar_telefono_final(telefono)
    
    def _hacer_clic_y_capturar(self, phone_button) -> Optional[str]:
        """Hace clic en el botón de teléfono y comprueba todas las fuentes de captura."""
        try:
            self.driver.execute_script("""
                var btn = arguments[0];
                var rect = btn.getBoundingClientRect();
                var x = rect.left + rect.width / 2;
                var y = rect.top + rect.height / 2;
                ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click'].forEach(function(type) {
                    var evt = new MouseEvent(type, {
                        bubbles: true, cancelable: true, view: window,
                        clientX: x, clientY: y, button: 0, buttons: 1
                    });
                    btn.dispatchEvent(evt);
                });
            """, phone_button)
        except UnexpectedAlertPresentException:
            try:
                alert = self.driver.switch_to.alert
                alert_text = alert.text
                alert.accept()
                telefono = self._extraer_telefono_de_texto(alert_text)
                if telefono:
                    return telefono
            except:
                pass
        except Exception as e:
            if self.modo_debug:
                print(f"      [DEBUG] Error en clic: {e}")
        
        for intento in range(8):
            time.sleep(0.5)
            
            captured = self.driver.execute_script("return window.__capturedPhone;")
            if captured:
                telefono = captured.replace('tel:', '').strip()
                if self.modo_debug:
                    print(f"      [DEBUG] ✓ Teléfono capturado por interceptor: {telefono}")
                return self._validar_telefono_final(telefono)
            
            ajax_resp = self.driver.execute_script("return window.__phoneAjaxResponse;")
            if ajax_resp:
                telefono = self._extraer_telefono_de_texto(ajax_resp)
                if telefono:
                    if self.modo_debug:
                        print(f"      [DEBUG] ✓ Teléfono del AJAX: {telefono}")
                    return telefono
            
            try:
                tel_links = self.driver.find_elements(By.CSS_SELECTOR, "a[href^='tel:']")
                for tl in tel_links:
                    href = tl.get_attribute('href')
                    if href and href.startswith('tel:') and len(href) > 6:
                        telefono = href.replace('tel:', '').strip()
                        if self.modo_debug:
                            print(f"      [DEBUG] ✓ Teléfono del href DOM: {telefono}")
                        return self._validar_telefono_final(telefono)
            except:
                pass
            
            if intento >= 3:
                try:
                    phone_text = self.driver.execute_script("""
                        var selectors = ['span.hidden-contact-phones_text', '.phone-number span',
                            '.see-phones-btn span', '.phone-details span', 'a.phone-number'];
                        for (var i = 0; i < selectors.length; i++) {
                            var els = document.querySelectorAll(selectors[i]);
                            for (var j = 0; j < els.length; j++) {
                                var text = els[j].textContent.trim();
                                var digits = text.replace(/[^0-9]/g, '');
                                if (digits.length >= 7) return text;
                            }
                        }
                        return null;
                    """)
                    if phone_text:
                        telefono = self._extraer_telefono_de_texto(phone_text)
                        if telefono:
                            if self.modo_debug:
                                print(f"      [DEBUG] ✓ Teléfono del texto visible: {telefono}")
                            return telefono
                except:
                    pass
        
        if self.modo_debug:
            print("      [DEBUG] No se pudo capturar teléfono tras clic")
        return None
    
    def _intentar_api_telefono_directa(self) -> Optional[str]:
        """Intenta obtener el teléfono directamente de la API de Idealista."""
        try:
            current_url = self.driver.current_url
            id_match = re.search(r'/inmueble/(\d+)', current_url)
            if not id_match:
                id_match = re.search(r'/(\d{6,})/', current_url)
            if not id_match:
                return None
            
            prop_id = id_match.group(1)
            if self.modo_debug:
                print(f"      [DEBUG] Intentando API directa para inmueble {prop_id}...")
            
            phone_response = self.driver.execute_script("""
                var id = arguments[0];
                var endpoints = [
                    '/es/ajax/ads/' + id + '/contact/phones',
                    '/ajax/listingController/phoneAction.ajax?adId=' + id,
                    '/ajax/ads/' + id + '/phones',
                    '/es/ajax/listingController/phoneAction.ajax?adId=' + id
                ];
                for (var i = 0; i < endpoints.length; i++) {
                    try {
                        var xhr = new XMLHttpRequest();
                        xhr.open('GET', endpoints[i], false);
                        xhr.setRequestHeader('X-Requested-With', 'XMLHttpRequest');
                        xhr.send();
                        if (xhr.status === 200 && xhr.responseText && xhr.responseText.length > 2) {
                            return {url: endpoints[i], status: xhr.status, body: xhr.responseText};
                        }
                    } catch(e) {}
                    try {
                        var xhr2 = new XMLHttpRequest();
                        xhr2.open('POST', endpoints[i], false);
                        xhr2.setRequestHeader('X-Requested-With', 'XMLHttpRequest');
                        xhr2.setRequestHeader('Content-Type', 'application/x-www-form-urlencoded');
                        xhr2.send();
                        if (xhr2.status === 200 && xhr2.responseText && xhr2.responseText.length > 2) {
                            return {url: endpoints[i], status: xhr2.status, body: xhr2.responseText};
                        }
                    } catch(e) {}
                }
                return null;
            """, prop_id)
            
            if phone_response and phone_response.get('body'):
                body = phone_response['body']
                if self.modo_debug:
                    print(f"      [DEBUG] API respondió: {body[:200]}")
                telefono = self._extraer_telefono_de_texto(body)
                if telefono:
                    return telefono
                try:
                    import json
                    data = json.loads(body)
                    return self._buscar_telefono_en_json(data)
                except:
                    pass
        except Exception as e:
            if self.modo_debug:
                print(f"      [DEBUG] Error en API directa: {e}")
        return None
    
    def _buscar_telefono_en_json(self, data) -> Optional[str]:
        """Busca recursivamente un teléfono en una estructura JSON."""
        if isinstance(data, str):
            return self._extraer_telefono_de_texto(data)
        elif isinstance(data, dict):
            for key, value in data.items():
                key_lower = key.lower()
                if 'phone' in key_lower or 'telefon' in key_lower or 'tel' == key_lower or 'mobile' in key_lower:
                    if isinstance(value, str):
                        telefono = self._extraer_telefono_de_texto(value)
                        if not telefono:
                            digitos = re.sub(r'[^\d]', '', value)
                            if len(digitos) >= 7:
                                return value.strip()
                        return telefono
                result = self._buscar_telefono_en_json(value)
                if result:
                    return result
        elif isinstance(data, list):
            for item in data:
                result = self._buscar_telefono_en_json(item)
                if result:
                    return result
        return None
    
    def _validar_telefono_final(self, telefono: Optional[str]) -> Optional[str]:
        """Validación estricta: nunca devolver texto sin al menos 7 dígitos."""
        if not telefono:
            return None
        digitos = re.sub(r'[^\d]', '', telefono)
        if len(digitos) < 7:
            if self.modo_debug:
                print(f"      [DEBUG] ✗ Rechazado (no es teléfono): '{telefono}' ({len(digitos)} dígitos)")
            return None
        return telefono
    
    def _extraer_telefono_de_texto(self, texto: str) -> Optional[str]:
        """Extrae un número de teléfono de un texto usando regex"""
        if not texto:
            return None
        phone_patterns = [
            r'\+34[\s]?[6789]\d{2}[\s]?\d{3}[\s]?\d{3}',
            r'[6789]\d{2}[\s]?\d{2}[\s]?\d{2}[\s]?\d{2}',
            r'[6789]\d{2}[\s]?\d{3}[\s]?\d{3}',
            r'\d{3}[\s]?\d{3}[\s]?\d{3}',
            r'\d{9}',
        ]
        for pattern in phone_patterns:
            match = re.search(pattern, texto)
            if match:
                return match.group(0).strip()
        return None
    
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
            telefono = self._extraer_telefono_detalle()
            
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
    
    def filtrar_listado_particulares(self, paginas=None, urls_conocidas=None):
        """Filtra viviendas de particulares usando utag_data del HTML.
        
        Extrae la variable JavaScript utag_data que contiene datos estructurados
        de todos los anuncios, incluyendo owner.type:
          - type "1" = Particular/Propietario
          - type "2" = Profesional (Agencia/Banco)
        
        Si urls_conocidas contiene URLs, se detiene al encontrar un anuncio ya conocido
        (el listado se asume ordenado por fecha descendente).
        """
        if not self.driver:
            print("[ERROR] Driver no inicializado")
            return []
        
        print(f"\n🔍 [FILTRADO POR utag_data]")
        print("="*70)
        
        if paginas is None:
            print("    Modo: TODAS LAS PÁGINAS (hasta detectar el final)")
        else:
            print(f"    Modo: {paginas} página(s)")
        
        if urls_conocidas:
            print(f"    📂 URLs ya conocidas: {len(urls_conocidas)} (se parará al encontrar una)")
        
        particulares = []
        pagina_actual = 1
        primer_articulo_id = None
        urls_primera_pagina = set()
        encontrado_conocido = False
        
        # Limpiar URL base: quitar parámetros, extensión .htm y paginación existente
        url_base = self.driver.current_url.split('?')[0]
        parametros = '?' + self.driver.current_url.split('?')[1] if '?' in self.driver.current_url else ''
        
        # Detectar si es URL de tipo "areas" (formato diferente de paginación)
        es_url_areas = '/areas/' in url_base
        
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
                if es_url_areas:
                    url_pagina = f"{url_base}/pagina-{pagina_actual}{parametros}"
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
                if re.search(r'pagina-1(\?|$|\.htm)', url_actual):
                    print(f"\n✅ Detectado final del listado (redirigió a página-1)")
                    break
                
                pagina_en_url = re.search(r'pagina-(\d+)', url_actual)
                if pagina_en_url:
                    numero_en_url = int(pagina_en_url.group(1))
                    if numero_en_url < pagina_actual:
                        print(f"\n✅ Detectado final del listado (URL muestra página {numero_en_url}, esperábamos {pagina_actual})")
                        break
                else:
                    print(f"\n✅ Detectado final del listado (URL sin paginación, redirigido desde página {pagina_actual})")
                    break
            
            # Scroll para cargar contenido
            for i in range(5):
                self.driver.execute_script(f"window.scrollTo(0, {300 * (i + 1)});")
                time.sleep(random.uniform(0.3, 0.8))
            time.sleep(random.uniform(1, 2))
            
            # Parsear HTML
            soup = BeautifulSoup(self.driver.page_source, 'html.parser')
            
            # Buscar artículos para comprobar que la página cargó
            articulos = soup.find_all('article', class_='item')
            
            if not articulos:
                print("[!] No se encontraron artículos - recargando página...")
                time.sleep(random.uniform(2, 4))
                self.driver.refresh()
                time.sleep(random.uniform(3, 5))
                
                for i in range(5):
                    self.driver.execute_script(f"window.scrollTo(0, {300 * (i + 1)});")
                    time.sleep(random.uniform(0.3, 0.8))
                time.sleep(random.uniform(1, 2))
                
                soup = BeautifulSoup(self.driver.page_source, 'html.parser')
                articulos = soup.find_all('article', class_='item')
                
                if not articulos:
                    print("    ⚠️  Sigue sin artículos tras recargar")
                    print("    📁 Verifica el navegador manualmente (posible captcha/bloqueo)")
                    respuesta = input("    ¿Reintentar? (s/n, Enter=s): ").strip().lower()
                    if respuesta != 'n':
                        print("    🔄 Reintentando...")
                        continue
                    else:
                        print("    ⏭️  Saltando a la siguiente URL...")
                        break
                else:
                    print(f"    ✅ Recarga exitosa, {len(articulos)} artículos encontrados")
            
            # Extraer URLs de artículos actuales para detectar fin de listado
            urls_articulos_actuales = set()
            for art in articulos:
                link = art.find('a', class_='item-link')
                if link:
                    url_art = link.get('href', '')
                    if url_art:
                        urls_articulos_actuales.add(url_art)
            
            # Detectar fin de listado comparando con página 1
            primer_articulo_actual = articulos[0].get('data-element-id') if articulos else None
            
            if pagina_actual == 1:
                primer_articulo_id = primer_articulo_actual
                urls_primera_pagina = urls_articulos_actuales.copy()
            elif pagina_actual > 1:
                if primer_articulo_actual and primer_articulo_actual == primer_articulo_id:
                    print(f"\n✅ Detectado final del listado (primer artículo repetido)")
                    break
                
                if urls_primera_pagina and urls_articulos_actuales:
                    coincidentes = len(urls_articulos_actuales.intersection(urls_primera_pagina))
                    porcentaje = (coincidentes / len(urls_articulos_actuales)) * 100
                    if porcentaje >= 80:
                        print(f"\n✅ Detectado final del listado ({porcentaje:.0f}% artículos coinciden con página 1)")
                        break
            
            # ============================================================
            # EXTRAER utag_data: datos estructurados con owner.type
            # ============================================================
            script_tag = soup.find('script', string=re.compile(r'var\s+utag_data\s*='))
            
            if not script_tag:
                print("    ⚠️  No se encontró utag_data, usando método fallback (logo-branding)")
                # Fallback: método antiguo con logo
                particulares_en_pagina = self._filtrar_por_logo(articulos, urls_conocidas)
                if particulares_en_pagina is None:
                    encontrado_conocido = True
                    break
                particulares.extend(particulares_en_pagina)
                print(f"✅ Particulares en esta página (fallback): {len(particulares_en_pagina)}")
                pagina_actual += 1
                continue
            
            # Extraer el JSON de utag_data
            try:
                script_text = script_tag.string
                match = re.search(r'utag_data\s*=\s*(\{.*?\})\s*;', script_text, re.DOTALL)
                if not match:
                    print("    ⚠️  No se pudo parsear utag_data")
                    pagina_actual += 1
                    continue
                
                json_str = match.group(1)
                data = json.loads(json_str)
            except (json.JSONDecodeError, AttributeError) as e:
                print(f"    ⚠️  Error parseando utag_data: {e}")
                pagina_actual += 1
                continue
            
            # Extraer anuncios del listado
            ads = data.get('list', {}).get('ads', [])
            
            if not ads:
                print(f"    📊 utag_data encontrado pero sin anuncios en list.ads")
                if self.modo_debug:
                    keys = list(data.keys())
                    print(f"      [DEBUG] Claves disponibles en utag_data: {keys[:10]}")
                pagina_actual += 1
                continue
            
            # Crear un índice de artículos HTML por data-element-id para extraer datos visuales
            articulos_por_id = {}
            for art in articulos:
                art_id = art.get('data-element-id')
                if art_id:
                    articulos_por_id[art_id] = art
            
            print(f"📊 Total artículos: {len(articulos)} | utag_data ads: {len(ads)}")
            
            # Identificar IDs de particulares con utag_data
            ids_particulares_pagina = set()
            particulares_en_pagina = 0
            profesionales_en_pagina = 0
            
            for ad in ads:
                ad_id = str(ad.get('adId', ''))
                owner_type = ad.get('owner', {}).get('type', '')
                
                # Construir URL del anuncio
                url_detalle = f"https://www.idealista.com/inmueble/{ad_id}/"
                
                # Comprobar si ya conocido
                if urls_conocidas and url_detalle in urls_conocidas:
                    print(f"\n🛑 Anuncio ya conocido: {url_detalle}")
                    print("    Deteniendo búsqueda (los siguientes ya están registrados)")
                    encontrado_conocido = True
                    break
                
                if owner_type == "1":
                    ids_particulares_pagina.add(ad_id)
                    
                    # Extraer datos del HTML del listado
                    art_html = articulos_por_id.get(ad_id)
                    
                    if art_html:
                        # Título
                        link = art_html.find('a', class_='item-link')
                        titulo = link.get('title', 'Sin título') if link else 'Sin título'
                        
                        # Precio
                        precio_elem = art_html.find('span', class_='item-price')
                        precio = precio_elem.get_text(strip=True) if precio_elem else 'N/A'
                        
                        # Habitaciones y metros desde item-detail
                        habitaciones = None
                        metros = None
                        detalles = art_html.find_all('span', class_='item-detail')
                        for detalle in detalles:
                            texto = detalle.get_text(strip=True)
                            if 'hab.' in texto:
                                habitaciones = texto
                            elif 'm²' in texto:
                                metros = texto
                        
                        # Descripción
                        desc_elem = art_html.find('div', class_='item-description')
                        descripcion = desc_elem.get_text(strip=True) if desc_elem else None
                        
                        # Ubicación (del título, tras la coma: "Piso en X, UBICACION")
                        ubicacion = ''
                        if titulo and ',' in titulo:
                            # "Piso en Calle de Sants, Sants - Badal, Barcelona" -> "Sants - Badal, Barcelona"
                            partes = titulo.split(',', 1)
                            ubicacion = partes[1].strip() if len(partes) > 1 else ''
                    else:
                        # Fallback: datos mínimos de utag_data
                        titulo = ad.get('title', 'Sin título')
                        precio_val = ad.get('price', 'N/A')
                        precio = f"{precio_val:,.0f}€".replace(',', '.') if isinstance(precio_val, (int, float)) else str(precio_val)
                        hab_val = ad.get('rooms', None)
                        met_val = ad.get('size', None)
                        habitaciones = f"{hab_val} hab." if hab_val else None
                        metros = f"{met_val} m²" if met_val else None
                        ubicacion = ad.get('address', ad.get('neighborhood', ''))
                        descripcion = ad.get('description', None)
                    
                    particulares.append({
                        'id': ad_id,
                        'url': url_detalle,
                        'titulo': titulo,
                        'precio': precio,
                        'habitaciones': habitaciones,
                        'metros': metros,
                        'ubicacion': ubicacion,
                        'descripcion': descripcion,
                    })
                    
                    particulares_en_pagina += 1
                    
                    if self.modo_debug:
                        print(f"      [DEBUG] ✓ PARTICULAR: ID {ad_id} - {titulo[:50]}")
                else:
                    profesionales_en_pagina += 1
                    if self.modo_debug:
                        print(f"      [DEBUG] ✗ Profesional: ID {ad_id} (owner.type={owner_type})")
            
            if encontrado_conocido:
                break
            
            print(f"✅ Particulares: {particulares_en_pagina} | Profesionales: {profesionales_en_pagina}")
            
            # Extraer teléfonos de los particulares en esta página
            if particulares_en_pagina > 0:
                ids_particulares_pagina = [p['id'] for p in particulares[-particulares_en_pagina:]]
                telefonos = self._extraer_telefonos_listado(ids_particulares_pagina)
                
                # Asignar teléfonos a los particulares
                for p in particulares[-particulares_en_pagina:]:
                    p['telefono'] = telefonos.get(p['id'], None)
            
            pagina_actual += 1
        
        print(f"\n{'='*70}")
        print(f"[RESUMEN]")
        print(f"  Páginas procesadas: {pagina_actual}")
        print(f"  Particulares encontrados: {len(particulares)}")
        if encontrado_conocido:
            print(f"  🛑 Se detuvo al encontrar un anuncio ya registrado")
        print(f"{'='*70}")
        
        if not particulares:
            if urls_conocidas:
                print("\n✅ No hay viviendas nuevas desde la última búsqueda")
            else:
                print("\n[!] No se encontraron particulares en el listado")
            return []
        
        # Construir objetos Vivienda directamente (sin visitar páginas de detalle)
        print(f"\n📋 Construyendo {len(particulares)} registros de particulares...")
        todas_viviendas = []
        
        for info in particulares:
            telefono = info.get('telefono')
            vivienda = Vivienda(
                titulo=info['titulo'],
                precio=info['precio'],
                ubicacion=info.get('ubicacion', ''),
                habitaciones=info.get('habitaciones'),
                metros=info.get('metros'),
                url=info['url'],
                descripcion=info.get('descripcion'),
                anunciante="Particular",
                fecha_scraping=datetime.now().isoformat(),
                portal="Idealista",
                telefono=telefono
            )
            todas_viviendas.append(vivienda)
            
            print(f"    ✅ {info['titulo'][:50]}... | 💰 {info['precio']} | 📞 {telefono or 'N/A'}")
        
        print("\n" + "="*70)
        print("📊 RESUMEN FINAL")
        print("="*70)
        print(f"Particulares encontrados:  {len(todas_viviendas)}")
        con_telefono = sum(1 for v in todas_viviendas if v.telefono)
        print(f"Con teléfono extraído:     {con_telefono}")
        
        return todas_viviendas
    
    def _extraer_telefonos_listado(self, ids_particulares: list) -> dict:
        """Extrae teléfonos haciendo clic en 'Ver teléfono' de cada particular en el listado.
        
        Retorna dict {ad_id: telefono_str}
        """
        telefonos = {}
        
        for ad_id in ids_particulares:
            try:
                # Buscar el article con este ID
                article_selector = f'article[data-element-id="{ad_id}"]'
                article = self.driver.find_elements(By.CSS_SELECTOR, article_selector)
                
                if not article:
                    if self.modo_debug:
                        print(f"      [DEBUG] No se encontró article para ID {ad_id}")
                    continue
                
                article = article[0]
                
                # Buscar el botón "Ver teléfono" dentro del article
                phone_btn = article.find_elements(By.CSS_SELECTOR, 'button.see-phones-btn')
                
                if not phone_btn:
                    # Intentar selector alternativo
                    phone_btn = article.find_elements(By.CSS_SELECTOR, 'button.phone-btn')
                
                if not phone_btn:
                    if self.modo_debug:
                        print(f"      [DEBUG] No se encontró botón teléfono para ID {ad_id}")
                    continue
                
                # Scroll al artículo para que sea visible
                self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", article)
                time.sleep(random.uniform(0.3, 0.6))
                
                # Hacer clic en "Ver teléfono"
                phone_btn[0].click()
                time.sleep(random.uniform(0.8, 1.5))
                
                # Leer el teléfono revelado
                phone_text = article.find_elements(By.CSS_SELECTOR, '.hidden-contact-phones_text')
                
                for elem in phone_text:
                    texto = elem.text.strip()
                    # Verificar que es un número de teléfono (contiene dígitos)
                    if texto and any(c.isdigit() for c in texto):
                        telefonos[ad_id] = texto
                        if self.modo_debug:
                            print(f"      [DEBUG] 📞 ID {ad_id}: {texto}")
                        break
                
                # Pequeña pausa entre clics
                time.sleep(random.uniform(0.3, 0.8))
                
            except Exception as e:
                if self.modo_debug:
                    print(f"      [DEBUG] Error extrayendo teléfono de {ad_id}: {e}")
        
        print(f"    📞 Teléfonos extraídos: {len(telefonos)}/{len(ids_particulares)}")
        return telefonos
    
    def _filtrar_por_logo(self, articulos, urls_conocidas=None):
        """Método fallback: filtra por ausencia de logo-branding.
        Retorna lista de particulares o None si se encontró uno conocido."""
        resultado = []
        for articulo in articulos:
            tiene_logo = articulo.find('picture', class_='logo-branding')
            if not tiene_logo:
                element_id = articulo.get('data-element-id')
                link = articulo.find('a', class_='item-link')
                if element_id and link:
                    url_detalle = link.get('href', '')
                    if url_detalle and not url_detalle.startswith('http'):
                        url_detalle = "https://www.idealista.com" + url_detalle
                    if urls_conocidas and url_detalle in urls_conocidas:
                        return None  # Señal de que se encontró conocido
                    titulo = link.get('title', 'Sin título')
                    resultado.append({
                        'id': element_id,
                        'url': url_detalle,
                        'titulo': titulo,
                    })
        return resultado
    
    def scrapear_con_filtrado(self, paginas=None, ubicacion=None):
        """Método principal de scraping con filtrado de dos etapas.
        
        Si ubicacion se proporciona, carga el JSON persistente y para al encontrar
        un anuncio ya conocido.
        """
        urls_conocidas = set()
        if ubicacion:
            ruta_json = self._obtener_ruta_json_persistente(ubicacion)
            json_existente = self._cargar_json_existente(ruta_json)
            urls_conocidas = json_existente['urls_conocidas']
            if not urls_conocidas:
                print("    📋 No hay datos previos, se hará búsqueda completa")
        
        return self.filtrar_listado_particulares(paginas, urls_conocidas=urls_conocidas)


def cargar_urls_idealista(config_file: str = "config.json") -> list:
    """Carga las URLs de Idealista desde config.json"""
    try:
        with open(config_file, 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        if 'idealista' in config and 'urls' in config['idealista']:
            return config['idealista']['urls']
        return []
    except:
        return []


def main():
    print("""
    ╔══════════════════════════════════════════════════════╗
    ║     IDEALISTA SCRAPER - Selenium                     ║
    ║     Usando Chrome en modo debug                      ║
    ╚══════════════════════════════════════════════════════╝
    """)
    
    # Modo debug
    print("[?] ¿Activar modo DEBUG?")
    debug = input("    s/n (Enter = no): ").strip().lower() == 's'
    
    # Cargar URLs de config
    urls_config = cargar_urls_idealista()
    urls_a_procesar = []  # Lista de {'url': ..., 'nombre': ...}
    
    # Modo no interactivo por argumentos
    import sys
    if len(sys.argv) > 1:
        # Uso: python idealista_scraper.py [indice] [paginas]
        # Ej: python idealista_scraper.py 1 3   (primera URL, 3 páginas)
        idx = int(sys.argv[1]) - 1
        paginas = int(sys.argv[2]) if len(sys.argv) > 2 else 3
        debug = "--debug" in sys.argv or "-d" in sys.argv
        
        if urls_config and 0 <= idx < len(urls_config):
            item = urls_config[idx]
            urls_a_procesar = [{'url': IdealistaScraper._asegurar_orden_fecha_idealista(item['url']), 'nombre': item.get('nombre', 'Sin nombre')}]
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
            url = input("\nIntroduce la URL de Idealista: ").strip()
            nombre = input("Nombre/ubicación para esta búsqueda: ").strip() or "Manual"
            urls_a_procesar = [{'url': url, 'nombre': nombre}]
    else:
        url = input("\nIntroduce la URL de Idealista: ").strip()
        nombre = input("Nombre/ubicación para esta búsqueda: ").strip() or "Manual"
        urls_a_procesar = [{'url': url, 'nombre': nombre}]
    
    # Número de páginas
    print("\n[?] ¿Cuántas páginas por búsqueda?")
    num_input = input("    (Enter = todas): ").strip()
    paginas = None if not num_input or num_input.lower() == 'todas' else int(num_input)
    
    # Crear scraper (se conectará al Chrome en modo debug)
    scraper = IdealistaScraper(modo_debug=debug)
    
    if not scraper.conectar_chrome():
        print("\n[!] No se pudo conectar al Chrome.")
        print("    Asegúrate de ejecutar primero: ./start_chrome_debug.sh")
        return
    
    try:
        for i, item in enumerate(urls_a_procesar, 1):
            url = IdealistaScraper._asegurar_orden_fecha_idealista(item['url'])
            nombre = item['nombre']
            
            # Actualizar la URL de búsqueda del scraper
            scraper.search_url = url
            
            print(f"\n\n{'='*70}")
            print(f"  PROCESANDO: {nombre} ({i}/{len(urls_a_procesar)})")
            print(f"  📅 Ordenado por fecha de publicación (más recientes primero)")
            print(f"{'='*70}")
            
            # Navegar primero a la URL antes de scrapear
            print(f"\n[*] Navegando a: {url[:80]}...")
            scraper._navegar_con_reintentos(url)
            time.sleep(random.uniform(2, 4))
            
            # Verificar si hay captcha
            scraper.detectar_captcha()
            
            viviendas = scraper.scrapear_con_filtrado(paginas, ubicacion=nombre)
            
            # Guardar resultados de esta URL
            if viviendas:
                ruta_json = scraper._obtener_ruta_json_persistente(nombre)
                scraper.guardar(viviendas, ruta_json, ubicacion=nombre, url_scrapeada=url)
            else:
                print(f"\n⚠️  No se encontraron viviendas nuevas de particulares en {nombre}")
                # Subir JSON existente a la API igualmente
                ruta_json = scraper._obtener_ruta_json_persistente(nombre)
                if os.path.exists(ruta_json):
                    try:
                        with open(ruta_json, 'r', encoding='utf-8') as f:
                            data_existente = json.load(f)
                        print(f"☁️  Subiendo JSON existente ({data_existente.get('total', 0)} registros) a la API...")
                        BaseScraper.subir_a_api(data_existente)
                    except Exception as e:
                        print(f"⚠️  Error al leer JSON existente para subir: {e}")
            
            if i < len(urls_a_procesar):
                print("\n⏳ Esperando antes de la siguiente URL...")
                time.sleep(random.uniform(10, 20))
        
    except KeyboardInterrupt:
        print("\n\n[!] Scraping interrumpido por el usuario")
    except Exception as e:
        print(f"\n[ERROR] {e}")
    
    print("\n✅ Scraping completado")
    input("\nPresiona Enter para salir...")


if __name__ == "__main__":
    main()
