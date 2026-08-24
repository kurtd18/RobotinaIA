"""Tests de app/services/fee_config.py."""

import pytest

from app.services.fee_config import (
    CRYPTO_FEE_CONFIG,
    STOCK_FEE_CONFIG,
    FlatPercentageFeeConfig,
)


def test_default_stock_fee_config_is_unconfigured_and_passes_gross_pnl_through():
    net_pnl, configured = STOCK_FEE_CONFIG.apply(100.0, 10, 50.0)

    assert net_pnl == 100.0
    assert configured is False


def test_default_crypto_fee_config_is_unconfigured_and_passes_gross_pnl_through():
    net_pnl, configured = CRYPTO_FEE_CONFIG.apply(100.0, 10, 50.0)

    assert net_pnl == 100.0
    assert configured is False


def test_configured_flat_percentage_reduces_pnl_and_reports_configured_true():
    config = FlatPercentageFeeConfig(fee_pct=0.1, configured=True)

    net_pnl, configured = config.apply(100.0, 10, 50.0)

    assert net_pnl < 100.0
    assert configured is True


def test_configured_flat_percentage_computes_the_expected_fee():
    config = FlatPercentageFeeConfig(fee_pct=0.01, configured=True)

    # valor de la operación = 10 * 50.0 = 500.0, comisión = 500.0 * 0.01 = 5.0
    net_pnl, configured = config.apply(100.0, 10, 50.0)

    assert net_pnl == 95.0
    assert configured is True


def test_negative_fee_pct_raises_value_error_at_construction():
    with pytest.raises(ValueError):
        FlatPercentageFeeConfig(fee_pct=-0.01, configured=True)


def test_stock_and_crypto_fee_configs_are_independent_instances():
    assert STOCK_FEE_CONFIG is not CRYPTO_FEE_CONFIG
