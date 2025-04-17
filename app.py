from flask import Flask, render_template, request, jsonify, make_response, abort, flash, redirect, url_for
from werkzeug.utils import secure_filename
import os

app = Flask(__name__)
app.secret_key = 'your-secret-key'

UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'fits'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024 * 2  # 100 MB

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/')
def home():
    return render_template('upload_form.html')

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        flash("No file part in the request")
        return redirect(request.url)

    files = request.files.getlist('file')
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
        if success_count == 1:
            flash("File uploaded successfully!")
        else:   
            flash(f"{success_count} files uploaded successfully!")
    else:
        flash("No valid .fits file uploaded.")

    return redirect(url_for('home'))

@app.errorhandler(413)
def too_large(e):
    flash("File is too large. Max size is 100MB.")
    return redirect(request.url)

if __name__ == '__main__':
    app.run(debug=True)
