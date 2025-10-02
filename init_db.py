# init_db.py
import sqlite3, os
import qrcode

DB_PATH = "auditorio.db"
QR_DIR = os.path.join("static", "qr")
os.makedirs(QR_DIR, exist_ok=True)

# Lista de asientos bloqueados según el plano (ejemplo, debes completarla con los reales del PDF)
BLOQUEADOS = ["A5","B3","C1","D3","L8"]

def seat_list():
    seats = []
    for row in "ABCDEFGHIJKLMNOPQ":
        for num in range(1, 17):
            seats.append((f"{row}{num}", row, num))
    for row in "RSTU":
        for num in range(1, 14):
            seats.append((f"{row}{num}", row, num))
    return seats

def init_db():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS seats(
            id TEXT PRIMARY KEY,
            row TEXT NOT NULL,
            num INTEGER NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('disponible','vendido','bloqueado'))
        )
    """)
    for sid, row, num in seat_list():
        status = "bloqueado" if sid in BLOQUEADOS else "disponible"
        cur.execute("INSERT OR IGNORE INTO seats(id,row,num,status) VALUES(?,?,?,?)",
                    (sid, row, num, status))
    con.commit()
    con.close()

def generate_qr():
    for sid, _, _ in seat_list():
        path = os.path.join(QR_DIR, f"{sid}.png")
        if not os.path.exists(path):
            img = qrcode.make(sid)
            img.save(path)
    print("QR generados en static/qr/")

if __name__ == "__main__":
    init_db()
    generate_qr()
    print("DB y QR listos.")