# ドキュメント索引

[English](en/README.md) · [README](../README.md)

操作の入口は画面内の **Your first flight → help map → Full tour**。cockpit の `Settings → Getting started` から開けます。ここは install・update・困ったときと、必要に応じて読む詳しい参照の目次です。

## はじめる

- [Quick start](../README.md#クイックスタート) — 本体を入れて初回ガイドへ進む。
- [インストール](install.md) — 1行 install の前提・計画・確認結果を読み、まず cockpit を開く。
- [研究セット](research-set.md) — digest-paper と公開 demo vault を本体の後に追加する。

## 使い方

- [使い方](usage.md) — 画面の guide/help map を入口に、必要な操作を詳しく調べる。
- [Full tour](FULL_TOUR.md) — 16段の実操作とチェックの条件、ゲーム・保存・別窓の仕様。

## install・update

- [Update](install.md#5-更新する) — 既存設定を引き継いで更新する手順。
- [設定](configuration.md) — 接続先、環境変数、保存先とプライバシーの設定を調べる。

## Windows・WSL

- [WSL2](install.md#はじめて入れる人へブラウザで使うmac--windows-wsl2) — 標準の Windows 導入は Ubuntu 内で行い、Windows のブラウザで開く。
- [Windows UI](usage.md#windowswsl2での違い) — shortcut・Windows Terminal・ファイルと画像の扱い。

## 困ったとき

- [トラブルシューティング](troubleshooting.md) — 起動・接続・port・tmux・CDN の問題を切り分ける。

## 設計・開発者向け

- [アーキテクチャ概要](ARCHITECTURE_OVERVIEW.md) — tmux、Codex App、network、履歴と肖像画像の境界。
- [実装アーキテクチャ](ARCHITECTURE.md) — backend の HTTP/WebSocket、tmux 制御、Mail 連携を読む。
- [デザイン言語](DESIGN.md) — 視覚・motion・色・typography の実装基準。
- [Roster findability 設計メモ（discussion draft）](DESIGN_roster_findability.md) — 過去の計測と設計案。現行操作の手順書とは区別して読む。
- [開発への入口](../app/README.md) — desktop app の開発用起動と、hotkey の表示・非表示の確認。

`docs/*.md` と `docs/en/*.md` は、同じファイル名で日英の対にします。画像/GIFは各文書に付随する資料です。索引の網羅性と日英の対応は `python3 scripts/check_docs_index.py`（repository の根から）で確認できます。
