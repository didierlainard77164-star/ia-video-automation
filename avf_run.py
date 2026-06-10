# -*- coding: utf-8 -*-
"""
AVF -- Orchestrateur : lance la chaine complete pour un projet.

Etapes :
  1. Verifie que la video FR source est en place
  2. Telecharge les traductions depuis HeyGen  (heygen_download.py)
  3. Post-traite + genere le manifest.json     (avf_post.py)
  4. Affiche le status final                   (avf_status.py)

Usage :
    py avf_run.py "6 st"          # projet complet
    py avf_run.py "6 st" --post   # post-traitement seul (HeyGen deja fait)
    py avf_run.py "6 st" --status # status seul
"""

import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import urlretrieve

AVF_DIR         = Path(__file__).parent
VIDEOS_EN_COURS = AVF_DIR / "videos_en_cours"
VIDEO_EXT       = {".mp4", ".mov", ".mkv", ".avi"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def titre(texte: str):
    print(f"\n{'='*55}")
    print(f"  {texte}")
    print(f"{'='*55}")


def etape(n: int, texte: str):
    print(f"\n[{n}] {texte}")
    print("-" * 45)


def run(script: str, args: list[str] = []) -> int:
    cmd = ["py", str(AVF_DIR / script)] + args
    result = subprocess.run(cmd, cwd=str(AVF_DIR))
    return result.returncode


def trouver_projet(filtre: str) -> Path | None:
    filtre = filtre.strip().lower()
    for p in VIDEOS_EN_COURS.iterdir():
        if p.is_dir() and filtre in p.name.lower():
            return p
    return None


def video_fr_presente(projet: Path) -> Path | None:
    fr_video = projet / "fr" / "video"
    if not fr_video.exists():
        return None
    for f in fr_video.iterdir():
        if f.is_file() and f.suffix.lower() in VIDEO_EXT:
            return f
    return None


def creer_dossiers_langue(projet: Path, langues: list[str]):
    """Pre-cree l'arborescence pour chaque langue."""
    for lang in langues:
        for sub in ("video", "tiktok", "youtube", "titres"):
            (projet / lang / sub).mkdir(parents=True, exist_ok=True)


def normaliser_url(url: str) -> str:
    raw = (url or "").strip()
    if not raw:
        return ""
    if raw.startswith("http://") or raw.startswith("https://"):
        return raw
    return f"https://{raw}"


def telecharger_video_depuis_url(url: str, dest_dir: Path) -> Path | None:
    """Telecharge une video source dans fr/video depuis une URL directe ou via yt-dlp."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    parsed = urlparse(url)
    suffix = Path(parsed.path).suffix.lower()

    # Cas simple : URL directe vers un fichier video
    if suffix in VIDEO_EXT:
        nom = Path(parsed.path).name or "source.mp4"
        target = dest_dir / nom
        print(f"  Telechargement direct : {url}")
        urlretrieve(url, str(target))
        print(f"  ✓ Video source enregistree : {target.name}")
        return target

    # Cas general : URL de page (YouTube, Vimeo, site web, etc.)
    print("  URL non directe, tentative via yt-dlp...")
    out_tpl = str(dest_dir / "source_url_%(title).80s.%(ext)s")
    cmd = ["py", "-m", "yt_dlp", "-f", "mp4/best", "--no-playlist", "-o", out_tpl, url]
    result = subprocess.run(cmd, cwd=str(AVF_DIR))
    if result.returncode != 0:
        return None

    # Prend la video la plus recente creee dans le dossier
    videos = sorted(
        [f for f in dest_dir.iterdir() if f.is_file() and f.suffix.lower() in VIDEO_EXT],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return videos[0] if videos else None


# ---------------------------------------------------------------------------
# Modes
# ---------------------------------------------------------------------------

def mode_complet(projet: Path):
    """Telechargement HeyGen + post-traitement + status."""
    titre(f"AVF — Pipeline complet : {projet.name}")

    # Etape 1 — Video FR
    etape(1, "Verification video FR source")
    vid = video_fr_presente(projet)
    if vid:
        print(f"  ✓ {vid.name}")
    else:
        print(f"  ✗ Aucune video dans {projet}/fr/video/")
        print("    Place ta video FR dans ce dossier, puis relance.")
        sys.exit(1)

    # Etape 2 — HeyGen download
    etape(2, "Telechargement depuis HeyGen")
    print("  (Le navigateur Edge va s'ouvrir — ne pas fermer)")
    time.sleep(1)
    code = run("heygen_download.py")
    if code != 0:
        print(f"\n  ! heygen_download.py a echoue (code {code})")
        print("    Verifie que HeyGen a bien termine les traductions.")
        sys.exit(code)

    # Etape 3 — Post-traitement
    etape(3, "Post-traitement FFmpeg + manifest.json")
    code = run("avf_post.py", [projet.name])
    if code != 0:
        print(f"\n  ! avf_post.py a echoue (code {code})")
        sys.exit(code)

    # Etape 4 — Sync
    etape(4, "Synchronisation vers videos_finales/ et Linux")
    run("avf_sync.py", [projet.name])

    # Etape 5 — Status
    etape(5, "Etat final du projet")
    run("avf_status.py")

    titre(f"Pipeline termine : {projet.name}")
    print("  Prochaine etape : remplir l'editorial (ChatGPT + Linux)")
    print(f"  Manifest : {projet / 'manifest.json'}")


def mode_post(projet: Path):
    """Post-traitement seul (HeyGen deja fait)."""
    titre(f"AVF — Post-traitement : {projet.name}")
    etape(1, "Post-traitement FFmpeg + manifest.json")
    code = run("avf_post.py", [projet.name])
    if code != 0:
        sys.exit(code)
    etape(2, "Synchronisation vers videos_finales/ et Linux")
    run("avf_sync.py", [projet.name])
    etape(3, "Etat final")
    run("avf_status.py")


def mode_status():
    """Status seul."""
    run("avf_status.py")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    args = sys.argv[1:]

    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        sys.exit(0)

    # Flags
    only_post   = "--post"   in args
    only_status = "--status" in args
    url_source = None
    if "--url" in args:
        try:
            idx = args.index("--url")
            url_source = normaliser_url(args[idx + 1])
        except Exception:
            print("Usage URL invalide : --url <adresse>")
            sys.exit(1)

    nom_projet  = next((a for a in args if not a.startswith("--")), None)

    if only_status:
        mode_status()
        return

    if not nom_projet:
        print("Usage : py avf_run.py \"nom du projet\" [--post|--status]")
        sys.exit(1)

    if not VIDEOS_EN_COURS.exists():
        print(f"Dossier introuvable : {VIDEOS_EN_COURS}")
        sys.exit(1)

    projet = trouver_projet(nom_projet)
    if not projet:
        # Creer le dossier si nouveau projet
        projet = VIDEOS_EN_COURS / nom_projet
        projet.mkdir(parents=True, exist_ok=True)
        (projet / "fr" / "video").mkdir(parents=True, exist_ok=True)
        print(f"Nouveau projet cree : {projet}")

    # Si URL fournie, tente de telecharger automatiquement la source FR
    if url_source:
        fr_video_dir = projet / "fr" / "video"
        vid_existante = video_fr_presente(projet)
        if vid_existante:
            print(f"Source FR deja presente, URL ignoree : {vid_existante.name}")
        else:
            print(f"Telechargement source depuis URL : {url_source}")
            try:
                telechargee = telecharger_video_depuis_url(url_source, fr_video_dir)
            except Exception as e:
                print(f"  ! Echec telechargement URL : {e}")
                sys.exit(1)
            if not telechargee:
                print("  ! Impossible de recuperer une video depuis cette URL.")
                print("    Conseil: fournir une URL directe .mp4 ou installer/valider yt-dlp.")
                sys.exit(1)

    if not video_fr_presente(projet):
        print(f"  -> Place ta video FR dans : {projet / 'fr' / 'video'}")
        sys.exit(0)

    if only_post:
        mode_post(projet)
    else:
        mode_complet(projet)


if __name__ == "__main__":
    main()
