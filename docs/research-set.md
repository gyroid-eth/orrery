# 研究セット（digest-paper と demo vault）

[English](en/research-set.md)

ORRERY 本体を入れた後に、論文を agent のチームに読書ノートにさせるための一式を、1 行で用意します。

```bash
curl -fsSL https://raw.githubusercontent.com/gyroid-eth/orrery/master/scripts/research-set.sh | bash
```

- 何も変えずに見るだけ: `... | bash -s -- --check`
- vault の置き場を変える: `... | bash -s -- --vault-dir <フォルダ>`

Mac はターミナル、Windows は WSL2 の Ubuntu の中で打ちます。先に ORRERY 本体の 1 行（[install](install.md)）が要ります。

## すること

1. **digest-paper の add-on**: `~/.agentstack/addons/digest-paper/src` に取得し（2 回目からは更新）、add-on 自身の `scripts/install.sh` で入れます。Claude と Codex の skill の置き場に link し、同じ名前の別の skill があれば置き換えません（そのときは、最後に出す頼み方の文が add-on の SKILL.md を名指しします）
2. **demo vault**: GitHub の tarball を展開して置きます。git の checkout にはしません（Mistral のキーを入れた plugin の設定を誤って commit しないため）。**フォルダがすでにあり、中に何かあれば何も変えません**（空のフォルダは vault ではないので、そこに置きます。中断した実行が残した空のフォルダもこれで使われます）
   - Mac: `~/Documents/orrery-demo-vault`
   - WSL: Windows の `C:\Users\<あなた>\Documents\orrery-demo-vault`（Obsidian は Windows 側で動くため。WSL からは `/mnt/c/...`）
3. **次にすることを出す**: Obsidian で開くフォルダ（WSL では Windows の形）、pdf-mistral に Mistral のキーを入れる場所、cockpit の agent に貼る頼み方の文（パスを埋めたもの）を 3 つ
   - (a) pdf-mistral で変換した論文から
   - (b) **Mistral のキーが無いとき**: PDF をこの機械で変換してから（図はラスターの図の切り出しとページ全体の画像で、pdf-mistral より粗い）
   - (c) vault に入っている変換済みの論文から（一番速い。見本のノートがあるので、自分のノートは `...-r2` として隣に保存される）

API キーは読みも書きもしません。sudo も使いません。

## agent

digest-paper は Claude が書き、Codex が確かめるのが基本です。片方しか無い機械では、同じ種類の agent 2 体が書き手と確かめ役を受け持ちます（別の会社のモデルによる確かめではないことが、ノートに書かれます）。最後の表に、どの組で動くかが出ます。WSL で Windows 側の `codex` しか無いときは、使えないと出ます（WSL の中に Codex を入れてください）。
