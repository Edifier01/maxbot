import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_ADAPTER_METHODS = {
    "send_message",
    "join_group",
    "fetch_history",
    "read_message",
    "add_reaction",
}

# S01 covers the client/send/destination boundary. The artificial-presence
# paths are removed by S02 and have their own regression gate there.
SOURCE_REGIONS = {
    ROOT / "main.py": (1157, 1412),
    ROOT / "app" / "campaign_send.py": (230, 364),
    ROOT / "app" / "routes_profiles.py": (122, 215),
}


def test_external_adapter_actions_are_gateway_bound() -> None:
    violations: list[str] = []
    for path, (first_line, last_line) in SOURCE_REGIONS.items():
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr not in FORBIDDEN_ADAPTER_METHODS:
                continue
            if isinstance(node.func.value, ast.Name) and node.func.value.id == "gateway":
                continue
            if first_line <= node.lineno <= last_line:
                violations.append(f"{path.relative_to(ROOT)}:{node.lineno}:{node.func.attr}")

    assert violations == [], "raw MAX adapter calls bypass gateway: " + ", ".join(violations)
