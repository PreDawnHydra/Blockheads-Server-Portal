"""Check that a server page follows the server's state without reloading, the Settings Back button, and the
whitelist toggle. Usage: python tests/ui_state_changes.py URL OUT_DIR [--chrome PATH] [--password PW]"""
import argparse
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ap = argparse.ArgumentParser()
ap.add_argument("url")
ap.add_argument("out")
ap.add_argument("--chrome")
ap.add_argument("--password", default="testpass123")
args = ap.parse_args()
out = Path(args.out)
out.mkdir(parents=True, exist_ok=True)

with sync_playwright() as p:
    browser = p.chromium.launch(executable_path=args.chrome) if args.chrome else p.chromium.launch()
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    page.goto(args.url)
    time.sleep(1.5)
    if page.locator("text=Sign in").count():
        page.fill("input[type=password]", args.password)
        page.click("text=Sign in")
        time.sleep(1)
    server = page.evaluate("fetch('/api/servers').then(r => r.json()).then(l => l.find(s => s.status === 'running').id)")
    page.goto(f"{args.url}#/server/{server}/world")
    time.sleep(1.5)
    welcome = page.locator("textarea")
    print("running: welcome editable =", welcome.is_enabled())
    page.screenshot(path=str(out / "world-running.png"))
    page.click("text=Stop server")
    for _ in range(30):
        time.sleep(0.5)
        if page.locator("textarea").is_enabled():
            break
    print("after stop (no reload): welcome editable =", page.locator("textarea").is_enabled())
    page.screenshot(path=str(out / "world-stopped.png"))

    page.goto(f"{args.url}#/server/{server}/lists")
    time.sleep(1)
    wl = page.locator(".panel", has_text="Whitelist")
    wl.locator("textarea").fill("SOMEONE")
    wl.locator("button", has_text="Save").click()
    time.sleep(1)
    print("whitelist after save:", wl.locator(".hint").first.inner_text())
    wl.locator(".toggle").click()
    time.sleep(1)
    print("after toggle off:", wl.locator(".hint").first.inner_text(), "| list file:",
          page.evaluate(f"fetch('/api/servers/{server}').then(r => r.json()).then(s => s.lists.whitelist)"))
    page.screenshot(path=str(out / "whitelist-off.png"))
    wl.locator(".toggle").click()
    time.sleep(1)
    print("after toggle on:", page.evaluate(f"fetch('/api/servers/{server}').then(r => r.json()).then(s => s.lists.whitelist)"))

    page.goto(f"{args.url}#/settings")
    time.sleep(1)
    page.screenshot(path=str(out / "settings.png"))
    page.click("text=Back")
    time.sleep(1)
    print("Back from settings ->", page.url)

    # Delete the server from its Settings tab; home must not list it; its old address goes home; restore it.
    page.goto(f"{args.url}#/server/{server}/settings")
    time.sleep(1)
    page.locator("button", has_text="Delete server").click()
    page.locator(".dim button.red").click()
    time.sleep(2)
    names = page.evaluate("fetch('/api/servers').then(r => r.json()).then(l => l.map(s => s.name))")
    print("after delete, home lists:", names, "| page:", page.url)
    page.screenshot(path=str(out / "home-after-delete.png"))
    page.goto(f"{args.url}#/server/{server}/overview")
    time.sleep(1.5)
    print("old address ->", page.url)
    page.goto(f"{args.url}#/settings")
    time.sleep(1)
    page.locator(".panel", has_text="Trash").locator("button.green").first.click()
    time.sleep(1.5)
    print("after restore:", page.evaluate("fetch('/api/servers').then(r => r.json()).then(l => l.map(s => s.name))"))
    browser.close()
