from flask import (Flask, render_template, request, flash, redirect, send_from_directory, make_response, jsonify)
import os
import time
import uuid
import subprocess
from threading import Lock, Thread
import tempfile
from flask_cors import CORS
from werkzeug.utils import secure_filename

from mocpy import MOC

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
    cmd = [
        "java", "-jar", "tools/Hipsgen.jar",
        f"in={fits_file}",
        f"out={output_folder}",
        "creator_did=test/P/HTTP/F658N",
        "INDEX"
    ]
    print("🆗 running command:", ' '.join(cmd))
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        return True
    except subprocess.CalledProcessError as e:
        print("❌ error generating fits index", e.stderr)
        return False

def get_fits_tiles_cmd(input_folder, output_folder):
    return [
        "java", "-jar", "tools/Hipsgen.jar",
        f"in={input_folder}",
        f"out={output_folder}",
        "creator_did=test/P/HTTP/F658N",
        "TILES"
    ]

def get_png_tiles_cmd(input_folder, output_folder):
    return [
        "java", "-jar", "tools/Hipsgen.jar",
        f"in={input_folder}",
        f"out={output_folder}",
        "creator_did=test/P/HTTP/F658N",
        "pixelCut=0 5 log",
        "PNG"
    ]

def count_tiles_by_extension(root_dir, extension):
    count = 0
    for dirpath, dirnames, filenames in os.walk(root_dir):
        count += sum(1 for f in filenames if f.lower().endswith(extension))
    return count

def generate_tiles_with_progress(command, output_folder, total_tiles, start_pct, span_pct, hips_id):
    proc = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    ext = '.png' if command[-1] == 'PNG' else '.fits'

    try:
        while proc.poll() is None:
            count = count_tiles_by_extension(output_folder, ext)
            frac = min(count / total_tiles, 1.0)
            pct = start_pct + int(frac * span_pct)
            with progress_lock:
                task_queue[hips_id]['progress'] = pct
            time.sleep(0.5)

        if proc.returncode != 0:
            err = proc.stderr.read().decode()
            raise Exception(f"Hipsgen failed ({ext}): {err}")
    finally:
        with progress_lock:
            task_queue[hips_id]['progress'] = start_pct + span_pct

def background_task(hips_id, filename, fits_path, user_id):
    with progress_lock:
        task_queue[hips_id] = {'progress': 0, 'status': 'running'}

    try:
        hips_output_dir = os.path.join("hips", hips_id)
        os.makedirs(hips_output_dir, exist_ok=True)

        if not generate_fits_index(hips_output_dir, fits_path):
            raise Exception("failed to generate fits index")
        with progress_lock:
            task_queue[hips_id]['progress'] = 2

        moc = MOC.load(os.path.join(hips_output_dir, "HpxFinder", "Moc.fits"))
        order_max = moc.max_order
        total_tiles = sum(
            len(moc.degrade_to_order(o).flatten())
            for o in range(order_max + 1)
        )
        if total_tiles == 0:
            raise Exception("no tiles found")

        input_path = fits_path
        cmd_tiles = get_fits_tiles_cmd(input_path, hips_output_dir)
        generate_tiles_with_progress(cmd_tiles, hips_output_dir,
                                     total_tiles, start_pct=2, span_pct=48,
                                     hips_id=hips_id)

        cmd_png = get_png_tiles_cmd(input_path, hips_output_dir)
        generate_tiles_with_progress(cmd_png, hips_output_dir,
                                     total_tiles, start_pct=50, span_pct=49,
                                     hips_id=hips_id)

        with progress_lock:
            task_queue[hips_id]['progress'] = 100
            task_queue[hips_id]['status'] = 'complete'

    except Exception as e:
        with progress_lock:
            task_queue[hips_id]['progress'] = 100
            task_queue[hips_id]['status'] = 'error'
        print("❌ background task failed:", e)

@app.route("/")
def index():
    user_id = request.cookies.get('userID') or str(uuid.uuid4())
    user_folder = os.path.join(app.config['UPLOAD_FOLDER'], user_id)
    os.makedirs(user_folder, exist_ok=True)

    if user_id not in user_files:
        user_files[user_id] = [
            {"filename": f, "hips_id": None}
            for f in os.listdir(user_folder) if f.endswith(".fits")
        ]

    files = user_files[user_id]
    latest = next((f['hips_id'] for f in files[::-1] if f['hips_id']), None)
    resp = make_response(render_template('upload_form.html', files=files, hips_id=latest))
    resp.set_cookie('userID', user_id, expires=time.time() + 365*24*3600)
    return resp

@app.route("/upload", methods=["POST"])
def upload_file():
    user_id = request.cookies.get('userID')
    if not user_id:
        return redirect('/')
    files = request.files.getlist("file")
    valid = [f for f in files if f and allowed_file(f.filename)]
    if not valid:
        flash("❌ no valid file")
        return redirect('/')
    folder = os.path.join(app.config['UPLOAD_FOLDER'], user_id)
    os.makedirs(folder, exist_ok=True)
    for f in valid:
        name = secure_filename(f.filename)
        path = os.path.join(folder, name)
        f.save(path)
        if not any(e['filename']==name for e in user_files.setdefault(user_id, [])):
            user_files[user_id].append({"filename": name, "hips_id": None})
        flash(f"✅ {name} uploaded")
    return redirect('/')

@app.route("/generate_hips", methods=["POST"])
def generate_hips():
    user_id = request.cookies.get('userID')
    selected = request.form.getlist('selected_files')
    if not user_id or not selected:
        flash("❌ user unknown or no file selected")
        return redirect('/')
    
    ##
    if len(selected) > 1:
        files = []
        for all in selected:
            files += all.split(',')

        temp_dir = tempfile.mkdtemp()
        upload_dir = os.path.join(app.config['UPLOAD_FOLDER'], user_id)
        for name in files:
            src = os.path.join(os.path.abspath(upload_dir), name)
            dst = os.path.join(temp_dir, name)
            os.symlink(src, dst)
            flash(f"✅ {name} linked in temp dir")
        hips_id = f"{user_id}/multi_{abs(hash('_'.join(files)))}"
        Thread(target=background_task, args=(hips_id, None, temp_dir, user_id)).start()

        properties_path = os.path.join("hips", hips_id, "properties")
        hips_ra = hips_dec = hips_fov = None
        if os.path.exists(properties_path):
            with open(properties_path) as f:
                for line in f:
                    if line.startswith("hips_initial_ra"):
                        hips_ra = float(line.split("=")[1].strip())
                    elif line.startswith("hips_initial_dec"):
                        hips_dec = float(line.split("=")[1].strip())
                    elif line.startswith("hips_initial_fov"):
                        hips_fov = float(line.split("=")[1].strip())

        print("🆗 ra : " + str(hips_ra))
        print("🆗 dec : " + str(hips_dec))
        print("🆗 fov : " + str(hips_fov))

        return jsonify({'hips_id': hips_id, 'hips_ra': hips_ra, 'hips_dec': hips_dec, 'hips_fov': hips_fov})
    ##

    filename = selected[0]
    entry = next((e for e in user_files[user_id] if e['filename'] == filename), None)
    if not entry:
        flash("❌ file not found")
        return redirect('/')
    fits_path = os.path.join(app.config['UPLOAD_FOLDER'], user_id, filename)
    hips_id = f"{user_id}/{os.path.splitext(filename)[0]}"
    entry['hips_id'] = hips_id
    Thread(target=background_task, args=(hips_id, filename, fits_path, user_id)).start()

    properties_path = os.path.join("hips", hips_id, "properties")
    hips_ra = hips_dec = hips_fov = None
    if os.path.exists(properties_path):
        with open(properties_path) as f:
            for line in f:
                if line.startswith("hips_initial_ra"):
                    hips_ra = float(line.split("=")[1].strip())
                elif line.startswith("hips_initial_dec"):
                    hips_dec = float(line.split("=")[1].strip())
                elif line.startswith("hips_initial_fov"):
                    hips_fov = float(line.split("=")[1].strip())

    print("🆗 ra : " + str(hips_ra))
    print("🆗 dec : " + str(hips_dec))
    print("🆗 fov : " + str(hips_fov))

    return ({'hips_id': hips_id, 'hips_ra': hips_ra, 'hips_dec': hips_dec, 'hips_fov': hips_fov})


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
        flash("❌ unknown user")
        return redirect('/')
    folder = os.path.join(app.config['UPLOAD_FOLDER'], user_id)
    counter = 0
    for e in user_files[user_id]:
        p = os.path.join(folder, e['filename'])
        if os.path.exists(p):
            os.remove(p); counter += 1
    user_files[user_id] = []
    flash(f"✅ {counter} deleted" if counter else "ℹ️ nothing to delete")
    return redirect('/')

@app.route('/hips/<path:filename>')
def serve_hips(filename):
    return send_from_directory('hips', filename)

@app.route("/delete/<filename>", methods=["POST"])
def delete_file(filename):
    user_id = request.cookies.get('userID')
    if not user_id or user_id not in user_files:
        flash("❌ unknown user")
        return redirect('/')
    folder = os.path.join(app.config['UPLOAD_FOLDER'], user_id)
    p = os.path.join(folder, filename)
    if os.path.exists(p):
        os.remove(p)
        user_files[user_id] = [e for e in user_files[user_id] if e['filename'] != filename]
        flash(f"✅ {filename} deleted")
    else:
        flash(f"❌ {filename} not found")
    return redirect('/')
    
@app.route("/display", methods=["GET", "POST"])
def display():
    user_id = request.cookies.get('userID')
    if not user_id:
        flash("❌ unknown user")
        return redirect('/')

    folder = os.path.join("hips", user_id)
    if not os.path.exists(folder):
        flash("❌ no hips found")
        return redirect('/')

    hips_list = [d for d in os.listdir(folder)
                 if os.path.isdir(os.path.join(folder, d))]

    selected_file = None
    if request.method == "POST":
        selected_file = request.form.get("selected_file")
        if selected_file not in hips_list:
            flash(f"❌ {selected_file} not found")
            selected_file = None

    return render_template(
        'display.html', files=hips_list, selected_file=selected_file)

@app.route("/display/<filename>", methods=["POST"])
def display_hips(filename):
    user_id = request.cookies.get('userID')
    if not user_id:
        flash("❌ unknown user")
        return redirect('/')
    folder = os.path.join("hips", user_id)
    if not os.path.exists(folder):
        flash("❌ no hips found")
        return redirect('/')
    hips_list = [d for d in os.listdir(folder)
                 if os.path.isdir(os.path.join(folder, d))]
    if filename not in hips_list:
        flash(f"❌ {filename} not found")
        return redirect('/display')
    
    return render_template('display.html',
                      files=hips_list,
                      selected_file=filename)

@app.errorhandler(413)
def too_large(e):
    flash("file too large : max 5Gb")
    return redirect('/')

if __name__ == "__main__":
    app.run(debug=True)
