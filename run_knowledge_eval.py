"""Team experiment: one Full run after reviewing gaps from a normal paired eval."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent/'ai-services'))
from eval_harness.knowledge_followup import main

if __name__ == '__main__':
    main()
