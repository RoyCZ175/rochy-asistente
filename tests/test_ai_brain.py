from dataclasses import dataclass

from ai_brain import TOOLS, AIBrain


@dataclass
class FakeConfig:
    groq_api_key: str = "fake-key-for-tests"
    groq_model: str = "openai/gpt-oss-20b"
    assistant_name: str = "Jarvis"


def test_every_tool_has_a_matching_function():
    brain = AIBrain(FakeConfig())
    tool_names = {tool["function"]["name"] for tool in TOOLS}
    assert tool_names == set(brain.functions.keys())


def test_tools_have_required_schema_fields():
    for tool in TOOLS:
        function = tool["function"]
        assert "name" in function
        assert "description" in function
        assert "parameters" in function
