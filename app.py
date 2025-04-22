from flask import Flask, render_template, request, flash, redirect, url_for
from werkzeug.utils import secure_filename
import os
import subprocess

app = Flask(__name__)
app.secret_key = 'your-secret-key'

UPLOAD_FOLDER = 'data/HTTP/F658N'
ALLOWED_EXTENSIONS = {'fits'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024 * 40  # 4Go MB

# Ensure upload folder exists
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def generate_fits_tiles(output_folder):
    command = [
        "java", "-jar", "tools/Hipsgen.jar",
        "in=data/HTTP/F658N",
        f"out={output_folder}",
        "creator_did=test/P/HTTP/F658N"
    ]
    try:
        result = subprocess.run(command, check=True, capture_output=True, text=True)
        print("✅ fts tiles generated ", result.stdout)
        return True
    except subprocess.CalledProcessError as e:
        print("❌ error generating fits tiles ", e.stderr)
        return False

def generate_png_tiles(output_folder):
    command = [
        "java", "-jar", "tools/Hipsgen.jar",
        "in=data/HTTP/F658N",
        f"out={output_folder}",
        "creator_did=test/P/HTTP/F658N",
        'pixelCut=0 5 log',
        "PNG"
    ]
    try:
        result = subprocess.run(command, check=True, capture_output=True, text=True)
        print("✅ png tiles generated ", result.stdout)
        return True
    except subprocess.CalledProcessError as e:
        print("❌ error generating png tiles ", e.stderr)
        return False

@app.route('/')
def home():
    return render_template('upload_form.html')


@app.route('/index')
def index():
    return render_template('index.html')

@app.route('/properties')
def properties():
    return render_template('properties')

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        flash("no file in the request")
        return redirect(request.url)

    files = request.files.getlist('file')
    if not files or all(f.filename == '' for f in files):
        flash("no file selected")
        return redirect(request.url)

    success_count = 0
    for file in files:
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            success_count += 1

    if success_count:
        if success_count == 1:
            flash("1 file uploaded successfully! :)")
        else:
            flash(f"{success_count} files uploaded successfully! :)")

        output_dir = "hips/F658N"

        if not generate_fits_tiles(output_dir):
            flash("❌error during fits tiles generation")

        if not generate_png_tiles(output_dir):
            flash("❌ error during PNG tiles generation")
    else:
        flash("no valid fits file uploaded")

    return redirect(url_for('home'))

@app.errorhandler(413)
def too_large(e):
    flash("file is too large, max size is 4Go")
    return redirect(request.url)

if __name__ == '__main__':
    app.run(debug=True)
