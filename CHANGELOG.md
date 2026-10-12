# 変更履歴

## Unreleased

- cockpit に明示的な global 接続を追加。Telemetry の共通認証・Mail・登録 controller を使い、全 HTTP route と WebSocket の最初の frame を認証する。返信の流れ、指示 block の案内、既存 session の稼働観測を表示し、Lock で表示と通信を消去する。既定の旧 mode と切替無効は維持する。
- browser・app・setup は既存の runtime 設定と共有 probe を使い、global では project の作成や Mail DB の直読みを行わない。
