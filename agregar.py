import sqlite3

DB_PATH = "auditorio.db"

def agregar_columna_activo():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    # Verificar si la columna ya existe
    cur.execute("PRAGMA table_info(eventos)")
    columnas = [r[1] for r in cur.fetchall()]
    if "activo" in columnas:
        print("✅ La columna 'activo' ya existe.")
    else:
        cur.execute("ALTER TABLE eventos ADD COLUMN activo INTEGER DEFAULT 1")
        con.commit()
        print("✅ Columna 'activo' agregada correctamente.")

    con.close()

if __name__ == "__main__":
    agregar_columna_activo()