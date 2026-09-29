# 使い方

> English version: [en/usage.md](en/usage.md)

[前: 設定](configuration.md) · [README に戻る](../README.md) · [次: トラブルシューティング](troubleshooting.md)

ORRERY cockpit は、左の roster、中央の terminal、右の ORRERY Mail rail、系譜表示、ORRERY Telemetry の TELEMETRY を一つの画面にまとめます。

## やりたいことから探す

| やりたいこと | 操作 | 詳細 |
| --- | --- | --- |
| 稼働中の agent を見つけたい | 左 roster を検索し、tile をクリック | [Roster](#roster) |
| agent の名前を Mail の宛先や指示文に貼りたい | roster tile の名前の右にある copy icon | [名前のコピー](#名前のコピー) |
| よく見る agent を roster の上に固定したい | roster tile 右上の pin icon | [Pin](#pin) |
| agent の terminal を開いて指示したい | roster / palette から session を開き、composer で送信 | [Terminal](#terminal)・[Prompt composer](#prompt-composer) |
| 複数 agent を同時に見たい | `Cmd` / `Ctrl` を押しながら roster tile / session label / pane tab をクリック | [Split](#split) |
| 一つの terminal を cockpit から出して、別の窓で見たい | session label を terminal の上へ drag すると浮く。cockpit の外（または端）へ drag すると独立の窓になる。pane header の `↗ WINDOW` でも開ける | [独立の窓](#独立の窓) |
| agent が出した URL やパスを開きたい／手元のファイルを agent に渡したい | 端末の URL・パスをクリック／Finder でコピーしたファイルを composer に貼る | [端末から開く・端末に渡す](#端末から開く端末に渡す) |
| 画面を明るい配色にしたい | Settings › Color theme で `Light`（または `System`） | [配色テーマ（light mode）](#配色テーマlight-mode) |
| Claude / Codex の利用枠の残りを知りたい | header の `LEFT` pill を見る。クリックで window ごとの残量 | [Usage（残量表示）](#usage残量表示) |
| terminal の過去出力から末尾へ戻りたい | `↓ BOTTOM`、`Cmd+↓`、または active な session label / pane tab を再クリック | [Terminal](#terminal) |
| agent を新しく起動したい | `+ NEW AGENT` で engine、directory、task を指定 | [NEW AGENT](#new-agent) |
| agent 間の会話を読みたい | 右 mail rail の card を開く。二者間を追う場合は TELEMETRY の NETWORK edge をクリック | [Agent Mail](#agent-mail)・[TELEMETRY](#telemetry) |
| spawn の親子関係と最近の通信を見たい | mini-orrery を見る。header の `PLANETARIUM` か `⤢` で Planetarium を開く | [Mini-orrery](#mini-orrery)・[Planetarium](#planetarium) |
| TELEMETRY で見つけた agent の terminal を開きたい | TELEMETRY で agent を選び `OPEN IN COCKPIT` | [TELEMETRY から cockpit で開く](#telemetry-から-cockpit-で開く) |
| Windows（WSL2）で使う | shortcut は `Alt`、窓は Windows Terminal で開く | [Windows（WSL2）での違い](#windowswsl2での違い) |
| 終了した agent を復活させたい | TELEMETRY で gone / retired agent を選び `RESUME` | [TELEMETRY](#telemetry) |
| 複数 agent をまとめて終了したい | native roster の `Select`、または TELEMETRY の `SELECT` から `EXIT` | [Select と一括 EXIT](#select-と一括-exit) |
| 複数 agent の履歴を時系列で再生したい | TELEMETRY で対象を複数選択し `DIGEST REPLAY` | [REPLAY](#replay) |
| session を素早く切り替えたい | `Cmd+K` で検索、または `Cmd+1`〜`Cmd+9`（WSL では `Alt+K`、`Alt+1`〜`Alt+9`） | [Jump palette と shortcut](#jump-palette-と-shortcut) |
| 特定 session を直接開く URL を作りたい | `cockpit.html?session=<session-name>` | [Jump palette と shortcut](#jump-palette-と-shortcut) |
| terminal を Ghostty でも開きたい | active session の `GHOSTTY`（WSL では `WIN TERMINAL`） | [Ghostty で開く](#ghostty-で開く)・[Windows（WSL2）での違い](#windowswsl2での違い) |
| tmux の表示幅を ORRERY に合わせたい／外部 client に戻したい | `CLAIMED` / `FOLLOW` を切り替える | [Claim / Follow](#claim--follow) |
| ORRERY.app を keyboard で表示／非表示にしたい | install 時に登録された global hotkey を使う | [インストールの global hotkey](install.md#global-hotkey) |

## 見つけにくい操作の一覧

次は、実装上は利用できても、画面に恒常的な説明がない、短い hint だけ、hover して初めて分かる、または埋め込み TELEMETRY の中にある操作です。この表を機能追加時の発見可能性 checklist とします。Settings や `+ NEW AGENT` のように、常時見える明示的な button だけで到達できる機能は除外しています。

| 見つけにくい操作 | 画面上の手がかり | この文書での説明 |
| --- | --- | --- |
| `Cmd+K` の agent / tmux session palette（WSL では `Alt+K`） | palette を開くまで shortcut 表示なし | [Jump palette と shortcut](#jump-palette-と-shortcut) |
| `Cmd+1`〜`Cmd+9` で attach 済み session を切替（WSL では `Alt+1`〜`Alt+9`） | 常時表示なし | [Jump palette と shortcut](#jump-palette-と-shortcut) |
| roster tile の copy icon で agent 名をコピー | hover したときだけ icon が出る | [名前のコピー](#名前のコピー) |
| roster tile の pin icon で agent を上に固定 | 固定前は hover したときだけ icon が出る | [Pin](#pin) |
| roster tile の hover / keyboard focus で詳細 card（pane title、最新 mail、runtime など） | hover するまで出ない | [Roster](#roster) |
| header の `N need you` chip で、質問・承認待ちの agent だけに roster を絞る | 該当 agent がいるときだけ chip が出る | [Roster](#roster) |
| `Esc` で roster の Select mode を抜ける | 常時表示なし | [Select と一括 EXIT](#select-と一括-exit) |
| `Cmd` / `Ctrl` + roster tile、session label、pane tab で Split へ追加／除外 | terminal 未選択時の小さな hint のみ | [Split](#split) |
| single 表示へ移った後、`SPLIT n` chip で直前の Split を復元 | chip の tooltip のみ | [Split](#split) |
| Split の identity label を別 cell へ drag して順番を交換 | drag handle 表示なし | [Split](#split) |
| session label を drag して浮かせる、浮かせた窓の title bar を cockpit の外（または端）へ出して独立の窓にする | drag handle 表示なし。見えるのは pane header の `↗ WINDOW` だけ | [独立の窓](#独立の窓) |
| tab strip の `⊞` chip で Split の layout を選ぶ | chip の文字は現在の layout 名だけ | [Split](#split) |
| Split divider を drag、grid divider を double-click して比率 reset | hover line と tooltip のみ | [Split](#split) |
| active な session label / pane tab / Split identity label の再クリックで末尾へ移動 | label 上に説明なし | [Terminal](#terminal) |
| `Cmd+↓` で active terminal の末尾へ移動（Mac のみ） | 常時表示なし。scroll 中は `↓ BOTTOM` が現れる | [Terminal](#terminal) |
| session group の `×` は tmux を kill せず detach、pane tab の `×` は管理 pane の close request | 同じ `×` で意味が異なる | [Terminal](#terminal)・[Split](#split) |
| composer の `Esc` interrupt、`↑` / `↓` history、`/` か `$` で skill 候補、画像 paste | composer 上部の短い hint のみ | [Prompt composer](#prompt-composer) |
| session を終える built-in や記号の取り違えを、送信前に止める送信ガード | 該当する入力を送ったときだけ出る | [送信ガード](#送信ガード) |
| 端末の URL をクリックで browser、パスをクリックで Finder／エクスプローラー | mouse を乗せると下線が出るだけ | [端末から開く・端末に渡す](#端末から開く端末に渡す) |
| Finder でコピーしたファイルを composer に貼ると絶対パスが入る（drag & drop は無い） | 貼ったあとの toast のみ | [端末から開く・端末に渡す](#端末から開く端末に渡す) |
| `LEFT` pill のクリックで window ごとの残量と reset、取れないときの理由 | pill には最小の % だけ | [Usage（残量表示）](#usage残量表示) |
| Settings の Color theme（Dark / Light / System）と Vision profile | Settings を開くまで見えない | [配色テーマ（light mode）](#配色テーマlight-mode) |
| Split の cell の名札の `×` で、その session だけを外す | 名札に mouse を乗せたときだけ出る | [Split](#split) |
| 独立の窓の書きかけの下書きが、窓を閉じると cockpit に戻る | 戻ったときの表示なし | [独立の窓](#独立の窓) |
| roster の検索の件数 `N/M` と、0 件のときの `Clear` | 検索したときだけ出る | [Roster](#roster) |
| `?session=` deep link と開発用 `?ws=` override | UI 入口なし | [Jump palette と shortcut](#jump-palette-と-shortcut) |
| mini-orrery node の hover で identity / role / model、click で mail filter と terminal jump | node に text label なし | [Mini-orrery](#mini-orrery) |
| mini-orrery の `⤢` で Planetarium、`Esc` または外側 click で閉じる | glyph の text label なし | [Planetarium](#planetarium) |
| mail card click で本文、`thread` で thread、`Esc` で drawer を閉じる | card / drawer を開くまで詳細なし | [Agent Mail](#agent-mail) |
| roster tile / mini-orrery node / terminal の focus に合わせて mail rail の filter が切り替わる | filter chip の選択が変わるだけ | [Agent Mail](#agent-mail) |
| NEW AGENT の scientist 選択後、🎲 で未使用 adjective を再抽選 | icon と tooltip のみ | [NEW AGENT](#new-agent) |
| TELEMETRY NETWORK の edge click で二者間 mail drawer | ORRERY 側の button からは分からない | [TELEMETRY](#telemetry) |
| TELEMETRY の agent panel の `OPEN IN COCKPIT` で、その agent の terminal へ移る | TELEMETRY を開いて agent を選ぶまで見えない | [TELEMETRY から cockpit で開く](#telemetry-から-cockpit-で開く) |
| TELEMETRY で gone / retired agent を選んで `RESUME` | 終了 agent は native roster に出ない | [TELEMETRY](#telemetry) |
| TELEMETRY の複数選択から一括 `EXIT` / `RESUME` / `DIGEST REPLAY` | TELEMETRY を開くまで見えない | [TELEMETRY](#telemetry)・[REPLAY](#replay) |
| TELEMETRY の spawn name 衝突時に `SHUFFLE` で同じ scientist の別名を再提案 | embedded spawn modal 内だけに表示 | [NEW AGENT](#new-agent) |
| ORRERY.app の global show / hide hotkey と、その候補の優先順 | cockpit 内に現在の割当表示なし | [インストールの global hotkey](install.md#global-hotkey) |

## 起動後の確認

1. header に `connecting` / `disconnected` / `error` が出ていないか確認（live のときは何も出ない）
2. `/telemetry/health` で ORRERY Telemetry dashboard の到達状態を確認
3. roster の agent 名と `tmux list-sessions` の session 名が一致するか確認
4. terminal を一つ開き、入力と output を確認

ORRERY Telemetry が不達でも terminal は利用できます。roster は `dashboard offline`、spawn はエラー、TELEMETRY embed は停止します。

## Roster

Roster は ORRERY Telemetry `/api/agents` を3秒間隔で取得し、稼働中の agent を表示します。

tile の読み方（上から）:

- scientist portrait と名前（hover すると名前の右に copy icon、右上に pin icon）
- engine（`claude` / `codex` / `gemini` など）、`model · context window`、role。role が無いときは、他の agent と見分けられる cwd の末尾を出す
- `CTX` の棒と %: その agent の **context の使用率**。65% を超えると色が変わる
- 状態の記号と説明文: `◇` 作業中、`⏎` 承認待ち、`?` 質問待ち、`·` 待機。説明文は task が具体的ならそれ、無ければ pane title、どちらも無ければ `Needs description`。task が変わると `updated Nm ago` が付く

並び順は、pin した agent → 承認・質問待ち → 作業中 → 待機 → 最後に動いた順 → 名前 です。tile をクリックすると、agent と同名の tmux session を必要に応じて attach して focus します（`Tab` で focus して `Enter` / `Space` でも同じ）。

検索欄は、名前・説明文（task か pane title）・role（無ければ cwd の差分）を対象に絞り込みます。model や provider は対象外です。絞り込み中は件数が `N/M` で出て、1 件も合わないときは `searched: task, role, cwd · Clear` の帯が出ます。

![roster の検索。左は test で1件に絞った状態、右は1件も合わず searched の帯が出た状態](images/cockpit_roster_search.png)

warmup、finished、gone、retired の row は左 roster に表示しません。Codex App Bridge 由来の agent は telemetry には現れますが tmux pane を持たないため、terminal jump は offline hint になります。

tile をクリックすると、右の mail rail の filter もその agent に切り替わります。tile に mouse を乗せる（または `Tab` で focus する）と、右に詳細 card が出ます。pane title、最新 mail の件名、最後に動いた時刻、ORRERY Mail への登録時刻、起動時刻、provider / model / command、成果物の数（Deliverables。1 件以上あるときだけ）、表示している説明文の出どころと具体さが並びます。

![CoralCurie の tile に mouse を乗せて出した詳細 card。Deliverables 3 の行がある](images/cockpit_roster_detail.png)

成果物（Deliverables）は、ORRERY Telemetry が project の `logs/` から集めた、その agent の作業ログ（`LOG_*.md` のうち frontmatter の `agent:` がその agent のもの）です。一覧は TELEMETRY の agent panel の `Output` タブで開けます（[TELEMETRY](#telemetry)）。

header の `working` / `waiting` は稼働中 agent の数です。

### 人の判断が要る agent

質問への回答（`?`）や承認（`⏎`）を待って手が止まった agent は、次のように目立たせます。

- roster の肖像の輪が光る。承認待ちは赤く点滅し、質問待ちは水色でゆっくり明滅する（OS で動きを減らす設定にしていると、質問待ちの明滅は止まる）
- tile が roster の上のほうへ並ぶ（pin した agent の次）
- header に `N need you` が出る。クリックするとその agent だけに roster を絞り、もう一度押すと解除する（待っている agent がいなくなると自動で解除）
- mini-orrery と Planetarium の node の右上に `?`（質問待ち）か `!`（承認待ち）が付く

tile をクリックすればその端末に入り、質問を読んで composer から答えを送れます。答えて agent が動き出すと、点滅と `need you` は消えます。

![7体の中で PearlFaraday だけが赤く点滅し、1 need you が出る。need you で絞り込み、tile をクリックして承認の質問を読み、composer から 1 を送ると点滅が消える](images/cockpit_need_you.gif)

TELEMETRY の DECK と NETWORK での見え方は [介入待ちの見分け方](#介入待ちの見分け方) にあります。

![roster の tile。WildNewton は pin で上に固定され、CosmicGuericke には hover で copy icon と詳細 card が出ている](images/cockpit_roster_pin_copy.png)

### 名前のコピー

tile に mouse を乗せると、agent 名の右に copy icon が出ます。クリックすると agent 名だけ（emoji や role を含まない、Mail と spawn が使う名前そのもの）をクリップボードに入れ、右下に `COPIED · <name>` と出ます。Mail の宛先や、別の agent への指示文にそのまま貼れます。

クリップボードが使えない window や、ブラウザが書き込みを許可しなかった場合は `COPY FAILED · …` と出ます。3秒待っても応答がない場合も失敗として表示します。Select mode の間は icon を出しません。

### Pin

何体も動いていると、roster は状態の順に並び替わり続けます。親の agent やレビュー役など、いつも見る agent は pin しておくと、並び替えに関係なく上に留まります。

tile 右上の pin icon を押すと、その agent を roster の上に固定します。固定した agent と、それ以外の間には区切り線が入ります。もう一度押すと外れます（`PINNED` / `UNPINNED` と表示）。

![状態の変化で並び替わる roster の中で JadeNoether を pin すると上に留まり、区切り線ができる。もう一度押すと外れる](images/cockpit_pin.gif)

pin は左 roster だけの機能です。右の mail rail や mini-orrery には pin はありません。pin の状態は Settings と同じく ORRERY.app と browser tab の間で共有され、agent が retire すると自動で外れます。Select mode の間は icon を出しません。

## Usage（残量表示）

header の Settings の左にある `LEFT  CLAUDE 41%  CODEX 47%` の pill は、**アカウント単位の利用枠があとどれだけ残っているか**です。各 agent の `CTX`（その session の context の使用率）とは別物です。pill には provider ごとに、通常の枠のうち **残りが最も少ない window の %**（次の仕事を実際に縛る枠）を出します。

pill をクリックすると `Usage left` が開き、provider が返した window を円弧の dial で、reset までの時間つきで並べます。

![Usage left。Claude は 5H 64%・7D 41%・FABLE 18%、Codex は 5H 88%・7D 47%。Codex の追加枠 Spark は untouched](images/cockpit_usage_popover.png)

- **Claude**: `5h`（5 時間の枠）、`7d`（週の枠）、モデル別の週の枠（`FABLE` など。サーバーが返したときだけ）
- **Codex**: `5h`、`7d`。Spark などの名前付きの追加枠は `ADDITIONAL LIMIT` の下に分けて出し、pill の値には使いません。追加枠を全く使っていないときは `untouched · 5h / 7d at 100% left` の 1 行にまとめます
- 数字と輪の色: 50% より上は緑、50% 以下で黄、20% 以下で赤
- 各 dial の下は reset までの時間（`in 2h 59m`、`in 3d`）。見出しの右は、いちばん早い reset の時刻

![LEFT をクリックして Usage left を開き、残量が減っていく様子。5H が 64% から 19% へ、色が緑から黄、赤へ変わる](images/cockpit_usage.gif)

**取得元と更新の間隔**: cockpit は provider を直接読みません。ORRERY Telemetry の dashboard が読んだ値（`/api/quotas`）を、ORRERY backend 経由で受け取ります。

- Claude: Claude Code が保持している OAuth token で、Anthropic の usage endpoint を読みます（token は読むだけで、更新や書き戻しはしない）
- Codex: `codex app-server` の `account/rateLimits/read`
- cockpit は 1 分ごと（tab が見えている間）、pill を開いたとき、tab に戻ったときに読み直します。ORRERY backend は同じ値を 60 秒 cache します。provider への問い合わせの頻度は ORRERY Telemetry が決めます（Claude は約 10 分に 1 回）

**古くなったとき・取れないとき**: 取得に失敗した間は、前回の値を残したまま、pill の数字を薄くし、`Usage left` の見出しに `· stale` を付けます。取れない理由は見出しの右に出ます。

| 表示 | 意味 |
| --- | --- |
| `sign in to Claude Code` | Claude Code の token が無い、または失効している |
| `codex not on PATH` | `codex` が見つからない |
| `not reachable` | provider に届かない |
| `rate limited · retrying later` | provider に回数を制限された。あとで取り直す |
| `unavailable` | ORRERY Telemetry が止まっている、またはその provider の値を返していない |

独立の窓（[独立の窓](#独立の窓)）では、残量表示を取りに行きません。

## Select と一括 EXIT

Select mode では eligible な live agent を複数選び、ORRERY Telemetry の `/api/exit` へ順番に request します。

1. Select mode を開く
2. 対象 agent を選ぶ
3. EXIT を押す
4. 3秒以内に二段目の確認を押す

`Esc` で Select mode を抜けます。

これは agent process へ終了を依頼する変更操作です。mail の読み取りや UI filter とは異なり、実行前に対象を再確認してください。ORRERY Telemetry dashboard が不達の場合は利用できません。

## Terminal

terminal は `xterm.js` を使い、ORRERY backend の `/ws` と tmux control mode を介して pane を操作します。

- session group と pane tab
- keyboard input
- browser 側6000行の scrollback
- `↓BOTTOM` または `Cmd+↓` で末尾へ移動
- backend 切断後1.5秒で自動再接続
- pane 内の URL はクリックで既定ブラウザ、`/…` や `~/…` の絶対パスはクリックで Finder（ファイルは選択表示、フォルダは開く）。空白入りのパスも実在する範囲まで自動で判定。`/compact` のような 1 語や相対パスはリンクにならない

active な session label / pane tab を再クリックしても末尾へ移動します。`Cmd+↓` は Mac だけです。WSL では `↓ BOTTOM` か label の再クリックを使います。session group の `×` は cockpit から detach するだけで、tmux session を kill しません。pane tab の `×` は backend へ pane close を要求しますが、破壊的 close は `orrery-` prefix の管理 session だけに制限され、最後の1 pane は閉じません。

backend は起動時に live tmux session ごとに recorder connection を一つ接続します。browser からの pane attach は tile / palette の操作時に遅延実行されます。

上に scroll して過去の出力を読んでいる間は、新しい出力が来ても末尾へ引き戻しません。backend を再起動すると、cockpit は page を自動で読み直します（composer の下書きは残る）。

## 端末から開く・端末に渡す

agent が端末に出した URL やファイルのパスは、そのままクリックで開けます。逆に、手元のファイルは貼り付けるだけで agent に渡せます。

![端末の URL をクリックすると browser で開き（URL の toast）、パスをクリックすると Finder で表示され（FINDER の toast）、composer にファイルを貼るとパスが入る](images/cockpit_open_paste.gif)

- **URL をクリック**: 既定の browser で開きます（`https://` と `http://` だけ）
- **パスをクリック**: `/…` や `~/…` の絶対パスは、Finder（Windows ではエクスプローラー）で表示します。ファイルは選択した状態で、フォルダは開いた状態になります。空白を含むパスも、実在する範囲まで自動でリンクにします。`/compact` のような 1 語や相対パスはリンクになりません
- **ファイルを貼る**: Finder でファイルをコピーし（`Cmd+C`）、composer で `Cmd+V` を押すと、カーソルの位置にファイルの**絶対パス**が入ります。複数ならスペースで区切り、空白や引用符を含むパスは `'…'` で囲みます。`path → composer`（複数なら `N paths → composer`）と出ます。「このファイルを読んで」と書き足して送れば、agent にファイルを渡せます
- **画像を貼る**: スクリーンショットなど、ファイルではない画像のデータを貼ると、composer ではなく agent の端末に `Ctrl+V` を送り、CLI 自身に画像を読ませます（`image → <agent>` と出る）。WSL では、画像を PNG に保存してそのパスを composer に入れます

ファイルや画像を cockpit に **drag & drop することはできません**。貼り付けを使います。

Windows（WSL2）では、URL は Windows の既定の browser、パスはエクスプローラーで開きます。どちらも、backend を Windows Terminal などデスクトップから起動したときに有効です（ssh 経由で起動した backend では窓が出ません）。ファイルや画像の貼り付けも使えます。WSL での仕組み（エクスプローラーでコピーしたファイルは WSL のパスに直して入る、スクリーンショットは PNG に保存してそのパスが入る）は [WSL でのファイル・画像の貼り付け](#wsl-でのファイル画像の貼り付け) を見てください。

## Split

`Cmd` または `Ctrl` を押しながら agent / session を選ぶと、最大12 session を同時表示できます。

- 2〜4件、5件以上に応じた layout preset
- row / column / wide / main-left / grid
- divider drag でサイズ変更
- label drag で並べ替え

![3件の Split。CoralCurie の名札を PearlFaraday の cell へ drag して位置を入れ替え（SPLIT · CoralCurie ↔ PearlFaraday）、続けて境目を drag して幅を変える](images/cockpit_split_drag.gif)

cell の名札に mouse を乗せると `×` が出ます。押すとその session を cockpit から外し（tmux の session は残る）、残りが 1 つになると single 表示に戻ります。名札の drag は `Esc` で取り消せます。

Split を一時的に離れて single session を表示しても、member list は `SPLIT n` chip に残り、chip を押すと復元できます。Split cell 上部の identity label は click で focus、別の cell へ drag すると二つの位置を交換します。divider の比率は drag で変更でき、grid layout の divider は double-click で均等比率へ reset します。

tab strip の `SPLIT n` の右にある `⊞` chip（現在の layout 名を表示）を押すと、その人数で選べる layout の一覧が開きます。2件は ROW / COLUMN、3件は WIDE / MAIN-L / ROW / COLUMN、4件以上は GRID / ROW / COLUMN です。選んだ layout は人数ごとに記憶されます。Split に入っている session の tab には `⊞` の印が付きます。

![3件の Split。SteelCurie、HazelBell、FoggyLavoisier の端末を横に3列並べた ROW layout](images/cockpit_split.png)

![`⊞ WIDE` chip から開いた 3 pane layout の一覧](images/cockpit_split_layout.png)

この Split は複数 session を並べる表示機能です。tmux の `split-window` とは異なり、通常の agent session に新しい pane を作りません。

WebSocket protocol 自体の破壊的 `split` / `close` は、`orrery-` prefix の管理 session だけに許可されます。`close` は最後の1 pane を消しません。

## 独立の窓

一つの session の terminal を cockpit から出して、浮かせたり別の窓で開いたりできます。

- **浮かせる**: tab strip の session label をつかみ、terminal の上で離す。cockpit の上に、title bar 付きの小さな窓として浮く。title bar で移動、右下の角でサイズを変える
- **独立の窓にする**: session label を cockpit の外へ drag して離す。浮かせた窓なら、その title bar を外へ出す。窓が最大化されていて外が無いときは、端の 8px で離す（ghost に `OWN WINDOW` と出る）。active な pane の header にある `↗ WINDOW` を押しても開ける
- **戻す**: 窓を閉じると、session は元の cockpit の tab に戻って前面になる。浮かせた窓の `⇤`、独立の窓の header の `⇤ COCKPIT`、tab strip のチップの `⇤` でも戻せる

![session の名札を tab strip から terminal の上へ drag して浮かせ（FLOAT）、title bar で動かし、↗ で独立の窓にし（WINDOW のチップ）、窓を閉じると tab に戻る](images/cockpit_pane_float.gif)

外に出ている session は、tab strip に `◰ FLOAT` / `↗ WINDOW` のチップとして残ります。チップをクリックすると、その窓が前面に来ます。roster や palette からその agent を選んだときも、cockpit に二重に開かず、窓のほうを前面にします。Split に入っていた session は、外に出すと Split から外れます。戻したときは、通常の tab として戻ります。

![JadeNoether を cockpit の上に浮かせ、CoralCurie を独立の窓で開いた状態。tab strip に ◰ FLOAT と ↗ WINDOW のチップが並ぶ](images/cockpit_pane_window.png)

独立の窓の中身は、同じ cockpit の page を一つの session だけの表示（`cockpit.html?solo=1&session=<name>`）で開いたものです。backend から見ると、同じ session に websocket が一つ増えるだけです。tmux への接続（recorder）は増えません。session が外に出ている間、cockpit はその session を detach します。そのため、同じ session が二つの幅で同時に描かれることはありません。Claim / Follow は、外に出た窓のサイズで働きます。

窓の開き方は環境で異なります。

- ORRERY.app: app の窓として開く
- browser（Mac の browser、WSL の Windows 側の browser）: popup として開く。popup が block されたときは toast が出て、浮かせる表示にとどまる。cockpit の origin（`127.0.0.1:8791` など）で popup を許可する

cockpit を reload しても、開いている窓は自動で引き取られ、チップが戻ります。

窓の composer に書きかけの文があるまま窓を閉じると、その下書きは cockpit の composer に戻ります（cockpit 側に別の下書きがあるときは上書きせず、`UNSENT TEXT … KEPT` と出して窓側の下書きを残す）。

## Claim / Follow

interactive terminal client がない session では、ORRERY が viewport size を claim して tmux window を調整します。Ghostty など別の interactive client が現れると、通常は claim を解放してその client に follow します。

- Claim は tmux の実際の grid size を変更
- 外部 client の折り返し幅にも影響
- 手動 toggle は自動判定より優先
- window ごとの初回 Claim 直前に、local `window-size` option の有無と値、正確な grid size を snapshot
- 同じ window の再 Claim では初回 snapshot を上書きしない
- Follow は session 内で ORRERY が ownership を持つ distinct window すべてへ release を送り、各 snapshot を復元
- group close / auto detach / app close は owned window を release してから detach
- backend も最後の peer detach / disconnect / teardown 時に tracked window だけを復元

復元時は Claim 前の grid size と local option をそのまま戻します。元が未設定なら未設定へ戻し、外部 client が設定した `manual` などの値は元値へ戻します。Claim せず attach / detach しただけの window には size command を発行せず、外部の manual 設定を変更しません。

画面共有や既存 TUI を操作中は、Claim による width 変更を意識してください。復元に失敗した tracked entry は消費せず、後続の release / detach / teardown で再試行します。teardown でも復元できなかった場合は backend が session 名と window ID を stderr に記録します。

## Ghostty で開く

active session を外部 Ghostty で開けます。実装は次の executable を使用します。

```text
/Applications/Ghostty.app/Contents/MacOS/ghostty
```

既に interactive client が attach 済みなら新しい window は開かず、`already` として扱います。Ghostty path の公開 override はありません。

## Prompt composer

composer は、端末とは別の入力欄です。端末に直接打つと、他の agent からの通知が同じ端末に流れ込んで書きかけが埋もれますが、composer に打っている文は、端末に何が流れてきてもそのまま残ります。

送り先は、そのとき active な pane の agent です（composer の左に顔と名前が出る）。roster の tile や tab をクリックして別の agent を active にすると、送り先だけが切り替わり、打っている文はそのまま持ち越されます。

![CoralCurie への指示を打っている間に通知が流れてきても書きかけは残り、roster で OnyxDarwin をクリックして送り先を替えて送る](images/cockpit_composer_calm.gif)

下書きは cockpit に 1 つだけで、送り先の agent ごとには分かれません。打つたびに保存され、reload や ORRERY.app の再起動のあとも残り、送信すると消えます。保存先はその window の `localStorage` で、他の window とは共有しません。独立の窓は、それぞれの session ごとに自分の下書きを持ちます（閉じると cockpit に戻る。[独立の窓](#独立の窓)）。

composer は active pane へ bracketed paste を送り、250 ms 後に carriage return を送信します。

| 操作 | 動作 |
| --- | --- |
| `Enter` | 送信 |
| `Shift+Enter` | 改行 |
| `Esc` | interrupt |
| `↑` / `↓` | 最大50件の送信履歴 |
| ファイル paste | コピーしたファイルのパスを composer に入れる（空白を含むパスは引用符で囲む） |
| 画像 paste | Mac: literal `Ctrl+V` を TUI へ転送。WSL: 画像を PNG として保存し、そのパスを composer に入れる |

IME composition 中の Enter は誤送信を避ける guard があります。送信履歴も `localStorage` に保存されます。

`⎋ STOP` は `Esc` と同じ interrupt、`SEND ⏎` は `Enter` と同じ送信です。送ると `sent → <agent>` と出ます。composer の左には送信先の agent の顔と名前が出ます。ファイルを貼るとパスが入ります（[端末から開く・端末に渡す](#端末から開く端末に渡す)）。

### skill と command の候補

入力が `/` か `$` で始まると、送信先の CLI の skill と built-in command を最大8件、候補に出します。`↑` / `↓` で選び、`Tab` か `Enter` で確定すると、その CLI の正しい記号（Claude と Gemini は `/`、Codex は `$`）に直して入れます。

| 送信先 | skill を探す場所 | built-in |
| --- | --- | --- |
| Claude Code | `~/.claude/skills` | compact / clear / model / mcp / resume / help |
| Codex | `~/.codex/skills`（同梱の skill を含む） | compact / new / model / approvals / status / help |
| Gemini | `~/.gemini/skills` | compress / clear / model / mcp / stats / help |

![Codex の agent に $r と打つと、$review-pr（skill）と approvals（built-in）が候補に出る](images/cockpit_skill_menu.png)

### 送信ガード

送信する前に、1 行目が次のどちらかなら送らずに止め、composer の上に確認の帯を出します。

- **session を終える・消す built-in**: Claude の `/clear` `/logout` `/exit` `/quit`、Codex の `/logout` `/quit` `/exit` `/new`、Gemini の `/clear` `/exit` `/quit`
- **記号の取り違え**: Codex に `/名前`、Claude に `$名前` を送ろうとしたとき。同じ名前の skill があれば、正しい記号に直して送るボタンを出す

帯のボタンは、直して送る（例 `send as $review-pr`）・`send as typed`（そのまま送る）・`cancel` です。

![Codex の agent に /review-pr 3 を送ろうとすると、codex runs skills as $review-pr と止まり、send as $review-pr を選べる](images/cockpit_send_guard.png)

## Jump palette と shortcut

`Cmd+K` で fuzzy search palette を開きます。対象は roster agent と tmux-only session です。

- `↑` / `↓`: 選択
- `Enter`: focus / attach
- `Esc`: 閉じる
- `Cmd+1`〜`Cmd+9`: attach 済み session を focus

split member がある場合は、その並びが number shortcut で優先されます。

URL から session を指定できます。

```text
http://127.0.0.1:8791/cockpit.html?session=<session-name>
```

開発時だけ `?ws=ws://127.0.0.1:<port>/ws` で WebSocket を上書きできます。

## NEW AGENT

`+ NEW AGENT` は ORRERY Telemetry dashboard の spawn API を使います。dashboard が offline の場合、catalog の一部を表示できても spawn は実行できません。

入力項目:

- Auto または Scientist + Adjective の identity
- Claude / Codex provider、model、reasoning effort
- working directory
- task（必須、最大4000文字）
- standalone または parent
- role / emoji / group
- worktree / base revision
- headless または Ghostty

parent 候補は live Claude agent だけです。Auto は `name:null` を送り、名前・model・effort・directory の最終検証は ORRERY Telemetry server が行います。

`Spawn` を押すと、右下に経過が出ます。`LAUNCHING · <名前>` のあと、起動できれば `SPAWNED · <名前>`、失敗すれば `SPAWN FAILED · <名前> · <理由>` です。140 秒たっても結果が返らないときは `no verdict after 140s` と出ます（agent は起動しているかもしれないので、roster を確かめる）。

scientist を選ぶと未使用の adjective が自動で一つ選ばれ、name card の 🎲 で再抽選できます。embedded TELEMETRY 側の spawn modal では、名前の衝突時に `SHUFFLE` が同じ scientist の別の verified name を server に再提案させます。

filesystem browser は hidden directory を除外し、最大200件を返します。ただし ORRERY の `/telemetry/fs/dirs` には root allowlist がないため、localhost-only の利用境界を維持してください。

## Mini-orrery

mini-orrery は live agent の spawn forest と、直近90秒の mail edge / comet を表示します。

- node click で agent / session へ jump
- node hover で identity、role、model を表示
- spawn edge で親子関係を表示
- mail edge で最近の通信を表示
- Settings で全体 Orrery と active agent 中心の Telemetry network を切り替え
- Telemetry network の深さは1〜3 hop

色は lineage に使い、稼働状態は motion で表します。node の右上の `?` は質問への回答待ち、`!` は承認待ちです。重要度 high / urgent の Mail の comet は大きく描きます。

## Planetarium

header の `PLANETARIUM`、または mini-orrery 右上の `⤢` で overlay を開きます。

- spawn forest
- 直近90秒の live mail
- agent jump
- `OPEN TELEMETRY`

![Planetarium。親の LuckyGoodall から子の BraveTuring と GreenMaxwell へ spawn の線が伸び、親を持たない LimeGalileo は別の木として並ぶ](images/cockpit_planetarium.png)

![PLANETARIUM で木を開き、Mail が届くたびに線が光る。node をクリックするとその端末へ移る](images/cockpit_planetarium.gif)

node をクリックすると、その agent の terminal へ移り、overlay を閉じます。`Esc`、外側の click、または右上の `⤢` でも閉じます。mini-orrery を Settings で Telemetry network 表示にしていても、Planetarium は常に spawn forest を描きます。Planetarium は cockpit 内の系譜探索です。ORRERY Telemetry dashboard の full NETWORK / DIGEST REPLAY とは役割が異なります。

## Agent Mail

右 rail は ORRERY Telemetry の live message window と、ORRERY が read-only SQLite から取得する recent 40件を merge / dedupe します。

- ALL または最近8 agent で filter
- message detail
- 安全な限定 Markdown
- thread 表示（最大50件）

![新しい Mail が流れてきて、card で本文、thread で往復を時系列に読み、roster で agent を選ぶとその Mail に絞られる](images/cockpit_mail.gif)

mail card をクリックすると、rail の下半分がその message の drawer に切り替わります。drawer には送信者、宛先（to / cc の区別）、正確な時刻と経過時間、importance、件名、本文が出ます。thread のある message は `thread (n)` で時系列表示に切り替わり、thread 内の項目をクリックするとその message を開きます。`←` か `Esc` で一覧に戻ります。

![左: mail rail の一覧。上の mini-orrery に親子の木、その下に filter chip と card が並ぶ。右: card をクリックして開いた drawer](images/cockpit_mail_rail.png)

mail card や送信者名をクリックしても、terminal へは移りません。agent の terminal を開くには、左 roster の tile か mini-orrery の node を使います。逆向きには連動していて、roster の tile を選ぶ、mini-orrery の node を押す、terminal の pane を focus する、のいずれかで filter chip がその agent に切り替わります（pane の場合は、その agent の mail が一覧にあるときだけ）。chip に出ていない agent を選ぶと、その agent の最近の mail を追加で取得します。
右 rail の見出しの右は、普段は `live · 5m` です。ここに `project key not configured` と出ているときは、Mail の DB を読む project key が設定されていません（[設定](configuration.md)）。

mail UI は表示専用です。reply / send 操作はありません。DB は SQLite read-only mode で開きますが、cockpit の他機能には terminal input や spawn などの変更操作があります。

## TELEMETRY

TELEMETRY button は ORRERY Telemetry dashboard を `/network/?embed=1` の iframe として開きます。ORRERY backend が dashboard root、`/api/*`、`/assets/*`、`/portrait` を同一 origin へ proxy します。

以下はすべて、ORRERY に埋め込まれる ORRERY Telemetry dashboard の実画面です。ORRERY native の roster / terminal / mail rail ではありません。`DECK` は agent ごとの状態を card で読み、`NETWORK` は agent 間の広がりを node と link で読みます。

### 最初の状態

![TELEMETRY の DECK に3体の agent が並ぶ初期状態](images/deck_start.png)

見るポイント: `DECK` では上部の `RUNNING` / `AGENTS` と各 card の name、model、task、稼働状態を一度に確認できます。

![TELEMETRY の NETWORK に3体の独立した node が見える初期状態](images/net_start.png)

見るポイント: `NETWORK` の左上に `3 nodes · 0 links` と表示され、まだ link のない3体を個別の node として確認できます。

### agent と通信が増えた状態

![TELEMETRY の DECK に12体の agent と受信した通信が並ぶ](images/deck_growing.png)

見るポイント: agent が増えると card が12体へ広がり、`RX` のある card では相手、task、importance も同じ画面で見分けられます。

![TELEMETRY の NETWORK に12体の node と link が広がる](images/net_growing.png)

見るポイント: `12 nodes · 6 links · 6 spawn / total 12` と node 間の線から、増員と接続の広がりを俯瞰できます。

### 介入待ちの見分け方

![TELEMETRY の DECK。質問待ちは疑問符、承認待ちは赤枠と APPROVAL で示される](images/deck_humanloop.png)

見るポイント: card 右上の `?` は質問への回答待ち、赤い外枠と `APPROVAL` は承認待ちです。通常の稼働 card と見分け、先に人の判断が必要な agent を特定できます。

![TELEMETRY の NETWORK。通信が密な12体の中に介入待ちの疑問符が見える](images/net_humanloop.png)

見るポイント: 通信が密になっても node 付近の `?` から介入待ちを見つけられます。質問待ちと承認待ちの区別は `DECK` の表示で確認します。

embed 側で使える機能:

- NETWORK
- History / Output
- role assign
- SELECT
- EXIT / RESUME
- DIGEST REPLAY

NETWORK の node は agent の選択、edge はその二者間の ORRERY Mail drawer を開きます。gone / retired agent は native roster には出ないため、復活させる場合は TELEMETRY で選択して `RESUME` を実行します。複数 agent の `EXIT` / `RESUME` / `DIGEST REPLAY` も TELEMETRY の `SELECT` から実行できます。

agent panel の `History` タブには、その agent の会話と tool の呼び出し（ファイルの編集 `Edit` の中身を含む。先頭 240 字まで）が時系列で並びます。`Output` タブには、その agent の成果物（作業ログ `LOG_*.md`。最大 25 件）が並び、Obsidian の vault の中のファイルならクリックで Obsidian で開けます。ほかの agent が何を編集したかは、この `History` か、その agent の端末（Split に並べると同時に見られる）で確かめます。

これらは ORRERY native UI の再実装ではなく、ORRERY Telemetry dashboard の機能です。`:8770` が不達の場合は利用できません。

cockpit は iframe の pause / resume を制御し、dashboard からの jump を cockpit の pane focus へ橋渡しします。

### 接続の仕組み

TELEMETRY は、ORRERY Telemetry（repository は orrery-telemetry）の dashboard（既定 `127.0.0.1:8770`）そのものです。cockpit が dashboard を作り直しているわけではありません。

1. header の `TELEMETRY` を押すと、cockpit は `/network/?embed=1` を overlay 内の iframe に読み込む
2. ORRERY backend（`:8791`）が `/network/*` を dashboard の `/` へ、`/api/*`、`/assets/*`、`/portrait` をそのまま dashboard へ中継する。browser から見ると cockpit と同じ origin なので、iframe と cockpit が `postMessage` でやり取りできる
3. `embed=1` で開かれた dashboard は、terminal を自分で開く代わりに cockpit へ処理を渡す

cockpit から dashboard へは、overlay を閉じたときに更新停止（`net-pause`）、開き直したときに再開（`net-resume`）を送ります。Settings の配色も dashboard へ送ります。dashboard から cockpit へは、次の2つを送ります。

| dashboard 側の操作 | cockpit の動作 |
| --- | --- |
| agent panel の `OPEN IN COCKPIT` | TELEMETRY を閉じ、その agent の terminal を開いて focus |
| `+ NEW AGENT` | TELEMETRY を閉じ、cockpit 自身の NEW AGENT 画面を開く |

### TELEMETRY から cockpit で開く

![header の TELEMETRY で DECK を開き、NETWORK で agent を選び、OPEN IN COCKPIT でその端末に戻る](images/cockpit_telemetry.gif)

TELEMETRY の `DECK` で card をクリックすると、その agent の panel が開きます。右上の `OPEN IN COCKPIT` を押すと TELEMETRY が閉じ、cockpit でその agent の terminal が開きます。dashboard を単独で開いたとき（`http://127.0.0.1:8770/`）は同じ button が `OPEN TMUX` になり、dashboard の server が terminal の窓を開きます。

![TELEMETRY の agent panel。右上に EXIT、OPEN IN COCKPIT、Close が並ぶ](images/cockpit_telemetry_open_in_cockpit.png)

単独で開いた dashboard から cockpit へ移る button はありません。cockpit 側で特定の agent を開きたいときは、`cockpit.html?session=<session-name>` の URL を使います（[Jump palette と shortcut](#jump-palette-と-shortcut)）。

## REPLAY

![NETWORK で agent を選んで Replay を押すと、spawn と Mail が時間軸で再生される。速さを上げ、時間軸をクリックして後半に飛ぶ](images/cockpit_replay.gif)

操作: TELEMETRY の `NETWORK` で `SELECT` を押し、node をクリックして 2 体以上を選び、下に出るバーの `Replay` を押します。`PLAY` / `PAUSE` で再生と一時停止、`SPD` の目盛りで速さ（×1〜×10000）、`HOLD` で Mail の吹き出しを出しておく時間、時間軸のクリックで好きな時刻に飛びます。`✕ CLOSE` か `Esc` で終わります。

REPLAY は embedded ORRERY Telemetry dashboard の DIGEST REPLAY です。ORRERY Mail history を持つ複数 agent を選び、mail、spawn、exit / retire、状態遷移を時系列で再生します。

- play / pause / seek
- speed と HOLD
- GROUP-ONLY
- TIME-TRAVEL

ORRERY backend だけで replay を生成する機能ではありません。ORRERY Telemetry と project-scoped mail history が必要です。

## Settings

設定は backend が `~/.orrery/prefs.json` に持ち、ORRERY.app の window と browser tab で共有されます。どこで変えても数秒で他の window に反映されます（prompt の下書きと履歴は window ごと）。

Settings で変更できる値:

- terminal font: 9〜16 px、0.5 px step
- 5-way split 以上の auto-shrink: -1.5 px
- mini-orrery mode
- Telemetry network depth

値は browser の `localStorage` に置き、backend の `~/.orrery/prefs.json` と約 4 秒ごとに同期します。Reset が戻すのは font と auto-shrink だけで、すべての cockpit state を消す操作ではありません。

配色（Dark / Light / System）と Vision profile も Settings にあります（[配色テーマ（light mode）](#配色テーマlight-mode)）。

## 配色テーマ（light mode）

Settings の `Appearance` › `Color theme` で、`Dark`（既定）・`Light`・`System` を選べます。Light は、紙のような暖かい地の色に、濃い文字を載せた配色です。暗い部屋では Dark、明るい部屋や長時間の読み書きでは Light、というように使い分けられます。

![同じ画面の Dark。2 体の端末を並べた Split と、左の roster、右の Mail](images/cockpit_theme_dark.png)

![同じ画面の Light。端末・roster・Mail・header がすべて明るい配色になる](images/cockpit_theme_light.png)

![Settings を開き、Color theme を Light に替え、また Dark に戻す](images/cockpit_theme_switch.gif)

Light にすると、次がまとめて切り替わります。

- cockpit の画面全体（roster・端末の枠・Mail・mini-orrery・Settings など）
- **端末の中の配色**。暗い背景を前提に色を付けてくる CLI の出力（diff の赤と緑の背景など）も、文字が読める濃さに自動で補正します
- 埋め込みの TELEMETRY（cockpit が同じ配色を送る）
- ORRERY.app では、窓の外観と Dock のアイコン

`System` は OS の外観（ライト / ダーク）に合わせ、OS 側が切り替わるとその場で追従します。選んだ配色は Settings と同じく、ORRERY.app と browser の他の窓にも数秒で反映されます。

### Vision profile

Settings の `Vision profile · small text + tracking` では、小さい文字と字間を調整できます。

- `P1 Small text`: 12 px より小さい UI の文字を、最大 +2 px 大きくする
- `P2 Wide tracking`: 字間の上限を 0.08 em にする（コードの部分は除く）

どちらも `A`（変更なし）・`.25`・`.5`・`.75`・`1` の 5 段階で、2 つを同時に使えます。`A · Current (no change)` で元に戻ります。変更は埋め込みの TELEMETRY にも同時に当てるため、ORRERY Telemetry が止まっていると適用できません（`VISION PROFILE REJECTED` と出て元に戻る）。

## Windows（WSL2）での違い

WSL2 で backend を動かし、Windows 側の browser で開くと、cockpit は起動時に backend へ動作環境を問い合わせ（`/telemetry/platform`）、次の点を切り替えます。Mac と同じ操作はそのまま使えます。

| 項目 | Mac | Windows（WSL2） |
| --- | --- | --- |
| Jump palette | `Cmd+K` | `Alt+K`（palette の左上の表示も `Alt+K` になる） |
| attach 済み session の切替 | `Cmd+1`〜`Cmd+9` | `Alt+1`〜`Alt+9` |
| Split へ追加 | `Cmd` / `Ctrl` + click | `Ctrl` + click |
| terminal の末尾へ | `Cmd+↓`、`↓ BOTTOM`、label の再クリック | `↓ BOTTOM`、label の再クリック（`Cmd+↓` に当たるキーはない） |
| terminal を外で開く | `GHOSTTY`（Ghostty の窓） | `WIN TERMINAL`（Windows Terminal `wt.exe` の新しい tab で、同じ tmux session に attach） |
| pane 内の URL をクリック | 既定の browser | Windows の既定 browser（`wslview`、無ければ `explorer.exe`） |
| pane 内のパスをクリック | Finder | エクスプローラー（`explorer.exe`。パスは `wslpath` で Windows 形式に直す） |
| ファイルの貼り付け | Finder でコピーしたファイルのパス | エクスプローラーでコピーしたファイルのパス（`/mnt/c/...` など WSL のパスに直して入れる） |
| 画像の貼り付け | TUI が Mac のクリップボードから読む（`Ctrl+V` を転送） | スクリーンショットなどの画像を PNG で保存し、そのパスを入れる |
| 独立の窓 | ORRERY.app の窓（browser なら popup） | Windows の browser の popup（popup の許可が要る） |

`Cmd` は Windows では Windows キーにあたり OS が使うため、`Ctrl+K` / `Ctrl+1`〜`9` は browser が使うため、WSL では `Alt` にしています。`Alt+K` / `Alt+1`〜`9` は terminal に focus があっても cockpit が受け取り、agent には送りません。

![WSL で開いた Jump palette。左上に Alt+K と表示される](images/cockpit_palette_wsl.png)

![WSL の pane header。右端の button が WIN TERMINAL になる](images/cockpit_pane_header_wsl.png)

`WIN TERMINAL` が押せないときは、button に mouse を乗せると理由が出ます（`wt.exe` が PATH に無い、`WSL_DISTRO_NAME` が無い、など）。Windows Terminal が無い場合は Microsoft Store から入れます。backend が動作環境をまだ返していない間は、誤って貼り付け成功と表示しないよう、ファイル・画像の貼り付けを保留します。

### WSL でのファイル・画像の貼り付け

WSL の backend は、Windows のクリップボードを `powershell.exe`（Windows PowerShell）で読みます。

- エクスプローラーでファイルをコピーし、composer で `Ctrl+V` を押すと、そのファイルのパスが入ります。Windows のパス（`C:\Users\...`）は `wslpath -u` で WSL のパス（`/mnt/c/Users/...`）に直します。日本語のファイル名もそのまま入ります。
- 複数のファイルのうち WSL のパスに直せないもの（`\\server\share` のようなネットワーク上のパスなど）があると、直せたものだけを入れ、残りは画面の右下に名前を出します。
- スクリーンショット（`Win+Shift+S` など）を貼ると、画像を PNG として `/tmp/orrery-clipboard-<uid>/` に保存し、そのパスを入れます。agent はそのパスの画像を読めます。保存先のフォルダと画像は本人だけが読める権限（0700 / 0600）にします。保存先は環境変数 `ORRERY_CLIPBOARD_DIR`（絶対パス）で変えられます。新しいものから50枚を残し、それより古いものは消します。
- 貼り付けのたびに PowerShell を起動するため、パスが入るまで少し待つことがあります。

使えないときは、画面の右下に理由が出ます。

| 表示 | 意味 |
| --- | --- |
| `... cannot reach powershell.exe` | WSL から Windows の program を呼べない（interop が無効、など）。`/telemetry/platform` の `file_paste` が `false` になる |
| `clipboard reader failed (clipboard_no_session)` | backend から起動した PowerShell が、Windows のデスクトップの無い session（session 0）で動いている。ssh など、Windows にログインした画面の外から backend を起動すると起こりうる。Windows Terminal など、ログインした画面の中の WSL で backend を起動し直す |
| `clipboard reader failed (clipboard_unreadable)` | PowerShell がクリップボードを読めなかった（理由は backend の log に出る）、画像を保存できなかった、またはコピーしたファイルのどれも WSL のパスに直せなかった |

## Codex App の扱い

ORRERY は Codex App snapshot を直接読みません。任意の ORRERY Telemetry Codex App Bridge が dashboard `/api/agents` へ統合した row を表示します。

Codex App runtime には tmux pane がないため、cockpit terminal から入力できません。embedded dashboard では ChatGPT app を前面化する `open` capability だけを利用し、EXIT、KILL、wake、terminal attach は行いません。cold wake と delivery は Bridge が管理します。

## 関連文書

- [インストール](install.md)
- [設定](configuration.md)
- [トラブルシューティング](troubleshooting.md)
- [アーキテクチャ概要](ARCHITECTURE_OVERVIEW.md)
- [実装アーキテクチャ](ARCHITECTURE.md)
- [デザイン言語](DESIGN.md)
