# Retomar Gameflix

## Objetivo
Siguiente versión: **v3 · tele** (que Gameflix se juegue en la tele Samsung con control USB).

## Estado (2026-11-03)
- v2 · Mundos terminada, publicada y probada por Jams en el celular. En el tracker la versión ya quedó cerrada.
- El catálogo tiene 76 juegos de GBA, más los de NES y Game Boy. Los ROMs se suben en bloque con `herramientas/importar_carpeta.py`.
- Todo está commiteado y en `/var/www/gameflix`. El servicio `gameflix.service` está corriendo.

## Decisiones tomadas
Las de v2 están en el CLAUDE.md, en la sección "v2 · Mundos". En corto:
- recuerda el último mundo de cada perfil
- 14 tipos de juego en español
- no hay vista de "qué juega cada uno"
- el tiempo jugado se usa solo para las sugerencias

## Siguiente paso
Arrancar la v3 (tele). Antes, Jams tiene que pasar:
1. Modelo y año de la tele Samsung (para saber qué navegador o Tizen trae).
2. Qué control USB va a usar.

## Pendientes
- Idea 52 del tracker: reportes de lo que juega cada uno, solo si algún día se piden.
- Si algún tipo de juego de libretro no cuadra (por ejemplo Beyblade y Zelda ALttP salen como RPG), se corrige en "Editar juego".
