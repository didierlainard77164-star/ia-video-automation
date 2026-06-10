# -*- coding: utf-8 -*-
"""
AVF -- Synchronisation vers videos_finales/ (local) et Linux (Samba).

Copie les fichiers utiles d'un projet vers deux destinations :
  1. videos_finales/<projet>/    (archive Windows locale)
  2. <CHEMIN_LINUX>/<projet>/    (partage Samba Linux - lvd17)

Sont copies : sources video/SRT, livrables TikTok/YouTube, documents editoriaux,
et manifest.json.
Un fichier copie_serveur.done est cree apres succes complet.

Usage :
    py avf_sync.py "6 st"        # sync un projet
    py avf_sync.py               # sync tous les projets
    py avf_sync.py "6 st" --dry  # simulation sans copier
"""

import shutil
import sys
import threading
from pathlib import Path

AVF_DIR         = Path(__file__).parent
VIDEOS_EN_COURS = AVF_DIR / "videos_en_cours"
LANGUES_CONNUES = {"fr", "en", "de", "es", "it", "pt", "ar", "ja", "zh", "ko", "ru", "nl", "pl"}

try:
    from config import CHEMIN_LINUX, VIDEOS_FINALES, PATTERNS_SYNC, FICHIERS_RACINE
except ImportError:
    print("ERREUR : config.py introuvable. Cree-le depuis config.py.")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------

def path_accessible(path: Path, timeout: float = 3.0) -> bool:
    """Teste l'accessibilite d'un chemin reseau avec timeout (evite le gel Windows)."""
    result = [False]
    def check():
        try:
            result[0] = path.exists()
        except Exception:
            result[0] = False
    t = threading.Thread(target=check, daemon=True)
    t.start()
    t.join(timeout)
    return result[0]


def copier(src: Path, dst: Path, dry: bool) -> bool:
    """Copie src -> dst. Retourne True si copie effectuee."""
    if not src.exists():
        return False
    if dst.exists() and dst.stat().st_mtime >= src.stat().st_mtime:
        return False  # deja a jour
    if not dry:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    return True


def sync_projet(projet: Path, destination: Path, dry: bool, label: str) -> tuple[int, int]:
    """Sync un projet vers une destination. Retourne (copies, erreurs)."""
    copies = 0
    erreurs = 0

    # Fichiers par langue
    for lang_dir in sorted(projet.iterdir()):
        if not lang_dir.is_dir() or lang_dir.name not in LANGUES_CONNUES:
            continue
        for pattern in PATTERNS_SYNC:
            for src in lang_dir.glob(pattern):
                # Chemin relatif depuis la racine du projet
                rel = Path(lang_dir.name) / src.relative_to(lang_dir)
                dst = destination / projet.name / rel
                try:
                    if copier(src, dst, dry):
                        action = "[DRY]" if dry else "  +"
                        print(f"  {action} {label}/{projet.name}/{rel}")
                        copies += 1
                except Exception as e:
                    print(f"  ! ERREUR {src.name} → {label} : {e}")
                    erreurs += 1

    # Fichiers racine (manifest.json, etc.)
    for nom in FICHIERS_RACINE:
        src = projet / nom
        dst = destination / projet.name / nom
        try:
            if copier(src, dst, dry):
                action = "[DRY]" if dry else "  +"
                print(f"  {action} {label}/{projet.name}/{nom}")
                copies += 1
        except Exception as e:
            print(f"  ! ERREUR {nom} → {label} : {e}")
            erreurs += 1

    return copies, erreurs


def sync_un_projet(projet: Path, dry: bool) -> bool:
    print(f"\n{'='*55}")
    print(f"  Sync : {projet.name}{' [DRY RUN]' if dry else ''}")
    print(f"{'='*55}")

    marker = projet / "copie_serveur.done"
    total_copies = 0
    total_erreurs = 0

    # -- Destination 1 : videos_finales/ local --
    print(f"\n  → Local (videos_finales/)")
    c, e = sync_projet(projet, VIDEOS_FINALES, dry, "videos_finales")
    total_copies += c
    total_erreurs += e
    if c == 0 and e == 0:
        print("    (deja a jour)")

    # -- Destination 2 : Linux Samba --
    print(f"\n  → Linux ({CHEMIN_LINUX})")
    if not path_accessible(CHEMIN_LINUX, timeout=3.0):
        print(f"    ! Partage inaccessible (timeout 3s) — Linux eteint ou chemin incorrect")
        print(f"    ! Modifie CHEMIN_LINUX dans config.py si besoin")
        samba_ok = False
    else:
        c, e = sync_projet(projet, CHEMIN_LINUX, dry, "linux")
        total_copies += c
        total_erreurs += e
        if c == 0 and e == 0:
            print("    (deja a jour)")
        samba_ok = (e == 0)

    # -- Bilan --
    print(f"\n  Bilan : {total_copies} fichier(s) copie(s), {total_erreurs} erreur(s)")

    if not dry and total_erreurs == 0 and samba_ok:
        marker.touch()
        print(f"  ✓ copie_serveur.done cree")
    elif dry:
        print("  (simulation — aucun fichier touche)")

    return total_erreurs == 0


def main():
    args = sys.argv[1:]
    dry  = "--dry" in args
    noms = [a for a in args if not a.startswith("--")]

    if not VIDEOS_EN_COURS.exists():
        print(f"Dossier introuvable : {VIDEOS_EN_COURS}")
        sys.exit(1)

    if noms:
        filtre = noms[0].strip().lower()
        projets = [
            p for p in VIDEOS_EN_COURS.iterdir()
            if p.is_dir() and filtre in p.name.lower()
        ]
    else:
        projets = sorted(p for p in VIDEOS_EN_COURS.iterdir() if p.is_dir())

    if not projets:
        print("Aucun projet trouve.")
        sys.exit(0)

    succes = 0
    for projet in projets:
        ok = sync_un_projet(projet, dry)
        if ok:
            succes += 1

    print(f"\n=== Sync termine : {succes}/{len(projets)} projet(s) OK ===")


if __name__ == "__main__":
    main()
