# Telegram Suggest

Phone-keyboard-style word suggestions for **Telegram Desktop** on Windows 10/11.
It learns from what you type and offers the most likely words after one or two letters.

- Uzbek (Cyrillic and Latin), Russian and English words
- Matches Telegram's colours: day, night or any custom theme
- Fully offline: no network, no telemetry; only single words and word pairs are stored, never messages
- One portable `.exe`, no installation or admin rights needed

## Install

Download `TelegramSuggest.exe` and run it. An «А» icon appears next to the clock;
the program starts with Windows from then on (can be turned off in the settings).

**Updating:** run the new `.exe`. It closes the old version and takes its place;
your dictionary and settings are kept (they live in `%APPDATA%\TelegramSuggest`).
Starting the same version again just opens its settings window.

## Usage

| Action | Keys |
|---|---|
| Insert the highlighted word | `Tab` |
| Insert word 1–4 | `Ctrl+1` … `Ctrl+4` (numbers appear while `Ctrl` is held) |
| Insert any word | click it |
| Remove a word from the dictionary | right-click it |
| Hide suggestions for this word | `Esc` |
| Pause / resume | `Ctrl+Alt+P` or the tray icon |

Settings, your word list and history import are in the tray icon menu.
To get useful suggestions from day one, import a Telegram chat export
(Telegram → ⋮ → *Export chat history*, HTML or JSON): only your own messages are learned.

## Privacy

- Keys are read only while Telegram is the active window, never in password fields.
- Logs contain technical events only, no typed text.
- For the theme, one background colour of Telegram's message field is computed every
  couple of seconds; the pixels are discarded at once.

## Build from source

Requires Python 3.11+ on Windows.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest      # tests
run.bat                                    # run without a console
run_diag.bat                               # run with a console showing what the app sees
build.bat                                  # tests + dist\TelegramSuggest.exe
```

## How it works

| Module | Role |
|---|---|
| `hook.py`, `keymap.py` | low-level keyboard hook, keys → characters for the active layout |
| `engine.py`, `lexicon.py`, `store.py` | word buffer, ranking with time decay and bigrams, SQLite |
| `positioning.py` | finds Telegram's input field via UI Automation |
| `overlay.py`, `theme.py` | non-activating suggestion window, colours sampled from Telegram |
| `inserter.py` | types the chosen word with a single `SendInput` |
| `importer.py` | learns from Telegram exports |
| `instance.py` | single running copy, update by running a newer `.exe` |

Known limitation: if Telegram runs as administrator, the program must too, otherwise
Windows blocks both reading keys and typing.
