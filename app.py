from flask import (Flask, render_template, request, flash,
                   redirect, send_from_directory, make_response, jsonify)
import os
import time
import uuid
import subprocess
from threading import Lock, Thread
import tempfile
from flask_cors import CORS
from werkzeug.utils import secure_filename
import shutil
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
    """
    Check if the file has a valid extension.

    Args:
        filename (str): Name of the file to check.

    Returns:
        bool: True if the file has a valid extension, False otherwise.
    """
    return (
        '.' in filename and
        filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS
    )


def generate_fits_index(output_folder, fits_file):
    """
    Generate the FITS index for the input file
    and save it in the output folder,
    using a Java command line.

    Args:
        output_folder (str): Path to the output folder.
        fits_file (str): Path to the input FITS file.

    Returns:
        bool: True if the index was generated successfully, False otherwise.
    """
    cmd = [
        "java", "-jar", "tools/Hipsgen.jar",
        f"in={fits_file}",
        f"out={output_folder}",
        "creator_did=test/P/HTTP/F658N",
        "INDEX",
    ]
    print("🆗 running command:", ' '.join(cmd))

    try:
        subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            text=True,
        )
        return True

    except subprocess.CalledProcessError as e:
        print("❌ error generating fits index", e.stderr)
        return False


def get_fits_tiles_cmd(input_folder, output_folder):
    """
    Generate the command to create tiles from a FITS file.

    Args:
        filename (str): Name of the file to check.

    Returns:
        bool: True if the file has a valid extension, False otherwise.
    """
    return [
        "java", "-jar", "tools/Hipsgen.jar",
        f"in={input_folder}",
        f"out={output_folder}",
        "creator_did=test/P/HTTP/F658N",
        "TILES"
    ]


def get_png_tiles_cmd(input_folder, output_folder):
    """
    Generate the command to create png from a FITS file.

    Args:
        filename (str): Name of the file to check.

    Returns:
        bool: True if the file has a valid extension, False otherwise.
    """
    return [
        "java", "-jar", "tools/Hipsgen.jar",
        f"in={input_folder}",
        f"out={output_folder}",
        "creator_did=test/P/HTTP/F658N",
        "pixelCut=0 5 log",
        "PNG"
    ]


def count_tiles_by_extension(root_dir, extension):
    """
    Count the number of files with a specific extension in a directory.

    Args:
        root_dir (str): Path to the root directory.
        extension (str): File extension to count.

    Returns:
        int: Number of files with the specified extension.
    """
    count = 0
    for dirpath, dirnames, filenames in os.walk(root_dir):
        count += sum(1 for f in filenames if f.lower().endswith(extension))
    return count


def generate_tiles_with_progress(command, output_folder,
                                 total_tiles, start_pct,
                                 span_pct, hips_id):
    """
    Generate tiles with progress tracking.

    Args:
        command (list): Command to execute for tile generation.
        output_folder (str): Path to the output folder.
        total_tiles (int): Total number of tiles to generate.
        start_pct (int): Starting percentage for progress.
        span_pct (int): Percentage span for progress.
        hips_id (str): Unique identifier for the HIPS task.
    """
    proc = subprocess.Popen(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
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
    """
    Background task to generate HiPS tiles and PNGs.
    This function runs in a separate thread. It generates the FITS index,
    tiles, and PNGs, and updates the progress in the task queue.

    Args:
        hips_id (str): Unique identifier for the HiPS task.
        filename (str): Name of the input FITS file.
        fits_path (str): Path to the input FITS file.
        user_id (str): Unique identifier for the user.
    """
    with progress_lock:
        task_queue[hips_id] = {"progress": 0, "status": "running"}

    try:
        hips_output_dir = os.path.join("hips", hips_id)
        os.makedirs(hips_output_dir, exist_ok=True)

        if not generate_fits_index(hips_output_dir, fits_path):
            raise Exception("Failed to generate FITS index")

        with progress_lock:
            task_queue[hips_id]["progress"] = 2

        moc_path = os.path.join(hips_output_dir, "HpxFinder", "Moc.fits")
        moc = MOC.load(moc_path)
        order_max = moc.max_order

        total_tiles = sum(
            len(moc.degrade_to_order(o).flatten())
            for o in range(order_max + 1)
        )

        if total_tiles == 0:
            raise Exception("No tiles found")

        cmd_tiles = get_fits_tiles_cmd(fits_path, hips_output_dir)
        generate_tiles_with_progress(
            cmd_tiles,
            hips_output_dir,
            total_tiles,
            start_pct=2,
            span_pct=48,
            hips_id=hips_id,
        )

        cmd_png = get_png_tiles_cmd(fits_path, hips_output_dir)
        generate_tiles_with_progress(
            cmd_png,
            hips_output_dir,
            total_tiles,
            start_pct=50,
            span_pct=49,
            hips_id=hips_id,
        )

        with progress_lock:
            task_queue[hips_id]["progress"] = 100
            task_queue[hips_id]["status"] = "complete"

    except Exception as e:
        with progress_lock:
            task_queue[hips_id]["progress"] = 100
            task_queue[hips_id]["status"] = "error"

        print("❌ Background task failed:", e)


@app.route("/")
def index():
    """
    Render the main page with the upload form and list of uploaded files.
    This function checks if the user has a unique identifier as a cookie.
    If not, it generates a new one and sets it in the cookies.
    It also creates a folder for the user to store uploaded files.
    If the user has already uploaded files, it retrieves them from the folder
    and displays them in the upload form.

    Returns:
        Response:
            Rendered HTML template with the upload form and list of files.
    """
    user_id = request.cookies.get("userID") or str(uuid.uuid4())
    user_folder = os.path.join(app.config["UPLOAD_FOLDER"], user_id)
    os.makedirs(user_folder, exist_ok=True)

    if user_id not in user_files:
        user_files[user_id] = []
        for f in os.listdir(user_folder):
            if f.endswith(".fits"):
                full_path = os.path.join(user_folder, f)
                size_mb = round(os.path.getsize(full_path) / (1024 * 1024), 2)
                user_files[user_id].append({
                    "filename": f,
                    "hips_id": None,
                    "fileweight": size_mb,
                })

    files = user_files[user_id]
    latest = next(
        (f["hips_id"] for f in reversed(files) if f["hips_id"]),
        None,
    )

    resp = make_response(
        render_template(
            "upload_form.html",
            files=files,
            hips_id=latest,
        )
    )
    resp.set_cookie(
        "userID",
        user_id,
        expires=time.time() + 365 * 24 * 3600,  # 1 year
    )
    return resp


@app.route("/upload", methods=["POST"])
def upload_file():
    """
    Handle the file upload from the user.
    This function checks if the user has a unique identifier as a cookie.
    If not, it redirects to the main page.
    It also checks if the uploaded files are valid.
    If they are it saves them in the user's folder.
    If the files are valid, it adds them to the user's file list.
    If no valid files are found, it displays an error message.
    If the user has already uploaded files, it retrieves them from the folder
    and displays them in the upload form.

    Returns:
        Response:
            Redirect to the main page with a success or error message.
    """
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
        file_size_mb = round(os.path.getsize(path) / (1024 * 1024), 2)
        if not any(e['filename'] == name for e in user_files.setdefault(
            user_id, [])
        ):
            user_files[user_id].append({
                "filename": name,
                "hips_id": None,
                "fileweight": file_size_mb,
            })
    return redirect('/')


@app.route("/generate_hips", methods=["POST"])
def generate_hips():
    user_id = request.cookies.get('userID')
    selected = request.form.getlist('selected_files')
    project_name = request.form.get('project_name', '').strip()

    if not user_id or not selected:
        flash("❌ user unknown or no file selected")
        return redirect('/')

    if len(selected) > 1:
        if not project_name:
            flash("❌ name your project")
            return redirect('/')

        files = []
        for all_files in selected:
            files += all_files.split(',')

        temp_dir = tempfile.mkdtemp()
        upload_dir = os.path.join(app.config['UPLOAD_FOLDER'], user_id)
        for name in files:
            src = os.path.join(os.path.abspath(upload_dir), name)
            dst = os.path.join(temp_dir, name)
            os.symlink(src, dst)
            flash(f"✅ {name} linked in temp dir")

        safe_project_name = project_name.replace("/", "_").replace("\\", "_")
        hips_id = f"{user_id}/{safe_project_name}"

        Thread(
            target=background_task,
            args=(hips_id,
                  None,
                  temp_dir,
                  user_id,
                  )).start()

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

        return jsonify({
            'hips_id': hips_id,
            'hips_ra': hips_ra,
            'hips_dec': hips_dec,
            'hips_fov': hips_fov
        })

    # Cas fichier unique
    filename = selected[0]
    entry = next((
        e for e in user_files.get(user_id, []) if e['filename'] == filename),
        None
    )

    if not entry:
        flash("❌ file not found")
        return redirect('/')

    fits_path = os.path.join(app.config["UPLOAD_FOLDER"], user_id, filename)

    base_name = project_name if project_name else os.path.splitext(filename)[0]
    hips_id = f"{user_id}/{base_name}"
    entry["hips_id"] = hips_id

    Thread(
        target=background_task,
        args=(
            hips_id,
            filename,
            fits_path,
            user_id,
        ),
    ).start()

    properties_path = os.path.join(
        "hips",
        hips_id,
        "properties",
    )
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

    return {
        'hips_id': hips_id,
        'hips_ra': hips_ra,
        'hips_dec': hips_dec,
        'hips_fov': hips_fov,
    }


@app.route("/get_progress")
def get_progress():
    """
    Get the progress of the HiPS generation task.

    Checks the progress of the HiPS generation task based on the unique
    identifier (`hips_id`) provided in the request. Returns the current
    progress percentage and status if the task exists.

    Returns:
        Response: A JSON response containing:
            - progress (int): Progress percentage of the HiPS task.
            - status (str): Current status of the HiPS task.
    """
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
    """
    Delete all uploaded FITS files for the current user.

    This function identifies the user by their cookie.
    If the user is known, it deletes all their uploaded files
    from the server and clears their entry from the user_files list.
    A flash message is displayed based on the result.
    """
    user_id = request.cookies.get('userID')
    if not user_id or user_id not in user_files:
        flash("❌ unknown user")
        return redirect('/')

    folder = os.path.join(app.config['UPLOAD_FOLDER'], user_id)
    counter = 0

    for e in user_files[user_id]:
        path = os.path.join(folder, e['filename'])
        if os.path.exists(path):
            os.remove(path)
            counter += 1

    user_files[user_id] = []

    flash(f"✅ {counter} deleted" if counter else "ℹ️ nothing to delete")
    return redirect('/')


@app.route('/hips/<path:filename>')
def serve_hips(filename):
    """
    Serve a HiPS file from the 'hips' directory.

    Args:
        filename (str): Path to the file within the 'hips' directory.

    Returns:
        Response: The requested file as a Flask response.
    """
    return send_from_directory('hips', filename)


@app.route("/delete/<filename>", methods=["POST"])
def delete_file(filename):
    """
    Delete a specific file from the user's uploaded files.

    Args:
        filename (str): Name of the file to delete.

    Returns:
        Response: Redirect to the main page with a success or error message.
    """
    user_id = request.cookies.get('userID')

    if not user_id or user_id not in user_files:
        flash("❌ unknown user")
        return redirect('/')

    folder = os.path.join(app.config['UPLOAD_FOLDER'], user_id)
    path = os.path.join(folder, filename)

    if os.path.exists(path):
        os.remove(path)
        user_files[user_id] = [e for e in user_files[user_id]
                               if e['filename'] != filename]
        flash(f"✅ {filename} deleted")
    else:
        flash(f"❌ {filename} not found")

    return redirect('/')


@app.route("/delete/<user_id>/<hipex_id>", methods=["POST"])
def delete_hips(user_id, hipex_id):
    """
    Delete the entire HiPS folder for the given hipex_id.

    Args:
        user_id (str): ID of the user (from URL, but validated via cookie).
        hipex_id (str): Unique identifier for the HiPS dataset.

    Returns:
        Response: Redirect to the main page with a success or error message.
    """
    cookie_user_id = request.cookies.get('userID')
    if (
        not cookie_user_id
        or cookie_user_id != user_id
        or (user_id not in user_files)
    ):
        flash("❌ unknown or unauthorized user")
        return redirect('/display')
    folder = os.path.join("hips", user_id, hipex_id)
    if os.path.exists(folder):
        shutil.rmtree(folder)
        flash(f"✅ HiPS folder '{hipex_id}' deleted")
    else:
        flash(f"❌ HiPS folder '{hipex_id}' not found")

    return redirect('/display')


@app.route("/display", methods=["GET", "POST"])
def display():
    """
    Display the list of HiPS files for the current user.

    Args:
        request (Request): The incoming request object.
        response (Response): The outgoing response object.

    Returns:
        Response: Rendered HTML template with the list of HiPS files.
    """
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
        'display.html',
        files=hips_list,
        selected_file=selected_file
    )


@app.route("/display/<filename>", methods=["POST"])
def display_hips(filename):
    """
    Display a specific HiPS file for the current user.
    This function checks if the user has a unique identifier as a cookie.
    If not, it redirects to the main page.

    Args:
        filename (str): Name of the HiPS file to display.
        request (Request): The incoming request object.
        response (Response): The outgoing response object.

    Returns:
        Response: Rendered HTML template with the selected HiPS file.
    """
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


@app.route("/infos", methods=["GET"])
def infos():
    """
    Display the information of a specific HiPS file.

    Args:
        fov (float): Field of view of the HiPS file.
        ra (float): Right Ascension of the HiPS file.
        dec (float): Declination of the HiPS file.

    Returns:
        Response: Rendered HTML template with the HiPS file information.
    """
    hips_id = request.args.get('hips_id')
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

    return jsonify({
        'hips_id': hips_id,
        'hips_ra': hips_ra,
        'hips_dec': hips_dec,
        'hips_fov': hips_fov
    })


@app.errorhandler(413)
def too_large(e):
    """
    Handle the 413 error (Request Entity Too Large).

    Args:
        e (Exception): The exception object.

    Returns:
        Response: Redirect to the main page with an error message.
    """
    flash("file too large : max 5Gb")
    return redirect('/')


if __name__ == "__main__":
    app.run(debug=True)
