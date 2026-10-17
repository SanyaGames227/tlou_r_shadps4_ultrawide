# TLOU Remastered — Ultrawide Patch

Ultrawide / custom resolution support for *The Last of Us Remastered* (PS4 `01.11`) on [shadPS4](https://github.com/shadps4-emu/shadPS4).

<img width="2560" height="1080" src="https://github.com/user-attachments/assets/ec5ce884-c21f-4de7-844b-149825074d96" />


The resolution patch is available directly in shadPS4 — **no extra steps needed** to get ultrawide working.

The only thing you need to do manually is **fix cutscenes** — by default they render at 16:9 and will appear stretched. This tool patches the video shader to fix that.

---

## Fixing cutscenes

<img width="2560" height="1080" src="https://github.com/user-attachments/assets/c5de30b5-95c9-4cc4-b945-d352a2fbdee5" />


### Step 1 — Enable shader dumping in shadPS4

In shadPS4: **Settings → GPU → Dump Shaders** ✓

### Step 2 — Dump the shader

Launch the game, go to **Options → Credits** and let it play for a few seconds. That's enough to dump the shader — you don't need to sit through it.

### Step 3 — Find the dumped file

```
<shadPS4 folder>/user/shader/dumps/cs_0x00000000562c4394_0.spv
```

### Step 4 — Patch it

Run the patcher and drop the `.spv` file into the **Shader** field, set your resolution, click **Create patch**.

### Step 5 — Install

Copy the output file to:
```
<shadPS4 folder>/user/shader/patch/cs_0x00000000562c4394_0.spv
```

⚠️ If shader cache is enabled — delete the game's shader cache afterwards, otherwise the fix won't take effect.

---

That's it. Launch the game and cutscenes will display correctly.

---

## For enthusiasts / custom resolutions

The patcher also generates a full XML patch if you need a resolution not included in shadPS4's built-in patch. It adjusts memory budgets, aspect ratio, HUD, camera, crosshair, fonts, and interaction icons — everything needed for an arbitrary resolution.

**Requirements:** Python 3.8+, PyQt5 (`pip install PyQt5`)

```
python tlou_ultrawide.py
```

The generated `<Metadata>` block goes into `TheLastOfUsRemastered.xml` in your shadPS4 patches folder, before the closing `</Patch>` tag.

Tested: 2240×960, 2560×1080, 3440×1440

<details>
<summary>CLI usage</summary>

```
python tlou_ultrawide.py --cli 2560 1080 \
    [--eboot eboot.bin] \
    [--xml base.xml out.xml] \
    [--spv in.spv out.spv] \
    [--dmem | --extra MB] \
    [--aggressive] \
    [--frac %] \
    [--keep-old] \
    [--lang en|ru|uk]
```

</details>

---

> Not affiliated with Naughty Dog or Sony Interactive Entertainment. For personal/emulation use only.
