"""Prueba rápida: arranca cada juego en el celular y saca capturas (con infra/home/video/capturas/demo.py corriendo)."""
import asyncio, sys
from pathlib import Path
from playwright.async_api import async_playwright
BASE = 'http://127.0.0.1:9400/gameflix/'
OUT = Path(__file__).resolve().parent / 'png' / 'explorar'
UA = 'Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Mobile Safari/537.36'

async def main(ids):
    OUT.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        nav = await p.chromium.launch(args=['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--autoplay-policy=no-user-gesture-required'])
        for j in ids:
            ctx = await nav.new_context(viewport={'width': 390, 'height': 844}, device_scale_factor=2, is_mobile=True, has_touch=True, user_agent=UA, locale='es-ES')
            pg = await ctx.new_page()
            await pg.goto(BASE, wait_until='networkidle'); await pg.get_by_text('Ana', exact=True).click(); await pg.wait_for_timeout(800)
            await pg.goto(BASE + f'jugar.html?j={j}', wait_until='networkidle'); await pg.wait_for_timeout(1500)
            await pg.screenshot(path=str(OUT / f'j{j}_0.png'))
            await pg.locator('text=▶ Jugar').first.tap(); await pg.wait_for_timeout(5000)
            await pg.screenshot(path=str(OUT / f'j{j}_1.png'))
            for k in range(3):
                await pg.keyboard.press('Enter'); await pg.wait_for_timeout(1200)
            await pg.screenshot(path=str(OUT / f'j{j}_2.png'))
            print(j, 'ok', flush=True)
            await ctx.close()
        await nav.close()

asyncio.run(main([int(x) for x in sys.argv[1:]] or [1, 3, 4, 5, 6, 7]))
