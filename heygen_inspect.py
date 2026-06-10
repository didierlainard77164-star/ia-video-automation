"""
Inspecte la page HeyGen après dépôt vidéo pour trouver les sélecteurs des cases à cocher.
"""
from playwright.sync_api import sync_playwright, Error as PlaywrightError
from pathlib import Path

SESSION_DIR = Path(__file__).parent / ".heygen_session"
RAPPORT = Path(__file__).parent / "heygen_inspect_rapport.txt"


def main():
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

            print("Dépose une vidéo manuellement et attends la liste des langues.")
            print("Le script va analyser automatiquement dans 30 secondes...")
            page.wait_for_timeout(30000)

            lignes = []

            # Checkboxes
            lignes.append("=== CHECKBOXES ===")
            checkboxes = page.locator("input[type='checkbox']").all()
            lignes.append(f"Nombre : {len(checkboxes)}")
            for i, cb in enumerate(checkboxes):
                try:
                    label = cb.evaluate("el => el.closest('label')?.innerText || el.getAttribute('aria-label') || ''")
                    lignes.append(f"  [{i}] '{label.strip()}'")
                except Exception:
                    lignes.append(f"  [{i}] (illisible)")

            # Boutons
            lignes.append("\n=== BOUTONS ===")
            for btn in page.locator("button").all():
                try:
                    txt = btn.inner_text().strip()
                    if txt:
                        lignes.append(f"  '{txt}'")
                except Exception:
                    pass

            # Textes langues
            lignes.append("\n=== LANGUES ===")
            for lang in ["English", "German", "Spanish", "Arabic", "Italian", "Portuguese"]:
                els = page.get_by_text(lang, exact=False).all()
                for el in els:
                    try:
                        tag = el.evaluate("el => el.tagName")
                        classes = el.evaluate("el => el.className")
                        lignes.append(f"  {lang} → <{tag}> class='{classes}'")
                    except Exception:
                        pass

            # URL
            lignes.append(f"\n=== URL ===\n  {page.url}")

            rapport = "\n".join(lignes)
            RAPPORT.write_text(rapport, encoding="utf-8")
            print(f"\n✓ Rapport sauvegardé dans : {RAPPORT}")
            print(rapport)

            page.wait_for_timeout(3000)

        except PlaywrightError as e:
            print(f"Erreur Playwright : {e}")
        finally:
            try:
                browser.close()
            except Exception:
                pass


if __name__ == "__main__":
    main()
