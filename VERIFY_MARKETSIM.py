"""Quick offline verification for MarketSim AI Final Complete Groq Enhanced."""
from pathlib import Path
import ast, sys
ROOT=Path(__file__).resolve().parent
files=[p for p in ROOT.rglob('*.py') if '__pycache__' not in p.parts]
errors=[]
for p in files:
    try: ast.parse(p.read_text(encoding='utf-8'))
    except Exception as e: errors.append((str(p.relative_to(ROOT)),str(e)))
print(f'Python files checked: {len(files)}')
if errors:
    print('SYNTAX ERRORS:')
    for p,e in errors: print('-',p,e)
    sys.exit(1)
print('Python syntax: OK')
print('Core files:')
for rel in ['frontend/pages/login.html','frontend/index.html','frontend/js/app.js','backend/main.py','database.py','data_preprocessor.py','schema_mapper.py','digital_twin.py','advanced_simulation.py','staged_data_workflow.py']:
    p=ROOT/rel
    print(('OK  ' if p.exists() else 'MISS'),rel)
if not all((ROOT/r).exists() for r in ['frontend/pages/login.html','frontend/index.html','frontend/js/app.js','backend/main.py','database.py','data_preprocessor.py','schema_mapper.py','digital_twin.py','advanced_simulation.py','staged_data_workflow.py']): sys.exit(2)
print('Structure: OK')
