import ui_server


def test_broadcast_state_without_server_running_does_not_raise():
    ui_server.broadcast_state("idle")


def test_broadcast_transcript_without_server_running_does_not_raise():
    ui_server.broadcast_transcript("user", "hola")


def test_get_text_command_times_out_when_empty():
    assert ui_server.get_text_command(timeout=0.05) is None


def test_text_queue_roundtrip():
    ui_server._text_queue.put("hola rochy")
    assert ui_server.get_text_command(timeout=1.0) == "hola rochy"
