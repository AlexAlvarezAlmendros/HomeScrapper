# HomeScrapper - Idealista Property Scraper

Web scraper para extraer anuncios de viviendas de Idealista, con enfoque especial en detectar y filtrar anuncios de **particulares** (propietarios directos) vs inmobiliarias.

## 🚀 Características Principales

- **Filtrado de dos etapas**: Identifica particulares primero en el listado y luego verifica en la página de detalle
- **Detección automática de páginas**: Procesa todas las páginas disponibles automáticamente
- **Extracción completa de datos**: Título, precio, ubicación, habitaciones, metros cuadrados, descripción, teléfono
- **Método CDP (Chrome DevTools Protocol)**: Conexión a Chrome en modo debug para evitar detección
- **Anti-detección**: Sin bloqueos de DataDome o sistemas anti-bot

## 📁 Archivos del Proyecto

### Scrapers

- **`HomeScraperIdealista.py`**
  - Scraper con filtrado de particulares mediante CDP
  - Se conecta a Chrome en modo debugging
  - Extracción completa de datos incluyendo teléfono
  - Procesamiento automático de todas las páginas

### Archivos de Configuración

- **`start_chrome_debug.sh`**: Inicia Chrome en modo debugging (Linux)
- **`start_chrome_debug.bat`**: Inicia Chrome en modo debugging (Windows)
- **`start_scraper.sh`**: Script para ejecutar el scraper (Linux)
- **`start_scraper.bat`**: Script para ejecutar el scraper (Windows)
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

### 🐧 Uso en Linux

#### Paso 1: Iniciar Chrome en modo debugging

En una terminal:
```bash
cd HomeScrapper
./start_chrome_debug.sh
```

O manualmente:
```bash
# Con Google Chrome
google-chrome --remote-debugging-port=9222 --user-data-dir="$HOME/selenium_chrome_profile"

# Con Chromium
chromium-browser --remote-debugging-port=9222 --user-data-dir="$HOME/selenium_chrome_profile"
```

#### Paso 2: Navegar a Idealista
En el Chrome que se abrió:
1. Ve a **idealista.com**
2. Configura tu búsqueda (zona, precio, tipo de vivienda)
3. Resuelve cualquier CAPTCHA si aparece

#### Paso 3: Ejecutar el scraper
En otra terminal:
```bash
cd HomeScrapper
source .venv/bin/activate
python HomeScraperIdealista.py
```

O usa el script:
```bash
./start_scraper.sh
```

---

### 🔐 Uso con VPN (ProtonVPN en Linux)

El scraper soporta cambio automático de VPN para evitar bloqueos.

#### Instalar ProtonVPN
```bash
# Descargar desde https://protonvpn.com/support/linux-vpn-tool/
# O instalar con pip:
pip install protonvpn-cli

# Iniciar sesión
protonvpn signin tu_email@ejemplo.com
```

#### Ejecutar scraper con rotación de VPN

1. Ejecuta el scraper:
```bash
python HomeScraperIdealista.py
```

2. Cuando pregunte **"¿Activar ROTACIÓN DE IP?"** → Responde `s`

3. Cuando pregunte **"¿Quieres cambio de VPN AUTOMÁTICO?"** → Elige `3` (ProtonVPN)

El scraper cambiará automáticamente de servidor VPN cada 15 peticiones, conectándose a servidores europeos (España, Francia, Alemania, etc.) para mejor rendimiento con Idealista.

#### Comandos útiles de ProtonVPN
```bash
protonvpn connect --fastest      # Conectar al más rápido
protonvpn connect --country ES   # Conectar a España
protonvpn connect --random       # Servidor aleatorio
protonvpn disconnect             # Desconectar
protonvpn countries              # Ver países disponibles
```

---

### 🪟 Uso en Windows

#### Paso 1: Iniciar Chrome en modo debugging
```bash
.\start_chrome_debug.bat
```

#### Paso 2: Navegar a tu búsqueda de Idealista
En el Chrome que se abrió, ve a Idealista y configura tu búsqueda (ubicación, precio, tipo de vivienda, etc.)

#### Paso 3: Ejecutar el scraper
```bash
python HomeScraperIdealista.py
```

---

### HomeScraperIdealista.py (CDP)

Este método usa Chrome DevTools Protocol para evitar detección.

#### Paso 1: Iniciar Chrome en modo debugging
```bash
.\start_chrome_debug.bat
```

#### Paso 2: Navegar a tu búsqueda de Idealista
En el Chrome que se abrió, ve a Idealista y configura tu búsqueda (ubicación, precio, tipo de vivienda, etc.)

#### Paso 3: Ejecutar el scraper
```bash
python HomeScraperIdealista.py
```

#### Opciones interactivas:
```
[?] ¿Activar modo DEBUG? (s/n)
    > Muestra información detallada del proceso

[?] OPCIONES:
    1. Navegar automáticamente a tu URL y scrapear CON FILTRADO (recomendado)
    2. Ya estoy en la página, scrapear CON FILTRADO
    3. Ya estoy en la página, scrapear sin filtrado (método antiguo)

[?] ¿Cuántas páginas quieres scrapear?
    > Deja vacío o escribe 'todas' para procesar TODAS las páginas
    > O especifica un número (ej: 3)
```

### Método Alternativo: scraper_particulares.py

```bash
python scraper_particulares.py --url "https://www.idealista.com/venta-viviendas/barcelona/" --paginas 3
```

**Opciones:**
- `--url`: URL de búsqueda de Idealista (requerido)
- `--paginas`: Número de páginas a procesar (default: 1)
- `--headless`: Ejecutar sin interfaz gráfica
- `--debug`: Activar mensajes de debug

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

Nombre del archivo: `viviendas_idealista_YYYYMMDD_HHMMSS.json`

## 🔍 Detección Automática de Páginas

El scraper detecta automáticamente cuándo ha llegado a la última página:

- Construye URLs: `/pagina-2`, `/pagina-3`, etc.
- Detecta redirección a `pagina-1` (indica el final)
- Regex preciso: evita confundir `pagina-10` con `pagina-1`

## 🛡️ Anti-Detección

### Técnicas Utilizadas:

1. **Chrome DevTools Protocol (CDP)**
   - Se conecta a Chrome ya abierto
   - No usa automatización detectable

2. **Tiempos aleatorios**
   - Pausas entre 1-3 segundos
   - Simula comportamiento humano

3. **Scroll natural**
   - Hace scroll progresivo en la página
   - Activa carga lazy-load

4. **User Agent real**
   - Usa User-Agent de Chrome actualizado

## ⚠️ Consideraciones

- **Uso responsable**: No hacer scraping masivo que sobrecargue el servidor
- **Terms of Service**: Revisa los términos de uso de Idealista
- **Rate limiting**: El scraper incluye pausas para no ser agresivo
- **Datos personales**: Los teléfonos son datos sensibles, úsalos responsablemente

## 🐛 Troubleshooting

### Error: "No se pudo conectar a Chrome"
**Solución**: Asegúrate de ejecutar `start_chrome_debug.bat` primero

### Error: "DataDome bloqueó el acceso"
**Solución**: El script te pedirá resolver el CAPTCHA manualmente en el navegador

### No se encuentran artículos
**Solución**: 
- Verifica que estás en una página de resultados de Idealista
- Comprueba que hay anuncios visibles en la página

### No se extraen teléfonos
**Solución**: 
- Activa modo debug con `-s` o `--debug`
- Verifica que el botón "Ver teléfono" es clickeable
- Algunos anuncios pueden no tener teléfono visible

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