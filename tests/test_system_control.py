import system_control as sc


def test_known_app_alias_resolves():
    assert sc.APP_ALIASES["notepad"] == "notepad.exe"
    assert sc.APP_ALIASES["bloc de notas"] == "notepad.exe"


def test_open_unknown_app_returns_helpful_message():
    message = sc.open_app("una_app_que_no_existe_12345")
    assert "no encontré" in message.lower()


def test_get_time_mentions_hora():
    assert "hora" in sc.get_time().lower()
