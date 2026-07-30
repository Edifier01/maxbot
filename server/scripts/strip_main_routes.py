from pathlib import Path

lines = Path("main.py").read_text(encoding="utf-8").splitlines()
start_models = next(i for i, l in enumerate(lines) if l.strip().startswith("# --- API models"))
end_models = next(
    i for i, l in enumerate(lines) if l.strip() == "class RateLimitMiddleware(BaseHTTPMiddleware):"
)
start_routes = next(i for i, l in enumerate(lines) if '@app.get("/api/profiles")' in l)
end_routes = next(
    i
    for i, l in enumerate(lines)
    if l.strip().startswith("try:") and "register_server" in lines[i + 1]
)
out = lines[:start_models] + lines[end_models:start_routes] + lines[end_routes:]
Path("main.py").write_text("\n".join(out) + "\n", encoding="utf-8")
print("removed models", end_models - start_models, "routes", end_routes - start_routes)
