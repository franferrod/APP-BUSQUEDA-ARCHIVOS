import os
import shutil
from datetime import datetime

def make_snapshot():
    # Versión actual sugerida
    version_base = "v1.0.0" 
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    folder_name = f"SNAPSHOT_{version_base}_{timestamp}"
    
    backup_root = "BACKUPS"
    target_dir = os.path.join(backup_root, folder_name)
    
    if not os.path.exists(backup_root):
        os.makedirs(backup_root)
        
    os.makedirs(target_dir)
    
    # Archivos críticos para el proyecto
    files_to_copy = [
        "buscar_piezas.py",
        "models.py",
        "controllers.py",
        "BuscadorPiezas.spec",
        "requirements.txt",
        "ALSI_BUSCADOR.ico",
        "ALSI_IMAGOTIPO_naranja.png",
        "ALSI_ISOTIPO_naranja.png",
        "INSTALAR_LOCAL.bat",
        "compilar.bat"
    ]
    
    print(f"--- Iniciando Snapshot en {target_dir} ---")
    
    copied_count = 0
    for file in files_to_copy:
        if os.path.exists(file):
            shutil.copy2(file, target_dir)
            print(f" [+] Copiado: {file}")
            copied_count += 1
        else:
            print(f" [!] No encontrado: {file}")
            
    print(f"\n--- Snapshot completado: {copied_count} archivos guardados ---")
    print(f"Ubicacion: {os.path.abspath(target_dir)}")

if __name__ == "__main__":
    make_snapshot()
    input("\nPresiona Enter para cerrar...")
