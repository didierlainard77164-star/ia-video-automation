# -*- coding: utf-8 -*-
"""
Inspecte ce qui se passe quand on clique Download sur HeyGen.
Surveille : nouveaux onglets, telechargements, popups.
"""

from playwright.sync_api import sync_playwright, Error as PlaywrightError
from pathlib import Path

SESSION_DIR = Path(__file__).parent / ".heygen_session"


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch_persistent_context(
            user_data_dir=str(SESSION_DIR),
            channel="msedge",
            headless=False,
            viewport={"width": 1280, "height": 800},
        )

        # Surveille tous les telechargements
        downloads = []
        browser.on("download", lambda d: downloads.append(d))

        # Surveille toutes les nouvelles pages/onglets
        new_pages = []
        browser.on("page", lambda pg: new_pages.append(pg))

        try:
            page = browser.pages[0] if browser.pages else browser.new_page()
            page.goto("https://app.heygen.com/apps/translate")
            page.wait_for_timeout(4000)

            # Surveille les requetes reseau (URLs video)
            video_urls = []
            def on_request(request):
                url = request.url
                if any(ext in url for ext in [".mp4", ".mov", "download", "export"]):
                    video_urls.append(url)
                    print(f"  [RESEAU] {url[:100]}")
            page.on("request", on_request)

            print("Clique sur la carte de la video '6 st-English' dans le navigateur.")
            print("Puis clique sur le bouton Download.")
            print("Attente de 20 secondes pour capturer ce qui se passe...")
            page.wait_for_timeout(20000)

            print("\n=== RAPPORT ===")
            print(f"Telechargements detectes : {len(downloads)}")
            for d in downloads:
                print(f"  - {d.suggested_filename} -> {d.url}")

            print(f"\nNouveaux onglets detectes : {len(new_pages)}")
            for pg in new_pages:
                try:
                    print(f"  - URL : {pg.url}")
                except Exception:
                    pass

            print(f"\nURLs video dans les requetes : {len(video_urls)}")
            for url in video_urls:
                print(f"  - {url}")

            # Capture aussi le HTML de ce qui est ouvert
            print("\nBoutons visibles actuellement :")
            for btn in page.locator("button").all():
                try:
                    txt = btn.inner_text(timeout=500).strip()
                    if txt and len(txt) < 50:
                        print(f"  '{txt}'")
                except Exception:
                    pass

            input("\nAppuie sur ENTREE pour fermer : ")

        except PlaywrightError as e:
            print(f"Erreur : {e}")
        finally:
            try:
                browser.close()
            except Exception:
                pass


if __name__ == "__main__":
    main()
