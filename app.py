import json
import re
from pathlib import Path
from datetime import datetime, timedelta

import pandas as pd
import streamlit as st
import requests
import base64
from io import BytesIO

st.set_page_config(page_title="Controle de Coletas", page_icon="🚚", layout="wide")

DB = Path(__file__).with_name("coletas_db.json")
BASE_CEP = "04150-010"
MUITO_PERTO = set(range(40, 44))   # 040 a 043
PERTO = set(range(10, 16))         # 010 a 015
PRIORITARIOS = ("BRAMSYS", "FARMATEC")

INITIAL_ROWS = [
    {"id":"imp_20260914_52577254","num_coleta":"52577254","cep":"09811-323","cliente":"EDSON AZUL",
     "valor_nf":0.0,"volumes":"1-8-70X15X100","observacoes":"","solicitado_em":"2026-09-14T08:30:00",
     "motorista":"PAULO","status":"FINALIZADO","data_coleta":"2026-09-14"},
    {"id":"imp_20260914_DIVERSOS_FARMATEC","num_coleta":"DIVERSOS","cep":"SEM CEP","cliente":"FARMATEC",
     "valor_nf":0.0,"volumes":"?","observacoes":"A PARTIR 16:00","solicitado_em":"2026-09-14T08:30:00",
     "motorista":"PAULO","status":"FINALIZADO","data_coleta":"2026-09-14"},
    {"id":"imp_50973543","num_coleta":"50973543","cep":"09570-540","cliente":"MEDTEC","valor_nf":35000.0,
     "volumes":"1-2-52X31X38","observacoes":"Na planilha: 2026-09-16 00:00:00",
     "solicitado_em":"2026-09-15T12:01:00","motorista":"","status":"PENDENTE"},
    {"id":"imp_53096271","num_coleta":"53096271","cep":"04254-010","cliente":"NEW VIT","valor_nf":4081.0,
     "volumes":"17-1-30X3045","observacoes":"","solicitado_em":"2026-09-15T12:01:00","motorista":"","status":"PENDENTE"},
    {"id":"imp_DIVERSOS_FARMATEC_1509","num_coleta":"DIVERSOS","cep":"04070-000","cliente":"FARMATEC","valor_nf":0.0,
     "volumes":"","observacoes":"","solicitado_em":"2026-09-15T12:01:00","motorista":"","status":"PENDENTE"},
    {"id":"imp_52986732","num_coleta":"52986732","cep":"03518-020","cliente":"METALÚRGICA ROEDAN","valor_nf":3000.0,
     "volumes":"1-9,600-800X200X100","observacoes":"","solicitado_em":"2026-09-15T12:01:00","motorista":"","status":"PENDENTE"},
    {"id":"imp_53805426","num_coleta":"53805426","cep":"01521-000","cliente":"ALFA ELEVADORES","valor_nf":3531.15,
     "volumes":"1-5.40-105X26X12","observacoes":"","solicitado_em":"2026-09-15T12:01:00","motorista":"","status":"PENDENTE"},
    {"id":"imp_53612860","num_coleta":"53612860","cep":"01128-000","cliente":"MARIA CYMROT","valor_nf":2870.35,
     "volumes":"1-6,89-107X20X20","observacoes":"","solicitado_em":"2026-09-15T12:01:00","motorista":"","status":"PENDENTE"},
    {"id":"imp_53847640","num_coleta":"53847640","cep":"01004-010","cliente":"R&E FOLHEADOS","valor_nf":726.76,
     "volumes":"1-516-12X23X18","observacoes":"","solicitado_em":"2026-09-15T12:01:00","motorista":"","status":"PENDENTE"},
    {"id":"imp_53978702","num_coleta":"53978702","cep":"01004-010","cliente":"ROGER BIJU","valor_nf":809.60,
     "volumes":"1-592-10X18X22","observacoes":"","solicitado_em":"2026-09-15T12:01:00","motorista":"","status":"PENDENTE"},
]

def _secret(name, default=None):
    try:
        return st.secrets.get(name, default)
    except Exception:
        return default

def github_config():
    token = _secret("GITHUB_TOKEN")
    repo = _secret("GITHUB_REPO")
    branch = _secret("GITHUB_DATA_BRANCH", "main")
    path = _secret("GITHUB_DB_PATH", "coletas_db.json")
    return token, repo, branch, path

def github_read():
    token, repo, branch, path = github_config()
    if not token or not repo:
        return None
    url = f"https://api.github.com/repos/{repo}/contents/{path}"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    r = requests.get(url, headers=headers, params={"ref": branch}, timeout=20)
    if r.status_code == 404:
        return []
    r.raise_for_status()
    payload = r.json()
    raw = base64.b64decode(payload["content"]).decode("utf-8")
    return json.loads(raw)

def github_write(rows):
    token, repo, branch, path = github_config()
    if not token or not repo:
        return False
    url = f"https://api.github.com/repos/{repo}/contents/{path}"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    sha = None
    current = requests.get(url, headers=headers, params={"ref": branch}, timeout=20)
    if current.status_code == 200:
        sha = current.json().get("sha")
    elif current.status_code != 404:
        current.raise_for_status()
    content = base64.b64encode(
        json.dumps(rows, ensure_ascii=False, indent=2, default=str).encode("utf-8")
    ).decode("ascii")
    body = {
        "message": f"Atualiza coletas {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "content": content,
        "branch": branch,
    }
    if sha:
        body["sha"] = sha
    resp = requests.put(url, headers=headers, json=body, timeout=20)
    resp.raise_for_status()
    return True

def save(rows):
    # Sempre mantém cópia local quando estiver rodando no PC.
    try:
        DB.write_text(json.dumps(rows, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    except Exception:
        pass
    try:
        github_write(rows)
    except Exception as exc:
        st.warning(f"Os dados foram salvos localmente, mas houve falha ao sincronizar com o GitHub: {exc}")

def load():
    rows = None
    try:
        rows = github_read()
    except Exception:
        rows = None

    if rows is None:
        if DB.exists():
            try:
                rows = json.loads(DB.read_text(encoding="utf-8"))
            except Exception:
                rows = []
        else:
            rows = []

    ids = {str(r.get("id","")) for r in rows}
    keys = {(str(r.get("num_coleta","")), str(r.get("cliente","")), str(r.get("cep",""))) for r in rows}
    changed = False
    for r in INITIAL_ROWS:
        key = (str(r.get("num_coleta","")), str(r.get("cliente","")), str(r.get("cep","")))
        if r["id"] not in ids and key not in keys:
            rows.append(r.copy())
            ids.add(r["id"])
            keys.add(key)
            changed = True
    if changed:
        save(rows)
    return rows

def login_screen():
    if st.session_state.get("authenticated"):
        return True

    st.markdown("""
    <div class="login-wrap">
      <div class="login-title">🚚 CONTROLE DE COLETAS</div>
      <div class="login-sub">GDS Logística · Acesso operacional</div>
    </div>
    """, unsafe_allow_html=True)

    with st.form("login_form"):
        usuario = st.text_input("Usuário")
        senha = st.text_input("Senha", type="password")
        entrar = st.form_submit_button("ENTRAR", type="primary", use_container_width=True)

    if entrar:
        try:
            users = dict(st.secrets["users"])
        except Exception:
            users = {}
        if not users:
            st.error("Configure os usuários em .streamlit/secrets.toml ou nos Secrets do Streamlit Cloud.")
            return False
        esperado = users.get(usuario.strip().lower())
        if esperado is not None and str(esperado) == senha:
            st.session_state.authenticated = True
            st.session_state.usuario = usuario.strip().lower()
            st.rerun()
        else:
            st.error("Usuário ou senha inválidos.")
    return False


def normcep(value):
    digits = re.sub(r"\D", "", str(value or ""))
    return f"{digits[:5]}-{digits[5:8]}" if len(digits) == 8 else str(value or "").strip()

def head(cep):
    digits = re.sub(r"\D", "", str(cep or ""))
    return int(digits[:3]) if len(digits) >= 3 else 999

def regiao(cep):
    digits = re.sub(r"\D", "", str(cep or ""))
    if len(digits) != 8:
        return "SEM CEP"
    h = head(cep)
    if h in MUITO_PERTO:
        return "MUITO PERTO"
    if h in PERTO:
        return "PERTO"
    return "LONGE"

def priority(cliente):
    nome = str(cliente or "").upper()
    return any(p in nome for p in PRIORITARIOS)

def proximo_dia_util(base=None):
    d = (base or datetime.now()).date() + timedelta(days=1)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d

def data_br(d):
    return d.strftime("%d/%m/%Y")

def parse_date(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value)).date()
    except Exception:
        return None

def prioridade_manual_rank(r):
    p = str(r.get("prioridade_operacional", "Normal"))
    return {"Próxima coleta": 0, "Prioritária": 1, "Normal": 2}.get(p, 2)

def cep_head(cep):
    """Retorna os 3 primeiros dígitos numéricos do CEP para ordenação operacional."""
    n = re.sub(r"\D", "", str(cep or ""))
    if len(n) < 3:
        return 999
    try:
        return int(n[:3])
    except Exception:
        return 999

def cliente_inicio_rota(r):
    """Regra operacional: estes clientes devem ser atendidos no início da rota, com o veículo vazio."""
    nome = str(r.get("cliente","")).strip().upper()
    return nome in {"R&E FOLHEADOS", "ROGER BIJU"} and normcep(r.get("cep","")) == "01004-010"

def ordem_operacional(r):
    # Próxima coleta manual continua sendo ordem direta da operação.
    manual = prioridade_manual_rank(r)
    # R&E/ROGER vêm no início da rota automática por regra de segurança.
    seguranca = 0 if cliente_inicio_rota(r) else 1
    pri_cliente = 0 if priority(r.get("cliente")) else 1
    rg = {"LONGE":0, "PERTO":1, "MUITO PERTO":2}.get(regiao(r.get("cep")), 3)
    try:
        nf = float(r.get("valor_nf",0) or 0)
    except Exception:
        nf = 0
    return (manual, seguranca, pri_cliente, rg, cep_head(r.get("cep")), nf)

def ordem_futuro(r):
    # Rota manual salva para a data tem precedência absoluta.
    ordem = r.get("rota_manual_ordem")
    if ordem not in (None, "", 0, "0"):
        try:
            return (0, int(ordem), 0, 0, 0)
        except Exception:
            pass
    # Automático: manhã começa mais longe e volta em direção à loja; 040–043 ficam por último.
    h = head(r.get("cep"))
    faixa = 2 if h in MUITO_PERTO else (1 if h in PERTO else 0)
    return (1, faixa, -h, float(r.get("valor_nf") or 0), str(r.get("cliente", "")))

def registrar_status(r, novo_status, usuario):
    anterior = r.get("status", "PENDENTE")
    if anterior == novo_status:
        return
    hist = r.setdefault("historico_status", [])
    hist.append({"em": datetime.now().isoformat(timespec="seconds"), "usuario": usuario,
                 "de": anterior, "para": novo_status})
    r["status"] = novo_status
    if novo_status not in ("COLETADO", "ENTREGUE NA LOJA"):
        r.pop("coletado_em", None)
        r.pop("entregue_loja_em", None)
    if novo_status != "ENTREGUE NA LOJA":
        r.pop("entregue_loja_em", None)

def rota_futura_grupos(futuro):
    ordenados = sorted(futuro, key=ordem_futuro)
    # Se houver rota manual, respeitamos exatamente a sequência escolhida.
    if any(r.get("rota_manual_ordem") for r in ordenados):
        return [("ROTA MANUAL", ordenados)]
    manha, tarde = [], []
    for r in ordenados:
        h = head(r.get("cep"))
        # Faixas muito deslocadas do eixo da base (ex.: 095) ficam como ciclo após almoço.
        if h >= 90:
            tarde.append(r)
        else:
            manha.append(r)
    # Coletas 040–043 podem completar o retorno de qualquer ciclo; se existe rota longa isolada à tarde,
    # elas ficam disponíveis para agrupamento no retorno desse ciclo.
    if tarde:
        perto_base = [r for r in manha if head(r.get("cep")) in MUITO_PERTO]
        manha = [r for r in manha if r not in perto_base]
        tarde.extend(sorted(perto_base, key=lambda r: float(r.get("valor_nf") or 0)))
    return [("ROTA 1 — MANHÃ", manha), ("ROTA 2 — APÓS O ALMOÇO", tarde)]

def separar_programacao(rows, agora=None):
    agora = agora or datetime.now()
    prox = proximo_dia_util(agora)
    hoje, futuro, sem_cep = [], [], []

    for base in rows:
        status = base.get("status","PENDENTE")
        if status in ("COLETADO","ENTREGUE NA LOJA","FINALIZADO","CANCELADO"):
            continue

        r = base.copy()
        r["regiao"] = regiao(r.get("cep"))

        if r["regiao"] == "SEM CEP":
            sem_cep.append(r)
            continue

        programado = parse_date(r.get("programado_para"))
        if programado and programado > agora.date():
            futuro.append(r)
            continue

        if status in ("LIBERADA","EM ROTA"):
            hoje.append(r)
            continue

        if agora.hour < 13:
            hoje.append(r)
            continue

        # Durante a tarde, prioridade e CEP 040–043 continuam candidatos para hoje.
        # A viabilidade por trânsito/tempo será refinada quando a API de rotas estiver ativa.
        if priority(r.get("cliente")) or r["regiao"] == "MUITO PERTO":
            hoje.append(r)
        else:
            r["programado_para"] = prox.isoformat()
            futuro.append(r)

    hoje.sort(key=ordem_operacional)
    futuro.sort(key=ordem_futuro)
    sem_cep.sort(key=ordem_operacional)
    return hoje, futuro, sem_cep

def cargas_no_veiculo(rows):
    return [r for r in rows if r.get("status") == "COLETADO"]

def proxima_acao(rows, hoje, futuro):
    cargas = cargas_no_veiculo(rows)
    # Ordem manual "Próxima coleta" vence qualquer sugestão automática.
    for r in hoje:
        if r.get("prioridade_operacional") == "Próxima coleta" and r.get("status") in ("PENDENTE","LIBERADA","EM ROTA"):
            return "COLETA", r
    em_execucao = [r for r in hoje if r.get("status") in ("LIBERADA","EM ROTA")]
    if em_execucao:
        return "COLETA", sorted(em_execucao, key=ordem_operacional)[0]
    if cargas:
        return "LOJA", cargas
    pendentes_hoje = [r for r in hoje if r.get("status","PENDENTE") == "PENDENTE"]
    if pendentes_hoje:
        return "COLETA", sorted(pendentes_hoje, key=ordem_operacional)[0]
    return "CONCLUIDO", futuro

def resumo_whatsapp(rows, agora=None):
    agora = agora or datetime.now()
    hoje, futuro, sem_cep = separar_programacao(rows, agora)
    prox = proximo_dia_util(agora)
    cargas = cargas_no_veiculo(rows)
    linhas = ["🚚 *PROGRAMAÇÃO DE COLETAS*", f"📅 *{agora.strftime('%d/%m/%Y')}*", ""]
    if cargas:
        linhas.append("🏢 *AÇÃO ATUAL — LEVAR AS COLETAS PARA A LOJA*")
        for r in cargas:
            linhas.append(f"• *{r.get('cliente','')}* | {r.get('cep','')} | Coleta {r.get('num_coleta','')}")
        linhas.append("")
    linhas.append("📍 *PREVISTAS PARA HOJE*")
    ativos=[r for r in hoje if r.get("status") not in ("COLETADO","ENTREGUE NA LOJA")]
    if ativos:
        for i,r in enumerate(sorted(ativos,key=ordem_operacional),1):
            tag="🚨 " if r.get("prioridade_operacional")=="Próxima coleta" else ("⭐ " if priority(r.get("cliente")) or r.get("prioridade_operacional")=="Prioritária" else "")
            linhas.append(f"{i}. {tag}*{r.get('cliente','')}* | {r.get('cep','')} | Coleta {r.get('num_coleta','')} | NF {money(r.get('valor_nf',0))}")
    else:
        linhas.append("• Nenhuma coleta pendente para hoje.")
    linhas += ["", f"🌅 *PRÓXIMO DIA ÚTIL — {data_br(prox)}*"]
    grupos=rota_futura_grupos(futuro)
    houve=False
    for nome,grupo in grupos:
        if not grupo: continue
        houve=True; linhas += ["", f"🚚 *{nome}*"]
        for i,r in enumerate(grupo,1):
            tag="🚨 " if r.get("prioridade_operacional")=="Próxima coleta" else ("⭐ " if priority(r.get("cliente")) or r.get("prioridade_operacional")=="Prioritária" else "")
            linhas.append(f"{i}. {tag}*{r.get('cliente','')}* | {r.get('cep','')} | Coleta {r.get('num_coleta','')}")
        linhas.append("🏢 *Retornar e deixar as coletas na loja*")
    if not houve: linhas.append("• Nenhuma coleta programada.")
    if sem_cep:
        linhas += ["", "⚠️ *PENDÊNCIAS SEM CEP*"]
        for r in sem_cep: linhas.append(f"• {r.get('num_coleta','')} — {r.get('cliente','')}")
    return "\n".join(linhas)

def money(v):
    try:
        return f"R$ {float(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return "R$ 0,00"

def update_row(rows, row_id, **changes):
    for r in rows:
        if str(r.get("id")) == str(row_id):
            r.update(changes)
            break
    save(rows)

def show_items(r):
    itens = r.get("itens") or []
    if itens:
        df = pd.DataFrame(itens).rename(columns={
            "volumes":"Volumes","peso_kg":"Peso (kg)","medidas":"Medidas","descricao":"Descrição"
        })
        st.dataframe(df, use_container_width=True, hide_index=True)
    elif r.get("volumes"):
        st.caption(f"📦 Dados importados da planilha: {r.get('volumes')}")

def abrir_edicao(row_id):
    st.session_state.edit_id = str(row_id)

def formulario_edicao(rows, r):
    st.markdown("#### ✏️ Editar coleta")
    with st.form(f"editar_{r['id']}", enter_to_submit=False):
        a,b,c=st.columns(3)
        numero=a.text_input("Número da coleta", value=str(r.get("num_coleta","")))
        cep=b.text_input("CEP", value=str(r.get("cep","")))
        cliente=c.text_input("Cliente", value=str(r.get("cliente","")))
        a,b,c=st.columns(3)
        valor=a.number_input("Valor da NF", min_value=0.0, value=float(r.get("valor_nf") or 0), step=100.0, format="%.2f")
        opcoes=["Normal","Prioritária","Próxima coleta"]
        atual=r.get("prioridade_operacional","Normal") if r.get("prioridade_operacional","Normal") in opcoes else "Normal"
        prioridade=a.selectbox("Prioridade operacional",opcoes,index=opcoes.index(atual))
        statuses=["PENDENTE","LIBERADA","EM ROTA","COLETADO","ENTREGUE NA LOJA","CANCELADO"]
        status_atual=r.get("status","PENDENTE") if r.get("status","PENDENTE") in statuses else "PENDENTE"
        status=b.selectbox("Status operacional",statuses,index=statuses.index(status_atual))
        prog=parse_date(r.get("programado_para")) or datetime.now().date()
        programado=c.date_input("Programado para",value=prog)
        obs=st.text_area("Observações",value=str(r.get("observacoes", "")))
        x,y=st.columns(2)
        salvar=x.form_submit_button("💾 Salvar alterações",type="primary",use_container_width=True)
        cancelar=y.form_submit_button("Cancelar",use_container_width=True)
    if cancelar:
        st.session_state.edit_id=None; st.rerun()
    if salvar:
        cep_ok=normcep(cep)
        if not numero.strip() or not cliente.strip() or regiao(cep_ok)=="SEM CEP":
            st.error("Preencha número da coleta, cliente e um CEP válido.")
        else:
            antigo=r.get("status","PENDENTE")
            r.update({"num_coleta":numero.strip(),"cep":cep_ok,"cliente":cliente.strip().upper(),"valor_nf":float(valor),
                      "prioridade_operacional":prioridade,"programado_para":programado.isoformat(),"observacoes":obs.strip()})
            if antigo != status:
                registrar_status(r,status,st.session_state.get("usuario",""))
                if status == "COLETADO":
                    r["data_coleta"] = datetime.now().date().isoformat()
                    r["coletado_em"] = datetime.now().isoformat(timespec="seconds")
                elif status == "ENTREGUE NA LOJA":
                    r["entregue_loja_em"] = datetime.now().isoformat(timespec="seconds")
            # "Próxima coleta" deve ser única.
            if prioridade=="Próxima coleta":
                for outra in rows:
                    if str(outra.get("id"))!=str(r.get("id")) and outra.get("prioridade_operacional")=="Próxima coleta":
                        outra["prioridade_operacional"]="Normal"
            save(rows); st.session_state.edit_id=None
            st.session_state.flash=f"✅ Alterações salvas — coleta {numero.strip()} · {cliente.strip().upper()}"
            st.rerun()

def coleta_card(rows, r, prox_data):
    estrela = "🛡️ " if cliente_inicio_rota(r) else ("⭐ " if priority(r.get("cliente")) else "")
    st.markdown(
        f"""<div class="coleta-card">
        <div class="coleta-title">{estrela}{r.get('cliente','')} <span>— {r.get('cep','')}</span></div>
        <div class="coleta-meta">Coleta <b>{r.get('num_coleta','')}</b> ·
        NF <b>{money(r.get('valor_nf',0))}</b> · Status <b>{r.get('status','PENDENTE')}</b></div>
        </div>""",
        unsafe_allow_html=True
    )
    if r.get("observacoes"):
        st.caption(f"📝 {r.get('observacoes')}")
    if r.get("prioridade_operacional") == "Próxima coleta":
        st.error("🚨 PRIORIDADE MANUAL — PRÓXIMA COLETA")
    elif r.get("prioridade_operacional") == "Prioritária":
        st.warning("⭐ Prioridade operacional")
    if st.button("✏️ Editar coleta", key=f"edit_{r['id']}", use_container_width=True):
        abrir_edicao(r["id"]); st.rerun()
    if str(st.session_state.get("edit_id")) == str(r.get("id")):
        formulario_edicao(rows, r)

    status = r.get("status","PENDENTE")
    if status == "PENDENTE":
        a,b = st.columns(2)
        if a.button("🚚 Liberar coleta", key=f"lib_{r['id']}", use_container_width=True, type="primary"):
            registrar_status(r,"LIBERADA",st.session_state.get("usuario",""))
            r["liberada_em"]=datetime.now().isoformat(timespec="seconds")
            r["programado_para"]=datetime.now().date().isoformat(); save(rows); st.rerun()
        if b.button(f"↪️ Deixar para {data_br(prox_data)}", key=f"next_{r['id']}", use_container_width=True):
            update_row(rows, r["id"], programado_para=prox_data.isoformat())
            st.rerun()
    elif status == "LIBERADA":
        st.success("✅ Coleta liberada para o motorista.")
        if st.button("📦 Marcar como coletada", key=f"col_{r['id']}", use_container_width=True):
            agora = datetime.now()
            registrar_status(r, "COLETADO", st.session_state.get("usuario",""))
            r["data_coleta"] = agora.date().isoformat()
            r["coletado_em"] = agora.isoformat(timespec="seconds")
            # A ordem "Próxima coleta" vale apenas até a execução.
            if r.get("prioridade_operacional") == "Próxima coleta":
                r["prioridade_operacional"] = "Normal"
            r["ordem_manual"] = None
            save(rows)
            st.session_state["painel"] = "PROXIMA"
            st.session_state["flash_operacional"] = f"✅ Coleta {r.get('num_coleta','')} confirmada como coletada."
            st.rerun()
    elif status == "EM ROTA":
        st.info("🚚 Motorista em rota para esta coleta.")
    elif status == "COLETADO":
        st.warning("📦 Coleta realizada — carga está no veículo e precisa retornar à loja.")
    elif status == "ENTREGUE NA LOJA":
        st.success("🏢 Carga entregue na loja.")

st.markdown("""
<style>
.block-container{padding-top:1.4rem;max-width:1500px}
.coleta-card{border:1px solid #dbe3ec;border-left:5px solid #163a63;border-radius:10px;padding:14px 16px;margin:10px 0 6px;background:#fff}
.coleta-title{font-size:1.05rem;font-weight:800;color:#153452}
.coleta-title span{font-weight:700;color:#345}
.coleta-meta{font-size:.9rem;color:#52606d;margin-top:5px}
div[data-testid="stButton"] button{min-height:52px;border-radius:10px;font-weight:700}
</style>
""", unsafe_allow_html=True)


st.markdown("""
<style>
h1{font-weight:900!important;color:#17365d!important}
h2,h3{font-weight:850!important;color:#17365d!important}
.coleta-card{border-radius:14px!important;border-left:6px solid #1f4e79!important;background:linear-gradient(135deg,#ffffff,#f4f8fd)!important;padding:18px 20px!important;box-shadow:0 3px 12px rgba(23,54,93,.10)!important}
.coleta-title{font-size:1.14rem!important;font-weight:900!important}
.coleta-meta{font-weight:650!important}
div[data-testid="stButton"] button{min-height:58px!important;border-radius:13px!important;font-weight:850!important;box-shadow:0 2px 8px rgba(23,54,93,.08)!important}
div[data-testid="stTabs"] button{font-weight:850!important}
</style>
""", unsafe_allow_html=True)


st.markdown("""
<style>
.return-card{
    display:flex;align-items:center;gap:18px;
    padding:22px 24px;margin:12px 0 14px;
    border-radius:16px;border:1px solid #b8cbe0;
    border-left:7px solid #17365d;
    background:linear-gradient(135deg,#eef5fc,#ffffff);
    box-shadow:0 4px 15px rgba(23,54,93,.12)
}
.return-icon{font-size:2.2rem}
.return-title{font-size:1.25rem;font-weight:900;color:#17365d}
.return-sub{font-size:.95rem;font-weight:650;color:#52606d;margin-top:4px}
</style>
""", unsafe_allow_html=True)


st.markdown("""
<style>
.login-wrap{max-width:520px;margin:45px auto 20px;text-align:center;padding:28px;border-radius:18px;background:linear-gradient(135deg,#17365d,#245b8f);box-shadow:0 8px 24px rgba(23,54,93,.20)}
.login-title{font-size:1.55rem;font-weight:900;color:white;letter-spacing:.4px}
.login-sub{margin-top:7px;font-size:.95rem;font-weight:650;color:#e8f1fb}
</style>
""", unsafe_allow_html=True)

if not login_screen():
    st.stop()

rows = load()
flash_operacional = st.session_state.pop("flash_operacional", None)
if flash_operacional:
    st.success(flash_operacional)

prox_data = proximo_dia_util()
hoje, futuro, sem_cep = separar_programacao(rows)

top1, top2 = st.columns([8,2])
with top1:
    st.title("🚚 Controle de Coletas")
    st.caption(f"Base operacional: CEP {BASE_CEP} · planejamento dinâmico por coleta · próximo dia útil: {data_br(prox_data)}")
with top2:
    st.caption(f"👤 {st.session_state.get('usuario','')}")
    if st.button("Sair", use_container_width=True):
        st.session_state.authenticated = False
        st.rerun()

if github_config()[0] and github_config()[1]:
    st.caption("☁️ Dados sincronizados com banco JSON no GitHub")
else:
    st.caption("💻 Modo local — configure os Secrets do GitHub antes de publicar para não depender do arquivo local")

menu = st.radio("Navegação", ["📍 Planejamento","➕ Nova coleta","💬 Resumo WhatsApp","🗺️ Rota manual","📊 Histórico / Excel"], horizontal=True, label_visibility="collapsed")

if st.session_state.get("menu_anterior") != menu:
    if menu == "📍 Planejamento":
        st.session_state.painel = "PROXIMA"
    st.session_state.menu_anterior = menu

flash = st.session_state.pop("flash", None)
if flash:
    st.success(flash)

if menu == "📍 Planejamento":
    if "painel" not in st.session_state: st.session_state.painel="PROXIMA"
    acao_tipo, acao_dados=proxima_acao(rows,hoje,futuro)
    proxima=acao_dados if acao_tipo=="COLETA" else None
    pendentes=[r for r in rows if r.get("status","PENDENTE") not in ("COLETADO","ENTREGUE NA LOJA","FINALIZADO","CANCELADO")]
    c1,c2,c3,c4=st.columns(4)
    if c1.button(f"🚚  PRÓXIMA AÇÃO  •  {1 if acao_tipo in ('COLETA','LOJA') else 0}",use_container_width=True): st.session_state.painel="PROXIMA"; st.rerun()
    if c2.button(f"📍  HOJE — RESTANTES  •  {len(hoje)}",use_container_width=True): st.session_state.painel="HOJE"; st.rerun()
    if c3.button(f"📅  {data_br(prox_data)} — PRÓXIMO DIA ÚTIL  •  {len(futuro)}",use_container_width=True): st.session_state.painel="FUTURO"; st.rerun()
    if c4.button(f"⏳  PENDENTES  •  {len(pendentes)}",use_container_width=True): st.session_state.painel="PENDENTES"; st.rerun()
    st.divider(); painel=st.session_state.painel
    if painel=="PROXIMA":
        if acao_tipo=="COLETA" and proxima:
            st.subheader("🚚 Próxima coleta"); coleta_card(rows,proxima,prox_data)
        elif acao_tipo=="LOJA":
            st.subheader("🏢 Próxima ação")
            st.markdown('<div class="return-card"><div class="return-icon">🏢</div><div><div class="return-title">LEVAR AS COLETAS PARA A LOJA</div><div class="return-sub">Retornar à base operacional — CEP 04150-010</div></div></div>',unsafe_allow_html=True)
            cargas=acao_dados; st.caption(f"📦 {len(cargas)} coleta(s) no veículo aguardando retorno.")
            for carga in cargas: st.write(f"**{carga.get('num_coleta','')} — {carga.get('cliente','')}** · {carga.get('cep','')}")
            if st.button("✅ CHEGOU NA LOJA — DESCARREGAR COLETAS",type="primary",use_container_width=True):
                agora_txt=datetime.now().isoformat(timespec="seconds")
                for base in rows:
                    if base.get("status")=="COLETADO": registrar_status(base,"ENTREGUE NA LOJA",st.session_state.get("usuario","")); base["entregue_loja_em"]=agora_txt
                save(rows); st.rerun()
        else:
            st.subheader("✅ Operação atual concluída")
            st.success(f"Não há outra coleta prevista para agora. Próximas programadas para {data_br(prox_data)}." if futuro else "Não há outra coleta pendente para agora.")
    elif painel=="HOJE":
        st.subheader("📍 Coletas que ainda fazem sentido hoje")
        if not hoje: st.info("Nenhuma coleta prevista para hoje.")
        for r in hoje: coleta_card(rows,r,prox_data)
    elif painel=="FUTURO":
        st.subheader(f"🌅 Programação — {data_br(prox_data)}")
        grupos=rota_futura_grupos(futuro)
        if not futuro: st.info("Nenhuma coleta programada para o próximo dia útil.")
        for nome,grupo in grupos:
            if grupo:
                st.markdown(f"### 🚚 {nome}")
                for r in grupo: coleta_card(rows,r,prox_data)
                st.info("🏢 Ao finalizar este ciclo: levar as coletas para a loja.")
    else:
        st.subheader("⏳ Todas as pendências")
        if not pendentes: st.info("Nenhuma pendência.")
        for r in pendentes: coleta_card(rows,r,prox_data)
    if sem_cep:
        with st.expander(f"⚠️ {len(sem_cep)} coleta(s) sem CEP válido"):
            for r in sem_cep: st.write(f"**{r.get('num_coleta','')} — {r.get('cliente','')}**")

elif menu == "➕ Nova coleta":
    st.subheader("➕ Nova coleta")
    if st.session_state.get("nova_ok"):
        st.success(st.session_state.pop("nova_ok"))
    with st.form("nova_coleta",clear_on_submit=True,enter_to_submit=False):
        a,b,c=st.columns(3)
        numero=a.text_input("Número da coleta"); cep=b.text_input("CEP",placeholder="00000-000"); cliente=c.text_input("Cliente")
        a,b=st.columns(2)
        valor_nf=a.number_input("Valor da NF",min_value=0.0,step=100.0,format="%.2f")
        prioridade=b.selectbox("Prioridade operacional",["Normal","Prioritária","Próxima coleta"])
        observacoes=st.text_area("Observações")
        salvar=st.form_submit_button("💾 SALVAR COLETA",type="primary",use_container_width=True)
    if salvar:
        cep_ok=normcep(cep)
        if not numero.strip() or not cliente.strip() or regiao(cep_ok)=="SEM CEP": st.error("Preencha número da coleta, cliente e um CEP válido.")
        elif any(str(r.get("num_coleta","")).strip()==numero.strip() and str(r.get("cliente","")).upper()==cliente.strip().upper() and r.get("status")!="CANCELADO" for r in rows): st.error("⚠️ Esta coleta já está cadastrada para este cliente. Verifique antes de salvar novamente.")
        else:
            if prioridade=="Próxima coleta":
                for r in rows:
                    if r.get("prioridade_operacional")=="Próxima coleta": r["prioridade_operacional"]="Normal"
            nova={"id":datetime.now().strftime("%Y%m%d%H%M%S%f"),"num_coleta":numero.strip(),"cep":cep_ok,"cliente":cliente.strip().upper(),"valor_nf":float(valor_nf),"observacoes":observacoes.strip(),"solicitado_em":datetime.now().isoformat(timespec="seconds"),"motorista":"","status":"PENDENTE","prioridade_operacional":prioridade}
            rows.append(nova); save(rows); st.session_state.nova_ok=f"✅ Coleta {numero.strip()} — {cliente.strip().upper()} salva com sucesso!"; st.rerun()

elif menu == "💬 Resumo WhatsApp":
    st.subheader("💬 Resumo para WhatsApp"); st.caption("Mensagem pronta para copiar e enviar ao time.")
    st.text_area("Programação",value=resumo_whatsapp(rows),height=480)
    st.info("Copie a mensagem acima. No WhatsApp, os textos entre *asteriscos* aparecem em negrito.")

elif menu == "🗺️ Rota manual":
    st.subheader("🗺️ Montar rota manual")
    data_rota=st.date_input("Data da rota",value=prox_data)
    candidatos=[r for r in rows if r.get("status","PENDENTE") not in ("COLETADO","ENTREGUE NA LOJA","FINALIZADO","CANCELADO") and (parse_date(r.get("programado_para")) in (None,data_rota) or data_rota==prox_data)]
    st.caption("Defina 1, 2, 3... para a sequência desejada. Zero deixa a coleta fora da rota manual. A rota manual prevalece sobre a sugestão automática.")
    with st.form("rota_manual_form",enter_to_submit=False):
        ordens={}
        for r in sorted(candidatos,key=ordem_futuro):
            c1,c2=st.columns([5,1])
            c1.markdown(f"**{r.get('cliente','')}** · {r.get('cep','')} · Coleta {r.get('num_coleta','')} · {money(r.get('valor_nf',0))}")
            atual=int(r.get("rota_manual_ordem") or 0) if parse_date(r.get("programado_para"))==data_rota else 0
            ordens[r['id']]=c2.number_input("Ordem",min_value=0,max_value=99,value=atual,step=1,key=f"ord_{r['id']}",label_visibility="collapsed")
        salvar_rota=st.form_submit_button("💾 Salvar rota manual",type="primary",use_container_width=True)
    if salvar_rota:
        usados=[v for v in ordens.values() if v>0]
        if len(usados)!=len(set(usados)): st.error("Não repita o mesmo número de ordem em duas coletas.")
        else:
            for r in rows:
                if r.get("id") in ordens:
                    o=int(ordens[r['id']]); r["rota_manual_ordem"]=o if o>0 else None
                    if o>0: r["programado_para"]=data_rota.isoformat()
            save(rows); st.success("✅ Rota manual salva com sucesso.")
    if st.button("↩️ Voltar esta data para rota automática",use_container_width=True):
        for r in rows:
            if parse_date(r.get("programado_para"))==data_rota: r["rota_manual_ordem"]=None
        save(rows); st.rerun()

else:
    st.subheader("📊 Histórico / Excel")
    if rows:
        df=pd.DataFrame(rows)
        colunas=[c for c in ["num_coleta","cep","cliente","valor_nf","prioridade_operacional","rota_manual_ordem","motorista","status","solicitado_em","liberada_em","coletado_em","entregue_loja_em","data_coleta","programado_para","observacoes"] if c in df.columns]
        st.dataframe(df[colunas],use_container_width=True,hide_index=True)
        bio=BytesIO()
        with pd.ExcelWriter(bio,engine="openpyxl") as writer: df.to_excel(writer,index=False,sheet_name="Coletas")
        st.download_button("⬇️ Baixar backup em Excel",data=bio.getvalue(),file_name=f"coletas_backup_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",use_container_width=True)
        st.markdown("### ✏️ Editar / corrigir coleta")
        opcoes={f"{r.get('num_coleta','')} — {r.get('cliente','')} — {r.get('status','')}":r for r in rows}
        escolha=st.selectbox("Selecione uma coleta",[""]+list(opcoes.keys()))
        if escolha: formulario_edicao(rows,opcoes[escolha])
    else: st.info("Nenhum registro.")

st.caption("Controle de Coletas · V1.9.1 GitHub/Streamlit")
