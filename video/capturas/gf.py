"""Capturas y footage de Gameflix para los videos (con infra/home/video/capturas/demo.py corriendo:
copia de demo con perfiles inventados y solo juegos libres).

    ~/.cache/onetake-venv/bin/python gf.py [pantallas] [footage]
Salen en video/capturas/png/ (pantallas, piezas, gf.js con rectángulos) y video/capturas/footage/ (webm).
"""

import asyncio
import json
import sys
from pathlib import Path

from playwright.async_api import async_playwright

BASE = 'http://127.0.0.1:9400/gameflix/'
AQUI = Path(__file__).resolve().parent
PNG, FOOT = AQUI / 'png', AQUI / 'footage'
UA = 'Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Mobile Safari/537.36'
JUEGO = 6        # The Hat Chooses the Wizard (GBA, libre)
ARGS = ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--autoplay-policy=no-user-gesture-required']
RECT = """e => { const r = e.getBoundingClientRect(); return {x: r.x, y: r.y + scrollY, w: r.width, h: r.height}; }"""


async def entrar(pg, quien='Ana'):
    await pg.goto(BASE, wait_until='networkidle')
    await pg.get_by_text(quien, exact=True).click()
    await pg.wait_for_timeout(1200)


async def pantallas(nav):
    datos = {}
    ctx = await nav.new_context(viewport={'width': 390, 'height': 844}, device_scale_factor=3, is_mobile=True,
                                has_touch=True, user_agent=UA, locale='es-ES')
    pg = await ctx.new_page()
    await pg.goto(BASE, wait_until='networkidle'); await pg.wait_for_timeout(800)
    await pg.screenshot(path=str(PNG / 'perfiles.png'))
    perfiles = pg.locator('.perfil')
    datos['perfiles'] = []
    for i in range(await perfiles.count()):
        e = perfiles.nth(i)
        await e.screenshot(path=str(PNG / f'perfil_{i}.png'))
        datos['perfiles'].append(await e.evaluate(RECT))
    await perfiles.first.click(); await pg.wait_for_timeout(1500)
    await pg.screenshot(path=str(PNG / 'catalogo.png'))
    await pg.screenshot(path=str(PNG / 'catalogo_largo.png'), full_page=True)
    datos['largo'] = await pg.evaluate('document.documentElement.scrollHeight')
    cajas = pg.locator('.fila .cartucho')
    datos['cartuchos'] = []
    for i in range(await cajas.count()):
        e = cajas.nth(i)
        await e.scroll_into_view_if_needed()
        await e.screenshot(path=str(PNG / f'cartucho_{i}.png'), omit_background=True)
        datos['cartuchos'].append({**await e.evaluate(RECT), 'texto': (await e.inner_text()).strip()[:40]})
    await pg.evaluate('scrollTo(0,0)')
    datos['filas'] = await pg.eval_on_selector_all('.fila', 'es => es.map(e => { const r = e.getBoundingClientRect(); return {y: r.y + scrollY, h: r.height, titulo: e.querySelector("h2")?.textContent}; })')
    await pg.goto(BASE + f'#juego/{JUEGO}', wait_until='networkidle'); await pg.wait_for_timeout(1200)
    await pg.screenshot(path=str(PNG / 'detalle.png'))
    await pg.goto(BASE + f'jugar.html?j={JUEGO}', wait_until='networkidle'); await pg.wait_for_timeout(2500)
    await pg.screenshot(path=str(PNG / 'jugar.png'))
    b = await pg.locator('text=▶ Jugar').first.bounding_box()
    datos['jugar_boton'] = {'x': b['x'] + b['width'] / 2, 'y': b['y'] + b['height'] / 2}
    await ctx.close()
    (PNG / 'gf.js').write_text('window.GF = ' + json.dumps(datos, ensure_ascii=False) + ';\n')
    print(json.dumps(datos, ensure_ascii=False)[:1500])


async def jugar(pg, segundos, empezar=True):
    """Pasa la pantalla de título y juega sobre la primera plataforma (va y viene saltando, sin caer al hoyo)."""
    if empezar:
        for _ in range(3):
            await pg.keyboard.press('Enter'); await pg.wait_for_timeout(1100)
        await pg.wait_for_timeout(600)
    patron = [('ArrowRight', 0.25, False), ('ArrowRight', 0.45, True), ('ArrowRight', 0.2, False), (None, 0.15, True),
              ('ArrowLeft', 0.35, True), ('ArrowLeft', 0.3, False), ('ArrowRight', 0.3, True), (None, 0.25, False)]
    t = 0.0
    while t < segundos:
        for tecla, dur, salta in patron:
            if tecla:
                await pg.keyboard.down(tecla)
            if salta:
                await pg.keyboard.down('x')
            await pg.wait_for_timeout(int(dur * 1000))
            if salta:
                await pg.keyboard.up('x')
            if tecla:
                await pg.keyboard.up(tecla)
            t += dur


async def footage(nav):
    FOOT.mkdir(exist_ok=True)
    # celular: entra, toca Jugar, juega, guarda estado en la ranura 1
    # el video de Playwright sale en px CSS (390x844); las capturas fijas salen a 3x (nítidas).
    # (con zoom CSS el canvas WebGL del emulador sale negro: no sirve para grabar a más resolución)
    ctx = await nav.new_context(viewport={'width': 390, 'height': 844}, device_scale_factor=3, is_mobile=True,
                                has_touch=True, user_agent=UA, locale='es-ES',
                                record_video_dir=str(FOOT / 'cel'), record_video_size={'width': 390, 'height': 844})
    pg = await ctx.new_page()
    await entrar(pg, 'Sofi')   # perfil sin estados guardados: la ranura 1 está vacía
    await pg.goto(BASE + f'jugar.html?j={JUEGO}', wait_until='networkidle'); await pg.wait_for_timeout(1500)
    await pg.locator('text=▶ Jugar').first.tap(); await pg.wait_for_timeout(4500)
    await jugar(pg, 9)
    await pg.screenshot(path=str(PNG / 'cel_ultimo.png'))
    # guardar estado desde el menú del emulador → nuestro diálogo de ranuras
    await pg.mouse.click(195, 300); await pg.wait_for_timeout(500)
    await pg.wait_for_timeout(700)   # que se vea el menú del emulador antes de tocar
    await pg.evaluate("""() => [...document.querySelectorAll('.ejs_menu_text')]
        .find(e => e.textContent.trim() === 'Guardar Estado').closest('button').click()""")
    await pg.wait_for_timeout(1200)
    await pg.screenshot(path=str(PNG / 'ranuras.png'))
    b = await pg.locator('#ranuras button, #ranuras .ranura').first.bounding_box()
    (PNG / 'ranura1.json').write_text(json.dumps({'x': b['x'] + b['width'] / 2, 'y': b['y'] + b['height'] / 2}))
    await pg.locator('#ranuras button, #ranuras .ranura').first.click(); await pg.wait_for_timeout(2500)
    await pg.screenshot(path=str(PNG / 'guardado.png'))
    await ctx.close()
    # tablet horizontal: abre directo en el estado 1 y sigue
    ctx = await nav.new_context(viewport={'width': 1180, 'height': 820}, device_scale_factor=2, has_touch=True,
                                is_mobile=True, user_agent=UA.replace('Pixel 8', 'SM-X710').replace(' Mobile', ''),
                                locale='es-ES', record_video_dir=str(FOOT / 'tab'), record_video_size={'width': 1180, 'height': 820})
    pg = await ctx.new_page()
    await entrar(pg, 'Sofi')   # perfil sin estados guardados: la ranura 1 está vacía
    await pg.goto(BASE + f'jugar.html?j={JUEGO}&estado=1', wait_until='networkidle'); await pg.wait_for_timeout(1500)
    await pg.screenshot(path=str(PNG / 'tab_jugar.png'))
    await pg.locator('text=▶ Jugar').first.tap(); await pg.wait_for_timeout(4000)
    await pg.screenshot(path=str(PNG / 'tab_inicio.png'))
    await jugar(pg, 7, empezar=False)
    await ctx.close()


async def main(que):
    PNG.mkdir(exist_ok=True)
    async with async_playwright() as p:
        nav = await p.chromium.launch(args=ARGS)
        if 'pantallas' in que:
            await pantallas(nav)
        if 'footage' in que:
            await footage(nav)
        await nav.close()


if __name__ == '__main__':
    asyncio.run(main(sys.argv[1:] or ['pantallas', 'footage']))
