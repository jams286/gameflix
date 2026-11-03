#!/usr/bin/env python3
"""Arma datos/generos.json con el género de cada juego según libretro-database.

libretro publica en metadat/genre/<sistema>.dat el género de cada ROM identificada por su CRC32
(el mismo que guarda Gameflix en juegos.crc32). Aquí se baja, se traduce a las categorías en
español de Gameflix y se guarda como {consola: {categoría: [crc, ...]}}. servidor.py lo lee al
arrancar. Correrlo de nuevo solo hace falta para actualizar los datos.

    herramientas/generos_libretro.py
"""

import json
import re
import urllib.parse
import urllib.request
from pathlib import Path

DESTINO = Path(__file__).resolve().parent.parent / 'datos' / 'generos.json'
BASE = 'https://raw.githubusercontent.com/libretro/libretro-database/master/metadat/genre/'
SISTEMAS = {
    'nes': 'Nintendo - Nintendo Entertainment System',
    'snes': 'Nintendo - Super Nintendo Entertainment System',
    'gb': 'Nintendo - Game Boy',
    'gbc': 'Nintendo - Game Boy Color',
    'gba': 'Nintendo - Game Boy Advance',
}
# Género de libretro -> categoría de Gameflix (lo que no está aquí queda sin categoría: "Otros")
CATEGORIAS = {
    'Action': 'Acción',
    'Adventure': 'Aventura',
    'Platform': 'Plataformas',
    'Role-playing (RPG)': 'RPG',
    'Strategy': 'Estrategia',
    'Simulation': 'Simulación',
    'Puzzle': 'Puzzle', 'Thinking': 'Puzzle',
    'Fighting': 'Peleas', "Beat'em Up": 'Peleas',
    'Shooter': 'Disparos', "Shoot'em Up": 'Disparos', 'Lightgun Shooter': 'Disparos',
    'Racing': 'Carreras',
    'Sports': 'Deportes', 'Sports with Animals': 'Deportes', 'Hunting and Fishing': 'Deportes',
    'Board': 'Cartas y mesa', 'Card': 'Cartas y mesa', 'Gambling': 'Cartas y mesa',
    'Casual Game': 'Casual', 'Pinball': 'Casual', 'Quiz': 'Casual', 'Music / Dancing': 'Casual',
    'Educational': 'Casual',
}


def main():
    salida = {}
    for consola, sistema in SISTEMAS.items():
        req = urllib.request.Request(BASE + urllib.parse.quote(sistema + '.dat'),
                                     headers={'User-Agent': 'gameflix-generos/1.0'})
        with urllib.request.urlopen(req, timeout=60) as r:
            texto = r.read().decode('utf-8', 'replace')
        por_categoria = {}
        for genero, crc in re.findall(r'genre "([^"]+)"\s*rom \( crc ([0-9A-Fa-f]{8})', texto):
            categoria = CATEGORIAS.get(genero)
            if categoria:
                por_categoria.setdefault(categoria, set()).add(crc.lower())
        salida[consola] = {c: sorted(crcs) for c, crcs in sorted(por_categoria.items())}
        print(f'{consola}: {sum(map(len, por_categoria.values()))} juegos con género')
    DESTINO.parent.mkdir(exist_ok=True)
    DESTINO.write_text(json.dumps(salida, ensure_ascii=False, separators=(',', ':')) + '\n', encoding='utf-8')
    print(f'-> {DESTINO} ({DESTINO.stat().st_size // 1024} KB)')


if __name__ == '__main__':
    main()
