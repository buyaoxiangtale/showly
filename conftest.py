import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent
_WEB_DIR = _ROOT / "optional" / "web"
# 仓库重组（web/ → optional/web/）后的导入兼容：
#  1) optional/web 上 sys.path，`import app` 风格的旧测试继续可用；
#  2) `web` 注册为 optional.web 的别名，`import web.app` 风格继续可用。
if str(_WEB_DIR) not in sys.path:
    sys.path.insert(0, str(_WEB_DIR))
try:
    import optional.web as _optional_web  # noqa: F401

    sys.modules.setdefault("web", _optional_web)
except ImportError:  # optional/web 缺失时让旧导入自然报错
    pass


@pytest.fixture(autouse=True)
def isolate_web_outputs(request, tmp_path_factory, monkeypatch):
    if not request.node.path.is_relative_to(Path(__file__).parent / "tests"):
        return
    outputs = tmp_path_factory.mktemp("isolated-web-outputs")
    for name in ("app", "web.app", "optional.web.app"):
        module = sys.modules.get(name)
        if module is not None and hasattr(module, "OUTPUTS_DIR"):
            monkeypatch.setattr(module, "OUTPUTS_DIR", outputs)
