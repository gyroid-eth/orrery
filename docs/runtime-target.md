# 旧 cockpit の tmux 対象保護

cockpit は起動時に legacy の接続先を1つ確定し、以後は絶対 socket を明示した `tmux -S` を使います。control attach・入力・split/close・terminal を開く操作の直前に、Telemetry の共有 helper で対象を照合します。socket や server PID が変わったときは拒否し、裸の tmux へ戻しません。server が無い状態で起動した場合だけ、同じ接続先に現れた最初の server を固定できます。

これは旧 consumer の互換保護です。global の専用 terminal・WS・pane window の移植は後続です。新規 global 専用起動を有効にするものではありません。既存の純旧 mode の操作と、補助 session に対する従来の split/close 制限は維持します。

## 配置による動作

| 配置 | 対象への操作 |
|---|---|
| 共有 helper が正常 | 既存 context/live の読取 snapshot で global pane を拒否し、通常の legacy pane は継続 |
| helper が欠落・旧版・内部失敗、global の手掛かりが無い | 固定 layout の負の admission を通して旧操作を継続 |
| helper が使えず、client root・context・config 等がある／不明 | `GLOBAL_TARGET_HELPER_UNAVAILABLE` で操作を拒否、一覧の読取は継続 |
| 正常 helper でも root が壊れている／partial | `GLOBAL_TARGET_OWNERSHIP_UNKNOWN`。任意名の global standalone を除外できないため、修復まで全対象の副作用を拒否 |
| dedicated global socket を継承した legacy 起動 | `GLOBAL_TMUX_LEGACY_CONSUMER_REFUSED` で起動を拒否 |

共有判定・schema・reason の正本は Telemetry の `bin/lib/runtime_tmux.py` / `runtime_tmux_contract.json` です。cockpit は所属判定・socket 台帳・親子台帳を保存しません。helper が無い場合の配置確認だけを `bridge/runtime_target.py` に集約しています。`env.sh` は既存 literal reader で読み、実行しません。

拒否理由は既存の WS/HTTP エラーに表示します。`agentstack-runtime-client tmux-diagnostics` で root の原因を確認し、該当する既存 config の `agentstack-ui-client status` で状態を読みます。root/config を修復し、診断の `global_complete=true` を確認して再試行します。動いている root や pending を消して回避しないでください。

更新前の旧版を専用 pane の `TMUX` を継承して直接起動することは未対応です。専用起動を有効にする前に Telemetry と cockpit の両方を対応版へ更新します。既存 custom legacy endpoint は socket/server の証明を起動時に固定します。WT は同じ Linux distro と絶対 socket を argv として運び、Windows path に変換しません。

## 接続する既存 caller

| 呼び手 | transport / admission |
|---|---|
| roster、interactive client、pane→session、question capture | 同じ明示 `-S`。question の内容を読む前に対象照合 |
| control-mode attach と入力・capture・resize・split/close | attach 前、既存送信 lock 内の書込み直前に対象照合。lifetime pipe/guard は維持 |
| closed 判定の has-session / list-sessions / show-options | 3本とも同じ明示 `-S` と TMUX/TMUX_PANE を外した環境。従来の True/False/unknown 判定は維持 |
| Ghostty / WT attach | 照合後の完全 argv/env。同一 Linux socket、WT の distro は既存処理 |
| control bridge の補助 session 作成 | 配置照合を作成前に行い、存在する他の session を採用・rename しない |

## fixture

共有 helper は製品コードを複製せず、固定した Telemetry commit の installer payload 宣言から配備します。試験には `ORRERY_TEST_TELEMETRY_ROOT` でその checkout を指定します。隔離 HOME・短い一時 directory・専用 tmux server を使い、live の default server・実 provider・実 Mail DB は使いません。schema/consumer の試験では process-start を fixture に固定し、実 OS の証明は共有契約の外側試験で区別します。

admission と tmux の副作用は OS の原子的 transaction ではありません。同 UID の非協調 process を完全に隔離できるとは説明しません。送信 lock の内側で直前に照合し、外部待機を挟みません。
