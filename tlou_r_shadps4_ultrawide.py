#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TLOU Remastered (PS4, AppVer 01.11) - генератор патча любого разрешения / соотношения сторон
для shadPS4: XML-патч (eboot.bin) + замена SPIR-V шейдера видеороликов.

GUI (PyQt5):   python3 tlou_ultrawide.py
CLI:           python3 tlou_ultrawide.py --cli 2560 1080 [--eboot eboot.bin] [--xml base.xml|github out.xml]
                                         [--spv in.spv out.spv] [--aggressive]
                                         [--cache ПАПКА|ZIP] [--dmem | --extra МБ] [--frac %] [--keep-old] [--lang en|ru|uk]
  --xml github OUT   взять актуальный TheLastOfUsRemastered.xml с GitHub (shadps4-emu/ps4_cheats) и дополнить его
  --cache     кэш шейдеров shadPS4 (папка или .zip): найти в нём шейдер видео (по размеру + SHA-256) и пропатчить на месте
  --dmem      режим «с расширением dmem»: CPU не урезается, константа direct-памяти растёт на D
  --extra МБ  частичное расширение (остальное забирается у CPU)
  --keep-old  не отключать прежние разрешающие секции в базовом XML
"""
import sys, os, re, struct, math, argparse, hashlib, shutil, zipfile, copy, time

MB = 1 << 20
AUTHOR = "sanyagames227"
TITLE_IDS = ["CUSA00552", "CUSA00556", "CUSA00557", "CUSA00559"]
BASE_W, BASE_H = 1920, 1080

# ----------------------------------------------------------------------------------------
# Оригинальные значения eboot.bin 01.11 (адрес в XML = vaddr + 0x400000)
# ----------------------------------------------------------------------------------------
ORIG_BYTES = {  # адрес: оригинальные байты (для проверки eboot)
    0xeb0673: "90" * 13, 0xeb05f1: "90" * 13, 0x69234c: "c5fa5985e0fdffff",
    0xeb0663: "90" * 10, 0x69374b: "c5fa5945f0", 0xeb0691: "90" * 13,
    0x6965a4: "c5fa5985a0feffff", 0xe223c7: "90909090", 0xe252ac: "b48c7300",
    0x1572444: "cdcccc3a610b363b", 0x1586f80: "0000803f", 0x1586bb8: "0000a044",
    0x1586bc4: "0000a044", 0xa250dc: "5881ad00", 0xead8c1: "c5d258eec5d2592d6fe36b00", 0x109fc61: "90" * 29, 0xeb091b: "398ee33f", 0xeb0594: "398ee33f",
    0x14c9890: "2307863f", 0x14c9928: "2307863f",
}
ORIG_BUDGET = {  # адрес записи: (имя, размер в байтах)
    0x18a58c8: ("PRX_DIRECT_MEM", 20971520),
    0x18a58e8: ("CPU_MEMORY", 2097152000),
    0x18a5908: ("GPU_MEMORY", 2713714688),
    0x18a6668: ("SCREENSHOT_ALLOC", 133193728),
    0x18a5f88: ("SCREAM_SND_STREAM_MEM", 67108864),
    0x18a6008: ("SCREAM_SOUND_BANK_HEAP", 94371840),
    0x18a6488: ("LOADING_HEAP", 543162368),
    0x18a6548: ("GAME_TO_GPU_RING", 189792256),
    0x18a6568: ("RENDER_TO_GPU_RING", 686817280),
    0x18a6708: ("RENDER_TARGET #133", 44154880),
    0x18a6728: ("RENDER_TARGET #134", 690699264),
    0x18a6768: ("RENDER_BUFFER", 385875968),
    0x18a6788: ("LEVEL_BUFFER", 268435456),
}
A_PRX, A_CPU, A_GPU, A_SCR, A_SND1, A_SND2, A_LOAD, A_G2G, A_R2G, A_RT133, A_RT134, A_RB, A_LVL = \
    0x18a58c8, 0x18a58e8, 0x18a5908, 0x18a6668, 0x18a5f88, 0x18a6008, 0x18a6488, 0x18a6548, 0x18a6568, \
    0x18a6708, 0x18a6728, 0x18a6768, 0x18a6788
# запас, проверенный на практике (подтверждено на 2240x960 и 2560x1080)
MARGINS = {A_RT133: 1.15, A_RT134: 1.057, A_RB: 1.006}
LEVEL_CUT = 20 * MB          # LEVEL_BUFFER 256 -> 236 МБ (как в Pro-таблице игры)
SCR_MIN, SND_MIN, LOAD_MIN = 24 * MB, 1 * MB, 256 * MB
R2G_MIN, G2G_MIN = 400 * MB, 100 * MB


# ----------------------------------------------------------------------------------------
# Локализация (EN / RU / UK). Язык берётся из системы, иначе EN. Переопределить: --lang en|ru|uk
# ----------------------------------------------------------------------------------------
LANG = "en"
TR = {
 "en": {
  "no_change": "Area is not larger than 1920x1080 - no memory budget changes needed.",
  "budget_err": "For %dx%d +%d MB of GPU memory is needed, but only %d MB can be safely taken from CPU%s.\nEnable dmem expansion or the aggressive mode, lower the resolution-dependent share, or pick a lower resolution.",
  "no_aggr": " (aggressive mode is off)",
  "margin_note": " (margin reduced to 1.0)",
  "info_text": "GPU +%d MB, CPU -%d MB, total direct memory %d MB%s%s",
  "info_exp": " (expanded: the direct-memory constant is patched, shadPS4 needs enough dmem)",
  "info_orig": " (as in the original)",
  "dmem_ok": "No dmem expansion needed: total direct memory is %d MB, stock shadPS4 is fine.",
  "dmem_exp": "Total direct memory of the game: %d MB (0x%x bytes) = 4608 + %d MB. shadPS4 must provide at least %d MB of direct memory to the game (the game asks the emulator for the size, function 0x1485f80, it is used as searchEnd in sceKernelAllocateDirectMemory). With stock shadPS4 (4608 MB) the game will crash - build/configure the emulator with such dmem. The patch targets the base mode (in Neo mode the game compares the size with 5 GB).",
  "card_exp": "shadPS4 must provide at least %d MB (4608 + %d MB) of direct memory. With stock shadPS4 the game will crash - use an emulator build with this dmem. Base mode only (Neo mode compares the size with 5 GB).",
  "card_ok": "Stock shadPS4 (4608 MB) is enough.",
  "gpu_cap_note": " (the game cannot allocate more than %d MB for GPU_MEMORY, so the resolution-dependent growth is limited to %d%%)",
  "c_169": "16:9: aspect, camera, HUD and video shader patches are not needed (only resolution and memory)",
  "spv_skip169": "Shader skipped: not needed for 16:9",
  "g_169": "   ✔ 16:9: only resolution and memory are patched (HUD, camera and shader stay untouched)",
  "spv_cache": '⚠ Heads-up: with the shader cache enabled, shadPS4 may keep using the stock shader from the cache instead of user/shader/patch. Specify the cache folder or ZIP in the «Shader cache» field (--cache in CLI) and the patcher will patch the shader right there.',
  "put_xml": "   -> copy into your shadPS4 folder: %s",
  "put_spv": "   -> copy into your shadPS4 folder: %s",
  "put_all": "Copy the «user» folder from the ShadPS4 folder into your shadPS4 folder (merge, replace files).",
  "c_res": "2. Resolution: the 1920x1080 slot of the Neo table -> %dx%d",
  "c_aspect": "3. Global aspect ratio %d:%d",
  "c_budget": "1. Memory budgets: %s",
  "c_row": "%s: %.2f -> %.2f MB",
  "c_dmem_const": "Direct memory size (kAllocSystemDirect) 4608 -> %d MB (base table)",
  "c_dmem_warn": "ATTENTION: shadPS4 must provide at least %d MB of direct memory (dmem) to the game",
  "c_clip": "4. Game camera clipping bounds: x * R, R=%.6f",
  "c_cam": "5. Render camera: cot(fov/2) / R",
  "c_ui": "6. HUD/UI quads: X scale 2/(1280*R), offset -1/R",
  "c_proj": "10. 3D -> canvas projection: X * R",
  "c_font": "8. Font: canvas width 1280*R",
  "c_cross": "9. Crosshair (disp32 -> constant of block 8)",
  "c_dev": "7. Dev Menu UI",
  "c_icon": "11. Interact/pickup icons: world->canvas X * R (code cave)",
  "c_treasure": "12. Collectibles preview (pickup notification / inventory artifacts): scene camera fov keeps the 16:9 vertical view",
  "md_name": "Ultrawide %dx%d",
  "md_note_dmem": ". Requires shadPS4 with dmem of at least %d MB",
  "err_nopatch": "The base XML has no </Patch>",
  "spv_bad": "Corrupted SPIR-V", "spv_not": "This is not SPIR-V",
  "spv_uv": "UV calculation not found (CompositeConstruct -> ImageSample). Is this the TLOU video shader?",
  "spv_uvs": "Unexpected UV structure", "spv_nof32": "No float32 type", "spv_noiw": "No OpImageWrite", "spv_notex": "Texel not found",
  "spv_already": "Shader was already patched (k=%.5f, b=%.5f): constants replaced with k=%.5f, b=%.5f",
  "spv_orig": "Original shader: inserted u' = u*%.5f + (%.5f), black mask outside [0,1]",
  "eboot_ok": "eboot: OK (clean 01.11)", "eboot_bad": "eboot: differs at %s - not a clean 01.11", "eboot_fail": "eboot: cannot read (%s)",
  "g_title": "TLOU Remastered — Ultrawide Patch",
  "g_sub": "Generates an XML patch for eboot.bin 01.11 and a video cutscene shader for shadPS4",
  "g_res": "Resolution", "g_preset": "Preset:", "g_width": "Width:", "g_height": "Height:", "g_custom": "Custom…",
  "g_ratio": "Aspect ratio %.4f:1 (%d:%d), multiplier to 16:9 R = %.6f",
  "g_narrow": "   ⚠ narrower than 16:9: HUD edges will be cropped",
  "g_files": "Files", "g_browse": "Browse…",
  "g_eboot": "eboot.bin:", "ph_eboot": "optional — checks that it is a clean 01.11",
  "g_xmlin": "Base XML:",
  "g_spv": "Shader (.spv):", "ph_spv": "cs_0x00000000562c4394_0.spv (original or already patched)",
  "g_outhint": "Results are saved into the «ShadPS4» folder next to the source files, with the same structure as in shadPS4 (user/patches/…, user/shader/patch/…). Copy it into your shadPS4 folder yourself.",
  "g_mem": "Memory budget",
  "mode_off": "Without dmem expansion — reduce CPU memory (stock shadPS4)",
  "mode_full": "With dmem expansion — keep CPU memory (needs shadPS4 with larger dmem)",
  "g_adv": "Show advanced (experimental) options",
  "adv_manual": "Set the dmem expansion manually", "adv_extra": "Extra direct memory:",
  "adv_extra_tip": "How many MB of direct memory to add above 4608. The rest of the GPU growth is taken from CPU.",
  "adv_frac": "Resolution-dependent share:",
  "adv_frac_tip": "Share of the RENDER_TARGET/RENDER_BUFFER budget that grows with the screen area. 100% is safe; lower values are for very large resolutions (verify by running the game).",
  "adv_aggr": "Aggressive mode (also shrink RENDER_TO_GPU_RING / GAME_TO_GPU_RING)",
  "adv_keep": "Do not disable previous resolution sections in the base XML",
  "card_cap": "Direct memory (dmem) that shadPS4 must provide", "card_std": "(stock value)", "bytes": "bytes",
  "card_bad": "Calculation is impossible with the current settings.",
  "g_calc": "Budget calculation", "col_entry": "Entry", "col_was": "Was, MB", "col_now": "Now, MB",
  "sum_cap": " | safely freed from CPU: %d MB", "g_log": "Log", "g_go": "Create patch",
  "done_title": "Done", "done_msg": "Files saved. See the log for details.", "err_title": "Error", "err_prefix": "Error: %s",
  "log_xml": "XML saved: %s", "log_spv": "Shader: %s\n  -> %s",
  'g_gh': 'Add the patch to the latest file from GitHub (recommended)',
  'g_ghhint': 'Downloads the current TheLastOfUsRemastered.xml from shadps4-emu/ps4_cheats and appends the patch to its end. An identical patch is not duplicated, an outdated one is replaced. If GitHub is unavailable, you get a block to paste into TheLastOfUsRemastered.xml manually.',
  'gh_fetch': 'GitHub: downloading the latest TheLastOfUsRemastered.xml…',
  'gh_ok': '   downloaded: %d bytes, patches in the file: %d',
  'gh_added': '✔ Patch «%s» added to the end of the file.',
  'gh_updated': '✔ Patch «%s» already existed in an older form (%d lines, now %d) — replaced entirely.',
  'gh_off': '   earlier resolution patches switched off: %d',
  'gh_same': 'Patch «%s» is already in the GitHub file and is identical — nothing to add.',
  'gh_conflict': 'The GitHub file already has a patch «%s» with a different set of lines (%d there, %d in the patcher). It was left untouched so that nothing is overwritten by mistake.',
  'gh_fail': 'Could not download the file from GitHub: %s',
  'gh_bad': 'unexpected file contents',
  'gh_skip': 'GitHub is not used: a base XML file is specified.',
  'put_gh': '   -> replace this file in your shadPS4 folder: %s',
  'gh_man_log': 'A block for manual insertion is saved: %s',
  'gh_man_msg': 'The patch block is saved here:\n%s\n\nOpen TheLastOfUsRemastered.xml (<shadPS4>/user/patches/shadPS4) in a text editor and paste the block right before the closing </Patch> tag.',
  'warn_title': 'Done, with a note',
  'ph_xmlin': 'optional — your own base file (used instead of GitHub)',
  'g_cache': 'Shader cache (workaround)',
  'g_cachep': 'Cache:',
  'g_dir': 'Folder…',
  'g_zip': 'ZIP…',
  'ph_cache': 'optional — folder or .zip with the shadPS4 shader cache',
  'g_cachehint': 'Workaround for a shadPS4 bug: with the shader cache enabled, from the second launch the emulator ignores user/shader/patch and takes the stock shader from the cache. The patcher finds the video shader in the cache (by size and SHA-256) and patches it in place. Close the game and shadPS4 beforehand. The original shader is saved to the «backup» folder.',
  'cache_scan': 'Shader cache: scanning %s',
  'cache_stat': '   files checked: %d · same size: %d · confirmed by SHA-256: %d',
  'cache_hit_orig': '   found the stock video shader: %s',
  'cache_hit_patched': '   found an already patched video shader: %s',
  'cache_backup': '   backup of the original: %s',
  'cache_zip': '   rewriting the archive, this may take a moment…',
  'cache_done': '✔ Shader cache: patched %d file(s) for %dx%d.',
  'cache_reset': '✔ Shader cache: the previously patched shader was reset to neutral (16:9), files: %d.',
  'cache_same': 'Shader cache: the shader is already patched for %dx%d — nothing to change.',
  'cache_skip169': 'Shader cache left untouched: the video shader is not needed for 16:9.',
  'cache_nf_log': '⚠ Shader cache: the video shader was not found (see the hint).',
  'cache_nf_title': 'Video shader not found in the cache',
  'cache_nf_msg': 'The cutscene video shader is not in the shader cache yet.\n\nIt appears there only after the game has played a cutscene. To fix this:\n1. Launch the game and start any cutscene — for example Options → Credits (the credits are a cutscene too).\n2. Close the game completely.\n3. Run the patcher again with the same cache path.',
  'cache_err_path': 'Shader cache path not found: %s',
  'cache_err_type': 'The specified file is not a ZIP archive: %s',
  'cache_err_write': 'Could not write to the shader cache: %s\nClose the game and shadPS4, then try again.',
  'cache_err_verify': 'Verification after writing failed — the original archive was left unchanged.',
  # v5 new strings
  'opt_tag': '(optional)',
  'help_title': 'Help',
  'g_spv_group': 'Video cutscene shader patch',
  'spv_use_lbl': 'Patch the video shader too (fixes stretched cutscenes for ultrawide)',
  'spv_why': 'Without this patch, cutscenes (in-engine videos) will appear stretched. Not needed for 16:9.',
  'spv_auto_lbl': 'Recommended — patch via shader cache (automatic)',
  'spv_fname_lbl': 'File to find:',
  'spv_cache_prereq': 'Requires: enable «Enable Shader Cache» in shadPS4 settings. Then launch the game, play any cutscene at least once (Options → Credits works), close the game. The shader cache will be at: <shadPS4 folder>\\user\\shader\\cache',
  'spv_cache_hint': 'Specify the folder above (<shadPS4>\\user\\shader\\cache) or its ZIP export. The patcher will find and patch the video shader automatically — no need to know the file name. Close the game and shadPS4 before patching.\n⚠ Note: after updating shadPS4 you may need to re-patch the shader — the cache file name can change with a new emulator version.',
  'spv_manual_prereq': 'Requires: enable «Enable Shader Dumping» in shadPS4 settings. Launch the game, play any cutscene (Options → Credits works), close the game. The shader will appear at: <shadPS4 folder>\\user\\shader\\dumps',
  'spv_manual_lbl': 'Alternative — use shader dumps (manual .spv file)',
  'g_spv_file': 'Shader file:',
  'spv_manual_hint': 'The file name is shown above — find it in the dumps folder. After patching, the result goes to user\\shader\\patch\\.',
  'g_extra_sect': 'Advanced / optional files ▸',
  'extra_sect_hint': 'These fields are optional. eboot.bin is only used to verify the game version. Base XML is only needed if you already have a custom cheats file.',
  'mode_desc_off': '✅ GPU gets more memory — CPU memory stays untouched. Recommended. Supported by all recent shadPS4 builds out of the box.',
  'mem_help_tip': 'Extended (recommended): GPU gets more memory — CPU memory stays unchanged. Supported out of the box by all recent shadPS4 builds. Safest for game stability.\n\nStandard: GPU gets more memory — taken from CPU memory (sound buffers, loading heap, screenshots are reduced). Works with stock shadPS4, but may rarely cause instability.\n\nFor most users: use Extended if your shadPS4 supports it.',
  'status_will_create': 'Will create',
  'go_tooltip': 'Creates:\n• XML patch for eboot.bin (resolution, aspect ratio, HUD, camera, memory)\n• Video shader patch (if enabled above)\nResults are saved in a «ShadPS4» folder next to this program.',
 },
 "ru": {
  "no_change": "Площадь не больше 1920x1080 - бюджеты памяти менять не нужно.",
  "budget_err": "Для %dx%d нужно +%d МБ GPU, а безопасно высвободить можно только %d МБ CPU%s.\nВключите расширение dmem или агрессивный режим, уменьшите долю, зависящую от разрешения, или выберите разрешение поменьше.",
  "no_aggr": " (агрессивный режим выключен)",
  "margin_note": " (запас уменьшен до 1.0)",
  "info_text": "GPU +%d МБ, CPU -%d МБ, общая direct-память %d МБ%s%s",
  "info_exp": " (расширена: патчится константа direct-памяти, shadPS4 должен отдавать достаточный dmem)",
  "info_orig": " (как в оригинале)",
  "dmem_ok": "Расширение dmem не требуется: итоговая direct-память %d МБ, стоковый shadPS4 подходит.",
  "dmem_exp": "Итоговая direct-память игры: %d МБ (0x%x байт) = 4608 + %d МБ. shadPS4 должен отдавать игре не меньше %d МБ direct-памяти (размер игра узнаёт у эмулятора, функция 0x1485f80, он идёт как searchEnd в sceKernelAllocateDirectMemory). Со стоковым shadPS4 (4608 МБ) игра упадёт - соберите/настройте эмулятор с таким dmem. Патч рассчитан на базовый режим (в Neo-режиме игра сверяет размер с 5 ГБ).",
  "card_exp": "shadPS4 должен отдавать не меньше %d МБ (4608 + %d МБ) direct-памяти. Со стоковым shadPS4 игра упадёт - нужна сборка эмулятора с таким dmem. Только базовый режим (в Neo игра сверяет размер с 5 ГБ).",
  "card_ok": "Стокового shadPS4 (4608 МБ) достаточно.",
  "gpu_cap_note": " (игра не может выделить GPU_MEMORY больше %d МБ, поэтому рост, зависящий от разрешения, ограничен до %d%%)",
  "c_169": "16:9: правки аспекта, камеры, HUD и шейдера видео не нужны (только разрешение и память)",
  "spv_skip169": "Шейдер пропущен: для 16:9 не нужен",
  "g_169": "   ✔ 16:9: патчится только разрешение и память (HUD, камера и шейдер не трогаются)",
  "spv_cache": '⚠ Важно: при включённом кэше шейдеров shadPS4 может продолжать брать стоковый шейдер из кэша, а не из user/shader/patch. Укажите папку или ZIP кэша в поле «Кэш шейдеров» (в CLI — --cache), и патчер пропатчит шейдер прямо там.',
  "put_xml": "   -> перенесите в папку shadPS4: %s",
  "put_spv": "   -> перенесите в папку shadPS4: %s",
  "put_all": "Скопируйте папку «user» из созданной папки ShadPS4 в вашу папку shadPS4 (с объединением и заменой файлов).",
  "c_res": "2. Разрешение: слот 1920x1080 в Neo-таблице -> %dx%d",
  "c_aspect": "3. Глобальный аспект %d:%d",
  "c_budget": "1. Бюджеты памяти: %s",
  "c_row": "%s: %.2f -> %.2f МБ",
  "c_dmem_const": "Размер direct-памяти (kAllocSystemDirect) 4608 -> %d МБ (базовая таблица)",
  "c_dmem_warn": "ВНИМАНИЕ: shadPS4 должен отдавать игре не меньше %d МБ direct-памяти (dmem)",
  "c_clip": "4. Рамки отсечения игровой камеры: x * R, R=%.6f",
  "c_cam": "5. Рендер-камера: cot(fov/2) / R",
  "c_ui": "6. HUD/UI-квады: масштаб X 2/(1280*R), смещение -1/R",
  "c_proj": "10. Проекция 3D -> канва: X * R",
  "c_font": "8. Шрифт: ширина канвы 1280*R",
  "c_cross": "9. Прицел (disp32 -> константа блока 8)",
  "c_dev": "7. Dev Menu UI",
  "c_icon": "11. Иконки взаимодействия/подбора: проекция мир->канвас X * R (code cave)",
  "c_treasure": "12. Превью коллекционных предметов (уведомление о подборе / артефакты в инвентаре): fov камеры сцены сохраняет вертикальный обзор 16:9",
  "md_name": "Ультраширокий %dx%d",
  "md_note_dmem": ". Нужен shadPS4 с dmem не меньше %d МБ",
  "err_nopatch": "В базовом XML нет </Patch>",
  "spv_bad": "Битый SPIR-V", "spv_not": "Это не SPIR-V",
  "spv_uv": "Не найден расчёт UV (CompositeConstruct -> ImageSample). Это шейдер видео TLOU?",
  "spv_uvs": "Неожиданная структура UV", "spv_nof32": "Нет типа float32", "spv_noiw": "Нет OpImageWrite", "spv_notex": "Не найден texel",
  "spv_already": "Шейдер уже был пропатчен (k=%.5f, b=%.5f): константы заменены на k=%.5f, b=%.5f",
  "spv_orig": "Шейдер оригинальный: вставлено u' = u*%.5f + (%.5f), чёрная маска вне [0,1]",
  "eboot_ok": "eboot: OK (оригинальный 01.11)", "eboot_bad": "eboot: отличается в %s - это не чистый 01.11", "eboot_fail": "eboot: не удалось прочитать (%s)",
  "g_title": "TLOU Remastered — Ultrawide Patch",
  "g_sub": "Генератор XML-патча eboot.bin 01.11 и шейдера видеороликов для shadPS4",
  "g_res": "Разрешение", "g_preset": "Пресет:", "g_width": "Ширина:", "g_height": "Высота:", "g_custom": "Свой…",
  "g_ratio": "Соотношение %.4f:1 (%d:%d), множитель к 16:9 R = %.6f",
  "g_narrow": "   ⚠ уже, чем 16:9: HUD по краям будет обрезаться",
  "g_files": "Файлы", "g_browse": "Обзор…",
  "g_eboot": "eboot.bin:", "ph_eboot": "необязательно — проверка, что это чистый 01.11",
  "g_xmlin": "Базовый XML:",
  "g_spv": "Шейдер (.spv):", "ph_spv": "cs_0x00000000562c4394_0.spv (оригинал или уже пропатченный)",
  "g_outhint": "Результаты сохраняются в папку «ShadPS4» рядом с исходными файлами, со структурой как в shadPS4 (user/patches/…, user/shader/patch/…). Перенесите её в папку shadPS4 самостоятельно.",
  "g_mem": "Бюджет памяти",
  "mode_off": "Без расширения dmem — урезать CPU-память (стоковый shadPS4)",
  "mode_full": "С расширением dmem — CPU-память не трогать (нужен shadPS4 с большим dmem)",
  "g_adv": "Показать расширенные (экспериментальные) настройки",
  "adv_manual": "Задать расширение dmem вручную", "adv_extra": "Доп. direct-память:",
  "adv_extra_tip": "Сколько МБ direct-памяти добавить сверх 4608. Остаток прироста GPU забирается у CPU.",
  "adv_frac": "Доля, зависящая от разрешения:",
  "adv_frac_tip": "Какая часть бюджета RENDER_TARGET/RENDER_BUFFER растёт вместе с площадью экрана. 100% — безопасно, меньше — для очень больших разрешений (проверяйте запуском).",
  "adv_aggr": "Агрессивный режим (урезать ещё и RENDER_TO_GPU_RING / GAME_TO_GPU_RING)",
  "adv_keep": "Не отключать прежние разрешающие секции в базовом XML",
  "card_cap": "Direct-память (dmem), которую должен отдавать shadPS4", "card_std": "(стоковое значение)", "bytes": "байт",
  "card_bad": "Расчёт невозможен для текущих параметров.",
  "g_calc": "Расчёт бюджетов", "col_entry": "Запись", "col_was": "Было, МБ", "col_now": "Стало, МБ",
  "sum_cap": " | безопасно высвобождаемо у CPU: %d МБ", "g_log": "Журнал", "g_go": "Создать патч",
  "done_title": "Готово", "done_msg": "Файлы сохранены. Подробности — в журнале.", "err_title": "Ошибка", "err_prefix": "Ошибка: %s",
  "log_xml": "XML сохранён: %s", "log_spv": "Шейдер: %s\n  -> %s",
  'g_gh': 'Дополнить патчем актуальный файл с GitHub (рекомендуется)',
  'g_ghhint': 'Скачивает текущий TheLastOfUsRemastered.xml из shadps4-emu/ps4_cheats и добавляет патч в его конец. Такой же патч не дублируется, устаревший заменяется. Если GitHub недоступен, вы получите блок для ручной вставки в TheLastOfUsRemastered.xml.',
  'gh_fetch': 'GitHub: скачиваю актуальный TheLastOfUsRemastered.xml…',
  'gh_ok': '   скачано: %d байт, патчей в файле: %d',
  'gh_added': '✔ Патч «%s» добавлен в конец файла.',
  'gh_updated': '✔ Патч «%s» уже был, но в устаревшем виде (строк: %d, теперь %d) — заменён целиком.',
  'gh_off': '   прежних патчей разрешения отключено: %d',
  'gh_same': 'Патч «%s» уже есть в файле на GitHub и полностью совпадает — добавлять нечего.',
  'gh_conflict': 'В файле на GitHub уже есть патч «%s» с другим набором строк (там %d, в патчере %d). Файл оставлен без изменений, чтобы ничего не перезаписать по ошибке.',
  'gh_fail': 'Не удалось скачать файл с GitHub: %s',
  'gh_bad': 'неожиданное содержимое файла',
  'gh_skip': 'GitHub не используется: указан свой базовый XML.',
  'put_gh': '   -> замените этот файл в папке shadPS4: %s',
  'gh_man_log': 'Блок для ручной вставки сохранён: %s',
  'gh_man_msg': 'Блок патча сохранён здесь:\n%s\n\nОткройте TheLastOfUsRemastered.xml (<папка shadPS4>/user/patches/shadPS4) в текстовом редакторе и вставьте блок прямо перед закрывающим тегом </Patch>.',
  'warn_title': 'Готово, но есть нюанс',
  'ph_xmlin': 'необязательно — свой базовый файл (используется вместо GitHub)',
  'g_cache': 'Кэш шейдеров (временное решение)',
  'g_cachep': 'Кэш:',
  'g_dir': 'Папка…',
  'g_zip': 'ZIP…',
  'ph_cache': 'необязательно — папка или .zip с кэшем шейдеров shadPS4',
  'g_cachehint': 'Обход бага shadPS4: при включённом кэше шейдеров со второго запуска эмулятор игнорирует user/shader/patch и берёт стоковый шейдер из кэша. Патчер находит шейдер видео в кэше (по размеру и SHA-256) и патчит его на месте. Перед этим закройте игру и shadPS4. Оригинал шейдера сохраняется в папку «backup».',
  'cache_scan': 'Кэш шейдеров: сканирую %s',
  'cache_stat': '   проверено файлов: %d · совпал размер: %d · подтверждено SHA-256: %d',
  'cache_hit_orig': '   найден стоковый шейдер видео: %s',
  'cache_hit_patched': '   найден уже пропатченный шейдер видео: %s',
  'cache_backup': '   копия оригинала: %s',
  'cache_zip': '   пересобираю архив, это может занять некоторое время…',
  'cache_done': '✔ Кэш шейдеров: пропатчено файлов — %d (%dx%d).',
  'cache_reset': '✔ Кэш шейдеров: ранее пропатченный шейдер приведён к нейтральному виду (16:9), файлов: %d.',
  'cache_same': 'Кэш шейдеров: шейдер уже пропатчен под %dx%d — менять нечего.',
  'cache_skip169': 'Кэш шейдеров не тронут: для 16:9 шейдер видео не нужен.',
  'cache_nf_log': '⚠ Кэш шейдеров: шейдер видео не найден (см. подсказку).',
  'cache_nf_title': 'Шейдер видео не найден в кэше',
  'cache_nf_msg': 'Шейдер видеороликов пока отсутствует в кэше шейдеров.\n\nОн появляется там только после того, как в игре проиграна катсцена. Что нужно сделать:\n1. Запустите игру и включите любую катсцену — например, Options → Credits (титры тоже являются катсценой).\n2. Полностью закройте игру.\n3. Запустите патчер ещё раз с тем же путём к кэшу.',
  'cache_err_path': 'Путь к кэшу шейдеров не найден: %s',
  'cache_err_type': 'Указанный файл не является ZIP-архивом: %s',
  'cache_err_write': 'Не удалось записать в кэш шейдеров: %s\nЗакройте игру и shadPS4 и повторите попытку.',
  'cache_err_verify': 'Проверка после записи не пройдена — исходный архив оставлен без изменений.',
  # v5 new strings
  'opt_tag': '(необязательно)',
  'help_title': 'Справка',
  'g_spv_group': 'Патч шейдера видеороликов',
  'spv_use_lbl': 'Также пропатчить шейдер видео (исправляет растяжение катсцен для ультраширокого)',
  'spv_why': 'Без этого патча катсцены (внутриигровые видео) будут растянуты. Для 16:9 не нужен.',
  'spv_auto_lbl': 'Рекомендуется — патч через кэш шейдеров (автоматически)',
  'spv_fname_lbl': 'Файл для поиска:',
  'spv_cache_prereq': 'Необходимо: включите «Enable Shader Cache» в настройках shadPS4. Затем запустите игру, воспроизведите любую катсцену хотя бы раз (Options → Credits подойдёт), закройте игру. Кэш шейдеров находится по пути: <папка shadPS4>\\user\\shader\\cache',
  'spv_cache_hint': 'Укажите папку выше (<shadPS4>\\user\\shader\\cache) или её ZIP-архив. Патчер автоматически найдёт и пропатчит шейдер видео — знать имя файла не нужно. Закройте игру и shadPS4 перед патчингом.\n⚠ Важно: после обновления shadPS4 возможно придётся пропатчить шейдер заново — имя файла в кэше может поменяться с новой версией эмулятора.',
  'spv_manual_prereq': 'Необходимо: включите «Enable Shader Dumping» в настройках shadPS4. Запустите игру, воспроизведите любую катсцену (Options → Credits подойдёт), закройте игру. Шейдер появится по пути: <папка shadPS4>\\user\\shader\\dumps',
  'spv_manual_lbl': 'Альтернатива — дампы шейдеров (вручную, .spv файл)',
  'g_spv_file': 'Файл шейдера:',
  'spv_manual_hint': 'Имя файла указано выше — найдите его в папке dumps. После патчинга результат кладётся в user\\shader\\patch\\.',
  'g_extra_sect': 'Дополнительно / необязательные файлы ▸',
  'extra_sect_hint': 'Эти поля необязательны. eboot.bin нужен только для проверки версии игры. Базовый XML — только если у вас уже есть свой файл патчей.',
  'mode_desc_off': '✅ GPU получает больше памяти — CPU-память не трогается. Рекомендуется. Поддерживается всеми актуальными сборками shadPS4 из коробки.',
  'mem_help_tip': 'Расширенный (рекомендуется): GPU получает больше памяти — CPU-память не меняется. Поддерживается всеми актуальными сборками shadPS4 из коробки. Наиболее безопасен для стабильности.\n\nСтандартный: GPU получает больше памяти — за счёт CPU-памяти (звуковые буферы, куча загрузки, скриншоты уменьшаются). Работает со стоковым shadPS4, но в редких случаях возможны нестабильность или крашы.\n\nДля большинства: используйте Расширенный, это поддерживается всеми актуальными сборками shadPS4.',
  'status_will_create': 'Будет создано',
  'go_tooltip': 'Создаёт:\n• XML-патч для eboot.bin (разрешение, аспект, HUD, камера, память)\n• Патч шейдера видео (если включено выше)\nРезультаты сохраняются в папку «ShadPS4» рядом с программой.',
 },
 "uk": {
  "no_change": "Площа не більша за 1920x1080 - бюджети пам'яті змінювати не потрібно.",
  "budget_err": "Для %dx%d потрібно +%d МБ GPU, а безпечно вивільнити можна лише %d МБ CPU%s.\nУвімкніть розширення dmem або агресивний режим, зменште частку, що залежить від роздільної здатності, або оберіть меншу роздільну здатність.",
  "no_aggr": " (агресивний режим вимкнено)",
  "margin_note": " (запас зменшено до 1.0)",
  "info_text": "GPU +%d МБ, CPU -%d МБ, загальна direct-пам'ять %d МБ%s%s",
  "info_exp": " (розширена: патчиться константа direct-пам'яті, shadPS4 має віддавати достатній dmem)",
  "info_orig": " (як в оригіналі)",
  "dmem_ok": "Розширення dmem не потрібне: підсумкова direct-пам'ять %d МБ, стоковий shadPS4 підходить.",
  "dmem_exp": "Підсумкова direct-пам'ять гри: %d МБ (0x%x байт) = 4608 + %d МБ. shadPS4 має віддавати грі не менше %d МБ direct-пам'яті (розмір гра дізнається в емулятора, функція 0x1485f80, він іде як searchEnd у sceKernelAllocateDirectMemory). Зі стоковим shadPS4 (4608 МБ) гра впаде - зберіть/налаштуйте емулятор з таким dmem. Патч розрахований на базовий режим (у Neo-режимі гра звіряє розмір з 5 ГБ).",
  "card_exp": "shadPS4 має віддавати не менше %d МБ (4608 + %d МБ) direct-пам'яті. Зі стоковим shadPS4 гра впаде - потрібна збірка емулятора з таким dmem. Лише базовий режим (у Neo гра звіряє розмір з 5 ГБ).",
  "card_ok": "Стокового shadPS4 (4608 МБ) достатньо.",
  "gpu_cap_note": " (гра не може виділити GPU_MEMORY більше %d МБ, тому зростання, що залежить від роздільної здатності, обмежено до %d%%)",
  "c_169": "16:9: правки співвідношення, камери, HUD та шейдера відео не потрібні (лише роздільна здатність і пам'ять)",
  "spv_skip169": "Шейдер пропущено: для 16:9 не потрібен",
  "g_169": "   ✔ 16:9: патчиться лише роздільна здатність і пам'ять (HUD, камера та шейдер не чіпаються)",
  "spv_cache": '⚠ Важливо: за ввімкненого кешу шейдерів shadPS4 може й надалі брати стоковий шейдер із кешу, а не з user/shader/patch. Вкажіть теку або ZIP кешу в полі «Кеш шейдерів» (у CLI — --cache), і патчер пропатчить шейдер просто там.',
  "put_xml": "   -> перенесіть у папку shadPS4: %s",
  "put_spv": "   -> перенесіть у папку shadPS4: %s",
  "put_all": "Скопіюйте папку «user» зі створеної папки ShadPS4 у вашу папку shadPS4 (з об'єднанням і заміною файлів).",
  "c_res": "2. Роздільна здатність: слот 1920x1080 у Neo-таблиці -> %dx%d",
  "c_aspect": "3. Глобальне співвідношення сторін %d:%d",
  "c_budget": "1. Бюджети пам'яті: %s",
  "c_row": "%s: %.2f -> %.2f МБ",
  "c_dmem_const": "Розмір direct-пам'яті (kAllocSystemDirect) 4608 -> %d МБ (базова таблиця)",
  "c_dmem_warn": "УВАГА: shadPS4 має віддавати грі не менше %d МБ direct-пам'яті (dmem)",
  "c_clip": "4. Рамки відсікання ігрової камери: x * R, R=%.6f",
  "c_cam": "5. Рендер-камера: cot(fov/2) / R",
  "c_ui": "6. HUD/UI-квади: масштаб X 2/(1280*R), зміщення -1/R",
  "c_proj": "10. Проєкція 3D -> полотно: X * R",
  "c_font": "8. Шрифт: ширина полотна 1280*R",
  "c_cross": "9. Приціл (disp32 -> константа блока 8)",
  "c_dev": "7. Dev Menu UI",
  "c_icon": "11. Іконки взаємодії/підбору: проєкція світ->канвас X * R (code cave)",
  "c_treasure": "12. Превʼю колекційних предметів (сповіщення про підбір / артефакти в інвентарі): fov камери сцени зберігає вертикальний огляд 16:9",
  "md_name": "Ультраширокий %dx%d",
  "md_note_dmem": ". Потрібен shadPS4 з dmem не менше %d МБ",
  "err_nopatch": "У базовому XML немає </Patch>",
  "spv_bad": "Пошкоджений SPIR-V", "spv_not": "Це не SPIR-V",
  "spv_uv": "Не знайдено розрахунок UV (CompositeConstruct -> ImageSample). Це шейдер відео TLOU?",
  "spv_uvs": "Неочікувана структура UV", "spv_nof32": "Немає типу float32", "spv_noiw": "Немає OpImageWrite", "spv_notex": "Не знайдено texel",
  "spv_already": "Шейдер уже було пропатчено (k=%.5f, b=%.5f): константи замінено на k=%.5f, b=%.5f",
  "spv_orig": "Шейдер оригінальний: вставлено u' = u*%.5f + (%.5f), чорна маска поза [0,1]",
  "eboot_ok": "eboot: OK (оригінальний 01.11)", "eboot_bad": "eboot: відрізняється в %s - це не чистий 01.11", "eboot_fail": "eboot: не вдалося прочитати (%s)",
  "g_title": "TLOU Remastered — Ultrawide Patch",
  "g_sub": "Генератор XML-патча eboot.bin 01.11 та шейдера відеороликів для shadPS4",
  "g_res": "Роздільна здатність", "g_preset": "Пресет:", "g_width": "Ширина:", "g_height": "Висота:", "g_custom": "Власна…",
  "g_ratio": "Співвідношення %.4f:1 (%d:%d), множник до 16:9 R = %.6f",
  "g_narrow": "   ⚠ вужче за 16:9: HUD по краях буде обрізатись",
  "g_files": "Файли", "g_browse": "Огляд…",
  "g_eboot": "eboot.bin:", "ph_eboot": "необов'язково — перевірка, що це чистий 01.11",
  "g_xmlin": "Базовий XML:",
  "g_spv": "Шейдер (.spv):", "ph_spv": "cs_0x00000000562c4394_0.spv (оригінал або вже пропатчений)",
  "g_outhint": "Результати зберігаються в папку «ShadPS4» поруч з вихідними файлами, зі структурою як у shadPS4 (user/patches/…, user/shader/patch/…). Перенесіть її в папку shadPS4 самостійно.",
  "g_mem": "Бюджет пам'яті",
  "mode_off": "Без розширення dmem — урізати CPU-пам'ять (стоковий shadPS4)",
  "mode_full": "З розширенням dmem — CPU-пам'ять не чіпати (потрібен shadPS4 з більшим dmem)",
  "g_adv": "Показати розширені (експериментальні) налаштування",
  "adv_manual": "Задати розширення dmem вручну", "adv_extra": "Дод. direct-пам'ять:",
  "adv_extra_tip": "Скільки МБ direct-пам'яті додати понад 4608. Решта приросту GPU забирається у CPU.",
  "adv_frac": "Частка, що залежить від роздільної здатності:",
  "adv_frac_tip": "Яка частина бюджету RENDER_TARGET/RENDER_BUFFER росте разом з площею екрана. 100% — безпечно, менше — для дуже великих роздільних здатностей (перевіряйте запуском).",
  "adv_aggr": "Агресивний режим (урізати ще й RENDER_TO_GPU_RING / GAME_TO_GPU_RING)",
  "adv_keep": "Не вимикати попередні секції роздільної здатності в базовому XML",
  "card_cap": "Direct-пам'ять (dmem), яку має віддавати shadPS4", "card_std": "(стокове значення)", "bytes": "байт",
  "card_bad": "Розрахунок неможливий для поточних параметрів.",
  "g_calc": "Розрахунок бюджетів", "col_entry": "Запис", "col_was": "Було, МБ", "col_now": "Стало, МБ",
  "sum_cap": " | безпечно вивільнити у CPU: %d МБ", "g_log": "Журнал", "g_go": "Створити патч",
  "done_title": "Готово", "done_msg": "Файли збережено. Подробиці — в журналі.", "err_title": "Помилка", "err_prefix": "Помилка: %s",
  "log_xml": "XML збережено: %s", "log_spv": "Шейдер: %s\n  -> %s",
  'g_gh': 'Доповнити патчем актуальний файл з GitHub (рекомендовано)',
  'g_ghhint': 'Завантажує поточний TheLastOfUsRemastered.xml із shadps4-emu/ps4_cheats і додає патч наприкінці. Такий самий патч не дублюється, застарілий замінюється. Якщо GitHub недоступний, ви отримаєте блок для ручної вставки в TheLastOfUsRemastered.xml.',
  'gh_fetch': 'GitHub: завантажуємо актуальний TheLastOfUsRemastered.xml…',
  'gh_ok': '   завантажено: %d байт, патчів у файлі: %d',
  'gh_added': '✔ Патч «%s» додано наприкінці файлу.',
  'gh_updated': '✔ Патч «%s» уже був, але в застарілому вигляді (рядків: %d, тепер %d) — замінено повністю.',
  'gh_off': '   попередніх патчів роздільної здатності вимкнено: %d',
  'gh_same': 'Патч «%s» уже є у файлі на GitHub і повністю збігається — додавати нічого.',
  'gh_conflict': 'У файлі на GitHub уже є патч «%s» з іншим набором рядків (там %d, у патчері %d). Файл залишено без змін, щоб нічого не перезаписати помилково.',
  'gh_fail': 'Не вдалося завантажити файл з GitHub: %s',
  'gh_bad': 'неочікуваний вміст файлу',
  'gh_skip': 'GitHub не використовується: вказано власний базовий XML.',
  'put_gh': '   -> замініть цей файл у теці shadPS4: %s',
  'gh_man_log': 'Блок для ручної вставки збережено: %s',
  'gh_man_msg': 'Блок патча збережено тут:\n%s\n\nВідкрийте TheLastOfUsRemastered.xml (<тека shadPS4>/user/patches/shadPS4) у текстовому редакторі та вставте блок одразу перед закривним тегом </Patch>.',
  'warn_title': 'Готово, але є нюанс',
  'ph_xmlin': "необов'язково — власний базовий файл (використовується замість GitHub)",
  'g_cache': 'Кеш шейдерів (тимчасове рішення)',
  'g_cachep': 'Кеш:',
  'g_dir': 'Тека…',
  'g_zip': 'ZIP…',
  'ph_cache': "необов'язково — тека або .zip з кешем шейдерів shadPS4",
  'g_cachehint': 'Обхід бага shadPS4: за ввімкненого кешу шейдерів із другого запуску емулятор ігнорує user/shader/patch і бере стоковий шейдер із кешу. Патчер знаходить шейдер відео в кеші (за розміром і SHA-256) та патчить його на місці. Перед цим закрийте гру і shadPS4. Оригінал шейдера зберігається в теку «backup».',
  'cache_scan': 'Кеш шейдерів: скануємо %s',
  'cache_stat': '   перевірено файлів: %d · збігся розмір: %d · підтверджено SHA-256: %d',
  'cache_hit_orig': '   знайдено стоковий шейдер відео: %s',
  'cache_hit_patched': '   знайдено вже пропатчений шейдер відео: %s',
  'cache_backup': '   копія оригіналу: %s',
  'cache_zip': '   перезбираємо архів, це може тривати певний час…',
  'cache_done': '✔ Кеш шейдерів: пропатчено файлів — %d (%dx%d).',
  'cache_reset': '✔ Кеш шейдерів: раніше пропатчений шейдер приведено до нейтрального вигляду (16:9), файлів: %d.',
  'cache_same': 'Кеш шейдерів: шейдер уже пропатчено під %dx%d — міняти нічого.',
  'cache_skip169': 'Кеш шейдерів не чіпали: для 16:9 шейдер відео не потрібен.',
  'cache_nf_log': '⚠ Кеш шейдерів: шейдер відео не знайдено (див. підказку).',
  'cache_nf_title': 'Шейдер відео не знайдено в кеші',
  'cache_nf_msg': "Шейдера відеороликів поки немає в кеші шейдерів.\n\nВін з'являється там лише після того, як у грі відтворено катсцену. Що потрібно зробити:\n1. Запустіть гру та увімкніть будь-яку катсцену — наприклад, Options → Credits (титри також є катсценою).\n2. Повністю закрийте гру.\n3. Запустіть патчер ще раз із тим самим шляхом до кешу.",
  'cache_err_path': 'Шлях до кешу шейдерів не знайдено: %s',
  'cache_err_type': 'Указаний файл не є ZIP-архівом: %s',
  'cache_err_write': 'Не вдалося записати в кеш шейдерів: %s\nЗакрийте гру та shadPS4 і повторіть спробу.',
  'cache_err_verify': 'Перевірка після запису не пройдена — вихідний архів залишено без змін.',
  # v5 new strings
  'opt_tag': '(необов\'язково)',
  'help_title': 'Довідка',
  'g_spv_group': 'Патч шейдера відеороликів',
  'spv_use_lbl': 'Також пропатчити шейдер відео (виправляє розтягування катсцен для ультраширокого)',
  'spv_why': 'Без цього патчу катсцени (внутрішньоігрові відео) будуть розтягнуті. Для 16:9 не потрібен.',
  'spv_auto_lbl': 'Рекомендовано — патч через кеш шейдерів (автоматично)',
  'spv_fname_lbl': 'Файл для пошуку:',
  'spv_cache_prereq': 'Необхідно: увімкніть «Enable Shader Cache» у налаштуваннях shadPS4. Потім запустіть гру, відтворіть будь-яку катсцену хоча б раз (Options → Credits підійде), закрийте гру. Кеш шейдерів знаходиться за шляхом: <тека shadPS4>\\user\\shader\\cache',
  'spv_cache_hint': 'Вкажіть теку вище (<shadPS4>\\user\\shader\\cache) або її ZIP-архів. Патчер автоматично знайде і пропатчить шейдер відео — знати ім\'я файлу не потрібно. Закрийте гру та shadPS4 перед патчингом.\n⚠ Важливо: після оновлення shadPS4 можливо доведеться пропатчити шейдер знову — ім\'я файлу в кеші може змінитися з новою версією емулятора.',
  'spv_manual_prereq': 'Необхідно: увімкніть «Enable Shader Dumping» у налаштуваннях shadPS4. Запустіть гру, відтворіть будь-яку катсцену (Options → Credits підійде), закрийте гру. Шейдер з\'явиться за шляхом: <тека shadPS4>\\user\\shader\\dumps',
  'spv_manual_lbl': 'Альтернатива — дампи шейдерів (вручну, .spv файл)',
  'g_spv_file': 'Файл шейдера:',
  'spv_manual_hint': 'Ім\'я файлу вказано вище — знайдіть його у теці dumps. Після патчингу результат кладеться в user\\shader\\patch\\.',
  'g_extra_sect': 'Додатково / необов\'язкові файли ▸',
  'extra_sect_hint': 'Ці поля необов\'язкові. eboot.bin потрібен лише для перевірки версії гри. Базовий XML — лише якщо у вас вже є власний файл патчів.',
  'mode_desc_off': '✅ GPU отримує більше пам\'яті — CPU-пам\'ять не чіпається. Рекомендовано. Підтримується всіма актуальними збірками shadPS4 з коробки.',
  'mem_help_tip': 'Розширений (рекомендовано): GPU отримує більше пам\'яті — CPU-пам\'ять не змінюється. Підтримується всіма актуальними збірками shadPS4 з коробки. Найбезпечніший для стабільності.\n\nСтандартний: GPU отримує більше пам\'яті — за рахунок CPU-пам\'яті (звукові буфери, купа завантаження, скріншоти зменшуються). Працює зі стоковим shadPS4, але в рідкісних випадках можливі нестабільність або краші.\n\nДля більшості: використовуйте Розширений, це підтримується всіма актуальними збірками shadPS4.',
  'status_will_create': 'Буде створено',
  'go_tooltip': 'Створює:\n• XML-патч для eboot.bin (роздільна здатність, аспект, HUD, камера, пам\'ять)\n• Патч шейдера відео (якщо увімкнено вище)\nРезультати зберігаються в теку «ShadPS4» поруч з програмою.',
 },
}


def tr(key, *a):
    s = TR.get(LANG, {}).get(key) or TR["en"][key]
    return s % a if a else s


def detect_lang():
    """Язык системы: ru / uk, иначе en."""
    cands = []
    try:
        from PyQt5 import QtCore
        cands += [str(x) for x in QtCore.QLocale.system().uiLanguages()] + [QtCore.QLocale.system().name()]
    except Exception:
        pass
    try:
        import locale
        cands += [locale.getlocale()[0] or "", os.environ.get("LANG", ""), os.environ.get("LANGUAGE", "")]
    except Exception:
        pass
    for c in cands:
        code = c.lower().replace("_", "-")[:2]
        if code in ("ru", "uk"): return code
        if code == "en": return "en"
    return "en"


GPU_MAX_MB = 4096            # лимит игры на размер GPU_MEMORY (и CPU_MEMORY): <= 4 GiB
DMEM_BASE_MB = 4608           # kAllocSystemDirect по умолчанию (константа 0x120000000)
FULL_EXTRA = 1 << 16          # «бесконечное» расширение: CPU не урезается вообще


def is_169(W, H):
    """16:9 (любое разрешение): HUD, камера и шейдер видео менять не нужно."""
    return abs((W / H) / (16 / 9) - 1) < 0.003


def resolve_extra(mode, manual=0):
    """mode: 'off' - без расширения dmem (урезать CPU), 'full' - с расширением (CPU не трогаем), 'custom' - вручную."""
    return 0 if mode == 'off' else FULL_EXTRA if mode == 'full' else int(manual)


def dmem_note(info):
    """Текст про direct-память для выбранного разрешения (GUI/CLI/XML)."""
    t = info.get("dmem_mb", DMEM_BASE_MB)
    if not info.get("expanded"):
        return tr("dmem_ok", t)
    return tr("dmem_exp", t, t * MB, t - DMEM_BASE_MB, t)


DMEM_HEADROOM_MB = 1000        # запас сверх расчёта: на 2560x1080 расчёт 402 МБ, +500 и +1000 не хватило, заработало с +1500


def dmem_user_extra(info):
    """Сколько МБ dmem юзеру выделить в shadPS4: расчётное D + запас, округлено вверх до 500 МБ."""
    d = info["dmem_mb"] - DMEM_BASE_MB
    return int(math.ceil((d + DMEM_HEADROOM_MB) / 500.0)) * 500


def f32(x): return struct.pack('<f', x).hex()
def u32(x): return struct.pack('<I', int(x)).hex()


# ----------------------------------------------------------------------------------------
# Бюджеты памяти
# ----------------------------------------------------------------------------------------
class BudgetError(Exception):
    pass


def calc_budget(W, H, aggressive=False, frac=1.0, margins=None, extra=0):
    """Возвращает (lines, rows, info). rows: (имя, было МБ, стало МБ). Ничего не удаляет и не ломает
    инварианты игры: PRX+CPU+GPU = 4608 МБ, суммы подбюджетов CPU и GPU сходятся ТОЧНО, CPU/GPU кратны 2 МБ."""
    O = {a: v[1] for a, v in ORIG_BUDGET.items()}
    area = (W * H) / (BASE_W * BASE_H)
    area = 1.0 + (area - 1.0) * frac if area > 1.0 else area   # frac: доля бюджета, зависящая от разрешения
    if area <= 1.0:
        return [], [], dict(D=0, total=DMEM_BASE_MB, dmem_mb=DMEM_BASE_MB, expanded=False,
                            text=tr("no_change"))
    mg = dict(MARGINS) if margins is None else margins

    def plan(mg):
        nw = {}
        for a in (A_RT133, A_RT134, A_RB):
            nw[a] = round(O[a] / MB * area * mg[a])
        nw[A_RB] += (-nw[A_RB]) % 16
        dg = (nw[A_RT133] * MB - O[A_RT133]) + (nw[A_RT134] * MB - O[A_RT134]) \
             + (nw[A_RB] * MB - O[A_RB]) - LEVEL_CUT
        D = math.ceil(dg / MB)
        D += D % 2                       # AllocateMemory: размер кратен 2 МБ
        return nw, D

    donors = [(A_SCR, SCR_MIN), (A_SND1, SND_MIN), (A_SND2, SND_MIN), (A_LOAD, LOAD_MIN)]
    if aggressive:
        donors += [(A_R2G, R2G_MIN), (A_G2G, G2G_MIN)]
    cap = sum((O[a] - m) // MB for a, m in donors)
    nw, D = plan(mg)
    note = ""
    gpu_room = GPU_MAX_MB - O[A_GPU] // MB   # ограничение игры: размер области <= 4 GiB (assert в AllocateVirtualMemoryAddressRange)
    capped = None
    if D > gpu_room:                         # GPU_MEMORY не должен превысить 4096 МБ
        mg1 = {a: 1.0 for a in mg}
        nw, D = plan(mg1); note = tr("margin_note")
        if D > gpu_room:
            area0 = area
            for pct in range(99, 0, -1):     # подгоняем рост бюджета под потолок
                area = 1.0 + (area0 - 1.0) * pct / 100
                nw, D = plan(mg1)
                if D <= gpu_room: break
            capped = pct
            note += tr("gpu_cap_note", GPU_MAX_MB, pct)
    if D - extra > cap:
        nw, D = plan({a: 1.0 for a in mg})
        note = tr("margin_note")
        if D - extra > cap:
            raise BudgetError(tr("budget_err", W, H, D, cap, "" if aggressive else tr("no_aggr")))
    new = dict(O)
    for a in (A_RT133, A_RB):
        new[a] = nw[a] * MB
    new[A_LVL] = O[A_LVL] - LEVEL_CUT
    # RT134 - «поглотитель»: суммарный прирост GPU-записей = D МБ ровно
    new[A_RT134] = O[A_RT134] + D * MB - (new[A_RT133] - O[A_RT133]) - (new[A_RB] - O[A_RB]) \
                   - (new[A_LVL] - O[A_LVL])
    new[A_GPU] = O[A_GPU] + D * MB
    cut_total = max(0, D - extra)        # сколько реально забираем у CPU (остальное покрывает расширенная direct-память)
    new[A_CPU] = O[A_CPU] - cut_total * MB
    rem = cut_total
    for a, m in donors:                  # целые МБ, по порядку
        cut = min(rem, (O[a] - m) // MB)
        new[a] = O[a] - cut * MB
        rem -= cut
    assert rem == 0
    total = (new[A_PRX] + new[A_CPU] + new[A_GPU]) // MB
    assert total == 4608 + D - cut_total and total % 2 == 0
    lines, rows = [], []
    order = [A_RT133, A_RT134, A_RB, A_LVL, A_GPU, A_CPU, A_SCR, A_SND1, A_SND2, A_LOAD, A_R2G, A_G2G]
    for a in order:
        if new[a] != O[a]:
            lines.append((a, (u32(new[a]) if new[a] < (1 << 32) else struct.pack('<Q', new[a]).hex())))
            rows.append((ORIG_BUDGET[a][0], O[a] / MB, new[a] / MB))
    info = dict(D=D, cap=cap, gpu_capped=capped, area=area, total=total, dmem_mb=total, expanded=(total != DMEM_BASE_MB), cut=cut_total,
                text=tr("info_text", D, cut_total, total, tr("info_exp") if total != 4608 else tr("info_orig"), note))
    return lines, rows, info


# ----------------------------------------------------------------------------------------
# Строки XML-патча
# ----------------------------------------------------------------------------------------
def build_lines(W, H, aggressive=False, frac=1.0, extra=0):
    R = (W / H) / (16 / 9)
    cw = 1280 * R
    L = []

    def c(t): L.append(("c", t))
    def add(a, v): L.append(("l", (a, v)))

    # 1. Бюджеты памяти (+ размер direct-памяти)
    bl, rows, info = calc_budget(W, H, aggressive, frac, None, extra)
    if bl:
        c(tr("c_budget", info["text"]))
        for a, v in bl:
            c(tr("c_row", ORIG_BUDGET[a][0], ORIG_BUDGET[a][1] / MB, int.from_bytes(bytes.fromhex(v), 'little') / MB))
            add(a, v)
        if info["total"] != 4608:
            c(tr("c_dmem_const", info["total"]))
            add(0x6f5e46, struct.pack('<Q', info["total"] * MB).hex())
            c(tr("c_dmem_warn", info["total"]))
    # 2. Разрешение
    c(tr("c_res", W, H))
    add(0x156bfbc, u32(W)); add(0x156bfdc, u32(H))
    # 3. Соотношение сторон
    if not is_169(W, H):
        c(tr("c_aspect", W, H))
        add(0xeb091b, f32(W / H)); add(0xeb0594, f32(W / H))
    if is_169(W, H):
        c(tr("c_169"))
        return L, rows, info
    c(tr("c_clip", R))
    for a, v in [(0xeb0673, "c5fa590501000000c3" + f32(R)), (0xeb05f1, "c5fa5985e0fdffffe975000000"),
                 (0x69234c, "e8a0e281000f1f00"), (0xeb0663, "c5fa5945f0e906000000"),
                 (0x69374b, "e813cf8100"), (0xeb0691, "c5fa5985a0feffffe9d5ffffff"),
                 (0x6965a4, "e8e8a081000f1f00")]:
        add(a, v)
    c(tr("c_cam"))
    add(0xe223c7, f32(1 / R)); add(0xe252ac, "17d1ffff")
    # --- UI: от базовых к зависимым ---
    c(tr("c_ui"))
    add(0x1572444, f32(2 / cw)); add(0x157244c, f32(-1 / R))
    c(tr("c_dev"))
    for x in (0x156ced0, 0x156cee0, 0x156cf20):
        add(x, f32(2 / cw)); add(x + 8, f32(-1 / R))
    c(tr("c_font"))
    add(0x1586bb8, f32(cw)); add(0x1586bc4, f32(cw))
    c(tr("c_cross"))          # использует константу шрифта
    add(0xa250dc, "d81ab600")
    c(tr("c_proj"))
    add(0x1586f80, f32(R))
    c(tr("c_icon"))
    SITE, BACK, CAVE, K640 = 0xead8c1, 0xead8cd, 0x109fc61, 0x156bc3c
    rel = lambda nxt, tgt: struct.pack('<i', tgt - nxt).hex()
    add(SITE, "e9" + rel(SITE + 5, CAVE) + "90" * 7)
    add(CAVE, "c5d2592d" + rel(CAVE + 8, CAVE + 25) + "c5d258ee" + "c5d2592d" + rel(CAVE + 20, K640)
        + "e9" + rel(CAVE + 25, BACK) + f32(R))
    c(tr("c_treasure"))
    # камера сцены сокровищ: горизонтальный fov 60° -> вертикальный обзор как в 16:9
    fov = 2 * math.atan(R * math.tan(1.0470927953720093 / 2))
    add(0x14c9890, f32(fov)); add(0x14c9928, f32(fov))
    return L, rows, info


def lines_to_text(L):
    out = []
    for k, v in L:
        if k == "c":
            out.append("      <!-- %s -->" % v)
        else:
            out.append('      <Line Type="bytes" Address="0x%08x" Value="%s"/>' % v)
    return "\n".join(out)


RATIOS = [("4:3", 4 / 3), ("5:4", 5 / 4), ("3:2", 3 / 2), ("16:10", 16 / 10), ("16:9", 16 / 9),
          ("21:9", 21 / 9), ("32:9", 32 / 9)]


def ratio_label(W, H):
    """Маркетинговое название соотношения сторон: 2560x1080 -> 21:9, 3440x1440 -> 21:9, 3840x1080 -> 32:9."""
    ar = W / H
    name, val = min(RATIOS, key=lambda r: abs(ar / r[1] - 1))
    if abs(ar / val - 1) <= 0.035:
        return name
    g = math.gcd(W, H); a, b = W // g, H // g
    return "%d:%d" % (a, b) if max(a, b) <= 50 else "%.2f:1" % ar


def patch_name(W, H):
    return "Resolution Patch %dx%d (%s)" % (W, H, ratio_label(W, H))


def make_metadata(W, H, aggressive, frac=1.0, extra=0):
    L, rows, info = build_lines(W, H, aggressive, frac, extra)
    R = (W / H) / (16 / 9)
    # Описание патча - всегда на английском, простым языком (не локализуется)
    note = "Resolution %dx%d." % (W, H)
    if info.get("expanded"):
        need = dmem_user_extra(info)
        note += " Allocate +%d MB dmem in shadPS4." % need
    if not is_169(W, H):
        note += " WARNING: introduces a cutscenes stretch, for the fix search for 'sanyagames227/tlou_r_shadps4_ultrawide' on GitHub."
    note = note.replace('&', '&amp;').replace('"', '&quot;').replace('<', '&lt;')
    return ('    <Metadata Title="The Last of Us Remastered" Name="%s" Note="%s" Author="%s" '
            'PatchVer="1.0" AppVer="01.11" AppElf="eboot.bin" isEnabled="true">\n    <PatchList>\n%s\n'
            '    </PatchList>\n    </Metadata>\n' % (patch_name(W, H), note, AUTHOR, lines_to_text(L))), rows, info


def build_xml(W, H, base_text=None, aggressive=False, frac=1.0, extra=0, disable_old=True):
    meta, rows, info = make_metadata(W, H, aggressive, frac, extra)
    if base_text:
        x = re.sub(r'[ \t]*<Metadata[^>]*Author="%s"[^>]*>.*?</Metadata>[ \t]*\r?\n?' % AUTHOR, '', base_text, flags=re.S)

        def off(m):  # выключаем прежние разрешающие секции (они пишут в те же адреса), если disable_old
            blk = m.group(0)
            if not disable_old:
                return blk
            if '0x0156bfbc' in blk.lower() or '0x156bfbc' in blk.lower():
                blk = re.sub(r'isEnabled="true"', 'isEnabled="false"', blk, count=1)
            return blk
        x = re.sub(r'<Metadata\b.*?</Metadata>', off, x, flags=re.S)
        if '</Patch>' not in x:
            raise ValueError(tr("err_nopatch"))
        x = x.replace('</Patch>', meta + '</Patch>')
    else:
        ids = "\n".join("        <ID>%s</ID>" % t for t in TITLE_IDS)
        x = '<?xml version="1.0"?>\n<Patch>\n    <TitleID>\n%s\n    </TitleID>\n%s</Patch>\n' % (ids, meta)
    return x, rows, info


# ----------------------------------------------------------------------------------------
# Актуальный TheLastOfUsRemastered.xml с GitHub: дополняем его своим патчем вместо генерации с нуля
# ----------------------------------------------------------------------------------------
GH_RAW_URL = "https://github.com/shadps4-emu/ps4_cheats/raw/refs/heads/main/PATCHES/TheLastOfUsRemastered.xml"
GH_FILE = "TheLastOfUsRemastered.xml"
BLOCK_RE = re.compile(r'<Metadata\b[^>]*>.*?</Metadata>', re.S)
ADDR_RES = 0x156bfbc                 # адрес ширины экрана: по нему узнаём «разрешающие» патчи


class GhError(Exception):
    pass


def fetch_github_xml(timeout=15):
    import urllib.request
    req = urllib.request.Request(GH_RAW_URL, headers={"User-Agent": "tlou-ultrawide-patcher"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = r.read(8 * MB)
        text = data.decode("utf-8-sig")
    except Exception as e:
        raise GhError(str(getattr(e, "reason", None) or e))
    if "</Patch>" not in text or not any(t in text for t in TITLE_IDS):
        raise GhError(tr("gh_bad"))
    return text


def _attrs(tag):
    return dict(re.findall(r'([\w:]+)\s*=\s*"([^"]*)"', tag))


def _open_tag(block):
    return re.match(r'<Metadata\b[^>]*>', block).group(0)


def _pairs(block):
    """Множество (адрес, значение) всех <Line> блока - по нему сравниваем патчи."""
    out = set()
    for t in re.findall(r'<Line\b[^>]*>', block):
        a = _attrs(t)
        try:
            out.add((int(a["Address"], 16), a["Value"].lower()))
        except (KeyError, ValueError):
            pass
    return out


def merge_patch(base, block, W, H, disable_old=True):
    """Добавляет/обновляет наш патч в тексте XML. Возвращает (текст|None, действие, подробности).
    Действия: added - дописан в конец; updated - в файле был неполный/старый, заменён целиком;
    same - уже есть и совпадает; conflict - в файле другой набор строк, не трогаем."""
    nl = "\r\n" if "\r\n" in base else "\n"
    name, legacy = patch_name(W, H), "Ultrawide %dx%d" % (W, H)
    new_pairs = _pairs(block)

    def is_ours(blk):
        at = _attrs(_open_tag(blk))
        return at.get("AppVer") == "01.11" and (at.get("Name") == name or
                                                (at.get("Name") == legacy and at.get("Author") == AUTHOR))
    cur = next((m for m in BLOCK_RE.finditer(base) if is_ours(m.group(0))), None)
    d = dict(old=0, new=len(new_pairs), disabled=0)
    if cur:
        old_pairs = _pairs(cur.group(0)); d["old"] = len(old_pairs)
        renamed = _attrs(_open_tag(cur.group(0))).get("Name") != name
        if old_pairs == new_pairs and not renamed:
            return None, "same", d
        if not (old_pairs < new_pairs or (old_pairs == new_pairs and renamed)):
            return None, "conflict", d           # на GitHub есть строки, которых нет у нас, - не затираем
    cnt = [0]

    def off(m):                                 # выключаем другие «разрешающие» патчи: они пишут в те же адреса
        blk = m.group(0); at = _attrs(_open_tag(blk))
        if is_ours(blk) or at.get("AppVer") != "01.11" or at.get("isEnabled", "").lower() != "true": return blk
        if not any(a == ADDR_RES for a, _ in _pairs(blk)): return blk
        cnt[0] += 1
        return re.sub(r'isEnabled="true"', 'isEnabled="false"', blk, count=1, flags=re.I)
    text = BLOCK_RE.sub(off, base) if disable_old else base
    d["disabled"] = cnt[0]
    body = block.strip("\r\n").replace("\n", nl)
    cur = next((m for m in BLOCK_RE.finditer(text) if is_ours(m.group(0))), None)
    if cur:                                      # заменяем на месте (отступ перед блоком остаётся прежним)
        return text[:cur.start()] + body.lstrip() + text[cur.end():], "updated", d
    i = text.rfind("</Patch>")
    pre = "" if i == 0 or text[i - 1] in "\r\n" else nl
    return text[:i] + pre + body + nl + text[i:], "added", d


def build_github_xml(W, H, aggressive=False, frac=1.0, extra=0, disable_old=True, log=print, fetch=None):
    """Скачивает файл с GitHub и вносит патч. Возвращает dict(status, xml, block, rows, info, text).
    status: added | updated | same | conflict | offline. xml - готовый файл (только added/updated)."""
    block, rows, info = make_metadata(W, H, aggressive, frac, extra)
    res = dict(status="offline", xml=None, block=block, rows=rows, info=info, text="")
    name = patch_name(W, H)
    log(tr("gh_fetch"))
    try:
        base = (fetch or fetch_github_xml)()
    except GhError as e:
        res["text"] = tr("gh_fail", e); return res
    log(tr("gh_ok", len(base.encode("utf-8")), len(BLOCK_RE.findall(base))))
    text, act, d = merge_patch(base, block, W, H, disable_old)
    res["status"], res["xml"] = act, text
    if d["disabled"]: log(tr("gh_off", d["disabled"]))
    res["text"] = {"added": lambda: tr("gh_added", name),
                   "updated": lambda: tr("gh_updated", name, d["old"], d["new"]),
                   "same": lambda: tr("gh_same", name),
                   "conflict": lambda: tr("gh_conflict", name, d["old"], d["new"])}[act]()
    return res


# ----------------------------------------------------------------------------------------
# Проверка eboot.bin
# ----------------------------------------------------------------------------------------
def check_eboot(path):
    d = open(path, 'rb').read()
    n = struct.unpack('<H', d[0x18:0x1a])[0]
    eo = 0x20 + 32 * n
    phoff, = struct.unpack('<Q', d[eo + 0x20:eo + 0x28])
    phnum, = struct.unpack('<H', d[eo + 0x38:eo + 0x3a])
    phent, = struct.unpack('<H', d[eo + 0x36:eo + 0x38])
    ph = [struct.unpack('<IIQQQQQQ', d[eo + phoff + i * phent:eo + phoff + i * phent + 56]) for i in range(phnum)]
    ss = {}
    for i in range(n):
        f, off, csz, msz = struct.unpack('<QQQQ', d[0x20 + 32 * i:0x20 + 32 * i + 32])
        if f & 0x800: ss[f >> 20] = off
    segs = [(p[3], p[5], ss[i]) for i, p in enumerate(ph) if i in ss and p[0] in (1, 0x61000010)]

    def rd(a, k):
        v = a - 0x400000
        for va, fsz, fo in segs:
            if va <= v < va + fsz: return d[fo + v - va:fo + v - va + k]
        raise KeyError(hex(a))
    bad = []
    for a, h in ORIG_BYTES.items():
        if rd(a, len(h) // 2).hex() != h: bad.append("0x%x" % a)
    for a, (nm, v) in ORIG_BUDGET.items():
        if struct.unpack('<Q', rd(a, 8))[0] != v: bad.append("0x%x" % a)
    return bad


# ----------------------------------------------------------------------------------------
# SPIR-V: патч шейдера видео (YUV->RGB). Работает и с оригиналом, и с уже пропатченным (любое R).
# ----------------------------------------------------------------------------------------
OP_FLOAT, OP_BOOL, OP_CONST, OP_CCOMP, OP_FUNC, OP_FMUL, OP_FADD = 22, 20, 43, 44, 54, 133, 129
OP_CCONSTRUCT, OP_SAMPLE, OP_IMGWRITE, OP_SELECT, OP_AND, OP_FGE, OP_FLE = 80, 88, 99, 169, 167, 190, 188


def _parse(w):
    i, out = 5, []
    while i < len(w):
        wc = w[i] >> 16
        if wc == 0: raise ValueError(tr("spv_bad"))
        out.append([i, w[i] & 0xffff, wc]); i += wc
    return out


def _fbits(x): return struct.unpack('<I', struct.pack('<f', x))[0]


def patch_spv(data, R):
    """Возвращает (новые байты, описание). Для R<=1 маска не срабатывает (кадр обрезается по краям)."""
    if len(data) % 4 or struct.unpack('<I', data[:4])[0] != 0x07230203:
        raise ValueError(tr("spv_not"))
    w = list(struct.unpack('<%dI' % (len(data) // 4), data))
    ins = _parse(w)
    defs = {}   # id результата -> индекс инструкции
    for k, (i, op, wc) in enumerate(ins):
        if 19 <= op <= 39:                       # OpType*: [hdr, id, ...]
            defs[w[i + 1]] = k
        elif op not in (62, OP_IMGWRITE, 247, 248, 249, 250, 251, 253, 56, 14, 15, 16, 17, 5, 6, 71, 72, 3, 4, 7, 8) and wc >= 3:
            defs[w[i + 2]] = k                   # остальные: [hdr, type, id, ...]
    # --- найти координаты семплирования: CompositeConstruct(vec2, u, v) -> ImageSample
    cons = []
    for k, (i, op, wc) in enumerate(ins):
        if op == OP_SAMPLE:
            kc = defs.get(w[i + 4])
            if kc is not None and ins[kc][1] == OP_CCONSTRUCT and ins[kc][2] == 5 and ins[kc] not in cons:
                cons.append(ins[kc])
    if not cons:
        raise ValueError(tr("spv_uv"))
    u0 = w[cons[0][0] + 3]
    if any(w[c[0] + 3] != u0 for c in cons):
        raise ValueError(tr("spv_uvs"))
    ku = defs[u0]
    # --- уже пропатчен? u' = FAdd(FMul(u, c1), c2)
    if ins[ku][1] == OP_FADD:
        i = ins[ku][0]
        fm = defs.get(w[i + 3]); c2 = defs.get(w[i + 4])
        if fm is not None and c2 is not None and ins[fm][1] == OP_FMUL and ins[c2][1] == OP_CONST:
            c1 = defs.get(w[ins[fm][0] + 4])
            if c1 is not None and ins[c1][1] == OP_CONST:
                old1 = struct.unpack('<f', struct.pack('<I', w[ins[c1][0] + 3]))[0]
                old2 = struct.unpack('<f', struct.pack('<I', w[ins[c2][0] + 3]))[0]
                w[ins[c1][0] + 3] = _fbits(R); w[ins[c2][0] + 3] = _fbits((1 - R) / 2)
                return struct.pack('<%dI' % len(w), *w), \
                    tr("spv_already", old1, old2, R, (1 - R) / 2)
    # --- оригинал: вставка кода
    bound = w[3]
    ids = iter(range(bound, bound + 32)); used = []

    def new():
        v = next(ids); used.append(v); return v
    # типы/константы
    f32t = next((w[i + 1] for i, op, wc in ins if op == OP_FLOAT and w[i + 2] == 32), None)
    if f32t is None: raise ValueError(tr("spv_nof32"))
    boolt = next((w[i + 1] for i, op, wc in ins if op == OP_BOOL), None)
    globs = []                                   # новые глобальные инструкции
    if boolt is None:
        boolt = new(); globs.append([0x00020000 | OP_BOOL, boolt])

    def find_const(val):
        for i, op, wc in ins:
            if op == OP_CONST and w[i + 1] == f32t and wc == 4 and w[i + 3] == _fbits(val): return w[i + 2]
        return None

    def const(val):
        c = find_const(val)
        if c is None:
            c = new(); globs.append([0x00040000 | OP_CONST, f32t, c, _fbits(val)])
        return c
    cR, cB, c0, c1 = const(R), const(( 1 - R) / 2), const(0.0), const(1.0)
    # ImageWrite
    kw = next((k for k, (i, op, wc) in enumerate(ins) if op == OP_IMGWRITE), None)
    if kw is None: raise ValueError(tr("spv_noiw"))
    iw = ins[kw][0]; texel = w[iw + 3]
    kt = defs.get(texel)
    if kt is None: raise ValueError(tr("spv_notex"))
    v4t = w[ins[kt][0] + 1]
    zero4 = None
    for i, op, wc in ins:
        if op == OP_CCOMP and w[i + 1] == v4t and all(w[j] == c0 for j in range(i + 3, i + wc)): zero4 = w[i + 2]
    if zero4 is None:
        zero4 = new()
        globs.append([(3 + 4) << 16 | OP_CCOMP, v4t, zero4, c0, c0, c0, c0])
    # тело
    X, U1 = new(), new()
    ge, le, an, sel = new(), new(), new(), new()
    # --- сборка
    out = w[:5]
    first_func = next(i for i, op, wc in ins if op == OP_FUNC)
    ku_i = ins[ku][0]; ku_end = ku_i + ins[ku][2]
    cons_pos = {c[0] for c in cons}
    j = 5
    res = list(w[:5])
    for i, op, wc in ins:
        body = list(w[i:i + wc])
        if i == first_func:
            for g in globs: res += g
        if i in cons_pos:
            body[3] = U1
        if i == iw:
            res += [(5 << 16) | OP_FGE, boolt, ge, U1, c0]
            res += [(5 << 16) | OP_FLE, boolt, le, U1, c1]
            res += [(5 << 16) | OP_AND, boolt, an, ge, le]
            res += [(6 << 16) | OP_SELECT, v4t, sel, an, texel, zero4]
            body[3] = sel
        res += body
        if i == ku_i:
            res += [(5 << 16) | OP_FMUL, f32t, X, u0, cR]
            res += [(5 << 16) | OP_FADD, f32t, U1, X, cB]
    res[3] = max(used) + 1 if used else bound
    return struct.pack('<%dI' % len(res), *res), \
        tr("spv_orig", R, (1 - R) / 2)


# ----------------------------------------------------------------------------------------
# Кэш шейдеров shadPS4: заглушка на время, пока эмулятор при включённом кэше берёт стоковый шейдер
# вместо user/shader/patch. Ищем шейдер видео в папке/ZIP кэша по размеру + SHA-256 и патчим на месте.
# ----------------------------------------------------------------------------------------
SPV_ORIG_SIZE = 4144                     # размер оригинального шейдера видео (cs_0x00000000562c4394_0.spv)
SPV_ORIG_SHA256 = "0dc367b61caecdd39e35a827576323b28fa129da38e3774baff9ec131b599337"
SPV_PATCHED_MAX_EXTRA = 256              # пропатченный шейдер длиннее оригинала максимум на столько байт
SPV_CANON_R = 1.5                        # «пробное» R для опознания пропатченной версии (любого R)
SPV_CANON_SHA256 = "7006771ef698104827aaeae22e10a0566fdc9655964270c2b2ae23480cbd9485"           # sha256(patch_spv(оригинал, SPV_CANON_R))


class CacheError(Exception):
    pass


def _size_ok(n):
    """Дешёвый предфильтр: считаем хэш только у файлов подходящего размера."""
    return n == SPV_ORIG_SIZE or (SPV_ORIG_SIZE < n <= SPV_ORIG_SIZE + SPV_PATCHED_MAX_EXTRA and n % 4 == 0)


def spv_kind(data):
    """'orig' - стоковый шейдер видео, 'patched' - он же, уже пропатченный нами (под любое R), иначе None."""
    n = len(data)
    if n == SPV_ORIG_SIZE:
        return "orig" if hashlib.sha256(data).hexdigest() == SPV_ORIG_SHA256 else None
    if _size_ok(n):
        try:
            probe, _ = patch_spv(data, SPV_CANON_R)
        except Exception:
            return None
        return "patched" if hashlib.sha256(probe).hexdigest() == SPV_CANON_SHA256 else None
    return None


def _backup_original(backup_dir, label, data, n):
    os.makedirs(backup_dir, exist_ok=True)
    base = re.sub(r'[^\w.\-]+', '_', os.path.basename(label.replace('\\', '/'))) or "shader.spv"
    stem, ext = os.path.splitext(base)
    p = os.path.join(backup_dir, "%s_%s_%d%s" % (stem, time.strftime("%Y%m%d-%H%M%S"), n, ext or ".spv"))
    with open(p, 'wb') as f: f.write(data)
    return p


def _rewrite_zip(path, repl):
    """Пересобирает ZIP, подменяя записи repl {индекс: байты}. Сначала во временный файл, проверка, затем атомарная замена."""
    tmp = path + ".patching"
    try:
        with zipfile.ZipFile(path) as zin, zipfile.ZipFile(tmp, 'w', allowZip64=True) as zout:
            zout.comment = zin.comment
            for i, inf in enumerate(zin.infolist()):
                ni = copy.copy(inf)
                if i in repl:
                    zout.writestr(ni, repl[i], compress_type=inf.compress_type)
                elif inf.is_dir():
                    zout.writestr(ni, b"")
                else:
                    with zin.open(inf) as src, zout.open(ni, 'w', force_zip64=inf.file_size >= (1 << 31) - 1) as dst:
                        shutil.copyfileobj(src, dst, 1 << 20)
        with zipfile.ZipFile(tmp) as chk:               # проверяем результат до замены оригинала
            names = chk.infolist()
            for i, data in repl.items():
                if chk.read(names[i]) != data: raise CacheError(tr("cache_err_verify"))
        os.replace(tmp, path)
    except CacheError:
        raise
    except OSError as e:
        raise CacheError(tr("cache_err_write", e))
    finally:
        if os.path.exists(tmp):
            try: os.remove(tmp)
            except OSError: pass


def patch_cache(path, W, H, backup_dir, log=print):
    """Находит шейдер видео в кэше (папка или ZIP) и патчит его под W×H.
    Возвращает dict(status=patched|reset|same|skip169|notfound, changed=N, text=итоговая строка)."""
    path = os.path.abspath(os.path.expanduser(path.strip().strip('"')))
    if not os.path.exists(path):
        raise CacheError(tr("cache_err_path", path))
    is_zip = os.path.isfile(path)
    if is_zip and not zipfile.is_zipfile(path):
        raise CacheError(tr("cache_err_type", path))
    neutral = is_169(W, H)                               # для 16:9 шейдер не нужен: максимум - сбросить ранее наложенный патч
    R = 1.0 if neutral else (W / H) / (16 / 9)
    log(tr("cache_scan", path))

    scanned = cands = 0
    hits = []                                            # (ключ, вид, байты)
    if is_zip:
        zf = zipfile.ZipFile(path)
        try:
            infos = zf.infolist()
            for i, inf in enumerate(infos):
                if inf.is_dir(): continue
                scanned += 1
                if not _size_ok(inf.file_size): continue
                cands += 1
                data = zf.read(inf); k = spv_kind(data)
                if k: hits.append((i, k, data))
            label = lambda key: "%s → %s" % (os.path.basename(path), infos[key].filename)
        finally:
            zf.close()
    else:
        for dp, _, fns in os.walk(path):
            for fn in fns:
                fp = os.path.join(dp, fn)
                try: size = os.path.getsize(fp)
                except OSError: continue
                scanned += 1
                if not _size_ok(size): continue
                cands += 1
                try:
                    with open(fp, 'rb') as f: data = f.read()
                except OSError: continue
                k = spv_kind(data)
                if k: hits.append((fp, k, data))
        label = lambda key: os.path.relpath(key, path)
    log(tr("cache_stat", scanned, cands, len(hits)))
    for key, k, _ in hits:
        log(tr("cache_hit_orig" if k == "orig" else "cache_hit_patched", label(key)))

    if not hits:
        if neutral:
            return dict(status="skip169", changed=0, text=tr("cache_skip169"))
        return dict(status="notfound", changed=0, text=tr("cache_nf_log"))

    plan = []                                            # что реально меняем
    for key, k, data in hits:
        if neutral and k == "orig": continue
        new, _ = patch_spv(data, R)
        if new != data: plan.append((key, k, data, new))
    if not plan:
        return dict(status="skip169" if neutral else "same", changed=0,
                    text=tr("cache_skip169") if neutral else tr("cache_same", W, H))

    for n, (key, k, data, _) in enumerate(plan):         # копия стокового шейдера (пропатченные не копируем)
        if k == "orig":
            log(tr("cache_backup", _backup_original(backup_dir, label(key), data, n)))
    try:
        if is_zip:
            log(tr("cache_zip"))
            _rewrite_zip(path, {key: new for key, _, _, new in plan})
        else:
            for key, _, _, new in plan:
                tmp = key + ".patching"
                try:
                    with open(tmp, 'wb') as f: f.write(new)
                    os.replace(tmp, key)
                finally:
                    if os.path.exists(tmp):
                        try: os.remove(tmp)
                        except OSError: pass
    except OSError as e:
        raise CacheError(tr("cache_err_write", e))
    if neutral:
        return dict(status="reset", changed=len(plan), text=tr("cache_reset", len(plan)))
    return dict(status="patched", changed=len(plan), text=tr("cache_done", len(plan), W, H))


# ----------------------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------------------
def cli(a):
    W, H = a.cli
    if a.eboot:
        bad = check_eboot(a.eboot)
        print(tr("eboot_ok") if not bad else tr("eboot_bad", ", ".join(bad)))
    if a.xml and a.xml[0].lower() == "github":
        gr = build_github_xml(W, H, a.aggressive, a.frac / 100, resolve_extra('full' if a.dmem else 'custom', a.extra),
                              not a.keep_old, print)
        print(gr["text"])
        if gr["xml"] is not None:
            with open(a.xml[1], 'w', encoding='utf-8', newline='') as f: f.write(gr["xml"])
            print("XML:", a.xml[1])
        elif gr["status"] in ("offline", "conflict"):
            bp = a.xml[1] + ".block.txt"
            open(bp, 'w', encoding='utf-8').write(gr["block"])
            print(tr("gh_man_log", bp)); print(tr("gh_man_msg", bp))
        print("dmem:", dmem_note(gr["info"]))
    elif a.xml:
        base = open(a.xml[0], encoding='utf-8').read() if os.path.exists(a.xml[0]) else None
        x, rows, info = build_xml(W, H, base, a.aggressive, a.frac / 100, resolve_extra('full' if a.dmem else 'custom', a.extra),
                                  not a.keep_old)
        open(a.xml[1], 'w', encoding='utf-8').write(x)
        print("XML:", a.xml[1], "-", info["text"])
        for r in rows: print("   %-26s %9.2f -> %9.2f МБ" % r)
        print("dmem:", dmem_note(info))
    if a.spv and is_169(W, H):
        print("SPV:", tr("spv_skip169"))
    elif a.spv:
        R = (W / H) / (16 / 9)
        out, msg = patch_spv(open(a.spv[0], 'rb').read(), R)
        open(a.spv[1], 'wb').write(out); print("SPV:", a.spv[1], "-", msg)
        if not a.cache: print(tr("spv_cache"))
    if a.cache:
        try:
            res = patch_cache(a.cache, W, H, os.path.join(out_root(), "backup"), print)
        except CacheError as e:
            print(tr("err_prefix", e)); return 1
        print(res["text"])
        if res["status"] == "notfound":
            print(); print(tr("cache_nf_msg")); return 3
    return 0


# ----------------------------------------------------------------------------------------
# Автоматические пути результата (поля «Сохранить …» в GUI не нужны)
# ----------------------------------------------------------------------------------------
XML_DIR = os.path.join("user", "patches", "shadPS4")


def xml_rel(W, H):
    return os.path.join(XML_DIR, "TheLastofUsRemastered_%dx%d.xml" % (W, H))
SPV_REL = os.path.join("user", "shader", "patch")


def xml_gh_rel(): return os.path.join(XML_DIR, GH_FILE)


def block_rel(W, H): return "ManualInsert_%dx%d.txt" % (W, H)      # вне user/, чтобы не попасть в папку патчей эмулятора


def out_root(*srcs):
    """Папка ShadPS4 рядом с exe (или python-файлом); внутри - структура shadPS4."""
    if getattr(sys, 'frozen', False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, "ShadPS4")


def out_xml_path(root, W, H):
    return os.path.join(root, xml_rel(W, H))


def out_spv_path(spv_in, root):
    """<ShadPS4>/user/shader/patch/cs_0x...spv"""
    m = re.search(r'cs_0x[0-9a-fA-F]+_\d+\.spv', os.path.basename(spv_in))
    return os.path.join(root, SPV_REL, m.group(0) if m else os.path.basename(spv_in))



# ----------------------------------------------------------------------------------------
# GUI v5 — переработан полностью для максимальной интуитивности (PyQt5, Fusion, тёмная тема).
#
# Ключевые изменения UX:
#  • Все необязательные поля скрыты за секцией «Дополнительно» — новичок их не видит.
#  • Шейдер: чекбокс с автоматически подставленным именем файла (cs_0x00000000562c4394_0.spv),
#    юзер просто указывает папку (или ZIP кэша), не ищет файл вручную.
#  • Кнопка «Создать патч» переименована и содержит tooltip с полным списком того, что она делает.
#  • Бюджет памяти: два понятных варианта с иконкой-подсказкой, «Почему это нужно?» раскрывается.
#  • Итоговые окна (done/warn) переписаны — чёткий список шагов «что делать дальше».
#  • Поле eboot.bin полностью убрано из основного вида (только в «Дополнительно»).
#  • Лейблы Optional помечены серым текстом «(необязательно)».
#  • Статус-строка внизу показывает, что именно будет создано при нажатии кнопки.
# ----------------------------------------------------------------------------------------
SPV_CANON_NAME = "cs_0x00000000562c4394_0.spv"   # имя шейдера видео


def gui():
    from PyQt5 import QtWidgets as Q, QtGui, QtCore
    app = Q.QApplication(sys.argv)
    app.setStyle("Fusion")

    BLUE, BLUE_H, BLUE_D = "#0070d1", "#1a85e6", "#00439c"
    pal = QtGui.QPalette()
    C = QtGui.QColor
    for role, col in (
        (QtGui.QPalette.Window, "#161a22"), (QtGui.QPalette.Base, "#0f131a"),
        (QtGui.QPalette.AlternateBase, "#141922"), (QtGui.QPalette.Button, "#232a36"),
        (QtGui.QPalette.ButtonText, "#e6ebf2"), (QtGui.QPalette.Highlight, BLUE),
        (QtGui.QPalette.HighlightedText, "#ffffff"), (QtGui.QPalette.Text, "#e6ebf2"),
        (QtGui.QPalette.WindowText, "#e6ebf2"), (QtGui.QPalette.ToolTipBase, "#232a36"),
        (QtGui.QPalette.ToolTipText, "#e6ebf2"), (QtGui.QPalette.BrightText, "#ffffff"),
        (QtGui.QPalette.Link, "#4da3ff"), (QtGui.QPalette.Light, "#33405a"),
        (QtGui.QPalette.Midlight, "#2a3447"), (QtGui.QPalette.Mid, "#1c2330"),
        (QtGui.QPalette.Dark, "#0b0e14"), (QtGui.QPalette.Shadow, "#05070b"),
    ):
        pal.setColor(role, C(col))
    if hasattr(QtGui.QPalette, "PlaceholderText"):
        pal.setColor(QtGui.QPalette.PlaceholderText, C("#7a8599"))
    for role in (QtGui.QPalette.Text, QtGui.QPalette.ButtonText, QtGui.QPalette.WindowText):
        pal.setColor(QtGui.QPalette.Disabled, role, C("#667086"))
    pal.setColor(QtGui.QPalette.Disabled, QtGui.QPalette.Highlight, C("#2b3447"))
    app.setPalette(pal)

    app.setStyleSheet("""
        QGroupBox {
            font-weight: 600; border: 1px solid #2b3441; border-radius: 6px;
            margin-top: 12px; padding: 10px 8px 6px 8px; background: #1a1f29;
        }
        QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 5px; color: #4da3ff; }
        QLabel#title  { font-size: 19px; font-weight: 700; color: #f2f6fc; }
        QLabel#subtitle { color: #8793a8; }
        QLabel#hint { color: #6a7a94; font-style: italic; }
        QLabel#optional_tag { color: #56657a; font-size: 10px; }
        QLabel#chip { background: #10294a; border: 1px solid #1d4f8a; border-radius: 9px;
                      padding: 3px 10px; color: #9fcdff; }
        QLabel#chip[warn="true"] { background: #3d3416; border-color: #7a6422; color: #f0d58a; }
        QPushButton#primary {
            background: %(b)s; color: #ffffff; font-weight: 700; font-size: 14px;
            padding: 10px 30px; border: 1px solid %(bd)s; border-radius: 4px;
        }
        QPushButton#primary:hover { background: %(bh)s; }
        QPushButton#primary:disabled { background: #1d2a40; color: #6f7d96; border-color: #1d2a40; }
        QPushButton#secondary {
            background: #232a36; color: #c8d4e6; border: 1px solid #2e3d52;
            border-radius: 4px; padding: 5px 12px;
        }
        QPushButton#secondary:hover { background: #2e3d52; }
        QFrame#dmem { border: 1px solid #1d4f8a; border-radius: 8px; background: #0f2442; }
        QFrame#dmem[state="warn"] { border-color: #7a6422; background: #2f2b17; }
        QFrame#dmem[state="err"]  { border-color: #8b2222; background: #2a1414; }
        QLabel#dmbig { font-size: 24px; font-weight: 700; color: #66b2ff; }
        QFrame#dmem[state="warn"] QLabel#dmbig { color: #f3c75a; }
        QFrame#dmem[state="err"]  QLabel#dmbig { color: #f07070; }
        QLabel#dmhex { color: #93a0b6; font-family: Consolas,Menlo,monospace; }
        QPlainTextEdit { font-family: Consolas,Menlo,monospace; font-size: 11px; }
        QLabel#step_title { font-weight: 700; color: #4da3ff; }
        QFrame#statusbar { background: #111722; border-top: 1px solid #2b3441; }
        QLabel#statuslbl { color: #8799b6; font-size: 11px; padding: 4px 8px; }
        QLabel#statuslbl[active="true"] { color: #a3c8ff; }
        QToolButton#helpbtn { border: none; color: #4da3ff; font-weight: 700;
                              background: transparent; padding: 0 3px; font-size: 12px; }
        QToolButton#helpbtn:hover { color: #80c0ff; }
    """ % dict(b=BLUE, bh=BLUE_H, bd=BLUE_D))

    # -----------------------------------------------------------------------
    # Вспомогательные виджеты
    # -----------------------------------------------------------------------
    def mk_label(text, obj=None, wrap=False):
        lb = Q.QLabel(text)
        if obj: lb.setObjectName(obj)
        if wrap: lb.setWordWrap(True)
        return lb

    def help_btn(tip):
        """Маленькая кнопка «?» с всплывающей подсказкой."""
        b = Q.QToolButton()
        b.setObjectName("helpbtn")
        b.setText("?")
        b.setToolTip(tip)
        b.setToolTipDuration(10000)
        b.clicked.connect(lambda: Q.QMessageBox.information(None, tr("help_title"), tip))
        return b

    class FileRow(Q.QWidget):
        """Строка выбора файла: лейбл + поле + кнопка Browse."""
        def __init__(s, label, flt, placeholder="", optional=False):
            super().__init__()
            h = Q.QHBoxLayout(s); h.setContentsMargins(0, 0, 0, 0); h.setSpacing(6)
            lbl_w = Q.QWidget(); lbl_h = Q.QHBoxLayout(lbl_w); lbl_h.setContentsMargins(0,0,0,0); lbl_h.setSpacing(2)
            lbl = Q.QLabel(label); lbl.setMinimumWidth(105)
            lbl_h.addWidget(lbl)
            if optional:
                opt = mk_label(tr("opt_tag"), "optional_tag"); lbl_h.addWidget(opt)
            lbl_h.addStretch(1)
            s.edit = Q.QLineEdit(); s.edit.setPlaceholderText(placeholder); s.edit.setClearButtonEnabled(True)
            b = Q.QPushButton(tr("g_browse")); b.setObjectName("secondary")
            h.addWidget(lbl_w); h.addWidget(s.edit, 1); h.addWidget(b)
            s.flt = flt
            b.clicked.connect(s.pick)
        def pick(s):
            f = Q.QFileDialog.getOpenFileName(s, s.edit.placeholderText(), s.edit.text(), s.flt)[0]
            if f: s.edit.setText(f)
        def text(s): return s.edit.text().strip()

    class CacheRow(Q.QWidget):
        """Строка выбора папки или ZIP кэша шейдеров — с двумя кнопками."""
        def __init__(s):
            super().__init__()
            h = Q.QHBoxLayout(s); h.setContentsMargins(0, 0, 0, 0); h.setSpacing(6)
            lw = Q.QWidget(); lh = Q.QHBoxLayout(lw); lh.setContentsMargins(0,0,0,0); lh.setSpacing(2)
            lbl = Q.QLabel(tr("g_cachep")); lbl.setMinimumWidth(105)
            opt = mk_label(tr("opt_tag"), "optional_tag")
            lh.addWidget(lbl); lh.addWidget(opt); lh.addStretch(1)
            s.edit = Q.QLineEdit(); s.edit.setPlaceholderText(tr("ph_cache")); s.edit.setClearButtonEnabled(True)
            bd = Q.QPushButton(tr("g_dir")); bd.setObjectName("secondary")
            bz = Q.QPushButton(tr("g_zip")); bz.setObjectName("secondary")
            h.addWidget(lw); h.addWidget(s.edit, 1); h.addWidget(bd); h.addWidget(bz)
            bd.clicked.connect(s.pick_dir); bz.clicked.connect(s.pick_zip)
        def pick_dir(s):
            f = Q.QFileDialog.getExistingDirectory(s, tr("g_cache"), s.edit.text())
            if f: s.edit.setText(f)
        def pick_zip(s):
            f = Q.QFileDialog.getOpenFileName(s, tr("g_cache"), s.edit.text(), "ZIP (*.zip);;*")[0]
            if f: s.edit.setText(f)
        def text(s): return s.edit.text().strip()

    # -----------------------------------------------------------------------
    # Главное окно
    # -----------------------------------------------------------------------
    class Win(Q.QMainWindow):
        PRESETS = [
            ("21:9  2560×1080", 2560, 1080), ("21:9  3440×1440", 3440, 1440),
            ("21:9  2240×960",  2240, 960),  ("21:9  3840×1646", 3840, 1646),
            ("32:9  3840×1080", 3840, 1080), ("16:10 1920×1200", 1920, 1200),
            ("16:10 2560×1600", 2560, 1600), ("16:9  2560×1440", 2560, 1440),
            (None, 0, 0),
        ]

        def __init__(s):
            super().__init__()
            s.setWindowTitle(tr("g_title") + " (shadPS4)")
            s.resize(1200, 800)

            cw = Q.QWidget(); s.setCentralWidget(cw)
            root_v = Q.QVBoxLayout(cw); root_v.setContentsMargins(0, 0, 0, 0); root_v.setSpacing(0)

            # Заголовок
            hdr = Q.QWidget(); hdr.setStyleSheet("background:#1a1f29; border-bottom:1px solid #2b3441;")
            hdr_h = Q.QHBoxLayout(hdr); hdr_h.setContentsMargins(16, 10, 16, 10)
            tl = Q.QLabel(tr("g_title")); tl.setObjectName("title")
            st = Q.QLabel(tr("g_sub"));  st.setObjectName("subtitle")
            hdr_v = Q.QVBoxLayout(); hdr_v.setSpacing(2)
            hdr_v.addWidget(tl); hdr_v.addWidget(st)
            hdr_h.addLayout(hdr_v, 1)
            root_v.addWidget(hdr)

            # Основное содержимое
            body = Q.QWidget(); body_h = Q.QHBoxLayout(body)
            body_h.setContentsMargins(14, 10, 14, 8); body_h.setSpacing(14)
            root_v.addWidget(body, 1)

            left  = Q.QVBoxLayout(); left.setSpacing(8)
            right = Q.QVBoxLayout(); right.setSpacing(8)
            body_h.addLayout(left, 55); body_h.addLayout(right, 45)

            # ── ШАГ 1: Разрешение ──────────────────────────────────────────
            g_res = Q.QGroupBox("1. " + tr("g_res")); gv = Q.QVBoxLayout(g_res)
            hrow = Q.QHBoxLayout(); hrow.setSpacing(10)
            s.pre = Q.QComboBox()
            for p in s.PRESETS: s.pre.addItem(p[0] or tr("g_custom"))
            s.w = Q.QSpinBox(); s.w.setRange(640, 16384); s.w.setValue(2560); s.w.setSuffix(" px")
            s.h = Q.QSpinBox(); s.h.setRange(360, 8640); s.h.setValue(1080); s.h.setSuffix(" px")
            for x in (Q.QLabel(tr("g_preset")), s.pre,
                      Q.QLabel(tr("g_width")),  s.w,
                      Q.QLabel(tr("g_height")), s.h):
                hrow.addWidget(x)
            hrow.addStretch(1); gv.addLayout(hrow)
            s.info = Q.QLabel(); s.info.setObjectName("chip"); s.info.setWordWrap(True)
            gv.addWidget(s.info)
            left.addWidget(g_res)

            # ── ШАГ 2: Шейдер видео (необязательно для 16:9) ──────────────
            g_spv = Q.QGroupBox("2. " + tr("g_spv_group")); gspv = Q.QVBoxLayout(g_spv)

            # Чекбокс включения + краткое пояснение
            s.spv_use = Q.QCheckBox(tr("spv_use_lbl")); s.spv_use.setChecked(False)
            spv_why = mk_label(tr("spv_why"), "subtitle", wrap=True)
            gspv.addWidget(s.spv_use); gspv.addWidget(spv_why)

            # Блок выбора файла — появляется только когда чекбокс включён
            s.spv_block = Q.QWidget(); sb = Q.QVBoxLayout(s.spv_block); sb.setContentsMargins(0,4,0,0); sb.setSpacing(4)

            # ── Метод А: кэш шейдеров (рекомендуется) ──
            spv_auto_lbl = mk_label(tr("spv_auto_lbl"), "step_title")
            sb.addWidget(spv_auto_lbl)
            sb.addWidget(mk_label(tr("spv_cache_prereq"), "hint", wrap=True))

            cache_row_h = Q.QHBoxLayout(); cache_row_h.setSpacing(6)
            cache_row_h.addWidget(mk_label(tr("g_cachep")))
            s.cache = Q.QLineEdit(); s.cache.setPlaceholderText(tr("ph_cache")); s.cache.setClearButtonEnabled(True)
            b_cache_dir = Q.QPushButton(tr("g_dir")); b_cache_dir.setObjectName("secondary")
            b_cache_zip = Q.QPushButton(tr("g_zip")); b_cache_zip.setObjectName("secondary")
            b_cache_dir.clicked.connect(s.pick_cache_dir); b_cache_zip.clicked.connect(s.pick_cache_zip)
            cache_row_h.addWidget(s.cache, 1); cache_row_h.addWidget(b_cache_dir); cache_row_h.addWidget(b_cache_zip)
            sb.addLayout(cache_row_h)
            # Подсказка: где находится папка кэша
            sb.addWidget(mk_label(tr("spv_cache_hint"), "hint", wrap=True))

            # ── Разделитель ──
            sep = Q.QFrame(); sep.setFrameShape(Q.QFrame.HLine); sep.setStyleSheet("color:#2b3441"); sb.addWidget(sep)

            # ── Метод Б: ручной .spv файл ──
            spv_man_lbl = mk_label(tr("spv_manual_lbl"), "step_title"); sb.addWidget(spv_man_lbl)
            sb.addWidget(mk_label(tr("spv_manual_prereq"), "hint", wrap=True))

            # Показываем ожидаемое имя файла — пользователь сразу знает что искать
            spv_name_row = Q.QHBoxLayout(); spv_name_row.setSpacing(6)
            spv_name_row.addWidget(mk_label(tr("spv_fname_lbl")))
            s.spv_name_chip = Q.QLabel(SPV_CANON_NAME)
            s.spv_name_chip.setObjectName("chip")
            s.spv_name_chip.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
            spv_name_row.addWidget(s.spv_name_chip); spv_name_row.addStretch(1)
            sb.addLayout(spv_name_row)

            man_row_h = Q.QHBoxLayout(); man_row_h.setSpacing(6)
            man_row_h.addWidget(mk_label(tr("g_spv_file")))
            s.spvin = Q.QLineEdit(); s.spvin.setPlaceholderText(SPV_CANON_NAME); s.spvin.setClearButtonEnabled(True)
            b_spv = Q.QPushButton(tr("g_browse")); b_spv.setObjectName("secondary")
            b_spv.clicked.connect(s.pick_spv)
            man_row_h.addWidget(s.spvin, 1); man_row_h.addWidget(b_spv)
            sb.addLayout(man_row_h)
            sb.addWidget(mk_label(tr("spv_manual_hint"), "hint", wrap=True))

            gspv.addWidget(s.spv_block)
            s.spv_block.setVisible(False)
            s.spv_use.toggled.connect(lambda v: s.spv_block.setVisible(v))
            s.spv_use.toggled.connect(s.update_status)
            s.cache.textChanged.connect(s.update_status)
            s.spvin.textChanged.connect(s.update_status)
            left.addWidget(g_spv)

            # ── ШАГ 3: Бюджет памяти ──────────────────────────────────────
            g_mem = Q.QGroupBox("3. " + tr("g_mem")); gm = Q.QVBoxLayout(g_mem); gm.setSpacing(6)

            mem_top = Q.QHBoxLayout()
            s.mode = Q.QComboBox()
            if LANG == "en":
                s.mode.addItem("✅  Extended — keep full CPU memory  (recommended, supported by all recent shadPS4 builds)")
                s.mode.addItem("⚠️  Standard — reduce CPU memory  (stock shadPS4, may cause instability)")
            elif LANG == "uk":
                s.mode.addItem("✅  Розширений — зберегти CPU-пам'ять  (рекомендовано, підтримується з коробки)")
                s.mode.addItem("⚠️  Стандартний — урізати CPU-пам'ять  (стоковий shadPS4, можливі проблеми)")
            else:
                s.mode.addItem("✅  Расширенный — сохранить CPU-память  (рекомендуется, поддерживается из коробки)")
                s.mode.addItem("⚠️  Стандартный — урезать CPU-память  (стоковый shadPS4, возможны проблемы)")
            s.mode.setCurrentIndex(0)
            s.mode.setMinimumWidth(300)

            mem_help = help_btn(tr("mem_help_tip"))
            mem_top.addWidget(s.mode, 1); mem_top.addWidget(mem_help)
            gm.addLayout(mem_top)

            s.mode_desc = mk_label(tr("mode_desc_off"), "subtitle", wrap=True); gm.addWidget(s.mode_desc)

            # Расширенные настройки (скрыты)
            s.advchk = Q.QCheckBox(tr("g_adv")); gm.addWidget(s.advchk)
            s.adv = Q.QWidget(); av = Q.QVBoxLayout(s.adv); av.setContentsMargins(18, 0, 0, 0); av.setSpacing(4)
            s.manual = Q.QCheckBox(tr("adv_manual"))
            s.extra  = Q.QSpinBox(); s.extra.setRange(0, 4096); s.extra.setSingleStep(64)
            s.extra.setValue(512); s.extra.setSuffix(" МБ" if LANG != "en" else " MB")
            s.extra.setToolTip(tr("adv_extra_tip"))
            s.frac   = Q.QSpinBox(); s.frac.setRange(10, 100); s.frac.setValue(100); s.frac.setSuffix(" %")
            s.frac.setToolTip(tr("adv_frac_tip"))
            s.aggr   = Q.QCheckBox(tr("adv_aggr"))
            s.keep   = Q.QCheckBox(tr("adv_keep"))
            hm = Q.QHBoxLayout(); hm.addWidget(s.manual); hm.addWidget(s.extra); hm.addStretch(1)
            hf = Q.QHBoxLayout(); hf.addWidget(Q.QLabel(tr("adv_frac"))); hf.addWidget(s.frac); hf.addStretch(1)
            av.addLayout(hm); av.addLayout(hf); av.addWidget(s.aggr); av.addWidget(s.keep)
            s.adv.setVisible(False); gm.addWidget(s.adv)
            left.addWidget(g_mem)

            # ── Дополнительно (необязательно) ─────────────────────────────
            s.extra_chk = Q.QCheckBox(tr("g_extra_sect")); left.addWidget(s.extra_chk)
            s.extra_sect = Q.QGroupBox(""); ex = Q.QVBoxLayout(s.extra_sect); ex.setSpacing(4)
            ex.addWidget(mk_label(tr("extra_sect_hint"), "hint", wrap=True))

            # eboot.bin
            s.eboot = FileRow(tr("g_eboot"), "eboot.bin (*.bin);;*", tr("ph_eboot"), optional=True)
            ex.addWidget(s.eboot)

            # Базовый XML
            xml_row_h = Q.QHBoxLayout(); xml_row_h.setSpacing(6)
            xml_lw = Q.QWidget(); xml_lh = Q.QHBoxLayout(xml_lw); xml_lh.setContentsMargins(0,0,0,0); xml_lh.setSpacing(2)
            xml_lh.addWidget(mk_label(tr("g_xmlin"))); xml_lh.addWidget(mk_label(tr("opt_tag"), "optional_tag")); xml_lh.addStretch(1)
            s.xmlin = Q.QLineEdit(); s.xmlin.setPlaceholderText(tr("ph_xmlin")); s.xmlin.setClearButtonEnabled(True)
            b_xml = Q.QPushButton(tr("g_browse")); b_xml.setObjectName("secondary")
            b_xml.clicked.connect(lambda: s._pick_xml())
            xml_row_h.addWidget(xml_lw); xml_row_h.addWidget(s.xmlin, 1); xml_row_h.addWidget(b_xml)
            ex.addLayout(xml_row_h)

            # GitHub чекбокс
            s.gh = Q.QCheckBox(tr("g_gh")); s.gh.setChecked(True); ex.addWidget(s.gh)
            ex.addWidget(mk_label(tr("g_ghhint"), "hint", wrap=True))
            s.xmlin.textChanged.connect(lambda t: s.gh.setEnabled(not t.strip()))

            s.extra_sect.setVisible(False)
            s.extra_chk.toggled.connect(s.extra_sect.setVisible)
            left.addWidget(s.extra_sect)
            left.addStretch(1)

            # ── Правая колонка: dmem карточка + расчёт ────────────────────
            s.card = Q.QFrame(); s.card.setObjectName("dmem"); cv = Q.QVBoxLayout(s.card); cv.setSpacing(4)
            cap_lbl = mk_label(tr("card_cap")); cap_lbl.setStyleSheet("font-weight:600")
            s.dmbig = Q.QLabel(); s.dmbig.setObjectName("dmbig")
            s.dmhex = Q.QLabel(); s.dmhex.setObjectName("dmhex")
            s.dmtxt = Q.QLabel(); s.dmtxt.setWordWrap(True)
            for x in (cap_lbl, s.dmbig, s.dmhex, s.dmtxt): cv.addWidget(x)
            right.addWidget(s.card)

            g3 = Q.QGroupBox(tr("g_calc")); l3 = Q.QVBoxLayout(g3)
            s.sum = Q.QLabel(); s.sum.setWordWrap(True); l3.addWidget(s.sum)
            s.tbl = Q.QTableWidget(0, 3)
            s.tbl.setHorizontalHeaderLabels([tr("col_entry"), tr("col_was"), tr("col_now")])
            s.tbl.horizontalHeader().setSectionResizeMode(0, Q.QHeaderView.Stretch)
            s.tbl.verticalHeader().setVisible(False)
            s.tbl.setEditTriggers(Q.QAbstractItemView.NoEditTriggers)
            s.tbl.setAlternatingRowColors(True); s.tbl.setMinimumHeight(160)
            l3.addWidget(s.tbl); right.addWidget(g3, 1)

            s.log = Q.QPlainTextEdit(); s.log.setReadOnly(True); s.log.setMaximumHeight(90)
            s.log.setPlaceholderText(tr("g_log")); right.addWidget(s.log)

            # ── Статус-строка + кнопка ────────────────────────────────────
            bot = Q.QFrame(); bot.setObjectName("statusbar")
            bot_h = Q.QHBoxLayout(bot); bot_h.setContentsMargins(14, 6, 14, 6)
            s.status_lbl = Q.QLabel(); s.status_lbl.setObjectName("statuslbl"); s.status_lbl.setWordWrap(True)
            s.go = Q.QPushButton(tr("g_go")); s.go.setObjectName("primary")
            s.go.setToolTip(tr("go_tooltip"))
            bot_h.addWidget(s.status_lbl, 1); bot_h.addWidget(s.go)
            root_v.addWidget(bot)

            # ── Сигналы ───────────────────────────────────────────────────
            s.pre.currentIndexChanged.connect(s.on_pre)
            s.w.valueChanged.connect(s.refresh); s.h.valueChanged.connect(s.refresh)
            s.mode.currentIndexChanged.connect(s.on_mode_change)
            s.mode.currentIndexChanged.connect(s.refresh)
            s.advchk.toggled.connect(s.on_adv)
            for x in (s.aggr, s.manual): x.toggled.connect(s.refresh)
            s.frac.valueChanged.connect(s.refresh); s.extra.valueChanged.connect(s.refresh)
            s.go.clicked.connect(s.run)
            s.eboot.edit.editingFinished.connect(s.check_eboot)
            s.on_pre(0)

        # ── helpers ───────────────────────────────────────────────────────
        def _pick_xml(s):
            f = Q.QFileDialog.getOpenFileName(s, tr("g_xmlin"), s.xmlin.text(), "XML (*.xml);;*")[0]
            if f: s.xmlin.setText(f)

        def pick_cache_dir(s):
            f = Q.QFileDialog.getExistingDirectory(s, tr("g_cache"), s.cache.text())
            if f: s.cache.setText(f)

        def pick_cache_zip(s):
            f = Q.QFileDialog.getOpenFileName(s, tr("g_cache"), s.cache.text(), "ZIP (*.zip);;*")[0]
            if f: s.cache.setText(f)

        def pick_spv(s):
            f = Q.QFileDialog.getOpenFileName(s, tr("g_spv"), s.spvin.text(), "SPIR-V (*.spv);;*")[0]
            if f: s.spvin.setText(f)

        def adv_on(s): return s.advchk.isChecked()

        def mode_key(s):
            if s.adv_on() and s.manual.isChecked(): return "custom"
            return "full" if s.mode.currentIndex() == 0 else "off"

        def extra_val(s): return resolve_extra(s.mode_key(), s.extra.value())
        def aggr_val(s): return s.adv_on() and s.aggr.isChecked() and s.mode_key() != "full"
        def frac_val(s): return (s.frac.value() if s.adv_on() else 100) / 100

        def on_mode_change(s, idx):
            # idx 0 = расширенный (full/рекомендуется), idx 1 = стандартный (off/урезание CPU)
            if LANG == "en":
                descs = [
                    "✅ GPU gets more memory — CPU memory stays untouched. Recommended. Supported by all recent shadPS4 builds out of the box.",
                    "⚠️ GPU gets more memory — taken from CPU memory (sound, loading heap, screenshot buffers are reduced). Works with stock shadPS4, but may cause instability or crashes in rare cases.",
                ]
            elif LANG == "uk":
                descs = [
                    "✅ GPU отримує більше пам'яті — CPU-пам'ять не чіпається. Рекомендовано. Підтримується всіма актуальними збірками shadPS4 з коробки.",
                    "⚠️ GPU отримує більше пам'яті — за рахунок CPU-пам'яті (звук, купа завантаження, буфери скріншотів зменшуються). Працює зі стоковим shadPS4, але в рідкісних випадках можливі збої або краші.",
                ]
            else:
                descs = [
                    "✅ GPU получает больше памяти — CPU-память не трогается. Рекомендуется. Поддерживается всеми актуальными сборками shadPS4 из коробки.",
                    "⚠️ GPU получает больше памяти — за счёт CPU-памяти (звук, куча загрузки, буферы скриншотов уменьшаются). Работает со стоковым shadPS4, но в редких случаях возможны зависания или краши.",
                ]
            s.mode_desc.setText(descs[idx] if idx < len(descs) else "")

        def on_adv(s, on): s.adv.setVisible(on); s.refresh()

        def on_pre(s, i):
            _, w, h = s.PRESETS[i]
            if w:
                s.w.blockSignals(True); s.h.blockSignals(True)
                s.w.setValue(w); s.h.setValue(h)
                s.w.blockSignals(False); s.h.blockSignals(False)
            s.refresh()

        def say(s, t): s.log.appendPlainText(t); Q.QApplication.processEvents()

        def repolish(s, *ws):
            for w_ in ws: w_.style().unpolish(w_); w_.style().polish(w_)

        def update_status(s):
            """Обновляет строку внизу: показывает что именно будет создано."""
            parts = []
            Wd, Hd = s.w.value(), s.h.value()
            if LANG == "en":
                parts.append("XML patch for eboot.bin")
                if not is_169(Wd, Hd):
                    if s.spv_use.isChecked():
                        if s.cache.text().strip():
                            parts.append("video shader patch directly in cache")
                        elif s.spvin.text().strip():
                            parts.append("video shader patch (manual file)")
                        else:
                            parts.append("video shader patch (no file selected yet)")
                lbl = tr("status_will_create") + ": " + " + ".join(parts)
            elif LANG == "uk":
                parts.append("XML-патч для eboot.bin")
                if not is_169(Wd, Hd):
                    if s.spv_use.isChecked():
                        if s.cache.text().strip():
                            parts.append("патч шейдера відео в кеші")
                        elif s.spvin.text().strip():
                            parts.append("патч шейдера відео (ручний файл)")
                        else:
                            parts.append("патч шейдера відео (файл не вказано)")
                lbl = tr("status_will_create") + ": " + " + ".join(parts)
            else:
                parts.append("XML-патч для eboot.bin")
                if not is_169(Wd, Hd):
                    if s.spv_use.isChecked():
                        if s.cache.text().strip():
                            parts.append("патч шейдера видео прямо в кэше")
                        elif s.spvin.text().strip():
                            parts.append("патч шейдера видео (ручной файл)")
                        else:
                            parts.append("патч шейдера видео (файл не выбран)")
                lbl = tr("status_will_create") + ": " + " + ".join(parts)
            s.status_lbl.setText(lbl)
            has = bool(parts)
            s.status_lbl.setProperty("active", "true" if has else "false")
            s.repolish(s.status_lbl)

        def refresh(s):
            Wd, Hd = s.w.value(), s.h.value()
            R = (Wd / Hd) / (16 / 9)
            g = math.gcd(Wd, Hd)
            s.mode.setEnabled(not (s.adv_on() and s.manual.isChecked()))
            s.extra.setEnabled(s.adv_on() and s.manual.isChecked())
            s.aggr.setEnabled(s.mode_key() != "full")
            s.info.setProperty("warn", R < 0.999)
            s.info.setText(tr("g_ratio", Wd / Hd, Wd // g, Hd // g, R)
                           + (tr("g_narrow") if R < 0.999 else "")
                           + (tr("g_169") if is_169(Wd, Hd) else ""))
            s.repolish(s.info)
            s.tbl.setRowCount(0)
            try:
                _, rows, info = calc_budget(Wd, Hd, s.aggr_val(), s.frac_val(), None, s.extra_val())
                s.sum.setText(info["text"] + (tr("sum_cap", info["cap"]) if "cap" in info else ""))
                for r in rows:
                    n = s.tbl.rowCount(); s.tbl.insertRow(n)
                    for c, t in enumerate((r[0], "%.2f" % r[1], "%.2f" % r[2])):
                        it = Q.QTableWidgetItem(t)
                        if c: it.setTextAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
                        s.tbl.setItem(n, c, it)
                s.go.setEnabled(True)
                exp = info["expanded"]
                s.card.setProperty("state", "warn" if exp else "ok")
                s.dmbig.setText("%d %s" % (info["dmem_mb"], "МБ" if LANG != "en" else "MB"))
                s.dmhex.setText("0x%x %s%s" % (info["dmem_mb"] * MB,
                                                tr("bytes"), "  " + tr("card_std") if not exp else ""))
                s.dmtxt.setText("⚠ " + tr("card_exp", info["dmem_mb"], info["dmem_mb"] - DMEM_BASE_MB)
                                if exp else "✔ " + tr("card_ok"))
            except BudgetError as e:
                s.sum.setText("⚠ " + str(e)); s.go.setEnabled(False)
                s.card.setProperty("state", "err"); s.dmbig.setText("—"); s.dmhex.setText("")
                s.dmtxt.setText(tr("card_bad"))
            s.repolish(s.card, s.dmbig, s.dmhex, s.dmtxt)
            s.update_status()

        def check_eboot(s):
            p = s.eboot.text()
            if not p: return
            try:
                bad = check_eboot(p)
                s.say(tr("eboot_ok") if not bad else tr("eboot_bad", ", ".join(bad)))
            except Exception as e:
                s.say(tr("eboot_fail", e))

        def _next_steps_html(s, root, did_xml, did_spv, did_cache, gr, cres, manual):
            """Формирует понятный список шагов 'Что делать дальше'."""
            mb = "МБ" if LANG != "en" else "MB"
            steps = []
            if did_xml or manual:
                if gr and gr.get("xml") is not None:
                    rel = xml_gh_rel()
                elif manual:
                    rel = None
                else:
                    Wd, Hd = s.w.value(), s.h.value()
                    rel = xml_rel(Wd, Hd)
                if rel:
                    if LANG == "en":
                        steps.append("Copy folder «user» from «%s» into your shadPS4 folder (merge, overwrite)." % root)
                    elif LANG == "uk":
                        steps.append("Скопіюйте теку «user» з «%s» у теку shadPS4 (з об'єднанням і заміною)." % root)
                    else:
                        steps.append("Скопируйте папку «user» из «%s» в папку shadPS4 (с объединением и заменой)." % root)
                elif manual:
                    if LANG == "en":
                        steps.append("Open TheLastOfUsRemastered.xml in shadPS4/user/patches/shadPS4 and paste the block from «%s» before </Patch>." % manual)
                    elif LANG == "uk":
                        steps.append("Відкрийте TheLastOfUsRemastered.xml у shadPS4/user/patches/shadPS4 та вставте блок з «%s» перед </Patch>." % manual)
                    else:
                        steps.append("Откройте TheLastOfUsRemastered.xml в shadPS4/user/patches/shadPS4 и вставьте блок из «%s» перед </Patch>." % manual)
            if did_cache and cres and cres.get("changed", 0):
                if LANG == "en": steps.append("Shader cache: patched in-place — no extra copy needed.")
                elif LANG == "uk": steps.append("Кеш шейдерів: пропатчено на місці — копіювати нічого.")
                else: steps.append("Кэш шейдеров: пропатчен на месте — дополнительного копирования не нужно.")
            elif did_spv and not did_cache:
                if LANG == "en": steps.append("Copy folder «user» from «%s» into your shadPS4 folder to apply the shader patch." % root)
                elif LANG == "uk": steps.append("Скопіюйте теку «user» з «%s» у теку shadPS4 для застосування патчу шейдера." % root)
                else: steps.append("Скопируйте папку «user» из «%s» в папку shadPS4 для применения патча шейдера." % root)
            if LANG == "en": steps.append("In shadPS4: right-click the game → Edit Cheats → enable the patch «Resolution Patch %dx%d»." % (s.w.value(), s.h.value()))
            elif LANG == "uk": steps.append("У shadPS4: ПКМ по грі → Edit Cheats → увімкніть патч «Resolution Patch %dx%d»." % (s.w.value(), s.h.value()))
            else: steps.append("В shadPS4: ПКМ по игре → Edit Cheats → включите патч «Resolution Patch %dx%d»." % (s.w.value(), s.h.value()))
            lines = "\n".join("  %d. %s" % (i+1, st) for i, st in enumerate(steps))
            if LANG == "en": head = "Done! What to do next:\n\n"
            elif LANG == "uk": head = "Готово! Що робити далі:\n\n"
            else: head = "Готово! Что делать дальше:\n\n"
            return head + lines

        def run(s):
            Wd, Hd = s.w.value(), s.h.value()
            did = False; spv_done = False; cres = None; gr = None; manual = None
            cache_path = s.cache.text().strip()
            xmlin_path = s.xmlin.text().strip()
            spvin_path = s.spvin.text().strip()
            use_spv = s.spv_use.isChecked() and not is_169(Wd, Hd)
            use_gh = s.gh.isChecked() and not xmlin_path
            disable_old = not (s.adv_on() and s.keep.isChecked())
            root = out_root()

            try:
                # --- XML патч ---
                if use_gh:
                    Q.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
                    try:
                        gr = build_github_xml(Wd, Hd, s.aggr_val(), s.frac_val(), s.extra_val(), disable_old, s.say)
                    finally:
                        Q.QApplication.restoreOverrideCursor()
                    s.say(gr["text"])
                    info = gr["info"]
                    if gr["xml"] is not None:
                        out = os.path.join(root, xml_gh_rel())
                        os.makedirs(os.path.dirname(out), exist_ok=True)
                        with open(out, 'w', encoding='utf-8', newline='') as f: f.write(gr["xml"])
                        s.say(tr("log_xml", out)); did = True
                    elif gr["status"] in ("offline", "conflict"):
                        manual = os.path.join(root, block_rel(Wd, Hd))
                        os.makedirs(root, exist_ok=True)
                        open(manual, 'w', encoding='utf-8').write(gr["block"])
                        s.say(tr("gh_man_log", manual))
                    if info["expanded"]: s.say("⚠ " + dmem_note(info))
                else:
                    if s.gh.isChecked() and xmlin_path: s.say(tr("gh_skip"))
                    base = open(xmlin_path, encoding='utf-8').read() if xmlin_path else None
                    out = out_xml_path(root, Wd, Hd)
                    os.makedirs(os.path.dirname(out), exist_ok=True)
                    x, rows, info = build_xml(Wd, Hd, base, s.aggr_val(), s.frac_val(), s.extra_val(), disable_old)
                    open(out, 'w', encoding='utf-8').write(x)
                    s.say(tr("log_xml", out))
                    if info["expanded"]: s.say("⚠ " + dmem_note(info))
                    did = True

                # --- Шейдер (ручной файл) ---
                if use_spv and spvin_path:
                    res, msg = patch_spv(open(spvin_path, 'rb').read(), (Wd / Hd) / (16 / 9))
                    out = out_spv_path(spvin_path, root)
                    os.makedirs(os.path.dirname(out), exist_ok=True)
                    open(out, 'wb').write(res)
                    s.say(tr("log_spv", msg, out))
                    if not cache_path: s.say(tr("spv_cache"))
                    did = spv_done = True

                # --- Шейдер через кэш ---
                if use_spv and cache_path:
                    s.go.setEnabled(False); Q.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
                    try:
                        cres = patch_cache(cache_path, Wd, Hd, os.path.join(root, "backup"), s.say)
                    finally:
                        Q.QApplication.restoreOverrideCursor(); s.go.setEnabled(True)
                    s.say(cres["text"])

                # --- Итоговый диалог ---
                nf = bool(cres and cres["status"] == "notfound")
                body = s._next_steps_html(root, did, spv_done, bool(cres), gr, cres, manual)

                # Дополнительные предупреждения
                extra_notes = []
                if gr: extra_notes.append(gr["text"])
                if cres: extra_notes.append(cres["text"])
                elif spv_done and not cache_path: extra_notes.append(tr("spv_cache"))
                if manual: extra_notes.append(tr("gh_man_msg", manual))
                if nf: extra_notes.append(tr("cache_nf_msg"))
                if extra_notes:
                    body += "\n\n─────────────────────\n" + "\n\n".join(extra_notes)

                if nf or manual:
                    Q.QMessageBox.warning(s, tr("warn_title"), body)
                else:
                    Q.QMessageBox.information(s, tr("done_title"), body)

            except Exception as e:
                s.say(tr("err_prefix", e))
                Q.QMessageBox.critical(s, tr("err_title"), str(e))

    w = Win(); w.show()
    shot = os.environ.get("TLOU_SHOT")
    if os.environ.get("TLOU_ADV"): w.advchk.setChecked(True)
    if shot:
        QtCore.QTimer.singleShot(300, lambda: (w.grab().save(shot), app.quit()))
    sys.exit(app.exec_())


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--cli", nargs=2, type=int, metavar=("W", "H"))
    ap.add_argument("--eboot"); ap.add_argument("--xml", nargs=2, metavar=("IN", "OUT"))
    ap.add_argument("--spv", nargs=2, metavar=("IN", "OUT")); ap.add_argument("--aggressive", action="store_true")
    ap.add_argument("--extra", type=int, default=0)
    ap.add_argument("--dmem", action="store_true")
    ap.add_argument("--keep-old", action="store_true")
    ap.add_argument("--frac", type=float, default=100.0)
    ap.add_argument("--cache", metavar="DIR|ZIP")
    ap.add_argument("--lang", choices=["en", "ru", "uk"])
    a = ap.parse_args()
    LANG = a.lang or detect_lang()
    sys.exit(cli(a)) if a.cli else gui()
