"""Drive a running portal through its pages in a headless browser and save screenshots.

Usage: python tests/ui_walkthrough.py URL OUT_DIR [--apk PATH] [--chrome PATH] [--password PW]
Against a fresh portal it runs setup (password, APK upload); against a set-up one it signs in.
"""
import argparse
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ap = argparse.ArgumentParser()
ap.add_argument("url")
ap.add_argument("out")
ap.add_argument("--apk")
ap.add_argument("--chrome")
ap.add_argument("--password", default="testpass123")
args = ap.parse_args()
out = Path(args.out)
out.mkdir(parents=True, exist_ok=True)


def shot(page, name):
    time.sleep(0.8)
    page.screenshot(path=str(out / f"{name}.png"))
    print("saved", name)


with sync_playwright() as p:
    browser = p.chromium.launch(executable_path=args.chrome) if args.chrome else p.chromium.launch()
    for label, viewport in (("desktop", {"width": 1280, "height": 800}), ("phone", {"width": 412, "height": 900})):
        ctx = browser.new_context(viewport=viewport, device_scale_factor=2 if label == "phone" else 1)
        page = ctx.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: m.type == "error" and errors.append(m.text))
        page.goto(args.url)
        time.sleep(1.5)
        if page.locator("text=Welcome").count():
            inputs = page.locator("input[type=password]")
            inputs.nth(0).fill(args.password)
            inputs.nth(1).fill(args.password)
            page.click("text=Continue")
            time.sleep(1)
        if page.locator("text=Sign in").count():
            page.fill("input[type=password]", args.password)
            page.click("text=Sign in")
            time.sleep(1)
        if page.locator("text=Upload APK").count():
            shot(page, f"{label}-assets")
            if args.apk:
                page.set_input_files("input[type=file]", args.apk)
                page.wait_for_load_state("load")
                time.sleep(4)
            else:
                page.click("text=Later")
        shot(page, f"{label}-home")
        page.goto(args.url + "#/create")
        time.sleep(1)
        page.fill("input[placeholder='World name']", f"UI {label}")
        page.locator(".toggle").nth(1).click()  # custom rules
        shot(page, f"{label}-create")
        page.locator(".cell", has_text="temperature").click()
        shot(page, f"{label}-rule-choice")
        page.locator(".dim .cell", has_text="very hot").click()
        page.locator(".slot").first.click()
        page.locator(".dim .cell", has_text="Choose an item").click()
        time.sleep(0.5)
        page.locator(".dim .tabs button").nth(2).click()
        shot(page, f"{label}-item-picker")
        page.locator(".dim .item-grid .slot").nth(3).click()
        time.sleep(0.4)
        page.locator(".dim input").fill("12")
        page.locator(".dim button.green").click()
        shot(page, f"{label}-create-filled")
        page.click("text=Create World >> nth=-1")
        time.sleep(8)
        shot(page, f"{label}-console")
        server = page.url.split("#/server/")[1].split("/")[0]
        for tab in ("overview", "players", "chat", "world", "lists", "backups", "stats", "settings"):
            page.goto(f"{args.url}#/server/{server}/{tab}")
            time.sleep(1)
            shot(page, f"{label}-{tab}")
        page.goto(args.url + "#/")
        time.sleep(1.5)
        shot(page, f"{label}-home-after")
        page.goto(args.url + "#/settings")
        shot(page, f"{label}-settings")
        page.goto(args.url + f"#/server/{server}/world")
        time.sleep(1)
        page.locator(".cell", has_text="Delete").click()
        time.sleep(0.6)
        shot(page, f"{label}-dialog")
        print(label, "page errors:", errors or "none")
        ctx.close()
    browser.close()
