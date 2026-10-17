# TLOU Remastered — Ultrawide Patch

Ultrawide / custom resolution support for *The Last of Us Remastered* (PS4 `01.11`) on [shadPS4](https://github.com/shadps4-emu/shadPS4).

<img width="2560" height="1080" src="https://github.com/user-attachments/assets/50b698af-f1f5-4993-87fc-134f06d02df2" />


The resolution patch is available directly in shadPS4 — **no extra steps needed** to get ultrawide working.

The only thing you need to do manually is **fix cutscenes** — by default they render at 16:9 and will appear stretched. This tool patches the video shader to fix that.

---

## Fixing cutscenes

<img width="2560" height="1080" src="https://github.com/user-attachments/assets/d5fbeb9a-a3f8-4744-8dee-ac885c4f1223" />


### Step 1 — Get the shader file

Download **[cs_0x00000000562c4394_0.spv](https://github.com/SanyaGames227/tlou_r_shadps4_ultrawide/blob/main/cs_0x00000000562c4394_0.spv)** from this repository — this is the clean original shader used as input for the patcher.

### Step 2 — Patch it

Run the patcher, drop the `.spv` into the **Shader** field, set your resolution, click **Create patch**.

### Step 3 — Install

Copy the output file to:
```
<shadPS4 folder>/user/shader/patch/cs_0x00000000562c4394_0.spv
```

⚠️ If shader cache is enabled in shadPS4 — delete the game's shader cache afterwards, otherwise the fix won't take effect.

---

That's it. Launch the game and cutscenes will display correctly.

---

<details>
<summary>The shader from this repo doesn't work or causes issues? Dump it yourself from the game.</summary>

### Step 1 — Enable shader dumping in shadPS4

In shadPS4: **Settings → GPU → Dump Shaders** ✓

### Step 2 — Dump the shader

Launch the game, go to **Options → Credits** and let it play for a few seconds.

### Step 3 — Find the dumped file

```
<shadPS4 folder>/user/shader/dumps/cs_0x00000000562c4394_0.spv
```

Use this file as input in Step 2 above instead.

</details>

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
