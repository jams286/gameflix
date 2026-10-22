# gameflix

Juegos retro en el navegador, "tipo Netflix": cada quien elige su perfil, ve las consolas en filas con sus cartuchos y juega desde el celular, la tablet o la compu. La partida de cada perfil se guarda en el servidor, así que se puede empezar en un dispositivo y seguir en otro.

- Página: https://192.168.1.4/gameflix/
- Consolas: NES, Super Nintendo, Game Boy, Game Boy Color y Game Boy Advance (emuladas con [EmulatorJS](https://emulatorjs.org) 4.2.3 y sus núcleos de libretro).
- Datos: `~/.local/share/casa/gameflix.db` (perfiles, carátulas, saves y estados) y `~/.local/share/casa/gameflix-roms/` (ROMs).

## Partes

- `web/`: página estática que se publica en `/var/www/gameflix/` (`index.html` catálogo y admin, `jugar.html` reproductor).
- `web/emulatorjs/`: EmulatorJS con solo los núcleos que se usan. No va en git; se baja con `herramientas/traer-emulatorjs.sh`.
- `servidor.py`: API JSON (solo Python estándar + SQLite) en `127.0.0.1:8777`. nginx publica `/gameflix/api/` → `/api/`.
- `servicio/gameflix.service`: servicio systemd de usuario.
- `herramientas/servidor_prueba.py`: imita a nginx para probar sin publicar.

## Comandos

Bajar EmulatorJS (solo la primera vez o al cambiar de versión):

```
~/proyectos/casa/gameflix/herramientas/traer-emulatorjs.sh
```

Publicar la página:

```
rsync -a --delete ~/proyectos/casa/gameflix/web/ /var/www/gameflix/
```

Instalar o actualizar el servicio:

```
mkdir -p ~/.config/systemd/user
cp ~/proyectos/casa/gameflix/servicio/gameflix.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now gameflix.service
systemctl --user restart gameflix.service   # después de cambiar servidor.py
```

Ver el log: `journalctl --user -u gameflix -f`

Probar sin tocar los datos reales:

```
GAMEFLIX_PUERTO=18777 GAMEFLIX_BD=/tmp/gf/gameflix.db GAMEFLIX_ROMS=/tmp/gf/roms python3 servidor.py &
python3 herramientas/servidor_prueba.py 18778 18777    # -> http://127.0.0.1:18778/gameflix/
```

Respaldo automático: la BD todos los días a las 3:30 a. m. en `/media/datos/Backups/casa/AAAA-MM-DD/`, y las ROMs en `/media/datos/Backups/casa/gameflix-roms/` (proyecto `infra/respaldos`).

## Juegos de prueba

Homebrew que sus autores reparten gratis:

| Juego | Consola | Autor | Licencia / origen |
|---|---|---|---|
| Tobu Tobu Girl | Game Boy | Tangram Games | MIT (código); ROM de [Homebrew Hub](https://hh.gbdev.io/game/tobutobugirl) |
| µCity | Game Boy Color | AntonioND | GPL-3.0; [GitHub](https://github.com/AntonioND/ucity) |
| Nova the Squirrel | NES | NovaSquirrel | GPL-3.0 (código), CC-BY-NC-SA 4.0 (gráficos); [GitHub](https://github.com/NovaSquirrel/NovaTheSquirrel) |
| Uwol: Quest for Money | Super Nintendo | Alekmaul, Mojon Twins | Gratis de sus autores; [retrobrews](https://github.com/retrobrews/snes-games) |
| Space Rescue Squad (demo) | Super Nintendo | undisbeliever | zlib (código); [GitHub](https://github.com/undisbeliever/space-rescue-squad) |
| The Hat Chooses the Wizard | Game Boy Advance | Corwin, Gwilym (agbrs) | MPL-2.0; [Homebrew Hub](https://hh.gbdev.io/game/the-hat-chooses-the-wizard) |
| Skyland | Game Boy Advance | Evan Bowman | MPL-2.0; [GitHub](https://github.com/evanbowman/skyland) |

Las carátulas de prueba son capturas de pantalla de cada juego (de las mismas fuentes).
