# 稼働中の ORRERY Mail service を更新する

> English version: [agentstack-mail-update.en.md](en/agentstack-mail-update.md)

この文書は、すでに traffic を捌いている machine へ `agentstack_mail` の新しい
build を出荷する手順です。同梱 service が唯一の provider になって以降
`scripts/install.sh` が管理している配置を前提にしています。それ以前に
`cutover-maintenance/` の下で手作業していた配置は過去のものです。installer が
書くものはそれを読みませんが、かつてそれを使った machine には unit や pointer
file が残っていることがあるので、下の事前確認は「消えているはず」と仮定せず
探します。

**まず `--update-mail`。** installer は `--update-mail` を付けると、稼働中の
Mail をこの checkout の build に差し替えます（下の「[`--update-mail` による差し替え](#--update-mail-による差し替え)」）。
candidate の build、scratch port での検証、database の backup を稼働中の Mail を
止めずに済ませてから切り替え、新しい build が応答しなければ前の build に戻します。
付けない再実行（既定 `keep`）は差し替えず、差を `notice:` で示します。
`AGENTSTACK_MAIL_UPDATE=auto`（opt-in）は、安全に差し替えられるときだけ差し替え、
だめなら今の build を残して install を成功させます。
下の手動の手順は、`--update-mail` が拒否した配置を扱うときと、その各段階が何を
しているかを確かめるときのためのものです。

**適用範囲。** コマンドは既定の配置を前提にします。install dir は
`~/.agentstack`、`--install-dir` なし、install 時の `AGENTSTACK_MAIL_*` override
なし。custom install は対象外です。この文書が `env.sh` から読む値はあなたの
確認用の shell 変数であって installer には渡らず、installer は毎回の呼び出しに
自身の `--install-dir` と override を要し、`agentstack-mailctl` は `AGENTSTACK_HOME`
から `env.sh` を見つけます。そのどれもここでは検証していません。`env.sh` は
service root を `AGENTSTACK_MAIL_DIR` として記録しますが、installer の入力名は
`AGENTSTACK_MAIL_SERVICE_ROOT` です。

**実行済みの範囲。** 切替そのもの（unit の保持、停止、install、確認: 手順 5〜7）
は 2026-09-18 に稼働中の machine で、この手順の前の草稿を使って 1 回実行しました。
12 秒の outage はその run の値です。その後、事前確認（手順 0）と offline 検証
（手順 3）をここに書いたとおりに installed service に対して再実行し、手順 2 と
3 の停止条件は `uv`・`git`・`lsof` を stub にした無害な bash 対照で確かめました（親 shell に残った旧値、`git` の失敗、`lsof` の不在と失敗を含む）。
手順 4〜7 はその live run に基づきますが、ここに書いた形で通しては再実行して
いません。Rollback 節の手動の手順は installer の source から読んだもので、未実行です。
`--update-mail` は、一時 HOME・一時 state root・空き port の上で実 server を
起動する test（`tests/test_install_mail_update.py`）で、切り替え、前の build への
戻し、新しい build が応答しないときの自動 rollback、offline 検証の失敗で
止めないこと、を通しています。稼働中の machine ではまだ実行していません。

## installer がすること・しないこと

`install.sh` は毎回 hooks・skills・dashboard・`bin/`・`env.sh`・autostart unit を
更新します。ORRERY Mail については次のどちらか一方の経路を取ります。

- **設定された endpoint に何かが応答している。** installer はそれに
  `health_check` を送ります。答えに `database_url` があり、それが期待する state
  database に解決されれば listener を採用します。その render を `env.sh` に記録し、
  service には**触りません**。port が占有されているのに ORRERY Mail として答え
  ない、あるいは別の database を配信している場合は error で止まります。採用
  したあと、稼働中の build がこの checkout の build と違えば、既定（`keep`）では
  `notice:` で差を示すだけで、service には**触りません**。`--update-mail` と
  `auto` は下の差し替えに進みます（package の tree が同じ commit どうしなら、
  どれでも何もしません）。dashboard
  の `/api/version` は package の版であって、port の裏にある build ではありません。
- **何も応答していない。** installer は checkout の正確な commit で candidate を
  用意し（無ければ build、あるが不完全なら run を止める）、service env を render
  し、`agentstack-mailctl` で起動し、`env.sh` と autostart unit をその render に
  向け、配信される database が共有のものであることを確かめます。

したがって手動の更新とは「古い service を止めてから installer を走らせる」こと
で、その間に autostart unit が古い build を起こさないよう unit を押さえておきます。
差し替え（`auto` と `--update-mail`）はこの二つの経路の間を installer の中で行います。

## `--update-mail` による差し替え

```bash
./scripts/install.sh --print-mail-plan         # Mail をどうするかを 1 行で（読むだけ）
./scripts/install.sh --dry-run                 # 計画全体を表示する
./scripts/install.sh --update-mail             # 差し替える（できなければ exit 1）
AGENTSTACK_MAIL_UPDATE=auto ./scripts/install.sh   # 安全に差し替えられるときだけ（opt-in）
./scripts/install.sh                           # 差し替えない（既定 keep、--keep-mail と同じ）
```

| 指定 | 稼働中の build が違うとき | 差し替えられない・失敗したとき |
| --- | --- | --- |
| `AGENTSTACK_MAIL_UPDATE=auto`（opt-in） | 下の 1〜5 で差し替える。ただし `agentstack-mailctl` 管理の配置で、検証が通り、止まる時間の見込みが `AGENTSTACK_MAIL_UPDATE_OUTAGE_BUDGET`（既定 8 秒）以内のときだけ | 今の build を残し、warning を出して exit 0 |
| `--update-mail`（`AGENTSTACK_MAIL_UPDATE=update`） | 差し替える。止まる時間の予算は使わない（時期を人が選んだ） | exit 1 |
| なし、`--keep-mail`（`AGENTSTACK_MAIL_UPDATE=keep`） | 差し替えず、`notice:` で差を示す | — |

選び方は `--mail auto|update|keep`（`--mail=VALUE` も可）で、`--update-mail` と
`--keep-mail` はその別名です。option は `AGENTSTACK_MAIL_UPDATE` より優先します
（cockpit の update.sh は option で渡すので、外側の環境の値に負けません）。`AGENTSTACK_MAIL_UPDATE` は
毎回の指定で、`env.sh` には記録しません（一度選んだ値が以後ずっと効かないように）。
`auto` はまだ既定ではありません。既定にする前に、rollback まで含めた停止時間の
上限と、更新後の database で前の build が動くことの確認を入れます
（[設計メモ](https://github.com/gyroid-eth/orrery-telemetry/blob/master/docs/agentstack-mail-update-design.md)）。止まる時間の見込みは、
検証で candidate が database の snapshot に対して応答するまでの秒数に、停止と
health の待ちの分（1.5 秒）を足したものです。

最後に 1 行、機械が読む結果を出します。`--dry-run` では同じ欄を `mail-plan:` で
出します。値に空白は入らず、reason は固定の code です。

```text
mail-result: <installed|switched|kept|unchanged|refused|rolled-back> mode=<auto|update|keep> from=<commit> to=<commit> running=<commit> outage_s=<秒> reason=<code>
mail-plan: <install|switch|keep|unchanged|refuse> mode=<…> running=<commit> to=<commit> reason=<code>
```

`from` はこの run の前に動いていた build（無い・特定できないときは空）、`to` は
この checkout の build、`running` は今動いている build です（switched / installed
なら `to`、それ以外は `from`）。rollback の失敗、`--update-mail` の拒否、中断では
行を出さずに非 0 で終わります。読む側は、行が無いことを失敗として扱ってください。

reason の code: `no_running_mail`、`newer_build`、`same_candidate`、`same_package`、
`keep_default`、`keep_requested`、`not_mailctl_managed`、`deployment_unidentified`、`verify_failed`、
`outage_over_budget`、`outage_unknown`、`backup_failed`、`start_failed_rolled_back`、`adopted`、
（`--print-mail-plan` だけ）`plan_unavailable`。`--print-mail-plan` は pidfile・
render・git だけを読み、project key がなくても、何が起きても exit 0 で 1 行を
出します。計画であって約束ではありません（実際の run は検証のうえで残すことがあります）。

採用経路で稼働中の deployment を特定したあと、この checkout の candidate
（`candidates/<commit>/venv`）が稼働中のものと違えば、次の順に進みます。
1〜4 の間、稼働中の Mail は止まりません。

1. **candidate を用意する。** 完全なものがあれば再利用し、無ければ clean な
   commit から build します（不完全なら止まる）。新しい render を書きます。
2. **offline で検証する。** SQLite の backup API で共有 database の snapshot を
   `/tmp/orrery-mail-verify.*`（mode 700）に取り、空の process 環境で
   candidate を空き loopback port（`AGENTSTACK_MAIL_UPDATE_VERIFY_PORT` で固定可）に
   起動します。その port が使用中か、稼働中の Mail の port と同じなら、何も起動せず
   `not-switched` で終わります。そこにいる何かの health を candidate のものと
   読まないためです。scratch の service env は
   本番の render と同じ関数から作るので、database・archive・signals・管理
   socket はすべて scratch を指します。`/mcp` と `/api` の両方の `health_check`
   が scratch の database を返すこと、起動時の DDL が既存の table・column・
   index・trigger を消したり定義し直したりしていないこと、`PRAGMA quick_check`
   が `ok` であることを確かめます。待っている間は 10 秒ごとに経過を表示します。
   snapshot は成否に関わらず削除し、server log だけを
   `mail-service/runtime/mail-update-verify.log` に残します。検証中に Ctrl-C や
   SIGTERM で止めても、scratch の server を止めて snapshot を消してから終わり
   ます（終了 status 130。稼働中の Mail は止めていない）。
3. **database を backup する。** `mail-service/backups/storage-<UTC>-before-<commit>.sqlite3`
   （mode 600）。直近 3 個を残します（`AGENTSTACK_MAIL_UPDATE_BACKUPS`）。
   自動で戻すのは build だけで、database は戻しません。backup は、新しい build
   が data を壊したと分かったときに人が判断して使うためのものです。
4. **切り替える。** `agentstack-mailctl stop` で前の runner を止め（stop marker が
   autostart の sweep を押さえる）、新しい render で `agentstack-mailctl start`
   します。endpoint の health が共有 database を返し、pidfile が新しい runner を
   指すことを確かめます。
5. **応答しなければ戻す。** 新しい runner を止め、前の render で start し直し、
   同じ確認をします。前の candidate・render・runner は不変で、書き換えていません。

そのあと `env.sh`、autostart unit、`connections/local.json`、`install-state.json`
を、実際に稼働している方の deployment で書きます。`install-state.json` の
`agent_mail.update` に結果（`switched`・`rolled-back`・`not-switched`）、理由と
その code、mode、実際に止まっていた秒数（`outage_seconds`）、前後の render と
candidate、backup の path を記録します。

| 結果 | Mail | 終了 status（`auto`） | 終了 status（`--update-mail`） |
| --- | --- | --- | --- |
| `switched` | 新しい build | 0 | 0 |
| `not-switched`（1〜3 で失敗、または止まる時間の見込みが予算超え） | 前の build。止めていない | 0（warning） | 1 |
| `rolled-back`（4 で失敗し 5 が成功） | 前の build。数秒〜 grace 分の停止あり | 0（warning） | 1 |
| rollback 失敗 | 停止中の可能性。error が状態と次の操作を示す | 1（その場で終了） | 1（その場で終了） |
| 切り替え中に中断（Ctrl-C・SIGTERM・端末を閉じる） | `env.sh` がすでに新しい build を指していればそのまま、でなければ前の build に戻す | 130 | 130 |

`not-switched` と `rolled-back` でも installer の残りは前の build に対して完了
します。`--update-mail` の終了 status 1 は「頼まれた更新は起きていない」ことを
示します。`auto` では更新は頼まれていないので 0 で終わり、warning と結果行で
知らせます。

**前の build に戻す。** 前の candidate を pin して同じ操作をします。render は
同じ入力から同じ path になり、そのまま再利用されます。

```bash
AGENTSTACK_MAIL_CANDIDATE_ID=<前の commit> \
AGENTSTACK_MAIL_SERVICE_VENV=~/.agentstack/mail-service/candidates/<前の commit>/venv \
  ./scripts/install.sh --update-mail
```

**影響を受けるもの・受けないもの。**

- **接続。** server は stateless HTTP なので、切り替えは session を失いません。
  停止から新しい server の応答までの間（前回の手動 run で 12 秒）に届いた
  request は接続拒否になります。戻り方は client で違います（2026-10-02 に一時
  HOME・別 port で測定）。launcher が bind した stdio proxy（子の Claude と
  Codex）は呼び出しごとに接続するので、次の呼び出しから戻ります。top level の
  Codex（`~/.codex/config.toml` の `url`）は 71 秒止めても次の呼び出しで戻り
  ました。top level の Claude Code（`~/.claude.json` の `type: http`）は、止まって
  いた時間が 15 秒までなら自動で戻り、18 秒以上では戻らず、`/mcp` から
  orrery-mail を reconnect する必要がありました。installer は実際に止まっていた
  秒数と、動いている Claude Code の session ごとに確かめる手順（`/mcp` で
  orrery-mail が connected か、health_check などの小さい呼び出しが通るか）を、
  止まった時間の長さに関わらず毎回出します。止まっている間に失敗と表示された
  Mail の操作は、server が実行した後で返事だけ失われた場合があるので、繰り返す
  前に実行済みかを確かめてください（送信は相手の inbox や送信履歴、登録は
  `whois`、spawn・resume は dashboard）。文の正本は `scripts/install.sh` の
  `mail_update_reconnect_hint` で、setup.sh も同じ文を出します。installer の health check や
  selftest は Mail が応答することの確認で、すでに動いていた session の接続が
  戻ったことの確認ではありません。
- **token と credential。** agent の token は共有 database にあり、client 側の
  file（`~/.agentstack/runtime` など）には触れません。build が変わっても変わり
  ません。
- **稼働中の session と bound proxy。** 再起動も再登録も要りません。test では、
  切り替え前に登録した agent が同じ owner token で切り替え後も送受信でき、
  違う token は拒否されることを確かめています。launcher が bind した proxy の
  `runtime_status` は `state: "bound"`・`agent_id: null` を返します。これは
  binding があることだけを示し、Mail には問い合わせていません。Mail に届くか
  どうかは、`fetch_inbox` などを実際に呼んで確かめてください（2026.09.30.4
  以前の proxy は、同じ場合に平常時から `state: "registering"` を返していました。
  これも止まっている証拠ではありません）。
- **systemd の timer（WSL2 など）。** unit は `env.sh` を読んで
  `agentstack-mailctl start` を実行するだけで、render の path を持ちません。
  切り替え後に timer が発火しても新しい build を見つけて何もしません（test で
  unit の command をそのまま実行して確認）。
- **enrollment。** `server_instance_id` は database の `mail_instances` にあるので
  同じ値のままです。`connections/local.json` の `expected_server_instance_id`
  は保持し、`mail_env` だけを新しい render に書き換えます。管理 socket の path
  は state root から決まるので同じです。
- **database・archive・signals。** 同じ state root を使い続けます。新しい build の
  起動時の DDL は追加だけを許し、既存の table・column・index・trigger を消すか
  定義し直す build は検証で止まります。
- **autostart。** 切り替え中は stop marker が sweep を押さえ、`start` がそれを
  外します。unit は `env.sh` を読むので、installer が `env.sh` を書き換えた時点で
  新しい render を起動するようになります。

**扱わないもの。** `agentstack-mailctl` が起動した runner（pidfile が生きた
runner を指す）だけを差し替えます。deployment を特定できない listener と
launchd が直接 supervise する service は対象外で、何も止めません。`--update-mail`
は error で終わり、`auto` は今の build を残して続けます（`refused`）。state root・service root・endpoint の override（`AGENTSTACK_MAIL_*`、
`AGENTSTACK_MCP_URL`）は同じ経路で扱い、test もこれらを override して実行して
います。既定以外の `--install-dir` も拒否はしませんが、それ自体は test して
いません。

時間の上限: 検証 server の応答待ち `AGENTSTACK_MAIL_UPDATE_VERIFY_TIMEOUT`
（既定 120 秒）、新しい build の起動待ち `AGENTSTACK_MAIL_UPDATE_START_GRACE`
（既定は controller の `AGENTSTACK_MAIL_START_GRACE`、180 秒）。rollback の起動は
controller の既定の grace で待ちます。`auto` が差し替える止まる時間の見込みの
上限 `AGENTSTACK_MAIL_UPDATE_OUTAGE_BUDGET`（既定 8 秒）。

## 配置

これらは installed の `env.sh` から解決します。仮定で決めないでください。state
root の既定は install dir と独立に `~/.agentstack/mail` で、endpoint・label
prefix・各 root はどれも設定可能です。

| `env.sh` の変数 | 意味 |
| --- | --- |
| `AGENTSTACK_MAIL_DIR`（service root） | `candidates/<commit>/venv`: 不変の candidate。正確な commit ごとに 1 つの venv で、`packages/agentstack_mail` から `uv` で build する。`renders/<commit>-<id>/service.env` と `run-agentstack-mail.sh`: (commit, venv, endpoint, state root) の組ごとに 1 つの render。id はちょうどその入力の hash なので、同じ入力は同じ directory を指し、installer は既存の render を書き換えることを拒否する。`runtime/agentstack-mail.pid`（2 行: runner の pid と runner の path）と `runtime/agentstack-mail.log` |
| `AGENTSTACK_MAIL_STATE_ROOT`（state root） | `storage.sqlite3`（WAL mode）、`archive/`、`signals/`。共有 state で、どの candidate にも属さず、deployment をまたいで固定 |
| `AGENTSTACK_MAIL_ENV` | controller と autostart unit が起動する render |
| `AGENTSTACK_MCP_URL` | endpoint。その port を見る |
| `AGENTSTACK_PYTHON` | candidate を build する interpreter |

autostart unit は `<label prefix>.mail`（`AGENTSTACK_LABEL_PREFIX` 未設定なら
`org.agentstack.mail`）です。macOS では 300 秒ごとの launchd job、systemd では同名
の `.timer` で、`agentstack-mailctl start` を実行し、それは `env.sh` を読みます。
installer が管理する範囲に第二の supervisor はありません。旧配置の残骸は事前
確認で探します。

## 原則

- **candidate は不変。** 新しい build は新しい `candidates/<commit>` directory。
  既存の candidate に `uv venv` や `pip install` を再実行しない。前のものは disk に
  手つかずで残り、それが rollback です。
- **database は共有 state。** 起動時に schema を変える build には専用の
  migration plan が要り、ここでは扱いません。始める前に
  `packages/agentstack_mail/src` の tree diff に DDL が無いことを見ます。
- **切り替える前に検証する。後ではない。** 停止より前のことはすべて、隔離した
  process 環境で、scratch port と database の一貫した snapshot に対して行います。
- **どの build が応答しているかは port に聞く。** `launchctl print` でも pidfile
  でも自分のメモでも package の版でもなく。

## 手順

各手順は shell 関数です。定義してから `step_N || echo "step N failed"` の形で
呼び、最初の失敗で止めてください。関数は最初に失敗した確認で非 0 を返し、その
後ろは何も実行しません。手順を 1 つの長いブロックにしていないのはそのためです。
`bash` で実行してください。事前確認は `zsh` でも確かめています。

0. **事前確認: installed の値を読む。** `env.sh` は `shlex.quote` で書かれている
   ので、右辺は shell に unquote させます。何も漏れないよう subshell で行います。
   必須の値はすべて存在しなければなりません。

   ```bash
   INSTALL=~/.agentstack
   REPO=<deploy する commit の汚れのない checkout>
   port_free() {  # 0 only when lsof ran and found no listener on TCP port $1
     local out err rc
     command -v lsof >/dev/null 2>&1 || { echo "lsof is not installed" >&2; return 1; }
     err=$(mktemp) || return 1
     out=$(lsof -nP -iTCP:"$1" -sTCP:LISTEN 2>"$err"); rc=$?
     if [ -s "$err" ]; then echo "lsof failed:" >&2; cat "$err" >&2; rm -f "$err"; return 1; fi
     rm -f "$err"
     [ $rc -ne 0 ] || { echo "port $1 is occupied:" >&2; echo "$out" >&2; return 1; }
     [ $rc -eq 1 ] && [ -z "$out" ] || { echo "lsof exited with status $rc without an error message; not treating port $1 as free" >&2; return 1; }
   }
   listener_pid() {  # prints the pid listening on TCP port $1; fails when there is none or lsof failed
     local out err rc pid
     command -v lsof >/dev/null 2>&1 || { echo "lsof is not installed" >&2; return 1; }
     err=$(mktemp) || return 1
     out=$(lsof -nP -iTCP:"$1" -sTCP:LISTEN 2>"$err"); rc=$?
     if [ -s "$err" ]; then echo "lsof failed:" >&2; cat "$err" >&2; rm -f "$err"; return 1; fi
     rm -f "$err"
     [ $rc -eq 0 ] || { echo "nothing is listening on port $1" >&2; return 1; }
     pid=$(printf '%s\n' "$out" | awk 'NR>1{print $2; exit}')
     [ -n "$pid" ] || { echo "lsof reported a listener on port $1 but no pid could be read" >&2; return 1; }
     printf '%s\n' "$pid"
   }
   step_0() {
     local assignments
     [ -f "$INSTALL/env.sh" ] || { echo "no env.sh under $INSTALL" >&2; return 1; }
     assignments=$(
       set +u
       unset AGENTSTACK_PYTHON AGENTSTACK_MCP_URL AGENTSTACK_MAIL_DIR AGENTSTACK_MAIL_STATE_ROOT AGENTSTACK_MAIL_ENV AGENTSTACK_LABEL_PREFIX
       . "$INSTALL/env.sh" >/dev/null || exit 1
       for k in AGENTSTACK_PYTHON AGENTSTACK_MCP_URL AGENTSTACK_MAIL_DIR AGENTSTACK_MAIL_STATE_ROOT AGENTSTACK_MAIL_ENV; do
         eval "v=\${$k:-}"; [ -n "$v" ] || { echo "env.sh does not define $k" >&2; exit 1; }
       done
       for k in AGENTSTACK_PYTHON AGENTSTACK_MCP_URL AGENTSTACK_MAIL_DIR AGENTSTACK_MAIL_STATE_ROOT AGENTSTACK_MAIL_ENV AGENTSTACK_LABEL_PREFIX; do
         eval "v=\${$k:-}"; printf '%s=%q\n' "$k" "$v"
       done
     ) || { echo "could not read the required values from $INSTALL/env.sh" >&2; return 1; }
     eval "$assignments"
     PY=$AGENTSTACK_PYTHON; SVC=$AGENTSTACK_MAIL_DIR; STATE=$AGENTSTACK_MAIL_STATE_ROOT
     OLD_ENV=$AGENTSTACK_MAIL_ENV; LABEL="${AGENTSTACK_LABEL_PREFIX:-org.agentstack}.mail"
     [ -x "$PY" ] || { echo "AGENTSTACK_PYTHON is not executable: $PY" >&2; return 1; }
     [ -f "$OLD_ENV" ] || { echo "current render env is missing: $OLD_ENV" >&2; return 1; }
     PORT=$("$PY" -c 'import sys,urllib.parse;print(urllib.parse.urlparse(sys.argv[1]).port or "")' "$AGENTSTACK_MCP_URL")
     [ -n "$PORT" ] || { echo "no port in AGENTSTACK_MCP_URL" >&2; return 1; }
     SHA=$(git -C "$REPO" rev-parse HEAD) || return 1
     echo "python=$PY service_root=$SVC state_root=$STATE port=$PORT label=$LABEL sha=$SHA"
   }
   step_0 || echo "step 0 failed"
   ```

1. **その commit で test suite を gate する**（dev venv、`CONTRIBUTING.md`
   参照）: `PYTHONPATH=. .venv/bin/python -m pytest -q` が汚れのない単発の run で
   green、かつ `packages/agentstack_mail/tests` も green。

2. **candidate を先に build する。** ただし既に完全なものがあれば触りません。
   これで outage に `pip install` が入りません。installer はこの path に完全な
   candidate があれば再利用し、不完全なものがあれば止まります。

   ```bash
   step_2() {
     local status
     V="$SVC/candidates/$SHA/venv"
     if [ -x "$V/bin/agentstack-mail" ] && [ -x "$V/bin/agentstack-mail-service" ] && [ -x "$V/bin/agentstack-mail-migrate" ]; then
       echo "candidate complete; not touching it"; return 0
     fi
     [ ! -e "$V" ] || { echo "candidate exists but is incomplete: $V" >&2; return 1; }
     status=$(git -C "$REPO" status --porcelain -- packages/agentstack_mail) || { echo "git status failed in $REPO" >&2; return 1; }
     [ -z "$status" ] || { echo "packages/agentstack_mail is dirty" >&2; return 1; }
     uv venv --python "$PY" "$V" || return 1
     uv pip install --python "$V/bin/python" "$REPO/packages/agentstack_mail" || return 1
     [ -x "$V/bin/agentstack-mail" ] && [ -x "$V/bin/agentstack-mail-service" ] && [ -x "$V/bin/agentstack-mail-migrate" ]
   }
   step_2 || echo "step 2 failed"
   ```

3. **candidate を隔離した環境で offline 検証する。** server は python-decouple で
   設定を読み、これは env file より process 環境を優先します。`env.sh` を
   source 済みの shell（あるいは `AGENTSTACK_MAIL_*` が 1 つでも入った環境）から
   起動すると scratch server が live の database を向きます。空の環境で起動
   します。database の snapshot は `cp` ではなく SQLite の backup API で取ります。
   live file は WAL mode で、main file だけの copy は commit 済みの page を欠く
   ことがあります。snapshot は credential を含むので private に保ち、終わったら
   削除します。

   live の render env を写したあと、場所を指す設定はすべて scratch に書き換えます。
   書き換えの対象から漏れた設定は live と同じ場所を指したままになり、scratch server
   が live の資源を開こうとします（enroll の管理 socket が加わったとき、これで
   `management socket is already active` と起動に失敗しました）。
   `scratch_env_isolated` は、書き換えずに写した行が実在するディレクトリの下を
   指していれば止めます。止まったら、その設定の書き換えを `sed` に足してください。

   ```bash
   probe() {  # probe <url> <tool> '<json arguments>'  → JSON-RPC の応答を出力
     "$PY" - "$1" "$2" "$3" <<'PY'
   import json, sys, urllib.request
   url, tool, args = sys.argv[1:]
   body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
           "params": {"name": tool, "arguments": json.loads(args)}}
   req = urllib.request.Request(url, data=json.dumps(body).encode(),
         headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream"})
   print(urllib.request.urlopen(req, timeout=15).read().decode())
   PY
   }
   scratch_env_isolated() {  # scratch_env_isolated <live env> <scratch env>
     # live から書き換えずに写した行が、実在する場所を指していたら 1 を返す
     local line key v d bad=0
     while IFS= read -r line; do
       case "$line" in AGENTSTACK_MAIL_*=*) ;; *) continue ;; esac
       grep -qxF -- "$line" "$1" || continue
       key=${line%%=*}; v=${line#*=}; v=${v#[\'\"]}; v=${v%[\'\"]}; v=${v#*:///}
       case "$v" in
         /*) d=$(dirname "$v")
             if [ "$d" != / ] && [ -d "$d" ]; then
               echo "scratch env still points $key at the live location $v; rewrite it to \$S" >&2; bad=1
             fi ;;
       esac
     done < "$2"
     return $bad
   }
   step_3() {
     local S SPORT=18799 SPID rc=1 r
     [ -x "$V/bin/agentstack-mail" ] || { echo "candidate server binary is missing: $V (run step 2)" >&2; return 1; }
     port_free "$SPORT" || return 1
     S=$(mktemp -d) || return 1
     chmod 700 "$S"; mkdir -p "$S/state/archive" "$S/state/signals"
     "$PY" - "$STATE/storage.sqlite3" "$S/state/storage.sqlite3" <<'PY' || { rm -rf "$S"; return 1; }
   import sqlite3, sys
   src = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True); dst = sqlite3.connect(sys.argv[2])
   src.backup(dst); dst.close(); src.close()
   PY
     sed -e "s#^AGENTSTACK_MAIL_HTTP_PORT=.*#AGENTSTACK_MAIL_HTTP_PORT=$SPORT#" \
         -e "s#^AGENTSTACK_MAIL_DATABASE_URL=.*#AGENTSTACK_MAIL_DATABASE_URL=sqlite+aiosqlite:///$S/state/storage.sqlite3#" \
         -e "s#^AGENTSTACK_MAIL_STORAGE_ROOT=.*#AGENTSTACK_MAIL_STORAGE_ROOT=$S/state/archive#" \
         -e "s#^AGENTSTACK_MAIL_NOTIFICATIONS_SIGNALS_DIR=.*#AGENTSTACK_MAIL_NOTIFICATIONS_SIGNALS_DIR=$S/state/signals#" \
         -e "s#^AGENTSTACK_MAIL_MANAGEMENT_SOCKET=.*#AGENTSTACK_MAIL_MANAGEMENT_SOCKET=$S/mgmt.sock#" \
         "$OLD_ENV" > "$S/service.env"
     grep -qE '^AGENTSTACK_MAIL_HTTP_HOST=(127\.0\.0\.1|localhost|::1)$' "$S/service.env" || { echo "scratch env is not loopback" >&2; rm -rf "$S"; return 1; }
     scratch_env_isolated "$OLD_ENV" "$S/service.env" || { rm -rf "$S"; return 1; }
     env -i HOME="$HOME" PATH=/usr/bin:/bin AGENTSTACK_MAIL_ENV_FILE="$S/service.env" \
       "$V/bin/agentstack-mail" > "$S/server.log" 2>&1 &
     SPID=$!
     for _ in $(seq 1 100); do
       kill -0 "$SPID" 2>/dev/null || { echo "scratch server exited early; see $S/server.log" >&2; return 1; }
       curl -s -o /dev/null --max-time 2 "http://127.0.0.1:$SPORT/api" && break; sleep 0.2
     done
     if r=$(probe "http://127.0.0.1:$SPORT/mcp" health_check '{}') && [ "${r#*$S/state/storage.sqlite3}" != "$r" ] \
        && r=$(probe "http://127.0.0.1:$SPORT/api" health_check '{}') && [ "${r#*$S/state/storage.sqlite3}" != "$r" ] \
        && r=$(probe "http://127.0.0.1:$SPORT/api" whois '{"project_key": "<live database にある project key>", "agent_name": "<そこにいる agent>"}') && [ "${r#*\"<そこにいる agent>\"}" != "$r" ] \
        && r=$(probe "http://127.0.0.1:$SPORT/api" health_check '{"nonce": "canary-value"}') && [ "${r#*canary-value}" = "$r" ] && [ "${r#*isError\":true}" != "$r" ] \
        && [ "$(grep -c canary-value "$S/server.log")" = 0 ]; then
       echo "candidate verified on scratch port $SPORT"; rc=0
     else
       echo "candidate failed offline verification; log kept at $S/server.log" >&2
     fi
     kill "$SPID" 2>/dev/null; wait "$SPID" 2>/dev/null
     [ $rc -eq 0 ] && rm -rf "$S"
     return $rc
   }
   step_3 || echo "step 3 failed"
   ```

   成功とは次のすべてです。両 path が scratch の `database_url` で `health_check`
   に答える。read が record を返す。拒否された呼び出しが、呼び手由来の値を含まない
   error を返し、scratch log にもそれが無い。1 つでも外れたら candidate は準備
   できておらず、手順はここで止まります。

4. **現在の deployment を記録し、installer を dry-run する。** すべて動いている
   うちに行います。dry run は exit 0 で、既存の service を再利用すると言わなければ
   なりません。それ以外なら live の状態はあなたの認識と違い、切替は待ちです。

   ```bash
   step_4() {
     local pid log
     pid=$(listener_pid "$PORT") || return 1
     echo "OLD candidate: $(ps -o command= -p "$pid")"          # この行を控える
     echo "OLD render:    $OLD_ENV"                              # この行を控える
     log=$(mktemp) || return 1
     ( cd "$REPO" && bash scripts/install.sh --scoped --dry-run ) > "$log" 2>&1 || { echo "dry run failed; see $log" >&2; return 1; }
     grep -q "would reuse existing ORRERY Mail service" "$log" || { echo "dry run did not plan to reuse the running service; see $log" >&2; return 1; }
     rm -f "$log"
   }
   step_4 || echo "step 4 failed"
   ```

5. **autostart unit を押さえる。** unit は `env.sh` が指すものを起動し、installer が
   `env.sh` を書き換えるまでそれは古い render です。あなたの停止と installer の
   起動の間に発火すると古い build が戻り、installer はそれを採用します。

   macOS:

   ```bash
   step_5() {
     launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null
     ! launchctl print "gui/$(id -u)/$LABEL" >/dev/null 2>&1 || { echo "$LABEL is still loaded" >&2; return 1; }
     ! grep -lE 'agentstack-mail-service|cutover-maintenance|current-deployment\.env' ~/Library/LaunchAgents/*.plist 2>/dev/null | grep . || { echo "older-layout units above must be disabled first" >&2; return 1; }
     ! crontab -l 2>/dev/null | grep -E 'agentstack-mail-service|cutover-maintenance|current-deployment\.env' || { echo "older-layout cron entries above must be disabled first" >&2; return 1; }
   }
   step_5 || echo "step 5 failed"
   ```

   systemd:

   ```bash
   step_5() {
     systemctl --user stop "$LABEL.timer"
     ! systemctl --user is-active --quiet "$LABEL.timer" || { echo "$LABEL.timer is still active" >&2; return 1; }
     ! systemctl --user list-units --all --no-legend 2>/dev/null | grep -E 'agentstack-mail-service|cutover-maintenance' || { echo "older-layout units above must be disabled first" >&2; return 1; }
     ! crontab -l 2>/dev/null | grep -E 'agentstack-mail-service|cutover-maintenance|current-deployment\.env' || { echo "older-layout cron entries above must be disabled first" >&2; return 1; }
   }
   step_5 || echo "step 5 failed"
   ```

6. **止めて、install する。** ここが outage window です。candidate を先に build した
   状態で 1 回測った値は、停止から ready まで 12 秒でした。`agentstack-mailctl stop`
   は自分が記録した managed runner に signal を送り、endpoint が答えなくなるまで
   待ちます。自分が起動していない process は止めません。

   ```bash
   step_6() {
     local log
     "$INSTALL/bin/agentstack-mailctl" stop || return 1
     port_free "$PORT" || return 1
     log=$(mktemp) || return 1
     ( cd "$REPO" && bash scripts/install.sh --scoped ) 2>&1 | tee "$log"
     [ "${PIPESTATUS[0]}" -eq 0 ] || { echo "installer failed; see $log" >&2; return 1; }
     ! grep -q "existing ORRERY Mail listener detected" "$log" || { echo "the old build came back during the window and was adopted: not deployed" >&2; return 1; }
     grep -q "candidate venv $SVC/candidates/$SHA/venv" "$log" || { echo "installer did not use candidate $SHA" >&2; return 1; }
     rm -f "$log"
   }
   step_6 || echo "step 6 failed"
   ```

   installer の出力に、この順で期待する行:
   `no native listener found`、
   `reuse immutable ORRERY Mail candidate venv .../candidates/$SHA/venv`、
   `render namespaced ORRERY Mail service env .../renders/$SHA-<id>/service.env`、
   `ORRERY Mail started (pid ..., ready after Ns)`、
   `ORRERY Mail will restart at login`。代わりに
   `existing ORRERY Mail listener detected` が出たら、窓の間に何かが古い build を
   起動して installer がそれを採用したということで、deployment は**起きていません**。
   何が起動したかを突き止め、もう一度止めて、この手順をやり直します。

   前の `env.sh` を source 済みの shell で構いません。installer が inherited の
   `AGENTSTACK_MAIL_ENV` を許すのは、installed の `env.sh` の値と等しく、service
   root の `renders/` の下にあり、`AGENTSTACK_MAIL_SERVICE_ENV` が未設定のときだけ
   です。それ以外の値は run を止めます。

7. **production を確かめてから完了と言う。** すべての確認が成り立たなければ
   なりません。1 つでも外れたら deployment は完了していません。

   ```bash
   step_7() {
     local pid new_env r
     pid=$(listener_pid "$PORT") || return 1
     # venv の python は Homebrew の Python.app として見えることがある（Air で実測）。venv/bin/ の下の実行ファイルで判定する
     ps -o command= -p "$pid" | grep -q "candidates/$SHA/venv/bin/" || { echo "port $PORT is not served by candidate $SHA" >&2; return 1; }
     new_env=$( set +u; . "$INSTALL/env.sh" || exit 1; printf '%s' "$AGENTSTACK_MAIL_ENV" )
     [ "${new_env#$SVC/renders/$SHA-}" != "$new_env" ] || { echo "env.sh does not point at a render of $SHA: $new_env" >&2; return 1; }
     sed -n 2p "$SVC/runtime/agentstack-mail.pid" | grep -q "$(dirname "$new_env")/" || { echo "pidfile runner is not inside the new render" >&2; return 1; }
     if [ "$(uname)" = Darwin ]; then launchctl list | grep -q "$LABEL" || { echo "$LABEL is not registered" >&2; return 1; }
     else systemctl --user is-active --quiet "$LABEL.timer" || { echo "$LABEL.timer is not active" >&2; return 1; }; fi
     "$INSTALL/bin/agentstack-mailctl" status || return 1
     "$INSTALL/bin/agentstack-selftest" || return 1
     r=$(probe "$AGENTSTACK_MCP_URL" health_check '{}') && [ "${r#*$STATE/storage.sqlite3}" != "$r" ] || { echo "live health_check does not report the shared database" >&2; return 1; }
     echo "deployed $SHA; old render was $OLD_ENV, new render is $new_env"
   }
   step_7 || echo "step 7 failed"
   ```

   手順 3 の probe を実際の endpoint に対して繰り返します。変更が引数の扱いや
   logging に触れたなら、拒否される呼び出しも含めます。`$SHA`、新旧の render
   path、outage、probe の結果を deployment note に記録します。

## Rollback

前の build への戻しは `--update-mail` に前の candidate を pin するのが test で
通した経路です（上の節）。以下は手動で行う場合の手順です。

**installer の source から読んだ手順で、未実行です。** 頼る前に scratch な install
で検証する plan として扱ってください。

前の candidate と render は disk に残っています。rollback は前の commit で前進
手順を繰り返すことですが、違いが 2 つあります。第一に、
`AGENTSTACK_MAIL_CANDIDATE_ID` は candidate directory の名前を決めるだけです。
その directory が無ければ*現在の* checkout の package が旧い名前の下に build され
ます（あるが不完全なら installer は止まります）。だから止める前に旧 candidate が
完全であることを確かめ、`AGENTSTACK_MAIL_SERVICE_VENV` で明示的に pin します。
こうすると installer は build する代わりに止まります。第二に、installer が管理する
他のものは走らせた checkout から来ます。

```bash
rollback() {
  local OLD_SHA=$1 OLD_V
  OLD_V="$SVC/candidates/$OLD_SHA/venv"
  [ -x "$OLD_V/bin/agentstack-mail" ] && [ -x "$OLD_V/bin/agentstack-mail-service" ] && [ -x "$OLD_V/bin/agentstack-mail-migrate" ] \
    || { echo "old candidate is not complete: $OLD_V" >&2; return 1; }
  step_5 || return 1
  "$INSTALL/bin/agentstack-mailctl" stop || return 1
  port_free "$PORT" || return 1
  ( cd "$REPO" && AGENTSTACK_MAIL_CANDIDATE_ID="$OLD_SHA" AGENTSTACK_MAIL_SERVICE_VENV="$OLD_V" bash scripts/install.sh --scoped ) || return 1
  SHA=$OLD_SHA step_7
}
rollback <前の commit> || echo "rollback failed"
```

unit は `env.sh` に従うので、別に更新する pointer はありません。

## 実際にどの build が動いているかを確認する

自分が行った deployment と、その port が応答している build は別の主張です。
port に聞きます。

```bash
pid=$(lsof -nP -iTCP:<port> -sTCP:LISTEN | awk 'NR>1{print $2}')
ps -o command= -p "$pid"          # which candidate's python is this
```

`agentstack-mail.pid` の pid は runner であって server ではありません。server は
その子で、descriptor を持って request に答えているのはその子です。runner を
測って「修正が反映された」と結論づけるのは、ここですでに一度起きた間違い
です。dashboard の `/api/version` を読むのも同じ間違いで、それは package の版
であり、Mail を切り替えたかどうかに関わらず再実行のたびに変わります。

**動いている build に足りない機能。** `agentstack-doctor` は動いている Mail の
`tools/list` を 1 回読み、この install が頼る機能（`scripts/lib/mail_required_features.json`。
例: 旧形式の Claude の子を Mail 付きで再開する `register_agent` の `existing_agent_id`）
のうち欠けているものごとに `warn:` を出し、直し方（`--update-mail`）を示します。
Mail そのものは動いているので、doctor の exit status は変えません。最後に
setup.sh が読む 1 行を出します。

```text
mail-features: status=<ok|missing|unknown> missing=<tool.parameter,...> running=<commit>
```

`unknown` は Mail に問い合わせられなかったことで、機能がそろっている意味では
ありません。

**古い Mail の案内。** install.sh は、この run で差し替えなかった Mail がこの
checkout の build より**古いと分かるとき**（動いている build の commit がこの
checkout の commit の祖先であるとき）、結果行の前に短い案内を出します。動いて
いる build の方が新しいときは「checkout の方が古い。Mail をこの checkout から
更新する前に pull する」と、どちらが新しいか分からない（分岐・この checkout に
無い commit）ときはそう出し、どちらでもこの checkout からの更新は勧めません
（古い checkout から更新すると Mail を戻してしまうため）。頼る機能が欠けている
ことは、どの場合も知らせます。ただし欠けていることは「この checkout から更新
すれば直る」根拠ではないので、そのときは「動いている build と同じか新しい
checkout から更新する」と案内します。足りない機能、
更新の仕方（`./scripts/install.sh --mail update`／`./scripts/setup.sh --mail update`）、
更新のリスク（止まるのは通常は数秒。新しい build が起動しないと、切り替えと
前の build への戻しに数分かかりうる。短い上限は保証しない。その間の Mail の
呼び出しは失敗しうる。子と Codex は自分で戻る。top level の Claude Code は戻らない
ことがある。Claude Code 2.1.287 の試験では 8 秒と 15 秒の停止は自分で戻り、18 秒と
19 秒は戻らなかった）、戻らなかったときの操作（その session で `/mcp` →
orrery-mail（✘ failed と表示）→ Reconnect。Authenticate ではない）です。doctor も
欠けた機能があれば同じ案内を出します。文の正本は `scripts/lib/mail_update_notice.py`
で、cockpit の setup.sh も `install.sh --print-mail-update-advice`（読むだけ・常に
exit 0・古いと分かるときだけ出す・更新の command の行を除く）でこれを出します。

## 経緯

同梱 service より前の deployment は `cutover-maintenance/` の下で
`agentstack-mail-service render/stop/start` を手で走らせ、pointer file を読む
supervisor を置いていました。その supervisor が一度（2026-08-26）古い build を
静かに戻したため、installer の配置は `env.sh` を読む supervisor 1 つになり、
手順 5 は残骸を探します。`cutover-maintenance/` の下の cutover receipt は 2026-08
の cutover を行った candidate を pin しています。receipt は出来事を記述するので
あって現在稼働中の build を記述するものではなく、この手順はそれを編集しません。
