# 利用中の agent に ORRERY の導入を手伝ってもらう

[English](en/install-with-agent.md) · [クイックスタート](../README.md#始める)

Claude Code や Codex CLI がすでに使える場合は、その会話で次の依頼文を渡せます。導入先と、agent に作業させたいフォルダを伝えてください。

```text
ORRERY の README に従って、この PC にブラウザー版 cockpit と Telemetry を導入するのを手伝ってください。
まず OS と前提を確認し、変更する場所と導入計画を見せてください。
ファイルや設定を変える前に私の承認を待ち、installer の確認やログインは私に戻してください。
API キー、トークン、鍵束の内容は読まないでください。
最後に doctor と selftest の結果、ブラウザーで開く URL、残っている作業を教えてください。
```

1. agent と一緒に [一行版の計画表示](install.md#1-行で入れる更新する)（`--check`、詳しい設定の preview は `--dry-run`）を読みます。作業フォルダ、使うポート、既存の Mail の扱い、利用者設定の変更対象を確認します。
2. 進めるときは、自分のターミナルで installer の計画に `yes` と入力します。OS の許可、provider のログイン、Codex の hook 審査も自分で行います。API が必要な場合は、鍵を OS の鍵束に保存し、agent に渡すのは設定に必要な参照だけにします。
3. 表示された URL をブラウザーで開き、**Your first flight** を確かめます。[追加機能の入口](install.md#使う機能を追加する)から使う項目だけを準備します。
