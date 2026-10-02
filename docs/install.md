# インストール

> English version: [en/install.md](en/install.md)

[README に戻る](../README.md) · [次: 設定](configuration.md)

## 1 行で入れる・更新する

Mac のターミナル、または Windows では WSL2 の Ubuntu の中で、次の 1 行を打ちます。orrery-telemetry と cockpit の両方が入り、動作の確認（doctor と、Mail の往復を試す selftest）まで済ませてから、cockpit が起動して URL が出ます。すでに入っている人では、同じ 1 行が更新になります（telemetry だけ・古い版・setup.sh の無い従来の版・detached でも）。

```bash
curl -fsSL https://raw.githubusercontent.com/gyroid-eth/orrery/master/scripts/get.sh | bash
```

- **何を信頼して何が動くか**: 信頼するのは GitHub の `gyroid-eth/orrery` と `gyroid-eth/orrery-telemetry` だけです（checkout の origin がこの URL と完全に一致しないときは、触らずに止まります）。動くのは `get.sh`、cockpit の `scripts/setup.sh`、orrery-telemetry の `scripts/install.sh`、必要なときだけ uv の公式 installer です
- **何も変えずに確かめる**: `curl -fsSL …/get.sh | bash -s -- --check`（前提と計画だけ）、`… | bash -s -- --dry-run`（加えて 4 項目の変更の preview）。どちらも HOME に何も書きません（必要な取得は一時 folder で行い、終われば消します）
- **終了コードで判定する CI や script** では、`curl | bash` は取得の失敗を 0 と返すことがあるので、`curl -fsSL …/get.sh -o get.sh && bash get.sh --yes` のように保存してから実行します
- 前提（git・tmux・curl・uv・Python 3.11 以上）はまとめて確かめます。git・tmux・curl が足りなければ入れる 1 行を出して、何も変えずに止まります。uv と Python は sudo なしで入れられるので計画に入れます（shell の設定 file は変えません）
- 変更の前に計画を 1 画面にまとめ、**`yes` と打って Enter** で 1 回だけ承認します。変わるのは 4 つです: `~/.claude.json`（MCP）、`~/.claude/settings.json`（hooks と permissions）、`~/.codex/AGENTS.md`（Codex の全作業に効く global な block）、project の `CLAUDE.md`（block）。どれも先に backup を取ります。各変更ごとに preview を見て答えたいときは `--ask-each`、計画を読んだうえで質問を省くときは `--yes` を付けます（`… | bash -s -- --ask-each`）
- 初回は agent に作業させる folder を聞きます（Enter で `~/orrery-work`）。`--project-key PATH` でも渡せます
- 確認は doctor の終了コードで判定します（0 以外なら、出力を画面に出して ready とは言いません）。更新が失敗して「今の版のまま起動」を選んだ run も ready とは言わず、最初の記録を残します
- 最後に、4 項目が「適用した／すでに同じ／skip」のどれだったか、Mail を新しく入れたか動いているものを使い続けたか、doctor と selftest の結果を出します。Claude Code か Codex が無ければ「基盤のみ準備済み」と出ます
- すでに cockpit が動いていて版が違うときは、止めずに「その窓で Ctrl-C して起動し直す」と案内します
- **失敗したとき**: 承認の前の検査で止まったときは、setup は何も変えていません（ただし入口の `get.sh` がその前に行ったこと、つまり新しく取得した cockpit の checkout、または従来版の `.git` への取得は残り、画面にそう出ます）。承認の後に失敗したときは**巻き戻しません**。最初の試みの時点と今とで何が変わったかを表で出し、続きから進める 1 行を出します（その表の「最初」は、すべての確認が通るまで上書きされません。`~/.orrery-install/`）。前の版に戻すコマンドは用意していません
- 新しく入れたものを取り除くときは、表示された `<orrery-telemetry の checkout>/scripts/uninstall.sh` を使います（Mail の DB は `--purge-data` を付けない限り残ります。2 つの checkout・uv・Python も残ります）。**更新の取り消しには使わないでください**（既存の環境ごと取り除きます）

以下は、手で 1 段ずつ入れる手順です。

## はじめて入れる人へ（ブラウザで使う・Mac / Windows WSL2）

この節だけで、自分の Mac または Windows（WSL2）に ORRERY cockpit を入れ、ブラウザで開くところまで進めます。デスクトップアプリ（`ORRERY.app`）は使いません。Mac でもブラウザで開きます。アプリの build や常駐は、この節の後ろの「動作環境」以降を参照してください。

### 0. 先に orrery-telemetry を入れる

ORRERY cockpit は、エージェント一覧・NEW AGENT（spawn）・Mail・利用枠を [ORRERY Telemetry](https://github.com/gyroid-eth/orrery-telemetry)（repository は orrery-telemetry。旧名 AgentStack で、環境変数 `AGENTSTACK_*` と `~/.agentstack` にその名残がある）から読みます。**orrery-telemetry の [インストール手順](https://github.com/gyroid-eth/orrery-telemetry/blob/master/docs/install.md) を最後まで済ませてから**、この先に進んでください。Windows の人は、その文書の「Windows（WSL2）で入れる」節に従い、WSL2 の Ubuntu の中に入れます。

cockpit は orrery-telemetry の最新の release に合わせて作っています。**すでに入れている人も、先に orrery-telemetry を最新にしてください**（orrery-telemetry の repository で `git pull` のあと `./scripts/install.sh`。cockpit を入れた後は、手順 5 の `./scripts/update.sh` で両方をまとめて更新できます）。古い版のままだと、終了した Codex の agent の再開ができないなど、cockpit の一部が動きません。

手順 2 の `scripts/start-cockpit.sh` は、起動のたびに次の 2 つを確かめます。どちらも起動は止めません。

- **必要な世代か**: dashboard の `/api/version` の `api`（cockpit が頼る API の世代）が cockpit の必要とする値より小さい・無い・読めないときは、`WARN` と更新のコマンド（手順 5 の `scripts/update.sh`）を出す
- **新しい版が出ているか**: GitHub で orrery-telemetry の最新の release を調べ、手元より新しければ `note` で知らせる。結果は 1 日、venv の folder（`bridge/.venv`）に覚えておく。ネットにつながらない・遅いときは何も出さない。調べないようにするには `ORRERY_NO_UPDATE_CHECK=1` を付けて起動する

次の 4 つがそろっていれば準備完了です。

- `~/.agentstack/bin/agentstack-doctor` が問題を報告しない
- ブラウザで `http://127.0.0.1:8770/` を開くと orrery-telemetry の dashboard が表示される
- `curl -s http://127.0.0.1:8770/api/version` に `"api": 2` 以上がある。1 は、この仕組みより前のすべての版（`version` が [最新の release](https://github.com/gyroid-eth/orrery-telemetry/releases/latest) と同じならなおよい）
- Claude Code か Codex CLI にログイン済み（`claude` を起動して `/login`、または `codex login`）。Windows では **Ubuntu の中に入れたもの**にログインします。Windows 側に入れたものは使われません

### 守ること: 同じマシン・同じユーザー・同じ tmux

cockpit は、orrery-telemetry が起動したエージェントの tmux セッションを直接見に行きます。そのため、次をすべて同じにします。

- **同じ OS 環境**: Windows では、orrery-telemetry を入れたのと同じ WSL2 の Ubuntu。Mac では同じ Mac
- **同じユーザー**: orrery-telemetry を入れたユーザーのまま（`sudo` や別ユーザーで cockpit を起動しない）
- **同じ tmux server**: エージェントは `agent-start` / `agent-start-codex` か cockpit の NEW AGENT で起動する。`tmux -L 名前` や `TMUX_TMPDIR` で別の tmux server を使わない

### 1. ORRERY を手元に置く

repository を取得します。

```bash
git clone https://github.com/gyroid-eth/orrery.git orrery
cd orrery
```

repository が公開される前は、招待を受けた GitHub アカウントでしか取得できません。

Windows では、**Ubuntu のプロンプト（`user@PC:~$`）で**打ちます。置き場所は Ubuntu の home の下（例: `~/orrery`）にします。`/mnt/c/...`（Windows のドライブ）の下は遅く、権限の扱いも違うので避けます。

### 2. 起動 script を走らせる

repository の中で:

```bash
./scripts/start-cockpit.sh
```

script は 1 回で次を行います。

1. 前提の確認（Python 3.10 以上・tmux・orrery-telemetry の設定・project key・dashboard の応答。orrery-telemetry の版が古ければ警告だけ出す）
2. `bridge/.venv` に Python の環境を作り、`bridge/requirements.txt` の package を入れる（初回だけ時間がかかります。2 回目からは変更が無ければ飛ばします）
3. orrery-telemetry の設定（`~/.agentstack/env.sh` の project key・Mail DB・dashboard の port）を引き継ぐ。`~/.agentstack` や `~/.orrery` の設定 file は書き換えません
4. backend を**この窓の中で**起動し、応答を確かめてから開く URL を表示する

うまくいくと、最後に次のように表示されます。

```text
==============================================================
  ORRERY cockpit is running. Open this URL in your browser:

    http://127.0.0.1:8791/cockpit.html
...
==============================================================
```

### 3. ブラウザで開く

表示された `http://127.0.0.1:8791/cockpit.html` をブラウザで開きます。

- Mac: Safari や Chrome で開きます
- Windows: **Windows 側の** Edge や Chrome で開きます。WSL2 の `127.0.0.1` は Windows 側に転送されるので、そのまま届きます

左の一覧にエージェントが出ていなければ、cockpit の NEW AGENT から起動するか、別の窓で `~/.agentstack/bin/agent-start /path/to/your-project`（Codex なら `agent-start-codex`）を実行します。

### 4. 止める・次に起動する

- 止めるときは、script を動かしている窓で `Ctrl-C` を押します。窓を閉じても止まります
- **起動した窓は開いたままにします。** cockpit はその窓の中で動いています（常駐はしません）
- Windows では、Windows Terminal から起動した agent・dashboard・Mail は、Ubuntu の窓を閉じても裏で動き続けます。使い終わって WSL のメモリを Windows に返したいときは、PowerShell で `wsl --shutdown` を打ちます。その後や PC の再起動の後に使うときは、Ubuntu を開き、`~/.agentstack/bin/agentstack-doctor` で状態を見て、止まっていれば `~/.agentstack/dashboard/agentctl.sh start` と `~/.agentstack/bin/agentstack-mailctl start` で起動してから、もう一度 `./scripts/start-cockpit.sh` を実行します

### 5. 更新する

cockpit の folder で次を実行します。orrery-telemetry と cockpit が 1 回で最新になります。

```bash
./scripts/update.sh
```

終わったら、cockpit を動かしている窓で `Ctrl-C` を押し、`./scripts/start-cockpit.sh` をもう一度実行します。

#### 詳しく

- 先に orrery-telemetry を更新します。入れた場所で `git pull --ff-only` と `./scripts/install.sh` を実行します。
- 次に cockpit で `git pull --ff-only` を実行します。
- 前回の設定はそのまま使います。project key、dashboard の port、Mail の URL などは `~/.agentstack/env.sh` から読みます。
- いまの shell で設定している値があれば、そちらを使います。
- Codex の plugin を入れていれば、その更新もします。
- 最後に、orrery-telemetry の版と cockpit の commit を表示します。
- 次のどれかにあたると、理由を表示して何も変えずに止まります。commit していない変更がある、更新で上書きされる未追跡のファイルがある、fast-forward できない、remote に届かない。
- orrery-telemetry の `install.sh` が失敗したときは、cockpit は更新しません。
- `./scripts/update.sh --dry-run` は、何をするかを表示するだけで、何も変えません。
- `bridge/requirements.txt` が変わっていれば、次に起動したときに `start-cockpit.sh` が package を入れ直します。
- dashboard が応答しないときは、`~/.agentstack/bin/agentstack-doctor` で状態を見て、`~/.agentstack/dashboard/agentctl.sh start` で起動します。
- 手で更新するときは、orrery-telemetry で `git pull` と `./scripts/install.sh` を実行してから、cockpit で `git pull` を実行します。Codex の plugin の更新は、orrery-telemetry の [docs/codex-app.md](https://github.com/gyroid-eth/orrery-telemetry/blob/master/docs/codex-app.md) にあります。

### 足りないものがあるとき

script は前提をまとめて確かめ、足りないものを `NG` の行で示し、何も起動せずに止まります。`NG` の下の `Fix:` に直し方が出ます。

| 表示（抜粋） | 意味と直し方 |
| --- | --- |
| `Python 3.10 or newer is required.` | Python が古いか無い。Mac は `brew install python@3.13`、Ubuntu は `sudo apt install python3`。特定の Python を使うなら `ORRERY_PYTHON=/path/to/python3 ./scripts/start-cockpit.sh` |
| `tmux is not installed.` | Mac は `brew install tmux`、Ubuntu は `sudo apt install tmux` |
| `orrery-telemetry is not installed` | `~/.agentstack/env.sh` が無い。手順 0 の orrery-telemetry を先に入れる |
| `No project key is configured.` | orrery-telemetry の installer を `--project-key /absolute/path/to/your-project` 付きで入れ直す |
| `Something answers at ..., but it is not the orrery-telemetry dashboard.` | dashboard の port で別の program が応答している。`agentstack-doctor` で dashboard の状態と port を確かめる |
| `The orrery-telemetry dashboard does not answer` | `agentstack-doctor` で状態を見て、`agentctl.sh start` で起動する（表示されたコマンドをそのまま使えます） |
| `Port 8791 is used by another program.` | cockpit 以外の program が 8791 を使っている。`PORT=8796 ./scripts/start-cockpit.sh` のように別の port で起動し、表示された URL を開く |
| `cannot create a venv (ensurepip is missing)` | Ubuntu の Python に venv の部品が無い。表示どおり `sudo apt install python3.X-venv` を入れる（`uv` があれば script はそちらで作るので、この表示は出ません） |
| `Installing the Python packages failed` | network を確かめて、もう一度実行する |

`note` の行は止まる理由ではありません。たとえば `neither 'claude' nor 'codex' is on PATH` は、NEW AGENT でエージェントを起動できないという意味です。Claude Code か Codex CLI を入れてログインし、script を実行し直します。

すでに cockpit が同じ port で動いているときは、二重に起動せず、開く URL だけを表示して終わります。

前提の確認と Python 環境の準備だけを行い、backend を起動しない場合は `--check` を付けます。

```bash
./scripts/start-cockpit.sh --check
```

### Windows（WSL2）で違うところ

- WSL2 での動作は、Windows 11 と WSL2 の Ubuntu で確認中です（2026-09-28 時点）
- cockpit の中の「窓を開く」ボタンは、Mac の Ghostty の代わりに Windows Terminal（`wt.exe`）のタブを開きます。Windows Terminal が無ければ Microsoft Store から入れます
- ファイルや画像の貼り付けは WSL2 では使えません。通常のテキストの貼り付けは使えます
- `Cmd+K` などの shortcut は `Alt+K` などに変わります。違いの一覧は [使い方の「Windows（WSL2）での違い」](usage.md#windowswsl2での違い) を参照してください

## 動作環境

`ORRERY.app` の正式な利用対象は macOS です。Python backend は Unix / tmux を前提にしており、macOS 専用 guard はありません。ブラウザで開く使い方は Windows の WSL2（Ubuntu）でも確認中です（[はじめて入れる人へ](#はじめて入れる人へブラウザで使うmac--windows-wsl2)）。それ以外の OS は製品として保証していません。

必須:

- Python 3.10 以上
- `tmux`
- `pip` と `venv`
- runtime CDN に接続できるネットワーク

desktop app の開発・build 時:

- Node.js と npm
- Rust toolchain と Cargo
- Tauri v2 の platform prerequisites

全機能を使う場合:

- [ORRERY Telemetry](https://github.com/gyroid-eth/orrery-telemetry)
- ORRERY Mail SQLite
- Claude Code または Codex CLI を動かす tmux セッション

Node / Rust の version は repository で pin されていません。組織の標準 toolchain を使い、`npm ci` と Cargo build が通る組み合わせを固定してください。

## repository と Python 環境

repository を clone します。

```bash
git clone https://github.com/gyroid-eth/orrery.git
cd orrery
```

backend 専用 virtual environment を作ります。

```bash
python3 -m venv bridge/.venv
bridge/.venv/bin/python -m pip install --upgrade pip
bridge/.venv/bin/python -m pip install -r bridge/requirements.txt
```

主な Python dependency は次のとおりです。

| package | version range | 用途 |
| --- | --- | --- |
| `aiohttp` | `>=3.9,<4` | static / telemetry HTTP と WebSocket |
| `websockets` | `>=12,<16` | tmux control bridge |
| `Pillow` | `>=10,<12` | portrait helper |
| `pyte` | `>=0.8.2,<1` | terminal recorder / screen state |

## ORRERY Telemetry と接続する

ORRERY は既定で ORRERY Telemetry dashboard の URL `http://127.0.0.1:8770` を使用します。ORRERY Telemetry の `AGENTSTACK_PORT` を `8770` 以外にした場合は、backend の起動前に `ORRERY_DASHBOARD_URL` で接続先を指定します（末尾の `/` は無視されます）。

```bash
export ORRERY_DASHBOARD_URL=http://127.0.0.1:8780
```

`scripts/start-cockpit.sh` は、`ORRERY_DASHBOARD_URL` が未設定なら `~/.agentstack/env.sh` の `AGENTSTACK_PORT` から自動で設定します。`ORRERY.app` の sidecar は Finder 起動では shell の環境変数を読まないため、app と組み合わせる場合は `8770` のままにしてください。

両者で同じ absolute project key を設定します。

```bash
export AGENTSTACK_PROJECT_KEY=/absolute/path/to/your/project
export ORRERY_PROJECT_KEY="$AGENTSTACK_PROJECT_KEY"
```

ORRERY Mail DB が既定の `~/.agentstack/mail/storage.sqlite3` 以外にある場合は、ORRERY Telemetry の `AGENTSTACK_MAIL_DB` に加えて ORRERY 側も指定します。

```bash
export AGENTSTACK_MAIL_DB=/absolute/path/to/storage.sqlite3
export ORRERY_MAIL_DB="$AGENTSTACK_MAIL_DB"
```

ORRERY Telemetry を先に起動し、次を確認します。

```bash
curl -fsS http://127.0.0.1:8770/api/agents
```

ORRERY Telemetry が停止していても ORRERY の terminal、tmux inventory、local portrait、直接 SQLite を読める mail route は利用できます。roster、spawn、embedded TELEMETRY、REPLAY、dashboard control は縮退または停止します。

## backend を単体起動する

repository root から:

```bash
bridge/.venv/bin/python bridge/orrery_backend.py
```

または `bridge/` に移動して:

```bash
cd bridge
.venv/bin/python orrery_backend.py
```

既定の URL は次のとおりです。

```text
http://127.0.0.1:8791/cockpit.html
```

確認:

```bash
curl -fsS http://127.0.0.1:8791/telemetry/health
open http://127.0.0.1:8791/cockpit.html
```

`PORT` または `--port` で backend 単体の port は変更できますが、`ORRERY.app` は常に `:8791` を開きます。desktop app と組み合わせる場合は変更しないでください。`HOST` は `127.0.0.1` だけが許可されます。

## desktop app を build する

```bash
cd app
npm ci
npm run build
```

生成先:

```text
app/src-tauri/target/release/bundle/macos/ORRERY.app
```

現行 bundle は ad-hoc sign で、Developer ID signing と notarization は行いません。組織配布では自社の signing / notarization pipeline を追加してください。

開発起動:

```bash
cd app
npm ci
npm run dev
```

## sidecar の path を設定する

`ORRERY.app` は backend や venv を内包しません。`:8791` が応答しない場合、checkout 内の Python と script を detached sidecar として起動します。

Finder / LaunchServices から起動した app は shell の `~/.zshrc` や、そこで export した値を読みません。Finder 起動では共有設定 file に checkout root を保存します。

```json
{
  "orrery_root": "/absolute/path/to/orrery"
}
```

保存先は `~/.orrery/config.json` です。directory を作り、JSON のトップレベル object として保存してください。app は `orrery_root` から `bridge/.venv/bin/python` と `bridge/orrery_backend.py` を導出します。

解決順:

1. `ORRERY_BACKEND_PYTHON` / `ORRERY_BACKEND_SCRIPT`（各 path を個別に override）
2. `AGENTSTACK_ORRERY_ROOT` からの相対 path
3. `~/.orrery/config.json` の `orrery_root`
4. 未設定または path 不在なら actionable reason を log して offline page

env は app process が継承する開発起動や terminal 直起動での override です。

```bash
AGENTSTACK_ORRERY_ROOT=/absolute/path/to/orrery \
  /Applications/ORRERY.app/Contents/MacOS/ORRERY
```

Python または script が見つからない場合、app は bundled offline page を表示し、3秒ごとに `:8791` を再確認します。その場合は backend を手動で起動して Retry できます。sidecar は app window を閉じても生存するため、終了させる場合は process を明示的に管理してください。

## release bundle を確認・install する

repository root から dry-run を先に実行します。

```bash
./scripts/install-app.sh --dry-run
./scripts/install-app.sh
```

script は確認後に `rsync -a --delete` で `/Applications/ORRERY.app` を置き換えます。権限昇格は行わず、`codesign` と `open` の command は表示するだけです。必要なら `-y` で確認を省略できます。

## global hotkey

app は次の順に登録を試み、最初に利用できる key を採用します。

1. `Cmd+Shift+O`
2. `Cmd+Ctrl+O`
3. `Cmd+Alt+O`
4. `Cmd+Shift+F19`

すべて失敗しても app は起動します。採用された binding は startup log を確認し、hide / show を一度手動で検証してください。

## データの置き場所とアンインストール

`ORRERY.app` を削除するだけでは、関連する checkout、backend、履歴、ORRERY Telemetry、tmux session は削除されません。

| 対象 | 既定の場所 / 状態 | app 削除後 |
| --- | --- | --- |
| desktop app | `/Applications/ORRERY.app` | 削除される対象 |
| source checkout / venv | clone 先、`bridge/.venv` | 残る |
| ORRERY 共有設定 | `~/.orrery/config.json` | 残る |
| detached backend | `orrery_backend.py` process | app を閉じても生存し得る |
| terminal 履歴 | `~/.orrery/history` | 残る |
| prompt draft / 最大50件の履歴 | WebView / browser の `localStorage` | profile data として残り得る |
| font / layout / mini / NEW AGENT Advanced / colour theme 設定 | `~/.orrery/prefs.json`（backend が持ち、各 WebView / browser の `localStorage` に写す） | app window と browser tab で同じ値になる。localStorage 側にも残る |
| tmux sessions | 利用者の default tmux server | kill されず残る |
| ORRERY Telemetry / ORRERY Mail DB | それぞれの install / data path | ORRERY は削除しない |

削除前に session group を detach し、backend を停止してください。frontend は ORRERY が Claim した distinct window すべてへ release を送ってから detach し、backend も最後の peer detach / disconnect / teardown 時に tracked window だけを復元します。復元先は初回 Claim 直前の正確な grid size と local `window-size` option です。Claim せず attach / detach しただけの window には size command を発行せず、外部 client の manual 設定をそのまま保ちます。

復元に失敗した snapshot は後続経路での再試行用に保持されます。teardown でも復元できない場合は backend が session 名と window ID を stderr に記録するため、backend log と tmux の window option を確認してください。

任意データも消す場合は、対象を個別に確認してから削除します。

1. `ORRERY.app`
2. ORRERY の source checkout と `bridge/.venv`
3. `ORRERY_HISTORY_DIR`（既定 `~/.orrery/history`）
4. `~/.orrery/config.json`
5. ORRERY origin の WebView / browser localStorage

ORRERY Telemetry、ORRERY Mail DB、利用者の tmux session は共有基盤・利用者データです。ORRERY の uninstall 手順で削除しないでください。

## 関連文書

- [設定](configuration.md)
- [使い方](usage.md)
- [トラブルシューティング](troubleshooting.md)
- [アーキテクチャ概要](ARCHITECTURE_OVERVIEW.md)
- [実装アーキテクチャ](ARCHITECTURE.md)
