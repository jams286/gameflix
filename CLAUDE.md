# gameflix (casa)

Juegos retro (NES, SNES, GB, GBC, GBA) en el navegador con perfiles tipo Netflix y partidas guardadas en el servidor por perfil. Entra desde el hub `infra/home`. Comandos en el README.

## Qué hace

- "¿Quién está jugando?": perfiles con avatar (emoji + color) y PIN opcional (4 a 8 números). Al elegir uno se guarda una cookie `gameflix` (token en la tabla `sesiones`, ruta `/gameflix/api/`, HttpOnly). El perfil elegido dura en el dispositivo; `sessionStorage` (`gameflix.dentro`) hace que al abrir la app en una pestaña nueva se vuelva a mostrar la pantalla de perfiles, y al regresar de un juego no.
- Catálogo: destacado (lo último que jugó el perfil, o uno al azar), fila "Seguir jugando" (por la tabla `jugados`, que se llena al pedir la ROM) y una fila por consola. Cada juego es un **cartucho** dibujado con CSS según la consola (`.cartucho-nes`, `-snes`, `-gb`, `-gbc`, `-gba`); la carátula va como etiqueta. Sin carátula, la etiqueta se arma con el título y el color de la consola.
- Detalle del juego: jugar/continuar, "Tu partida" (fecha del último save y versiones anteriores para recuperar) y 3 ranuras de estados con captura.
- Admin (perfiles con `admin`; al inicio solo Jams): subir ROMs (sueltas o en .zip, de una en una con barra de avance; la consola sale de la extensión, y un .gb con bandera CGB-only 0xC0 va a GBC), editar título, mover entre GB y GBC (mismo núcleo), carátula (se achica en el navegador si pasa de 1000 px o 1.5 MB), borrar juego; crear/editar/borrar perfiles, poner o quitar PIN y admin. Nadie puede quitarse el admin ni borrarse a sí mismo (así siempre queda un admin).
- Perfiles iniciales: Jams (admin, sin PIN) y Victor (sin PIN). Jams pidió que ambos fueran sin PIN; sin PIN en Jams cualquiera puede entrar al admin desde su perfil.

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
