"""Public method signatures are what type checkers see."""

from __future__ import annotations

from pathlib import Path

import mypy.api


def test_unknown_keywords_and_missing_arguments_are_type_errors(tmp_path: Path) -> None:
    snippet = tmp_path / "signatures.py"
    snippet.write_text(
        "\n".join(
            [
                "from pajabi import Kajabi",
                "",
                "kajabi = Kajabi(access_token='token')",
                "kajabi.contacts.create(site_id='1', emial='x')",
                "kajabi.contacts.offers.grant('1')",
                "kajabi.forms.submit('1', name='x')",
            ]
        ),
        encoding="utf-8",
    )
    stdout, stderr, code = mypy.api.run(
        [
            "--strict",
            "--python-version",
            "3.10",
            "--cache-dir",
            str(tmp_path / "mypy-cache"),
            "--no-incremental",
            "--no-color-output",
            "--show-error-codes",
            str(snippet),
        ]
    )
    output = stdout + stderr
    assert code != 0, output
    assert 'Unexpected keyword argument "emial"' in output, output
    assert 'Missing positional argument "offer_ids"' in output, output
    assert 'Missing named argument "email" for "submit"' in output, output


def test_valid_contact_create_type_checks(tmp_path: Path) -> None:
    snippet = tmp_path / "valid.py"
    snippet.write_text(
        "\n".join(
            [
                "from pajabi import Kajabi",
                "",
                "kajabi = Kajabi(access_token='token')",
                "kajabi.contacts.create(site_id='1', name='Jane', subscribed=True)",
                "kajabi.forms.submit('1', name='Jane', email='jane@example.com')",
            ]
        ),
        encoding="utf-8",
    )
    stdout, stderr, code = mypy.api.run(
        [
            "--strict",
            "--python-version",
            "3.10",
            "--cache-dir",
            str(tmp_path / "mypy-cache"),
            "--no-incremental",
            "--no-color-output",
            "--show-error-codes",
            str(snippet),
        ]
    )
    assert code == 0, stdout + stderr
