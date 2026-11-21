"""Synthetic subject used only by the test suite (not shipped, not real course content)."""
import json
from pathlib import Path

SAMPLE = {
    "title": "Sample subject",
    "description": "Synthetic data for the automated tests.",
    "cards": [
        {"id": "q-single", "type": "choice", "question": "Question 1?",
         "options": [{"text": "Option A"}, {"text": "Option B"}, {"text": "Option C", "correct": True}, {"text": "Option D"}],
         "explanation": "Explanation 1."},
        {"id": "q-multi", "type": "choice", "question": "Question 2? (select all that apply)",
         "options": [{"text": "Option A", "correct": True}, {"text": "Option B", "correct": True},
                     {"text": "Option C"}, {"text": "Option D", "correct": True}]},
        {"id": "q-open", "type": "open", "question": "Question 3?", "answer": "Model answer 3.",
         "explanation": "Explanation 3."},
        {"id": "q-four", "type": "choice", "question": "Question 4?",
         "options": [{"text": "Option A"}, {"text": "Option B", "correct": True}, {"text": "Option C"}]},
        {"id": "q-open2", "type": "open", "question": "Question 5?", "answer": "Model answer 5."},
        {"id": "q-last", "type": "choice", "question": "Question 6?",
         "options": [{"text": "Option A", "correct": True}, {"text": "Option B"}, {"text": "Option C"}]},
    ],
}


def write(path: Path) -> None:
    Path(path).write_text(json.dumps(SAMPLE, indent=2), encoding="utf-8")
