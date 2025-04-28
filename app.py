from flask import Flask, render_template, request, flash, redirect, url_for, send_from_directory
from werkzeug.utils import secure_filename
import os
import subprocess
import shutil

app = Flask(__name__)
app.secret_key = 'your-secret-key'

HIPS_DIR = os.path.join(os.getcwd(), 'hips')
UPLOAD_FOLDER = 'data/HTTP/F658N'
ALLOWED_EXTENSIONS = {'fits'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024 * 40  # 4 Go

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def generate_fits_index(output_folder):
    command = [
        "java", "-jar", "tools/Hipsgen.jar",
        "in=data/HTTP/F658N",
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
def home():
    return render_template("upload_form.html")

@app.route("/upload", methods=["POST"])
def upload_file():
    if 'file' not in request.files:
        flash("No file part in request")
        return redirect(request.url)

    files = request.files.getlist("file")
    if not files or all(f.filename == '' for f in files):
        flash("No file selected")
        return redirect(request.url)

    success_count = 0
    for file in files:
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            success_count += 1

    if success_count:
        output_dir = "hips/F658N"
        if not generate_fits_index(output_dir):
            flash("❌ error during fits index generation")
        if not generate_fits_tiles(output_dir):
            flash("❌ error during fits tiles generation")
        if not generate_png_tiles(output_dir):
            flash("❌ error during png tiles generation")
        flash("✅ files uploaded and HiPS generated")
    else:
        flash("❌ no valid fits file uploaded")

    return redirect(url_for('home'))

@app.route("/deleteAll", methods=["POST"])
def delete_all():
    folders = ["data/HTTP/F658N", "hips/F658N"]
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
            return redirect(url_for('home'))

    flash("All files deleted and folders reset")
    return redirect(url_for('home'))

@app.route('/hips/<path:filename>')
def serve_hips(filename):
    return send_from_directory('hips', filename)

@app.route("/view/<survey>")
def view_survey(survey):
    properties_path = os.path.join(HIPS_DIR, survey, "properties")
    initial_ra = 0
    initial_dec = 0
    initial_fov = 180

    if os.path.exists(properties_path):
        with open(properties_path) as f:
            for line in f:
                if 'hips_initial_ra' in line:
                    initial_ra = line.split('=')[1].strip()
                elif 'hips_initial_dec' in line:
                    initial_dec = line.split('=')[1].strip()
                elif 'hips_initial_fov' in line:
                    initial_fov = line.split('=')[1].strip()

    return render_template(
        "viewer.html",
        survey=survey,
        initial_ra=initial_ra,
        initial_dec=initial_dec,
        initial_fov=initial_fov
    )

@app.errorhandler(413)
def too_large(e):
    flash("File too large, max 4GB")
    return redirect(request.url)

if __name__ == "__main__":
    app.run(debug=True)
