from flask import Flask, jsonify, request, Response, render_template
import sqlite3

app = Flask(__name__, static_folder="static", template_folder="templates")
DB_PATH = "auditorio.db"

def db_conn():
    con = sqlite3.connect(DB_PATH, timeout=5, check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/validar")
def validar():
    return render_template("validar.html")

@app.route("/api/eventos", methods=["GET"])
def api_eventos():
    con = db_conn()
    cur = con.cursor()
    cur.execute("SELECT id, nombre, fecha FROM eventos ORDER BY fecha DESC")
    eventos = [dict(r) for r in cur.fetchall()]
    con.close()
    return jsonify(eventos)

@app.route("/api/seats/<int:evento_id>", methods=["GET"])
def api_seats(evento_id):
    con = db_conn()
    cur = con.cursor()
    cur.execute("SELECT id,row,num,status FROM asientos WHERE evento_id=? ORDER BY row,num", (evento_id,))
    rows = [dict(r) for r in cur.fetchall()]
    con.close()
    return jsonify(rows)

@app.route("/api/buy/<int:evento_id>", methods=["POST"])
def api_buy(evento_id):
    data = request.get_json(force=True)
    seats = data.get("seats", [])
    con = db_conn()
    cur = con.cursor()
    sold, unavailable = [], []
    for sid in seats:
        cur.execute("SELECT status FROM asientos WHERE id=? AND evento_id=?", (sid, evento_id))
        r = cur.fetchone()
        if not r:
            unavailable.append(sid)
            continue
        if r["status"] == "disponible":
            cur.execute("UPDATE asientos SET status='vendido' WHERE id=? AND evento_id=?", (sid, evento_id))
            sold.append(sid)
        else:
            unavailable.append(sid)
    con.commit()
    con.close()
    return jsonify({"ok": True, "sold": sold, "unavailable": unavailable})

@app.route("/api/validate/<int:evento_id>", methods=["POST"])
def api_validate(evento_id):
    try:
        data = request.get_json(force=True)
        seat_id = data.get("seat_id")
        con = db_conn()
        cur = con.cursor()
        cur.execute("SELECT status FROM asientos WHERE id=? AND evento_id=?", (seat_id, evento_id))
        r = cur.fetchone()
        if not r:
            con.close()
            return jsonify({"ok": False, "msg": "Asiento no existe"}), 404
        if r["status"] != "vendido":
            con.close()
            return jsonify({"ok": False, "msg": "Solo se pueden validar asientos vendidos"}), 400
        cur.execute("UPDATE asientos SET status='validado' WHERE id=? AND evento_id=?", (seat_id, evento_id))
        con.commit()
        con.close()
        return jsonify({"ok": True, "seat": seat_id})
    except Exception as e:
        return jsonify({"ok": False, "msg": f"Error: {str(e)}"}), 500

@app.route("/api/report/<int:evento_id>", methods=["GET"])
def api_report(evento_id):
    con = db_conn()
    cur = con.cursor()
    cur.execute("SELECT status, COUNT(*) AS c FROM asientos WHERE evento_id=? GROUP BY status", (evento_id,))
    counts = {r["status"]: r["c"] for r in cur.fetchall()}
    cur.execute("""
        SELECT row,
               COUNT(*) AS total,
               SUM(status='vendido') AS vendidos,
               SUM(status='validado') AS validados
        FROM asientos
        WHERE evento_id=?
        GROUP BY row
        ORDER BY row
    """, (evento_id,))
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

@app.route("/api/reset/<int:evento_id>", methods=["POST"])
def api_reset(evento_id):
    con = db_conn()
    cur = con.cursor()
    cur.execute("UPDATE asientos SET status='disponible' WHERE evento_id=?", (evento_id,))
    con.commit()
    con.close()
    return jsonify({"ok": True, "msg": "Auditorio reiniciado"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)