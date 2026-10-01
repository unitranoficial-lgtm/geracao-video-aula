#!/usr/bin/env python3
"""
Google Flow automation — Etapa 2 do workflow de vídeo-aula Unitran
Gera imagens e vídeos no Flow a partir do roteiro.json

Uso básico:
  python flow_automation.py --roteiro output/ibs_e_cbs_para_o_transportador/roteiro.json \\
                             --project-id c8026a66-92c0-4ed8-9347-3dd0bd0e3e3d

Flags adicionais:
  --profile "Profile 3"      Perfil Chrome com a conta Google (detecta automaticamente se omitido)
  --apenas-videos            Pular geração de imagens (usar as que já estão na galeria)
  --pausar-imagens           Parar para confirmação manual após cada imagem
  --headless                 Rodar sem janela visível (não recomendado para uso inicial)

Pré-requisitos:
  playwright install chromium  (ou usar Chrome instalado com --channel chrome)
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import struct
import zlib
from pathlib import Path
from playwright.sync_api import sync_playwright, Page, BrowserContext, TimeoutError as PlaywrightTimeout

# Força UTF-8 no stdout para suportar ✓, ⚠ etc. no console Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ────────────────────────────────────────────────────────────────────────────
# Configurações (ajustar conforme necessário)
# ────────────────────────────────────────────────────────────────────────────

CHROME_USER_DATA = r"C:\Users\UNITRAN\AppData\Local\Google\Chrome\User Data"
CHROME_PROFILE = "Profile 3"          # Perfil com conta unitranoficial@gmail.com

FLOW_BASE_URL = "https://flow.google.com"
ACCOUNT_SLOT = "u/0"                  # /u/0/ = unitranoficial@gmail.com

# Perfil Chrome persistente dedicado ao script (não o perfil real do usuário)
# Fica na mesma pasta do script; o Google mantém a sessão entre execuções.
FLOW_PROFILE_DIR = Path(__file__).parent / "flow_chrome_profile"

# Mantido para compatibilidade — não mais usado na autenticação principal
SESSION_FILE = Path(__file__).parent / "flow_session.json"

TIMEOUT_GERACAO_MS = 5 * 60 * 1000   # 5 min de espera por geração de imagem
PAUSA_ENTRE_SUBMISSOES_MS = 2000      # pausa entre submissões de vídeo
ASPECT_RATIO = "16:9"                  # sobrescrito pelo entrypoint vertical

# ────────────────────────────────────────────────────────────────────────────
# Utilitários gerais
# ────────────────────────────────────────────────────────────────────────────

def log(msg: str, end: str = "\n"):
    print(msg, end=end, flush=True)


def chrome_esta_rodando() -> bool:
    result = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq chrome.exe", "/FO", "CSV"],
        capture_output=True, text=True
    )
    return "chrome.exe" in result.stdout


def _copiar_arquivo_com_share(src: Path, dst: Path):
    """
    Copia um arquivo mesmo que esteja aberto por outro processo,
    usando Win32 CreateFileW com FILE_SHARE_READ|WRITE|DELETE.
    Necessário para os arquivos SQLite do Chrome (Cookies, Sessions…)
    que ficam locked enquanto o browser está aberto.
    """
    import ctypes
    import ctypes.wintypes as wt

    GENERIC_READ = 0x80000000
    FILE_SHARE_ALL = 0x7          # READ | WRITE | DELETE
    OPEN_EXISTING = 3
    FILE_ATTRIBUTE_NORMAL = 0x80
    INVALID = ctypes.c_void_p(-1).value

    k32 = ctypes.windll.kernel32
    hsrc = k32.CreateFileW(
        str(src), GENERIC_READ, FILE_SHARE_ALL,
        None, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, None,
    )
    if hsrc == INVALID:
        raise OSError(f"CreateFileW falhou para {src.name}: erro {k32.GetLastError()}")

    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        CHUNK = 1024 * 1024
        buf = ctypes.create_string_buffer(CHUNK)
        read = wt.DWORD(0)
        with open(dst, "wb") as f:
            while True:
                ok = k32.ReadFile(hsrc, buf, CHUNK, ctypes.byref(read), None)
                if not ok or read.value == 0:
                    break
                f.write(buf.raw[: read.value])
    finally:
        k32.CloseHandle(hsrc)


def _copiar_dir_recursivo(src: Path, dst: Path, ignorar: set[str]):
    """Copia src→dst recursivamente; usa CreateFileW para arquivos locked."""
    dst.mkdir(parents=True, exist_ok=True)
    for item in src.iterdir():
        if item.name in ignorar:
            continue
        dest = dst / item.name
        if item.is_dir():
            _copiar_dir_recursivo(item, dest, ignorar)
        else:
            try:
                shutil.copy2(item, dest)
            except (PermissionError, OSError):
                try:
                    _copiar_arquivo_com_share(item, dest)
                except Exception as e:
                    log(f"  ⚠ Pulando {item.name}: {e}")


def copiar_perfil_temp(user_data: str, profile: str) -> tuple[str, str]:
    """
    Copia o perfil Chrome para um dir temporário sem fechar o Chrome.
    Usa Win32 CreateFileW com shared access para arquivos locked (Cookies, Sessions…).
    Retorna (temp_user_data_dir, nome_do_perfil_dentro_dele).
    """
    src = Path(user_data) / profile
    temp_base = Path(tempfile.mkdtemp(prefix="flow_pw_"))
    dst_profile = "Default"
    dst = temp_base / dst_profile

    log(f"Chrome aberto — copiando perfil para temp: {temp_base}")
    ignorar = {"Cache", "Code Cache", "GPUCache", "ShaderCache", "DawnCache"}
    _copiar_dir_recursivo(src, dst, ignorar)
    # Cookies e tokens recentes usam a chave criptográfica do arquivo Local
    # State na raiz do user-data-dir. Sem ele a cópia abre, mas perde o login.
    local_state_src = Path(user_data) / "Local State"
    if local_state_src.exists():
        try:
            shutil.copy2(local_state_src, temp_base / "Local State")
        except (PermissionError, OSError):
            _copiar_arquivo_com_share(local_state_src, temp_base / "Local State")
    log(f"  Perfil copiado ✓")
    return str(temp_base), dst_profile


def corrigir_exit_type(user_data: str, profile: str):
    """Define exit_type=Normal no Preferences para evitar dialog 'Restaurar páginas?'."""
    prefs_path = Path(user_data) / profile / "Preferences"
    if not prefs_path.exists():
        return
    try:
        with open(prefs_path, encoding="utf-8-sig") as f:
            data = json.load(f)
        data.setdefault("profile", {})["exit_type"] = "Normal"
        data["profile"]["exited_cleanly"] = True
        with open(prefs_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    except Exception as e:
        log(f"  ⚠ Não foi possível corrigir exit_type: {e}")


CDP_DEBUG_PORT = 9222


CHROME_EXE = r"C:\Program Files\Google\Chrome\Application\chrome.exe"


def _launch_args():
    return [
        "--disable-blink-features=AutomationControlled",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-session-crashed-bubble",
    ]


def _matar_chrome_residual():
    """Encerra processos Chrome que ainda seguram o perfil dedicado do script."""
    try:
        profile_path = str(FLOW_PROFILE_DIR).lower()
        result = subprocess.run(
            ["wmic", "process", "where",
             "name='chrome.exe'", "get", "processid,commandline", "/format:csv"],
            capture_output=True, text=True, timeout=10
        )
        for line in result.stdout.splitlines():
            if profile_path.replace("\\", "/") in line.lower().replace("\\", "/"):
                parts = line.split(",")
                if len(parts) >= 2:
                    try:
                        pid = parts[-1].strip()
                        if pid.isdigit():
                            subprocess.run(["taskkill", "/F", "/PID", pid],
                                           capture_output=True, timeout=5)
                            log(f"  [init] Chrome residual PID {pid} encerrado")
                    except Exception:
                        pass
    except Exception:
        pass


def _configurar_chrome_download_dir(pasta_saida: Path):
    """Escreve nas preferências do perfil Chrome para que downloads
    vão direto para pasta_saida sem diálogo nem intercepção do Playwright."""
    import json as _json
    prefs_path = FLOW_PROFILE_DIR / "Default" / "Preferences"
    if not prefs_path.exists():
        log(f"  ⚠ Chrome Preferences não encontrado em {prefs_path}")
        return
    try:
        prefs = _json.loads(prefs_path.read_text(encoding="utf-8"))
        dl = prefs.setdefault("download", {})
        dl["default_directory"] = str(pasta_saida.absolute())
        dl["prompt_for_download"] = False
        dl["directory_upgrade"] = True
        prefs_path.write_text(_json.dumps(prefs, ensure_ascii=False), encoding="utf-8")
        log(f"  Chrome download dir → {pasta_saida.absolute()}")
    except Exception as e:
        log(f"  ⚠ Não foi possível configurar download dir: {e}")


def _abrir_contexto_persistente(p, headless: bool = False):
    """Abre contexto persistente com o perfil dedicado do script."""
    _matar_chrome_residual()
    FLOW_PROFILE_DIR.mkdir(parents=True, exist_ok=True)

    # Depois do primeiro setup, abrir um contexto limpo a partir do
    # storage_state completo (cookies + localStorage). O login atual do Google
    # depende de ambos; restaurar apenas cookies em um perfil persistente não é
    # suficiente e fazia a conta parecer desconectada ao reabrir o script.
    if SESSION_FILE.exists():
        try:
            browser = p.chromium.launch(
                channel="chrome",
                headless=headless,
                slow_mo=50,
                args=_launch_args(),
            )
            context = browser.new_context(
                storage_state=str(SESSION_FILE),
                viewport={"width": 1440, "height": 900},
                accept_downloads=True,
            )
            log(f"  Sessão restaurada do storage_state completo")
            return context
        except Exception as error:
            log(f"  ⚠ Falha ao abrir storage_state completo; usando perfil: {error}")

    context = p.chromium.launch_persistent_context(
        user_data_dir=str(FLOW_PROFILE_DIR),
        channel="chrome",
        headless=headless,
        slow_mo=50,
        viewport={"width": 1440, "height": 900},
        accept_downloads=True,
        args=_launch_args(),
    )
    # Cookies de sessão do Google podem ser removidos quando o Chrome
    # automatizado fecha, mesmo usando um user-data-dir persistente. Restaurar
    # o storage_state salvo pelo setup mantém esses cookies entre execuções.
    if SESSION_FILE.exists():
        try:
            state = json.loads(SESSION_FILE.read_text(encoding="utf-8"))
            cookies = state.get("cookies", [])
            if cookies:
                context.add_cookies(cookies)
                log(f"  Sessão restaurada do storage_state ({len(cookies)} cookies)")
        except Exception as error:
            log(f"  ⚠ Não foi possível restaurar storage_state: {error}")
    # O perfil dedicado e persistente é a fonte primária da autenticação.
    # Importar automaticamente um bundle externo pode sobrescrever cookies que
    # acabaram de ser renovados por --setup-session e desconectar a conta.
    # A recuperação por bundle fica disponível apenas por opção explícita.
    bundle_path = (
        Path(__file__).parent.parent
        / "flow-agent-api-test" / "flow-agent" / "cookies"
        / "account_c34e9d938fa3.json"
    )
    importar_bundle = os.environ.get("FLOW_IMPORT_COOKIE_BUNDLE", "").strip() == "1"
    if importar_bundle and bundle_path.exists():
        try:
            bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
            cookies = []
            for source in bundle.get("cookies", []):
                cookie = {
                    key: source[key]
                    for key in ("name", "value", "domain", "path")
                    if key in source
                }
                if source.get("expirationDate"):
                    cookie["expires"] = source["expirationDate"]
                cookie["httpOnly"] = bool(source.get("httpOnly", False))
                cookie["secure"] = bool(source.get("secure", False))
                same_site = str(source.get("sameSite", "Lax")).capitalize()
                cookie["sameSite"] = same_site if same_site in {"Strict", "Lax", "None"} else "Lax"
                cookies.append(cookie)
            context.add_cookies(cookies)
            log(f"  Sessão atualizada pelo bundle autenticado ({len(cookies)} cookies)")
        except Exception as error:
            log(f"  ⚠ Não foi possível importar o bundle de sessão: {error}")
    return context


def _abrir_contexto_chrome_logado(p, profile: str, headless: bool = False):
    """Copia o perfil real e abre a cópia autenticada para automação.

    Chrome 136+ proíbe remote debugging no diretório padrão. A cópia temporária
    é a forma suportada de preservar o perfil original e ainda usar Playwright.
    """
    log(f"Copiando a sessão autenticada do Chrome ({profile})...")
    try:
        temp_user_data, temp_profile = copiar_perfil_temp(CHROME_USER_DATA, profile)
        corrigir_exit_type(temp_user_data, temp_profile)
        return p.chromium.launch_persistent_context(
            user_data_dir=temp_user_data,
            channel="chrome",
            headless=headless,
            slow_mo=50,
            viewport={"width": 1440, "height": 900},
            accept_downloads=True,
            args=[f"--profile-directory={temp_profile}", *_launch_args()],
        )
    except Exception as error:
        raise RuntimeError(
            "Não foi possível copiar/abrir o perfil Chrome autenticado. Feche "
            "todas as janelas do Chrome e tente novamente."
        ) from error


def _flow_esta_autenticado(page: Page, timeout: int = 20000) -> bool:
    """Valida login pela interface atual, com ou sem /u/0 na URL."""
    if "/about" in page.url or "accounts.google.com" in page.url:
        return False
    try:
        page.locator(
            'button:has-text("New project"), button:has-text("Novo projeto"), '
            '[aria-label="New project"], [aria-label="Novo projeto"], '
            'button[aria-label="Detalhes da conta"]'
        ).first.wait_for(state="visible", timeout=timeout)
        return True
    except Exception:
        if "/project/" in page.url:
            for rotulo in ("Todas as mídias", "All media", "Vídeos", "Videos"):
                try:
                    if page.get_by_text(rotulo, exact=True).first.is_visible(timeout=1000):
                        return True
                except Exception:
                    continue
        return False


def setup_session(p, after_login=None):
    """Abre Chrome com perfil persistente dedicado e aguarda login manual.

    Após o login, o perfil fica salvo em flow_chrome_profile/ e as execuções
    futuras reutilizam a sessão sem novo login (enquanto o Google não expirar).
    """
    log("=== Configurar Sessão do Google Flow ===\n")
    log(f"Perfil: {FLOW_PROFILE_DIR}")
    log("Uma janela do Chrome vai abrir. Faça login com unitranoficial@gmail.com.\n")

    context = _abrir_contexto_persistente(p, headless=False)
    page = context.pages[0] if context.pages else context.new_page()

    try:
        page.goto("https://flow.google.com/", wait_until="domcontentloaded", timeout=60000)
    except Exception:
        pass

    # Conduzir automaticamente a landing e o seletor de contas até a etapa
    # que realmente exige intervenção humana (senha/2FA).
    if "/about" in page.url:
        try:
            page.get_by_role("button", name=re.compile(r"Crie com o Google Flow", re.I)).first.click(timeout=10000)
            page.wait_for_timeout(3000)
        except Exception:
            pass
    if "accounts.google.com" in page.url:
        try:
            page.get_by_text("unitranoficial@gmail.com", exact=True).first.click(timeout=10000)
            page.wait_for_timeout(3000)
        except Exception:
            pass
    try:
        page.bring_to_front()
    except Exception:
        pass

    def _pagina_flow_autenticada():
        # O login do Google pode concluir em uma nova aba. Sempre procurar a
        # aba autenticada mais recente, em vez de observar apenas a aba inicial.
        for candidate in reversed(context.pages):
            try:
                if _flow_esta_autenticado(candidate, timeout=1000):
                    return candidate
            except Exception:
                continue
        return None

    pagina_autenticada = _pagina_flow_autenticada()
    if pagina_autenticada is None:
        log("Janela aberta → faça login com unitranoficial@gmail.com.")
        log("Aguardando o painel autenticado do Flow... (até 5 minutos)")
        limite = time.time() + 300
        while time.time() < limite:
            pagina_autenticada = _pagina_flow_autenticada()
            if pagina_autenticada is not None:
                page = pagina_autenticada
                break
            page.wait_for_timeout(1000)
    else:
        page = pagina_autenticada

    url_atual = page.url
    log(f"  URL final: {url_atual}")

    # O Flow novo usa a raiz https://flow.google.com/ mesmo autenticado.
    # Só considerar logout quando houver redirecionamento explícito para a
    # landing page ou para o domínio de login do Google.
    pagina_autenticada = _pagina_flow_autenticada()
    if pagina_autenticada is None:
        log("\nERRO: não autenticado no Flow.")
        log("  Certifique-se de ter feito login e tente novamente.")
        context.close()
        sys.exit(1)
    page = pagina_autenticada

    log(f"  Autenticado ✓ — título: {page.title()}")

    # Salvar também cookies de sessão, que não sobrevivem necessariamente ao
    # fechamento do Chrome mesmo dentro de um perfil persistente.
    context.storage_state(path=str(SESSION_FILE))
    log(f"  Estado autenticado salvo em {SESSION_FILE.name} ✓")

    # Algumas versões recentes do Chrome/Google invalidam a sessão do perfil
    # automatizado logo depois que a janela é fechada. Permitir que a operação
    # pendente continue no mesmo contexto autenticado evita um novo login e
    # torna a retomada de downloads confiável.
    if after_login is not None:
        after_login(page, context)

    context.close()
    log(f"\nPerfil salvo em: {FLOW_PROFILE_DIR} ✓")
    log("Nas próximas execuções não precisa fazer login novamente.\n")
    log("Agora rode:")
    log("  python flow_automation.py --roteiro output/seguros_obrigatorios_trc/roteiro.json --project-id 589c1ebf-4d13-4f47-9076-2a60e64328c5")


def conectar_via_cdp(p) -> "BrowserContext | None":
    """Tenta conectar ao Chrome em execução via porta de debug."""
    import urllib.request
    try:
        urllib.request.urlopen(f"http://localhost:{CDP_DEBUG_PORT}/json/version", timeout=2)
    except Exception:
        return None
    try:
        browser = p.chromium.connect_over_cdp(f"http://localhost:{CDP_DEBUG_PORT}")
        if browser.contexts:
            log(f"  Conectado ao Chrome via CDP (porta {CDP_DEBUG_PORT}) ✓")
            return browser.contexts[0]
        log(f"  Conectado via CDP mas sem contexto existente — usando novo")
        return browser.new_context()
    except Exception as e:
        log(f"  ⚠ Falha ao conectar via CDP: {e}")
        return None


def esperar_rede(page: Page, timeout: int = 15000):
    try:
        page.wait_for_load_state("networkidle", timeout=timeout)
    except PlaywrightTimeout:
        pass  # continuar mesmo que a rede não fique totalmente quieta


def colar_texto(page: Page, texto: str):
    """Cola texto via clipboard — muito mais rápido que digitação caractere a caractere."""
    page.evaluate(f"navigator.clipboard.writeText({json.dumps(texto)})")
    page.keyboard.press("Control+v")


def preencher_contenteditable(page: Page, texto: str):
    """Preenche o campo de prompt principal (div contenteditable)."""
    el = page.locator('div[contenteditable="true"]').first
    el.click()
    page.keyboard.press("Control+a")
    page.keyboard.press("Delete")
    # Usar clipboard para evitar lentidão de digitação
    page.evaluate(f"navigator.clipboard.writeText({json.dumps(texto)})")
    page.keyboard.press("Control+v")
    page.wait_for_timeout(300)


# ────────────────────────────────────────────────────────────────────────────
# Navegação
# ────────────────────────────────────────────────────────────────────────────

def criar_projeto_automatico(page: Page) -> str:
    """
    Navega para o Flow, cria um novo projeto clicando em 'Novo projeto'
    e retorna o project_id extraído da URL.
    """
    log("Nenhum project-id fornecido — criando novo projeto automaticamente...")
    try:
        page.goto(f"{FLOW_BASE_URL}/{ACCOUNT_SLOT}/", wait_until="domcontentloaded", timeout=60000)
    except PlaywrightTimeout:
        pass
    page.wait_for_timeout(2000)

    # Desde a atualização de setembro/2026, a área autenticada também pode
    # usar a raiz flow.google.com sem /u/0. Não confundir essa URL com logout.
    if "/about" in page.url or "accounts.google.com" in page.url:
        raise RuntimeError("Sessão não autenticada — rode --setup-session primeiro.")

    # Confirma a sessão pela presença do comando de criar projeto. Se a página
    # ainda estiver carregando, aguarda antes de concluir que houve logout.
    try:
        page.locator(
            'button:has-text("New project"), button:has-text("Novo projeto"), '
            '[aria-label="New project"], [aria-label="Novo projeto"]'
        ).first.wait_for(state="visible", timeout=15000)
    except Exception:
        if "flow.google.com" not in page.url:
            raise RuntimeError("Sessão não autenticada — rode --setup-session primeiro.")

    # Tentar clicar no botão de novo projeto
    for seletor in [
        'button:has-text("Novo projeto")',
        'button:has-text("New project")',
        'a:has-text("Novo projeto")',
        'a:has-text("New project")',
        '[aria-label="Novo projeto"]',
        '[aria-label="New project"]',
    ]:
        try:
            page.click(seletor, timeout=4000)
            log(f"  Clicou em '{seletor}'")
            page.wait_for_timeout(3000)
            break
        except Exception:
            continue

    # Aguardar até que a URL contenha /project/<id>
    try:
        page.wait_for_url(lambda u: "/project/" in u, timeout=30000)
    except PlaywrightTimeout:
        pass

    url_atual = page.url
    import re as _re
    m = _re.search(r"/project/([a-f0-9\-]{30,})", url_atual)
    if not m:
        raise RuntimeError(f"Não foi possível extrair project_id da URL: {url_atual}")

    project_id = m.group(1)
    log(f"  Projeto criado com ID: {project_id}")
    return project_id


def abrir_projeto(page: Page, project_id: str):
    url = f"{FLOW_BASE_URL}/{ACCOUNT_SLOT}/project/{project_id}"
    log(f"Navegando para {url}")
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=90000)
    except PlaywrightTimeout:
        log("  ⚠ goto timeout — continuando (página pode ainda estar carregando)")
    # Aguardar o botão de configurações aparecer — indica que o projeto carregou
    # Verificar se foi redirecionado para landing page (sessão expirada / não autenticado)
    if "/about" in page.url or page.url.rstrip("/") == "https://flow.google.com":
        raise RuntimeError(
            f"Sessão não autenticada — Flow redirecionou para landing page ({page.url}). "
            "Certifique-se de que o Chrome está aberto e logado em unitranoficial@gmail.com no Profile 3."
        )
    try:
        page.wait_for_selector('button[aria-label="Gatilho de configurações"]', timeout=60000)
    except PlaywrightTimeout:
        esperar_rede(page, timeout=15000)
    if "404" in page.url:
        raise RuntimeError(f"Projeto não encontrado: {project_id}")
    if "/about" in page.url:
        raise RuntimeError("Sessão perdida após carregamento — Flow redirecionou para landing page.")
    log(f"Projeto aberto: {page.title()}")


def ir_para_aba(page: Page, aba: str):
    """Clica no item do sidebar esquerdo (ex: 'Vídeos', 'Imagens')."""
    try:
        page.get_by_text(aba, exact=True).first.click(timeout=5000)
        page.wait_for_timeout(1000)
        log(f"  Aba '{aba}' aberta ✓")
    except Exception as e:
        log(f"  ⚠ Não foi possível abrir aba '{aba}': {e}")


# ────────────────────────────────────────────────────────────────────────────
# Galeria — identificar imagens existentes
# ────────────────────────────────────────────────────────────────────────────

def listar_thumbnails_em_picker(page: Page) -> list:
    """Retorna lista de thumbnails dentro de um picker de recurso aberto.
    Os itens aparecem ordenados do mais recente (índice 0) ao mais antigo."""
    page.wait_for_timeout(500)
    seletores = [
        '[role="gridcell"]',
        '[role="listitem"]',
        '[role="option"]',
    ]
    for sel in seletores:
        items = page.locator(sel).all()
        if items:
            return items
    return []


def _normalizar_id_recurso(valor: str) -> str:
    """Extrai a identidade estável; descarta query/URL temporária do Flow."""
    valor = valor or ""
    match = re.search(r'/(?:image|video)/([0-9a-f-]{20,})', valor, re.I)
    return match.group(1).lower() if match else valor.split("?", 1)[0]


def _identidade_recurso_picker(item) -> str:
    """Retorna uma identidade estável apenas para recursos realmente prontos."""
    try:
        valor = item.evaluate("""
            el => {
              const media = el.querySelector('img[src], video[src], video[poster], source[src]');
              if (!media) return '';
              return media.currentSrc || media.src || media.poster || media.getAttribute('src') || '';
            }
        """) or ""
        return _normalizar_id_recurso(valor)
    except Exception:
        return ""


def _recursos_imagem_no_picker(page: Page) -> list[dict]:
    """Lê imagens prontas do picker; placeholders/falhas não entram na lista."""
    try:
        page.evaluate("""() => document.querySelector(
            'button[aria-label="Adicionar elementos à caixa de comando"]'
        )?.click()""")
        page.wait_for_timeout(500)
        page.evaluate("""() => {
            const tab = Array.from(document.querySelectorAll('*')).find(el =>
              el.children.length === 0 && (el.textContent || '').trim() === 'Imagens');
            tab?.click();
            const input = Array.from(document.querySelectorAll('input')).find(
              el => el.placeholder === 'Pesquisar recursos');
            if (input && input.value) {
              input.value = '';
              input.dispatchEvent(new Event('input', {bubbles: true}));
            }
        }""")
        page.wait_for_timeout(300)
        recursos = page.evaluate("""() => {
            const sel = '[role="gridcell"], [role="listitem"], [role="option"]';
            return Array.from(document.querySelectorAll(sel)).map(el => {
                const m = el.querySelector('img[src], video[src], video[poster], source[src]');
                if (!m) return null;
                const id = m.currentSrc || m.src || m.poster || m.getAttribute('src') || '';
                if (!id) return null;
                return {id, nome: (el.textContent || '').trim()};
            }).filter(Boolean);
        }""")
        for recurso in recursos:
            recurso["id"] = _normalizar_id_recurso(recurso["id"])
            recurso["nome"] = _limpar_nome_picker(recurso["nome"]).strip()
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        return recursos
    except Exception:
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass
        return []


def _aguardar_nova_imagem_pronta(page: Page, ids_antes: set[str],
                                  falhas_antes: int, timeout_s: int = 120) -> dict:
    """Espera uma imagem nova utilizável ou transforma a falha do card em erro."""
    inicio = time.time()
    while time.time() - inicio < timeout_s:
        falhas_agora = _contar_falhas_na_pagina(page)
        if falhas_agora > falhas_antes:
            raise GeracaoFalhouError(
                f"Flow criou um novo card de falha ({falhas_antes} → {falhas_agora})"
            )
        recursos = _recursos_imagem_no_picker(page)
        novos = [recurso for recurso in recursos if recurso["id"] not in ids_antes]
        if novos:
            return novos[0]
        page.wait_for_timeout(2000)
    raise GeracaoFalhouError("nenhuma imagem nova e utilizável apareceu no picker")


def _aguardar_lote_recursos(page: Page, ids_antes: set[str], falhas_antes: int,
                             quantidade: int, timeout_s: int = 600) -> list[dict]:
    """Espera um lote completo sem confundir placeholders com imagens prontas."""
    inicio = time.time()
    while time.time() - inicio < timeout_s:
        falhas_agora = _contar_falhas_na_pagina(page)
        if falhas_agora > falhas_antes:
            raise GeracaoFalhouError(
                f"o lote criou {falhas_agora - falhas_antes} novo(s) card(s) de falha"
            )
        recursos = _recursos_imagem_no_picker(page)
        novos = [recurso for recurso in recursos if recurso["id"] not in ids_antes]
        if len(novos) >= quantidade:
            return novos[:quantidade]
        log(f"  Lote: {len(novos)}/{quantidade} imagens prontas")
        page.wait_for_timeout(4000)
    raise GeracaoFalhouError(
        f"timeout do lote: somente {len(novos)}/{quantidade} imagens ficaram prontas"
    )


# ────────────────────────────────────────────────────────────────────────────
# Geração de Imagem (Etapa 2a)
# ────────────────────────────────────────────────────────────────────────────

def _clicar_toggle(page: Page, texto_contem: str):
    """Clica no mat-button-toggle cujo textContent inclui o texto dado."""
    page.evaluate(f"""
        document.querySelectorAll('button.mat-button-toggle-button').forEach(b => {{
            if (b.textContent.includes('{texto_contem}')) b.click();
        }});
    """)
    page.wait_for_timeout(300)


def _selecionar_proporcao(page: Page):
    """Seleciona a proporção configurada no entrypoint atual."""
    # A interface nova expõe as proporções como radio com aria-label; esta é
    # a identificação mais estável e independe do ícone/texto interno.
    try:
        radio = page.get_by_role("radio", name=ASPECT_RATIO, exact=True)
        if radio.count() and radio.first.is_visible():
            radio.first.click()
            page.wait_for_timeout(200)
            return
    except Exception:
        pass

    selecionou = page.evaluate(r"""ratio => {
        const candidatos = Array.from(document.querySelectorAll(
          'button.mat-button-toggle-button, mat-button-toggle button, [role="radio"], button'
        )).filter(el => el.offsetParent !== null);
        const alvo = candidatos.find(el =>
          (el.getAttribute('aria-label') || '').trim() === ratio ||
          (el.getAttribute('title') || '').trim() === ratio ||
          (el.textContent || '').replace(/\s+/g, ' ').trim() === ratio
        );
        if (!alvo) return false;
        if (alvo.getAttribute('aria-checked') !== 'true') alvo.click();
        return true;
    }""", ASPECT_RATIO)
    if not selecionou:
        raise RuntimeError(f"Proporção {ASPECT_RATIO} não encontrada no painel do Flow")
    page.wait_for_timeout(200)


def abrir_modo_imagem(page: Page, num_imagens: int = 1):
    """Abre configurações e seleciona modo Imagem, configurando o count correto."""
    page.click('button[aria-label="Gatilho de configurações"]')
    page.wait_for_timeout(400)
    _clicar_toggle(page, "Imagem")
    page.wait_for_timeout(200)
    _selecionar_proporcao(page)
    # Definir contagem
    page.evaluate(f"""
        document.querySelectorAll('button.mat-button-toggle-button').forEach(b => {{
            if (b.textContent.trim() === 'x{num_imagens}') b.click();
        }});
    """)
    page.wait_for_timeout(200)
    # Fechar pelo próprio gatilho. Escape nem sempre fecha este popover e pode
    # deixar uma instância oculta do botão de geração sobreposta ao editor.
    page.evaluate("""() => {
        const b = Array.from(document.querySelectorAll(
          'button[aria-label="Gatilho de configurações"]')).find(
            el => el.offsetParent !== null);
        b?.click();
    }""")
    page.wait_for_timeout(400)
    log(f"  Modo: Imagem | Quantidade: x{num_imagens} | Proporção: {ASPECT_RATIO}")


def _clicar_qualquer_botao_com_texto(page: Page, texto: str) -> bool:
    """Clica no primeiro botão/tab/link visível que contenha o texto dado."""
    return page.evaluate(f"""
        (() => {{
            const sels = ['button', '[role="tab"]', 'a', 'mat-button-toggle'];
            for (const sel of sels) {{
                for (const el of document.querySelectorAll(sel)) {{
                    if (el.textContent.includes('{texto}')) {{
                        el.click();
                        return true;
                    }}
                }}
            }}
            return false;
        }})()
    """)


def abrir_modo_frames(page: Page):
    """Abre configurações, seleciona Vídeo → Frames e fecha o painel."""

    def _abrir_painel():
        for aria in ["Gatilho de configurações", "Configurações da grade de blocos", "Configurações"]:
            try:
                page.click(f'button[aria-label="{aria}"]', timeout=3000)
                page.wait_for_timeout(800)
                return True
            except Exception:
                continue
        return False

    def _painel_tem_toggles() -> bool:
        return page.evaluate("""
            (() => {
                const els = document.querySelectorAll('mat-button-toggle, [role="tab"]');
                return Array.from(els).some(e =>
                    e.textContent.includes('Imagem') ||
                    e.textContent.includes('Vídeo') ||
                    e.textContent.includes('Frames')
                );
            })()
        """)

    def _dump_painel_texto() -> str:
        """Retorna todos os textos visíveis nos toggles/tabs do painel para diagnóstico."""
        try:
            return page.evaluate("""
                (() => {
                    const els = document.querySelectorAll(
                        'mat-button-toggle, [role="tab"], button, [role="radio"]'
                    );
                    return Array.from(els)
                        .filter(e => e.offsetParent !== null)
                        .map(e => e.textContent.trim())
                        .filter(t => t.length > 0 && t.length < 40)
                        .slice(0, 20)
                        .join(' | ');
                })()
            """)
        except Exception:
            return "(erro ao ler painel)"

    def _tentar_ativar_frames() -> bool:
        """Sequência completa: abrir painel → Vídeo → Frames → fechar. Retorna True se slots visíveis."""
        _abrir_painel()
        # Clicar Vídeo
        _clicar_toggle(page, "Vídeo")
        page.wait_for_timeout(800)
        # Log diagnóstico: o que está visível agora?
        texto_painel = _dump_painel_texto()
        log(f"  [diag] painel após Vídeo: {texto_painel[:120]}")
        # Se painel fechou, reabrir E clicar Vídeo novamente (painel volta ao estado padrão)
        if not _painel_tem_toggles():
            log("  Painel fechou após Vídeo — reabrindo e selecionando Vídeo novamente...")
            _abrir_painel()
            page.wait_for_timeout(400)
            _clicar_toggle(page, "Vídeo")
            page.wait_for_timeout(800)
            texto_painel2 = _dump_painel_texto()
            log(f"  [diag] painel após reabrir+Vídeo: {texto_painel2[:120]}")
        # Clicar Frames — tentar também variantes em português ("Quadros")
        ok = _clicar_qualquer_botao_com_texto(page, "Frames")
        if not ok:
            ok = _clicar_qualquer_botao_com_texto(page, "Quadros")
        if not ok:
            try:
                page.get_by_text("Frames", exact=True).first.click(timeout=2000)
                ok = True
            except Exception:
                pass
        log(f"  Sub-tab 'Frames': {'✓' if ok else '⚠ não encontrado'}")
        page.wait_for_timeout(600)
        _selecionar_proporcao(page)
        # Fechar painel
        page.keyboard.press("Escape")
        page.wait_for_timeout(900)
        return _slots_frames_visiveis(page)

    for tentativa in range(3):
        if _tentar_ativar_frames():
            log("  Modo Frames confirmado ✓")
            return
        log(f"  Tentativa {tentativa + 1}/3 falhou — aguardando e tentando novamente...")
        page.wait_for_timeout(1500)

    btns = page.evaluate("""
        Array.from(document.querySelectorAll('button[aria-label]'))
             .map(b => b.getAttribute('aria-label'))
             .filter(l => l).slice(0, 25)
    """)
    raise RuntimeError(f"Modo Frames não ativado após 3 tentativas. aria-labels: {btns}")


class GeracaoFalhouError(Exception):
    pass


def _criar_png_branco_9x16(caminho: Path, largura: int = 1080, altura: int = 1920):
    """Cria PNG branco puro sem dependências externas."""
    caminho.parent.mkdir(parents=True, exist_ok=True)
    linha = b"\x00" + (b"\xff\xff\xff" * largura)
    pixels = linha * altura

    def chunk(tipo: bytes, dados: bytes) -> bytes:
        return (
            struct.pack(">I", len(dados)) + tipo + dados
            + struct.pack(">I", zlib.crc32(tipo + dados) & 0xFFFFFFFF)
        )

    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", largura, altura, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(pixels, 9))
        + chunk(b"IEND", b"")
    )
    caminho.write_bytes(png)


def enviar_coringa_branca(page: Page, pasta_saida: Path) -> dict:
    """Envia uma coringa branca local quando o Flow bloqueia sua geração."""
    caminho = pasta_saida / "coringa_branca_9x16.png"
    if not caminho.exists():
        _criar_png_branco_9x16(caminho)

    ids_antes = {r["id"] for r in _recursos_imagem_no_picker(page)}
    log(f"  Enviando coringa branca local: {caminho.name}")
    page.get_by_role("button", name="Menu para adicionar arquivos").click()
    with page.expect_file_chooser(timeout=10000) as evento:
        try:
            page.get_by_role("menuitem", name="Enviar").click()
        except Exception:
            page.get_by_text("Enviar", exact=True).click()
    evento.value.set_files(str(caminho.absolute()))

    try:
        concordo = page.get_by_role("button", name="Concordo")
        concordo.wait_for(state="visible", timeout=5000)
        concordo.click()
    except Exception:
        pass

    limite = time.time() + 60
    while time.time() < limite:
        page.wait_for_timeout(2000)
        recursos = _recursos_imagem_no_picker(page)
        novo = next((r for r in recursos if r["id"] not in ids_antes), None)
        if novo:
            log(f"  Coringa branca enviada e validada: '{novo['nome']}' ✓")
            return novo
    raise RuntimeError("Upload da coringa branca não apareceu no picker após 60s")


def aguardar_geracao(page: Page, timeout_ms: int = TIMEOUT_GERACAO_MS,
                     label: str = "geração", falhas_iniciais: int = 0):
    """Aguarda a conclusão de uma geração (imagem ou vídeo) no Flow.
    Lança GeracaoFalhouError se o Flow reportar falha de política."""
    log(f"  Aguardando {label} ", end="")
    # Espera inicial para o indicador de loading aparecer
    time.sleep(3)
    inicio = time.time()
    limite = timeout_ms / 1000

    def _checar_falha():
        try:
            falhas_atuais = _contar_falhas_na_pagina(page)
            if falhas_atuais > falhas_iniciais:
                return True
            return page.evaluate("""
                (() => {
                    const texts = ['viole nossas políticas', 'This generation may violate',
                                   'generation failed', 'Unable to generate'];
                    const overlays = document.querySelectorAll('[class*="overlay"], [class*="snack"], [class*="toast"]');
                    for (const el of overlays) {
                        if (texts.some(t => (el.innerText || '').includes(t))) return true;
                    }
                    return false;
                })()
            """)
        except Exception:
            return False

    while time.time() - inicio < limite:
        carregando = page.locator('[aria-label*="carregando"], [aria-busy="true"], [aria-label*="Gerando"]').count()
        if _checar_falha():
            log(" ✗ (falha de política)")
            raise GeracaoFalhouError(f"{label} falhou por violação de política")
        if carregando == 0:
            # Pausa breve e checa novamente — evita falso positivo por race condition
            time.sleep(1)
            if _checar_falha():
                log(" ✗ (falha de política)")
                raise GeracaoFalhouError(f"{label} falhou por violação de política")
            log(" ✓")
            return
        print(".", end="", flush=True)
        time.sleep(3)

    log(f" (timeout atingido — {label} pode ainda estar em andamento)")


def aguardar_videos_prontos(page: Page, num_takes: int,
                             timeout_por_take_s: int = 300):
    """Aguarda todos os vídeos renderizarem na aba Vídeos, sem sleep fixo.

    Faz poll a cada 10s verificando se ainda há indicadores de loading/geração.
    Retorna quando a aba estiver quieta ou o timeout for atingido.
    """
    ir_para_aba(page, "Vídeos")
    page.wait_for_timeout(2000)

    timeout_total = num_takes * timeout_por_take_s
    log(f"  Aguardando render de {num_takes} vídeo(s) (timeout: {timeout_total // 60} min) ", end="")
    time.sleep(5)  # janela inicial para o Flow enfileirar

    inicio = time.time()
    while time.time() - inicio < timeout_total:
        carregando = page.evaluate("""
            (() => {
                const seletores = [
                    '[aria-busy="true"]',
                    '[aria-label*="carregando"]',
                    '[aria-label*="Gerando"]',
                    '[aria-label*="Processando"]',
                    '[aria-label*="gerando"]',
                    '[aria-label*="processando"]',
                ];
                return seletores.reduce((acc, s) => acc + document.querySelectorAll(s).length, 0);
            })()
        """)
        if carregando == 0:
            log(" ✓")
            page.wait_for_timeout(1500)  # buffer para UI estabilizar
            return
        print(".", end="", flush=True)
        time.sleep(10)

    log(f" (timeout — continuando mesmo assim)")


def adicionar_referencia_coringa(page: Page, nome_coringa: str,
                                 id_coringa: str = "") -> bool:
    """
    Abre o picker de recursos e seleciona a imagem coringa como referência
    para a geração de imagem, buscando pelo nome exato gravado após a geração.
    """
    inicio_etapa = time.perf_counter()
    try:
        abriu = page.evaluate("""() => {
            const b = document.querySelector(
              'button[aria-label="Adicionar elementos à caixa de comando"]');
            if (!b) return false;
            b.click();
            return true;
        }""")
        if not abriu:
            raise RuntimeError("botão de adicionar referência não encontrado")
        page.wait_for_timeout(250)

        # Navega e seleciona em uma única avaliação no DOM. Evita dezenas de
        # Locator.evaluate() sequenciais, que esperavam a estabilidade do Angular.
        page.evaluate("""() => {
            const tab = Array.from(document.querySelectorAll('*')).find(el =>
              el.children.length === 0 && (el.textContent || '').trim() === 'Imagens');
            tab?.click();
        }""")
        page.wait_for_timeout(200)
        # Força o Flow a materializar a coringa no DOM mesmo quando a galeria
        # virtualizada a remove após a submissão do take anterior.
        if nome_coringa:
            page.evaluate(r"""nome => {
                const input = Array.from(document.querySelectorAll('input')).find(
                  el => el.placeholder === 'Pesquisar recursos' && el.offsetParent !== null);
                if (!input) return;
                const termo = nome.replace(/…|\.\.\.$/g, '').trim().split(/\s+/)[0];
                const setter = Object.getOwnPropertyDescriptor(
                  HTMLInputElement.prototype, 'value').set;
                setter.call(input, termo);
                input.dispatchEvent(new Event('input', {bubbles: true}));
                input.dispatchEvent(new Event('change', {bubbles: true}));
            }""", nome_coringa)
            page.wait_for_timeout(300)
        selecionou = False
        limite_recurso = time.time() + 5
        limpar_em = time.time() + 2.5
        filtro_limpo = False
        while time.time() < limite_recurso and not selecionou:
            selecionou = page.evaluate(r"""({id, nome}) => {
                const seletores = '[role="gridcell"], [role="listitem"], [role="option"]';
                const items = Array.from(document.querySelectorAll(seletores));
                let escolhido = null;
                const normalizar = valor => {
                  const m = (valor || '').match(/\/(?:image|video)\/([0-9a-f-]{20,})/i);
                  return m ? m[1].toLowerCase() : (valor || '').split('?')[0];
                };
                if (id) {
                  escolhido = items.find(el => {
                    const m = el.querySelector('img[src], video[src], video[poster], source[src]');
                    if (!m) return false;
                    const src = m.currentSrc || m.src || m.poster || m.getAttribute('src') || '';
                    return normalizar(src) === normalizar(id);
                  });
                }
                // Itens virtualizados podem ter texto antes de receber img/src.
                // O título da coringa é usado apenas como fallback do UUID.
                if (!escolhido && nome) {
                  const termo = nome.replace(/…|\.\.\.$/g, '').trim().slice(0, 24);
                  escolhido = items.find(el => (el.textContent || '').includes(termo));
                }
                if (!escolhido) return false;
                escolhido.click();
                escolhido.dispatchEvent(new MouseEvent('dblclick', {
                  bubbles: true, cancelable: true, view: window
                }));
                return true;
            }""", {"id": id_coringa, "nome": nome_coringa})
            if not selecionou:
                if not filtro_limpo and time.time() >= limpar_em:
                    page.evaluate("""() => {
                        const input = Array.from(document.querySelectorAll('input')).find(
                          el => el.placeholder === 'Pesquisar recursos' && el.offsetParent !== null);
                        if (!input) return;
                        const setter = Object.getOwnPropertyDescriptor(
                          HTMLInputElement.prototype, 'value').set;
                        setter.call(input, '');
                        input.dispatchEvent(new Event('input', {bubbles: true}));
                        input.dispatchEvent(new Event('change', {bubbles: true}));
                    }""")
                    filtro_limpo = True
                elif filtro_limpo:
                    page.evaluate("""() => {
                        const input = Array.from(document.querySelectorAll('input')).find(
                          el => el.placeholder === 'Pesquisar recursos' && el.offsetParent !== null);
                        const raiz = input?.closest('.cdk-overlay-pane') || input?.parentElement?.parentElement;
                        if (!raiz) return;
                        const candidatos = [
                          ...raiz.querySelectorAll('cdk-virtual-scroll-viewport, [class*="scroll"], div')
                        ].filter(el => el.scrollHeight > el.clientHeight + 20);
                        const alvo = candidatos.sort(
                          (a, b) => (b.scrollHeight - b.clientHeight) -
                                    (a.scrollHeight - a.clientHeight)
                        )[0];
                        if (alvo) {
                          alvo.scrollTop = Math.min(
                            alvo.scrollHeight, alvo.scrollTop + Math.max(220, alvo.clientHeight * .75));
                          alvo.dispatchEvent(new Event('scroll', {bubbles: true}));
                        }
                    }""")
                page.wait_for_timeout(100)
        if not selecionou:
            diagnostico = page.evaluate("""() => ({
                buscas: Array.from(document.querySelectorAll('input')).filter(
                  el => el.placeholder === 'Pesquisar recursos').map(el => ({
                    value: el.value, visible: el.offsetParent !== null
                  })),
                itens: Array.from(document.querySelectorAll(
                  '[role="gridcell"], [role="listitem"], [role="option"]'
                )).slice(0, 12).map(el => {
                    const m = el.querySelector('img[src], video[src], video[poster], source[src]');
                    return {
                      texto: (el.textContent || '').trim().slice(0, 100),
                      media: m ? (m.currentSrc || m.src || m.poster || '') : '',
                      visible: el.offsetParent !== null
                    };
                })
            })""")
            log(f"  Diagnóstico do picker: {json.dumps(diagnostico, ensure_ascii=False)}")
            log("  ⚠ A imagem coringa exata não foi encontrada no picker")
            page.keyboard.press("Escape")
            return False
        page.wait_for_timeout(150)

        # Clicar "Incluir no comando" para fechar o picker e adicionar a referência
        # Alguns builds incluem o item imediatamente no duplo clique.
        incluiu = page.evaluate("""() => !Array.from(document.querySelectorAll('input')).some(
            el => el.placeholder === 'Pesquisar recursos' && el.offsetParent !== null
        )""")
        limite = time.time() + 10
        while time.time() < limite and not incluiu:
            incluiu = page.evaluate("""() => {
                const b = Array.from(document.querySelectorAll('button')).find(
                  el => (el.textContent || '').trim() === 'Incluir no comando');
                if (!b || b.disabled || b.getAttribute('aria-disabled') === 'true') return false;
                b.click();
                return true;
            }""")
            if not incluiu:
                page.wait_for_timeout(250)
        if not incluiu:
            raise RuntimeError(
                "Flow não habilitou 'Incluir no comando' em 10 segundos"
            )
        page.wait_for_timeout(200)

        duracao = time.perf_counter() - inicio_etapa
        log(f"  Referência coringa '{nome_coringa[:40]}' selecionada em {duracao:.1f}s ✓")
        return True
    except Exception as e:
        log(f"  ⚠ Falha ao adicionar referência: {e}")
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass
        return False


def _variacao_prompt(prompt: str, tentativa: int) -> str:
    """Retorna variação leve do prompt para retry após policy violation."""
    if tentativa == 0:
        return prompt
    # Variações que evitam triggers de policy: substituir termos que podem ser
    # interpretados como suspeitos (muitas negações, "empty", "blank")
    parece_coringa = any(token in prompt.lower() for token in (
        "blank white", "pure solid white", "completely blank", "empty canvas"
    ))
    if parece_coringa:
        prompts_coringa = [
            f"Uniform featureless pure #FFFFFF color field filling every pixel edge-to-edge, {ASPECT_RATIO}. This is only a digital background color, not an object or surface.",
            f"Full-bleed solid #FFFFFF white image, perfectly uniform from edge to edge, {ASPECT_RATIO}. No physical scene or display surface.",
            f"A completely uniform RGB 255,255,255 field across the entire {ASPECT_RATIO} image. Render only the flat background color.",
        ]
        return prompts_coringa[(tentativa - 1) % len(prompts_coringa)]
    variacoes = [
        lambda p: p.replace("completely empty", "ready for drawing").replace("no objects, no text, no drawings", "clean surface"),
        lambda p: p.replace("Flat 2D digital illustration,", "Simple graphic design,").replace("no room, no furniture, no perspective, no angle,", ""),
        lambda p: p + " Educational illustration.",
    ]
    idx = (tentativa - 1) % len(variacoes)
    try:
        return variacoes[idx](prompt)
    except Exception:
        return prompt + " Simple educational style."


def _prompt_com_regras_visuais(prompt: str, coringa: bool = False) -> str:
    """Aplica invariantes globais a qualquer roteiro, independentemente do estilo."""
    regra_idioma = (
        " Any text visibly rendered in the image must be Brazilian Portuguese (PT-BR), "
        "with correct accents. Translate every English label to Portuguese; keep only "
        "proper names or standard symbols that should not be translated."
    )
    texto = (prompt or "").strip()
    texto = re.sub(r"(?<!\d)(?:16:9|9:16)(?!\d)", ASPECT_RATIO, texto)
    if coringa and any(token in texto.lower() for token in (
        "pure solid white", "pure white background", "#ffffff", "totalmente branca"
    )):
        return (
            "Uniform featureless pure #FFFFFF white color field filling every pixel "
            f"edge-to-edge in a {ASPECT_RATIO} image. Render only the digital background color. "
            "It is not a board, whiteboard, canvas, slide, paper, card, panel, wall or "
            "physical surface. No frame, border, margin, shadow, texture, gradient, "
            "perspective, lighting, room, object, person, drawing or text."
        )
    return texto + regra_idioma


def _submeter_imagem(page: Page, prompt: str, num_imagens: int = 1,
                     nome_coringa: str = "", id_coringa: str = ""):
    """Configura e submete geração de imagem SEM aguardar conclusão."""
    inicio = time.perf_counter()
    abrir_modo_imagem(page, num_imagens=num_imagens)
    log(f"  [tempo] configuração: {time.perf_counter() - inicio:.1f}s")
    preencher_contenteditable(page, _prompt_com_regras_visuais(prompt))
    log(f"  [tempo] prompt: {time.perf_counter() - inicio:.1f}s acumulados")
    if nome_coringa:
        if not adicionar_referencia_coringa(page, nome_coringa, id_coringa=id_coringa):
            raise RuntimeError("imagem coringa exata não pôde ser adicionada como referência")
        # Picker já fecha ao clicar "Incluir no comando"; pequena pausa para UI estabilizar
        page.wait_for_timeout(300)
    atividade_antes = page.locator(
        '[aria-busy="true"], [aria-label*="carregando"], [aria-label*="Gerando"]'
    ).count()
    submeteu = False
    botoes_gerar = page.locator('button[aria-label="Iniciar geração"]')
    for indice in range(botoes_gerar.count()):
        botao = botoes_gerar.nth(indice)
        try:
            if botao.is_visible(timeout=200) and botao.is_enabled(timeout=200):
                botao.click(force=True, timeout=3000)
                submeteu = True
                break
        except Exception:
            continue
    if not submeteu:
        raise RuntimeError("botão 'Iniciar geração' não estava habilitado")
    # Uma submissão real limpa o editor. Sem esta confirmação, o próximo
    # take anexaria outra referência ao mesmo prompt.
    limpou = False
    limite_limpeza = time.time() + 5
    while time.time() < limite_limpeza and not limpou:
        limpou = page.evaluate("""atividadeAntes => {
            const editores = Array.from(document.querySelectorAll('[contenteditable="true"]'))
              .filter(el => el.offsetParent !== null);
            const editorLimpo = editores.length === 0 || editores.every(
              el => !(el.innerText || el.textContent || '').trim());
            const atividade = document.querySelectorAll(
              '[aria-busy="true"], [aria-label*="carregando"], [aria-label*="Gerando"]'
            ).length;
            return editorLimpo || atividade > atividadeAntes;
        }""", atividade_antes)
        if not limpou:
            page.wait_for_timeout(100)
    if not limpou:
        raise RuntimeError(
            "o Flow não limpou o editor; a geração não foi realmente submetida"
        )
    log(f"  [tempo] submissão completa: {time.perf_counter() - inicio:.1f}s")


def _contar_falhas_na_pagina(page: Page) -> int:
    """Conta quantos cards com 'Falha' estão visíveis na página do Flow."""
    try:
        return page.evaluate("""
            () => {
                const spans = Array.from(document.querySelectorAll('span, div, p'));
                return spans.filter(el =>
                    el.children.length === 0 &&
                    el.textContent.trim() === 'Falha'
                ).length;
            }
        """)
    except Exception:
        return 0


def _nomes_no_picker(page: Page) -> list:
    """Abre o picker, lê todos os nomes de imagens e fecha. Retorna lista ordenada (mais recente primeiro)."""
    try:
        page.click('button[aria-label="Adicionar elementos à caixa de comando"]')
        page.wait_for_timeout(500)
        try:
            tab = page.get_by_text("Imagens", exact=True).first
            if tab.is_visible(timeout=1000):
                tab.click()
                page.wait_for_timeout(300)
        except Exception:
            pass
        try:
            caixa = page.get_by_placeholder("Pesquisar recursos").first
            caixa.fill("", timeout=1000)
            page.wait_for_timeout(300)
        except Exception:
            pass
        items = listar_thumbnails_em_picker(page)
        nomes = [_limpar_nome_picker(it.text_content() or "").strip() for it in items]
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        return [n for n in nomes if n]
    except Exception:
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass
        return []


def aguardar_lote_imagens(page: Page, nomes_antes: set, num_takes: int,
                           timeout_por_take_s: int = 120) -> list:
    """
    Aguarda num_takes novas imagens aparecerem no picker após submissão em lote.
    Retorna lista de nomes novos ordenada como o picker (mais recente primeiro).
    O Flow processa em FIFO: take_1 termina antes → aparece mais antigo (último índice).
    Retorna cedo se detectar falhas suficientes para explicar o déficit.
    """
    timeout = num_takes * timeout_por_take_s
    log(f"  Aguardando {num_takes} imagens em lote (timeout: {timeout // 60}min) ", end="")
    time.sleep(5)
    inicio = time.time()
    novos: list = []
    while time.time() - inicio < timeout:
        nomes_atual = _nomes_no_picker(page)
        novos = [n for n in nomes_atual if n not in nomes_antes]
        if len(novos) >= num_takes:
            log(" ✓")
            return novos[:num_takes]
        # Detectar falhas na UI para retornar cedo em vez de esperar timeout
        num_falhas = _contar_falhas_na_pagina(page)
        pendentes = num_takes - len(novos)
        if num_falhas > 0 and num_falhas >= pendentes:
            log(f" ✗ ({num_falhas} falha(s) — {len(novos)}/{num_takes} obtidos)")
            return novos
        if num_falhas > 0:
            print(f"[{len(novos)}/{num_takes}, {num_falhas}✗]", end="", flush=True)
        else:
            print(f"[{len(novos)}/{num_takes}]", end="", flush=True)
        time.sleep(8)
    log(f" (timeout — {len(novos)}/{num_takes} encontrados)")
    return novos


def gerar_imagens_take(page: Page, prompt: str, num_imagens: int = 1,
                       pausar: bool = False, nome_coringa: str = "",
                       id_coringa: str = "") -> dict:
    """
    Gera N imagens para o take com o prompt fornecido (modo sequencial — aguarda cada uma).
    Se nome_coringa for fornecido, seleciona a coringa como referência via picker.
    Faz até 3 tentativas em caso de falha por política.
    """
    max_tentativas = 3
    for tentativa in range(max_tentativas):
        recursos_antes = _recursos_imagem_no_picker(page)
        ids_antes = {recurso["id"] for recurso in recursos_antes}
        falhas_antes = _contar_falhas_na_pagina(page)
        prompt_atual = _prompt_com_regras_visuais(
            _variacao_prompt(prompt, tentativa), coringa=not bool(nome_coringa)
        )
        if tentativa > 0:
            log(f"  ↩ Retry {tentativa}/{max_tentativas - 1} após falha de política...")
            page.wait_for_timeout(2000)

        log(f"  Configurando modo Imagem (x{num_imagens})...")
        abrir_modo_imagem(page, num_imagens=num_imagens)

        log(f"  Preenchendo prompt de imagem...")
        preencher_contenteditable(page, prompt_atual)

        if nome_coringa:
            if not adicionar_referencia_coringa(
                    page, nome_coringa, id_coringa=id_coringa):
                raise RuntimeError("imagem coringa exata não pôde ser adicionada como referência")
            try:
                page.wait_for_selector(".cdk-overlay-backdrop", state="hidden", timeout=3000)
            except Exception:
                try:
                    page.keyboard.press("Escape")
                    page.wait_for_timeout(400)
                except Exception:
                    pass

        log(f"  Submetendo geração...")
        page.click('button[aria-label="Iniciar geração"]')
        page.wait_for_timeout(500)

        if pausar:
            log("  ⏸  Gerando imagens. Pressione Enter ao ver os resultados no Flow...")
            input()
            return
        try:
            aguardar_geracao(
                page, label="geração de imagem", falhas_iniciais=falhas_antes
            )
            recurso = _aguardar_nova_imagem_pronta(
                page, ids_antes=ids_antes, falhas_antes=falhas_antes
            )
            log(f"  Imagem nova validada no picker: '{recurso['nome'] or '(sem título)'}' ✓")
            return recurso
        except GeracaoFalhouError as e:
            log(f"  ⚠ {e}")
            if tentativa == max_tentativas - 1:
                raise


# ────────────────────────────────────────────────────────────────────────────
# Geração de Vídeo (Etapa 2b)
# ────────────────────────────────────────────────────────────────────────────

def definir_configuracoes_video(page: Page):
    """Garante modo Frames (Início+Fim) e configurações 720p padrão para vídeo."""
    abrir_modo_frames(page)


def _limpar_nome_picker(texto: str) -> str:
    """Remove prefixos/sufixos de tipo que text_content() concatena (ex: 'image', 'Imagem')."""
    import re as _re
    t = texto.strip()
    t = _re.sub(r'^(image|imagem|vídeo|video)\s*', '', t, flags=_re.IGNORECASE)
    t = _re.sub(r'\s*(Imagem|image|Vídeo|Video)$', '', t, flags=_re.IGNORECASE)
    return t.strip()


def obter_nome_nova_imagem(page: Page, nomes_conhecidos: set) -> str:
    """
    Abre o picker, varre todos os itens e retorna o PRIMEIRO nome que não está
    em nomes_conhecidos. Isso é confiável porque o Flow nomeia cada imagem de
    forma única, independente da ordem de exibição ('Recentes').
    """
    try:
        page.click('button[aria-label="Adicionar elementos à caixa de comando"]')
        page.wait_for_timeout(700)
        try:
            imagens_tab = page.get_by_text("Imagens", exact=True).first
            if imagens_tab.is_visible(timeout=1500):
                imagens_tab.click()
                page.wait_for_timeout(400)
        except Exception:
            pass
        # Garantir que não há filtro ativo
        try:
            caixa = page.get_by_placeholder("Pesquisar recursos").first
            caixa.fill("", timeout=1000)
            page.wait_for_timeout(500)
        except Exception:
            pass
        items = listar_thumbnails_em_picker(page)
        nomes_picker = [_limpar_nome_picker(it.text_content() or "").strip() for it in items]
        log(f"  Picker itens: {[n[:30] for n in nomes_picker]}")
        # Retornar o primeiro nome que não estava antes
        for nome in nomes_picker:
            if nome and nome not in nomes_conhecidos:
                page.keyboard.press("Escape")
                page.wait_for_timeout(400)
                return nome
        # Fallback: retornar o primeiro item disponível
        nome = nomes_picker[0] if nomes_picker else ""
        page.keyboard.press("Escape")
        page.wait_for_timeout(400)
        return nome
    except Exception as e:
        log(f"  ⚠ obter_nome_nova_imagem: {e}")
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass
        return ""


def _slots_frames_visiveis(page: Page) -> bool:
    """Verifica se os slots Início/Fim do modo Frames estão visíveis na área de comando."""
    return page.evaluate("""
        (() => {
            const textos = ['Inicio', 'Início', 'Start'];
            return textos.some(t =>
                Array.from(document.querySelectorAll('button, span, div, p'))
                    .some(el => el.textContent.trim() === t && el.offsetParent !== null)
            );
        })()
    """)


def _picker_frame_esta_aberto(page: Page) -> bool:
    """Verifica se o diálogo de seleção de frame está visível."""
    try:
        return page.get_by_text("Selecione uma imagem de frame", exact=False).first.is_visible(timeout=500)
    except Exception:
        return False


def _abrir_picker_frame_slot(page: Page, slot_aria: str):
    """Abre o picker de frame para o slot dado (Inicio ou Fim), detectando auto-avanço."""
    if _picker_frame_esta_aberto(page):
        log(f"  Picker '{slot_aria}' já aberto (auto-avanço do Flow).")
        return
    aliases = {
        "Início": ["Inicio", "Início", "Start"],
        "Fim":    ["Fim", "End"],
    }
    for texto in aliases.get(slot_aria, [slot_aria]):
        try:
            page.get_by_text(texto, exact=True).first.click(timeout=3000)
            return
        except Exception:
            continue
    raise Exception(f"Botão de slot '{slot_aria}' não encontrado")


def _confirmar_picker_frame(page: Page):
    """Clica 'Incluir no comando' e aguarda o picker fechar."""
    try:
        page.get_by_text("Incluir no comando", exact=True).first.click(timeout=5000)
    except Exception:
        try:
            page.get_by_text("Incluir", exact=False).first.click(timeout=3000)
        except Exception:
            pass
    try:
        page.wait_for_selector(".cdk-overlay-backdrop", state="hidden", timeout=6000)
    except Exception:
        page.keyboard.press("Escape")
        page.wait_for_timeout(500)
    page.wait_for_timeout(400)


def descobrir_nomes_picker(page: Page, num_takes: int) -> dict:
    """
    Abre o picker de frame, lê todos os nomes das imagens na ordem padrão
    (mais recente primeiro) e mapeia: coringa → nome, take_1 → nome, etc.
    Fecha o picker sem selecionar nada.
    """
    _abrir_picker_frame_slot(page, "Início")
    page.wait_for_timeout(800)

    items = listar_thumbnails_em_picker(page)
    nomes = [_limpar_nome_picker(it.text_content() or "") for it in items]
    log(f"  Imagens descobertas no picker: {nomes}")

    # Fechar sem selecionar
    page.keyboard.press("Escape")
    page.wait_for_timeout(600)

    # Picker ordena mais-recente-primeiro:
    # [take_N_mais_novo, ..., take_1, coringa_mais_antiga]
    mapa = {}
    if len(nomes) >= num_takes + 1:
        mapa["coringa"] = nomes[-1]           # mais antiga = coringa
        for i in range(num_takes):
            n_take = num_takes - i             # take3, take2, take1
            mapa[f"take_{n_take}"] = nomes[i]
    elif nomes:
        mapa["coringa"] = nomes[-1]
        for i in range(min(num_takes, len(nomes) - 1)):
            mapa[f"take_{num_takes - i}"] = nomes[i]

    log(f"  Mapa de nomes: {mapa}")
    return mapa


def _selecionar_frame_por_nome(page: Page, slot_aria: str, nome_imagem: str,
                               position_hint: int = 0, recurso_id: str = "") -> bool:
    """Abre o picker do slot, busca a imagem pelo nome exato e confirma.

    position_hint: índice do resultado a selecionar quando há múltiplos com mesmo nome.
      0  = primeiro (mais recente) — padrão
      -1 = último (mais antigo, útil para o coringa)
      N  = Nth resultado
    Este hint é aplicado apenas quando há resultados; se só houver um, seleciona ele.
    """
    try:
        _abrir_picker_frame_slot(page, slot_aria)
        page.wait_for_timeout(600)

        # Pesquisar pelo nome (sem ellipsis final — Flow pode truncar o texto exibido)
        termo_busca = nome_imagem.rstrip("…").rstrip("...").strip()
        try:
            caixa = page.get_by_placeholder("Pesquisar recursos").first
            caixa.fill(termo_busca, timeout=2000)
            page.wait_for_timeout(800)
        except Exception:
            pass

        items = listar_thumbnails_em_picker(page)
        log(f"  Picker '{slot_aria}' após busca '{termo_busca[:25]}': {len(items)} item(s)")

        if recurso_id:
            item_exato = next(
                (item for item in items if _identidade_recurso_picker(item) == recurso_id),
                None,
            )
            if item_exato is None:
                try:
                    caixa = page.get_by_placeholder("Pesquisar recursos").first
                    caixa.fill("", timeout=1000)
                    page.wait_for_timeout(700)
                except Exception:
                    pass
                items = listar_thumbnails_em_picker(page)
                item_exato = next(
                    (item for item in items if _identidade_recurso_picker(item) == recurso_id),
                    None,
                )
            if item_exato is None:
                # O Flow pode renovar a URL/identidade interna de um recurso
                # entre sessões. Quando a busca textual retorna exatamente um
                # item, o nome salvo continua sendo uma prova inequívoca.
                termo_normalizado = _limpar_nome_picker(termo_busca).lower()
                candidatos_nome = [
                    item for item in items
                    if termo_normalizado and termo_normalizado[:20] in
                    _limpar_nome_picker(item.text_content() or "").lower()
                ]
                if len(candidatos_nome) == 1:
                    item_exato = candidatos_nome[0]
                    log(f"  ID do recurso mudou; usando correspondência única por nome em '{slot_aria}'")
                else:
                    page.keyboard.press("Escape")
                    raise RuntimeError(
                        f"recurso exato do frame '{slot_aria}' não encontrado no picker"
                    )
            item_exato.click()
            page.wait_for_timeout(500)
            _confirmar_picker_frame(page)
            log(f"  '{slot_aria}' = recurso validado {recurso_id[:45]}... ✓")
            return True

        if not items:
            # Busca não retornou nada — limpar filtro e usar posição como fallback
            log(f"  Picker vazio após busca — limpando filtro, usando posição {position_hint}")
            try:
                caixa = page.get_by_placeholder("Pesquisar recursos").first
                caixa.fill("", timeout=1000)
                page.wait_for_timeout(700)
            except Exception:
                pass
            items = listar_thumbnails_em_picker(page)
            nomes2 = [_limpar_nome_picker(it.text_content() or "") for it in items]
            log(f"  Picker sem filtro: {len(items)} itens — {[n[:25] for n in nomes2[:4]]}")
            if not items:
                log(f"  ⚠  Picker '{slot_aria}' completamente vazio")
                page.keyboard.press("Escape")
                return False
            idx = min(position_hint, len(items) - 1)
            items[idx].click()
        else:
            # Busca encontrou resultado(s) — usar o primeiro (nomes são únicos no Flow)
            items[0].click()

        page.wait_for_timeout(500)
        _confirmar_picker_frame(page)
        log(f"  '{slot_aria}' = '{nome_imagem[:40]}' ✓")
        return True
    except Exception as e:
        log(f"  ⚠  Picker '{slot_aria}' falhou: {e}")
        return False


def _termo_busca_take(take: dict) -> str:
    """Extrai a primeira palavra-chave distinta do conteúdo visual do take para pesquisa no picker."""
    conteudo = take.get("conteudo_visual", "") or take.get("prompt_imagem", "")
    # Pegar primeira palavra com mais de 4 letras que não seja artigo/preposição
    ignorar = {"icon", "with", "text", "line", "over", "side", "the", "and", "for"}
    for palavra in conteudo.split():
        p = palavra.strip(".,;:").lower()
        if len(p) > 4 and p not in ignorar:
            return p
    return conteudo[:10]


def configurar_video_take(page: Page, take: dict, nomes_picker: dict, num_takes: int = 0, **_kwargs):
    """
    Configura e submete o vídeo de um take no modo Frames.
    nomes_picker deve conter {'coringa': str, 'take_1': str, 'take_2': str, ...}
    num_takes: total de takes do roteiro, usado para calcular position_hint por posição
               quando nomes são idênticos (Flow ordena mais-recente-primeiro no picker).
    """
    n = take["numero"]
    log(f"\n[Take {n}] Configurando vídeo...")

    # Garantir modo Frames antes de cada take (reativa se perdeu o estado)
    if not _slots_frames_visiveis(page):
        log("  Slots Início/Fim não visíveis — reativando modo Frames...")
        abrir_modo_frames(page)

    nome_coringa = nomes_picker.get("coringa", "")
    nome_take    = nomes_picker.get(f"take_{n}", "")
    id_coringa   = nomes_picker.get("coringa_id", "")
    id_take      = nomes_picker.get(f"take_{n}_id", "")
    log(f"  Frames: Início='{nome_coringa[:40]}' | Fim='{nome_take[:40]}'")

    # Calcular position_hints considerando que o picker mostra mais-recente-primeiro:
    # ordem geração: coringa(1º) → take_1(2º) → ... → take_M(último)
    # ordem picker:  take_M(índice 0) → ... → take_1(índice M-1) → coringa(índice M)
    total = num_takes or n  # fallback se não informado
    coringa_idx = total     # coringa é sempre o mais antigo = índice total
    take_idx    = total - n  # take_N: mais recente (take_M=0) → mais antigo (take_1=M-1)

    # ── INÍCIO = coringa ───────────────────────────────────────────────────
    log(f"  Definindo Início (coringa)...")
    inicio_ok = _selecionar_frame_por_nome(
        page, "Início", nome_coringa,
        position_hint=coringa_idx, recurso_id=id_coringa,
    )

    # ── FIM = imagem do take ───────────────────────────────────────────────
    log(f"  Definindo Fim (take {n})...")
    fim_ok = _selecionar_frame_por_nome(
        page, "Fim", nome_take,
        position_hint=take_idx, recurso_id=id_take,
    )

    if not inicio_ok or not fim_ok:
        raise RuntimeError(
            f"Take {n} não submetido: frame inicial ou final não foi confirmado"
        )

    # ── Prompt de vídeo ───────────────────────────────────────────────────
    log(f"  Preenchendo prompt...")
    preencher_contenteditable(
        page,
        _prompt_com_regras_visuais(take["prompt_video"]),
    )

    # ── Submeter ──────────────────────────────────────────────────────────
    log(f"  Submetendo vídeo take {n}...")
    page.click('button[aria-label="Iniciar geração"]')
    log(f"  ✓ Take {n} submetido!")

    page.wait_for_timeout(PAUSA_ENTRE_SUBMISSOES_MS)


# ────────────────────────────────────────────────────────────────────────────
# Download
# ────────────────────────────────────────────────────────────────────────────

def _pagina_viva(page: Page) -> bool:
    try:
        page.evaluate("1")
        return True
    except Exception:
        return False


def _restaurar_pagina(page: Page, context, project_id: str):
    """Reabre o projeto no Flow caso a página tenha fechado."""
    try:
        if _pagina_viva(page):
            return page
        pg = context.new_page()
        pg.goto(f"https://flow.google.com/u/0/project/{project_id}")
        pg.wait_for_timeout(2000)
        return pg
    except Exception:
        return page


def _coletar_cards_video(page: Page, max_passes: int = 120) -> list[dict]:
    """Retorna todos os cards de vídeo, do mais recente ao mais antigo.

    A identidade é a URL da miniatura do próprio card. O scan percorre os
    containers roláveis aos poucos e acumula itens já vistos, portanto não
    depende de viewport gigante nem da quantidade de vídeos na galeria.
    """
    return page.evaluate(
        """
        async ({maxPasses}) => {
          const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
          const seen = new Map();
          const findScrollers = () => {
            const result = [document.scrollingElement];
            for (const el of document.querySelectorAll('*')) {
              const style = getComputedStyle(el);
              if (/(auto|scroll)/.test(style.overflowY) &&
                  el.scrollHeight > el.clientHeight + 20) result.push(el);
            }
            return [...new Set(result.filter(Boolean))];
          };
          const collect = () => {
            for (const image of document.querySelectorAll(
                'img[alt="Miniatura do vídeo gerada"], img[alt*="video generated" i]')) {
              const id = image.currentSrc || image.src;
              if (!id || seen.has(id)) continue;
              const card = image.closest('.container') || image.parentElement;
              const title = card?.querySelector('.footer-title')?.textContent?.trim() || '';
              seen.set(id, {id, title});
            }
          };

          const scrollers = findScrollers();
          for (const el of scrollers) el.scrollTop = 0;
          await sleep(250);
          collect();

          let stablePasses = 0;
          for (let pass = 0; pass < maxPasses && stablePasses < 3; pass++) {
            const beforeCount = seen.size;
            let moved = false;
            for (const el of scrollers) {
              const before = el.scrollTop;
              const step = Math.max(500, Math.floor(el.clientHeight * 0.8));
              el.scrollTop = Math.min(before + step, el.scrollHeight);
              if (el.scrollTop !== before) moved = true;
            }
            await sleep(180);
            collect();
            stablePasses = (!moved && seen.size === beforeCount) ? stablePasses + 1 : 0;
          }
          return [...seen.values()];
        }
        """,
        {"maxPasses": max_passes},
    )


def _mapear_cards_para_takes(cards_atuais: list[dict], ids_antes: set[str],
                              num_takes: int) -> dict[int, dict]:
    """Mapeia os cards novos para takes sem usar posição de botão no DOM.

    O Flow insere cards novos no início da galeria. Como a submissão ocorre na
    ordem take_1..take_N, a ordem visual do lote é take_N..take_1.
    """
    novos = [card for card in cards_atuais if card.get("id") not in ids_antes]
    if len(novos) < num_takes:
        raise RuntimeError(
            f"A galeria contém somente {len(novos)} vídeo(s) novo(s), "
            f"mas eram esperados {num_takes}. Nenhum download foi iniciado."
        )
    if len(novos) > num_takes:
        raise RuntimeError(
            f"A galeria contém {len(novos)} vídeos novos, mas o lote esperava "
            f"{num_takes}. Há gerações extras após o snapshot; nenhum download "
            "foi iniciado para evitar numeração incorreta."
        )
    return {
        n_take: novos[num_takes - n_take]
        for n_take in range(1, num_takes + 1)
    }


def _localizar_card_por_id(page: Page, card_id: str, max_passes: int = 120):
    """Rola a galeria até o card identificado pela miniatura exclusiva."""
    seletor = 'img[alt="Miniatura do vídeo gerada"], img[alt*="video generated" i]'
    page.evaluate("""
        () => {
          for (const el of [document.scrollingElement, ...document.querySelectorAll('*')]) {
            if (!el) continue;
            const style = getComputedStyle(el);
            if (el === document.scrollingElement ||
                (/(auto|scroll)/.test(style.overflowY) && el.scrollHeight > el.clientHeight + 20)) {
              el.scrollTop = 0;
            }
          }
        }
    """)
    page.wait_for_timeout(600)

    stable_passes = 0
    for _ in range(max_passes):
        imagens = page.locator(seletor)
        for idx in range(imagens.count()):
            imagem = imagens.nth(idx)
            src = imagem.evaluate("img => img.currentSrc || img.src || ''")
            if src == card_id:
                return imagem.locator("xpath=ancestor::div[contains(@class, 'container')][1]")

        moved = page.evaluate("""
            () => {
              let moved = false;
              for (const el of [document.scrollingElement, ...document.querySelectorAll('*')]) {
                if (!el) continue;
                const style = getComputedStyle(el);
                if (el !== document.scrollingElement &&
                    !(/(auto|scroll)/.test(style.overflowY) && el.scrollHeight > el.clientHeight + 20)) continue;
                const before = el.scrollTop;
                const step = Math.max(500, Math.floor(el.clientHeight * 0.8));
                el.scrollTop = Math.min(before + step, el.scrollHeight);
                if (el.scrollTop !== before) moved = true;
              }
              return moved;
            }
        """)
        page.wait_for_timeout(300)
        if not moved:
            stable_passes += 1
            if stable_passes >= 3:
                break
        else:
            stable_passes = 0
    return None


def baixar_videos_prontos(page: Page, num_takes: int, pasta_saida: Path,
                          project_id: str = "", somente_take: int | None = None):
    """
    Baixa cada vídeo pelo ID exclusivo do card, nunca pela posição do botão.

    O snapshot salvo antes da submissão separa o lote atual de vídeos antigos.
    O manifesto associa cada take ao card e ao hash do arquivo, permitindo
    retomar downloads sem trocar ordem ou aceitar duplicatas.
    """
    import requests as _requests
    import hashlib as _hashlib
    import base64 as _base64

    context = page.context
    log("\n=== Download dos vídeos ===")

    def _get_cookies(pg):
        try:
            return {c["name"]: c["value"] for c in context.cookies()}
        except Exception:
            return {}

    def _md5(path):
        return _hashlib.md5(Path(path).read_bytes()).hexdigest()

    # Script de bloqueio window.close + interceptor blob (injetado antes de cada take)
    _JS_BLOCK_AND_BLOB = """
        () => {
            // Bloquear window.close
            try {
                Object.defineProperty(window, 'close', {
                    value: function(){ console.log('[flow-dl] window.close blocked'); },
                    writable: false, configurable: false
                });
            } catch(e) {
                window.close = function(){ console.log('[flow-dl] window.close blocked (assign)'); };
            }
            // Interceptar createObjectURL para capturar blob de vídeo
            if (!window.__blobIntercepted) {
                window.__blobIntercepted = true;
                window.__blobBase64 = null;
                const _orig = URL.createObjectURL.bind(URL);
                URL.createObjectURL = function(obj) {
                    const url = _orig(obj);
                    if (obj instanceof Blob && obj.type && obj.type.includes('video')) {
                        const reader = new FileReader();
                        reader.onloadend = function() {
                            window.__blobBase64 = reader.result;
                        };
                        reader.readAsDataURL(obj);
                    }
                    return url;
                };
            } else {
                window.__blobBase64 = null;  // zerando para o próximo take
            }
        }
    """

    baixados = 0
    pg = page  # página atual (pode ser restaurada)
    _global_seen_hashes: dict = {}
    baseline_path = pasta_saida / "videos_antes.json"
    manifest_path = pasta_saida / "videos_download_manifest.json"
    try:
        baseline_data = json.loads(baseline_path.read_text(encoding="utf-8"))
        ids_antes = set(baseline_data.get("ids", []))
    except Exception:
        raise RuntimeError(
            f"Snapshot do lote não encontrado em {baseline_path}. "
            "O script não escolherá vídeos por posição sem essa prova de identidade. "
            "Execute a geração completa para criar um novo snapshot."
        )

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        manifest = {"project_id": project_id, "takes": {}}

    ir_para_aba(pg, "Vídeos")
    pg.wait_for_timeout(2000)
    cards_atuais = _coletar_cards_video(pg)
    mapa_explicito_path = pasta_saida / "videos_card_map.json"
    if mapa_explicito_path.exists():
        mapa_ids = json.loads(mapa_explicito_path.read_text(encoding="utf-8"))
        cards_por_id = {card.get("id"): card for card in cards_atuais}
        mapa_cards = {}
        for n_take in range(1, num_takes + 1):
            card_id = mapa_ids.get(str(n_take), "")
            card = cards_por_id.get(card_id)
            if card is None:
                raise RuntimeError(
                    f"Card explícito do take {n_take} não foi encontrado; nenhum download iniciado"
                )
            mapa_cards[n_take] = card
        log(f"  Mapeamento explícito validado em {mapa_explicito_path}")
    else:
        mapa_cards = _mapear_cards_para_takes(cards_atuais, ids_antes, num_takes)
    log(f"  {len(cards_atuais)} card(s) encontrados; {num_takes} associado(s) ao lote atual.")

    for n_take in range(1, num_takes + 1):
        if somente_take is not None and n_take != somente_take:
            continue
        nome_arquivo = pasta_saida / f"take_{n_take}.mp4"
        arquivo_parcial = pasta_saida / f"take_{n_take}.mp4.part"
        card = mapa_cards[n_take]
        card_id = card["id"]
        registro = manifest.get("takes", {}).get(str(n_take), {})

        # Só reutilizar arquivo quando o manifesto comprova card e hash.
        if (nome_arquivo.exists() and nome_arquivo.stat().st_size > 50_000 and
                registro.get("card_id") == card_id and
                registro.get("md5") == _md5(nome_arquivo)):
            _global_seen_hashes[registro["md5"]] = n_take
            baixados += 1
            log(f"  take_{n_take}.mp4 já validado para este card — pulando")
            continue
        if arquivo_parcial.exists():
            arquivo_parcial.unlink()

        # ── Restaurar página se necessário ───────────────────────────────────
        if not _pagina_viva(pg):
            log(f"  [take {n_take}] Página morta — restaurando...")
            pg = _restaurar_pagina(pg, context, project_id)
            pg.wait_for_timeout(2000)

        if not _pagina_viva(pg):
            log(f"  ⚠ Não foi possível restaurar a página para take_{n_take}")
            continue

        # ── Navegar fresho para aba Vídeos (limpa requests background) ───────
        try:
            ir_para_aba(pg, "Vídeos")
            pg.wait_for_timeout(2500)
        except Exception as e_aba:
            log(f"  ⚠ Erro ao navegar para aba Vídeos (take {n_take}): {e_aba}")
            continue

        # Reencontrar o card pela miniatura exclusiva. Se estiver virtualizado,
        # o coletor percorre toda a rolagem e deixa os cards carregados no DOM.
        _coletar_cards_video(pg)
        card_locator = _localizar_card_por_id(pg, card_id)
        if card_locator is None or card_locator.count() == 0:
            log(f"  ⚠ Card do take_{n_take} não encontrado pelo ID; abortando sem adivinhar posição")
            continue

        log(f"  take_{n_take}.mp4 ← card '{card.get('title', '')[:55]}'")

        _download_ok = False
        _cdn_holder: list = []

        def _restaurar_pos_dup():
            nonlocal pg
            if not _pagina_viva(pg):
                pg = _restaurar_pagina(pg, context, project_id)
                try:
                    pg.wait_for_timeout(2000)
                    ir_para_aba(pg, "Vídeos")
                    pg.wait_for_timeout(1500)
                    _coletar_cards_video(pg)
                except Exception:
                    pass

        # Uma única tentativa no card identificado. Não há fallback por posição,
        # pois baixar um take errado é pior do que reportar a falha.
        for _ in range(1):
            if not _pagina_viva(pg):
                log("    ⚠ Página morreu antes do download")
                break

            _cdn_holder.clear()

            def _on_req(req, _h=_cdn_holder):
                url = req.url
                if "flow-content" in url and ("/video/" in url or ".mp4" in url):
                    _h.append(url)
            pg.on("request", _on_req)

            try:
                btn = card_locator.locator('button[aria-label="Mais opções"]').first
                btn.scroll_into_view_if_needed(timeout=5000)
                btn.hover(force=True, timeout=4000)
                pg.wait_for_timeout(300)
                btn.click(force=True, timeout=4000)
                pg.wait_for_timeout(800)

                # Verificar se é botão de vídeo
                item_dl = None
                for texto_dl in ["Fazer o download", "Fazer download", "Download"]:
                    try:
                        c = pg.get_by_text(texto_dl, exact=True).first
                        if c.is_visible():
                            item_dl = c
                            break
                    except Exception:
                        continue

                if item_dl is None:
                    menu_diag = pg.evaluate("""() => Array.from(document.querySelectorAll(
                        '[role="menu"] *, [role="menuitem"], .cdk-overlay-pane *'
                    )).filter(el => el.offsetParent !== null && el.children.length === 0)
                      .map(el => (el.textContent || '').trim())
                      .filter(Boolean).slice(0, 40)""")
                    card_diag = card_locator.inner_text(timeout=2000)
                    log(f"    [diag] card identificado sem opção de download; "
                        f"card={card_diag[:180]!r}; menu={menu_diag}")
                    # Alguns cards reproduzíveis não abrem o menu de download.
                    # Abrir o card exato permite capturar a mesma URL CDN usada
                    # pelo player, sem recorrer a outro card ou à posição.
                    try:
                        pg.keyboard.press("Escape")
                        _cdn_holder.clear()
                        clicou_play = card_locator.evaluate("""el => {
                            const icone = Array.from(el.querySelectorAll('*')).find(
                              n => (n.textContent || '').trim() === 'play_circle');
                            const alvo = icone?.closest('button') || icone || el;
                            alvo.click();
                            return !!icone;
                        }""")
                        log(f"    [diag] controle play interno acionado={clicou_play}")
                        for _espera in range(20):
                            pg.wait_for_timeout(500)
                            if _cdn_holder:
                                break
                        if not _cdn_holder:
                            urls_player = pg.evaluate("""() => {
                                const urls = [];
                                document.querySelectorAll('video, video source').forEach(el => {
                                  const u = el.currentSrc || el.src || el.getAttribute('src') || '';
                                  if (u && !u.startsWith('blob:')) urls.push(u);
                                });
                                performance.getEntriesByType('resource').forEach(e => {
                                  if (e.name.includes('flow-content') &&
                                      (e.name.includes('/video/') || e.name.includes('.mp4'))) {
                                    urls.push(e.name);
                                  }
                                });
                                return [...new Set(urls)];
                            }""")
                            _cdn_holder.extend(urls_player)
                        if _cdn_holder:
                            cdn_player = _cdn_holder[-1]
                            resposta = _requests.get(cdn_player, timeout=60, verify=False)
                            resposta.raise_for_status()
                            arquivo_parcial.write_bytes(resposta.content)
                            if arquivo_parcial.stat().st_size <= 50_000:
                                raise RuntimeError("mídia capturada do player é pequena demais")
                            hash_atual = _md5(arquivo_parcial)
                            if hash_atual in _global_seen_hashes:
                                raise RuntimeError(
                                    f"mídia duplicada do take {_global_seen_hashes[hash_atual]}"
                                )
                            arquivo_parcial.replace(nome_arquivo)
                            _global_seen_hashes[hash_atual] = n_take
                            manifest.setdefault("takes", {})[str(n_take)] = {
                                "card_id": card_id,
                                "title": card.get("title", ""),
                                "md5": hash_atual,
                                "bytes": nome_arquivo.stat().st_size,
                            }
                            manifest_path.write_text(
                                json.dumps(manifest, ensure_ascii=False, indent=2),
                                encoding="utf-8",
                            )
                            baixados += 1
                            _download_ok = True
                            log(f"    → salvo ({nome_arquivo.stat().st_size // 1024}KB) via player CDN ✓")
                        else:
                            log("    [diag] player abriu, mas não expôs URL de mídia")
                    except Exception as exc_player:
                        log(f"    [diag] captura pelo player falhou: {exc_player}")
                    pg.keyboard.press("Escape")
                    pg.wait_for_timeout(400)
                    try:
                        pg.remove_listener("request", _on_req)
                    except Exception:
                        pass
                    break

                log("    Card de vídeo confirmado ✓")

                # Injetar blob interceptor + bloquear window.close
                try:
                    pg.evaluate(_JS_BLOCK_AND_BLOB)
                except Exception:
                    pass

                # Hover em "Fazer o download" para abrir submenu de qualidade
                try:
                    item_dl.hover(timeout=3000)
                except Exception:
                    pass
                pg.wait_for_timeout(800)

                # O Flow nem sempre abre o submenu de qualidade apenas com
                # hover depois do primeiro download do lote. Nesse estado, o
                # item continua visível, mas "720p" nunca é montado no DOM.
                # Um clique no mesmo item abre o submenu sem escolher arquivo.
                if not any(el.is_visible() for el in pg.get_by_text("720p", exact=True).all()):
                    try:
                        item_dl.click(timeout=3000)
                        pg.wait_for_timeout(800)
                    except Exception:
                        pass

                # Limpar CDN holder — só capturar URL gerada PELO clique 720p
                _cdn_holder.clear()

                # Clicar 720p
                log(f"    Clicando 720p...")
                todos_720 = [el for el in pg.get_by_text("720p", exact=True).all() if el.is_visible()]
                log(f"    [diag] {len(todos_720)} elemento(s) '720p' visíveis")
                if todos_720:
                    todos_720[-1].click(timeout=5000)
                else:
                    pg.get_by_text("720p", exact=True).last.click(timeout=5000)

                # Aguardar CDN URL ou blob (up to 8s)
                try:
                    for _ in range(16):
                        pg.wait_for_timeout(500)
                        if _cdn_holder:
                            break
                        try:
                            b64 = pg.evaluate("() => window.__blobBase64")
                            if b64:
                                break
                        except Exception:
                            break
                except Exception:
                    pass

                try:
                    pg.remove_listener("request", _on_req)
                except Exception:
                    pass

                # Verificar capturas
                cdn_url = None
                blob_b64 = None
                if _cdn_holder:
                    cdn_url = _cdn_holder[0]  # primeiro URL após o clique 720p
                    log(f"    [diag] CDN URL via request: {cdn_url[:80]}...")
                try:
                    blob_b64 = pg.evaluate("() => window.__blobBase64")
                except Exception:
                    blob_b64 = None

                salvo = False

                # Método 1: blob
                if blob_b64 and isinstance(blob_b64, str) and "base64," in blob_b64:
                    try:
                        raw = _base64.b64decode(blob_b64.split("base64,")[1])
                        if len(raw) > 50_000:
                            arquivo_parcial.write_bytes(raw)
                            sz = arquivo_parcial.stat().st_size
                            log(f"    → salvo ({sz // 1024}KB) via blob ✓")
                            salvo = True
                    except Exception as e_blob:
                        log(f"    ⚠ Erro ao salvar blob: {e_blob}")

                # Método 2: CDN URL via requests
                if not salvo and cdn_url:
                    try:
                        cookies = _get_cookies(pg)
                        resp = _requests.get(cdn_url, cookies=cookies, timeout=120, verify=False, stream=True)
                        resp.raise_for_status()
                        with open(str(arquivo_parcial), "wb") as _f:
                            for _chunk in resp.iter_content(chunk_size=65536):
                                _f.write(_chunk)
                        sz = arquivo_parcial.stat().st_size
                        if sz < 50_000:
                            raise RuntimeError(f"Arquivo muito pequeno: {sz} bytes")
                        log(f"    → salvo ({sz // 1024}KB) via cdn_request ✓")
                        salvo = True
                    except Exception as e_cdn:
                        log(f"    ⚠ Erro no download CDN: {e_cdn}")
                        if arquivo_parcial.exists() and arquivo_parcial.stat().st_size < 50_000:
                            try:
                                arquivo_parcial.unlink()
                            except Exception:
                                pass

                if not salvo:
                    log(f"    ⚠ Nenhum método funcionou para take_{n_take}")
                    _restaurar_pos_dup()
                    break

                hash_video = _md5(arquivo_parcial)
                if hash_video in _global_seen_hashes:
                    duplicado_de = _global_seen_hashes[hash_video]
                    arquivo_parcial.unlink(missing_ok=True)
                    log(f"    ⚠ Conteúdo duplicado do take_{duplicado_de}; arquivo rejeitado")
                    break

                arquivo_parcial.replace(nome_arquivo)
                _global_seen_hashes[hash_video] = n_take
                manifest.setdefault("takes", {})[str(n_take)] = {
                    "card_id": card_id,
                    "title": card.get("title", ""),
                    "md5": hash_video,
                    "bytes": nome_arquivo.stat().st_size,
                }
                manifest_path.write_text(
                    json.dumps(manifest, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                baixados += 1

                _download_ok = True
                break  # sucesso

            except Exception as e_scan:
                log(f"    ⚠ Erro ao baixar card do take_{n_take}: {e_scan}")
                try:
                    pg.remove_listener("request", _on_req)
                except Exception:
                    pass
                try:
                    pg.keyboard.press("Escape")
                    pg.wait_for_timeout(300)
                except Exception:
                    pass

        if not _download_ok:
            log(f"    ⚠ take_{n_take} não baixado; nenhum card alternativo foi usado")
            continue

        # ── Restaurar página para o próximo take ──────────────────────────────
        if not _pagina_viva(pg):
            log(f"  [take {n_take}] Página fechou após download — restaurando para o próximo take...")
            pg = _restaurar_pagina(pg, context, project_id)
            try:
                pg.wait_for_timeout(2000)
            except Exception:
                pass
            if not _pagina_viva(pg):
                log(f"  ⚠ Contexto do browser morreu — não é possível continuar na mesma sessão")
                log(f"  Re-execute com --apenas-videos para baixar os takes restantes")
                break

    log(f"\n  {baixados}/{num_takes} vídeos baixados.")


# ────────────────────────────────────────────────────────────────────────────
# Main
# ────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Automação Google Flow — geração de imagens e vídeos para vídeo-aulas"
    )
    parser.add_argument("--setup-session", action="store_true",
                        help="Login manual uma vez → salva sessão para runs futuros")
    parser.add_argument("--roteiro", default=None,
                        help="Caminho para roteiro.json (ex: output/projeto/roteiro.json)")
    parser.add_argument("--project-id", default=None,
                        help="ID do projeto no Google Flow (ex: c8026a66-92c0-4ed8-9347-3dd0bd0e3e3d)")
    parser.add_argument("--profile", default=CHROME_PROFILE,
                        help=f"Pasta do perfil Chrome (padrão: {CHROME_PROFILE})")
    parser.add_argument("--apenas-videos", action="store_true",
                        help="Pular geração de imagens (usar as que já estão na galeria)")
    parser.add_argument("--refazer-videos", action="store_true",
                        help="Pular geração de imagens mas re-submeter configurações de vídeo (usa nomes_picker.json existente)")
    parser.add_argument("--pausar-imagens", action="store_true",
                        help="Pausar após cada geração de imagem para seleção manual")
    parser.add_argument("--so-download", action="store_true",
                        help="Pular geração e ir direto para o download dos vídeos")
    parser.add_argument("--download-take", type=int, default=None,
                        help="Com --so-download, baixar somente este número de take")
    parser.add_argument("--listar-videos", action="store_true",
                        help="Listar os cards de vídeo atuais do projeto e sair")
    parser.add_argument("--listar-imagens", action="store_true",
                        help="Listar os recursos de imagem atuais do projeto e sair")
    parser.add_argument("--refazer-take", type=int, default=None,
                        help="Re-submeter somente um take de vídeo usando os frames já salvos")
    parser.add_argument("--refazer-imagem-take", type=int, default=None,
                        help="Regenerar somente o frame final de um take e atualizar nomes_picker.json")
    parser.add_argument("--auto", action="store_true",
                        help="Modo automático: gera coringa + imagens + vídeos sem input() interativo")
    parser.add_argument("--headless", action="store_true",
                        help="Rodar sem janela (não recomendado para uso inicial)")
    parser.add_argument("--usar-chrome-logado", action="store_true",
                        help="Usar diretamente o perfil Chrome autenticado; requer fechar o Chrome comum")
    args = parser.parse_args()

    # ── Modo setup de sessão ──────────────────────────────────────────────
    if args.setup_session:
        with sync_playwright() as p:
            if args.roteiro and (args.so_download or args.refazer_videos):
                roteiro_path = Path(args.roteiro)
                if not roteiro_path.exists():
                    parser.error(f"roteiro não encontrado: {roteiro_path}")
                roteiro_setup = json.loads(roteiro_path.read_text(encoding="utf-8"))
                pasta_setup = roteiro_path.parent
                _configurar_chrome_download_dir(pasta_setup)

                def _retomar_download_na_sessao(page, _context):
                    project_id = args.project_id
                    if not project_id:
                        project_file = pasta_setup / "project_id.txt"
                        if project_file.exists():
                            project_id = project_file.read_text(encoding="utf-8").strip()
                    if not project_id:
                        raise RuntimeError("--project-id é obrigatório para retomar o download")
                    abrir_projeto(page, project_id)
                    page.wait_for_timeout(2000)

                    if args.refazer_videos:
                        log("\n=== Recuperação na mesma sessão: refazendo lote de vídeos ===")
                        ir_para_aba(page, "Vídeos")
                        page.wait_for_timeout(1500)
                        cards_antes = _coletar_cards_video(page)
                        (pasta_setup / "videos_antes.json").write_text(
                            json.dumps({
                                "project_id": project_id,
                                "ids": [card["id"] for card in cards_antes],
                                "count": len(cards_antes),
                            }, ensure_ascii=False, indent=2),
                            encoding="utf-8",
                        )
                        log(f"Snapshot salvo: {len(cards_antes)} vídeo(s) existentes antes do novo lote")
                        definir_configuracoes_video(page)
                        nomes_path = pasta_setup / "nomes_picker.json"
                        nomes_picker = json.loads(nomes_path.read_text(encoding="utf-8"))
                        for take in roteiro_setup["takes"]:
                            configurar_video_take(
                                page,
                                take=take,
                                nomes_picker=nomes_picker,
                                num_takes=roteiro_setup["num_takes"],
                            )
                        log("✓ Novo lote submetido; aguardando os renders...")
                        aguardar_videos_prontos(page, roteiro_setup["num_takes"])

                    baixar_videos_prontos(
                        page,
                        roteiro_setup["num_takes"],
                        pasta_setup,
                        project_id=project_id,
                        somente_take=args.download_take,
                    )

                setup_session(p, after_login=_retomar_download_na_sessao)
            else:
                setup_session(p)
        return

    if not args.roteiro:
        parser.error("--roteiro é obrigatório (use --setup-session para configurar a sessão)")

    # ── Ler roteiro ───────────────────────────────────────────────────────
    roteiro_path = Path(args.roteiro)
    if not roteiro_path.exists():
        log(f"ERRO: roteiro não encontrado: {roteiro_path}")
        sys.exit(1)

    roteiro = json.loads(roteiro_path.read_text(encoding="utf-8"))
    pasta_saida = roteiro_path.parent
    takes = roteiro["takes"]
    num_takes = roteiro["num_takes"]

    log(f"\n{'='*50}")
    log(f"Google Flow Automation — {roteiro['titulo']}")
    log(f"  Proporção: {ASPECT_RATIO}")
    log(f"  Takes: {num_takes}")
    log(f"  Pasta de saída: {pasta_saida}")
    log(f"  Projeto Flow: {args.project_id or '(novo — será criado automaticamente)'}")
    log(f"  Perfil Chrome: {args.profile}")
    log(f"{'='*50}\n")

    # ── Iniciar browser com perfil persistente ───────────────────────────
    if not args.usar_chrome_logado and not FLOW_PROFILE_DIR.exists():
        log(f"ERRO: perfil não encontrado em {FLOW_PROFILE_DIR}")
        log("Execute primeiro: python flow_automation.py --setup-session")
        sys.exit(1)

    if args.usar_chrome_logado:
        log(f"Usando a sessão autenticada do Chrome ({args.profile})...")
    else:
        log(f"Abrindo Chrome com perfil persistente ({FLOW_PROFILE_DIR.name})...")
        _configurar_chrome_download_dir(pasta_saida)
    with sync_playwright() as p:
        if args.usar_chrome_logado:
            context = _abrir_contexto_chrome_logado(p, args.profile, headless=args.headless)
        else:
            context = _abrir_contexto_persistente(p, headless=args.headless)

        page = context.pages[0] if context.pages else context.new_page()
        page.set_default_timeout(60000)

        # Validar a conta antes de criar projeto ou gastar créditos.
        try:
            # A raiz do Flow pode redirecionar contas válidas para /about.
            # Quando já conhecemos o projeto, validar a sessão diretamente nele
            # é mais confiável e evita falsos pedidos de login.
            url_validacao = (
                f"{FLOW_BASE_URL}/{ACCOUNT_SLOT}/project/{args.project_id}"
                if args.project_id else f"{FLOW_BASE_URL}/{ACCOUNT_SLOT}/"
            )
            page.goto(url_validacao, wait_until="domcontentloaded", timeout=60000)
        except Exception:
            pass
        # A interface nova pode redirecionar até contas autenticadas para a
        # landing /about. Entrar pelo CTA oficial antes de concluir logout.
        if "/about" in page.url:
            for seletor in [
                'a:has-text("Crie com o Google Flow")',
                'button:has-text("Crie com o Google Flow")',
                'a:has-text("Create with Google Flow")',
                'button:has-text("Create with Google Flow")',
            ]:
                try:
                    page.locator(seletor).first.click(timeout=5000)
                    page.wait_for_timeout(5000)
                    log(f"  Entrada no estúdio pelo CTA da landing ✓")
                    break
                except Exception:
                    continue
        if not _flow_esta_autenticado(page, timeout=20000):
            try:
                log(f"  [auth diag] URL: {page.url}")
                log(f"  [auth diag] título: {page.title()}")
                texto_diag = page.locator("body").inner_text(timeout=3000)
                log(f"  [auth diag] página: {texto_diag[:500].replace(chr(10), ' | ')}")
                page.screenshot(path=str(Path(__file__).parent / "auth_diagnostic.png"))
            except Exception:
                pass
            context.close()
            raise RuntimeError(
                "Conta Google não autenticada neste perfil. Rode --setup-session "
                "ou use --usar-chrome-logado com o Profile 3."
            )
        log("  Sessão do Google Flow autenticada ✓")

        # ── Abrir projeto ─────────────────────────────────────────────────
        project_id_path = pasta_saida / "project_id.txt"
        # Para --apenas-videos / --refazer-videos sem --project-id, reutilizar o projeto salvo
        if (args.apenas_videos or args.refazer_videos or args.so_download) and not args.project_id and project_id_path.exists():
            saved_id = project_id_path.read_text(encoding="utf-8").strip()
            log(f"--apenas-videos: reutilizando projeto salvo {saved_id}")
            project_id = saved_id
        else:
            project_id = args.project_id or criar_projeto_automatico(page)
        abrir_projeto(page, project_id)
        page.wait_for_timeout(2000)
        # Persistir project_id para uso com --apenas-videos ou --so-download futuros
        project_id_path.write_text(project_id, encoding="utf-8")

        if args.listar_imagens:
            recursos = _recursos_imagem_no_picker(page)
            recursos_path = pasta_saida / "imagens_recursos.json"
            recursos_path.write_text(
                json.dumps(recursos, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            log(f"\n=== {len(recursos)} recurso(s) de imagem no projeto ===")
            for indice, recurso in enumerate(recursos, 1):
                log(f"  {indice}. {recurso.get('nome', '')} | {recurso.get('id', '')[:80]}")
            log(f"  Lista completa salva em {recursos_path}")
            context.close()
            return

        if args.listar_videos:
            ir_para_aba(page, "Vídeos")
            page.wait_for_timeout(1500)
            cards = _coletar_cards_video(page)
            cards_path = pasta_saida / "videos_cards.json"
            cards_path.write_text(
                json.dumps(cards, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            log(f"\n=== {len(cards)} card(s) de vídeo no projeto ===")
            for indice, card in enumerate(cards, 1):
                log(f"  {indice}. {card.get('title', '')} | {card.get('id', '')[:80]}")
            log(f"  Lista completa salva em {cards_path}")
            context.close()
            return

        if args.refazer_imagem_take is not None:
            numero = args.refazer_imagem_take
            if numero < 1 or numero > num_takes:
                context.close()
                raise RuntimeError(f"--refazer-imagem-take deve estar entre 1 e {num_takes}")
            nomes_path = pasta_saida / "nomes_picker.json"
            nomes_picker = json.loads(nomes_path.read_text(encoding="utf-8"))
            take = next(t for t in takes if t["numero"] == numero)
            log(f"\n=== Refazendo somente o frame final do take {numero} ===")
            recurso = gerar_imagens_take(
                page,
                prompt=take["prompt_imagem"],
                num_imagens=1,
                nome_coringa=nomes_picker.get("coringa", ""),
                id_coringa=nomes_picker.get("coringa_id", ""),
            )
            nomes_picker[f"take_{numero}"] = recurso["nome"] or "Sem título"
            nomes_picker[f"take_{numero}_id"] = recurso["id"]
            nomes_path.write_text(
                json.dumps(nomes_picker, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            log(f"✓ Frame do take {numero} salvo em {nomes_path}")
            context.close()
            return

        if args.refazer_take is not None:
            numero = args.refazer_take
            if numero < 1 or numero > num_takes:
                context.close()
                raise RuntimeError(f"--refazer-take deve estar entre 1 e {num_takes}")
            nomes_path = pasta_saida / "nomes_picker.json"
            if not nomes_path.exists():
                context.close()
                raise RuntimeError(f"Nomes dos frames não encontrados em {nomes_path}")
            nomes_picker = json.loads(nomes_path.read_text(encoding="utf-8"))
            take = next(t for t in takes if t["numero"] == numero)
            log(f"\n=== Refazendo somente o take {numero} ===")
            definir_configuracoes_video(page)
            configurar_video_take(page, take=take, nomes_picker=nomes_picker, num_takes=num_takes)
            log(f"\n✓ Take {numero} re-submetido. Os demais não foram alterados.")
            context.close()
            return

        # ── Modo só-download ──────────────────────────────────────────────
        if args.so_download:
            baixar_videos_prontos(
                page, num_takes, pasta_saida,
                project_id=project_id, somente_take=args.download_take,
            )
            context.close()
            return

        # --apenas-videos / --refazer-videos implicam modo automático (sem input() interativo)
        auto = args.auto or args.apenas_videos or args.refazer_videos

        nomes_path = pasta_saida / "nomes_picker.json"

        # ── Etapa 2a: Imagens ─────────────────────────────────────────────
        if not args.apenas_videos and not args.refazer_videos:
            log("=== ETAPA 2a: Geração de Imagens ===\n")
            nomes_gerados: dict = {}
            nomes_conhecidos: set = set()

            # Gerar coringa primeiro (container de referência)
            recurso_coringa = None
            if nomes_path.exists():
                try:
                    checkpoint = json.loads(nomes_path.read_text(encoding="utf-8"))
                    checkpoint_id = _normalizar_id_recurso(
                        checkpoint.get("coringa_id", "")
                    )
                    checkpoint_nome = checkpoint.get("coringa", "").replace("…", "")[:24]
                    recursos_atuais = _recursos_imagem_no_picker(page)
                    recurso_coringa = next(
                        (r for r in recursos_atuais if r["id"] == checkpoint_id), None
                    )
                    if recurso_coringa is None and checkpoint_nome:
                        recurso_coringa = next(
                            (r for r in recursos_atuais
                             if checkpoint_nome in r.get("nome", "")), None
                        )
                    if recurso_coringa:
                        log("[Coringa] Reutilizando checkpoint validado no picker ✓")
                except Exception:
                    recurso_coringa = None
            if recurso_coringa is None:
                log("[Coringa] Gerando imagem coringa...")
                log(f"  {roteiro['prompt_imagem_coringa'][:100]}...")
                try:
                    recurso_coringa = gerar_imagens_take(
                        page,
                        prompt=roteiro["prompt_imagem_coringa"],
                        num_imagens=1,
                        pausar=not auto,
                        nome_coringa="",
                    )
                    log("[Coringa] Imagem coringa gerada ✓\n")
                except GeracaoFalhouError:
                    log("[Coringa] Flow bloqueou o fundo vazio; usando PNG branco local...")
                    recurso_coringa = enviar_coringa_branca(page, pasta_saida)
                    log("[Coringa] Imagem coringa enviada ✓\n")
            nome_coringa_ref = recurso_coringa["nome"] or "Sem título"
            id_coringa_ref = recurso_coringa["id"]
            nomes_gerados["coringa"] = nome_coringa_ref
            nomes_gerados["coringa_id"] = id_coringa_ref
            nomes_path.write_text(
                json.dumps(nomes_gerados, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            nomes_conhecidos.add(nome_coringa_ref)
            log(f"[Coringa] Recurso validado: '{nome_coringa_ref}' ({id_coringa_ref[:45]}...) ✓")

            if args.pausar_imagens and not auto:
                # Modo manual: sequencial com pausa para seleção humana
                for take in takes:
                    n = take["numero"]
                    log(f"[Take {n}/{num_takes}] Gerando imagem (referência: '{nome_coringa_ref[:30]}')...")
                    log(f"  {take['prompt_imagem'][:100]}...")
                    recurso_take = gerar_imagens_take(
                        page,
                        prompt=take["prompt_imagem"],
                        num_imagens=1,
                        pausar=True,
                        nome_coringa=nome_coringa_ref,
                        id_coringa=id_coringa_ref,
                    )
                    nome_take = recurso_take["nome"] or "Sem título"
                    nomes_gerados[f"take_{n}"] = nome_take
                    nomes_gerados[f"take_{n}_id"] = recurso_take["id"]
                    nomes_conhecidos.add(nome_take)
                    log(f"[Take {n}] Nome registrado: '{nome_take}' ✓\n")
            else:
                # Submeter todos primeiro: o Flow pode processar os frames finais em
                # paralelo. A associação usa os IDs novos e a ordem FIFO do picker.
                recursos_antes = _recursos_imagem_no_picker(page)
                ids_antes = {recurso["id"] for recurso in recursos_antes}
                falhas_antes = _contar_falhas_na_pagina(page)
                for take in takes:
                    n = take["numero"]
                    log(f"[Take {n}/{num_takes}] Submetendo frame final em lote...")
                    log(f"  {take['prompt_imagem'][:100]}...")
                    try:
                        _submeter_imagem(
                            page,
                            prompt=take["prompt_imagem"],
                            num_imagens=1,
                            nome_coringa=nome_coringa_ref,
                            id_coringa=id_coringa_ref,
                        )
                    except RuntimeError as exc:
                        if "coringa exata" not in str(exc):
                            raise
                        log("  Coringa saiu da janela recente; regenerando uma equivalente...")
                        recurso_coringa = gerar_imagens_take(
                            page,
                            prompt=roteiro["prompt_imagem_coringa"],
                            num_imagens=1,
                            nome_coringa="",
                        )
                        nome_coringa_ref = recurso_coringa["nome"] or "Sem título"
                        id_coringa_ref = recurso_coringa["id"]
                        # A coringa auxiliar não pode entrar no mapeamento take→imagem.
                        ids_antes.add(id_coringa_ref)
                        nomes_gerados["coringa"] = nome_coringa_ref
                        nomes_gerados["coringa_id"] = id_coringa_ref
                        nomes_path.write_text(
                            json.dumps(nomes_gerados, ensure_ascii=False, indent=2),
                            encoding="utf-8",
                        )
                        _submeter_imagem(
                            page,
                            prompt=take["prompt_imagem"],
                            num_imagens=1,
                            nome_coringa=nome_coringa_ref,
                            id_coringa=id_coringa_ref,
                        )
                    page.wait_for_timeout(400)

                log(f"\n[Lote] {num_takes} frames submetidos; aguardando em paralelo...")
                recursos_novos = _aguardar_lote_recursos(
                    page, ids_antes, falhas_antes, num_takes,
                    timeout_s=max(300, num_takes * 90),
                )
                # Picker: mais recente primeiro; fila de submissão: take 1 primeiro.
                recursos_por_take = list(reversed(recursos_novos))
                for take, recurso_take in zip(takes, recursos_por_take):
                    n = take["numero"]
                    nome_take = recurso_take["nome"] or "Sem título"
                    nomes_gerados[f"take_{n}"] = nome_take
                    nomes_gerados[f"take_{n}_id"] = recurso_take["id"]
                    nomes_conhecidos.add(nome_take)
                    log(f"[Take {n}] Recurso validado: '{nome_take}' ✓\n")

            # Salvar nomes para uso posterior com --apenas-videos
            nomes_path.write_text(
                __import__("json").dumps(nomes_gerados, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
            log(f"Nomes salvos em {nomes_path}")

            if not auto:
                log("\nIMPORTANTE: Selecione a melhor imagem de cada take na galeria antes de continuar.")
                log("Pressione Enter quando estiver pronto para gerar os vídeos...")
                input()
            else:
                log("\nModo auto: aguardando 5s para a galeria atualizar...")
                page.wait_for_timeout(5000)

        # ── Etapa 2b: Vídeos ──────────────────────────────────────────────
        if not args.apenas_videos:
            log("\n=== ETAPA 2b: Geração de Vídeos ===")
            if args.refazer_videos:
                log("Modo --refazer-videos: re-submetendo configurações de vídeo com nomes corrigidos...\n")
            else:
                log("Modo Frames (Início=coringa, Fim=take), submetendo em fila...\n")

            # Snapshot dos vídeos já existentes. Depois do lote, somente cards
            # ausentes deste snapshot poderão ser associados aos takes.
            ir_para_aba(page, "Vídeos")
            page.wait_for_timeout(1500)
            cards_antes = _coletar_cards_video(page)
            videos_antes_path = pasta_saida / "videos_antes.json"
            videos_antes_path.write_text(
                json.dumps({
                    "project_id": project_id,
                    "ids": [card["id"] for card in cards_antes],
                    "count": len(cards_antes),
                }, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            log(f"Snapshot salvo: {len(cards_antes)} vídeo(s) existentes antes do lote")

            # Ativar modo Frames (Início + Fim)
            definir_configuracoes_video(page)

            if not auto:
                log("\n⚠  ATENÇÃO: Confirme que as imagens foram geradas corretamente antes de continuar.")
                log("   Pressione Enter para iniciar a geração dos vídeos...")
                input()

            # Carregar nomes do arquivo salvo durante geração de imagens
            nomes_picker: dict = {}
            if nomes_path.exists():
                import json as _json
                nomes_picker = _json.loads(nomes_path.read_text(encoding="utf-8"))
                log(f"\nNomes carregados de {nomes_path}: {nomes_picker}")
            else:
                # Fallback: descobrir pelo picker (menos confiável com imagens de runs anteriores)
                log("\n⚠ Arquivo de nomes não encontrado — descobrindo pelo picker (menos confiável)...")
                nomes_picker = descobrir_nomes_picker(page, len(takes))

            for take in takes:
                configurar_video_take(page, take=take, nomes_picker=nomes_picker, num_takes=num_takes)

            log("\n✓ Todos os vídeos submetidos!")
            log("O Flow processa em fila. Aguarde a conclusão antes de baixar.\n")

        # ── Download ──────────────────────────────────────────────────────
        if args.apenas_videos:
            log("\n=== Download direto (--apenas-videos) ===")
        elif args.refazer_videos:
            log(f"\n=== Aguardando render dos vídeos (poll inteligente) ===")
            aguardar_videos_prontos(page, num_takes)
        elif not auto:
            log("Pressione Enter quando todos os vídeos aparecerem como concluídos no Flow...")
            input()
        else:
            log(f"\n=== Aguardando render dos vídeos (poll inteligente) ===")
            aguardar_videos_prontos(page, num_takes)

        baixar_videos_prontos(page, num_takes, pasta_saida, project_id=project_id)

        log(f"\n{'='*50}")
        log(f"✓ Processo concluído!")
        log(f"  Vídeos em: {pasta_saida}")
        log(f"  Próximo passo: Etapa 4 (FFmpeg)")
        log(f"{'='*50}\n")

        context.close()


if __name__ == "__main__":
    main()
