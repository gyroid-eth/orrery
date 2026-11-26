# ドキュメント索引

[English](en/README.md) · [README](../README.md)

操作の入口は画面内の **Your first flight → help map → Full tour**。cockpit の `Settings → Getting started` から開けます。ここは install・update・困ったときと、必要に応じて読む詳しい参照の目次です。

日本語の文書が正本です。英語の入口は [README.en.md](../README.en.md) で、下の各ガイドにも対応する英語版があります。

## はじめる

- [Quick start](../README.md#始める) — 本体を入れて初回ガイドへ進む。
- [インストール](install.md) — 1行 install の前提・計画・確認結果を読み、まず cockpit を開く。
- [利用中の agent と導入を進める](install-with-agent.md) — 依頼文、計画、利用者の承認。
- [ChatGPT MCP](chatgpt-mcp.md) — 読み取り専用アダプター。
- [研究セット](research-set.md) — digest-paper と公開 demo vault を本体の後に追加する。

## 目的から選ぶ

- [最初のガイドと Help map を開く](first-flight.md)
- [agent を起動して依頼する](start-an-agent.md)
- [agent の状態を見てまとめて選ぶ](manage-agents.md)
- [Reader で作業と参照ファイルを見る](read-a-file.md)
- [届いた ORRERY Mail を読む](read-mail.md)
- [Mini Graph で agent の詳細と再起動を見る](inspect-mini-graph.md)
- [利用枠の残りとリセット時刻を見る](check-usage.md)
- [Telemetry で状態と履歴を見る](view-telemetry.md)
- [agent の親子関係をたどる](trace-agent-family.md)
- [cockpit の見た目を調整する](adjust-cockpit.md)
- [Cockpit の画面一覧](cockpit-map.md)

## 使い方

- [使い方](usage.md) — 画面の guide/help map を入口に、必要な操作を詳しく調べる。
- [Full tour](FULL_TOUR.md) — 16段の実操作とチェックの条件、ゲーム・保存・別窓の仕様。

## 明示freshの切替候補

- [Telemetryのfresh移行・停止復旧](https://github.com/gyroid-eth/orrery-telemetry/blob/master/docs/fresh-global-update.md) — 限定fixture確認と本番受入を分離。通常設定からの私有起動・停止は確認済み。実OS manager/Finder GUI・実provider/trust/導入・最終CIと本人在席の切替は未受入。復帰・App前面化は今回の対象外。

## install・update

- [Update](install.md#5-更新する) — 既存設定を引き継いで更新する手順。
- [設定](configuration.md) — 接続先、環境変数、保存先とプライバシーの設定を調べる。

## Windows・WSL

- [WSL2](install.md#はじめて入れる人へブラウザで使うmac--windows-wsl2) — 標準の Windows 導入は Ubuntu 内で行い、Windows のブラウザで開く。
- [Windows UI](usage.md#windowswsl2での違い) — shortcut・Windows Terminal・ファイルと画像の扱い。

## 困ったとき

- [トラブルシューティング](troubleshooting.md) — 起動・接続・port・tmux・CDN の問題を切り分ける。

## Telemetry の利用と設定

- [ORRERY Mail の更新と復旧](agentstack-mail-update.md)
- [Gemini を使う](antigravity.md)
- [Codex App とつなぐ](codex-app.md)
- [画面を見て操作する](computer-use.md)
- [Telemetry の設定](telemetry-configuration.md)
- [Telemetry の画面で状態と履歴を調べる](dashboard.md)
- [agent に仕事を分ける](delegation.md)
- [Telemetry 単体で始める](getting-started.md)
- [ORRERY の指示を移行する](instruction-migration.md)
- [Telemetry 単体を導入・更新・削除する](telemetry-install.md)
- [agent を起動・再開する](launchers.md)
- [スマホで見る・指示を送る](mobile.md)
- [DeepSeek・Local LLM を設定する](native-setup.md)
- [Obsidian と一緒に使う](obsidian.md)
- [常駐 agent を用意する](persistent-agents.md)
- [Telemetry のトラブルを調べる](telemetry-troubleshooting.md)
- [native Windows の開発用起動を試す](windows-local.md)
- [WSL の鍵束に API キーを保存する](wsl-keyring.md)
- [ChatGPT から読み取る](chatgpt-mcp.md)

## 設計・開発者向け

- [アーキテクチャ概要](ARCHITECTURE_OVERVIEW.md) — tmux、Codex App、network、履歴と肖像画像の境界。
- [実装アーキテクチャ](ARCHITECTURE.md) — backend の HTTP/WebSocket、tmux 制御、Mail 連携を読む。
- [legacy/fresh tmux対象の保護](runtime-target.md) — 固定接続先、freshの選択I/A・期限・gapと停止。
- [デザイン言語](DESIGN.md) — 視覚・motion・色・typography の実装基準。
- [Roster findability 設計メモ（discussion draft）](DESIGN_roster_findability.md) — 過去の計測と設計案。現行操作の手順書とは区別して読む。
- [開発への入口](../app/README.md) — desktop app の開発用起動と、hotkey の表示・非表示の確認。

`docs/*.md` と `docs/en/*.md` は、同じファイル名で日英の対にします。画像/GIFは各文書に付随する資料です。索引の網羅性と日英の対応は `python3 scripts/check_docs_index.py`（repository の根から）で確認できます。
