# 研究セット（digest-paper と demo vault）

[English](en/research-set.md)

ORRERY 本体を入れた後に、論文を agent のチームに読書ノートにさせるための一式を、1 行で用意します。

```bash
curl -fsSL https://raw.githubusercontent.com/gyroid-eth/orrery/master/scripts/research-set.sh | bash
```

- 何も変えずに見るだけ: `... | bash -s -- --check`
- vault の置き場を変える: `... | bash -s -- --vault-dir <フォルダ>`
- 英語版の vault と頼み方の文（既定は日本語）: `... | bash -s -- --lang en`

Mac はターミナル、Windows は WSL2 の Ubuntu の中で打ちます。先に ORRERY 本体の 1 行（[install](install.md)）が要ります。

## すること

1. **digest-paper の add-on**: `~/.agentstack/addons/digest-paper/src` に取得し（2 回目からは更新）、add-on 自身の `scripts/install.sh` で入れます。Claude と Codex の skill の置き場に link し、同じ名前の別の skill があれば置き換えません（そのときは、最後に出す頼み方の文が add-on の SKILL.md を名指しします）
2. **demo vault**: GitHub の tarball を展開して置きます。git の checkout にはしません（Mistral のキーを入れた plugin の設定を誤って commit しないため）。**フォルダがすでにあり、中に何かあれば何も変えません**（空のフォルダは vault ではないので、そこに置きます。中断した実行が残した空のフォルダもこれで使われます）。`--lang en` のときは英語版の vault（`orrery-demo-vault-en`）、それ以外は日本語版です
   - Mac: `~/Documents/orrery-demo-vault`（`--lang en` では `orrery-demo-vault-en`）
   - WSL: Windows の `C:\Users\<あなた>\Documents\orrery-demo-vault`（`--lang en` では `orrery-demo-vault-en`。Obsidian は Windows 側で動くため。WSL からは `/mnt/c/...`）
3. **vault を agent の作業 folder にする**: agent の作業 folder が既定の `~/orrery-work` のままなら、ORRERY の setup を `--project-key <vault>` で打ち直して、vault を作業 folder にします（setup が計画を見せて、1 回だけ確認します）。これ以降に起動した agent は vault で動き、vault の `CLAUDE.md` に ORRERY の指示の block が足され（元の内容はそのまま。2 回目以降も 1 つだけ）、file の予約が vault に効き、`+ NEW AGENT` も vault から始まります。Codex の指示は `~/.codex/AGENTS.md` です。すでに動いている agent は古い folder のままなので、新しく起動してください。**自分で選んだ作業 folder は変えません**（変える 1 行を出すだけです）。`--check` では何も変えません
4. **次にすることを出す**: Obsidian で開くフォルダ（WSL では Windows の形）、pdf-mistral に Mistral のキーを入れる場所、cockpit の agent に貼る頼み方の文（パスを埋めたもの、`--lang en` では英語）を 3 つ
   - (a) pdf-mistral で変換した論文から
   - (b) **Mistral のキーが無いとき**: PDF をこの機械で変換してから（図はラスターの図の切り出しとページ全体の画像で、pdf-mistral より粗い）
   - (c) vault に入っている変換済みの論文から（一番速い。見本のノートがあるので、自分のノートは `...-r2` として隣に保存される）

API キーは読みも書きもしません。sudo も使いません。

## agent

digest-paper は Claude が書き、Codex が確かめるのが基本です。片方しか無い機械では、同じ種類の agent 2 体が書き手と確かめ役を受け持ちます（別の会社のモデルによる確かめではないことが、ノートに書かれます）。最後の表に、どの組で動くかが出ます。WSL で Windows 側の `codex` しか無いときは、使えないと出ます（WSL の中に Codex を入れてください）。
