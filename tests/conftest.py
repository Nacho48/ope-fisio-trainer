import sys
from pathlib import Path

# Los módulos del proyecto viven en la carpeta padre y se importan planos.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
