"""CLI entry point for evaluation module: python -m evaluation run ..."""
import sys
from evaluation.runner import main

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "run":
        sys.argv.pop(1)
    main()
