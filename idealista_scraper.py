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
        """Filtra viviendas que NO tienen logo de inmobiliaria en el listado.
        
        Si urls_conocidas contiene URLs, se detiene al encontrar un anuncio ya conocido
        (el listado se asume ordenado por fecha descendente).
        """
        if not self.driver:
            print("[ERROR] Driver no inicializado")
            return []
        
        print(f"\n🔍 [ETAPA 1: FILTRADO EN LISTADO]")
        print("="*70)
        
        if paginas is None:
            print("    Modo: TODAS LAS PÁGINAS (hasta detectar el final)")
        else:
            print(f"    Modo: {paginas} página(s)")
        
        if urls_conocidas:
            print(f"    📂 URLs ya conocidas: {len(urls_conocidas)} (se parará al encontrar una)")
        
        posibles_particulares = []
        pagina_actual = 1
        articulos_vistos_ids = set()
        primer_articulo_id = None
        urls_primera_pagina = set()
        encontrado_conocido = False
        
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
                if re.search(r'pagina-1(\?|$|\.htm)', url_actual):
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
                else:
                    # Si estamos en página > 1 pero la URL no tiene /pagina-X, nos redirigieron a la primera
                    # Esto ocurre cuando Idealista redirige páginas inexistentes a la URL base
                    print(f"\n✅ Detectado final del listado (URL sin paginación, redirigido desde página {pagina_actual})")
                    if self.modo_debug:
                        print(f"      [DEBUG] URL actual: {url_actual}")
                        print(f"      [DEBUG] URL esperada contenía: pagina-{pagina_actual}")
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
            
            # Obtener el ID del primer artículo y las URLs de todos los artículos
            primer_articulo_actual = articulos[0].get('data-element-id') if articulos else None
            
            # Extraer URLs de artículos actuales para comparación
            urls_articulos_actuales = set()
            for art in articulos:
                link = art.find('a', class_='item-link')
                if link:
                    url_art = link.get('href', '')
                    if url_art:
                        urls_articulos_actuales.add(url_art)
            
            # VERIFICACIÓN CRÍTICA: Si el primer artículo coincide con el de la página 1, volvimos al inicio
            if pagina_actual == 1:
                primer_articulo_id = primer_articulo_actual
                urls_primera_pagina = urls_articulos_actuales.copy()
                if self.modo_debug:
                    print(f"      [DEBUG] Primer artículo de página 1: {primer_articulo_id}")
                    print(f"      [DEBUG] URLs guardadas de página 1: {len(urls_primera_pagina)}")
            elif pagina_actual > 1:
                # Verificar si el primer artículo es el mismo que la página 1
                if primer_articulo_actual and primer_articulo_actual == primer_articulo_id:
                    print(f"\n✅ Detectado final del listado (primer artículo repetido: {primer_articulo_actual})")
                    print(f"    → La página {pagina_actual} muestra los mismos resultados que la página 1")
                    break
                
                # Verificación adicional: comparar URLs de artículos
                # Si más del 80% de las URLs coinciden con la página 1, es una redirección
                if urls_primera_pagina and urls_articulos_actuales:
                    coincidentes = len(urls_articulos_actuales.intersection(urls_primera_pagina))
                    porcentaje_coincidencia = (coincidentes / len(urls_articulos_actuales)) * 100 if urls_articulos_actuales else 0
                    
                    if self.modo_debug:
                        print(f"      [DEBUG] URLs coincidentes con página 1: {coincidentes}/{len(urls_articulos_actuales)} ({porcentaje_coincidencia:.1f}%)")
                    
                    if porcentaje_coincidencia >= 80:
                        print(f"\n✅ Detectado final del listado (redirección detectada)")
                        print(f"    → {coincidentes}/{len(urls_articulos_actuales)} artículos ({porcentaje_coincidencia:.1f}%) coinciden con página 1")
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
                        
                        # Comprobar si este anuncio ya está en el JSON
                        if urls_conocidas and url_detalle in urls_conocidas:
                            print(f"\n🛑 Anuncio ya conocido encontrado: {url_detalle[:60]}...")
                            print("    Deteniendo búsqueda (los siguientes ya están registrados)")
                            encontrado_conocido = True
                            break
                        
                        titulo = link.get('title', 'Sin título')
                        
                        posibles_particulares.append({
                            'id': element_id,
                            'url': url_detalle,
                            'titulo': titulo
                        })
                        
                        posibles_en_esta_pagina += 1
                        
                        if self.modo_debug:
                            print(f"      [DEBUG] ✓ Posible particular: ID {element_id} - {titulo[:50]}")
            
            if encontrado_conocido:
                break
            
            print(f"✅ Posibles particulares en esta página: {posibles_en_esta_pagina}")
            
            # Incrementar contador
            pagina_actual += 1
        
        print(f"\n{'='*70}")
        print(f"[RESUMEN ETAPA 1]")
        print(f"  Páginas procesadas: {pagina_actual}")
        print(f"  Posibles particulares nuevos: {len(posibles_particulares)}")
        if encontrado_conocido:
            print(f"  🛑 Se detuvo al encontrar un anuncio ya registrado")
        print(f"{'='*70}")
        
        if not posibles_particulares:
            if urls_conocidas:
                print("\n✅ No hay viviendas nuevas desde la última búsqueda")
            else:
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
