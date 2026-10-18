# TLOU Remastered — Ultrawide Patcher

Any resolution and aspect ratio for *The Last of Us Remastered* (PS4 `01.11`) on [shadPS4](https://github.com/shadps4-emu/shadPS4), including correct cutscenes.

<img width="2560" height="1080" src="docs/screenshots/screenshot_1.jpeg" />

## Usage

1. Run the patcher and select your **shadPS4 folder** (the one containing `user`).
2. Choose a resolution.
3. Click **Create patch**.
4. In shadPS4, enable the patch (right-click the game → **Cheats / Patches**).

That's it. The patcher takes care of everything else:

- adds the patch to the current `TheLastOfUsRemastered.xml` from GitHub (`user/patches`);
- patches the cutscene video shader, so cutscenes are no longer stretched;
- keeps your own patches and their on/off state (optional checkbox, shown if you already have the XML);
- turns off other resolution patches and replaces old ones of the same resolution.

Backups are saved to the `ShadPS4/backup` folder next to the patcher.

<img src="docs/screenshots/tlou_r_shadps4_ultrawide.png" />

## Cutscenes

The shader is taken from **your own copy of the game** — this repository does not distribute it. For the patcher to find it:

1. Enable **Shader Cache** or **Dump Shaders** in shadPS4.
2. Start the game, open **Options → Credits** and let it play for a few seconds.
3. Close the game and run the patcher (press **Refresh** if it is already open).

Not needed for 16:9.

<img width="2560" height="1080" src="docs/screenshots/screenshot_2.jpg" />

## Memory mode

- **Extended** (recommended): CPU memory is untouched. After creating the patch, the patcher tells you how much to add to **dmem** in shadPS4 (e.g. `+1500 MB`). The same value is in the patch's Note in the XML.
- **Standard**: GPU memory is taken from CPU memory. Works with stock shadPS4; rare instability possible.

## Requirements

Python 3.8+ and PyQt5 (`pip install PyQt5`).

```
python tlou_r_shadps4_ultrawide.py
```

Tested: 2240×960, 2560×1080, 3440×1440. The interface is available in English, Russian and Ukrainian (detected from the system language).

<details>
<summary>CLI</summary>

```
python tlou_r_shadps4_ultrawide.py --cli 2560 1080 --root <shadPS4 folder> \
    [--xml custom.xml] [--dmem] [--no-keep-custom] [--lang en|ru|uk]
```

- `--xml` — add the patch to your own XML instead of the one from GitHub.
- `--dmem` — Extended memory mode.
- `--no-keep-custom` — don't carry over custom patches from the existing XML.

Exit code `3` means the video shader was not found yet (see *Cutscenes*).

</details>

---

> Not affiliated with Naughty Dog or Sony Interactive Entertainment. For personal/emulation use only.
