"""
Conexión a la base de datos de RobotinaIA.
"""

import sqlite3

from app.core.settings import Settings


def get_connection():
    return sqlite3.connect(Settings.DATABASE_NAME)