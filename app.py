from flask import Flask, render_template, request, flash, redirect, url_for, send_from_directory, make_response, jsonify
from werkzeug.utils import secure_filename
from time import sleep
import os
import subprocess
import shutil
import uuid
from flask_cors import CORS
import time
import threading
import json
from mocpy import MOC
from threading import Lock, Thread

app = Flask(__name__)
CORS(app)
app.secret_key = 'your-secret-key'

HIPS_DIR = os.path.join(os.getcwd(), 'hips')

UPLOAD_FOLDER = 'data/HTTP/F658N/'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
#os.makedirs(UPLOAD_FOLDER, exist_ok=True)

ALLOWED_EXTENSIONS = {'fits'}
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024 * 40  # 4 Go

user_files = {}
progress_data = {}
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

def generate_fits_tiles(output_folder):
    command = [
        "java", "-jar", "tools/Hipsgen.jar",
        "in=data/HTTP/F658N",
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
        "in=data/HTTP/F658N",
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

def get_total_nb_tiles(moc_path):
    total_nb_tiles = 0
    moc = MOC.load(moc_path)
    hips_order = moc.max_order
    for order in range(0, hips_order+1):
        total_nb_tiles += len(moc.degrade_to_order(order).flatten())
    return total_nb_tiles

def get_nb_tiles_generated(hips_root):
    nb_tiles = 0
    for root, dirs, files in os.walk(os.path.join(hips_root, 'Norder')):
        for file in files:
            if file.endswith('.jpg') or file.endswith('.png') or file.endswith('.fits'):
                nb_tiles += 1
    return nb_tiles

def background_task(hips_id, filename, fits_path):
    with progress_lock:
        task_queue[hips_id] = {'progress': 0, 'status': 'running'}

    try:
        hips_output_dir = os.path.join("hips", hips_id)
        os.makedirs(hips_output_dir, exist_ok=True)

        with progress_lock:
            task_queue[hips_id]['progress'] = 5
        
        if generate_fits_index(hips_output_dir, fits_path):
            with progress_lock:
                task_queue[hips_id]['progress'] = 25
            
            if generate_fits_tiles(hips_output_dir):
                with progress_lock:
                    task_queue[hips_id]['progress'] = 60
                
                if generate_png_tiles(hips_output_dir):
                    with progress_lock:
                        task_queue[hips_id]['progress'] = 100
                        task_queue[hips_id]['status'] = 'complete'
                    return True
        
        with progress_lock:
            task_queue[hips_id]['progress'] = 100
            task_queue[hips_id]['status'] = 'error'
        return False

    except Exception as e:
        with progress_lock:
            task_queue[hips_id]['progress'] = 100
            task_queue[hips_id]['status'] = 'error'
        return False

@app.route("/")
def index():
    user_id = request.cookies.get('userID')
    if not user_id:
        user_id = str(uuid.uuid4())

    user_folder = os.path.join(app.config['UPLOAD_FOLDER'], user_id)
    os.makedirs(user_folder, exist_ok=True)

    if user_id not in user_files:
        user_files[user_id] = []
        for filename in os.listdir(user_folder):
            if filename.endswith(".fits"):
                user_files[user_id].append({
                    "filename": filename,
                    "hips_id": None
                })

    files = user_files.get(user_id, [])
  
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

    if 'file' not in request.files:
        flash("❌ no file received")
        return redirect('/')

    uploaded_files = request.files.getlist("file")
    if not uploaded_files or all(f.filename == '' for f in uploaded_files):
        flash("❌ no file selected")
        return redirect('/')

    valid_files = [f for f in uploaded_files if f and allowed_file(f.filename)]
    if not valid_files:
        flash("❌ no .fits file valid")
        return redirect('/')

    if user_id not in user_files:
        user_files[user_id] = []


    for file in valid_files:
        filename = secure_filename(file.filename)
        fits_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(fits_path)

        if not any(entry['filename'] == filename for entry in user_files[user_id]):
            user_files[user_id].append({
            "filename": filename,
            "hips_id": None
        })


        flash(f"✅ file {filename} uploaded")

    return redirect('/')

@app.route('/hips/<path:filename>')
def serve_hips(filename):
    return send_from_directory('hips', filename)

#@app.route("/view/<hips_id>")
#def show_hips(hips_id):
#    return render_template("/", hips_id=hips_id)

@app.route("/my_files")
def my_files():
    user_id = request.cookies.get('userID')
    if not user_id or user_id not in user_files:
        return "nof files found for this user"

    return render_template("/", files=user_files[user_id])

@app.route("/generate_hips", methods=["POST"])
def generate_hips():
    hips_id = None
    user_id = request.cookies.get('userID')
    if not user_id or user_id not in user_files:
        flash("❌ unknown user")
        return redirect('/')

    selected_files = request.form.getlist('selected_files')
    hips_ids = []
    if not selected_files:
        flash("❌ no file selected")
        return redirect('/')

    for filename in selected_files:
        user_file_entry = next((f for f in user_files[user_id] if f["filename"] == filename), None)
        if not user_file_entry:
            flash(f"❌ file {filename} not found")
            continue

        #if user_file_entry.get("hips_id"):
        #    flash(f" hips already generated for {filename}")
        #    continue

        fits_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        if not os.path.exists(fits_path):
            flash(f"❌ file {filename} missing")
            continue

        Thread(target=background_task, args=(
            hips_id, 
            filename, 
            fits_path
        )).start()
   
    """
        hips_id = f"{uuid.uuid4()}_{filename.rsplit('.', 1)[0]}"
        hips_ids.append(hips_id)

        hips_output_dir = os.path.join("hips", hips_id)
        os.makedirs(hips_output_dir, exist_ok=True)

        if not generate_fits_index(hips_output_dir, fits_path):
            flash(f"❌ hips error for {filename}")
        elif not generate_fits_tiles(hips_output_dir):
            flash(f"❌ fites tiles error for {filename}")
        elif not generate_png_tiles(hips_output_dir):
            flash(f"❌ png error for {filename}")
        else:
            user_file_entry["hips_id"] = hips_id
            flash(f"✅ hips generated for {filename}")
            """

    return jsonify({'hips_id': hips_ids[0] if hips_ids else None})

@app.route("/get_progress")
def get_progress():
    hips_id = request.args.get('hips_id')
    if not hips_id:
        return jsonify(progress=0)

    hips_root = os.path.join("hips", hips_id)
    stages = {
        'index': 20,
        'fits_tiles': 50,
        'png_tiles': 80,
        'complete': 100
    }

    try:
        props_file = os.path.join(hips_root, 'properties')
        moc_file = os.path.join(hips_root, 'Moc.fits')
        
        if not os.path.exists(props_file):
            return jsonify(progress=1)
            
        if os.path.exists(moc_file):
            if os.path.exists(os.path.join(hips_root, 'Norder3')):
                return jsonify(progress=stages['png_tiles'])
            return jsonify(progress=stages['fits_tiles'])
            
        return jsonify(progress=stages['index'])

    except Exception as e:
        return jsonify(progress=0)

@app.route("/deleteAll", methods=["POST"])
def delete_all():
    user_id = request.cookies.get('userID')

    if not user_id or user_id not in user_files:
        flash("❌ Utilisateur inconnu", "error")
        return redirect('/')

    deleted_count = 0
    for file_info in user_files[user_id]:
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], file_info['filename'])
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
                deleted_count += 1
        except Exception as e:
            flash(f"❌ Erreur lors de la suppression de {file_info['filename']}", "error")

    user_files[user_id] = []

    if deleted_count > 0:
        flash(f"✅ {deleted_count} fichier(s) supprimé(s)", "success")
    else:
        flash("ℹ️ Aucun fichier à supprimer", "info")

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

    fits_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    if os.path.exists(fits_path):
        os.remove(fits_path)
        user_files[user_id].remove(user_file_entry)
        flash(f"✅ file {filename} deleted")
    else:
        flash(f"❌ file {filename} missing")

    return redirect('/')

@app.errorhandler(413)
def too_large(e):
    flash("File too large, max 4GB")
    return redirect('/')

if __name__ == "__main__":
    app.run(debug=True)
