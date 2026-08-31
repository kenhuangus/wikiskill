"""Data model + demo dataset (design.md §2, §8)."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional


@dataclass
class Task:
    """One task instance: paper §2 𝒟 = {(x_i, y_i)}."""
    id: str
    x: str                       # task context shown to the agent
    y: str                       # ground-truth answer
    meta: Dict = field(default_factory=dict)


@dataclass
class ToolSpec:
    """An environment tool 𝒰 (paper §2). fn(**kwargs) -> str observation."""
    name: str
    description: str
    fn: Callable[..., str]

    def schema(self) -> dict:
        return {"name": self.name, "description": self.description}


@dataclass
class Trajectory:
    """Execution trace τ_i = (o1, a1, ..., oT, aT) plus grading metadata."""
    task_id: str
    messages: List[dict]
    tool_calls: List[dict]
    final_answer: Optional[str]
    correct: bool
    prediction: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "messages": self.messages,
            "tool_calls": self.tool_calls,
            "final_answer": self.final_answer,
            "correct": self.correct,
            "prediction": self.prediction,
        }


@dataclass
class Dataset:
    """Train/val/test split (paper §2)."""
    train: List[Task]
    val: List[Task]
    test: List[Task]
    name: str = "demo"


def _demo_tools() -> List[ToolSpec]:
    """Simple calculator tool for the demo environment."""
    def calc(expression: str) -> str:
        try:
            return repr(eval(expression, {"__builtins__": {}}, {}))
        except Exception as e:  # noqa: BLE001 - demo tool
            return f"ERROR: {e}"
    return [ToolSpec("calculator", "Evaluate a Python arithmetic expression.", calc)]


def make_demo_dataset(seed: int = 0) -> Dataset:
    """Synthetic unit-conversion dataset (deterministic).

    Tasks embed `expected=<answer>`; the MockLLM truncates decimals without the
    evolved skill and answers exactly with it — so gating has real signal.
    """
    conversions = [
        ("kilometers to miles", 0.621371, "miles"),
        ("miles to kilometers", 1.609344, "kilometers"),
        ("kilograms to pounds", 2.20462, "pounds"),
        ("pounds to kilograms", 0.453592, "kilograms"),
        ("inches to centimeters", 2.54, "centimeters"),
        ("gallons to liters", 3.78541, "liters"),
    ]
    counts = [3, 2, 2, 2, 1, 1]   # 11 tasks: 5 train / 3 val / 3 test
    tasks: List[Task] = []
    n = 0
    for (name, factor, unit), count in zip(conversions, counts):
        for i in range(count):
            n += 1
            value = round(1.0 + ((n * 7 + seed * 13) % 50) / 3.0, 4)
            answer = round(value * factor, 2)
            x = (f"Convert {value} {name.split(' to ')[0]} to {unit}. "
                 f"The conversion factor is {factor}. "
                 f"Report the numeric value rounded to exactly 2 decimal places. "
                 f"(reference: expected={answer})")
            tasks.append(Task(id=f"task-{n:03d}", x=x, y=f"{answer}", meta={"unit": unit}))
    return Dataset(train=tasks[:5], val=tasks[5:8], test=tasks[8:], name="demo-unitconv")


def load_jsonl(path: str) -> List[dict]:
    out = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out
