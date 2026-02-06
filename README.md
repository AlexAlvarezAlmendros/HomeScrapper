# HomeScraper - Multi-Portal Property Scraper

Web scraper **escalable** para múltiples portales inmobiliarios, con enfoque especial en detectar y filtrar anuncios de **particulares** (propietarios directos) vs inmobiliarias/profesionales.

## 🌟 Portales Soportados

✅ **Idealista** - Portal líder en España  
✅ **Fotocasa** - Portal de clasificados inmobiliarios  
🔜 **Fácilmente extensible** a nuevos portales (Pisos.com, Habitaclia, etc.)

## 🚀 Características Principales

- **🔌 Arquitectura Multi-Portal**: Sistema escalable basado en Factory Pattern
- **🎯 Filtrado de dos etapas**: Identifica particulares en listado y verifica en detalle
- **♾️ Detección automática de páginas**: Procesa todas las páginas disponibles
- **📊 Extracción completa de datos**: Título, precio, ubicación, habitaciones, m², descripción
- **🛡️ Método CDP**: Conexión a Chrome en modo debug para evitar detección
- **🔄 Rotación de IP**: Soporte para cambio automático de VPN (NordVPN, Windscribe, etc.)
- **🤖 Anti-detección**: Delays aleatorios, pausas inteligentes, manejo de captchas

## 📁 Estructura del Proyecto

### Scrapers Core

- **`HomeScraper.py`** ⭐ - Script principal con menú interactivo multi-portal
- **`base_scraper.py`** - Clase base abstracta con funcionalidad común
- **`idealista_scraper.py`** - Scraper específico para Idealista
- **`fotocasa_scraper.py`** - Scraper específico para Fotocasa
- **`scraper_factory.py`** - Factory para gestionar portales de forma escalable

### Archivos Legacy

- **`HomeScraperIdealista.py`** - Versión antigua solo para Idealista (mantener por compatibilidad)

### Archivos de Configuración

- **`start_chrome_debug.bat`**: Inicia Chrome en modo debugging
- **`requirements_advanced.txt`**: Dependencias del proyecto
- **`profile_4931/`**: Perfil de Chrome para debugging

## 🛠️ Instalación

### 🐧 Linux (Ubuntu/Debian/Xubuntu)

1. **Clonar el repositorio**
```bash
git clone https://github.com/AlexAlvarezAlmendros/HomeScrapper.git
cd HomeScrapper
```

2. **Instalar Python y pip (si no los tienes)**
```bash
sudo apt update
sudo apt install python3 python3-pip python3-venv python-is-python3
```

3. **Instalar Chrome o Chromium**
```bash
# Opción A: Chromium (recomendado)
sudo apt install chromium-browser

# Opción B: Google Chrome
wget https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
sudo dpkg -i google-chrome-stable_current_amd64.deb
sudo apt -f install
```

4. **Crear y activar entorno virtual**
```bash
python -m venv .venv
source .venv/bin/activate
```

5. **Instalar dependencias**
```bash
pip install -r requirements_advanced.txt
```

6. **Dar permisos a los scripts**
```bash
chmod +x start_chrome_debug.sh start_scraper.sh
```

### 🪟 Windows

1. **Clonar el repositorio**
```bash
git clone https://github.com/AlexAlvarezAlmendros/HomeScrapper.git
cd HomeScrapper
```

2. **Crear entorno virtual**
```bash
python -m venv .venv
```

3. **Activar entorno virtual**
```powershell
# Windows PowerShell
.venv\Scripts\Activate.ps1

# Windows CMD
.venv\Scripts\activate.bat
```

4. **Instalar dependencias**
```bash
pip install -r requirements_advanced.txt
```

## 📖 Uso

### Script Principal: HomeScraper.py (Recomendado)

Este es el script multi-portal con menú interactivo.

#### Paso 1: Iniciar Chrome en modo debugging
```bash
.\start_chrome_debug.bat
```

#### Paso 2: Ejecutar el scraper
```bash
python HomeScraper.py
```

#### Paso 3: Seguir el menú interactivo

**Selección de Portal:**
```
Portales disponibles:
  1. Idealista
  2. Fotocasa

Elige un portal (1-2):
```

**Configuración:**
```
[?] ¿Activar modo DEBUG? (s/n)
    > Muestra información detallada del proceso de detección

[?] ¿Activar ROTACIÓN DE IP? (s/n)
    > Cambia de IP automáticamente o manualmente cada N peticiones
    > Soporte para NordVPN, ExpressVPN, ProtonVPN, Surfshark, Windscribe

[?] OPCIONES:
    1. Navegar automáticamente a la URL y scrapear
    2. Ya estoy en la página, scrapear directamente

[?] ¿Cuántas páginas quieres scrapear?
    > Enter = TODAS las páginas disponibles
    > O especifica un número (ej: 3)
```

### Uso del Script Legacy (Solo Idealista)

Si solo necesitas Idealista, puedes usar el script original:

```bash
python HomeScraperIdealista.py
```

## 🎯 Cómo Funciona el Filtrado de Particulares

### Paso 1: Filtrado en el Listado
Analiza cada anuncio en la página de resultados y descarta aquellos que tienen el elemento:
```html
<picture class="logo-branding">
```
Este elemento solo aparece en anuncios de inmobiliarias.

### Paso 2: Verificación en Detalle
Para cada posible particular, accede a la página de detalle y busca:
```html
<div class="professional-name">
  <div class="name">Particular</div>
</div>
```

### Paso 3: Extracción de Datos
Si es confirmado como particular, extrae:
- ✅ Título de la vivienda
- ✅ Precio
- ✅ Ubicación/Dirección
- ✅ Número de habitaciones
- ✅ Metros cuadrados
- ✅ Descripción completa
- ✅ Teléfono de contacto (hace click en "Ver teléfono")

## 📊 Formato de Salida

Los resultados se guardan en formato JSON con timestamp:

```json
{
  "timestamp": "2025-11-14T16:05:49",
  "url": "https://www.idealista.com/...",
  "total": 45,
  "particulares": 12,
  "inmobiliarias": 33,
  "viviendas": {
    "todas": [...],
    "solo_particulares": [
      {
        "titulo": "Casa de pueblo en venta",
        "precio": "195.000 €",
        "ubicacion": "Major-ag.bellmun, 7",
        "habitaciones": "5 hab.",
        "metros": "263 m²",
        "url": "https://www.idealista.com/...",
        "descripcion": "...",
        "anunciante": "Particular",
        "telefono": "936 17 16 04",
        "fecha_scraping": "2025-11-14T16:05:49"
      }
    ],
    "solo_inmobiliarias": [...]
  }
}
```

Nombre del archivo: `viviendas_<portal>_YYYYMMDD_HHMMSS.json`

## 🔧 Añadir Nuevos Portales

La arquitectura es totalmente escalable. Para añadir un nuevo portal:

### Paso 1: Crear el scraper específico

```python
# nuevo_portal_scraper.py
from base_scraper import BaseScraper, Vivienda
from bs4 import BeautifulSoup

class NuevoPortalScraper(BaseScraper):
    
    def get_portal_name(self) -> str:
        return "NuevoPortal"
    
    def get_search_url(self) -> str:
        return "https://www.nuevoportal.com/buscar/..."
    
    def es_particular(self, html_texto: str) -> tuple[bool, str]:
        # Implementar lógica específica del portal
        pass
    
    def extraer_vivienda(self, elemento):
        # Implementar extracción específica del portal
        pass
    
    def scrapear_pagina(self):
        # Implementar scraping de página
        pass
    
    def scrapear_con_filtrado(self, paginas=None):
        # Implementar método principal
        pass
```

### Paso 2: Registrar en la factory

```python
# scraper_factory.py
from nuevo_portal_scraper import NuevoPortalScraper

class ScraperFactory:
    _scrapers: Dict[str, Type[BaseScraper]] = {
        'idealista': IdealistaScraper,
        'fotocasa': FotocasaScraper,
        'nuevoportal': NuevoPortalScraper,  # ← Añadir aquí
    }
```

**¡Listo!** El nuevo portal aparecerá automáticamente en el menú.

## 🔍 Detección Automática de Páginas

El scraper detecta automáticamente cuándo ha llegado a la última página:

- Busca botones de "siguiente página" en el DOM
- Detecta redirecciones o URLs repetidas
- Para automáticamente cuando no hay más resultados

## 🛡️ Anti-Detección y Rotación de IP

### Técnicas Anti-Detección:

1. **Chrome DevTools Protocol (CDP)**
   - Conexión a Chrome ya abierto, no automatización detectable

2. **Delays aleatorios**
   - Entre páginas: 3-7 segundos
   - Entre detalles: 2-5 segundos
   - Pausas largas cada 10 peticiones: 15-30 segundos

3. **Rotación de IP automática**
   - Soporte para VPNs: NordVPN, ExpressVPN, ProtonVPN, Surfshark, Windscribe
   - Cambio automático cada N peticiones (configurable)
   - Modo manual con pausas para cambio manual

4. **Detección y manejo de captchas**
   - Detecta captchas de DataDome automáticamente
   - Pausa el scraper para resolución manual
   - Continúa automáticamente después

## ⚠️ Consideraciones

- **Uso responsable**: No hacer scraping masivo que sobrecargue servidores
- **Terms of Service**: Revisa los términos de uso de cada portal
- **Rate limiting**: El scraper incluye pausas inteligentes
- **Datos personales**: Los datos extraídos deben usarse responsablemente
- **IP bans**: Usa rotación de IP si planeas hacer scraping extensivo

## 🐛 Troubleshooting

### Error: "No se pudo conectar a Chrome"
**Solución**: Ejecuta `start_chrome_debug.bat` primero y espera a que Chrome se abra

### Error: "Portal no disponible"
**Solución**: Verifica que el portal esté en la lista con `ScraperFactory.get_available_portals()`

### Captcha detectado constantemente
**Solución**: 
- Activa rotación de IP automática
- Aumenta los delays en `base_scraper.py`
- Reduce el número de páginas por sesión

### No se encuentran artículos
**Solución**: 
- Verifica que estás en una página de resultados del portal
- Los selectores CSS pueden haber cambiado, actualiza el scraper específico
- Activa modo debug para ver qué está pasando

### Selectores CSS no funcionan
**Solución**:
- Los portales cambian su HTML frecuentemente
- Inspecciona el HTML con DevTools de Chrome
- Actualiza los selectores en el archivo `<portal>_scraper.py` correspondiente

## 📝 Licencia

Ver archivo [LICENSE](LICENSE)

## 👤 Autor

Alex Alvarez Almendros
- GitHub: [@AlexAlvarezAlmendros](https://github.com/AlexAlvarezAlmendros)

## 🤝 Contribuciones

Las contribuciones son bienvenidas. Por favor:
1. Fork del proyecto
2. Crea una rama para tu feature (`git checkout -b feature/AmazingFeature`)
3. Commit de tus cambios (`git commit -m 'Add some AmazingFeature'`)
4. Push a la rama (`git push origin feature/AmazingFeature`)
5. Abre un Pull Request

## ⭐ Agradecimientos

- Selenium WebDriver
- BeautifulSoup4
- undetected-chromedriver

---

**Nota**: Este proyecto es solo para fines educativos. Úsalo de manera responsable y respeta los términos de servicio de los sitios web.