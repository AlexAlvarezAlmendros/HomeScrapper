"""
Factory para crear scrapers de diferentes portales inmobiliarios
Permite añadir nuevos portales fácilmente
"""

from typing import Dict, Type, List, Optional
from base_scraper import BaseScraper
from idealista_scraper import IdealistaScraper
from fotocasa_scraper import FotocasaScraper


class ScraperFactory:
    """Factory para crear instancias de scrapers según el portal elegido"""
    
    # Registro de scrapers disponibles
    _scrapers: Dict[str, Type[BaseScraper]] = {
        'idealista': IdealistaScraper,
        'fotocasa': FotocasaScraper,
    }
    
    @classmethod
    def get_available_portals(cls) -> List[str]:
        """Retorna lista de portales disponibles"""
        return list(cls._scrapers.keys())
    
    @classmethod
    def create_scraper(cls, portal: str, modo_debug=False, usar_rotacion_ip=False, vpn_provider=None, search_url=None) -> BaseScraper:
        """
        Crea una instancia del scraper apropiado según el portal
        
        Args:
            portal: Nombre del portal ('idealista', 'fotocasa', etc.)
            modo_debug: Activar modo debug
            usar_rotacion_ip: Activar rotación de IP
            vpn_provider: Proveedor de VPN para rotación automática
            search_url: URL de búsqueda personalizada (opcional)
            
        Returns:
            Instancia del scraper correspondiente
            
        Raises:
            ValueError: Si el portal no existe
        """
        portal_lower = portal.lower()
        
        if portal_lower not in cls._scrapers:
            available = ', '.join(cls._scrapers.keys())
            raise ValueError(f"Portal '{portal}' no disponible. Portales disponibles: {available}")
        
        scraper_class = cls._scrapers[portal_lower]
        return scraper_class(
            modo_debug=modo_debug, 
            usar_rotacion_ip=usar_rotacion_ip, 
            vpn_provider=vpn_provider,
            search_url=search_url
        )
    
    @classmethod
    def register_scraper(cls, portal_name: str, scraper_class: Type[BaseScraper]):
        """
        Registra un nuevo scraper en la factory
        Útil para añadir scrapers personalizados sin modificar este archivo
        
        Args:
            portal_name: Nombre del portal (ej: 'pisos.com')
            scraper_class: Clase del scraper que hereda de BaseScraper
        """
        if not issubclass(scraper_class, BaseScraper):
            raise TypeError(f"{scraper_class.__name__} debe heredar de BaseScraper")
        
        cls._scrapers[portal_name.lower()] = scraper_class
        print(f"[OK] Scraper para '{portal_name}' registrado exitosamente")
    
    @classmethod
    def get_portal_info(cls, portal: str) -> Optional[dict]:
        """
        Obtiene información sobre un portal específico
        
        Args:
            portal: Nombre del portal
            
        Returns:
            Diccionario con información del portal
        """
        portal_lower = portal.lower()
        
        if portal_lower not in cls._scrapers:
            return None
        
        scraper_class = cls._scrapers[portal_lower]
        # Crear instancia temporal para obtener info
        temp_scraper = scraper_class()
        
        return {
            'name': temp_scraper.get_portal_name(),
            'url': temp_scraper.get_search_url(),
            'class': scraper_class.__name__
        }
    
    @classmethod
    def list_portals_info(cls):
        """Muestra información de todos los portales disponibles"""
        print("\n" + "="*70)
        print("PORTALES DISPONIBLES")
        print("="*70)
        
        for idx, portal_key in enumerate(cls._scrapers.keys(), 1):
            info = cls.get_portal_info(portal_key)
            print(f"\n{idx}. {info['name']}")
            print(f"   Clave: {portal_key}")
            print(f"   URL: {info['url']}")
            print(f"   Clase: {info['class']}")
        
        print("\n" + "="*70)


# Ejemplo de cómo añadir un nuevo portal sin modificar la factory:
# 
# from nuevo_portal_scraper import NuevoPortalScraper
# ScraperFactory.register_scraper('nuevo_portal', NuevoPortalScraper)
