#!/usr/bin/env python3
"""Generate and check the cockpit theme-axis inventory.

The output unit is a normalized record list, never a hand-copied count.  The
browser repeats the same authored-declaration rules through CSSOM and derives
dynamic element expectations from an immutable pre-apply DOM snapshot.
"""

from __future__ import annotations

import argparse
import ast
import difflib
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COCKPIT = ROOT / "bridge" / "cockpit.html"
STYLE_FILES = (ROOT / "bridge" / "orrery_view.css", ROOT / "bridge" / "mail_view.css")
SNAPSHOT = ROOT / "tools" / "fixtures" / "theme_axis_inventory.json"
VERSION = 1
INLINE_INVENTORY_RE = re.compile(
    r'(<script id="agentstack-theme-axis-inventory" type="application/json">\n)'
    r'(.*?)'
    r'(\n</script>)',
    re.S,
)
INLINE_INVENTORY_SENTINEL = "{}"


@dataclass(frozen=True)
class Rule:
    selector: str
    property: str
    value: str
    source: str
    line: int

    def record(self) -> dict[str, object]:
        return {
            "selector": self.selector,
            "property": self.property,
            "value": " ".join(self.value.split()),
            "source": self.source,
            "line": self.line,
        }


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical_digest(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256_bytes(payload.encode())


def normalized_cockpit_source(source: str) -> str:
    """Remove generated inventory bytes before hashing the owning document."""
    normalized, count = INLINE_INVENTORY_RE.subn(
        lambda match: match.group(1) + INLINE_INVENTORY_SENTINEL + match.group(3),
        source,
    )
    if count != 1:
        raise ValueError("expected exactly one embedded cockpit theme inventory")
    return normalized


def strip_comments(css: str) -> str:
    return re.sub(r"/\*.*?\*/", lambda match: "\n" * match.group(0).count("\n"), css, flags=re.S)


def normalize_selector(value: str) -> str:
    return re.sub(r"\s*,\s*", ",", " ".join(value.split()))


def matching_brace(text: str, start: int) -> int:
    depth = 0
    quote = ""
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = ""
            continue
        if char in "\"'":
            quote = char
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index
    raise ValueError(f"unclosed CSS block at offset {start}")


def declarations(body: str) -> list[tuple[str, str, int]]:
    result: list[tuple[str, str, int]] = []
    start = 0
    depth = 0
    quote = ""
    escaped = False
    chunks: list[tuple[str, int]] = []
    for index, char in enumerate(body):
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = ""
        elif char in "\"'":
            quote = char
        elif char == "(":
            depth += 1
        elif char == ")":
            depth = max(0, depth - 1)
        elif char == ";" and depth == 0:
            chunks.append((body[start:index], start))
            start = index + 1
    chunks.append((body[start:], start))
    for chunk, offset in chunks:
        if ":" not in chunk:
            continue
        prop, value = chunk.split(":", 1)
        prop = prop.strip().lower()
        if re.fullmatch(r"--[-\w]+|[-a-z]+", prop) and value.strip():
            result.append((prop, value.strip(), offset))
    return result


def parse_css(css: str, source: str, base_line: int = 1) -> list[Rule]:
    text = strip_comments(css)
    records: list[Rule] = []

    def walk(fragment: str, fragment_offset: int = 0, keyframe: str | None = None) -> None:
        cursor = 0
        while cursor < len(fragment):
            open_at = fragment.find("{", cursor)
            if open_at < 0:
                break
            header_start = cursor
            header = fragment[header_start:open_at].strip()
            close_at = matching_brace(fragment, open_at)
            body = fragment[open_at + 1 : close_at]
            absolute = fragment_offset + header_start
            line = base_line + text.count("\n", 0, absolute)
            if header.startswith("@keyframes"):
                name = header.split(None, 1)[1].strip()
                walk(body, fragment_offset + open_at + 1, name)
            elif header.startswith("@"):
                walk(body, fragment_offset + open_at + 1, keyframe)
            elif keyframe:
                for prop, value, _ in declarations(body):
                    records.append(Rule(f"@keyframes {keyframe}", prop, value, source, line))
            elif header:
                for prop, value, rel in declarations(body):
                    prop_line = line + body.count("\n", 0, rel)
                    records.append(Rule(normalize_selector(header), prop, value, source, prop_line))
            cursor = close_at + 1

    walk(text)
    return records


def source_rules() -> tuple[list[Rule], dict[str, str]]:
    html = COCKPIT.read_text()
    styles = list(re.finditer(r"<style>(.*?)</style>", html, flags=re.S | re.I))
    rules: list[Rule] = []
    for match in styles:
        base_line = html.count("\n", 0, match.start(1)) + 1
        rules.extend(parse_css(match.group(1), "bridge/cockpit.html", base_line))
    for path in STYLE_FILES:
        rules.extend(parse_css(path.read_text(), str(path.relative_to(ROOT))))
    digests = {"bridge/cockpit.html": sha256_bytes(normalized_cockpit_source(html).encode())}
    digests.update({
        str(path.relative_to(ROOT)): sha256_bytes(path.read_bytes()) for path in STYLE_FILES
    })
    return rules, digests


def glow_manifest() -> list[dict[str, object]]:
    source = COCKPIT.read_text()
    block = source.split("const THEME_GLOW_EFFECT_MANIFEST=Object.freeze([", 1)[1].split(
        "].map(([selector,property,categories,mode", 1
    )[0]
    records: list[dict[str, object]] = []
    for line in block.splitlines():
        item = line.strip().removesuffix(",")
        if not item.startswith("["):
            continue
        values = ast.literal_eval(item)
        selector, prop, categories, mode = values[:4]
        record: dict[str, object] = {
            "selector": normalize_selector(selector),
            "property": prop,
            "categories": categories,
            "mode": mode,
        }
        names = ("override_selector", "activation_selector", "activation_property")
        for name, value in zip(names, values[4:]):
            record[name] = normalize_selector(value) if "selector" in name else value
        records.append(record)
    return records


def split_selectors(selector: str) -> list[str]:
    return [part.strip() for part in selector.split(",")]


def split_css_components(prop: str, value: str) -> list[str]:
    if prop == "filter":
        components: list[str] = []
        cursor = 0
        needle = "drop-shadow("
        while True:
            start = value.find(needle, cursor)
            if start < 0:
                break
            depth = 1
            index = start + len(needle)
            while index < len(value) and depth:
                if value[index] == "(":
                    depth += 1
                elif value[index] == ")":
                    depth -= 1
                index += 1
            components.append(" ".join(value[start:index].split()))
            cursor = index
        return components
    components = []
    start = depth = 0
    for index, char in enumerate(value):
        if char == "(":
            depth += 1
        elif char == ")":
            depth = max(0, depth - 1)
        elif char == "," and depth == 0:
            components.append(" ".join(value[start:index].split()))
            start = index + 1
    components.append(" ".join(value[start:].split()))
    return [component for component in components if component]


def glow_mutation_records(
    manifest: list[dict[str, object]], rules: list[Rule]
) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for item in manifest:
        if item["mode"] != "scale":
            continue
        selector = str(item["selector"])
        override = str(item.get("override_selector") or "")
        prop = str(item["property"])
        base_values = [rule.value for rule in rules if rule.selector == selector and rule.property == prop]
        endpoint_values = [rule.value for rule in rules if rule.selector == override and rule.property == prop]
        for occurrence, (base, endpoint) in enumerate(zip(base_values, endpoint_values)):
            base_parts = split_css_components(prop, base)
            endpoint_parts = split_css_components(prop, endpoint)
            for component, base_part in enumerate(base_parts):
                if component >= len(endpoint_parts) or base_part == endpoint_parts[component]:
                    continue
                records.append({
                    "selector": selector,
                    "property": prop,
                    "occurrence": occurrence,
                    "component": component,
                })
    return records


def source_record_key(record: dict[str, object]) -> str:
    return f'{record["selector"]}\0{record["property"]}'


def effect_target_records(
    axis: str,
    *,
    base: list[Rule],
    rules: list[Rule],
    manifest: list[dict[str, object]],
) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    if axis in {"dim-contrast", "background"}:
        tokens = {
            "dim-contrast": ("--ink-dim", "--ink-faint"),
            "background": (
                "--bg", "--panel", "--panel-2", "--elev", "--ink",
                "--ink-dim", "--ink-faint", "--hair", "--hair-2",
            ),
        }[axis]
        records.extend(
            {"selector": rule.selector, "property": rule.property, "value": " ".join(rule.value.split())}
            for rule in base
            if any(f"var({token}" in rule.value for token in tokens)
            and not rule.selector.startswith("@keyframes ")
        )
        axis_prefix = f'html[data-theme-axis="{axis}"] '
        root_prefix = f':root[data-theme-axis="{axis}"]'
        for rule in rules:
            if rule.property.startswith("--") or rule.selector.startswith("@keyframes "):
                continue
            selector = rule.selector
            if selector.startswith(axis_prefix):
                selector = selector[len(axis_prefix) :]
            elif selector == root_prefix:
                selector = ":root"
            else:
                continue
            records.append({"selector": selector, "property": rule.property, "value": " ".join(rule.value.split())})
    elif axis == "glow":
        for item in manifest:
            if item["mode"] != "scale" or str(item["property"]).startswith("--"):
                continue
            selector = str(item.get("activation_selector") or item["selector"])
            if selector.startswith("@keyframes "):
                continue
            records.append({"selector": selector, "property": str(item["property"]), "value": ""})

    unique: list[dict[str, str]] = []
    positions: dict[tuple[str, str], int] = {}
    for record in records:
        key = (normalize_selector(record["selector"]), record["property"])
        normalized = {"selector": key[0], "property": key[1], "value": record["value"]}
        if key in positions:
            # Axis-authored override records are appended after base token
            # consumers and therefore become the expected derivation template.
            unique[positions[key]] = normalized
            continue
        positions[key] = len(unique)
        unique.append(normalized)
    return unique


def build_inventory() -> dict[str, object]:
    rules, source_digests = source_rules()
    base = [
        rule for rule in rules
        if "data-theme-axis" not in rule.selector and not rule.selector.startswith("@keyframes theme-axis-")
    ]

    def px(value: str) -> float | None:
        match = re.fullmatch(r"(\d*\.?\d+)px", value.strip())
        return float(match.group(1)) if match else None

    small: list[Rule] = []
    tracking: list[Rule] = []
    for rule in base:
        selector = rule.selector
        if rule.property == "font-size" and ".brand" not in selector and ".xterm" not in selector:
            size = px(rule.value)
            if size is not None and size < 12:
                small.append(rule)
        if rule.property == "letter-spacing" and not re.search(r"\.brand|\.xterm|\bcode\b|\bpre\b", selector):
            value = rule.value.strip()
            size_rule = next((candidate for candidate in base if candidate.selector == selector and candidate.property == "font-size"), None)
            if value.endswith("em") and float(value[:-2]) > 0.08:
                tracking.append(rule)
            elif value.endswith("px"):
                spacing = float(value[:-2])
                size = px(size_rule.value) if size_rule else None
                if (size and spacing / size > 0.08) or (not size and spacing > 0):
                    tracking.append(rule)

    token_records: dict[str, list[Rule]] = {}
    for axis in ("dim-contrast", "background"):
        selector = f':root[data-theme-axis="{axis}"]'
        token_records[axis] = [rule for rule in rules if rule.selector == selector and rule.property.startswith("--")]

    manifest = glow_manifest()
    by_selector_property = {(rule.selector, rule.property) for rule in base}
    keyframe_properties = {(rule.selector, rule.property) for rule in base if rule.selector.startswith("@keyframes ")}
    missing: list[dict[str, object]] = []
    for item in manifest:
        key = (str(item["selector"]), str(item["property"]))
        if key not in by_selector_property and key not in keyframe_properties:
            missing.append(item)

    effect_candidates = {
        (rule.selector, rule.property)
        for rule in base
        if (
            rule.property in {"box-shadow", "text-shadow"}
            or (rule.property == "filter" and "drop-shadow" in rule.value)
            or (rule.property == "background" and "radial-gradient" in rule.value)
        )
    }
    manifest_effects = {
        (str(item["selector"]), str(item["property"]))
        for item in manifest
        if not str(item["selector"]).startswith(":root")
    }
    uncovered = sorted(effect_candidates - manifest_effects)

    axes = {
        "dim-contrast": {
            "source": {"unit": "token-write", "records": [rule.record() for rule in token_records["dim-contrast"]]},
            "mutation": {"unit": "token-write", "records": [rule.record() for rule in token_records["dim-contrast"]]},
        },
        "small-text": {
            "source": {"unit": "declaration", "records": [rule.record() for rule in small]},
            "mutation": {"unit": "element", "expected_rule": "eligible computed font-size < 12px pre-apply snapshot"},
        },
        "tracking": {
            "source": {"unit": "declaration", "records": [rule.record() for rule in tracking]},
            "mutation": {"unit": "element", "expected_rule": "eligible computed letter-spacing/font-size > 0.08 pre-apply snapshot"},
        },
        "glow": {
            "source": {"unit": "declaration", "records": manifest},
            "mutation": {"unit": "effect-component", "records": glow_mutation_records(manifest, rules)},
        },
        "background": {
            "source": {"unit": "token-write", "records": [rule.record() for rule in token_records["background"]]},
            "mutation": {"unit": "token-write", "records": [rule.record() for rule in token_records["background"]]},
        },
    }
    for axis_name, axis in axes.items():
        if axis_name in {"small-text", "tracking"}:
            axis["effect"] = {
                "unit": "computed-target",
                "expected_rule": f"{axis_name} immutable eligible-element snapshot",
            }
        else:
            axis["effect"] = {
                "unit": "computed-target",
                "records": effect_target_records(
                    axis_name, base=base, rules=rules, manifest=manifest
                ),
            }
    for axis in axes.values():
        for section in ("source", "mutation", "effect"):
            payload = axis[section]
            if "records" in payload:
                payload["expected"] = len(payload["records"])
                payload["digest"] = canonical_digest(payload["records"])

    rules_descriptor = {
        "version": VERSION,
        "small_text": "font-size px <12; exclude .brand/.xterm",
        "tracking": "letter-spacing >.08em; exclude .brand/.xterm/code/pre",
        "glow": "classified selector/property declaration surfaces; mutate mode=scale components",
        "tokens": "custom properties authored in the axis override selector",
        "dynamic": "immutable pre-apply eligible-element snapshot",
        "visibility": "pre-apply rendered nonzero box intersecting viewport",
        "success": (
            "visibleExpected > 0; visibleReached === visibleExpected; "
            "visibleChanged > 0; changed > 0"
        ),
    }
    inventory: dict[str, object] = {
        "version": VERSION,
        "surface": "cockpit",
        "source_files": source_digests,
        "source_digest": canonical_digest(source_digests),
        "rules": rules_descriptor,
        "rules_digest": canonical_digest(rules_descriptor),
        "axes": axes,
        "validation": {"missing_manifest_records": missing, "uncovered_effect_declarations": uncovered},
    }
    inventory["inventory_digest"] = canonical_digest(inventory)
    return inventory


def runtime_inventory(inventory: dict[str, object]) -> dict[str, object]:
    axes: dict[str, object] = {}
    for name, axis_value in inventory["axes"].items():
        axis = axis_value
        source = axis["source"]
        runtime_axis: dict[str, object] = {
            "source": {
                "unit": source["unit"],
                "digest": source["digest"],
                "records": [source_record_key(record) for record in source["records"]],
            },
            "mutation": {"unit": axis["mutation"]["unit"]},
            "effect": {"unit": "computed-target"},
        }
        if "records" in axis["mutation"]:
            runtime_axis["mutation"]["digest"] = axis["mutation"]["digest"]
            runtime_axis["mutation"]["records"] = [
                source_record_key(record) for record in axis["mutation"]["records"]
            ]
        if "records" in axis["effect"]:
            runtime_axis["effect"]["records"] = axis["effect"]["records"]
        else:
            runtime_axis["effect"]["expected_rule"] = axis["effect"]["expected_rule"]
        axes[name] = runtime_axis
    return {
        "version": inventory["version"],
        "surface": inventory["surface"],
        "source_digest": inventory["source_digest"],
        "rules_digest": inventory["rules_digest"],
        "inventory_digest": inventory["inventory_digest"],
        "axes": axes,
    }


def serialized(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def inline_serialized(inventory: dict[str, object]) -> str:
    return serialized(runtime_inventory(inventory)).rstrip("\n").replace("</", "<\\/")


def replace_inline_inventory(source: str, inventory: dict[str, object]) -> str:
    updated, count = INLINE_INVENTORY_RE.subn(
        lambda match: match.group(1) + inline_serialized(inventory) + match.group(3),
        source,
    )
    if count != 1:
        raise ValueError("expected exactly one embedded cockpit theme inventory")
    return updated


def print_diff(label: str, current: str, expected: str) -> None:
    print(f"{label} is stale", file=sys.stderr)
    sys.stderr.writelines(difflib.unified_diff(
        current.splitlines(keepends=True), expected.splitlines(keepends=True),
        fromfile=f"committed/{label}", tofile=f"generated/{label}",
    ))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true", help="refresh the committed record snapshot")
    parser.add_argument("--check", action="store_true", help="fail if coverage is incomplete or snapshot is stale")
    args = parser.parse_args()
    inventory = build_inventory()
    rendered = serialized(inventory)
    cockpit_source = COCKPIT.read_text()
    rendered_cockpit = replace_inline_inventory(cockpit_source, inventory)
    if args.write:
        SNAPSHOT.write_text(rendered)
        COCKPIT.write_text(rendered_cockpit)
    if args.check:
        validation = inventory["validation"]
        if validation["missing_manifest_records"] or validation["uncovered_effect_declarations"]:
            print(json.dumps(validation, indent=2), file=sys.stderr)
            return 1
        stale = False
        if not SNAPSHOT.exists() or SNAPSHOT.read_text() != rendered:
            print_diff("tools/fixtures/theme_axis_inventory.json", SNAPSHOT.read_text() if SNAPSHOT.exists() else "", rendered)
            stale = True
        if cockpit_source != rendered_cockpit:
            current_match = INLINE_INVENTORY_RE.search(cockpit_source)
            rendered_match = INLINE_INVENTORY_RE.search(rendered_cockpit)
            print_diff(
                "bridge/cockpit.html embedded theme inventory",
                current_match.group(2) if current_match else "",
                rendered_match.group(2) if rendered_match else "",
            )
            stale = True
        if stale:
            print(f"stale inventory: run {Path(__file__).relative_to(ROOT)} --write", file=sys.stderr)
            return 1
        axes = inventory["axes"]
        for name, axis in axes.items():
            if axis["source"].get("expected", 0) == 0:
                print(f"{name}: zero source records", file=sys.stderr)
                return 1
            if name not in {"small-text", "tracking"} and axis["mutation"].get("expected", 0) == 0:
                print(f"{name}: zero mutation records", file=sys.stderr)
                return 1
            if name not in {"small-text", "tracking"} and axis["effect"].get("expected", 0) == 0:
                print(f"{name}: zero effect records", file=sys.stderr)
                return 1
    if not args.write:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
