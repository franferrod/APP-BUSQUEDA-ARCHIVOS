import os
from PIL import Image, ImageDraw

def generar_icono_profesional(imagen_base_path, salida_ico_path):
    """
    Crea un icono .ico multi-resolución de alta calidad.
    Combina el isotipo de ALSI con una lupa inclinada profesional.
    """
    if not os.path.exists(imagen_base_path):
        print(f"Error: No se encuentra {imagen_base_path}")
        return

    # 1. Cargar el isotipo original (fuente de alta calidad)
    # El archivo original tiene 13KB, lo tratamos con cuidado.
    base = Image.open(imagen_base_path).convert("RGBA")
    
    # Resoluciones estándar para Windows (incluidas las de alta DPI)
    # 256 es vital para que no se vea pixelado en el escritorio.
    resoluciones = [16, 32, 48, 64, 128, 256]
    icon_images = []

    for size in resoluciones:
        # Creamos un lienzo transparente para cada tamaño
        canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        
        # EL LOGO (Isotipo Naranja): 
        # Lo escalamos para que ocupe la mayor parte del icono pero deje aire.
        # Usamos LANCZOS para máxima nitidez en el reescalado.
        logo_k = 0.82
        logo_size = int(size * logo_k)
        logo_resized = base.resize((logo_size, logo_size), Image.Resampling.LANCZOS)
        
        # Posición: un poco desplazado para dejar hueco a la lupa abajo-derecha
        logo_pos = (int(size * 0.04), int(size * 0.04))
        canvas.paste(logo_resized, logo_pos, logo_resized)
        
        # LA LUPA:
        # Para que no se vea "pixelada" al dibujarla directamente en tamaños bajos,
        # la dibujamos en un canvas gigante (oversampling) y luego la pegamos.
        factor = 4
        hd_size = size * factor
        lupa_hd = Image.new("RGBA", (hd_size, hd_size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(lupa_hd)
        
        # Coordenadas proporcionales en el canvas HD
        # La lupa estará en el cuadrante inferior derecho
        r = int(hd_size * 0.18) # Radio del lente
        cx = int(hd_size * 0.72) # Centro X
        cy = int(hd_size * 0.72) # Centro Y
        thick = max(2, int(hd_size * 0.04)) # Grosor del aro
        
        color_lupa = (60, 60, 60, 255) # Gris oscuro "industrial"
        
        # Aro de la lupa
        draw.ellipse([cx-r, cy-r, cx+r, cy+r], outline=color_lupa, width=thick)
        
        # Mango (inclinado 45 grados)
        # Empieza un poco dentro del aro y sale hacia la esquina
        m_start = (cx + int(r*0.7), cy + int(r*0.7))
        m_end = (cx + int(r*1.8), cy + int(r*1.8))
        draw.line([m_start, m_end], fill=color_lupa, width=int(thick * 1.6))
        
        # Redimensionar la lupa a su tamaño final con alta calidad
        lupa_final = lupa_hd.resize((size, size), Image.Resampling.LANCZOS)
        
        # Pegar la lupa sobre el logo
        canvas.paste(lupa_final, (0, 0), lupa_final)
        
        icon_images.append(canvas)

    # 3. GUARDADO CRITICO:
    # Para que Windows reconozca todas las capas y NO pierda calidad:
    # 1. El primer frame debe ser el más grande (256x256) según algunas specs de Windows.
    # 2. Usamos el parámetro 'sizes' explícitamente.
    icon_images.sort(key=lambda x: x.width, reverse=True) # De mayor a menor
    
    icon_images[0].save(
        salida_ico_path,
        format='ICO',
        append_images=icon_images[1:],
        bitmap_format='png' # Fuerza compresión PNG para los frames grandes (calidad + poco peso)
    )
    
    # Verificación de salida
    final_size = os.path.getsize(salida_ico_path)
    print(f"Icono generado: {salida_ico_path} ({final_size} bytes)")
    print(f"Capas incluidas: {[img.size for img in icon_images]}")

if __name__ == "__main__":
    generar_icono_profesional("ALSI_ISOTIPO_naranja.png", "ALSI_BUSCADOR.ico")
