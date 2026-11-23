# ORRERY for Windows

ORRERY を Windows ネイティブ（WSL なし）で動かすための作り直しです。今は Phase 3 まで進んでいます。次のものができています。

- **hub**：エージェント同士がメールとホワイトボードでやり取りする
- **host**：Claude Code と Antigravity をブラウザから起動・操作できる
- **配送役**：メールが届いたら、待機中の宛先を自動で起こす

| Phase | 内容 | 状態 |
|---|---|---|
| 1 | hub：共通の SQLite と MCP サーバー | できた |
| 2 | host：ConPTY でエージェントを起動し、ブラウザの xterm で操作する | できた |
| 3 | 配送役：待機中の宛先に、PTY から通知を打ち込んで起こす | できた |
| 4 | 画面：roster とメール一覧の見た目を ORRERY に揃える | これから |

## 配送役（待機中のエージェントを起こす）

host は、未読のメールがあるエージェントが待機中になると、そのターミナルに一行の通知を打ち込みます。例：`[ORRERY] New mail from bob: "件名". Call fetch_inbox to read it, then act on it.` と Enter。人が打ち込むのと同じなので、エージェントは自分で `fetch_inbox` を呼んで対応します。tmux の `send-keys` の代わりに、ターミナルを持っている host 自身が打ち込む形です。

**待機中かどうかの判断**

- **Claude Code**：起動時に `--settings` で hook を渡します（[host/hook.py](host/hook.py)）。`SessionStart` と `Stop` で待機中、`UserPromptSubmit` で作業中です。
  - 画面に `esc to interrupt` が出ているときは、hook に関係なく作業中とみなします。
  - hook が来ないまま 30 秒静かな場合は、待機中とみなします（中断したときなど）。
- **Antigravity**：hook がないので、画面で判断します。画面の下端が `? for shortcuts` なら待機中、`esc to cancel` なら作業中です。

**打ち込まない場面**（メールは未読のまま残り、失われません）

- 確認画面（フォルダの信頼、ツールの許可など）が出ているとき。Enter が選択肢を選んでしまうためです。roster では、人の判断待ちとして点滅します。
- 待機に入ってから、人がそのターミナルに文字を入力したとき。書きかけの指示に通知を付け足さないためです。次に待機に入ったときに通知します。
  - xterm の自動応答、矢印キー、マウスは入力として数えません。
- 1 時間に 30 回起こしたとき。エージェント同士が延々と返信し合うのを止めるためで、roster に **PAUSED** と出ます。
  - MCP の説明文でも、「お礼だけの返信はしない、終わったやり取りには返信しない」ようエージェントに伝えています。

配送待ちの通知は roster に `✉ N` と出ます。カーソルを合わせると待っている理由が分かります。

**記録の流し直し**

ブラウザで開き直したときの記録の流し直しは、ConPTY の大きさで描いてから自分の大きさに合わせます。ConPTY は自分の画面を描く命令を出しているので、大きさが違う端末にそのまま流すと崩れるためです。流し直す記録からは、端末への問い合わせ（カーソル位置など）を取り除きます。古い問い合わせへの答えが、今動いているプログラムに届かないようにするためです。複数のタブで同じエージェントを開いたときに自動応答を返すのは、最後に入力したタブか、大きさを変えたタブだけです。

## 始め方

```
pip install -r windows\requirements.txt
python windows\host\server.py
```

ブラウザで http://127.0.0.1:8791/ を開き、**NEW AGENT** から名前、CLI（Claude Code / Antigravity）、作業フォルダを指定します。

- host が各エージェントのターミナル（ConPTY）を持ちます。ブラウザを閉じたり再読み込みしたりしても、エージェントは止まりません。開き直すと直近の出力が流し直されます。
- host を止めると、エージェントも終了します。roster は残るので、**RESUME** を押すとそのフォルダの直前の会話から再開します（`--continue`）。
- 起動したエージェントは、hub の MCP（`orrery-hub`）に自分の名前で参加しています。Claude Code には起動のたびに `--mcp-config` で渡すので、全体設定への登録は要りません。Antigravity は全体登録が必要です。未登録なら画面上部に **REGISTER** が出ます。
- host は 127.0.0.1 でだけ待ち受けます。他のサイトのページからは操作できないように、Host / Origin と専用ヘッダー（`X-Orrery`）を確認しています。
- 状態は `%LOCALAPPDATA%\orrery-win\` に置かれます（`agents.json`、各エージェントの設定ファイル、`hub.db`）。ポートは `--port`、もしくは環境変数 `ORRERY_WIN_PORT` で変えられます。
- Claude Code の中（VS Code のパネルなど）から host を起動しても大丈夫です。親セッションの印になる環境変数（`CLAUDECODE` や `CLAUDE_CODE_SESSION_ID` など）は、子に渡す前に取り除きます。

## hub

- **DB**：`%LOCALAPPDATA%\orrery-win\hub.db`（環境変数 `ORRERY_HUB_DB` で変更可）。PC 上のすべてのエージェントがこの一つのファイルを共有します。テーブルは ORRERY Mail と同じ形の `agents` / `messages` / `message_recipients` と、ホワイトボード用の `board` です。
- **MCP サーバー**：[hub/mcp_server.py](hub/mcp_server.py)。外部パッケージは不要で、Python 3.11 以上で動きます。次のツールを提供します。

| ツール | 内容 |
|---|---|
| `send_message(to, subject, body, importance?, reply_to?)` | 名前で宛先を指定して送る。`reply_to` を付けると同じスレッドになる |
| `fetch_inbox(include_read?, limit?)` | 未読を全文で受け取り、既読にする |
| `read_thread(thread_id)` | スレッドを古い順に読む |
| `list_agents()` | 宛先にできるエージェントと、自分の名前 |
| `board_write(topic, text)` / `board_read(topic?)` | ホワイトボードへの追記と読み取り。`topic` を省くと topic の一覧 |

### 自分の名前

自分の名前は次の順で決まります。

1. 引数 `--agent NAME`
2. 環境変数 `ORRERY_AGENT`
3. どちらも無ければ、作業フォルダ名と CLI の種類から自動で付ける（例：`myproject-claude`、`myproject-agy`）

Claude Code も Antigravity も、自分の環境変数を MCP サーバーに引き継ぎます。なので、`ORRERY_AGENT` を設定した状態で CLI を起動すれば、その名前で参加できます。Phase 2 以降は host がこの環境変数を設定して起動します。

## 登録

`python` は、`where python` で表示される絶対パスにしておくと確実です。

**Antigravity**：MCP は全体設定として登録します。

```
agy mcp add orrery-hub C:\path\to\python.exe C:\path\to\orrery\windows\hub\mcp_server.py
```

ツールを呼ぶたびに許可を求められます。毎回の確認を省きたい場合は、`~/.gemini/antigravity-cli/settings.json` の `permissions.allow` に `mcp(orrery-hub/*)` を加えます（書式は `mcp(<server>/<tool>)`）。ヘッドレス（`-p`）では確認ができず拒否されるので、`--settings '{"permissions":{"allow":["mcp(orrery-hub/*)"]}}'` のように渡します。

**Claude Code**：全体に登録する場合です。

```
claude mcp add -s user orrery-hub -- C:\path\to\python.exe C:\path\to\orrery\windows\hub\mcp_server.py
```

一回だけ試す場合は、`--mcp-config <json> --strict-mcp-config --allowedTools mcp__orrery-hub` で渡せます。全体設定は変わりません。

## 手で使う

人も `--as` で名前を名乗ればやり取りに参加できます（初めて使う名前はその場で登録されます）。

```
python windows\hub\cli.py agents
python windows\hub\cli.py send --as me --to alice,bob "件名" "本文"
python windows\hub\cli.py inbox --as me
python windows\hub\cli.py thread 1
python windows\hub\cli.py board
python windows\hub\cli.py post --as me plan "今日の方針"
```

## テスト

```
python -m pytest windows/tests -q
```

host のテスト（[tests/test_host.py](tests/test_host.py)）は、本物の CLI の代わりに小さな Python プログラムを ConPTY で起動して、入力の往復、再接続したときの流し直し、停止を確かめます。このテストは Windows と pywinpty が必要です。今の CI（ubuntu）は、このディレクトリのテストを実行しません。
