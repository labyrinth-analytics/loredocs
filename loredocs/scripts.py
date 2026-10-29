import sys
from pathlib import Path

def relink_autolinks_main():
    """Console entry point for loredocs-relink-autolinks command."""
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from scripts.relink_autolinks import main
    main()
