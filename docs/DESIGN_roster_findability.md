# Roster findability 設計メモ

> Status: discussion draft（設計のみ。実装判断は未確定）  
> 対象: `bridge/cockpit.html` の左ペイン roster  
> 調査日: 2026-08-06

## 結論

解くべき問題は、説明行を `live` と `task` のどちらにするかだけではない。**エージェントの「現在何をしているか」を表す正本がなく、表示・検索・spawn/登録が別々の情報を採用していること**が本体である。

短期には、表示用 descriptor と検索対象を同じ関数から作るべきである。中期には、app spawn を含む全経路で `task_summary`、`role`、`parent`、`origin` を持たせ、latest inbox subject や pane title から現在の仕事を推測しなくてよい契約へ移す。`observed_active` は「最近触ったエージェント」を探す補助には効くが、identity の代用にはしない。

## 再測定

### 方法と制約

- 対象 commit: `d452712`
- telemetry snapshot: 2026-08-06 15:33:09 JST（`curl http://127.0.0.1:8791/telemetry/agents`）
- roster と同じ条件、`(running || category === 'agent') && category !== 'warmup'`、で36体を抽出した。
- `GLYPH_STRIP`、`paintTile()` の説明行選択、`rosterNameMatches()` の hay をソースからそのまま Node の集計スクリプトへ写し、同一 snapshot に適用した。
- headless Chrome は起動できず、in-app Browser も localhost のアクセス許可を得られなかった。このため以下はスクリーンショットを数えた値ではなく、**実データに現行の表示・検索関数を適用した source-aligned replay** である。

依頼時の37体とは母集団と時刻が違うため、絶対数は一致しない。むしろ、固定値を転記せず再測定できたことを優先する。

その後、CuriousCopernicus が同じ36体について実 DOM の `.statetext` と実 `rosterNameMatches()` で追試した。`displayIndexParity 3/36`、`collisionExposure 22/36`、`maxGroup 13`、`claude-agent-stack: displayed 7 / hits 1 / overlap 0` がすべて一致した。以下では source-aligned replay をこの実 UI 検証済み baseline として扱う。

### 結果

| 観点 | 今回の値 | 判断 |
| --- | ---: | --- |
| roster 対象 | 36体 | 依頼時37体から変動 |
| `task` が非空 | 36/36 | task がないことより、使われ方と内容品質が問題 |
| 有効な `live` が非空 | 34/36 | 34体では `live` が説明行を占有 |
| 説明行に `task` が出た | 2/36 | `live` が空だった CuriousCopernicus と SnowyDirac のみ |
| role が非空 | 17/36 | 19/36（52.8%）が空 |
| instruction subject が非空 | 33/36 | coverage は高いが、最新mailであって現在の assignment とは限らない |
| 説明行の異なる文字列 | 17種類/36体 | 個別に一意なのは14/36体（38.9%） |
| 重複文字列に属する体数 | 22/36（61.1%） | 最大重複は13体 |
| 表示中の説明行を完全一致検索して自分がヒット | 3/36（8.3%） | 表示と検索の契約が分離している |

重複上位は次の通りだった。

| 説明行 | 表示体数 | 現行検索ヒット | そのうち実際に表示している体 |
| --- | ---: | ---: | ---: |
| `<vault-directory>` | 13 | 1 | 1（WhiteFermi） |
| `claude-agent-stack` | 7 | 1 | **0** |
| `Claude Code` | 2 | 0 | 0 |

`claude-agent-stack` の検索ヒットは ProOpus だった。ProOpus の task にその語があるためで、説明行にその語が見えている7体は一体も検索結果に残らない。単に「表示7、検索1」ではなく、**その1体も利用者が見て検索した集合とは別物**である。上位3重複群22体のうち、表示語から正しい表示体を回収できたのは WhiteFermi 1体だけ（4.5%）だった。

### 依頼の5点に対する確認

1. **`live` による task の隠蔽は再現した。** 今回は34/36体で `live` が優先された。したがって「一度も task が出ない」は常に成り立つ不変条件ではなく、今回は2体で task が出た。ただし根本の優先順位問題はそのままである。上位3文字列だけで22/36体（61.1%）を占めた。
2. **見えている語と検索対象の逆転は再現し、想定より悪かった。** hay は name/model/provider/cmd/role/task であり、`live` を含まない。表示説明行の完全一致検索で自分自身を回収できたのは3/36体だった。
3. **task の内容品質問題も再現した。** 「作業対象・成果物・判断内容を含まず、session の場所または canonical/inbox の受け渡しだけを述べる」を transport-only と判定すると13/36体（36.1%）だった。判定対象は CrispOstwald、WhiteFermi、WildDirac、SnowyDirac、SnugGalileo、SpryVesalius、RedLovelace、SandyPlanck、SleekMendeleev、SmartGauss、PureLovelace、PolarBell、CyanArrhenius。境界例を含む人手分類なので、この13体という値は反論可能であり、判定語彙を固定して継続測定する必要がある。
4. **role 欠損は再現した。** 今回は19/36体（52.8%）が空だった。依頼時の21/37とは個体数が違うが、約半数という傾向は同じである。
5. **非該当が消えることはコードで確認した。** `.agent.filtered-out { display:none }` と `classList.toggle('filtered-out', !visible)` により、0件の query なら36/36体が隠れる。ただし、これは独立した根本原因ではない。filter が非該当を隠すのは通常の挙動であり、問題は (2) の false negative によって対象まで隠すこと、0件の理由と回復手段が弱いことである。全非該当を薄く残すと37体規模ではかえって走査負荷が戻る。

### parent cue の追試

CuriousCopernicus の graph 追試では、cwd 衝突群13体のうち spawn parent を持つのは7体で、その7体中4体は GrandLamarr に集中した。また `parent` は `/telemetry/agents` の各行にはなく、`/telemetry/graph` の spawn edge との join が必要だった。

したがって parent は有益な検索 cue ではあるが、単独の secondary fallback にはならない。

- coverage が13体中7体に留まる。
- 同じ親への sibling spawn を区別しない。
- roster payload だけで描画できず、graph の取得失敗・更新差への縮退設計が要る。

parent は常時表示せず、`parent:` query と hover/detail で使う。secondary は role、origin、識別可能な cwd などとの複合 fallback にする。

## 問題の再定義

左ペインで必要なのは、次の3種類の findability である。

1. **Recognition:** 一覧を眺めて「このエージェントはあの仕事」と区別できる。
2. **Recall:** task、role、親、project など覚えている断片を入力して対象を絞れる。
3. **Recovery by recency:** 名前も仕事も思い出せないとき、直近に活動した個体へ戻れる。

現状は scientist name が stable identity、pane title が primary description、task/role が検索キー、`observed_active` が順位という別々の契約になっている。特に pane title は「端末で今見えている短文」または cwd であり、assignment identity ではない。task は登録時の自由文なので transport-only が混ざる。instruction は最新 inbox subject であり、完了報告や reservation 解放も入るため、現在の仕事の正本にはできない。

したがって、`task || live` と `live || task` の比較だけでは解けない。本当に必要なのは、次の共有契約である。

```text
agent identity
  stable: name
  current work: normalized descriptor + provenance + updated_at
  context: role / parent / origin / cwd
  recency: observed_active
  search: rendered fieldsと同じ語彙 + 明示的なstructured token
```

## 設計案

### 案A: 優先順位と search hay だけ直す

説明行を `task || live || last_active_rel` にし、search hay に `live` と `instruction.subject` を追加する。0件表示と clear action も付ける。

利点:

- 既存 payload だけで成立し、変更範囲が小さい。
- 表示している task は検索可能になる。
- cwd だけが13体並ぶ状態は大きく減る。

欠点:

- transport-only task 13体が前面に出る。
- `instruction.subject` は現在の assignment とは限らず、完了報告や古い依頼まで hit する。
- `live` を hay に足すだけでは `<vault-directory>` で13体が残り、検索可能性は上がっても識別力は上がらない。
- 表示と検索を別々に編集する構造が残り、再び drift する。

この案は hotfix としては妥当だが、完了形にはしない。

また、案Aを単独で先行リリースしない。後述の quality 表示と同じ release boundary に置かないと、transport-only task を「有益な説明がある」ように見せるためである。

### 案B: 共通の roster descriptor を作る

表示と検索の両方が使う view model を一つ作る。

```text
descriptor.primary    現在の具体的な作業（1行）
descriptor.secondary  role · parent または識別可能な cwd
descriptor.recency    observed_active の相対時刻
descriptor.tokens     primary/secondary に実際に描画した語 + stable name
descriptor.provenance explicit-assignment | task | instruction | live | fallback
descriptor.quality    specific | generic | missing
```

候補の選び方は「field の固定順位」ではなく、provenance と quality で決める。

1. 明示的な current assignment が specific なら primary にする。
2. 既存 task が specific なら使う。
3. instruction は task-like な subject かつ current assignment と確認できる場合だけ使う。単なる最新 inbox は使わない。
4. live は cwd basename、agent name、`Claude Code` のような generic 値を除き、作業内容らしい場合だけ使う。
5. specific な primary がなければ `Needs description` を明示し、generic task を有益に見せかけない。

secondary は role を優先し、なければ parent/origin、最後に cwd を使う。cwd は basename だけでなく、共通 prefix を除いた最短差分を計算し、差がなければ表示しない。`observed_active` は primary の材料ではなく、`active 3m ago` のような tertiary 情報と並び順に使う。

parent は graph join が成功し、値がある場合だけ候補にする。欠損時に `—`、root、現在時刻などを推測で埋めない。

filter は原則 `display:none` のままでよい。ただし、表示した primary/secondary は必ず tokens に入り、0件時には `0/36 · Clear · searched: task, role, parent, cwd` を示す。必要なら `parent:Name`、`role:critic`、`cwd:orrery`、`active:<10m` の structured query を追加する。

利点:

- 「見える語は検索できる」を構造で保証できる。
- task と live の二択ではなく、情報品質に応じて縮退できる。
- descriptor の provenance/quality を telemetry で数えられる。
- 将来、palette や split cell に同じ契約を再利用できる。

欠点:

- quality 判定を heuristic だけで始めると、言語・固有名詞・短いが有益な task で誤判定する。
- primary の自動切替が多いと、一覧上の位置とラベルが落ち着かない。
- current assignment が payload にない限り、推測の上限は残る。

### 案C: app spawn / 登録時に識別情報を作る

spawn 経路に current assignment の contract を導入する。

必須または自動検証する項目:

| field | 意味 |
| --- | --- |
| `task_summary` | 対象または成果物を含む短い現在作業。`Read inbox` のような transport-only を warning にする |
| `role` | 同じ task 内での役割。空を許す場合も missing を可視化する |
| `parent` | spawn 親。既存 graph の lineage と結ぶ |
| `origin` | delegate / app / CLI / warm-pool claim など |
| `assignment_id`, `updated_at` | latest mail と現在 assignment を分離する |

app 側でユーザーが長文を入力する必要はない。spawn prompt、親の依頼 subject、選択中 project から summary の種を作る。`task_summary` の正本所有者は agent 自身とし、inbox を読んだ直後に一度更新する。古い summary を新鮮に見せないため `updated_at` は必須とし、未設定を現在時刻や `0` で埋めない。assignment の更新より古い descriptor は薄字と `updated 3h ago` のような表示で stale を明示する。

利点:

- 表示側の推測では直せない transport-only 層を発生源で減らせる。
- parent/origin により、名前を覚えていなくても spawn context から探せる。
- assignment の履歴と現在値を区別できる。

欠点:

- app、delegate、CLI、Agent Mail 登録など複数経路の変更が必要。
- 必須入力を強くすると spawn の速度を落とし、形式だけ埋めた低品質文字列を増やす。
- 既存 agent の backfill が必要で、段階移行中は混在する。

## `descriptor.quality` heuristic の測定

案Bの費用対効果を見るため、上記と同じ36体 snapshot の `task` に測定用の判定器を適用した。判定器の正本は [`tools/descriptor_quality_probe.py`](../tools/descriptor_quality_probe.py) に置いた。標準ライブラリのみの read-only probe であり、本体実装ではない。

```bash
# 現在の :8791 を cockpit roster と同じ条件で測る
python3 tools/descriptor_quality_probe.py --list generic

# 固定 snapshot と非稼働 holdout を測る
python3 tools/descriptor_quality_probe.py --json agents.json --population roster
python3 tools/descriptor_quality_probe.py --json agents.json --population non-running --list specific
```

### 判定規則

1. NFKC normalize と trim 後に空なら `missing`。
2. absolute path、4文字以上の既知 agent name、`PR-B0` のような coordination ticket ID を除く。短い agent name が `execute` や `inbox` の一部を壊さないよう、4文字未満の name は除去しない。
3. 英語と日本語の relay 語彙を除く。例: `canonical`、`inbox`、`awaiting`、`read`、`execute`、`task`、`parent`、`正本`、`タスク`、`届く`、`経由`、`委任`、`実行`。
4. punctuation と whitespace を除いた残余が4文字以上なら `specific`、未満なら `generic`。

意図は既知の文章パターン13個を列挙することではなく、**場所・agent名・受け渡し機構を消した後に、作業対象または成果物が残るか**を測ることである。

### 結果

| quality | heuristic | 人手分類 | 差 |
| --- | ---: | ---: | ---: |
| `specific` | 23/36（63.9%） | 23/36 | 0 |
| `generic` | 13/36（36.1%） | 13/36 | 0 |
| `missing` | 0/36 | 0/36 | 0 |

confusion matrix は generic true positive 13、false positive 0、false negative 0、specific true negative 23 だった。generic 13体の残余は全て0文字、specific の最小残余は PlumFeynman の `origamidesign` 13文字だった。この snapshot では threshold を1〜13文字の範囲で動かしても分布は変わらない。

### 非稼働 holdout

語彙と閾値を上記コードへ固定した後、同じ telemetry payload のうち `running === false` の298体を holdout として一度だけ測った。

| quality | roster 36体 | non-running 298体 |
| --- | ---: | ---: |
| `specific` | 23（63.9%） | 220（73.8%） |
| `generic` | 13（36.1%） | 73（24.5%） |
| `missing` | 0 | 5（1.7%） |

holdout の正解ラベルはないため、73.8%を精度とは解釈できない。出力を監査すると、少なくとも次の明白な false `specific` が残った。

| agent | task | 残余 |
| --- | --- | --- |
| NimbleLovelace | `Reading assigned inbox task` | `reading` |
| AshLavoisier | `CuriousCopernicus からの正本タスクを inbox で確認して遂行` | `確認して遂行` |
| BalmyTuring | `Codex session in .` | `codexsession` |
| SnowyBoltzmann | `Processing canonical task received via agent-mail inbox` | `processing` |

失敗原因は、英語の活用形 `reading` / `processing`、日本語の言い換え `確認して遂行`、相対 path `.`、space を含む path、`scoped work` のような具体的に見える placeholder である。一方、CuriousCopernicus が例示した CreamLangmuir の `ProOpus からの inbox 正本タスクを実行` は、この正本 probe では `generic`、残余0文字になった。

したがって、この heuristic は**学習元36体には一致するが、holdout で壊れる**。relay 語彙をこの snapshot を見て選んだ時点で汎化性能ではなく、語彙追加の追いかけだけでは未知 boilerplate を塞げない。production の quality は hard gate にせず warning とし、変更ごとに固定 holdout と明白な transport-only fixture の両方で precision/recall を測る。

`Needs description` に落ちるのは13/36体で、そのうち role があるのは6体だけだった。案Bだけを出すと欠損を正直に可視化はできるが、残り7体の識別情報は増えない。このため最初の deployable slice は、quality 表示だけでなく agent が `task_summary` を更新できる案Cの最小経路と同じ release boundary に置く。

## 推奨案

**案Bを表示・検索の正本にし、案Cのうち agent-owned `task_summary` 更新経路を最初から組み合わせ、`parent` と `origin` を段階的に供給する**構成を推奨する。案Aは案Bの内部互換 layer としてのみ採用し、単独では出さない。

理由は次の通り。

1. 現 snapshot では task coverage は100%なのに、表示説明行の self-retrieval は8.3%しかない。まずデータ量ではなく、同じ descriptor を表示と検索で共有する必要がある。
2. 同時に36.1%の task が transport-only なので、`task || live` だけでは quality 問題を前面化する。quality/provenance を契約に含める必要がある。
3. instruction coverage は91.7%あるが、内容は assignment、完了、解除などが混在する。latest inbox を検索へ全部足す案は recall と引き換えに precision を落とす。
4. role は約半数欠けるため、role 単独を primary identity にできない。parent/origin を含む複数の独立 cue が要る。
5. `observed_active` は recovery by recency に有効だが、同じ cwd の13体を意味的に区別しない。identity ではなく並び順・補助表示に限定した方が役割が明確である。

反論可能な点は、案Bの quality 判定コストである。もし transport-only task が実利用上十分で、利用者が agent name を既に覚えているなら案Aの費用対効果が勝つ。その判断は、次節の task lookup success と time-to-find を測って決める。

最小の deployable scope は次の4点を不可分とする。

1. `deriveRosterDescriptor()` 相当の共通 view model と `specific / generic / missing / stale`。
2. agent が inbox 読了後に `task_summary` と `updated_at` を更新する経路。
3. primary/secondary と同じ tokens を使う検索。latest inbox subject は既定 hay に入れず、必要なら `mail:` token に隔離する。
4. 非該当は隠したまま、`0/N`、検索対象、Clear を常に示す。

parent graph join、常時 lineage 表示、高度な structured query はこの最小範囲から外せる。

## 効果測定

同じ固定 snapshot を現行 UI と候補 UI に与え、母集団変動を除いて比較する。最低30体、app spawn と delegate spawn の両方を含む fixture を使う。

### 主要指標

| 指標 | 今回 baseline | 推奨する合格線 |
| --- | ---: | ---: |
| collision exposure: 重複 primary に属する agent | 22/36（61.1%） | 25%以下 |
| maximum collision group | 13体 | 3体以下 |
| display-index parity: primary 全文を検索して本人が残る | 3/36（8.3%） | 100% |
| specific current-work coverage | 23/36（63.9%、上記の人手分類） | 95%以上 |
| role coverage | 17/36（47.2%） | 新規 app spawn で95%以上、全体80%以上 |
| rendered-term retrieval failure | 上位22体中21体を正しく回収できず | 0% |

`display-index parity` は「検索ヒット数」だけより厳しい。検索結果が1件でも、それが表示語を持つ本人でなければ成功と数えない。

### タスクベース指標

fixture の各 agent に ground-truth の「対象」「成果物」「role」「parent」を付け、利用者に10件を探してもらう。

- median time-to-find: 5秒以下
- P90 time-to-find: 12秒以下
- wrong jump rate: 5%以下
- task/role/parent のいずれか一つの cue から正しい agent が top 3 に入る率: 90%以上
- `Needs description` のまま新規 app spawn される率: 5%以下

### 安定性の guardrail

- assignment が変わらない限り、primary descriptor は polling や spinner/pane title の変化で変わらない。
- primary が変わった場合は provenance と `updated_at` を記録し、1 assignment あたりの不要な label churn を0回にする。
- filter 0件時に総数、query、clear action が必ず見え、存在を消した理由が説明できる。
- 実際の tile 幅で truncation 後も識別 token が残る率を95%以上にする。長文全文ではなく、先頭に対象または成果物を置く。

## フォローアップで決定した論点

実装前の論点として次の5点を提示した。

1. `task_summary` の正本所有者は spawn 元、親、agent 自身のどれか。agent が更新するなら、assignment 完了時の stale 値をどう閉じるか。
2. quality 判定は warning のみにするか、app spawn を止めるか。私は warning と `Needs description` 可視化から始めるのが安全だと考える。
3. latest inbox subject は検索対象に含めるか。私は current assignment と結び付いた subject のみを既定対象にし、mail 全文探索は別 UI に分ける方がよいと考える。
4. filter 非該当を薄く残すか。私は既定では隠し、結果数・clear・false-empty 排除で回復可能にする方を推す。
5. parent/lineage を常時文字で出すか。情報密度を守るため secondary の fallback または hover/detail とし、`parent:` query では常に使える形を推す。

CuriousCopernicus とのフォローアップで、次のように合意した。

- summary の正本所有者は agent。spawn 文言は種に留め、inbox 読了後に本人が更新する。
- quality は warning のみで spawn を止めない。
- latest inbox subject は既定検索に入れず、`mail:` に隔離する。
- filter 非該当は隠し、false negative と0件時の説明を直す。
- parent/lineage は常時表示しない。
