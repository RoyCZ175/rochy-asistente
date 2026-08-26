from code_generator import _safe_name, _strip_code_fence


def test_safe_name_sanitizes_path_characters():
    assert _safe_name("../../etc/passwd") == "______etc_passwd"
    assert _safe_name("Mi Página Web!!") == "mi_p_gina_web__"


def test_safe_name_defaults_when_empty():
    assert _safe_name("   ") == "proyecto"


def test_strip_code_fence_removes_markdown_wrapper():
    wrapped = "```html\n<h1>Hola</h1>\n```"
    assert _strip_code_fence(wrapped) == "<h1>Hola</h1>"


def test_strip_code_fence_leaves_plain_code_untouched():
    plain = "<h1>Hola</h1>"
    assert _strip_code_fence(plain) == plain
