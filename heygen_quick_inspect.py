# -*- coding: utf-8 -*-
from playwright.sync_api import sync_playwright
from pathlib import Path

SESSION_DIR = Path(__file__).parent / ".heygen_session"

with sync_playwright() as p:
    browser = p.chromium.launch_persistent_context(
        user_data_dir=str(SESSION_DIR),
        channel="msedge",
        headless=False,
        viewport={"width": 1280, "height": 800},
    )
    try:
        page = browser.pages[0] if browser.pages else browser.new_page()
        page.goto("https://app.heygen.com/apps/translate")
        print("Attente 8s chargement...")
        page.wait_for_timeout(8000)

        print("\n=== TOUS LES BOUTONS ===")
        for btn in page.locator("button").all():
            try:
                txt = btn.inner_text(timeout=500).strip()
                if txt and len(txt) < 120:
                    print(f"  {repr(txt[:80])}")
            except Exception:
                pass

        input("\nENTREE pour fermer : ")
    finally:
        try:
            browser.close()
        except Exception:
            pass
