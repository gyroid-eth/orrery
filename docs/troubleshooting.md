# トラブルシューティング

> English version: [en/troubleshooting.md](en/troubleshooting.md)

[前: 使い方](usage.md) · [README に戻る](../README.md) · [次: アーキテクチャ概要](ARCHITECTURE_OVERVIEW.md)

最初に backend と dashboard を分けて確認します。

```bash
curl -fsS http://127.0.0.1:8791/telemetry/health
curl -fsS http://127.0.0.1:8770/api/agents
tmux list-sessions
```

`/telemetry/health` は backend 自身と ORRERY Telemetry dashboard の到達性を区別します。

## `ORRERY.app` が offline page のまま

app は `:8791/cockpit.html` を確認し、不達なら checkout の backend を sidecar として起動します。

確認:

1. `bridge/.venv/bin/python` が存在し実行可能か
2. `bridge/orrery_backend.py` が存在するか
3. `~/.orrery/config.json` の `orrery_root` が実際の checkout を指すか
4. env override を使う場合は `AGENTSTACK_ORRERY_ROOT` または個別 path が app process に渡っているか
5. backend log に dependency error がないか（ORRERY.app が起動した backend の log は `~/Library/Logs/ORRERY/backend.log`）

GUI app は `~/.zshrc` を読まず、shell より短い `PATH` で起動します。Finder 起動では共有設定 file を使います。config の欠損、不正 JSON、root 内の Python / script 不在、spawn failure は log に actionable reason を出して offline page に留まります。修正後に Retry するか、backend を手動で `:8791` に起動してください。

## backend が起動しない

repository root から正しい script path で起動します。

```bash
bridge/.venv/bin/python bridge/orrery_backend.py
```

`bridge/.venv/bin/python orrery_backend.py` を repository root で実行すると script が見つかりません。後者の形式は `cd bridge` 後だけ有効です。

dependency を再確認:

```bash
bridge/.venv/bin/python -m pip install -r bridge/requirements.txt
bridge/.venv/bin/python -c "import aiohttp, websockets, PIL, pyte"
```

Python 3.10 未満では union type syntax を解釈できません。

## `pyte` が見つからない

terminal recorder は `pyte` を使います。

```bash
bridge/.venv/bin/python -m pip install "pyte>=0.8.2,<1"
bridge/.venv/bin/python -c "import pyte; print(pyte.__version__)"
```

`ORRERY.app` が別の Python を使っている場合は、install した venv を明示します。

```bash
export ORRERY_BACKEND_PYTHON=/absolute/path/to/orrery/bridge/.venv/bin/python
```

## port `8791` が使用中

listener を確認します。

```bash
lsof -nP -iTCP:8791 -sTCP:LISTEN
```

既存 ORRERY backend ならその process を再利用できます。別 service なら安全に停止するか、browser-only 利用で backend port を変えます。

```bash
bridge/.venv/bin/python bridge/orrery_backend.py --port 8801
open http://127.0.0.1:8801/cockpit.html
```

`ORRERY.app` の URL は `:8791` 固定なので、変更 port には追随しません。

## ORRERY Telemetry `:8770` に届かない

```bash
curl -i http://127.0.0.1:8770/api/agents
```

確認:

- ORRERY Telemetry dashboard が起動しているか
- `AGENTSTACK_PORT` を `8770` 以外に変えた場合、`ORRERY_DASHBOARD_URL` を同じ port に合わせたか（`scripts/start-cockpit.sh` は `~/.agentstack/env.sh` から自動で合わせます）
- ORRERY と ORRERY Telemetry が同じ user / host で動いているか

不達時の縮退:

| 機能 | 状態 |
| --- | --- |
| terminal / tmux sessions | 利用可能 |
| local portrait | 利用可能 |
| read-only SQLite mail | DB が読めれば利用可能 |
| roster / live graph | `dashboard offline` |
| spawn | HTTP 502、利用不可 |
| TELEMETRY / REPLAY / dashboard control | 利用不可 |

catalog の fallback が見えても offline spawn はできません。spawn POST は dashboard を必要とします。

## NETWORK で介入待ちの `?` / `!` が見えない

古い ORRERY Telemetry build では、NETWORK の layout によって質問待ちの `?` や承認待ちの `!` が隣の node に隠れ、見えたり見えなかったりすることがあります。SVG は画面上の重なりを DOM の描画順で決めるため、後から描かれた node が介入表示を覆うことが原因です。

現行 build は介入待ちの node を常に最前面へ描きます。古い build で再現する場合は ORRERY Telemetry を更新してください。更新前、または NETWORK で判断しにくい場合は `DECK` に切り替えます。質問待ちは card 右上の `?`、承認待ちは赤い外枠と `APPROVAL` で確認できます。実画面は[使い方の「介入待ちの見分け方」](usage.md#介入待ちの見分け方)を参照してください。

## mail が表示されない

ORRERY は `AGENTSTACK_MAIL_DB` を自動では読みません。

```bash
export ORRERY_MAIL_DB=/absolute/path/to/storage.sqlite3
export ORRERY_PROJECT_KEY=/absolute/path/to/your/project
```

確認:

- DB file が存在し backend user から読めるか
- ORRERY Telemetry と ORRERY の project key が同じ absolute path か
- DB 内の `projects.human_key` と一致するか
- schema error が `/telemetry/mail/recent` に出ていないか

DB 不在や schema error は backend 全体を停止しません。mail route だけが `ok:false` を返します。

## roster は見えるが terminal が一切開かない

次の症状が同時に出る場合は、個別の agent ではなく backend が tmux executable を解決できているか確認します。

- roster と ORRERY Mail rail は正常に表示される
- header は `tmux · 0/0`
- 中央は `waiting for sessions…` のまま
- terminal から backend を起動すると動くが、Finder から `ORRERY.app` を起動すると再現する

Finder、launchd、Tauri sidecar からの GUI 起動は shell の設定を読まず、`/usr/bin:/bin:/usr/sbin:/sbin` のような短い `PATH` で始まります。そのため terminal では見つかる Homebrew の tmux が、GUI 起動では見つからないことがあります。

現行 backend は起動時に `PATH`、次に既知の install 先から tmux を探します。見つからなければ探索した `PATH` と候補を表示して起動を中止します。解決結果を確実に確認するには、repository root から backend を foreground で起動します。Finder 起動の detached sidecar は stdout / stderr を保存しません。

```bash
bridge/.venv/bin/python bridge/orrery_backend.py
```

成功時は起動直後に次の形式で表示されます。

```text
ORRERY: tmux resolved to /opt/homebrew/bin/tmux
```

それでも見つからない場合は terminal で実体を確認し、絶対 path を `TMUX_BIN` に指定して backend を起動します。その backend を動かしたまま `ORRERY.app` を開けます。

```bash
command -v tmux
TMUX_BIN=/absolute/path/to/tmux bridge/.venv/bin/python bridge/orrery_backend.py
```

`TMUX_BIN` は executable だけを指定します。custom socket / server を渡す option ではなく、backend と同じ user / environment の default tmux server を使います。

backend の実行中に解決済みの tmux binary が消えた場合は、次の route が空の `[]` ではなく HTTP `503` と `tmux_unavailable` を返します。

```bash
curl -i http://127.0.0.1:8791/telemetry/sessions
```

## 特定の roster tile だけ terminal が開かない

cockpit jump は agent name と tmux session name の一致を前提にします。

```bash
tmux list-sessions -F '#{session_name}'
```

次の row は terminal を持ちません。

- Codex App Bridge 由来の `surface: codex-app`
- tmux session が終了した agent
- 名前が異なる手動 session

Codex App agent は telemetry で観測できますが terminal attach はできません。

backend startup は live session ごとに recorder control client を接続します。session 数が多い環境では tmux client 数が増えることを想定してください。

## terminal の折り返し幅が変わる

ORRERY の Claim は tmux window size を実際に変更します。Ghostty などの interactive client にも同じ grid width が見えます。

- external client を優先するなら Follow
- ORRERY viewport を優先するなら Claim
- Follow は ORRERY-owned の distinct window すべてを各 Claim 前 snapshot へ復元
- session group close / app close は自動で owned window を release-on-detach
- backend の最後の peer detach / disconnect / teardown にも tracked-only の復元 safety net

初回 Claim 前に local `window-size` option の有無と値、正確な grid size を保存し、復元時にその状態を戻します。同じ window の再 Claim で snapshot は上書きしません。Claim せず attach / detach しただけなら size command を発行しないため、外部の manual 設定は変わりません。

幅が戻らない場合:

1. backend log の `ORRERY window-size restore incomplete` と session / window ID を確認
2. release 失敗後も backend が動いていれば Follow または detach で再試行
3. `tmux show-window-options -v -t '<window-id>' window-size` で現在の local option を確認
4. 最終 teardown 後も復元できなかった場合だけ、保存していた外部設定を確認して手動復旧

復元に失敗した tracked snapshot は成功するまで消費しません。反対に、ORRERY が ownership を持たない window を一括 unset する処理はありません。

## terminal が空、または xterm が読み込まれない

現行 frontend は `xterm.js 5.5.0` と `addon-fit 0.10.0` を CDN から読みます。ネットワークや Content Security Policy が jsDelivr / Google Fonts を拒否すると、font は fallback し、xterm script がなければ terminal UI は成立しません。

確認:

- browser / WebView の developer console
- CDN への DNS / TLS 到達
- proxy / firewall / CSP

現行配布は完全 self-contained offline bundle ではありません。

## WebSocket が切断を繰り返す

1. backend process が生存しているか
2. `/telemetry/health` が返るか
3. browser URL と WebSocket origin が同じか
4. 開発用 `?ws=` override が古くないか

client は1.5秒後に再接続します。production では同一 origin の `/ws` を使い、`?ws=` は開発用途に限定してください。

## Split が tmux pane を増やさない

正常です。cockpit の Split は複数 session の表示 layout で、tmux `split-window` ではありません。

protocol の pane `split` / `close` は `orrery-` prefix の管理 session だけに許可され、通常 agent session では拒否されます。

## Ghostty が開かない

実装は固定 path を使用します。

```text
/Applications/Ghostty.app/Contents/MacOS/ghostty
```

別 path の binary override はありません。既に interactive client が attach 済みの場合は新しい Ghostty window を開かず `already` を返します。

## prompt が送信されない

composer は bracketed paste の250 ms 後に carriage return を送ります。

- active pane が正しいか
- IME composition 中ではないか
- pane が agent TUI ではなく shell prompt になっていないか
- WebSocket が connected か

`Shift+Enter` は改行、`Esc` は interrupt です。画像 paste は file upload ではなく literal `Ctrl+V` を TUI へ転送します。

## 履歴が残る／消えない

terminal recorder は既定で `~/.orrery/history` に保存し、通常7日、orphan 24時間を保持します。prompt draft / history は `localStorage`、共有設定は `~/.orrery/config.json` に残ります。`ORRERY.app` の削除だけでは消えません。

削除範囲は[インストールの「データの置き場所とアンインストール」](install.md#データの置き場所とアンインストール)を参照し、ORRERY Telemetry や ORRERY Mail DB を巻き込まないでください。

## 関連文書

- [インストール](install.md)
- [設定](configuration.md)
- [使い方](usage.md)
- [アーキテクチャ概要](ARCHITECTURE_OVERVIEW.md)
- [実装アーキテクチャ](ARCHITECTURE.md)
