import streamlit as st
import sqlite3
import pandas as pd

DB_NAME = "robotinaia.db"


def cargar_senales():
    conn = sqlite3.connect(DB_NAME)

    try:
        df = pd.read_sql_query(
            """
            SELECT
                id,
                symbol,
                score,
                signal,
                price,
                timestamp
            FROM signals
            ORDER BY id DESC
            """,
            conn
        )

    except Exception:

        df = pd.DataFrame()

    conn.close()

    return df


st.set_page_config(
    page_title="RobotinaIA",
    page_icon="🤖",
    layout="wide"
)

st.title("🤖 RobotinaIA")
st.subheader("Centro de Control")

df = cargar_senales()

col1, col2, col3 = st.columns(3)

col1.metric(
    "Señales",
    len(df)
)

if not df.empty:

    pendientes = len(
        df[df["signal"] == "PENDING"]
    )

else:

    pendientes = 0

col2.metric(
    "Pendientes",
    pendientes
)

col3.metric(
    "Ejecutadas",
    len(df[df["signal"] == "EXECUTED"])
    if not df.empty
    else 0
)

st.divider()

st.subheader("Señales almacenadas")

if df.empty:

    st.warning(
        "No existen señales todavía."
    )

else:

    st.dataframe(
        df,
        use_container_width=True
    )