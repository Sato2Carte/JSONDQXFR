_F='utf-8'
_E=False
_D='user_settings.ini'
_C='launcher'
_B=True
_A=None
from common.config import UserConfig
from common.db_ops import create_db_schema
from common.lib import get_project_root,setup_logging
from common.process import start_process,wait_for_dqx_to_launch,check_if_running_as_admin,is_dqx_process_running
from common.update import check_for_updates,download_custom_files,download_dat_files,import_name_overrides,download_file
from dqxcrypt.dqxcrypt import start_logger
from hooking.hook import activate_hooks
from pathlib import Path
from scans.manager import run_scans
from scans.walkthrough import loop_scan_for_walkthrough
from loguru import logger as log
import argparse,sys,time,configparser,os
def is_fr_launcher(config_path=_D):
        'Retourne True si [launcher] language = FR dans user_settings.ini';A='language'
        if not os.path.isfile(config_path):return _E
        parser=configparser.ConfigParser();parser.read(config_path,encoding=_F);return parser.has_section(_C)and parser.has_option(_C,A)and parser.get(_C,A).strip().upper()=='FR'
def is_patchdaily_enabled(config_path=_D):
        'Retourne True si [launcher] patchdaily = True dans user_settings.ini';A='patchdaily'
        if not os.path.isfile(config_path):return _E
        parser=configparser.ConfigParser();parser.read(config_path,encoding=_F);return parser.has_section(_C)and parser.has_option(_C,A)and parser.get(_C,A).strip().lower()=='true'
def is_serversidefr_enabled(config_path=_D):
        'Retourne True si [launcher] serversidefr = True dans user_settings.ini';A='serversidefr'
        if not os.path.isfile(config_path):return _E
        parser=configparser.ConfigParser();parser.read(config_path,encoding=_F);return parser.has_section(_C)and parser.has_option(_C,A)and parser.get(_C,A).strip().lower()=='true'
def mettre_a_jour_db_fr(log):
        '\n    Met à jour la DB FR depuis GitHub (SSTFR/fr) en une seule fonction.\n    - Importe sqlite3/json/time/Path en interne (évite NameError).\n    - Utilise common.update.download_with_retry si dispo, sinon fallback requests + retry.\n    ';D='PRAGMA synchronous=NORMAL;';C='PRAGMA journal_mode=DELETE;';B='misc_files';A='';import os,time,json,sqlite3;from pathlib import Path
        try:from common.update import download_with_retry as _dl
        except Exception:_dl=_A
        try:import requests
        except Exception:requests=_A
        def _download(url,retries=3,timeout=30):
                if _dl is not _A:return _dl(url)
                if requests is _A:raise RuntimeError('Aucun téléchargeur disponible (ni common.update.download_with_retry ni requests).')
                last_err=_A
                for attempt in range(1,retries+1):
                        try:r=requests.get(url,timeout=timeout);r.raise_for_status();return r
                        except Exception as e:last_err=e;time.sleep(min(2*attempt,5))
                raise last_err
        try:create_db_schema()
        except NameError:log.warning('create_db_schema() introuvable : on continue quand même.')
        GITHUB_BASE='https://raw.githubusercontent.com/Sato2Carte/Server-Side-Text/SSTFR/fr/';json_files=['fixed_dialog_template.json','m00_strings.json','quests.json','story_so_far_template.json','walkthrough.json','glossary.json'];os.makedirs(Path(__file__).parent/B,exist_ok=_B);db_path=Path(__file__).parent/B/'clarity_dialogFR.db'
        try:
                with sqlite3.connect(db_path)as conn:conn.execute(C);conn.execute(D);conn.execute('DELETE FROM "fixed_dialog_template";');conn.commit();log.info('🧹 Table fixed_dialog_template vidée.')
        except Exception as e:log.warning(f"Impossible de vider fixed_dialog_template: {e}")
        def ensure_table_schema(conn,table_name,unique_idx=_B):
                conn.execute(f'''
            CREATE TABLE IF NOT EXISTS "{table_name}" (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ja TEXT,
                en TEXT
            );
        ''')
                if unique_idx:
                        try:conn.execute(f'CREATE UNIQUE INDEX IF NOT EXISTS idx_{table_name}_ja ON "{table_name}"(ja);')
                        except Exception as ie:log.warning(f"Index unique non créé pour {table_name}: {ie}")
        def ensure_fixed_dialog_schema(conn):
                conn.execute('\n            CREATE TABLE IF NOT EXISTS "fixed_dialog_template" (\n                id INTEGER PRIMARY KEY AUTOINCREMENT,\n                ja TEXT,\n                en TEXT,\n                bad_string INTEGER NOT NULL DEFAULT 0\n            );\n        ')
                try:conn.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_fixed_dialog_template_ja ON "fixed_dialog_template"(ja);')
                except Exception as ie:log.warning(f"Index unique non créé pour fixed_dialog_template: {ie}")
        def upsert_rows(conn,table_name,items):
                sql=f'\n            INSERT INTO "{table_name}" (ja, en)\n            VALUES (?, ?)\n            ON CONFLICT(ja) DO UPDATE SET en = excluded.en;\n        ';rows=[(str(ja).strip(),A if fr is _A else str(fr).strip())for(ja,fr)in items.items()if ja]
                if rows:conn.executemany(sql,rows)
        def upsert_fixed_dialog(conn,items):
                sql='\n            INSERT INTO "fixed_dialog_template" (ja, en, bad_string)\n            VALUES (?, ?, 0)\n            ON CONFLICT(ja) DO UPDATE SET en = excluded.en, bad_string = 0;\n        ';rows=[(str(ja).strip(),A if fr is _A else str(fr).strip())for(ja,fr)in items.items()if ja]
                if rows:conn.executemany(sql,rows)
        def update_only_en_by_ja(conn,table_name,items):
                cur=conn.cursor();updated=skipped=0
                for(ja,fr)in items.items():
                        if not ja:continue
                        ja_s=str(ja).strip();fr_s=A if fr is _A else str(fr).strip()
                        if not ja_s:continue
                        cur.execute(f'UPDATE "{table_name}" SET en = ? WHERE ja = ?;',(fr_s,ja_s))
                        if cur.rowcount==0:skipped+=1
                        else:updated+=1
                return updated,skipped
        for file_name in json_files:
                table=file_name.replace('.json',A);url=GITHUB_BASE+file_name
                try:response=_download(url);data=json.loads(response.content.decode(_F))
                except Exception as e:log.error(f"Échec du téléchargement ou parsing de {url} : {e}");continue
                if isinstance(data,list):items={entry.get('ja',A):entry.get('fr',A)for entry in data if isinstance(entry,dict)}
                elif isinstance(data,dict):items={str(k):A if v is _A else str(v)for(k,v)in data.items()}
                else:log.error(f"Format JSON non supporté pour {file_name}");continue
                try:
                        with sqlite3.connect(db_path)as conn:
                                conn.execute(C);conn.execute(D);t0=time.time()
                                if table=='fixed_dialog_template':ensure_fixed_dialog_schema(conn);upsert_fixed_dialog(conn,items);conn.commit();log.info(f"✅ {table}: {len(items)} lignes upsert (bad_string=0) en {int((time.time()-t0)*1000)} ms.")
                                elif table=='m00_strings':ensure_table_schema(conn,table,unique_idx=_E);updated,skipped=update_only_en_by_ja(conn,table,items);conn.commit();log.info(f"✅ {table}: {updated} MAJ, {skipped} non trouvées (UPDATE-only) en {int((time.time()-t0)*1000)} ms.")
                                else:ensure_table_schema(conn,table,unique_idx=_B);upsert_rows(conn,table,items);conn.commit();log.info(f"✅ {table}: {len(items)} lignes upsert en {int((time.time()-t0)*1000)} ms.")
                except Exception as e:log.error(f"Erreur d'injection pour {table}: {e}")
def telecharger_patch_fr():
        "Télécharge et applique le patch FR (DAT/IDX) dans le dossier DQX de l'utilisateur.";F='w+b';E='installdirectory';D='config';C='data00000000.win32.dat0';B='Game/Content/Data';A='/'
        if is_dqx_process_running():log.exception('Veuillez fermer DQX avant de mettre à jour les fichiers DAT/IDX traduits.')
        if not check_if_running_as_admin():log.exception('Ce programme doit être exécuté en administrateur pour appliquer le patch FR DAT/IDX. Relancez-le en administrateur puis réessayez.')
        config=UserConfig();read_game_path=A.join([config.game_path,B,C])
        if not os.path.exists(read_game_path):
                default_game_path='C:/Program Files (x86)/SquareEnix/DRAGON QUEST X'
                if os.path.exists(default_game_path):config.update(section=D,key=E,value=default_game_path)
                else:
                        log.warning('Impossible de vérifier le dossier DRAGON QUEST X. Sélectionnez manuellement le dossier « DRAGON QUEST X » où le jeu est installé.')
                        while _B:
                                dqx_path=askdirectory()
                                if not dqx_path:log.error("Aucun dossier sélectionné (fenêtre fermée). Le programme va s'arrêter.")
                                dat0_path=A.join([dqx_path,B,C])
                                if os.path.isfile(dat0_path):config.update(section=D,key=E,value=dqx_path);log.success('Chemin DRAGON QUEST X vérifié.');break
                                else:log.warning('Chemin invalide. Sélectionnez le dossier « DRAGON QUEST X » où le jeu est installé.')
        config.reinit();dqx_path=A.join([config.game_path,B])
        if is_patchdaily_enabled():fr_dat_urls=['https://github.com/Sato2Carte/JSONDQXFR/releases/download/sub/data00000000.win32.dat1'];fr_idx_urls=['https://github.com/Sato2Carte/JSONDQXFR/releases/download/sub/data00000000.win32.idx'];log.info('Téléchargement des fichiers FR (Patch quotidien (Instable))…')
        else:fr_dat_urls=['https://github.com/Sato2Carte/JSONDQXFR/releases/download/dat%2Fidx/data00000000.win32.dat1'];fr_idx_urls=['https://github.com/Sato2Carte/JSONDQXFR/releases/download/dat%2Fidx/data00000000.win32.idx'];log.info('Téléchargement des fichiers FR…')
        dat_request,last_err=_A,_A
        for url in fr_dat_urls:
                try:dat_request=download_file(url);break
                except Exception as e:last_err=e;log.warning(f"Échec depuis {url} ({e}); tentative suivante…")
        if dat_request is _A:raise last_err or RuntimeError('Impossible de télécharger le fichier DAT1 FR.')
        idx_request,last_err=_A,_A
        for url in fr_idx_urls:
                try:idx_request=download_file(url);break
                except Exception as e:last_err=e;log.warning(f"Échec depuis {url} ({e}); tentative suivante…")
        if idx_request is _A:raise last_err or RuntimeError('Impossible de télécharger le fichier IDX FR.')
        with open(dqx_path+'/data00000000.win32.dat1',F)as f:f.write(dat_request.content)
        with open(dqx_path+'/data00000000.win32.idx',F)as f:f.write(idx_request.content)
        log.success('Patch FR DAT/IDX appliqué avec succès.')
def parse_arguments():A='store_true';parser=argparse.ArgumentParser(description='dqxclarity: A Japanese to English translation tool for Dragon Quest X.');parser.add_argument('-u','--disable-update-check',action=A,help='Disables checking for updates on each launch.');parser.add_argument('-c','--communication-window',action=A,help='Writes hooks into the game to translate the dialog window with a live translation service.');parser.add_argument('-p','--player-names',action=A,help='Scans for player names and changes them to their Romaji counterpart.');parser.add_argument('-n','--npc-names',action=A,help='Scans for NPC names and changes them to their Romaji counterpart.');parser.add_argument('-l','--community-logging',action=A,help='Enables dumping important game information that the dqxclarity devs need to continue this project.');parser.add_argument('-d','--update-dat',action=A,help='Update the translated idx and dat file with the latest from Github. Requires the game to be closed.');return parser.parse_args()
def main():
        A='Updating custom text in db.';args=parse_arguments();logs_dir=Path(get_project_root('logs'));logs_dir.mkdir(parents=_B,exist_ok=_B);log_path=get_project_root('logs/console.log');Path(log_path).unlink(missing_ok=_B);log=setup_logging();log.info('Running. Please wait until this window says "Done!" before logging into your character.');log.debug('Ensuring db structure.');create_db_schema();log.debug('Checking user_settings.ini.');UserConfig(warnings=_B)
        if not is_fr_launcher(_D):
                if args.update_dat:log.info('Updating DAT mod.');download_dat_files()
                if not args.disable_update_check:
                        log.info(A);check_for_updates(update=_B)
                        if is_serversidefr_enabled():mettre_a_jour_db_fr(log)
                        else:download_custom_files()
        elif not args.disable_update_check:
                telecharger_patch_fr();log.info(A);check_for_updates(update=_B)
                if is_serversidefr_enabled():mettre_a_jour_db_fr(log)
                else:download_custom_files()
        import_name_overrides()
        try:
                if not any(vars(args).values()):log.success('No options were selected. dqxclarity will exit.');time.sleep(3);sys.exit(0)
                wait_for_dqx_to_launch()
                if args.player_names or args.communication_window:start_process(name='Hook loader',target=activate_hooks,args=(args.player_names,args.communication_window))
                if args.communication_window:start_process(name='Walkthrough scanner',target=loop_scan_for_walkthrough,args=())
                if args.community_logging:log.warning('Logs can be found in the "logs" folder. You should only enable this flag if you were asked to by the dqxclarity team. This feature is unstable. You will not receive help if you\'ve enabled this on your own. Once you\'re done logging, you will need to manually close the dqxclarity window.');start_process(name='Community logging',target=start_logger,args=())
                if args.player_names or args.npc_names:start_process(name='Name scanner',target=run_scans,args=(args.player_names,args.npc_names))
                log.success('Done! Keep this window open (minimize it) and have fun on your adventure!')
        except Exception:log.exception('An exception occurred. dqxclarity will exit.');sys.exit(1)
if __name__=='__main__':main()
