"""Servicio de Gameflix: perfiles, catálogo de juegos retro, ROMs, carátulas y partidas.

Escucha solo en 127.0.0.1; nginx publica /gameflix/api/ -> /api/.
Sin dependencias externas (solo la biblioteca estándar).

    python3 servidor.py

Sesión: al elegir perfil (POST /api/entrar) se guarda una cookie `gameflix` con un token.
Todo lo demás pide esa cookie; lo de /api/admin/ además pide que el perfil sea admin.

Partidas de cada perfil en cada juego:
    save     la memoria con batería del cartucho (lo que el juego guarda por sí solo).
             Se guarda cada versión distinta y se conservan las últimas MAX_HISTORIAL.
    estados  "fotos" de la máquina completa en RANURAS ranuras, con una captura de pantalla.

Rutas:
    GET    /api/perfiles                         perfiles + el perfil de la sesión (o null)
    POST   /api/entrar                           {"perfil_id", "pin"?} -> pone la cookie
    POST   /api/salir
    GET    /api/catalogo                         consolas con sus juegos y "seguir jugando"
    GET    /api/juegos/<id>                      juego + estado de su save y sus ranuras
    GET    /api/juegos/<id>/rom/<nombre>         la ROM (el nombre solo importa a EmulatorJS)
    POST   /api/juegos/<id>/tiempo               {"segundos"} jugados desde el último aviso (para sugerir)
    GET    /api/juegos/<id>/caratula             imagen
    GET    /api/juegos/<id>/save                 último save del perfil (204 si no hay)
    PUT    /api/juegos/<id>/save                 cuerpo: bytes del save
    GET    /api/juegos/<id>/saves                historial del save
    POST   /api/juegos/<id>/saves/<sid>/restaurar
    GET    /api/juegos/<id>/estados/<n>          bytes del estado
    GET    /api/juegos/<id>/estados/<n>/captura  PNG
    PUT    /api/juegos/<id>/estados/<n>          cuerpo: largo de la captura (4 bytes) + captura + estado
    DELETE /api/juegos/<id>/estados/<n>
    POST   /api/admin/juegos?nombre=&consola=&titulo=   cuerpo: la ROM (o un .zip con ella)
    PATCH  /api/admin/juegos/<id>                {"titulo"?, "consola"?, "genero"?}
    DELETE /api/admin/juegos/<id>
    PUT    /api/admin/juegos/<id>/caratula       cuerpo: imagen JPEG, PNG o WebP
    DELETE /api/admin/juegos/<id>/caratula
    POST   /api/admin/perfiles                   {"nombre", "avatar", "color", "admin", "pin"}
    PATCH  /api/admin/perfiles/<id>              lo mismo, todo opcional ("pin": "" lo quita)
    DELETE /api/admin/perfiles/<id>
"""

import hashlib
import hmac
import io
import json
import os
import re
import secrets
import sqlite3
import struct
import threading
import time
import zipfile
import zlib
from datetime import datetime
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

HOST = '127.0.0.1'
# Se pueden cambiar para pruebas sin tocar los datos reales
PUERTO = int(os.environ.get('GAMEFLIX_PUERTO', 8777))
BD = Path(os.environ.get('GAMEFLIX_BD', Path.home() / '.local/share/casa/gameflix.db'))
ROMS = Path(os.environ.get('GAMEFLIX_ROMS', Path.home() / '.local/share/casa/gameflix-roms'))

COOKIE = 'gameflix'
RUTA_COOKIE = '/gameflix/api/'
MAX_JSON = 8 * 1024
MAX_ROM = 38 * 1024 * 1024        # GBA llega a 32 MB; nginx corta en 40 MB
MAX_SAVE = 1024 * 1024            # los saves de cartucho no pasan de 128 KB
MAX_ESTADO = 12 * 1024 * 1024
MAX_CARATULA = 3 * 1024 * 1024
MAX_TITULO, MAX_NOMBRE = 60, 20
MAX_HISTORIAL = 10
RANURAS = 3

CONSOLAS = {  # en el orden en que salen en la app
    'nes':  {'nombre': 'NES',              'core': 'fceumm',   'ext': ('.nes',)},
    'snes': {'nombre': 'Super Nintendo',   'core': 'snes9x',   'ext': ('.sfc', '.smc')},
    'gb':   {'nombre': 'Game Boy',         'core': 'gambatte', 'ext': ('.gb',)},
    'gbc':  {'nombre': 'Game Boy Color',   'core': 'gambatte', 'ext': ('.gbc',)},
    'gba':  {'nombre': 'Game Boy Advance', 'core': 'mgba',     'ext': ('.gba',)},
}
EXTENSIONES = {ext: c for c, info in CONSOLAS.items() for ext in info['ext']}
TIPOS_IMAGEN = {b'\xff\xd8\xff': 'image/jpeg', b'\x89PNG': 'image/png', b'RIFF': 'image/webp'}
COLORES = ['#e50914', '#2e86ab', '#7fb069', '#a15dd1', '#f2a541', '#d6457b', '#17a398', '#6c757d']
# Categorías de juego (en este orden salen en el admin). Se llenan solas con datos/generos.json
# (libretro-database por CRC32, ver herramientas/generos_libretro.py); sin dato, "Otros".
GENEROS = ['Acción', 'Aventura', 'Plataformas', 'RPG', 'Estrategia', 'Simulación', 'Puzzle', 'Peleas',
           'Disparos', 'Carreras', 'Deportes', 'Cartas y mesa', 'Casual', 'Otros']
ARCHIVO_GENEROS = Path(__file__).resolve().parent / 'datos' / 'generos.json'
MAX_TIEMPO = 180                  # segundos que cuenta un aviso de tiempo jugado (llegan cada minuto)
SUGERIDOS = 10
PERFILES_INICIALES = [('Jams', '🎮', '#e50914', 1), ('Victor', '🦖', '#2e86ab', 0)]

candado = threading.Lock()   # una escritura a la vez


class NoAutorizado(Exception):
    """Sin sesión válida (401) o sin permiso de admin (403)."""

    def __init__(self, mensaje, codigo=401):
        super().__init__(mensaje)
        self.codigo = codigo


class NoExiste(Exception):
    pass


# ---------- Base de datos ----------

def conectar():
    con = sqlite3.connect(BD, timeout=10)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA foreign_keys = ON')
    return con


def preparar_bd():
    BD.parent.mkdir(parents=True, exist_ok=True)
    ROMS.mkdir(parents=True, exist_ok=True)
    with conectar() as con:
        con.executescript('''
            PRAGMA journal_mode = WAL;
            CREATE TABLE IF NOT EXISTS perfiles (
                id       INTEGER PRIMARY KEY,
                nombre   TEXT NOT NULL,
                avatar   TEXT NOT NULL,
                color    TEXT NOT NULL,
                pin      TEXT,                 -- "sal$hash" (PBKDF2) o NULL si no tiene
                admin    INTEGER NOT NULL DEFAULT 0,
                creado   TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sesiones (
                token     TEXT PRIMARY KEY,
                perfil_id INTEGER NOT NULL REFERENCES perfiles(id) ON DELETE CASCADE,
                creada    TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS juegos (
                id               INTEGER PRIMARY KEY,
                consola          TEXT NOT NULL,
                titulo           TEXT NOT NULL,
                archivo          TEXT NOT NULL,   -- nombre dentro de ROMS
                sha1             TEXT NOT NULL UNIQUE,
                crc32            TEXT NOT NULL,
                tamano           INTEGER NOT NULL,
                caratula         BLOB,
                caratula_tipo    TEXT,
                caratula_version INTEGER NOT NULL DEFAULT 0,
                creado           TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS saves (
                id        INTEGER PRIMARY KEY,
                perfil_id INTEGER NOT NULL REFERENCES perfiles(id) ON DELETE CASCADE,
                juego_id  INTEGER NOT NULL REFERENCES juegos(id) ON DELETE CASCADE,
                datos     BLOB NOT NULL,
                sha1      TEXT NOT NULL,
                creado    TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS saves_perfil_juego ON saves (perfil_id, juego_id, id);
            CREATE TABLE IF NOT EXISTS estados (
                perfil_id INTEGER NOT NULL REFERENCES perfiles(id) ON DELETE CASCADE,
                juego_id  INTEGER NOT NULL REFERENCES juegos(id) ON DELETE CASCADE,
                ranura    INTEGER NOT NULL,
                datos     BLOB NOT NULL,
                captura   BLOB,
                creado    TEXT NOT NULL,
                PRIMARY KEY (perfil_id, juego_id, ranura)
            );
            CREATE TABLE IF NOT EXISTS jugados (
                perfil_id INTEGER NOT NULL REFERENCES perfiles(id) ON DELETE CASCADE,
                juego_id  INTEGER NOT NULL REFERENCES juegos(id) ON DELETE CASCADE,
                ultima_vez TEXT NOT NULL,
                veces     INTEGER NOT NULL DEFAULT 1,
                PRIMARY KEY (perfil_id, juego_id)
            );
        ''')
        migrar(con)
        if not con.execute('SELECT 1 FROM perfiles').fetchone():
            for nombre, avatar, color, admin in PERFILES_INICIALES:
                con.execute('INSERT INTO perfiles (nombre, avatar, color, admin, creado) VALUES (?, ?, ?, ?, ?)',
                            (nombre, avatar, color, admin, ahora()))


def cargar_generos():
    """{(consola, crc32): categoría} desde datos/generos.json (vacío si no está)."""
    try:
        datos = json.loads(ARCHIVO_GENEROS.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}
    return {(consola, crc): categoria
            for consola, categorias in datos.items()
            for categoria, crcs in categorias.items() for crc in crcs}


GENERO_POR_CRC = cargar_generos()


def genero_de(consola, crc):
    # GB y GBC comparten juegos (los duales están en las dos listas de libretro)
    otras = {'gb': 'gbc', 'gbc': 'gb'}
    return GENERO_POR_CRC.get((consola, crc)) or GENERO_POR_CRC.get((otras.get(consola), crc))


def migrar(con):
    """Columnas que se agregaron después de la v1."""
    columnas = {f[1] for f in con.execute('PRAGMA table_info(juegos)')}
    if 'genero' not in columnas:
        con.execute('ALTER TABLE juegos ADD COLUMN genero TEXT')   # NULL = sin dato ("Otros")
        for f in con.execute('SELECT id, consola, crc32 FROM juegos').fetchall():
            con.execute('UPDATE juegos SET genero = ? WHERE id = ?', (genero_de(f[1], f[2]), f[0]))
    if 'segundos' not in {f[1] for f in con.execute('PRAGMA table_info(jugados)')}:
        con.execute('ALTER TABLE jugados ADD COLUMN segundos INTEGER NOT NULL DEFAULT 0')


def ahora():
    return datetime.now().isoformat(timespec='seconds')


def limpiar_texto(valor, maximo):
    if not isinstance(valor, str):
        return ''
    return re.sub(r'\s+', ' ', valor).strip()[:maximo]


# ---------- Perfiles y sesiones ----------

def hash_pin(pin, sal=None):
    sal = sal or secrets.token_hex(8)
    h = hashlib.pbkdf2_hmac('sha256', pin.encode(), bytes.fromhex(sal), 100_000).hex()
    return f'{sal}${h}'


def pin_correcto(guardado, pin):
    sal, _ = guardado.split('$', 1)
    return hmac.compare_digest(hash_pin(pin, sal), guardado)


def perfil_publico(f):
    return {'id': f['id'], 'nombre': f['nombre'], 'avatar': f['avatar'], 'color': f['color'],
            'tiene_pin': f['pin'] is not None, 'admin': bool(f['admin'])}


def perfil_de_sesion(con, token):
    if not token:
        return None
    return con.execute('SELECT p.* FROM sesiones s JOIN perfiles p ON p.id = s.perfil_id WHERE s.token = ?',
                       (token,)).fetchone()


def listar_perfiles(con, token):
    actual = perfil_de_sesion(con, token)
    return {'perfiles': [perfil_publico(f) for f in con.execute('SELECT * FROM perfiles ORDER BY id')],
            'actual': perfil_publico(actual) if actual else None}


def entrar(datos):
    perfil_id = datos.get('perfil_id')
    with candado, conectar() as con:
        f = con.execute('SELECT * FROM perfiles WHERE id = ?', (perfil_id,)).fetchone()
        if not f:
            raise ValueError('Ese perfil ya no existe')
        if f['pin'] is not None and not pin_correcto(f['pin'], str(datos.get('pin') or '')):
            time.sleep(1)   # frena a quien pruebe PINs al azar
            raise NoAutorizado('PIN incorrecto', 403)
        token = secrets.token_urlsafe(24)
        con.execute('INSERT INTO sesiones (token, perfil_id, creada) VALUES (?, ?, ?)', (token, f['id'], ahora()))
        return token, perfil_publico(f)


def salir(token):
    with candado, conectar() as con:
        con.execute('DELETE FROM sesiones WHERE token = ?', (token,))


def validar_perfil(datos, nuevo):
    cambios = {}
    if nuevo or 'nombre' in datos:
        nombre = limpiar_texto(datos.get('nombre'), MAX_NOMBRE)
        if not nombre:
            raise ValueError('Falta el nombre')
        cambios['nombre'] = nombre
    if nuevo or 'avatar' in datos:
        avatar = limpiar_texto(datos.get('avatar'), 8) or '🙂'
        cambios['avatar'] = avatar
    if nuevo or 'color' in datos:
        color = datos.get('color') or COLORES[0]
        if not isinstance(color, str) or not re.fullmatch(r'#[0-9a-fA-F]{6}', color):
            raise ValueError('Color inválido')
        cambios['color'] = color
    if nuevo or 'admin' in datos:
        cambios['admin'] = 1 if datos.get('admin') else 0
    if 'pin' in datos:
        pin = datos.get('pin') or ''
        if pin and not re.fullmatch(r'\d{4,8}', str(pin)):
            raise ValueError('El PIN debe tener de 4 a 8 números')
        cambios['pin'] = hash_pin(str(pin)) if pin else None
    return cambios


def crear_perfil(datos):
    cambios = validar_perfil(datos, nuevo=True)
    with candado, conectar() as con:
        columnas = ', '.join(cambios)
        con.execute(f'INSERT INTO perfiles ({columnas}, creado) VALUES ({", ".join("?" * len(cambios))}, ?)',
                    (*cambios.values(), ahora()))
        return listar_perfiles(con, None)


def cambiar_perfil(perfil_id, datos, yo):
    cambios = validar_perfil(datos, nuevo=False)
    if not cambios:
        raise ValueError('Nada que cambiar')
    with candado, conectar() as con:
        if not con.execute('SELECT 1 FROM perfiles WHERE id = ?', (perfil_id,)).fetchone():
            raise NoExiste()
        if cambios.get('admin') == 0 and perfil_id == yo['id']:
            raise ValueError('No puedes quitarte el admin a ti mismo')
        con.execute(f'UPDATE perfiles SET {", ".join(f"{k} = ?" for k in cambios)} WHERE id = ?',
                    (*cambios.values(), perfil_id))
        if 'pin' in cambios and cambios['pin'] is not None:
            # Con PIN nuevo, los demás dispositivos tienen que volver a ponerlo
            con.execute('DELETE FROM sesiones WHERE perfil_id = ? AND perfil_id != ?', (perfil_id, yo['id']))
        return listar_perfiles(con, None)


def borrar_perfil(perfil_id, yo):
    if perfil_id == yo['id']:
        raise ValueError('No puedes borrar tu propio perfil')
    with candado, conectar() as con:
        con.execute('DELETE FROM perfiles WHERE id = ?', (perfil_id,))
        return listar_perfiles(con, None)


# ---------- Catálogo ----------

def juego_publico(f):
    return {'id': f['id'], 'consola': f['consola'], 'titulo': f['titulo'], 'tamano': f['tamano'],
            'ext': Path(f['archivo']).suffix, 'genero': f['genero'] or 'Otros',
            'caratula': f['caratula_version'] if f['caratula_tipo'] else None}


def leer_catalogo(con, perfil):
    juegos = con.execute('''
        SELECT j.*, g.ultima_vez,
               EXISTS(SELECT 1 FROM saves s WHERE s.perfil_id = :p AND s.juego_id = j.id) AS con_save
        FROM juegos j LEFT JOIN jugados g ON g.juego_id = j.id AND g.perfil_id = :p
        ORDER BY j.titulo COLLATE NOCASE
    ''', {'p': perfil['id']}).fetchall()
    consolas = []
    for clave, info in CONSOLAS.items():
        lista = [dict(juego_publico(f), con_save=bool(f['con_save'])) for f in juegos if f['consola'] == clave]
        consolas.append({'id': clave, 'nombre': info['nombre'], 'juegos': lista,
                         'sugeridos': sugerir(con, perfil, juegos, clave)})
    # Todo lo jugado, lo más reciente primero (la app lo separa por consola)
    seguir = [f['id'] for f in sorted((f for f in juegos if f['ultima_vez']),
                                       key=lambda f: f['ultima_vez'], reverse=True)]
    return {'perfil': perfil_publico(perfil), 'consolas': consolas, 'seguir': seguir, 'generos': GENEROS}


def sugerir(con, perfil, juegos, consola):
    """Hasta SUGERIDOS juegos de la consola que el perfil no ha abierto, según cuánto juega cada
    género (lo de la misma consola pesa el doble) y, de desempate, lo que juega el resto de la casa."""
    jugado = {}   # juego_id -> "peso" de lo que lo ha jugado el perfil
    familia = {}  # juego_id -> lo mismo, pero de los demás perfiles
    for f in con.execute('SELECT perfil_id, juego_id, veces, segundos FROM jugados'):
        peso = f['segundos'] + 120 * f['veces']   # abrirlo cuenta aunque no haya tiempo registrado
        destino = jugado if f['perfil_id'] == perfil['id'] else familia
        destino[f['juego_id']] = destino.get(f['juego_id'], 0) + peso
    por_id = {f['id']: f for f in juegos}
    afinidad = {}
    for juego_id, peso in jugado.items():
        f = por_id.get(juego_id)
        if f:
            genero = f['genero'] or 'Otros'
            # "Otros" es un cajón de sastre: dice poco de lo que le gusta
            peso *= (2 if f['consola'] == consola else 1) * (0.3 if genero == 'Otros' else 1)
            afinidad[genero] = afinidad.get(genero, 0) + peso
    tope_afinidad = max(afinidad.values(), default=0) or 1
    tope_familia = max(familia.values(), default=0) or 1
    dia = datetime.now().strftime('%Y%m%d')   # para que el orden de los empates cambie cada día
    candidatos = []
    for f in juegos:
        if f['consola'] != consola or f['id'] in jugado:
            continue
        puntos = afinidad.get(f['genero'] or 'Otros', 0) / tope_afinidad + 0.3 * familia.get(f['id'], 0) / tope_familia
        if puntos > 0:
            azar = hashlib.sha1(f'{dia}-{perfil["id"]}-{f["id"]}'.encode()).hexdigest()
            candidatos.append((-puntos, azar, f['id'], f['genero'] or 'Otros'))
    # Que no salgan todos del mismo género: primero hasta la mitad de cada uno, luego el resto
    elegidos, por_genero = [], {}
    for _, _, juego_id, genero in sorted(candidatos):
        if por_genero.get(genero, 0) < SUGERIDOS // 2:
            elegidos.append(juego_id)
            por_genero[genero] = por_genero.get(genero, 0) + 1
    resto = [c[2] for c in sorted(candidatos) if c[2] not in elegidos]
    return (elegidos + resto)[:SUGERIDOS]


def sumar_tiempo(perfil, juego_id, datos):
    segundos = datos.get('segundos')
    if not isinstance(segundos, (int, float)) or segundos <= 0:
        raise ValueError('Segundos inválidos')
    segundos = int(min(segundos, MAX_TIEMPO))
    with candado, conectar() as con:
        exigir_juego(con, juego_id)
        con.execute('''INSERT INTO jugados (perfil_id, juego_id, ultima_vez, segundos) VALUES (?, ?, ?, ?)
                       ON CONFLICT DO UPDATE SET ultima_vez = excluded.ultima_vez,
                                                 segundos = segundos + excluded.segundos''',
                    (perfil['id'], juego_id, ahora(), segundos))
    return {'ok': True}


def leer_juego(con, perfil, juego_id):
    f = con.execute('SELECT * FROM juegos WHERE id = ?', (juego_id,)).fetchone()
    if not f:
        raise NoExiste()
    save = con.execute('SELECT creado, length(datos) AS tamano FROM saves WHERE perfil_id = ? AND juego_id = ? '
                       'ORDER BY id DESC LIMIT 1', (perfil['id'], juego_id)).fetchone()
    estados = con.execute('SELECT ranura, creado FROM estados WHERE perfil_id = ? AND juego_id = ? ORDER BY ranura',
                          (perfil['id'], juego_id)).fetchall()
    return {'juego': dict(juego_publico(f), core=CONSOLAS[f['consola']]['core'],
                          consola_nombre=CONSOLAS[f['consola']]['nombre']),
            'save': dict(save) if save else None,
            'estados': [dict(e) for e in estados], 'ranuras': RANURAS}


def archivo_rom(con, perfil, juego_id, contar):
    f = con.execute('SELECT archivo FROM juegos WHERE id = ?', (juego_id,)).fetchone()
    if not f:
        raise NoExiste()
    if contar:
        with candado:
            con.execute('''INSERT INTO jugados (perfil_id, juego_id, ultima_vez) VALUES (?, ?, ?)
                           ON CONFLICT DO UPDATE SET ultima_vez = excluded.ultima_vez, veces = veces + 1''',
                        (perfil['id'], juego_id, ahora()))
            con.commit()
    return ROMS / f['archivo']


def sacar_de_zip(datos):
    """Si el archivo es un .zip, devuelve (nombre, bytes) de la ROM más grande que traiga."""
    try:
        z = zipfile.ZipFile(io.BytesIO(datos))
    except zipfile.BadZipFile:
        raise ValueError('El .zip está dañado') from None
    candidatos = [i for i in z.infolist() if Path(i.filename).suffix.lower() in EXTENSIONES]
    if not candidatos:
        raise ValueError('El .zip no trae ninguna ROM conocida (.nes, .sfc, .smc, .gb, .gbc, .gba)')
    info = max(candidatos, key=lambda i: i.file_size)
    if info.file_size > MAX_ROM:
        raise ValueError('La ROM es demasiado grande')
    return Path(info.filename).name, z.read(info)


def titulo_desde_archivo(nombre):
    base = Path(nombre).stem
    base = re.sub(r'_+', ' ', base)
    base = re.sub(r'\s*\[[^\]]*\]', '', base)   # quita marcas tipo [!] o [b1]
    return limpiar_texto(base, MAX_TITULO) or 'Sin nombre'


def consola_de(nombre, datos):
    consola = EXTENSIONES.get(Path(nombre).suffix.lower())
    if not consola:
        raise ValueError('No reconozco la consola por la extensión (.nes, .sfc, .smc, .gb, .gbc, .gba o .zip)')
    # Un .gb que solo corre en Game Boy Color (bandera 0xC0 en la cabecera) va con los de GBC
    if consola == 'gb' and len(datos) > 0x143 and datos[0x143] == 0xC0:
        consola = 'gbc'
    return consola


def subir_juego(consulta, datos):
    nombre = consulta.get('nombre', [''])[0]
    if not datos:
        raise ValueError('No llegó ningún archivo')
    if datos[:4] == b'PK\x03\x04' or nombre.lower().endswith('.zip'):
        nombre, datos = sacar_de_zip(datos)
    consola = consulta.get('consola', [''])[0] or consola_de(nombre, datos)
    if consola not in CONSOLAS:
        raise ValueError('Consola inválida')
    titulo = limpiar_texto(consulta.get('titulo', [''])[0], MAX_TITULO) or titulo_desde_archivo(nombre)
    sha1 = hashlib.sha1(datos).hexdigest()
    ext = Path(nombre).suffix.lower()
    if ext not in CONSOLAS[consola]['ext']:
        ext = CONSOLAS[consola]['ext'][0]
    with candado, conectar() as con:
        repetido = con.execute('SELECT titulo FROM juegos WHERE sha1 = ?', (sha1,)).fetchone()
        if repetido:
            raise ValueError(f'Ese juego ya está en la lista como "{repetido["titulo"]}"')
        archivo = f'{sha1}{ext}'
        temporal = ROMS / (archivo + '.tmp')
        temporal.write_bytes(datos)
        temporal.replace(ROMS / archivo)
        crc = f'{zlib.crc32(datos):08x}'
        cur = con.execute('''INSERT INTO juegos (consola, titulo, archivo, sha1, crc32, tamano, creado, genero)
                             VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                          (consola, titulo, archivo, sha1, crc, len(datos), ahora(), genero_de(consola, crc)))
        return juego_publico(con.execute('SELECT * FROM juegos WHERE id = ?', (cur.lastrowid,)).fetchone())


def cambiar_juego(juego_id, datos):
    cambios = {}
    if 'titulo' in datos:
        titulo = limpiar_texto(datos['titulo'], MAX_TITULO)
        if not titulo:
            raise ValueError('El título no puede quedar vacío')
        cambios['titulo'] = titulo
    if 'consola' in datos:
        if datos['consola'] not in CONSOLAS:
            raise ValueError('Consola inválida')
        cambios['consola'] = datos['consola']
    if 'genero' in datos:
        if datos['genero'] not in GENEROS:
            raise ValueError('Categoría inválida')
        cambios['genero'] = datos['genero']
    if not cambios:
        raise ValueError('Nada que cambiar')
    with candado, conectar() as con:
        f = con.execute('SELECT * FROM juegos WHERE id = ?', (juego_id,)).fetchone()
        if not f:
            raise NoExiste()
        if 'consola' in cambios and CONSOLAS[cambios['consola']]['core'] != CONSOLAS[f['consola']]['core']:
            raise ValueError('Solo se puede mover entre Game Boy y Game Boy Color (usan el mismo emulador)')
        con.execute(f'UPDATE juegos SET {", ".join(f"{k} = ?" for k in cambios)} WHERE id = ?',
                    (*cambios.values(), juego_id))
        return juego_publico(con.execute('SELECT * FROM juegos WHERE id = ?', (juego_id,)).fetchone())


def borrar_juego(juego_id):
    with candado, conectar() as con:
        f = con.execute('SELECT archivo FROM juegos WHERE id = ?', (juego_id,)).fetchone()
        if not f:
            raise NoExiste()
        con.execute('DELETE FROM juegos WHERE id = ?', (juego_id,))
        (ROMS / f['archivo']).unlink(missing_ok=True)
        return {'ok': True}


def poner_caratula(juego_id, datos):
    tipo = next((t for firma, t in TIPOS_IMAGEN.items() if datos.startswith(firma)), None)
    if not tipo or (tipo == 'image/webp' and datos[8:12] != b'WEBP'):
        raise ValueError('La carátula debe ser JPEG, PNG o WebP')
    with candado, conectar() as con:
        if not con.execute('''UPDATE juegos SET caratula = ?, caratula_tipo = ?, caratula_version = caratula_version + 1
                              WHERE id = ?''', (datos, tipo, juego_id)).rowcount:
            raise NoExiste()
        return juego_publico(con.execute('SELECT * FROM juegos WHERE id = ?', (juego_id,)).fetchone())


def quitar_caratula(juego_id):
    with candado, conectar() as con:
        if not con.execute('''UPDATE juegos SET caratula = NULL, caratula_tipo = NULL,
                              caratula_version = caratula_version + 1 WHERE id = ?''', (juego_id,)).rowcount:
            raise NoExiste()
        return juego_publico(con.execute('SELECT * FROM juegos WHERE id = ?', (juego_id,)).fetchone())


# ---------- Partidas ----------

def exigir_juego(con, juego_id):
    if not con.execute('SELECT 1 FROM juegos WHERE id = ?', (juego_id,)).fetchone():
        raise NoExiste()


def guardar_save(perfil, juego_id, datos):
    if not datos:
        raise ValueError('El save llegó vacío')
    sha1 = hashlib.sha1(datos).hexdigest()
    with candado, conectar() as con:
        exigir_juego(con, juego_id)
        ultimo = con.execute('SELECT sha1, creado FROM saves WHERE perfil_id = ? AND juego_id = ? ORDER BY id DESC LIMIT 1',
                             (perfil['id'], juego_id)).fetchone()
        if ultimo and ultimo['sha1'] == sha1:
            return {'nuevo': False, 'creado': ultimo['creado'], 'sha1': sha1}
        creado = ahora()
        con.execute('INSERT INTO saves (perfil_id, juego_id, datos, sha1, creado) VALUES (?, ?, ?, ?, ?)',
                    (perfil['id'], juego_id, datos, sha1, creado))
        con.execute('''DELETE FROM saves WHERE perfil_id = ? AND juego_id = ? AND id NOT IN (
                           SELECT id FROM saves WHERE perfil_id = ? AND juego_id = ? ORDER BY id DESC LIMIT ?)''',
                    (perfil['id'], juego_id, perfil['id'], juego_id, MAX_HISTORIAL))
        return {'nuevo': True, 'creado': creado, 'sha1': sha1}


def historial_saves(con, perfil, juego_id):
    exigir_juego(con, juego_id)
    filas = con.execute('SELECT id, creado, length(datos) AS tamano FROM saves WHERE perfil_id = ? AND juego_id = ? '
                        'ORDER BY id DESC', (perfil['id'], juego_id)).fetchall()
    return {'saves': [dict(f) for f in filas]}


def restaurar_save(perfil, juego_id, save_id):
    with conectar() as con:
        f = con.execute('SELECT datos FROM saves WHERE id = ? AND perfil_id = ? AND juego_id = ?',
                        (save_id, perfil['id'], juego_id)).fetchone()
    if not f:
        raise NoExiste()
    # Se vuelve a guardar como el más reciente; si ya era el último, no cambia nada
    with candado, conectar() as con:
        con.execute('INSERT INTO saves (perfil_id, juego_id, datos, sha1, creado) VALUES (?, ?, ?, ?, ?)',
                    (perfil['id'], juego_id, f['datos'], hashlib.sha1(f['datos']).hexdigest(), ahora()))
        con.execute('''DELETE FROM saves WHERE perfil_id = ? AND juego_id = ? AND id NOT IN (
                           SELECT id FROM saves WHERE perfil_id = ? AND juego_id = ? ORDER BY id DESC LIMIT ?)''',
                    (perfil['id'], juego_id, perfil['id'], juego_id, MAX_HISTORIAL))
    with conectar() as con:
        return historial_saves(con, perfil, juego_id)


def validar_ranura(n):
    if not 1 <= n <= RANURAS:
        raise ValueError('Ranura inválida')
    return n


def guardar_estado(perfil, juego_id, ranura, cuerpo):
    validar_ranura(ranura)
    if len(cuerpo) < 4:
        raise ValueError('Estado inválido')
    largo = struct.unpack('>I', cuerpo[:4])[0]
    captura, datos = cuerpo[4:4 + largo], cuerpo[4 + largo:]
    if len(captura) != largo or not datos:
        raise ValueError('Estado inválido')
    if captura and not captura.startswith(b'\x89PNG'):
        captura = b''
    creado = ahora()
    with candado, conectar() as con:
        exigir_juego(con, juego_id)
        con.execute('''INSERT OR REPLACE INTO estados (perfil_id, juego_id, ranura, datos, captura, creado)
                       VALUES (?, ?, ?, ?, ?, ?)''', (perfil['id'], juego_id, ranura, datos, captura or None, creado))
    return {'ranura': ranura, 'creado': creado}


def borrar_estado(perfil, juego_id, ranura):
    with candado, conectar() as con:
        con.execute('DELETE FROM estados WHERE perfil_id = ? AND juego_id = ? AND ranura = ?',
                    (perfil['id'], juego_id, validar_ranura(ranura)))
    return {'ok': True}


# ---------- HTTP ----------

class Binario:
    """Respuesta que no es JSON: bytes o un archivo."""

    def __init__(self, tipo, datos=None, archivo=None, cache=False, extra=None):
        self.tipo, self.datos, self.archivo, self.cache, self.extra = tipo, datos, archivo, cache, extra or {}


def blob(con, sql, params, tipo):
    f = con.execute(sql, params).fetchone()
    if not f or f[0] is None:
        raise NoExiste()
    return Binario(tipo, datos=f[0])


def ultimo_save(con, perfil, juego_id):
    exigir_juego(con, juego_id)
    f = con.execute('SELECT datos, sha1, creado FROM saves WHERE perfil_id = ? AND juego_id = ? ORDER BY id DESC LIMIT 1',
                    (perfil['id'], juego_id)).fetchone()
    if not f:
        return None   # 204
    return Binario('application/octet-stream', datos=f['datos'], extra={'X-Sha1': f['sha1'], 'X-Creado': f['creado']})


def caratula(con, juego_id):
    f = con.execute('SELECT caratula, caratula_tipo FROM juegos WHERE id = ?', (juego_id,)).fetchone()
    if not f or f['caratula'] is None:
        raise NoExiste()
    return Binario(f['caratula_tipo'], datos=f['caratula'], cache=True)


# (método, patrón, quién: 'libre' | 'perfil' | 'admin', cuerpo: 'json' | máximo en bytes | None, acción)
# La acción recibe (m, datos, perfil, con, consulta)
RUTAS = [
    ('GET',    r'/api/perfiles', 'libre', None, None),            # se atienden aparte (cookies)
    ('POST',   r'/api/entrar', 'libre', 'json', None),
    ('POST',   r'/api/salir', 'libre', None, None),
    ('GET',    r'/api/catalogo', 'perfil', None, lambda m, d, p, c, q: leer_catalogo(c, p)),
    ('GET',    r'/api/juegos/(\d+)', 'perfil', None, lambda m, d, p, c, q: leer_juego(c, p, int(m[1]))),
    ('GET',    r'/api/juegos/(\d+)/rom/[^/]+', 'perfil', None, None),   # archivo, se atiende aparte
    ('POST',   r'/api/juegos/(\d+)/tiempo', 'perfil', 'json', lambda m, d, p, c, q: sumar_tiempo(p, int(m[1]), d)),
    ('GET',    r'/api/juegos/(\d+)/caratula', 'perfil', None, lambda m, d, p, c, q: caratula(c, int(m[1]))),
    ('GET',    r'/api/juegos/(\d+)/save', 'perfil', None, lambda m, d, p, c, q: ultimo_save(c, p, int(m[1]))),
    ('PUT',    r'/api/juegos/(\d+)/save', 'perfil', MAX_SAVE, lambda m, d, p, c, q: guardar_save(p, int(m[1]), d)),
    ('GET',    r'/api/juegos/(\d+)/saves', 'perfil', None, lambda m, d, p, c, q: historial_saves(c, p, int(m[1]))),
    ('POST',   r'/api/juegos/(\d+)/saves/(\d+)/restaurar', 'perfil', None,
     lambda m, d, p, c, q: restaurar_save(p, int(m[1]), int(m[2]))),
    ('GET',    r'/api/juegos/(\d+)/estados/(\d+)', 'perfil', None,
     lambda m, d, p, c, q: blob(c, 'SELECT datos FROM estados WHERE perfil_id = ? AND juego_id = ? AND ranura = ?',
                                (p['id'], int(m[1]), int(m[2])), 'application/octet-stream')),
    ('GET',    r'/api/juegos/(\d+)/estados/(\d+)/captura', 'perfil', None,
     lambda m, d, p, c, q: blob(c, 'SELECT captura FROM estados WHERE perfil_id = ? AND juego_id = ? AND ranura = ?',
                                (p['id'], int(m[1]), int(m[2])), 'image/png')),
    ('PUT',    r'/api/juegos/(\d+)/estados/(\d+)', 'perfil', MAX_ESTADO,
     lambda m, d, p, c, q: guardar_estado(p, int(m[1]), int(m[2]), d)),
    ('DELETE', r'/api/juegos/(\d+)/estados/(\d+)', 'perfil', None,
     lambda m, d, p, c, q: borrar_estado(p, int(m[1]), int(m[2]))),
    ('POST',   r'/api/admin/juegos', 'admin', MAX_ROM, lambda m, d, p, c, q: subir_juego(q, d)),
    ('PATCH',  r'/api/admin/juegos/(\d+)', 'admin', 'json', lambda m, d, p, c, q: cambiar_juego(int(m[1]), d)),
    ('DELETE', r'/api/admin/juegos/(\d+)', 'admin', None, lambda m, d, p, c, q: borrar_juego(int(m[1]))),
    ('PUT',    r'/api/admin/juegos/(\d+)/caratula', 'admin', MAX_CARATULA,
     lambda m, d, p, c, q: poner_caratula(int(m[1]), d)),
    ('DELETE', r'/api/admin/juegos/(\d+)/caratula', 'admin', None, lambda m, d, p, c, q: quitar_caratula(int(m[1]))),
    ('POST',   r'/api/admin/perfiles', 'admin', 'json', lambda m, d, p, c, q: crear_perfil(d)),
    ('PATCH',  r'/api/admin/perfiles/(\d+)', 'admin', 'json', lambda m, d, p, c, q: cambiar_perfil(int(m[1]), d, p)),
    ('DELETE', r'/api/admin/perfiles/(\d+)', 'admin', None, lambda m, d, p, c, q: borrar_perfil(int(m[1]), p)),
]


class Manejador(BaseHTTPRequestHandler):
    server_version = 'Gameflix'

    def log_message(self, formato, *args):
        pass  # sin ruido en el journal por cada consulta

    def token(self):
        cookie = SimpleCookie(self.headers.get('Cookie') or '')
        return cookie[COOKIE].value if COOKIE in cookie else None

    def enviar(self, codigo, cuerpo, tipo, encabezados=()):
        self.send_response(codigo)
        self.send_header('Content-Type', tipo)
        self.send_header('Content-Length', str(len(cuerpo)))
        for k, v in encabezados:
            self.send_header(k, v)
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(cuerpo)

    def responder(self, codigo, datos, encabezados=()):
        cuerpo = json.dumps(datos, ensure_ascii=False).encode('utf-8')
        self.enviar(codigo, cuerpo, 'application/json; charset=utf-8', [('Cache-Control', 'no-store'), *encabezados])

    def responder_binario(self, b):
        if b.archivo:
            # ROMs: se mandan por pedazos para no tener 32 MB en memoria por cada pedido
            tamano = b.archivo.stat().st_size
            self.send_response(200)
            self.send_header('Content-Type', b.tipo)
            self.send_header('Content-Length', str(tamano))
            self.send_header('Cache-Control', 'private, no-cache')
            self.end_headers()
            if self.command != 'HEAD':
                with open(b.archivo, 'rb') as f:
                    while trozo := f.read(256 * 1024):
                        self.wfile.write(trozo)
            return
        cache = 'private, max-age=31536000, immutable' if b.cache else 'no-store'
        self.enviar(200, b.datos, b.tipo, [('Cache-Control', cache), *b.extra.items()])

    def leer_cuerpo(self, maximo):
        largo = int(self.headers.get('Content-Length') or 0)
        if largo > maximo:
            self.close_connection = True   # no se leyó el cuerpo: la conexión no se puede reusar
            raise ValueError(f'El archivo es demasiado grande (máximo {maximo // (1024 * 1024) or 1} MB)')
        return self.rfile.read(largo) if largo else b''

    def leer_json(self):
        crudo = self.leer_cuerpo(MAX_JSON)
        if not crudo:
            return {}
        try:
            datos = json.loads(crudo)
        except json.JSONDecodeError:
            raise ValueError('JSON inválido') from None
        if not isinstance(datos, dict):
            raise ValueError('Se esperaba un objeto JSON')
        return datos

    def cookie_sesion(self, token, borrar=False):
        valor = f'{COOKIE}={token}; Path={RUTA_COOKIE}; HttpOnly; SameSite=Strict'
        return ('Set-Cookie', valor + ('; Max-Age=0' if borrar else '; Max-Age=31536000'))

    def atender(self):
        partes = urlsplit(self.path)
        ruta, consulta = partes.path, parse_qs(partes.query)
        metodo = 'GET' if self.command == 'HEAD' else self.command
        for verbo, patron, quien, cuerpo, accion in RUTAS:
            m = re.fullmatch(patron, ruta)
            if verbo == metodo and m:
                break
        else:
            self.responder(404, {'error': 'No existe'})
            return
        try:
            token = self.token()
            if ruta == '/api/entrar':
                token, perfil = entrar(self.leer_json())
                self.responder(200, {'perfil': perfil}, [self.cookie_sesion(token)])
                return
            if ruta == '/api/salir':
                if token:
                    salir(token)
                self.responder(200, {'ok': True}, [self.cookie_sesion('', borrar=True)])
                return
            with conectar() as con:
                if ruta == '/api/perfiles':
                    self.responder(200, listar_perfiles(con, token))
                    return
                # El permiso se revisa antes de leer el cuerpo (una ROM pesa hasta 32 MB)
                perfil = perfil_de_sesion(con, token)
                if not perfil:
                    raise NoAutorizado('Elige tu perfil otra vez')
                if quien == 'admin' and not perfil['admin']:
                    raise NoAutorizado('Solo el admin puede hacer eso', 403)
                datos = self.leer_json() if cuerpo == 'json' else self.leer_cuerpo(cuerpo) if cuerpo else {}
                if '/rom/' in ruta:
                    rom = archivo_rom(con, perfil, int(m[1]), contar=self.command == 'GET')
                    self.responder_binario(Binario('application/octet-stream', archivo=rom))
                    return
                resultado = accion(m, datos, perfil, con, consulta)
            if resultado is None:
                self.send_response(204)
                self.send_header('Cache-Control', 'no-store')
                self.end_headers()
            elif isinstance(resultado, Binario):
                self.responder_binario(resultado)
            else:
                self.responder(200, resultado)
        except NoAutorizado as e:
            if int(self.headers.get('Content-Length') or 0):
                self.close_connection = True   # el cuerpo quedó sin leer
            self.responder(e.codigo, {'error': str(e)})
        except NoExiste:
            self.responder(404, {'error': 'Eso ya no existe'})
        except ValueError as e:
            self.responder(400, {'error': str(e)})
        except (BrokenPipeError, ConnectionResetError):
            pass   # el celular cerró la conexión a medio envío
        except Exception as e:  # noqa: BLE001 - que el servicio no se caiga por un pedido
            print('Error:', repr(e), flush=True)
            self.responder(500, {'error': 'Error interno'})

    do_GET = do_HEAD = do_POST = do_PUT = do_PATCH = do_DELETE = atender


def main():
    preparar_bd()
    servidor = ThreadingHTTPServer((HOST, PUERTO), Manejador)
    print(f'Gameflix en http://{HOST}:{PUERTO} (BD: {BD}, ROMs: {ROMS})', flush=True)
    servidor.serve_forever()


if __name__ == '__main__':
    main()
