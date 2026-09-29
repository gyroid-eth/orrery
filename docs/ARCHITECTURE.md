# 実装アーキテクチャ

> English version: [en/ARCHITECTURE.md](en/ARCHITECTURE.md)

[前: アーキテクチャ概要](ARCHITECTURE_OVERVIEW.md) · [README に戻る](../README.md) · [次: デザイン言語](DESIGN.md)

tmux・Codex App・network・データ保持・肖像画像の扱いは[アーキテクチャ概要](ARCHITECTURE_OVERVIEW.md)、セキュリティの前提は [README](../README.md#セキュリティとプライバシー) にあります。この文書は contributor 向けに backend、route、WebSocket、tmux 制御の実装責務だけを扱います。

## Component

| component | path | 責務 |
| --- | --- | --- |
| unified backend | `bridge/orrery_backend.py` | aiohttp origin、telemetry proxy、mail、portrait、tmux session manager |
| tmux control plumbing | `bridge/control_server.py` | control-mode parse、pane stream、input / resize |
| cockpit | `bridge/cockpit.html` | layout と entry point |
| frontend logic | `bridge/orrery_view.js`、`bridge/mail_view.js` | roster、terminal、graph、mail、interaction |
| desktop shell | `app/` | Tauri window、shared config、offline page、sidecar、global hotkey |
| history store | `ORRERY_HISTORY_DIR` | terminal recorder JSON |

backend は ORRERY Telemetry の source を import せず、dashboard を外部 HTTP service として扱います。

## 起動 sequence

1. bind host が `127.0.0.1` か検証
2. static / HTTP / WebSocket route を登録
3. default tmux server の live session を列挙
4. session ごとに recorder control client を接続
5. persisted terminal history を session identity と照合して復元
6. browser client の接続を待つ

browser が session を選ぶまで pane attach は遅延します。recorder connection は live session ごとに存在し、常時 history を更新します。

## HTTP route

| method / path | 実装責務 |
| --- | --- |
| `GET /ws` | WebSocket protocol v2 |
| `GET /telemetry/agents` | `:8770/api/agents` を取得し annotation と question 判定を merge |
| `GET /telemetry/messages?since=&limit=` | `:8770/api/messages-since` |
| `GET /telemetry/graph?all=&days=` | `:8770/api/graph` |
| `GET /telemetry/spawn-catalog` | `:8770/api/spawn-names` と local Codex catalog overlay |
| `POST /telemetry/spawn` | JSON object を `:8770/api/spawn` へ proxy |
| `POST /telemetry/open-ghostty` | session 検証と Ghostty attach |
| `GET /telemetry/health` | backend と dashboard reachability。`boot` は backend process の識別子（全 response の `X-Orrery-Boot` header と同じ値。page は変化を見て自分を reload する） |
| `GET` / `PUT /telemetry/prefs` | app window と browser tab で共有する cockpit 設定（`~/.orrery/prefs.json`）。PUT は `{"set": {...}, "remove": [...]}`。key は whitelist、値は文字列のみ |
| `GET /telemetry/usage?refresh=` | Claude / Codex のアカウント利用枠。provider ごとに60秒 cache、失敗時は前回値を `stale` で保持。`refresh=1` で cache を飛ばす |
| `GET /telemetry/mail/recent?limit=&agent=` | project-scoped SQLite recent。limit 1〜100、既定40 |
| `GET /telemetry/mail/message?id=` | message detail / recipient |
| `GET /telemetry/mail/thread?thread_id=&limit=` | thread。既定 / 最大50 / 100 |
| `GET /telemetry/portrait?name=&hi=&style=pixel` | local PNG または initials SVG |
| `GET /telemetry/sessions` | tmux inventory と interactive client flag |
| `GET /telemetry/skills` | built-in と `~/.claude/skills/*/SKILL.md`。30秒 cache |
| `GET /telemetry/fs/dirs?path=` | hidden を除く directory browser。最大200、root allowlist なし |
| `* /network` | ORRERY Telemetry dashboard root embed |
| `* /network/<tail>` | ORRERY Telemetry dashboard root 配下の passthrough |
| `* /api/<tail>` | ORRERY Telemetry API passthrough |
| `* /assets/<tail>` | ORRERY Telemetry asset passthrough |
| `GET /portrait` | ORRERY Telemetry portrait passthrough |
| `STATIC /<path>` | `bridge/` static。`/cockpit.html` を含み directory index 有効 |

passthrough は全 method を受けますが、request body を読むのは POST だけです。upstream response header は `Content-Type` と cache 制御以外を保持しません。

`/telemetry/spawn-catalog` の upstream 契約は ORRERY Telemetry の `/api/spawn-names` だけです。404 はそのまま返し、別の live-only route へ fallback しません。

## WebSocket protocol

`/ws` は protocol v2 の session inventory と pane stream を扱います。

client operation:

- attach / detach
- refresh
- input
- resize
- release
- close

server event:

- sessions inventory
- pane reset / snapshot
- incremental output
- layout / lifecycle update
- operation result / error

unknown session は error を返します。browser client ごとの attach / split 上限は12 session です。

## tmux safety

backend は default tmux server を使います。`TMUX_BIN` / `--tmux-bin` は executable の置換で、socket selector ではありません。

通常 session では attach、read、input、resize、refresh を許可します。pane `split` / `close` は session 名が `orrery-` で始まる場合だけ許可し、最後の1 pane の close を拒否します。

backend は session を自動作成・kill しません。legacy `control_server.py` は session 未指定時に test session を作るため、製品起動経路として使わないでください。

## Recorder と復元

recorder は `pyte` screen を更新し、30秒間隔で JSON を flush します。

- pane history 最大2000行
- attach snapshot 最大1000行
- 通常 retention 7日
- orphan retention 24時間

同名 session の stale history を誤復元しないため、session 名と pane ID だけでなく session creation identity を照合します。

Claim 中は `resize-window` で window size を pin します。backend の `SessionState.claimed_windows` は window ID ごとに、初回 Claim 直前の `WindowSizeSnapshot` を保持します。snapshot は local `window-size` option の有無と値、および正確な grid width / height です。同じ window の再 Claim では上書きしません。

frontend は Follow、auto release、group close、roster prune、`beforeunload` で、session 内の pane を window ID で distinct 化してから共通の release を送ります。backend の明示 release は対象 pane の tracked window だけを復元し、最後の peer detach / disconnect と teardown は tracked window 全件だけを復元します。Claim を行わない plain attach / detach では ownership map が空のため、外部 manual option を含む window-size command は発行しません。

restore は snapshot size への `resize-window`、control client の per-window size 更新、元の local option 復元の順で行います。元が未設定なら `set-option -u`、設定済みなら `manual` などの元値を再設定します。成功した entry だけを ownership map から消費します。初回 resize 後の rollback、release、detach、teardown のいずれで restore が失敗しても snapshot を保持して再試行でき、最終 teardown で残った window ID は stderr に記録します。

## Frontend runtime

cockpit は `xterm.js 5.5.0` と `addon-fit 0.10.0` を CDN から読みます。terminal logic は script load を前提にするため、self-contained distribution に変更する場合は asset vendoring、CSP、license notice、bundle inclusion を同時に更新してください。

prompt draft / history は各 window の `localStorage` だけに残ります。font、auto-shrink、split layout、mini mode / depth、colour theme、theme profile、NEW AGENT Advanced の開閉状態は `bridge/prefs_sync.js` が backend の `/telemetry/prefs`（`~/.orrery/prefs.json`）と同期します。読み込み時に同期 GET で `localStorage` へ写し、`setItem` を横取りして PUT し、4 秒ごとの GET で他 window の変更を取り込んで `oc:prefs-changed` を投げます。app window と browser tab が別々の設定を持って見た目が食い違う、という事故の再発防止です。Reset の対象は font と auto-shrink だけです。

## ORRERY Telemetry failure boundary

dashboard request は ORRERY backend 経由で proxy します。dashboard の failure を terminal failure に昇格させません。

| upstream failure | ORRERY の動作 |
| --- | --- |
| agents / graph / message API 不達 | offline 表示、terminal 継続 |
| spawn 不達 | 502、agent を作らない |
| embed root 不達 | TELEMETRY を利用不可 |
| annotation API 不達 | env / config / ORRERY Telemetry runtime / legacy の順に file fallback を試す |

spawn catalog の local fallback は modal 表示用で、spawn 実行の fallback ではありません。

## Security boundary

- bind は `127.0.0.1` 限定
- localhost 内の認証なし
- static は `bridge/` 全体を directory index 付きで公開
- `/telemetry/fs/dirs` に root allowlist なし
- dashboard control route を passthrough
- ORRERY Mail SQL だけ read-only

localhost-only を変更する場合は、認証、CSRF、origin、directory browser、terminal input、mail body、control API を一体で設計し直す必要があります。

## Test support

tmux-free frontend mock:

```bash
python3 bridge/tests/mock_backend.py
```

unified backend contract:

```bash
cd bridge
ORRERY_E2E_V2=1 .venv/bin/python tests/e2e_bridge.py -v
```

stream stress:

```bash
cd bridge
ORRERY_E2E_V2=1 ORRERY_STREAM_ROUNDS=20 \
  .venv/bin/python tests/e2e_bridge.py -v
```

E2E は専用 tmux socket と一意な test session を使います。default tmux server や実 agent session を cleanup 対象にしないでください。

`pytest` を別途導入した環境では同じ file を `-m pytest` でも実行できます。`bridge/requirements.txt` には `pytest` が含まれないため、標準 library の実行経路を基本例にしています。

## 文書の責務

- この文書: source component、route、protocol、実装制約
- [デザイン言語](DESIGN.md): visual token、motion、state 表現
- [使い方](usage.md): 利用者操作
- [設定](configuration.md): 環境変数の全数
