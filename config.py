# -*- coding: utf-8 -*-
"""
AVF -- Configuration des chemins de synchronisation.
Modifie ce fichier selon ton installation.
"""

from pathlib import Path

# ---------------------------------------------------------------------------
# Chemin vers le partage Samba Linux (projet lvd17)
# Exemples :
#   Lecteur reseau mappe     : Path("Z:/lvd17/avf")
#   Chemin UNC direct        : Path(r"\\nom-du-serveur\lvd17\avf")
#   Chemin UNC avec IP       : Path(r"\\192.168.1.50\lvd17\avf")
# ---------------------------------------------------------------------------
CHEMIN_LINUX = Path(r"\\192.168.0.193\lvd17\avf")

# ---------------------------------------------------------------------------
# Dossier local de livraison finale (archive Windows)
# ---------------------------------------------------------------------------
VIDEOS_FINALES = Path(__file__).parent / "videos_finales"

# ---------------------------------------------------------------------------
# Fichiers a synchroniser par langue (relatifs au dossier langue)
# On copie aussi les sources et les documents editoriaux pour que l'autre PC
# puisse reconstruire le manifest et reutiliser les livrables sans ambiguite.
# ---------------------------------------------------------------------------
PATTERNS_SYNC = [
    "video/*.mp4",
    "video/*.srt",
    "editorial/*",
    "tiktok/*.mp4",
    "youtube/*.mp4",
    "youtube/*.srt",
]

# Fichiers a la racine du projet (pas d'un sous-dossier langue)
FICHIERS_RACINE = [
    "manifest.json",
]
