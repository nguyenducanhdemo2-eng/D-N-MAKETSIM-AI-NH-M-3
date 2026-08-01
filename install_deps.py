import subprocess, sys
pkgs = ['scikit-learn', 'aiohttp', 'tqdm']
cmd = [sys.executable, '-m', 'pip', 'install', *pkgs]
print('Running:', ' '.join(cmd))
result = subprocess.run(cmd, capture_output=True, text=True)
print(result.stdout)
print(result.stderr)
raise SystemExit(result.returncode)
