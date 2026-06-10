from pathlib import Path

BASE_DIR        = Path(__file__).parent
VIDEOS_EN_COURS = BASE_DIR / "videos_en_cours"

# Toutes les langues gérées par le pipeline (FR = source, pas traduite)
LANGUES_CONNUES = {"fr", "en", "de", "es", "it", "pt", "ar", "ja", "zh", "ko", "ru", "nl", "pl"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv"}


def has_files(folder: Path) -> bool:
    if not folder.exists():
        return False
    return any(f.is_file() for f in folder.iterdir())


def has_video(folder: Path) -> bool:
    if not folder.exists():
        return False
    return any(f.suffix.lower() in VIDEO_EXTENSIONS for f in folder.iterdir())


def check(condition: bool) -> str:
    return "☑" if condition else "☐"


def langues_du_projet(projet: Path) -> list[str]:
    """Retourne les codes langue détectés dans le projet, triés."""
    return sorted(
        d.name for d in projet.iterdir()
        if d.is_dir() and d.name in LANGUES_CONNUES
    )


def afficher_status(projet: Path):
    nom = projet.name
    langues = langues_du_projet(projet)
    manifest_ok = (projet / "manifest.json").exists()

    print(f"\nVidéo : {nom}  [{', '.join(langues) if langues else 'aucune langue'}]")
    print("-" * 48)

    dossier_cree = projet.exists()
    video_fr = has_video(projet / "fr" / "video")
    print(f"  {check(dossier_cree)} Dossier créé")
    print(f"  {check(video_fr)} Vidéo FR source rangée")
    print(f"  {check(manifest_ok)} manifest.json")
    print()

    if not langues:
        print("  (aucune traduction trouvée)")
        return

    # Largeur de colonne selon le nombre de langues
    col = 6
    header = "  " + "".join(f"{lg.upper():>{col}}" for lg in langues)
    sep    = "  " + "-" * (col * len(langues))

    def ligne(label: str, fn):
        cases = "".join(f"{check(fn(lg)):>{col}}" for lg in langues)
        print(f"  {label:<24}{cases}")

    print(header)
    print(sep)
    ligne("Traduction (vidéo)",  lambda lg: has_video(projet / lg / "video"))
    ligne("TikTok prêt",         lambda lg: has_video(projet / lg / "tiktok"))
    ligne("YouTube prêt",        lambda lg: has_video(projet / lg / "youtube"))
    ligne("SRT extrait",         lambda lg: has_files(projet / lg / "youtube") and
                                             any((projet / lg / "youtube").glob("*.srt")))
    ligne("Éditorial rempli",    lambda lg: _editorial_ok(projet, lg))
    print(sep)
    print()

    copie_serveur = (projet / "copie_serveur.done").exists()
    print(f"  {check(copie_serveur)} Copie serveur")


def _editorial_ok(projet: Path, lang: str) -> bool:
    """Vérifie que le champ editorial.title est rempli dans le manifest."""
    import json
    m = projet / "manifest.json"
    if not m.exists():
        return False
    try:
        d = json.loads(m.read_text(encoding="utf-8"))
        return bool(d.get("languages", {}).get(lang, {}).get("editorial", {}).get("title"))
    except Exception:
        return False


def main():
    if not VIDEOS_EN_COURS.exists():
        print("Aucun projet trouvé (dossier videos_en_cours absent)")
        return

    projets = sorted([p for p in VIDEOS_EN_COURS.iterdir() if p.is_dir()])

    if not projets:
        print("Aucun projet en cours.")
        return

    print(f"=== AVF — État des projets ({len(projets)} vidéo(s)) ===")
    for projet in projets:
        afficher_status(projet)


if __name__ == "__main__":
    main()
