"""Hoja de contacto vertical de una composición: fotos.py comp.html 1.0,2.5,... salida.png [ancho_celda]"""
import asyncio
import io
import sys
from pathlib import Path

from PIL import Image
from playwright.async_api import async_playwright


async def main(comp, tiempos, salida, cw=300):
    W, H = 1080, 1920
    ch = cw * H // W
    cols = min(len(tiempos), 7)
    filas = (len(tiempos) + cols - 1) // cols
    hoja = Image.new('RGB', (cols * cw, filas * ch), 'black')
    async with async_playwright() as p:
        nav = await p.chromium.launch()
        pg = await nav.new_page(viewport={'width': W, 'height': H})
        errores = []
        pg.on('pageerror', lambda e: errores.append(str(e)))
        await pg.goto(Path(comp).resolve().as_uri())
        await pg.evaluate('window.__ready')
        for i, t in enumerate(tiempos):
            await pg.evaluate(f'window.__seek({t})')
            await pg.wait_for_timeout(40)
            im = Image.open(io.BytesIO(await pg.screenshot())).convert('RGB').resize((cw, ch), Image.LANCZOS)
            hoja.paste(im, ((i % cols) * cw, (i // cols) * ch))
        await nav.close()
    hoja.save(salida)
    print('ok', salida, 'errores:', errores or 'ninguno')


if __name__ == '__main__':
    a = sys.argv
    asyncio.run(main(a[1], [float(x) for x in a[2].split(',')], a[3], int(a[4]) if len(a) > 4 else 300))
