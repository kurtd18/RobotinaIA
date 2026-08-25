import sys
from pathlib import Path

import streamlit as st

# Permite correr este archivo con "streamlit run app/dashboard/dashboard.py"
# sin depender del directorio desde el que se invoque.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from app.services.signal_query_service import listar_senales

st.set_page_config(
    page_title="RobotinaIA",
    page_icon="🤖",
    layout="wide"
)

st.title("🤖 RobotinaIA")
st.subheader("Centro de Control")

df = listar_senales()

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
        width="stretch"
    )