import click
import sys
import requests
import time
import sqlite3
from io import BytesIO
from pathlib import Path
from openpyxl import load_workbook
from common.config import UserConfig
from common.db_ops import create_db_schema
from common.lib import get_project_root, setup_logging
from common.process import wait_for_dqx_to_launch
from common.update import (
    check_for_updates,
    download_custom_files,
    download_dat_files,
    import_name_overrides,
    download_file
)
from dqxcrypt.dqxcrypt import start_logger
from hooking.hook import activate_hooks
from clarity import loop_scan_for_walkthrough, run_scans
from multiprocessing import Process
import threading

def switch_db_path_to_en():
    target_file = Path(__file__).parent / "common" / "db_ops.py"
    original_line = 'db_file = get_project_root("misc_files/clarity_dialogFR.db")'
    english_line = 'db_file = get_project_root("misc_files/clarity_dialog.db")'
    with open(target_file, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    with open(target_file, 'w', encoding='utf-8') as f:
        for line in lines:
            if original_line in line:
                f.write(line.replace(original_line, english_line))
            else:
                f.write(line)

def switch_db_path_to_fr():
    target_file = Path(__file__).parent / "common" / "db_ops.py"
    original_line = 'db_file = get_project_root("misc_files/clarity_dialog.db")'
    french_line = 'db_file = get_project_root("misc_files/clarity_dialogFR.db")'
    with open(target_file, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    with open(target_file, 'w', encoding='utf-8') as f:
        for line in lines:
            if original_line in line:
                f.write(line.replace(original_line, french_line))
            else:
                f.write(line)

def download_with_retry(url, attempts=3, delay=3):
    for attempt in range(attempts):
        try:
            response = requests.get(url)
            response.raise_for_status()
            return response
        except Exception as e:
            print(f"[!] Tentative {attempt+1}/{attempts} échouée pour {url} : {e}")
            if attempt < attempts - 1:
                print(f"Nouvelle tentative dans {delay} secondes...")
                time.sleep(delay)
    raise Exception(f"Échec du téléchargement après {attempts} tentatives : {url}")

def get_settings():
    config_path = Path(__file__).parent / "user_settings.ini"
    settings = {
        "language": "EN",
        "patchdaily": False
    }
    if not config_path.exists():
        print("user_settings.ini introuvable. Utilisation des valeurs par défaut.")
        return settings

    with open(config_path, encoding="utf-8") as f:
        for line in f:
            if line.strip().startswith("#") or "=" not in line:
                continue
            key, value = line.strip().split("=", 1)
            key, value = key.strip().lower(), value.strip()
            if key == "language" and value.upper() in ["FR", "EN"]:
                settings["language"] = value.upper()
            elif key == "patchdaily":
                settings["patchdaily"] = value.lower() == "true"

    return settings


@click.command()
@click.option('-u', '--disable-update-check', is_flag=True)
@click.option('-c', '--communication-window', is_flag=True)
@click.option('-p', '--player-names', is_flag=True)
@click.option('-n', '--npc-names', is_flag=True)
@click.option('-l', '--community-logging', is_flag=True)
@click.option('-d', '--update-dat', is_flag=True)
def blast_off(disable_update_check=False, communication_window=False, player_names=False, npc_names=False, community_logging=False, update_dat=False):
    logs_dir = Path(get_project_root("logs"))
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_path = get_project_root("logs/console.log")
    Path(log_path).unlink(missing_ok=True)

    log = setup_logging()
    log.info("Getting started. DO NOT TOUCH THE GAME OR REMOVE YOUR MEMORY CARD.")
    log.info("Checking user_settings.ini.")
    UserConfig(warnings=True)
    settings = get_settings()
    choice = settings["language"]
    patchdaily = settings["patchdaily"]


    if update_dat:
        if choice == 'FR':
            switch_db_path_to_fr()
            log.info("Téléchargement des fichiers DAT et IDX en FR...")
            if patchdaily:
                fr_dat_url = 'https://github.com/Sato2Carte/JSONDQXFR/releases/download/sub/data00000000.win32.dat1'
                fr_idx_url = 'https://github.com/Sato2Carte/JSONDQXFR/releases/download/sub/data00000000.win32.idx'
            else:
                fr_dat_url = 'https://github.com/Sato2Carte/JSONDQXFR/releases/download/dat%2Fidx/data00000000.win32.dat1'
                fr_idx_url = 'https://github.com/Sato2Carte/JSONDQXFR/releases/download/dat%2Fidx/data00000000.win32.idx'
            try:
                response = download_file(fr_dat_url)
                response.raise_for_status()
                file_path = Path(UserConfig().game_path) / 'Game/Content/Data/data00000000.win32.dat1'
                with open(file_path, 'wb') as f:
                    f.write(response.content)
                log.info(f'DAT1 FR sauvegardé dans {file_path}')
            except Exception as e:
                log.error(f"Erreur DAT1 FR: {e}")
            try:
                response = download_file(fr_idx_url)
                response.raise_for_status()
                file_path = Path(UserConfig().game_path) / 'Game/Content/Data/data00000000.win32.idx'
                with open(file_path, 'wb') as f:
                    f.write(response.content)
                log.info(f'IDX FR sauvegardé dans {file_path}')
            except Exception as e:
                log.error(f"Erreur IDX FR: {e}")
            log.info("Création de la structure de la DB.")
            create_db_schema()

            if not disable_update_check:
                log.info("Updating custom text in db.")
                check_for_updates(update=True)
                download_custom_files()

                log.info("Mise à jour du contenu FR dans la base locale...")
                xlsx_files = [
                    "extracted_bad_strings.xlsx",
                    "extracted_fixed_dialog_template.xlsx",
                    "extracted_m00_strings.xlsx",
                    "extracted_quests.xlsx",
                    "extracted_story_so_far_template.xlsx",
                    "extracted_walkthrough.xlsx"
                ]
                GITHUB_BASE = "https://github.com/Sato2Carte/ServSideText/raw/refs/heads/main/fr/"
                db_path = Path(__file__).parent / "misc_files" / "clarity_dialogFR.db"

                def update_table_from_excel(table_name, xlsx_url, db_path):
                    log.info(f"Traitement de {table_name}")
                    try:
                        response = download_with_retry(xlsx_url)
                    except Exception as e:
                        log.error(f"Échec critique du téléchargement : {e}")
                        return
                    wb = load_workbook(filename=BytesIO(response.content), read_only=True)
                    ws = wb.active
                    conn = sqlite3.connect(db_path)
                    cursor = conn.cursor()
                    count_updated = 0
                    count_skipped = 0
                    count_inserted = 0
                    for row in ws.iter_rows(min_row=2, values_only=True):
                        if len(row) < 3:
                            continue
                        ja, _, fr = row[0], row[1], row[2]
                        if not ja or not fr:
                            continue
                        ja, fr = ja.strip(), fr.strip()
                        cursor.execute(f"SELECT en FROM {table_name} WHERE ja = ?", (ja,))
                        result = cursor.fetchone()
                        if result is None:
                            cursor.execute(f"INSERT INTO {table_name} (ja, en) VALUES (?, ?)", (ja, fr))
                            count_inserted += 1
                        else:
                            current_en = result[0].strip() if result[0] else ""
                            if current_en == fr:
                                count_skipped += 1
                                continue
                            cursor.execute(f"UPDATE {table_name} SET en = ? WHERE ja = ?", (fr, ja))
                            count_updated += 1
                    conn.commit()
                    conn.close()
                    log.info(f"✅ {count_updated} maj, {count_inserted} insérés, {count_skipped} inchangés")

                for file_name in xlsx_files:
                    table = file_name.replace("extracted_", "").replace(".xlsx", "")
                    url = GITHUB_BASE + file_name
                    update_table_from_excel(table, url, str(db_path))
        else:
            switch_db_path_to_en()
            log.info("Langue choisie : EN. Préparation de la base de données.")
            create_db_schema()
            if not disable_update_check:
                log.info("Updating custom text in db.")
                check_for_updates(update=True)
                download_custom_files()
            download_dat_files()
    else:
        log.info("Par défaut, DB en EN.")
        switch_db_path_to_en()
        create_db_schema()
        if not disable_update_check:
            log.info("Updating custom text in db.")
            check_for_updates(update=True)
            download_custom_files()

    import_name_overrides()

    try:
        wait_for_dqx_to_launch()
        def start_process(name: str, target, args: tuple):
            p = Process(name=name, target=target, args=args)
            p.start()
            time.sleep(.5)
            while not p.is_alive():
                time.sleep(0.25)
        start_process("Hook loader", activate_hooks, (player_names, communication_window,))
        if communication_window:
            start_process("Walkthrough scanner", loop_scan_for_walkthrough, ())
        if community_logging:
            log.info("Thanks for enabling logging! Logs are in 'logs'.")
            threading.Thread(name="Community logging", target=start_logger, daemon=True).start()
        start_process("Flavortown scanner", run_scans, (player_names, npc_names))
        log.success("Done! Keep this window open and enjoy your adventure!")
    except Exception:
        log.exception("An exception occurred. dqxclarity will exit.")
        sys.exit(1)

if __name__ == "__main__":
    blast_off()
