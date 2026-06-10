from pathlib import Path
import shutil

# Répertoires principaux
BASE_DIR = Path.cwd()

VIDEOS_SOURCE = BASE_DIR / "videos_sources"
VIDEOS_EN_COURS = BASE_DIR / "videos_en_cours"

LANGUES = ["fr", "en", "de", "es"]

def create_project(video_file):

    nom_video = video_file.stem

    projet = VIDEOS_EN_COURS / nom_video

    if projet.exists():
        print(f"Projet déjà existant : {nom_video}")
        return

    print(f"Création du projet : {nom_video}")

    for langue in LANGUES:

        (projet / langue / "video").mkdir(parents=True, exist_ok=True)
        (projet / langue / "titres").mkdir(parents=True, exist_ok=True)
        (projet / langue / "youtube").mkdir(parents=True, exist_ok=True)
        (projet / langue / "tiktok").mkdir(parents=True, exist_ok=True)

    # Copie vidéo originale
    shutil.copy2(
        video_file,
        projet / "fr" / "video" / video_file.name
    )

    print("Projet créé avec succès")


def main():

    fichiers_video = []

    extensions = [".mp4", ".mov", ".mkv"]

    for ext in extensions:
        fichiers_video.extend(
            VIDEOS_SOURCE.glob(f"*{ext}")
        )

    if not fichiers_video:
        print("Aucune vidéo trouvée")
        return

    for video in fichiers_video:
        create_project(video)


if __name__ == "__main__":
    main()
