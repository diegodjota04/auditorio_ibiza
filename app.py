from flask import Flask, jsonify, request, Response, render_template
import sqlite3

app = Flask(__name__, static_folder="static", template_folder="templates")
DB_PATH = "auditorio.db"

def db_conn():
    con = sqlite3.connect(DB_PATH, check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/validar")
def validar():
    return render_template("validar.html")

@app.route("/api/seats", methods=["GET"])
def api_seats():
    con = db_conn()
    cur = con.cursor()
    cur.execute("SELECT id,row,num,status FROM seats ORDER BY row,num")
    rows = [dict(r) for r in cur.fetchall()]
    con.close()
    return jsonify(rows)

@app.route("/api/buy", methods=["POST"])
def api_buy():
    data = request.get_json(force=True)
    seats = data.get("seats", [])
    if not seats:
        return jsonify({"ok": False, "msg": "No se recibieron asientos"}), 400

    con = db_conn()
    cur = con.cursor()
    sold, unavailable = [], []
    for sid in seats:
        cur.execute("SELECT status FROM seats WHERE id = ?", (sid,))
        r = cur.fetchone()
        if not r:
            unavailable.append(sid)
            continue
        if r["status"] == "disponible":
            cur.execute("UPDATE seats SET status='vendido' WHERE id=?", (sid,))
            sold.append(sid)
        else:
            unavailable.append(sid)
    con.commit()
    con.close()
    return jsonify({"ok": True, "sold": sold, "unavailable": unavailable})

@app.route("/api/toggle_block", methods=["POST"])
def api_toggle_block():
    data = request.get_json(force=True)
    seat_id = data.get("seat_id")
    con = db_conn()
    cur = con.cursor()
    cur.execute("SELECT status FROM seats WHERE id=?", (seat_id,))
    r = cur.fetchone()
    if not r:
        con.close()
        return jsonify({"ok": False, "msg": "Asiento no existe"}), 404

    current = r["status"]
    if current == "bloqueado":
        cur.execute("UPDATE seats SET status='disponible' WHERE id=?", (seat_id,))
        new_status = "disponible"
    elif current == "disponible":
        cur.execute("UPDATE seats SET status='bloqueado' WHERE id=?", (seat_id,))
        new_status = "bloqueado"
    else:
        con.close()
        return jsonify({"ok": False, "msg": "No se puede bloquear este asiento"}), 400

    con.commit()
    con.close()
    return jsonify({"ok": True, "seat": seat_id, "new_status": new_status})

@app.route("/api/unoccupy", methods=["POST"])
def api_unoccupy():
    data = request.get_json(force=True)
    seat_id = data.get("seat_id")
    con = db_conn()
    cur = con.cursor()
    cur.execute("SELECT status FROM seats WHERE id=?", (seat_id,))
    r = cur.fetchone()
    if not r:
        con.close()
        return jsonify({"ok": False, "msg": "Asiento no existe"}), 404

    if r["status"] != "vendido":
        con.close()
        return jsonify({"ok": False, "msg": "Solo se pueden desocupar asientos vendidos"}), 400

    cur.execute("UPDATE seats SET status='disponible' WHERE id=?", (seat_id,))
    con.commit()
    con.close()
    return jsonify({"ok": True, "seat": seat_id, "new_status": "disponible"})

@app.route("/api/validate", methods=["POST"])
def api_validate():
    data = request.get_json(force=True)
    seat_id = data.get("seat_id")
    con = db_conn()
    cur = con.cursor()
    cur.execute("SELECT status FROM seats WHERE id=?", (seat_id,))
    r = cur.fetchone()
    if not r:
        con.close()
        return jsonify({"ok": False, "msg": "Asiento no existe"}), 404

    if r["status"] != "vendido":
        con.close()
        return jsonify({"ok": False, "msg": "Solo se pueden validar asientos vendidos"}), 400

    cur.execute("UPDATE seats SET status='validado' WHERE id=?", (seat_id,))
    con.commit()
    con.close()
    return jsonify({"ok": True, "seat": seat_id, "new_status": "validado"})

@app.route("/api/report", methods=["GET"])
def api_report():
    con = db_conn()
    cur = con.cursor()
    cur.execute("SELECT status, COUNT(*) AS c FROM seats GROUP BY status")
    counts = {r["status"]: r["c"] for r in cur.fetchall()}

    cur.execute("""
        SELECT row,
               COUNT(*) AS total,
               SUM(status='vendido') AS vendidos,
               SUM(status='validado') AS validados
        FROM seats
        GROUP BY row
        ORDER BY row
    """)
    by_row = [
        {
            "row": r["row"],
            "total": r["total"],
            "vendidos": r["vendidos"] or 0,
            "validados": r["validados"] or 0
        }
        for r in cur.fetchall()
    ]
    con.close()
    return jsonify({"counts": counts, "by_row": by_row})

@app.route("/api/export.csv", methods=["GET"])
def api_export_csv():
    con = db_conn()
    cur = con.cursor()
    cur.execute("SELECT id,row,num,status FROM seats ORDER BY row,num")
    rows = cur.fetchall()
    con.close()
    csv_lines = ["id,row,num,status"]
    for r in rows:
        line = f"{r['id']},{r['row']},{r['num']},{r['status']}"
        csv_lines.append(line)
    csv_data = "\n".join(csv_lines)
    return Response(csv_data, mimetype="text/csv")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)