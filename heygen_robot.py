"""
AVF � Robot HeyGen
D�pose une vid�o, s�lectionne les langues et lance la traduction.
"""

from playwright.sync_api import sync_playwright, Error as PlaywrightError
from pathlib import Path
import sys

SESSION_DIR = Path(__file__).parent / ".heygen_session"
VIDEOS_EN_COURS = Path(__file__).parent / "videos_en_cours"

LANGUES_CIBLES = ["English", "German", "Spanish"]


def get_video_a_traduire():
    for projet in sorted(VIDEOS_EN_COURS.iterdir()):
        if not projet.is_dir():
            continue
        video_fr = (
            list((projet / "fr" / "video").glob("*.mp4")) +
            list((projet / "fr" / "video").glob("*.mov")) +
            list((projet / "fr" / "video").glob("*.mkv"))
        )
        if not video_fr:
            continue
        video_en = list((projet / "en" / "video").glob("*"))
        if not video_en:
            return video_fr[0], projet.name
    return None, None


def main():
    video_path, nom_projet = get_video_a_traduire()

    if not video_path:
        print("Aucune video a traduire trouvee.")
        sys.exit(0)

    print(f"Projet  : {nom_projet}")
    print(f"Video   : {video_path.name}")
    print(f"Langues : {', '.join(LANGUES_CIBLES)}")
    print()

    with sync_playwright() as p:
        browser = p.chromium.launch_persistent_context(
            user_data_dir=str(SESSION_DIR),
            channel="msedge",
            headless=False,
            viewport={"width": 1280, "height": 800},
        )

        try:
            page = browser.pages[0] if browser.pages else browser.new_page()

            print("Ouverture de HeyGen...")
            page.goto("https://app.heygen.com/apps/translate")
            page.wait_for_timeout(4000)

            if "login" in page.url or "signin" in page.url:
                print("Connecte-toi manuellement dans le navigateur.")
                input("Appuie sur ENTREE une fois connecte : ")
                page.goto("https://app.heygen.com/apps/translate")
                page.wait_for_timeout(4000)

            print("Depot de la video...")
            file_input = page.locator("input[type='file']").first
            file_input.set_input_files(str(video_path))

            print("Attente du panneau de langues (max 30s)...")
            page.wait_for_selector("button:has-text('Translate')", timeout=30000)
            page.wait_for_timeout(2000)

            for langue in LANGUES_CIBLES:
                print(f"  Selection : {langue}")
                btn = page.get_by_role("button", name=langue, exact=True).first
                btn.click()
                page.wait_for_timeout(500)

            print("\nLancement de la traduction...")
            translate_btn = page.get_by_role("button", name="Translate", exact=True).last
            translate_btn.click()
            page.wait_for_timeout(3000)

            print(f"\nTraduction lancee pour : {video_path.name}")
            input("\nAppuie sur ENTREE pour fermer le navigateur : ")

        except PlaywrightError as e:
            print(f"Erreur Playwright : {e}")
        except Exception as e:
            print(f"Erreur : {e}")
        finally:
            try:
                browser.close()
            except Exception:
                pass


if __name__ == "__main__":
    main()

