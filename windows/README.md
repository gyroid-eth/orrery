# ORRERY for Windows

ORRERY を Windows ネイティブ（WSL なし）で動かすための作り直しです。次のものができています。

- **hub**：エージェント同士がメールとホワイトボードでやり取りする
- **host**：Claude Code と Antigravity をブラウザから起動・操作できる
- **配送役**：メールが届いたら、待機中の宛先を自動で起こす
- **画面**：見た目を ORRERY に揃え、関係図と planetarium は元の cockpit のもの（[bridge/orrery_view.js](../bridge/orrery_view.js)）をそのまま使う

| Phase | 内容 | 状態 |
|---|---|---|
| 1 | hub：共通の SQLite と MCP サーバー | できた |
| 2 | host：ConPTY でエージェントを起動し、ブラウザの xterm で操作する | できた |
| 3 | 配送役：待機中の宛先に、PTY から通知を打ち込んで起こす | できた |
| 4 | 画面：roster とメール一覧の見た目を ORRERY に揃える | できた |
| 5 | 元の cockpit の関係図と planetarium を取り込む。フォルダ選択、名前の自動決定 | できた |

## 位置づけ

ORRERY 本体は、Windows では WSL2 の中で動きます（tmux と ORRERY Telemetry を使います）。この `windows/` は、WSL を使わずに Windows だけで動く別の実装です。

- **独立しています**：`windows/` の外のファイルは変えません（`.gitattributes` と `.gitignore` に一行ずつ足しただけです）。macOS 版や WSL2 版の動きには影響しません。
- **メールは別の仕組みです**：tmux と ORRERY Telemetry の代わりに、ConPTY を持つ host と、SQLite の hub（`windows/hub`）を使います。テーブルの形は ORRERY Mail に合わせていますが、WSL2 版や Mac 版のエージェントとはメールを交わせません。
- **元の画面部品を借ります**：関係図と planetarium は `bridge/orrery_view.js` と `orrery_view.css` を書き換えずに読み込み、Windows 側の窓口（[web/oc.js](web/oc.js)）から `window.OC` と `oc:agents` / `oc:mail` を渡します。元の図が更新されれば、そのまま入ります。
- **対応する CLI**：Claude Code と Antigravity CLI（`agy.exe`）。

## 画面

画面は ORRERY と同じ配色、フォント、部品の形で、三列に並んでいます。

- **ヘッダー**：**PLANETARIUM**（関係図の全画面表示）、作業中と待機中の数、人の判断待ちの数、時計
- **AGENT（左）**：絞り込み欄と、エージェントのカード
  - カードには、肖像画、エンジン（CLAUDE / ANTIGRAVITY）、作業フォルダ、状態が出ます。
  - 肖像画はリポジトリの public domain の肖像画（科学者 50 人）から選びます。科学者と同じ名前（例：`Curie`）ならその人の肖像、それ以外は名前ごとに決まった一枚です（[host/portraits.py](host/portraits.py)）。
  - 人の判断を待っているカードは点滅します。未読は琥珀色の数字、配送待ちは `✉ N` で出ます。
- **中央**：ターミナルと PROMPT 欄
  - PROMPT 欄に書いた内容は、⏎ で送られます。⇧⏎ で改行、Esc か ⊘ STOP で中断です。複数行は一つの貼り付け（bracketed paste）として送るので、途中の改行で送信されません。
  - ターミナルに直接打つと、配送役は「書きかけがあるかもしれない」と判断して通知を待ちます。PROMPT 欄から送ればその心配がありません。
- **AGENT MAIL（右）**：関係図、エージェントごとの絞り込み、メールのカード
  - 関係図は元の cockpit の `bridge/orrery_view.js` です。roster のエージェントが並び、新しいメールは彗星になって飛び、やり取りした組が 90 秒のあいだ線で結ばれます。作業中のエージェントには琥珀色の弧が回り、人の判断を待っていると `!` が出ます。
  - 図のエージェントを押すと、そのエージェントを開き、メールをそのエージェントに絞り込みます。
  - 図の右上の ⤢ かヘッダーの **PLANETARIUM** で、同じ図を全画面で開きます（Esc か外側のクリックで閉じます）。Windows 版には系譜（誰が誰を起動したか）がないので、全員が一列に並び、名前の下に作業フォルダ名が出ます。
  - メールのカードはクリックで本文を開きます。
- **NEW AGENT**：名前、CLI、作業フォルダを指定します。
  - 作業フォルダは **参照…** で Windows のフォルダ選択ダイアログから選べます。ページからはフォルダの完全なパスを知れないので、同じ PC で動く host がダイアログを開きます（Tk 8.6 の Explorer 形式）。
  - 名前を空にすると、肖像のある科学者から、まだ使われていない名前をランダムに付けます。ハブにだけ残っている名前（消したエージェントのメールが残っているもの）も避けます。
- `?agent=名前` を付けて開くと、そのエージェントが選ばれた状態になります。

## 配送役（待機中のエージェントを起こす）

host は、未読のメールがあるエージェントが待機中になると、そのターミナルに一行の通知を打ち込みます。例：`[ORRERY] New mail from bob: "件名". Call fetch_inbox to read it, then act on it.` と Enter。人が打ち込むのと同じなので、エージェントは自分で `fetch_inbox` を呼んで対応します。tmux の `send-keys` の代わりに、ターミナルを持っている host 自身が打ち込む形です。

**待機中かどうかの判断**

- **Claude Code**：起動時に `--settings` で hook を渡します（[host/hook.py](host/hook.py)）。`SessionStart` と `Stop` で待機中、`UserPromptSubmit` で作業中です。画面とは次のように組み合わせます。
  - 画面に `esc to interrupt` か確認画面が出ているときは、hook に関係なく作業中（確認画面なら人の判断待ち）です。
  - 画面のプロンプト欄（罫線のすぐ下の `❯` か `>` で始まる行）が見えていれば待機中です。Claude Code は同じ版でも、起動のしかたによって `❯` と `>` のどちらかを描きます。
  - 作業中の印もプロンプト欄も見えないときは、hook の言うとおりにします。描き方がまた変わっても、`Stop` が届けば待機中になります。
  - `Stop` が来ないままプロンプト欄が見えて 30 秒静かな場合は、待機中とみなします（中断したときなど）。
- **Antigravity**：hook がないので、画面で判断します。画面の下端が `? for shortcuts` なら待機中、`esc to cancel` なら作業中です。

**打ち込まない場面**（メールは未読のまま残り、失われません）

- 確認画面（フォルダの信頼、ツールの許可など）が出ているとき。Enter が選択肢を選んでしまうためです。roster では、人の判断待ちとして点滅します。
- 待機に入ってから、人がそのターミナルに文字を入力したとき。書きかけの指示に通知を付け足さないためです。次に待機に入ったときに通知します。
  - xterm の自動応答、矢印キー、マウスは入力として数えません。
- 1 時間に 30 回起こしたとき。エージェント同士が延々と返信し合うのを止めるためで、roster に **PAUSED** と出ます。
  - MCP の説明文でも、「お礼だけの返信はしない、終わったやり取りには返信しない」ようエージェントに伝えています。

配送待ちの通知は roster に `✉ N` と出ます。カーソルを合わせると待っている理由が分かります。

**通知のやり直し**

通知を打ち込んでも、エージェントが動けないことがあります。例えば Antigravity は、`Failed to start a conversation: backend returned an empty conversation id` で始められずにプロンプトへ戻ることがあります。そこで、通知から 60 秒たっても未読のままなら、待機中になったときに `[ORRERY] Unread mail from ...` ともう一度通知します。やり直しは一通につき 2 回までです（host を起動し直すと数え直し）。それでも読まれないメールは、未読のまま残ります。

**打ち込み方**

通知も PROMPT 欄の内容も、プログラムが bracketed paste を有効にしている（`ESC[?2004h`。Claude Code と Antigravity はどちらも有効）ときは、一つの貼り付けとして送り、少し間をおいて Enter を送ります。Claude Code は、続けて届いた入力を貼り付けとみなします。そのため、印のない長い文の直後に送った Enter が改行として取り込まれ、送信されないことがあったからです。

**記録の流し直し**

ブラウザで開き直したときの記録の流し直しは、ConPTY の大きさで描いてから自分の大きさに合わせます。ConPTY は自分の画面を描く命令を出しているので、大きさが違う端末にそのまま流すと崩れるためです。流し直す記録からは、端末への問い合わせ（カーソル位置など）を取り除きます。古い問い合わせへの答えが、今動いているプログラムに届かないようにするためです。複数のタブで同じエージェントを開いたときに自動応答を返すのは、最後に入力したタブか、大きさを変えたタブだけです。

## 始め方

[start.cmd](start.cmd) をダブルクリックします。host が起動し、既定のブラウザで http://127.0.0.1:8791/ が開きます。**NEW AGENT** から CLI（Claude Code / Antigravity）と作業フォルダ（**参照…** で選べます）を指定します。名前は空でもかまいません。プロジェクトのフォルダに置くファイルはありません。

- Python は 3.11 以上が必要です。`python`、`py -3` の順に、実際に動いて 3.11 以上のものを探します（Microsoft Store の仮の `python.exe` や古い Python は飛ばします）。決めたいときは環境変数 `ORRERY_PYTHON` に `python.exe` のパスを入れます。
- 必要なパッケージ（[requirements.txt](requirements.txt)）が無いか古いときは、その場で `pip install` します。
- 開いた黒い窓が host です。**窓を閉じると、host と、host が起動したエージェントがすべて終了します。** roster は残るので、次に起動したら **RESUME** で再開できます。
- host がもう動いているときに start.cmd を開くと、二つ目は起動せず、ページだけを開きます。
- host のオプションはそのまま渡せます（例：`start.cmd --port 8800`）。

手で起動する場合はこうです。

```
pip install -r windows\requirements.txt
python windows\host\server.py [--open]
```

- host が各エージェントのターミナル（ConPTY）を持ちます。ブラウザを閉じたり再読み込みしたりしても、エージェントは止まりません。開き直すと直近の出力が流し直されます。
- host を止めると、エージェントも終了します。roster は残るので、**RESUME** を押すとそのエージェント自身の会話から再開します。
  - 会話は ID で開きます（Claude Code は `--resume <id>`、Antigravity は `--conversation <id>`）。ID は roster（`agents.json` の `conversation`）に残します。
  - `--continue` は使いません。`--continue` はそのフォルダで一番新しい会話を開くので、同じリポジトリで VS Code のパネルなど別の Claude Code を使っていると、その会話をエージェントが乗っ取ってしまうためです（実際に起きました）。
  - Claude Code：初回の起動で host が ID を決めて渡します（`--session-id`）。`/clear` や `/resume` で会話が変わると、SessionStart の hook が新しい ID を知らせます。
  - Antigravity：ID を指定して始める方法がありません。最初のプロンプトを送ると会話のファイル（`~/.gemini/antigravity-cli/conversations/<id>.db`）ができるので、そのエージェントの作業フォルダの会話で、Enter を打ってから 30 秒以内にできたものをそのエージェントの会話とみなします。まだ一度もプロンプトを送っていないエージェントの RESUME は、新しい会話になります。
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
