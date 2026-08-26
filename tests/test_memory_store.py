import memory_store as mem


def test_remember_and_recall_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(mem, "MEMORY_PATH", str(tmp_path / "user_memory.json"))

    mem.remember("nombre", "Roger")
    facts = mem.load_facts()

    assert facts["nombre"] == "Roger"
    assert "roger" in mem.as_prompt_context().lower()


def test_forget_removes_fact(tmp_path, monkeypatch):
    monkeypatch.setattr(mem, "MEMORY_PATH", str(tmp_path / "user_memory.json"))

    mem.remember("color favorito", "azul")
    mem.forget("color favorito")

    assert mem.load_facts() == {}


def test_missing_file_returns_empty_dict(tmp_path, monkeypatch):
    monkeypatch.setattr(mem, "MEMORY_PATH", str(tmp_path / "no_existe.json"))
    assert mem.load_facts() == {}
    assert mem.as_prompt_context() == ""
