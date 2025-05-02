from flask import Flask, render_template, request, flash, redirect, url_for, send_from_directory, make_response
from werkzeug.utils import secure_filename
import os
import subprocess
import shutil
import uuid
from flask_cors import CORS

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

    resp = make_response(render_template('upload_form.html', files=files))
    resp.set_cookie('userID', user_id)

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
def hips(filename):
    return send_from_directory('hips', filename)

@app.route("/view/<hips_id>")
def show_hips(hips_id):
    return render_template( "/", hips_id=hips_id)
    
@app.route("/myfiles")
def myfiles():
    user_id = request.cookies.get('userID')
    if not user_id or user_id not in user_files:
        return "nof files found for this user"

    return render_template("/", files=user_files[user_id])

@app.route("/generate_hips", methods=["POST"])
def generate_hips():
    user_id = request.cookies.get('userID')
    if not user_id or user_id not in user_files:
        flash("❌ unknown user")
        return redirect('/')

    selected_files = request.form.getlist('selected_files')
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

        hips_id = f"{uuid.uuid4()}_{filename.rsplit('.', 1)[0]}"
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

    return render_template("upload_form.html", hips_id=hips_id)

@app.route("/deleteAll", methods=["POST"])
def delete_all():
    folders = ["data/HTTP/F658N/", "hips/"]
    for folder in folders:
        try:
            if os.path.exists(folder):
                shutil.rmtree(folder)
                print(f"Deleted {folder}")
            os.makedirs(folder, exist_ok=True)
            print(f"Recreated {folder}")
        except Exception as e:
            print(f"Error handling {folder}: {e}")
            flash(f"Error deleting {folder}: {e}")
            return redirect('/')
    flash("all files deleted and folders reset")
    return redirect('/')

@app.errorhandler(413)
def too_large(e):
    flash("File too large, max 4GB")
    return redirect('/')

if __name__ == "__main__":
    app.run(debug=True)
