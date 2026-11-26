# Save a DeepSeek API key in Ubuntu WSL

> 日本語: [wsl-keyring.md](../wsl-keyring.md)

Create a password-protected keyring inside Ubuntu (WSL2) and save your DeepSeek API key there. Claude Code and Codex are not required. This does not use Windows Credential Manager.

These are first-time storage instructions. If the key is already saved, keep the existing keyring and item and continue to [connection setup](native-setup.md#5-connect-the-configuration-files).

These instructions are based on official documentation and source code. **The complete procedure has not yet been verified on a fresh WSL installation.** Saving the key and testing an ORRERY API connection are separate steps.

| Where you are prompted | What to enter |
| --- | --- |
| A `sudo` password prompt | Your Ubuntu user's password |
| A keyring creation or Unlock dialog | The keyring password you choose; this is separate from the API key |
| `Password:` from `secret-tool store` | Your DeepSeek API key |

The values `service=orrery-dsh-deepseek` and `account=api-key` below identify the stored item. They are not the keyring name or your Ubuntu username. Do not save a Local server's key under this DeepSeek item.

## 1. Open Ubuntu and prepare the applications

On your logged-in Windows desktop, open **Ubuntu** from the Start menu. Do not use an SSH or root shell. Use the same Ubuntu distribution and ordinary user account that will run ORRERY.

You need WSLg, which displays Linux GUI applications under WSL2, and your user's D-Bus. Check in Ubuntu:

```bash
ps -p 1 -o comm=
systemctl --user status dbus.socket --no-pager
```

If PID 1 is not `systemd`, or you cannot connect to the user bus, follow [Microsoft's systemd setup](https://learn.microsoft.com/en-us/windows/wsl/systemd) first. For GUI problems, use the [WSLg setup and troubleshooting guide](https://learn.microsoft.com/en-us/windows/wsl/tutorials/gui-apps). If WSL needs updating or restarting, finish your work before running `wsl --shutdown` yourself: it stops all WSL instances.

If `seahorse` (Passwords and Keys), `gnome-keyring`, or `libsecret-tools` is missing, run the following in Ubuntu yourself:

```bash
sudo apt-get update
apt-get --simulate install --no-install-recommends seahorse gnome-keyring libsecret-tools
```

Review the proposed additions and updates before installing. If the plan proposes unexpected removals or authentication changes such as PAM integration, pause here and resolve the OS prerequisites first. `--no-install-recommends` avoids recommended additions such as the module for unlocking keyrings at login ([APT reference](https://manpages.ubuntu.com/manpages/noble/man8/apt-get.8.html)).

```bash
sudo apt-get install --no-install-recommends seahorse gnome-keyring libsecret-tools
```

## 2. Open Passwords and Keys with the standard Secret Service

Check the existing services as the same ordinary Ubuntu user:

```bash
busctl --user status org.freedesktop.secrets
systemctl --user status gnome-keyring-daemon.service --no-pager
```

If GNOME Keyring is already running as that user, use it. If another application owns the Secret Service, stop this procedure rather than starting a second provider.

On a new setup where Secret Service is not running and the check above finds the packaged gnome-keyring unit, start that unit yourself:

```bash
systemctl --user start gnome-keyring-daemon.service
```

Next, make WSLg's display environment available to your user's services and open the standard GUI:

```bash
dbus-update-activation-environment --systemd DISPLAY WAYLAND_DISPLAY XAUTHORITY
seahorse &
```

The final `&` lets you keep using this terminal while the GUI is open.

If the window or password dialog does not appear, or the service cannot start, do not enter a key. Return to the OS prerequisites in step 1. This procedure does not start an alternative daemon or D-Bus, or edit PAM settings.

## 3. Create a password-protected keyring

In Passwords and Keys, follow these steps. Labels may differ with the application version or language:

1. Press `+` at the top left and choose **Password Keyring**, not a PGP or SSH key.
2. Choose an unused name, such as `ORRERY`, and press `Add`.
3. Choose a **nonempty keyring password** and enter it again to confirm. Do not enter the API key here.
4. Press `Continue`. Do not approve storing the keyring without a password.

Check that the new keyring appears under `Passwords` on the left. If it is locked, right-click it, choose `Unlock`, and enter the **keyring password**. Do not choose `Set as default`. Keep the existing Login/default settings; you will select the storage location explicitly below. See the official [creation](https://help.gnome.org/seahorse/keyring-create.html) and [unlocking](https://help.gnome.org/seahorse/keyring-unlock.html) instructions.

## 4. Identify the keyring path and check for an existing item

In the same Ubuntu terminal, list the actual keyring paths (collection paths). This does not display secret values:

```bash
busctl --user get-property org.freedesktop.secrets /org/freedesktop/secrets \
  org.freedesktop.Secret.Service Collections
```

The number after `ao` is the count, followed by the paths. Copy a displayed path into the next prompt to check its name, repeating for other paths if necessary. Omit the quotation marks. Use the actual path beginning with `/org/freedesktop/secrets/collection/...`; do not infer it from the keyring's name.

```bash
read -r -p 'Keyring object path: ' orrery_keyring_path
busctl --user get-property org.freedesktop.secrets "$orrery_keyring_path" \
  org.freedesktop.Secret.Collection Label
busctl --user get-property org.freedesktop.secrets "$orrery_keyring_path" \
  org.freedesktop.Secret.Collection Locked
```

For a keyring you named `ORRERY`, Label should be `s "ORRERY"`. An unlocked keyring reports `b false` for Locked. Confirm both before continuing. `orrery_keyring_path` holds only this non-secret path. Do not proceed with a different label, an invalid path, or a locked keyring ([collection property reference](https://specifications.freedesktop.org/secret-service/latest/org.freedesktop.Secret.Collection.html)).

Also check whether a matching item is already saved. This returns matching item paths, without reading the key:

```bash
busctl --user call org.freedesktop.secrets /org/freedesktop/secrets \
  org.freedesktop.Secret.Service SearchItems 'a{ss}' 2 \
  service orrery-dsh-deepseek account api-key
```

If there are no matching items, both the unlocked and locked counts are zero (for example, `aoao 0 0` in `busctl`). If an item exists, skip saving or decide yourself how to handle the existing item. Do not overwrite, delete, or save it again to resolve this check.

## 5. Save the API key with hidden input

Use the **same terminal** that holds the confirmed path. Passing only the display name to `--collection` treats it as an alias, so use the actual path identified above:

```bash
test -t 0 && /usr/bin/secret-tool store \
  --collection="$orrery_keyring_path" \
  --label='ORRERY DeepSeek API key' \
  service orrery-dsh-deepseek account api-key
```

At `Password:`, paste your **DeepSeek API key** and press Enter. Neither characters nor `*` should appear. Do not enter your keyring or Ubuntu password. To cancel, use Ctrl+C rather than submitting an empty value. Do not put the key in command arguments, environment variables, a file, or a pipe. See the [hidden-input and collection implementation](https://github.com/GNOME/libsecret/blob/0.21.7/tool/secret-tool.c#L284-L335).

If the command returns without showing `Password:`, do not treat the key as saved; check that you are using an interactive Ubuntu terminal. If a separate GUI Unlock dialog appears, enter the **keyring password** only in that dialog.

Immediately check `echo $?` for `0`, then repeat `SearchItems` from step 4. After a first registration, expect one unlocked and zero locked matches. If there is an error, no match, or multiple matches, stop without displaying the key or repeating the save. You do not need `secret-tool lookup` or `Show password` to reveal its value.

## 6. Return to ORRERY's connection setup

You have checked storage and the item's existence. This does not yet confirm API access or Mail delivery.

The configuration should reference `secret-service` with `service=orrery-dsh-deepseek` and `account=api-key`, rather than contain the key. The save command's `--collection` is not a new manifest field. After a restart, unlock the keyring in the same GUI if necessary. The dashboard must use the same Ubuntu distribution, user, and D-Bus as the storage step.

Continue at [“5. Connect the configuration files” in the setup guide](native-setup.md#5-connect-the-configuration-files).

For background, see GNOME's [standard user service](https://github.com/GNOME/gnome-keyring/blob/main/daemon/gnome-keyring-daemon.service.in), [GUI environment registration](https://dbus.freedesktop.org/doc/dbus-update-activation-environment.1.html), and the [Secret Service search specification](https://specifications.freedesktop.org/secret-service/latest/org.freedesktop.Secret.Service.html).
