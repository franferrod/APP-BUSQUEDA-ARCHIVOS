import pytest
import os
import sys
import sqlite3
from pathlib import Path

# Añadir el directorio padre al path para importar los módulos
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models import IndexManager


class TestIndexManagerBuscar:
    """Suite de tests para el método buscar() con scoring multi-keyword (@test-driven-development)"""

    @pytest.fixture(autouse=True)
    def setup_db(self, tmp_path, monkeypatch):
        """Crea una BD temporal con datos de prueba para cada test"""
        # Redirigir CONFIG_DIR y DB_PATH a tmp_path
        import models
        monkeypatch.setattr(models, 'CONFIG_DIR', tmp_path)
        monkeypatch.setattr(models, 'DB_PATH', tmp_path / 'test_index.db')
        
        self.db = IndexManager()
        
        # Insertar datos de prueba
        with self.db.get_connection() as conn:
            test_data = [
                ('travesaño_cama_inox.sldprt', 'EMRAH', 2025, 'VICASO', '25011 LÍNEA', 'MECANICA', 
                 r'\\OFITEC-7\test\travesaño_cama_inox.sldprt', '.sldprt', 1700000000, 1024),
                ('eje_principal.sldprt', 'DANI', 2024, 'AGRO', '24005 CORTADORA', 'LAYOUT',
                 r'\\OFITEC-5\test\eje_principal.sldprt', '.sldprt', 1699000000, 2048),
                ('cama_inox_v2.sldasm', 'MARCOS', 2025, 'VICASO', '25022 EMPAQUETADORA', 'MECANICA',
                 r'\\OFITEC-2\test\cama_inox_v2.sldasm', '.sldasm', 1700500000, 4096),
                ('correa_transporte.dwg', 'EMILIA', 2023, 'TECRESA', '23001 HORNO', 'LISTADOS',
                 r'\\OFITEC-3\test\correa_transporte.dwg', '.dwg', 1690000000, 512),
                ('plano_general.pdf', 'PACO', 2024, 'MARFRAN', '24010 PALETIZADORA', 'OFERTAS Y PEDIDOS',
                 r'D:\test\plano_general.pdf', '.pdf', 1695000000, 8192),
                ('travesaño_reforzado.sldprt', 'JESUS', 2025, 'VICASO', '25011 LÍNEA', 'MECANICA',
                 r'\\OFITEC-1\test\travesaño_reforzado.sldprt', '.sldprt', 1700100000, 3072),
            ]
            for d in test_data:
                conn.execute('''INSERT INTO archivos 
                    (nombre_archivo, compañero, año, cliente, proyecto, tipo_carpeta, 
                     ruta_completa, extension, ultima_modificacion, tamaño_bytes)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''', d)
            conn.commit()

    # -------------------------------------------------------------------------
    # Tests de búsqueda simple
    # -------------------------------------------------------------------------
    def test_busqueda_simple_encuentra_resultados(self):
        """Buscar una sola palabra devuelve las filas correctas"""
        resultados = self.db.buscar("travesaño")
        assert len(resultados) == 2
        nombres = [r[0] for r in resultados]
        assert 'travesaño_cama_inox.sldprt' in nombres
        assert 'travesaño_reforzado.sldprt' in nombres

    def test_busqueda_parcial(self):
        """LIKE funciona con coincidencia parcial"""
        resultados = self.db.buscar("eje")
        assert len(resultados) == 1
        assert resultados[0][0] == 'eje_principal.sldprt'

    def test_busqueda_sin_resultados(self):
        """Término inexistente devuelve lista vacía"""
        resultados = self.db.buscar("xyz_no_existe_999")
        assert len(resultados) == 0

    def test_busqueda_vacia_devuelve_todos(self):
        """Sin término de búsqueda, devuelve todos los archivos"""
        resultados = self.db.buscar("")
        assert len(resultados) == 6

    # -------------------------------------------------------------------------
    # Tests de búsqueda multi-keyword con scoring
    # -------------------------------------------------------------------------
    def test_multi_keyword_basico(self):
        """Buscar con comas divide en keywords y encuentra coincidencias"""
        resultados = self.db.buscar("travesaño, cama")
        assert len(resultados) >= 2
        # El primer resultado debe contener ambas palabras (mayor score)
        assert 'travesaño_cama_inox.sldprt' == resultados[0][0]

    def test_multi_keyword_scoring_orden(self):
        """El scoring prioriza archivos con más keywords coincidentes"""
        resultados = self.db.buscar("travesaño, cama, inox")
        # travesaño_cama_inox.sldprt tiene las 3 palabras → score más alto
        assert resultados[0][0] == 'travesaño_cama_inox.sldprt'

    def test_multi_keyword_or_logic(self):
        """Multi-keyword usa OR: archivos con cualquier keyword aparecen"""
        resultados = self.db.buscar("eje, correa")
        assert len(resultados) == 2
        nombres = [r[0] for r in resultados]
        assert 'eje_principal.sldprt' in nombres
        assert 'correa_transporte.dwg' in nombres

    # -------------------------------------------------------------------------
    # Tests de filtros
    # -------------------------------------------------------------------------
    def test_filtro_compañeros(self):
        """Filtrar por compañeros limita resultados"""
        resultados = self.db.buscar("", compañeros=['EMRAH', 'DANI'])
        assert all(r[1] in ['EMRAH', 'DANI'] for r in resultados)

    def test_filtro_años(self):
        """Filtrar por años limita resultados"""
        resultados = self.db.buscar("", años=['2025'])
        assert all(r[2] == 2025 for r in resultados)

    def test_filtro_extension_piezas(self):
        """Filtrar por extensión .sldprt devuelve solo piezas"""
        resultados = self.db.buscar("", extensiones=['.sldprt'])
        assert all(r[0].endswith('.sldprt') for r in resultados)
        assert len(resultados) == 3  # travesaño, eje, reforzado

    def test_filtro_extension_planos(self):
        """Filtrar por múltiples extensiones de planos funciona"""
        resultados = self.db.buscar("", extensiones=['.slddrw', '.dwg'])
        assert len(resultados) == 1
        assert resultados[0][0] == 'correa_transporte.dwg'

    def test_filtro_carpeta(self):
        """Filtrar por tipo_carpeta (Mecánica, Layout...) funciona"""
        # En setup_db hay 3 MECANICA: travesaño_cama_inox, cama_inox_v2, travesaño_reforzado
        resultados = self.db.buscar("", carpetas=['MECANICA'])
        assert len(resultados) == 3
        assert all(r[5] == 'MECANICA' for r in resultados)

    def test_filtro_dual_extension_y_carpeta(self):
        """Filtrar por Extensión (.sldasm) y Carpeta (MECANICA) simultáneamente"""
        resultados = self.db.buscar("", extensiones=['.sldasm'], carpetas=['MECANICA'])
        assert len(resultados) == 1
        assert resultados[0][0] == 'cama_inox_v2.sldasm'

    def test_filtros_combinados(self):
        """Combinar keyword + compañero + año filtra correctamente"""
        resultados = self.db.buscar("travesaño", compañeros=['EMRAH'], años=['2025'])
        assert len(resultados) == 1
        assert resultados[0][0] == 'travesaño_cama_inox.sldprt'

    # -------------------------------------------------------------------------
    # Tests de seguridad SQL (@sql-injection-testing)
    # -------------------------------------------------------------------------
    def test_sql_injection_simple_quote(self):
        """Una comilla simple en el término no rompe la consulta"""
        resultados = self.db.buscar("'; DROP TABLE archivos; --")
        assert isinstance(resultados, list)
        # Verificar que la tabla sigue existiendo
        with self.db.get_connection() as conn:
            count = conn.execute("SELECT COUNT(*) FROM archivos").fetchone()[0]
            assert count == 6

    def test_sql_injection_union_select(self):
        """Un intento UNION SELECT no extrae datos"""
        resultados = self.db.buscar("' UNION SELECT * FROM preferencias --")
        assert isinstance(resultados, list)

    def test_sql_injection_in_companions(self):
        """SQL injection en filtro de compañeros no afecta"""
        resultados = self.db.buscar("eje", compañeros=["DANI'; DROP TABLE archivos;--"])
        assert isinstance(resultados, list)

    # -------------------------------------------------------------------------
    # Tests de preferencias
    # -------------------------------------------------------------------------
    def test_guardar_y_leer_preferencia(self):
        """Preferencias se guardan y recuperan correctamente"""
        self.db.guardar_preferencia("test_key", "test_value")
        assert self.db.obtener_preferencia("test_key") == "test_value"

    def test_preferencia_default(self):
        """Preferencia inexistente devuelve el default"""
        assert self.db.obtener_preferencia("no_existe", "DEFAULT") == "DEFAULT"

    def test_preferencia_sobreescritura(self):
        """Guardar la misma clave la sobreescribe"""
        self.db.guardar_preferencia("clave", "v1")
        self.db.guardar_preferencia("clave", "v2")
        assert self.db.obtener_preferencia("clave") == "v2"


class TestIndexManagerDB:
    """Tests de integración para la estructura de la BD"""

    @pytest.fixture(autouse=True)
    def setup_db(self, tmp_path, monkeypatch):
        import models
        monkeypatch.setattr(models, 'CONFIG_DIR', tmp_path)
        monkeypatch.setattr(models, 'DB_PATH', tmp_path / 'test_index.db')
        self.db = IndexManager()

    def test_tablas_creadas(self):
        """init_db crea las 3 tablas requeridas"""
        with self.db.get_connection() as conn:
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ).fetchall()
            table_names = [t[0] for t in tables]
            assert 'archivos' in table_names
            assert 'preferencias' in table_names
            assert 'estado_indexacion' in table_names

    def test_indices_creados(self):
        """init_db crea los índices de rendimiento"""
        with self.db.get_connection() as conn:
            indexes = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%'"
            ).fetchall()
            idx_names = [i[0] for i in indexes]
            assert 'idx_nombre' in idx_names
            assert 'idx_compañero' in idx_names
            assert 'idx_año' in idx_names
            assert 'idx_tipo' in idx_names


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
