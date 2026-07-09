# -*- coding: utf-8 -*-
"""
Módulo para extraer propiedades personalizadas de archivos SolidWorks (.sldprt, .sldasm)
utilizando el Document Manager API a través del ejecutable C# SwPropExtractor.exe
"""
import os
import json
import subprocess
import configparser

CONFIG_PATH = os.path.expanduser('~/.alsi_busqueda/config.ini')

class SWPropertyExtractor:
    def __init__(self):
        self.license_key = self._load_license_key()
        
        # Ruta al ejecutable (compilado via compilar.bat y empaquetado)
        if hasattr(sys, '_MEIPASS'):
            self.extractor_exe = os.path.join(sys._MEIPASS, 'SwPropExtractor.exe')
        else:
            self.extractor_exe = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'SwPropExtractor.exe')
            
        if not os.path.exists(self.extractor_exe):
            print(f"Warning: No se encontró el ejecutable {self.extractor_exe}")

    def _load_license_key(self):
        """Carga la clave de licencia desde el archivo de configuración"""
        if not os.path.exists(CONFIG_PATH):
            return ""
            
        try:
            config = configparser.ConfigParser()
            config.read(CONFIG_PATH)
            if 'SolidWorks' in config and 'DocumentManagerKey' in config['SolidWorks']:
                return config['SolidWorks']['DocumentManagerKey'].strip()
        except Exception as e:
            print(f"Error leyendo config: {e}")
            
        return ""
        
    def save_license_key(self, key):
        """Guarda la clave de licencia en el archivo de configuración"""
        os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
        config = configparser.ConfigParser()
        
        if os.path.exists(CONFIG_PATH):
            config.read(CONFIG_PATH)
            
        if 'SolidWorks' not in config:
            config['SolidWorks'] = {}
            
        config['SolidWorks']['DocumentManagerKey'] = key
        
        with open(CONFIG_PATH, 'w') as f:
            config.write(f)
            
        self.license_key = key

    def extract_properties(self, filepath):
        """
        Extrae propiedades de un archivo.
        Devuelve un dict con las propiedades, o None si falla.
        """
        if not self.license_key:
            return None
            
        if not os.path.exists(self.extractor_exe):
            return None
            
        try:
            # CREATE_NO_WINDOW = 0x08000000 para que no salte la consola negra
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            
            result = subprocess.run(
                [self.extractor_exe, self.license_key, filepath],
                capture_output=True,
                startupinfo=startupinfo,
                timeout=20  # V2.0.0: 20s (antes 5) — ensamblajes grandes/red lenta
            )
            
            if result.stdout:
                try:
                    text_out = result.stdout.decode('cp850')
                except UnicodeDecodeError:
                    try:
                        text_out = result.stdout.decode('utf-8')
                    except UnicodeDecodeError:
                        text_out = result.stdout.decode('latin-1', errors='replace')
                        
                data = json.loads(text_out)
                if "error" in data:
                    print(f"Error SW DM para {os.path.basename(filepath)}: {data['error']}")
                    return None
                return data
                
        except Exception as e:
            print(f"Error ejecutando SwPropExtractor en {os.path.basename(filepath)}: {e}")
            
        return None

# Instancia global por defecto
import sys
extractor = SWPropertyExtractor()
