# デザイン言語

> English version: [en/DESIGN.md](en/DESIGN.md)

[前: 実装アーキテクチャ](ARCHITECTURE.md) · [README に戻る](../README.md)

この文書は ORRERY cockpit の視覚・motion・情報表現を定義します。実装の構成は[実装アーキテクチャ](ARCHITECTURE.md)、機能操作は[使い方](usage.md)を参照してください。

## Concept: instrument panel × crew

ORRERY は scientist identity を持つ agent crew を操作する、暗い instrument panel です。telemetry の精密さと portrait の人間味を同居させることが identity です。

過剰な cyberpunk neon ではなく、長時間の監視と操作に耐える落ち着いた cockpit を目指します。

## Typography

- display / agent name: `Fraunces`
- telemetry / chrome / terminal: `IBM Plex Mono`

agent name、wordmark、panel heading には editorial serif を使い、数値、path、label、terminal には mono を使います。font CDN が不達の場合は fallback を許容します。

## Color

全体は near-monochrome です。hue は意味を持つため、用途を限定します。

| token | value | 用途 |
| --- | --- | --- |
| `--bg` | `#0b0d11` | near-black slate |
| `--ink` | `#ece5d6` | warm parchment text |
| `--amber` | `#f2b65a` | 注意を促す限定 accent |
| lineage local | `#5fb3a3` | spawn lineage |
| lineage remote | `#b58be0` | spawn lineage |
| lineage delegate | `#83b06a` | spawn lineage |

### Rule

- 色は spawn lineage の識別に予約する
- working / waiting / idle を色だけで区別しない
- state は motion、text、icon を併用する
- contrast を維持し、portrait の色に UI state を依存しない

## State と motion

| state / event | 表現 |
| --- | --- |
| working | portrait ring の回転 |
| approval wait | ring と prompt の blink、`⏎` |
| speaking | typing cursor を伴う speech bubble |
| idle | motion を止める |
| live mail | lineage / mail edge 上の comet |
| page load | crew tile と mail card の staggered rise |
| terminal focus | block cursor と限定的な phosphor glow |

`prefers-reduced-motion` を尊重し、motion を止めても text / icon で状態を理解できる設計を維持してください。

## Chrome と locale

navigation、panel label、control 名は簡潔な英語を使います。

```text
CREW
TERMINAL
AGENT MAIL
TELEMETRY
SETTINGS
```

task、live output、mail、agent が生成した content は原文の locale を保ちます。content を UI 側で機械翻訳しません。

## Layout

基本構成:

- 左: roster と検索
- 中央: terminal、session / pane tab、prompt composer
- 右: ORRERY Mail rail
- header: agents（稼働 / 一覧）、Usage pill、Settings、Planetarium、Telemetry、clock。backend の接続状態は live でないときだけ現れる
- overlay: jump palette、spawn、Planetarium、Settings、Usage dial、TELEMETRY

Usage pill は他の header utility と同じ pill で、provider ごとに縛りになっている window の % だけを持ちます。文字は 11px の tabular で、残量 50% より上は `--ln-local` の emerald、50% 以下は amber、20% 以下は alert の赤の 3 段です。クリックで開く dial は同じ値を同じ 3 色の円弧で見せるもので、数字は lining figures で円の中心に置き、装飾の輪を足しません。

Split は同時に扱う session 数に応じて layout を変えます。5件以上では font auto-shrink を使えますが、情報密度のために可読性を失わないよう9 px未満にはしません。

## Terminal

terminal screen だけに inset shadow、scanline、phosphor glow を使い、画面全体を装飾しません。terminal output の ANSI color は保持し、cockpit の lineage color と競合させないよう chrome から分離します。

Claim / Follow の状態は、表示上の layout state ではなく tmux window size に影響する操作として明示します。

## Portrait

scientist portrait は round medallion で表示し、軽い grayscale / sepia と vignette で palette に馴染ませます。画像がない場合は initials SVG を使います。

通常、高解像度、pixel style の asset source を区別し、実 directory 名 `portraits_64`、`portraits`、`portraits_px` と一致させます。manifest 掲載済み source の作者、license、変換情報は manifest と [CREDITS.md](../CREDITS.md)を正本にします。未掲載の portrait は配布 UI に使いません。ただし `assets/portraits_px/` のドット絵 50枚は、作者 gyroid が ChatGPT（OpenAI の画像生成）で文章の指示だけから生成したものです。写真は入力に使っていません。repository と同じ条件（PolyForm Perimeter License 1.0.1）で配布します。

portrait alias は provider tier や subscription を表しません。agent の能力・価格・契約を portrait 名から推測して表示しないでください。

## Mini-orrery と Planetarium

spawn forest を topology、最近の mail を一時的な edge / comet として表示します。

- node color は lineage
- node motion は state
- node click は agent jump
- mini は常時把握、Planetarium は探索
- Telemetry network mode は active agent から1〜3 hop

多数 node で label が重なる場合は、常時 label を増やすのではなく hover / focus で詳細を開示します。

## Agent Mail

mail card は subject、sender、importance、time を先に示し、本文は detail で開きます。Markdown は安全な限定 subset だけを描画します。

mail は機密情報を含み得るため、screen share 中の accidental exposure を抑える視認性と close 操作を優先します。reply / send がない read-only rail であることを、control affordance でも誤認させないでください。

## Accessibility

- color だけで状態を伝えない
- keyboard で palette、terminal、composer、modal を操作可能にする
- focus ring を消さない
- reduced motion でも state を読める
- 9 px未満の terminal font を許可しない
- overlay は `Esc` で閉じ、focus を元の control に戻す

## 変更時の確認

visual change では次を確認します。

1. lineage color と state 表現が混線していない
2. light / dark portrait の両方で ring と label が読める
3. 1、2〜4、5〜12 session layout で terminal が操作できる
4. ORRERY Telemetry offline、mail empty、portrait missing の縮退が空白にならない
5. keyboard と reduced motion で主要操作を完了できる
6. third-party font / xterm が不達でも理由を診断できる

## 関連文書

- [アーキテクチャ概要](ARCHITECTURE_OVERVIEW.md)
- [実装アーキテクチャ](ARCHITECTURE.md)
- [使い方](usage.md)
