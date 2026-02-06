"""
Script de prueba para verificar que la estructura multi-portal funciona correctamente
"""

from scraper_factory import ScraperFactory


def test_factory():
    """Prueba que la factory funciona correctamente"""
    print("\n" + "="*70)
    print("TEST: SCRAPER FACTORY")
    print("="*70)
    
    # Test 1: Listar portales disponibles
    print("\n[TEST 1] Listar portales disponibles")
    portales = ScraperFactory.get_available_portals()
    print(f"Portales disponibles: {portales}")
    assert len(portales) >= 2, "Debe haber al menos 2 portales"
    assert 'idealista' in portales, "Debe incluir Idealista"
    assert 'fotocasa' in portales, "Debe incluir Fotocasa"
    print("✅ PASS")
    
    # Test 2: Obtener información de cada portal
    print("\n[TEST 2] Obtener información de portales")
    for portal in portales:
        info = ScraperFactory.get_portal_info(portal)
        print(f"\n  Portal: {portal}")
        print(f"  - Nombre: {info['name']}")
        print(f"  - URL: {info['url']}")
        print(f"  - Clase: {info['class']}")
        assert info is not None, f"Info de {portal} no debe ser None"
        assert 'name' in info, f"Info de {portal} debe tener 'name'"
        assert 'url' in info, f"Info de {portal} debe tener 'url'"
        assert 'class' in info, f"Info de {portal} debe tener 'class'"
    print("\n✅ PASS")
    
    # Test 3: Crear instancias de scrapers
    print("\n[TEST 3] Crear instancias de scrapers")
    for portal in portales:
        scraper = ScraperFactory.create_scraper(portal, modo_debug=True)
        print(f"\n  {portal}:")
        print(f"  - Nombre: {scraper.get_portal_name()}")
        print(f"  - URL: {scraper.get_search_url()}")
        print(f"  - Modo debug: {scraper.modo_debug}")
        assert scraper is not None, f"Scraper de {portal} no debe ser None"
        assert scraper.get_portal_name(), f"Scraper de {portal} debe tener nombre"
        assert scraper.get_search_url(), f"Scraper de {portal} debe tener URL"
    print("\n✅ PASS")
    
    # Test 4: Intentar crear scraper de portal inexistente
    print("\n[TEST 4] Manejar portal inexistente")
    try:
        ScraperFactory.create_scraper('portal_inexistente')
        print("❌ FAIL - Debería lanzar ValueError")
        return False
    except ValueError as e:
        print(f"  Error esperado: {e}")
        print("✅ PASS")
    
    # Test 5: Listar información de todos los portales
    print("\n[TEST 5] Listar información completa")
    ScraperFactory.list_portals_info()
    print("✅ PASS")
    
    print("\n" + "="*70)
    print("TODOS LOS TESTS PASARON ✅")
    print("="*70)
    return True


def test_scrapers_structure():
    """Prueba que los scrapers tienen todos los métodos necesarios"""
    print("\n" + "="*70)
    print("TEST: ESTRUCTURA DE SCRAPERS")
    print("="*70)
    
    portales = ScraperFactory.get_available_portals()
    
    metodos_requeridos = [
        'get_portal_name',
        'get_search_url',
        'es_particular',
        'extraer_vivienda',
        'scrapear_pagina',
        'scrapear_con_filtrado',
        'conectar_chrome',
        'navegar_a_url',
        'detectar_captcha',
        'delay_aleatorio',
        'incrementar_contador_peticiones',
        'guardar',
        'mostrar_resumen'
    ]
    
    for portal in portales:
        print(f"\n[TEST] Verificando {portal}")
        scraper = ScraperFactory.create_scraper(portal)
        
        for metodo in metodos_requeridos:
            assert hasattr(scraper, metodo), f"{portal} debe tener método {metodo}"
            print(f"  ✓ {metodo}")
        
        print(f"✅ {portal} tiene todos los métodos requeridos")
    
    print("\n" + "="*70)
    print("ESTRUCTURA CORRECTA ✅")
    print("="*70)
    return True


if __name__ == "__main__":
    print("""
    ╔══════════════════════════════════════════════════════╗
    ║   TEST SUITE - HOME SCRAPER MULTI-PORTAL            ║
    ╚══════════════════════════════════════════════════════╝
    """)
    
    try:
        test_factory()
        test_scrapers_structure()
        
        print("\n" + "="*70)
        print("🎉 TODOS LOS TESTS COMPLETADOS EXITOSAMENTE")
        print("="*70)
        print("\n[*] El sistema multi-portal está listo para usar")
        print("[*] Ejecuta: python HomeScraper.py")
        
    except AssertionError as e:
        print(f"\n❌ TEST FALLIDO: {e}")
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
