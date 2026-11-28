"""Observe the live composer independently of its model display name."""
import pytest

import pane_submission as submission


def frame(rows, *, command="zsh", cursor=0):
    metadata = "\t".join(["/tmp/fixture.sock", "100", "%1", "200",
                          str(cursor), "0", "2", "1", command])
    return submission.frame(metadata, rows, "%1")


# The first two segments preserve the original status labels from the Mac
# GreenWatt, CoolBohr, and LeafyYukawa terminal captures. Local paths are omitted.
@pytest.mark.parametrize("status", [
    pytest.param("  \x1b[38;2;246;226;183mGPT-6.2-Sol high\x1b[38;2;117;117;117m · "
                 "\x1b[38;2;242;181;144mContext 38% left\x1b[38;2;117;117;117m", id="sol"),
    pytest.param("  \x1b[38;2;246;226;183mGPT-6.1 Terra high\x1b[39m · "
                 "\x1b[38;2;242;181;144mContext 97% left\x1b[39m", id="terra"),
    pytest.param("  \x1b[38;2;246;226;183mGPT-6-Luna high\x1b[39m · "
                 "\x1b[38;2;242;181;144mContext 88% left\x1b[39m", id="luna"),
    pytest.param("\x1b[0m  \x1b[38;2;246;226;183mGPT-6-Luna xhigh\x1b[39m · ~/fixture",
                 id="luna-wsl-context-hidden"),
    pytest.param("\x1b[49m  \x1b[38;2;246;226;183mGPT-6.2-Astra high\x1b[38;2;117;117;117m · "
                 "\x1b[38;2;242;181;144mContext 94% left\x1b[38;2;117;117;117m", id="astra"),
])
def test_empty_codex_editor_with_native_status_text(status):
    observed = frame(["› ", "", status, "  ← for agents · ? for shortcuts"])
    assert observed.editor == "codex" and observed.empty


@pytest.mark.parametrize("effort", ["xhigh", "ultra"])
def test_codex_with_context_hidden(effort):
    # Exercise the layout without a Context segment, and with an opaque label.
    status = f"  Local test model {effort}"
    assert frame(["› ", "", status, "  ← for agents · ? for shortcuts"]).empty
    assert frame(["› ", "", status]).empty


def test_plain_transcript_after_a_prompt_glyph_does_not_prove_a_codex_footer():
    assert not frame(["› ", "Some text high"]).empty


def test_codex_sol_ultra_uses_the_double_chevron_in_the_live_editor():
    # Cropped from the CrimsonKepler capture, omitting local workspace metadata.
    rows = [
        "\x1b[1m\x1b[38;2;186;130;255m»\x1b[0m \x1b[2mAsk Codex to do anything\x1b[0m",
        "",
        "  \x1b[38;2;246;226;183mGPT-6.2-Sol ultra\x1b[39m · "
        "\x1b[38;2;242;181;144mContext 97% left\x1b[39m",
        "  \x1b[1m←\x1b[0m for agents · \x1b[1m?\x1b[0m for shortcuts",
    ]
    observed = frame(rows)
    assert observed.editor == "codex" and observed.empty
    assert not frame([rows[0], "", "Ordinary transcript text"]).empty


def test_antigravity_without_a_mode_prefix_can_show_other_model_families():
    rule = "─" * 46
    observed = frame([rule, "> ", rule, "Alternative model · low"], command="agy", cursor=1)
    assert observed.editor == "agy" and observed.empty
