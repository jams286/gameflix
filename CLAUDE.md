# gameflix (casa)

Tracker: gameflix

Juegos retro (NES, SNES, GB, GBC, GBA) en el navegador con perfiles tipo Netflix y partidas guardadas en el servidor por perfil. Entra desde el hub `infra/home`. Comandos en el README.

## Qué hace

- "¿Quién está jugando?": perfiles con avatar (emoji + color) y PIN opcional (4 a 8 números). Al elegir uno se guarda una cookie `gameflix` (token en la tabla `sesiones`, ruta `/gameflix/api/`, HttpOnly). El perfil elegido dura en el dispositivo; `sessionStorage` (`gameflix.dentro`) hace que al abrir la app en una pestaña nueva se vuelva a mostrar la pantalla de perfiles, y al regresar de un juego no.
- Consolas como "mundos" (v2, ver abajo). Dentro de cada una: destacado, buscador, chips por tipo de juego, "Seguir jugando", "Te podría gustar" y una fila por tipo. Cada juego es un **cartucho** dibujado con CSS según la consola (`.cartucho-nes`, `-snes`, `-gb`, `-gbc`, `-gba`); la carátula va como etiqueta. Sin carátula, la etiqueta se arma con el título y el color de la consola.
- Detalle del juego: jugar/continuar, "Tu partida" (fecha del último save y versiones anteriores para recuperar) y 3 ranuras de estados con captura.
- Admin (perfiles con `admin`; al inicio solo Jams): subir ROMs (sueltas o en .zip, de una en una con barra de avance; la consola sale de la extensión, y un .gb con bandera CGB-only 0xC0 va a GBC), editar título, mover entre GB y GBC (mismo núcleo), carátula (se achica en el navegador si pasa de 1000 px o 1.5 MB), borrar juego; crear/editar/borrar perfiles, poner o quitar PIN y admin. Nadie puede quitarse el admin ni borrarse a sí mismo (así siempre queda un admin).
- Perfiles iniciales: Jams (admin, sin PIN) y Victor (sin PIN). Jams pidió que ambos fueran sin PIN; sin PIN en Jams cualquiera puede entrar al admin desde su perfil.

## v2 · Mundos (2026-11-03)

- Rutas: `#perfiles`, `#consolas` (selector), `#mundo/<consola>`, `#admin`. `#catalogo` lleva al último mundo del perfil en ese dispositivo (`localStorage` `gameflix.mundo.<perfil>`); si no hay, al selector (o directo si solo una consola tiene juegos). Decisión de Jams: recordar el último mundo y entrar directo. En la barra hay un botón con la consola actual (⇄) para cambiar, y "Cambiar de consola" en el menú del perfil. "Salir" del juego vuelve a `#mundo/<consola del juego>`.
- Selector: una tarjeta por consola con juegos (color de la consola, cuántos juegos, último jugado y un abanico de 3 cartuchos).
- Dentro del mundo: destacado = último jugado en esa consola, si no la primera sugerencia, si no uno al azar. Buscador (sin acentos ni mayúsculas, busca en título y tipo) y chips por tipo; con algo activo, las filas se cambian por una cuadrícula. Filas: "Seguir jugando" (solo esa consola, 10), "Te podría gustar", una por tipo (de más a menos juegos); los tipos con un solo juego y "Otros" van juntos en "Más juegos". Con menos de 8 juegos (`POCOS`) no hay buscador ni chips: una sola cuadrícula. El buscador se pega bajo la barra (`--alto-barra`) y la barra se vuelve sólida al bajar.
- Tipos de juego: columna `juegos.genero` (NULL = "Otros"). Se llena con `datos/generos.json` (libretro por CRC32, traducido a 14 categorías en español, ver `GENEROS` y `herramientas/generos_libretro.py`): al subir y, una sola vez, en la migración (`migrar()` en `preparar_bd`). GB y GBC se buscan cruzados. Editable en "Editar juego". A mano (no estaban en libretro) se pusieron: Tobu Tobu Girl, Nova, Uwol, Hat Chooses the Wizard, SMB Classic NES → Plataformas; µCity → Simulación; Space Rescue Squad → Acción; Skyland, FE Binding Blade → Estrategia; Emerald Elite Redux, DBZ Buu's Fury → RPG; Pokémon Pinball → Casual; Yu-Gi-Oh! WCT 2004 → Cartas y mesa.
- Tiempo jugado: `jugados.segundos`. `jugar.js` cuenta cada 5 s si el juego corre visible y sin pausa, y avisa cada 60 s (`POST api/juegos/<id>/tiempo`, el servidor acepta hasta 180 s por aviso), más lo que quede al salir o al ocultarse (keepalive). Decisión de Jams: **no hay vista** de lo que juega cada uno (ni para admin; su perfil es para jugar). Solo alimenta las sugerencias; reportes, si algún día los pide (está en Ideas del tracker).
- Sugerencias (`sugerir()` en el servidor): juegos de la consola que el perfil no ha abierto, puntuados por la afinidad del perfil a cada tipo (segundos + 120 por cada vez que lo abrió; lo de la misma consola pesa el doble, "Otros" pesa 0.3) y, de desempate, 0.3 × lo que juegan los demás perfiles. Máximo la mitad del mismo tipo primero; empates ordenados por un hash del día (cambian a diario).

## Partidas

- **Save del cartucho (SRAM)**: EmulatorJS lo deja en su FS virtual (`/data/saves/<Núcleo>/<nombre de la ROM>.srm`, persistido en IndexedDB). La ROM se pide como `api/juegos/<id>/rom/p<perfil>-j<juego>.<ext>` para que el archivo sea distinto por perfil aunque compartan dispositivo (el servidor ignora el nombre). Al arrancar (`EJS_onGameStart`) `jugar.js` trae el del servidor, lo escribe en el FS, llama `loadSaveFiles()` y `restart()`; verificado que el núcleo queda con esos bytes. Si lo local es más nuevo (el sha1 del servidor coincide con el último sincronizado, guardado en `localStorage` `gameflix.sync.<perfil>.<juego>`, y lo local es distinto) gana lo local y se sube.
- Mientras se juega, cada 10 s `gameManager.saveSaveFiles()` → evento `saveSaveFiles` → si cambió el sha1, `PUT api/juegos/<id>/save` (subidas en cola, de una en una). También al ocultarse la página (`visibilitychange`, con `keepalive` si pesa < 60 KB) y al tocar "Salir". No se sube un save "en blanco" (todo 0x00 o 0xFF) si el servidor no tiene ninguno. El servidor guarda cada versión distinta y conserva las últimas 10 (`MAX_HISTORIAL`).
- **Estados**: los botones "Guardar/Cargar estado" del menú de EmulatorJS disparan `EJS_onSaveState`/`EJS_onLoadState`, que abren el diálogo de 3 ranuras (el juego se pausa mientras). El PUT lleva `[4 bytes largo de la captura][PNG][estado]`. La captura sale de `gameManager.screenshot()`: el `screenshot` que trae el evento viene `undefined` por un error de EmulatorJS 4.2.3. `jugar.html?j=<id>&estado=<n>` abre directo en un estado. Los estados dependen de la versión del núcleo: al actualizar EmulatorJS pueden dejar de cargar (el save del cartucho no).
- Ocultos en EmulatorJS: netplay, caché, exportar/importar save, guardado rápido, grabar pantalla y salir (lo cubre nuestro "Salir"). `EJS_disableDatabases` evita que guarde la ROM y el núcleo en IndexedDB.

## Cómo está hecho

- `servidor.py`: `ThreadingHTTPServer` + `sqlite3`, solo biblioteca estándar, en `127.0.0.1:8777`. Tablas `perfiles` (PIN como PBKDF2 `sal$hash`), `sesiones`, `juegos` (carátula como BLOB con `caratula_version` para la caché del navegador), `saves`, `estados`, `jugados`. Las ROMs van en archivos `<sha1>.<ext>` (no se repite un juego: único por sha1) y se mandan por pedazos. El permiso se revisa antes de leer el cuerpo. Variables `GAMEFLIX_PUERTO`, `GAMEFLIX_BD` y `GAMEFLIX_ROMS` para probar sin tocar los datos reales.
- Límites: ROM 38 MB (nginx corta en 40 MB), save 1 MB, estado 12 MB, carátula 3 MB.
- `web/`: HTML/CSS/JS sin frameworks, tema oscuro, Bebas Neue para el logo y títulos, Atkinson Hyperlegible para el texto. `app.js` usa el hash para la vista (`#perfiles`, `#catalogo`, `#admin`). Rutas relativas para funcionar bajo `/gameflix/`.
- EmulatorJS se carga desde `web/emulatorjs/` (sin CDN). Las rutas relativas que se le pasan (`EJS_backgroundImage`) las antepone con su carpeta: por eso la carátula de fondo va como URL absoluta. El gamepad táctil aparece cuando el botón "▶ Jugar" se toca con el dedo en un navegador con user agent de celular.
- Audio en iOS: Safari calla el audio web cuando el iPhone está en silencio. `jugar.js` pone `navigator.audioSession.type = "playback"` (iOS 17+) y, en iOS más viejos, al primer toque reproduce en bucle un WAV silencioso generado en JS (cambia la sesión a reproducción). Cada toque reanuda el `AudioContext` del emulador si quedó pausado (al volver de otra app). Confirmado por Jams: sin esto, en modo silencio no sonaba.
- No hacen falta los headers COOP/COEP: estos núcleos no usan hilos (`EJS_threads` apagado).

## Importar carpetas de ROMs (2026-11-03)

- `herramientas/importar_carpeta.py` llama directo a `subir_juego`/`poner_caratula`/`consola_de` de `servidor.py` contra la misma BD (sin API ni PIN; respeta `GAMEFLIX_BD`/`GAMEFLIX_ROMS`). Los repetidos por sha1 se saltan solos.
- Título: del nombre No-Intro del archivo dentro del zip (quita regiones, `[!]`, numeración `1840 - `, `# GBA`; "X, The - Y" → "The X: Y"; Pokemon → Pokémon) + diccionario `TITULOS` para los que quedan feos. Jams eligió títulos limpios.
- Carátula: `thumbnails.libretro.com/<sistema>/Named_Boxarts/` (nombres No-Intro, con `&:*?` cambiados por `_`). Primero exacta, luego la misma base en otra región (prefiere USA), luego "parecida" (difflib, solo con `--aceptar-parecidas`) y `CARATULAS` a mano. Se achica a 1000 px. Jams está bien con el recorte central de la caja en la etiqueta.
- 2026-11-03: se importó `/media/datos/Games/roms/gba` (73 juegos, todos con carátula). Jams pidió dejar solo los USA de los repetidos: se saltaron `Dragonball Z - Supersonic Warriors GBA.zip`, `Final Fantasy - Tactics Advanced GBA.zip` y `The Legend Of Zelda - A Link To The Past (E)(Cezar).zip`. El Emerald Elite Redux se renombró a "Pokémon Emerald Elite Redux". ROMs quedaron en ~880 MB.

## Pruebas

- Firefox headless no tiene WebGL y EmulatorJS no arranca ahí. Se probó con Playwright + Chromium headless (`chromium-headless-shell`, con `--use-angle=swiftshader --enable-unsafe-swiftshader`), usando el venv de `personal/rm-ecommerce` (`.venv/bin/python`). Para ver el gamepad táctil hay que poner un user agent de Android.
- Para matar los servidores de prueba, usar su PID o el puerto, nunca `pkill -f servidor.py` (mata las otras tools).

## Dónde corre

- Página: https://192.168.1.4/gameflix/ (archivos en `/var/www/gameflix/`, copiados de `web/`).
- API: nginx publica `/gameflix/api/` → `127.0.0.1:8777/api/` (config en `infra/nginx`, cuerpo hasta 40 MB).
- Servicio systemd de usuario `gameflix.service` (copia en `servicio/`).
- Ícono del hub: `infra/home/iconos/gameflix.svg` (copia de `web/favicon.svg`).

## Memoria (movida de la memoria global el 2026-10-25)

- **Estado al 2026-10-22:** probado en celular e iPhone, funciona. Perfiles: Jams (admin, con PIN) y Victor (sin PIN).
- **No tocar / no proponer:** lo de xdg-desktop-portal-gtk (lo ve Jams aparte); limpiar ROMs borradas de la carpeta espejo del respaldo (decidió dejarlo así).
- **Ideas abiertas:** al retomar, preguntar si sigue con la tele o con el juego propio.
  - Juego propio de GB/NES (se sugirió GB Studio, GBDK o ensamblador 6502).
  - Tele Samsung (Tizen, modo desarrollador activo) con control USB. Falta que Jams diga modelo/año y qué control. Plan propuesto: empezar por `/gameflix/tele.html` (diagnóstico de WASM/WebGL/Gamepad y botones). Opción 1: navegador de la tele (dudas: CA casera, rendimiento SNES/GBA, Gamepad API). Opción 2: app `.wgt` que abre la URL, firmada con certificado de Samsung (cuenta + DUID), con `sdb connect` + `tizen install` (Host PC IP 192.168.1.4) y navegación con flechas y foco. No se ha construido nada.

## Videos (2026-10-31)

- `video/`: dos reels verticales (A "El cartucho", B "Empiezo aquí, sigo allá") con perfiles inventados y The Hat Chooses the Wizard. Cómo regenerarlos en `video/README.md`; usa la copia de demo de `infra/home/video/capturas/demo.py`. Finales en `/media/datos/Videos/`.
- Grabar el emulador: video de Playwright a 1× (con zoom CSS el canvas sale negro); perfil sin estados para que el diálogo de ranuras no pida confirmar.
