import ast, pathlib
src = pathlib.Path("src/app_legacy.py").read_text(encoding="utf-8")
for n in ast.parse(src).body:
    if isinstance(n, ast.FunctionDef) and n.name == "extrair_id_controle_ap":
        print(f"===== linhas {n.lineno}-{n.end_lineno} =====")
        print("\n".join(src.splitlines()[n.lineno-1:n.end_lineno]))
        print("\ndeps internas:", [x.id for x in ast.walk(n)
              if isinstance(x, ast.Name) and isinstance(x.ctx, ast.Load)][:20])
