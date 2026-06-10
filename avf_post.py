# -*- coding: utf-8 -*-
"""
AVF -- Post-traitement des videos traduites par HeyGen.

Pour chaque video dans videos_en_cours/<projet>/<lang>/video/ :
  - TikTok  : portrait 9:16,  sous-titres graves, encode optimise
  - YouTube : paysage 16:9,   fond flou, sous-titres graves, haute qualite

Usage :
    py avf_post.py                  # traite tous les projets
    py avf_post.py "6 st"           # traite un seul projet
"""

import subprocess
import shutil
import sys
import json
import datetime
from pathlib import Path

# Forcer UTF-8 sur stdout meme quand lance en sous-processus (pipe Windows cp1252)
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

VIDEOS_EN_COURS = Path(__file__).parent / "videos_en_cours"
BASE_DIR        = Path(__file__).parent   # racine avf/

CRF_TIKTOK  = 23   # bon compromis qualite/taille pour TikTok
CRF_YOUTUBE = 18   # haute qualite YouTube

# Whisper model to use for ASR fallback: tiny, base, small, medium, large
WHISPER_MODEL = "small"

LANGUES_CONNUES = {"en", "de", "es", "fr", "it", "pt", "ar"}

LANG_LABELS = {
    "fr": "Français", "en": "English", "de": "Deutsch",
    "es": "Español", "it": "Italiano", "pt": "Português", "ar": "العربية",
}


# ---------------------------------------------------------------------------
# Helpers FFmpeg
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Helpers manifest
# ---------------------------------------------------------------------------

def get_duration(path: Path) -> float | None:
    """Retourne la duree en secondes via ffprobe, ou None."""
    if not path or not path.exists():
        return None
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_format", str(path)],
            capture_output=True, text=True, encoding="utf-8"
        )
        return round(float(json.loads(result.stdout)["format"]["duration"]), 2)
    except Exception:
        return None


def rel(path: Path | None) -> str | None:
    """Chemin relatif depuis BASE_DIR, separateurs Unix, ou None."""
    if path is None or not path.exists():
        return None
    try:
        return str(path.relative_to(BASE_DIR)).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def build_language_entry(projet: Path, lang: str, now: str) -> dict:
    lang_dir  = projet / lang
    video_dir = lang_dir / "video"
    tiktok_dir = lang_dir / "tiktok"
    youtube_dir = lang_dir / "youtube"

    sources     = sorted(video_dir.glob("*.mp4")) if video_dir.exists() else []
    source_srts = sorted(video_dir.glob("*.srt")) if video_dir.exists() else []
    input_mp4   = sources[0] if sources else None
    base        = input_mp4.stem.replace("_with_captions", "") if input_mp4 else f"{projet.name.replace(' ','_')}-{lang}"

    srt_video   = source_srts[0] if source_srts else None
    tiktok_mp4  = (tiktok_dir / f"{base}_tiktok.mp4") if tiktok_dir.exists() else None
    youtube_mp4 = (youtube_dir / f"{base}_youtube.mp4") if youtube_dir.exists() else None
    srt_youtube = (youtube_dir / srt_video.name) if (srt_video and youtube_dir.exists()) else None

    def ready(p): return p is not None and p.exists()

    status = "ready_for_editorial" if (ready(tiktok_mp4) and ready(youtube_mp4)) \
             else ("processing" if ready(input_mp4) else "pending")

    return {
        "languageCode": lang,
        "languageLabel": LANG_LABELS.get(lang, lang),
        "status": status,
        "folders": {
            "root":    f"videos_en_cours/{projet.name}/{lang}",
            "video":   f"videos_en_cours/{projet.name}/{lang}/video",
            "tiktok":  f"videos_en_cours/{projet.name}/{lang}/tiktok",
            "youtube": f"videos_en_cours/{projet.name}/{lang}/youtube",
        },
        "inputs": {
            "translatedVideoWithCaptions": {
                "path": rel(input_mp4), "kind": "video", "role": "language_source",
                "format": "mp4", "aspectRatio": "unknown", "subtitlesBurned": True,
                "audioLanguage": lang,
                "subtitleLanguage": lang if ready(srt_video) else None,
                "ready": ready(input_mp4), "checksum": None,
                "durationSeconds": get_duration(input_mp4),
                "notes": "Source HeyGen" if lang != "fr" else "Source originale",
            },
            "translatedSrt": {
                "path": rel(srt_video), "kind": "subtitle",
                "role": "language_source_subtitles", "format": "srt",
                "language": lang, "ready": ready(srt_video), "checksum": None,
                "notes": "Sous-titres extraits" if ready(srt_video) else None,
            },
        },
        "deliverables": {
            "verticalSocialMaster": {
                "path": rel(tiktok_mp4), "kind": "video",
                "role": "vertical_social_master", "format": "mp4",
                "aspectRatio": "9:16", "resolution": "1080x1920",
                "subtitlesBurned": False, "captionHandling": "platform_native",
                "ready": ready(tiktok_mp4), "checksum": None,
                "durationSeconds": get_duration(tiktok_mp4),
                "notes": "Master vertical propre pour TikTok, Reels et Shorts",
            },
            "horizontalLongMaster": {
                "path": rel(youtube_mp4), "kind": "video",
                "role": "horizontal_long_master", "format": "mp4",
                "aspectRatio": "16:9", "resolution": "1920x1080",
                "subtitlesBurned": False, "captionHandling": "external_srt",
                "ready": ready(youtube_mp4), "checksum": None,
                "durationSeconds": get_duration(youtube_mp4),
                "notes": "Version paysage avec fond floute pour YouTube",
            },
            "horizontalLongSrt": {
                "path": rel(srt_youtube), "kind": "subtitle",
                "role": "horizontal_long_subtitles", "format": "srt",
                "language": lang, "ready": ready(srt_youtube), "checksum": None,
                "notes": "Sous-titres a uploader sur YouTube",
            },
            "futureAssets": {
                "verticalCaptionedMaster": {"path": None, "ready": False, "notes": "Reserve pour un futur besoin hors TikTok"},
                "thumbnail":    {"path": None, "ready": False},
                "squarePreview": {"path": None, "ready": False},
                "audioOnly":    {"path": None, "ready": False},
                "chaptersJson": {"path": None, "ready": False},
                "posterFrame":  {"path": None, "ready": False},
            },
        },
        "editorial": {
            "title": None, "shortTitle": None, "internalTitle": None,
            "description": None, "hook": None, "cta": None,
            "hashtags": [], "keywords": [], "summary": None,
            "speakerName": None, "seriesName": None, "episodeLabel": None,
            "topic": None, "audience": None, "tone": None,
            "complianceNotes": None, "filledBy": None, "filledAt": None,
        },
        "publicationPlan": {
            "campaignName": None, "scheduledAt": None,
            "timezone": "Europe/Paris", "autoPublish": True,
            "targets": {
                "tiktok":          {"enabled": True,  "assetRef": "verticalSocialMaster", "subtitleMode": "platform_native", "captionRef": "editorial.description", "hashtagsRef": "editorial.hashtags", "scheduledAt": None, "status": "pending", "metricool": {"brandId": None, "providerId": None}, "notes": "TikTok gere ses propres sous-titres"},
                "instagram_reels": {"enabled": False, "assetRef": "verticalSocialMaster", "subtitleMode": "none", "captionRef": "editorial.description", "hashtagsRef": "editorial.hashtags", "scheduledAt": None, "status": "pending", "metricool": {"brandId": None, "providerId": None}, "notes": None},
                "facebook_reels":  {"enabled": False, "assetRef": "verticalSocialMaster", "subtitleMode": "none", "captionRef": "editorial.description", "hashtagsRef": "editorial.hashtags", "scheduledAt": None, "status": "pending", "metricool": {"brandId": None, "providerId": None}, "notes": None},
                "youtube":         {"enabled": False, "assetRef": "horizontalLongMaster", "subtitleAssetRef": "horizontalLongSrt", "subtitleMode": "uploaded_srt", "titleRef": "editorial.title", "descriptionRef": "editorial.description", "hashtagsRef": "editorial.hashtags", "scheduledAt": None, "status": "pending", "metricool": {"brandId": None, "providerId": None}, "notes": None},
                "youtube_shorts":  {"enabled": False, "assetRef": "verticalSocialMaster", "subtitleMode": "none", "titleRef": "editorial.title", "descriptionRef": "editorial.description", "hashtagsRef": "editorial.hashtags", "scheduledAt": None, "status": "pending", "metricool": {"brandId": None, "providerId": None}, "notes": None},
                "facebook_feed":   {"enabled": False, "assetRef": "verticalSocialMaster", "subtitleMode": "none", "captionRef": "editorial.description", "hashtagsRef": "editorial.hashtags", "scheduledAt": None, "status": "pending", "metricool": {"brandId": None, "providerId": None}, "notes": "Decision ulterieure"},
                "linkedin":        {"enabled": False, "assetRef": "horizontalLongMaster", "subtitleMode": "none", "captionRef": "editorial.description", "scheduledAt": None, "status": "pending", "metricool": {"brandId": None, "providerId": None}, "notes": None},
                "x":               {"enabled": False, "assetRef": "verticalSocialMaster", "subtitleMode": "none", "captionRef": "editorial.description", "scheduledAt": None, "status": "pending", "metricool": {"brandId": None, "providerId": None}, "notes": None},
            },
        },
        "platformOverrides": {
            "tiktok":          {"title": None, "description": None, "hashtags": [], "thumbnailPath": None},
            "youtube":         {"title": None, "description": None, "hashtags": [], "thumbnailPath": None, "playlist": None, "category": None},
            "facebook_reels":  {"title": None, "description": None, "hashtags": []},
            "instagram_reels": {"title": None, "description": None, "hashtags": []},
        },
        "qualityControl": {
            "videoPlayable": None, "audioOk": None, "subtitlesOk": None,
            "lipSyncOk": None, "translationOk": None, "brandingOk": None,
            "safeToPublish": None, "validatedBy": None, "validatedAt": None,
            "issues": [],
        },
        "analytics": {
            "campaignCode": None, "trackingLabel": None, "utmSource": None,
            "utmMedium": None, "utmCampaign": None, "targetAudience": None,
            "funnelStage": None, "goal": None,
        },
        "archive": {
            "keepSourceFiles": True, "keepDeliveryFiles": True,
            "publishedUrls": [], "metricoolPostIds": [], "notes": None,
        },
    }


def generer_manifest(projet: Path) -> None:
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    project_id = projet.name.replace(" ", "_").lower()

    langues_dirs = [
        d for d in sorted(projet.iterdir())
        if d.is_dir() and d.name in LANGUES_CONNUES
    ]

    languages = {
        d.name: build_language_entry(projet, d.name, now)
        for d in langues_dirs
    }

    manifest = {
        "schemaVersion": "1.0",
        "project": {
            "projectId": project_id,
            "projectLabel": projet.name,
            "projectType": "video-campaign",
            "workflowSource": "other-pc",
            "primaryLanguage": "fr",
            "status": "in_progress",
            "createdAt": now,
            "updatedAt": now,
            "tags": [], "notes": None,
        },
        "governance": {
            "owner": None, "editorialOwner": None, "technicalOwner": None,
            "validationOwner": None, "rightsStatus": "unknown",
            "usageRightsNotes": None, "consentStatus": "unknown", "consentNotes": None,
        },
        "branding": {
            "brandName": "Les Fermes de la Vie",
            "logoPath": None, "introBackgroundAssetPath": None,
            "outroTemplatePath": None, "thumbnailTemplatePath": None,
            "visualNotes": None,
        },
        "upstreamSource": {
            "primaryCapture": {
                "language": "fr", "videoPath": None, "audioPath": None,
                "transcriptPath": None, "srtPath": None, "capturedAt": None,
                "device": None, "operator": None, "notes": None,
            },
            "translationPipeline": {
                "provider": "HeyGen", "providerJobId": None, "providerRunId": None,
                "sourceMachine": "other-pc", "translationNotes": None,
            },
        },
        "defaults": {
            "timezone": "Europe/Paris",
            "defaultVerticalNetworks":  ["tiktok", "instagram_reels", "facebook_reels", "youtube_shorts"],
            "defaultHorizontalNetworks": ["youtube"],
            "defaultVerticalAssetRef":   "verticalSocialMaster",
            "defaultHorizontalAssetRef": "horizontalLongMaster",
        },
        "languages": languages,
    }

    dest = projet / "manifest.json"
    dest.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n  Manifest genere : {dest}")


def run_ffmpeg(args: list, desc: str) -> bool:
    print(f"    {desc}...", flush=True)
    proc = subprocess.Popen(
        ["ffmpeg", "-y", "-stats"] + args,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace",
        bufsize=1
    )
    last_progress = ""
    for line in proc.stdout:
        line = line.rstrip()
        if not line:
            continue
        # Les lignes de progression FFmpeg contiennent "frame=" ou "size="
        if "frame=" in line or "size=" in line or "time=" in line:
            last_progress = line
            # N'affiche que toutes les N frames pour ne pas noyer la console
            if "fps=" in line:
                print(f"    >> {line}", flush=True)
        elif line.startswith("ffmpeg") or "Error" in line or "error" in line:
            print(f"    ! {line}", flush=True)
        # Les lignes d'info importantes (codec, dimensions...)
        elif any(k in line for k in ("Stream", "Output", "Overwrite", "video:", "audio:")):
            print(f"    {line}", flush=True)
    proc.wait()
    if proc.returncode != 0:
        print(f"    ! FFmpeg echoue (code {proc.returncode})", flush=True)
        return False
    print(f"    OK : {desc}", flush=True)
    return True



# ---------------------------------------------------------------------------
# Etapes de traitement
# ---------------------------------------------------------------------------

def creer_srt_placeholder(srt: Path, lang: str = "fr") -> Path:
    """Crée un fichier SRT placeholder si l'extraction n'est pas possible."""
    srt.parent.mkdir(parents=True, exist_ok=True)
    content = (
        "1\n"
        "00:00:00,000 --> 00:00:01,000\n"
        f"Sous-titres non disponibles pour {lang}.\n"
    )
    srt.write_text(content, encoding="utf-8")
    print(f"    SRT placeholder créé : {srt.name}")
    return srt


def find_subtitle_stream(input_mp4: Path) -> int | None:
    """Retourne l'index du premier flux subtitle, ou None si aucun."""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_streams", str(input_mp4)],
            capture_output=True, text=True, encoding="utf-8"
        )
        if result.returncode != 0:
            return None
        data = json.loads(result.stdout or "{}")
        for stream in data.get("streams", []):
            if stream.get("codec_type") == "subtitle":
                return stream.get("index")
    except Exception:
        pass
    return None


def build_srt_text(segments: list[dict]) -> str:
    lines = []
    for idx, seg in enumerate(segments, start=1):
        start = seg.get("start", 0.0)
        end = seg.get("end", 0.0)
        text = seg.get("text", "").strip().replace("\n", " ")
        start_ts = format_srt_timestamp(start)
        end_ts = format_srt_timestamp(end)
        lines.append(str(idx))
        lines.append(f"{start_ts} --> {end_ts}")
        lines.append(text)
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def format_srt_timestamp(seconds: float) -> str:
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds - int(seconds)) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def transcrire_whisper_srt(input_mp4: Path, lang: str = "fr") -> Path | None:
    """Transcrit une vidéo en SRT via Whisper si le package est installé."""
    try:
        import whisper
    except ImportError:
        print("    Whisper non installé ; installer openai-whisper pour la transcription ASR.")
        return None

    try:
        print(f"    Transcription Whisper ({WHISPER_MODEL}) en cours pour {lang}...")
        model = whisper.load_model(WHISPER_MODEL)
        result = model.transcribe(str(input_mp4), language=lang, task="transcribe", fp16=False)
        segments = result.get("segments", [])
        if not segments:
            print("    Whisper n'a généré aucun segment.")
            return None
        srt = input_mp4.with_suffix(".srt")
        srt.write_text(build_srt_text(segments), encoding="utf-8")
        print(f"    SRT Whisper créé : {srt.name}")
        # Copy to youtube folder for visibility/upload if present
        try:
            lang_dir = input_mp4.parent.parent
            youtube_dir = lang_dir / "youtube"
            if youtube_dir.exists():
                dest = youtube_dir / srt.name
                shutil.copy(srt, dest)
                print(f"    Copie SRT dans youtube/: {dest}")
        except Exception as e:
            print(f"    Erreur copie SRT vers youtube: {e}")
        return srt
    except Exception as exc:
        print(f"    Erreur Whisper : {exc}")
        return None


def extraire_srt(input_mp4: Path, lang: str = "fr", overwrite: bool = False, force_whisper: bool = False) -> Path | None:
    """Extrait la piste ST en .srt a cote de la video. Retourne le chemin ou None."""
    srt = input_mp4.with_suffix(".srt")

    if force_whisper:
        print(f"    --force-whisper : transcription Whisper directe (SRT et flux intégrés ignorés).")
        if srt.exists():
            try:
                srt.unlink()
            except Exception:
                pass
        return transcrire_whisper_srt(input_mp4, lang=lang)

    if srt.exists():
        if not overwrite:
            print(f"    SRT deja present : {srt.name} (utilise --overwrite-srt pour écraser)")
            return srt
        else:
            print(f"    SRT deja present mais sera écrasé : {srt.name}")
            try:
                srt.unlink()
            except Exception:
                pass

    stream_index = find_subtitle_stream(input_mp4)
    if stream_index is not None:
        ok = run_ffmpeg(
            ["-i", str(input_mp4), "-map", f"0:{stream_index}", str(srt)],
            f"Extraction ST -> {srt.name}"
        )
        if ok and srt.exists():
            # also copy to youtube folder for convenience
            try:
                lang_dir = input_mp4.parent.parent
                youtube_dir = lang_dir / "youtube"
                if youtube_dir.exists():
                    dest = youtube_dir / srt.name
                    shutil.copy(srt, dest)
                    print(f"    Copie SRT dans youtube/: {dest}")
            except Exception as e:
                print(f"    Erreur copie SRT vers youtube: {e}")
            return srt
        print(f"    Extraction du flux de sous-titres {stream_index} échouée pour {lang}.")

    print(f"    Aucun flux de sous-titres détecté ou extraction impossible pour {input_mp4.name}. Tentative Whisper.")
    whisper_srt = transcrire_whisper_srt(input_mp4, lang=lang)
    if whisper_srt:
        return whisper_srt

    print(f"    Aucune piste ST trouvée pour {lang}, création d'un placeholder SRT.")
    return creer_srt_placeholder(srt, lang=lang)


def make_tiktok(input_mp4: Path, srt: Path | None, output: Path, overwrite: bool = False) -> bool:
    """Portrait 9:16 SANS sous-titres graves : TikTok genere les siens."""
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists() and not overwrite:
        print(f"    Deja present : {output.name}")
        return True

    return run_ffmpeg([
        "-i", str(input_mp4),
        "-map", "0:v", "-map", "0:a",   # exclut la piste ST
        "-c:v", "libx264", "-crf", str(CRF_TIKTOK), "-preset", "fast",
        "-profile:v", "high", "-level", "4.0",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        str(output)
    ], f"TikTok portrait (ST TikTok natifs) -> {output.name}")


def make_youtube(input_mp4: Path, srt: Path | None, output: Path, overwrite: bool = False) -> bool:
    """Paysage 16:9 a partir d'une source portrait ou paysage.
    Portrait (HeyGen 9:16) : fit-height (personne entiere visible) + bandes floues sur les cotes.
    Paysage               : fond flou + image centree (standard YouTube).
    """

    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists() and not overwrite:
        print(f"    Deja present : {output.name}")
        return True

    # Détection portrait vs paysage
    src_w, src_h = 1920, 1080
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_streams", "-select_streams", "v:0", str(input_mp4)],
            capture_output=True, text=True, encoding="utf-8"
        )
        streams = json.loads(r.stdout).get("streams", [])
        if streams:
            src_w = streams[0].get("width", 1920)
            src_h = streams[0].get("height", 1080)
    except Exception:
        pass

    is_portrait = src_h > src_w

    if is_portrait:
        # Portrait (9:16 HeyGen) : fit-height -> personne entiere visible, bandes floues sur les cotes
        # Zoom : fg occupe 60% de la largeur (1152px), hauteur recadree au centre
        # 720x1280 -> scale 1152x2048 -> crop centre 1152x1080 -> bandes floues ~384px chaque cote
        # On voit ~53% de la hauteur originale (visage + buste clairement visible)
        scale_w = 1152  # 60% de 1920, deja pair
        print(f"    Source portrait {src_w}x{src_h} -> zoom 60% ({scale_w}px large) + bandes floues", flush=True)
        vf = (
            "[0:v]scale=1920:1080,boxblur=luma_radius=30:luma_power=2[bg];"
            f"[0:v]scale={scale_w}:trunc(ih*{scale_w}/iw/2)*2[fg_tall];"
            f"[fg_tall]crop={scale_w}:1080:0:(ih-1080)/2[fg];"
            "[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1[vout]"
        )
    else:
        # Paysage : fond flou + image centree
        print(f"    Source paysage {src_w}x{src_h} -> fond flou 1920x1080", flush=True)
        vf = (
            "[0:v]scale=1920:1080,boxblur=luma_radius=30:luma_power=2[bg];"
            "[0:v]scale=1920:-2[fg];"
            "[bg][fg]overlay=0:(H-h)/2,setsar=1[vout]"
        )

    ok = run_ffmpeg([
        "-i", str(input_mp4),
        "-filter_complex", vf,
        "-map", "[vout]", "-map", "0:a",
        "-c:v", "libx264", "-crf", str(CRF_YOUTUBE), "-preset", "slow",
        "-profile:v", "high", "-level", "4.1",
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        str(output)
    ], f"YouTube paysage -> {output.name}")

    # Copie le SRT a cote pour upload manuel sur YouTube
    if ok and srt and srt.exists():
        srt_dest = output.parent / srt.name
        if not srt_dest.exists():
            shutil.copy(srt, srt_dest)
            print(f"    SRT pret pour upload : {srt_dest.name}")
    return ok


# ---------------------------------------------------------------------------
# Parcours des projets
# ---------------------------------------------------------------------------

def traiter_langue(lang_dir: Path, srt_only: bool = False, overwrite_srt: bool = False, force_whisper: bool = False, overwrite_youtube: bool = False, overwrite_tiktok: bool = False):
    """Traite un dossier de langue (ex: 6 st/es/)."""
    video_dir = lang_dir / "video"
    if not video_dir.exists():
        print(f"    Dossier video absent pour la langue {lang_dir.name} ({lang_dir})")
        return

    sources = sorted(video_dir.glob("*.mp4"))
    if not sources:
        print(f"    Pas de fichier .mp4 trouvé dans {video_dir}")
        return

    input_mp4 = sources[0]
    print(f"\n  [{lang_dir.name}] {input_mp4.name}")

    # Base du nom (retire _with_captions pour les sorties)
    base = input_mp4.stem.replace("_with_captions", "")

    # 1. Extraction ST
    srt = extraire_srt(input_mp4, lang=lang_dir.name, overwrite=overwrite_srt, force_whisper=force_whisper)

    if srt_only:
        return

    # 2. TikTok
    tiktok_out = lang_dir / "tiktok" / f"{base}_tiktok.mp4"
    make_tiktok(input_mp4, srt, tiktok_out, overwrite=overwrite_tiktok)

    # 3. YouTube
    youtube_out = lang_dir / "youtube" / f"{base}_youtube.mp4"
    make_youtube(input_mp4, srt, youtube_out, overwrite=overwrite_youtube)


def traiter_projet(projet: Path, srt_only: bool = False, overwrite_srt: bool = False, force_whisper: bool = False, overwrite_youtube: bool = False, overwrite_tiktok: bool = False, lang_filter: str | None = None):
    print(f"\n{'='*55}")
    print(f"  Projet : {projet.name}")
    print(f"{'='*55}")

    langues_dossiers = [
        d for d in sorted(projet.iterdir())
        if d.is_dir() and d.name in LANGUES_CONNUES
    ]

    if lang_filter:
        langues_dossiers = [d for d in langues_dossiers if d.name == lang_filter]

    if not langues_dossiers:
        candidats = [d.name for d in projet.iterdir() if d.is_dir()]
        print("  Aucun dossier de langue reconnu.")
        print(f"  Dossiers présents : {candidats}")
        return

    print(f"  Langues reconnues : {[d.name for d in langues_dossiers]}")
    for lang_dir in langues_dossiers:
        traiter_langue(lang_dir, srt_only=srt_only, overwrite_srt=overwrite_srt, force_whisper=force_whisper, overwrite_youtube=overwrite_youtube, overwrite_tiktok=overwrite_tiktok)

    generer_manifest(projet)


def main():
    if not VIDEOS_EN_COURS.exists():
        print(f"Dossier introuvable : {VIDEOS_EN_COURS}")
        sys.exit(1)

    # Options CLI: --srt-only, --overwrite-srt, --force-whisper, --overwrite-youtube, --overwrite-all, --lang <code> [projet]
    args = sys.argv[1:]
    srt_only = False
    overwrite_srt = False
    force_whisper = False
    overwrite_youtube = False
    overwrite_tiktok = False
    lang_filter = None
    reste = []
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--srt-only":
            srt_only = True
        elif a in ("--overwrite-srt", "--srt-force", "--force"):
            overwrite_srt = True
        elif a == "--force-whisper":
            force_whisper = True
            overwrite_srt = True
        elif a == "--overwrite-youtube":
            overwrite_youtube = True
        elif a == "--overwrite-tiktok":
            overwrite_tiktok = True
        elif a == "--overwrite-all":
            overwrite_youtube = True
            overwrite_tiktok = True
        elif a == "--lang" and i + 1 < len(args):
            lang_filter = args[i + 1].strip().lower()
            i += 1
        else:
            reste.append(a)
        i += 1
    filtre = reste[0].strip().lower() if reste else None

    projets = sorted(
        p for p in VIDEOS_EN_COURS.iterdir()
        if p.is_dir() and (filtre is None or filtre in p.name.lower())
    )

    if not projets:
        msg = f"Aucun projet" + (f" matching '{filtre}'" if filtre else "")
        print(msg)
        sys.exit(0)

    print(f"{len(projets)} projet(s) a traiter")
    ok_total = 0
    for projet in projets:
        traiter_projet(projet, srt_only=srt_only, overwrite_srt=overwrite_srt, force_whisper=force_whisper,
                       overwrite_youtube=overwrite_youtube, overwrite_tiktok=overwrite_tiktok,
                       lang_filter=lang_filter)
        ok_total += 1

    print(f"\n=== Post-traitement termine : {ok_total} projet(s) ===")
    print(f"Sorties dans : {VIDEOS_EN_COURS}")


if __name__ == "__main__":
    main()
