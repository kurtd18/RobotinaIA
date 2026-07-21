import sqlite3
import yfinance as yf

print("VERSION UPDATE_SIGNALS V2")

conn = sqlite3.connect("signals.db")

cursor = conn.cursor()

cursor.execute("""
SELECT
    id,
    activo,
    precio_entrada
FROM signals
WHERE resultado='PENDIENTE'
""")

senales = cursor.fetchall()

print("=" * 80)
print("ACTUALIZANDO SENALES")
print("=" * 80)

for id_senal, activo, precio_entrada in senales:

    try:

        data = yf.Ticker(activo).history(
            period="5d",
            interval="5m"
        )

        if data.empty:

            print(f"{activo}: SIN DATOS")
            continue

        precio_actual = float(
            data.iloc[-1]["Close"]
        )

        resultado = (
            "GANO"
            if precio_actual > precio_entrada
            else "PERDIO"
        )

        cursor.execute(
            """
            UPDATE signals
            SET
                precio_salida=?,
                resultado=?
            WHERE id=?
            """,
            (
                precio_actual,
                resultado,
                id_senal
            )
        )

        print(
            f"{activo} | "
            f"Entrada={precio_entrada:.2f} | "
            f"Salida={precio_actual:.2f} | "
            f"{resultado}"
        )

    except Exception as e:

        print(f"{activo}: ERROR")
        print(e)

conn.commit()
conn.close()

print("=" * 80)
print("PROCESO FINALIZADO")
print("=" * 80)