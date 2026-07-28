"""
Script de inicialización de la base de datos de RobotinaIA.
Uso: python init_db.py
"""

from loguru import logger

from app.database.schema import create_tables


def init_db():
    """Crea las tablas necesarias si no existen."""

    create_tables()
    logger.info("Base de datos robotinaia.db creada/verificada correctamente.")


if __name__ == "__main__":
    init_db()