import os
import sys
import time
import ctypes
import socket
import threading
import urllib.request
import urllib.error
import re
import unicodedata
import tkinter as tk
import logging
import json
import subprocess
import xml.etree.ElementTree as ET
from datetime import timedelta
from pathlib import Path

try:
    import PyATEMMax
    PYATEM_OK = True
except ImportError:
    PyATEMMax = None
    PYATEM_OK = False

from datetime import datetime
from html.parser import HTMLParser
from tkinter import ttk, messagebox, filedialog

try:
    from pypdf import PdfReader
    PYPDF_OK = True
except Exception:
    try:
        from PyPDF2 import PdfReader
        PYPDF_OK = True
    except Exception:
        PdfReader = None
        PYPDF_OK = False


# ============================================================================
# CONFIGURAÇÕES PADRÃO
# ============================================================================

CULTURA_URL = "https://cultura.uol.com.br/roteiro/"
CASPAR_HOST = "127.0.0.1"
CASPAR_PORT = 5250
CASPAR_CHANNEL = 1
CASPAR_LAYER = 1
MEDIA_ROOT = r"D:\media"
CASPAR_MEDIA_ROOT = r"D:\media"
POLL_SECONDS = 60
LATE_TOLERANCE_SECONDS = 4
AMCP_RETRIES = 3
AMCP_RETRY_DELAY = 0.5
LOG_DIR = r"D:\log"

# Modo eleitoral: configuração editável na tela.
ELECTORAL_WINDOWS_DEFAULT = [("13:00:00", "13:25:00"), ("20:30:00", "20:55:00")]
ATEM_IP_DEFAULT = "192.168.100.26"
ATEM_NORMAL_SOURCE = 1
ATEM_ELECTORAL_SOURCE = 2
ATEM_CASPAR_SOURCE = 8
ATEM_VMIX_SOURCE = 7
CASPAR_PREROLL_SECONDS = 0.35
CHANNEL_FPS = 60000 / 1001
DEFAULT_SLATE_SKIP_SECONDS = 7.0
OPERATIONAL_START_SECONDS = 5 * 3600
GRADE_CONFIRMATIONS_REQUIRED = 2
GRADE_CANDIDATE_MAX_AGE_SECONDS = 180

# AO VIVO — V1.34
LIVE_CULTURA_PATTERNS_DEFAULT = "JORNAL DA CULTURA;JORNAL DA TARDE;ANTIMATÉRIA;CARTÃO VERDE"
LIVE_WEEKDAY_MORNING_DEFAULT = ("07:00:00", "08:00:00")
LIVE_WEEKDAY_EVENING_DEFAULT = ("18:00:00", "19:00:00")
LIVE_SATURDAY_DEFAULT = ("07:00:00", "08:30:00")
# Durante o período eleitoral, o programa local de sábado começa às 07:25.
LIVE_SATURDAY_ELECTORAL_DEFAULT = ("07:25:00", "08:30:00")

STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scheduler_cultura_estado.json")
PROGRAM_EVENTS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "eventos_programa.json")



def electoral_norm(text):
    text = unicodedata.normalize("NFKD", str(text or ""))
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = text.upper()
    text = re.sub(r"\([^)]*\)", " ", text)
    text = re.sub(r"[^A-Z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()

def electoral_tokens(text):
    stop = {"PARTIDO","FEDERACAO","COLIGACAO","BRASILEIRO","BRASILEIRA","DO","DA","DE","DOS","DAS","E","FE","BRASIL"}
    return {t for t in electoral_norm(text).split() if t and t not in stop}

def daypart_key(value):
    try:
        hour = value.hour if isinstance(value, datetime) else int(str(value).split(":")[0])
    except Exception:
        hour = 0
    if 5 <= hour < 11: return "05-11"
    if 11 <= hour < 18: return "11-18"
    return "18-24"

# ============================================================================
# LOG
# ============================================================================

def setup_logging():
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        log_file = os.path.join(
            LOG_DIR,
            f"caspar_scheduler_{datetime.now().strftime('%Y-%m-%d')}.log"
        )
    except Exception:
        log_file = os.path.join(
            os.getcwd(),
            f"caspar_scheduler_{datetime.now().strftime('%Y-%m-%d')}.log"
        )

    logging.basicConfig(
        filename=log_file,
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        encoding="utf-8"
    )

    logging.info("Scheduler iniciado.")
    return log_file


# ============================================================================
# PERSISTÊNCIA
# ============================================================================

def load_state():
    try:
        if os.path.isfile(STATE_FILE):
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
    except Exception:
        logging.exception("Falha ao carregar estado persistente.")
    return {}


def save_state_file(data):
    try:
        tmp = STATE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, STATE_FILE)
        return True
    except Exception:
        logging.exception("Falha ao salvar estado persistente.")
        return False


def load_program_events_file():
    """Lê a base separada usada apenas pelas âncoras de INSERT AVULSO."""
    try:
        if os.path.isfile(PROGRAM_EVENTS_FILE):
            with open(PROGRAM_EVENTS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and isinstance(data.get("programas"), list):
                return data
    except Exception:
        logging.exception("Falha ao carregar eventos_programa.json.")
    return {"data_grade": "", "atualizado_em": "", "gerado_em": "", "programas": []}


def save_program_events_file(programs, source_updated="--:--:--"):
    """Grava somente eventos cujo Tipo é PROGRAMA, em JSON independente."""
    try:
        payload = {
            "data_grade": datetime.now().strftime("%d/%m/%Y"),
            "atualizado_em": source_updated,
            "gerado_em": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
            "programas": programs,
        }
        tmp = PROGRAM_EVENTS_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        os.replace(tmp, PROGRAM_EVENTS_FILE)
        return True
    except Exception:
        logging.exception("Falha ao salvar eventos_programa.json.")
        return False


# ============================================================================
# ADMINISTRADOR
# ============================================================================

def is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def run_as_admin():
    if os.name != "nt" or is_admin():
        return True

    try:
        script = os.path.abspath(sys.argv[0])

        if getattr(sys, "frozen", False):
            executable = sys.executable
            params = " ".join(f'"{arg}"' for arg in sys.argv[1:])
        else:
            executable = sys.executable
            params = " ".join(
                f'"{arg}"'
                for arg in [script] + sys.argv[1:]
            )

        result = ctypes.windll.shell32.ShellExecuteW(
            None,
            "runas",
            executable,
            params,
            os.getcwd(),
            1
        )

        if result <= 32:
            raise OSError(f"ShellExecuteW retornou {result}")

        return False

    except Exception as exc:
        ctypes.windll.user32.MessageBoxW(
            None,
            f"Não foi possível iniciar como Administrador.\n\n{exc}",
            "CasparCG Scheduler",
            0x10
        )
        sys.exit(1)


# ============================================================================
# HTML TV CULTURA
# ============================================================================

def norm(value):
    return " ".join((value or "").strip().split()).upper()


def live_norm(value):
    """Normalização tolerante a acentos para casar nomes da grade ao vivo."""
    text = norm(value)
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    return text


def duration_to_seconds(value):
    value = (value or "").strip()

    m = re.match(r"^(\d{2}):(\d{2}):(\d{2})", value)
    if not m:
        return 0

    h, mnt, s = map(int, m.groups())
    return h * 3600 + mnt * 60 + s


class CulturaTableParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows = []
        self._in_tr = False
        self._cell_tag = None
        self._cell_parts = []
        self._row = []

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()

        if tag == "tr":
            self._in_tr = True
            self._row = []

        elif self._in_tr and tag in ("td", "th"):
            self._cell_tag = tag
            self._cell_parts = []

        elif self._cell_tag is not None and tag == "br":
            self._cell_parts.append(" ")

    def handle_data(self, data):
        if self._cell_tag is not None:
            self._cell_parts.append(data)

    def handle_endtag(self, tag):
        tag = tag.lower()

        if self._cell_tag is not None and tag == self._cell_tag:
            value = " ".join("".join(self._cell_parts).split())
            self._row.append(value)
            self._cell_tag = None
            self._cell_parts = []

        elif tag == "tr" and self._in_tr:
            if self._row:
                self.rows.append(self._row)

            self._row = []
            self._in_tr = False


def download_cultura_html(url):
    # Duplo cache-buster. Alguns proxies/CDNs ignoram um parâmetro conhecido,
    # por isso usamos timestamp em nanossegundos + valor aleatório do relógio.
    sep = "&" if "?" in url else "?"
    token = time.time_ns()
    fresh_url = (
        f"{url}{sep}_nocache={token}"
        f"&_ts={int(time.time() * 1000)}"
    )

    request = urllib.request.Request(
        fresh_url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/152.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
            "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.6",
            "Accept-Encoding": "identity",
            "Cache-Control": "no-cache, no-store, max-age=0, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
            "Connection": "close",
            "Referer": "https://cultura.uol.com.br/",
        },
        method="GET"
    )

    # opener próprio para evitar reaproveitamento de conexão/resposta.
    opener = urllib.request.build_opener()
    with opener.open(request, timeout=20) as response:
        data = response.read()

    if not data:
        raise RuntimeError("A TV Cultura respondeu sem conteúdo.")

    return data


def extract_cultura_metadata(html_text):
    # Remove tags apenas para obter um texto contínuo e confiável.
    plain = re.sub(r"<[^>]+>", " ", html_text)
    plain = " ".join(plain.split())

    updated_match = re.search(
        r"Atualizado\s+em\s*:\s*(\d{2}:\d{2}:\d{2})",
        plain,
        flags=re.IGNORECASE
    )

    modified_match = re.search(
        r"[ÚU]ltima\s+modifica[cç][aã]o\s+na\s+lista\s+[aà]s\s*:\s*"
        r"(\d{2}:\d{2}:\d{2})",
        plain,
        flags=re.IGNORECASE
    )

    return {
        "updated": updated_match.group(1) if updated_match else "--:--:--",
        "modified": modified_match.group(1) if modified_match else "--:--:--",
    }


def parse_cultura(html_bytes):
    html_text = html_bytes.decode("utf-8", errors="replace")
    metadata = extract_cultura_metadata(html_text)

    parser = CulturaTableParser()
    parser.feed(html_text)
    parser.close()

    events = []
    grade_events = []
    program_events = []

    for row in parser.rows:
        if len(row) < 5:
            continue

        start = norm(row[0])
        duration_raw = norm(row[1])
        divulgation = norm(row[2])
        category = norm(row[3])
        title = " ".join(row[4:]).strip()

        if not re.fullmatch(r"\d{2}:\d{2}:\d{2}", start):
            continue

        duration = duration_to_seconds(duration_raw)

        # V1.34: catálogo independente de âncoras. Aqui o filtro é SOMENTE
        # Tipo == PROGRAMA, sem exigir ESTADO. Isso contempla a grade mostrada
        # pela Cultura mesmo quando a coluna Veiculação vem vazia.
        if category == "PROGRAMA":
            end_time = start
            try:
                total = sum(int(x) * 60 ** i for i, x in enumerate(reversed(start.split(":")))) + duration
                total %= 24 * 3600
                end_time = f"{total // 3600:02d}:{(total % 3600) // 60:02d}:{total % 60:02d}"
            except Exception:
                pass
            program_events.append({
                "start": start,
                "duration": duration,
                "end": end_time,
                "title": title,
                "divulgation": divulgation,
                "category": category,
            })

        # V1.36.5 — grade de referência INTEGRAL.
        # Preserva todas as linhas válidas da Cultura, independentemente de
        # Veiculação/Tipo. A grade integral é usada para visualização quando o
        # modo eleitoral está DESABILITADO; não vira insert automático.
        grade_events.append({
            "start": start,
            "duration": duration,
            "title": title,
            "divulgation": divulgation,
            "category": category,
        })

        # Inserts políticos continuam com o filtro original, sem alteração.
        if divulgation != "ESTADO":
            continue

        if category != "HORARIO POLITICO":
            continue

        events.append({
            "start": start,
            "duration": duration,
            "title": title,
            "divulgation": divulgation,
            "category": category,
            "is_cultura_political_insert": True,
        })

    # Uma única inserção por horário.
    unique = []
    seen = set()

    for event in events:
        if event["start"] in seen:
            continue

        seen.add(event["start"])
        unique.append(event)

    unique.sort(key=lambda e: e["start"])

    # Também deduplicamos a grade completa por horário+título.
    grade_unique = []
    grade_seen = set()
    for event in grade_events:
        key = (event["start"], live_norm(event["title"]))
        if key in grade_seen:
            continue
        grade_seen.add(key)
        grade_unique.append(event)
    grade_unique.sort(key=lambda e: e["start"])

    # Catálogo PROGRAMA: preserva ocorrências distintas pelo horário+título.
    program_unique = []
    program_seen = set()
    for event in program_events:
        key = (event["start"], live_norm(event["title"]))
        if key in program_seen:
            continue
        program_seen.add(key)
        program_unique.append(event)
    program_unique.sort(key=lambda e: e["start"])

    return unique, metadata, grade_unique, program_unique


# ============================================================================
# AMCP / CASPARCG
# ============================================================================

class CasparAMCP:
    def __init__(self, host, port, timeout=3):
        self.host = host
        self.port = port
        self.timeout = timeout

    def send(self, command):
        data = (command.strip() + "\r\n").encode("utf-8")
        last_error = None

        for attempt in range(1, AMCP_RETRIES + 1):
            try:
                with socket.create_connection(
                    (self.host, self.port),
                    timeout=self.timeout
                ) as sock:
                    sock.sendall(data)
                    sock.settimeout(self.timeout)

                    chunks = []

                    while True:
                        try:
                            part = sock.recv(4096)
                            if not part:
                                break

                            chunks.append(part)

                            if b"\r\n" in part:
                                break

                        except socket.timeout:
                            break

                response = b"".join(chunks).decode(
                    "utf-8",
                    errors="replace"
                ).strip()

                logging.info(
                    "AMCP OK | tentativa=%s | comando=%s | resposta=%s",
                    attempt,
                    command,
                    response.replace("\r", " ").replace("\n", " ")
                )

                return response

            except Exception as exc:
                last_error = exc
                logging.warning(
                    "AMCP falhou | tentativa=%s/%s | comando=%s | erro=%s",
                    attempt,
                    AMCP_RETRIES,
                    command,
                    exc
                )

                if attempt < AMCP_RETRIES:
                    time.sleep(AMCP_RETRY_DELAY)

        raise last_error


# ============================================================================
# APLICATIVO
# ============================================================================

class SchedulerApp(tk.Tk):
    def __init__(self):
        super().__init__()

        self.saved_state = load_state()

        self.title("TV Cultura -> CasparCG Scheduler | V1.36.6 LOGO INTERVALOS CORRIGIDO")
        self.geometry("1180x790")
        self.minsize(1000, 700)

        self.url_var = tk.StringVar(value=self.saved_state.get("url", CULTURA_URL))

        self.host_var = tk.StringVar(value=self.saved_state.get("caspar_host", CASPAR_HOST))
        self.port_var = tk.StringVar(value=str(self.saved_state.get("caspar_port", CASPAR_PORT)))
        self.channel_var = tk.StringVar(value=str(self.saved_state.get("caspar_channel", CASPAR_CHANNEL)))
        self.layer_var = tk.StringVar(value=str(self.saved_state.get("caspar_layer", CASPAR_LAYER)))

        self.media_root_var = tk.StringVar(value=self.saved_state.get("media_root", r"D:\media\2026\ELEICOES26"))
        self.caspar_media_root_var = tk.StringVar(value=self.saved_state.get("caspar_media_root", CASPAR_MEDIA_ROOT))
        self.default_media_var = tk.StringVar(value=self.saved_state.get("default_media", ""))
        self.selected_media_var = tk.StringVar(value=self.saved_state.get("selected_media", ""))
        self.skip_slate_var = tk.BooleanVar(value=bool(self.saved_state.get("skip_slate_selection", False)))
        self.skip_slate_seconds_var = tk.StringVar(value=str(self.saved_state.get("skip_slate_seconds", DEFAULT_SLATE_SKIP_SECONDS)))
        self.integral_selection_var = tk.BooleanVar(value=bool(self.saved_state.get("integral_selection", False)))

        self.poll_var = tk.StringVar(value=str(self.saved_state.get("poll_seconds", POLL_SECONDS)))
        self.grade_offset_var = tk.StringVar(value=str(self.saved_state.get("grade_offset_seconds", 0)))

        self.cultura_status_var = tk.StringVar(
            value="Cultura: aguardando primeira atualização"
        )
        self.cultura_updated_var = tk.StringVar(
            value="Atualizado em: --:--:--"
        )
        self.cultura_modified_var = tk.StringVar(
            value="Última modificação: --:--:--"
        )
        self.cultura_sync_var = tk.StringVar(
            value="Sincronização: aguardando"
        )
        self.last_cultura_updated = None
        self.last_cultura_modified = None
        self.last_cultura_signature = None

        # V1.35.2 — grade recebida/candidata x grade operacional confirmada.
        self.operational_cultura_insert_events = []
        self.operational_cultura_grade_events = []
        self.operational_program_events = []
        self.operational_grade_signature = None
        # V1.35.8 — marcador REAL da lista publicada pela Cultura.
        # "Atualizado em" é apenas horário de consulta/ping e NÃO governa a grade.
        self.operational_modified_marker = None
        self.candidate_cultura_insert_events = []
        self.candidate_cultura_grade_events = []
        self.candidate_program_events = []
        self.candidate_grade_signature = None
        self.candidate_grade_count = 0
        self.candidate_grade_first_seen = 0.0
        self.grade_confirmation_pending = False
        self.grade_quick_confirm_after_id = None
        self.grade_refresh_ok = True

        self.caspar_status_var = tk.StringVar(
            value="CasparCG: não testado"
        )
        self.auto_status_var = tk.StringVar(
            value="AUTOMÁTICO: DESARMADO"
        )
        self.clock_var = tk.StringVar(value="--:--:--")
        self.next_event_var = tk.StringVar(value="Próximo: --")
        self.countdown_var = tk.StringVar(value="Faltam: --")

        self.electoral_enabled_var = tk.BooleanVar(value=bool(self.saved_state.get("electoral_enabled", False)))
        self.electoral_openclose_var = tk.BooleanVar(value=bool(self.saved_state.get("electoral_openclose", False)))
        self.electoral_start1_var = tk.StringVar(value=self.saved_state.get("electoral_start1", "13:00:00"))
        self.electoral_end1_var = tk.StringVar(value=self.saved_state.get("electoral_end1", "13:25:00"))
        self.electoral_start2_var = tk.StringVar(value=self.saved_state.get("electoral_start2", "20:30:00"))
        self.electoral_end2_var = tk.StringVar(value=self.saved_state.get("electoral_end2", "20:55:00"))
        self.electoral_open_media_var = tk.StringVar(value=self.saved_state.get("electoral_open_media", ""))
        self.electoral_close_media_var = tk.StringVar(value=self.saved_state.get("electoral_close_media", ""))
        self.electoral_status_var = tk.StringVar(value="ELEITORAL: DESABILITADO")
        self.electoral_boundary_executed = set()

        self.electoral_cadastro_path_var = tk.StringVar(
            value=self.saved_state.get("electoral_cadastro_path", "")
        )
        self.electoral_cadastro_status_var = tk.StringVar(value="Cadastro eleitoral: não carregado")
        self.electoral_registration = {}
        self.electoral_daily_plan = []
        self.electoral_daily_plan_date = None
        self.electoral_rotation_history = dict(self.saved_state.get("electoral_rotation_history", {}))
        self.electoral_valid_plays = list(self.saved_state.get("electoral_valid_plays", []))
        # V1.35.3 — várias mídias PADRÃO eleitorais, alternadas em sequência.
        saved_defaults = self.saved_state.get("electoral_default_media_list", [])
        if not isinstance(saved_defaults, list):
            saved_defaults = []
        legacy_default = self.saved_state.get("default_media", "")
        self.electoral_default_media_list = [str(x) for x in saved_defaults if str(x).strip()]
        if not self.electoral_default_media_list and legacy_default:
            self.electoral_default_media_list = [legacy_default]
        self.electoral_default_rotation_index = int(self.saved_state.get("electoral_default_rotation_index", 0) or 0)
        # Memória de transição para detectar SAÍDA real da janela eleitoral.
        self._electoral_was_locked = False

        # AO VIVO — Cultura + programação local via vMix.
        self.live_enabled_var = tk.BooleanVar(value=True)
        self.live_cultura_patterns_var = tk.StringVar(value=self.saved_state.get("live_cultura_patterns", LIVE_CULTURA_PATTERNS_DEFAULT))
        self.live_wd_morning_start_var = tk.StringVar(value=self.saved_state.get("live_wd_morning_start", LIVE_WEEKDAY_MORNING_DEFAULT[0]))
        self.live_wd_morning_end_var = tk.StringVar(value=self.saved_state.get("live_wd_morning_end", LIVE_WEEKDAY_MORNING_DEFAULT[1]))
        self.live_wd_evening_start_var = tk.StringVar(value=self.saved_state.get("live_wd_evening_start", LIVE_WEEKDAY_EVENING_DEFAULT[0]))
        self.live_wd_evening_end_var = tk.StringVar(value=self.saved_state.get("live_wd_evening_end", LIVE_WEEKDAY_EVENING_DEFAULT[1]))
        self.live_sat_start_var = tk.StringVar(value=self.saved_state.get("live_sat_start", LIVE_SATURDAY_DEFAULT[0]))
        self.live_sat_end_var = tk.StringVar(value=self.saved_state.get("live_sat_end", LIVE_SATURDAY_DEFAULT[1]))
        self.live_sat_electoral_start_var = tk.StringVar(value=self.saved_state.get("live_sat_electoral_start", LIVE_SATURDAY_ELECTORAL_DEFAULT[0]))
        self.live_sat_electoral_end_var = tk.StringVar(value=self.saved_state.get("live_sat_electoral_end", LIVE_SATURDAY_ELECTORAL_DEFAULT[1]))
        self.live_status_var = tk.StringVar(value="PGM JSON: aguardando cadastro")
        self.pgm_json_path_var = tk.StringVar(value=self.saved_state.get(
            "pgm_json_path",
            str(Path(__file__).resolve().parent / "programas.json")
        ))
        self.pgm_json_status_var = tk.StringVar(value="PGM JSON: não carregado")
        self.pgm_records = []
        self.live_return_source = None
        self.cultura_grade_events = []
        self.program_events_db = load_program_events_file()
        self.program_events = list(self.program_events_db.get("programas", []))
        self.live_active = False
        self.live_source = None
        self.live_return_source = None
        self.live_title = None
        self.live_key = None
        self.live_planned_end = None
        self.live_dismissed = set()
        self.live_overrun_logged = False
        # V1.34 — horários automáticos que caem dentro de programa Cultura marcado
        # ficam em suspense até o fim previsto; depois a grade é atualizada.
        self.live_suspended_keys = set()
        self.live_resync_pending = False

        self.atem_ip_var = tk.StringVar(value=self.saved_state.get("atem_ip", ATEM_IP_DEFAULT))
        self.atem_normal_var = tk.StringVar(value=str(self.saved_state.get("atem_normal_source", ATEM_NORMAL_SOURCE)))
        self.atem_electoral_var = tk.StringVar(value=str(self.saved_state.get("atem_electoral_source", ATEM_ELECTORAL_SOURCE)))
        self.atem_caspar_var = tk.StringVar(value=str(self.saved_state.get("atem_caspar_source", ATEM_CASPAR_SOURCE)))
        self.atem_vmix_var = tk.StringVar(value=str(self.saved_state.get("atem_vmix_source", ATEM_VMIX_SOURCE)))
        self.atem_status_var = tk.StringVar(value="ATEM: desconectado")
        # V1.36.4 — LOGO automático via MP1 já configurado no ATEM / DSK1.
        # Regra: CULTURA no PROGRAM + Veiculação vazia + Tipo PROGRAMA = ON.
        self.logo_mp1_status_var = tk.StringVar(value="LOGO MP1: aguardando")
        self.logo_mp1_on = None
        self.atem = None
        self.atem_connected = False
        self.local_insertion_active = False
        self.local_insertion_until = None

        # V1.34 — BREAK ASSISTIDO / PLAYLIST AGREGADA durante AO VIVO.
        self.break_playlist_active = False
        self.break_playlist_stop_now = threading.Event()
        self.break_playlist_finish_current = threading.Event()
        self.break_playlist_status_var = tk.StringVar(value="BREAK ASSISTIDO: aguardando")

        self.events = []
        self.media_overrides = dict(self.saved_state.get("media_overrides", {}))
        self.slate_skip_overrides = dict(self.saved_state.get("slate_skip_overrides", {}))
        self.executed = set()

        # V1.34 — inserts avulsos persistentes e controle de virada diária.
        self.avulsos = list(self.saved_state.get("avulsos", []))
        # V1.34 — reservas de breaks manuais vinculadas a eventos PROGRAMA.
        self.manual_breaks = list(self.saved_state.get("manual_breaks", []))
        self.manual_break_step_seconds = int(self.saved_state.get("manual_break_step_seconds", 5) or 5)
        self.integral_overrides = dict(self.saved_state.get("integral_overrides", {}))
        self.current_day_key = datetime.now().strftime("%Y-%m-%d")
        self.projection_status_var = tk.StringVar(value="Fonte reserva: XML/TXT somente se HTML falhar")
        self.projection_events = []
        self.projection_grade_events = []
        self.projection_date = None
        self._media_duration_cache = {}
        self.last_projection_fetch_day = None

        self.armed = False
        self.refresh_in_progress = False
        self.next_refresh_at = 0.0

        self._build_ui()
        self._refresh_default_media_display()
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        if self.electoral_cadastro_path_var.get().strip():
            self.after(250, lambda: self.load_electoral_registration(manual=False))

        self.after(100, self._clock_loop)
        self.after(350, self.load_pgm_json)
        self.after(700, self.refresh_now)
        self.after(1000, self.auto_startup_connect_and_arm)

    # ------------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------------

    def _build_ui(self):
        # Layout operacional: parâmetros à esquerda e lista de inserts à direita.
        root = ttk.Frame(self, padding=10)
        root.pack(fill="both", expand=True)
        root.columnconfigure(1, weight=1)
        root.rowconfigure(0, weight=1)

        # Painel esquerdo com rolagem vertical própria.
        # Assim as configurações nunca ficam escondidas em telas mais baixas.
        left_outer = ttk.Frame(root, width=360)
        left_outer.grid(row=0, column=0, sticky="ns", padx=(0, 10))
        left_outer.grid_propagate(False)
        left_outer.rowconfigure(0, weight=1)
        left_outer.columnconfigure(0, weight=1)

        left_canvas = tk.Canvas(left_outer, highlightthickness=0, borderwidth=0)
        left_scrollbar = ttk.Scrollbar(
            left_outer, orient="vertical", command=left_canvas.yview
        )
        left_canvas.configure(yscrollcommand=left_scrollbar.set)

        left_canvas.grid(row=0, column=0, sticky="nsew")
        left_scrollbar.grid(row=0, column=1, sticky="ns")

        left = ttk.Frame(left_canvas)
        left_window = left_canvas.create_window((0, 0), window=left, anchor="nw")

        def _update_left_scrollregion(event=None):
            left_canvas.configure(scrollregion=left_canvas.bbox("all"))

        def _resize_left_content(event):
            # O conteúdo acompanha a largura útil do painel.
            left_canvas.itemconfigure(left_window, width=event.width)

        left.bind("<Configure>", _update_left_scrollregion)
        left_canvas.bind("<Configure>", _resize_left_content)

        # Rolagem pelo mouse somente quando o cursor estiver sobre o painel esquerdo.
        def _left_mousewheel(event):
            if event.delta:
                left_canvas.yview_scroll(-1 * int(event.delta / 120), "units")
            return "break"

        def _bind_left_mousewheel(event=None):
            left_canvas.bind_all("<MouseWheel>", _left_mousewheel)

        def _unbind_left_mousewheel(event=None):
            left_canvas.unbind_all("<MouseWheel>")

        left_canvas.bind("<Enter>", _bind_left_mousewheel)
        left_canvas.bind("<Leave>", _unbind_left_mousewheel)
        left.bind("<Enter>", _bind_left_mousewheel)
        left.bind("<Leave>", _unbind_left_mousewheel)

        right = ttk.Frame(root)
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(2, weight=1)

        # ===================== ESQUERDA =====================
        source = ttk.LabelFrame(left, text="TV Cultura", padding=8)
        source.pack(fill="x", pady=(0, 7))
        source.columnconfigure(1, weight=1)

        ttk.Label(source, text="HTML:").grid(row=0, column=0, sticky="w")
        ttk.Entry(source, textvariable=self.url_var, width=35).grid(
            row=0, column=1, columnspan=2, sticky="ew", padx=(5, 0)
        )
        ttk.Label(source, text="Atualizar a cada:").grid(row=1, column=0, sticky="w", pady=(5, 0))
        ttk.Entry(source, textvariable=self.poll_var, width=7).grid(
            row=1, column=1, sticky="w", padx=(5, 0), pady=(5, 0)
        )
        ttk.Label(source, text="segundos").grid(row=1, column=2, sticky="w", pady=(5, 0))

        # V1.34 — correção operacional da grade quando o sinal real adianta/atrasa
        # antes da atualização do site. Negativo = executar antes; positivo = depois.
        ttk.Label(source, text="OFFSET GRADE:").grid(row=2, column=0, sticky="w", pady=(5, 0))
        grade_offset_frame = ttk.Frame(source)
        grade_offset_frame.grid(row=2, column=1, columnspan=2, sticky="w", padx=(5, 0), pady=(5, 0))

        ttk.Button(
            grade_offset_frame, text="- 1s", width=5,
            command=lambda: self.adjust_grade_offset(-1)
        ).pack(side="left")
        grade_offset_entry = ttk.Entry(
            grade_offset_frame, textvariable=self.grade_offset_var,
            width=7, justify="center"
        )
        grade_offset_entry.pack(side="left", padx=4)
        ttk.Button(
            grade_offset_frame, text="+ 1s", width=5,
            command=lambda: self.adjust_grade_offset(1)
        ).pack(side="left")
        ttk.Button(
            grade_offset_frame, text="ZERAR", width=6,
            command=self.reset_grade_offset
        ).pack(side="left", padx=(4, 0))

        grade_offset_entry.bind("<Return>", lambda e: self.apply_grade_offset_from_ui())
        grade_offset_entry.bind("<FocusOut>", lambda e: self.apply_grade_offset_from_ui())
        grade_offset_entry.bind("<Up>", lambda e: (self.adjust_grade_offset(1), "break")[1])
        grade_offset_entry.bind("<Down>", lambda e: (self.adjust_grade_offset(-1), "break")[1])

        ttk.Label(
            source,
            text="− = Cultura adiantada / + = Cultura atrasada",
            font=("Segoe UI", 8)
        ).grid(row=3, column=0, columnspan=3, sticky="w")

        ttk.Label(source, textvariable=self.cultura_updated_var).grid(
            row=4, column=0, columnspan=3, sticky="w", pady=(5, 0)
        )
        ttk.Label(source, textvariable=self.cultura_modified_var).grid(
            row=5, column=0, columnspan=3, sticky="w"
        )
        ttk.Label(source, textvariable=self.cultura_sync_var).grid(
            row=6, column=0, columnspan=3, sticky="w"
        )
        ttk.Label(source, textvariable=self.projection_status_var, wraplength=325).grid(
            row=7, column=0, columnspan=3, sticky="w"
        )
        ttk.Button(source, text="ATUALIZAR AGORA", command=self.refresh_now).grid(
            row=8, column=0, columnspan=3, sticky="ew", pady=(6, 0)
        )

        caspar = ttk.LabelFrame(left, text="CasparCG / AMCP", padding=8)
        caspar.pack(fill="x", pady=(0, 7))

        ttk.Label(caspar, text="Host").grid(row=0, column=0, sticky="w")
        ttk.Entry(caspar, textvariable=self.host_var, width=14).grid(row=0, column=1, padx=4)
        ttk.Label(caspar, text="Porta").grid(row=0, column=2)
        ttk.Entry(caspar, textvariable=self.port_var, width=6).grid(row=0, column=3, padx=4)
        ttk.Label(caspar, text="Canal").grid(row=1, column=0, sticky="w", pady=(5, 0))
        ttk.Entry(caspar, textvariable=self.channel_var, width=5).grid(row=1, column=1, sticky="w", padx=4, pady=(5, 0))
        ttk.Label(caspar, text="Layer").grid(row=1, column=2, pady=(5, 0))
        ttk.Entry(caspar, textvariable=self.layer_var, width=5).grid(row=1, column=3, sticky="w", padx=4, pady=(5, 0))
        ttk.Button(caspar, text="TESTAR CASPAR", command=self.test_caspar).grid(
            row=2, column=0, columnspan=4, sticky="ew", pady=(6, 0)
        )

        atem = ttk.LabelFrame(left, text="ATEM Television Studio HD", padding=8)
        atem.pack(fill="x", pady=(0, 7))

        ttk.Label(atem, text="IP:").grid(row=0, column=0, sticky="w")
        ttk.Entry(atem, textvariable=self.atem_ip_var, width=17).grid(row=0, column=1, sticky="w")
        ttk.Button(atem, text="CONECTAR", command=self.connect_atem).grid(
            row=0, column=2, sticky="ew", padx=(6, 0)
        )

        ttk.Label(atem, text="CULTURA-SP  HDMI 1").grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(atem, textvariable=self.atem_normal_var, width=5).grid(row=1, column=1, sticky="w", pady=(6, 0))
        ttk.Button(
            atem, text="CULTURA-SP",
            command=lambda: self.atem_set_program(self.atem_normal_source())
        ).grid(row=1, column=2, sticky="ew", padx=(6, 0), pady=(6, 0))

        ttk.Label(atem, text="TVE-CURITIBA HDMI 2").grid(row=2, column=0, sticky="w", pady=(4, 0))
        ttk.Entry(atem, textvariable=self.atem_electoral_var, width=5).grid(row=2, column=1, sticky="w", pady=(4, 0))
        ttk.Button(
            atem, text="TVE-CURITIBA",
            command=lambda: self.atem_set_program(self.atem_electoral_source())
        ).grid(row=2, column=2, sticky="ew", padx=(6, 0), pady=(4, 0))

        ttk.Label(atem, text="vMIX          SDI 7").grid(row=3, column=0, sticky="w", pady=(4, 0))
        ttk.Entry(atem, textvariable=self.atem_vmix_var, width=5).grid(row=3, column=1, sticky="w", pady=(4, 0))
        ttk.Button(
            atem, text="vMIX",
            command=lambda: self.atem_set_program(int(self.atem_vmix_var.get().strip()))
        ).grid(row=3, column=2, sticky="ew", padx=(6, 0), pady=(4, 0))

        ttk.Label(atem, text="CASPAR-LOCAL  SDI 8").grid(row=4, column=0, sticky="w", pady=(4, 0))
        ttk.Entry(atem, textvariable=self.atem_caspar_var, width=5).grid(row=4, column=1, sticky="w", pady=(4, 0))
        ttk.Button(
            atem, text="CASPAR-LOCAL",
            command=lambda: self.atem_set_program(self.atem_caspar_source())
        ).grid(row=4, column=2, sticky="ew", padx=(6, 0), pady=(4, 0))

        ttk.Label(
            atem, textvariable=self.atem_status_var, font=("Segoe UI", 9, "bold")
        ).grid(row=5, column=0, columnspan=3, sticky="w", pady=(6, 0))
        ttk.Label(
            atem, textvariable=self.logo_mp1_status_var, font=("Segoe UI", 9, "bold")
        ).grid(row=6, column=0, columnspan=3, sticky="w", pady=(3, 0))

        live = ttk.LabelFrame(left, text="PROGRAMAS AUTOMÁTICOS — BACKEND JSON", padding=8)
        live.pack(fill="x", pady=(0, 7))
        live.columnconfigure(0, weight=1)

        ttk.Label(live, text="Cadastro externo: programas.json",
                  font=("Segoe UI", 9, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Label(live, textvariable=self.pgm_json_status_var, wraplength=325).grid(
            row=1, column=0, sticky="w", pady=(4, 0)
        )
        self.pgm_view = tk.Listbox(live, height=6, exportselection=False)
        self.pgm_view.grid(row=2, column=0, sticky="ew", pady=(5, 0))

        pgm_buttons = ttk.Frame(live)
        pgm_buttons.grid(row=3, column=0, sticky="ew", pady=(5, 0))
        ttk.Button(pgm_buttons, text="RECARREGAR JSON", command=self.load_pgm_json).pack(
            side="left", fill="x", expand=True
        )
        ttk.Button(pgm_buttons, text="ABRIR CADASTRO PGM", command=self.open_pgm_cadastro).pack(
            side="left", fill="x", expand=True, padx=(4, 0)
        )
        ttk.Label(live, textvariable=self.live_status_var,
                  font=("Segoe UI", 9, "bold"), wraplength=325).grid(
            row=4, column=0, sticky="w", pady=(6, 0)
        )
        ttk.Button(live, text="ENCERRAR PGM AGORA", command=self.end_live_now).grid(
            row=5, column=0, sticky="ew", pady=(6, 0)
        )

        electoral = ttk.LabelFrame(left, text="Modo eleitoral (opcional)", padding=8)
        electoral.pack(fill="x", pady=(0, 7))

        ttk.Checkbutton(
            electoral, text="HABILITAR PERÍODO ELEITORAL",
            variable=self.electoral_enabled_var, command=self.on_electoral_toggle
        ).grid(row=0, column=0, columnspan=4, sticky="w")

        ttk.Checkbutton(
            electoral, text="Mídia de abertura/encerramento",
            variable=self.electoral_openclose_var
        ).grid(row=1, column=0, columnspan=4, sticky="w", pady=(3, 0))

        ttk.Label(electoral, text="Janela 1").grid(row=2, column=0, sticky="w", pady=(5, 0))
        ttk.Entry(electoral, textvariable=self.electoral_start1_var, width=9).grid(row=2, column=1, pady=(5, 0))
        ttk.Label(electoral, text="até").grid(row=2, column=2, padx=4, pady=(5, 0))
        ttk.Entry(electoral, textvariable=self.electoral_end1_var, width=9).grid(row=2, column=3, pady=(5, 0))

        ttk.Label(electoral, text="Janela 2").grid(row=3, column=0, sticky="w", pady=(3, 0))
        ttk.Entry(electoral, textvariable=self.electoral_start2_var, width=9).grid(row=3, column=1, pady=(3, 0))
        ttk.Label(electoral, text="até").grid(row=3, column=2, padx=4, pady=(3, 0))
        ttk.Entry(electoral, textvariable=self.electoral_end2_var, width=9).grid(row=3, column=3, pady=(3, 0))

        ttk.Label(electoral, textvariable=self.electoral_status_var, font=("Segoe UI", 9, "bold")).grid(
            row=4, column=0, columnspan=4, sticky="w", pady=(5, 0)
        )

        ttk.Label(electoral, text="Cadastro eleitoral:").grid(row=5, column=0, sticky="w", pady=(6,0))
        ttk.Entry(electoral, textvariable=self.electoral_cadastro_path_var, width=22).grid(
            row=5, column=1, columnspan=2, sticky="ew", pady=(6,0)
        )
        ttk.Button(electoral, text="...", width=3, command=self.choose_electoral_registration).grid(
            row=5, column=3, pady=(6,0)
        )
        ttk.Button(electoral, text="CARREGAR / ATUALIZAR CADASTRO",
                   command=lambda: self.load_electoral_registration(manual=True)).grid(
            row=6, column=0, columnspan=4, sticky="ew", pady=(4,0)
        )
        ttk.Label(electoral, textvariable=self.electoral_cadastro_status_var,
                  wraplength=320, font=("Segoe UI",8,"bold")).grid(
            row=7, column=0, columnspan=4, sticky="w", pady=(4,0)
        )
        electoral.columnconfigure(1, weight=1)

        media = ttk.LabelFrame(left, text="Mídias / Insert", padding=8)
        media.pack(fill="x", pady=(0, 7))
        media.columnconfigure(1, weight=1)

        ttk.Label(media, text="Raiz:").grid(row=0, column=0, sticky="w")
        ttk.Entry(media, textvariable=self.media_root_var, width=27).grid(row=0, column=1, sticky="ew", padx=4)
        ttk.Button(media, text="...", width=3, command=self.choose_media_root).grid(row=0, column=2)

        ttk.Label(media, text="Media-path:").grid(row=1, column=0, sticky="w", pady=(4, 0))
        ttk.Entry(media, textvariable=self.caspar_media_root_var, width=27).grid(
            row=1, column=1, columnspan=2, sticky="ew", padx=4, pady=(4, 0)
        )

        ttk.Label(media, text="Padrão(s):").grid(row=2, column=0, sticky="w", pady=(4, 0))
        ttk.Entry(media, textvariable=self.default_media_var, width=27).grid(row=2, column=1, sticky="ew", padx=4, pady=(4, 0))
        ttk.Button(media, text="...", width=3, command=self.choose_default_media).grid(row=2, column=2, pady=(4, 0))

        ttk.Label(media, text="Seleção:").grid(row=3, column=0, sticky="w", pady=(4, 0))
        ttk.Entry(media, textvariable=self.selected_media_var, width=27).grid(row=3, column=1, sticky="ew", padx=4, pady=(4, 0))
        ttk.Button(media, text="...", width=3, command=self.choose_selected_media).grid(row=3, column=2, pady=(4, 0))

        ttk.Checkbutton(media, text="Pular claquete inicial", variable=self.skip_slate_var).grid(
            row=4, column=0, columnspan=2, sticky="w", pady=(5, 0)
        )
        ttk.Entry(media, textvariable=self.skip_slate_seconds_var, width=6).grid(row=4, column=2, sticky="e", pady=(5, 0))

        ttk.Checkbutton(media, text="INTEGRAL se mídia exceder o slot", variable=self.integral_selection_var).grid(
            row=5, column=0, columnspan=3, sticky="w", pady=(4,0)
        )
        ttk.Button(
            media, text="APLICAR À SELEÇÃO", command=self.apply_media_to_selection
        ).grid(row=6, column=0, columnspan=3, sticky="ew", pady=(6, 0))

        operation = ttk.LabelFrame(left, text="Operação", padding=8)
        operation.pack(fill="x")

        ttk.Button(operation, text="SELECIONAR TUDO", command=self.select_all).grid(row=0, column=0, sticky="ew", padx=(0, 3))
        ttk.Button(operation, text="LIMPAR SELEÇÃO", command=self.clear_selection).grid(row=0, column=1, sticky="ew")
        ttk.Button(operation, text="PLAY SELECIONADO", command=self.play_selected).grid(row=1, column=0, sticky="ew", padx=(0, 3), pady=(4, 0))
        ttk.Button(operation, text="STOP", command=self.stop).grid(row=1, column=1, sticky="ew", pady=(4, 0))

        ttk.Label(operation, textvariable=self.break_playlist_status_var, font=("Segoe UI", 9, "bold"), wraplength=320).grid(
            row=2, column=0, columnspan=2, sticky="ew", pady=(6, 2)
        )
        ttk.Button(operation, text="■ CORTAR E VOLTAR À REDE", command=self.break_cut_now).grid(
            row=3, column=0, columnspan=2, sticky="ew", pady=(2, 0)
        )
        ttk.Button(operation, text="✓ TERMINAR ATUAL E VOLTAR", command=self.break_finish_current).grid(
            row=4, column=0, columnspan=2, sticky="ew", pady=(3, 0)
        )

        ttk.Button(operation, text="SALVAR CONFIGURAÇÃO", command=self.save_state).grid(
            row=5, column=0, columnspan=2, sticky="ew", pady=(6, 0)
        )

        self.arm_button = ttk.Button(operation, text="ARMAR AUTOMÁTICO", command=self.toggle_armed)
        self.arm_button.grid(row=6, column=0, columnspan=2, sticky="ew", pady=(4, 0))
        operation.columnconfigure(0, weight=1)
        operation.columnconfigure(1, weight=1)

        # ===================== DIREITA =====================
        status = ttk.LabelFrame(right, text="Operação / Próximo Insert", padding=8)
        status.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        status.columnconfigure(1, weight=1)

        ttk.Label(status, textvariable=self.clock_var, font=("Segoe UI", 18, "bold")).grid(
            row=0, column=0, rowspan=2, sticky="w"
        )
        ttk.Label(status, textvariable=self.next_event_var, font=("Segoe UI", 11, "bold")).grid(
            row=0, column=1, sticky="w", padx=(18, 0)
        )
        ttk.Label(status, textvariable=self.countdown_var).grid(
            row=1, column=1, sticky="w", padx=(18, 0)
        )
        ttk.Label(status, textvariable=self.cultura_status_var).grid(row=2, column=0, columnspan=2, sticky="w")
        ttk.Label(status, textvariable=self.caspar_status_var).grid(row=3, column=0, columnspan=2, sticky="w")
        ttk.Label(status, textvariable=self.auto_status_var, font=("Segoe UI", 11, "bold")).grid(
            row=0, column=2, rowspan=2, sticky="e", padx=(12, 0)
        )

        # INSERT AVULSO fica no lado direito, imediatamente acima da lista.
        avf = ttk.LabelFrame(right, text="INSERT AVULSO — V1.35.2", padding=6)
        avf.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        avf.columnconfigure(0, weight=1)
        ttk.Label(
            avf,
            text="BLOCO/JANELA LOCAL + mídias FIXAS ou VINCULADAS ao término da anterior.",
        ).grid(row=0, column=0, sticky="w")
        av_buttons = ttk.Frame(avf)
        av_buttons.grid(row=0, column=1, sticky="e", padx=(12, 0))
        ttk.Button(av_buttons, text="+ NOVO AVULSO", command=self.add_avulso_dialog).pack(side="left")
        ttk.Button(av_buttons, text="+ BLOCO / JANELA LOCAL", command=self.add_manual_break_dialog).pack(side="left", padx=4)
        ttk.Button(av_buttons, text="EDITAR", command=self.edit_selected_insert).pack(side="left", padx=4)
        ttk.Button(av_buttons, text="EXCLUIR", command=self.delete_selected_insert).pack(side="left")

        table_frame = ttk.LabelFrame(right, text="LISTA DE INSERTS", padding=6)
        table_frame.grid(row=2, column=0, sticky="nsew")
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)

        columns = ("hora", "origem", "dur", "durmidia", "saida", "evento", "midia", "estado")
        self.tree = ttk.Treeview(
            table_frame, columns=columns, show="headings", selectmode="extended"
        )
        self.tree.heading("hora", text="Entrada")
        self.tree.heading("origem", text="Origem")
        self.tree.heading("dur", text="Grade/Slot")
        self.tree.heading("durmidia", text="Mídia")
        self.tree.heading("saida", text="Saída final")
        self.tree.heading("evento", text="Evento")
        self.tree.heading("midia", text="Mídia CasparCG")
        self.tree.heading("estado", text="Estado")

        self.tree.column("hora", width=82, anchor="center", stretch=False)
        self.tree.column("origem", width=75, anchor="center", stretch=False)
        self.tree.column("dur", width=75, anchor="center", stretch=False)
        self.tree.column("durmidia", width=75, anchor="center", stretch=False)
        self.tree.column("saida", width=90, anchor="center", stretch=False)
        self.tree.column("evento", width=260)
        self.tree.column("midia", width=390)
        self.tree.column("estado", width=125, anchor="center", stretch=False)

        vsb = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(table_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")

        self.tree.tag_configure("next", font=("Segoe UI", 9, "bold"))
        self.tree.tag_configure("executed", foreground="gray")
        self.tree.tag_configure("manual", font=("Segoe UI", 9, "bold"))

        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        win_w = min(1500, max(1100, screen_w - 40))
        win_h = min(900, max(650, screen_h - 90))
        self.geometry(f"{win_w}x{win_h}")
        self.minsize(1050, 620)



    def _hms_to_seconds_safe(self, value):
        try:
            h, m, s = map(int, str(value).split(":"))
            if 0 <= h <= 23 and 0 <= m <= 59 and 0 <= s <= 59:
                return h * 3600 + m * 60 + s
        except Exception:
            pass
        return None

    def _is_operational_start(self, value):
        sec = self._hms_to_seconds_safe(value)
        return sec is not None and OPERATIONAL_START_SECONDS <= sec < 24 * 3600

    def _filter_operational_cultura(self, rows):
        return [dict(r) for r in (rows or []) if self._is_operational_start(r.get("start"))]

    def _grade_signature(self, inserts):
        # Assinatura só do que realmente comanda inserção, ignorando eventos <05h.
        normalized = []
        for e in self._filter_operational_cultura(inserts):
            normalized.append((
                str(e.get("start","")),
                int(e.get("duration",0) or 0),
                str(e.get("title","")).strip()
            ))
        return tuple(normalized)

    def _promote_operational_grade(self, inserts, grade_events, program_events, signature, metadata=None):
        # V1.35.6 RESET OPERACIONAL:
        # elimina referências da grade anterior antes de instalar a nova.
        # Preserva histórico de PLAY, AVULSOS, PGM e configurações persistentes.
        self.events = [e for e in getattr(self, "events", [])
                       if e.get("origin") not in (None, "CULTURA")]
        self.operational_cultura_insert_events = []
        self.operational_cultura_grade_events = []
        self.operational_program_events = []
        self.operational_cultura_insert_events = self._filter_operational_cultura(inserts)
        # Grade de referência preservada integralmente (00:00–23:59).
        # O corte operacional >=05h continua valendo apenas para inserts automáticos.
        self.operational_cultura_grade_events = [dict(r) for r in (grade_events or [])]
        self.operational_program_events = self._filter_operational_cultura(program_events)
        self.operational_grade_signature = signature
        if metadata:
            modified = str(metadata.get("modified", "") or "").strip()
            if modified and modified != "--:--:--":
                self.operational_modified_marker = modified

        # Compatibilidade com restante do Scheduler.
        self.cultura_insert_events = [dict(e, origin="CULTURA") for e in self.operational_cultura_insert_events]
        self.cultura_grade_events = list(self.operational_cultura_grade_events)
        self.program_events = list(self.operational_program_events)
        self.events = list(self.cultura_insert_events)

        self.candidate_cultura_insert_events = []
        self.candidate_cultura_grade_events = []
        self.candidate_program_events = []
        self.candidate_grade_signature = None
        self.candidate_grade_count = 0
        self.candidate_grade_first_seen = 0.0
        self.grade_confirmation_pending = False

        self.rebuild_combined_events()
        self.refresh_tree()

        if metadata:
            self.cultura_sync_var.set(
                f"Sincronização: OPERACIONAL CONFIRMADA | modificação {metadata.get('modified','--:--:--')}"
            )
        else:
            self.cultura_sync_var.set("Sincronização: OPERACIONAL CONFIRMADA")

        if self.armed:
            self.auto_status_var.set("AUTOMÁTICO: ARMADO")

    def _accept_or_stage_grade(self, inserts, grade_events, program_events, metadata):
        """V1.36.0 — grade direta.

        A fonte escolhida pelo refresh é a autoridade desta leitura:
        HTML válido tem prioridade; XML/TXT existe apenas como fallback.
        Não há grade candidata, dupla confirmação nem retenção de horário antigo.
        """
        signature = self._grade_signature(inserts)
        if signature != self.operational_grade_signature:
            self._promote_operational_grade(
                inserts, grade_events, program_events, signature, metadata
            )
            return "PROMOTED"

        # Mesmo conteúdo: mantém a grade e apenas atualiza o marcador real.
        modified = str((metadata or {}).get("modified", "") or "").strip()
        if modified and modified != "--:--:--":
            self.operational_modified_marker = modified
        self.grade_refresh_ok = True
        self.grade_confirmation_pending = False
        return "UNCHANGED"

    def _schedule_quick_grade_confirmation(self):
        try:
            if self.grade_quick_confirm_after_id is not None:
                self.after_cancel(self.grade_quick_confirm_after_id)
        except Exception:
            pass
        self.grade_quick_confirm_after_id = self.after(2000, self._quick_grade_confirmation)

    def _quick_grade_confirmation(self):
        self.grade_quick_confirm_after_id = None
        if not self.grade_confirmation_pending or self.refresh_in_progress:
            return
        logging.info("CONFIRMAÇÃO RÁPIDA DA GRADE | segunda consulta automática")
        self.refresh_now()

    def _grade_auto_allowed(self):
        # PGM/eleitoral/manual continuam tendo sua própria lógica.
        # O disparo automático de inserts Cultura fica bloqueado enquanto a nova grade
        # não estiver confirmada.
        if self.grade_confirmation_pending:
            return False
        if self.operational_grade_signature is None:
            return False
        return True

    def _event_is_visible_now(self, event, now=None):
        if now is None:
            now = datetime.now()

        # Cultura antes de 05h nunca aparece na grade operacional.
        if event.get("origin") == "CULTURA" and not self._is_operational_start(event.get("published_start", event.get("start"))):
            return False

        start = event.get("start", "")
        sec = self._hms_to_seconds_safe(start)
        if sec is None:
            return True

        current = now.hour * 3600 + now.minute * 60 + now.second
        try:
            duration = float(event.get("duration", event.get("slot", 0)) or 0)
        except Exception:
            duration = 0.0

        end_sec = sec + max(0.0, duration)

        # Eventos futuros ou em andamento permanecem. Vencidos desaparecem.
        return current <= end_sec


    # ------------------------------------------------------------------------
    # ATEM
    # ------------------------------------------------------------------------

    def atem_normal_source(self):
        return int(self.atem_normal_var.get().strip())

    def atem_electoral_source(self):
        return int(self.atem_electoral_var.get().strip())

    def atem_caspar_source(self):
        return int(self.atem_caspar_var.get().strip())

    def atem_vmix_source(self):
        return int(self.atem_vmix_var.get().strip())

    def connect_atem(self):
        if not PYATEM_OK:
            messagebox.showerror(
                "ATEM",
                "PyATEMMax não está instalado.\n\n"
                "Execute:\npy -m pip install PyATEMMax"
            )
            return

        ip = self.atem_ip_var.get().strip()
        self.atem_status_var.set(f"ATEM: conectando {ip}...")

        threading.Thread(
            target=self._connect_atem_worker,
            args=(ip,),
            daemon=True
        ).start()

    def _connect_atem_worker(self, ip):
        try:
            if self.atem:
                try:
                    self.atem.disconnect()
                except Exception:
                    pass

            sw = PyATEMMax.ATEMMax()
            sw.connect(ip, connTimeout=5)

            if not sw.waitForConnection(timeout=5):
                raise TimeoutError(f"Sem resposta do ATEM em {ip}")

            self.atem = sw
            self.atem_connected = True
            self.logo_mp1_on = None
            logging.info("ATEM conectado | ip=%s", ip)

            try:
                source = sw.programInput[0].videoSource
                text = f"ATEM: conectado | PROGRAM {source}"
            except Exception:
                text = "ATEM: conectado"

            self.after(0, lambda: self.atem_status_var.set(text))

        except Exception as exc:
            self.atem_connected = False
            logging.exception("Falha ao conectar ATEM")
            self.after(0, lambda: self.atem_status_var.set("ATEM: ERRO"))
            self.after(
                0,
                lambda e=str(exc): messagebox.showerror("ATEM", e)
            )

    def ensure_atem(self):
        if self.atem and self.atem_connected and getattr(self.atem, "connected", False):
            return True

        ip = self.atem_ip_var.get().strip()

        if not PYATEM_OK:
            raise RuntimeError("PyATEMMax não está instalado.")

        sw = PyATEMMax.ATEMMax()
        sw.connect(ip, connTimeout=4)

        if not sw.waitForConnection(timeout=4):
            try:
                sw.disconnect()
            except Exception:
                pass
            raise TimeoutError(f"ATEM sem resposta em {ip}")

        self.atem = sw
        self.atem_connected = True
        return True

    def atem_set_program(self, source):
        try:
            self.ensure_atem()
            self.atem.setProgramInputVideoSource(0, int(source))
            self.atem_status_var.set(f"ATEM: PROGRAM {source}")
            logging.info("ATEM PROGRAM | fonte=%s", source)
            return True
        except Exception as exc:
            self.atem_connected = False
            self.atem_status_var.set("ATEM: ERRO")
            logging.exception("Falha ATEM PROGRAM | fonte=%s", source)
            messagebox.showerror("ATEM", f"Falha ao trocar PROGRAM:\n\n{exc}")
            return False

    def _cultura_program_for_now(self, now=None, logo_window=False):
        """Retorna a LINHA ATUAL da grade Cultura quando ela própria for PROGRAMA.

        V1.36.6:
        - usa a grade integral, não o catálogo de programas com durações que podem
          sobrepor chamadas, classificações e intervalos;
        - o fim efetivo da linha é limitado pelo início da próxima linha da grade;
        - logo entra 3 s após o início e sai 5 s antes do fim efetivo;
        - qualquer linha atual que não seja PROGRAMA ou tenha Veiculação preenchida
          força o logo para OFF.
        """
        if now is None:
            now = datetime.now()

        current = now.hour * 3600 + now.minute * 60 + now.second
        offset = int(self.grade_offset_seconds() or 0)

        rows = [dict(r) for r in (
            self.operational_cultura_grade_events
            or getattr(self, "cultura_grade_events", [])
            or []
        )]

        timeline = []
        for event in rows:
            raw_start = event.get("published_start", event.get("start", ""))
            start = self._hms_to_seconds_safe(raw_start)
            if start is None:
                continue
            start = (start + offset) % (24 * 3600)
            timeline.append((start, event))

        timeline.sort(key=lambda item: item[0])

        for idx, (start, event) in enumerate(timeline):
            try:
                duration = max(0, int(event.get("duration", 0) or 0))
            except Exception:
                duration = 0

            declared_end = start + duration if duration > 0 else start
            next_start = timeline[idx + 1][0] if idx + 1 < len(timeline) else None

            if next_start is not None and next_start > start:
                effective_end = min(declared_end, next_start) if duration > 0 else next_start
            else:
                effective_end = declared_end

            if effective_end <= start:
                continue
            if not (start <= current < effective_end):
                continue

            if norm(event.get("category", "")) != "PROGRAMA":
                return None
            if norm(event.get("divulgation", "")):
                return None

            active_start = start + (3 if logo_window else 0)
            active_end = effective_end - (5 if logo_window else 0)

            if active_end <= active_start:
                return None
            return event if active_start <= current < active_end else None

        return None

    @staticmethod
    def _atem_value(value):
        """Extrai o valor numérico de ATEMConstant ou de um int simples."""
        try:
            return int(value.value)
        except Exception:
            return int(value)

    def _set_logo_mp1(self, enabled):
        """Liga/desliga DSK1; MP1/logo deve estar previamente configurado no ATEM."""
        enabled = bool(enabled)
        if self.logo_mp1_on is enabled:
            return
        try:
            self.ensure_atem()
            # Em PyATEMMax, DSK1 fica em switcher.atem.dsks.dsk1.
            try:
                dsk1 = self.atem.atem.dsks.dsk1
            except Exception:
                dsk1 = 0

            self.atem.setDownstreamKeyerOnAir(dsk1, enabled)

            # Confere o estado devolvido pelo ATEM quando disponível.
            try:
                actual = bool(self.atem.downstreamKeyer[dsk1].onAir)
            except Exception:
                actual = enabled

            self.logo_mp1_on = actual
            self.logo_mp1_status_var.set(f"LOGO MP1 / DSK1: {'ON' if actual else 'OFF'}")
            logging.info("LOGO MP1 / DSK1 | solicitado=%s | estado=%s",
                         "ON" if enabled else "OFF",
                         "ON" if actual else "OFF")
        except Exception as exc:
            self.logo_mp1_on = None
            self.logo_mp1_status_var.set(f"LOGO MP1 / DSK1: ERRO ({exc})")
            logging.exception("Falha ao controlar LOGO MP1 / DSK1")

    def update_logo_mp1(self, now=None):
        """Automação do logo: somente Cultura + Veiculação vazia + PROGRAMA."""
        if now is None:
            now = datetime.now()

        # Não dependa apenas da flag atem_connected: em reconexões ela pode ficar
        # momentaneamente fora de sincronia com o objeto conectado.
        try:
            self.ensure_atem()
        except Exception as exc:
            self.logo_mp1_on = None
            self.logo_mp1_status_var.set(f"LOGO MP1: aguardando ATEM ({exc})")
            return

        try:
            source_obj = self.atem.programInput[0].videoSource
            current_source = self._atem_value(source_obj)
            cultura_source = int(self.atem_normal_source())
            on_cultura = current_source == cultura_source
        except Exception as exc:
            self.logo_mp1_status_var.set(f"LOGO MP1: erro lendo PROGRAM ({exc})")
            logging.exception("Falha ao ler PROGRAM para automação do LOGO MP1")
            return

        program = self._cultura_program_for_now(now, logo_window=True) if on_cultura else None
        should_on = bool(on_cultura and program is not None)

        if on_cultura and program is None:
            self.logo_mp1_status_var.set("LOGO MP1: CULTURA / fora da janela +3s / -5s")
        elif not on_cultura:
            self.logo_mp1_status_var.set(f"LOGO MP1: OFF / PROGRAM {current_source}")

        self._set_logo_mp1(should_on)

    def base_source_for_time(self, now=None):
        if now is None:
            now = datetime.now()

        # PRIORIDADE 1: janela eleitoral.
        if self.is_electoral_lock(now):
            return self.atem_electoral_source()

        # PRIORIDADE 2: programa ao vivo já assumido pelo sistema.
        if self.live_active and self.live_source is not None:
            return int(self.live_source)

        return self.atem_normal_source()

    def restore_base_source(self, now=None):
        source = self.base_source_for_time(now)
        return self.atem_set_program(source)

    # ------------------------------------------------------------------------
    # PROGRAMA AO VIVO — V1.34
    # ------------------------------------------------------------------------

    def on_live_toggle(self):
        # Compatibilidade com estados antigos. Na V1.34 o controle é automático:
        # basta haver programa selecionado na caixa/lista AO VIVO.
        self.live_enabled_var.set(True)
        self.live_dismissed.clear()
        self.live_status_var.set("AO VIVO: AUTOMÁTICO / verificando programa atual...")
        logging.info("Controle AO VIVO AUTOMÁTICO habilitado.")
        self.save_state()

    def live_cultura_patterns(self):
        # Mantém compatibilidade com configurações antigas, porém a edição agora
        # é feita exclusivamente pela lista derivada de eventos_programa.json.
        return [
            live_norm(x) for x in self.live_cultura_patterns_var.get().split(";")
            if live_norm(x)
        ]

    def live_program_titles(self):
        return [
            x.strip() for x in self.live_cultura_patterns_var.get().split(";")
            if x.strip()
        ]

    def refresh_live_program_widgets(self):
        """Atualiza catálogo/lista AO VIVO a partir da mesma base PROGRAMA dos avulsos."""
        combo = getattr(self, "live_program_combo", None)
        listbox = getattr(self, "live_program_listbox", None)

        if combo is not None:
            rows = list(self.program_events or [])
            labels = [f'{e.get("start","--:--:--")} | {e.get("title","")}' for e in rows]
            combo["values"] = labels
            self._live_program_combo_rows = rows
            if labels and not self.live_program_choice_var.get():
                combo.current(0)

        if listbox is not None:
            listbox.delete(0, "end")
            for title in self.live_program_titles():
                listbox.insert("end", title)

    def add_live_program_from_catalog(self):
        rows = getattr(self, "_live_program_combo_rows", [])
        combo = getattr(self, "live_program_combo", None)
        if combo is None:
            return

        idx = combo.current()
        if not (0 <= idx < len(rows)):
            messagebox.showwarning("AO VIVO", "Escolha um evento PROGRAMA da Cultura.")
            return

        title = rows[idx].get("title", "").strip()
        if not title:
            return

        # V1.34: selecionar/adicionar um programa já habilita automaticamente
        # o controle AO VIVO; não existe mais ação separada do operador.
        self.live_enabled_var.set(True)
        current = self.live_program_titles()
        normalized = {live_norm(x) for x in current}
        if live_norm(title) not in normalized:
            current.append(title)
            self.live_cultura_patterns_var.set(";".join(current))
            self.live_dismissed.clear()
            self.save_state()
            logging.info("Programa Cultura marcado AO VIVO | %s", title)

        self.refresh_live_program_widgets()

    def remove_live_program_selected(self):
        box = getattr(self, "live_program_listbox", None)
        if box is None or not box.curselection():
            messagebox.showwarning("AO VIVO", "Selecione um programa da lista para remover.")
            return

        idx = int(box.curselection()[0])
        current = self.live_program_titles()
        if 0 <= idx < len(current):
            removed = current.pop(idx)
            self.live_cultura_patterns_var.set(";".join(current))
            self.live_dismissed.clear()
            self.save_state()
            logging.info("Programa removido da lista AO VIVO | %s", removed)

        self.refresh_live_program_widgets()

    def _hms_seconds(self, value):
        if not self.validate_hms(value):
            return None
        h, m, s = map(int, value.split(":"))
        return h * 3600 + m * 60 + s

    def _window_contains(self, now, start, end):
        a = self._hms_seconds(start)
        b = self._hms_seconds(end)
        if a is None or b is None:
            return False
        cur = now.hour * 3600 + now.minute * 60 + now.second
        return a <= cur < b

    def _today_dt(self, now, hms):
        h, m, s = map(int, hms.split(":"))
        return now.replace(hour=h, minute=m, second=s, microsecond=0)

    def load_pgm_json(self):
        """Carrega o cadastro externo. O Scheduler apenas lê; a edição fica no app separado."""
        path = Path(self.pgm_json_path_var.get().strip() or (Path(__file__).resolve().parent / "programas.json"))
        try:
            if not path.exists():
                self.pgm_records = []
                self.pgm_json_status_var.set(f"PGM JSON: arquivo não encontrado | {path.name}")
                self.live_status_var.set("PGM: sem cadastro externo — automação normal continua")
                self.refresh_pgm_view()
                return False
            data = json.loads(path.read_text(encoding="utf-8"))
            rows = data.get("programas", [])
            if not isinstance(rows, list):
                raise ValueError("campo 'programas' não é uma lista")
            valid = []
            for row in rows:
                if not isinstance(row, dict) or not row.get("nome"):
                    continue
                if not self.validate_hms(str(row.get("inicio",""))) or not self.validate_hms(str(row.get("fim",""))):
                    continue
                try:
                    int(row.get("entrada", row.get("source", 1)))
                    int(row.get("saida", self.atem_normal_source()))
                except Exception:
                    continue
                valid.append(row)
            self.pgm_records = valid
            self.pgm_json_status_var.set(f"PGM JSON: {len(valid)} programa(s) carregado(s) | {path.name}")
            self.refresh_pgm_view()
            logging.info("PGM JSON carregado | arquivo=%s | programas=%s", path, len(valid))
            return True
        except Exception as exc:
            self.pgm_records = []
            self.pgm_json_status_var.set(f"PGM JSON: ERRO — {exc}")
            self.refresh_pgm_view()
            logging.exception("Falha ao carregar programas.json")
            return False

    def refresh_pgm_view(self):
        box = getattr(self, "pgm_view", None)
        if box is None:
            return
        box.delete(0, "end")
        for row in self.pgm_records:
            if not row.get("ativo", True):
                continue
            dias = ",".join(row.get("dias", []))
            entrada = row.get("entrada", row.get("source", 1))
            saida = row.get("saida", self.atem_normal_source())
            box.insert("end", f"{row.get('nome')} | {dias} | {row.get('inicio')}→{row.get('fim')} | {entrada}→{saida}")

    def open_pgm_cadastro(self):
        folder = Path(__file__).resolve().parent
        candidates = [
            folder / "CADASTRO_PGM_V1_1_ENTRADA_SAIDA.py",
            folder / "CADASTRO_PGM_V1.py",
        ]
        app = next((p for p in candidates if p.exists()), None)
        if app is None:
            messagebox.showinfo("Cadastro PGM", "Cadastro PGM não encontrado na pasta do Scheduler.")
            return
        try:
            import subprocess, sys
            subprocess.Popen([sys.executable, str(app)], cwd=str(folder))
        except Exception as exc:
            messagebox.showerror("Cadastro PGM", f"Não foi possível abrir o cadastro:\\n\\n{exc}")

    def _pgm_candidate(self, now):
        day_names = ["SEG","TER","QUA","QUI","SEX","SAB","DOM"]
        today_code = day_names[now.weekday()]
        cur = now.hour * 3600 + now.minute * 60 + now.second
        today = now.strftime("%Y-%m-%d")

        for row in self.pgm_records:
            if not row.get("ativo", True) or not row.get("ao_vivo", True):
                continue
            dias = [str(x).upper() for x in row.get("dias", [])]
            if today_code not in dias:
                continue
            start = str(row.get("inicio",""))
            end = str(row.get("fim",""))
            a = self._hms_seconds(start)
            b = self._hms_seconds(end)
            if a is None or b is None:
                continue
            inside = (a <= cur < b) if a < b else (cur >= a or cur < b)
            if not inside:
                continue

            key = (today, "PGM_JSON", str(row.get("id", row.get("nome",""))), start, end)
            if key in self.live_dismissed:
                continue
            planned_end = self._today_dt(now, end)
            if a >= b and cur >= a:
                planned_end += timedelta(days=1)
            return {
                "key": key,
                "title": row.get("nome","PGM"),
                "source": int(row.get("entrada", row.get("source", 1))),
                "return_source": int(row.get("saida", self.atem_normal_source())),
                "start": start,
                "end": end,
                "planned_end": planned_end,
                "kind": "PGM_JSON"
            }
        return None

    def _live_event_datetime(self, event, now=None):
        if now is None:
            now = datetime.now()
        try:
            h, m, s = map(int, event.get("start", "").split(":"))
            return now.replace(hour=h, minute=m, second=s, microsecond=0)
        except Exception:
            return None

    def _mark_live_suspended_events(self, now=None):
        """Marca como suspensos os horários automáticos que venceram dentro
        da janela Cultura AO VIVO. Eles não são executados nem marcados como
        executados; aguardam a atualização/relocação da grade após o programa."""
        if now is None:
            now = datetime.now()
        if not self.live_active or not self.live_planned_end:
            return
        if not self.live_key:
            return
        candidate_start = None
        if len(self.live_key) >= 5 and self.live_key[1] == "PGM_JSON":
            candidate_start = self.live_key[3]
        elif len(self.live_key) >= 3:
            candidate_start = self.live_key[2]
        if not candidate_start or not self.validate_hms(candidate_start):
            return
        live_start = self._today_dt(now, candidate_start)

        for event in self.events:
            if event.get("reference_only"):
                continue
            if event.get("origin") == "MANUAL":
                continue
            event_dt = self._live_event_datetime(event, now)
            if event_dt is None:
                continue
            if live_start <= event_dt < self.live_planned_end and event_dt <= now:
                key = self.event_key(event)
                if key not in self.executed:
                    self.live_suspended_keys.add(key)

    def _finish_live_by_schedule(self, now=None):
        """Encerra automaticamente o estado AO VIVO Cultura no fim previsto,
        restaura a fonte-base e força uma nova leitura da grade. Os horários
        suspensos só voltam a ser avaliados depois dessa sincronização."""
        if now is None:
            now = datetime.now()

        old_title = self.live_title or "PGM"
        suspended = len(self.live_suspended_keys)
        logging.warning(
            "PGM ENCERRADO PELO HORÁRIO PREVISTO | programa=%s | suspensos=%s",
            old_title, suspended
        )
        return_source = self.live_return_source
        self._clear_live_state(add_dismiss=True)
        self.live_resync_pending = True
        self.live_status_var.set(
            f"AO VIVO ENCERRADO PELO HORÁRIO — atualizando/relocando grade | suspensos {suspended}"
        )

        if self.atem_connected and not self.local_insertion_active:
            if return_source is not None and not self.is_electoral_lock(now):
                self.atem_set_program(int(return_source))
            else:
                self.restore_base_source(now)

        # Força consulta imediata; enquanto ela não termina, _check_schedule
        # bloqueia os disparos para não executar horários vencidos.
        self.next_refresh_at = 0.0
        self.refresh_now()

    def _begin_live(self, candidate):
        self.live_active = True
        self.live_source = int(candidate["source"])
        self.live_return_source = int(candidate.get("return_source", self.atem_normal_source()))
        self.live_title = candidate["title"]
        self.live_key = candidate["key"]
        self.live_planned_end = candidate["planned_end"]
        self.live_overrun_logged = False
        logging.warning(
            "AO VIVO INICIADO | tipo=%s | programa=%s | fonte=%s | fim_previsto=%s",
            candidate.get("kind"), self.live_title, self.live_source, candidate.get("end")
        )
        self.live_status_var.set(
            f"🔴 AO VIVO — {self.live_title} | PROGRAM {self.live_source} | previsto até {candidate.get('end')}"
        )
        if self.atem_connected and not self.local_insertion_active and not self.is_electoral_lock():
            self.atem_set_program(self.live_source)

    def _clear_live_state(self, add_dismiss=True):
        if add_dismiss and self.live_key is not None:
            self.live_dismissed.add(self.live_key)
        self.live_active = False
        self.live_source = None
        self.live_title = None
        self.live_key = None
        self.live_planned_end = None
        self.live_overrun_logged = False

    def end_live_now(self):
        if not self.live_active:
            self.live_status_var.set("AO VIVO: nenhum programa ativo")
            return
        old_title = self.live_title or "PGM"
        return_source = self.live_return_source
        logging.warning("PGM ENCERRADO MANUALMENTE | programa=%s", old_title)
        self._clear_live_state(add_dismiss=True)
        self.live_status_var.set(f"PGM ENCERRADO — {old_title}")
        if self.atem_connected and not self.local_insertion_active:
            if return_source is not None and not self.is_electoral_lock():
                self.atem_set_program(int(return_source))
            else:
                self.restore_base_source()

    def update_live_control(self, now=None):
        if now is None:
            now = datetime.now()

        if self.live_active:
            if self.live_planned_end and now >= self.live_planned_end:
                self._mark_live_suspended_events(now)
                self._finish_live_by_schedule(now)
                return

            self._mark_live_suspended_events(now)
            if self.is_electoral_lock(now) or self.local_insertion_active:
                return

            if self.atem_connected:
                try:
                    current = self.atem.programInput[0].videoSource
                    if int(current) != int(self.live_source):
                        self.atem.setProgramInputVideoSource(0, int(self.live_source))
                        self.atem_status_var.set(f"ATEM: PROGRAM {self.live_source} / PGM")
                        logging.warning("PGM restaurou PROGRAM | fonte=%s", self.live_source)
                except Exception:
                    logging.exception("Falha ao reforçar fonte do PGM")
            return

        candidate = self._pgm_candidate(now)
        if candidate is not None:
            self._begin_live(candidate)
        else:
            ativos = sum(1 for r in self.pgm_records if r.get("ativo", True) and r.get("ao_vivo", True))
            self.live_status_var.set(f"PGM: AUTOMÁTICO / aguardando janela | ativos {ativos}")

    # ------------------------------------------------------------------------
    # ------------------------------------------------------------------------
    # CADASTRO ELEITORAL / TRE — V1.34
    # ------------------------------------------------------------------------

    def choose_electoral_registration(self):
        path = filedialog.askopenfilename(
            title="Carregar cadastro_eleitoral.json",
            initialdir=self.media_root_var.get() or MEDIA_ROOT,
            filetypes=[("Cadastro eleitoral","*.json"),("Todos os arquivos","*.*")]
        )
        if path:
            self.electoral_cadastro_path_var.set(path)
            self.load_electoral_registration(manual=True)

    def _find_tre_daily_pdf(self):
        reg = self.electoral_registration or {}
        candidates = []
        for p in reg.get("tre_files", []) or []:
            if p and os.path.isfile(p) and p.lower().endswith(".pdf"):
                candidates.append(p)
        folder = reg.get("tre_folder", "")
        if folder and os.path.isdir(folder):
            for n in os.listdir(folder):
                p = os.path.join(folder, n)
                if os.path.isfile(p) and n.lower().endswith(".pdf") and p not in candidates:
                    candidates.append(p)
        for p in candidates:
            n = electoral_norm(os.path.basename(p))
            if "PROGRAMACAO POR DIA" in n and "INSER" in n:
                return p
        if PYPDF_OK:
            for p in candidates:
                try:
                    first = PdfReader(p).pages[0].extract_text() or ""
                    n = electoral_norm(first)
                    if "PROGRAMACAO POR DIA" in n and "SISTEMA HORARIO ELEITORAL" in n:
                        return p
                except Exception:
                    pass
        return ""

    def _parse_tre_daily_plan(self, pdf_path, target_date):
        if not PYPDF_OK:
            raise RuntimeError("Instale pypdf: pip install pypdf")
        target = target_date.strftime("%d/%m/%Y")
        reader = PdfReader(pdf_path)
        lines = []
        for page in reader.pages:
            lines.extend((page.extract_text() or "").splitlines())

        cargos = [("Deputado Estadual","DE"),("Deputado Federal","DF"),("Senador","SEN"),("Governador","GOV")]
        rows = []
        current_date = None
        current_block = None

        for raw in lines:
            line = re.sub(r"\s+"," ",raw).strip()
            if not line:
                continue
            dm = re.match(r"^(\d{2}/\d{2}/\d{4})\s+(.*)$", line)
            if dm:
                current_date = dm.group(1)
                line = dm.group(2).strip()
            if current_date != target:
                continue

            cargo_name = cargo_code = None
            ln = electoral_norm(line)
            for suffix, code in cargos:
                if ln.endswith(electoral_norm(suffix)):
                    cargo_name, cargo_code = suffix, code
                    break
            if not cargo_code:
                continue

            body = re.sub(re.escape(cargo_name)+r"\s*$","",line,flags=re.I).strip()
            m = re.match(r"^(\d+)(?:\s+(\d+))?\s+(.*)$", body)
            if not m:
                continue
            n1 = int(m.group(1))
            n2 = int(m.group(2)) if m.group(2) else None
            if n2 is not None:
                current_block = n1
                seq = n2
            else:
                seq = n1
            rows.append({
                "date":target, "block":current_block, "seq":seq,
                "agremiacao":m.group(3).strip(), "cargo":cargo_code,
                "cargo_name":cargo_name
            })
        return rows

    def _registration_match(self, tre_name, cargo):
        ags = (self.electoral_registration or {}).get("agremiacoes",{}) or {}
        tn = electoral_norm(tre_name)
        tt = electoral_tokens(tre_name)
        aliases = set()
        for content in re.findall(r"\(([^)]*)\)", str(tre_name or "")):
            for token in re.split(r"[/,\s-]+", content):
                token = electoral_norm(token)
                if token and not token.isdigit():
                    aliases.add(token)
        best = None
        for name, ag in ags.items():
            cfg = (ag.get("cargos",{}) or {}).get(cargo)
            if not cfg: continue
            nn = electoral_norm(name)
            if nn == tn or nn in aliases:
                return name, cfg
            toks = electoral_tokens(name)
            score = len(toks & tt) / max(1,len(toks | tt))
            if nn and (nn in tn or tn in nn): score += 0.55
            if best is None or score > best[0]:
                best=(score,name,cfg)
        if best and best[0] >= 0.34:
            return best[1],best[2]
        return None,None

    def _determination_sequences(self, pdf_path):
        if not (PYPDF_OK and pdf_path and os.path.isfile(pdf_path)):
            return {}
        result={}
        for page in PdfReader(pdf_path).pages:
            items=[]
            def visitor(txt,cm,tm,font,size):
                t=(txt or "").strip()
                if t: items.append((t,float(tm[4]),float(tm[5])))
            try:
                page.extract_text(visitor_text=visitor)
            except Exception:
                continue
            dates=[]; rows=[]
            for t,x,y in items:
                dm=re.search(r"\b(\d{2}/\d{2}/\d{4})\b",t)
                if dm: dates.append((dm.group(1),y))
                m=re.search(r"\b(05h\s*-\s*11h|11h\s*-\s*18h|18h\s*-\s*24h)\b.*?\b([A-Z0-9][A-Z0-9_. -]{1,60})\s+\d+[\"”']?",t,re.I)
                if m:
                    b=electoral_norm(m.group(1)).replace("H","").replace(" ","")
                    band="05-11" if b.startswith("05-11") else ("11-18" if b.startswith("11-18") else "18-24")
                    rows.append((y,band,m.group(2).strip()))
            if not dates: continue
            for y,band,title in rows:
                d,_=min(dates,key=lambda z:abs(y-z[1]))
                result.setdefault(d,{}).setdefault(band,[]).append((y,title))
        final={}
        for d,bands in result.items():
            final[d]={}
            for band,rows in bands.items():
                final[d][band]=[t for _,t in sorted(rows,key=lambda z:z[0])]
        return final

    def _match_media_filename(self, folder, expected):
        if not folder or not os.path.isdir(folder): return ""
        videos=[os.path.join(folder,n) for n in os.listdir(folder)
                if os.path.isfile(os.path.join(folder,n))
                and os.path.splitext(n)[1].lower() in (".mp4",".mov",".mxf",".avi",".mkv")]
        target=electoral_norm(expected)
        for p in videos:
            stem=electoral_norm(os.path.splitext(os.path.basename(p))[0])
            if stem==target: return p
        for p in videos:
            stem=electoral_norm(os.path.splitext(os.path.basename(p))[0])
            if target and (target in stem or stem in target): return p
        return ""

    def _electoral_media_pool(self, cfg):
        # Catálogo dinâmico: cadastro + conteúdo atual da pasta, sem duplicatas.
        pool=[]; seen=set()
        def add(p):
            p=str(p or "").strip()
            if not p or not os.path.isfile(p): return
            if os.path.splitext(p)[1].lower() not in (".mp4",".mov",".mxf",".avi",".mkv"): return
            ap=os.path.normcase(os.path.abspath(p))
            if ap not in seen:
                seen.add(ap); pool.append(p)
        for p in (cfg.get("media",[]) or []): add(p)
        folder=str(cfg.get("folder","") or "").strip()
        if folder and os.path.isdir(folder):
            for n in os.listdir(folder): add(os.path.join(folder,n))
        return sorted(pool,key=lambda p:electoral_norm(os.path.basename(p)))

    def _next_seq_media(self, agrem, cargo, cfg, band, planned_offset=0):
        media=self._electoral_media_pool(cfg)
        if not media: return "",None
        key=f"{datetime.now():%Y-%m-%d}|{cargo}|{electoral_norm(agrem)}|{band}|SEQ"
        last=self.electoral_rotation_history.get(key,"")
        try:
            base=[os.path.normcase(os.path.abspath(p)) for p in media].index(os.path.normcase(os.path.abspath(last)))+1
        except Exception: base=0
        return media[(base+int(planned_offset or 0))%len(media)],key

    def _resolve_electoral_media(self, plan,event,planned_seq_offset=0):
        cargo=plan.get("cargo","")
        tre=plan.get("agremiacao","")
        agrem,cfg=self._registration_match(tre,cargo)
        band=daypart_key(event.get("start","00:00:00"))
        if not cfg:
            return self._next_default_electoral_media(False),"PADRÃO",tre,None,""
        det=cfg.get("determination","")
        if det and os.path.isfile(det):
            try:
                seqs=self._determination_sequences(det)
                titles=seqs.get(datetime.now().strftime("%d/%m/%Y"),{}).get(band,[])
                if titles:
                    key=f"{datetime.now():%Y-%m-%d}|{cargo}|{electoral_norm(agrem)}|{band}|DET"
                    last=self.electoral_rotation_history.get(key,"")
                    ix=(titles.index(last)+1)%len(titles) if last in titles else 0
                    expected=titles[ix]
                    media=self._match_media_filename(cfg.get("folder",""),expected)
                    if media: return media,"DETERMINAÇÃO",agrem,key,expected
                    return self._next_default_electoral_media(False),"PADRÃO / MÍDIA PI AUSENTE",agrem,key,expected
            except Exception:
                logging.exception("Falha determinação | %s",det)
        media,key=self._next_seq_media(agrem,cargo,cfg,band,planned_seq_offset)
        if media: return media,"SEQUENCIAL",agrem,key,os.path.basename(media)
        return self._next_default_electoral_media(False),"PADRÃO",agrem,None,""

    def _apply_electoral_plan_to_cultura_events(self, base):
        if not self.electoral_daily_plan:
            return base

        # V1.35.7:
        # cultura_insert_events é criado EXCLUSIVAMENTE pelo parser
        # ESTADO + HORARIO POLITICO. Portanto não procuramos a expressão
        # "HORARIO POLITICO" no título da matéria (ela não existe ali).
        cultura = [
            e for e in base
            if e.get("origin", "CULTURA") == "CULTURA"
            and (
                e.get("is_cultura_political_insert") is True
                or (
                    electoral_norm(e.get("divulgation", "")) == "ESTADO"
                    and electoral_norm(e.get("category", "")) == "HORARIO POLITICO"
                )
            )
        ]

        # Compatibilidade imediata com grades já carregadas antes desta versão:
        # se os eventos CULTURA vieram do antigo parser sem os marcadores,
        # eles ainda são válidos porque self.cultura_insert_events contém
        # somente os inserts ESTADO + HORARIO POLITICO.
        if not cultura:
            ids_validos = {id(e) for e in getattr(self, "cultura_insert_events", [])}
            cultura = [
                e for e in base
                if e.get("origin", "CULTURA") == "CULTURA"
                and (id(e) in ids_validos or not e.get("origin"))
            ]

        cultura.sort(key=lambda e: e.get("start", ""))

        planned_seq_counts = {}
        for i, event in enumerate(cultura):
            if i >= len(self.electoral_daily_plan):
                break

            plan = self.electoral_daily_plan[i]
            cargo = plan.get("cargo", "")
            tre = plan.get("agremiacao", "")
            agrem0, cfg0 = self._registration_match(tre, cargo)
            band0 = daypart_key(event.get("start", "00:00:00"))
            seq_group = (cargo, electoral_norm(agrem0 or tre), band0)
            offset = planned_seq_counts.get(seq_group, 0)

            media, mode, agrem, key, expected = self._resolve_electoral_media(
                plan, event, offset
            )

            if mode == "SEQUENCIAL":
                planned_seq_counts[seq_group] = offset + 1

            event.update({
                "electoral_plan": plan,
                "electoral_local": True,
                "electoral_media": media,
                "electoral_mode": mode,
                "electoral_agremiacao": agrem,
                "electoral_cargo": cargo,
                "electoral_history_key": key,
                "electoral_expected": expected,
                "integral": True,
            })

        return base

    def load_electoral_registration(self, manual=False):
        path=self.electoral_cadastro_path_var.get().strip()
        if not path:
            if manual: messagebox.showwarning("Cadastro eleitoral","Selecione o cadastro_eleitoral.json.")
            return False
        try:
            with open(path,"r",encoding="utf-8") as f:
                self.electoral_registration=json.load(f)
            pdf=self._find_tre_daily_pdf()
            if not pdf:
                raise FileNotFoundError("PDF TRE 'Programação por dia' não encontrado.")
            self.electoral_daily_plan=self._parse_tre_daily_plan(pdf,datetime.now().date())
            self.electoral_daily_plan_date=datetime.now().strftime("%Y-%m-%d")
            self.electoral_cadastro_status_var.set(
                f"Cadastro OK | TRE hoje: {len(self.electoral_daily_plan)} inserções"
            )
            logging.warning("CADASTRO ELEITORAL OK | %s | itens=%s",path,len(self.electoral_daily_plan))
            self.rebuild_combined_events(); self.refresh_tree(); self.save_state()
            return True
        except Exception as exc:
            self.electoral_registration={}; self.electoral_daily_plan=[]
            self.electoral_cadastro_status_var.set(f"Cadastro eleitoral: ERRO — {exc}")
            logging.exception("Cadastro eleitoral")
            if manual: messagebox.showerror("Cadastro eleitoral",str(exc))
            return False

    def _register_electoral_valid_play(self,event,media,started,finished):
        if not event.get("electoral_local"): return
        rec={"date":started.strftime("%Y-%m-%d"),"start_real":started.strftime("%H:%M:%S"),
             "end_real":finished.strftime("%H:%M:%S"),
             "duration_real":round((finished-started).total_seconds(),3),
             "cultura_start":event.get("start",""),"cargo":event.get("electoral_cargo",""),
             "agremiacao":event.get("electoral_agremiacao",""),"mode":event.get("electoral_mode",""),
             "expected":event.get("electoral_expected",""),"media":media}
        self.electoral_valid_plays.append(rec)
        key=event.get("electoral_history_key")
        if key:
            if event.get("electoral_mode")=="DETERMINAÇÃO":
                self.electoral_rotation_history[key]=event.get("electoral_expected","")
            elif event.get("electoral_mode")=="SEQUENCIAL":
                self.electoral_rotation_history[key]=media
        self.save_state()
        logging.info("PLAY ELEITORAL VÁLIDO | %s",rec)

    # MODO ELEITORAL
    # ------------------------------------------------------------------------

    def on_electoral_toggle(self):
        if self.electoral_enabled_var.get():
            self.electoral_status_var.set("ELEITORAL: HABILITADO")
            logging.info("Modo eleitoral HABILITADO | grade operacional: slots ESTADO/HORARIO POLITICO.")
        else:
            self.electoral_status_var.set("ELEITORAL: DESABILITADO / GRADE INTEGRAL")
            logging.info("Modo eleitoral DESABILITADO | grade de referência integral liberada.")
        self.save_state()
        # A composição da lista muda com o modo eleitoral:
        # habilitado = inserts eleitorais; desabilitado = grade Cultura integral.
        self.rebuild_combined_events()
        self.refresh_tree()

        if self.atem_connected and not self.local_insertion_active:
            self.restore_base_source()

    def choose_electoral_media(self, kind):
        path = filedialog.askopenfilename(
            title="Escolha a mídia eleitoral",
            initialdir=self.media_root_var.get() or MEDIA_ROOT,
            filetypes=[
                ("Vídeos", "*.mp4 *.mov *.mxf *.avi *.mkv"),
                ("Todos os arquivos", "*.*")
            ]
        )
        if path:
            if kind == "open":
                self.electoral_open_media_var.set(path)
            else:
                self.electoral_close_media_var.set(path)

    def electoral_windows(self):
        return [
            (self.electoral_start1_var.get().strip(), self.electoral_end1_var.get().strip()),
            (self.electoral_start2_var.get().strip(), self.electoral_end2_var.get().strip()),
        ]

    def validate_hms(self, value):
        try:
            datetime.strptime(value, "%H:%M:%S")
            return True
        except ValueError:
            return False

    def is_electoral_lock(self, now=None):
        if not self.electoral_enabled_var.get():
            return False

        if now is None:
            now = datetime.now()

        # PGM/janela eleitoral somente de segunda a sábado. O mapeamento TRE continua no domingo.
        if now.weekday() == 6:
            return False

        current = now.strftime("%H:%M:%S")

        for start, end in self.electoral_windows():
            if not self.validate_hms(start) or not self.validate_hms(end):
                continue
            if start <= current < end:
                return True

        return False

    def update_electoral_status(self, now=None):
        if not self.electoral_enabled_var.get():
            self.electoral_status_var.set("ELEITORAL: DESABILITADO")
            return

        if self.is_electoral_lock(now):
            self.electoral_status_var.set("🔒 JANELA ELEITORAL — INSERÇÕES BLOQUEADAS")
        else:
            self.electoral_status_var.set("ELEITORAL: HABILITADO / FORA DA JANELA")

    def enforce_electoral_source(self, now):
        if not self.electoral_enabled_var.get():
            return

        if not self.is_electoral_lock(now):
            return

        if self.local_insertion_active:
            return

        if not self.atem_connected:
            return

        try:
            current = self.atem.programInput[0].videoSource
            wanted = self.atem_electoral_source()

            if current != wanted:
                self.atem.setProgramInputVideoSource(0, wanted)
                self.atem_status_var.set(f"ATEM: PROGRAM {wanted} / ELEITORAL")
                logging.warning(
                    "Proteção eleitoral restaurou PROGRAM | atual=%s | desejado=%s",
                    current, wanted
                )
        except Exception:
            logging.exception("Falha ao reforçar fonte eleitoral")

    def handle_electoral_transition(self, now):
        """Detecta entrada/saída da janela. Na saída, retorna explicitamente à cabeça de rede HDMI 1."""
        locked=self.is_electoral_lock(now)
        if self._electoral_was_locked and not locked:
            logging.warning("FIM DA JANELA ELEITORAL | retorno explícito à CULTURA / HDMI 1")
            if not self.local_insertion_active:
                self.atem_set_program(self.atem_normal_source())
        self._electoral_was_locked=locked

    def handle_electoral_boundaries(self, now):
        """Dispara apenas mídias opcionais de abertura/encerramento.

        A troca física HDMI1/HDMI2/SDI8 será ligada ao módulo de controle
        do ATEM após validarmos os comandos do switcher.
        """
        if not self.electoral_enabled_var.get():
            return

        if not self.electoral_openclose_var.get():
            return

        # PGM/janela eleitoral: segunda a sábado. Domingo mantém apenas o mapeamento TRE.
        if now.weekday() == 6:
            return

        today = now.strftime("%Y-%m-%d")
        current = now.strftime("%H:%M:%S")

        for idx, (start, end) in enumerate(self.electoral_windows(), start=1):
            if current == start:
                key = (today, idx, "OPEN")
                if key not in self.electoral_boundary_executed:
                    media = self.electoral_open_media_var.get().strip()
                    if media:
                        self.electoral_boundary_executed.add(key)
                        logging.info("Abertura eleitoral | janela=%s | midia=%s", idx, media)
                        threading.Thread(
                            target=self._electoral_media_worker,
                            args=("ABERTURA", media),
                            daemon=True
                        ).start()

            if current == end:
                key = (today, idx, "CLOSE")
                if key not in self.electoral_boundary_executed:
                    media = self.electoral_close_media_var.get().strip()
                    if media:
                        self.electoral_boundary_executed.add(key)
                        logging.info("Encerramento eleitoral | janela=%s | midia=%s", idx, media)
                        threading.Thread(
                            target=self._electoral_media_worker,
                            args=("ENCERRAMENTO", media),
                            daemon=True
                        ).start()

    def _electoral_media_worker(self, label, media):
        try:
            response = self.send_play(media)
            logging.info("%s eleitoral executada | resposta=%s", label, response)
            self.after(
                0,
                lambda: self.caspar_status_var.set(f"CasparCG: {label} ELEITORAL")
            )
        except Exception:
            logging.exception("Falha na mídia eleitoral | tipo=%s | midia=%s", label, media)

    # ------------------------------------------------------------------------
    # PERSISTÊNCIA
    # ------------------------------------------------------------------------

    def collect_state(self):
        def as_int(var, default):
            try:
                return int(var.get().strip())
            except Exception:
                return default

        return {
            "url": self.url_var.get().strip(),
            "caspar_host": self.host_var.get().strip(),
            "caspar_port": as_int(self.port_var, CASPAR_PORT),
            "caspar_channel": as_int(self.channel_var, CASPAR_CHANNEL),
            "caspar_layer": as_int(self.layer_var, CASPAR_LAYER),
            "poll_seconds": as_int(self.poll_var, POLL_SECONDS),
            "grade_offset_seconds": self.grade_offset_seconds(),

            "media_root": self.media_root_var.get().strip(),
            "caspar_media_root": self.caspar_media_root_var.get().strip(),
            "default_media": self._next_default_electoral_media(False) or self.default_media_var.get().strip(),
            "electoral_default_media_list": list(self.electoral_default_media_list),
            "electoral_default_rotation_index": int(self.electoral_default_rotation_index),
            "selected_media": self.selected_media_var.get().strip(),
            "skip_slate_selection": bool(self.skip_slate_var.get()),
            "skip_slate_seconds": self.skip_slate_seconds_var.get().strip(),
            "integral_selection": bool(self.integral_selection_var.get()),

            # Exceções escolhidas para cada horário.
            "media_overrides": dict(self.media_overrides),
            "slate_skip_overrides": dict(self.slate_skip_overrides),
            "integral_overrides": dict(self.integral_overrides),
            "avulsos": list(self.avulsos),
            "manual_breaks": list(self.manual_breaks),
            "manual_break_step_seconds": int(self.manual_break_step_seconds),

            "atem_ip": self.atem_ip_var.get().strip(),
            "atem_normal_source": as_int(self.atem_normal_var, ATEM_NORMAL_SOURCE),
            "atem_electoral_source": as_int(self.atem_electoral_var, ATEM_ELECTORAL_SOURCE),
            "atem_caspar_source": as_int(self.atem_caspar_var, ATEM_CASPAR_SOURCE),
            "atem_vmix_source": as_int(self.atem_vmix_var, ATEM_VMIX_SOURCE),

            "pgm_json_path": self.pgm_json_path_var.get().strip(),
            "live_enabled": bool(self.live_enabled_var.get()),
            "live_cultura_patterns": self.live_cultura_patterns_var.get().strip(),
            "live_wd_morning_start": self.live_wd_morning_start_var.get().strip(),
            "live_wd_morning_end": self.live_wd_morning_end_var.get().strip(),
            "live_wd_evening_start": self.live_wd_evening_start_var.get().strip(),
            "live_wd_evening_end": self.live_wd_evening_end_var.get().strip(),
            "live_sat_start": self.live_sat_start_var.get().strip(),
            "live_sat_end": self.live_sat_end_var.get().strip(),
            "live_sat_electoral_start": self.live_sat_electoral_start_var.get().strip(),
            "live_sat_electoral_end": self.live_sat_electoral_end_var.get().strip(),

            "electoral_enabled": bool(self.electoral_enabled_var.get()),
            "electoral_openclose": bool(self.electoral_openclose_var.get()),
            "electoral_start1": self.electoral_start1_var.get().strip(),
            "electoral_end1": self.electoral_end1_var.get().strip(),
            "electoral_start2": self.electoral_start2_var.get().strip(),
            "electoral_end2": self.electoral_end2_var.get().strip(),
            "electoral_open_media": self.electoral_open_media_var.get().strip(),
            "electoral_close_media": self.electoral_close_media_var.get().strip(),
            "electoral_cadastro_path": self.electoral_cadastro_path_var.get().strip(),
            "electoral_rotation_history": dict(self.electoral_rotation_history),
            "electoral_valid_plays": list(self.electoral_valid_plays[-5000:]),
        }

    def save_state(self):
        ok = save_state_file(self.collect_state())
        if ok:
            logging.info("Estado salvo em %s", STATE_FILE)
        return ok

    def on_close(self):
        self.save_state()

        try:
            if self.atem:
                self.atem.disconnect()
        except Exception:
            pass

        self.destroy()

    # ------------------------------------------------------------------------
    # AVULSOS / DURAÇÃO REAL
    # ------------------------------------------------------------------------

    def _sec_to_hms(self, sec):
        sec = max(0, int(round(sec))) % 86400
        return f"{sec//3600:02d}:{(sec%3600)//60:02d}:{sec%60:02d}"

    def _add_hms(self, hms, seconds):
        return self._sec_to_hms(self._hms_seconds(hms) + int(round(seconds)))

    # --------------------------------------------------------------------
    # V1.34 — OFFSET GLOBAL DA GRADE CULTURA
    # --------------------------------------------------------------------
    def grade_offset_seconds(self):
        try:
            return int(str(self.grade_offset_var.get()).strip())
        except Exception:
            return 0

    def grade_time(self, hms):
        """Converte um horário publicado pela Cultura em horário operacional."""
        if not self.validate_hms(hms):
            return hms
        return self._add_hms(hms, self.grade_offset_seconds())

    def event_source_start(self, event):
        """Chave original da Cultura para manter mídia/claquete mesmo mudando offset."""
        return event.get("published_start", event.get("start", ""))

    def apply_grade_offset_from_ui(self):
        try:
            value = int(str(self.grade_offset_var.get()).strip())
        except Exception:
            messagebox.showerror(
                "OFFSET GRADE",
                "Digite um número inteiro de segundos.\n\nExemplos: -20, 0, +35"
            )
            self.grade_offset_var.set("0")
            value = 0

        # Limite amplo de segurança: uma hora para cada lado.
        value = max(-3600, min(3600, value))
        self.grade_offset_var.set(str(value))
        self.rebuild_combined_events()
        self.refresh_tree()
        self.save_state()
        logging.warning("OFFSET GLOBAL DA GRADE alterado | segundos=%+d", value)

    def adjust_grade_offset(self, delta):
        value = self.grade_offset_seconds() + int(delta)
        value = max(-3600, min(3600, value))
        self.grade_offset_var.set(str(value))
        self.apply_grade_offset_from_ui()

    def reset_grade_offset(self):
        self.grade_offset_var.set("0")
        self.apply_grade_offset_from_ui()

    def media_duration(self, media):
        """Duração física do arquivo. Usa ffprobe quando disponível; fallback None."""
        if not media or not os.path.isfile(media): return None
        try:
            stamp=(media, os.path.getmtime(media), os.path.getsize(media))
            if stamp in self._media_duration_cache: return self._media_duration_cache[stamp]
            cp = subprocess.run(["ffprobe","-v","error","-show_entries","format=duration","-of","default=noprint_wrappers=1:nokey=1",media], capture_output=True, text=True, timeout=8, creationflags=(0x08000000 if os.name=="nt" else 0))
            v=float(cp.stdout.strip()); v=v if v>0 else None
            self._media_duration_cache[stamp]=v
            return v
        except Exception:
            return None

    def _avulso_air_duration(self, a):
        """Duração lógica/operacional do AVULSO.

        A duração física é lida automaticamente por ffprobe. PULAR CLAQUETE reduz
        o tempo efetivamente exibido; AJUSTE (+/-) corrige o ponto lógico de saída.
        O resultado nunca é negativo.
        """
        media = str(a.get("media", "") or "").strip()
        media_len = self.media_duration(media)
        if media_len is None:
            # Compatibilidade: se ffprobe/arquivo não estiver disponível, usa o
            # valor salvo pelo operador/versões anteriores como fallback.
            try:
                media_len = float(a.get("slot", 0) or 0)
            except Exception:
                media_len = 0.0
        try:
            skip = float(a.get("skip_seconds", DEFAULT_SLATE_SKIP_SECONDS) or 0) if a.get("skip_slate", False) else 0.0
        except Exception:
            skip = 0.0
        try:
            adjust = float(a.get("duration_adjust", a.get("offset", 0)) or 0)
        except Exception:
            adjust = 0.0
        return max(0.0, float(media_len or 0.0) - max(0.0, skip) + adjust)

    def _manual_block_by_id(self, block_id):
        if block_id in (None, "", 0, "0"):
            return None
        for b in self.manual_breaks:
            if str(b.get("id")) == str(block_id):
                return b
        return None

    def _avulso_resolved_start(self, a, previous_any=None, previous_in_block=None):
        """Resolve o início sem qualquer vínculo com PROGRAMA/Cultura.

        FIXO: usa o horário digitado.
        VINCULADO: começa no fim lógico do AVULSO anterior. Se pertencer a um
        BLOCO/JANELA e for a primeira mídia desse bloco, começa no início do bloco.
        """
        if a.get("mode", "FIXO") == "FIXO":
            t = a.get("time", "00:00:00")
            return t if self.validate_hms(t) else None

        block = self._manual_block_by_id(a.get("block_id"))
        prev = previous_in_block if block else previous_any
        if prev:
            return prev.get("end")
        if block:
            t = block.get("time", "")
            return t if self.validate_hms(t) else None

        # Sem predecessor não escondemos a mídia da grade: mantemos o horário
        # salvo como fallback e marcamos aviso visual no evento.
        t = a.get("time", "")
        return t if self.validate_hms(t) else None

    def rebuild_combined_events(self):
        # V1.36.5:
        # - ELEITORAL HABILITADO: mantém somente os slots Cultura que comandam
        #   inserts ESTADO + HORARIO POLITICO.
        # - ELEITORAL DESABILITADO: mostra a grade Cultura INTEGRAL como
        #   referência, sem transformar programas/chamadas em inserts automáticos.
        base=[]
        electoral_mode = bool(self.electoral_enabled_var.get())
        if electoral_mode:
            source_rows = self.operational_cultura_insert_events or getattr(self, "cultura_insert_events", self.events)
        else:
            source_rows = self.operational_cultura_grade_events or getattr(self, "cultura_grade_events", [])

        for e in source_rows:
            if e.get("origin","CULTURA") != "CULTURA" and "origin" in e:
                continue
            raw_start = e.get("published_start", e.get("start",""))
            if electoral_mode:
                if not self._is_operational_start(raw_start):
                    continue
            elif self._hms_to_seconds_safe(raw_start) is None:
                continue
            item = dict(e, origin="CULTURA")
            item["published_start"] = raw_start
            item["start"] = self.grade_time(raw_start)
            item["grade_offset"] = self.grade_offset_seconds()
            if not electoral_mode:
                item["reference_only"] = True
            base.append(item)

        if electoral_mode:
            base=self._apply_electoral_plan_to_cultura_events(base)

        wd=datetime.now().weekday()
        names=["SEG","TER","QUA","QUI","SEX","SAB","DOM"]

        # Resolve os AVULSOS na ordem em que foram cadastrados. Isso é deliberado:
        # VINCULADO significa "comece quando o anterior terminar".
        previous_any = None
        previous_by_block = {}
        for i,a in enumerate(self.avulsos):
            if not a.get("enabled",True) or names[wd] not in a.get("days",names):
                continue

            block_id = a.get("block_id")
            prev_block = previous_by_block.get(str(block_id)) if block_id not in (None,"",0,"0") else None
            st=self._avulso_resolved_start(a, previous_any=previous_any, previous_in_block=prev_block)
            if not st:
                continue

            media=str(a.get("media","") or "").strip()
            duration=self._avulso_air_duration(a)
            end_time=self._add_hms(st, duration)
            block=self._manual_block_by_id(block_id)
            orphan = a.get("mode","FIXO") == "VINCULADO" and not (prev_block if block else previous_any) and not block

            ev={
                "start":st,
                "duration":duration,
                "title":a.get("title","AVULSO"),
                "origin":"AVULSO",
                "avulso_id":a.get("id",i),
                "avulso_media":media,
                "integral":False,  # duração lógica já incorpora o ajuste
                "skip_slate":bool(a.get("skip_slate",False)),
                "skip_seconds":float(a.get("skip_seconds",DEFAULT_SLATE_SKIP_SECONDS) or 0),
                "duration_adjust":float(a.get("duration_adjust", a.get("offset",0)) or 0),
                "linked":a.get("mode","FIXO") == "VINCULADO",
                "link_orphan":orphan,
                "block_id":block_id,
                "calculated_end":end_time,
            }
            base.append(ev)
            resolved={"start":st,"end":end_time,"duration":duration,"event":ev}
            previous_any=resolved
            if block_id not in (None,"",0,"0"):
                previous_by_block[str(block_id)]=resolved

        # BLOCO/JANELA LOCAL: reserva operacional; jamais auto-dispara.
        for i,b in enumerate(self.manual_breaks):
            if not b.get("enabled", True) or names[wd] not in b.get("days", names):
                continue
            st=b.get("time","")
            if not self.validate_hms(st):
                continue
            slot=float(b.get("slot",0) or 0)
            block_id=b.get("id",i)
            children=[e for e in base if e.get("origin")=="AVULSO" and str(e.get("block_id"))==str(block_id)]
            used=sum(float(e.get("duration",0) or 0) for e in children)
            remaining=slot-used
            base.append({
                "start":st, "published_start":st, "duration":slot,
                "title":b.get("title", f"BLOCO {i+1}"), "origin":"MANUAL",
                "manual_break_id":block_id, "manual_media":"",
                "skip_slate":False, "skip_seconds":0.0, "integral":False,
                "block_used":used, "block_remaining":remaining,
                "calculated_end":self._add_hms(st, slot)
            })
        base.sort(key=lambda e:(e["start"], 0 if e.get("origin")=="MANUAL" else 1))
        self.events=base

    def add_manual_break_dialog(self, edit_index=None):
        """Cria/edita um BLOCO/JANELA LOCAL protegido na grade.

        O bloco define início + duração disponível. As mídias são cadastradas em
        AVULSO e podem ser associadas a este bloco; VINCULADO encadeia cada mídia
        ao final lógico da anterior. O bloco em si nunca auto-dispara.
        """
        old = self.manual_breaks[edit_index] if edit_index is not None else {}
        w = tk.Toplevel(self); w.title("Bloco / Janela Local — V1.34"); w.transient(self); w.grab_set()
        title = tk.StringVar(value=old.get("title", f"BLOCO LOCAL {len(self.manual_breaks)+1}"))
        raw = old.get("time", datetime.now().strftime("%H:%M:%S"))
        if not self.validate_hms(raw): raw = datetime.now().strftime("%H:%M:%S")
        hh0, mm0, ss0 = [int(x) for x in raw.split(":")]
        hv=tk.StringVar(value=f"{hh0:02d}"); mv=tk.StringVar(value=f"{mm0:02d}"); sv=tk.StringVar(value=f"{ss0:02d}")
        days=tk.StringVar(value=" ".join(old.get("days", ["SEG","TER","QUA","QUI","SEX","SAB","DOM"])))
        slot=tk.StringVar(value=str(old.get("slot",150) or 150))
        ttk.Label(w,text="Início do bloco").grid(row=0,column=0,sticky="w",padx=8,pady=5)
        tf=ttk.Frame(w); tf.grid(row=0,column=1,sticky="w",padx=8,pady=5)
        for n,(var, vals2) in enumerate(((hv,range(24)),(mv,range(60)),(sv,range(60)))):
            ttk.Spinbox(tf,values=tuple(f"{i:02d}" for i in vals2),textvariable=var,width=3,justify="center",wrap=True).pack(side="left")
            if n < 2: ttk.Label(tf,text=":").pack(side="left",padx=2)
        ttk.Label(w,text="Nome do bloco").grid(row=1,column=0,sticky="w",padx=8,pady=4)
        ttk.Entry(w,textvariable=title,width=40).grid(row=1,column=1,sticky="ew",padx=8,pady=4)
        ttk.Label(w,text="Duração reservada (segundos)").grid(row=2,column=0,sticky="w",padx=8,pady=4)
        ttk.Entry(w,textvariable=slot,width=12).grid(row=2,column=1,sticky="w",padx=8,pady=4)
        ttk.Label(w,text="Dias SEG TER...").grid(row=3,column=0,sticky="w",padx=8,pady=4)
        ttk.Entry(w,textvariable=days,width=40).grid(row=3,column=1,sticky="ew",padx=8,pady=4)
        ttk.Label(w,text="Ex.: 150 s = 02:30. As mídias serão associadas pelo INSERT AVULSO.").grid(row=4,column=0,columnspan=2,sticky="w",padx=8,pady=(6,2))
        ttk.Label(w,text="O Scheduler mostra SOBRA ou EXCESSO do conjunto vinculado.").grid(row=5,column=0,columnspan=2,sticky="w",padx=8,pady=(0,6))
        def save():
            try:
                h=max(0,min(23,int(hv.get()))); m=max(0,min(59,int(mv.get()))); s=max(0,min(59,int(sv.get())))
                sl=max(0,float(str(slot.get()).replace(",",".")))
            except Exception:
                messagebox.showwarning("Bloco local","Confira horário e duração.",parent=w); return
            valid={"SEG","TER","QUA","QUI","SEX","SAB","DOM"}
            ds=[x for x in days.get().upper().replace(","," ").split() if x in valid]
            if not ds: ds=list(valid)
            rec={"id":old.get("id",time.time_ns()),"title":title.get().strip() or "BLOCO LOCAL","time":f"{h:02d}:{m:02d}:{s:02d}","days":ds,"slot":sl,"enabled":True}
            if edit_index is None: self.manual_breaks.append(rec)
            else: self.manual_breaks[edit_index]=rec
            self.rebuild_combined_events(); self.refresh_tree(); self.save_state(); w.destroy()
        ttk.Button(w,text="CRIAR BLOCO" if edit_index is None else "SALVAR ALTERAÇÕES",command=save).grid(row=6,column=0,columnspan=2,sticky="ew",padx=8,pady=8)
        w.columnconfigure(1,weight=1)

    def _selected_manual_index(self):
        e=self._selected_manual_event()
        if not e: return None
        mid=e.get("manual_break_id")
        for i,b in enumerate(self.manual_breaks):
            if b.get("id")==mid: return i
        return None

    def edit_selected_insert(self):
        sel=self.tree.selection()
        if not sel:
            messagebox.showwarning("Editar","Selecione um AVULSO ou um BLOCO/JANELA LOCAL."); return
        try: e=self.events[int(sel[0])]
        except Exception: return
        if e.get("origin")=="MANUAL":
            i=self._selected_manual_index()
            if i is not None: self.add_manual_break_dialog(i)
        elif e.get("origin")=="AVULSO": self.edit_selected_avulso()
        else: messagebox.showwarning("Editar","Eventos CULTURA não são editados por este botão.")

    def delete_selected_insert(self):
        sel=self.tree.selection()
        if not sel:
            messagebox.showwarning("Excluir","Selecione um AVULSO ou um BLOCO/JANELA LOCAL."); return
        try: e=self.events[int(sel[0])]
        except Exception: return
        if e.get("origin")=="MANUAL":
            i=self._selected_manual_index()
            if i is not None and messagebox.askyesno("Bloco local","Excluir este BLOCO/JANELA LOCAL?\n\nOs avulsos associados continuarão cadastrados, mas ficarão sem bloco."):
                self.manual_breaks.pop(i); self.rebuild_combined_events(); self.save_state(); self.refresh_tree()
        elif e.get("origin")=="AVULSO": self.delete_selected_avulso()
        else: messagebox.showwarning("Excluir","Eventos CULTURA não são excluídos por este botão.")

    def _manual_break_record(self, event):
        mid=event.get("manual_break_id")
        for b in self.manual_breaks:
            if b.get("id") == mid: return b
        return None

    def add_avulso_dialog(self, edit_index=None):
        old=self.avulsos[edit_index] if edit_index is not None else {}
        w=tk.Toplevel(self); w.title("Insert Avulso — V1.34"); w.transient(self); w.grab_set()
        vals={
          "title":tk.StringVar(value=old.get("title","VINHETA / CHAMADA")),
          "mode":tk.StringVar(value=old.get("mode","FIXO")),
          "time":tk.StringVar(value=old.get("time","00:00:00")),
          "days":tk.StringVar(value=" ".join(old.get("days",["SEG","TER","QUA","QUI","SEX"]))),
          "duration_adjust":tk.StringVar(value=str(old.get("duration_adjust", old.get("offset",0)))),
          "media":tk.StringVar(value=old.get("media","")),
          "skip_slate":tk.BooleanVar(value=bool(old.get("skip_slate",False))),
          "skip_seconds":tk.StringVar(value=str(old.get("skip_seconds",DEFAULT_SLATE_SKIP_SECONDS))),
          "enabled":tk.BooleanVar(value=old.get("enabled",True))}

        ttk.Label(w,text="Modo:").grid(row=0,column=0,sticky="w",padx=8,pady=5)
        mode_combo=ttk.Combobox(w,textvariable=vals["mode"],values=("FIXO","VINCULADO"),state="readonly",width=16)
        mode_combo.grid(row=0,column=1,sticky="w",padx=8)
        ttk.Label(w,text="VINCULADO = começa exatamente no fim lógico da mídia anterior.").grid(row=0,column=2,sticky="w",padx=4)

        ttk.Label(w,text="Evento").grid(row=1,column=0,sticky="w",padx=8,pady=4)
        ttk.Entry(w,textvariable=vals["title"],width=45).grid(row=1,column=1,columnspan=2,sticky="ew",padx=8,pady=4)

        ttk.Label(w,text="Hora fixa / fallback").grid(row=2,column=0,sticky="w",padx=8,pady=4)
        time_frame = ttk.Frame(w); time_frame.grid(row=2,column=1,sticky="w",padx=8,pady=4)
        raw_time = vals["time"].get().strip()
        if not self.validate_hms(raw_time): raw_time = "00:00:00"
        hh0, mm0, ss0 = [int(x) for x in raw_time.split(":")]
        hour_var=tk.StringVar(value=f"{hh0:02d}"); minute_var=tk.StringVar(value=f"{mm0:02d}"); second_var=tk.StringVar(value=f"{ss0:02d}")
        def sync_fixed_time(*_):
            try:
                h=max(0,min(23,int(hour_var.get()))); m=max(0,min(59,int(minute_var.get()))); sec=max(0,min(59,int(second_var.get())))
            except Exception: return
            vals["time"].set(f"{h:02d}:{m:02d}:{sec:02d}")
        for n,(var,rng) in enumerate(((hour_var,range(24)),(minute_var,range(60)),(second_var,range(60)))):
            sp=ttk.Spinbox(time_frame,values=tuple(f"{i:02d}" for i in rng),textvariable=var,width=3,justify="center",wrap=True,command=sync_fixed_time)
            sp.pack(side="left"); sp.bind("<FocusOut>",sync_fixed_time); sp.bind("<KeyRelease>",sync_fixed_time)
            if n<2: ttk.Label(time_frame,text=":").pack(side="left",padx=2)

        ttk.Label(w,text="Dias SEG TER...").grid(row=3,column=0,sticky="w",padx=8,pady=4)
        ttk.Entry(w,textvariable=vals["days"],width=45).grid(row=3,column=1,columnspan=2,sticky="ew",padx=8,pady=4)

        # Associação opcional a BLOCO/JANELA LOCAL.
        ttk.Label(w,text="Bloco / Janela local").grid(row=4,column=0,sticky="w",padx=8,pady=4)
        blocks=list(self.manual_breaks or [])
        block_labels=["(SEM BLOCO)"]+[f'{b.get("time","--:--:--")} | {b.get("title","BLOCO")} | {float(b.get("slot",0) or 0):g}s' for b in blocks]
        block_display=tk.StringVar(value="(SEM BLOCO)")
        block_combo=ttk.Combobox(w,textvariable=block_display,values=block_labels,state="readonly",width=58)
        block_combo.grid(row=4,column=1,columnspan=2,sticky="ew",padx=8,pady=4)
        old_bid=old.get("block_id")
        if old_bid not in (None,"",0,"0"):
            for pos,b in enumerate(blocks, start=1):
                if str(b.get("id"))==str(old_bid): block_combo.current(pos); break
        else: block_combo.current(0)

        ttk.Label(w,text="Mídia Caspar").grid(row=5,column=0,sticky="w",padx=8,pady=4)
        ttk.Entry(w,textvariable=vals["media"],width=58).grid(row=5,column=1,sticky="ew",padx=8,pady=4)
        duration_var=tk.StringVar(value="Duração: --")
        def update_duration(*_):
            media=vals["media"].get().strip()
            d=self.media_duration(media)
            try: skip=float(vals["skip_seconds"].get().replace(",",".")) if vals["skip_slate"].get() else 0.0
            except Exception: skip=0.0
            try: adj=float(vals["duration_adjust"].get().replace(",","."))
            except Exception: adj=0.0
            if d is None:
                duration_var.set("Duração: arquivo/ffprobe indisponível")
            else:
                logical=max(0.0,d-max(0.0,skip)+adj)
                duration_var.set(f"Duração mídia: {d:.3f}s | lógica: {logical:.3f}s")
        def browse():
            x=filedialog.askopenfilename(initialdir=self.media_root_var.get() or MEDIA_ROOT,filetypes=[("Vídeos","*.mp4 *.mov *.mxf *.avi *.mkv"),("Todos","*.*")])
            if x:
                vals["media"].set(x); update_duration()
        ttk.Button(w,text="ESCOLHER MÍDIA",command=browse).grid(row=5,column=2,padx=6)
        ttk.Label(w,textvariable=duration_var,font=("Segoe UI",9,"bold")).grid(row=6,column=1,columnspan=2,sticky="w",padx=8)

        ttk.Label(w,text="Ajuste duração (+/- s)").grid(row=7,column=0,sticky="w",padx=8,pady=4)
        adj_entry=ttk.Entry(w,textvariable=vals["duration_adjust"],width=12); adj_entry.grid(row=7,column=1,sticky="w",padx=8,pady=4)
        adj_entry.bind("<KeyRelease>",update_duration)

        skip_frame=ttk.Frame(w); skip_frame.grid(row=8,column=0,columnspan=3,sticky="w",padx=8,pady=4)
        cb=ttk.Checkbutton(skip_frame,text="PULAR CLAQUETE",variable=vals["skip_slate"],command=update_duration); cb.pack(side="left")
        ttk.Label(skip_frame,text="   Segundos:").pack(side="left")
        sk=ttk.Spinbox(skip_frame,from_=0.0,to=600.0,increment=0.5,textvariable=vals["skip_seconds"],width=7,command=update_duration); sk.pack(side="left",padx=(4,0)); sk.bind("<KeyRelease>",update_duration)
        ttk.Checkbutton(w,text="ATIVO",variable=vals["enabled"]).grid(row=9,column=0,columnspan=2,sticky="w",padx=8)

        def save():
            sync_fixed_time()
            try:
                adj=float(vals["duration_adjust"].get().replace(",",".")); skip_seconds=max(0.0,float(vals["skip_seconds"].get().replace(",",".")))
            except Exception:
                messagebox.showerror("Avulso","Ajuste e claquete precisam ser números válidos.",parent=w); return
            media=vals["media"].get().strip()
            if not media:
                messagebox.showerror("Avulso","Escolha uma mídia. O VINCULADO não pode existir sem arquivo.",parent=w); return
            if not os.path.isfile(media):
                messagebox.showerror("Avulso",f"Arquivo de mídia não encontrado:\n\n{media}",parent=w); return
            # Valida também se o arquivo está dentro da media-path do Caspar.
            try: self.media_to_caspar_name(media)
            except Exception as exc:
                messagebox.showerror("Avulso",str(exc),parent=w); return
            if vals["mode"].get()=="FIXO" and not self.validate_hms(vals["time"].get().strip()):
                messagebox.showerror("Avulso","Hora inválida.",parent=w); return
            days=[x.upper() for x in vals["days"].get().replace(","," ").split() if x.upper() in {"SEG","TER","QUA","QUI","SEX","SAB","DOM"}]
            if not days: days=["SEG","TER","QUA","QUI","SEX","SAB","DOM"]
            idx=block_combo.current(); block_id=(blocks[idx-1].get("id") if idx>0 and idx-1<len(blocks) else None)
            a={"id":old.get("id",time.time_ns()),"title":vals["title"].get().strip() or os.path.basename(media),"mode":vals["mode"].get(),"time":vals["time"].get().strip(),"days":days,"duration_adjust":adj,"media":media,"block_id":block_id,"skip_slate":vals["skip_slate"].get(),"skip_seconds":skip_seconds,"enabled":vals["enabled"].get()}
            if edit_index is None:self.avulsos.append(a)
            else:self.avulsos[edit_index]=a
            self.rebuild_combined_events(); self.save_state(); self.refresh_tree(); w.destroy()
        ttk.Button(w,text="SALVAR",command=save).grid(row=10,column=0,columnspan=3,sticky="ew",padx=8,pady=8)
        w.columnconfigure(1,weight=1); update_duration()

    def _selected_avulso_index(self):
        sel=self.tree.selection()
        if not sel:return None
        e=self.events[int(sel[0])]
        if e.get("origin")!="AVULSO":return None
        aid=e.get("avulso_id")
        for i,a in enumerate(self.avulsos):
            if a.get("id",i)==aid:return i
        return None

    def edit_selected_avulso(self):
        i=self._selected_avulso_index()
        if i is None: messagebox.showwarning("Avulso","Selecione um INSERT AVULSO na lista."); return
        self.add_avulso_dialog(i)

    def delete_selected_avulso(self):
        i=self._selected_avulso_index()
        if i is None: messagebox.showwarning("Avulso","Selecione um INSERT AVULSO na lista."); return
        if messagebox.askyesno("Avulso","Excluir este insert avulso?"):
            self.avulsos.pop(i); self.rebuild_combined_events(); self.save_state(); self.refresh_tree()

    def parse_fallback_bytes(self, data):
        """Parser do fallback DPTX XML/TXT. Procura horários, duração e os campos
        ESTADO/HORARIO POLITICO; mantém também a grade para âncoras AO VIVO."""
        text=data.decode("utf-8",errors="replace")
        blocks=[]
        try:
            root=ET.fromstring(text)
            for el in root.iter():
                blob=" ".join([el.tag]+[f"{k}={v}" for k,v in el.attrib.items()]+[(el.text or "")])
                if re.search(r"\d{2}:\d{2}:\d{2}",blob): blocks.append(blob)
        except Exception:
            blocks=text.splitlines()
        inserts=[]; grade=[]
        for blob in blocks:
            times=re.findall(r"\b\d{2}:\d{2}:\d{2}\b",blob)
            if not times: continue
            start=times[0]; dur=duration_to_seconds(times[1]) if len(times)>1 else 0
            bnorm=norm(blob)
            # título: tenta name/event/name= e cai no bloco resumido
            m=re.search(r'(?:name|nome|evento|event)\s*[=:]\s*["\']?([^"\'<>;|]+)',blob,re.I)
            title=(m.group(1).strip() if m else re.sub(r"\s+"," ",blob)[:120])
            divulgation = "ESTADO" if "ESTADO" in bnorm else ("NACIONAL" if "NACIONAL" in bnorm else "")
            category = "HORARIO POLITICO" if "HORARIO POLITICO" in bnorm else ("PROGRAMA" if "PROGRAMA" in bnorm else "")
            # Fallback também preserva a grade integral para referência.
            ge={"start":start,"duration":dur,"title":title,"divulgation":divulgation,"category":category}
            grade.append(ge)
            if divulgation == "ESTADO" and category == "HORARIO POLITICO":
                inserts.append({"start":start,"duration":dur,"title":title,"divulgation":divulgation,"category":category,"is_cultura_political_insert":True})
        # dedupe
        di={e["start"]:e for e in inserts}; dg={(e["start"],live_norm(e["title"])):e for e in grade}
        return sorted(di.values(),key=lambda e:e["start"]), sorted(dg.values(),key=lambda e:e["start"])

    def _fallback_urls(self, day):
        token=day.strftime("%d%m%Y")
        return [f"https://cultura.uol.com.br/roteiro/files/dptx{token}.xml",f"https://cultura.uol.com.br/roteiro/files/dptx{token}.txt"]

    def handle_day_rollover(self, now):
        day=now.strftime("%Y-%m-%d")
        if day==self.current_day_key:return
        old=self.current_day_key; self.current_day_key=day
        self.executed.clear(); self.electoral_boundary_executed.clear(); self.live_dismissed.clear()
        # V1.35.6: nunca herda associação eleitoral do dia anterior.
        self.electoral_daily_plan=[]
        self.events=[e for e in self.events if e.get("origin") not in (None,"CULTURA")]
        self.last_cultura_updated=None; self.last_cultura_modified=None; self.last_cultura_signature=None
        self.next_refresh_at=0
        self.operational_cultura_insert_events=[]
        self.operational_cultura_grade_events=[]
        self.operational_program_events=[]
        self.operational_grade_signature=None
        logging.warning("NOVO DIA detectado | %s -> %s | grade Cultura limpa; nova leitura HTML > XML",old,day)
        self.cultura_sync_var.set(f"📅 NOVO DIA {now.strftime('%d/%m/%Y')} — sincronizando grade")
        if self.electoral_cadastro_path_var.get().strip():
            self.load_electoral_registration(manual=False)
        self.refresh_now()

    # ------------------------------------------------------------------------
    # MÍDIA
    # ------------------------------------------------------------------------

    def choose_media_root(self):
        path = filedialog.askdirectory(
            title="Escolha a pasta raiz do CasparCG",
            initialdir=self.media_root_var.get() or MEDIA_ROOT
        )

        if path:
            self.media_root_var.set(path)
            self.save_state()

    def _refresh_default_media_display(self):
        rows=[p for p in self.electoral_default_media_list if p]
        if not rows:
            self.default_media_var.set("")
        elif len(rows)==1:
            self.default_media_var.set(rows[0])
        else:
            self.default_media_var.set(f"{len(rows)} mídias padrão — alternância automática")

    def _next_default_electoral_media(self, advance=False):
        rows=[p for p in self.electoral_default_media_list if p and os.path.isfile(p)]
        if not rows:
            legacy=self.default_media_var.get().strip()
            return legacy if legacy and os.path.isfile(legacy) else ""
        ix=self.electoral_default_rotation_index % len(rows)
        chosen=rows[ix]
        if advance:
            self.electoral_default_rotation_index=(ix+1)%len(rows)
            self.save_state()
        return chosen

    def choose_default_media(self):
        paths = filedialog.askopenfilenames(
            title="Escolha uma ou mais mídias padrão eleitorais",
            initialdir=self.media_root_var.get() or MEDIA_ROOT,
            filetypes=[
                ("Vídeos", "*.mp4 *.mov *.mxf *.avi *.mkv"),
                ("Todos os arquivos", "*.*")
            ]
        )
        if paths:
            self.electoral_default_media_list=list(paths)
            self.electoral_default_rotation_index=0
            self._refresh_default_media_display()
            self.save_state()


    def choose_selected_media(self):
        path = filedialog.askopenfilename(
            title="Escolha a mídia para o(s) horário(s) selecionado(s)",
            initialdir=self.media_root_var.get() or MEDIA_ROOT,
            filetypes=[
                ("Vídeos", "*.mp4 *.mov *.mxf *.avi *.mkv"),
                ("Todos os arquivos", "*.*")
            ]
        )

        if path:
            self.selected_media_var.set(path)
            self.save_state()

    def apply_media_to_selection(self):
        selected = self.tree.selection()

        if not selected:
            messagebox.showwarning(
                "Mídia",
                "Selecione um ou mais horários."
            )
            return

        media = self.selected_media_var.get().strip()

        if not media:
            messagebox.showwarning(
                "Mídia",
                "Escolha a mídia da seleção primeiro."
            )
            return

        try:
            skip_seconds = float(self.skip_slate_seconds_var.get().strip().replace(",", "."))
            if skip_seconds < 0:
                raise ValueError
        except Exception:
            messagebox.showerror(
                "Claquete",
                "O tempo da claquete precisa ser um número igual ou maior que zero."
            )
            return

        skip_enabled = bool(self.skip_slate_var.get())

        for iid in selected:
            index = int(iid)
            if 0 <= index < len(self.events):
                event = self.events[index]
                if event.get("origin") == "MANUAL":
                    b = self._manual_break_record(event)
                    if b is not None:
                        b["media"] = media
                        b["skip_slate"] = skip_enabled
                        b["skip_seconds"] = skip_seconds
                        b["integral"] = bool(self.integral_selection_var.get())
                        event["manual_media"] = media
                        event["skip_slate"] = skip_enabled
                        event["skip_seconds"] = skip_seconds
                        event["integral"] = bool(self.integral_selection_var.get())
                    continue
                start = self.event_source_start(event)
                self.media_overrides[start] = media
                self.slate_skip_overrides[start] = {
                    "enabled": skip_enabled,
                    "seconds": skip_seconds
                }
                self.integral_overrides[start] = bool(self.integral_selection_var.get())

        logging.info(
            "Mídia aplicada | arquivo=%s | itens=%s | pular_claquete=%s | segundos=%s",
            media, len(selected), skip_enabled, skip_seconds
        )
        self.save_state()
        self.refresh_tree()

    def media_for_event(self, event):
        if event.get("electoral_local"):
            media=event.get("electoral_media","")
            if media and os.path.isfile(media): return media
            return self.default_media_var.get().strip()
        if event.get("origin") == "MANUAL":
            return ""
        if event.get("origin") == "AVULSO":
            return event.get("avulso_media", "")
        key = self.event_source_start(event)
        return (self.media_overrides.get(key) or self.default_media_var.get().strip())

    def media_to_caspar_name(self, media):
        media = media.strip().strip('"')

        if not media:
            raise ValueError("Nenhuma mídia foi configurada.")

        # IMPORTANTE:
        # A raiz usada no comando PLAY deve ser a media-path do CasparCG,
        # e não a pasta de trabalho usada para procurar os arquivos.
        root = self.caspar_media_root_var.get().strip() or CASPAR_MEDIA_ROOT

        if os.path.isabs(media):
            rel = os.path.relpath(media, root)

            if rel.startswith(".."):
                raise ValueError(
                    "A mídia está fora da media-path configurada no CasparCG.\n\n"
                    f"Media-path Caspar: {root}\n"
                    f"Arquivo: {media}"
                )

            media = rel

        media = media.replace("\\", "/")
        media, _ext = os.path.splitext(media)

        logging.info(
            "Conversão mídia -> Caspar | arquivo=%s | raiz=%s | clip=%s",
            self.default_media_var.get().strip(),
            root,
            media
        )

        return media

    def slate_skip_for_event(self, event):
        if event.get("origin") == "MANUAL":
            try:
                seconds = float(event.get("skip_seconds", DEFAULT_SLATE_SKIP_SECONDS))
            except Exception:
                seconds = DEFAULT_SLATE_SKIP_SECONDS
            return bool(event.get("skip_slate", False)), max(0.0, seconds)
        if event.get("origin") == "AVULSO":
            try:
                seconds = float(event.get("skip_seconds", DEFAULT_SLATE_SKIP_SECONDS))
            except Exception:
                seconds = DEFAULT_SLATE_SKIP_SECONDS
            return bool(event.get("skip_slate", False)), max(0.0, seconds)

        data = self.slate_skip_overrides.get(self.event_source_start(event), {})
        try:
            seconds = float(data.get("seconds", DEFAULT_SLATE_SKIP_SECONDS))
        except Exception:
            seconds = DEFAULT_SLATE_SKIP_SECONDS

        return bool(data.get("enabled", False)), max(0.0, seconds)

    def skip_seconds_to_frames(self, seconds):
        return max(0, int(round(float(seconds) * CHANNEL_FPS)))

    # ------------------------------------------------------------------------
    # CASPAR
    # ------------------------------------------------------------------------

    def amcp(self):
        return CasparAMCP(
            self.host_var.get().strip(),
            int(self.port_var.get().strip())
        )

    def target(self):
        return (
            f"{int(self.channel_var.get().strip())}-"
            f"{int(self.layer_var.get().strip())}"
        )

    def test_caspar(self):
        try:
            response = self.amcp().send("VERSION SERVER")
            self.caspar_status_var.set(
                f"CasparCG: conectado ({response[:45]})"
            )
            logging.info("Teste CasparCG OK | %s", response)
        except Exception as exc:
            self.caspar_status_var.set("CasparCG: ERRO")
            messagebox.showerror(
                "CasparCG",
                f"Falha na conexão AMCP:\n\n{exc}"
            )

    def send_play(self, media, seek_frames=0):
        clip = self.media_to_caspar_name(media)

        if seek_frames > 0:
            command = f'PLAY {self.target()} "{clip}" SEEK {int(seek_frames)}'
        else:
            command = f'PLAY {self.target()} "{clip}"'

        response = self.amcp().send(command)

        if response and not (
            response.startswith("200")
            or response.startswith("201")
            or response.startswith("202")
        ):
            raise RuntimeError(
                f"CasparCG respondeu:\n{response}"
            )

        return response

    def play_selected(self):
        selected = self.tree.selection()

        if not selected:
            messagebox.showwarning("PLAY", "Selecione um ou mais horários.")
            return

        if self.is_electoral_lock():
            messagebox.showwarning(
                "PLAY BLOQUEADO",
                "A janela eleitoral está protegida.\n"
                "Nenhuma inserção local pode tomar o PROGRAM."
            )
            return

        rows = []
        for iid in selected:
            try:
                index = int(iid)
                if 0 <= index < len(self.events):
                    event = self.events[index]
                    media = self.media_for_event(event)
                    if media:
                        rows.append((event, media))
            except Exception:
                continue

        if not rows:
            messagebox.showwarning("PLAY", "Nenhuma das linhas selecionadas possui mídia aplicada.")
            return

        rows.sort(key=lambda item: item[0].get("start", "00:00:00"))

        # Durante AO VIVO, múltiplas linhas selecionadas formam um único BREAK
        # assistido: o operador dispara apenas a primeira; as demais seguem
        # automaticamente sem retornar à rede entre as peças.
        if self.live_active:
            if self.break_playlist_active or self.local_insertion_active:
                messagebox.showwarning("BREAK ASSISTIDO", "Já existe um break/inserção em execução.")
                return

            self.break_playlist_stop_now.clear()
            self.break_playlist_finish_current.clear()
            self.break_playlist_active = True
            logging.warning(
                "BREAK ASSISTIDO DISPARADO | programa=%s | itens=%s | play_real=%s",
                self.live_title, len(rows), datetime.now().strftime("%H:%M:%S")
            )
            threading.Thread(
                target=self._assisted_break_worker,
                args=(rows,),
                daemon=True
            ).start()
            return

        # Fora de AO VIVO preserva o comportamento tradicional: uma linha por PLAY.
        if len(rows) > 1:
            messagebox.showwarning(
                "PLAY",
                "Playlist agregada é usada durante AO VIVO.\n"
                "Fora de AO VIVO, selecione apenas uma linha."
            )
            return

        event, media = rows[0]
        if event.get("origin") == "MANUAL":
            logging.warning(
                "BLOCO LOCAL PLAY | evento=%s | reservado=%s | play_real=%s | midia=%s",
                event.get("title"), event.get("start"), datetime.now().strftime("%H:%M:%S"), media
            )

        threading.Thread(
            target=self._local_playout_worker,
            args=(event, media, True),
            daemon=True
        ).start()

    def break_cut_now(self):
        if not self.break_playlist_active:
            messagebox.showinfo("BREAK ASSISTIDO", "Não existe break agregado em execução.")
            return
        self.break_playlist_stop_now.set()
        self.break_playlist_finish_current.set()
        self.break_playlist_status_var.set("BREAK: CORTE IMEDIATO solicitado — retornando à rede")
        logging.warning("BREAK ASSISTIDO | CORTE IMEDIATO solicitado")

    def break_finish_current(self):
        if not self.break_playlist_active:
            messagebox.showinfo("BREAK ASSISTIDO", "Não existe break agregado em execução.")
            return
        self.break_playlist_finish_current.set()
        self.break_playlist_status_var.set("BREAK: terminar mídia atual e voltar — próximas canceladas")
        logging.warning("BREAK ASSISTIDO | TERMINAR ATUAL E VOLTAR solicitado")

    def _event_play_duration(self, event, media):
        skip_enabled, skip_seconds = self.slate_skip_for_event(event)
        original_duration = max(0, int(event.get("duration", 0) or 0))
        media_len = self.media_duration(media)
        if media_len is not None and skip_enabled:
            media_len = max(0.0, media_len - skip_seconds)
        integral = bool(
            event.get(
                "integral",
                self.integral_overrides.get(self.event_source_start(event), False)
            )
        )
        if event.get("origin") == "AVULSO":
            return float(event.get("duration", 0) or 0)
        if original_duration <= 0:
            return float(media_len or 0)
        if media_len is not None and media_len > original_duration and integral:
            return float(media_len)
        return float(original_duration)

    def _assisted_break_worker(self, rows):
        """Executa uma playlist agregada mantendo CASPAR/SDI8 no PROGRAM."""
        self.local_insertion_active = True
        try:
            if self.is_electoral_lock():
                return

            total = sum(self._event_play_duration(e, m) for e, m in rows)
            self.after(0, lambda: self.break_playlist_status_var.set(
                f"🔴 BREAK ASSISTIDO | {len(rows)} mídia(s) | total previsto {int(total)//60:02d}:{int(total)%60:02d}"
            ))

            # Pré-carrega a primeira peça antes do corte.
            first_event, first_media = rows[0]
            skip_enabled, skip_seconds = self.slate_skip_for_event(first_event)
            seek_frames = self.skip_seconds_to_frames(skip_seconds) if skip_enabled else 0
            response = self.send_play(first_media, seek_frames=seek_frames)
            logging.info("BREAK item PLAY pronto | item=1 | midia=%s | resposta=%s", first_media, response)
            time.sleep(CASPAR_PREROLL_SECONDS)

            if self.is_electoral_lock() or self.break_playlist_stop_now.is_set():
                try:
                    self.amcp().send(f"STOP {self.target()}")
                except Exception:
                    pass
                self.restore_base_source()
                return

            if not self.atem_set_program(self.atem_caspar_source()):
                raise RuntimeError("Não foi possível colocar SDI 8 no PROGRAM.")

            for pos, (event, media) in enumerate(rows, start=1):
                if pos > 1:
                    if self.break_playlist_finish_current.is_set() or self.break_playlist_stop_now.is_set():
                        break
                    skip_enabled, skip_seconds = self.slate_skip_for_event(event)
                    seek_frames = self.skip_seconds_to_frames(skip_seconds) if skip_enabled else 0
                    response = self.send_play(media, seek_frames=seek_frames)
                    logging.info("BREAK item PLAY | item=%s/%s | midia=%s | resposta=%s", pos, len(rows), media, response)

                duration = self._event_play_duration(event, media)
                started = datetime.now()
                self.local_insertion_until = time.time() + duration
                media_name = os.path.basename(media)
                self.after(0, lambda p=pos, n=len(rows), mn=media_name, d=duration:
                           self.break_playlist_status_var.set(
                               f"🔴 BREAK {p}/{n} | {mn} | {d:.1f}s"
                           ))

                completed = True
                end_at = time.monotonic() + duration
                while time.monotonic() < end_at:
                    if self.is_electoral_lock() or self.break_playlist_stop_now.is_set():
                        completed = False
                        break
                    time.sleep(0.03)

                elapsed = max(0.0, (datetime.now() - started).total_seconds())

                if completed:
                    self.executed.add(self.event_key(event))
                    logging.info(
                        "BREAK item EXECUTADO | item=%s/%s | evento=%s | midia=%s | duracao_real=%.3f",
                        pos, len(rows), event.get("title"), media, elapsed
                    )
                else:
                    logging.warning(
                        "BREAK item INTERROMPIDO | item=%s/%s | evento=%s | midia=%s | duracao_real=%.3f",
                        pos, len(rows), event.get("title"), media, elapsed
                    )

                self.after(0, self.refresh_tree)

                if not completed or self.break_playlist_finish_current.is_set():
                    break

            # Tira o Caspar do ar antes de parar o player.
            self.restore_base_source()
            try:
                self.amcp().send(f"STOP {self.target()}")
            except Exception:
                logging.exception("Falha STOP Caspar após BREAK ASSISTIDO")

            logging.info("BREAK ASSISTIDO FINALIZADO | retorno=%s", self.base_source_for_time())
            self.after(0, lambda: self.break_playlist_status_var.set("BREAK ASSISTIDO: finalizado / rede restaurada"))

        except Exception as exc:
            logging.exception("Falha no BREAK ASSISTIDO")
            try:
                self.restore_base_source()
                self.amcp().send(f"STOP {self.target()}")
            except Exception:
                pass
            self.after(0, lambda e=str(exc): messagebox.showerror("BREAK ASSISTIDO", e))
        finally:
            self.local_insertion_active = False
            self.local_insertion_until = None
            self.break_playlist_active = False
            self.break_playlist_stop_now.clear()
            self.break_playlist_finish_current.clear()

    def _local_playout_worker(self, event, media, manual=False):
        """PLAY no Caspar, corta para SDI8 e retorna à fonte-base ao terminar."""
        try:
            if self.is_electoral_lock():
                logging.warning(
                    "Inserção recusada: janela eleitoral | horario=%s",
                    event["start"]
                )
                return

            self.local_insertion_active = True

            skip_enabled, skip_seconds = self.slate_skip_for_event(event)
            seek_frames = self.skip_seconds_to_frames(skip_seconds) if skip_enabled else 0

            response = self.send_play(media, seek_frames=seek_frames)
            logging.info(
                "Caspar PLAY pronto | horario=%s | resposta=%s | seek_frames=%s | skip_seconds=%s",
                event["start"], response, seek_frames, skip_seconds if skip_enabled else 0
            )

            # Pequeno preroll: deixa o Caspar iniciar antes de colocá-lo no PROGRAM.
            time.sleep(CASPAR_PREROLL_SECONDS)

            # Revalida a trava imediatamente antes do corte.
            if self.is_electoral_lock():
                logging.warning(
                    "Corte SDI8 cancelado: janela eleitoral iniciou durante preroll"
                )
                try:
                    self.amcp().send(f"STOP {self.target()}")
                except Exception:
                    pass
                self.restore_base_source()
                return

            if not self.atem_set_program(self.atem_caspar_source()):
                raise RuntimeError("Não foi possível colocar SDI 8 no PROGRAM.")

            play_started_real = datetime.now()
            original_duration = max(0, int(event.get("duration", 0)))
            media_len = self.media_duration(media)
            if media_len is not None and skip_enabled:
                media_len = max(0.0, media_len - skip_seconds)
            integral = bool(event.get("integral", self.integral_overrides.get(self.event_source_start(event), False)))
            # V1.34 AVULSO: duration já é a duração lógica calculada (mídia - claquete +/- ajuste).
            if event.get("origin") == "AVULSO":
                duration = float(event.get("duration",0) or 0)
            # ELEITORAL LOCAL: duração física da mídia tem prioridade.
            elif event.get("electoral_local"):
                duration = media_len or original_duration
            # Slot 0 (avulso) = duração automática da mídia.
            elif original_duration <= 0:
                duration = media_len or 0
            elif media_len is not None and media_len > original_duration and integral:
                duration = media_len
            else:
                duration = original_duration
            # Se a mídia for menor que o slot, não enviamos STOP: o Caspar mantém
            # o último frame até o fim do slot. Se for maior e INTEGRAL=Não,
            # o STOP acontece no fim da grade; INTEGRAL=Sim usa duração real.
            self.local_insertion_until = time.time() + duration

            self.after(
                0,
                lambda: self.caspar_status_var.set(
                    f"NO AR: CASPAR até +{duration}s"
                )
            )

            # Mantém a inserção pelo tempo publicado pela Cultura.
            end_at = time.monotonic() + duration
            while time.monotonic() < end_at:
                # Segurança: se uma janela eleitoral começar, sai imediatamente.
                if self.is_electoral_lock():
                    logging.warning(
                        "Inserção interrompida pelo início da janela eleitoral."
                    )
                    break
                time.sleep(0.05)

            # Primeiro tira o Caspar do ar retornando à fonte-base.
            self.restore_base_source()

            # Depois para o player.
            try:
                self.amcp().send(f"STOP {self.target()}")
            except Exception:
                logging.exception("Falha STOP Caspar após inserção")

            self._register_electoral_valid_play(event, media, play_started_real, datetime.now())
            if event.get("electoral_local") and str(event.get("electoral_mode","")).startswith("PADRÃO"):
                current_default=self._next_default_electoral_media(False)
                if current_default and os.path.abspath(media)==os.path.abspath(current_default):
                    self._next_default_electoral_media(True)

            if manual:
                self.executed.add(self.event_key(event))
                self.after(0, self.refresh_tree)
            logging.info(
                "Inserção finalizada | horario=%s | retorno=%s",
                event["start"],
                self.base_source_for_time()
            )

        except Exception as exc:
            logging.exception(
                "Falha na inserção integrada | horario=%s | midia=%s",
                event.get("start"), media
            )
            try:
                self.restore_base_source()
            except Exception:
                pass
            self.after(
                0,
                lambda e=str(exc): messagebox.showerror(
                    "Falha de inserção",
                    e
                )
            )
        finally:
            self.local_insertion_active = False
            self.local_insertion_until = None

    def stop(self):
        try:
            response = self.amcp().send(
                f"STOP {self.target()}"
            )
            self.caspar_status_var.set(
                f"CasparCG: STOP ({response[:30]})"
            )
        except Exception as exc:
            messagebox.showerror(
                "STOP",
                str(exc)
            )

    # ------------------------------------------------------------------------
    # CULTURA
    # ------------------------------------------------------------------------

    def refresh_now(self):
        if self.refresh_in_progress:
            return

        self.refresh_in_progress = True
        self.cultura_status_var.set(
            "Cultura: atualizando..."
        )

        threading.Thread(
            target=self._refresh_worker,
            daemon=True
        ).start()

    def _download_current_day_xml_fallback(self):
        """Baixa XML/TXT do dia atual somente como fallback do HTML."""
        day = datetime.now().date()
        last_error = None
        for url in self._fallback_urls(day):
            try:
                req = urllib.request.Request(
                    url + f"?_{time.time_ns()}",
                    headers={"User-Agent":"Mozilla/5.0","Cache-Control":"no-cache"}
                )
                with urllib.request.urlopen(req, timeout=12) as r:
                    data = r.read()
                inserts, grade = self.parse_fallback_bytes(data)
                if inserts or grade:
                    return inserts, grade, url
            except Exception as exc:
                last_error = exc
        raise RuntimeError(f"Fallback XML/TXT indisponível: {last_error or 'sem dados'}")

    def _refresh_worker(self):
        # V1.35.9 — prioridade de fonte:
        # 1) campo HTML preenchido -> tenta exclusivamente o HTML;
        # 2) campo HTML vazio OU falha de acesso -> XML/TXT do dia atual;
        # 3) nunca mistura HTML e XML na mesma atualização operacional.
        html_url = self.url_var.get().strip()

        if html_url:
            try:
                html = download_cultura_html(html_url)
                events, metadata, grade_events, program_events = parse_cultura(html)
                signature = tuple(
                    (e["start"], e["duration"], e["title"])
                    for e in events
                )
                self.after(
                    0,
                    lambda: self._refresh_success(
                        events, metadata, signature, grade_events, program_events,
                        source_kind="HTML"
                    )
                )
                return
            except Exception as html_exc:
                logging.warning(
                    "HTML Cultura indisponível; acionando fallback XML/TXT | %s",
                    html_exc
                )

        try:
            events, grade_events, source_url = self._download_current_day_xml_fallback()
            signature = tuple(
                (e["start"], e["duration"], e["title"])
                for e in events
            )
            self.after(
                0,
                lambda: self._refresh_xml_success(
                    events, grade_events, signature, source_url,
                    reason=("CAMPO HTML VAZIO" if not html_url else "FALHA NO HTML")
                )
            )
        except Exception as exc:
            # Python remove a variável da exceção ao sair do bloco except.
            # Captura a mensagem agora para o callback assíncrono do Tkinter.
            error_message = str(exc)
            self.after(0, lambda msg=error_message: self._refresh_error(msg))

    def _refresh_success(self, events, metadata, signature, grade_events, program_events, source_kind="HTML"):
        """Aplica diretamente a grade HTML válida, sem projeção nem dupla confirmação."""
        self.grade_refresh_ok = True
        source_updated = metadata.get("updated", "--:--:--")
        source_modified = metadata.get("modified", "--:--:--")
        previous_signature = self.last_cultura_signature
        schedule_changed = previous_signature is not None and signature != previous_signature

        result = self._accept_or_stage_grade(
            events, grade_events, program_events, metadata
        )

        if program_events:
            self.program_events = list(program_events)
            save_program_events_file(self.program_events, source_updated)
            self.program_events_db = load_program_events_file()
            self.refresh_live_program_widgets()

        self.rebuild_combined_events()

        if self.live_resync_pending:
            self.live_suspended_keys.clear()
            self.live_resync_pending = False

        self.last_cultura_updated = source_updated
        self.last_cultura_modified = source_modified
        self.last_cultura_signature = signature
        self.refresh_in_progress = False

        try:
            poll = max(10, int(self.poll_var.get().strip()))
        except Exception:
            poll = POLL_SECONDS
        self.next_refresh_at = time.time() + poll

        local_now = datetime.now().strftime("%H:%M:%S")
        offset = self.grade_offset_seconds()
        self.cultura_updated_var.set(
            f"Consulta/ping Cultura: {datetime.now().strftime('%d/%m/%Y')} {source_updated}"
        )
        self.cultura_modified_var.set(
            f"Última modificação: {source_modified}"
        )
        self.cultura_sync_var.set(
            f"Sincronização: HTML OPERACIONAL às {local_now}"
        )
        self.cultura_status_var.set(
            f"Cultura: {len(events)} horários | FONTE: HTML | consulta {local_now} | OFFSET {offset:+d}s"
        )
        self.projection_status_var.set(
            "Fonte reserva: XML/TXT somente se HTML falhar"
        )

        logging.info(
            "GRADE HTML APLICADA | inserts=%s | modificacao=%s | mudou=%s",
            len(events), source_modified, schedule_changed
        )
        self.save_state()
        self.refresh_tree()

    def _refresh_xml_success(self, events, grade_events, signature, source_url, reason):
        """Substitui integralmente a grade Cultura por XML/TXT somente quando o HTML não é utilizável."""
        metadata = {"updated":"--:--:--", "modified":"--:--:--"}

        # XML é uma fonte alternativa completa; substitui a grade Cultura,
        # nunca é somado/misturado com o HTML anterior.
        self._promote_operational_grade(
            events, grade_events, [], signature, metadata
        )
        self.grade_refresh_ok = True
        self.last_cultura_updated = None
        self.last_cultura_modified = None
        self.last_cultura_signature = signature
        self.refresh_in_progress = False

        try:
            poll = max(10, int(self.poll_var.get().strip()))
        except Exception:
            poll = POLL_SECONDS
        self.next_refresh_at = time.time() + poll

        local_now = datetime.now().strftime("%H:%M:%S")
        ext = source_url.rsplit(".", 1)[-1].split("?", 1)[0].upper()
        self.cultura_updated_var.set(
            f"Consulta/ping Cultura: {local_now} | fallback {ext}"
        )
        self.cultura_modified_var.set(
            f"Última modificação: indisponível no fallback {ext}"
        )
        self.cultura_sync_var.set(
            f"Sincronização: FONTE {ext} (FALLBACK — {reason}) às {local_now}"
        )
        self.cultura_status_var.set(
            f"Cultura: {len(events)} horários | FONTE: {ext} (FALLBACK) | consulta {local_now} | OFFSET {self.grade_offset_seconds():+d}s"
        )
        logging.warning(
            "GRADE OPERACIONAL VIA FALLBACK | fonte=%s | motivo=%s | horarios=%s",
            source_url, reason, len(events)
        )
        self.save_state()
        self.refresh_tree()

    def _refresh_error(self, error):

        self.grade_refresh_ok = False
        if self.armed:
            self.auto_status_var.set("AUTOMÁTICO: SUSPENSO — FALHA DE ATUALIZAÇÃO")
        self.refresh_in_progress = False
        self.next_refresh_at = time.time() + 20

        self.cultura_status_var.set(
            "Cultura: ERRO na atualização"
        )
        if self.live_resync_pending:
            self.cultura_sync_var.set(
                "Sincronização: ERRO pós AO VIVO — automático permanece EM SUSPENSO"
            )
            self.live_status_var.set(
                "PÓS AO VIVO: aguardando atualização válida para liberar automático"
            )
        else:
            self.cultura_sync_var.set(
                "Sincronização: ERRO — mantendo a última grade válida"
            )
        logging.error("Falha ao atualizar Cultura | %s", error)

        messagebox.showerror(
            "TV Cultura",
            f"Não foi possível atualizar o HTML:\n\n{error}"
        )

    # ------------------------------------------------------------------------
    # AGENDA
    # ------------------------------------------------------------------------

    def event_key(self, event):
        return (
            datetime.now().strftime("%Y-%m-%d"),
            event.get("origin","CULTURA"),
            self.event_source_start(event),
            event.get("manual_break_id", event.get("avulso_id", event.get("title","")))
        )

    def event_state(self, event):
        if event.get("reference_only"):
            return "GRADE CULTURA"

        key = self.event_key(event)

        if key in self.executed:
            return "EXECUTADO"

        now_dt = datetime.now()
        now = now_dt.strftime("%H:%M:%S")

        if self.electoral_enabled_var.get():
            for start, end in self.electoral_windows():
                if self.validate_hms(start) and self.validate_hms(end):
                    if start <= event["start"] < end:
                        return "BLOQUEADO ELEITORAL"

        if event.get("origin") == "MANUAL":
            if event["start"] < now:
                return "AGUARDANDO BREAK"
            return "RESERVADO MANUAL"

        if key in self.live_suspended_keys:
            if self.live_resync_pending:
                return "SUSPENSO — RELOCALIZANDO"
            return "MANUAL DURANTE AO VIVO"

        # V1.34: durante um AO VIVO ativo, os eventos que pertencem à janela
        # prevista do programa deixam de ser automáticos e ficam disponíveis
        # ao operador. Mesmo após o horário previsto, não viram PASSOU.
        if self.live_active and self.live_planned_end:
            try:
                h, m, s = map(int, event["start"].split(":"))
                event_dt = now_dt.replace(hour=h, minute=m, second=s, microsecond=0)
                live_start = None
                if self.live_key and len(self.live_key) >= 3:
                    candidate_start = self.live_key[2]
                    if self.validate_hms(candidate_start):
                        live_start = self._today_dt(now_dt, self.grade_time(candidate_start) if self.live_key[1] == "CULTURA" else candidate_start)
                if live_start is None:
                    live_start = now_dt.replace(hour=0, minute=0, second=0, microsecond=0)
                if live_start <= event_dt < self.live_planned_end:
                    return "MANUAL DURANTE AO VIVO"
            except Exception:
                pass

        if event["start"] < now:
            return "PASSOU"

        if self.armed:
            return "ARMADO"

        return "AGUARDANDO"

    def next_pending_event(self, now=None):
        if now is None:
            now = datetime.now()

        current = now.strftime("%H:%M:%S")

        for event in self.events:
            if event.get("reference_only"):
                continue
            key = self.event_key(event)

            if key in self.executed:
                continue

            if self.electoral_enabled_var.get():
                blocked = False
                for start, end in self.electoral_windows():
                    if self.validate_hms(start) and self.validate_hms(end):
                        if start <= event["start"] < end:
                            blocked = True
                            break
                if blocked:
                    continue

            if event["start"] >= current:
                return event

        return None

    def update_next_event_display(self, now=None):
        if now is None:
            now = datetime.now()

        event = self.next_pending_event(now)

        if not event:
            self.next_event_var.set("Próximo: --")
            self.countdown_var.set("Faltam: --")
            return

        h, m, s = map(int, event["start"].split(":"))
        target = now.replace(hour=h, minute=m, second=s, microsecond=0)

        delta = int((target - now).total_seconds())

        if delta < 0:
            delta = 0

        hh = delta // 3600
        mm = (delta % 3600) // 60
        ss = delta % 60

        media = self.media_for_event(event)
        media_name = os.path.basename(media) if media else "(sem mídia)"

        self.next_event_var.set(
            f"Próximo: {event['start']} | {media_name}"
        )

        self.countdown_var.set(
            f"Faltam: {hh:02d}:{mm:02d}:{ss:02d}"
        )

    def refresh_tree(self):
        selected_starts = set()

        for iid in self.tree.selection():
            try:
                idx = int(iid)
                selected_starts.add(
                    self.events[idx]["start"]
                )
            except Exception:
                pass

        self.tree.delete(
            *self.tree.get_children()
        )

        for index, event in enumerate(self.events):
            media = self.media_for_event(event)

            if media:
                display_media = os.path.basename(media)
                skip_enabled, skip_seconds = self.slate_skip_for_event(event)
                if skip_enabled:
                    display_media += f"  [PULA {skip_seconds:g}s]"
            else:
                display_media = "(sem mídia)"

            tags = ()
            state = self.event_state(event)
            if event.get("origin") == "MANUAL":
                rem=float(event.get("block_remaining",0) or 0)
                state = (f"SOBRA {rem:.1f}s" if rem >= 0 else f"EXCESSO {abs(rem):.1f}s")
            elif event.get("link_orphan"):
                state = "VÍNCULO SEM ANTERIOR"

            next_event = self.next_pending_event()
            if next_event and event["start"] == next_event["start"]:
                tags = ("next",)
            elif state == "EXECUTADO":
                tags = ("executed",)
            elif state == "MANUAL DURANTE AO VIVO":
                tags = ("manual",)
            elif event.get("origin") == "MANUAL":
                tags = ("manual",)

            self.tree.insert(
                "",
                "end",
                iid=str(index),
                values=(
                    event["start"], event.get("origin","CULTURA"), (f"{float(event.get('duration',0) or 0):.1f}s" if event.get("origin") in ("AVULSO","MANUAL") else event["duration"]),
                    (f"{self.media_duration(media):.1f}s" if self.media_duration(media) is not None else "--"),
                    event.get("calculated_end") or self._add_hms(event["start"], (self.media_duration(media) if ((event.get("integral",False) or self.integral_overrides.get(self.event_source_start(event),False)) and self.media_duration(media) and self.media_duration(media)>event.get("duration",0)) else (event.get("duration",0) or self.media_duration(media) or 0))),
                    (event["title"] + (" | VINCULADO" if event.get("linked") else "") + (f" | {event.get('electoral_cargo','')} - {event.get('electoral_agremiacao','')} [{event.get('electoral_mode','')}]" if event.get("electoral_local") else "")), display_media, state
                ),
                tags=tags
            )

        for index, event in enumerate(self.events):
            if event["start"] in selected_starts:
                try:
                    self.tree.selection_add(str(index))
                except tk.TclError:
                    pass

    def select_all(self):
        items = self.tree.get_children()
        self.tree.selection_set(items)

    def clear_selection(self):
        self.tree.selection_remove(self.tree.selection())

    def auto_startup_connect_and_arm(self):
        """Na abertura: testa CasparCG, conecta ATEM e arma sem exigir clique do operador."""
        if self.armed:
            return
        self.auto_status_var.set("AUTOMÁTICO: INICIALIZANDO...")
        self.caspar_status_var.set("CasparCG: conectando...")
        self.atem_status_var.set("ATEM: conectando...")

        def worker():
            try:
                response = self.amcp().send("VERSION SERVER")
                if not response:
                    raise RuntimeError("CasparCG não respondeu ao VERSION SERVER")
                self.ensure_atem()
            except Exception:
                logging.exception("Inicialização automática falhou")
                def fail():
                    self.armed = False
                    self.auto_status_var.set("AUTOMÁTICO: SUSPENSO — FALHA DE CONEXÃO")
                    self.arm_button.configure(text="TENTAR ARMAR NOVAMENTE")
                self.after(0, fail)
                return

            def ok():
                self.armed = True
                self.auto_status_var.set("AUTOMÁTICO: ARMADO" if self._grade_auto_allowed() else "AUTOMÁTICO: SUSPENSO — AGUARDANDO GRADE CONFIRMADA")
                self.arm_button.configure(text="DESARMAR AUTOMÁTICO")
                self.caspar_status_var.set("CasparCG: conectado")
                self.atem_status_var.set("ATEM: conectado")
                logging.info("Inicialização automática OK | CasparCG + ATEM | AUTOMÁTICO ARMADO")
                self.refresh_tree()
            self.after(0, ok)

        threading.Thread(target=worker, daemon=True).start()

    def toggle_armed(self):
        if self.armed:
            self.armed = False
            self.auto_status_var.set(
                "AUTOMÁTICO: DESARMADO"
            )
            self.arm_button.configure(
                text="ARMAR AUTOMÁTICO"
            )
            logging.info("Automático DESARMADO.")
            self.refresh_tree()
            return

        if not self._next_default_electoral_media(False):
            answer = messagebox.askyesno(
                "Armar automático",
                "Não existe mídia padrão definida.\n\n"
                "Somente horários com mídia aplicada individualmente "
                "poderão ser executados.\n\n"
                "Deseja armar mesmo assim?"
            )

            if not answer:
                return

        try:
            response = self.amcp().send(
                "VERSION SERVER"
            )
        except Exception as exc:
            messagebox.showerror(
                "Armar automático",
                "O CasparCG não está acessível.\n\n"
                f"{exc}"
            )
            return

        if not response:
            messagebox.showerror(
                "Armar automático",
                "O CasparCG não respondeu ao teste AMCP."
            )
            return

        try:
            self.ensure_atem()
        except Exception as exc:
            messagebox.showerror(
                "Armar automático",
                "O ATEM não está acessível. O automático não será armado.\n\n"
                f"{exc}"
            )
            return

        self.armed = True
        logging.info("Automático ARMADO.")
        self.auto_status_var.set(
            "AUTOMÁTICO: ARMADO"
        )
        self.arm_button.configure(
            text="DESARMAR AUTOMÁTICO"
        )
        self.caspar_status_var.set(
            "CasparCG: conectado"
        )
        self.refresh_tree()

    def _clock_loop(self):
        now = datetime.now()
        self.clock_var.set(now.strftime("%H:%M:%S"))
        self.handle_day_rollover(now)
        self.update_next_event_display(now)
        self.update_electoral_status(now)

        # Detecta/acompanha programas AO VIVO. O horário final gera aviso, não corte.
        self.update_live_control(now)

        # Detecta transição eleitoral e garante retorno explícito à cabeça de rede.
        self.handle_electoral_transition(now)

        # Durante a janela protegida, HDMI2/TVE tem prioridade absoluta.
        self.enforce_electoral_source(now)

        # V1.36.6 — Logo MP1 via DSK1: usa a LINHA ATUAL da grade integral; +3s após início e -5s antes do próximo evento/fim.
        self.update_logo_mp1(now)

        # Abertura/encerramento eleitoral opcionais.
        if self.armed:
            self.handle_electoral_boundaries(now)

        # Atualização automática do HTML.
        if (
            not self.refresh_in_progress
            and time.time() >= self.next_refresh_at
        ):
            self.refresh_now()

        # Verifica agenda 5 vezes por segundo.
        if self.armed:
            self._check_schedule(now)

        self.after(200, self._clock_loop)

    def _event_inside_local_block(self, event):
        """Retorna o bloco que cobre o horário do evento, se houver."""
        if event.get("origin") == "MANUAL":
            return None
        sec=self._hms_seconds(event.get("start",""))
        if sec is None:
            return None
        wd=datetime.now().weekday(); names=["SEG","TER","QUA","QUI","SEX","SAB","DOM"]
        for b in self.manual_breaks:
            if not b.get("enabled",True) or names[wd] not in b.get("days",names):
                continue
            st=b.get("time","")
            a=self._hms_seconds(st)
            if a is None:
                continue
            try: dur=float(b.get("slot",0) or 0)
            except Exception: dur=0.0
            if a <= sec < a + dur:
                return b
        return None

    def _linked_block_worker(self, rows, block_event):
        """Executa mídias de um BLOCO em sequência contínua no SDI8.

        Não retorna à rede entre as peças. Se houver SOBRA no bloco, mantém o
        último frame até o limite reservado; se houver EXCESSO, toca a sequência
        completa e registra o excesso na interface/log.
        """
        self.local_insertion_active=True
        self.break_playlist_active=True
        try:
            if self.is_electoral_lock():
                return
            rows=sorted(rows,key=lambda item:item[0].get("start","00:00:00"))
            if not rows:
                return
            block_duration=float(block_event.get("duration",0) or 0)
            planned=sum(float(e.get("duration",0) or 0) for e,_m in rows)
            logging.warning("BLOCO LOCAL INICIADO | inicio=%s | reservado=%.3f | midias=%.3f | itens=%s",
                            block_event.get("start"),block_duration,planned,len(rows))

            first_event,first_media=rows[0]
            skip_enabled,skip_seconds=self.slate_skip_for_event(first_event)
            seek_frames=self.skip_seconds_to_frames(skip_seconds) if skip_enabled else 0
            response=self.send_play(first_media,seek_frames=seek_frames)
            logging.info("BLOCO item PLAY pronto | item=1 | midia=%s | resposta=%s",first_media,response)
            time.sleep(CASPAR_PREROLL_SECONDS)
            if self.is_electoral_lock():
                try:self.amcp().send(f"STOP {self.target()}")
                except Exception:pass
                self.restore_base_source(); return
            if not self.atem_set_program(self.atem_caspar_source()):
                raise RuntimeError("Não foi possível colocar SDI 8 no PROGRAM.")

            block_started=time.monotonic()
            for pos,(event,media) in enumerate(rows,start=1):
                if pos>1:
                    skip_enabled,skip_seconds=self.slate_skip_for_event(event)
                    seek_frames=self.skip_seconds_to_frames(skip_seconds) if skip_enabled else 0
                    response=self.send_play(media,seek_frames=seek_frames)
                    logging.info("BLOCO item PLAY | item=%s/%s | midia=%s | resposta=%s",pos,len(rows),media,response)
                duration=float(event.get("duration",0) or 0)
                self.local_insertion_until=time.time()+duration
                self.after(0,lambda p=pos,n=len(rows),mn=os.path.basename(media),d=duration:
                           self.break_playlist_status_var.set(f"🔴 BLOCO LOCAL {p}/{n} | {mn} | {d:.1f}s"))
                end_at=time.monotonic()+duration
                while time.monotonic()<end_at:
                    if self.is_electoral_lock():
                        raise RuntimeError("Bloco interrompido por janela eleitoral.")
                    time.sleep(0.03)
                self.executed.add(self.event_key(event))
                self.after(0,self.refresh_tree)

            elapsed=time.monotonic()-block_started
            remaining=block_duration-elapsed
            if remaining>0:
                self.after(0,lambda r=remaining:self.break_playlist_status_var.set(f"🔴 BLOCO LOCAL | sobra {r:.1f}s — mantendo último frame"))
                hold_end=time.monotonic()+remaining
                while time.monotonic()<hold_end:
                    if self.is_electoral_lock(): break
                    time.sleep(0.03)
            self.executed.add(self.event_key(block_event))
            self.restore_base_source()
            try:self.amcp().send(f"STOP {self.target()}")
            except Exception:logging.exception("Falha STOP Caspar após BLOCO LOCAL")
            logging.warning("BLOCO LOCAL FINALIZADO | inicio=%s | decorrido=%.3f | reservado=%.3f",
                            block_event.get("start"),time.monotonic()-block_started,block_duration)
            self.after(0,lambda:self.break_playlist_status_var.set("BLOCO LOCAL: finalizado / rede restaurada"))
        except Exception as exc:
            logging.exception("Falha no BLOCO LOCAL")
            try:self.restore_base_source(); self.amcp().send(f"STOP {self.target()}")
            except Exception:pass
            self.after(0,lambda e=str(exc):messagebox.showerror("BLOCO LOCAL",e))
        finally:
            self.local_insertion_active=False
            self.local_insertion_until=None
            self.break_playlist_active=False

    def _check_schedule(self, now):
        if self.local_insertion_active:
            return

        if self.live_resync_pending:
            return

        if self.is_electoral_lock(now):
            return

        if self.live_active:
            self._mark_live_suspended_events(now)
            return

        current_seconds = now.hour * 3600 + now.minute * 60 + now.second

        for event in self.events:
            # Linhas da grade integral existem apenas para referência visual e
            # para outras automações de estado; nunca são disparadas como insert.
            if event.get("reference_only"):
                continue
            if event.get("origin") == "CULTURA":
                # Segurança: nunca dispara um horário Cultura antigo enquanto a
                # nova grade está pendente ou após falha de atualização.
                if not self.grade_refresh_ok or not self._grade_auto_allowed():
                    continue
                raw_time = event.get("published_start", event.get("start",""))
                if not self._is_operational_start(raw_time):
                    continue
            # BLOCO/JANELA é contêiner operacional; nunca dispara sozinho.
            if event.get("origin") == "MANUAL":
                continue

            key=self.event_key(event)
            if key in self.executed:
                continue

            # O BLOCO abre espaço na grade: um insert CULTURA comum que caia
            # dentro da janela local não deve entrar por cima da cobertura local.
            # Eventos eleitorais locais continuam sob a lógica eleitoral própria.
            block_cover=self._event_inside_local_block(event)
            if block_cover and event.get("origin")=="CULTURA" and not event.get("electoral_local"):
                self.executed.add(key)
                logging.info("Insert CULTURA suprimido por BLOCO LOCAL | horario=%s | evento=%s | bloco=%s",
                             event.get("start"),event.get("title"),block_cover.get("title"))
                continue

            if self.electoral_enabled_var.get() and now.weekday() != 6:
                blocked_event=False
                for start_h,end_h in self.electoral_windows():
                    if self.validate_hms(start_h) and self.validate_hms(end_h) and start_h <= event["start"] < end_h:
                        blocked_event=True; break
                if blocked_event:
                    self.executed.add(key)
                    logging.info("Inserção bloqueada pelo período eleitoral | horario=%s | evento=%s",event["start"],event["title"])
                    continue

            h,m,s=map(int,event["start"].split(":")); target_seconds=h*3600+m*60+s
            delta=current_seconds-target_seconds
            if delta<0: continue
            if delta>LATE_TOLERANCE_SECONDS: continue

            media=self.media_for_event(event)
            if not media:
                continue

            # AVULSO pertencente a bloco: o primeiro item dispara a sequência
            # inteira sem cortes de volta à rede entre as mídias.
            block_id=event.get("block_id") if event.get("origin")=="AVULSO" else None
            if block_id not in (None,"",0,"0"):
                block_event=next((e for e in self.events if e.get("origin")=="MANUAL" and str(e.get("manual_break_id"))==str(block_id)),None)
                rows=[]
                for e in self.events:
                    if e.get("origin")=="AVULSO" and str(e.get("block_id"))==str(block_id) and self.event_key(e) not in self.executed:
                        mpath=self.media_for_event(e)
                        if mpath: rows.append((e,mpath))
                rows.sort(key=lambda item:item[0].get("start","00:00:00"))
                if rows and rows[0][0] is event and block_event:
                    self.local_insertion_active=True
                    self.break_playlist_active=True
                    threading.Thread(target=self._linked_block_worker,args=(rows,block_event),daemon=True).start()
                    return
                # Se não é o primeiro pendente, aguarda o primeiro cuidar da cadeia.
                continue

            # Disparo automático unitário tradicional.
            self.executed.add(key)
            logging.info("Disparo automático | horario=%s | midia=%s",event["start"],media)
            self.refresh_tree()
            threading.Thread(target=self._local_playout_worker,args=(event,media,False),daemon=True).start()
            return

    def _play_worker(self, event, media):
        try:
            response = self.send_play(media)

            logging.info(
                "EXECUTADO com sucesso | horario=%s | resposta=%s",
                event["start"],
                response
            )

            self.after(
                0,
                lambda: self.caspar_status_var.set(
                    f"CasparCG: EXECUTADO {event['start']}"
                )
            )

        except Exception as exc:
            # Em falha de AMCP, liberamos o evento para nova tentativa
            # dentro da pequena janela de tolerância.
            self.executed.discard(
                self.event_key(event)
            )
            logging.exception(
                "Falha no disparo automático | horario=%s | midia=%s",
                event["start"],
                media
            )

            self.after(
                0,
                lambda: messagebox.showerror(
                    "Falha no disparo automático",
                    f"Horário: {event['start']}\n\n{exc}"
                )
            )


if __name__ == "__main__":
    LOG_FILE = setup_logging()
    if not run_as_admin():
        sys.exit(0)

    app = SchedulerApp()
    app.mainloop()