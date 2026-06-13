"""Entry point para Streamlit Community Cloud."""

import sys
from pathlib import Path

# Agregar la raiz del proyecto al path para que los imports funcionen
_PROJECT_ROOT = Path(__file__).resolve().parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.dashboard.app import main

if __name__ == "__main__":
    main()
else:
    # Streamlit Cloud ejecuta el archivo directamente
    main()
