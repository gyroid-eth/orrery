Community-maintained / experimental. Verified environment: Windows 11 build 26200, CPython 3.12.10, Windows PowerShell 5.1.26100.9168.

# native Windows での実験的なDashboard起動

この開発用helperはcheckoutからMailとDashboardを起動し、応答を確認してブラウザを開きます。
標準installerではありません。
オーナーがWindowsの主経路としているのはWSL2で、native Windowsは引き続き未対応です。
方針は[Issue #3](https://github.com/gyroid-eth/orrery-telemetry/issues/3)を参照してください。

初回にPython 3.11以上、Gitとrepositoryの`.venv`を準備します。
[CONTRIBUTING.md](https://github.com/gyroid-eth/orrery-telemetry/blob/master/CONTRIBUTING.md)の依存関係を導入し、Windowsでは`.venv\Scripts\python.exe`を使ってください。
個人のCLI設定、managed instructions、Windows serviceは導入しません。
runtime sessionの検出にはnative tmuxが必要です。
tmuxがなければ警告を表示し、Mailを参照する表示だけを利用できます。

準備後は任意の作業ディレクトリのPowerShellから次の1コマンドで起動します。

```powershell
& 'C:\path\to\orrery-telemetry\scripts\windows\start-windows.ps1' -Project 'C:\path\to\your-project'
```

初回は`-DryRun`を付け、DB、project、起動または再利用するprocessを確認してください。
既定のstate directoryは`%LOCALAPPDATA%\orrery-telemetry\local`、Mail portは18765、Dashboard portは8770です。
stateは再起動後も残ります。
既存環境では、その`storage.sqlite3`を含む実際の`-StateDirectory`と、`-MailPort`、`-DashboardPort`を指定します。
`-PythonCommand`で開発用interpreterを選択でき、`-NoBrowser`でブラウザの自動起動を抑止できます。

helperはMailのhealth応答からDBを照合し、既存Dashboardのprocess環境から同じDB、project、Mail URLを使っていることを確認します。
version、agents、graph APIにもアクセスします。
異なるlistenerがあれば起動を止めます。
再利用したprocessは終了しません。
環境変数はchild processだけに適用し、作業場所をcheckoutに固定するため、PowerShellを別の場所で開いてもmodule importが失敗しません。

processを起動した場合はPowerShellを開いたままにします。
EnterまたはCtrl+Cで、その実行が起動したprocessだけを終了します。
ウィンドウを強制的に閉じる操作は管理された終了ではありません。
logはstate directoryに保存します。
正常終了を送れない場合はchildを強制終了した旨を表示し、未commitのarchive fileはMailの既存の起動時回復に委ねます。
childが途中で終了した場合も、同じ実行が起動した残りのchildを終了します。
自動再起動やWindowsログイン時の常駐化は行いません。

確認対象はブラウザでのDashboard閲覧です。
NEW AGENT、terminal jump、child委任、resume、mail watcher、hook、Codex Desktop Bridgeのnative動作確認は含みません。
Codex agentの起動は別launcherの担当です。
長いWindows Mail archive pathには、マージ済みの[PR #7](https://github.com/gyroid-eth/orrery-telemetry/pull/7)のstorage修正を利用します。

回帰テストは、MailとDashboardの新規起動、PIDを増やさない再利用、DBとprojectの不一致、portの競合、起動したprocessだけの終了、DBの保持を確認します。
native Windows全対応を示す結果ではありません。
