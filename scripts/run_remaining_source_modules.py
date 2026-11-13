"""Continue independent authored modules; the agent inspects failures afterwards."""
import subprocess,sys,argparse
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser();parser.add_argument('--modules',nargs='+',default=['02','03','05']);args=parser.parse_args()
for module in args.modules:
 result=subprocess.run([sys.executable,str(ROOT/'scripts/run_source_module.py'),'--module',module,'--language','ja-JP','--reuse-build'],cwd=ROOT)
 subprocess.run([sys.executable,str(ROOT/'scripts/summarize_source_suite.py')],cwd=ROOT)
 if result.returncode:raise SystemExit(result.returncode)
