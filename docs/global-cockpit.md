# Global mode の cockpit

[English](en/global-cockpit.md) · [ドキュメント索引](README.md)

この経路は明示的な試験用です。既定は旧 mode のまま、新 mode への切替は有効にしません。準備済みの ORRERY Telemetry と同じ利用者の環境を使い、Mail DB を cockpit から直接開きません。

## 起動

既存の `AGENTSTACK_HOME/env.sh`、または起動環境で `AGENTSTACK_RUNTIME_MODE=global` と `AGENTSTACK_GLOBAL_SERVER_CONFIG` を指定します。`AGENTSTACK_HOME` はその準備済み環境、`ORRERY_DASHBOARD_URL` は対応する loopback の Telemetry URL です。browser と app は同じ `scripts/start-cockpit.sh` を使います。global の設定・能力が欠けていたら旧 mode に戻らず停止します。

`scripts/setup.sh --check` / `--dry-run` は既存の共有 probe と instruction resolver の plan を呼び、project・Mail DB・provider file・service を変更しません。適用時も指示 block の変更は既存 resolver の同意手順に従います。研究セットの work folder は Mail の名前空間を変えません。

## Unlock と Lock

`agentstack-http-operator show` で、この cockpit の `AGENTSTACK_HOME` にある capability を確認して Unlock に貼り付けます。値は page session の `sessionStorage` に置きます。保存できない browser では memory のみで、reload 後は再度 Unlock が必要です。同じ origin の別 tab は短い handshake で権限を受け取ります。page に権限を与えた拡張機能や同 origin の code は信頼範囲に含まれます。

Lock は当該 page session の表示・terminal buffer・Mail 見出し・相手名・設定の観測値を消し、通信を中止します。同じ origin の tab にも通知します。server 側で capability を失効する操作ではありません。native app の clipboard・opener・pane 操作も Unlock 前と Lock 後は拒否します。

HTTP は static asset の読取りを除く全 route で共有 admission を使います。loopback だけでは許可せず、Host・Origin 等と private capability を確認します。WebSocket は接続直後の最初の frame で同じ capability を認証し、完了前は session 一覧・attach・input を扱いません。global では接続先の `?ws=` override を受け付けません。

## Mail と agent

右 pane の **View as** で正の agent ID に対応する視点を明示的に選びます。最近の Mail から返信の流れを開き、長い会話は **Load more visible mail** で続けます。見えない親の ID・名前は補いません。見えない前の Mail は短い案内、古い指示 block は控えめな案内と日英 docs のリンクで示します。Telemetry ボタンの network も同じ共有 controller を使います。

NEW AGENT は共有の登録・起動 controller を使います。中断した登録は status が示す Replay / Abandon へ進み、未知の process を推測で起動し直しません。terminal は認証済み WebSocket からの session を使います。

稼働状態・ctx・親子は Telemetry の既存のローカル観測を読取り、cockpit に別の台帳を作りません。観測できなければ **ACTIVITY UNKNOWN**。App の current provider live を証明できない場合も unknown です。quota は `/api/quotas` の値を直接表示します。

## 能力照合と確認範囲

認可済み `/telemetry/health` は `runtime_mode=global`、`api=1` と次の capability（各1）を返します: `operator_http_admission`、`global_mail_bridge`、`instruction_migration`、`websocket_first_frame_auth`、`global_runtime_observation`。upstream の binding・API・capability も返し、異なる binding を検出したら利用不可になります。これは切替の許可ではなく、共有 probe の `cutover_ready` は false のままです。

実 HTTP/管理 socket と合成 Mail、返信6段・長文・狭幅・light/dark・Lock を隔離して確認します。provider binary は不要です。実 provider と native app の操作、別 UID の実接続は外側の確認対象です。Gemini の実 agy は未確認です。

## 終了操作と PR7 の関門

global の Select/Exit は理由を示して無効にしています。旧 mode の終了操作は従来どおりです。global の単体・複数の exit / retire は、既存の終了処理を共有 admission/controller に接続して、**PR7 で既定を切り替える前に必ず対応・受入れ確認**します。legacy の `/api/exit` に通しません。

## 旧 UI の呼出し先の照合

`cockpit.html` と bridge の fetch / XMLHttpRequest / WebSocket / native invoke を照合した担当表です。非 static HTTP はすべて共有 admission を通します。

| 旧経路・用途 | global の扱い | 分類 |
| --- | --- | --- |
| `/telemetry/agents`, `/messages`, `/graph` の定期取得 | `/api/agents`, `/api/runtime-observations` と共有 network。旧 poll は起動しない | 6c 対応 |
| `/telemetry/mail/recent`, `/message`, `/thread` | `/api/mail/*` の共有 Mail controller。thread は返信の流れへ | 6c 対応 |
| `/telemetry/spawn-catalog`, `/spawn-status`, `/spawn`, `/fs/dirs` | 共有 operation controller の `/api/global/*`, `/api/fs/dirs` | 6c 対応 |
| `/telemetry/usage`, `/telemetry/portrait` | `/api/quotas`, `/portrait`。画像は認可済み blob で取得 | 6c 対応 |
| `/telemetry/open-url`, `/reveal-path`, `/open-ghostty`, `/path-probe`, `/platform`, `/identity`, `/sessions`, `/skills`, `/clipboard/files` | 同じ local handler を admission の内側で使う | 6c 対応 |
| `/telemetry/prefs` GET/PUT | 認可済み route は保持。旧同期 XHR driver は読み込まず、初期表示は browser の theme 設定を使う | 旧同期 driver は不要 |
| `/network`, `/network/*` と画像・共有 script | 固定 asset と canonical API のみ。任意 passthrough は撤去 | 6c 対応 |
| `/ws`: attach/detach/input/close/resize/release/refresh/codex-page | 最初の frame の認証後に既存 dispatch。close は terminal pane、release は入力権の解放で、agent の exit ではない | 6c 対応 |
| native clipboard/opener/pane/tour window | Unlock の内側だけ。theme の純粋な初期読取は既存のまま | 6c 対応 |
| `/api/exit`（単体・複数） | Select/Exit を理由付きで無効。旧 route に fallback しない | 明示無効＋PR7 前に必須 |

## 開発時の関連確認

共有 module の依存は CI と同じ Telemetry commit `b38b76a4abcd07b44c0184665ef8e7a2e3f0393e` の full clone を `ORRERY_TEST_TELEMETRY_ROOT` に指定します。`python -m pip install -r bridge/requirements.txt pytest -e "$ORRERY_TEST_TELEMETRY_ROOT/packages/agentstack_mail"` の後、global cockpit の関連試験を serial で実行します。browser 試験は既存の CDP service を `ORRERY_CDP_URL` に指定し、自分で browser を起動しません。実 tmux の試験と one-command installer は sandbox の外で、専用 HOME・socket・port を使います。
