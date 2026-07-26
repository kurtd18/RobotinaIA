import sqlite3

DB_NAME = "robotinaia.db"

conn = sqlite3.connect(DB_NAME)

cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS signals (

    id INTEGER PRIMARY KEY AUTOINCREMENT,

    symbol TEXT NOT NULL,

    score INTEGER NOT NULL,

    signal TEXT NOT NULL,

    price REAL NOT NULL,

    timestamp TEXT NOT NULL

)
""")

conn.commit()
conn.close()

print("Base de datos robotinaia.db creada correctamente.")