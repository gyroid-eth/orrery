# The research set (digest-paper and the demo vault)

[日本語](../research-set.md)

After ORRERY itself is installed, one line sets up what you need to have an agent team turn a paper into a reading note.

```bash
curl -fsSL https://raw.githubusercontent.com/gyroid-eth/orrery/master/scripts/research-set.sh | bash
```

- Only look, change nothing: `... | bash -s -- --check`
- Put the vault elsewhere: `... | bash -s -- --vault-dir <folder>`

Type it in Terminal on a Mac, or inside the WSL2 Ubuntu on Windows. ORRERY's own one-line install ([install](install.md)) comes first.

## What it does

1. **The digest-paper add-on**: fetched to `~/.agentstack/addons/digest-paper/src` (updated on later runs) and installed with the add-on's own `scripts/install.sh`, which links it for Claude and Codex and never replaces another skill of the same name (the requests it prints then name the add-on's SKILL.md).
2. **The demo vault**: a GitHub tarball, unpacked; not a git checkout (so a plugin setting holding your Mistral key is never committed by mistake). **A folder that already exists is never changed.**
   - Mac: `~/Documents/orrery-demo-vault`
   - WSL: Windows' `C:\Users\<you>\Documents\orrery-demo-vault` (Obsidian runs on Windows; from WSL it is `/mnt/c/...`)
3. **What to do next**: the folder to open in Obsidian (in Windows form on WSL), where to enter a Mistral key for pdf-mistral, and three requests to paste to an agent in the cockpit, with the paths filled in:
   - (a) a paper converted with pdf-mistral
   - (b) **no Mistral key**: the PDF is converted on your machine first (figures are rougher: raster figures cut out, otherwise whole-page images)
   - (c) the paper already converted in the vault (quickest; the vault has a sample note of it, so yours is saved beside it as `...-r2`)

It never reads or writes an API key and never uses sudo.

## Agents

digest-paper normally has Claude write and Codex check. With only one of them, two agents of that kind take the two roles, and the note says the check was not by another company's model. The final table says which team will run. On WSL, a Windows `codex` is reported as not usable (install Codex inside WSL).
