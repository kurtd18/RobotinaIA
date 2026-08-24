"""Tests de app/services/portfolio_service.py."""

from app.database.connection import get_connection
from app.services import portfolio_service
from app.services.fee_config import FlatPercentageFeeConfig


def test_add_position_crypto_sets_normalized_symbol(db_path):
    position_id = portfolio_service.add_position(
        "BTC-USD", 0.01, 50000, asset_class="crypto"
    )

    conn = get_connection()
    row = conn.execute(
        "SELECT symbol, asset_class, normalized_symbol FROM portfolio WHERE id = ?",
        (position_id,),
    ).fetchone()
    conn.close()

    assert row == ("BTC-USD", "crypto", "BTC")


def test_add_position_stock_sets_normalized_symbol_equal_to_symbol(db_path):
    position_id = portfolio_service.add_position(
        "AAPL", 10, 150.0, asset_class="stock"
    )

    conn = get_connection()
    row = conn.execute(
        "SELECT symbol, asset_class, normalized_symbol FROM portfolio WHERE id = ?",
        (position_id,),
    ).fetchone()
    conn.close()

    assert row == ("AAPL", "stock", "AAPL")


def test_get_open_positions_returns_only_open_as_dicts(db_path):
    open_id = portfolio_service.add_position("AAPL", 10, 150.0, asset_class="stock")
    closed_id = portfolio_service.add_position("MSFT", 5, 300.0, asset_class="stock")
    portfolio_service.sell_position(closed_id, 310.0)

    abiertas = portfolio_service.get_open_positions()

    assert len(abiertas) == 1
    assert abiertas[0]["id"] == open_id
    assert abiertas[0]["symbol"] == "AAPL"
    assert abiertas[0]["asset_class"] == "stock"


def test_sell_position_under_default_fee_config_matches_naive_calc_and_fees_included_zero(db_path):
    position_id = portfolio_service.add_position("AAPL", 10, 150.0, asset_class="stock")

    resultado = portfolio_service.sell_position(position_id, 160.0)

    pnl_esperado = (160.0 - 150.0) * 10  # (sell_price - buy_price) * quantity
    assert resultado["pnl"] == pnl_esperado
    assert resultado["fees_included"] == 0

    conn = get_connection()
    fees_included_en_db = conn.execute(
        "SELECT fees_included FROM portfolio WHERE id = ?", (position_id,)
    ).fetchone()[0]
    conn.close()
    assert fees_included_en_db == 0


def test_sell_position_with_configured_fee_config_reports_lower_pnl(db_path, monkeypatch):
    position_id = portfolio_service.add_position("AAPL", 10, 150.0, asset_class="stock")

    fee_config_configurado = FlatPercentageFeeConfig(fee_pct=0.001, configured=True)
    monkeypatch.setitem(portfolio_service._FEE_CONFIGS, "stock", fee_config_configurado)

    resultado = portfolio_service.sell_position(position_id, 160.0)

    pnl_sin_comision = (160.0 - 150.0) * 10
    assert resultado["fees_included"] == 1
    assert resultado["pnl"] < pnl_sin_comision

    conn = get_connection()
    fees_included_en_db = conn.execute(
        "SELECT fees_included FROM portfolio WHERE id = ?", (position_id,)
    ).fetchone()[0]
    conn.close()
    assert fees_included_en_db == 1


def test_sell_position_returns_none_for_unknown_position(db_path):
    resultado = portfolio_service.sell_position(999999, 100.0)
    assert resultado is None


def test_aplicar_trailing_stop_raises_stop_to_old_target_and_target_by_3pct(db_path):
    position_id = portfolio_service.add_position(
        "AAPL", 10, 100.0, asset_class="stock", target_price=110.0, stop_loss=95.0
    )

    stop_loss, target_price = portfolio_service.aplicar_trailing_stop(
        position_id, precio_actual=110.0, stop_loss=95.0, target_price=110.0
    )

    assert stop_loss == 110.0  # el viejo target_price se vuelve el nuevo stop
    assert target_price == 110.0 * 1.03  # +3% exacto

    conn = get_connection()
    row = conn.execute(
        "SELECT stop_loss, target_price FROM portfolio WHERE id = ?", (position_id,)
    ).fetchone()
    conn.close()
    assert row == (stop_loss, target_price)


def test_aplicar_trailing_stop_compounds_across_two_calls(db_path):
    position_id = portfolio_service.add_position(
        "AAPL", 10, 100.0, asset_class="stock", target_price=110.0, stop_loss=95.0
    )

    stop_loss, target_price = portfolio_service.aplicar_trailing_stop(
        position_id, precio_actual=110.0, stop_loss=95.0, target_price=110.0
    )
    primer_target = target_price

    stop_loss, target_price = portfolio_service.aplicar_trailing_stop(
        position_id, precio_actual=target_price, stop_loss=stop_loss, target_price=target_price
    )

    assert stop_loss == primer_target
    assert target_price == primer_target * 1.03


def test_aplicar_trailing_stop_applies_multiple_steps_in_one_call_when_price_jumps(db_path):
    """Si el precio saltó varios niveles de una sola vez, un único
    llamado debe componer todos los escalones que correspondan."""
    position_id = portfolio_service.add_position(
        "AAPL", 10, 100.0, asset_class="stock", target_price=110.0, stop_loss=95.0
    )

    # 115.0 supera el primer objetivo (110.0) y el segundo (113.3), pero
    # no el tercero (116.699) - un único llamado debe componer
    # exactamente 2 escalones, ni 1 ni 3.
    precio_salto = 115.0
    stop_loss, target_price = portfolio_service.aplicar_trailing_stop(
        position_id, precio_actual=precio_salto, stop_loss=95.0, target_price=110.0
    )

    assert stop_loss == 110.0 * 1.03
    assert target_price == 110.0 * 1.03 * 1.03


def test_marcar_alerta_stop_and_registrar_decision_persist(db_path):
    position_id = portfolio_service.add_position("AAPL", 10, 150.0, asset_class="stock")

    portfolio_service.marcar_alerta_stop(position_id, True)
    conn = get_connection()
    alerta = conn.execute(
        "SELECT alerta_stop_enviada FROM portfolio WHERE id = ?", (position_id,)
    ).fetchone()[0]
    conn.close()
    assert alerta == 1

    portfolio_service.registrar_decision(position_id, "MANTENER", 148.0)
    conn = get_connection()
    decision = conn.execute(
        "SELECT decision, precio FROM portfolio_decisions WHERE position_id = ?",
        (position_id,),
    ).fetchone()
    conn.close()
    assert decision == ("MANTENER", 148.0)
