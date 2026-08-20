from voice_assistant import parse_command, build_response


def test_parse_command_opens_app():
    cmd = parse_command("abre el bloc de notas")
    assert cmd["action"] == "open_app"
    assert "notepad" in cmd["target"]


def test_parse_command_time():
    cmd = parse_command("qué hora es")
    assert cmd["action"] == "time"


def test_build_response_contains_hour():
    text = build_response("qué hora es")
    assert "hora" in text.lower()
