# -*- coding: utf-8 -*-
"""
Inspecte la PAGE VIDEO HeyGen pour trouver le selecteur exact du bouton Download.
Lance le script, attends que la page video s'ouvre, puis appuie sur ENTREE.
"""
from playwright.sync_api import sync_playwright
from pathlib import Path

SESSION_DIR = Path(__file__).parent / ".heygen_session"
RAPPORT = Path(__file__).parent / "heygen_inspect_video_rapport.txt"

# Met ici une URL d'une video existante (visible dans le navigateur)
# Ex: https://app.heygen.com/videos/8f210b0b23124a18b035b6305913940d-es
URL_VIDEO = "https://app.heygen.com/videos/8f210b0b23124a18b035b6305913940d-es"

with sync_playwright() as p:
    browser = p.chromium.launch_persistent_context(
        user_data_dir=str(SESSION_DIR),
        channel="msedge",
        headless=False,
        viewport={"width": 1280, "height": 800},
    )
    try:
        page = browser.pages[0] if browser.pages else browser.new_page()
        page.goto(URL_VIDEO)
        print(f"Navigation vers : {URL_VIDEO}")
        print("Attente 10s chargement...")
        page.wait_for_timeout(10000)
        print(f"URL actuelle : {page.url}")
        print("\nSi la page n'est pas chargee, attends et appuie sur ENTREE quand c'est pret.")
        input("ENTREE pour scanner la page : ")

        lignes = []
        lignes.append(f"URL : {page.url}")
        lignes.append("")

        # Screenshot
        shot = Path(__file__).parent / "heygen_inspect_video.png"
        page.screenshot(path=str(shot))
        lignes.append(f"Screenshot : {shot}")
        lignes.append("")

        # Tous les boutons
        lignes.append("=== BOUTONS <button> ===")
        btns = page.locator("button").all()
        lignes.append(f"Nombre total : {len(btns)}")
        for i, btn in enumerate(btns):
            try:
                txt = btn.inner_text(timeout=500).strip().replace("\n", " ")
                aria = btn.get_attribute("aria-label") or ""
                title = btn.get_attribute("title") or ""
                cls = (btn.get_attribute("class") or "")[:80]
                visible = btn.is_visible()
                lignes.append(f"  [{i}] visible={visible} text={repr(txt[:60])} aria={repr(aria)} title={repr(title)}")
                lignes.append(f"       class={repr(cls)}")
            except Exception as e:
                lignes.append(f"  [{i}] ERREUR: {e}")

        # Liens avec "download"
        lignes.append("\n=== LIENS <a> ===")
        links = page.locator("a").all()
        for i, lnk in enumerate(links[:50]):
            try:
                txt = lnk.inner_text(timeout=300).strip().replace("\n", " ")
                href = lnk.get_attribute("href") or ""
                aria = lnk.get_attribute("aria-label") or ""
                download = lnk.get_attribute("download") or ""
                if txt or aria or download or "download" in href.lower():
                    lignes.append(f"  [{i}] text={repr(txt[:60])} aria={repr(aria)} href={repr(href[:80])} dl={repr(download)}")
            except Exception:
                pass

        # Elements avec aria-label contenant "download"
        lignes.append("\n=== ELEMENTS aria-label*=download ===")
        try:
            els = page.locator("[aria-label*='ownload']").all()
            for el in els:
                try:
                    tag = el.evaluate("el => el.tagName")
                    aria = el.get_attribute("aria-label") or ""
                    txt = el.inner_text(timeout=300).strip().replace("\n", " ")
                    cls = (el.get_attribute("class") or "")[:80]
                    visible = el.is_visible()
                    lignes.append(f"  <{tag}> visible={visible} aria={repr(aria)} text={repr(txt[:60])}")
                    lignes.append(f"    class={repr(cls)}")
                except Exception as e:
                    lignes.append(f"  ERREUR: {e}")
        except Exception as e:
            lignes.append(f"  ERREUR globale: {e}")

        # Elements avec title contenant "download"
        lignes.append("\n=== ELEMENTS title*=download ===")
        try:
            els = page.locator("[title*='ownload']").all()
            for el in els:
                try:
                    tag = el.evaluate("el => el.tagName")
                    title = el.get_attribute("title") or ""
                    txt = el.inner_text(timeout=300).strip().replace("\n", " ")
                    visible = el.is_visible()
                    lignes.append(f"  <{tag}> visible={visible} title={repr(title)} text={repr(txt[:60])}")
                except Exception:
                    pass
        except Exception:
            pass

        # Tous les elements cliquables / role=button
        lignes.append("\n=== ELEMENTS role=button ===")
        try:
            els = page.locator("[role='button']").all()
            for el in els[:30]:
                try:
                    tag = el.evaluate("el => el.tagName")
                    aria = el.get_attribute("aria-label") or ""
                    txt = el.inner_text(timeout=300).strip().replace("\n", " ")
                    visible = el.is_visible()
                    lignes.append(f"  <{tag}> visible={visible} aria={repr(aria)} text={repr(txt[:60])}")
                except Exception:
                    pass
        except Exception:
            pass

        rapport = "\n".join(lignes)
        RAPPORT.write_text(rapport, encoding="utf-8")
        print(f"\nRapport sauvegarde : {RAPPORT}")
        print(rapport[:3000])

        input("\nENTREE pour fermer : ")
    finally:
        try:
            browser.close()
        except Exception:
            pass
