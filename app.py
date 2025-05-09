from flask import Flask, render_template, request, flash, redirect, url_for, send_from_directory, make_response, jsonify
from werkzeug.utils import secure_filename
import os
import subprocess
import uuid
from flask_cors import CORS
import time
import threading
from mocpy import MOC
from threading import Lock, Thread

app = Flask(__name__)
CORS(app)
app.secret_key = 'your-secret-key'

UPLOAD_FOLDER = 'uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
ALLOWED_EXTENSIONS = {'fits'}
app.config['MAX_CONTENT_LENGTH'] = 4 * 1024 * 1024 * 1024  # 4 Go

user_files = {}
task_queue = {}
progress_lock = Lock()

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def generate_fits_index(output_folder, fits_file):
    command = [
        "java", "-jar", "tools/Hipsgen.jar",
        f"in={fits_file}",
        f"out={output_folder}",
        "creator_did=test/P/HTTP/F658N",
        "INDEX"
    ]
    try:
        result = subprocess.run(command, check=True, capture_output=True, text=True)
        print("✅ fits index generated", result.stdout)
        return True
    except subprocess.CalledProcessError as e:
        print("❌ error generating fits index", e.stderr)
        return False

def generate_fits_tiles(output_folder, input_folder):
    command = [
        "java", "-jar", "tools/Hipsgen.jar",
        f"in={input_folder}",
        f"out={output_folder}",
        "creator_did=test/P/HTTP/F658N",
        "TILES"
    ]
    try:
        result = subprocess.run(command, check=True, capture_output=True, text=True)
        print("✅ fits tiles generated", result.stdout)
        return True
    except subprocess.CalledProcessError as e:
        print("❌ error generating fits tiles", e.stderr)
        return False

def generate_png_tiles(output_folder):
    command = [
        "java", "-jar", "tools/Hipsgen.jar",
        f"in={output_folder}",
        f"out={output_folder}",
        "creator_did=test/P/HTTP/F658N",
        "pixelCut=0 5 log",
        "PNG"
    ]
    try:
        result = subprocess.run(command, check=True, capture_output=True, text=True)
        print("✅ png tiles generated", result.stdout)
        return True
    except subprocess.CalledProcessError as e:
        print("❌ error generating png tiles", e.stderr)
        return False

def count_tiles_by_extension(root_dir, ext):
    count = 0
    for root, _, files in os.walk(root_dir):
        count += len([f for f in files if f.endswith(ext)])
    return count

def background_task(hips_id, filename, fits_path):
    with progress_lock:
        task_queue[hips_id] = {'progress': 0, 'status': 'running'}

    try:
        hips_output_dir = os.path.join("hips", hips_id)
        os.makedirs(hips_output_dir, exist_ok=True)

        if not generate_fits_index(hips_output_dir, fits_path):
            raise Exception("Erreur lors de la génération de l'index")
        with progress_lock:
            task_queue[hips_id]['progress'] = 2

        moc_path = os.path.join(hips_output_dir, "HpxFinder", "Moc.fits")
        moc = MOC.load(moc_path)
        hips_order = moc.max_order
        total_tiles = sum(len(moc.degrade_to_order(order).flatten()) for order in range(hips_order + 1))

        if total_tiles == 0:
            raise Exception("Aucune tuile à générer")

        user_folder = os.path.dirname(fits_path)
        if not generate_fits_tiles(hips_output_dir, user_folder):
            raise Exception("Erreur lors de la génération des tuiles FITS")
        fits_dir = os.path.join(hips_output_dir, "FITS")
        while True:
            fits_count = count_tiles_by_extension(fits_dir, ".fits")
            frac = min(fits_count / total_tiles, 1.0)
            progress = 2 + int(frac * 48)
            with progress_lock:
                task_queue[hips_id]['progress'] = progress
            if fits_count >= total_tiles:
                break
            time.sleep(0.5)

        if not generate_png_tiles(hips_output_dir):
            raise Exception("Erreur lors de la génération des tuiles PNG")
        png_dir = os.path.join(hips_output_dir, "PNG")
        while True:
            png_count = count_tiles_by_extension(png_dir, ".png")
            frac = min(png_count / total_tiles, 1.0)
            progress = 50 + int(frac * 49)
            with progress_lock:
                task_queue[hips_id]['progress'] = progress
            if png_count >= total_tiles:
                break
            time.sleep(0.5)

        with progress_lock:
            task_queue[hips_id]['progress'] = 100
            task_queue[hips_id]['status'] = 'complete'

    except Exception as e:
        with progress_lock:
            task_queue[hips_id]['progress'] = 100
            task_queue[hips_id]['status'] = 'error'
        print("❌ Background task failed:", str(e))

@app.route("/")
def index():
    user_id = request.cookies.get('userID') or str(uuid.uuid4())
    user_folder = os.path.join(app.config['UPLOAD_FOLDER'], user_id)
    os.makedirs(user_folder, exist_ok=True)

    if user_id not in user_files:
        user_files[user_id] = [
            {"filename": f, "hips_id": None} for f in os.listdir(user_folder) if f.endswith(".fits")
        ]

    files = user_files[user_id]
    hips_ids = [f['hips_id'] for f in files if f.get('hips_id')]
    latest_hips_id = hips_ids[-1] if hips_ids else None

    resp = make_response(render_template('upload_form.html', files=files, hips_id=latest_hips_id))
    resp.set_cookie('userID', user_id, expires=time.time() + 60*60*24*365)
    return resp

@app.route("/upload", methods=["POST"])
def upload_file():
    user_id = request.cookies.get('userID')
    if not user_id:
        return redirect('/')

    uploaded_files = request.files.getlist("file")
    if not uploaded_files or all(f.filename == '' for f in uploaded_files):
        flash("❌ no file selected")
        return redirect('/')

    valid_files = [f for f in uploaded_files if f and allowed_file(f.filename)]
    if not valid_files:
        flash("❌ no .fits file valid")
        return redirect('/')

    user_folder = os.path.join(app.config['UPLOAD_FOLDER'], user_id)
    os.makedirs(user_folder, exist_ok=True)
    if user_id not in user_files:
        user_files[user_id] = []

    for file in valid_files:
        filename = secure_filename(file.filename)
        fits_path = os.path.join(user_folder, filename)
        file.save(fits_path)

        if not any(entry['filename'] == filename for entry in user_files[user_id]):
            user_files[user_id].append({"filename": filename, "hips_id": None})

        flash(f"✅ file {filename} uploaded")

    return redirect('/')

@app.route('/hips/<path:filename>')
def serve_hips(filename):
    return send_from_directory('hips', filename)

@app.route("/generate_hips", methods=["POST"])
def generate_hips():
    user_id = request.cookies.get('userID')
    if not user_id or user_id not in user_files:
        flash("❌ Utilisateur inconnu")
        return redirect('/')

    selected_files = request.form.getlist('selected_files')
    if not selected_files:
        flash("❌ Aucun fichier sélectionné")
        return redirect('/')

    filename = selected_files[0]
    user_file_entry = next((f for f in user_files[user_id] if f["filename"] == filename), None)
    if not user_file_entry:
        flash(f"❌ Fichier {filename} introuvable")
        return redirect('/')

    fits_path = os.path.join(app.config['UPLOAD_FOLDER'], user_id, filename)
    if not os.path.exists(fits_path):
        flash(f"❌ Fichier {filename} manquant")
        return redirect('/')

    hips_id = f"{uuid.uuid4()}_{filename.rsplit('.', 1)[0]}"
    user_file_entry["hips_id"] = hips_id
    Thread(target=background_task, args=(hips_id, filename, fits_path)).start()

    return jsonify({'hips_id': hips_id})

@app.route("/get_progress")
def get_progress():
    hips_id = request.args.get('hips_id')
    if not hips_id:
        return jsonify(progress=0, status='unknown')

    with progress_lock:
        task = task_queue.get(hips_id)
        if not task:
            return jsonify(progress=0, status='unknown')
        return jsonify(progress=task['progress'], status=task['status'])

@app.route("/deleteAll", methods=["POST"])
def delete_all():
    user_id = request.cookies.get('userID')
    if not user_id or user_id not in user_files:
        flash("❌ Utilisateur inconnu")
        return redirect('/')

    deleted_count = 0
    user_folder = os.path.join(app.config['UPLOAD_FOLDER'], user_id)
    for file_info in user_files[user_id]:
        file_path = os.path.join(user_folder, file_info['filename'])
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
                deleted_count += 1
        except Exception as e:
            flash(f"❌ Erreur lors de la suppression de {file_info['filename']}")

    user_files[user_id] = []
    flash(f"✅ {deleted_count} fichier(s) supprimé(s)" if deleted_count else "ℹ️ Aucun fichier à supprimer")
    return redirect('/')

@app.route("/delete/<filename>", methods=["POST"])
def delete_file(filename):
    user_id = request.cookies.get('userID')
    if not user_id or user_id not in user_files:
        flash("❌ unknown user")
        return redirect('/')

    user_file_entry = next((f for f in user_files[user_id] if f["filename"] == filename), None)
    if not user_file_entry:
        flash(f"❌ file {filename} not found")
        return redirect('/')

    file_path = os.path.join(app.config['UPLOAD_FOLDER'], user_id, filename)
    if os.path.exists(file_path):
        os.remove(file_path)
        user_files[user_id].remove(user_file_entry)
        flash(f"✅ file {filename} deleted")
    else:
        flash(f"❌ file {filename} missing")

    return redirect('/')

@app.errorhandler(413)
def too_large(e):
    flash("file too large : max 4Gb")
    return redirect('/')

if __name__ == "__main__":
    app.run(debug=True)
