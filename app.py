from flask import Flask, render_template, request, jsonify, send_from_directory, send_file, Response, g  # type: ignore
from werkzeug.utils import secure_filename  # type: ignore
from datetime import datetime
from functools import wraps
import sqlite3, os, re, hashlib
import io, zipfile
import qrcode  # type: ignore

app = Flask(__name__)

# ─── Configuración ────────────────────────────────────────────────
app.config["UPLOAD_FOLDER"] = "static/eventos"
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024   # 5 MB máximo por upload
ALLOWED_MIME = {"image/jpeg", "image/png", "image/webp"}
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}

# Credenciales por variables de entorno (fallback de desarrollo)
ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASS = os.environ.get("ADMIN_PASSWORD", "ibiza2026")

# Patrón válido para IDs de asientos: A-U seguido de 1-16
SEAT_RE = re.compile(r"^[A-U]\d{1,2}$")


# ─── Autenticación HTTP Basic ──────────────────────────────────────
def check_auth(username, password):
    return username == "admin" and password == "ibiza2026"


def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not auth or not check_auth(auth.username, auth.password):
            return Response(
                "Acceso restringido. Ingresa tus credenciales de administrador.",
                401,
                {"WWW-Authenticate": 'Basic realm="Auditorio Admin"'},
            )
        return f(*args, **kwargs)
    return decorated


# ─── Base de datos ─────────────────────────────────────────────────
def db_conn():
    con = sqlite3.connect(
        "auditorio.db",
        check_same_thread=False,
        timeout=10,
    )
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")   # mejor concurrencia en lectura/escritura
    return con


def init_db():
    """Crea índice de rendimiento si no existe."""
    con = db_conn()
    con.execute(
        "CREATE INDEX IF NOT EXISTS idx_asientos_evento ON asientos(evento_id)"
    )
    con.commit()
    con.close()


# ─── Cabeceras de seguridad ────────────────────────────────────────
@app.after_request
def add_security_headers(response):
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://unpkg.com; "
        "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
        "img-src 'self' data:; "
        "connect-src 'self';"
    )
    return response


# ─── Manejo global de errores ──────────────────────────────────────
@app.errorhandler(404)
def not_found(e):
    if request.path.startswith("/api/"):
        return jsonify({"ok": False, "msg": "Recurso no encontrado"}), 404
    return render_template("index.html"), 404


@app.errorhandler(413)
def too_large(e):
    return jsonify({"ok": False, "msg": "El archivo supera el límite de 5 MB"}), 413


@app.errorhandler(500)
def server_error(e):
    if request.path.startswith("/api/"):
        return jsonify({"ok": False, "msg": "Error interno del servidor"}), 500
    return "Error interno del servidor", 500


# ─── Validaciones de archivo ───────────────────────────────────────
def allowed_image(file):
    if not file or not file.filename:
        return False
    ext = os.path.splitext(file.filename)[1].lower()
    mime = file.mimetype or ""
    return ext in ALLOWED_EXTENSIONS and mime in ALLOWED_MIME


# ─── Rutas HTML ───────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/validar")
@require_auth
def validar():
    return render_template("validar.html")


@app.route("/admin")
@require_auth
def admin():
    return render_template("admin.html")


# ─── API eventos ──────────────────────────────────────────────────
@app.route("/api/eventos", methods=["GET"])
def api_eventos():
    con = db_conn()
    cur = con.cursor()
    cur.execute("SELECT id, nombre, fecha, activo FROM eventos ORDER BY fecha")
    eventos = [dict(r) for r in cur.fetchall()]
    con.close()
    return jsonify(eventos)


@app.route("/api/create_event_with_image", methods=["POST"])
@require_auth
def api_create_event_with_image():
    nombre = request.form.get("nombre", "").strip()
    fecha  = request.form.get("fecha", "").strip()
    imagen = request.files.get("imagen")

    if not nombre or not fecha or not imagen:
        return jsonify({"ok": False, "msg": "Todos los campos son requeridos"}), 400

    if not allowed_image(imagen):
        return jsonify({"ok": False, "msg": "Imagen inválida. Usa JPG, PNG o WebP (máx. 5 MB)"}), 400

    try:
        datetime.strptime(fecha, "%Y-%m-%d")
    except ValueError:
        return jsonify({"ok": False, "msg": "Formato de fecha inválido"}), 400

    con = db_conn()
    cur = con.cursor()
    try:
        cur.execute(
            "INSERT INTO eventos (nombre, fecha, activo) VALUES (?, ?, ?)",
            (nombre, fecha, 1),
        )
        evento_id = cur.lastrowid

        # Estructura Auditorio Ibiza
        asientos = []
        for r in "ABCDEFGHIJKLMNOPQ":
            for n in range(1, 17):
                asientos.append((f"{r}{n}", evento_id, r, n, "disponible"))
        for r in "RSTU":
            for n in range(1, 14):
                asientos.append((f"{r}{n}", evento_id, r, n, "disponible"))

        cur.executemany(
            "INSERT INTO asientos (id, evento_id, row, num, status) VALUES (?, ?, ?, ?, ?)",
            asientos,
        )
        con.commit()
    except Exception as e:
        con.rollback()
        con.close()
        return jsonify({"ok": False, "msg": f"Error al crear el evento: {str(e)}"}), 500

    con.close()

    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
    ext = os.path.splitext(secure_filename(imagen.filename))[1].lower() or ".jpg"
    imagen.save(os.path.join(app.config["UPLOAD_FOLDER"], f"{evento_id}.jpg"))

    return jsonify({"ok": True, "evento_id": evento_id})


# ─── BUG FIX: ruta estaba indentada dentro de api_create_event_with_image ───
@app.route("/api/evento/<int:evento_id>", methods=["PUT"])
@require_auth
def api_editar_evento(evento_id):
    nombre = request.form.get("nombre", "").strip()
    fecha  = request.form.get("fecha", "").strip()
    activo = request.form.get("activo", 1)
    imagen = request.files.get("imagen")

    if not nombre or not fecha:
        return jsonify({"ok": False, "msg": "Nombre y fecha requeridos"}), 400

    try:
        activo = int(activo)
    except (ValueError, TypeError):
        activo = 1

    con = db_conn()
    cur = con.cursor()
    cur.execute(
        "UPDATE eventos SET nombre=?, fecha=?, activo=? WHERE id=?",
        (nombre, fecha, activo, evento_id),
    )
    con.commit()
    con.close()

    if imagen:
        if not allowed_image(imagen):
            return jsonify({"ok": False, "msg": "Imagen inválida. Usa JPG, PNG o WebP (máx. 5 MB)"}), 400
        # make sure folder still exists (it should from create route, but safe to call again)
        os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
        # overwrite previous image (always save as .jpg to keep URL consistent)
        imagen.save(os.path.join(app.config["UPLOAD_FOLDER"], f"{evento_id}.jpg"))

    return jsonify({"ok": True, "msg": "Evento actualizado"})


@app.route("/api/evento/<int:evento_id>", methods=["DELETE"])
@require_auth
def api_eliminar_evento(evento_id):
    con = db_conn()
    cur = con.cursor()
    cur.execute("DELETE FROM asientos WHERE evento_id=?", (evento_id,))
    cur.execute("DELETE FROM eventos WHERE id=?", (evento_id,))
    con.commit()
    con.close()
    return jsonify({"ok": True, "msg": "Evento eliminado"})


@app.route("/api/evento/reset/<int:evento_id>", methods=["POST"])
@require_auth
def api_reset_evento(evento_id):
    con = db_conn()
    cur = con.cursor()
    cur.execute("UPDATE asientos SET status='disponible' WHERE evento_id=?", (evento_id,))
    con.commit()
    con.close()
    return jsonify({"ok": True, "msg": "Evento reiniciado"})


# ─── API asientos ─────────────────────────────────────────────────
@app.route("/api/seats/<int:evento_id>")
def api_seats(evento_id):
    con = db_conn()
    cur = con.cursor()
    cur.execute("SELECT id, status FROM asientos WHERE evento_id=?", (evento_id,))
    seats = [dict(r) for r in cur.fetchall()]
    con.close()
    return jsonify(seats)


@app.route("/api/buy/<int:evento_id>", methods=["POST"])
def api_buy(evento_id):
    data = request.get_json(force=True)
    seleccionados = data.get("seats", [])

    if not seleccionados or not isinstance(seleccionados, list):
        return jsonify({"ok": False, "msg": "Lista de asientos inválida"}), 400

    # Validar formato de cada seat_id
    seleccionados = [s for s in seleccionados if isinstance(s, str) and SEAT_RE.match(s)]
    if not seleccionados:
        return jsonify({"ok": False, "msg": "IDs de asiento inválidos"}), 400

    # Limitar a 10 por transacción
    seleccionados = seleccionados[:10]  # type: ignore

    vendidos = []
    no_disponibles = []

    con = db_conn()
    cur = con.cursor()
    try:
        con.execute("BEGIN EXCLUSIVE")
        for sid in seleccionados:
            cur.execute(
                "SELECT status FROM asientos WHERE id=? AND evento_id=?",
                (sid, evento_id),
            )
            r = cur.fetchone()
            if r and r["status"] == "disponible":
                cur.execute(
                    "UPDATE asientos SET status='vendido' WHERE id=? AND evento_id=?",
                    (sid, evento_id),
                )
                vendidos.append(sid)
            else:
                no_disponibles.append(sid)
        con.commit()
    except Exception as e:
        con.rollback()
        con.close()
        return jsonify({"ok": False, "msg": f"Error al procesar la compra: {str(e)}"}), 500

    con.close()
    return jsonify({"sold": vendidos, "unavailable": no_disponibles})


@app.route("/api/release/<int:evento_id>", methods=["POST"])
@require_auth
def api_release(evento_id):
    data = request.get_json(force=True)
    seleccionados = data.get("seats", [])

    if not seleccionados or not isinstance(seleccionados, list):
        return jsonify({"ok": False, "msg": "Lista de asientos inválida"}), 400

    seleccionados = [s for s in seleccionados if isinstance(s, str) and SEAT_RE.match(s)]
    if not seleccionados:
        return jsonify({"ok": False, "msg": "IDs de asiento inválidos"}), 400

    seleccionados = seleccionados[:10]  # type: ignore
    released = []
    failed = []

    con = db_conn()
    cur = con.cursor()
    try:
        con.execute("BEGIN EXCLUSIVE")
        for sid in seleccionados:
            cur.execute(
                "SELECT status FROM asientos WHERE id=? AND evento_id=?",
                (sid, evento_id),
            )
            r = cur.fetchone()
            if r and r["status"] == "vendido":
                cur.execute(
                    "UPDATE asientos SET status='disponible' WHERE id=? AND evento_id=?",
                    (sid, evento_id),
                )
                released.append(sid)
            else:
                failed.append(sid)
        con.commit()
    except Exception as e:
        con.rollback()
        con.close()
        return jsonify({"ok": False, "msg": f"Error procesando liberación: {e}"}), 500
    con.close()
    return jsonify({"released": released, "failed": failed})


@app.route("/api/validate/<int:evento_id>", methods=["POST"])
@require_auth
def api_validate(evento_id):
    data = request.get_json(force=True)
    sid = (data.get("seat_id") or "").strip().upper()

    if not SEAT_RE.match(sid):
        return jsonify({"ok": False, "msg": "ID de asiento inválido"}), 400

    con = db_conn()
    cur = con.cursor()
    cur.execute(
        "SELECT status FROM asientos WHERE id=? AND evento_id=?",
        (sid, evento_id),
    )
    r = cur.fetchone()
    if not r:
        con.close()
        return jsonify({"ok": False, "msg": "Entrada no encontrada"}), 404
    if r["status"] != "vendido":
        con.close()
        return jsonify({"ok": False, "msg": "Entrada no válida para validar"}), 400
    cur.execute(
        "UPDATE asientos SET status='validado' WHERE id=? AND evento_id=?",
        (sid, evento_id),
    )
    con.commit()
    con.close()
    return jsonify({"ok": True})


# --- API para generar QR en ZIP -----------------------------------
@app.route("/api/qrs/<int:evento_id>")
@require_auth
def api_qrs(evento_id):
    """Genera un ZIP con un PNG de QR por cada asiento del evento."""
    con = db_conn()
    cur = con.cursor()
    cur.execute(
        "SELECT id FROM asientos WHERE evento_id=? ORDER BY row, num",
        (evento_id,),
    )
    seats = [r["id"] for r in cur.fetchall()]
    con.close()

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for sid in seats:
            img = qrcode.make(sid)
            img_byte = io.BytesIO()
            img.save(img_byte, format="PNG")
            img_byte.seek(0)
            zf.writestr(f"{sid}.png", img_byte.read())
    buf.seek(0)
    return send_file(
        buf,
        as_attachment=True,
        download_name=f"qr_evento_{evento_id}.zip",
        mimetype="application/zip",
    )

@app.route("/api/report/<int:evento_id>")
@require_auth
def api_report(evento_id):
    con = db_conn()
    cur = con.cursor()
    cur.execute(
        """
        SELECT status, COUNT(*) as total FROM asientos
        WHERE evento_id=?
        GROUP BY status
        """,
        (evento_id,),
    )
    counts = {r["status"]: r["total"] for r in cur.fetchall()}

    cur.execute(
        """
        SELECT row, COUNT(*) as total,
               SUM(CASE WHEN status='vendido'  THEN 1 ELSE 0 END) as vendidos,
               SUM(CASE WHEN status='validado' THEN 1 ELSE 0 END) as validados
        FROM asientos WHERE evento_id=?
        GROUP BY row
        """,
        (evento_id,),
    )
    by_row = [dict(r) for r in cur.fetchall()]
    con.close()
    return jsonify({"counts": counts, "by_row": by_row})


@app.route("/evento/<int:evento_id>")
def vista_evento(evento_id):
    con = db_conn()
    cur = con.cursor()
    cur.execute(
        "SELECT nombre, fecha FROM eventos WHERE id=? AND activo=1", (evento_id,)
    )
    evento = cur.fetchone()
    con.close()

    if not evento:
        return "Evento no encontrado o inactivo", 404

    return render_template(
        "evento.html",
        evento_id=evento_id,
        nombre=evento["nombre"],
        fecha=evento["fecha"],
    )


# ─── Archivos estáticos con cache ──────────────────────────────────
@app.route("/static/eventos/<path:filename>")
def evento_image(filename):
    response = send_from_directory(app.config["UPLOAD_FOLDER"], filename)
    response.headers["Cache-Control"] = "public, max-age=86400"
    return response


# ─── Inicio ───────────────────────────────────────────────────────
if __name__ == "__main__":
    init_db()
    
    # Generar certificado permanentemente para que no tarde en iniciar
    if not os.path.exists('cert.crt') or not os.path.exists('cert.key'):
        print("Generando certificados SSL temporales por única vez...")
        from werkzeug.serving import make_ssl_devcert
        make_ssl_devcert('cert', host='192.168.20.32')
        
    app.run(debug=True, host='0.0.0.0', ssl_context=('cert.crt', 'cert.key'))