"""
Persistencia del resultado del CryptoScoringEngine en SQLite.

Usa una tabla propia (crypto_scores), separada de las tablas de la
estrategia de acciones (signals/portfolio/stats), en la misma base de
datos (reutiliza app/database/connection.py sin modificarlo). Pensada
para habilitar paper trading en una fase futura - todavía no se
implementa ninguna operación real ni simulada.
"""

import json
from datetime import datetime, timezone

from app.database.connection import get_connection

SCHEMA_CRYPTO_SCORES = """
CREATE TABLE IF NOT EXISTS crypto_scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    score_fundamental REAL,
    score_tecnico REAL,
    score_derivados REAL,
    score_sentimiento REAL,
    score_macro REAL,
    total_score REAL NOT NULL,
    confidence REAL NOT NULL,
    signal TEXT NOT NULL,
    risk_reward_ratio REAL,
    detalle_json TEXT NOT NULL
)
"""


def crear_tabla():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(SCHEMA_CRYPTO_SCORES)
    conn.commit()
    conn.close()


def _serializar(obj):
    if isinstance(obj, datetime):
        return obj.isoformat()
    return str(obj)


def guardar_resultado(resultado: dict) -> int:
    """Guarda el resultado completo del motor de scoring. `resultado`
    debe incluir symbol, timestamp, score_fundamental, score_tecnico,
    score_derivados, score_sentimiento, score_macro, total_score,
    confidence, signal, risk_reward (dict), y el resto del detalle."""
    crear_tabla()

    conn = get_connection()
    cursor = conn.cursor()

    riesgo = resultado.get("risk_reward") or {}
    ratio = riesgo.get("ratio")

    cursor.execute(
        """
        INSERT INTO crypto_scores (
            symbol, timestamp, score_fundamental, score_tecnico, score_derivados,
            score_sentimiento, score_macro, total_score, confidence, signal,
            risk_reward_ratio, detalle_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            resultado["symbol"],
            resultado["timestamp"].isoformat() if isinstance(resultado["timestamp"], datetime)
            else resultado["timestamp"],
            resultado.get("score_fundamental"),
            resultado.get("score_tecnico"),
            resultado.get("score_derivados"),
            resultado.get("score_sentimiento"),
            resultado.get("score_macro"),
            resultado["total_score"],
            resultado["confidence"],
            resultado["signal"],
            ratio,
            json.dumps(resultado, default=_serializar, ensure_ascii=False),
        ),
    )
    conn.commit()
    id_insertado = cursor.lastrowid
    conn.close()
    return id_insertado


def obtener_ultima_senal(symbol: str) -> dict | None:
    """Devuelve el último resultado guardado para `symbol`, o None si no
    hay ninguno todavía (usado para detectar cambio de señal)."""
    crear_tabla()

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT signal, total_score, confidence, timestamp
        FROM crypto_scores
        WHERE symbol = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (symbol,),
    )
    fila = cursor.fetchone()
    conn.close()

    if fila is None:
        return None

    return {"signal": fila[0], "total_score": fila[1], "confidence": fila[2], "timestamp": fila[3]}
