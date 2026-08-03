from app.database import get_connection

conn = get_connection()
conn.execute("UPDATE signals SET signal='EXPIRED' WHERE signal='PENDING'")
conn.commit()
conn.close()
print("Señales viejas marcadas como EXPIRED")