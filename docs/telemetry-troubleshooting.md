# トラブルシューティング

> English version: [troubleshooting.en.md](en/telemetry-troubleshooting.md)

[前: 設定](telemetry-configuration.md) · [README に戻る](../README.md) · [次: 第三者コンポーネント](https://github.com/gyroid-eth/orrery-telemetry/blob/master/docs/third-party.md)

最初に:

```bash
~/.agentstack/bin/agentstack-doctor
git -C /path/to/orrery-telemetry status --short
```

core doctor は install footprint、必須 command、managed block（marker があるかだけでなく、インストール済みの template と文面が一致するか。一致しなければ更新コマンドを表示）、managed agent 名、tmux mouse、tmux global identity env、dashboard endpoint と service manager の状態を検査します。repository 側は `git status` で変更を確認します。

dashboard は `/api/version` の正しい JSON response を「実際に配信中」の正本として判定し、launchd / systemd の登録・実行状態とは別に報告します。endpoint が応答していて manager が実行していなければ `unmanaged-background` です。mail-watcher health は `/api/mail-watcher-health` で別に確認してください。

## Cockpit backend の更新

Mac・Windows の ORRERY app は、起動中に checkout の更新を検知すると、送信・Exit・権限の再開が済んだあとに cockpit backend を自動で起こし直します。tmux の agent は引き続き動きます。接続が戻ると `Backend updated to …` が数秒表示されます。

自動試行は対象の commit ごとに1回です。失敗の理由を帯で確認し、必要なら `Restart backend` で再試行できます。操作の完了を確認できない旧 backend から移行するときは、操作が済んでから元の launcher で backend を一度起こし直してください。自動更新は、この機能を含む app と backend を用意すると、次の更新から毎回使えます。

自動試行の記録は backend が動く OS の `${XDG_STATE_HOME:-$HOME/.local/state}/orrery/backend-updates.jsonl` にあります。Windows app では Ubuntu 側を見てください。

## バグを報告するとき

```bash
~/.agentstack/bin/agentstack-doctor --report
```

`--- copy from here ---` から `--- copy to here ---` までをそのまま貼ってください。

dashboard のログが見つからないときは、報告用の出力より前に次のように表示されます。

```text
missing: dashboard log <install-dir>/runtime/dashboard.log
```

これまでに見つかった不具合は**すべて「報告者の環境と開発機の違い」**から出ており、その差がどこにあるかを突き止めるまでに毎回何往復もかかりました。この出力は、その往復で実際に聞いた項目だけを並べたものです。

| 項目 | これが分かれば判ること |
|---|---|
| ORRERY Mail の commit・origin より何コミット先か | 動いているコードが本当はどれか |
| `AGENT_NAME_ENFORCEMENT_MODE` | 要求した名前がそのまま通るかどうか |
| passthrough patch の有無 | 上のモードがそもそも受け付けられる版かどうか |
| requested-name handling | #140 / passthrough / 旧処理を合わせた最終判定。`unknown` は未判定 |
| `agents.retired_at` カラムの有無 | dashboard のクエリが成立するかどうか |
| open file limit | descriptor を使い切って落ちる側かどうか |
| tmux / python3 / uv / claude / codex の有無と版 | 前提コマンドが揃っているか |

**token や Authorization ヘッダは含みません**（そのままチャットに貼れるように、意図的に値を出さない作りにしてあり、テストで固定しています）。「何をして」「何を期待して」「何が起きたか」を末尾の欄に書き足してください。エラー文はそのまま貼ってもらうのが最も速いです。

## `MCP tool call requires approval, but approval policy is never`

Codex child が inherited MCP server を呼んだものの、その server または tool に明示的な許可がありません。たとえば次の TOML fragment を絶対 path に保存し、installer を再実行してください。

```toml
[mcp_servers.chrome-devtools]
default_tools_approval_mode = "approve"
```

```bash
./scripts/install.sh --codex-child-overlay /absolute/path/to/overlay.toml
```

特定 tool だけなら `[mcp_servers.chrome-devtools.tools.take_screenshot]` の `approval_mode = "approve"` を使います。詳細と接続先の上書き例は [委任と child agent](delegation.md#codex-child-と-mcp-承認) を参照してください。

## Mail の fixture digest mismatch

`Authorization fixture digest mismatch` や tools fixture の digest mismatch は、Git の `core.autocrlf=true` による checkout 時の CRLF 変換でも発生します。
次の command で対象ファイルの改行を確認できます。

```bash
git ls-files --eol packages/agentstack_mail/fixtures/authorization-tools-v1.json packages/agentstack_mail/fixtures/live-tools-list.json
```

この2ファイルは配布時の bytes を SHA-256 で固定しているため、`.gitattributes` で `text eol=lf` を指定しています。
新しい checkout では `core.autocrlf` の値にかかわらず `i/lf w/lf` になります。
既存 checkout で `w/crlf` のままなら、未コミットの変更を保存したうえで、この属性を含む revision から新しく clone してください。
CRLF に合わせて期待する digest を変更したり、認可 catalog の検証を無効にしたりしないでください。

## Windows Mail archive の MAX_PATH 超過

長い project path と message subject によって archive path が Windows の MAX_PATH を超えると、`WinError 206` で保存に失敗することがあります。
filesystem access には extended-length path を使い、Git staging には archive repository 内だけで `core.longpaths=true` を設定した Git を使います。
project identity、slug、filename と global Git 設定は維持します。

Windows 回帰テストは260文字を超える path で message 保存、Git staging、起動時の未commit file 回復を検証します。
native Windows installer、service 管理、Codex Desktop Bridge の対応を示すテストではありません。
UNC path の変換も含みますが、network share での実動作は未検証です。

## `NOT CONFIGURED`

原因は dashboard service に `AGENTSTACK_PROJECT_KEY` または `AGENTSTACK_VAULT` がないことです。

確認:

1. `~/.agentstack/env.sh`
2. launchd plist / systemd unit の environment
3. service の再起動後に `/api/graph`

修復:

```bash
export AGENTSTACK_PROJECT_KEY=/absolute/project/path
./scripts/install.sh
```

DECK の tmux state は設定なしでも見えます。mail edge、history / replay、spawn だけが使えない状態は意図された縮退動作です。Output は cwd / git root の `logs/` fallback を引き続き探索します。

## 起動のたびに `ORRERY instruction migration: N notices` と出る

agent の起動時に、指示ファイル（`~/.claude/CLAUDE.md`、`~/.codex/AGENTS.md`、作業 folder の `CLAUDE.md` など）の ORRERY 管理ブロックについて、知らせの件数が出ます。各ファイルの path と理由は `agentstack-doctor` で確認できます。

### `[legacy]`、または `differs from the installed template`

管理ブロックがインストール済みの template より古い状態です。SSH や script などの非対話 shell で installer を実行すると、管理ブロックの更新を見送り、install の log に `non-interactive shell; skipping … managed setup` と出ます。理由が `INSTRUCTION_PATH_UNSAFE` の場合は、次の節を確認してください。

端末で、知らせや install の log に出ている command を実行します。Claude は `agentstack-claude-setup`、Codex は `agentstack-codex-setup` です。既存のファイルを書き換える場合は確認を求めます。書き換えるのは管理ブロックだけで、元のファイル全体の控えは、既定では `~/.agentstack/backups/instruction-migration/` に残ります。

先に計画だけ見るときは `--plan` を付けます。[承認の条件は指示ファイルの移行ガイドを参照してください。](instruction-migration.md#consent)

古い Codex の `AGENTS.md` を片付ける `--remove-legacy-block` は、ファイル自体を削除する場合があるため、`--assume-yes` を付けても端末で `y` の確認が必要です。

### `[unknown]`（`INSTRUCTION_PATH_UNSAFE: …`）

指示ファイルの所有者が違う、group や他の利用者が書き込める、または path を安全にたどれないとき、ORRERY はそのファイルの確認と更新を見送ります。setup を実行しても、理由になっている条件が残っている間は知らせが続きます。agent の起動と Mail は続けて使えます。

WSL の Windows drive（`/mnt/c/…` など）で Linux の権限メタデータが無効だと、Windows のアクセス権が `rwxrwxrwx` などに見えることがあります。Windows drive（DrvFs）と確認でき、WSL 上の所有者が現在の利用者と一致する場合、ORRERY はこの見かけの権限を区別して確認・更新します。更新時は全文の控えを取ってから、同じファイルに書き込み、読み直して確認します。Windows 側の個別アクセス権はそのファイルに残ります。この知らせが残るときは、`agentstack-doctor` に表示された path と理由を確認してください。[WSL のファイル権限](https://learn.microsoft.com/ja-jp/windows/wsl/file-permissions)

## Output が空、または link にならない

Output の file は `LOG_*.md` で、frontmatter の `agent:` が dashboard の canonical agent 名と一致する必要があります。

1. `AGENTSTACK_DELIVERABLE_ROOTS` を設定した場合は `:` 区切りの各 directory が service process から読めるか確認
2. 未設定なら `AGENTSTACK_PROJECT_KEY/logs/`、次に vault、cwd / git root の fallback を確認
3. `env.sh` だけを変えた場合は installer を再実行し、launchd / systemd environment に反映
4. item が `AGENTSTACK_VAULT` の外なら非リンク表示が正常です。vault 内 item だけが `obsidian://` link になります

## launchd が起動しない

```bash
label=org.agentstack.agentdashboard
plist="$HOME/Library/LaunchAgents/$label.plist"
target="gui/$(id -u)/$label"

launchctl enable "$target"
launchctl bootout "$target" 2>/dev/null || true
while launchctl print "$target" >/dev/null 2>&1; do sleep 0.1; done
launchctl bootstrap "gui/$(id -u)" "$plist"
tail -f ~/.agentstack/dashboard/dashboard.log
```

`enable` は `bootstrap` より先に行います。無効化された label を先に bootstrap すると
macOS が `Input/output error` を返す場合があります。また `bootout` は非同期なので、
`launchctl print` で job が消えるまで待ってから再登録します。installer と
`agentctl.sh start` はこの順序を自動で行い、GUI domain 自体を使えない場合の
supervised-background fallback は従来どおりです。

よくある原因:

- port `8770` を別 process が使用
- plist の Python / PATH が古い
- `~/.agentstack` を移動した
- install 後に `env.sh` だけを変更
- dashboard file の copy が不完全

port を変える場合:

```bash
AGENTSTACK_PORT=8771 ./scripts/install.sh --port 8771
```

installer は使用中 port を検出すると service 登録前に停止します。

## Linux / WSL で service がない

**素の Linux は未検証、WSL2 は実機確認済みです。** systemd user 経路と supervised background への fallback は実装されていますが、素の Linux ホストでの登録・timer 起動は通していません。CI（ubuntu-latest）は `systemctl` をスタブにして unit の生成と呼び出し順だけを検査しています。WSL2（Ubuntu 26.04 / WSL 2.7）では Mail の timer 起動と dashboard、agent 起動、jump まで通しています。うまくいかなければ issue で環境と出力を報告してください。

systemd user session が使える場合:

```bash
systemctl --user status org.agentstack.agentdashboard.service
systemctl --user daemon-reload
```

WSL2 では systemd user と linger が使える場合に installer が dashboard の unit を有効にします。systemd user が使えない場合や、WSL2 で linger を確認できない場合は、`nohup` と pidfile で起動します。localhost dashboard と browser terminal は利用できます。WSL2 では dashboard の jump が Windows Terminal（`wt.exe`）の新しいタブを開いて `wsl.exe -d <distro>` 経由で tmux に attach します（`AGENTSTACK_TERMINAL=auto` が `wt` を選ぶ）。素の Linux では jump は未対応のままです。

### WSL2 で Ubuntu の窓を閉じたとき

**従来モードの dashboard は、agent の作業中に WSL を自動で保持します。** Windows の WMI で元の接続とは独立した非表示の `wsl.exe` を起動し、無活動が60秒続くと手放します。`agentstack-doctor` は Windows の `.wslconfig` を読み取り、設定は変更しません。

- tmux の agent process（Claude、Codex、Antigravity）が動いている間は保持します。承認や返答を待っている agent も含みます。
- dashboard の NEW AGENT や `agent-start` / `agent-start-codex` は、起動前に保持を予約します。保持を確認できない場合も agent の起動は続き、NEW AGENT の通知または shell の `WSL hold: ...` に理由が出ます。残った予約は3分で失効します。
- dashboard のページを表示している間も保持します。ページを隠すか閉じると、この保持理由が外れます。dashboard、Mail、watcher、tmux の記録用接続はそれだけでは保持理由になりません。
- header の `WSL kept · 2 agents` は保持理由、`WSL hold ends in 42s` は解除までの秒数です。`agentstack-doctor` で理由、Windows 側の PID、状態の鮮度を確認できます。
- tmux やプロセス一覧を読み取れない場合は、最後に確認した agent に対する保持を続け、`WSL kept · state unknown` と表示します。状態の更新が30秒を超えて途絶えると `WSL status stale` と表示します。
- 隠れた `wsl.exe` が早く終了すると dashboard が再起動を試みます。失敗が3回続くと次の試行まで5分待ちます。dashboard 自体が終了しても、最後に確認した agent が生きている間は保持が続きます。

**自動保持が効かないときは、作業中は Windows 側で Ubuntu の窓を1つ開けておきます。** header に `WSL not kept` が出た場合、または自動保持を無効にした場合に使えます。`--no-wsl-anchor` または installer 実行時の `AGENTSTACK_WSL_ANCHOR=0` で無効になり、`--wsl-anchor` で戻せます。設定は `env.sh` に保存されます。

Windows Terminal などのデスクトップの窓から起動したものは、最後の窓を閉じても Windows 側に `wslhost.exe` が残り、WSL が動き続けることがあります（WSL 2.7.13 で90秒以上 Running を確認）。Windows の SSH サーバー経由で起動した場合は、接続終了時にその `wslhost.exe` が片付けられます。自動保持や他の Windows クライアントが無ければ、最後の接続から約15秒で止まることを WSL 2.7.13 で確認しています。WSL 内の sshd への直接接続は未検証です。

保持が解除された後も WSL が動き続けていてすぐに止めたい場合は、PowerShell で次を実行します。**すべての distro と WSL の VM がすぐに止まる**ので、agent と他の distro を含む WSL 上の作業を先に保存・終了してください。

```powershell
wsl --shutdown
```

次に Ubuntu を開くと、有効にした systemd user unit が dashboard を起動し、Mail の timer が約1分後に Mail の起動を試みます。supervised background の dashboard は `agentctl.sh start` で起動します。

- Ubuntu の起動時に systemd user manager を起動し、ログアウト後も dashboard、Mail の timer と watcher を動かすには、WSL の中で `loginctl enable-linger "$USER"` を設定してから installer を実行します。
- `.wslconfig` の `[general] instanceIdleTimeout=-1` は distro を、`[wsl2] vmIdleTimeout=-1` は distro の停止後も VM を動かし続けます。普段の接続経路で自動保持と切断後の稼働を確認できた場合に、これらの設定を外せます。`agentstack-doctor` の案内に従い、該当行を消して一度 `wsl --shutdown` を実行します。

同じ PC で native Windows の helper（`scripts/windows/`）も動かしている場合、WSL2 の 8770 は Windows の localhost に転送されるので、Windows 側に同じ port の dashboard が残っているとブラウザはそちらに繋がり、WSL の agent が見えません。どちらかの port を変えるか、native 側を止めてから開きます。

## macOS で `EPERM`

Desktop / Documents / Downloads 配下なら TCC を疑います。

1. Full Disk Access 済み terminal から root agent を起動
2. 既存 tmux server / session を終了
3. 同じ terminal から再作成
4. または project を保護対象外へ移動

`chmod` で直らない場合があるのは、file mode ではなく起動元 app identity が判定されるためです。詳しくは[インストール](telemetry-install.md#macos-の-tcc--full-disk-access)を参照してください。

## Codex に通知 text は入るが送信されない

text と submit を一回の `send-keys` に混ぜないでください。

```bash
tmux send-keys -t "$session" -l "$text"
sleep 0.2
tmux send-keys -t "$session" C-m
```

Codex REPL では `Enter` keysym が submit にならない場合があるため `C-m` を使います。

追加確認:

- target pane が Codex / Claude REPL か、bare shell ではないか
- `AGENTSTACK_SIGNALS_DIR` に backlog がないか
- `/api/mail-watcher-health` の `watcher_running`
- `last_success_age_s` と `recent_results`

## Mail watcher が yellow / red

24時間以上古く、宛先の tmux session が無い signal は `orphan_signal_count` に分け、health の滞留判定から除外します。新しいwatcherは、session一覧で宛先不在を確認すると通知signalだけを取り下げ、再試行を止めます。Mail本体・inboxはそのままです。古いwatcherが残した通知や、tmuxの確認に失敗して残した通知は存在し得るため、残留だけでは配送障害と断定しません。生きている宛先・新しい signal・headless runtime は除外せず、tmux の確認に失敗した場合も全数を判定に残します。doctor は古い残留数と片付け方を warn に出しますが、health が green ならこの warn だけで exit 1 にはしません。

必要なら、インストールの環境を読み込んで候補を確認します。`--prune` を付けると、削除直前にも session が無いことを確認し、signals 配下の24時間以上古い通常ファイルだけを削除します。Mail の DB・inbox・notify-state は触りません。symlink は辿らず、tmux の測定に失敗した場合は削除しません。session を再開する予定の宛先は、先に再開してください。

```sh
source ~/.agentstack/env.sh
"${AGENTSTACK_PYTHON:-python3}" ~/.agentstack/dashboard/mail_signals.py
"${AGENTSTACK_PYTHON:-python3}" ~/.agentstack/dashboard/mail_signals.py --prune
```

```bash
curl -s http://127.0.0.1:8770/api/mail-watcher-health
```

- watcher process がない
- signal が残り、直近成功が古い
- ORRERY Mail endpoint / bearer token が不正
- target tmux session がない

watcher は installer が service として登録します（macOS は launchd `org.agentstack.mail-watcher`、Linux / WSL2 は systemd user unit `org.agentstack.mail-watcher.service`。`watcher_mode` にどちらで動いているかが出ます）。`watcher_running` が `false` のまま signal が溜まるのは、この unit が無い古いインストール（2026-09-07 より前は `agent-start` が tmux session として起動するだけで、dashboard から spawn した agent しかいない host では誰も起動しなかった）か、unit の登録に失敗した場合です。`bash scripts/install.sh` を再実行すると登録し直します。手動で確認するなら:

```bash
launchctl print gui/$(id -u)/org.agentstack.mail-watcher   # macOS
systemctl --user status org.agentstack.mail-watcher.service   # Linux / WSL2
tail ~/.agentstack/runtime/mail-watcher.log
```

`AGENTSTACK_MAIL_HOME` と `AGENTSTACK_SIGNALS_DIR` が service と launcher で一致しているか確認します。

**mail は inbox に届くのに tmux に通知が入らず、log に `Stale watcher lock detected; taking ownership` と `mkdir: ... File exists` が数秒おきに並ぶ**なら、watcher が lock の取り直しに失敗して service manager に再起動され続けています。前の watcher が EXIT trap を通らずに死ぬ（SIGKILL、host のクラッシュ、process を差し替える deploy）と lock dir に heartbeat が残り、2026-09-12 より前の watcher はそれを片付けられませんでした。`launchctl print` の `runs` が数千になっているのが目印です。復旧は lock dir を消すだけです（keepalive が次の起動で取り直します）:

```bash
rm -rf ~/.agentstack/runtime/mail-watcher.lock   # AGENTSTACK_MAIL_WATCHER_LOCK_DIR を変えていればそのパス
tail -3 ~/.agentstack/runtime/mail-watcher.log
```

repo を更新して `bash scripts/install.sh` を再実行すれば、以後の takeover は残り物があっても通ります。

**1 台の Mac に複数の利用者がいて、`log` に `Permission denied` と `Stale watcher lock detected` が交互に数秒おきに並び、watcher が一度も動かない**なら、lock dir を他人の watcher と共有しています（2026-10-05 以前は既定が `/tmp/orrery-mail-watcher.lock` で全利用者共通だったため、1 台の Mac の 2 人目の利用者が先にいる利用者の lock を取れず無限リトライしていました）。既定は利用者ごと（`$AGENTSTACK_RUNTIME_DIR/mail-watcher.lock`）になっており、repo を更新して `bash scripts/install.sh` を再実行すれば解決します。`AGENTSTACK_MAIL_WATCHER_LOCK_DIR`・`_PIDFILE`・`_HEARTBEAT` を手で他人の path（`/tmp` 配下の共有 path など）に向けている場合、watcher は**何も書かず、別の場所へ切り替えもせず**に止まり、log に「この path は別の利用者の物。override を外すか自分の path に」と一度だけ出します。設定を外す（または自分だけが書ける場所に変える）と動きます。2026-10-05 より前の既定に自分の古い watcher がまだ生きている場合も、二重配送を避けるため新しい watcher は起動せず、止める案内を出します（その pid が watcher の process でなければ、stale として扱います）。`agentstack-doctor` も、watcher が動いていない・status が red / yellow・heartbeat が古い場合に warn します。

## Dashboard spawn がすぐ消える

1. `dashboard/logs/spawn.log` の末尾を見る
2. `tmux has-session -t '<child-name>'` を確認
3. `~/.local/bin/claude`、`codex`、指定 CLI が service の `PATH` から見えるか確認
4. `AGENTSTACK_SPAWN_SCRIPT` と working directory を確認
5. `AGENTSTACK_PROJECT_KEY` / `AGENTSTACK_VAULT` を確認
6. `AGENTSTACK_MAIL_ENV` に `HTTP_BEARER_TOKEN` があるか確認
7. `agentstack-reregister '<child-name>'` で token state を確認

dashboard は launcher 自身の readiness / early-death verdict を最大120秒待ち、その launcher が成功した後に exact tmux session を probe します。launchd の最小 PATH では `~/.local/bin` が欠けやすいため、spawn path はこれを先頭へ補います。

Codex の場合は `AGENTSTACK_CODEX_MODELS` と request model、effort allow-list も確認してください。

## Claude の子が起動の途中で止まる（readiness）

Claude の子は、入力を受け付ける画面になってから task を渡します。それ以外の画面では、launcher は task を入れずに止まります。そのとき、理由と画面（空行を除いた最大 40 行）を stderr と `AGENTSTACK_RUNTIME_DIR/spawn_incidents.log` に残します。待っている間は、10 秒ごとに経過を stderr に出します。

- **`one-time question about Claude in Chrome`**: Claude Code が「Claude in Chrome extension detected」と、ブラウザ操作の既定を利用者に尋ねています（拡張を入れた後の最初の起動などで出ます）。その答えは、今後のすべての Claude セッションの既定になる可能性があります（保存されるかどうかは確認していません）。そのため、launcher はキーを押さずにすぐ止まります。通常の端末で `claude` を一度開いて自分で答えるか、`/chrome` で決めてから、もう一度起動してください。
- **`one-time question (<heading>)`** は、「Claude in Chrome」の通知など、Claude Code が下部に Enter／Esc の案内がある起動画面を表示したときに出ます。通常の端末で `claude` を一度開いて応答し、子を起動し直してください。子が最初の指示にすでに返信している場合は、子の pane で応答できます。
- **`choice screen ORRERY does not recognise`**: 未知の選択画面が 10 秒続きました。キーは送っていません。incidents.log の画面を確かめ、想定どおりの画面なら通常の `claude` で一度答えてから、もう一度起動してください。
- **`Claude readiness timeout (60s)`**: 60 秒たっても入力を受け付ける画面になりませんでした。incidents.log の画面と、10 秒ごとの経過で、起動が遅いのか、画面を認識できていないのかを見分けてください。
- launcher がキーを押すのは、trust dialog を受理するときだけです。

## Codex の子の最初の task が始まったか分からない

Codex の子の最初の task は、画面への貼り付けではなく `codex -- "<task>"` の起動引数で渡します（Codex 0.158 で、起動途中に貼った task から turn が始まらないことがあったため。起動中の画面の切り替わりとの競争が最有力の仮説です）。task は再送しません。

task が始まったかどうかは、画面の文字ではなく、この起動の Codex の記録（rollout）で確かめます。Codex の history binding（任意の plugin の SessionStart hook）が、この起動の session と記録の場所を receipt に残している場合だけ確かめられます。

- 確かめられた: `spawn_incidents.log` に `task started (<name>, …; recorded in this launch's rollout)`
- binding が無い・働いていない: 最大90秒見張ったあと `Codex started (<name>); first-task confirmation unknown` と残します。失敗ではなく、子はそのまま作業を続けます。ただし launcher と `/api/spawn`（非同期なら `/api/spawn-status`）の確定は、その90秒のあいだ待たされます
- binding はあるが task の記録がまだ無い: `WARNING: first task not yet recorded` と残します。子は残します

見張りのあいだ launcher がキーを送るのは、実際の画面で確かめた形の trust 画面（`Trust this folder?`、`1. Trust and continue` / `2. Quit` と選択カーソル、最下行の `enter continue · esc quit`）だけです。model 選択や sign-in の画面、会話の中に出てきた同じ文言には応じません。その画面で止まっていれば、手で応じてください。

1. `tmux capture-pane -t '<child-name>' -p -S -1000` で画面を見る。Codex が作業中なら task は届いています
2. 起動画面で止まっていれば、その画面に応じる
3. 届いていないと確かめられたときだけ、task を手で送る

task は1つのコマンドライン引数になるため、120000 byte を超える task は起動前にエラーになります。長い説明は ORRERY Mail で送ってください。

## Spawn 名が拒否される

指定名は hyphen を除去した後、ASCII letter で始まる2〜64文字の alphabetic 名である必要があります。

- `occupied`: 既存 identity
- `unknown`: DB / auth / transport failure
- `available`: 使用可

`unknown` は使用できません。別名で回避する前に ORRERY Mail と project key を直してください。identity continuity を守るためです。

## 要求した名前と違う名前で登録される

ORRERY Mail が名前を受け入れず、生成名に置き換えた状態です。エージェントは動き続けるので気づきにくく、他のエージェントから宛先として呼べないことで初めて分かります。

```bash
~/.agentstack/bin/agentstack-doctor --report \
  | grep -E 'passthrough patch|requested-name handling'
```

`requested-name handling: replaced` なら、要求名を受け付けない既知の旧処理です。installer も事前に「要求した名前が生成名に置き換わる」と警告します。`unknown` は source が読めないか命名処理が既知の形でないため、対応しているとも対応していないとも推測していません。`passthrough patch: absent` でも #140 の `validate_explicit_agent_id` があれば `honored` になるため、patch 行だけで判断しないでください。

install 時の判定と根拠は `install-state.json` の `agent_mail.requested_name_honoring` に残ります。同梱 ORRERY Mail は要求名を受け付ける設定で起動します。旧 service がまだ応答している場合は `--retire-legacy-mail` で停止してから installer を再実行し、同梱 service へ切り替えてください。

旧 service が `sqlite+aiosqlite:///./storage.sqlite3` のような相対 DB URL を返す機体で
`unsupported database URL` が出る場合も、既知の legacy launchd label がロード中なら
`./scripts/install.sh --retire-legacy-mail ...` を使います。installer は label と plist が
実際に mail service を指すことを確認してから、listener の再利用判定より先に退役します。
フラグなしのエラーには検出 label が表示されます。label が表示されない場合は別の
listener なので、DB path を推測せず `agentstack-doctor --report` で所有者を確認してください。

### 別名で登録されたときに何が起きるか

エージェント自体は正常に動きます。壊れるのは**呼び名だけ**です。

| | |
|---|---|
| 動くもの | 送信・受信・ファイル予約・tmux セッション・dashboard 上の表示 |
| 壊れるもの | **親や他のエージェントが宛先に指定する名前**。要求名で `send_message` すると届きません |
| 肖像 | **出ません**。fallback 名（`GreenLake` 等）は科学者名で終わらないため、dashboard は顔を引けません |

肖像が出ないのは不具合ではなく、**この状態を見分けるための唯一の視覚的な手がかり**です。だからハッシュ等で機械的に顔を割り当てることはしていません。顔を配ると、失敗した登録が成功したものと見分けられなくなります。

そのうえで、顔の不在から察してもらうのは弱すぎるので、**要求名そのものを画面に出します**。

- **DECK**: 名前の下に `↯ asked for <要求した名前>`
- **ネットワーク図**: そのエージェントの名前ラベルが amber になり、hover で `requested <要求名>, registered as <実際の名前>`

記録は `$AGENTSTACK_RUNTIME_DIR/name-substitutions.json` にあり、登録が置き換わった場合のみ書かれます。

復旧するには、名前を受け付けるサーバーにしたうえで**エージェントを起動し直します**。既に登録された identity の名前は後から変えられません。

## Registration / inbox の認証に失敗する

別名を作らず:

```bash
AGENTSTACK_PROJECT_KEY=/absolute/project/path \
  ~/.agentstack/bin/agentstack-reregister "$AGENT_NAME"
```

を実行します。

明示 global context の exit 3 は `observed`（登録は未更新）です。program/model を指定して helper を再実行してください。

失敗時の stderr は、秘密を含まない定型診断です。たとえば
`stage=ensure_project reason=transport-failed curl_exit=7` は通信前半、
`stage=register_agent reason=http-rejected http_status=403` は HTTP 拒否、
`stage=response-parse reason=invalid-response` は応答形式で止まったことを示します。
`rpc-error` / `tool-error` はそれぞれ JSON-RPC / tool 層の失敗です。
`identity-check reason=identity-changed` なら、予約済み identity が別名へ置換されたため
fail-closed で停止しています。`credential_source` は `child-state` / `inherited` /
`runtime-file` のどこから owner credential を選んだかだけを示し、値は表示しません。

`http_status=401` や `403` だけで stale / wrong-owner token と断定しないでください。
`stage=local-token reason=credential-unavailable` の場合に限り、まず次の owner credential
保存先を確認します。

```text
$AGENTSTACK_RUNTIME_DIR/agent_token_<name>
$AGENTSTACK_RUNTIME_DIR/child-agents/<name>.json
```

token が missing / stale / wrong-owner なら親または operator へ報告してください。token を chat、log、process argument に貼らないでください。
launcher を一度も通らない常駐 bot で local token が元から無い、または失われた場合は、operator が [常駐 agent の enrollment と起動](persistent-agents.md) の `inspect` から始めます。モデルに `claim` / `recover` を実行させず、通常の登録失敗を credential 不在と推定しないでください。
診断追加前に捨てられた過去の response や curl stderr は、この表示から後追いで復元できません。

## 常駐 Claude Channels が config 検査で停止する

`agentstack-persistent run` は通常の `--channels plugin:...` と interactive PTY を残しつつ raw Mail を同名 bound overlay で抑止するため、実効 Claude config を起動前に fail-closed で検査します。

- `claude-project-root-unsupported`: profile の `working_directory` が symlink、または祖先に `.mcp.json` / `.claude/settings*.json` があります（実効 user config と一致する `settings.json` だけは除外）。subdirectory ではなく実際の Claude project root を指定します
- `claude-managed-configuration-unsupported`: macOS の managed MCP / settings file が存在します。v1 は存在自体を拒否するため、管理者へ相談し、1定義だけの書換で回避しません
- `claude-plugin-mail-conflict`: plugin の Mail server は standalone overlay で置換できません。operator が plugin を disable するか `--plugin-dir` を外し、失われる channel / 機能を確認します
- `claude-settings-flag-unsupported`: profile から `--settings` / `--setting-sources` / `--safe-mode` を外し、[常駐 agent の有限 source 契約](persistent-agents.md#interactive)へ設定を移します
- `claude-config-unreadable`、`claude-project-config-unreadable`、`claude-settings-unreadable`、`claude-plugin-inventory-unreadable`、`claude-plugin-definition-unreadable`、`claude-plugin-unavailable`: 対応する実効 config / inventory / plugin を修復します。別 source を推測して起動しません

wrapper は plugin や managed file を自動編集せず、設定本文、URL query、token を error に表示しません。生成された bound namespace は `AGENTSTACK_PERSISTENT_MAIL_MCP_NAMES` にあり、既存 alias が `agent-mail` だけなら案内も `agent-mail` です。詳細な source 表と境界は [常駐 agent の enrollment と起動](persistent-agents.md#interactive) が正本です。

## Hook が `AGENT NOT REGISTERED` で block する

Claude Code の `check-agent-registered.sh` は、現在の `session_id` で `register_agent` の成功が記録されるまで Edit / Write / Bash を block します。`/clear`、resume、compact 後は SessionStart hook の reminder を読み、既存 identity があるなら別名を作らず再登録します。

**まず自分がどちらの状況か切り分けます。**

`AGENT_NAME` があっても素通りするとは限りません。この guard は **identity conflict → endpoint 不正 → service 停止（outage policy）→ `AGENT_NAME` 免除 → flag** の順に見ます。`AGENT_NAME` が免除するのは **flag の要求だけ**です。`AGENT_NAME` が無いなら、下の復旧コマンドではなく次節を読んでください。

優先する復旧（**mail MCP を持つ session に限る**）:

```bash
AGENTSTACK_PROJECT_KEY=/absolute/project/path \
  ~/.agentstack/bin/agentstack-reregister "$AGENT_NAME"
```

このコマンドは remote の登録を修復しますが、**flag file は書きません**。flag を書けるのは `register_agent` MCP tool の PostToolUse (`mark-agent-registered.sh`) だけです。したがって block の解除には、その MCP tool を session の中から呼ぶ必要があります。

成功後に自分の `fetch_inbox` を実行します。`pending-*` tmux session のままなら registration read-back と rename が完了していません。server が返した canonical name を使い、既存同名 tmux session を自動で kill しないでください。

## 最初の Edit/Write/Bash が block される（launcher を経由しない client / service 停止中）

まず **mail service が応答しているか**を確認します。ここで分岐が変わります。

```bash
# endpoint はインストールごとに違います。install が使っている値を見てから叩きます。
grep AGENTSTACK_MCP_URL ~/.agentstack/env.sh
~/.agentstack/bin/agentstack-doctor --report
```

`agentstack-mailctl` は環境によっては入っていません（このリポジトリの開発機にも無い時期がありました）。**存在するものだけを使ってください。**

### service が応答していない場合

**登録は原理的に不可能です。** flag を書けるのは `register_agent` の PostToolUse だけで、その呼び出しは応答しない endpoint には通りません。tmux の中でも同じです。`agentstack-reregister` も flag を書かないので復旧になりません。

既定（`AGENTSTACK_MAIL_OUTAGE_POLICY=warn-open`）では、この状態の編集は**警告つきで通ります**。予約は取れないので、同じ project を共有する他 agent との衝突は検出されません。記録は `~/.agentstack/runtime/logs/unmanaged_sessions.jsonl` に残ります。

復旧は service 側です。

```bash
# 実在するものだけを絶対パスで叩きます（hook の案内も同じ基準です）
[ -x ~/.agentstack/bin/agentstack-mailctl ] && ~/.agentstack/bin/agentstack-mailctl start
[ -x ~/.agentstack/bin/agentstack-doctor ] && ~/.agentstack/bin/agentstack-doctor --report
```

`AGENTSTACK_MAIL_OUTAGE_POLICY=block` を設定している場合、この状態では編集自体が拒否されます（協調できないなら書かせない、という選択）。

### service が応答している場合

登録は可能なので、guard は登録を要求します。client に mail MCP があるなら `register_agent` を呼べば解除されます（IDE の agent panel からの登録実績があります）。

MCP を持たない client を協調の外で使うと決めているなら、その client の環境に明示的に設定します。

```bash
export AGENTSTACK_UNMANAGED_SESSION_POLICY=warn-open
```

**既定は block です。** 設定しない限り、identity を持たないセッションは登録を求められます。

## installer を再実行したら、外したはずの hook が戻ってきた

戻りません（2026-08-22 以降）。installer は自分が追加した entry を `<runtime>/settings-installed-entries.json` に記録し、**次回その entry が settings から消えていれば「意図的に外した」と読んで再追加しません**。結果は merge の出力の `respected_removals` に出ます。

意図的に戻したい場合だけ、明示します。

```bash
agentstack-merge-settings ... --restore-removed
```

記録が無い状態（初回インストール、記録ファイルを消した場合）では、従来どおり template の entry がすべて入ります。「消えている」ことが「外した」ことの証拠になるのは、**こちらが一度入れた記録がある場合だけ**です。

## Hook が `FILE RESERVATION REQUIRED` で block する

protected root 内の Edit / Write では、hook が exact identity を確定してから既存 reservation を相対/絶対 path の両方で renew-only 確認します。auto-acquire はしません。block する場合:

1. `AGENTSTACK_PROJECT_KEY` / `PROJECT_KEY` が reservation を作った project と一致するか確認
2. `AGENT_NAME`、または`TMUX_PANE`で明示したtmux sessionがcanonical identityを指すか確認。pane metadataとの不一致は`AGENT IDENTITY CONFLICT`として先に直す。tmux 外の client は `register_agent` 済みなら session index から identity が解決される。同一 session に複数の identity が結び付いている場合も `AGENT IDENTITY CONFLICT` で、どちらを残すかを決めてから再登録する
3. exact path または最小の glob を `file_reservation_paths` で予約
4. conflict が返ったら holder へ ORRERY Mail で連絡し、release または expiry を待つ

owner `registration_token` はこのhookのtool argumentsへ送られず、legacy HTTP bearerとは別物です。`isError`は省略またはboolean `false`だけを成功とします。exact identityとprotected scopeの確定後、最初の照会がtransport unreachableの場合だけfail-openです。HTTP/MCP/schema rejection、malformed response、definitive zero後のtransport failureはblockします。pathなし・protected root外はenforcement対象外なのでexit 0です。

strict版はcutover C5の全client restart/rebind後にdeployします。raw non-tmux Claude は、`register_agent` を呼んで session index に self binding ができていれば identity が解決されます。登録できない client（mail MCP を持たない起動経路）と identity source のない旧 session は `AGENTSTACK_UNMANAGED_SESSION_POLICY` の扱いになり、協調が必要なら `agent-start` 経由で再起動してください。guardを無効化したり、untargeted tmux sessionやstale metadataをidentityとして採用したりしないでください。

## Spawned child が自分の inbox を読めない

core doctor を実行します。

```bash
~/.agentstack/bin/agentstack-doctor
```

`child MCP proxy missing` または source tree 不足の warning が出る場合、`./scripts/install.sh` を再実行します。proxy がある child は owner token を model context に読み込まず、child-scoped stdio connection が代理で認証します。shared endpoint へ fallback した状態と proxy 経由を混在させないでください。

## Codex App Bridge / cold wake が動かない

Codex Desktop 統合には core doctor とは別の doctor、runtime state、失敗分類があります。[Codex App 統合の「よくある失敗」](codex-app.md#よくある失敗)を参照してください。Codex CLI session が Bridge に現れないのは意図された surface filter です。

## Dashboard に agent が二重表示される

tmux session 名と ORRERY Mail identity が一致しているか確認します。

```bash
tmux list-sessions
printf '%s\n' "$AGENT_NAME"
```

stale な top-level environment を継承した可能性がある場合は、新しい terminal から `agent-start` / `agent-start-codex` で起動し直します。launcher は `AGENT_NAME`、`PARENT_AGENT`、token、reserved marker を削除してから登録します。

## History が見つからない

`/api/history` は ORRERY Mail の agent program に応じて transcript 形式を選びます。program が無い・不明・読み取れない場合は provider 未確認として、どの transcript resolver にも進みません。Codex CLI は、現在の project の数値 agent ID に対応する session index と rollout 先頭の session ID が一致する場合だけ履歴を開きます。index が無い・壊れている・project / provider / ID が一致しない場合は「未確認」とし、時刻や cwd による探索、過去の cache、Claude transcript への fallback は行いません。

- ORRERY Mail の program が正しいか
- Codex では `runtime/session_index/<agent_id>.json` が現在の project / agent を指しているか
- transcript が disk に残っているか
- index の session ID と transcript 先頭の metadata ID が一致しているか
- child と parent の transcript を取り違えていないか

transcript が存在しない agent は mail timeline だけが見えることがあります。

## PC の再起動・強制終了の後に Resume が拒否される

`/delegate` の子は、動いている間は state が「動作中」で、正常に終わると retire され、保持期間のあいだ再開できる state になります。PC が落ちる（強制終了・電源断・OS の再起動で終了の処理が走らない）と retire されないまま残り、dashboard の RESUME も端末の `claude --resume` も「This child did not end normally …」で拒否します。再開を起動した直後に落ちた場合は「A resume of this child started and did not finish …」です。

dashboard は起動したとき（と、その後 1 時間ごと）に、**この machine が起動する前に書かれたまま**の「動作中」の state と、終わらなかった再開を、再開できる state に戻します。その名前の tmux session があるとき、起動の後に書かれた live-session の lease の process が生きているとき、tmux の状態が分からないとき、登録や旧形式の移行が途中のとき、owner credential が state と一致しないときは何も変えません。再起動の後に dashboard が動いていれば、手で retire する必要はありません。まだ拒否されるなら、その子の tmux session が残っていないかを確かめてください。

起動の前に書かれた live-session の lease（`runtime/live-sessions/<name>/<pid>`）は、PID が別の process に再利用されていることがあるので、生きている印として数えません。

## Terminal が開かない

- `AGENTSTACK_TERMINAL` の値を確認
- Ghostty / iTerm2 / Terminal.app の install path を確認
- `tmux has-session -t '<name>'`

`AGENTSTACK_TERMINAL=none` では OS terminal open を行いません。

## tmux の scrollback が使えない

`~/.tmux.conf`:

```tmux
set -g mouse on
set -g history-limit 50000
```

または `Ctrl+b [` で copy mode に入ります。`agentstack-doctor` も mouse mode を確認します。

## Uninstall が止まる

`install-state.json` が必要です。

```bash
ls -l ~/.agentstack/install-state.json
~/.agentstack/bin/agentstack-uninstall --dry-run
```

manifest がない状態で推測削除は行いません。settings や mail data を巻き込まないためです。

## 関連文書

- [インストール](telemetry-install.md)
- [Launcher と identity](launchers.md)
- [常駐 agent の enrollment と起動](persistent-agents.md)
- [Hooks と運用 helper](https://github.com/gyroid-eth/orrery-telemetry/blob/master/docs/hooks.md)
- [Codex App 統合](codex-app.md)
- [Dashboard](dashboard.md)
- [設定](telemetry-configuration.md)

## nvm の Codex で node が見つからない

dashboard の最小 PATH に nvm がなくても、検出した Codex と同じ bin（または symlink の解決先）に node があれば、確認と起動の両方で同じ PATH を使います。doctor の `Codex launcher binary` も同じ環境で `--version` に答えるかを確かめます。node がどちらにもなく login shell の PATH にもなければ、理由付きで候補を拒否します。

WSL の検査は、対象の checkout で次を実行します。

```bash
bash scripts/check-codex-nvm-wsl.sh /absolute/path/to/codex python3
```

Python 3.11 以上が必要です。追加 package は不要です。既にある CLI と Node.js だけを使い、一時 HOME / CODEX_HOME、最小 PATH で `--version` を確認します。model、login、thread、子の登録や tmux session は起動しません。通常の実 HOME に対する設定変更はありません。
