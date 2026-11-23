"""Foundation-Sec-8B-Reasoning as the participant's AI teammate.

Each episode is one conversation with the model, started fresh for every IDS table:

1. Initial assessment. When the episode loads, the model gets the whole table and
   answers in a fixed format: attack yes or no, attack type, and a 1 to 100 confidence
   for each. This runs in the background while the participant makes their own
   judgment, and fills the assessment card on the discussion page.
2. Discussion. The participant's messages go to the same conversation. The first one
   carries the participant's initial assessment.
3. Final conclusion. On final submission the model is asked for its own conclusion in
   the same format. It is not told the participant's final answer.

The words of every turn are in `prompts/`, so they can be read and changed without
touching code. A SHA-256 of each prompt file is saved with every model reply.

Replies come from the HAT chat server on talos, which relays them to llama.cpp. The app
sends its own system prompt, so no server-side audience mode is used.
"""
import csv
import hashlib
import io
import json
import os
import re
import string
import time
import urllib.error
import urllib.request
from pathlib import Path

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"

FIDELITY_LABELS = {
    "high_fidelity": "High fidelity (technical detail)",
    "low_fidelity": "Low fidelity (plain language)",
}

DEFAULTS = {
    # The chat server on talos. LLM_ENDPOINT overrides it, for example to run the app
    # on a laptop against an SSH tunnel to port 8090.
    "endpoint": "http://127.0.0.1:8080/v1/chat/completions",
    # Fixed, with no control in the page. Reasoning counts against it.
    "max_tokens": 4096,
    # The server's context window. Chat history is trimmed to fit inside it.
    "context_tokens": 16384,
    "default_fidelity": "high_fidelity",
    "show_fidelity_toggle": True,
    "timeout_seconds": 300,
    # Tries per assessment before the episode goes on without the model's answer.
    "assessment_attempts": 3,
    # The model sometimes writes past the end of its turn, inventing the participant's
    # next message or a new phase. A reply is cut at the first line, after its first,
    # that starts with one of these (ignoring case, spaces and markdown such as ** or #).
    "turn_end_markers": ["participant:", "you:", "user:", "assistant:", "ai teammate:",
                         "discussion:", "phase 1:", "phase 2:", "phase 3:",
                         "(not shown to the participant", "(word count"],
}

UNAVAILABLE = ("Your AI teammate is unavailable right now. Please let the experimenter "
               "know, and continue with your own assessment.")
INCOMPLETE = ("Your AI teammate could not finish a reply. Please send your message "
              "again.")

# Characters per token, on the low side for CSV, so the estimate errs towards trimming.
_CHARS_PER_TOKEN = 3


def config(settings):
    merged = {**DEFAULTS, **settings.get("llm", {})}
    merged["endpoint"] = os.environ.get("LLM_ENDPOINT", merged["endpoint"])
    if merged["default_fidelity"] not in FIDELITY_LABELS:
        raise ValueError(f"llm.default_fidelity must be one of {sorted(FIDELITY_LABELS)}")
    return merged


def load_prompts():
    """Every prompt file with its hash. Read once per episode, so editing a file never
    changes a conversation that is already under way."""
    prompts = {}
    for path in sorted(PROMPTS_DIR.glob("*.txt")):
        text = path.read_text(encoding="utf-8").strip()
        prompts[path.stem] = {"text": text,
                              "sha256": hashlib.sha256(text.encode()).hexdigest()}
    return prompts


def seed_for(participant_id, trial_id, call_index):
    """Same participant, episode and call give the same seed, so a reply can be
    reproduced from the saved data."""
    digest = hashlib.sha256(f"{participant_id}:{trial_id}:{call_index}".encode())
    return int(digest.hexdigest()[:8], 16) % (2**31)


def table_csv(rows):
    if not rows:
        return ""
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=list(rows[0].keys()), lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue()


def request_reply(endpoint, payload, timeout):
    """The one network call. Tests replace this."""
    req = urllib.request.Request(
        endpoint, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


# ---- parsing the assessment format ----------------------------------------

_FIELD = re.compile(
    r"^[\s#>*\-]*(attack type|attack|detection confidence|category confidence|explanation)"
    r"\s*:\s*(.*)$",
    re.IGNORECASE,
)

# Wordings the model has used for a category instead of the study's own label.
_ALIASES = {
    "reconnaissance": "Recon",
    "denial of service": "DoS",
    "ddos": "DoS",
    "data exfiltration": "Exfiltration",
    "command and control": "C&C beaconing",
    "c2 beaconing": "C&C beaconing",
    "c2": "C&C beaconing",
    "beaconing": "C&C beaconing",
    "lateral movement": "SMB",
    "web application attack": "DVWA",
    "sql injection": "DVWA",
    "credential theft": "Credential harvesting",
}


class AssessmentFormatError(ValueError):
    """The reply is not a usable assessment."""


def _confidence(value, name):
    # The value has to start with the number. Searching anywhere in it would read a
    # format line echoed back unfilled, "how sure ... from 1 (barely sure)", as 1.
    m = re.match(r"\s*(\d+)", value or "")
    if not m or not 1 <= int(m.group(1)) <= 100:
        raise AssessmentFormatError(f"{name} is not a number from 1 to 100: {value!r}")
    return int(m.group(1))


def _category(value, categories):
    clean = re.sub(r"\(.*?\)", "", value or "").strip().strip(".").strip()
    by_name = {c.casefold(): c for c in categories}
    key = clean.casefold()
    if key in by_name:
        return by_name[key]
    if key in _ALIASES:
        return _ALIASES[key]
    matches = [c for c in categories if c != "None"
               and re.search(rf"(?<!\w){re.escape(c.casefold())}(?!\w)", key)]
    if len(matches) == 1:
        return matches[0]
    raise AssessmentFormatError(f"attack type is not one of the study's categories: {value!r}")


def parse_assessment(text, categories):
    """Read the five fields. Raises AssessmentFormatError when the reply is unusable.

    Markdown is tolerated, and so are `85%` and `85/100`. The explanation runs from its
    label to the end of the reply. Attack No forces type None and makes the category
    confidence equal the detection confidence, the same rule the participant follows.
    """
    clean = (text or "").replace("**", "").replace("`", "")
    fields, explanation = {}, None
    lines = clean.splitlines()
    for i, line in enumerate(lines):
        m = _FIELD.match(line)
        if not m:
            continue
        name = m.group(1).lower()
        if name == "explanation":
            explanation = "\n".join([m.group(2), *lines[i + 1:]]).strip()
            break
        fields.setdefault(name, m.group(2).strip())

    attack = (fields.get("attack") or "").strip(" .").capitalize()
    if attack not in ("Yes", "No"):
        raise AssessmentFormatError(f"Attack is not Yes or No: {fields.get('attack')!r}")
    detection = _confidence(fields.get("detection confidence"), "Detection confidence")
    if attack == "No":
        attack_type, category = "None", detection
    else:
        attack_type = _category(fields.get("attack type"), categories)
        if attack_type == "None":
            raise AssessmentFormatError("Attack is Yes but the attack type is None")
        category = _confidence(fields.get("category confidence"), "Category confidence")
    if not explanation:
        raise AssessmentFormatError("no explanation")
    return {"attack_detected": attack, "attack_type": attack_type,
            "detection_confidence": detection, "category_confidence": category,
            "explanation": explanation}


def cut_reply(text, markers):
    """Split a reply into the part the participant sees and anything the model wrote
    after its turn should have ended. The first line is never a cut point, so a reply
    cannot be cut to nothing."""
    lines = text.strip().split("\n")
    for i, line in enumerate(lines[1:], start=1):
        start = line.lstrip(" \t*#>_").lower()
        if any(start.startswith(marker) for marker in markers):
            return "\n".join(lines[:i]).strip(), "\n".join(lines[i:]).strip()
    return text.strip(), ""


def failed_assessment(error):
    """No usable assessment. The episode goes on with the participant's answers alone."""
    return {"status": "failed", "error": error, "attempts": 0, "attack_detected": "",
            "attack_type": "", "detection_confidence": "", "category_confidence": "",
            "explanation": "", "raw_message": "", "fidelity": "", "seed": "",
            "prompt_sha256": "", "finish_reason": "", "completion_tokens": "",
            "latency_seconds": "", "cut_text": ""}


# ---- one episode's conversation -------------------------------------------


class EpisodeSession:
    """The conversation with the model about one IDS table.

    `initial` runs in a worker thread. The page does not touch the session again until
    that has finished, so nothing here needs a lock.
    """

    def __init__(self, settings, trial, participant_id):
        self.cfg = config(settings)
        self.categories = settings["attack_type_options"]
        self.trial = trial
        self.participant_id = participant_id
        self.prompts = load_prompts()
        self.messages = []      # user and assistant turns, without the system prompt
        self.calls = 0          # every request, retries included, for the seeds
        self.discussing = False
        self.carry = ""         # a participant message whose reply failed
        self.initial_result = None

    # -- prompts --

    def _template(self, name, **values):
        return string.Template(self.prompts[name]["text"]).substitute(values)

    def _remind(self, text, kind, fidelity):
        """Close a request with the short style reminder for this audience. A small model
        follows the latest message much more closely than the system prompt, so length
        and wording rules are repeated here. The participant never sees it."""
        return f"{text}\n\n{self.prompts[f'reminder_{kind}_{fidelity}']['text']}"

    def _categories_text(self):
        names = [c for c in self.categories if c != "None"]
        return ", ".join(names[:-1]) + " or " + names[-1]

    def prompt_hashes(self):
        return {name: p["sha256"] for name, p in self.prompts.items()}

    # -- requests --

    def _fit(self, messages, system):
        """Drop the oldest discussion turns until the request fits the context window.
        The table, the initial assessment and the turn carrying the participant's
        initial assessment are always kept."""
        budget = (self.cfg["context_tokens"] - self.cfg["max_tokens"] - 512) * _CHARS_PER_TOKEN
        messages = list(messages)
        size = len(system) + sum(len(m["content"]) for m in messages)
        while size > budget and len(messages) > 5:
            dropped = messages[3:5]
            del messages[3:5]
            size -= sum(len(m["content"]) for m in dropped)
        return messages

    def _call(self, messages, fidelity):
        self.calls += 1
        seed = seed_for(self.participant_id, self.trial["trial_id"], self.calls)
        system = self.prompts[f"system_{fidelity}"]
        payload = {
            "seed": seed,
            "max_tokens": self.cfg["max_tokens"],
            "stream": False,
            "messages": [{"role": "system", "content": system["text"]},
                         *self._fit(messages, system["text"])],
        }
        result = {"fidelity": fidelity, "seed": seed, "prompt_sha256": system["sha256"],
                  "finish_reason": "", "completion_tokens": "", "raw_message": "",
                  "cut_text": "", "error": ""}
        started = time.monotonic()
        try:
            body = request_reply(self.cfg["endpoint"], payload, self.cfg["timeout_seconds"])
        except (urllib.error.URLError, OSError, ValueError) as exc:
            result.update(error=str(exc), latency_seconds=round(time.monotonic() - started, 1))
            return result
        result["latency_seconds"] = round(time.monotonic() - started, 1)
        choice = (body.get("choices") or [{}])[0]
        kept, cut = cut_reply((choice.get("message") or {}).get("content") or "",
                              self.cfg["turn_end_markers"])
        result.update(
            finish_reason=choice.get("finish_reason") or "",
            completion_tokens=(body.get("usage") or {}).get("completion_tokens", ""),
            raw_message=kept,
            cut_text=cut,
        )
        return result

    def _assess(self, messages, fidelity):
        """Ask for an assessment, retrying with a new seed when the reply cannot be read."""
        attempts = []
        for _ in range(self.cfg["assessment_attempts"]):
            reply = self._call(messages, fidelity)
            attempts.append(reply)
            if reply["error"] or not reply["raw_message"]:
                continue
            try:
                parsed = parse_assessment(reply["raw_message"], self.categories)
            except AssessmentFormatError as exc:
                reply["error"] = f"format: {exc}"
                continue
            return {**reply, **parsed, "status": "ok", "attempts": len(attempts)}
        error = "; ".join(a["error"] or "empty reply" for a in attempts)
        # The last attempt's raw reply, seed and timing are kept for the record.
        return {**failed_assessment(error), **attempts[-1], "status": "failed",
                "error": error, "attempts": len(attempts)}

    # -- the three phases --

    def initial(self, fidelity):
        """Phase 1. Each attempt starts the conversation afresh."""
        turn = {"role": "user", "content": self._remind(self._template(
            "turn_initial", row_count=len(self.trial["ids_events"]),
            table=table_csv(self.trial["ids_events"]), categories=self._categories_text()),
            "assessment", fidelity)}
        result = self._assess([turn], fidelity)
        if result["status"] == "ok":
            self.messages = [turn, {"role": "assistant", "content": result["raw_message"]}]
        self.initial_result = result
        return result

    def chat(self, message, pre_answers, fidelity):
        """Phase 2. Returns the entry for the chat log."""
        text = f"{self.carry}\n\n{message}".strip() if self.carry else message
        if not self.discussing:
            text = self._template(
                "turn_discussion_start", attack=pre_answers["attack_detected"],
                attack_type=pre_answers["attack_type"],
                detection_confidence=pre_answers["detection_confidence"],
                category_confidence=pre_answers["category_confidence"], message=text)
        turn = {"role": "user", "content": self._remind(text, "chat", fidelity)}
        reply = self._call([*self.messages, turn], fidelity)
        if reply["error"] or not reply["raw_message"]:
            # Kept back and sent with the participant's next message.
            self.carry = f"{self.carry}\n\n{message}".strip() if self.carry else message
            status = "error" if reply["error"] else "incomplete"
            return {**reply, "status": status,
                    "message": UNAVAILABLE if status == "error" else INCOMPLETE}
        self.messages += [turn, {"role": "assistant", "content": reply["raw_message"]}]
        self.discussing, self.carry = True, ""
        status = "truncated" if reply["finish_reason"] == "length" else "ok"
        return {**reply, "status": status, "message": reply["raw_message"]}

    def final(self, fidelity):
        """Phase 3. The participant's final answer is deliberately not in the request."""
        turn = {"role": "user", "content": self._remind(self._template(
            "turn_final", categories=self._categories_text()), "assessment", fidelity)}
        result = self._assess([*self.messages, turn], fidelity)
        if result["status"] == "ok":
            self.messages += [turn, {"role": "assistant", "content": result["raw_message"]}]
        return result
