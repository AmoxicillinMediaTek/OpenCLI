#!/usr/bin/env python3
"""Tests for the streaming text repair and the /update command.

Run with: npm test   (or: python3 scripts/test_stream.py)
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ai_cli import TextStream, installed_package_name  # noqa: E402

failed = 0


def check(label, ok, detail=""):
    global failed
    print(("ok   " if ok else "FAIL ") + label + (("  -> " + str(detail)) if not ok else ""))
    if not ok:
        failed += 1


def stream(chunks):
    s = TextStream()
    for c in chunks:
        s.feed(c)
    return s.text


# a normal stream keeps every word
check(
    "normal stream is untouched",
    stream(["The", " quick", " brown", " fox"]) == "The quick brown fox",
    stream(["The", " quick", " brown", " fox"]),
)

# a provider that resends the whole answer every time
check(
    "resent answer is not repeated",
    stream(["The", "The quick", "The quick brown", "The quick brown fox"])
    == "The quick brown fox",
    stream(["The", "The quick", "The quick brown", "The quick brown fox"]),
)

# the same chunk twice in a row
check(
    "repeated chunk is not doubled",
    stream(["The", "The", " end"]) == "The end",
    stream(["The", "The", " end"]),
)

# a resent answer that starts with one letter
check(
    "resent answer is fixed from the first letter",
    stream(["T", "Th", "The quick brown fox jumps"]) == "The quick brown fox jumps",
    stream(["T", "Th", "The quick brown fox jumps"]),
)

# a real repeated word keeps its space
check(
    "a real repeat keeps the space",
    stream(["The", " The"]) == "The The",
    stream(["The", " The"]),
)

# words that start the same way are not glued together
check(
    "overlapping words stay separate",
    stream(["I like the", " cat"]) == "I like the cat",
    stream(["I like the", " cat"]),
)

# empty chunks do nothing
check("empty chunk is ignored", stream(["", "hi", ""]) == "hi", stream(["", "hi", ""]))

# the app can find out which npm package it belongs to
name = installed_package_name()
check(
    "package name is found",
    name.startswith("@") and name.endswith("/enzocli"),
    name,
)

# the /update command is wired up
source = open(os.path.join(os.path.dirname(__file__), "..", "ai_cli.py"), encoding="utf-8").read()
check("/update is a command", '("/update"' in source)
check("/update is handled", 'cmd == "/update"' in source)
check("/update is documented", "- `/update`" in source)

print("")
if failed:
    print(f"{failed} check(s) failed")
    sys.exit(1)
print("all checks passed")
