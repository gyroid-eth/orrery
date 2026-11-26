# Ubuntu WSLにDeepSeekのAPIキーを保存する

> English: [wsl-keyring.en.md](en/wsl-keyring.md)

Ubuntu（WSL2）側にパスワード付きの鍵束を作り、DeepSeek APIキーを保存します。Claude CodeやCodexは不要です。Windowsの資格情報マネージャーは使いません。

初めて保存する人向けの手順です。すでに保存済みなら、新しい鍵束や項目を作らず、既存の保存先を使って[接続設定](native-setup.md#5-設定例をコピーして接続先をつなぐ)へ進んでください。

この手順は公式資料とソースに基づく案内で、**新規WSLでの通し確認は未完了**です。キーの保存と、ORRERYからの実接続の確認は別の工程です。

| 入力を求められる場所 | 入れるもの |
| --- | --- |
| `sudo`のパスワード | Ubuntuのユーザーパスワード |
| 鍵束の作成・Unlock画面 | 本人が決める鍵束のパスワード。APIキーとは別 |
| `secret-tool store`の`Password:` | DeepSeek APIキー |

以下の`service=orrery-dsh-deepseek`と`account=api-key`は、保存項目を探すための名前です。鍵束名やUbuntuのユーザー名ではありません。Localの専用キーを、このDeepSeek用項目へ保存しないでください。

## 1. Ubuntuの画面と必要なアプリを用意する

Windowsにログインした画面で、スタートメニューから**Ubuntu**を開きます。SSHやrootのシェルでは行いません。ORRERYを使うのと同じUbuntu・同じ通常ユーザーで進めます。

WSL2でLinuxのGUIを開くWSLgと、同じユーザーのD-Busが必要です。Ubuntuで次を確認します。

```bash
ps -p 1 -o comm=
systemctl --user status dbus.socket --no-pager
```

PID1が`systemd`でない、またはuser busへ接続できない場合は、先に[Microsoftのsystemd準備手順](https://learn.microsoft.com/en-us/windows/wsl/systemd)へ進みます。GUIが開けない場合は[WSLgの準備・対処手順](https://learn.microsoft.com/en-us/windows/wsl/tutorials/gui-apps)を確認します。WSLの更新・再起動が必要な場合、`wsl --shutdown`は全WSLを止めるため、作業を終えて本人が実行してください。

`seahorse`（Passwords and Keys）、`gnome-keyring`、`libsecret-tools`が未導入なら、本人がUbuntuで次を実行します。

```bash
sudo apt-get update
apt-get --simulate install --no-install-recommends seahorse gnome-keyring libsecret-tools
```

追加・更新されるパッケージを確認してから、実際に導入します。意図しない削除やPAMなどの認証連携の変更が提案された場合は、ここでは進めずOSの準備を確認してください。`--no-install-recommends`は、鍵束のログイン自動解除用モジュールなどの推奨追加を避ける指定です（[APTの説明](https://manpages.ubuntu.com/manpages/noble/man8/apt-get.8.html)）。

```bash
sudo apt-get install --no-install-recommends seahorse gnome-keyring libsecret-tools
```

## 2. 標準のSecret ServiceでPasswords and Keysを開く

同じUbuntuの通常ユーザーで、既存サービスを確認します。

```bash
busctl --user status org.freedesktop.secrets
systemctl --user status gnome-keyring-daemon.service --no-pager
```

同じユーザーのGNOME Keyringが既に動いていれば、そのまま使います。別製品がSecret Serviceを所有している場合は、GNOME Keyringを重ねて起動せず、この手順を止めます。

Secret Serviceがまだ動いておらず、上の確認で配布済みのgnome-keyringのunitが見つかる新規環境では、本人がそのunitを起動します。

```bash
systemctl --user start gnome-keyring-daemon.service
```

次に、WSLgの表示環境を同ユーザーのサービスへ渡し、標準GUIを開きます。

```bash
dbus-update-activation-environment --systemd DISPLAY WAYLAND_DISPLAY XAUTHORITY
seahorse &
```

末尾の`&`で、GUIを開いたままこのターミナルを使えます。

画面やパスワードダイアログが出ない、サービスが起動できない場合は、キーを入力せず手順1のOS準備へ戻ります。別のdaemonやD-Busを起動したり、PAM設定を書き換えたりする手順ではありません。

## 3. パスワード付きの鍵束を作る

Passwords and Keysの画面で操作します。以下は英語の画面名を併記しています。版や翻訳で表示が異なる場合があります。

1. 左上の`+`を押し、**Password Keyring**を選びます。PGPやSSHの鍵ではありません。
2. 未使用の名前（例：`ORRERY`）を付け、`Add`を押します。
3. **空でない鍵束パスワード**を本人が決め、確認欄にも入れます。ここにはAPIキーを入れません。
4. `Continue`で作成します。パスワードを空にする確認は承認しません。

左側の`Passwords`に作った鍵束が現れたことを確認します。鍵が閉じていれば、右クリックして`Unlock`を選び、**鍵束パスワード**で開きます。`Set as default`は押しません。既存のLoginやdefaultの設定は変えず、次の工程で保存先を指定します。[公式の作成手順](https://help.gnome.org/seahorse/keyring-create.html)・[Unlock手順](https://help.gnome.org/seahorse/keyring-unlock.html)。

## 4. 作った鍵束のパスと既存項目を確認する

同じUbuntuのターミナルで、鍵束の実際のパス（collection path）を表示します。キーの値は表示されません。

```bash
busctl --user get-property org.freedesktop.secrets /org/freedesktop/secrets \
  org.freedesktop.Secret.Service Collections
```

`ao`の後の数字が件数、その後がパスです。表示されたパスを1つずつ、次の入力へコピーして名前を確かめます。引用符は含めず、`/org/freedesktop/secrets/collection/...`から始まる実際のパスを使います。鍵束名から推測しないでください。

```bash
read -r -p 'Keyring object path: ' orrery_keyring_path
busctl --user get-property org.freedesktop.secrets "$orrery_keyring_path" \
  org.freedesktop.Secret.Collection Label
busctl --user get-property org.freedesktop.secrets "$orrery_keyring_path" \
  org.freedesktop.Secret.Collection Locked
```

`ORRERY`を作った場合、Labelが`s "ORRERY"`、Unlock済みならLockedが`b false`です。両方を確認してから進みます。`orrery_keyring_path`には、この秘密でないパスだけを入れます。別の鍵束名、無効なパス、Lockedのままなら先へ進みません（[鍵束プロパティの仕様](https://specifications.freedesktop.org/secret-service/latest/org.freedesktop.Secret.Collection.html)）。

保存済みの同じ項目がないかも確認します。これは一致する項目のパスを返すだけで、キーは読み出しません。

```bash
busctl --user call org.freedesktop.secrets /org/freedesktop/secrets \
  org.freedesktop.Secret.Service SearchItems 'a{ss}' 2 \
  service orrery-dsh-deepseek account api-key
```

初回で一致する項目がなければ、Unlock済み・Lockedの件数はどちらも0です（`busctl`の表示例：`aoao 0 0`）。項目があれば、上書きせず登録工程を飛ばすか、本人が既存項目の扱いを決めます。削除や再保存で対処しないでください。

## 5. APIキーを非表示入力で保存する

確認したパスを持つ**同じターミナル**で実行します。鍵束の表示名だけを`--collection`に渡すと別のaliasとして扱われるため、上で確認した実パスを使います。

```bash
test -t 0 && /usr/bin/secret-tool store \
  --collection="$orrery_keyring_path" \
  --label='ORRERY DeepSeek API key' \
  service orrery-dsh-deepseek account api-key
```

`Password:`へ**DeepSeek APIキー**を貼り、Enterを押します。文字も`*`も出ないのが正常です。鍵束やUbuntuのパスワードを入れません。やめるときは空入力ではなくCtrl+Cです。キーをコマンドの引数・環境変数・ファイルへ書かず、pipeでも渡しません。[非表示入力とcollection指定の実装](https://github.com/GNOME/libsecret/blob/0.21.7/tool/secret-tool.c#L284-L335)。

`Password:`が出ずに戻った場合は、保存済みと扱わず、対話入力できるUbuntuのターミナルか確認します。GUIのUnlock画面が別に出た場合は、そちらにだけ**鍵束パスワード**を入れます。

実行直後に`echo $?`で`0`を確認し、手順4の`SearchItems`をもう一度実行します。初回登録の直後は、Unlock済み1件・Locked0件が期待値です。エラー、0件、複数件なら、キーを表示したり保存を繰り返したりせず止めます。`secret-tool lookup`や`Show password`で値を見せる必要はありません。

## 6. ORRERYの接続設定へ戻る

ここで確認できたのは保存と項目の存在です。APIへ接続できることやMailの成功は、まだ確認していません。

設定にはキーを書かず、`secret-service`の`service=orrery-dsh-deepseek`・`account=api-key`を参照します。保存時の`--collection`をmanifestの新しい項目として足す必要はありません。再起動後は必要に応じて同じGUIで鍵束をUnlockし、dashboardも保存時と同じUbuntu・ユーザーのD-Busを使います。

続いて[初期設定ガイドの「5. 設定例をコピーして、接続先をつなぐ」](native-setup.md#5-設定例をコピーして接続先をつなぐ)へ戻ります。

OSやD-Busの仕組みを確認する場合は、[GNOMEの標準user service](https://github.com/GNOME/gnome-keyring/blob/main/daemon/gnome-keyring-daemon.service.in)、[GUI環境の登録](https://dbus.freedesktop.org/doc/dbus-update-activation-environment.1.html)、[Secret Serviceの検索仕様](https://specifications.freedesktop.org/secret-service/latest/org.freedesktop.Secret.Service.html)を参照してください。
