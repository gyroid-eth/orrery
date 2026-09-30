# 設定

> English version: [en/configuration.md](en/configuration.md)

[前: インストール](install.md) · [README に戻る](../README.md) · [次: 使い方](usage.md)

ORRERY は `~/.orrery/config.json` と環境変数で設定します。共有設定 file は Finder 起動でも読まれ、環境変数は常に同じ項目の設定 file より優先されます。

## 最小設定

全連携機能を使う最小例:

```bash
export AGENTSTACK_PROJECT_KEY=/absolute/path/to/your/project
export ORRERY_PROJECT_KEY="$AGENTSTACK_PROJECT_KEY"

# DB が default と異なる場合
export AGENTSTACK_MAIL_DB=/absolute/path/to/storage.sqlite3
export ORRERY_MAIL_DB="$AGENTSTACK_MAIL_DB"
```

ORRERY Telemetry dashboard は `127.0.0.1:8770`、ORRERY backend は `127.0.0.1:8791` で起動します。

## 共有設定 file

Finder から起動する desktop app と Python backend が同じ file を読みます。

```text
~/.orrery/config.json
```

全項目を指定する例:

```json
{
  "orrery_root": "/absolute/path/to/orrery",
  "project_key": "/absolute/path/to/your/project",
  "mail_db": "~/.agentstack/mail/storage.sqlite3",
  "annotations_path": "~/.agentstack/runtime/annotations.json"
}
```

| key | 利用 component | 用途 |
| --- | --- | --- |
| `orrery_root` | Tauri shell | `bridge/.venv/bin/python` と backend script の基準 |
| `project_key` | Python backend | ORRERY Mail の project human key |
| `mail_db` | Python backend | read-only ORRERY Mail SQLite |
| `annotations_path` | Python backend | dashboard 不達時の annotation fallback |

トップレベル JSON object の任意 string key だけを受け付けます。空文字、非 string、未知 key は無視し、前後空白を除去して `~` を展開します。file の欠損、読取不能、不正 JSON は起動を停止せず未設定として扱います。path 情報を含むため file mode `0600` を推奨します。

### Desktop app の environment

`~/.zshrc` で export した `AGENTSTACK_ORRERY_ROOT` や `ORRERY_BACKEND_*` は Finder 起動には渡りません。通常の Finder 起動は `config.json` の `orrery_root` を使い、env override は `npm run dev` または app bundle 内 executable を同じ terminal から直接起動する場合に使います。

## runtime / build 変数

| 環境変数 | 既定値 | 用途 |
| --- | --- | --- |
| `ORRERY_MAIL_DB` | `config.mail_db`、その後 `~/.agentstack/mail/storage.sqlite3` | ORRERY が read-only で開く ORRERY Mail SQLite。`AGENTSTACK_MAIL_DB` への fallback はありません |
| `ORRERY_PROJECT_KEY` | `AGENTSTACK_PROJECT_KEY`、その後 `config.project_key`、最後は未設定 | mail query の `projects.human_key`。利用者の環境では absolute path を指定してください |
| `AGENTSTACK_PROJECT_KEY` | `config.project_key`、その後未設定 | ORRERY project key の共通 fallback。ORRERY Telemetry と同じ値を推奨 |
| `ORRERY_PORTRAIT_DIR` | `<repo>/assets/portraits_64` | 通常 portrait |
| `ORRERY_PORTRAIT_DIR_HI` | `<repo>/assets/portraits` | `hi=1` portrait |
| `ORRERY_PORTRAIT_DIR_PX` | `<repo>/assets/portraits_px` | `style=pixel` portrait |
| `AGENTSTACK_ANNOTATIONS` | `config.annotations_path`、その後 ORRERY Telemetry runtime / legacy path | dashboard annotation API が不達のときだけ読む file fallback |
| `ORRERY_HISTORY_DIR` | `~/.orrery/history` | terminal recorder の JSON 保存先 |
| `AGENTSTACK_ORRERY_ROOT` | `config.orrery_root`、その後未設定 | Tauri sidecar が checkout を探す root |
| `ORRERY_BACKEND_PYTHON` | `<root>/bridge/.venv/bin/python` | sidecar の Python |
| `ORRERY_BACKEND_SCRIPT` | `<root>/bridge/orrery_backend.py` | sidecar の backend script |
| `ORRERY_TMUX_SESSION` | 未設定 | legacy `control_server.py` の attach session。製品 backend では未使用 |
| `ORRERY_PORTRAIT_SOURCE_DIR` | `<repo>/assets/portraits_src` | `scripts/build_portraits.py` の入力 |

owner 固有 path への fallback はありません。必要な root / project を env または共有設定 file に明示し、未設定時の縮退を診断可能にしています。

## 一般名の環境変数と CLI

これらは `ORRERY_*` 接頭辞ではありませんが、起動契約の一部です。

| 対象 | 環境変数 / option | 既定値 | 注意 |
| --- | --- | --- | --- |
| desktop / backend | `HOME` | OS user home | `~/.orrery/config.json` と `~` 展開の基準 |
| unified backend | `HOST` | `127.0.0.1` | 他の address は拒否 |
| unified backend | `PORT` / `--port` | `8791` | `ORRERY.app` は変更に追随しません |
| unified backend | `TMUX_BIN` / `--tmux-bin` | `tmux` | binary path のみ。custom tmux socket option ではありません |
| legacy control server | `HOST` | `127.0.0.1` | 製品 server ではありません |
| legacy control server | `PORT` | `8780` | 開発用途 |
| legacy control server | `TMUX_BIN` | `tmux` | tmux executable |
| legacy control server | `SESSION` | 未設定 | `ORRERY_TMUX_SESSION` より優先 |

backend の port を変える例:

```bash
PORT=8801 bridge/.venv/bin/python bridge/orrery_backend.py
# または
bridge/.venv/bin/python bridge/orrery_backend.py --port 8801
```

browser では変更後の URL を直接開けますが、desktop app は `:8791` 固定です。

## test-only 変数

| 環境変数 | 既定値 | 用途 |
| --- | --- | --- |
| `ORRERY_E2E_V2` | 未設定 | `1` で unified-backend contract suite を有効化 |
| `ORRERY_STREAM_ROUNDS` | `5` | stream integrity test の round 数 |

```bash
cd bridge
ORRERY_E2E_V2=1 .venv/bin/python tests/e2e_bridge.py -v
```

## 接続先の優先順位

### project key

1. `ORRERY_PROJECT_KEY`
2. `AGENTSTACK_PROJECT_KEY`
3. `config.json` の `project_key`
4. 未設定

利用者の環境では1〜3のいずれかを absolute path で設定します。未設定時の mail API は `ok:false` と `project key not configured` を返します。ORRERY Telemetry と異なる値を設定すると、roster と mail rail が別 project を示すことがあります。

### ORRERY Mail DB

ORRERY は `ORRERY_MAIL_DB`、`config.json` の `mail_db`、既定 path の順に読みます。ORRERY Telemetry の `AGENTSTACK_MAIL_DB` は自動継承されないため、default 以外では両側に同じ path を設定します。

SQLite は次の形式で read-only open されます。

```text
file:<path>?mode=ro
```

DB 不在や schema error は backend 全体を停止せず、mail route が `ok:false` を返します。

### annotation fallback

`AGENTSTACK_ANNOTATIONS`、次に `config.json` の `annotations_path` を解決します。どちらかを明示した場合は、その1 file だけを対象にします。

どちらも未設定の場合は次の順に、最初に読める file を使います。

1. `~/.agentstack/runtime/annotations.json`
2. `~/.claude/tools/agent-dashboard/annotations.json`（legacy）

この file fallback は dashboard の `/api/annotations` が不達のときだけ使います。

### ORRERY Telemetry dashboard

ORRERY の接続先は次に固定されています。

```text
http://127.0.0.1:8770
```

ORRERY Telemetry 側で port を変えないでください。必要 API は `/api/agents`、`/api/messages-since`、`/api/graph`、`/api/spawn`、`/api/spawn-names`、`/api/annotations`、`/api/exit` です。

### tmux

`TMUX_BIN` で executable は変えられますが、socket / server を指定する公開 option はありません。backend process と同じ user / environment の default tmux server を使用します。agent name と tmux session name の一致が cockpit jump の前提です。

## portrait

portrait は次の directory から読みます。

- 通常: `ORRERY_PORTRAIT_DIR`
- 高解像度: `ORRERY_PORTRAIT_DIR_HI`
- pixel style: `ORRERY_PORTRAIT_DIR_PX`

該当 PNG がなければ initials SVG を返します。source asset の再生成では `ORRERY_PORTRAIT_SOURCE_DIR` を使い、manifest、SHA-1、provenance を検証します。manifest と `CREDITS.md` に掲載されていない portrait は、配布承認済み asset とみなしません。ただし `assets/portraits_px/` のドット絵 50枚は、作者 gyroid が ChatGPT（OpenAI の画像生成）で文章の指示だけから生成したものです。写真は入力に使っていません。repository と同じ条件（PolyForm Perimeter License 1.0.1）で配布します。

## 保存データとプライバシー

terminal recorder は `ORRERY_HISTORY_DIR` に pane JSON を30秒間隔で flush します。

- 1 pane あたり最大2000行を保持
- attach snapshot は最大1000行
- 通常履歴は7日保持
- 対応 session がない orphan は24時間保持

prompt composer は browser `localStorage` に draft と最大50件の送信履歴を保存します。font、split layout、mini-orrery mode / depth、NEW AGENT の Advanced panel 開閉状態も `localStorage` に保存されます。`~/.orrery/config.json` は app 削除後も残る利用者設定です。

共有 Mac、画面共有、機密 session では次を検討してください。

- `ORRERY_HISTORY_DIR` を暗号化された利用者専用 directory に変更
- browser profile を分離
- 利用後に prompt history / localStorage を消去
- mail rail と terminal を表示したまま画面共有しない
- 画面共有や録画では、デモモードを使う

デモモード（Settings の Demo mode、または URL の `?demo=1`。`?demo=0` はそのページだけ切る）は、画面に出るユーザー名と機体名を同じ文字数の `*` で伏せます。伏せるのは、home の path の中のユーザー名（`/Users/<名前>`、`/home/<名前>`、`C:\Users\<名前>`）、`<名前>@` の形、単語として出る機体名です。名前は backend の `GET /telemetry/identity` が `$HOME`・login 名・機体名（WSL では Windows のユーザー名も）から返し、推測はしません。ほかの単語の一部としての名前や、本文に書かれた人の名前は伏せません。伏せるのは表示だけで、agent・記録・Mail の中身は変わらず、端末の path と URL のクリックとコピーは本当の値で動きます。入力欄は本当の値を持ったまま、伏せた文字を重ねて表示します（送る内容・編集・コピーは本当の値）。名前が分かるまでは画面を出さず、backend が名前を返せないときは、画面を隠したまま理由と Retry を表示します（実名の画面に切り替えるには「Open without demo mode」を選ぶ）。Settings の switch は browser の `localStorage` に保存されます。

ほかに伏せたい語（Mail の本文に書かれた人の名前、案件の名前など）は、Settings の「Also mask these words」に `,` 区切りで足します（browser の `localStorage` に保存）。足した語もユーザー名と同じように、同じ幅の `*` で、端末の中身まで伏せ、クリックとコピーは本当の値に戻ります。英数字の語は、大文字小文字を区別せず、単語として出たときだけ伏せます（`Kobo` は `kobold` の中では伏せない）。日本語など、それ以外の文字を含む語は、単語の区切りが無いので、どこに出ても伏せます（`ミラノ` を足すと `ミラノさん` の `ミラノ` も伏せる）。1 文字の語は無視します。1 ページだけなら URL の `?mask=語,語` でも渡せますが、URL は履歴や共有に残るので、Settings の欄を使ってください。

保存先と削除後に残る状態は[インストールの「データの置き場所とアンインストール」](install.md#データの置き場所とアンインストール)も参照してください。

## localhost の安全境界

backend は `127.0.0.1` 以外への bind を拒否しますが、localhost 内の認証はありません。terminal input、spawn、EXIT、filesystem directory listing、dashboard control proxy にアクセスできるため、remote proxy や port forwarding で公開しないでください。

`/telemetry/fs/dirs` は hidden directory を除外しますが、dashboard 側の browser と異なり root allowlist を持ちません。localhost-only の境界を維持してください。

## 関連文書

- [インストール](install.md)
- [使い方](usage.md)
- [トラブルシューティング](troubleshooting.md)
- [アーキテクチャ概要](ARCHITECTURE_OVERVIEW.md)
- [実装アーキテクチャ](ARCHITECTURE.md)
