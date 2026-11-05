"""Draft answers to open questions with a local model (Ollama) on the
owner's own machine, for example the Qwen model on the Dell desktop.

The address is the owner's own setting and usually a private network
address, so this deliberately doesn't go through the discovery SSRF guard
(which refuses private addresses). It only ever calls the one configured
address, with a fixed path, and never follows redirects."""

from dataclasses import dataclass
from typing import Protocol

import httpx

LLM_TIMEOUT = 180.0
MAX_ANSWER_CHARS = 4000


class LocalModelError(Exception):
    """One-line, user-safe reason the local model couldn't answer."""


class LocalModel(Protocol):
    def generate(self, prompt: str) -> str: ...


@dataclass
class OllamaModel:
    url: str
    model: str
    transport: httpx.BaseTransport | None = None

    def generate(self, prompt: str) -> str:
        try:
            with httpx.Client(timeout=LLM_TIMEOUT, follow_redirects=False, transport=self.transport) as client:
                response = client.post(
                    f"{self.url}/api/generate",
                    json={"model": self.model, "prompt": prompt, "stream": False, "options": {"temperature": 0.4}},
                )
        except httpx.TimeoutException:
            raise LocalModelError("the local model took too long to answer") from None
        except httpx.HTTPError as exc:
            raise LocalModelError(f"couldn't reach the local model ({type(exc).__name__})") from None
        if response.status_code == 404:
            raise LocalModelError(f"the local model has no model named {self.model!r} (run: ollama pull {self.model})")
        if response.status_code != 200:
            raise LocalModelError(f"the local model answered with HTTP {response.status_code}")
        try:
            text = response.json().get("response", "")
        except ValueError:
            raise LocalModelError("the local model's answer wasn't JSON") from None
        return str(text).strip()[:MAX_ANSWER_CHARS]


def build_prompt(
    *,
    company: str,
    title: str,
    question: str,
    description: str,
    background: str,
    facts: dict[str, str],
) -> str:
    fact_lines = "\n".join(f"- {k}: {v}" for k, v in facts.items() if v)
    return (
        "You are helping a student fill in an internship application. Write their answer to one\n"
        "question, in the first person, as they would write it: plain text, no markdown, no greeting,\n"
        "at most 150 words. Use only facts from their background below; never invent experience,\n"
        "employers, numbers or skills. If the background doesn't give enough to answer honestly,\n"
        "reply with exactly: NEEDS YOU\n\n"
        f"Company: {company}\nRole: {title}\n\n"
        f"Their background:\n{background or '(none given)'}\n"
        f"{fact_lines}\n\n"
        f"Question: {question}\n"
        + (f"Question details: {description}\n" if description else "")
        + "\nAnswer:"
    )


def usable(answer: str) -> bool:
    return bool(answer) and "NEEDS YOU" not in answer.upper()
