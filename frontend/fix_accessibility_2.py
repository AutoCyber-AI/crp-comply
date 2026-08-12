#!/usr/bin/env python3
"""Second pass: remaining font sizes, gray text, and brand contrast."""
import os
import re

SRC = os.path.join(os.path.dirname(__file__), "src")

def read_file(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

def write_file(path, content):
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)

def process_file(path):
    full = os.path.join(SRC, path)
    if not os.path.exists(full):
        return
    content = read_file(full)
    original = content

    # Global font-size fixes
    content = content.replace("text-[9px]", "text-xs")
    content = content.replace("text-[10px]", "text-xs")
    content = content.replace("text-[11px]", "text-xs")

    # Gray text fixes (avoid dark/hover/focus/active variants)
    content = re.sub(r'(?<!dark:)(?<!hover:)(?<!focus:)(?<!active:)text-gray-400', 'text-gray-600', content)
    content = re.sub(r'(?<!dark:)(?<!hover:)(?<!focus:)(?<!active:)text-gray-500', 'text-gray-600', content)

    # Slate text fixes similarly
    content = re.sub(r'(?<!dark:)(?<!hover:)(?<!focus:)(?<!active:)text-slate-400', 'text-slate-600', content)
    content = re.sub(r'(?<!dark:)(?<!hover:)(?<!focus:)(?<!active:)text-slate-500', 'text-slate-600', content)

    if content != original:
        write_file(full, content)
        print(f"Updated {path}")

# Process all tsx/ts/css files
for root, dirs, files in os.walk(SRC):
    for name in files:
        if name.endswith((".tsx", ".ts", ".css")):
            rel = os.path.relpath(os.path.join(root, name), SRC).replace("\\", "/")
            process_file(rel)

# Fix remaining brand contrast issues manually
pricing = os.path.join(SRC, "pages/Pricing.tsx")
content = read_file(pricing)
content = content.replace("? 'bg-brand-600 text-white hover:bg-brand-500'", "? 'bg-brand-600 text-brand-900 hover:bg-brand-500'")
write_file(pricing, content)
print("Fixed Pricing.tsx brand contrast")

settings = os.path.join(SRC, "pages/Settings.tsx")
content = read_file(settings)
content = content.replace('bg-brand-600 px-3 py-2 text-xs font-semibold text-white hover:bg-brand-500', 'bg-brand-600 px-3 py-2 text-xs font-semibold text-brand-900 hover:bg-brand-500')
write_file(settings, content)
print("Fixed Settings.tsx brand contrast")

print("Done second pass.")
