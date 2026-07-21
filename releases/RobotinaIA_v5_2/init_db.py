import sqlite3

conn = sqlite3.connect(
    "signals.db"
)

cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS signals(

    id INTEGER PRIMARY KEY AUTOINCREMENT,

    fecha TEXT,
    activo TEXT,

    score INTEGER,

    precio_entrada REAL,

    precio_salida REAL,

    resultado TEXT
)
""")

conn.commit()

conn.close()

print(
    "Base de datos creada."
)