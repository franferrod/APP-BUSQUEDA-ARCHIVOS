"""
Tests para extraer_metadata() v1.0.7 — Parser de NAS nuevo.
Verifica los 4 casos del PRD + casos edge.
"""
import pytest
import os
import sys
from pathlib import Path

# Añadir directorio padre al path para importar controllers
sys.path.insert(0, str(Path(__file__).parent.parent))

from controllers import IndexadorThread


@pytest.fixture
def indexador(tmp_path, monkeypatch):
    """Crea un IndexadorThread mínimo para testing del parser.
    V1.0.7 - Mockea IndexManager para no requerir PostgreSQL real."""
    from unittest.mock import MagicMock
    
    # Crear un mock de IndexManager (no necesitamos BD real para tests de parsing)
    db_mock = MagicMock()
    
    rutas = {
        'PROYECTOS': r'\\192.168.1.10\Oficina Tecnica\ALSI PROYECTOS APROBADOS',
        'BIBLIOTECA_3D': r'\\192.168.1.10\Oficina Tecnica\ALSI BIBLIOTECA 3D',
        'ALSI_ESTANDAR': r'\\192.168.1.10\Oficina Tecnica\ALSI ESTANDAR',
    }
    thread = IndexadorThread(db_mock, rutas)
    return thread


class TestExtraerMetadataProyectos:
    """Caso 1 del PRD: Rutas de proyectos con CLIENTE/PROYECTO/ORDEN/TIPO"""

    def test_ruta_completa_mabe(self, indexador):
        """PRD Caso 1: MABE\\26046 LINEA PALETIZADO\\133 LINEA PALETIZADO\\MECANICA"""
        ruta_base = r'\\192.168.1.10\Oficina Tecnica\ALSI PROYECTOS APROBADOS'
        ruta_carpeta = os.path.join(ruta_base, 'MABE', '26046 LINEA PALETIZADO', 
                                     '133 LINEA PALETIZADO', 'MECANICA')
        
        meta = indexador.extraer_metadata(
            '26046.E223 CONJUNTO TRPs.SLDASM', ruta_carpeta,
            origen='PROYECTOS', ruta_base=ruta_base
        )
        
        assert meta['cliente'] == 'MABE'
        assert meta['codigo_proyecto'] == '26046'
        assert meta['nombre_proyecto'] == 'LINEA PALETIZADO'
        assert meta['año'] == 2026
        assert meta['codigo_orden'] == '133'
        assert meta['nombre_orden'] == 'LINEA PALETIZADO'
        assert meta['tipo'] == 'MECANICA'

    def test_año_2025(self, indexador):
        """Verificar inferencia de año 2025 desde código 25052"""
        ruta_base = r'\\192.168.1.10\Oficina Tecnica\ALSI PROYECTOS APROBADOS'
        ruta_carpeta = os.path.join(ruta_base, 'CLIENTE X', '25052 TRANSPORTADOR',
                                     '200 FASE 1', 'MECANICA')
        
        meta = indexador.extraer_metadata(
            'pieza.sldprt', ruta_carpeta,
            origen='PROYECTOS', ruta_base=ruta_base
        )
        
        assert meta['año'] == 2025
        assert meta['codigo_proyecto'] == '25052'

    def test_año_2019(self, indexador):
        """Verificar inferencia de año antiguo 2019"""
        ruta_base = r'\\192.168.1.10\Oficina Tecnica\ALSI PROYECTOS APROBADOS'
        ruta_carpeta = os.path.join(ruta_base, 'FORD', '19015 MESA GIRO',
                                     '50 MESA', 'LISTADOS')
        
        meta = indexador.extraer_metadata(
            'listado.pdf', ruta_carpeta,
            origen='PROYECTOS', ruta_base=ruta_base
        )
        
        assert meta['año'] == 2019
        assert meta['codigo_proyecto'] == '19015'
        assert meta['tipo'] == 'LISTADOS'

    def test_tipo_ofertas_pedidos(self, indexador):
        """Verificar tipo OFERTAS Y PEDIDOS"""
        ruta_base = r'\\192.168.1.10\Oficina Tecnica\ALSI PROYECTOS APROBADOS'
        ruta_carpeta = os.path.join(ruta_base, 'MABE', '26046 LINEA',
                                     '133 FASE', 'OFERTAS Y PEDIDOS')
        
        meta = indexador.extraer_metadata(
            'oferta.pdf', ruta_carpeta,
            origen='PROYECTOS', ruta_base=ruta_base
        )
        
        assert meta['tipo'] == 'OFERTAS Y PEDIDOS'


class TestExtraerMetadataBiblioteca:
    """Caso 2 del PRD: Rutas de ALSI BIBLIOTECA 3D"""

    def test_biblioteca_3d(self, indexador):
        """PRD Caso 2: ALSI BIBLIOTECA 3D\\RODILLOS\\..."""
        ruta_base = r'\\192.168.1.10\Oficina Tecnica\ALSI BIBLIOTECA 3D'
        ruta_carpeta = os.path.join(ruta_base, 'RODILLOS', 'ACERO INOX')
        
        meta = indexador.extraer_metadata(
            'rodillo_120.sldprt', ruta_carpeta,
            origen='BIBLIOTECA_3D', ruta_base=ruta_base
        )
        
        assert meta['cliente'] == 'ALSI'
        assert meta['año'] == 0
        assert meta['tipo'] in ('BIBLIOTECA', 'COMERCIAL')


class TestExtraerMetadataEstandar:
    """Caso 3 del PRD: Rutas de ALSI ESTANDAR"""

    def test_estandar_con_caracteres_especiales(self, indexador):
        """PRD Caso 3: ALSI ESTANDAR\\MESA DE TRÍAS (MTR)\\..."""
        ruta_base = r'\\192.168.1.10\Oficina Tecnica\ALSI ESTANDAR'
        ruta_carpeta = os.path.join(ruta_base, 'MESA DE TRÍAS (MTR)', 'COMPONENTES')
        
        meta = indexador.extraer_metadata(
            'mesa_trias.sldasm', ruta_carpeta,
            origen='ALSI_ESTANDAR', ruta_base=ruta_base
        )
        
        assert meta['cliente'] == 'ALSI'
        assert meta['año'] == 0
        assert meta['tipo'] in ('ESTANDAR', 'COMERCIAL')


class TestExtraerMetadataAcentos:
    """Caso 4 del PRD: Rutas con acentos y espacios"""

    def test_cliente_con_acentos(self, indexador):
        """PRD Caso 4: HORTOFRUTÍCOLA LAS NORIAS\\26081 ALIM. SORTIPACK\\..."""
        ruta_base = r'\\192.168.1.10\Oficina Tecnica\ALSI PROYECTOS APROBADOS'
        ruta_carpeta = os.path.join(
            ruta_base, 'HORTOFRUTÍCOLA LAS NORIAS',
            '26081 ALIM. SORTIPACK', '335 DISTRIBOR CAJAS', 'LISTADOS'
        )
        
        meta = indexador.extraer_metadata(
            'listado.pdf', ruta_carpeta,
            origen='PROYECTOS', ruta_base=ruta_base
        )
        
        # Debe conservar nombres reales, no inventar nombres
        assert meta['cliente'] == 'HORTOFRUTÍCOLA LAS NORIAS'
        assert meta['codigo_proyecto'] == '26081'
        assert meta['nombre_proyecto'] == 'ALIM. SORTIPACK'
        assert meta['año'] == 2026
        assert meta['codigo_orden'] == '335'
        assert meta['nombre_orden'] == 'DISTRIBOR CAJAS'
        assert meta['tipo'] == 'LISTADOS'




class TestExtraerMetadataEdgeCases:
    """Casos borde y fallbacks"""

    def test_ruta_corta_sin_orden(self, indexador):
        """Ruta con solo cliente y proyecto, sin orden"""
        ruta_base = r'\\192.168.1.10\Oficina Tecnica\ALSI PROYECTOS APROBADOS'
        ruta_carpeta = os.path.join(ruta_base, 'MABE', '26046 LINEA PALETIZADO')
        
        meta = indexador.extraer_metadata(
            'archivo.sldprt', ruta_carpeta,
            origen='PROYECTOS', ruta_base=ruta_base
        )
        
        assert meta['cliente'] == 'MABE'
        assert meta['codigo_proyecto'] == '26046'
        # No debería crashear aunque no tenga orden

    def test_ruta_solo_cliente(self, indexador):
        """Ruta con solo el cliente (archivo suelto bajo cliente)"""
        ruta_base = r'\\192.168.1.10\Oficina Tecnica\ALSI PROYECTOS APROBADOS'
        ruta_carpeta = os.path.join(ruta_base, 'MABE')
        
        meta = indexador.extraer_metadata(
            'archivo.sldprt', ruta_carpeta,
            origen='PROYECTOS', ruta_base=ruta_base
        )
        
        assert meta['cliente'] == 'MABE'
        # No debería crashear

    def test_sin_origen(self, indexador):
        """Ruta sin origen especificado (fallback)"""
        meta = indexador.extraer_metadata(
            'archivo.sldprt', r'C:\Temp\Archivos',
            origen=None, ruta_base=None
        )
        
        # No debe crashear, debe devolver metadata con defaults
        assert 'año' in meta
        assert 'cliente' in meta
        assert 'tipo' in meta
