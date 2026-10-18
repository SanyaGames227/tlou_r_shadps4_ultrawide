#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TLOU Remastered (PS4, AppVer 01.11) - генератор патча любого разрешения / соотношения сторон
для shadPS4: XML-патч (eboot.bin) + замена SPIR-V шейдера видеороликов.

GUI (PyQt5):   python3 tlou_r_shadps4_ultrawide.py
CLI:           python3 tlou_r_shadps4_ultrawide.py --cli 2560 1080 --root <папка shadPS4> [--xml свой.xml] [--dmem] [--lang en|ru|uk]
Указывается только папка shadPS4: XML берётся/создаётся в user/patches, шейдер видео патчится в user/cache (ZIP игры или файлы)
либо создаётся в user/shader/patch из user/shader/dumps. Без --xml патч добавляется в актуальный XML с GitHub.
"""
import sys, os, re, struct, math, argparse, hashlib, shutil, zipfile, copy, time

MB = 1 << 20
AUTHOR = "sanyagames227"
TITLE_IDS = ["CUSA00552", "CUSA00556", "CUSA00557", "CUSA00559"]
BASE_W, BASE_H = 1920, 1080

# ----------------------------------------------------------------------------------------
# Оригинальные значения eboot.bin 01.11 (адрес в XML = vaddr + 0x400000)
# ----------------------------------------------------------------------------------------
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
  "xml_state": "XML file: %s",
  "sh_checking": "Video shader: checking...",
  "sh_found": "Video shader found (%s)",
  "sh_cache": "cache",
  "sh_dumps": "dumps",
  "sh_patch": "patch folder",
  "sh_none": "Video shader not found: play any cutscene with Shader Cache or Shader Dumping enabled",
  "games_found": "Games found: %s",
  "root_games": "Installed versions: %s",
  "no_change": "Area is not larger than 1920x1080 - no memory budget changes needed.",
  "res_w16": "The width must be a multiple of 16 (the game crashes otherwise). Nearest values: %d or %d.",
  "budget_gpu": "A resolution of %dx%d does not fit: the game cannot allocate more than %d MB of GPU memory (a hard limit, dmem does not help). The maximum for this aspect ratio is about %dx%d.",
  "budget_err": "A resolution of %dx%d requires %d MB of additional GPU memory, but only %d MB can be taken from CPU memory%s. Select the Extended memory mode or a lower resolution.",
  "no_aggr": "",
  "margin_note": "(margin reduced to 1.0)",
  "info_text": "GPU +%d MB, CPU -%d MB, total direct memory %d MB%s%s",
  "info_exp": "(expanded: the direct-memory constant is patched, shadPS4 needs enough dmem)",
  "info_orig": "(as in the original)",
  "dmem_ok": "Total direct memory: %d MB. Standard shadPS4 is sufficient.",
  "dmem_exp": "Total direct memory: %d MB (0x%x bytes) = 4608 + %d MB. shadPS4 must provide at least %d MB.",
  "card_exp": "Increase dmem in shadPS4 by +%d MB.",
  "card_ok": "Standard shadPS4 (4608 MB) is sufficient.",
  "gpu_cap_note": "(the game cannot allocate more than %d MB for GPU_MEMORY, so the resolution-dependent growth is limited to %d%%)",
  "c_169": "16:9: aspect, camera, HUD and video shader patches are not needed (only resolution and memory)",
  "g_169": "16:9: only resolution and memory are patched.",
  "c_res": "2. Resolution: %dx%d",
  "c_aspect": "3. Global aspect ratio %d:%d",
  "c_budget": "1. Memory budgets: %s",
  "c_row": "%s: was %.2f MB, now %.2f MB",
  "c_dmem_const": "Direct memory size (kAllocSystemDirect): 4608 MB, new value %d MB",
  "c_dmem_warn": "shadPS4 must provide at least %d MB of direct memory (dmem)",
  "c_clip": "4. Game camera clipping bounds: x * R, R=%.6f",
  "c_cam": "5. Render camera: cot(fov/2) / R",
  "c_ui": "6. HUD/UI quads: X scale 2/(1280*R), offset -1/R",
  "c_proj": "10. 3D: canvas projection: X * R",
  "c_font": "8. Font: canvas width 1280*R",
  "c_cross": "9. Crosshair (disp32: constant of block 8)",
  "c_dev": "7. Dev Menu UI",
  "c_icon": "11. Interact/pickup icons: world->canvas X * R (code cave)",
  "c_treasure": "12. Collectibles preview (pickup notification / inventory artifacts): scene camera fov keeps the 16:9 vertical view",
  "err_nopatch": "The base XML has no </Patch>",
  "spv_bad": "Corrupted SPIR-V",
  "spv_not": "This is not SPIR-V",
  "spv_uv": "UV calculation not found (CompositeConstruct: ImageSample). Is this the TLOU video shader?",
  "spv_uvs": "Unexpected UV structure",
  "spv_nof32": "No float32 type",
  "spv_noiw": "No OpImageWrite",
  "spv_notex": "Texel not found",
  "spv_already": "Shader was already patched (k=%.5f, b=%.5f): constants replaced with k=%.5f, b=%.5f",
  "spv_orig": "Original shader: inserted u' = u*%.5f + (%.5f), black mask outside [0,1]",
  "g_title": "TLOU Remastered — Ultrawide Patcher",
  "g_sub": "Resolution and aspect ratio patch for eboot.bin 01.11 and the cutscene video shader (shadPS4)",
  "g_res": "Resolution",
  "g_width": "Width:",
  "g_height": "Height:",
  "g_custom": "Custom…",
  "g_max": "Max",
  "g_max_tip": "Set the maximum resolution for this aspect ratio",
  "g_ratio": "Aspect ratio: %d:%d (%.2f:1)",
  "g_narrow": "Narrower than 16:9: HUD edges will be cropped.",
  "g_browse": "Browse…",
  "g_refresh": "Refresh",
  "g_refresh_tip": "Re-check the XML file and shader cache without restarting",
  "g_keep": "Keep my custom patches",
  "kc_log": "Custom patches kept: %d; enabled states restored: %d.",
  "kc_dup": "Replaced old patches of the same resolution: %d.",
  "g_mem": "Memory budget",
  "bytes": "bytes",
  "g_go": "Create patch",
  "done_title": "Completed",
  "err_title": "Error",
  "err_prefix": "Error: %s",
  "log_spv": "Shader patch saved: %s, location: %s",
  "gh_fetch": "Downloading the current file from GitHub...",
  "gh_ok": "Downloaded: %d bytes, patches in file: %d",
  "gh_added": "Patch «%s» added to the end of the file.",
  "gh_updated": "Patch «%s» was outdated (%d lines, now %d) and has been replaced.",
  "gh_off": "Previous resolution patches disabled: %d",
  "gh_same": "Patch «%s» is already present in the GitHub file and is identical.",
  "gh_conflict": "The GitHub file already contains a patch «%s» with a different set of lines (%d, patcher: %d). The file was not modified.",
  "gh_fail": "Failed to download the file from GitHub: %s",
  "gh_bad": "unexpected file contents",
  "gh_man_msg": "The patch block was saved to:\n%s\n\nOpen TheLastOfUsRemastered.xml (user/patches) in a text editor and insert the block before the closing </Patch> tag.",
  "warn_title": "Notice",
  "cache_scan": "Scanning: %s",
  "cache_stat": "Files checked: %d, matching size: %d, confirmed by SHA-256: %d",
  "cache_hit_orig": "Original video shader found: %s",
  "cache_hit_patched": "Previously patched video shader found: %s",
  "cache_backup": "Backup of the original: %s",
  "cache_zip": "Rewriting the archive...",
  "cache_done": "Shader patched: files %d (%dx%d).",
  "cache_reset": "Shader reset to default (16:9): files %d.",
  "cache_same": "Shader is already patched for %dx%d.",
  "cache_skip169": "Shader patch is not required for 16:9.",
  "cache_nf_log": "Video shader not found.",
  "cache_err_path": "Path not found: %s",
  "cache_err_type": "The specified file is not a ZIP archive: %s",
  "cache_err_write": "Failed to write to the shader cache: %s\nClose the game and shadPS4 and try again.",
  "cache_err_verify": "Verification after writing failed; the original archive was not modified.",
  "dm_short": "Required dmem in shadPS4: at least %d MB",
  "g_root": "shadPS4 folder",
  "ph_root": "Select the shadPS4 folder (the one containing «user»)",
  "root_info": "shadPS4 folder recognized. XML: %s; shader cache: %s; shader dumps: %s",
  "yes_f": "found",
  "no_f": "not found",
  "root_bad": "The «user» folder was not found. Select the shadPS4 folder.",
  "g_src": "XML patch",
  "src_gh": "Download from GitHub and add the patch (recommended)",
  "src_own": "Use a custom XML file",
  "src_own_hint": "The patch will be added to the selected file; the result will be saved to the shadPS4 folder.",
  "ph_own": "XML file",
  "sh_info": "Video shader is patched automatically.\nShader cache in use: the cached shader is patched (play any cutscene beforehand: Options > Credits).\nShader cache not in use: enable Shader Dumping in shadPS4 and play a cutscene; the shader patch is created automatically.",
  "sh_nf": "Video shader not found. Enable Shader Cache or Shader Dumping in shadPS4, play any cutscene (Options > Credits), close the game and run the patcher again.",
  "confirm_title": "Confirmation",
  "confirm_msg": "The following files will be replaced. Backup copies are saved next to the program.\n\n%s\n\nContinue?",
  "cancelled": "Operation cancelled. No changes were made.",
  "xml_new": "XML file created: %s",
  "xml_repl": "XML file updated: %s",
  "xml_same": "XML file is up to date: %s",
  "done_msg2": "In shadPS4, enable the patch «%s» (right-click the game > Cheats / Patches).",
  "mode_ext": "Extended: CPU memory is preserved (recommended)",
  "mode_std": "Standard: CPU memory is reduced",
  "mode_ext_d": "GPU gets more memory, CPU memory stays untouched. Supported by all recent shadPS4 builds.",
  "mode_std_d": "GPU memory is taken from CPU memory (sound, loading, screenshots). Works with stock shadPS4, rare instability possible.",
 },
 "ru": {
  "xml_state": "Файл XML: %s",
  "sh_checking": "Шейдер видео: проверка...",
  "sh_found": "Шейдер видео найден (%s)",
  "sh_cache": "кэш",
  "sh_dumps": "дампы",
  "sh_patch": "папка патчей",
  "sh_none": "Шейдер видео не найден: запустите катсцену при включённом Shader Cache или Shader Dumping",
  "games_found": "Найдены версии игры: %s",
  "root_games": "Установленные версии игры: %s",
  "no_change": "Площадь не больше 1920x1080 - бюджеты памяти менять не нужно.",
  "res_w16": "Ширина должна быть кратна 16 (иначе игра вылетает). Ближайшие значения: %d и %d.",
  "budget_gpu": "Разрешение %dx%d не помещается: игра не может выделить GPU-память больше %d МБ (жёсткий лимит, dmem не поможет). Максимум для этого соотношения сторон — примерно %dx%d.",
  "budget_err": "Для разрешения %dx%d требуется дополнительно %d МБ памяти GPU, однако у CPU можно безопасно забрать только %d МБ%s. Выберите расширенный режим памяти или меньшее разрешение.",
  "no_aggr": "",
  "margin_note": "(запас уменьшен до 1.0)",
  "info_text": "GPU +%d МБ, CPU -%d МБ, общая direct-память %d МБ%s%s",
  "info_exp": "(расширена: патчится константа direct-памяти, shadPS4 должен отдавать достаточный dmem)",
  "info_orig": "(как в оригинале)",
  "dmem_ok": "Итоговая прямая память: %d МБ. Стандартной сборки shadPS4 достаточно.",
  "dmem_exp": "Итоговая прямая память: %d МБ (0x%x байт) = 4608 + %d МБ. shadPS4 должен предоставлять не менее %d МБ.",
  "card_exp": "Увеличьте dmem в shadPS4 на +%d МБ.",
  "card_ok": "Стандартной сборки shadPS4 (4608 МБ) достаточно.",
  "gpu_cap_note": "(игра не может выделить GPU_MEMORY больше %d МБ, поэтому рост, зависящий от разрешения, ограничен до %d%%)",
  "c_169": "16:9: правки аспекта, камеры, HUD и шейдера видео не нужны (только разрешение и память)",
  "g_169": "16:9: изменяются только разрешение и память.",
  "c_res": "2. Разрешение: %dx%d",
  "c_aspect": "3. Глобальный аспект %d:%d",
  "c_budget": "1. Бюджеты памяти: %s",
  "c_row": "%s: было %.2f МБ, стало %.2f МБ",
  "c_dmem_const": "Размер прямой памяти (kAllocSystemDirect): 4608 МБ, новое значение %d МБ",
  "c_dmem_warn": "shadPS4 должен предоставлять не менее %d МБ прямой памяти (dmem)",
  "c_clip": "4. Рамки отсечения игровой камеры: x * R, R=%.6f",
  "c_cam": "5. Рендер-камера: cot(fov/2) / R",
  "c_ui": "6. HUD/UI-квады: масштаб X 2/(1280*R), смещение -1/R",
  "c_proj": "10. Проекция 3D: канва: X * R",
  "c_font": "8. Шрифт: ширина канвы 1280*R",
  "c_cross": "9. Прицел (disp32: константа блока 8)",
  "c_dev": "7. Dev Menu UI",
  "c_icon": "11. Иконки взаимодействия/подбора: проекция мир->канвас X * R (code cave)",
  "c_treasure": "12. Превью коллекционных предметов (уведомление о подборе / артефакты в инвентаре): fov камеры сцены сохраняет вертикальный обзор 16:9",
  "err_nopatch": "В базовом XML нет </Patch>",
  "spv_bad": "Битый SPIR-V",
  "spv_not": "Это не SPIR-V",
  "spv_uv": "Не найден расчёт UV (CompositeConstruct: ImageSample). Это шейдер видео TLOU?",
  "spv_uvs": "Неожиданная структура UV",
  "spv_nof32": "Нет типа float32",
  "spv_noiw": "Нет OpImageWrite",
  "spv_notex": "Не найден texel",
  "spv_already": "Шейдер уже был пропатчен (k=%.5f, b=%.5f): константы заменены на k=%.5f, b=%.5f",
  "spv_orig": "Шейдер оригинальный: вставлено u' = u*%.5f + (%.5f), чёрная маска вне [0,1]",
  "g_title": "TLOU Remastered — Ultrawide Patcher",
  "g_sub": "Патч разрешения и соотношения сторон для eboot.bin 01.11 и шейдера видеороликов (shadPS4)",
  "g_res": "Разрешение",
  "g_width": "Ширина:",
  "g_height": "Высота:",
  "g_custom": "Свой…",
  "g_max": "Макс.",
  "g_max_tip": "Подставить максимальное разрешение для этого соотношения сторон",
  "g_ratio": "Соотношение сторон: %d:%d (%.2f:1)",
  "g_narrow": "Уже 16:9: края HUD будут обрезаны.",
  "g_browse": "Обзор…",
  "g_refresh": "Обновить",
  "g_refresh_tip": "Перепроверить XML и кэш шейдеров без перезапуска программы",
  "g_keep": "Сохранить мои кастомные патчи",
  "kc_log": "Сохранено кастомных патчей: %d; восстановлено состояний включения: %d.",
  "kc_dup": "Заменено старых патчей этого же разрешения: %d.",
  "g_mem": "Бюджет памяти",
  "bytes": "байт",
  "g_go": "Создать патч",
  "done_title": "Завершено",
  "err_title": "Ошибка",
  "err_prefix": "Ошибка: %s",
  "log_spv": "Патч шейдера сохранён: %s, расположение: %s",
  "gh_fetch": "Загрузка актуального файла с GitHub...",
  "gh_ok": "Загружено: %d байт, патчей в файле: %d",
  "gh_added": "Патч «%s» добавлен в конец файла.",
  "gh_updated": "Патч «%s» устарел (строк: %d, стало: %d) и заменён.",
  "gh_off": "Отключено прежних патчей разрешения: %d",
  "gh_same": "Патч «%s» уже присутствует в файле на GitHub и идентичен.",
  "gh_conflict": "Файл на GitHub уже содержит патч «%s» с другим набором строк (%d, в патчере: %d). Файл не изменён.",
  "gh_fail": "Не удалось загрузить файл с GitHub: %s",
  "gh_bad": "непредвиденное содержимое файла",
  "gh_man_msg": "Блок патча сохранён в файл:\n%s\n\nОткройте TheLastOfUsRemastered.xml (user/patches) в текстовом редакторе и вставьте блок перед закрывающим тегом </Patch>.",
  "warn_title": "Уведомление",
  "cache_scan": "Сканирование: %s",
  "cache_stat": "Проверено файлов: %d, совпал размер: %d, подтверждено SHA-256: %d",
  "cache_hit_orig": "Найден оригинальный шейдер видео: %s",
  "cache_hit_patched": "Найден ранее пропатченный шейдер видео: %s",
  "cache_backup": "Резервная копия оригинала: %s",
  "cache_zip": "Пересборка архива...",
  "cache_done": "Шейдер пропатчен: файлов %d (%dx%d).",
  "cache_reset": "Шейдер приведён к исходному виду (16:9): файлов %d.",
  "cache_same": "Шейдер уже пропатчен под %dx%d.",
  "cache_skip169": "Для 16:9 патч шейдера не требуется.",
  "cache_nf_log": "Шейдер видео не найден.",
  "cache_err_path": "Путь не найден: %s",
  "cache_err_type": "Указанный файл не является ZIP-архивом: %s",
  "cache_err_write": "Не удалось выполнить запись в кэш шейдеров: %s\nЗакройте игру и shadPS4 и повторите попытку.",
  "cache_err_verify": "Проверка после записи не пройдена; исходный архив не изменён.",
  "dm_short": "Требуемый dmem в shadPS4: не менее %d МБ",
  "g_root": "Папка shadPS4",
  "ph_root": "Укажите папку shadPS4 (содержащую «user»)",
  "root_info": "Папка shadPS4 распознана. XML: %s; кэш шейдеров: %s; дампы шейдеров: %s",
  "yes_f": "найден",
  "no_f": "не найден",
  "root_bad": "Папка «user» не найдена. Укажите папку shadPS4.",
  "g_src": "XML-патч",
  "src_gh": "Загрузить с GitHub и добавить патч (рекомендуется)",
  "src_own": "Использовать собственный XML-файл",
  "src_own_hint": "Патч будет добавлен в выбранный файл, результат будет сохранён в папку shadPS4.",
  "ph_own": "XML-файл",
  "sh_info": "Шейдер видео патчится автоматически.\nПри использовании кэша шейдеров патчится закэшированный шейдер (предварительно запустите любую катсцену: Options > Credits).\nБез кэша шейдеров включите Shader Dumping в shadPS4 и запустите катсцену; патч шейдера будет создан автоматически.",
  "sh_nf": "Шейдер видео не найден. Включите Shader Cache или Shader Dumping в shadPS4, запустите любую катсцену (Options > Credits), закройте игру и повторите запуск патчера.",
  "confirm_title": "Подтверждение",
  "confirm_msg": "Следующие файлы будут заменены. Резервные копии сохраняются рядом с программой.\n\n%s\n\nПродолжить?",
  "cancelled": "Операция отменена. Изменения не внесены.",
  "xml_new": "Файл XML создан: %s",
  "xml_repl": "Файл XML обновлён: %s",
  "xml_same": "Файл XML актуален: %s",
  "done_msg2": "В shadPS4 включите патч «%s» (правой кнопкой по игре > Cheats / Patches).",
  "mode_ext": "Расширенный: память CPU сохраняется (рекомендуется)",
  "mode_std": "Стандартный: память CPU уменьшается",
  "mode_ext_d": "GPU получает больше памяти, CPU-память не трогается. Поддерживается всеми актуальными сборками shadPS4.",
  "mode_std_d": "Память GPU берётся из CPU-памяти (звук, загрузка, скриншоты). Работает со стоковым shadPS4, возможна редкая нестабильность.",
 },
 "uk": {
  "xml_state": "Файл XML: %s",
  "sh_checking": "Шейдер відео: перевірка...",
  "sh_found": "Шейдер відео знайдено (%s)",
  "sh_cache": "кеш",
  "sh_dumps": "дампи",
  "sh_patch": "тека патчів",
  "sh_none": "Шейдер відео не знайдено: запустіть катсцену при ввімкненому Shader Cache або Shader Dumping",
  "games_found": "Знайдено версії гри: %s",
  "root_games": "Встановлені версії гри: %s",
  "no_change": "Площа не більша за 1920x1080 - бюджети пам'яті змінювати не потрібно.",
  "res_w16": "Ширина має бути кратна 16 (інакше гра вилітає). Найближчі значення: %d і %d.",
  "budget_gpu": "Роздільна здатність %dx%d не вміщується: гра не може виділити GPU-пам'яті більше %d МБ (жорсткий ліміт, dmem не допоможе). Максимум для цього співвідношення сторін — приблизно %dx%d.",
  "budget_err": "Для роздільної здатності %dx%d потрібно додатково %d МБ пам'яті GPU, проте у CPU можна безпечно забрати лише %d МБ%s. Виберіть розширений режим пам'яті або меншу роздільну здатність.",
  "no_aggr": "",
  "margin_note": "(запас зменшено до 1.0)",
  "info_text": "GPU +%d МБ, CPU -%d МБ, загальна direct-пам'ять %d МБ%s%s",
  "info_exp": "(розширена: патчиться константа direct-пам'яті, shadPS4 має віддавати достатній dmem)",
  "info_orig": "(як в оригіналі)",
  "dmem_ok": "Підсумкова пряма пам'ять: %d МБ. Стандартної збірки shadPS4 достатньо.",
  "dmem_exp": "Підсумкова пряма пам'ять: %d МБ (0x%x байт) = 4608 + %d МБ. shadPS4 має надавати щонайменше %d МБ.",
  "card_exp": "Збільште dmem у shadPS4 на +%d МБ.",
  "card_ok": "Стандартної збірки shadPS4 (4608 МБ) достатньо.",
  "gpu_cap_note": "(гра не може виділити GPU_MEMORY більше %d МБ, тому зростання, що залежить від роздільної здатності, обмежено до %d%%)",
  "c_169": "16:9: правки співвідношення, камери, HUD та шейдера відео не потрібні (лише роздільна здатність і пам'ять)",
  "g_169": "16:9: змінюються лише роздільна здатність і пам'ять.",
  "c_res": "2. Роздільна здатність: %dx%d",
  "c_aspect": "3. Глобальне співвідношення сторін %d:%d",
  "c_budget": "1. Бюджети пам'яті: %s",
  "c_row": "%s: було %.2f МБ, стало %.2f МБ",
  "c_dmem_const": "Розмір прямої пам'яті (kAllocSystemDirect): 4608 МБ, нове значення %d МБ",
  "c_dmem_warn": "shadPS4 має надавати щонайменше %d МБ прямої пам'яті (dmem)",
  "c_clip": "4. Рамки відсікання ігрової камери: x * R, R=%.6f",
  "c_cam": "5. Рендер-камера: cot(fov/2) / R",
  "c_ui": "6. HUD/UI-квади: масштаб X 2/(1280*R), зміщення -1/R",
  "c_proj": "10. Проєкція 3D: полотно: X * R",
  "c_font": "8. Шрифт: ширина полотна 1280*R",
  "c_cross": "9. Приціл (disp32: константа блока 8)",
  "c_dev": "7. Dev Menu UI",
  "c_icon": "11. Іконки взаємодії/підбору: проєкція світ->канвас X * R (code cave)",
  "c_treasure": "12. Превʼю колекційних предметів (сповіщення про підбір / артефакти в інвентарі): fov камери сцени зберігає вертикальний огляд 16:9",
  "err_nopatch": "У базовому XML немає </Patch>",
  "spv_bad": "Пошкоджений SPIR-V",
  "spv_not": "Це не SPIR-V",
  "spv_uv": "Не знайдено розрахунок UV (CompositeConstruct: ImageSample). Це шейдер відео TLOU?",
  "spv_uvs": "Неочікувана структура UV",
  "spv_nof32": "Немає типу float32",
  "spv_noiw": "Немає OpImageWrite",
  "spv_notex": "Не знайдено texel",
  "spv_already": "Шейдер уже було пропатчено (k=%.5f, b=%.5f): константи замінено на k=%.5f, b=%.5f",
  "spv_orig": "Шейдер оригінальний: вставлено u' = u*%.5f + (%.5f), чорна маска поза [0,1]",
  "g_title": "TLOU Remastered — Ultrawide Patcher",
  "g_sub": "Патч роздільної здатності та співвідношення сторін для eboot.bin 01.11 і шейдера відеороликів (shadPS4)",
  "g_res": "Роздільна здатність",
  "g_width": "Ширина:",
  "g_height": "Висота:",
  "g_custom": "Власна…",
  "g_max": "Макс.",
  "g_max_tip": "Підставити максимальну роздільну здатність для цього співвідношення сторін",
  "g_ratio": "Співвідношення сторін: %d:%d (%.2f:1)",
  "g_narrow": "Вужче за 16:9: краї HUD будуть обрізані.",
  "g_browse": "Огляд…",
  "g_refresh": "Оновити",
  "g_refresh_tip": "Перевірити XML і кеш шейдерів повторно без перезапуску програми",
  "g_keep": "Зберегти мої кастомні патчі",
  "kc_log": "Збережено кастомних патчів: %d; відновлено станів увімкнення: %d.",
  "kc_dup": "Замінено старих патчів цієї ж роздільної здатності: %d.",
  "g_mem": "Бюджет пам'яті",
  "bytes": "байт",
  "g_go": "Створити патч",
  "done_title": "Завершено",
  "err_title": "Помилка",
  "err_prefix": "Помилка: %s",
  "log_spv": "Патч шейдера збережено: %s, розташування: %s",
  "gh_fetch": "Завантаження актуального файлу з GitHub...",
  "gh_ok": "Завантажено: %d байт, патчів у файлі: %d",
  "gh_added": "Патч «%s» додано наприкінці файлу.",
  "gh_updated": "Патч «%s» застарів (рядків: %d, стало: %d) і замінений.",
  "gh_off": "Вимкнено попередніх патчів роздільної здатності: %d",
  "gh_same": "Патч «%s» уже присутній у файлі на GitHub і ідентичний.",
  "gh_conflict": "Файл на GitHub уже містить патч «%s» з іншим набором рядків (%d, у патчері: %d). Файл не змінено.",
  "gh_fail": "Не вдалося завантажити файл з GitHub: %s",
  "gh_bad": "неочікуваний вміст файлу",
  "gh_man_msg": "Блок патча збережено у файл:\n%s\n\nВідкрийте TheLastOfUsRemastered.xml (user/patches) у текстовому редакторі та вставте блок перед закривним тегом </Patch>.",
  "warn_title": "Повідомлення",
  "cache_scan": "Сканування: %s",
  "cache_stat": "Перевірено файлів: %d, збігся розмір: %d, підтверджено SHA-256: %d",
  "cache_hit_orig": "Знайдено оригінальний шейдер відео: %s",
  "cache_hit_patched": "Знайдено раніше пропатчений шейдер відео: %s",
  "cache_backup": "Резервна копія оригіналу: %s",
  "cache_zip": "Перезбирання архіву...",
  "cache_done": "Шейдер пропатчено: файлів %d (%dx%d).",
  "cache_reset": "Шейдер приведено до вихідного вигляду (16:9): файлів %d.",
  "cache_same": "Шейдер уже пропатчено під %dx%d.",
  "cache_skip169": "Для 16:9 патч шейдера не потрібен.",
  "cache_nf_log": "Шейдер відео не знайдено.",
  "cache_err_path": "Шлях не знайдено: %s",
  "cache_err_type": "Указаний файл не є ZIP-архівом: %s",
  "cache_err_write": "Не вдалося виконати запис у кеш шейдерів: %s\nЗакрийте гру та shadPS4 і повторіть спробу.",
  "cache_err_verify": "Перевірка після запису не пройдена; вихідний архів не змінено.",
  "dm_short": "Необхідний dmem у shadPS4: щонайменше %d МБ",
  "g_root": "Тека shadPS4",
  "ph_root": "Вкажіть теку shadPS4 (що містить «user»)",
  "root_info": "Теку shadPS4 розпізнано. XML: %s; кеш шейдерів: %s; дампи шейдерів: %s",
  "yes_f": "знайдено",
  "no_f": "не знайдено",
  "root_bad": "Теку «user» не знайдено. Вкажіть теку shadPS4.",
  "g_src": "XML-патч",
  "src_gh": "Завантажити з GitHub і додати патч (рекомендовано)",
  "src_own": "Використати власний XML-файл",
  "src_own_hint": "Патч буде додано до вибраного файлу, результат буде збережено в теку shadPS4.",
  "ph_own": "XML-файл",
  "sh_info": "Шейдер відео патчиться автоматично.\nПри використанні кешу шейдерів патчиться закешований шейдер (попередньо запустіть будь-яку катсцену: Options > Credits).\nБез кешу шейдерів увімкніть Shader Dumping у shadPS4 і запустіть катсцену; патч шейдера буде створено автоматично.",
  "sh_nf": "Шейдер відео не знайдено. Увімкніть Shader Cache або Shader Dumping у shadPS4, запустіть будь-яку катсцену (Options > Credits), закрийте гру та повторіть запуск патчера.",
  "confirm_title": "Підтвердження",
  "confirm_msg": "Наступні файли буде замінено. Резервні копії зберігаються поруч із програмою.\n\n%s\n\nПродовжити?",
  "cancelled": "Операцію скасовано. Зміни не внесено.",
  "xml_new": "Файл XML створено: %s",
  "xml_repl": "Файл XML оновлено: %s",
  "xml_same": "Файл XML актуальний: %s",
  "done_msg2": "У shadPS4 увімкніть патч «%s» (правою кнопкою по грі > Cheats / Patches).",
  "mode_ext": "Розширений: пам'ять CPU зберігається (рекомендовано)",
  "mode_std": "Стандартний: пам'ять CPU зменшується",
  "mode_ext_d": "GPU отримує більше пам'яті, CPU-пам'ять не чіпається. Підтримується всіма актуальними збірками shadPS4.",
  "mode_std_d": "Пам'ять GPU береться з CPU-пам'яті (звук, завантаження, скріншоти). Працює зі стоковим shadPS4, можлива рідкісна нестабільність.",
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
    if W % 16:                                   # ассерт игры: displaySize.m_w % 16 == 0
        lo = W // 16 * 16
        raise BudgetError(tr("res_w16", lo if lo >= 16 else 16, lo + 16))
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
        if D > gpu_room:                     # потолок 4 GiB: урезать рост render target нельзя (игра падает: Render Target Heap out of memory)
            area0 = area
            for pct in range(99, 0, -1):     # максимум, который помещается (с проверенным запасом)
                area = 1.0 + (area0 - 1.0) * pct / 100
                nw, D = plan(mg)
                if D <= gpu_room: break
            k = math.sqrt(area / ((W * H) / (BASE_W * BASE_H)))
            wmax = int(W * k) // 16 * 16             # ширина кратна 16 (требование игры)
            raise BudgetError(tr("budget_gpu", W, H, GPU_MAX_MB, wmax, int(wmax * H / W) // 2 * 2))
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


def max_res(W, H, extra=0):
    """Максимальное разрешение с тем же соотношением сторон: ширина кратна 16, проходит calc_budget."""
    def ok(n):
        w = n * 16; h = max(2, int(w * H / W) // 2 * 2)
        try: calc_budget(w, h, False, 1.0, None, extra); return True
        except BudgetError: return False
    lo, hi = 40, 1024                            # ширина 640..16384
    if not ok(lo): return W, H
    while lo < hi:
        m = (lo + hi + 1) // 2
        if ok(m): lo = m
        else: hi = m - 1
    w = lo * 16
    return w, max(2, int(w * H / W) // 2 * 2)


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
    if R < 0.999:
        note += " NOTE: aspect ratio narrower than 16:9 - the UI (HUD) will be cropped at the edges."
    note = note.replace('&', '&amp;').replace('"', '&quot;').replace('<', '&lt;')
    return ('    <Metadata Title="The Last of Us Remastered" Name="%s" Note="%s" Author="%s" '
            'PatchVer="1.0" AppVer="01.11" AppElf="eboot.bin" isEnabled="true">\n    <PatchList>\n%s\n'
            '    </PatchList>\n    </Metadata>\n' % (patch_name(W, H), note, AUTHOR, lines_to_text(L))), rows, info


def build_xml(W, H, base_text=None, aggressive=False, frac=1.0, extra=0, disable_old=True):
    meta, rows, info = make_metadata(W, H, aggressive, frac, extra)
    if base_text:
        x = re.sub(r'[ \t]*<Metadata[^>]*Author="%s"[^>]*>.*?</Metadata>[ \t]*\r?\n?' % AUTHOR, '', base_text, flags=re.S)

        x = re.sub(r'[ \t]*<Metadata\b.*?</Metadata>[ \t]*\r?\n?',
                   lambda m: "" if same_res(m.group(0), W, H) else m.group(0), x, flags=re.S)

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
ADDR_RES_H = 0x156bfdc               # адрес высоты экрана


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


def _set_enabled(block, val):
    tag = _open_tag(block)
    if re.search(r'isEnabled\s*=\s*"[^"]*"', tag):
        nt = re.sub(r'(isEnabled\s*=\s*)"[^"]*"', lambda m: '%s"%s"' % (m.group(1), val), tag, count=1)
    else:
        nt = tag[:-1].rstrip() + ' isEnabled="%s">' % val
    return nt + block[len(tag):]


def _key(blk):
    at = _attrs(_open_tag(blk))
    return (at.get("Name", ""), at.get("AppVer", ""), at.get("AppElf", ""))


def same_res(blk, W, H):
    """Патч задаёт ровно такое же разрешение W x H (ширина и высота)."""
    p = _pairs(blk)
    return (ADDR_RES, u32(W)) in p and (ADDR_RES_H, u32(H)) in p


def preserve_custom(new, old, W, H):
    """Переносит из прежнего XML пользователя: состояние isEnabled патчей, которые есть и в новом файле,
    а также патчи, которых в новом файле нет (кастомные), вместе с их состоянием.
    Прежние патчи другого разрешения переносятся выключенными; патчи того же разрешения W x H - дубликаты,
    они не переносятся (актуальный патч создаётся заново).
    Возвращает (текст, dict(states, custom, dup))."""
    name = patch_name(W, H)
    old_blocks = BLOCK_RE.findall(old)
    old_first = {}
    for b in old_blocks: old_first.setdefault(_key(b), b)
    new_keys = {_key(b) for b in BLOCK_RE.findall(new)}
    st = dict(states=0, custom=0, dup=0)

    def restore(m):
        blk = m.group(0)
        if _attrs(_open_tag(blk)).get("Name") == name: return blk      # наш новый патч всегда включён
        o = old_first.get(_key(blk))
        if o is None: return blk
        ov = _attrs(_open_tag(o)).get("isEnabled")
        if ov is not None and ov.lower() != _attrs(_open_tag(blk)).get("isEnabled", "").lower():
            blk = _set_enabled(blk, ov); st["states"] += 1
        return blk

    def clash(blk):                              # разрешающий патч не от нас не должен быть включён вместе с нашим
        at = _attrs(_open_tag(blk))
        if at.get("Name") == name or at.get("AppVer") != "01.11" or at.get("isEnabled", "").lower() != "true": return blk
        if not any(a == ADDR_RES for a, _ in _pairs(blk)): return blk
        return _set_enabled(blk, "false")
    text = BLOCK_RE.sub(restore, new)
    extra = []
    for b in old_blocks:
        if _key(b) in new_keys: continue
        if same_res(b, W, H): st["dup"] += 1; continue          # дубликат выбранного разрешения - заменяется новым
        extra.append(clash(b))
    text = BLOCK_RE.sub(lambda m: clash(m.group(0)), text)
    if extra:
        nl = "\r\n" if "\r\n" in text else "\n"
        i = text.rfind("</Patch>")
        pre = "" if i == 0 or text[i - 1] in "\r\n" else nl
        chunk = nl.join("    " + b.replace("\r\n", "\n").replace("\n", nl) for b in extra)
        text = text[:i] + pre + chunk + nl + text[i:]
        st["custom"] = len(extra)
    return text, st


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
    res["base"] = base
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


def patch_cache(path, W, H, backup_dir, log=print, patch_dir=None, dry=False):
    """Находит шейдер видео в кэше (папка или ZIP) и патчит его под W×H.
    Возвращает dict(status=patched|reset|same|skip169|notfound, changed=N, text=итоговая строка)."""
    path = os.path.abspath(os.path.expanduser(path.strip().strip('"')))
    if not os.path.exists(path):
        raise CacheError(tr("cache_err_path", path))
    single = os.path.isfile(path) and path.lower().endswith(".spv")
    is_zip = os.path.isfile(path) and not single
    if is_zip and not zipfile.is_zipfile(path):
        raise CacheError(tr("cache_err_type", path))
    # дампы шейдеров (папка dumps или одиночный .spv): исходник не трогаем, результат кладём в user/shader/patch
    dump_mode = bool(patch_dir) and (single or (not is_zip and "dumps" in [x.lower() for x in path.replace("\\", "/").split("/")]))
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
            label = lambda key: "%s: %s" % (os.path.basename(path), infos[key].filename)
        finally:
            zf.close()
    else:
        walk = [(os.path.dirname(path), [], [os.path.basename(path)])] if single else os.walk(path)
        for dp, _, fns in walk:
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
        label = (lambda key: os.path.basename(key)) if single else (lambda key: os.path.relpath(key, path))
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

    if dry:                                              # только список файлов, которые будут заменены
        tg = [os.path.join(patch_dir, os.path.basename(k)) for k, _, _, _ in plan] if dump_mode else [label(k) for k, _, _, _ in plan]
        return dict(status="plan", changed=len(plan), targets=[t for t in tg if not dump_mode or os.path.exists(t)], text="")
    if dump_mode:
        os.makedirs(patch_dir, exist_ok=True)
        for key, _, _, new in plan:
            out = os.path.join(patch_dir, os.path.basename(key))
            with open(out, 'wb') as f: f.write(new)
            log(tr("log_spv", os.path.basename(key), out))
        return dict(status="patched", dump=True, changed=len(plan),
                    text=tr("cache_done", len(plan), W, H))
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
# Автоматическая работа с папкой shadPS4
# ----------------------------------------------------------------------------------------
SPV_REL = os.path.join("user", "shader", "patch")


def block_rel(W, H): return "ManualInsert_%dx%d.txt" % (W, H)      # вне user/, чтобы не попасть в папку патчей эмулятора


def app_dir():
    return os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))


CFG_FILE = "tlou_r_shadps4_ultrawide.json"


def load_cfg():
    try:
        import json
        with open(os.path.join(app_dir(), CFG_FILE), encoding='utf-8') as f: return json.load(f)
    except Exception:
        return {}


def save_cfg(d):
    try:
        import json
        with open(os.path.join(app_dir(), CFG_FILE), 'w', encoding='utf-8') as f: json.dump(d, f, ensure_ascii=False, indent=1)
    except OSError:
        pass


def out_root():
    """Папка ShadPS4 рядом с exe (или python-файлом): сюда пишутся бэкапы и блок для ручной вставки."""
    return os.path.join(app_dir(), "ShadPS4")


def find_xml(root):
    for d in (os.path.join(root, "user", "patches"), os.path.join(root, "user", "patches", "shadPS4")):
        if os.path.isdir(d):
            for f in os.listdir(d):
                if f.lower() == GH_FILE.lower() and os.path.isfile(os.path.join(d, f)):
                    return os.path.join(d, f)
    return None


def detect_games(root):
    """Установленные версии игры (CUSA из TITLE_IDS): по именам папок/файлов в user (cache, game_data, savedata и т.д.)."""
    found = set(); base = os.path.join(root, "user")
    for dp, dn, fn in os.walk(base):
        if dp[len(base):].count(os.sep) >= 3: dn[:] = []
        for n in dn + fn:
            for t in TITLE_IDS:
                if t in n.upper(): found.add(t)
    return sorted(found)


def ensure_ids(xml, ids):
    """Добавляет в <TitleID> недостающие CUSA установленных версий (патч применяется ко всем)."""
    m = re.search(r'(<TitleID>)(.*?)(</TitleID>)', xml, re.S)
    if not m: return xml
    miss = [i for i in ids if i not in m.group(2)]
    if not miss: return xml
    nl = "\r\n" if "\r\n" in xml else "\n"
    add = "".join("        <ID>%s</ID>%s" % (i, nl) for i in miss)
    body = m.group(2).rstrip(" \t") 
    body = body if body.endswith(("\n",)) or not body.strip() else body + nl
    return xml[:m.start(2)] + body + add + "    " + xml[m.end(2):]


def xml_default(root): return os.path.join(root, "user", "patches", GH_FILE)


def patch_shader_auto(root, W, H, log=print, dry=False):
    """Кэш (user/cache: ZIP игры, иначе файлы папки) патчится на месте; дампы (user/shader/dumps) -> user/shader/patch."""
    cache = os.path.join(root, "user", "cache")
    dumps = os.path.join(root, "user", "shader", "dumps")
    patch_dir = os.path.join(root, SPV_REL)
    backup = os.path.join(out_root(), "backup")
    lg = (lambda *a: None) if dry else log
    out = dict(found=False, cache=False, dumps=False, patch=False, targets=[], texts=[], changed=0)

    def run(src):
        r = patch_cache(src, W, H, backup, lg, patch_dir, dry)
        if r["status"] != "notfound":
            out["found"] = True; out["dumps" if src == dumps else "patch" if src == patch_dir else "cache"] = True
        tg = r.get("targets", [])
        if src == patch_dir:                             # не дублируем файлы, уже учтённые при обработке дампов
            have = {os.path.basename(t) for t in out["targets"]}
            tg = [os.path.join(patch_dir, t) for t in tg if os.path.basename(t) not in have]
        out["targets"] += tg; out["changed"] += r["changed"]
        if not dry: out["texts"].append(r["text"])
        return r["status"] != "notfound"
    if os.path.isdir(cache):
        zips = [os.path.join(cache, f) for f in sorted(os.listdir(cache))
                if f.lower().endswith(".zip") and any(t in f.upper() for t in TITLE_IDS)]
        for z in [z for z in zips if zipfile.is_zipfile(z)]: run(z)                            # ZIP каждой установленной версии
        run(cache)                                       # и отдельные файлы/папки кэша
    if os.path.isdir(dumps):
        run(dumps)
    if os.path.isdir(patch_dir):                         # ранее созданный патч шейдера (user/shader/patch): обновляем или сбрасываем (напр. возврат на 16:9)
        run(patch_dir)
    return out


def apply_patch(root, W, H, extra, own_xml=None, confirm=None, log=print, keep_custom=False):
    """Весь процесс: XML (GitHub или свой файл) + шейдер видео. confirm(список файлов) -> bool спрашивается перед заменой."""
    root = os.path.abspath(os.path.expanduser(root.strip().strip('"')))
    if not os.path.isdir(os.path.join(root, "user")):
        raise ValueError(tr("root_bad"))
    R = dict(cancelled=False, manual=None, notes=[], shader_missing=False, name=patch_name(W, H))
    cur = find_xml(root); xml_path = cur or xml_default(root)
    new = None
    if own_xml:
        new, _, info = build_xml(W, H, open(own_xml, encoding='utf-8-sig').read(), False, 1.0, extra, True)
    else:
        gr = build_github_xml(W, H, False, 1.0, extra, True, log); info = gr["info"]
        R["notes"].append(gr["text"])
        if gr["xml"] is not None: new = gr["xml"]
        elif gr["status"] == "same": new = gr["base"]
        else:
            R["manual"] = os.path.join(out_root(), block_rel(W, H))
            os.makedirs(out_root(), exist_ok=True)
            open(R["manual"], 'w', encoding='utf-8').write(gr["block"])
            R["notes"].append(tr("gh_man_msg", R["manual"]))
    if new is not None and keep_custom and cur and not own_xml:
        try:
            new, kc = preserve_custom(new, open(cur, encoding='utf-8-sig').read(), W, H)
            if kc["custom"] or kc["states"]: log(tr("kc_log", kc["custom"], kc["states"]))
            if kc["dup"]: log(tr("kc_dup", kc["dup"]))
        except OSError:
            pass
    games = detect_games(root)
    if new is not None: new = ensure_ids(new, games)
    log(tr("games_found", ", ".join(games) if games else "-"))
    if info["expanded"]:
        R["notes"].append(tr("card_exp", dmem_user_extra(info)))
    old = open(cur, encoding='utf-8-sig').read() if cur and new is not None else None
    changed = new is not None and (old is None or old.replace("\r\n", "\n") != new.replace("\r\n", "\n"))
    repl = ([cur] if changed and cur else []) + patch_shader_auto(root, W, H, log, True)["targets"]
    if repl and confirm and not confirm([os.path.relpath(p, root) if os.path.isabs(p) else p for p in repl]):
        R["cancelled"] = True; R["notes"] = [tr("cancelled")]; return R
    if changed:
        if cur:
            os.makedirs(os.path.join(out_root(), "backup"), exist_ok=True)
            shutil.copy2(cur, os.path.join(out_root(), "backup", "%s_%s.xml" % (GH_FILE[:-4], time.strftime("%Y%m%d-%H%M%S"))))
        os.makedirs(os.path.dirname(xml_path), exist_ok=True)
        with open(xml_path, 'w', encoding='utf-8', newline='') as f: f.write(new)
        log(tr("xml_repl" if cur else "xml_new", xml_path))
    elif new is not None:
        log(tr("xml_same", xml_path))
    sh = patch_shader_auto(root, W, H, log, False)
    if not sh["found"] and not is_169(W, H):
        R["shader_missing"] = True; R["notes"].append(tr("sh_nf"))
    return R


# ----------------------------------------------------------------------------------------
# CLI:  python3 tlou_r_shadps4_ultrawide.py --cli 2560 1080 --root <папка shadPS4> [--xml свой.xml] [--dmem]
# ----------------------------------------------------------------------------------------
def cli(a):
    if not a.root:
        print("--root <shadPS4 folder> is required"); return 2
    W, H = a.cli
    ask = (lambda l: input(tr("confirm_msg", "\n".join(l)).replace("\n\n", "\n") + " [y/N] ").strip().lower() in ("y", "yes", "д", "да"))
    try:
        R = apply_patch(a.root, W, H, resolve_extra('full' if a.dmem else 'off'), a.xml, ask, print, not a.no_keep_custom)
    except (ValueError, GhError, OSError, BudgetError, CacheError) as e:
        print(tr("err_prefix", e)); return 1
    for n in R["notes"]: print(n)
    return 3 if R["shader_missing"] else 0


# ----------------------------------------------------------------------------------------
# GUI
# ----------------------------------------------------------------------------------------
def gui():
    from PyQt5 import QtWidgets as Q, QtGui, QtCore
    app = Q.QApplication(sys.argv)
    app.setStyle("Fusion")
    C = QtGui.QColor
    pal = QtGui.QPalette()
    for role, col in ((QtGui.QPalette.Window, "#161a22"), (QtGui.QPalette.Base, "#0f131a"),
                      (QtGui.QPalette.AlternateBase, "#141922"), (QtGui.QPalette.Button, "#232a36"),
                      (QtGui.QPalette.ButtonText, "#e6ebf2"), (QtGui.QPalette.Highlight, "#0070d1"),
                      (QtGui.QPalette.HighlightedText, "#ffffff"), (QtGui.QPalette.Text, "#e6ebf2"),
                      (QtGui.QPalette.WindowText, "#e6ebf2"), (QtGui.QPalette.ToolTipBase, "#232a36"),
                      (QtGui.QPalette.ToolTipText, "#e6ebf2")):
        pal.setColor(role, C(col))
    if hasattr(QtGui.QPalette, "PlaceholderText"):
        pal.setColor(QtGui.QPalette.PlaceholderText, C("#7a8599"))
    for role in (QtGui.QPalette.Text, QtGui.QPalette.ButtonText, QtGui.QPalette.WindowText):
        pal.setColor(QtGui.QPalette.Disabled, role, C("#667086"))
    app.setPalette(pal)
    app.setStyleSheet("""
        QGroupBox { font-weight: 600; border: 1px solid #2b3441; border-radius: 6px; margin-top: 12px;
                    padding: 12px 10px 8px 10px; background: #1a1f29; }
        QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 5px; color: #4da3ff; }
        QLabel#title { font-size: 19px; font-weight: 700; color: #f2f6fc; }
        QLabel#subtitle { color: #8793a8; }
        QLabel#hint { color: #6a7a94; }
        QLabel#chip { background: #10294a; border: 1px solid #1d4f8a; border-radius: 9px; padding: 3px 10px; color: #9fcdff; }
        QLabel#chip[warn="true"] { background: #3d3416; border-color: #7a6422; color: #f0d58a; }
        QLabel#ok { color: #6fd08c; } QLabel#bad { color: #f0a070; }
        QPushButton#primary { background: #0070d1; color: #fff; font-weight: 700; font-size: 14px;
                              padding: 10px 34px; border: 1px solid #00439c; border-radius: 4px; }
        QPushButton#primary:hover { background: #1a85e6; }
        QPushButton#primary:disabled { background: #1d2a40; color: #6f7d96; border-color: #1d2a40; }
        QPushButton#secondary { background: #232a36; color: #c8d4e6; border: 1px solid #2e3d52; border-radius: 4px; padding: 5px 12px; }
        QPushButton#secondary:hover { background: #2e3d52; }
        QPlainTextEdit { font-family: Consolas,Menlo,monospace; font-size: 11px; }
    """)

    def lab(text, obj=None):
        x = Q.QLabel(text); x.setWordWrap(True)
        x.setSizePolicy(Q.QSizePolicy.Preferred, Q.QSizePolicy.MinimumExpanding)
        if obj: x.setObjectName(obj)
        return x

    class Win(Q.QMainWindow):
        PRESETS = [("16:9  2560×1440", 2560, 1440), ("16:9  2880×1620", 2880, 1620), ("16:9  3840×2160", 3840, 2160),
                   ("16:10 1920×1200", 1920, 1200), ("16:10 2560×1600", 2560, 1600),
                   ("21:9  2240×960", 2240, 960), ("21:9  2560×1080", 2560, 1080), ("21:9  3440×1440", 3440, 1440),
                   ("21:9  3840×1646", 3840, 1646), ("32:9  3840×1080", 3840, 1080), (None, 0, 0)]

        def __init__(s):
            super().__init__()
            s.cfg = load_cfg()
            s.setWindowTitle(tr("g_title") + " (shadPS4)")
            cw = Q.QWidget(); s.setCentralWidget(cw)
            v = Q.QVBoxLayout(cw); v.setContentsMargins(16, 10, 16, 10); v.setSpacing(6)
            v.addWidget(lab(tr("g_title"), "title")); v.addWidget(lab(tr("g_sub"), "subtitle"))

            # 1. папка shadPS4
            g = Q.QGroupBox("1. " + tr("g_root")); gl = Q.QVBoxLayout(g)
            r = Q.QHBoxLayout()
            s.root = Q.QLineEdit(s.cfg.get("root", "")); s.root.setPlaceholderText(tr("ph_root")); s.root.setClearButtonEnabled(True)
            b = Q.QPushButton(tr("g_browse")); b.setObjectName("secondary"); b.clicked.connect(s.pick_root)
            rb = Q.QPushButton(tr("g_refresh")); rb.setObjectName("secondary"); rb.setToolTip(tr("g_refresh_tip"))
            rb.clicked.connect(s.check_root)
            r.addWidget(s.root, 1); r.addWidget(b); r.addWidget(rb); gl.addLayout(r)
            s.root_state = lab(""); gl.addWidget(s.root_state); v.addWidget(g)

            # 2. разрешение
            g = Q.QGroupBox("2. " + tr("g_res")); gl = Q.QVBoxLayout(g)
            r = Q.QHBoxLayout()
            s.pre = Q.QComboBox(); [s.pre.addItem(p[0] or tr("g_custom")) for p in s.PRESETS]
            s.w = Q.QSpinBox(); s.w.setRange(640, 16384); s.w.setValue(2560); s.w.setSingleStep(16); s.w.setSuffix(" px")
            s.h = Q.QSpinBox(); s.h.setRange(360, 8640); s.h.setValue(1080); s.h.setSuffix(" px")
            s.mx = Q.QPushButton(tr("g_max")); s.mx.setObjectName("secondary"); s.mx.setToolTip(tr("g_max_tip"))
            for x in (s.pre, Q.QLabel(tr("g_width")), s.w, Q.QLabel(tr("g_height")), s.h, s.mx): r.addWidget(x)
            r.addStretch(1); gl.addLayout(r)
            s.info = lab("", "chip"); gl.addWidget(s.info)
            s.sh_info = lab(tr("sh_info"), "hint"); gl.addWidget(s.sh_info)
            v.addWidget(g)

            # 3. XML
            g = Q.QGroupBox("3. " + tr("g_src")); gl = Q.QVBoxLayout(g)
            s.rb_gh = Q.QRadioButton(tr("src_gh")); s.rb_own = Q.QRadioButton(tr("src_own")); s.rb_gh.setChecked(True)
            s.gh_hint = lab("")
            s.keep = Q.QCheckBox(tr("g_keep")); s.keep.setChecked(s.cfg.get("keep_custom", True)); s.keep.setVisible(False)
            s.own_box = Q.QWidget(); ob = Q.QVBoxLayout(s.own_box); ob.setContentsMargins(0, 0, 0, 0); ob.setSpacing(4)
            r = Q.QHBoxLayout()
            s.own = Q.QLineEdit(); s.own.setPlaceholderText(tr("ph_own")); s.own.setClearButtonEnabled(True)
            b = Q.QPushButton(tr("g_browse")); b.setObjectName("secondary"); b.clicked.connect(s.pick_own)
            r.addWidget(s.own, 1); r.addWidget(b); ob.addLayout(r); ob.addWidget(lab(tr("src_own_hint"), "hint"))
            s.own_box.setVisible(False)
            for x in (s.rb_gh, s.keep, s.rb_own, s.own_box): gl.addWidget(x)
            v.addWidget(g)

            # 4. память
            g = Q.QGroupBox("4. " + tr("g_mem")); gl = Q.QVBoxLayout(g)
            s.mode = Q.QComboBox(); s.mode.addItem(tr("mode_ext")); s.mode.addItem(tr("mode_std"))
            s.mode_desc = lab("", "hint"); s.dm = lab("", "chip")
            for x in (s.mode, s.mode_desc, s.dm): gl.addWidget(x)
            v.addWidget(g)

            s.log = Q.QPlainTextEdit(); s.log.setReadOnly(True); s.log.setFixedHeight(80); s.log.setVisible(False)
            v.addWidget(s.log)
            s.go = Q.QPushButton(tr("g_go")); s.go.setObjectName("primary")
            hb = Q.QHBoxLayout(); cr = Q.QLabel("by sanyagames227 and Claude AI"); cr.setObjectName("hint"); hb.addWidget(cr); hb.addStretch(1); hb.addWidget(s.go); v.addLayout(hb)

            s.pre.currentIndexChanged.connect(s.on_pre); s.mx.clicked.connect(s.set_max)
            s.w.valueChanged.connect(s.on_size); s.h.valueChanged.connect(s.on_size)
            s.mode.currentIndexChanged.connect(s.refresh)
            s.rb_own.toggled.connect(s.on_src)
            s.scan_timer = QtCore.QTimer(s); s.scan_timer.setSingleShot(True); s.scan_timer.setInterval(500); s.scan_timer.timeout.connect(s.scan)
            s.root.textChanged.connect(s.check_root); s.own.textChanged.connect(s.refresh)
            s.go.clicked.connect(s.run)
            s.pre.setCurrentIndex(next(k for k, p in enumerate(s.PRESETS) if p[1:] == (2560, 1080))); s.on_pre(s.pre.currentIndex()); s.check_root(); s.adjust()

        def adjust(s):
            """Фиксированная ширина; высота подстраивается под видимые элементы."""
            lay = s.centralWidget().layout(); lay.activate()
            h = lay.totalHeightForWidth(640) if lay.hasHeightForWidth() else lay.sizeHint().height()
            s.setFixedSize(640, h)

        def adjust_later(s): QtCore.QTimer.singleShot(0, s.adjust)

        def center(s):
            g = s.frameGeometry(); g.moveCenter(app.primaryScreen().availableGeometry().center()); s.move(g.topLeft())

        def pick_root(s):
            f = Q.QFileDialog.getExistingDirectory(s, tr("g_root"), s.root.text())
            if f: s.root.setText(f)

        def pick_own(s):
            f = Q.QFileDialog.getOpenFileName(s, tr("g_src"), s.own.text(), "XML (*.xml);;*")[0]
            if f: s.own.setText(f)

        def on_src(s, own):
            s.own_box.setVisible(own); s.refresh()

        def on_size(s, *_):
            """Ручной ввод: в списке выбирается подходящий пресет, а если такого нет, - «Свой…»."""
            cur = (s.w.value(), s.h.value())
            i = next((k for k, (_, w, h) in enumerate(s.PRESETS) if w and (w, h) == cur), len(s.PRESETS) - 1)
            s.pre.blockSignals(True); s.pre.setCurrentIndex(i); s.pre.blockSignals(False)
            s.refresh()

        def set_max(s):
            w, h = max_res(s.w.value(), s.h.value(), s.mode_extra())
            s.w.blockSignals(True); s.h.blockSignals(True); s.w.setValue(w); s.h.setValue(h)
            s.w.blockSignals(False); s.h.blockSignals(False); s.on_size()

        def on_pre(s, i):
            _, w, h = s.PRESETS[i]
            if w:
                s.w.blockSignals(True); s.h.blockSignals(True); s.w.setValue(w); s.h.setValue(h)
                s.w.blockSignals(False); s.h.blockSignals(False)
            s.refresh()

        def repolish(s, *ws):
            for x in ws: x.style().unpolish(x); x.style().polish(x)

        def check_root(s):
            p = s.root.text().strip().strip('"')
            ok = bool(p) and os.path.isdir(os.path.join(p, "user"))
            s.sh_state = None
            if ok:
                g = detect_games(p)
                s.base_txt = tr("root_games", ", ".join(g) if g else tr("no_f")) + "\n" + tr("xml_state", tr("yes_f") if find_xml(p) else tr("no_f"))
                s.root_state.setObjectName("ok"); s.root_state.setText(s.base_txt + "\n" + tr("sh_checking"))
                s.scan_timer.start()
            else:
                s.scan_timer.stop(); s.root_state.setObjectName("bad"); s.root_state.setText(tr("root_bad") if p else "")
            s.root_state.setVisible(bool(s.root_state.text())); s.repolish(s.root_state); s.refresh()

        def scan(s):
            """Заранее ищет нужный шейдер видео (кэш / дампы) в выбранной папке."""
            p = s.root.text().strip().strip('"')
            if not os.path.isdir(os.path.join(p, "user")): return
            Q.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
            try: r = patch_shader_auto(p, 2560, 1080, lambda *a: None, True)
            except Exception: r = dict(cache=False, dumps=False, patch=False)
            finally: Q.QApplication.restoreOverrideCursor()
            if r["cache"] or r["dumps"] or r["patch"]:
                t = tr("sh_found", ", ".join([x for x, f in ((tr("sh_cache"), r["cache"]), (tr("sh_dumps"), r["dumps"]), (tr("sh_patch"), r["patch"])) if f]))
                s.root_state.setObjectName("ok")
            else:
                t = tr("sh_none"); s.root_state.setObjectName("bad")
            s.root_state.setText(s.base_txt + "\n" + t); s.repolish(s.root_state); s.adjust_later()

        def mode_extra(s): return resolve_extra('full' if s.mode.currentIndex() == 0 else 'off')

        def refresh(s):
            Wd, Hd = s.w.value(), s.h.value(); R = (Wd / Hd) / (16 / 9); g = math.gcd(Wd, Hd)
            s.info.setProperty("warn", R < 0.999)
            s.info.setText(tr("g_ratio", Wd // g, Hd // g, Wd / Hd) + ((" " + tr("g_narrow")) if R < 0.999 else "")
                           + ((" " + tr("g_169")) if is_169(Wd, Hd) else ""))
            s.sh_info.setVisible(not is_169(Wd, Hd)); s.repolish(s.info)
            s.mode_desc.setText(tr("mode_std_d")); s.mode_desc.setVisible(s.mode.currentIndex() == 1)
            ok = os.path.isdir(os.path.join(s.root.text().strip().strip('"'), "user")) and (not s.rb_own.isChecked() or bool(s.own.text().strip()))
            try:
                _, _, inf = calc_budget(Wd, Hd, False, 1.0, None, s.mode_extra())
                s.dm.setText(tr("dm_short", inf["dmem_mb"]) if inf["expanded"] else tr("card_ok"))
            except BudgetError as e:
                s.dm.setText(str(e)); ok = False
            s.keep.setVisible(bool(find_xml(s.root.text().strip().strip('"'))) and not s.rb_own.isChecked())
            s.go.setEnabled(ok); s.adjust_later()

        def say(s, t):
            s.log.setVisible(True); s.log.appendPlainText(t); s.adjust(); Q.QApplication.processEvents()

        def confirm(s, files):
            m = Q.QMessageBox.question(s, tr("confirm_title"), tr("confirm_msg", "\n".join(files)),
                                       Q.QMessageBox.Yes | Q.QMessageBox.No, Q.QMessageBox.No)
            return m == Q.QMessageBox.Yes

        def run(s):
            Wd, Hd = s.w.value(), s.h.value(); root = s.root.text().strip().strip('"')
            s.go.setEnabled(False); Q.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
            try:
                R = apply_patch(root, Wd, Hd, s.mode_extra(), s.own.text().strip() if s.rb_own.isChecked() else None,
                                lambda l: (Q.QApplication.restoreOverrideCursor(), s.confirm(l),
                                           Q.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor))[1], s.say,
                                not s.keep.isHidden() and s.keep.isChecked())
            except Exception as e:
                Q.QApplication.restoreOverrideCursor(); s.say(tr("err_prefix", e))
                Q.QMessageBox.critical(s, tr("err_title"), str(e)); s.refresh(); return
            Q.QApplication.restoreOverrideCursor(); s.refresh()
            s.cfg["root"] = root; s.cfg["keep_custom"] = s.keep.isChecked(); save_cfg(s.cfg)
            for n in R["notes"]: s.say(n)
            if R["cancelled"]: return
            body = tr("done_msg2", R["name"]) + ("\n\n" + "\n\n".join(R["notes"]) if R["notes"] else "")
            if R["shader_missing"] or R["manual"]: Q.QMessageBox.warning(s, tr("warn_title"), body)
            else: Q.QMessageBox.information(s, tr("done_title"), body)

    w = Win(); w.show(); w.center()
    shot = os.environ.get("TLOU_SHOT")
    if shot: QtCore.QTimer.singleShot(300, lambda: (w.grab().save(shot), app.quit()))
    sys.exit(app.exec_())


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--cli", nargs=2, type=int, metavar=("W", "H"))
    ap.add_argument("--root", metavar="SHADPS4_DIR")
    ap.add_argument("--xml", metavar="FILE", help="свой XML (иначе берётся с GitHub)")
    ap.add_argument("--dmem", action="store_true", help="расширенный режим (CPU-память не урезается)")
    ap.add_argument("--no-keep-custom", action="store_true", help="не переносить кастомные патчи и состояния из имеющегося XML")
    ap.add_argument("--lang", choices=["en", "ru", "uk"])
    a = ap.parse_args()
    LANG = a.lang or detect_lang()
    sys.exit(cli(a)) if a.cli else gui()
