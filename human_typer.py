#!/usr/bin/env python3
"""
Simulate human keyboard typing using native macOS CGEvent key press events.

Each character is sent as a real key-down + key-up pair through the HID event
tap, the same path physical keyboard input uses.

Requires Accessibility permission:
  System Settings → Privacy & Security → Accessibility → enable Terminal/iTerm/Cursor

Usage:
  python human_typer.py                    # type random dictionary sentences
  python human_typer.py --count 5          # type 5 sentences then stop
  python human_typer.py --text "hello"     # type specific text
  python human_typer.py --words            # type single dictionary words with spaces
  python human_typer.py --forever          # keep typing until Ctrl+C
  python human_typer.py --activity-test    # keyboard + mouse activity simulation
  python human_typer.py --research         # log event sources for monitor gap analysis
  python human_typer.py --delay 5          # wait 5s before starting (focus target window)
"""

from __future__ import annotations

import argparse
import random
import signal
import sys
import threading
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

try:
    from Quartz import (
        CGEventCreate,
        CGEventCreateKeyboardEvent,
        CGEventCreateMouseEvent,
        CGEventGetIntegerValueField,
        CGEventGetLocation,
        CGEventPost,
        CGEventSetFlags,
        kCGEventFlagMaskShift,
        kCGEventLeftMouseDown,
        kCGEventLeftMouseUp,
        kCGEventMouseMoved,
        kCGEventSourceStateID,
        kCGHIDEventTap,
    )
except ImportError as exc:
    print(
        "Missing dependency: pyobjc-framework-Quartz\n"
        "Install with: pip install pyobjc-framework-Quartz",
        file=sys.stderr,
    )
    raise SystemExit(1) from exc


# macOS virtual key codes (US QWERTY layout)
# https://developer.apple.com/documentation/coreservices/1537043-anonymous/kvkan
VK: dict[str, int] = {
    "a": 0,
    "s": 1,
    "d": 2,
    "f": 3,
    "h": 4,
    "g": 5,
    "z": 6,
    "x": 7,
    "c": 8,
    "v": 9,
    "b": 11,
    "q": 12,
    "w": 13,
    "e": 14,
    "r": 15,
    "y": 16,
    "t": 17,
    "1": 18,
    "2": 19,
    "3": 20,
    "4": 21,
    "6": 22,
    "5": 23,
    "=": 24,
    "9": 25,
    "7": 26,
    "-": 27,
    "8": 28,
    "0": 29,
    "]": 30,
    "o": 31,
    "u": 32,
    "[": 33,
    "i": 34,
    "p": 35,
    "l": 37,
    "j": 38,
    "'": 39,
    "k": 40,
    ";": 41,
    "\\": 42,
    ",": 43,
    "/": 44,
    "n": 45,
    "m": 46,
    ".": 47,
    "`": 50,
    " ": 49,  # space
    "\t": 48,  # tab
    "\n": 36,  # return / enter
}

# Characters that need Shift held (US layout)
SHIFT_CHARS: dict[str, str] = {
    "!": "1",
    "@": "2",
    "#": "3",
    "$": "4",
    "%": "5",
    "^": "6",
    "&": "7",
    "*": "8",
    "(": "9",
    ")": "0",
    "_": "-",
    "+": "=",
    "{": "[",
    "}": "]",
    "|": "\\",
    ":": ";",
    '"': "'",
    "<": ",",
    ">": ".",
    "?": "/",
    "~": "`",
}

ENTER_KEYCODE = 36

# macOS CGEvent source states — key signal for telling hardware vs injected input apart.
SOURCE_STATE_NAMES: dict[int, str] = {
    0: "HIDSystemState",       # physical keyboard/mouse hardware
    1: "Private",              # CGEventPost / synthetic injection (this script)
    2: "CombinedSessionState", # remapped/session-level events
}

FALLBACK_WORDS = (
    "the be to of and a in that have it for not on with he as you do at "
    "this but his by from they we say her she or an will my one all would "
    "there their what so up out if about who get which go me when make can "
    "like time no just him know take people into year your good some could "
    "them see other than then now look only come its over think also back "
    "after use two how our work first well way even new want because any "
    "these give day most us is was are been has had were said did may still "
    "find long down side found here much never same another while might "
    "place right old great where help through before line too means tell "
    "very follow came show around form three small set put end does large "
    "must big even such turn here why ask went men read need land different "
    "home move try kind hand picture again change off play spell air away "
    "animal house point page letter mother answer study learn should world "
    "high every near add food between own below country plant last school "
    "father keep tree start city earth eye light thought head under story "
    "saw left few along close something seem next hard open example begin "
    "life always those both paper together got group often run important "
    "until children side feet car mile night walk white sea began grow took "
    "river four carry state once book hear stop without second later miss "
    "idea enough eat face watch far really almost let above girl sometimes "
    "mountain cut young talk soon list song leave family body music color "
    "stand sun questions fish area mark dog horse birds problem complete room "
    "knew since ever piece told usually friends easy heard order red door "
    "sure become top ship across today during short better best however low "
    "hours black products happened whole measure remember early reached listen "
    "wind rock space covered fast several hold himself toward five step "
    "morning passed true hundred against pattern table north slowly money map "
    "farm pulled draw voice seen cold cried plan notice south sing war ground "
    "fall king town unit figure certain field travel wood fire upon done "
    "road half ten fly gave box finally wait correct oh quickly person became "
    "shown minutes strong stars front feel fact inches street decided contain "
    "course surface produce building ocean class note nothing rest carefully "
    "inside wheels stay green known island week less machine base ago stood "
    "plane system behind ran round boat game force brought understand warm "
    "common bring explain dry though language shape deep thousands yes clear "
    "yet government filled heat full hot check object rule among power cannot "
    "able six size dark ball material special heavy fine pair circle include "
    "built matter square perhaps bill felt suddenly test direction center "
    "ready anything divided general energy subject moon region return believe "
    "dance members picked simple cells paint mind love cause rain exercise "
    "eggs train blue wish drop developed window difference distance heart sit "
    "sum summer wall forest probably legs sat main winter wide written length "
    "reason kept edge interest arms brother race present beautiful store job "
    "corner gas count milk record direct cross speak solve appear metal son "
    "either ice sleep village factors result jumped snow ride care floor hill "
    "pushed baby buy century outside everything tall already instead phrase "
    "soil bed copy free hope spring case laughed nation quite type themselves "
    "temperature bright lead everyone method section lake iron within dictionary "
    "hair age amount scale pounds although per broken moment tiny possible gold "
    "quiet natural lot stone act build speed amount entire writing coffee "
    "garden morning window letter market simple quiet happy family garden "
).split()

SYSTEM_DICTIONARY_PATHS = (
    Path("/usr/share/dict/words"),
    Path("/usr/dict/words"),
)


def _filter_words(raw_words: Iterable[str]) -> list[str]:
    return [
        word
        for word in raw_words
        if 2 <= len(word) <= 12 and word.replace("'", "").isalpha()
    ]


def load_dictionary(use_full_dictionary: bool = False) -> list[str]:
    """Load readable dictionary words for natural-looking typing."""
    common = _filter_words(FALLBACK_WORDS)
    if not use_full_dictionary:
        return common

    for path in SYSTEM_DICTIONARY_PATHS:
        if not path.is_file():
            continue
        words = _filter_words(
            line.strip().lower()
            for line in path.read_text(encoding="utf-8", errors="ignore").splitlines()
            if line.strip()
        )
        if words:
            return words

    return common


_words: list[str] = load_dictionary()


@dataclass
class ActivityProfile:
    """Mouse activity timing for monitor testing."""

    move_interval_min: float = 1.0
    move_interval_max: float = 4.5
    jitter_min: int = 4
    jitter_max: int = 35
    click_chance: float = 0.15


@dataclass
class TypingProfile:
    """Human-like timing parameters (milliseconds)."""

    wpm: float = 55.0
    wpm_jitter: float = 12.0
    key_hold_min: float = 0.035
    key_hold_max: float = 0.095
    think_pause_chance: float = 0.04
    think_pause_min: float = 0.25
    think_pause_max: float = 0.9
    burst_chance: float = 0.08
    burst_speed_multiplier: float = 0.65
    newline_after_chunk_chance: float = 0.28
    paragraph_break_chance: float = 0.06


_stop_requested = False
_mouse_thread: threading.Thread | None = None
_research_logger: ResearchLogger | None = None


@dataclass
class ResearchLogger:
    """Collects posted-event metadata for monitor gap analysis."""

    log_path: Path
    started_at: float = field(default_factory=time.time)
    keyboard_events: int = 0
    mouse_move_events: int = 0
    mouse_click_events: int = 0
    source_states: dict[int, int] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def record(self, event_kind: str, event: object) -> None:
        source_state = int(CGEventGetIntegerValueField(event, kCGEventSourceStateID))
        source_name = SOURCE_STATE_NAMES.get(source_state, f"Unknown({source_state})")
        timestamp = datetime.now(UTC).isoformat(timespec="milliseconds")

        with self._lock:
            if event_kind.startswith("keyboard"):
                self.keyboard_events += 1
            elif event_kind == "mouse_move":
                self.mouse_move_events += 1
            elif event_kind.startswith("mouse_click"):
                self.mouse_click_events += 1
            self.source_states[source_state] = self.source_states.get(source_state, 0) + 1

            with self.log_path.open("a", encoding="utf-8") as handle:
                handle.write(
                    f"{timestamp}\t{event_kind}\t{source_state}\t{source_name}\n"
                )

    def print_summary(self) -> None:
        elapsed_min = max((time.time() - self.started_at) / 60.0, 0.01)
        total = self.keyboard_events + self.mouse_move_events + self.mouse_click_events
        keys_per_min = self.keyboard_events / elapsed_min
        mouse_per_min = (self.mouse_move_events + self.mouse_click_events) / elapsed_min

        print("\n=== Activity Research Summary ===", flush=True)
        print(f"Log file: {self.log_path}", flush=True)
        print(f"Duration: {elapsed_min:.2f} min", flush=True)
        print(f"Keyboard events posted: {self.keyboard_events} ({keys_per_min:.0f}/min)", flush=True)
        print(
            f"Mouse events posted: {self.mouse_move_events + self.mouse_click_events} "
            f"({mouse_per_min:.0f}/min)",
            flush=True,
        )
        print(f"Total posted events: {total}", flush=True)
        print("Event source breakdown:", flush=True)
        for state_id, count in sorted(self.source_states.items()):
            name = SOURCE_STATE_NAMES.get(state_id, f"Unknown({state_id})")
            print(f"  {name} [{state_id}]: {count}", flush=True)

        private_count = self.source_states.get(1, 0)
        hid_count = self.source_states.get(0, 0)
        print("\nCompare the Apploye activity % from this same time window.", flush=True)
        if private_count and not hid_count:
            print(
                "Expected finding: this script posts source=Private(1), not HID(0).\n"
                "If Apploye activity rose anyway → gap: it likely counts injected CGEventPost "
                "input without checking kCGEventSourceStateID.\n"
                "If Apploye activity stayed low → it likely ignores synthetic/private events "
                "or requires real hardware signals.",
                flush=True,
            )
        print(
            "\nFor a stronger monitor, only count HIDSystemState(0), add timing-entropy checks, "
            "and require correlated keyboard/mouse patterns.",
            flush=True,
        )


def _event_source_name(event: object) -> str:
    source_state = int(CGEventGetIntegerValueField(event, kCGEventSourceStateID))
    return SOURCE_STATE_NAMES.get(source_state, f"Unknown({source_state})")


def _post_event(event: object, event_kind: str) -> None:
    if _research_logger is not None:
        _research_logger.record(event_kind, event)
    CGEventPost(kCGHIDEventTap, event)


def start_research_logging(log_path: Path) -> None:
    global _research_logger
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text("timestamp\tevent_kind\tsource_state_id\tsource_state_name\n", encoding="utf-8")
    _research_logger = ResearchLogger(log_path=log_path)
    sample = CGEventCreateKeyboardEvent(None, 0, True)
    print(
        "Research mode enabled.\n"
        f"Sample keyboard event source: {_event_source_name(sample)}\n"
        f"Logging to: {log_path}\n"
        "Start Apploye timer, run this script, then compare activity % with the log.",
        flush=True,
    )


def stop_research_logging() -> None:
    global _research_logger
    if _research_logger is not None:
        _research_logger.print_summary()
    _research_logger = None


def _mouse_location() -> tuple[float, float]:
    event = CGEventCreate(None)
    if event is None:
        return (500.0, 500.0)
    point = CGEventGetLocation(event)
    return (float(point.x), float(point.y))


def _post_mouse_move(x: float, y: float) -> None:
    event = CGEventCreateMouseEvent(None, kCGEventMouseMoved, (x, y), 0)
    _post_event(event, "mouse_move")


def _post_mouse_click(x: float, y: float) -> None:
    down = CGEventCreateMouseEvent(None, kCGEventLeftMouseDown, (x, y), 0)
    _post_event(down, "mouse_click_down")
    time.sleep(random.uniform(0.04, 0.12))
    up = CGEventCreateMouseEvent(None, kCGEventLeftMouseUp, (x, y), 0)
    _post_event(up, "mouse_click_up")


def _simulate_mouse_activity(activity: ActivityProfile) -> None:
    while not _stop_requested:
        x, y = _mouse_location()
        dx = random.randint(-activity.jitter_max, activity.jitter_max)
        dy = random.randint(-activity.jitter_max, activity.jitter_max)
        if abs(dx) < activity.jitter_min:
            dx += random.choice([-1, 1]) * random.randint(activity.jitter_min, activity.jitter_max)
        if abs(dy) < activity.jitter_min:
            dy += random.choice([-1, 1]) * random.randint(activity.jitter_min, activity.jitter_max)

        target_x = max(0.0, x + dx)
        target_y = max(0.0, y + dy)
        steps = random.randint(2, 6)
        for step in range(1, steps + 1):
            if _stop_requested:
                return
            intermediate_x = x + (dx * step / steps)
            intermediate_y = y + (dy * step / steps)
            _post_mouse_move(intermediate_x, intermediate_y)
            time.sleep(random.uniform(0.01, 0.04))

        if random.random() < activity.click_chance:
            _post_mouse_click(target_x, target_y)

        time.sleep(random.uniform(activity.move_interval_min, activity.move_interval_max))


def start_mouse_activity(activity: ActivityProfile | None = None) -> None:
    global _mouse_thread
    profile = activity or ActivityProfile()
    _mouse_thread = threading.Thread(
        target=_simulate_mouse_activity,
        args=(profile,),
        name="mouse-activity",
        daemon=True,
    )
    _mouse_thread.start()


def stop_mouse_activity() -> None:
    global _mouse_thread
    if _mouse_thread and _mouse_thread.is_alive():
        _mouse_thread.join(timeout=1.0)
    _mouse_thread = None


def _handle_sigint(_signum, _frame) -> None:
    global _stop_requested
    _stop_requested = True
    print("\nStopping after current key...", flush=True)


def _char_to_key(char: str) -> tuple[int, bool]:
    """Return (virtual_keycode, needs_shift) for a character."""
    if char == "\n":
        return ENTER_KEYCODE, False

    if char.isupper():
        base = char.lower()
        if base not in VK:
            raise ValueError(f"No key mapping for {char!r}")
        return VK[base], True

    if char in SHIFT_CHARS:
        base = SHIFT_CHARS[char]
        return VK[base], True

    if char in VK:
        return VK[char], False

    raise ValueError(f"No key mapping for {char!r}")


def press_key(keycode: int, shift: bool = False) -> None:
    """Fire one physical-style key press (down then up) via CGEvent."""
    flags = kCGEventFlagMaskShift if shift else 0

    key_down = CGEventCreateKeyboardEvent(None, keycode, True)
    if flags:
        CGEventSetFlags(key_down, flags)
    _post_event(key_down, "keyboard_down")

    hold = random.uniform(0.035, 0.095)
    time.sleep(hold)

    key_up = CGEventCreateKeyboardEvent(None, keycode, False)
    if flags:
        CGEventSetFlags(key_up, flags)
    _post_event(key_up, "keyboard_up")


def inter_key_delay(profile: TypingProfile, char: str) -> float:
    """Compute delay before the next keystroke."""
    # Base delay from WPM with jitter (5 chars ≈ 1 word)
    base_wpm = max(20.0, random.gauss(profile.wpm, profile.wpm_jitter))
    base_delay = 60.0 / (base_wpm * 5.0)

    if random.random() < profile.burst_chance:
        base_delay *= profile.burst_speed_multiplier

    # Slightly longer after punctuation / sentence ends
    if char in ".!?":
        base_delay += random.uniform(0.08, 0.35)
    elif char in ",;:":
        base_delay += random.uniform(0.04, 0.15)
    elif char == " ":
        base_delay += random.uniform(0.02, 0.08)
    elif char == "\n":
        base_delay += random.uniform(0.12, 0.5)

    # Occasional "thinking" pause
    if random.random() < profile.think_pause_chance:
        base_delay += random.uniform(profile.think_pause_min, profile.think_pause_max)

    return max(0.03, base_delay)


def type_character(char: str, profile: TypingProfile) -> None:
    keycode, shift = _char_to_key(char)
    press_key(keycode, shift=shift)
    time.sleep(inter_key_delay(profile, char))


def type_text(text: str, profile: TypingProfile) -> None:
    for char in text:
        if _stop_requested:
            break
        type_character(char, profile)


def pick_word() -> str:
    return random.choice(_words)


def generate_sentence() -> str:
    """Build a readable sentence from dictionary words."""
    roll = random.random()
    if roll < 0.15:
        return pick_word()

    word_count = random.randint(4, 12)
    words = [pick_word() for _ in range(word_count)]
    words[0] = words[0].capitalize()

    if word_count > 6 and random.random() < 0.35:
        split_at = random.randint(2, word_count - 2)
        text = " ".join(words[:split_at]) + ", " + " ".join(words[split_at:])
    else:
        text = " ".join(words)

    ending = random.choice([".", ".", ".", "?", "!"])
    return text + ending


def type_trailing_break(profile: TypingProfile, text: str) -> None:
    """After a chunk, press Space or Enter like a human finishing a line."""
    if _stop_requested:
        return

    stripped = text.rstrip()
    ends_sentence = bool(stripped) and stripped[-1] in ".!?"
    newline_chance = 0.42 if ends_sentence else profile.newline_after_chunk_chance
    roll = random.random()

    if ends_sentence and roll < profile.paragraph_break_chance:
        type_character("\n", profile)
        if not _stop_requested:
            type_character("\n", profile)
    elif roll < newline_chance:
        type_character("\n", profile)
    else:
        type_character(" ", profile)


def type_chunk(text: str, profile: TypingProfile, trailing_break: bool = True) -> None:
    type_text(text, profile)
    if trailing_break and not _stop_requested:
        type_trailing_break(profile, text)


def type_sentences(count: int | None, profile: TypingProfile) -> None:
    if count is None:
        while not _stop_requested:
            type_chunk(generate_sentence(), profile)
        return
    for _ in range(count):
        if _stop_requested:
            break
        type_chunk(generate_sentence(), profile)


def random_words(count: int | None, profile: TypingProfile) -> None:
    if count is None:
        while not _stop_requested:
            type_chunk(pick_word(), profile)
        return
    for i in range(count):
        if _stop_requested:
            break
        type_chunk(pick_word(), profile, trailing_break=i < count - 1)


def random_letters(count: int | None, profile: TypingProfile) -> None:
    alphabet = "abcdefghijklmnopqrstuvwxyz"
    if count is None:
        while not _stop_requested:
            type_character(random.choice(alphabet), profile)
        return
    for _ in range(count):
        if _stop_requested:
            break
        type_character(random.choice(alphabet), profile)


def countdown(seconds: int) -> None:
    print(f"Focus the target window. Starting in {seconds}s... (Ctrl+C to abort)")
    for remaining in range(seconds, 0, -1):
        if _stop_requested:
            raise KeyboardInterrupt
        print(f"  {remaining}...", flush=True)
        time.sleep(1)
    print("Typing now.", flush=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Simulate human keyboard typing with real CGEvent key presses (macOS)."
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--text",
        type=str,
        help="Exact text to type (each character sent as a key event).",
    )
    mode.add_argument(
        "--words",
        action="store_true",
        help="Type single dictionary words with spaces instead of sentences.",
    )
    mode.add_argument(
        "--letters",
        action="store_true",
        help="Type random letters (gibberish) instead of dictionary text.",
    )

    parser.add_argument(
        "--count",
        type=int,
        default=5,
        help="Units to type before stopping: sentences by default, words with --words, letters with --letters (default: 5). Ignored with --text or --forever.",
    )
    parser.add_argument(
        "--forever",
        action="store_true",
        help="Keep typing until Ctrl+C. Ignored with --text.",
    )
    parser.add_argument(
        "--activity-test",
        action="store_true",
        help="Also simulate human-like mouse movement/clicks while typing.",
    )
    parser.add_argument(
        "--research",
        action="store_true",
        help="Log every posted event with macOS source-state metadata for monitor gap analysis.",
    )
    parser.add_argument(
        "--research-log",
        type=Path,
        default=Path("activity_research.log"),
        help="Output path for --research TSV log (default: activity_research.log).",
    )
    parser.add_argument(
        "--full-dict",
        action="store_true",
        help="Use the full macOS system dictionary instead of common everyday words.",
    )
    parser.add_argument(
        "--delay",
        type=int,
        default=3,
        help="Seconds to wait before typing so you can focus the target window (default: 3).",
    )
    parser.add_argument(
        "--wpm",
        type=float,
        default=55.0,
        help="Average typing speed in words per minute (default: 55).",
    )
    return parser.parse_args()


def main() -> None:
    signal.signal(signal.SIGINT, _handle_sigint)

    args = parse_args()
    global _words
    _words = load_dictionary(use_full_dictionary=args.full_dict)
    profile = TypingProfile(wpm=args.wpm)

    try:
        countdown(args.delay)
    except KeyboardInterrupt:
        print("\nAborted.")
        return

    if args.research:
        start_research_logging(args.research_log)

    if args.activity_test:
        print("Activity-test mode: keyboard + mouse simulation enabled.", flush=True)
        start_mouse_activity()

    try:
        if args.text is not None:
            if args.forever:
                print("Note: --forever is ignored with --text.", file=sys.stderr)
            type_text(args.text, profile)
        else:
            count = None if args.forever else args.count
            if args.letters:
                random_letters(count, profile)
            elif args.words:
                random_words(count, profile)
            else:
                type_sentences(count, profile)
    finally:
        stop_mouse_activity()
        stop_research_logging()

    print("\nDone." if not _stop_requested else "\nStopped.")


if __name__ == "__main__":
    main()
