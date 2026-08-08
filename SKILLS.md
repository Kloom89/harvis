# Writing HARVIS skills

A skill is **one Python file** dropped into `skills/`. HARVIS loads every
`*.py` there at boot (files starting with `_` are ignored), and users can
install yours live from the HUD (**AJUSTES → Skills instaladas → ＋ Instalar skill**) — no
restart needed.

A skill can export any combination of four things:

| Export | Type | What it does |
|---|---|---|
| `TOOLS` | `list[Tool]` | Functions every brain (Claude, Groq, Ollama…) can call |
| `PROMPT` | `str` | Context appended to the system prompt (tagged `[skill <name>]`) |
| `setup(cfg)` | `def` | Runs once at load, receives the parsed `config.yaml` |
| `WATCHER` | `async def` | Background loop that can speak up proactively |

The module docstring's **first line** is the description shown in the HUD.

## Tools

```python
from registry import kloom_tool

@kloom_tool(
    "spotify_play",                       # name the LLM calls
    "Plays a song or playlist on Spotify. Use when asked to play music.",
    {"query": str,                        # required param
     "shuffle": (bool, False)},           # optional param with default
    meta={"category": "media"},           # optional metadata
)
async def spotify_play(args):
    q = args["query"]
    ...
    return "Playing it, sir."             # what the assistant SPEAKS

TOOLS = [spotify_play]
```

Rules of the house:

- The handler is **async**, receives a `dict`, returns a `str`. That string
  is read **aloud** — keep it short, no markdown, no URLs.
- Never fabricate success. If the effect can fail silently, **verify it**
  and report the truth (`return f"Couldn't do it: {e}"`).
- Blocking work (subprocess, UI automation, file IO) goes through
  `asyncio.to_thread(...)`.
- Descriptions are what the LLM uses to pick your tool — write them for the
  model, mention *when* to use it.
- Destructive or outward actions (sending messages, deleting things) must be
  **two-step**: a `draft` tool that shows the result, and a `confirm` tool
  that only acts after the user explicitly approves. See `tools/whatsapp.py`.

## Prompt

```python
PROMPT = ("Redactor mode: with redactor_get you read what the user "
          "dictated, with redactor_paste you paste it anywhere.")
```

One or two sentences. It's injected into **every** brain's system prompt, so
keep it lean — tokens cost.

## Watchers (proactive skills)

```python
import asyncio

async def WATCHER(avisar, cfg):
    while True:
        await asyncio.sleep(15 * 60)
        if something_bad():
            await avisar("Sir, the media server is down.")
```

- `avisar(text)` speaks through the speakers **and** sends it to the paired
  Telegram chat.
- Exceptions kill only your watcher (guarded), but be polite: catch what you
  can and use `logging`.
- Read your settings from `cfg` (the parsed `config.yaml`) — don't hardcode
  paths or hosts. If your skill needs config the user didn't set, **return
  early with a log line** instead of crashing or nagging.
- Quiet hours are your responsibility (see `skills/vigia_homelab.py`).

## Full example

`skills/vigia_homelab.py` (SSH watcher with config, quiet hours and traces),
`skills/redactor.py` (tools + a mode that lives in the main loop) and
`skills/coach.py` (pure prompt persona) are the reference implementations.

## Checklist before you PR

1. One file, self-contained, no new heavy dependencies without a good reason.
2. Docstring first line = clear description (it shows in the HUD).
3. Tool outputs are speakable Spanish (or match the assistant's language).
4. No personal data, hosts, tokens or absolute paths — everything via
   `config.yaml` or env vars.
5. It loads clean: `python -c "import importlib.util as u; s=u.spec_from_file_location('x','skills/your_skill.py'); m=u.module_from_spec(s); s.loader.exec_module(m)"`.
