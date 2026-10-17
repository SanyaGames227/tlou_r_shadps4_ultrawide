#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TLOU Remastered (PS4, AppVer 01.11) - генератор патча любого разрешения / соотношения сторон
для shadPS4: XML-патч (eboot.bin) + замена SPIR-V шейдера видеороликов.

GUI (PyQt5):   python3 tlou_ultrawide.py
CLI:           python3 tlou_ultrawide.py --cli 2560 1080 [--eboot eboot.bin] [--xml base.xml out.xml]
                                         [--spv in.spv out.spv] [--aggressive]
                                         [--dmem | --extra МБ] [--frac %] [--keep-old] [--lang en|ru|uk]
  --dmem      режим «с расширением dmem»: CPU не урезается, константа direct-памяти растёт на D
  --extra МБ  частичное расширение (остальное забирается у CPU)
  --keep-old  не отключать прежние разрешающие секции в базовом XML
"""
import sys, os, re, struct, math, argparse

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
  "spv_cache": "⚠ If the shader cache is enabled in shadPS4, delete the old shader cache of the game after installing the patched shader - otherwise the emulator keeps using the old compiled shader and the video will not change.",
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
  "g_xmlin": "Base XML:", "ph_xmlin": "optional — the patch section will be added to it",
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
  "spv_cache": "⚠ Если в shadPS4 включён кэш шейдеров, после установки пропатченного шейдера удалите старый кэш шейдеров игры - иначе эмулятор продолжит использовать старый скомпилированный шейдер, и видео не изменится.",
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
  "g_xmlin": "Базовый XML:", "ph_xmlin": "необязательно — секция добавится к нему",
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
  "spv_cache": "⚠ Якщо в shadPS4 увімкнено кеш шейдерів, після встановлення пропатченого шейдера видаліть старий кеш шейдерів гри - інакше емулятор продовжить використовувати старий скомпільований шейдер, і відео не зміниться.",
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
  "g_xmlin": "Базовий XML:", "ph_xmlin": "необов'язково — секція додасться до нього",
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
    return L, rows, info


def lines_to_text(L):
    out = []
    for k, v in L:
        if k == "c":
            out.append("      <!-- %s -->" % v)
        else:
            out.append('      <Line Type="bytes" Address="0x%08x" Value="%s"/>' % v)
    return "\n".join(out)


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
            '    </PatchList>\n    </Metadata>\n' % ("Ultrawide %dx%d" % (W, H), note, AUTHOR, lines_to_text(L))), rows, info


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
# CLI
# ----------------------------------------------------------------------------------------
def cli(a):
    W, H = a.cli
    if a.eboot:
        bad = check_eboot(a.eboot)
        print(tr("eboot_ok") if not bad else tr("eboot_bad", ", ".join(bad)))
    if a.xml:
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
        open(a.spv[1], 'wb').write(out); print("SPV:", a.spv[1], "-", msg); print(tr("spv_cache"))


# ----------------------------------------------------------------------------------------
# Автоматические пути результата (поля «Сохранить …» в GUI не нужны)
# ----------------------------------------------------------------------------------------
XML_DIR = os.path.join("user", "patches", "shadPS4")


def xml_rel(W, H):
    return os.path.join(XML_DIR, "TheLastofUsRemastered_%dx%d.xml" % (W, H))
SPV_REL = os.path.join("user", "shader", "patch")


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
# GUI (PyQt5, Fusion, тёмная тема + зелёный акцент). Расширенные настройки скрыты за галочкой.
# ----------------------------------------------------------------------------------------
def gui():
    from PyQt5 import QtWidgets as Q, QtGui, QtCore
    app = Q.QApplication(sys.argv)
    app.setStyle("Fusion")
    BLUE, BLUE_H, BLUE_D = "#0070d1", "#1a85e6", "#00439c"       # PlayStation blue
    pal = QtGui.QPalette()
    C = QtGui.QColor
    for role, col in ((QtGui.QPalette.Window, "#161a22"), (QtGui.QPalette.Base, "#0f131a"),
                      (QtGui.QPalette.AlternateBase, "#141922"), (QtGui.QPalette.Button, "#232a36"),
                      (QtGui.QPalette.ButtonText, "#e6ebf2"), (QtGui.QPalette.Highlight, BLUE),
                      (QtGui.QPalette.HighlightedText, "#ffffff"), (QtGui.QPalette.Text, "#e6ebf2"),
                      (QtGui.QPalette.WindowText, "#e6ebf2"), (QtGui.QPalette.ToolTipBase, "#232a36"),
                      (QtGui.QPalette.ToolTipText, "#e6ebf2"), (QtGui.QPalette.BrightText, "#ffffff"),
                      (QtGui.QPalette.Link, "#4da3ff"), (QtGui.QPalette.Light, "#33405a"),
                      (QtGui.QPalette.Midlight, "#2a3447"), (QtGui.QPalette.Mid, "#1c2330"),
                      (QtGui.QPalette.Dark, "#0b0e14"), (QtGui.QPalette.Shadow, "#05070b")):
        pal.setColor(role, C(col))
    if hasattr(QtGui.QPalette, "PlaceholderText"): pal.setColor(QtGui.QPalette.PlaceholderText, C("#7a8599"))
    for role in (QtGui.QPalette.Text, QtGui.QPalette.ButtonText, QtGui.QPalette.WindowText):
        pal.setColor(QtGui.QPalette.Disabled, role, C("#667086"))
    pal.setColor(QtGui.QPalette.Disabled, QtGui.QPalette.Highlight, C("#2b3447"))
    app.setPalette(pal)
    # Поля, списки, спинбоксы, чекбоксы и кнопки не стилизуем - их рисует сам Fusion (по палитре).
    app.setStyleSheet("""
        QGroupBox{font-weight:600;border:1px solid #2b3441;border-radius:6px;margin-top:12px;padding:10px 8px 6px 8px;background:#1a1f29}
        QGroupBox::title{subcontrol-origin:margin;left:12px;padding:0 5px;color:#4da3ff}
        QLabel#title{font-size:19px;font-weight:700;color:#f2f6fc}
        QLabel#subtitle{color:#8793a8}
        QLabel#chip{background:#10294a;border:1px solid #1d4f8a;border-radius:9px;padding:3px 10px;color:#9fcdff}
        QLabel#chip[warn="true"]{background:#3d3416;border-color:#7a6422;color:#f0d58a}
        QPushButton#primary{background:%(b)s;color:#ffffff;font-weight:700;font-size:14px;padding:9px 26px;border:1px solid %(bd)s;border-radius:4px}
        QPushButton#primary:hover{background:%(bh)s}
        QPushButton#primary:disabled{background:#1d2a40;color:#6f7d96;border-color:#1d2a40}
        QFrame#dmem{border:1px solid #1d4f8a;border-radius:8px;background:#0f2442}
        QFrame#dmem[state="warn"]{border-color:#7a6422;background:#2f2b17}
        QLabel#dmbig{font-size:26px;font-weight:700;color:#66b2ff}
        QFrame#dmem[state="warn"] QLabel#dmbig{color:#f3c75a}
        QLabel#dmhex{color:#93a0b6;font-family:Consolas,Menlo,monospace}
        QPlainTextEdit{font-family:Consolas,Menlo,monospace;font-size:11px}
    """ % dict(b=BLUE, bh=BLUE_H, bd=BLUE_D))

    class FileRow(Q.QWidget):
        def __init__(s, label, flt, placeholder=""):
            super().__init__()
            h = Q.QHBoxLayout(s); h.setContentsMargins(0, 0, 0, 0)
            s.lbl = Q.QLabel(label); s.lbl.setMinimumWidth(110)
            s.edit = Q.QLineEdit(); s.edit.setPlaceholderText(placeholder); s.edit.setClearButtonEnabled(True)
            b = Q.QPushButton(tr("g_browse"))
            h.addWidget(s.lbl); h.addWidget(s.edit, 1); h.addWidget(b)
            s.flt = flt
            b.clicked.connect(s.pick)

        def pick(s):
            f = Q.QFileDialog.getOpenFileName(s, s.lbl.text(), s.edit.text(), s.flt)[0]
            if f: s.edit.setText(f)

        def text(s): return s.edit.text().strip()

    class Win(Q.QMainWindow):
        PRESETS = [("21:9  2560×1080", 2560, 1080), ("21:9  3440×1440", 3440, 1440), ("21:9  2240×960", 2240, 960),
                   ("21:9  3840×1646", 3840, 1646), ("32:9  3840×1080", 3840, 1080), ("16:10 1920×1200", 1920, 1200),
                   ("16:10 2560×1600", 2560, 1600), ("16:9  2560×1440", 2560, 1440), (None, 0, 0)]

        def __init__(s):
            super().__init__()
            s.setWindowTitle(tr("g_title") + " (shadPS4)")
            s.resize(1180, 760)
            c = Q.QWidget(); s.setCentralWidget(c)
            root = Q.QVBoxLayout(c); root.setContentsMargins(14, 10, 14, 12)
            t = Q.QLabel(tr("g_title")); t.setObjectName("title")
            st = Q.QLabel(tr("g_sub")); st.setObjectName("subtitle")
            root.addWidget(t); root.addWidget(st)
            cols = Q.QHBoxLayout(); root.addLayout(cols, 1)
            left, right = Q.QVBoxLayout(), Q.QVBoxLayout()
            cols.addLayout(left, 11); cols.addLayout(right, 10)

            # --- разрешение
            g2 = Q.QGroupBox(tr("g_res")); gv = Q.QVBoxLayout(g2); h = Q.QHBoxLayout()
            s.pre = Q.QComboBox(); [s.pre.addItem(p[0] or tr("g_custom")) for p in s.PRESETS]
            s.w = Q.QSpinBox(); s.w.setRange(640, 16384); s.w.setValue(2560); s.w.setSuffix(" px")
            s.h = Q.QSpinBox(); s.h.setRange(360, 8640); s.h.setValue(1080); s.h.setSuffix(" px")
            for x in (Q.QLabel(tr("g_preset")), s.pre, Q.QLabel(tr("g_width")), s.w, Q.QLabel(tr("g_height")), s.h): h.addWidget(x)
            h.addStretch(1); gv.addLayout(h)
            s.info = Q.QLabel(); s.info.setObjectName("chip"); s.info.setWordWrap(True)
            gv.addWidget(s.info); left.addWidget(g2)

            # --- файлы
            g = Q.QGroupBox(tr("g_files")); gl = Q.QVBoxLayout(g)
            s.eboot = FileRow(tr("g_eboot"), "eboot.bin (*.bin);;*", tr("ph_eboot"))
            s.xmlin = FileRow(tr("g_xmlin"), "XML (*.xml)", tr("ph_xmlin"))
            s.spvin = FileRow(tr("g_spv"), "SPIR-V (*.spv)", tr("ph_spv"))
            for r in (s.eboot, s.xmlin, s.spvin): gl.addWidget(r)
            hint = Q.QLabel(tr("g_outhint")); hint.setObjectName("subtitle"); hint.setWordWrap(True); gl.addWidget(hint)
            left.addWidget(g)

            # --- память: основной режим + расширенные настройки за галочкой
            g4 = Q.QGroupBox(tr("g_mem")); gm = Q.QVBoxLayout(g4)
            s.mode = Q.QComboBox(); s.mode.addItem(tr("mode_off")); s.mode.addItem(tr("mode_full")); s.mode.setCurrentIndex(1)
            gm.addWidget(s.mode)
            s.advchk = Q.QCheckBox(tr("g_adv")); gm.addWidget(s.advchk)
            s.adv = Q.QWidget(); av = Q.QVBoxLayout(s.adv); av.setContentsMargins(18, 0, 0, 0)
            s.manual = Q.QCheckBox(tr("adv_manual"))
            s.extra = Q.QSpinBox(); s.extra.setRange(0, 4096); s.extra.setSingleStep(64); s.extra.setValue(512); s.extra.setSuffix(" МБ" if LANG != "en" else " MB")
            s.extra.setToolTip(tr("adv_extra_tip"))
            s.frac = Q.QSpinBox(); s.frac.setRange(10, 100); s.frac.setValue(100); s.frac.setSuffix(" %"); s.frac.setToolTip(tr("adv_frac_tip"))
            s.aggr = Q.QCheckBox(tr("adv_aggr"))
            s.keep = Q.QCheckBox(tr("adv_keep"))
            hm = Q.QHBoxLayout(); hm.addWidget(s.manual); hm.addWidget(s.extra); hm.addStretch(1)
            hf = Q.QHBoxLayout(); hf.addWidget(Q.QLabel(tr("adv_frac"))); hf.addWidget(s.frac); hf.addStretch(1)
            for l in (hm, hf): av.addLayout(l)
            av.addWidget(s.aggr); av.addWidget(s.keep)
            s.adv.setVisible(False); gm.addWidget(s.adv); left.addWidget(g4); left.addStretch(1)

            # --- dmem-карточка
            s.card = Q.QFrame(); s.card.setObjectName("dmem"); cv = Q.QVBoxLayout(s.card)
            cap = Q.QLabel(tr("card_cap")); cap.setStyleSheet("font-weight:600")
            s.dmbig = Q.QLabel(); s.dmbig.setObjectName("dmbig")
            s.dmhex = Q.QLabel(); s.dmhex.setObjectName("dmhex")
            s.dmtxt = Q.QLabel(); s.dmtxt.setWordWrap(True)
            for x in (cap, s.dmbig, s.dmhex, s.dmtxt): cv.addWidget(x)
            right.addWidget(s.card)

            # --- таблица
            g3 = Q.QGroupBox(tr("g_calc")); l3 = Q.QVBoxLayout(g3)
            s.sum = Q.QLabel(); s.sum.setWordWrap(True)
            s.tbl = Q.QTableWidget(0, 3); s.tbl.setHorizontalHeaderLabels([tr("col_entry"), tr("col_was"), tr("col_now")])
            s.tbl.horizontalHeader().setSectionResizeMode(0, Q.QHeaderView.Stretch)
            s.tbl.verticalHeader().setVisible(False)
            s.tbl.setEditTriggers(Q.QAbstractItemView.NoEditTriggers); s.tbl.setAlternatingRowColors(True)
            s.tbl.setMinimumHeight(170)
            l3.addWidget(s.sum); l3.addWidget(s.tbl); right.addWidget(g3, 1)
            s.log = Q.QPlainTextEdit(); s.log.setReadOnly(True); s.log.setMaximumHeight(100)
            s.log.setPlaceholderText(tr("g_log")); right.addWidget(s.log)

            s.go = Q.QPushButton(tr("g_go")); s.go.setObjectName("primary")
            root.addWidget(s.go, alignment=QtCore.Qt.AlignRight)

            s.pre.currentIndexChanged.connect(s.on_pre)
            s.w.valueChanged.connect(s.refresh); s.h.valueChanged.connect(s.refresh)
            s.mode.currentIndexChanged.connect(s.refresh)
            s.advchk.toggled.connect(s.on_adv)
            for x in (s.aggr, s.manual): x.toggled.connect(s.refresh)
            s.frac.valueChanged.connect(s.refresh); s.extra.valueChanged.connect(s.refresh)
            s.go.clicked.connect(s.run)
            s.eboot.edit.editingFinished.connect(s.check)
            s.on_pre(0)

        def adv_on(s): return s.advchk.isChecked()

        def mode_key(s):
            if s.adv_on() and s.manual.isChecked(): return "custom"
            return "off" if s.mode.currentIndex() == 0 else "full"

        def extra_val(s): return resolve_extra(s.mode_key(), s.extra.value())
        def aggr_val(s): return s.adv_on() and s.aggr.isChecked() and s.mode_key() != "full"
        def frac_val(s): return (s.frac.value() if s.adv_on() else 100) / 100

        def on_adv(s, on):
            s.adv.setVisible(on); s.refresh()

        def on_pre(s, i):
            _, w, h = s.PRESETS[i]
            if w:
                s.w.blockSignals(True); s.h.blockSignals(True)
                s.w.setValue(w); s.h.setValue(h)
                s.w.blockSignals(False); s.h.blockSignals(False)
            s.refresh()

        def say(s, t): s.log.appendPlainText(t)

        def repolish(s, *ws):
            for w_ in ws: w_.style().unpolish(w_); w_.style().polish(w_)

        def refresh(s):
            Wd, Hd = s.w.value(), s.h.value()
            R = (Wd / Hd) / (16 / 9)
            g = math.gcd(Wd, Hd)
            s.mode.setEnabled(not (s.adv_on() and s.manual.isChecked()))
            s.extra.setEnabled(s.adv_on() and s.manual.isChecked())
            s.aggr.setEnabled(s.mode_key() != "full")
            s.info.setProperty("warn", R < 0.999)
            s.info.setText(tr("g_ratio", Wd / Hd, Wd // g, Hd // g, R) + (tr("g_narrow") if R < 0.999 else "") + (tr("g_169") if is_169(Wd, Hd) else ""))
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
                s.dmhex.setText("0x%x %s%s" % (info["dmem_mb"] * MB, tr("bytes"), "  " + tr("card_std") if not exp else ""))
                s.dmtxt.setText("⚠ " + tr("card_exp", info["dmem_mb"], info["dmem_mb"] - DMEM_BASE_MB) if exp else "✔ " + tr("card_ok"))
            except BudgetError as e:
                s.sum.setText("⚠ " + str(e)); s.go.setEnabled(False)
                s.card.setProperty("state", "warn"); s.dmbig.setText("—"); s.dmhex.setText("")
                s.dmtxt.setText(tr("card_bad"))
            s.repolish(s.card, s.dmbig, s.dmhex, s.dmtxt)

        def check(s):
            p = s.eboot.text()
            if not p: return
            try:
                bad = check_eboot(p)
                s.say(tr("eboot_ok") if not bad else tr("eboot_bad", ", ".join(bad)))
            except Exception as e:
                s.say(tr("eboot_fail", e))

        def run(s):
            Wd, Hd = s.w.value(), s.h.value(); R = (Wd / Hd) / (16 / 9)
            did = False; spv_done = False
            root = out_root(s.xmlin.text(), s.eboot.text(), s.spvin.text())
            try:
                if True:   # XML создаётся всегда (поля «Сохранить …» убраны)
                    base = open(s.xmlin.text(), encoding='utf-8').read() if s.xmlin.text() else None
                    out = out_xml_path(root, Wd, Hd)
                    os.makedirs(os.path.dirname(out), exist_ok=True)
                    x, rows, info = build_xml(Wd, Hd, base, s.aggr_val(), s.frac_val(), s.extra_val(),
                                              not (s.adv_on() and s.keep.isChecked()))
                    open(out, 'w', encoding='utf-8').write(x)
                    s.say(tr("log_xml", out)); s.say(tr("put_xml", xml_rel(Wd, Hd)))
                    if info["expanded"]: s.say("⚠ " + dmem_note(info))
                    did = True
                if s.spvin.text() and is_169(Wd, Hd):
                    s.say(tr("spv_skip169"))
                elif s.spvin.text():
                    res, msg = patch_spv(open(s.spvin.text(), 'rb').read(), R)
                    out = out_spv_path(s.spvin.text(), root)
                    os.makedirs(os.path.dirname(out), exist_ok=True)
                    open(out, 'wb').write(res)
                    s.say(tr("log_spv", msg, out)); s.say(tr("put_spv", os.path.join(SPV_REL, os.path.basename(out)))); s.say(tr("spv_cache")); did = spv_done = True
                if did: Q.QMessageBox.information(s, tr("done_title"), tr("done_msg") + "\n" + root + "\n\n" + tr("put_all") + ("\n\n" + tr("spv_cache") if spv_done else ""))
            except Exception as e:
                s.say(tr("err_prefix", e)); Q.QMessageBox.critical(s, tr("err_title"), str(e))

    w = Win(); w.show()
    shot = os.environ.get("TLOU_SHOT")        # отладка: сохранить скриншот окна и выйти
    if os.environ.get("TLOU_ADV"): w.advchk.setChecked(True)
    if shot:
        QtCore.QTimer.singleShot(300, lambda: (w.grab().save(shot), app.quit()))
    sys.exit(app.exec_())


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--cli", nargs=2, type=int, metavar=("W", "H"))
    ap.add_argument("--eboot"); ap.add_argument("--xml", nargs=2, metavar=("IN", "OUT"))
    ap.add_argument("--spv", nargs=2, metavar=("IN", "OUT")); ap.add_argument("--aggressive", action="store_true"); ap.add_argument("--extra", type=int, default=0, help="доп. direct-память сверх 4608 МБ (чётное число МБ)"); ap.add_argument("--dmem", action="store_true", help="режим с расширением dmem: CPU не урезается"); ap.add_argument("--keep-old", action="store_true", help="не отключать прежние разрешающие секции в базовом XML"); ap.add_argument("--frac", type=float, default=100.0, help="доля бюджета RT, зависящая от разрешения, %% (по умолчанию 100)")
    ap.add_argument("--lang", choices=["en", "ru", "uk"], help="язык интерфейса и описаний патча (по умолчанию - язык системы, иначе en)")
    a = ap.parse_args()
    LANG = a.lang or detect_lang()
    cli(a) if a.cli else gui()
