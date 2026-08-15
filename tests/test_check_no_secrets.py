"""Tests de scripts/check_no_secrets.py."""

from scripts.check_no_secrets import check_env_example_line, main, scan_paths


def test_scan_paths_detects_planted_telegram_token(tmp_path):
    fixture = tmp_path / "leaky_module.py"
    fixture.write_text(
        'TOKEN = "REDACTED"\n'
    )

    findings = scan_paths([str(fixture)])

    assert findings == [(str(fixture), 1)]


def test_scan_paths_clean_fixture_has_no_findings(tmp_path):
    fixture = tmp_path / "clean_module.py"
    fixture.write_text("def suma(a, b):\n    return a + b\n")

    findings = scan_paths([str(fixture)])

    assert findings == []


def test_env_example_placeholder_values_are_clean():
    assert check_env_example_line("TELEGRAM_BOT_TOKEN=your-telegram-bot-token-here") is False
    assert check_env_example_line("GEMINI_API_KEY=") is False
    assert check_env_example_line("# un comentario=algo") is False


def test_env_example_real_value_is_flagged():
    # Un chat id no tiene forma de "secreto" para las regex genéricas,
    # por eso .env.example necesita su propia regla: cualquier valor no
    # vacío y no-placeholder se marca.
    assert check_env_example_line("TELEGRAM_CHAT_ID=1059706281") is True


def test_main_exits_1_and_prints_path_for_planted_fixture(tmp_path, capsys):
    fixture = tmp_path / ".env.example"
    fixture.write_text("TELEGRAM_BOT_TOKEN=REDACTED\n")

    exit_code = main(files=[str(fixture)])

    assert exit_code == 1
    captured = capsys.readouterr()
    assert str(fixture) in captured.out


def test_main_exits_0_against_the_real_repo():
    # Ejercita el mismo camino que "python scripts/check_no_secrets.py"
    # corrido contra el repo real: post E1-T1 no debe quedar nada real.
    exit_code = main()

    assert exit_code == 0
