# ORRERY for Windows

ORRERY を Windows ネイティブ（WSL なし）で動かすための作り直しです。今の段階は Phase 1 で、エージェント同士がメールとホワイトボードでやり取りする hub ができています。

| Phase | 内容 | 状態 |
|---|---|---|
| 1 | hub：共通の SQLite と MCP サーバー | できた |
| 2 | host：ConPTY でエージェントを起動し、ブラウザの xterm で操作する | これから |
| 3 | 配送役：待機中の宛先に、PTY から通知を打ち込んで起こす | これから |
| 4 | 画面：roster とメール一覧の見た目を ORRERY に揃える | これから |

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

今の CI（ubuntu）はこのディレクトリのテストを実行しません。
