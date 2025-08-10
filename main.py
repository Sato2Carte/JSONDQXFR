import click
import sys
import requests
import time
import sqlite3
from io import BytesIO
from pathlib import Path
from openpyxl import load_workbook
from configparser import ConfigParser
import subprocess
import os

from common.config import UserConfig
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
from common.db_ops import create_db_schema
import threading

def patch_and_download_custom_updater():
    update_py_path = Path(__file__).parent / "common" / "update.py"
    updater_dest_path = Path(__file__).parent / "updater.py"
    custom_url = "https://raw.githubusercontent.com/Sato2Carte/JSONDQXFR/main/updater.py"

    # Étape 1 : Patch update.py
    if update_py_path.exists():
        try:
            lines = update_py_path.read_text(encoding="utf-8").splitlines(keepends=True)
            new_lines = []

            for line in lines:
                if line.strip().startswith("update_url ="):
                    new_line = f'                update_url = "{custom_url}"\n'
                    new_lines.append(new_line)
                else:
                    new_lines.append(line)

            update_py_path.write_text("".join(new_lines), encoding="utf-8")
        except Exception as e:
            print("[PATCH ERROR] Erreur lors de la modification de update.py :", e)
    else:
        print("[PATCH] Fichier update.py introuvable.")

    # Étape 2 : Télécharger updater.py depuis ton GitHub
    try:
        import requests
        response = requests.get(custom_url, timeout=15)
        response.raise_for_status()
        updater_dest_path.write_text(response.text, encoding="utf-8")
    except Exception as e:
        print("[PATCH ERROR] Échec du téléchargement de updater.py :", e)

patch_and_download_custom_updater()

def check_for_launcher_update():
    ini_path = Path(__file__).parent / "user_settings.ini"
    if not ini_path.exists():
        return

    config = ConfigParser()
    config.read(ini_path, encoding="utf-8")

    if config.has_section("launcher") and config.get("launcher", "mode", fallback="") == "maj":
        print("[MAJ] Mode 'maj' détecté. Lancement de la mise à jour...")

        exe_name = "dqxclarityFR.exe"
        new_url = "https://github.com/Sato2Carte/JSONDQXFR/releases/download/dqxclarityFR.exe/dqxclarityFR.exe"
        exe_path = Path(__file__).parent / exe_name

        try:
            # Supprime l'ancien exe
            if exe_path.exists():
                os.remove(exe_path)
                print("[MAJ] Ancien EXE supprimé.")

            # Télécharge le nouveau
            response = requests.get(new_url, timeout=30)
            response.raise_for_status()

            with open(exe_path, "wb") as f:
                f.write(response.content)
            print("[MAJ] Nouveau EXE téléchargé.")

            # Nettoyage de l'ini
            config.set("launcher", "mode", "")
            with open(ini_path, "w", encoding="utf-8") as configfile:
                config.write(configfile)
            print("[MAJ] INI nettoyé.")

            # Relance le nouveau EXE
            subprocess.Popen([str(exe_path)])
            print("[MAJ] Nouveau launcher lancé. Fermeture...")
            sys.exit()

        except Exception as e:
            print("[ERREUR MAJ]", e)
            sys.exit(1)

check_for_launcher_update()

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
        "patchdaily": False,
        "serversidefr": False
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
            elif key == "serversidefr":
                settings["serversidefr"] = value.lower() == "true"

    return settings

import json

from configparser import ConfigParser

from configparser import ConfigParser
from pathlib import Path

from tkinter.filedialog import askdirectory

from tkinter.filedialog import askdirectory

def get_verified_dqx_data_path():
    """Vérifie et retourne le chemin Game/Content/Data de DQX. Demande à l'utilisateur si besoin."""

    ini_path = Path(__file__).parent / "user_settings.ini"
    config = ConfigParser()
    config.read(ini_path, encoding="utf-8")

    current_path = config.get("config", "installdirectory", fallback="").strip()
    dat0_path = Path(current_path) / "Game" / "Content" / "Data" / "data00000000.win32.dat0"

    if not dat0_path.exists():
        print("[!] Le chemin d'installation dans user_settings.ini est invalide ou absent.")
        print("→ Merci de sélectionner le dossier DRAGON QUEST X.")

        while True:
            dqx_root = askdirectory(title="Sélectionnez le dossier DRAGON QUEST X")
            if not dqx_root:
                raise RuntimeError("Aucun dossier sélectionné. Abandon.")

            candidate = Path(dqx_root) / "Game" / "Content" / "Data" / "data00000000.win32.dat0"
            if candidate.exists():
                config.set("config", "installdirectory", dqx_root)
                with open(ini_path, "w", encoding="utf-8") as f:
                    config.write(f)
                print("[✓] Chemin DQX vérifié et enregistré.")
                return candidate.parent  # retourne le dossier "Data"
            else:
                print("[!] Dossier invalide. Merci de sélectionner le dossier DRAGON QUEST X (pas un sous-dossier).")
    else:
        return dat0_path.parent  # retourne le dossier "Data"


def ensure_default_install_path(log):
    """Remplit installdirectory dans user_settings.ini si vide."""
    ini_path = Path(__file__).parent / "user_settings.ini"
    if not ini_path.exists():
        log.warning("user_settings.ini introuvable.")
        return

    config = ConfigParser()
    config.read(ini_path, encoding="utf-8")

    if "config" in config:
        current_value = config["config"].get("installdirectory", "").strip()
        if not current_value:
            default_path = "C:/Program Files (x86)/SquareEnix/DRAGON QUEST X"
            config["config"]["installdirectory"] = default_path
            with open(ini_path, "w", encoding="utf-8") as f:
                config.write(f)
            log.info(f"Chemin d'installation par défaut appliqué : {default_path}")

def update_serverside_fr(log):
    log.info("Création de la structure de la DB.")
    create_db_schema()
    download_custom_files()

    GITHUB_BASE = "https://raw.githubusercontent.com/Sato2Carte/Server-Side-Text/SSTFR/fr/"
    json_files = [
        "fixed_dialog_template.json",
        "m00_strings.json",
        "quests.json",
        "story_so_far_template.json",
        "walkthrough.json",
        "glossary.json",
    ]

    db_path = Path(__file__).parent / "misc_files" / "clarity_dialogFR.db"

    # 1) Vider fixed_dialog_template
    try:
        with sqlite3.connect(db_path) as conn:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA synchronous=NORMAL;")
            conn.execute('DELETE FROM "fixed_dialog_template";')
            conn.commit()
            log.info("🧹 Table fixed_dialog_template vidée.")
    except Exception as e:
        log.warning(f"Impossible de vider fixed_dialog_template: {e}")

    # --- Helpers schémas -----------------------------------------------------
    def ensure_table_schema(conn, table_name: str, unique_idx: bool = True):
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS "{table_name}" (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ja TEXT,
                en TEXT
            );
        """)
        if unique_idx:
            try:
                conn.execute(f'CREATE UNIQUE INDEX IF NOT EXISTS idx_{table_name}_ja ON "{table_name}"(ja);')
            except Exception as ie:
                log.warning(f'Index unique non créé pour {table_name}: {ie}')

    def ensure_fixed_dialog_schema(conn):
        """Schéma spécifique pour fixed_dialog_template avec bad_string DEFAULT 0."""
        conn.execute("""
            CREATE TABLE IF NOT EXISTS "fixed_dialog_template" (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ja TEXT,
                en TEXT,
                bad_string INTEGER NOT NULL DEFAULT 0
            );
        """)
        try:
            conn.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_fixed_dialog_template_ja ON "fixed_dialog_template"(ja);')
        except Exception as ie:
            log.warning(f'Index unique non créé pour fixed_dialog_template: {ie}')

    # --- Helpers d'upsert/maj -----------------------------------------------
    def upsert_rows(conn, table_name: str, items: dict):
        """Upsert générique (ja/en)."""
        sql = f"""
            INSERT INTO "{table_name}" (ja, en)
            VALUES (?, ?)
            ON CONFLICT(ja) DO UPDATE SET en = excluded.en;
        """
        rows = []
        for ja, fr in items.items():
            if not ja:
                continue
            rows.append((str(ja).strip(), str(fr or "").strip()))
        if rows:
            conn.executemany(sql, rows)

    def upsert_fixed_dialog(conn, items: dict):
        """Upsert spécifique fixed_dialog_template en forçant bad_string = 0."""
        sql = """
            INSERT INTO "fixed_dialog_template" (ja, en, bad_string)
            VALUES (?, ?, 0)
            ON CONFLICT(ja) DO UPDATE SET
                en = excluded.en,
                bad_string = 0;
        """
        rows = []
        for ja, fr in items.items():
            if not ja:
                continue
            rows.append((str(ja).strip(), str(fr or "").strip()))
        if rows:
            conn.executemany(sql, rows)

    def update_only_en_by_ja(conn, table_name: str, items: dict):
        """
        UPDATE-only (m00_strings) pour préserver les autres colonnes (ex: 'file').
        Ne crée jamais de nouvelles lignes.
        """
        cur = conn.cursor()
        updated = 0
        skipped = 0
        for ja, fr in items.items():
            if not ja:
                continue
            ja_s = str(ja).strip()
            fr_s = "" if fr is None else str(fr).strip()
            if not ja_s:
                continue
            cur.execute(f'UPDATE "{table_name}" SET en = ? WHERE ja = ?;', (fr_s, ja_s))
            if cur.rowcount == 0:
                skipped += 1
            else:
                updated += 1
        return updated, skipped

    # 2) Télécharger chaque JSON et injecter dans sa table
    for file_name in json_files:
        table = file_name.replace(".json", "")
        url = GITHUB_BASE + file_name

        try:
            response = download_with_retry(url)
            data = json.loads(response.content.decode("utf-8"))
        except Exception as e:
            log.error(f"Échec du téléchargement ou parsing de {url} : {e}")
            continue

        # Normaliser en dict {ja: fr}
        if isinstance(data, list):
            items = {entry.get("ja", ""): entry.get("fr", "") for entry in data if isinstance(entry, dict)}
        elif isinstance(data, dict):
            items = data
        else:
            log.error(f"Format JSON non supporté pour {file_name}")
            continue

        try:
            with sqlite3.connect(db_path) as conn:
                conn.execute("PRAGMA journal_mode=WAL;")
                conn.execute("PRAGMA synchronous=NORMAL;")
                before = time.time()

                if table == "fixed_dialog_template":
                    # Schéma + upsert avec bad_string=0
                    ensure_fixed_dialog_schema(conn)
                    upsert_fixed_dialog(conn, items)
                    conn.commit()
                    dt_ms = int((time.time() - before) * 1000)
                    log.info(f"✅ {table}: {len(items)} lignes upsert (bad_string=0) en {dt_ms} ms.")

                elif table == "m00_strings":
                    # UPDATE-only pour préserver 'file' (et autres colonnes)
                    ensure_table_schema(conn, table, unique_idx=False)
                    updated, skipped = update_only_en_by_ja(conn, table, items)
                    conn.commit()
                    dt_ms = int((time.time() - before) * 1000)
                    log.info(f"✅ {table}: {updated} MAJ, {skipped} non trouvées (UPDATE-only) en {dt_ms} ms.")

                else:
                    # Autres tables → upsert standard
                    ensure_table_schema(conn, table, unique_idx=True)
                    upsert_rows(conn, table, items)
                    conn.commit()
                    dt_ms = int((time.time() - before) * 1000)
                    log.info(f"✅ {table}: {len(items)} lignes upsert en {dt_ms} ms.")
        except Exception as e:
            log.error(f"Erreur d'injection pour {table}: {e}")


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
    serversidefr = settings["serversidefr"]

    if serversidefr :
        if not disable_update_check:
            check_for_updates(update=True)
        update_serverside_fr(log)
    else:
        create_db_schema()

        if not disable_update_check:
            log.info("Updating custom text in db.")
            check_for_updates(update=True)
            download_custom_files()

    if choice == 'FR':
        ensure_default_install_path(log)
        data_path = get_verified_dqx_data_path()
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
            file_path = data_path / 'data00000000.win32.dat1'
            with open(file_path, 'wb') as f:
                f.write(response.content)
            log.info(f'DAT1 FR sauvegardé dans {file_path}')
        except Exception as e:
            log.error(f"Erreur DAT1 FR: {e}")

        try:
            response = download_file(fr_idx_url)
            response.raise_for_status()
            file_path = data_path / 'data00000000.win32.idx'
            with open(file_path, 'wb') as f:
                f.write(response.content)
            log.info(f'IDX FR sauvegardé dans {file_path}')
        except Exception as e:
            log.error(f"Erreur IDX FR: {e}")

    if update_dat and choice == 'EN':
        log.info("Updating DAT mod.")
        download_dat_files()

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

check_for_launcher_update()

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
        "patchdaily": False,
        "serversidefr": False
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
            elif key == "serversidefr":
                settings["serversidefr"] = value.lower() == "true"

    return settings

import json

from configparser import ConfigParser

from configparser import ConfigParser
from pathlib import Path

from tkinter.filedialog import askdirectory

from tkinter.filedialog import askdirectory

def get_verified_dqx_data_path():
    """Vérifie et retourne le chemin Game/Content/Data de DQX. Demande à l'utilisateur si besoin."""

    ini_path = Path(__file__).parent / "user_settings.ini"
    config = ConfigParser()
    config.read(ini_path, encoding="utf-8")

    current_path = config.get("config", "installdirectory", fallback="").strip()
    dat0_path = Path(current_path) / "Game" / "Content" / "Data" / "data00000000.win32.dat0"

    if not dat0_path.exists():
        print("[!] Le chemin d'installation dans user_settings.ini est invalide ou absent.")
        print("→ Merci de sélectionner le dossier DRAGON QUEST X.")

        while True:
            dqx_root = askdirectory(title="Sélectionnez le dossier DRAGON QUEST X")
            if not dqx_root:
                raise RuntimeError("Aucun dossier sélectionné. Abandon.")

            candidate = Path(dqx_root) / "Game" / "Content" / "Data" / "data00000000.win32.dat0"
            if candidate.exists():
                config.set("config", "installdirectory", dqx_root)
                with open(ini_path, "w", encoding="utf-8") as f:
                    config.write(f)
                print("[✓] Chemin DQX vérifié et enregistré.")
                return candidate.parent  # retourne le dossier "Data"
            else:
                print("[!] Dossier invalide. Merci de sélectionner le dossier DRAGON QUEST X (pas un sous-dossier).")
    else:
        return dat0_path.parent  # retourne le dossier "Data"


def ensure_default_install_path(log):
    """Remplit installdirectory dans user_settings.ini si vide."""
    ini_path = Path(__file__).parent / "user_settings.ini"
    if not ini_path.exists():
        log.warning("user_settings.ini introuvable.")
        return

    config = ConfigParser()
    config.read(ini_path, encoding="utf-8")

    if "config" in config:
        current_value = config["config"].get("installdirectory", "").strip()
        if not current_value:
            default_path = "C:/Program Files (x86)/SquareEnix/DRAGON QUEST X"
            config["config"]["installdirectory"] = default_path
            with open(ini_path, "w", encoding="utf-8") as f:
                config.write(f)
            log.info(f"Chemin d'installation par défaut appliqué : {default_path}")

def update_serverside_fr(log):
    log.info("Création de la structure de la DB.")
    create_db_schema()
    download_custom_files()

    log.info("Mise à jour du contenu FR depuis les fichiers JSON...")
    json_files = [
        "fixed_dialog_template.json",
        "m00_strings.json",
        "quests.json",
        "story_so_far_template.json",
        "walkthrough.json",
        "glossary.json"
    ]
    GITHUB_BASE = "https://raw.githubusercontent.com/Sato2Carte/Server-Side-Text/SSTFR/fr/"
    db_path = Path(__file__).parent / "misc_files" / "clarity_dialogFR.db"

    def update_table_from_json(table_name, json_url, db_path, allow_insert=True):
        log.info(f"Traitement de {table_name}")
        try:
            response = download_with_retry(json_url)
            data = json.loads(response.content.decode("utf-8"))
        except Exception as e:
            log.error(f"Échec du téléchargement ou du parsing de {json_url} : {e}")
            return

        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        count_updated = 0
        count_skipped = 0
        count_inserted = 0

        # normalise {ja: fr}
        if isinstance(data, list):
            items = {entry.get("ja",""): entry.get("fr","") for entry in data if isinstance(entry, dict)}
        elif isinstance(data, dict):
            items = data
        else:
            log.error(f"Format JSON non supporté pour {table_name}")
            conn.close()
            return

        for ja, fr in items.items():
            if not ja:
                continue
            ja, fr = str(ja).strip(), ("" if fr is None else str(fr).strip())
            cursor.execute(f'SELECT 1 FROM "{table_name}" WHERE ja = ? LIMIT 1;', (ja,))
            exists = cursor.fetchone() is not None

            if exists:
                # Ne modifie QUE la colonne en → file et le reste restent intacts
                cursor.execute(f'UPDATE "{table_name}" SET en = ? WHERE ja = ?;', (fr, ja))
                count_updated += 1
            else:
                if allow_insert:
                    cursor.execute(f'INSERT INTO "{table_name}" (ja, en) VALUES (?, ?);', (ja, fr))
                    count_inserted += 1
                else:
                    # on ne crée pas la ligne pour préserver l’intégrité (ex: colonne file NOT NULL)
                    count_skipped += 1

        conn.commit()
        conn.close()
        log.info(f"✅ {count_updated} maj, {count_inserted} insérés, {count_skipped} inchangés")




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
    serversidefr = settings["serversidefr"]

    if serversidefr :
        if not disable_update_check:
            check_for_updates(update=True)
        update_serverside_fr(log)
    else:
        create_db_schema()

        if not disable_update_check:
            log.info("Updating custom text in db.")
            check_for_updates(update=True)
            download_custom_files()

    if choice == 'FR':
        ensure_default_install_path(log)
        data_path = get_verified_dqx_data_path()
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
            file_path = data_path / 'data00000000.win32.dat1'
            with open(file_path, 'wb') as f:
                f.write(response.content)
            log.info(f'DAT1 FR sauvegardé dans {file_path}')
        except Exception as e:
            log.error(f"Erreur DAT1 FR: {e}")

        try:
            response = download_file(fr_idx_url)
            response.raise_for_status()
            file_path = data_path / 'data00000000.win32.idx'
            with open(file_path, 'wb') as f:
                f.write(response.content)
            log.info(f'IDX FR sauvegardé dans {file_path}')
        except Exception as e:
            log.error(f"Erreur IDX FR: {e}")

    if update_dat and choice == 'EN':
        log.info("Updating DAT mod.")
        download_dat_files()

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
