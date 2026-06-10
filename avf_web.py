# -*- coding: utf-8 -*-
"""
AVF -- Interface web locale.
Ouvre http://localhost:5000 dans le navigateur.

Usage :
    py avf_web.py
"""

import json
import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from werkzeug.utils import secure_filename
from flask import Flask, Response, jsonify, render_template_string, request, send_file, stream_with_context

AVF_DIR         = Path(__file__).parent
VIDEOS_EN_COURS = AVF_DIR / "videos_en_cours"
LANGUES_CONNUES = {"fr", "en", "de", "es", "it", "pt", "ar", "ja", "zh", "ko", "ru", "nl", "pl"}

try:
    from config import VIDEOS_FINALES
except ImportError:
    VIDEOS_FINALES = AVF_DIR / "videos_finales"
VIDEO_EXT       = {".mp4", ".mov", ".mkv", ".avi"}
EDITORIAL_EXT   = {".docx", ".doc", ".pdf", ".txt"}

app = Flask(__name__)
SERVER_PUBLIC_URL = "http://localhost:5000"

# SSE connection tracking for diagnostics
SSE_CONN_COUNT = 0
SSE_LOCK = threading.Lock()

# ---------------------------------------------------------------------------
# Helpers status (copie legere de avf_status.py)
# ---------------------------------------------------------------------------

def has_video(folder: Path) -> bool:
    return folder.exists() and any(f.suffix.lower() in VIDEO_EXT for f in folder.iterdir() if f.is_file())

def has_srt(folder: Path) -> bool:
    return folder.exists() and any(f.suffix == ".srt" for f in folder.iterdir() if f.is_file())

def editorial_ok(projet: Path, lang: str) -> bool:
    m = projet / "manifest.json"
    if not m.exists(): return False
    try:
        d = json.loads(m.read_text(encoding="utf-8"))
        return bool(d.get("languages", {}).get(lang, {}).get("editorial", {}).get("title"))
    except Exception:
        return False

def allowed_video_file(filename: str) -> bool:
    if not filename:
        return False
    return Path(filename).suffix.lower() in VIDEO_EXT


def save_upload(file, projet: Path, lang: str) -> tuple[bool, str]:
    if not file:
        return False, "Aucun fichier reçu"
    if not allowed_video_file(file.filename):
        return False, "Extension invalide : utilisez .mp4 .mov .mkv .avi"
    dest = projet / lang / "video"
    dest.mkdir(parents=True, exist_ok=True)
    name = secure_filename(file.filename)
    if not name:
        return False, "Nom de fichier invalide"
    target = dest / name
    file.save(str(target))
    return True, f"✓ Vidéo uploadée dans {target}"


def allowed_editorial_file(filename: str) -> bool:
    if not filename:
        return False
    return Path(filename).suffix.lower() in EDITORIAL_EXT


def save_editorial_upload(file, projet: Path, doc_type: str) -> tuple[bool, str]:
    """Sauvegarde un fichier éditorial (résumé, transcription, etc.)"""
    if not file:
        return False, "Aucun fichier reçu"
    if not allowed_editorial_file(file.filename):
        return False, "Extension invalide : utilisez .docx .doc .pdf .txt"
    dest = projet / "editorial"
    dest.mkdir(parents=True, exist_ok=True)
    name = secure_filename(file.filename)
    if not name:
        return False, "Nom de fichier invalide"
    target = dest / f"{doc_type}_{name}"
    file.save(str(target))
    return True, f"✓ Document uploadé : {target.name}"


def safe_path_under(root: Path, relative: str) -> Path | None:
    candidate = (root / relative).resolve()
    try:
        if root.resolve() in candidate.parents or root.resolve() == candidate:
            return candidate
    except Exception:
        pass
    return None


def first_video_file(folder: Path) -> Path | None:
    if not folder.exists():
        return None
    for ext in VIDEO_EXT:
        files = sorted(folder.glob(f"*{ext}"))
        if files:
            return files[0]
    return None


def first_srt_file(lang_dir: Path) -> Path | None:
    youtube_dir = lang_dir / "youtube"
    if youtube_dir.exists():
        files = sorted(youtube_dir.glob("*.srt"))
        if files:
            return files[0]
    # fallback to video folder SRT
    video_dir = lang_dir / "video"
    if video_dir.exists():
        files = sorted(video_dir.glob("*.srt"))
        if files:
            return files[0]
    return None


def get_preview_info(projet: Path, lang: str, step: str) -> dict:
    lang_dir = projet / lang
    if not lang_dir.exists():
        return {"type": "none", "message": "Langue introuvable"}

    if step == "source":
        video = first_video_file(lang_dir / "video")
        if video:
            return {"type": "video", "title": "Source", "file": str(video.relative_to(VIDEOS_EN_COURS)).replace('\\', '/'), "message": video.name}
        return {"type": "none", "message": "Aucune vidéo source trouvée"}

    if step in {"tiktok", "youtube"}:
        video = first_video_file(lang_dir / step)
        if video:
            return {"type": "video", "title": step.capitalize(), "file": str(video.relative_to(VIDEOS_EN_COURS)).replace('\\', '/'), "message": video.name}
        return {"type": "none", "message": f"Aucune vidéo {step} trouvée"}

    if step == "srt":
        srt = first_srt_file(lang_dir)
        if srt:
            return {"type": "text", "title": "SRT", "file": str(srt.relative_to(VIDEOS_EN_COURS)).replace('\\', '/'), "message": srt.name}
        return {"type": "none", "message": "Aucun SRT trouvé"}

    if step == "editorial":
        editorial_dir = projet / "editorial"
        files = []
        if editorial_dir.exists():
            for f in sorted(editorial_dir.iterdir()):
                if f.is_file():
                    files.append({"name": f.name, "path": str(f.relative_to(VIDEOS_EN_COURS)).replace('\\', '/'), "suffix": f.suffix.lower()})
        manifest = None
        manifest_path = projet / "manifest.json"
        if manifest_path.exists():
            try:
                data = json.loads(manifest_path.read_text(encoding="utf-8"))
                manifest = data.get("languages", {}).get(lang, {}).get("editorial")
            except Exception:
                manifest = None
        return {"type": "editorial", "title": "Éditorial", "files": files, "manifest": manifest, "message": "Voir le contenu éditorial"}

    return {"type": "none", "message": "Action inconnue"}


def get_projects():
    if not VIDEOS_EN_COURS.exists():
        return []
    projets = []
    for p in sorted(VIDEOS_EN_COURS.iterdir()):
        if not p.is_dir():
            continue

        # Always include FR as the primary language column (treated like other languages)
        langues = ['fr']
        # add other known languages (exclude 'fr' to avoid duplicates)
        autres = sorted(d.name for d in p.iterdir() if d.is_dir() and d.name in LANGUES_CONNUES and d.name != 'fr')
        langues.extend(autres)

        langs_status = {}
        dest_langs_status = {}
        dest_project = VIDEOS_FINALES / p.name
        for lg in langues:
            langs_status[lg] = {
                "source":    has_video(p / lg / "video"),
                "tiktok":    has_video(p / lg / "tiktok"),
                "youtube":   has_video(p / lg / "youtube"),
                "srt":       has_srt(p / lg / "youtube") or has_srt(p / lg / "video"),
                "editorial": editorial_ok(p, lg),
            }
            dest_langs_status[lg] = {
                "source":    has_video(dest_project / lg / "video"),
                "tiktok":    has_video(dest_project / lg / "tiktok"),
                "youtube":   has_video(dest_project / lg / "youtube"),
                "srt":       has_srt(dest_project / lg / "youtube") or has_srt(dest_project / lg / "video"),
                "editorial": editorial_ok(dest_project, lg),
            }

        # detect presence of editorial files uploaded via UI (prefix doc_type_)
        editorial_dir = p / 'editorial'
        editorial_files = {
            'youtube_summary': False,
            'tiktok_summary': False,
            'transcript': False,
        }
        if editorial_dir.exists():
            for dt in editorial_files.keys():
                if any(editorial_dir.glob(f"{dt}_*")):
                    editorial_files[dt] = True

        projets.append({
            "name":              p.name,
            "fr":                has_video(p / "fr" / "video"),
            "manifest":          (p / "manifest.json").exists(),
            "synced":            (p / "copie_serveur.done").exists(),
            "langues":           langues,
            "langs_status":      langs_status,
            "dest_langs_status": dest_langs_status,
            "editorial_files":   editorial_files,
        })
    return projets

# ---------------------------------------------------------------------------
# Streaming subprocess
# ---------------------------------------------------------------------------

def stream_cmd(args: list):
    """Execute une commande et streame la sortie en SSE."""
    def generate():
        global SSE_CONN_COUNT
        # register connection
        with SSE_LOCK:
            SSE_CONN_COUNT += 1
            print(f"+++ SSE connection opened (count={SSE_CONN_COUNT})")
        try:
            print(f"+++ Running command: {' '.join(args)}")
            proc = subprocess.Popen(
                args, cwd=str(AVF_DIR),
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace",
                bufsize=1,
                env={**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
            )
            for line in proc.stdout:
                text = line.rstrip()
                print(text)
                yield f"data: {text}\n\n"
            proc.wait()
            code = proc.returncode
            print(f"+++ Command finished (code={code}): {' '.join(args)}")
            yield f"data: \n\n"
            yield f"data: --- Termine (code {code}) ---\n\n"
            yield "event: done\ndata: ok\n\n"
        finally:
            with SSE_LOCK:
                SSE_CONN_COUNT -= 1
                print(f"--- SSE connection closed (count={SSE_CONN_COUNT})")
    return Response(stream_with_context(generate()), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------

PAGE = r"""<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AVF — Les Fermes de la Vie</title>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
<style>
  body { background:#f8f9fa; }
  .brand { background:#2d6a4f; color:#fff; padding:1rem 1.5rem; }
  .brand h1 { margin:0; font-size:1.4rem; letter-spacing:.05em; }
  .brand small { opacity:.7; font-size:.85rem; }
  .card-projet { border-left:4px solid #2d6a4f; }
  .badge-lang { font-size:.75rem; margin-right:3px; }
  .console-box { background:#1e1e1e; color:#d4d4d4; font-family:monospace;
                 font-size:.8rem; height:320px; overflow-y:auto; padding:1rem;
                 border-radius:.5rem; white-space:pre-wrap; }
  .console-box .ok  { color:#4ec9b0; }
  .console-box .err { color:#f48771; }
  .step-icon { font-size:1.1rem; }
  .btn-action { font-size:.82rem; padding:.25rem .7rem; }
  .preview-cell { cursor:pointer; }
  .preview-cell:hover { background: rgba(45,106,79,.08); }
  .preview-modal { display:none; position:fixed; inset:0; background:rgba(0,0,0,.65); z-index:2000; align-items:center; justify-content:center; padding:1rem; }
  .preview-modal.show { display:flex; }
  .preview-modal .modal-card { background:#fff; border-radius:.75rem; max-width:960px; width:100%; max-height:90vh; overflow:hidden; box-shadow:0 0 30px rgba(0,0,0,.25); }
  .preview-modal .modal-body { padding:1rem; overflow:auto; max-height:70vh; }
  .preview-modal .modal-header { padding:1rem; border-bottom:1px solid #e9ecef; display:flex; align-items:center; justify-content:space-between; gap:1rem; }
  .preview-modal .modal-footer { padding:1rem; border-top:1px solid #e9ecef; text-align:right; }
  .preview-modal pre { background:#f8f9fa; padding:1rem; border-radius:.5rem; white-space:pre-wrap; word-break:break-word; font-size:.9rem; }
  .preview-modal video { max-width:100%; max-height:60vh; display:block; margin:0 auto; border-radius:.5rem; }
  .preview-modal .btn-close { border:none; background:transparent; font-size:1.2rem; cursor:pointer; }
  .start-modal { display:none; position:fixed; inset:0; background:rgba(0,0,0,.55); z-index:2100; align-items:center; justify-content:center; padding:1rem; }
  .start-modal.show { display:flex; }
  .start-modal .modal-card { background:#fff; border-radius:.75rem; max-width:560px; width:100%; box-shadow:0 0 30px rgba(0,0,0,.25); }
  .start-modal .modal-header { padding:1rem; border-bottom:1px solid #e9ecef; display:flex; align-items:center; justify-content:space-between; gap:1rem; }
  .start-modal .modal-body { padding:1rem; }
  .start-modal .modal-footer { padding:1rem; border-top:1px solid #e9ecef; display:flex; gap:.5rem; justify-content:flex-end; }
  .help-modal { display:none; position:fixed; inset:0; background:rgba(0,0,0,.6); z-index:3000; align-items:flex-start; justify-content:center; padding:2rem 1rem; overflow-y:auto; }
  .help-modal.show { display:flex; }
  .help-modal .modal-card { background:#fff; border-radius:.75rem; max-width:780px; width:100%; box-shadow:0 0 40px rgba(0,0,0,.3); }
  .help-modal .modal-header { background:#2d6a4f; color:#fff; padding:1rem 1.5rem; border-radius:.75rem .75rem 0 0; display:flex; align-items:center; justify-content:space-between; }
  .help-modal .modal-header h5 { margin:0; font-size:1.15rem; }
  .help-modal .modal-header button { background:transparent; border:none; color:#fff; font-size:1.4rem; line-height:1; cursor:pointer; }
  .help-modal .modal-body { padding:1.5rem; }
  .help-modal .modal-footer { padding:1rem 1.5rem; border-top:1px solid #e9ecef; text-align:right; }
  .help-step { display:flex; gap:1rem; align-items:flex-start; margin-bottom:1.2rem; }
  .help-step .step-num { background:#2d6a4f; color:#fff; border-radius:50%; width:2rem; height:2rem; min-width:2rem; display:flex; align-items:center; justify-content:center; font-weight:bold; font-size:.95rem; }
  .help-step .step-body { flex:1; }
  .help-step .step-body strong { display:block; margin-bottom:.2rem; }
  .help-cmd { background:#1e1e1e; color:#4ec9b0; font-family:monospace; font-size:.85rem; padding:.4rem .75rem; border-radius:.4rem; display:inline-block; margin:.25rem 0; word-break:break-all; }
  .help-section-title { font-weight:700; color:#2d6a4f; border-bottom:2px solid #2d6a4f; padding-bottom:.3rem; margin:1.5rem 0 1rem; }
  .restart-overlay { display:none; position:fixed; inset:0; background:rgba(0,0,0,.82); z-index:9999; align-items:center; justify-content:center; flex-direction:column; color:#fff; font-family:monospace; }
  .restart-overlay.show { display:flex; }
  .restart-overlay h2 { font-size:1.4rem; margin-bottom:1rem; }
  .restart-overlay .countdown { font-size:3rem; font-weight:bold; color:#4ec9b0; }
  .restart-overlay .msg { margin-top:1rem; font-size:.9rem; opacity:.7; }
</style>
</head>
<body>

<div class="brand mb-4" style="display:flex; align-items:center; justify-content:space-between;">
  <div>
    <h1>&#127807; AVF — Les Fermes de la Vie</h1>
    <small>Pipeline vidéo automatisé</small>
  </div>
  <div class="d-flex gap-2">
    <button class="btn btn-danger btn-sm fw-bold" onclick="restarterServeur()" title="Libère le port 5000 et relance le serveur">🔄 Réinitialiser</button>
    <button class="btn btn-light btn-sm fw-bold" onclick="openHelp()">❓ Aide</button>
  </div>
</div>

<div class="alert alert-secondary py-3 mb-4">
  <div class="d-flex flex-wrap gap-2 align-items-center">
    <button class="btn btn-warning btn-sm" onclick="lancerFluxPost()">⚙ Flux post-traitement local</button>
    <button class="btn btn-info btn-sm" onclick="ouvrirFluxWebLocale()">🌐 Flux interface web locale</button>
    <button class="btn btn-success btn-sm" onclick="lancerFlux('srt')">📝 Générer SRT</button>
    <button class="btn btn-danger btn-sm" onclick="lancerFlux('srt_force')">🛠️ Écraser SRT</button>
    <div class="form-check form-switch ms-3 mb-0 d-flex align-items-center gap-2">
      <input class="form-check-input" type="checkbox" id="cbOverwrite" role="switch">
      <label class="form-check-label small fw-semibold text-danger" for="cbOverwrite">⚠️ Écraser les vidéos existantes</label>
    </div>
  </div>
  <div class="small text-muted mt-2">
    Ces boutons représentent les deux flux locaux : traitement vidéo post-HeyGen, et gestion éditoriale via cette interface.
  </div>
</div>

<div class="container-fluid px-4">
<div class="row g-4">

<!-- Colonne projets -->
<div class="col-lg-7">

  <div class="d-flex justify-content-between align-items-center mb-3">
    <div>
      <h5 class="mb-0">Projets en cours</h5>
      <div class="small text-muted">Sélectionne un projet pour afficher sa fiche</div>
    </div>
    <button class="btn btn-success btn-sm" onclick="showNew()">+ Nouveau projet</button>
  </div>

  <div class="row gx-2 mb-3 align-items-center">
    <div class="col-lg-6 col-md-8 col-sm-12">
      <select id="projectSelect" class="form-select form-select-sm" onchange="selectProject()">
        {% for p in projets %}
          <option value="{{ p.name }}">{{ p.name }}</option>
        {% endfor %}
      </select>
    </div>
    <div class="col-lg-6 col-md-4 col-sm-12 text-end">
      <div class="small text-muted">Projet actif: <span id="activeProjectLabel">{{ projets[0].name if projets else '' }}</span></div>
    </div>
  </div>

  <!-- Formulaire nouveau projet -->
  <div id="formNew" class="card mb-3 d-none">
    <div class="card-body">
      <label class="form-label fw-semibold">Nom du projet</label>
      <div class="input-group">
        <input type="text" id="newName" class="form-control" placeholder="ex: 7 printemps">
        <button class="btn btn-success" onclick="creerProjet()">Créer</button>
        <button class="btn btn-outline-secondary" onclick="hideNew()">Annuler</button>
      </div>
      <div class="form-text">Un dossier sera créé — place ensuite la vidéo FR à l'intérieur.</div>
    </div>
  </div>

  <div id="listeProjets">
    {% for p in projets %}
    <div class="card card-projet mb-3 shadow-sm project-card" data-project="{{ p.name }}" style="display:none;">
      <div class="card-body pb-2">
        <div class="d-flex justify-content-between align-items-start">
          <div>
            <h6 class="mb-1 fw-bold">{{ p.name }}</h6>
            <div class="mb-2">
              <span class="me-2" title="Vidéo FR">{{ '✅' if p.fr else '⬜' }} FR</span>
              <span class="me-2" title="manifest.json">{{ '✅' if p.manifest else '⬜' }} manifest</span>
              <span title="Synchronisé Linux">{{ '✅' if p.synced else '⬜' }} sync</span>
            </div>
          </div>
          <div class="text-end">
            {% for lg in p.langues %}
              {% set s = p.langs_status[lg] %}
              {% set all_ok = s.source and s.tiktok and s.youtube %}
              <span class="badge {{ 'bg-success' if all_ok else 'bg-secondary' }} badge-lang">{{ lg.upper() }}</span>
            {% endfor %}
          </div>
        </div>

        <!-- Détail par langue -->
        {% if p.langues %}
        <div class="small text-muted mb-1">✅ synchronisé &nbsp;·&nbsp; 🔄 à synchroniser &nbsp;·&nbsp; ☐ absent</div>
        <div class="table-responsive mb-2">
        <table class="table table-sm table-borderless mb-0" style="font-size:.8rem">
          <thead><tr>
            <th></th>
            {% for lg in p.langues %}<th class="text-center">{{ lg.upper() }}</th>{% endfor %}
          </tr></thead>
          <tbody>
            {% for step, label in [('source','Source'),('tiktok','TikTok'),('youtube','YouTube'),('srt','SRT'),('editorial','Éditorial')] %}
            <tr>
              <td class="text-muted">
                {% if step == 'srt' %}
                  <div class="d-inline-flex gap-1">
                    <button type="button" class="btn btn-success btn-sm" onclick="event.stopPropagation(); lancer('srt', '{{ p.name }}')" title="Générer les SRT pour toutes les langues">Générer SRT</button>
                    <button type="button" class="btn btn-outline-danger btn-sm" onclick="event.stopPropagation(); lancer('srt_force', '{{ p.name }}')" title="Écraser les SRT existants">Écraser</button>
                  </div>
                {% elif step == 'youtube' %}
                  <div class="d-inline-flex gap-1 align-items-center">
                    <span>YouTube</span>
                    <button type="button" class="btn btn-outline-warning btn-sm py-0 px-1" style="font-size:.72rem"
                            onclick="event.stopPropagation(); lancer('youtube_fix', '{{ p.name }}')"
                            title="Régénérer toutes les vidéos YouTube en 16/9">&#x21bb; Tout</button>
                  </div>
                {% else %}
                  {{ label }}
                {% endif %}
              </td>
              {% for lg in p.langues %}
                <td class="text-center preview-cell" data-project="{{ p.name }}" data-lang="{{ lg }}" data-step="{{ step }}"
                    onclick="showPreview(this)" title="Cliquer pour prévisualiser">
                  {% if p.dest_langs_status[lg][step] %}✅{% elif p.langs_status[lg][step] %}🔄{% else %}☐{% endif %}
                </td>
              {% endfor %}
            </tr>
            {% endfor %}
          </tbody>
        </table>
        </div>
        {% endif %}

        <!-- Boutons actions -->
        {% if not p.fr %}
        <div class="alert alert-warning py-2">
          <div class="d-flex align-items-center justify-content-between mb-2">
            <div>
              <strong>Vidéo FR source manquante</strong>
              <div class="small">Charge la vidéo FR de départ pour démarrer le flux.</div>
            </div>
            <span class="badge bg-warning text-dark">Étape 1</span>
          </div>
          <div class="input-group input-group-sm">
            <input type="file" class="form-control" id="file_fr_{{ loop.index }}" accept=".mp4,.mov,.mkv,.avi">
            <button class="btn btn-primary" onclick="uploadFile('{{ p.name }}', 'fr', {{ loop.index }})">Uploader</button>
          </div>
        </div>
        {% endif %}

        <div class="alert alert-secondary py-2">
          <div class="d-flex align-items-center justify-content-between mb-2">
            <div>
              <strong>Uploader une traduction</strong>
              <div class="small">Charge une vidéo traduite déjà disponible pour une langue.</div>
            </div>
            <span class="badge bg-secondary text-dark">Étape 2</span>
          </div>
          <div class="row gx-2 gy-2 align-items-center">
            <div class="col-auto">
              <select class="form-select form-select-sm" id="upload_lang_{{ loop.index }}">
                <option value="en">EN</option>
                <option value="de">DE</option>
                <option value="es">ES</option>
                <option value="it">IT</option>
                <option value="pt">PT</option>
                <option value="ar">AR</option>
                <option value="ja">JA</option>
                <option value="zh">ZH</option>
                <option value="ko">KO</option>
                <option value="ru">RU</option>
                <option value="nl">NL</option>
                <option value="pl">PL</option>
              </select>
            </div>
            <div class="col">
              <input type="file" class="form-control form-control-sm" id="file_lang_{{ loop.index }}" accept=".mp4,.mov,.mkv,.avi">
            </div>
            <div class="col-auto">
              <button class="btn btn-primary btn-sm" onclick="uploadTranslation('{{ p.name }}', {{ loop.index }})">Uploader</button>
            </div>
          </div>
        </div>

        <div class="alert alert-info py-2">
          <div class="d-flex align-items-center justify-content-between mb-2">
            <div>
              <strong>Documents éditoriaux</strong>
              <div class="small">Charge les résumés et transcription (Word, PDF, texte).</div>
            </div>
            <span class="badge bg-info text-dark">Étape 3</span>
          </div>
          <div class="row gx-2 gy-2">
            <div class="col-md-4 col-sm-6">
              <label class="form-label small mb-1">Résumé YouTube
                {% if p.editorial_files.youtube_summary %}
                  <span class="badge bg-success ms-2">Présent</span>
                {% else %}
                  <span class="badge bg-secondary ms-2">Absent</span>
                {% endif %}
              </label>
              <input type="file" class="form-control form-control-sm" id="file_youtube_{{ loop.index }}" accept=".docx,.doc,.pdf,.txt">
              <button class="btn btn-info btn-sm mt-1 w-100" onclick="uploadEditorial('{{ p.name }}', 'youtube_summary', {{ loop.index }})">📄</button>
            </div>
            <div class="col-md-4 col-sm-6">
              <label class="form-label small mb-1">Résumé TikTok
                {% if p.editorial_files.tiktok_summary %}
                  <span class="badge bg-success ms-2">Présent</span>
                {% else %}
                  <span class="badge bg-secondary ms-2">Absent</span>
                {% endif %}
              </label>
              <input type="file" class="form-control form-control-sm" id="file_tiktok_{{ loop.index }}" accept=".docx,.doc,.pdf,.txt">
              <button class="btn btn-info btn-sm mt-1 w-100" onclick="uploadEditorial('{{ p.name }}', 'tiktok_summary', {{ loop.index }})">📄</button>
            </div>
            <div class="col-md-4 col-sm-6">
              <label class="form-label small mb-1">Transcription
                {% if p.editorial_files.transcript %}
                  <span class="badge bg-success ms-2">Présent</span>
                {% else %}
                  <span class="badge bg-secondary ms-2">Absent</span>
                {% endif %}
              </label>
              <input type="file" class="form-control form-control-sm" id="file_transcript_{{ loop.index }}" accept=".docx,.doc,.pdf,.txt">
              <button class="btn btn-info btn-sm mt-1 w-100" onclick="uploadEditorial('{{ p.name }}', 'transcript', {{ loop.index }})">📄</button>
            </div>
          </div>
        </div>

        <div class="d-flex flex-wrap gap-1 mt-1">
          <button class="btn btn-outline-primary btn-action"
                  onclick="lancer('download', '{{ p.name }}')">⬇ HeyGen</button>
          <button class="btn btn-outline-warning btn-action"
                  onclick="lancerPost('{{ p.name }}')">⚙ Post-traiter</button>
          <button class="btn btn-outline-secondary btn-action"
                  onclick="lancer('check', '{{ p.name }}')">📋 Vérifier</button>
          <button class="btn btn-outline-info btn-action"
                  onclick="lancer('sync', '{{ p.name }}')">↑ Sync manquants</button>
          <button class="btn btn-outline-danger btn-action"
                  onclick="lancer('youtube_fix', '{{ p.name }}')" title="Recadre les vidéos YouTube (zoom 16:9) — écrase les fichiers existants">🎬 Recadrer YouTube</button>
          <button class="btn btn-success btn-action"
                  onclick="lancer('run', '{{ p.name }}')">▶ Pipeline complet</button>
          <button class="btn btn-outline-danger btn-action" title="Supprimer le projet"
                  onclick="supprimerProjet('{{ p.name }}')">🗑️ Supprimer</button>
        </div>
      </div>
    </div>
    {% else %}
    <div class="text-muted text-center py-4">Aucun projet. Crée-en un !</div>
    {% endfor %}
  </div>
</div>

<!-- Colonne console -->
<div class="col-lg-5">
  <div class="d-flex justify-content-between align-items-center mb-3">
    <h5 class="mb-0">Console</h5>
    <div>
      <span id="sseCount" class="badge bg-secondary me-2" style="font-size:.8rem">SSE:0</span>
      <span id="consoleTitle" class="text-muted me-2" style="font-size:.85rem"></span>
      <button class="btn btn-outline-secondary btn-sm me-1" onclick="clearConsole()">Effacer</button>
      <button id="stopBtn" class="btn btn-outline-danger btn-sm" onclick="stopSSE()">⏹️ Stop</button>
    </div>
  </div>
  <div id="progressArea" class="mb-3 d-none">
    <div class="d-flex align-items-center gap-2 mb-2">
      <div class="spinner-border spinner-border-sm text-warning" role="status"></div>
      <div id="progressLabel" class="small text-muted">Travail en cours...</div>
    </div>
    <div class="progress" style="height:0.8rem;">
      <div id="progressBar" class="progress-bar progress-bar-striped progress-bar-animated bg-warning" role="progressbar" style="width: 0%;" aria-valuenow="0" aria-valuemin="0" aria-valuemax="100"></div>
    </div>
  </div>
  <div id="console" class="console-box">En attente...</div>
</div>

</div>
</div>

<div id="previewModal" class="preview-modal" onclick="closePreview(event)">
  <div class="modal-card" onclick="event.stopPropagation()">
    <div class="modal-header">
      <div>
        <h5 id="previewTitle" class="mb-1">Aperçu</h5>
        <div id="previewSubtitle" class="text-muted small"></div>
      </div>
      <button class="btn-close" aria-label="Fermer" onclick="closePreview(event)">&times;</button>
    </div>
    <div class="modal-body" id="previewBody">
      <p class="text-muted">Chargement...</p>
    </div>
    <div class="modal-footer">
      <a id="previewDownload" class="btn btn-sm btn-outline-primary d-none" target="_blank" rel="noopener">Télécharger</a>
      <button id="previewRegen" class="btn btn-sm btn-outline-warning d-none" onclick="regenFichier()">&#x21bb; Régénérer</button>
      <button id="previewTransfer" class="btn btn-sm btn-success d-none" onclick="transferFichier()">📤 Transférer vers destination</button>
      <div id="previewTransferMsg" class="small ms-2"></div>
    </div>
  </div>
</div>

<!-- ===== OVERLAY REDEMARRAGE ===== -->
<div id="restartOverlay" class="restart-overlay">
  <h2>🔄 Redémarrage du serveur…</h2>
  <div class="countdown" id="restartCountdown">5</div>
  <div class="msg">Le serveur redémarre, la page se rechargera automatiquement.</div>
</div>

<!-- ===== MODALE AIDE ===== -->
<div id="helpModal" class="help-modal" onclick="closeHelp(event)">
  <div class="modal-card" onclick="event.stopPropagation()">
    <div class="modal-header">
      <h5>❓ Guide d'utilisation — AVF</h5>
      <button onclick="closeHelp(event)">&times;</button>
    </div>
    <div class="modal-body">

      <!-- LANCER LE SERVEUR -->
      <div class="help-section-title">🖥️ Démarrer le serveur</div>
      <p class="small text-muted mb-2">Ouvre un terminal PowerShell dans le dossier du projet, puis lance :</p>
      <div class="help-cmd">cd F:\Les_jardins_de_la_vie_4\ia\avf</div><br>
      <div class="help-cmd">py avf_web.py</div>
      <p class="small text-muted mt-2">Le serveur démarre sur <strong>http://localhost:5000</strong>.<br>
      Laisse le terminal ouvert tant que tu travailles.</p>

      <!-- OUVRIR DANS LE NAVIGATEUR -->
      <div class="help-section-title">🌐 Ouvrir dans le navigateur</div>
      <p class="small text-muted">Une fois le serveur lancé, ouvre ton navigateur et va à :</p>
      <div class="help-cmd">http://localhost:5000</div>
      <p class="small text-muted mt-2">Tu peux aussi appuyer sur <kbd>Ctrl+Clic</kbd> sur le lien affiché dans le terminal.</p>

      <!-- LIBERER LE PORT -->
      <div class="help-section-title">🔧 Port 5000 déjà occupé ? (Windows)</div>
      <p class="small text-muted mb-2">Si tu vois <em>"Address already in use"</em>, trouve et tue le processus qui occupe le port :</p>
      <div class="help-cmd">netstat -ano | findstr :5000</div>
      <p class="small text-muted mt-1 mb-1">Repère le PID (dernière colonne), puis :</p>
      <div class="help-cmd">taskkill /PID &lt;le_numero_pid&gt; /F</div>
      <p class="small text-muted mt-1">Exemple : <code>taskkill /PID 12345 /F</code><br>
      Puis relance <code>py avf_web.py</code>.</p>

      <!-- FLUX NORMAL -->
      <div class="help-section-title">🔄 Flux normal — étape par étape</div>

      <div class="help-step">
        <div class="step-num">1</div>
        <div class="step-body">
          <strong>Créer un nouveau projet</strong>
          Clique sur <em>+ Nouveau projet</em>, saisis un nom (ex: <code>7 printemps</code>). Un dossier est créé automatiquement.
        </div>
      </div>

      <div class="help-step">
        <div class="step-num">2</div>
        <div class="step-body">
          <strong>Uploader la vidéo source FR</strong>
          Dans la fiche du projet, utilise l'encart <em>Vidéo FR source manquante</em> pour charger ta vidéo de départ (MP4, MOV, MKV).
          L'icône 🔄 FR s'allume quand elle est bien présente (elle passera ✅ après synchronisation).<br><br>
          Ensuite, <strong>connecte-toi à HeyGen</strong> et lance la traduction de ta vidéo dans les langues souhaitées. HeyGen va générer les versions traduites que l'on téléchargera à l'étape suivante.
        </div>
      </div>

      <div class="help-step">
        <div class="step-num">3</div>
        <div class="step-body">
          <strong>Lancer le Pipeline complet</strong>
          Clique sur <em>▶ Pipeline complet</em>. Cela lance HeyGen pour télécharger les traductions, puis le post-traitement (recadrage TikTok / YouTube, génération des SRT).
          Suis la progression dans la <em>Console</em> à droite.
        </div>
      </div>

      <div class="help-step">
        <div class="step-num">4</div>
        <div class="step-body">
          <strong>Uploader les documents éditoriaux</strong>
          Dans l'encart <em>Documents éditoriaux</em> (Étape 3), charge le résumé YouTube, le résumé TikTok et la transcription (Word, PDF ou texte).
          Ces fichiers servent à l'outil de publication automatique.
        </div>
      </div>

      <div class="help-step">
        <div class="step-num">5</div>
        <div class="step-body">
          <strong>Synchroniser vers la destination</strong>
          Clique sur <em>↑ Sync manquants</em> pour copier tous les livrables vers <code>videos_finales/</code> (archive locale) et vers le serveur Linux.<br>
          Les icônes 🔄 (bleu = présent en source seulement) passent en ✅ (vert = copié en destination).<br>
          L'icône <em>sync</em> en haut de la fiche passe aussi au ✅ quand tout est transféré sans erreur.
        </div>
      </div>

      <div class="help-step">
        <div class="step-num">6</div>
        <div class="step-body">
          <strong>Prévisualiser / transférer un fichier individuel</strong>
          Clique sur n'importe quelle icône dans le tableau des langues pour ouvrir l'aperçu. Un bouton <em>📤 Transférer vers destination</em> permet de copier ce seul fichier sans tout re-synchroniser.
        </div>
      </div>

      <!-- LÉGENDE DES ICÔNES -->
      <div class="help-section-title">🔑 Légende des icônes</div>
      <table class="table table-sm table-bordered" style="font-size:.85rem">
        <tbody>
          <tr><td style="width:3rem" class="text-center">✅</td><td>Fichier présent <strong>et synchronisé</strong> vers la destination</td></tr>
          <tr><td class="text-center">🔄</td><td>Fichier présent en source, <strong>pas encore copié</strong> en destination → utilise <em>↑ Sync manquants</em></td></tr>
          <tr><td class="text-center">☐</td><td>Fichier <strong>absent</strong> (pas encore généré)</td></tr>
          <tr><td class="text-center">✅ sync</td><td>Le fichier marqueur <code>copie_serveur.done</code> existe → tout a été copié sans erreur</td></tr>
        </tbody>
      </table>

    </div>
    <div class="modal-footer">
      <button class="btn btn-success" onclick="closeHelp(event)">Fermer</button>
    </div>
  </div>
</div>

<div id="startModal" class="start-modal" onclick="closeStartModal(event)">
  <div class="modal-card" onclick="event.stopPropagation()">
    <div class="modal-header">
      <div>
        <h5 class="mb-1">Lancement depuis l'interface</h5>
        <div class="text-muted small" id="startModalProjectLabel"></div>
      </div>
      <button class="btn-close" aria-label="Fermer" onclick="closeStartModal(event)">&times;</button>
    </div>
    <div class="modal-body">
      <p class="mb-2">Choisissez l'action à lancer depuis l'interface locale.</p>
      <div class="small text-muted">Le bouton serveur vérifie que l'interface locale est active. Le bouton programme démarre le pipeline complet pour le projet sélectionné.</div>
    </div>
    <div class="modal-footer">
      <button class="btn btn-outline-secondary" onclick="closeStartModal(event)">Fermer</button>
      <button class="btn btn-outline-primary" onclick="demarrerServeurDepuisModal()">Démarrer serveur</button>
      <button class="btn btn-success" onclick="demarrerProgrammeDepuisModal()">Démarrer le programme</button>
    </div>
  </div>
</div>

<script>
let es = null;
let ssePollIntervalId = null;

function clearConsole() {
  document.getElementById('console').innerHTML = '';
}

function log(txt) {
  const box = document.getElementById('console');
  const line = document.createElement('div');
  if (txt.includes('Erreur') || txt.includes('ERREUR') || txt.includes('!')) {
    line.className = 'err';
  } else if (txt.includes('✓') || txt.includes('termine') || txt.includes('OK') || txt.includes('genere')) {
    line.className = 'ok';
  }
  line.textContent = txt;
  box.appendChild(line);
  box.scrollTop = box.scrollHeight;
}

function showProgress(label) {
  const area = document.getElementById('progressArea');
  const bar = document.getElementById('progressBar');
  const labelEl = document.getElementById('progressLabel');
  if (!area || !bar || !labelEl) return;
  area.classList.remove('d-none');
  labelEl.textContent = label || 'Travail en cours...';
  bar.style.width = '5%';
  bar.setAttribute('aria-valuenow', '5');
  bar.classList.add('progress-bar-animated', 'progress-bar-striped');
}

function updateProgress() {
  const bar = document.getElementById('progressBar');
  if (!bar) return;
  let current = Number(bar.getAttribute('aria-valuenow') || 0);
  if (current >= 95) return;
  current += 10;
  bar.style.width = `${current}%`;
  bar.setAttribute('aria-valuenow', `${current}`);
}

let _previewCtx = null;  // { projet, lang, step }

function showPreview(cell) {
  const projet = cell.dataset.project;
  const lang = cell.dataset.lang;
  const step = cell.dataset.step;
  if (!projet || !lang || !step) {
    return;
  }
  _previewCtx = { projet, lang, step };
  const title = `Aperçu — ${step.toUpperCase()} (${lang.toUpperCase()})`;
  const body = document.getElementById('previewBody');
  const subtitle = document.getElementById('previewSubtitle');
  const download = document.getElementById('previewDownload');
  const transfer = document.getElementById('previewTransfer');
  const transferMsg = document.getElementById('previewTransferMsg');
  const regen = document.getElementById('previewRegen');
  document.getElementById('previewTitle').textContent = title;
  subtitle.textContent = `Projet ${projet}`;
  body.innerHTML = '<p class="text-muted">Chargement...</p>';
  download.classList.add('d-none');
  transfer.classList.add('d-none');
  regen.classList.add('d-none');
  transferMsg.textContent = '';
  document.getElementById('previewModal').classList.add('show');

  fetch(`/preview/${encodeURIComponent(projet)}/${encodeURIComponent(lang)}/${encodeURIComponent(step)}`)
    .then(r => r.json())
    .then(data => {
      if (!data || data.type === 'none') {
        body.innerHTML = `<p>${data.message || 'Aucune prévisualisation disponible.'}</p>`;
        return;
      }
      if (data.type === 'video') {
        body.innerHTML = `
          <p class="small text-muted mb-2">${data.message}</p>
          <video controls src="/files/${encodeURIComponent(data.file)}"></video>
        `;
        download.href = `/files/${encodeURIComponent(data.file)}`;
        download.textContent = 'Télécharger la vidéo';
        download.classList.remove('d-none');
        transfer.classList.remove('d-none');
        if (['source','tiktok','youtube'].includes(step)) regen.classList.remove('d-none');
        return;
      }
      if (data.type === 'text') {
        fetch(`/files/${encodeURIComponent(data.file)}`)
          .then(r => r.text())
          .then(txt => {
            body.innerHTML = `<p class="small text-muted mb-2">${data.message}</p><pre>${escapeHtml(txt)}</pre>`;
            download.href = `/files/${encodeURIComponent(data.file)}`;
            download.textContent = 'Télécharger le SRT';
            download.classList.remove('d-none');
            transfer.classList.remove('d-none');
          })
          .catch(() => {
            body.innerHTML = `<p>${data.message}</p>`;
          });
        return;
      }
      if (data.type === 'editorial') {
        const files = data.files || [];
        const manifest = data.manifest;
        let html = `<p class="small text-muted mb-2">${data.message}</p>`;
        if (files.length) {
          html += '<div class="mb-3"><strong>Fichiers éditoriaux</strong><ul>' +
                  files.map(f => `<li><a href="/files/${encodeURIComponent(f.path)}" target="_blank">${escapeHtml(f.name)}</a> (${escapeHtml(f.suffix)})</li>`).join('') +
                  '</ul></div>';
        } else {
          html += '<p>Aucun fichier éditorial trouvé.</p>';
        }
        if (manifest) {
          html += '<div><strong>Métadonnées manifest</strong><pre>' + escapeHtml(JSON.stringify(manifest, null, 2)) + '</pre></div>';
        }
        body.innerHTML = html;
        return;
      }
      body.innerHTML = `<p>Type de preview non supporté : ${escapeHtml(data.type)}</p>`;
    })
    .catch(err => {
      body.innerHTML = `<p class="text-danger">Erreur de chargement : ${escapeHtml(err.message)}</p>`;
    });
}

function closePreview(event) {
  if (event && event.target !== event.currentTarget && !event.target.classList.contains('btn-close')) {
    return;
  }
  // Arrête toute vidéo en cours dans le modal avant de le fermer
  const modal = document.getElementById('previewModal');
  modal.querySelectorAll('video').forEach(v => { v.pause(); v.src = ''; });
  modal.classList.remove('show');
  _previewCtx = null;
}

function regenFichier() {
  if (!_previewCtx) return;
  const { projet, lang, step } = _previewCtx;
  // Ferme le modal proprement
  const modal = document.getElementById('previewModal');
  modal.querySelectorAll('video').forEach(v => { v.pause(); v.src = ''; });
  modal.classList.remove('show');
  _previewCtx = null;
  // Lance la régénération dans la console
  lancer('regen', `${projet}/${lang}/${step}`);
}

function transferFichier() {
  if (!_previewCtx) return;
  const { projet, lang, step } = _previewCtx;
  const btn = document.getElementById('previewTransfer');
  const msg = document.getElementById('previewTransferMsg');
  btn.disabled = true;
  btn.textContent = '⏳ Transfert...';
  msg.textContent = '';
  fetch(`/transfer/${encodeURIComponent(projet)}/${encodeURIComponent(lang)}/${encodeURIComponent(step)}`, { method: 'POST' })
    .then(r => r.json())
    .then(data => {
      btn.disabled = false;
      btn.textContent = '📤 Transférer vers destination';
      if (data.ok) {
        msg.style.color = '#2d6a4f';
        msg.textContent = '✓ ' + data.message;
        // refresh page after short delay so table updates
        setTimeout(() => { localStorage.setItem('avf_selected_project', projet); location.reload(); }, 1800);
      } else {
        msg.style.color = '#dc3545';
        msg.textContent = '✗ ' + data.message;
      }
    })
    .catch(err => {
      btn.disabled = false;
      btn.textContent = '📤 Transférer vers destination';
      msg.style.color = '#dc3545';
      msg.textContent = 'Erreur réseau : ' + err.message;
    });
}

function escapeHtml(text) {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

function completeProgress(success) {
  const area = document.getElementById('progressArea');
  const bar = document.getElementById('progressBar');
  const labelEl = document.getElementById('progressLabel');
  if (!area || !bar || !labelEl) return;
  bar.style.width = '100%';
  bar.setAttribute('aria-valuenow', '100');
  labelEl.textContent = success ? 'Tâche terminée' : 'Tâche échouée';
  area.classList.remove('d-none');
  setTimeout(() => { if (area) area.classList.add('d-none'); }, 2500);
}

function lancer(action, projet) {
  if (es) { es.close(); es = null; }
  clearConsole();
  document.getElementById('consoleTitle').textContent = action + ' — ' + projet;
  log('Lancement : ' + action + ' / ' + projet + ' ...');
  log('');
  showProgress('Exécution en cours : ' + action);

  es = new EventSource('/run/' + encodeURIComponent(action) + '/' + encodeURIComponent(projet));
  es.onmessage = e => { if (e.data) { log(e.data); updateProgress(); } };
  es.addEventListener('done', () => {
    es.close(); es = null;
    completeProgress(true);
    stopSsePolling();
    log('Terminé. Le journal est conservé tant que tu ne recharges pas la page.');
    if (action !== 'srt') {
      setTimeout(() => location.reload(), 1500);
    }
  });
  es.onerror = () => { log('--- Connexion perdue ---'); es.close(); es = null; };
  // start polling server-side count
  startSsePolling();
}

function lancerFluxPost() {
  const select = document.getElementById('projectSelect');
  if (!select || !select.value) { log('Choisis d’abord un projet.'); return; }
  const overwrite = document.getElementById('cbOverwrite');
  lancer(overwrite && overwrite.checked ? 'post_overwrite' : 'post', select.value);
}

function lancerPost(projet) {
  const overwrite = document.getElementById('cbOverwrite');
  lancer(overwrite && overwrite.checked ? 'post_overwrite' : 'post', projet);
}

function lancerFlux(action) {
  const select = document.getElementById('projectSelect');
  if (!select || !select.value) {
    log('Choisis d’abord un projet.');
    return;
  }
  lancer(action, select.value);
}

function ouvrirFluxWebLocale() {
  const select = document.getElementById('projectSelect');
  if (!select || !select.value) {
    log('Choisis d’abord un projet.');
    return;
  }
  const lbl = document.getElementById('startModalProjectLabel');
  if (lbl) lbl.textContent = 'Projet actif : ' + select.value;
  const modal = document.getElementById('startModal');
  if (modal) modal.classList.add('show');
}

function closeStartModal(event) {
  if (event && event.target !== event.currentTarget && !event.target.classList.contains('btn-close')) {
    return;
  }
  const modal = document.getElementById('startModal');
  if (modal) modal.classList.remove('show');
}

function demarrerServeurDepuisModal() {
  const select = document.getElementById('projectSelect');
  if (!select || !select.value) {
    log('Choisis d’abord un projet.');
    return;
  }
  clearConsole();
  document.getElementById('consoleTitle').textContent = 'Flux Web local';
  fetch('/server/start', { method: 'POST' })
    .then(r => r.json())
    .then(data => {
      log(data.message || 'Serveur local actif.');
      log('Flux interface web locale actif pour ' + select.value);
      selectProject();
      closeStartModal();
    })
    .catch(() => {
      log('Serveur local actif (verification reseau indisponible).');
      log('Flux interface web locale actif pour ' + select.value);
      selectProject();
      closeStartModal();
    });
}

function demarrerProgrammeDepuisModal() {
  const select = document.getElementById('projectSelect');
  if (!select || !select.value) {
    log('Choisis d’abord un projet.');
    return;
  }
  closeStartModal();
  lancer('run', select.value);
}

function showNew() {
  document.getElementById('formNew').classList.remove('d-none');
  document.getElementById('newName').focus();
}
function hideNew() {
  document.getElementById('formNew').classList.add('d-none');
}

function creerProjet() {
  const nom = document.getElementById('newName').value.trim();
  if (!nom) return;
  fetch('/nouveau', {method:'POST', headers:{'Content-Type':'application/json'},
                    body: JSON.stringify({nom})})
    .then(r => r.json())
    .then(d => {
      clearConsole(); log(d.message); hideNew();
      setTimeout(() => location.reload(), 800);
    });
}

function restarterServeur() {
  const overlay = document.getElementById('restartOverlay');
  overlay.classList.add('show');
  let n = 5;
  const el = document.getElementById('restartCountdown');
  el.textContent = n;
  setInterval(() => { if (n > 0) { n--; el.textContent = n; } }, 1000);
  fetch('/restart', { method: 'POST' }).catch(() => {});
  // Tente de recharger toutes les 800ms dès que le serveur répond
  function tryReload(tries) {
    if (tries > 40) { location.reload(); return; }
    fetch('/').then(() => location.reload()).catch(() => setTimeout(() => tryReload(tries + 1), 800));
  }
  setTimeout(() => tryReload(0), 3000);
}

function openHelp() {
  document.getElementById('helpModal').classList.add('show');
}

function closeHelp(event) {
  if (event && event.target !== event.currentTarget && !event.target.classList.contains('btn-close') && event.target.tagName !== 'BUTTON') {
    return;
  }
  document.getElementById('helpModal').classList.remove('show');
}

function stopSSE() {
  if (es) {
    es.close();
    es = null;
    log('EventSource arrêté par l\'utilisateur.');
    completeProgress(false);
  } else {
    log('Aucune connexion SSE active.');
  }
  stopSsePolling();
}

function updateSseCountFromServer() {
  fetch('/sse_count')
    .then(r => r.json())
    .then(d => {
      const el = document.getElementById('sseCount');
      if (el) el.textContent = `SSE:${d.count}`;
    })
    .catch(() => {});
}

function startSsePolling() {
  updateSseCountFromServer();
  if (ssePollIntervalId) clearInterval(ssePollIntervalId);
  ssePollIntervalId = setInterval(updateSseCountFromServer, 2000);
}

function stopSsePolling() {
  if (ssePollIntervalId) {
    clearInterval(ssePollIntervalId);
    ssePollIntervalId = null;
  }
  const el = document.getElementById('sseCount');
  if (el) el.textContent = 'SSE:0';
}

function selectProject() {
  const select = document.getElementById('projectSelect');
  if (!select) return;
  const project = select.value;
  localStorage.setItem('avf_selected_project', project);
  document.getElementById('activeProjectLabel').textContent = project;
  document.querySelectorAll('.project-card').forEach(card => {
    card.style.display = card.dataset.project === project ? 'block' : 'none';
  });
}

window.addEventListener('DOMContentLoaded', () => {
  const select = document.getElementById('projectSelect');
  if (!select || select.options.length === 0) return;
  const saved = localStorage.getItem('avf_selected_project');
  if (saved) {
    const option = Array.from(select.options).find(o => o.value === saved);
    if (option) select.value = saved;
  }
  if (select.selectedIndex < 0) select.selectedIndex = 0;
  selectProject();
});

function uploadFile(projet, lang, idx) {
  const input = document.getElementById(`file_${lang}_${idx}`);
  if (!input || !input.files || !input.files[0]) {
    log('Aucun fichier sélectionné.');
    return;
  }
  const file = input.files[0];
  const formData = new FormData();
  formData.append('file', file);
  clearConsole();
  document.getElementById('consoleTitle').textContent = 'Upload — ' + projet;
  log(`Upload de ${file.name} vers ${projet}/${lang}/video/ ...`);
  fetch(`/upload/${encodeURIComponent(projet)}/${encodeURIComponent(lang)}`, {
    method: 'POST', body: formData
  })
    .then(async r => {
      const data = await r.json();
      if (!r.ok) throw new Error(data.message || 'Erreur upload');
      log(data.message);
      localStorage.setItem('avf_selected_project', projet);
      setTimeout(() => location.reload(), 1200);
    })
    .catch(e => log('Erreur upload : ' + e.message));
}

function uploadTranslation(projet, idx) {
  const select = document.getElementById(`upload_lang_${idx}`);
  const lang = select ? select.value : null;
  if (!lang) {
    log('Choisis d’abord une langue.');
    return;
  }
  const input = document.getElementById(`file_lang_${idx}`);
  if (!input || !input.files || !input.files[0]) {
    log('Aucun fichier sélectionné.');
    return;
  }
  const file = input.files[0];
  const formData = new FormData();
  formData.append('file', file);
  clearConsole();
  document.getElementById('consoleTitle').textContent = 'Upload traduction — ' + projet;
  log(`Upload de ${file.name} vers ${projet}/${lang}/video/ ...`);
  fetch(`/upload/${encodeURIComponent(projet)}/${encodeURIComponent(lang)}`, {
    method: 'POST', body: formData
  })
    .then(async r => {
      const data = await r.json();
      if (!r.ok) throw new Error(data.message || 'Erreur upload');
      log(data.message);
      localStorage.setItem('avf_selected_project', projet);
      setTimeout(() => location.reload(), 1200);
    })
    .catch(e => log('Erreur upload : ' + e.message));
}

function uploadEditorial(projet, docType, idx) {
  const fileInputMap = {
    'youtube_summary': `file_youtube_${idx}`,
    'tiktok_summary': `file_tiktok_${idx}`,
    'transcript': `file_transcript_${idx}`
  };
  const inputId = fileInputMap[docType];
  if (!inputId) { log('Type de document inconnu.'); return; }
  const input = document.getElementById(inputId);
  if (!input || !input.files || !input.files[0]) { log('Aucun fichier selectione.'); return; }
  const file = input.files[0];
  const formData = new FormData();
  formData.append('file', file);
  formData.append('doc_type', docType);
  clearConsole();
  document.getElementById('consoleTitle').textContent = 'Upload document — ' + projet;
  log(`Upload de ${file.name} vers ${projet}/editorial/ ...`);
  fetch(`/upload-editorial/${encodeURIComponent(projet)}`, {
    method: 'POST', body: formData
  }).then(async r => {
    const data = await r.json();
    if (!r.ok) throw new Error(data.message || 'Erreur upload');
    log(data.message);
    localStorage.setItem('avf_selected_project', projet);
    setTimeout(() => location.reload(), 1200);
  }).catch(e => log('Erreur upload : ' + e.message));
}
</script>

</body></html>
"""

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route('/preview/<projet>/<lang>/<step>')
def preview(projet: str, lang: str, step: str):
    projet_path = VIDEOS_EN_COURS / projet
    if not projet_path.exists():
        return jsonify({"type": "none", "message": f"Projet introuvable : {projet}"}), 404
    if lang not in LANGUES_CONNUES and lang != 'fr':
        return jsonify({"type": "none", "message": f"Langue inconnue : {lang}"}), 400
    return jsonify(get_preview_info(projet_path, lang, step))


@app.route('/files/<path:filepath>')
def serve_file(filepath: str):
    target = safe_path_under(VIDEOS_EN_COURS, filepath)
    if not target or not target.exists() or not target.is_file():
        return jsonify({"message": "Fichier introuvable"}), 404
    resp = send_file(str(target), conditional=True)
    # Evite que le navigateur cache les videos generees (permet de voir la nouvelle version apres regeneration)
    if target.suffix.lower() in ('.mp4', '.webm', '.mov'):
        resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        resp.headers['Pragma'] = 'no-cache'
        resp.headers['Expires'] = '0'
    return resp


@app.route("/")
def index():
    return render_template_string(PAGE, projets=get_projects())


def check_completeness_stream(projet: str):
    """Vérifie et affiche la complétude source vs destination (videos_finales)."""
    def generate():
        proj_src = VIDEOS_EN_COURS / projet
        proj_dst = VIDEOS_FINALES / projet
        langues_all = LANGUES_CONNUES | {'fr'}
        steps = [
            ("video/*.mp4",   "Source vidéo"),
            ("tiktok/*.mp4",  "TikTok"),
            ("youtube/*.mp4", "YouTube"),
            ("youtube/*.srt", "SRT YouTube"),
            ("video/*.srt",   "SRT vidéo"),
        ]
        if not proj_src.exists():
            yield f"data: ❌ Projet introuvable : {projet}\n\n"
            yield "event: done\ndata: ok\n\n"
            return
        yield f"data: ═══ Complétude — {projet} ═══\n\n"
        yield f"data: Source  : {proj_src}\n\n"
        yield f"data: Dest    : {proj_dst}\n\n"
        yield f"data: \n\n"
        mf_src = proj_src / "manifest.json"
        mf_dst = proj_dst / "manifest.json"
        yield f"data: manifest.json  {'✓ source' if mf_src.exists() else '✗ absent'}  /  {'✓ dest' if mf_dst.exists() else '✗ non sync'}\n\n"
        yield f"data: \n\n"
        all_langs = sorted(
            d.name for d in proj_src.iterdir()
            if d.is_dir() and d.name in langues_all
        )
        missing_count = 0
        for lg in all_langs:
            yield f"data: ─── {lg.upper()} ───\n\n"
            src_lang = proj_src / lg
            dst_lang = proj_dst / lg
            for pattern, label in steps:
                src_files = list(src_lang.glob(pattern)) if src_lang.exists() else []
                dst_files = list(dst_lang.glob(pattern)) if dst_lang.exists() else []
                if src_files and dst_files:
                    icon = "✅"
                elif src_files:
                    icon = "🔄 à synchroniser"
                    missing_count += 1
                else:
                    icon = "☐  absent"
                yield f"data:   {label:<18} {icon}\n\n"
            yield f"data: \n\n"
        if missing_count:
            yield f"data: → {missing_count} élément(s) à synchroniser — utilise ↑ Sync manquants\n\n"
        else:
            yield f"data: ✓ Tout est synchronisé vers la destination\n\n"
        yield "event: done\ndata: ok\n\n"
    return Response(stream_with_context(generate()), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def regen_one_stream(projet: str, lang: str, step: str):
    """Regenere un seul fichier (tiktok ou youtube) pour une langue donnee."""
    step_flag = {
        "youtube": "--overwrite-youtube",
        "tiktok":  "--overwrite-tiktok",
        "source":  None,
    }
    flag = step_flag.get(step)
    if flag is None:
        def _err():
            yield f"data: Regeneration non disponible pour le step '{step}'\n\n"
            yield "event: done\ndata: ok\n\n"
        return Response(stream_with_context(_err()), mimetype="text/event-stream",
                        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
    # Lance avf_post.py --overwrite-xxx <projet> --lang <lang>
    args = ["py", "-u", str(AVF_DIR / "avf_post.py"), flag, "--lang", lang, projet]
    return stream_cmd(args)


@app.route("/run/<action>/<path:projet>")
def run_action(action: str, projet: str):
    if action == "check":
        return check_completeness_stream(projet)
    if action == "regen":
        # projet est en fait "nom_projet/lang/step"
        parts = projet.split("/")
        if len(parts) == 3:
            nom, lang, step = parts
            return regen_one_stream(nom, lang, step)
        return Response("Format invalide", status=400)
    cmds = {
        "download":       ["py", "-u", str(AVF_DIR / "heygen_download.py")],
        "post":           ["py", "-u", str(AVF_DIR / "avf_post.py"), projet],
        "post_overwrite": ["py", "-u", str(AVF_DIR / "avf_post.py"), "--overwrite-all", projet],
        "sync":           ["py", "-u", str(AVF_DIR / "avf_sync.py"), projet],
        "run":            ["py", "-u", str(AVF_DIR / "avf_run.py"), projet, "--post"],
        "srt":            ["py", "-u", str(AVF_DIR / "avf_post.py"), "--srt-only", projet],
        "srt_force":      ["py", "-u", str(AVF_DIR / "avf_post.py"), "--srt-only", "--overwrite-srt", projet],
        "youtube_fix":    ["py", "-u", str(AVF_DIR / "avf_post.py"), "--overwrite-youtube", projet],
    }
    if action not in cmds:
        return Response("Action inconnue", status=400)
    return stream_cmd(cmds[action])


@app.route("/upload/<projet>/<lang>", methods=["POST"])
def upload_video(projet: str, lang: str):
    if lang not in LANGUES_CONNUES and lang != 'fr':
        return jsonify({"message": f"Langue inconnue : {lang}"}), 400
    projet_path = VIDEOS_EN_COURS / projet
    if not projet_path.exists():
        return jsonify({"message": f"Projet introuvable : {projet}"}), 404
    file = request.files.get('file')
    ok, message = save_upload(file, projet_path, lang)
    return jsonify({"message": message}), (200 if ok else 400)


@app.route("/delete/<projet>", methods=["POST"])
def delete_project(projet: str):
    projet_path = VIDEOS_EN_COURS / projet
    if not projet_path.exists():
        return jsonify({"message": f"Projet introuvable : {projet}"}), 404
    try:
        shutil.rmtree(projet_path)
        return jsonify({"message": f"✓ Projet supprimé : {projet}"}), 200
    except Exception as e:
        return jsonify({"message": f"Erreur suppression : {e}"}), 500


@app.route("/upload-editorial/<projet>", methods=["POST"])
def upload_editorial(projet: str):
    projet_path = VIDEOS_EN_COURS / projet
    if not projet_path.exists():
        return jsonify({"message": f"Projet introuvable : {projet}"}), 404
    file = request.files.get('file')
    doc_type = request.form.get('doc_type', 'unknown')
    ok, message = save_editorial_upload(file, projet_path, doc_type)
    return jsonify({"message": message}), (200 if ok else 400)


@app.route("/nouveau", methods=["POST"])
def nouveau():
    nom = request.json.get("nom", "").strip()
    if not nom:
        return jsonify({"message": "Nom vide"}), 400
    dest = VIDEOS_EN_COURS / nom / "fr" / "video"
    dest.mkdir(parents=True, exist_ok=True)
    return jsonify({"message": f"✓ Projet créé : {nom}  →  Place ta vidéo FR dans {dest}"})


@app.route('/transfer/<projet>/<lang>/<step>', methods=['POST'])
def transfer_file(projet: str, lang: str, step: str):
    """Copie les fichiers source (videos_en_cours) vers la destination (videos_finales)."""
    proj_src = VIDEOS_EN_COURS / projet
    proj_dst = VIDEOS_FINALES / projet
    if not proj_src.exists():
        return jsonify({"ok": False, "message": f"Projet source introuvable : {projet}"}), 404

    step_patterns = {
        "source":    [("video", "*.mp4"), ("video", "*.mov"), ("video", "*.mkv"), ("video", "*.avi")],
        "tiktok":    [("tiktok", "*.mp4")],
        "youtube":   [("youtube", "*.mp4")],
        "srt":       [("youtube", "*.srt"), ("video", "*.srt")],
        "editorial": [],  # project-level, not per-lang
    }
    patterns = step_patterns.get(step)
    if patterns is None:
        return jsonify({"ok": False, "message": f"Step inconnu : {step}"}), 400

    src_lang_dir = proj_src / lang
    dst_lang_dir = proj_dst / lang
    copied = []
    for (subfolder, glob_pat) in patterns:
        src_folder = src_lang_dir / subfolder
        if not src_folder.exists():
            continue
        for src_file in sorted(src_folder.glob(glob_pat)):
            dst_file = dst_lang_dir / subfolder / src_file.name
            dst_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_file, dst_file)
            copied.append(src_file.name)

    if not copied:
        return jsonify({"ok": False, "message": "Aucun fichier source trouvé pour ce step."})
    return jsonify({"ok": True, "message": f"{len(copied)} fichier(s) transféré(s) : {', '.join(copied)}"})


@app.route('/favicon.ico')
def favicon():
    # Retourne vide pour éviter 404 dans la console du navigateur
    return ('', 204)


@app.route('/sse_count')
def sse_count():
  with SSE_LOCK:
    return jsonify({"count": SSE_CONN_COUNT})


@app.route('/restart', methods=['POST'])
def restart_server():
    import time as _time
    import tempfile
    def _do():
        _time.sleep(1.0)
        script = str(AVF_DIR / 'avf_web.py')
        extra  = ' '.join(f'"{a}"' for a in sys.argv[1:])
        bat = (
            f'@echo off\r\n'
            f'ping 127.0.0.1 -n 3 > nul\r\n'
            f'py "{script}" {extra}\r\n'
        )
        bat_path = AVF_DIR / '_restart_avf.bat'
        bat_path.write_text(bat, encoding='utf-8')
        subprocess.Popen(
            ['cmd', '/c', 'start', '/b', str(bat_path)],
            creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
            close_fds=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        os._exit(0)
    threading.Thread(target=_do, daemon=True).start()
    return jsonify({'ok': True, 'message': 'Redémarrage en cours…'})


@app.route('/server/start', methods=['POST'])
def server_start():
  return jsonify({"message": f"Serveur web local actif sur {SERVER_PUBLIC_URL}"})


def parse_host_port(argv: list[str]) -> tuple[str, int]:
  host = "127.0.0.1"
  port = 5000
  i = 0
  while i < len(argv):
    a = argv[i]
    if a == "--host" and i + 1 < len(argv):
      host = argv[i + 1].strip()
      i += 2
      continue
    if a == "--port" and i + 1 < len(argv):
      try:
        port = int(argv[i + 1].strip())
      except ValueError:
        print(f"Port invalide : {argv[i + 1]}")
        sys.exit(1)
      i += 2
      continue
    i += 1
  return host, port


if __name__ == "__main__":
  host, port = parse_host_port(sys.argv[1:])
  if host in ("127.0.0.1", "localhost"):
    public_host = "localhost"
  else:
    public_host = host

  SERVER_PUBLIC_URL = f"http://{public_host}:{port}"
  if port == 80:
    SERVER_PUBLIC_URL = f"http://{public_host}"

  print("=" * 50)
  print("  AVF — Interface web")
  print(f"  Ouvre : {SERVER_PUBLIC_URL}")
  print("=" * 50)
  app.run(host=host, port=port, debug=False, threaded=True)
