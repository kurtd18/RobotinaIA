"""Test de integración de punta a punta de revisar_alertas_portafolio()
(Épica 8, E8-T2): confirma que la migración de portfolio.py a
portfolio_service.py en app/alerts/portfolio_alerts.py no rompió el
ciclo completo - ningún test anterior ejercitaba esta función."""

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from app.alerts import portfolio_alerts
from app.database.connection import get_connection
from app.services import portfolio_service


def _df_con_precio(precio: float) -> pd.DataFrame:
    idx = pd.date_range("2026-01-01", periods=1, freq="5min", tz="UTC")
    return pd.DataFrame(
        {"Open": [precio], "High": [precio], "Low": [precio], "Close": [precio], "Volume": [1.0]},
        index=idx,
    )


def test_revisar_alertas_portafolio_reads_dict_shaped_positions_end_to_end(db_path, monkeypatch):
    position_id = portfolio_service.add_position(
        "AAPL", 10, 100.0, asset_class="stock", target_price=110.0, stop_loss=90.0
    )

    mock_enviar = MagicMock(return_value=200)
    monkeypatch.setattr(portfolio_alerts, "enviar_mensaje_telegram", mock_enviar)

    with patch("app.alerts.portfolio_alerts.yf.Ticker") as mock_ticker_cls:
        mock_ticker_cls.return_value.history.return_value = _df_con_precio(105.0)

        portfolio_alerts.revisar_alertas_portafolio()

    # No cruzó target ni stop - solo el aviso de crecimiento debió enviarse.
    assert mock_enviar.call_count == 1
    assert "ESTADO DE POSICIÓN" in mock_enviar.call_args.args[0]

    # La posición sigue abierta, sin cambios de stop/target.
    conn = get_connection()
    row = conn.execute(
        "SELECT status, stop_loss, target_price FROM portfolio WHERE id = ?", (position_id,)
    ).fetchone()
    conn.close()
    assert row == ("OPEN", 90.0, 110.0)


def test_revisar_alertas_portafolio_applies_trailing_stop_via_portfolio_service(
    db_path, monkeypatch
):
    position_id = portfolio_service.add_position(
        "AAPL", 10, 100.0, asset_class="stock", target_price=110.0, stop_loss=90.0
    )

    monkeypatch.setattr(portfolio_alerts, "enviar_mensaje_telegram", MagicMock(return_value=200))

    with patch("app.alerts.portfolio_alerts.yf.Ticker") as mock_ticker_cls:
        mock_ticker_cls.return_value.history.return_value = _df_con_precio(112.0)  # supera el target (110), no el siguiente (113.3)

        portfolio_alerts.revisar_alertas_portafolio()

    conn = get_connection()
    row = conn.execute(
        "SELECT stop_loss, target_price FROM portfolio WHERE id = ?", (position_id,)
    ).fetchone()
    conn.close()

    assert row == (110.0, 110.0 * 1.03)  # el trailing se persistió vía portfolio_service


def test_revisar_alertas_portafolio_isolates_failure_per_symbol(db_path, monkeypatch):
    """Un símbolo sin datos no debe tumbar la revisión del resto del
    portafolio - ya era así antes de la migración, se confirma que
    sigue siéndolo."""
    portfolio_service.add_position("ROTO", 10, 100.0, asset_class="stock")
    portfolio_service.add_position("OK", 10, 100.0, asset_class="stock")

    mock_enviar = MagicMock(return_value=200)
    monkeypatch.setattr(portfolio_alerts, "enviar_mensaje_telegram", mock_enviar)

    def fake_history(*args, **kwargs):
        raise RuntimeError("símbolo roto")

    llamados = []

    def fake_ticker(symbol):
        llamados.append(symbol)
        mock = MagicMock()
        if symbol == "ROTO":
            mock.history.side_effect = fake_history
        else:
            mock.history.return_value = _df_con_precio(100.0)
        return mock

    with patch("app.alerts.portfolio_alerts.yf.Ticker", side_effect=fake_ticker):
        portfolio_alerts.revisar_alertas_portafolio()

    assert llamados == ["ROTO", "OK"]  # se procesó ROTO, falló, y siguió con OK
    assert mock_enviar.call_count == 1  # solo OK generó su aviso de crecimiento
