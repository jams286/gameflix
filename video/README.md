# Videos de Gameflix

Dos reels verticales (1080×1920, 30 fps). Perfiles inventados y solo juegos libres; el juego es
**The Hat Chooses the Wizard** (GBA, homebrew libre). Hechos con el método `onetake`.

- `gameflix-a/`: **El cartucho** (17 s). Perfiles → catálogo → un cartucho se sale de la página, la cámara entra
  por su etiqueta (la misma escena con la que arranca el juego) → se juega → se guarda en la ranura 1 → marca.
  Música: "Pixel Peeker Polka (faster)".
- `gameflix-b/`: **Empiezo aquí, sigo allá** (15.5 s). Se juega en el celular, se guarda, la partida viaja como
  tarjeta a la casa (el servidor) y a la tablet, que sigue en el mismo punto. Footage real: la tablet abrió
  `jugar.html?j=6&estado=1` con el estado que guardó el celular. Música: "Pixelland".

Finales en `/media/datos/Videos/` (JamsData).

## Regenerar

Necesita la copia de demo del hub corriendo (`~/proyectos/infra/home/video/capturas/demo.py`, puerto 9400).

```
cd ~/proyectos/casa/gameflix/video/capturas
V=~/.cache/onetake-venv/bin/python
$V gf.py pantallas footage            # capturas a 3x + video de celular (390x844) y tablet (1180x820)
# frames a 30 fps (marcas medidas en el footage; ver comentarios en las comps):
ffmpeg -ss 14.0 -t 18.5 -i footage/cel/*.webm -vf fps=30 -q:v 2 frames/cel/%04d.jpg
ffmpeg -ss 3.0 -t 20 -i footage/tab/*.webm -vf fps=30 -q:v 2 frames/tab/%04d.jpg
cd ..
$V <onetake>/scripts/render.py gameflix-a/comp.html --out gameflix-a/draft.mp4 --width 1080 --height 1920 --workers 6
$V ~/proyectos/infra/home/video/sonido.py gameflix-a/comp.html "musica/Pixel Peeker Polka - faster.mp3" 0 gameflix-a/draft.mp4 gameflix-a/final.mp4
```

- El video de Playwright sale en px CSS: el celular se graba a 390×844 (el gameplay se ve bien escalado por ser
  pixel art); las pantallas de UI salen de capturas a 3×. Con zoom CSS el canvas del emulador sale negro.
- Para grabar se usa el perfil Sofi (sin estados): si la ranura 1 ya tiene algo, el `confirm()` de reemplazar
  lo cancela Playwright y no se guarda.
- Fuentes Bebas Neue y Atkinson Hyperlegible (OFL) embebidas en `fuentes/fuentes.js` para el render `file://`.
- La música (Kevin MacLeod, CC BY 4.0) no va en git: ver `musica/LICENCIA.md`.
