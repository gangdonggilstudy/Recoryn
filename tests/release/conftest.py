"""격리된 release helper import; 실제 사용자 설치·원본 경로를 사용하지 않는다."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "packaging"))
