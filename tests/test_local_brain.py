from local_brain import try_local_answer


def test_greeting_is_answered_locally():
    response = try_local_answer("hola", "Jarvis")
    assert response is not None
    assert "jarvis" in response.lower()


def test_simple_math_is_answered_locally():
    response = try_local_answer("cuánto es 2 + 2", "Jarvis")
    assert response is not None
    assert "4" in response


def test_power_operator_is_rejected():
    assert try_local_answer("9 ** 9 ** 9", "Jarvis") is None


def test_unknown_query_returns_none():
    assert try_local_answer("cuéntame sobre la teoría de cuerdas", "Jarvis") is None
