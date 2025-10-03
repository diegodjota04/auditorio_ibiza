from flask import Flask, render_template, request, jsonify, send_from_directory
from werkzeug.utils import secure_filename
from datetime import datetime
import sqlite3, os

app = Flask(__name__)
app.config["UPLOAD_FOLDER"] = "static/eventos"

def db_conn():
    con = sqlite3.connect("auditorio.db")
    con.row_factory = sqlite3.Row
    return con

# --- Rutas HTML ---
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/validar")
def validar():
    return render_template("validar.html")

@app.route("/admin")
def admin():
    return render_template("admin.html")

# --- API eventos ---
@app.route("/api/eventos", methods=["GET"])
def api_eventos():
    con = db_conn()
    cur = con.cursor()
    cur.execute("SELECT id, nombre, fecha, activo FROM eventos ORDER BY fecha")
    eventos = [dict(r) for r in cur.fetchall()]
    con.close()
    return jsonify(eventos)

@app.route("/api/create_event_with_image", methods=["POST"])
def api_create_event_with_image():
    nombre = request.form.get("nombre")
    fecha = request.form.get("fecha")
    imagen = request.files.get("imagen")

    if not nombre or not fecha or not imagen:
        return jsonify({"ok": False, "msg": "Todos los campos son requeridos"}), 400

    try:
        fecha_obj = datetime.strptime(fecha, "%Y-%m-%d")
    except:
        return jsonify({"ok": False, "msg": "Formato de fecha inválido"}), 400

    con = db_conn()
    cur = con.cursor()
    cur.execute("INSERT INTO eventos (nombre, fecha, activo) VALUES (?, ?, ?)", (nombre, fecha, 1))
    evento_id = cur.lastrowid

    # Estructura Auditorio Ibiza
    for r in "ABCDEFGHIJKLMNOPQ":
        for n in range(1, 17):
            sid = f"{r}{n}"
            cur.execute("INSERT INTO asientos (id, evento_id, row, num, status) VALUES (?, ?, ?, ?, ?)",
                        (sid, evento_id, r, n, "disponible"))
    for r in "RSTU":
        for n in range(1, 14):
            sid = f"{r}{n}"
            cur.execute("INSERT INTO asientos (id, evento_id, row, num, status) VALUES (?, ?, ?, ?, ?)",
                        (sid, evento_id, r, n, "disponible"))

    con.commit()
    con.close()

    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
    filename = secure_filename(f"{evento_id}.jpg")
    imagen.save(os.path.join(app.config["UPLOAD_FOLDER"], filename))

    return jsonify({"ok": True, "evento_id": evento_id})

@app.route("/api/evento/<int:evento_id>", methods=["PUT"])
def api_editar_evento():
    nombre = request.form.get("nombre")
    fecha = request.form.get("fecha")
    activo = request.form.get("activo", 1)
    imagen = request.files.get("imagen")

    if not nombre or not fecha:
        return jsonify({"ok": False, "msg": "Nombre y fecha requeridos"}), 400

    con = db_conn()
    cur = con.cursor()
    cur.execute("UPDATE eventos SET nombre=?, fecha=?, activo=? WHERE id=?", (nombre, fecha, activo, evento_id))
    con.commit()
    con.close()

    if imagen:
        filename = secure_filename(f"{evento_id}.jpg")
        imagen.save(os.path.join(app.config["UPLOAD_FOLDER"], filename))

    return jsonify({"ok": True, "msg": "Evento actualizado"})

@app.route("/api/evento/<int:evento_id>", methods=["DELETE"])
def api_eliminar_evento(evento_id):
    con = db_conn()
    cur = con.cursor()
    cur.execute("DELETE FROM asientos WHERE evento_id=?", (evento_id,))
    cur.execute("DELETE FROM eventos WHERE id=?", (evento_id,))
    con.commit()
    con.close()
    return jsonify({"ok": True, "msg": "Evento eliminado"})

@app.route("/api/evento/reset/<int:evento_id>", methods=["POST"])
def api_reset_evento(evento_id):
    con = db_conn()
    cur = con.cursor()
    cur.execute("UPDATE asientos SET status='disponible' WHERE evento_id=?", (evento_id,))
    con.commit()
    con.close()
    return jsonify({"ok": True, "msg": "Evento reiniciado"})

# --- API asientos ---
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
    vendidos = []
    no_disponibles = []

    con = db_conn()
    cur = con.cursor()
    for sid in seleccionados:
        cur.execute("SELECT status FROM asientos WHERE id=? AND evento_id=?", (sid, evento_id))
        r = cur.fetchone()
        if r and r["status"] == "disponible":
            cur.execute("UPDATE asientos SET status='vendido' WHERE id=? AND evento_id=?", (sid, evento_id))
            vendidos.append(sid)
        else:
            no_disponibles.append(sid)
    con.commit()
    con.close()
    return jsonify({"sold": vendidos, "unavailable": no_disponibles})

@app.route("/api/validate/<int:evento_id>", methods=["POST"])
def api_validate(evento_id):
    data = request.get_json(force=True)
    sid = data.get("seat_id")
    con = db_conn()
    cur = con.cursor()
    cur.execute("SELECT status FROM asientos WHERE id=? AND evento_id=?", (sid, evento_id))
    r = cur.fetchone()
    if not r:
        return jsonify({"ok": False, "msg": "Entrada no encontrada"}), 404
    if r["status"] != "vendido":
        return jsonify({"ok": False, "msg": "Entrada no válida para validar"}), 400
    cur.execute("UPDATE asientos SET status='validado' WHERE id=? AND evento_id=?", (sid, evento_id))
    con.commit()
    con.close()
    return jsonify({"ok": True})

@app.route("/api/report/<int:evento_id>")
def api_report(evento_id):
    con = db_conn()
    cur = con.cursor()
    cur.execute("""
        SELECT status, COUNT(*) as total FROM asientos
        WHERE evento_id=?
        GROUP BY status
    """, (evento_id,))
    counts = {r["status"]: r["total"] for r in cur.fetchall()}

    cur.execute("""
        SELECT row, COUNT(*) as total,
        SUM(CASE WHEN status='vendido' THEN 1 ELSE 0 END) as vendidos,
        SUM(CASE WHEN status='validado' THEN 1 ELSE 0 END) as validados
        FROM asientos WHERE evento_id=?
        GROUP BY row
    """, (evento_id,))
    by_row = [dict(r) for r in cur.fetchall()]
    con.close()
    return jsonify({"counts": counts, "by_row": by_row})

# --- Archivos estáticos ---
@app.route("/static/eventos/<path:filename>")
def evento_image(filename):
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename)

# --- Inicio ---
if __name__ == "__main__":
    app.run(debug=True)