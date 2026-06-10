# -*- coding: utf-8 -*-
"""
AVF -- Robot HeyGen - Telecharge les videos traduites.
3 mecanismes de capture : download event, popup, interception requete MP4.
Gestion dropdown ET modal apres clic Download + screenshots diagnostics.
"""

from playwright.sync_api import sync_playwright
from pathlib import Path
import requests as req_lib
import re

SESSION_DIR     = Path(__file__).parent / ".heygen_session"
VIDEOS_EN_COURS = Path(__file__).parent / "videos_en_cours"

# Noms EXACTS tels qu'affichés par HeyGen dans l'interface (sensible à la casse)
LANGUE_MAP = {
    "English":    "en",
    "German":     "de",
    "Spanish":    "es",
    # -- Langues prévues (vérifier le libellé exact dans HeyGen avant activation) --
    "Italian":    "it",
    "Portuguese": "pt",
    "Arabic":     "ar",
    # "Japanese":   "ja",   # exemple pour la suite
}
URL_TRANSLATE   = "https://app.heygen.com/apps/translate"


# ---------------------------------------------------------------------------
# Utilitaires
# ---------------------------------------------------------------------------

def projets_locaux():
    return {p.name.lower(): p for p in VIDEOS_EN_COURS.iterdir() if p.is_dir()}


def destination_depuis_carte(nom_carte, projets):
    for langue_heygen, code in LANGUE_MAP.items():
        if nom_carte.endswith(f"-{langue_heygen}"):
            nom_projet = nom_carte[: -len(f"-{langue_heygen}")].strip()
            return projets.get(nom_projet.lower()), code
    return None, None


def chemin_dest(nom_fichier, nom_carte, projets):
    projet, code = destination_depuis_carte(nom_carte, projets)
    if projet and code:
        return projet / code / "video" / nom_fichier
    return VIDEOS_EN_COURS / "downloads_heygen" / nom_fichier


def telecharger_url(url, dest):
    dest.parent.mkdir(parents=True, exist_ok=True)
    headers = {"User-Agent": "Mozilla/5.0"}
    with req_lib.get(url, stream=True, timeout=300, headers=headers) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length", 0))
        done  = 0
        with open(dest, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 1024):
                f.write(chunk)
                done += len(chunk)
                if total:
                    print(f"\r  {int(done/total*100)}%", end="", flush=True)
    print(f"\r  OK : {dest.name}")


# ---------------------------------------------------------------------------
# Scan cartes
# ---------------------------------------------------------------------------

def trouver_cartes_cibles(page, connus):
    cartes = []
    try:
        loc   = page.locator("button")
        count = loc.count()
        for idx in range(count):
            try:
                btn      = loc.nth(idx)
                txt      = btn.inner_text(timeout=300).strip()
                premiere = txt.split("\n")[0]
                for langue in LANGUE_MAP:
                    if premiere.endswith(f"-{langue}") and "Video Translate" in txt:
                        nom = premiere.replace(f"-{langue}", "").strip().lower()
                        if nom in connus:
                            cartes.append(premiere)
                        break
            except Exception:
                pass
    except Exception:
        pass
    return cartes


def cliquer_carte(page, nom_carte):
    try:
        loc   = page.locator("button")
        count = loc.count()
        for idx in range(count):
            try:
                btn = loc.nth(idx)
                txt = btn.inner_text(timeout=300).strip()
                if txt.startswith(nom_carte) and "Video Translate" in txt:
                    btn.scroll_into_view_if_needed()
                    page.wait_for_timeout(500)
                    btn.click()
                    return True
            except Exception:
                pass
    except Exception:
        pass
    return False


# ---------------------------------------------------------------------------
# Clic bouton Download (avec log detaille)
# ---------------------------------------------------------------------------

SELECTEURS_DOWNLOAD = [
    "button:has-text('Download')",
    "[aria-label*='Download' i]",
    "[title*='Download' i]",
    "[data-testid*='download' i]",
    "[role='button']:has-text('Download')",
]

def cliquer_download(page):
    try:
        page.mouse.move(640, 400)
        page.wait_for_timeout(800)
    except Exception:
        pass
    for sel in SELECTEURS_DOWNLOAD:
        try:
            els = page.locator(sel).all()
            for el in els:
                if el.is_visible(timeout=500):
                    aria  = el.get_attribute("aria-label") or ""
                    title = el.get_attribute("title") or ""
                    txt   = el.inner_text(timeout=200).strip().replace("\n", " ")[:40]
                    box   = el.bounding_box()
                    print(f"  Clic : [{repr(txt)}] aria={repr(aria)} title={repr(title)} pos={box}")
                    el.scroll_into_view_if_needed()
                    el.click()
                    return True
        except Exception:
            pass
    return False


# ---------------------------------------------------------------------------
# Gestion dropdown / modal apres clic Download
# ---------------------------------------------------------------------------

QUALITES_SEL = [
    "[role='menuitem']:has-text('1080')",
    "[role='menuitem']:has-text('720')",
    "[role='option']:has-text('1080')",
    "[role='option']:has-text('720')",
    "li.ant-dropdown-menu-item:has-text('1080')",
    "li.ant-dropdown-menu-item:has-text('720')",
    "li:has-text('1080p')",
    "li:has-text('720p')",
    "[role='dialog'] :text('1080')",
    "[role='dialog'] :text('720')",
    ".ant-modal :text('1080')",
    ".ant-modal :text('720')",
    ":text('1080p')",
    ":text('720p')",
    ":text('Original')",
]

CONFIRMER_SEL = [
    "[role='dialog'] button:has-text('Download')",
    "[role='dialog'] button:has-text('Confirm')",
    ".ant-modal-footer button:last-child",
    ".ant-modal button:has-text('Download')",
    "button:has-text('Start Download')",
    "button:has-text('Download Video')",
]

def gerer_apres_clic(page, nom_carte):
    page.wait_for_timeout(1500)

    # Screenshot diagnostic
    shot = Path(__file__).parent / f"debug_{nom_carte.replace(' ', '_')}.png"
    try:
        page.screenshot(path=str(shot))
        print(f"  Screenshot : {shot}")
    except Exception:
        pass

    # Log elements detectes
    for sel in ["[role='menu']", "[role='dialog']", ".ant-dropdown",
                ".ant-modal", ".ant-dropdown-menu",
                "[class*='dropdown' i]", "[class*='popover' i]",
                "[class*='menu' i]"]:
        try:
            if page.locator(sel).first.is_visible(timeout=300):
                print(f"  Detecte : {sel}")
        except Exception:
            pass

    # Essaie de cliquer une option de qualite
    for sel in QUALITES_SEL:
        try:
            el = page.locator(sel).first
            if el.is_visible(timeout=500):
                txt = el.inner_text(timeout=200).strip().replace("\n", " ")[:30]
                el.click()
                print(f"  Qualite cliquee : {repr(txt)} ({sel})")
                page.wait_for_timeout(800)
                for csel in CONFIRMER_SEL:
                    try:
                        c = page.locator(csel).first
                        if c.is_visible(timeout=1500):
                            c.click()
                            print(f"  Confirme : {csel}")
                            return
                    except Exception:
                        pass
                return
        except Exception:
            pass

    # Pas de qualite : essaie directement la confirmation
    for csel in CONFIRMER_SEL:
        try:
            c = page.locator(csel).first
            if c.is_visible(timeout=800):
                c.click()
                print(f"  Confirme direct : {csel}")
                return
        except Exception:
            pass

    print("  Aucune option/confirmation trouvee")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    with sync_playwright() as p:
        browser = p.chromium.launch_persistent_context(
            user_data_dir=str(SESSION_DIR),
            channel="msedge",
            headless=False,
            accept_downloads=True,
            viewport={"width": 1280, "height": 800},
        )
        try:
            page    = browser.pages[0] if browser.pages else browser.new_page()
            projets = projets_locaux()

            # Mecanisme 1 : download event
            dl_events = []
            def on_download(dl):
                print(f"  [DL-event] {dl.suggested_filename}")
                dl_events.append(dl)
            page.on("download", on_download)

            # Mecanisme 2 : popup / nouvelle fenetre
            popups = []
            def on_popup(popup):
                print(f"  [Popup] {popup.url}")
                popups.append(popup)
            page.on("popup", on_popup)

            # Mecanisme 3 : interception requetes MP4
            mp4_urls = []
            def on_request(request):
                url = request.url
                if re.search(r"\.(mp4|webm|mov)(\?|$)", url, re.I) or \
                   ("heygen" in url and "download" in url.lower()):
                    print(f"  [URL-MP4] {url[:100]}")
                    mp4_urls.append(url)
            page.on("request", on_request)

            print("Ouverture de HeyGen...")
            page.goto(URL_TRANSLATE)
            page.wait_for_timeout(8000)

            cibles = trouver_cartes_cibles(page, projets)
            print(f"\n{len(cibles)} carte(s) trouvee(s) :\n  " + "\n  ".join(cibles))

            resultats = []

            for i, nom_carte in enumerate(cibles):
                print(f"\n--- [{i+1}/{len(cibles)}] {nom_carte} ---")
                try:
                    if not cliquer_carte(page, nom_carte):
                        print("  Carte introuvable")
                        continue

                    print("  Navigation vers page video...")
                    try:
                        page.wait_for_url("**/videos/**", timeout=10000)
                    except Exception:
                        print("  Navigation non detectee, on continue")

                    print(f"  URL : {page.url}")
                    try:
                        page.wait_for_load_state("networkidle", timeout=20000)
                    except Exception:
                        pass
                    page.wait_for_timeout(2000)

                    n_dl  = len(dl_events)
                    n_pop = len(popups)
                    n_mp4 = len(mp4_urls)

                    print("  Clic Download...")
                    if not cliquer_download(page):
                        print("  Bouton introuvable -- dump:")
                        try:
                            for btn in page.locator("button").all()[:20]:
                                try:
                                    t = btn.inner_text(timeout=200).strip().replace("\n", " ")
                                    a = btn.get_attribute("aria-label") or ""
                                    if t or a:
                                        print(f"    [{repr(t[:50])}] aria={repr(a)}")
                                except Exception:
                                    pass
                        except Exception:
                            pass
                        page.go_back()
                        page.wait_for_timeout(3000)
                        continue

                    gerer_apres_clic(page, nom_carte)

                    print("  Attente capture (max 30s)...")
                    capture = None
                    for tick in range(30):
                        page.wait_for_timeout(1000)
                        if len(dl_events) > n_dl:
                            dl = dl_events[-1]
                            print(f"  [OK] Download event : {dl.suggested_filename}")
                            capture = {"type": "event", "dl": dl, "carte": nom_carte}
                            break
                        if len(popups) > n_pop:
                            pop = popups[-1]
                            print(f"  [OK] Popup : {pop.url}")
                            capture = {"type": "popup", "url": pop.url, "carte": nom_carte}
                            break
                        new_mp4 = mp4_urls[n_mp4:]
                        if new_mp4:
                            url = new_mp4[-1]
                            print(f"  [OK] URL MP4 : {url[:80]}")
                            capture = {"type": "url", "url": url, "carte": nom_carte}
                            break
                        if tick % 5 == 4:
                            print(f"  ... {tick+1}s")

                    if capture:
                        resultats.append(capture)
                    else:
                        print("  Echec 30s -- screenshot final")
                        shot = Path(__file__).parent / f"timeout_{nom_carte.replace(' ','_')}.png"
                        try:
                            page.screenshot(path=str(shot))
                            print(f"  Screenshot : {shot}")
                        except Exception:
                            pass

                    print("  Retour liste...")
                    page.go_back()
                    try:
                        page.wait_for_load_state("networkidle", timeout=15000)
                    except Exception:
                        pass
                    page.wait_for_timeout(3000)

                except Exception as e:
                    print(f"  Erreur : {e}")
                    try:
                        page.go_back()
                        page.wait_for_timeout(3000)
                    except Exception:
                        pass

            # ------------------------------------------------------------------
            # Sauvegarde
            # ------------------------------------------------------------------
            print(f"\n=== {len(resultats)} capture(s) a sauvegarder ===")
            sauvegardes = 0

            for r in resultats:
                nom_carte = r["carte"]
                try:
                    if r["type"] == "event":
                        dl          = r["dl"]
                        nom_fichier = dl.suggested_filename or f"{nom_carte}.mp4"
                        dest        = chemin_dest(nom_fichier, nom_carte, projets)
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        print(f"  Sauvegarde (event) : {dest}")
                        dl.save_as(str(dest))
                        print(f"  OK : {dest.name}")
                        sauvegardes += 1
                    elif r["type"] in ("url", "popup"):
                        url         = r["url"]
                        nom_fichier = re.sub(r"\?.*$", "", url.split("/")[-1])
                        if not nom_fichier or not nom_fichier.lower().endswith(".mp4"):
                            nom_fichier = f"{nom_carte}.mp4"
                        dest = chemin_dest(nom_fichier, nom_carte, projets)
                        print(f"  Telechargement (url) : {dest}")
                        telecharger_url(url, dest)
                        sauvegardes += 1
                except Exception as e:
                    print(f"  Erreur sauvegarde {nom_carte} : {e}")
                    fallback = VIDEOS_EN_COURS / "downloads_heygen" / f"{nom_carte}.mp4"
                    fallback.parent.mkdir(parents=True, exist_ok=True)
                    try:
                        if r["type"] == "event":
                            r["dl"].save_as(str(fallback))
                        else:
                            telecharger_url(r["url"], fallback)
                        print(f"  Secours OK : {fallback}")
                        sauvegardes += 1
                    except Exception as e2:
                        print(f"  Echec total : {e2}")

            print(f"\n=== Termine : {sauvegardes} video(s) sauvegardee(s) ===")
            if sauvegardes > 0:
                print(f"Dossier : {VIDEOS_EN_COURS}")
            input("Appuie sur ENTREE pour fermer : ")

        except Exception as e:
            print(f"Erreur generale : {e}")
        finally:
            try:
                browser.close()
            except Exception:
                pass


main()
