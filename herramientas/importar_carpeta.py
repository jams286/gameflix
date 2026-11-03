#!/usr/bin/env python3
"""Sube a Gameflix todas las ROMs de una carpeta (sueltas o en .zip), con título limpio
y, si se pide, carátula de libretro-thumbnails.

Usa directamente las funciones de servidor.py contra la misma BD (no pasa por la API,
así que no pide PIN). Respeta GAMEFLIX_BD y GAMEFLIX_ROMS para probar con datos aparte.

    herramientas/importar_carpeta.py /media/datos/Games/roms/gba            # solo muestra qué haría
    herramientas/importar_carpeta.py /media/datos/Games/roms/gba --subir
    herramientas/importar_carpeta.py /media/datos/Games/roms/gba --subir --caratulas
    herramientas/importar_carpeta.py ... --saltar "(E)(Cezar)"                 # no subir esos archivos
    herramientas/importar_carpeta.py --solo-caratulas                        # a los juegos que no tienen

Las carátulas salen de https://thumbnails.libretro.com/<sistema>/Named_Boxarts/, que usa
los nombres No-Intro (los mismos que suelen traer los .gba dentro del zip).
"""

import argparse
import difflib
import hashlib
import io
import re
import sys
import unicodedata
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import servidor  # noqa: E402

THUMBS = 'https://thumbnails.libretro.com/'
SISTEMAS = {
    'nes': 'Nintendo - Nintendo Entertainment System',
    'snes': 'Nintendo - Super Nintendo Entertainment System',
    'gb': 'Nintendo - Game Boy',
    'gbc': 'Nintendo - Game Boy Color',
    'gba': 'Nintendo - Game Boy Advance',
}
LADO_MAX = 1000                     # igual que el admin: se achica si pasa de 1000 px
USER_AGENT = 'gameflix-importar/1.0'

# Títulos que la regla general no deja bien (clave: título ya limpio por la regla)
TITULOS = {
    'Pokémon: Emerald Version': 'Pokémon Emerald',
    'Pokémon: FireRed Version': 'Pokémon FireRed',
    'Pokémon: Leaf Green Version': 'Pokémon LeafGreen',
    'Pokémon: Ruby Version': 'Pokémon Ruby',
    'Pokémon: Sapphire Version': 'Pokémon Sapphire',
    'Pokémon Pinball: Ruby & Sapphire': 'Pokémon Pinball: Ruby & Sapphire',
    'Final Fantasy 1 + 2: Dawn of Souls': 'Final Fantasy I & II: Dawn of Souls',
    'Final Fantasy 4 Advance': 'Final Fantasy IV Advance',
    'Final Fantasy 5 Advance': 'Final Fantasy V Advance',
    'Final Fantasy 6 Advance': 'Final Fantasy VI Advance',
    "Dragonball Z: Buu's Fury": "Dragon Ball Z: Buu's Fury",
    'Classic NES Series: Super Mario Bros.': 'Super Mario Bros. (Classic NES Series)',
    'Super Mario Advance 2: Super Mario World': 'Super Mario Advance 2: Super Mario World',
    'Kirby & The Amazing Mirror': 'Kirby & the Amazing Mirror',
    'Mario Tennis Advance: Power Tour': 'Mario Tennis: Power Tour',
    'Medabots: Metabee': 'Medabots: Metabee',
    'The SpongeBob SquarePants Movie': 'The SpongeBob SquarePants Movie',
    'Yoshi\'s Island: Super Mario Advance 3': "Super Mario Advance 3: Yoshi's Island",
    'Yu-Gi-Oh! 7 Trials to Glory World Championship Tournament 2005': 'Yu-Gi-Oh! 7 Trials to Glory: WCT 2005',
    'Zatchbell! Electric Arena': 'Zatch Bell! Electric Arena',
    'The Legend Of Zelda: A Link To The Past': 'The Legend of Zelda: A Link to the Past',
    'Final Fantasy: Tactics Advanced': 'Final Fantasy Tactics Advance',
}

# Carátulas que no salen solas (clave: título final)
CARATULAS = {
    "Super Mario Advance 3: Yoshi's Island": "Super Mario Advance 3 - Yoshi's Island (Europe) (En,Fr,De,Es,It)",
}


# ---------- Leer la carpeta ----------

def rom_de(ruta):
    """(nombre interno, bytes) de un archivo suelto o de la ROM más grande de un .zip."""
    datos = ruta.read_bytes()
    if datos[:4] == b'PK\x03\x04':
        with zipfile.ZipFile(io.BytesIO(datos)) as z:
            candidatos = [i for i in z.infolist() if Path(i.filename).suffix.lower() in servidor.EXTENSIONES]
            if not candidatos:
                raise ValueError('el .zip no trae ninguna ROM conocida')
            info = max(candidatos, key=lambda i: i.file_size)
            return Path(info.filename).name, z.read(info)
    return ruta.name, datos


# ---------- Títulos ----------

def nombre_base(nombre):
    """El nombre sin extensión, sin numeración de release ("1840 - "), sin "# GBA",
    sin etiquetas (USA), [!] ni "_" en lugar de ":"."""
    base = Path(nombre).stem
    base = re.sub(r'^\d{3,4}\s*-\s*', '', base)
    base = re.sub(r'\s*#.*$', '', base)
    base = re.sub(r'\s*\([^)]*\)|\s*\[[^\]]*\]', '', base)
    base = re.sub(r'\s*_\s*', ': ', base)            # "Metroid_ Zero Mission" (el ":" no cabe en archivos)
    base = re.sub(r'\s+GBA$', '', base)
    return re.sub(r'\s+', ' ', base).strip(' -:')


def titulo_limpio(nombre):
    t = nombre_base(nombre)
    t = re.sub(r'^(.*?), The\b', r'The \1', t)      # "Legend of Zelda, The - X" -> "The Legend of Zelda - X"
    t = t.replace(' - ', ': ', 1).replace(' - ', ' ').replace('!: ', '! ')
    t = re.sub(r'\bPokemon\b', 'Pokémon', t)
    return TITULOS.get(t, t)


# ---------- Carátulas ----------

def pedir(url):
    req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def indice(consola, cache={}):
    """Nombres (sin .png) de las carátulas disponibles para la consola."""
    if consola not in cache:
        url = THUMBS + urllib.parse.quote(SISTEMAS[consola]) + '/Named_Boxarts/'
        html = pedir(url).decode('utf-8', 'replace')
        nombres = {urllib.parse.unquote(h)[:-4] for h in re.findall(r'href="([^"/?]+\.png)"', html)}
        cache[consola] = sorted(nombres)
    return cache[consola]


def para_archivo(nombre):
    """libretro cambia &*/:`<>?\\| por _ en los nombres de archivo."""
    return re.sub(r'[&*/:`<>?\\|"]', '_', nombre)


def comparable(texto):
    texto = unicodedata.normalize('NFKD', texto).encode('ascii', 'ignore').decode().lower()
    texto = re.sub(r'\b(the|version|advance)\b', ' ', texto)
    texto = texto.replace('&', ' and ').replace('dragonball', 'dragon ball')
    return re.sub(r'[^a-z0-9]+', ' ', texto).strip()


PREFERIDAS = ('(USA', '(World', '(USA, Europe', '(Europe')


def buscar_caratula(consola, nombre_rom, titulo):
    """(nombre en libretro, cómo se encontró) o (None, motivo)."""
    disponibles = indice(consola)
    if titulo in CARATULAS and CARATULAS[titulo] in disponibles:
        return CARATULAS[titulo], 'a mano'
    exacto = para_archivo(Path(nombre_rom).stem)
    if exacto in disponibles:
        return exacto, 'exacta'
    # Mismo juego, otra revisión o región: comparo solo el nombre sin etiquetas
    objetivo = {comparable(nombre_base(nombre_rom)), comparable(titulo)}
    por_base = {}
    for d in disponibles:
        por_base.setdefault(comparable(re.sub(r'\s*\(.*$', '', d.replace('_ ', ': '))), []).append(d)
    for o in objetivo:
        if o in por_base:
            opciones = sorted(por_base[o], key=lambda d: (not any(p in d for p in PREFERIDAS), d))
            return opciones[0], 'misma base'
    # Lo más parecido (lo reviso a mano antes de aceptarlo)
    mejor = difflib.get_close_matches(comparable(titulo), list(por_base), n=1, cutoff=0.75)
    if mejor:
        opciones = sorted(por_base[mejor[0]], key=lambda d: (not any(p in d for p in PREFERIDAS), d))
        return opciones[0], 'parecida'
    return None, 'no encontrada'


def bajar_caratula(consola, nombre):
    url = (THUMBS + urllib.parse.quote(SISTEMAS[consola]) + '/Named_Boxarts/'
           + urllib.parse.quote(nombre + '.png'))
    datos = pedir(url)
    from PIL import Image
    img = Image.open(io.BytesIO(datos))
    img.load()
    if img.mode not in ('RGB', 'RGBA'):
        img = img.convert('RGBA')
    if max(img.size) > LADO_MAX:
        img.thumbnail((LADO_MAX, LADO_MAX), Image.LANCZOS)
    salida = io.BytesIO()
    if img.mode == 'RGBA' and img.getextrema()[3][0] < 255:
        img.save(salida, 'PNG', optimize=True)
    else:
        img.convert('RGB').save(salida, 'JPEG', quality=88)
    if salida.tell() > servidor.MAX_CARATULA:
        raise ValueError('la carátula quedó demasiado grande')
    return salida.getvalue()


# ---------- Principal ----------

def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('carpeta', nargs='?', type=Path)
    p.add_argument('--subir', action='store_true', help='subir de verdad (sin esto solo muestra el plan)')
    p.add_argument('--caratulas', action='store_true', help='buscar y poner carátula a lo que se sube')
    p.add_argument('--solo-caratulas', action='store_true',
                   help='no sube nada: pone carátula a los juegos de la BD que no tienen')
    p.add_argument('--aceptar-parecidas', action='store_true',
                   help='poner también las carátulas encontradas por parecido (revisarlas antes)')
    p.add_argument('--saltar', action='append', default=[], metavar='TEXTO',
                   help='no subir los archivos cuyo nombre contenga TEXTO (se puede repetir)')
    a = p.parse_args()
    servidor.preparar_bd()

    if a.solo_caratulas:
        with servidor.conectar() as con:
            filas = con.execute('SELECT id, consola, titulo FROM juegos WHERE caratula IS NULL').fetchall()
        for f in filas:
            poner(f['id'], f['consola'], f['titulo'], f['titulo'], a)
        return

    if not a.carpeta:
        p.error('falta la carpeta')
    with servidor.conectar() as con:
        ya = {f['sha1']: f['titulo'] for f in con.execute('SELECT sha1, titulo FROM juegos')}
    for ruta in sorted(a.carpeta.iterdir(), key=lambda r: r.name.lower()):
        if not ruta.is_file():
            continue
        if any(t in ruta.name for t in a.saltar):
            print(f'  - {ruta.name}: saltado')
            continue
        try:
            nombre, datos = rom_de(ruta)
            consola = servidor.consola_de(nombre, datos)
        except ValueError as e:
            print(f'  ✗ {ruta.name}: {e}')
            continue
        sha1 = hashlib.sha1(datos).hexdigest()
        titulo = titulo_limpio(nombre)
        if sha1 in ya:
            print(f'  = {ruta.name}: ya está como "{ya[sha1]}"')
            continue
        if not a.subir:
            print(f'  + [{consola}] {titulo:45}  ← {nombre}')
            if a.caratulas:
                encontrada, como = buscar_caratula(consola, nombre, titulo)
                print(f'        carátula {como}: {encontrada}')
            continue
        juego = servidor.subir_juego({'nombre': [nombre], 'titulo': [titulo]}, datos)
        ya[sha1] = titulo
        print(f'  + [{consola}] {titulo}  (id {juego["id"]})')
        if a.caratulas:
            poner(juego['id'], consola, nombre, titulo, a)


def poner(juego_id, consola, nombre_rom, titulo, a):
    try:
        encontrada, como = buscar_caratula(consola, nombre_rom, titulo)
        if not encontrada or (como == 'parecida' and not a.aceptar_parecidas):
            print(f'        sin carátula ({como}{": " + encontrada if encontrada else ""})')
            return
        servidor.poner_caratula(juego_id, bajar_caratula(consola, encontrada))
        print(f'        carátula {como}: {encontrada}')
    except Exception as e:  # una carátula que falla no frena el resto
        print(f'        carátula falló: {e}')


if __name__ == '__main__':
    main()
