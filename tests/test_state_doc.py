"""设计文档第 4 节的 State Schema 必须与 app/agents/state.py 逐字段一致。"""

import re
from pathlib import Path

import pytest

from app.agents import state as state_module

DOC = Path(__file__).resolve().parents[1] / "docs" / "week-2-design.md"


def doc_models():
    """解析文档中的 `class X(BaseModel):` 代码块，返回 {类名: [字段名, ...]}。"""
    models, current = {}, None
    for line in DOC.read_text(encoding="utf-8").splitlines():
        m = re.match(r"class (\w+)\(BaseModel\):", line)
        if m:
            current = models.setdefault(m.group(1), [])
            continue
        if current is not None:
            f = re.match(r"\s{4}(\w+):", line)
            if f:
                current.append(f.group(1))
            elif not line.startswith(" "):
                current = None
    return models


MODELS = doc_models()


def test_doc_declares_all_state_models():
    assert set(MODELS) == {"Research", "Citation", "Script", "TourState"}


@pytest.mark.parametrize("name", sorted(MODELS))
def test_fields_match_code(name):
    assert MODELS[name] == list(getattr(state_module, name).model_fields)
