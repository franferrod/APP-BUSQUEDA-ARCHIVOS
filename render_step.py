# -*- coding: utf-8 -*-
"""
Render de miniatura para STEP/IGES sin SolidWorks (V2.0.3).
Teselado con gmsh (núcleo OpenCascade) + render sombreado por z-buffer (numpy).

Se ejecuta como SUBPROCESO aislado (un archivo STEP corrupto/enorme puede
reventar gmsh — stack overflow — y no debe tumbar el pase nocturno):

    python render_step.py <entrada.step> <salida.jpg> [lado]

Códigos de salida: 0 = OK, 1 = sin geometría/fallo.
Requiere: pip install gmsh numpy pillow  (solo en el equipo indexador).
"""
import os, sys


def teselar(ruta):
    import gmsh
    import numpy as np
    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.option.setNumber("Geometry.OCCImportLabels", 0)
        gmsh.open(ruta)
        # Malla gruesa de superficie: es para una miniatura de 256px
        gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 12)
        gmsh.model.mesh.generate(2)
        ntags, coords, _ = gmsh.model.mesh.getNodes()
        if len(ntags) == 0:
            return None
        verts = np.array(coords, dtype=np.float64).reshape(-1, 3)
        remap = np.zeros(int(ntags.max()) + 1, dtype=np.int64)
        remap[ntags.astype(np.int64)] = np.arange(len(ntags))
        etypes, _, enodes = gmsh.model.mesh.getElements(2)
        tris = []
        for et, nod in zip(etypes, enodes):
            if et == 2:  # triángulos lineales
                tris.append(remap[np.array(nod, dtype=np.int64)].reshape(-1, 3))
        if not tris:
            return None
        return verts, np.vstack(tris)
    finally:
        gmsh.finalize()


def render_iso(verts, tris, lado=256):
    """Vista isométrica sombreada sobre fondo blanco (estilo miniatura SW)."""
    import numpy as np
    from PIL import Image
    a, b = np.radians(-45), np.radians(-30)
    Rz = np.array([[np.cos(a), -np.sin(a), 0], [np.sin(a), np.cos(a), 0], [0, 0, 1]])
    Rx = np.array([[1, 0, 0], [0, np.cos(b), -np.sin(b)], [0, np.sin(b), np.cos(b)]])
    v = verts @ Rz.T @ Rx.T
    mn, mx = v.min(0), v.max(0)
    ancho = max(mx[0] - mn[0], mx[1] - mn[1])
    if ancho <= 0:
        return None
    v2 = (v - (mn + mx) / 2) * ((lado * 0.86) / ancho)
    v2[:, 0] += lado / 2
    v2[:, 1] = lado / 2 - v2[:, 1]

    img = np.full((lado, lado, 3), 255, dtype=np.uint8)
    zbuf = np.full((lado, lado), -1e30)
    luz = np.array([0.35, -0.5, 0.8]); luz /= np.linalg.norm(luz)
    base = np.array([208, 213, 219], dtype=np.float64)

    p0, p1, p2 = v2[tris[:, 0]], v2[tris[:, 1]], v2[tris[:, 2]]
    n = np.cross(p1 - p0, p2 - p0)
    nn = np.linalg.norm(n, axis=1); nn[nn == 0] = 1
    inten = np.abs((n / nn[:, None]) @ luz) * 0.75 + 0.25

    for i in np.argsort(p0[:, 2] + p1[:, 2] + p2[:, 2]):
        a0, a1, a2 = p0[i], p1[i], p2[i]
        minx = max(int(min(a0[0], a1[0], a2[0])), 0)
        maxx = min(int(max(a0[0], a1[0], a2[0])) + 1, lado)
        miny = max(int(min(a0[1], a1[1], a2[1])), 0)
        maxy = min(int(max(a0[1], a1[1], a2[1])) + 1, lado)
        if minx >= maxx or miny >= maxy:
            continue
        d = (a1[0]-a0[0])*(a2[1]-a0[1]) - (a2[0]-a0[0])*(a1[1]-a0[1])
        if abs(d) < 1e-12:
            continue
        xs, ys = np.meshgrid(np.arange(minx, maxx), np.arange(miny, maxy))
        w1 = ((xs-a0[0])*(a2[1]-a0[1]) - (a2[0]-a0[0])*(ys-a0[1])) / d
        w2 = ((a1[0]-a0[0])*(ys-a0[1]) - (xs-a0[0])*(a1[1]-a0[1])) / d
        w0 = 1 - w1 - w2
        dentro = (w0 >= 0) & (w1 >= 0) & (w2 >= 0)
        if not dentro.any():
            continue
        z = w0*a0[2] + w1*a1[2] + w2*a2[2]
        sub = zbuf[miny:maxy, minx:maxx]
        gana = dentro & (z > sub)
        sub[gana] = z[gana]
        color = np.clip(base * inten[i], 0, 255).astype(np.uint8)
        img[miny:maxy, minx:maxx][gana] = color
    return Image.fromarray(img)


def main():
    if len(sys.argv) < 3:
        print("uso: render_step.py <entrada> <salida.jpg> [lado]")
        return 1
    entrada, salida = sys.argv[1], sys.argv[2]
    lado = int(sys.argv[3]) if len(sys.argv) > 3 else 256
    if not os.path.exists(entrada):
        return 1
    res = teselar(entrada)
    if not res:
        return 1
    im = render_iso(res[0], res[1], lado)
    if im is None:
        return 1
    im.save(salida, "JPEG", quality=85)
    return 0


if __name__ == '__main__':
    sys.exit(main())
