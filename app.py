from flask import Flask, render_template, request, jsonify
from flask_cors import CORS

import os
import json
from datetime import datetime
from supabase import create_client, Client
from datetime import date as _date

from datetime import datetime, timezone
from datetime import datetime, timedelta
import base64, hmac, hashlib, time
from urllib.parse import urlencode
from flask import make_response

import psycopg2


DEMO_WORKFLOW_MARKER = 'HRK_DEMO_WORKFLOW_RESET_V1'
DEMO_WORKFLOW_MARKERS = {
    'HRK_DEMO_WORKFLOW_RESET_V1',
    'FAKE_CODEX_CAL_20260629',
}
DEMO_WORKFLOW_RESET_CONFIRM = 'RESET KIT DEMO'
DEMO_WORKFLOW_CLIENTE_ID = 'e40505a2-354b-4e0a-8c55-115488407920'
DEMO_WORKFLOW_HOLDING_ID = '41c11f1d-2508-4b0d-ade0-8dda7efb8c2d'
LEGACY_DEMO_WORKFLOW_EVALUATION_IDS = [254, 255, 256, 257, 258, 259, 260]
DEMO_WORKFLOW_EMPLOYEE_CASES = [
    {
        'employee_id': 203,
        'final_rating': 4.60,
        'nine_box_position': 8,
        'performance_rating': 8.40,
        'potential_rating': 8.80,
        'workflow_status': 'em_calibracao_no_comite'
    },
    {
        'employee_id': 131,
        'final_rating': 3.80,
        'nine_box_position': 6,
        'performance_rating': 6.20,
        'potential_rating': 6.60,
        'workflow_status': 'enviada_ao_comite'
    },
    {
        'employee_id': 160,
        'final_rating': 4.20,
        'nine_box_position': 7,
        'performance_rating': 7.80,
        'potential_rating': 5.90,
        'workflow_status': 'aprovada_pelo_comite'
    },
    {
        'employee_id': 170,
        'final_rating': 2.40,
        'nine_box_position': 3,
        'performance_rating': 4.10,
        'potential_rating': 8.10,
        'workflow_status': 'feedback_realizado'
    },
    {
        'employee_id': 257,
        'final_rating': 3.10,
        'nine_box_position': 5,
        'performance_rating': 5.80,
        'potential_rating': 5.20,
        'workflow_status': 'devolvida_ao_gestor'
    },
    {
        'employee_id': 186,
        'final_rating': 2.55,
        'nine_box_position': 5,
        'performance_rating': 6.10,
        'potential_rating': 5.00,
        'workflow_status': 'ciencia_do_profissional'
    }
]


# ===== Helpers de acesso do Gestor =====
def current_manager_code():
    """
    Lê o cookie httpOnly 'manager_access' (definido ao entrar em /team?t=TOKEN).
    Se existir, retornamos o manager_code (ex.: '0007'); senão, None (modo RH).
    """
    try:
        mc = (request.cookies.get('manager_access') or '').strip()
        return mc if mc else None
    except Exception:
        return None

def restrict_to_manager_employee_ids():
    """
    Se houver manager_access, retorna a lista de IDs de funcionários do time desse gestor.
    Caso contrário (RH), retorna None.
    """
    mc = current_manager_code()
    if not mc:
        return None  # RH (sem filtro)

    try:
        r = (supabase.table('employees')
             .select('id')
             .eq('manager_code', mc)
             .execute())
        emp_ids = [row['id'] for row in (r.data or []) if row.get('id') is not None]
        return emp_ids
    except Exception as e:
        print('[restrict_to_manager_employee_ids] erro:', e)
        return []  # sem IDs => gestor vê nada







def _parse_iso(dt_str: str):
    if not dt_str:
        return None
    # aceita ISO com ou sem 'Z'
    try:
        if dt_str.endswith('Z'):
            return datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
        return datetime.fromisoformat(dt_str)
    except Exception:
        return None

def is_window_open():
    """Retorna (open_bool, start_dt, end_dt, period_str) comparando com o 'agora' em UTC."""
    period = get_current_period()
    row = get_window_row()  # já lê o período atual
    if not row:
        return (False, None, None, period)
    start_dt = _parse_iso(str(row.get('start_at')))
    end_dt   = _parse_iso(str(row.get('end_at')))
    if not start_dt or not end_dt:
        return (False, start_dt, end_dt, period)
    now = datetime.now(timezone.utc)
    return (start_dt <= now <= end_dt, start_dt, end_dt, period)


app = Flask(__name__)


CORS(
    app,
    resources={r"/api/*": {
        "origins": [
            "https://gestor.thehrkey.tech",
            "https://*.thehrkey.tech"
            "https://hoppscotch.io"
        ],
        "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        "allow_headers": ["Content-Type", "Authorization"],
        "expose_headers": ["Content-Type"],
        "supports_credentials": False
    }},
)


# ===================== Configurações / Conexão =====================
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
ADMIN_WINDOW_CODE = os.getenv('ADMIN_WINDOW_CODE', '').strip()  # usado em PUTs protegidos

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


from datetime import datetime, timezone, date



def _competence_from_request() -> _date:
    """
    Lê competência do request e normaliza para YYYY-MM-01 (1º dia do mês).
    Prioridade:
      1) Querystring: ?competence=YYYY-MM-01  ou  ?competence=YYYY-MM
      2) Header: X-Competence
      3) JSON body: {"competence": "..."}
      4) Fallback: mês atual
    """
    comp_str = ""

    # 1) querystring
    try:
        comp_str = (request.args.get("competence") or "").strip()
    except Exception:
        comp_str = ""

    # 2) header
    if not comp_str:
        try:
            comp_str = (request.headers.get("X-Competence") or "").strip()
        except Exception:
            comp_str = ""

    # 3) body json
    if not comp_str:
        try:
            body = request.get_json(silent=True) or {}
            comp_str = str(body.get("competence") or "").strip()
        except Exception:
            comp_str = ""

    # aceita YYYY-MM e transforma em YYYY-MM-01
    if comp_str and len(comp_str) == 7 and comp_str[4] == "-":
        comp_str = comp_str + "-01"

    # tenta parse ISO
    if comp_str:
        try:
            d = _date.fromisoformat(comp_str)  # espera YYYY-MM-DD
            return _month_start(d)
        except Exception:
            pass

    # 4) fallback: mês atual
    today = datetime.now(timezone.utc).date()
    return _month_start(today)


def _get_actor():
    """
    Quem alterou.
    Se você já tiver login/autenticação, aqui é onde a gente pega o usuário.
    Por enquanto, usa um header (X-User) ou 'admin'.
    """
    try:
        actor = (request.headers.get("X-User") or "").strip()
        return actor if actor else "admin"
    except Exception:
        return "admin"


def _save_employee_history(employee_id: int, data_snapshot: dict, action: str, round_code: str | None = None, competence: _date | None = None):
    """
    Grava um snapshot no employee_history.
    Se competence for informada, usa ela; senão tenta ler do request (fallback: mês atual).
    """
    comp = competence if competence is not None else _competence_from_request()
    payload = {
        "employee_id": employee_id,
        "competence": comp.isoformat(),        
        "round_code": round_code,
        "action": action,
        "changed_at": datetime.now(timezone.utc).isoformat(),
        "changed_by": _get_actor(),
        "data": data_snapshot
    }
    supabase.table("employee_history").insert(payload).execute()





MANAGER_LINK_SECRET = os.getenv('MANAGER_LINK_SECRET', '').encode('utf-8')
def _b64u(x: bytes) -> str:
    return base64.urlsafe_b64encode(x).decode('ascii').rstrip('=')

def _b64u_dec(s: str) -> bytes:
    pad = '=' * (-len(s) % 4)
    return base64.urlsafe_b64decode((s + pad).encode('ascii'))

def sign_manager_token(manager_code: str, exp_seconds: int = 2592000) -> str:
    """
    Gera um token assinado válido por ~30 dias (padrão).
    Payload: {"mc":"0007","exp":<epoch>}
    """
    if not MANAGER_LINK_SECRET:
        raise RuntimeError('MANAGER_LINK_SECRET ausente')
    payload = json.dumps({
        "mc": str(manager_code).strip(),
        "exp": int(time.time()) + int(exp_seconds)
    }, separators=(',', ':')).encode('utf-8')
    p = _b64u(payload)
    sig = hmac.new(MANAGER_LINK_SECRET, payload, hashlib.sha256).digest()
    s = _b64u(sig)
    return f"{p}.{s}"

def verify_manager_token(token: str):
    """Retorna dict com 'mc' se ok; senão None."""
    try:
        p, s = token.split('.', 1)
        payload = _b64u_dec(p)
        sig = _b64u_dec(s)
        good = hmac.compare_digest(sig, hmac.new(MANAGER_LINK_SECRET, payload, hashlib.sha256).digest())
        if not good:
            return None
        data = json.loads(payload.decode('utf-8'))
        if int(data.get('exp', 0)) < int(time.time()):
            return None
        mc = str(data.get('mc', '')).strip()
        return {"mc": mc} if mc else None
    except Exception:
        return None



# ===================== Competência (travamento) =====================
from datetime import date as _date

def _month_start(d: _date) -> _date:
    """Normaliza para o 1º dia do mês."""
    return _date(d.year, d.month, 1)

def _is_competence_closed(comp: _date) -> bool:
    """Retorna True se a competência estiver CLOSED."""
    comp = _month_start(comp)
    try:
        r = (
            supabase.table("competence_locks")
            .select("status")
            .eq("competence", comp.isoformat())
            .maybe_single()
            .execute()
        )
        row = r.data
        return bool(row and (row.get("status") == "CLOSED"))
    except Exception:
        # se der erro de consulta, por segurança NÃO bloqueia aqui
        # (vamos enxergar no log e corrigir depois)
        return False

def _assert_competence_open_or_admin(comp: _date):
    """
    Bloqueia se competência estiver fechada.
    Exceção: se veio um admin_code válido no request (header ou query/body).
    """
    comp = _month_start(comp)

    # 1) Se não estiver fechada, ok
    if not _is_competence_closed(comp):
        return

    # 2) Se estiver fechada, só libera com admin_code
    admin_code = ""
    try:
        admin_code = (request.headers.get("X-Admin-Code") or "").strip()
    except Exception:
        pass

    if not admin_code:
        # tenta querystring
        try:
            admin_code = (request.args.get("admin_code") or "").strip()
        except Exception:
            pass

    if not admin_code:
        # tenta body json
        try:
            body = request.get_json(silent=True) or {}
            admin_code = str(body.get("admin_code") or "").strip()
        except Exception:
            pass

    if not ADMIN_WINDOW_CODE:
        # se você não configurou ADMIN_WINDOW_CODE no Render, não tem como autorizar
        raise PermissionError("Competência fechada e ADMIN_WINDOW_CODE não configurado no servidor.")

    if admin_code != ADMIN_WINDOW_CODE:
        raise PermissionError(f"Competência {comp.isoformat()} está FECHADA. Informe admin_code válido para alterar.")

def _extract_competence_context_from_body(body: dict) -> dict:
    """
    Extrai contexto multiempresa do body.
    O WordPress envia esses campos junto no cadastro/edição.
    """
    body = body or {}

    return {
        "nivel_contexto": str(body.get("nivel_contexto") or "").strip().lower(),
        "cliente_id": str(body.get("cliente_id") or "").strip(),
        "holding_id": str(body.get("holding_id") or "").strip(),
        "empresa_id": str(body.get("empresa_id") or "").strip(),
        "filial_id": str(body.get("filial_id") or "").strip(),
        "contexto_nome": str(body.get("contexto_nome") or "").strip()
    }


def _remove_context_fields_from_employee_payload(data: dict):
    """
    Remove campos que servem só para controle de contexto.
    Eles não devem ser gravados diretamente na tabela employees.
    """
    for k in [
        "nivel_contexto",
        "cliente_id",
        "holding_id",
        "empresa_id",
        "filial_id",
        "contexto_nome",
        "admin_code"
    ]:
        data.pop(k, None)


def _is_competence_context_closed(comp: _date, ctx: dict) -> bool:
    """
    Consulta o status contextual da competência.
    Retorna True se o contexto estiver CLOSED.
    """
    comp = _month_start(comp)

    nivel_contexto = str(ctx.get("nivel_contexto") or "").strip().lower()
    cliente_id = str(ctx.get("cliente_id") or "").strip()
    holding_id = str(ctx.get("holding_id") or "").strip()
    empresa_id = str(ctx.get("empresa_id") or "").strip()
    filial_id = str(ctx.get("filial_id") or "").strip()

    if not nivel_contexto or not cliente_id:
        return False

    try:
        r = supabase.rpc("get_competence_context_status", {
            "p_competence": comp.isoformat(),
            "p_nivel_contexto": nivel_contexto,
            "p_cliente_id": cliente_id,
            "p_holding_id": holding_id or None,
            "p_empresa_id": empresa_id or None,
            "p_filial_id": filial_id or None
        }).execute()

        data = r.data

        if isinstance(data, list) and len(data) == 1:
            data = data[0]

        if isinstance(data, dict):
            return str(data.get("status") or "OPEN").upper() == "CLOSED"

        return False

    except Exception as e:
        print("[_is_competence_context_closed] erro:", e)
        return False


def _assert_competence_context_open_or_admin(comp: _date, body: dict):
    """
    Bloqueia cadastro/edição quando a competência do contexto estiver CLOSED.
    Se não vier contexto, cai na trava antiga global por compatibilidade.
    """
    comp = _month_start(comp)
    ctx = _extract_competence_context_from_body(body)

    # Se não veio contexto, mantém compatibilidade com a regra antiga.
    if not ctx.get("nivel_contexto") or not ctx.get("cliente_id"):
        _assert_competence_open_or_admin(comp)
        return

    if not _is_competence_context_closed(comp, ctx):
        return

    admin_code = ""

    try:
        admin_code = str(body.get("admin_code") or "").strip()
    except Exception:
        admin_code = ""

    if not ADMIN_WINDOW_CODE:
        raise PermissionError("Competência contextual fechada e ADMIN_WINDOW_CODE não configurado no servidor.")

    if admin_code != ADMIN_WINDOW_CODE:
        nome = ctx.get("contexto_nome") or ctx.get("nivel_contexto") or "contexto"
        raise PermissionError(
            f"Competência {comp.isoformat()} está FECHADA para {nome}. Informe admin_code válido para alterar."
        )    



# ===== CORS simples sem dependências =====
ALLOWED_ORIGINS = os.getenv('ALLOWED_ORIGINS', 'https://gestor.thehrkey.tech').split(',')

@app.after_request
def add_cors_headers(resp):
    origin = (request.headers.get('Origin', '') or '').rstrip('/')
    if origin in [o.rstrip('/') for o in ALLOWED_ORIGINS]:
        resp.headers['Access-Control-Allow-Origin'] = origin
        resp.headers['Vary'] = 'Origin'
        resp.headers['Access-Control-Allow-Methods'] = 'GET,POST,PUT,DELETE,OPTIONS'
        resp.headers['Access-Control-Allow-Headers'] = 'Content-Type,Authorization'
    return resp

@app.before_request
def handle_preflight():
    if request.method == 'OPTIONS' and request.path.startswith('/api/'):
        resp = app.make_response(('', 204))
        origin = (request.headers.get('Origin', '') or '').rstrip('/')
        if origin in [o.rstrip('/') for o in ALLOWED_ORIGINS]:
            resp.headers['Access-Control-Allow-Origin'] = origin
            resp.headers['Vary'] = 'Origin'
            resp.headers['Access-Control-Allow-Methods'] = 'GET,POST,PUT,DELETE,OPTIONS'
            resp.headers['Access-Control-Allow-Headers'] = 'Content-Type,Authorization'
        return resp


# ===================== Páginas =====================
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/manager')
def manager():
    return render_template('manager.html')

@app.route('/test')
def test():
    return "Teste funcionando!"


from flask import make_response

@app.route('/team')
def team():
    """
    Gestor acessa por link com ?t=TOKEN.
    Se o token for válido, gravamos o cookie httpOnly 'manager_access' com o manager_code.
    """
    t = (request.args.get('t') or '').strip()
    resp = make_response(render_template('manager.html'))  # reaproveita o mesmo front
    if t:
        info = verify_manager_token(t)
        if info and info.get('mc'):
            resp.set_cookie(
                'manager_access',
                info['mc'],                 # ex.: '0007'
                max_age=30*24*3600,         # 30 dias
                secure=True,
                httponly=True,
                samesite='Lax'
            )
        else:
            # token inválido: limpa cookie
            resp.set_cookie('manager_access', '', expires=0)
    return resp

from urllib.parse import urlencode

@app.route('/admin/generate-manager-link')
def admin_generate_manager_link():
    """
    Uso: /admin/generate-manager-link?manager_code=0007&days=30
    Retorna a URL para enviar ao gestor.
    """
    mc = (request.args.get('manager_code') or '').strip()
    days = int(request.args.get('days', '30') or '30')
    if not mc:
        return jsonify({"error": "Informe manager_code=XXXX (4 dígitos)"}), 400

    tok = sign_manager_token(mc, exp_seconds=days*24*3600)
    base = request.host_url.rstrip('/')
    link = f"{base}/team?{urlencode({'t': tok})}"
    return jsonify({"manager_code": mc, "valid_days": days, "link": link}), 200

@app.route('/api/auth/whoami', methods=['GET'])
def api_whoami():
    mc = request.cookies.get('manager_access')
    return jsonify({"role": ("manager" if mc else "admin"), "manager_code": mc or None}), 200


# ===================== Employees =====================
@app.route('/api/employees', methods=['GET'])
def get_employees():
    """
    Se existir o cookie manager_access, filtra os funcionários por manager_code.
    EXCEÇÃO: quando a requisição vier da tela /manager (RH), NÃO filtra.
    """
    try:
        # Detecta se a chamada veio da tela do RH
        referer = (request.headers.get('Referer') or '')
        from_manager_panel = '/manager' in referer

        # Código do gestor vindo do cookie (criado em /team?m=XXXX)
        manager_code = (request.cookies.get('manager_access') or '').strip()

        # Se existe cookie E não é a tela /manager, aplica o filtro
        if manager_code and not from_manager_panel:
            r = (
                supabase
                .table('employees')
                .select('*')
                .eq('manager_code', manager_code)
                .execute()
            )
        else:
            # RH (ou sem cookie) vê todos
            r = supabase.table('employees').select('*').execute()

        return jsonify(r.data or [])
    except Exception as e:
        print(f"Erro no endpoint /api/employees: {str(e)}")
        return jsonify({'error': str(e)}), 500



@app.route('/api/employees/by-manager', methods=['GET'])
def get_employees_by_manager():
    """
    Retorna apenas os funcionários cujo campo manager_name corresponde ao nome passado na querystring.
    Exemplo de uso: GET /api/employees/by-manager?manager_name=Maria%20Silva
    """
    try:
        manager_name = request.args.get('manager_name', '').strip()
        if not manager_name:
            return jsonify({'error': 'Parâmetro manager_name é obrigatório'}), 400

        # Busca case-insensitive (exato). Se quiser “contém”, troque eq -> ilike e use f'%{manager_name}%'
        r = supabase.table('employees') \
            .select('*') \
            .eq('manager_name', manager_name) \
            .execute()

        return jsonify(r.data or [])
    except Exception as e:
        print(f"Erro no endpoint /api/employees/by-manager: {str(e)}")
        return jsonify({'error': str(e)}), 500





@app.route('/api/employees', methods=['POST'])
def create_employee():
    try:
        data = request.get_json(silent=True) or {}

        # ✅ Competência vem da URL (?competence=YYYY-MM-01) ou fallback do helper
        comp = _competence_from_request()

        # ✅ Bloqueia cadastro se competência do contexto estiver FECHADA
        try:
            _assert_competence_context_open_or_admin(comp, data)
            _remove_context_fields_from_employee_payload(data)
        except PermissionError as e:
            return jsonify({
                "error": "COMPETENCE_CLOSED",
                "message": str(e),
                "competence": comp.isoformat(),
                "status": "CLOSED"
            }), 423

        # ✅ employees NÃO tem coluna "competence" e nem deve receber "admin_code"
        data.pop("competence", None)
        data.pop("admin_code", None)

        # 1) cria o employee
        r = supabase.table('employees').insert(data).execute()
        created = (r.data or [])
        if not created:
            return jsonify({'error': 'Falha ao criar employee (sem retorno do Supabase)'}), 500

        employee_id = created[0].get('id')
        if not employee_id:
            return jsonify({'error': 'Falha ao criar employee (id não retornou)'}), 500

        # 2) salva histórico (snapshot completo do registro criado)
        _save_employee_history(
            employee_id=int(employee_id),
            data_snapshot=created[0],
            action="CREATE",
            round_code=(data.get("round_code") or None),
            competence=comp
        )
        return jsonify(created), 201

    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ===================== Salary Grades =====================
@app.route('/api/salary-grades', methods=['GET'])
def get_salary_grades():
    try:
        r = supabase.table('salary_grades').select('*').execute()
        return jsonify(r.data)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ===================== Evaluation Criteria =====================
@app.route('/api/evaluation-criteria', methods=['GET'])
def get_evaluation_criteria():
    try:
        r = supabase.table('evaluation_criteria').select('*').order('dimension', desc=False).execute()
        return jsonify(r.data)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/evaluation-form/active', methods=['GET'])
def get_active_evaluation_form():
    try:
        employee_id = request.args.get('employee_id', type=int)

        if not employee_id:
            return jsonify({
                'error': 'EMPLOYEE_REQUIRED',
                'message': 'employee_id é obrigatório.'
            }), 400

        # 1) Descobre qual modelo ativo vale para este funcionário
        r_model = supabase.rpc(
            'get_active_evaluation_model_for_employee',
            {'p_employee_id': employee_id}
        ).execute()

        model_rows = r_model.data or []

        if not model_rows:
            return jsonify({
                'error': 'NO_ACTIVE_EVALUATION_MODEL',
                'message': 'Nenhum modelo de avaliação ativo encontrado para o contexto deste profissional.',
                'employee_id': employee_id
            }), 404

        model = model_rows[0]

        # 2) Busca critérios/afirmativas pela função SQL segura
        r_criteria = supabase.rpc(
            'get_active_evaluation_criteria_for_employee',
            {'p_employee_id': employee_id}
        ).execute()

        rows = r_criteria.data or []

        if not rows:
            return jsonify({
                'error': 'NO_ACTIVE_CRITERIA',
                'message': 'Nenhuma afirmativa ativa encontrada para o modelo deste profissional.',
                'employee_id': employee_id,
                'model': model
            }), 404

        # 3) Monta saída compatível com o front antigo
        criteria = []

        for row in rows:
            criteria.append({
                'id': row.get('criterio_id'),
                'dimension': row.get('dimension'),
                'type': row.get('type'),
                'name': row.get('name'),
                'description': row.get('description'),
                'weight': row.get('weight'),

                # campos novos para rastreabilidade
                'modelo_avaliacao_id': row.get('modelo_avaliacao_id'),
                'versao_modelo_id': row.get('versao_modelo_id'),
                'dimensao_id': row.get('dimensao_id'),
                'afirmativa_avaliacao_id': row.get('afirmativa_avaliacao_id'),
                'eixo_9box': row.get('eixo_9box'),
                'peso_usado': row.get('peso_usado'),
                'ordem_dimensao': row.get('ordem_dimensao'),
                'ordem_afirmativa': row.get('ordem_afirmativa')
            })

        return jsonify({
            'model': model,
            'criteria': criteria
        }), 200

    except Exception as e:
        return jsonify({
            'error': 'INTERNAL_ERROR',
            'message': str(e)
        }), 500

@app.route('/api/evaluation-criteria', methods=['POST'])
def create_evaluation_criteria():
    try:
        data = request.get_json()
        r = supabase.table('evaluation_criteria').insert(data).execute()
        return jsonify(r.data)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/evaluation-criteria/<int:criteria_id>', methods=['PUT'])
def update_evaluation_criteria(criteria_id):
    try:
        data = request.get_json()
        r = supabase.table('evaluation_criteria').update(data).eq('id', criteria_id).execute()
        return jsonify(r.data)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ===================== Cálculos de avaliação =====================
def calculate_evaluation_scores(evaluation_id, responses, goals_data, dimension_weights):
    """Calcula médias de dimensões, metas, final ponderado e posição 9-box."""
    try:
        criteria_response = supabase.table('evaluation_criteria').select('*').execute()
        criteria = {c['id']: c for c in criteria_response.data}

        dimension_ratings = {
            'INSTITUCIONAL': [],
            'FUNCIONAL': [],
            'INDIVIDUAL': []
        }

        for criteria_id, rating in responses.items():
            cid = int(criteria_id)
            if cid in criteria:
                dimension = criteria[cid]['dimension']
                dimension_ratings[dimension].append(float(rating))

        institucional_avg = sum(dimension_ratings['INSTITUCIONAL']) / len(dimension_ratings['INSTITUCIONAL']) if dimension_ratings['INSTITUCIONAL'] else 0
        funcional_avg     = sum(dimension_ratings['FUNCIONAL'])     / len(dimension_ratings['FUNCIONAL'])     if dimension_ratings['FUNCIONAL']     else 0
        individual_avg    = sum(dimension_ratings['INDIVIDUAL'])    / len(dimension_ratings['INDIVIDUAL'])    if dimension_ratings['INDIVIDUAL']    else 0

        # ===================== MÉDIA DE METAS (AGORA PONDERADA PELO PESO) =====================
        # Se as metas tiverem "weight", usamos média ponderada.
        # Se não tiver peso válido, caímos para a média simples (comportamento antigo).
        goal_ratings = []
        total_weight = 0.0
        weighted_sum = 0.0

        for g in (goals_data or []):
            rating_raw = g.get('rating')
            if rating_raw is None:
                continue

            try:
                rating = float(rating_raw)
            except (TypeError, ValueError):
                continue

            goal_ratings.append(rating)

            # peso da meta (pode estar em % ou só como número relativo)
            try:
                w_goal = float(g.get('weight') or 0)
            except (TypeError, ValueError):
                w_goal = 0.0

            if w_goal > 0:
                total_weight += w_goal
                weighted_sum += rating * w_goal

        if total_weight > 0:
            metas_avg = weighted_sum / total_weight
        elif goal_ratings:
            # fallback: se não tiver peso, usa média simples como antes
            metas_avg = sum(goal_ratings) / len(goal_ratings)
        else:
            metas_avg = 0.0


        w = {
            'INSTITUCIONAL': float(dimension_weights.get('INSTITUCIONAL', 25)),
            'FUNCIONAL':     float(dimension_weights.get('FUNCIONAL', 25)),
            'INDIVIDUAL':    float(dimension_weights.get('INDIVIDUAL', 25)),
            'METAS':         float(dimension_weights.get('METAS', 25)),
        }
        final_rating = (
            institucional_avg * (w['INSTITUCIONAL']/100.0) +
            funcional_avg     * (w['FUNCIONAL']/100.0) +
            individual_avg    * (w['INDIVIDUAL']/100.0) +
            metas_avg         * (w['METAS']/100.0)
        )

        # Desempenho/Potencial baseados em type do critério
        perf_list, pot_list = [], []
        for criteria_id, rating in responses.items():
            cid = int(criteria_id)
            if cid in criteria:
                t = criteria[cid]['type']
                if t == 'DESEMPENHO':
                    perf_list.append(float(rating))
                elif t == 'POTENCIAL':
                    pot_list.append(float(rating))
        performance_rating = sum(perf_list)/len(perf_list) if perf_list else 0
        potential_rating   = sum(pot_list)/len(pot_list) if pot_list else 0

        nine_box_position = calculate_nine_box_position(performance_rating, potential_rating)

        def rating_to_9box(r):
            rounded = round(r, 1)
            table = {
                1.0: 9.0, 1.1: 8.8, 1.2: 8.6, 1.3: 8.4, 1.4: 8.2, 1.5: 8.0,
                1.6: 7.8, 1.7: 7.6, 1.8: 7.4, 1.9: 7.2, 2.0: 7.0, 2.1: 6.8,
                2.2: 6.6, 2.3: 6.4, 2.4: 6.2, 2.5: 6.0, 2.6: 5.8, 2.7: 5.6,
                2.8: 5.4, 2.9: 5.2, 3.0: 5.0, 3.1: 4.8, 3.2: 4.6, 3.3: 4.4,
                3.4: 4.2, 3.5: 4.0, 3.6: 3.8, 3.7: 3.6, 3.8: 3.4, 3.9: 3.2,
                4.0: 3.0, 4.1: 2.8, 4.2: 2.6, 4.3: 2.4, 4.4: 2.2, 4.5: 2.0,
                4.6: 1.8, 4.7: 1.6, 4.8: 1.4, 4.9: 1.2, 5.0: 1.0
            }
            return table.get(rounded, 10 - (rounded*2))

        performance_9box = rating_to_9box(performance_rating)
        potential_9box   = rating_to_9box(potential_rating)

        return {
            'institucional_avg': round(institucional_avg, 2),
            'funcional_avg': round(funcional_avg, 2),
            'individual_avg': round(individual_avg, 2),
            'metas_avg': round(metas_avg, 2),
            'final_rating': round(final_rating, 2),
            'performance_rating': round(performance_9box, 2),  # escala 1–9
            'potential_rating': round(potential_9box, 2),      # escala 1–9
            'nine_box_position': nine_box_position
        }
    except Exception as e:
        print(f"Erro ao calcular scores: {e}")
        return None

def calculate_nine_box_position(performance, potential):
    def rating_to_9box(r):
        rounded = round(r, 1)
        table = {
            1.0: 9.0, 1.1: 8.8, 1.2: 8.6, 1.3: 8.4, 1.4: 8.2, 1.5: 8.0,
            1.6: 7.8, 1.7: 7.6, 1.8: 7.4, 1.9: 7.2, 2.0: 7.0, 2.1: 6.8,
            2.2: 6.6, 2.3: 6.4, 2.4: 6.2, 2.5: 6.0, 2.6: 5.8, 2.7: 5.6,
            2.8: 5.4, 2.9: 5.2, 3.0: 5.0, 3.1: 4.8, 3.2: 4.6, 3.3: 4.4,
            3.4: 4.2, 3.5: 4.0, 3.6: 3.8, 3.7: 3.6, 3.8: 3.4, 3.9: 3.2,
            4.0: 3.0, 4.1: 2.8, 4.2: 2.6, 4.3: 2.4, 4.4: 2.2, 4.5: 2.0,
            4.6: 1.8, 4.7: 1.6, 4.8: 1.4, 4.9: 1.2, 5.0: 1.0
        }
        return table.get(rounded, 10 - (rounded*2))

    perf9 = rating_to_9box(performance)
    pot9  = rating_to_9box(potential)

    perf_pos = 1 if perf9 >= 7 else (2 if perf9 >= 4 else 3)  # Alto/Médio/Baixo
    pot_pos  = 1 if pot9  >= 7 else (2 if pot9  >= 4 else 3)

    return (pot_pos - 1) * 3 + (4 - perf_pos)

# ===================== Última Avaliação =====================
def _get_responses_rows(evaluation_id: int):
    r = (supabase.table('evaluation_responses')
         .select('evaluation_id,criteria_id,rating,manager_comment')
         .eq('evaluation_id', evaluation_id)
         .order('criteria_id', desc=False)
         .execute())
    rows = r.data or []
    return [{
        'evaluation_id': x.get('evaluation_id'),
        'criteria_id': x.get('criteria_id'),
        'rating': x.get('rating'),
        'manager_comment': x.get('manager_comment')
    } for x in rows]

@app.route('/api/evaluations/latest', methods=['GET'])
def api_evaluations_latest():
    try:
        employee_id = request.args.get('employee_id', type=int)
        if not employee_id:
            return jsonify({'error': 'employee_id obrigatório'}), 400

        # Buscar avaliação

        
        # ✅ CORREÇÃO: Buscar avaliação por employee_id + round_code (se fornecido)
        round_code = request.args.get('round_code', '').strip()
        
        query = supabase.table('evaluations').select('*').eq('employee_id', employee_id)
        
        # Se round_code foi fornecido, filtrar por ele
        if round_code:
            query = query.eq('round_code', round_code)
        
        r_ev = query.order('evaluation_date', desc=True).order('created_at', desc=True).limit(1).execute()

        
        data = r_ev.data or []
        if not data:
            return jsonify({'error': 'nenhuma_avaliacao'}), 404
        ev = data[0]

        # Buscar respostas
        r_resp = (supabase.table('evaluation_responses')
                  .select('evaluation_id,criteria_id,rating,manager_comment')
                  .eq('evaluation_id', ev['id'])
                  .order('criteria_id', desc=False)
                  .execute())
        rows = r_resp.data or []

        responses = [{
            'evaluation_id': x.get('evaluation_id'),
            'criteria_id': x.get('criteria_id'),
            'rating': x.get('rating'),
            'manager_comment': x.get('manager_comment')
        } for x in rows]

        # Buscar metas da tabela individual_goals (FILTRANDO por employee_id + round_code + evaluation_id)
        goals = []
        try:
            goals_round = (round_code or ev.get('round_code') or '').strip()
            
            print(f"[DEBUG METAS] employee_id={employee_id}, round_code={goals_round}, evaluation_id={ev['id']}")
            
            # ✅ CORREÇÃO: Agora que a coluna evaluation_id existe, filtra por ela também
            q = (supabase.table('individual_goals')
                 .select('*')
                 .eq('employee_id', employee_id)
                 .eq('evaluation_id', ev['id']))  # ← ADICIONE ESTA LINHA
            
            if goals_round:
                q = q.eq('round_code', goals_round)
            
            r_goals = q.order('id', desc=False).execute()
            goals_data = r_goals.data or []
            
            print(f"[DEBUG METAS] Metas encontradas: {len(goals_data)}")
            
            for goal in goals_data:
                goals.append({
                    'round_code': goal.get('round_code'),
                    'index': goal.get('goal_index', 1),
                    'name': goal.get('goal_name', ''),
                    'description': goal.get('goal_description', ''),
                    'weight': float(goal.get('weight', 0) or 0),
                    'rating_1_criteria': goal.get('rating_1_criteria', ''),
                    'rating_2_criteria': goal.get('rating_2_criteria', ''),
                    'rating_3_criteria': goal.get('rating_3_criteria', ''),
                    'rating_4_criteria': goal.get('rating_4_criteria', ''),
                    'rating_5_criteria': goal.get('rating_5_criteria', ''),
                    'rating': int(goal.get('rating', 0)) if goal.get('rating') is not None else None
                })
            
            print(f"[DEBUG METAS] Total de metas processadas: {len(goals)}")
        
        except Exception as e:
            print(f"Erro ao buscar metas: {e}")
            import traceback
            traceback.print_exc()
            goals = []              
        
        # Pesos das dimensões - usar valores salvos ou padrão
        weights = {}
        if ev.get('dimension_weights'):
            # Se tem dimension_weights salvo, usa ele
            weights = ev['dimension_weights']
        else:
            # Fallback para colunas individuais (se existirem)
            weights = {
                'INSTITUCIONAL': float(ev.get('weight_institucional', 0)),
                'FUNCIONAL':     float(ev.get('weight_funcional', 0)),
                'INDIVIDUAL':    float(ev.get('weight_individual', 0)),
                'METAS':         float(ev.get('weight_metas', 0)),
            }

        return jsonify({
            'build_id': 'GOALS_FIX_001',
            'debug_rc': round_code,
            'debug_emp': employee_id,
            'evaluation': ev,
            'responses': responses,
            'weights': weights,
            'goals': goals
        })
    except Exception as e:
        return jsonify({'error': 'internal', 'detail': str(e)}), 500


# Compat: pegar respostas por evaluation_id
@app.route('/api/evaluation-responses', methods=['GET'])
def api_evaluation_responses():
    evaluation_id = request.args.get('evaluation_id', type=int)
    if not evaluation_id:
        return jsonify({'error': 'evaluation_id obrigatório'}), 400
    return jsonify(_get_responses_rows(evaluation_id))


# ✅ Rota para o dashboard: lista responses por round_code (e opcionalmente por year)
@app.route('/api/evaluation_responses', methods=['GET'])
def api_evaluation_responses_dashboard():
    try:
        round_code = (request.args.get('round_code') or '').strip() or None

        year_param = (request.args.get('year') or '').strip()
        year = None
        try:
            if year_param:
                year = int(year_param)
        except Exception:
            year = None

        # Segurança: se não vier NADA, devolve vazio (evita puxar tudo)
        if not round_code and not year:
            return jsonify([]), 200

        # 1) Buscar IDs das avaliações filtrando pelo round_code (prioridade) e/ou year
        eval_query = supabase.table('evaluations').select('id')

        if round_code:
            eval_query = eval_query.eq('round_code', round_code)

        if year:
            eval_query = eval_query.eq('evaluation_year', year)

        r_eval = eval_query.execute()
        eval_rows = r_eval.data or []
        eval_ids = [row.get('id') for row in eval_rows if row.get('id') is not None]

        if not eval_ids:
            return jsonify([]), 200

        # 2) Buscar responses dessas avaliações
        r_resp = (
            supabase
            .table('evaluation_responses')
            .select('*')
            .in_('evaluation_id', eval_ids)
            .execute()
        )

        return jsonify(r_resp.data or []), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500

        # 2) Buscar responses dessas avaliações
        # Ajuste o nome da tabela aqui SE a sua tabela tiver outro nome.
        # Pelo seu código (_get_responses_rows), o mais comum é "evaluation_responses".
        r_resp = (
            supabase
            .table('evaluation_responses')
            .select('*')
            .in_('evaluation_id', eval_ids)
            .execute()
        )

        return jsonify(r_resp.data or []), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ===================== Competência: Fechar / Reabrir =====================
@app.route("/api/competence/status", methods=["GET"])
def api_competence_status():
    """
    GET /api/competence/status?competence=YYYY-MM-01

    Agora suporta status contextual:
      ?competence=YYYY-MM-01
      &nivel_contexto=holding
      &cliente_id=...
      &holding_id=...
      &empresa_id=...
      &filial_id=...

    Se vier contexto, lê public.competence_context_locks.
    Se não vier contexto, mantém compatibilidade lendo public.competence_locks.
    """
    try:
        comp_str = (request.args.get("competence") or "").strip()
        if comp_str:
            comp = _month_start(datetime.fromisoformat(comp_str).date())
        else:
            comp = _month_start(_competence_from_request())

        nivel_contexto = (request.args.get("nivel_contexto") or "").strip().lower()
        cliente_id = (request.args.get("cliente_id") or "").strip()
        holding_id = (request.args.get("holding_id") or "").strip()
        empresa_id = (request.args.get("empresa_id") or "").strip()
        filial_id = (request.args.get("filial_id") or "").strip()

        # =========================================================
        # 1) STATUS CONTEXTUAL
        # =========================================================
        if nivel_contexto and cliente_id:
            r = supabase.rpc("get_competence_context_status", {
                "p_competence": comp.isoformat(),
                "p_nivel_contexto": nivel_contexto,
                "p_cliente_id": cliente_id,
                "p_holding_id": holding_id or None,
                "p_empresa_id": empresa_id or None,
                "p_filial_id": filial_id or None
            }).execute()

            data = r.data

            if isinstance(data, list) and len(data) == 1:
                data = data[0]

            if not data:
                return jsonify({
                    "competence": comp.isoformat(),
                    "status": "OPEN",
                    "exists": False,
                    "nivel_contexto": nivel_contexto,
                    "cliente_id": cliente_id,
                    "holding_id": holding_id or None,
                    "empresa_id": empresa_id or None,
                    "filial_id": filial_id or None
                }), 200

            if isinstance(data, dict):
                if "exists_lock" in data:
                    data["exists"] = data.pop("exists_lock")

            return jsonify(data), 200
        # =========================================================
        # 2) FALLBACK ANTIGO GLOBAL, para não quebrar telas antigas
        # =========================================================
        r = (
            supabase.table("competence_locks")
            .select("competence,status,closed_at,closed_by,closed_reason,reopened_at,reopened_by,reopen_reason")
            .eq("competence", comp.isoformat())
            .execute()
        )

        rows = r.data or []
        row = rows[0] if rows else None

        if not row:
            return jsonify({
                "competence": comp.isoformat(),
                "status": "OPEN",
                "exists": False
            }), 200

        return jsonify({
            "competence": row.get("competence"),
            "status": row.get("status") or "OPEN",
            "exists": True,

            "locked_at": row.get("closed_at"),
            "locked_by": row.get("closed_by"),
            "reason": row.get("closed_reason"),

            "reopened_at": row.get("reopened_at"),
            "reopened_by": row.get("reopened_by"),
            "reopen_reason": row.get("reopen_reason"),
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/competence/close", methods=["POST"])
def api_competence_close():
    """
    POST /api/competence/close

    Agora também é contextual.
    Body esperado:
      {
        "competence": "YYYY-MM-01",
        "admin_code": "...",
        "notes": "...",

        "nivel_contexto": "holding|empresa|filial|cliente",
        "cliente_id": "...",
        "holding_id": "...",
        "empresa_id": "...",
        "filial_id": "...",
        "contexto_nome": "..."
      }

    Importante:
    - Não fecha mais globalmente sem contexto.
    - Usa a mesma RPC contextual do finalize.
    """
    try:
        body = request.get_json(silent=True) or {}

        admin_code = str(body.get("admin_code") or "").strip()
        if not ADMIN_WINDOW_CODE:
            return jsonify({"error": "ADMIN_WINDOW_CODE não configurado no servidor."}), 500
        if admin_code != ADMIN_WINDOW_CODE:
            return jsonify({"error": "admin_code inválido."}), 403

        comp_str = str(body.get("competence") or "").strip()
        if not comp_str:
            return jsonify({"error": "competence obrigatória no formato YYYY-MM-01"}), 400

        comp = _month_start(datetime.fromisoformat(comp_str).date())
        notes = str(body.get("notes") or body.get("reason") or "").strip() or None

        nivel_contexto = str(body.get("nivel_contexto") or "").strip().lower()
        cliente_id = str(body.get("cliente_id") or "").strip()
        holding_id = str(body.get("holding_id") or "").strip()
        empresa_id = str(body.get("empresa_id") or "").strip()
        filial_id = str(body.get("filial_id") or "").strip()
        contexto_nome = str(body.get("contexto_nome") or "").strip() or None

        if not nivel_contexto:
            return jsonify({
                "error": "CONTEXT_REQUIRED",
                "message": "Fechamento global bloqueado. Informe nivel_contexto."
            }), 400

        if nivel_contexto not in ["cliente", "holding", "empresa", "filial"]:
            return jsonify({
                "error": "INVALID_CONTEXT_LEVEL",
                "message": "nivel_contexto inválido. Use cliente, holding, empresa ou filial."
            }), 400

        if not cliente_id:
            return jsonify({
                "error": "CLIENTE_ID_REQUIRED",
                "message": "cliente_id é obrigatório para fechamento contextual."
            }), 400

        if nivel_contexto == "holding" and not holding_id:
            return jsonify({
                "error": "HOLDING_ID_REQUIRED",
                "message": "holding_id é obrigatório para fechar competência por holding."
            }), 400

        if nivel_contexto == "empresa" and not empresa_id:
            return jsonify({
                "error": "EMPRESA_ID_REQUIRED",
                "message": "empresa_id é obrigatório para fechar competência por empresa."
            }), 400

        if nivel_contexto == "filial" and not filial_id:
            return jsonify({
                "error": "FILIAL_ID_REQUIRED",
                "message": "filial_id é obrigatório para fechar competência por filial."
            }), 400

        r = supabase.rpc("close_competence_contextual", {
            "p_competence": comp.isoformat(),
            "p_closed_by": _get_actor(),
            "p_closed_reason": notes,
            "p_nivel_contexto": nivel_contexto,
            "p_cliente_id": cliente_id,
            "p_holding_id": holding_id or None,
            "p_empresa_id": empresa_id or None,
            "p_filial_id": filial_id or None,
            "p_contexto_nome": contexto_nome
        }).execute()

        data = r.data

        if isinstance(data, list) and len(data) == 1:
            data = data[0]

        if isinstance(data, dict):
            if "out_competence" in data:
                data["competence"] = data.pop("out_competence")
            if "out_next_competence" in data:
                data["next_competence"] = data.pop("out_next_competence")

        return jsonify(data), 200

    except Exception as e:
        return jsonify({
            "error": "CLOSE_CONTEXTUAL_FAILED",
            "details": str(e),
            "traceback": traceback.format_exc()
        }), 500


from postgrest.exceptions import APIError
import traceback

@app.route("/api/competence/finalize", methods=["POST"])
def api_competence_finalize():
    """
    POST /api/competence/finalize

    Agora é contextual.
    Body esperado:
      {
        "competence": "YYYY-MM-01",
        "admin_code": "...",
        "reason": "...",

        "nivel_contexto": "holding|empresa|filial|cliente",
        "cliente_id": "...",
        "holding_id": "...",
        "empresa_id": "...",
        "filial_id": "...",
        "contexto_nome": "..."
      }

    Importante:
    - Não fecha mais globalmente sem contexto.
    - Chama a RPC public.finalize_competence_contextual.
    """
    try:
        body = request.get_json(silent=True) or {}

        admin_code = str(body.get("admin_code") or "").strip()
        if not ADMIN_WINDOW_CODE:
            return jsonify({"error": "ADMIN_WINDOW_CODE não configurado no servidor."}), 500
        if admin_code != ADMIN_WINDOW_CODE:
            return jsonify({"error": "admin_code inválido."}), 403

        comp_str = str(body.get("competence") or "").strip()
        if not comp_str:
            return jsonify({"error": "competence obrigatória no formato YYYY-MM-01"}), 400

        comp = _month_start(datetime.fromisoformat(comp_str).date())
        reason = str(body.get("reason") or "").strip() or None

        nivel_contexto = str(body.get("nivel_contexto") or "").strip().lower()
        cliente_id = str(body.get("cliente_id") or "").strip()
        holding_id = str(body.get("holding_id") or "").strip()
        empresa_id = str(body.get("empresa_id") or "").strip()
        filial_id = str(body.get("filial_id") or "").strip()
        contexto_nome = str(body.get("contexto_nome") or "").strip() or None

        if not nivel_contexto:
            return jsonify({
                "error": "CONTEXT_REQUIRED",
                "message": "Fechamento global bloqueado. Informe nivel_contexto."
            }), 400

        if nivel_contexto not in ["cliente", "holding", "empresa", "filial"]:
            return jsonify({
                "error": "INVALID_CONTEXT_LEVEL",
                "message": "nivel_contexto inválido. Use cliente, holding, empresa ou filial."
            }), 400

        if not cliente_id:
            return jsonify({
                "error": "CLIENTE_ID_REQUIRED",
                "message": "cliente_id é obrigatório para fechamento contextual."
            }), 400

        if nivel_contexto == "holding" and not holding_id:
            return jsonify({
                "error": "HOLDING_ID_REQUIRED",
                "message": "holding_id é obrigatório para fechar competência por holding."
            }), 400

        if nivel_contexto == "empresa" and not empresa_id:
            return jsonify({
                "error": "EMPRESA_ID_REQUIRED",
                "message": "empresa_id é obrigatório para fechar competência por empresa."
            }), 400

        if nivel_contexto == "filial" and not filial_id:
            return jsonify({
                "error": "FILIAL_ID_REQUIRED",
                "message": "filial_id é obrigatório para fechar competência por filial."
            }), 400

        try:
            r = supabase.rpc("finalize_competence_contextual", {
                "p_competence": comp.isoformat(),
                "p_closed_by": _get_actor(),
                "p_closed_reason": reason,
                "p_nivel_contexto": nivel_contexto,
                "p_cliente_id": cliente_id,
                "p_holding_id": holding_id or None,
                "p_empresa_id": empresa_id or None,
                "p_filial_id": filial_id or None,
                "p_contexto_nome": contexto_nome
            }).execute()

            data = r.data

        except APIError as e:
            payload = e.args[0] if e.args else None
            if isinstance(payload, dict) and payload.get("message"):
                return jsonify(payload), 200
            raise

        if isinstance(data, list) and len(data) == 1:
            data = data[0]

        if isinstance(data, dict):
            if "out_competence" in data:
                data["competence"] = data.pop("out_competence")
            if "out_next_competence" in data:
                data["next_competence"] = data.pop("out_next_competence")

        return jsonify(data), 200

    except Exception as e:
        return jsonify({
            "error": "FINALIZE_CONTEXTUAL_FAILED",
            "details": str(e),
            "traceback": traceback.format_exc()
        }), 500


@app.route("/api/competence/reopen", methods=["POST"])
def api_competence_reopen():
    """
    POST /api/competence/reopen

    Agora é contextual.
    Body esperado:
      {
        "competence": "YYYY-MM-01",
        "admin_code": "...",
        "notes": "...",

        "nivel_contexto": "holding|empresa|filial|cliente",
        "cliente_id": "...",
        "holding_id": "...",
        "empresa_id": "...",
        "filial_id": "...",
        "contexto_nome": "..."
      }

    Importante:
    - Não reabre mais globalmente sem contexto.
    - Reabre apenas o contexto informado.
    """
    try:
        body = request.get_json(silent=True) or {}

        admin_code = str(body.get("admin_code") or "").strip()
        if not ADMIN_WINDOW_CODE:
            return jsonify({"error": "ADMIN_WINDOW_CODE não configurado no servidor."}), 500
        if admin_code != ADMIN_WINDOW_CODE:
            return jsonify({"error": "admin_code inválido."}), 403

        comp_str = str(body.get("competence") or "").strip()
        if not comp_str:
            return jsonify({"error": "competence obrigatória no formato YYYY-MM-01"}), 400

        comp = _month_start(datetime.fromisoformat(comp_str).date())
        notes = str(body.get("notes") or body.get("reason") or "").strip() or None

        nivel_contexto = str(body.get("nivel_contexto") or "").strip().lower()
        cliente_id = str(body.get("cliente_id") or "").strip()
        holding_id = str(body.get("holding_id") or "").strip()
        empresa_id = str(body.get("empresa_id") or "").strip()
        filial_id = str(body.get("filial_id") or "").strip()
        contexto_nome = str(body.get("contexto_nome") or "").strip() or None

        if not nivel_contexto:
            return jsonify({
                "error": "CONTEXT_REQUIRED",
                "message": "Reabertura global bloqueada. Informe nivel_contexto."
            }), 400

        if nivel_contexto not in ["cliente", "holding", "empresa", "filial"]:
            return jsonify({
                "error": "INVALID_CONTEXT_LEVEL",
                "message": "nivel_contexto inválido. Use cliente, holding, empresa ou filial."
            }), 400

        if not cliente_id:
            return jsonify({
                "error": "CLIENTE_ID_REQUIRED",
                "message": "cliente_id é obrigatório para reabertura contextual."
            }), 400

        if nivel_contexto == "holding" and not holding_id:
            return jsonify({
                "error": "HOLDING_ID_REQUIRED",
                "message": "holding_id é obrigatório para reabrir competência por holding."
            }), 400

        if nivel_contexto == "empresa" and not empresa_id:
            return jsonify({
                "error": "EMPRESA_ID_REQUIRED",
                "message": "empresa_id é obrigatório para reabrir competência por empresa."
            }), 400

        if nivel_contexto == "filial" and not filial_id:
            return jsonify({
                "error": "FILIAL_ID_REQUIRED",
                "message": "filial_id é obrigatório para reabrir competência por filial."
            }), 400

        r = supabase.rpc("reopen_competence_contextual", {
            "p_competence": comp.isoformat(),
            "p_reopened_by": _get_actor(),
            "p_reopen_reason": notes,
            "p_nivel_contexto": nivel_contexto,
            "p_cliente_id": cliente_id,
            "p_holding_id": holding_id or None,
            "p_empresa_id": empresa_id or None,
            "p_filial_id": filial_id or None,
            "p_contexto_nome": contexto_nome
        }).execute()
        
        data = r.data
        
        if isinstance(data, list) and len(data) == 1:
            data = data[0]
        
        if isinstance(data, dict):
            if "out_competence" in data:
                data["competence"] = data.pop("out_competence")
        
        return jsonify(data), 200

    except Exception as e:
        return jsonify({
            "error": "REOPEN_CONTEXTUAL_FAILED",
            "details": str(e),
            "traceback": traceback.format_exc()
        }), 500




# ===================== Evaluations CRUD =====================
@app.route('/api/evaluations', methods=['GET'])
def get_evaluations():
    try:
        # ✅ aceita ?year=2025
        year_param = (request.args.get('year') or '').strip()
        year = None
        try:
            if year_param:
                year = int(year_param)
        except Exception:
            year = None

        query = supabase.table('evaluations').select('*')

        # se vier year, filtra por evaluation_year
        if year:
            query = query.eq('evaluation_year', year)

        r = query.execute()
        return jsonify(r.data or [])
    except Exception as e:
        return jsonify({'error': str(e)}), 500




@app.route('/api/evaluations', methods=['POST'])
def create_evaluation():
    try:
        data = request.get_json()

        # --- BLOQUEIO POR JANELA (usa helper is_window_open) ---
        open_now, _, _, _ = is_window_open()
        override_code = (data.get('code') or '').strip()
        if not open_now:
            if not ADMIN_WINDOW_CODE or override_code != ADMIN_WINDOW_CODE:
                return jsonify({'error': 'Janela de avaliação fechada'}), 403

        if not data.get('employee_id') or not data.get('responses'):
            return jsonify({'error': 'Dados obrigatórios não fornecidos'}), 400

        print(f"DEBUG: round_code recebido: {data.get('round_code')}")
        print(f"DEBUG: dados completos: {data}")



        # ✅ Define ano da avaliação com base no round_code, quando possível
        # Ex.: Start2026, IR2026, YE2026 -> 2026
        round_code_raw = str(data.get('round_code') or '').strip()
        evaluation_year_value = data.get('evaluation_year', None)

        try:
            import re
            m_year = re.search(r'(20\d{2})', round_code_raw)
            if m_year:
                evaluation_year_value = int(m_year.group(1))
            elif evaluation_year_value:
                evaluation_year_value = int(evaluation_year_value)
            else:
                evaluation_year_value = _date.today().year
        except Exception:
            evaluation_year_value = _date.today().year


        

        evaluation_data = {
           'employee_id': data['employee_id'],
           'evaluator_id': data.get('evaluator_id', 1),
           'evaluation_year': evaluation_year_value,
           'round_code': data.get('round_code'),
            
           'dimension_weights': data.get('dimension_weights', {}),
           'dimension_averages': data.get('dimension_averages', {}),
           'final_rating': data.get('final_rating'),
           'goals_average': data.get('goals_average'),

           # ✅ rastreabilidade multiempresa / modelo
           'cliente_id': data.get('cliente_id'),
           'empresa_id': data.get('empresa_id'),
           'filial_id': data.get('filial_id'),
           'modelo_avaliacao_id': data.get('modelo_avaliacao_id'),
           'versao_modelo_id': data.get('versao_modelo_id')
       }
        
        # ✅ CORREÇÃO: Verificar se já existe avaliação para este funcionário + rodada
        round_code = data.get('round_code', '').strip()
        is_update = data.get('update', False) or data.get('action') == 'update'
        existing_eval_id = data.get('id') or data.get('evaluation_id')
        
        # Se veio com ID explícito (update), usar esse ID
        if existing_eval_id and is_update:
            evaluation_id = int(existing_eval_id)
            print(f"DEBUG: Atualizando avaliação existente ID: {evaluation_id}")
            supabase.table('evaluations').update(evaluation_data).eq('id', evaluation_id).execute()
        else:
            # Buscar avaliação existente por employee_id + round_code
            query = supabase.table('evaluations').select('id').eq('employee_id', data['employee_id'])
            
            if round_code:
                query = query.eq('round_code', round_code)
            else:
                # Se não tem round_code, busca pelo ano (compatibilidade)
                query = query.eq('evaluation_year', data.get('evaluation_year', 2025))
            
            existing_eval = query.execute()
            
            if existing_eval.data:
                # Atualizar avaliação existente
                evaluation_id = existing_eval.data[0]['id']
                print(f"DEBUG: Avaliação {evaluation_id} encontrada e atualizada (employee_id={data['employee_id']}, round_code={round_code})")
                supabase.table('evaluations').update(evaluation_data).eq('id', evaluation_id).execute()
            else:
                # Criar nova avaliação
                evaluation_response = supabase.table('evaluations').insert(evaluation_data).execute()
                if not evaluation_response.data:
                    return jsonify({'error': 'Erro ao criar avaliação'}), 500
                evaluation_id = evaluation_response.data[0]['id']
                print(f"DEBUG: Nova avaliação {evaluation_id} criada (employee_id={data['employee_id']}, round_code={round_code})")

        # ✅ CORREÇÃO: Deletar respostas antigas antes de inserir novas (para não acumular)
        try:
            supabase.table('evaluation_responses').delete().eq('evaluation_id', evaluation_id).execute()
            print(f"DEBUG: Respostas antigas deletadas para avaliação {evaluation_id}")
        except Exception as e:
            print(f"DEBUG: Erro ao deletar respostas antigas: {e}")
        
                # ✅ Mapa de critérios/afirmativas do modelo ativo do funcionário
        # Usado para gravar cada resposta com rastreabilidade completa:
        # afirmativa_avaliacao_id, peso_usado e eixo_9box_usado.
        criteria_map = {}

        try:
            r_crit = supabase.rpc(
                'get_active_evaluation_criteria_for_employee',
                {'p_employee_id': int(data['employee_id'])}
            ).execute()

            for row in (r_crit.data or []):
                cid = row.get('criterio_id')
                if cid is not None:
                    criteria_map[int(cid)] = row

            print(f"DEBUG: criteria_map carregado com {len(criteria_map)} critérios")

        except Exception as e:
            print(f"DEBUG: erro ao carregar criteria_map: {e}")
            criteria_map = {}

        # Inserir novas respostas
        responses = []

        criteria_comments = data.get('criteria_comments') or data.get('comments_by_criteria') or {}

        if isinstance(criteria_comments, str):
            try:
                criteria_comments = json.loads(criteria_comments)
            except Exception:
                criteria_comments = {}

        
        for criteria_id, rating in data['responses'].items():
            cid = int(criteria_id)
            meta = criteria_map.get(cid, {})

            responses.append({
                'evaluation_id': evaluation_id,
                'criteria_id': cid,
                'rating': int(rating),

                # ✅ rastreabilidade multiempresa / modelo
                'cliente_id': data.get('cliente_id'),
                'modelo_avaliacao_id': data.get('modelo_avaliacao_id'),
                'versao_modelo_id': data.get('versao_modelo_id'),

                # ✅ rastreabilidade por afirmativa
                'afirmativa_avaliacao_id': meta.get('afirmativa_avaliacao_id'),
                'eixo_9box_usado': meta.get('eixo_9box'),
                'peso_usado': meta.get('peso_usado'),

                # ✅ comentário do gestor por afirmação/rating
                'manager_comment': str(criteria_comments.get(str(cid)) or criteria_comments.get(cid) or '').strip()
            })

        
        if responses:
            supabase.table('evaluation_responses').insert(responses).execute()
            print(f"DEBUG: {len(responses)} respostas inseridas para avaliação {evaluation_id}")
            
        # ✅ CORREÇÃO: Deletar apenas as metas desta avaliação específica (não todas do funcionário)
        try:
            delete_query = supabase.table('individual_goals').delete().eq('evaluation_id', evaluation_id)
            if round_code:
                delete_query = delete_query.eq('round_code', round_code)
            delete_query.execute()
            print(f"DEBUG: Metas antigas deletadas para avaliação {evaluation_id} (employee_id={data['employee_id']}, round_code={round_code})")
        except Exception as e:
            print(f"DEBUG: Erro ao deletar metas antigas: {e}")
        
        # Salvar metas na tabela individual_goals
        if data.get('goals'):
            goals_to_save = []
            for goal in data['goals']:
                goals_to_save.append({
                    'employee_id': data['employee_id'],
                    'evaluation_id': evaluation_id,
                    'round_code': round_code or data.get('round_code', ''),

                    # ✅ rastreabilidade multiempresa / modelo
                    'cliente_id': data.get('cliente_id'),
                    'empresa_id': data.get('empresa_id'),
                    'filial_id': data.get('filial_id'),
                    'modelo_avaliacao_id': data.get('modelo_avaliacao_id'),
                    'versao_modelo_id': data.get('versao_modelo_id'),

                    'goal_name': goal.get('name', ''),

                    
                    'goal_description': goal.get('description', ''),
                    'weight': float(goal.get('weight', 0)),
                    'rating_1_criteria': goal.get('rating_1_criteria', ''),
                    'rating_2_criteria': goal.get('rating_2_criteria', ''),
                    'rating_3_criteria': goal.get('rating_3_criteria', ''),
                    'rating_4_criteria': goal.get('rating_4_criteria', ''),
                    'rating_5_criteria': goal.get('rating_5_criteria', ''),
                    'rating': int(goal.get('rating', 0)) if goal.get('rating') else None
                })
            if goals_to_save:
                supabase.table('individual_goals').insert(goals_to_save).execute()
                print(f"DEBUG: {len(goals_to_save)} metas inseridas para avaliação {evaluation_id}")    
                        
        try:
            scores = calculate_evaluation_scores(
                evaluation_id,
                data['responses'],
                data.get('goals', []),
                data.get('dimension_weights', {})
            )
            if scores:
                supabase.table('evaluations').update(scores).eq('id', evaluation_id).execute()
        except Exception as calc_error:
            print(f"Erro ao calcular scores: {calc_error}")

        return jsonify({'id': evaluation_id, 'evaluation_id': evaluation_id, 'message': 'Avaliação salva com sucesso!'})

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/evaluations/<int:evaluation_id>', methods=['GET'])
def get_evaluation(evaluation_id):
    try:
        r = supabase.table('evaluations').select('*').eq('id', evaluation_id).execute()
        if not r.data:
            return jsonify({'error': 'Avaliação não encontrada'}), 404

        evaluation = r.data[0]
        rr = supabase.table('evaluation_responses').select('*').eq('evaluation_id', evaluation_id).execute()
        evaluation['responses'] = rr.data
        return jsonify(evaluation)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ===================== Goals / Dimension Weights =====================
@app.route('/api/individual-goals', methods=['GET'])
def get_individual_goals():
    try:
        r = supabase.table('individual_goals').select('*').execute()
        return jsonify(r.data)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/individual-goals', methods=['POST'])
def create_individual_goal():
    try:
        data = request.get_json()
        r = supabase.table('individual_goals').insert(data).execute()
        return jsonify(r.data)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/dimension-weights', methods=['GET'])
def get_dimension_weights():
    try:
        # Contexto recebido do WordPress
        cliente_id = (request.args.get('cliente_id') or '').strip()
        holding_id = (request.args.get('holding_id') or '').strip()
        empresa_id = (request.args.get('empresa_id') or '').strip()
        filial_id = (request.args.get('filial_id') or '').strip()
        nivel_contexto = (request.args.get('nivel_contexto') or '').strip().lower()
        contexto_nome = (request.args.get('contexto_nome') or '').strip()

        # Se não vier contexto, mantém compatibilidade com a tabela antiga global
        if not cliente_id:
            r_old = supabase.table('dimension_weights').select('*').execute()
            rows_old = r_old.data or []

            out_old = {
                'institutional': None,
                'functional': None,
                'individual': None,
                'metas': None
            }

            for row in rows_old:
                dim = str(row.get('dimension') or '').upper()
                val = row.get('weight')

                if dim == 'INSTITUCIONAL':
                    out_old['institutional'] = val
                elif dim == 'FUNCIONAL':
                    out_old['functional'] = val
                elif dim == 'INDIVIDUAL':
                    out_old['individual'] = val
                elif dim == 'METAS':
                    out_old['metas'] = val

            return jsonify(out_old), 200

        # ✅ Descobre o modelo/versão ativos do contexto usando função SQL segura
        r_model = supabase.rpc(
            'get_active_evaluation_model_for_context',
            {
                'p_cliente_id': cliente_id,
                'p_holding_id': holding_id or None,
                'p_empresa_id': empresa_id or None,
                'p_filial_id': filial_id or None,
                'p_nivel_contexto': nivel_contexto or None,
                'p_contexto_nome': contexto_nome or None
            }
        ).execute()

        model_rows = r_model.data or []

        if not model_rows:
            return jsonify({
                'error': 'NO_ACTIVE_MODEL_FOR_CONTEXT',
                'message': 'Nenhum modelo ativo encontrado para o contexto selecionado.',
                'debug': {
                    'cliente_id': cliente_id,
                    'holding_id': holding_id,
                    'empresa_id': empresa_id,
                    'filial_id': filial_id,
                    'nivel_contexto': nivel_contexto,
                    'contexto_nome': contexto_nome
                }
            }), 404

        modelo_id = model_rows[0].get('modelo_avaliacao_id')
        versao_id = model_rows[0].get('versao_modelo_id')

        
        # ✅ Busca pesos contextualizados usando função SQL segura
        r_weights = supabase.rpc(
            'get_dimension_weights_for_context',
            {
                'p_cliente_id': cliente_id,
                'p_holding_id': holding_id or None,
                'p_empresa_id': empresa_id or None,
                'p_filial_id': filial_id or None,
                'p_nivel_contexto': nivel_contexto or None,
                'p_contexto_nome': contexto_nome or None
            }
        ).execute()

        rows = r_weights.data or []

        rows = r_weights.data or []

        out = {
            'institutional': None,
            'functional': None,
            'individual': None,
            'metas': None,
            'modelo_avaliacao_id': modelo_id,
            'versao_modelo_id': versao_id
        }

        for row in rows:
            dim = str(row.get('dimension') or '').upper()
            val = row.get('weight')

            if dim == 'INSTITUCIONAL':
                out['institutional'] = val
            elif dim == 'FUNCIONAL':
                out['functional'] = val
            elif dim == 'INDIVIDUAL':
                out['individual'] = val
            elif dim == 'METAS':
                out['metas'] = val

        return jsonify(out), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500
        
@app.route('/api/dimension-weights', methods=['PUT'])
def update_dimension_weights():
    try:
        data = request.get_json() or {}

        cliente_id = (data.get('cliente_id') or '').strip()
        holding_id = (data.get('holding_id') or '').strip()
        empresa_id = (data.get('empresa_id') or '').strip()
        filial_id = (data.get('filial_id') or '').strip()
        nivel_contexto = (data.get('nivel_contexto') or '').strip().lower()
        contexto_nome = (data.get('contexto_nome') or '').strip()

        institutional = data.get('institutional')
        functional = data.get('functional')
        individual = data.get('individual')
        metas = data.get('metas')

        # Se não vier contexto, bloqueia para evitar alteração global acidental
        if not cliente_id:
            return jsonify({
                'error': 'CONTEXT_REQUIRED',
                'message': 'Contexto obrigatório para salvar pesos. A alteração global foi bloqueada por segurança.'
            }), 400

        total = (
            float(institutional or 0) +
            float(functional or 0) +
            float(individual or 0) +
            float(metas or 0)
        )

        if round(total, 2) != 100:
            return jsonify({
                'error': 'INVALID_TOTAL',
                'message': f'A soma dos pesos deve ser 100%. Soma atual: {total:.2f}%.'
            }), 400

        r = supabase.rpc(
            'update_dimension_weights_for_context',
            {
                'p_cliente_id': cliente_id,
                'p_holding_id': holding_id or None,
                'p_empresa_id': empresa_id or None,
                'p_filial_id': filial_id or None,
                'p_nivel_contexto': nivel_contexto or None,
                'p_contexto_nome': contexto_nome or None,
                'p_institucional': institutional,
                'p_funcional': functional,
                'p_individual': individual,
                'p_metas': metas
            }
        ).execute()

        rows = r.data or []

        return jsonify({
            'message': 'Pesos do contexto atualizados com sucesso.',
            'total': total,
            'items': rows
        }), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ===================== Período atual (controlado pelo banco) =====================
def get_current_period():
    """
    Lê o período atual na tabela 'evaluation_current_period' (id=1).
    Fallback para '102025' se não houver registro.
    """
    try:
        r = (supabase.table('evaluation_current_period')
             .select('period')
             .eq('id', 1)
             .maybe_single()

             .execute())
        data = r.data or {}
        p = (data.get('period') or '').strip()
        if p:
            return p
    except Exception as e:
        print('[get_current_period] fallback por erro:', e)
    return '102025'

@app.route('/api/evaluations/current-period', methods=['GET'])
def api_get_current_period():
    return jsonify({'period': get_current_period()}), 200

@app.route('/api/evaluations/current-period', methods=['PUT'])
def api_put_current_period():
    """
    Body: { "period": "MMYYYY", "code": "SEU-CODIGO" }
    """
    try:
        payload = request.get_json(force=True) or {}
    except Exception as e:
        return jsonify({'error': f'JSON inválido: {e}'}), 400

    if not ADMIN_WINDOW_CODE:
        return jsonify({'error': 'ADMIN_WINDOW_CODE não configurado'}), 500
    if (payload.get('code') or '').strip() != ADMIN_WINDOW_CODE:
        return jsonify({'error': 'Código RH incorreto'}), 403

    period = (payload.get('period') or '').strip()
    if not (period.isdigit() and len(period) == 6):
        return jsonify({'error': 'Período inválido. Use "MMYYYY", ex.: "102025".'}), 400

    try:
        supabase.table('evaluation_current_period').update({
            'period': period
        }).eq('id', 1).execute()
    except Exception as e:
        return jsonify({'error': 'Falha ao salvar período atual', 'detail': str(e)}), 500

    return jsonify({'message': 'Período atualizado', 'period': period}), 200

# ===================== Janela (usa período atual do banco) =====================
def get_window_row():
    """Lê direto da tabela 'evaluation_periods' para o período atual."""
    period = get_current_period()
    try:
        r = (supabase.table('evaluation_periods')
             .select('period,start_at,end_at')
             .eq('period', period)
             .limit(1)
             .execute())
        rows = r.data or []
        return rows[0] if rows else None
    except Exception as e:
        print('[get_window_row] erro:', e)
        return None

@app.route('/api/evaluations/window', methods=['GET'])
def api_get_window_status():
    is_open, start_dt, end_dt, period = is_window_open()
    return jsonify({
        'period': period,
        'open': bool(is_open),
        'start_at': start_dt.isoformat() if start_dt else None,
        'end_at':   end_dt.isoformat() if end_dt else None,
    }), 200


@app.route('/api/evaluations/window', methods=['PUT', 'OPTIONS'])
def api_put_window_update():
    if request.method == 'OPTIONS':
        return ('', 204)
    try:
        payload = request.get_json(force=True) or {}
    except Exception as e:
        return jsonify({'error': f'JSON inválido: {e}'}), 400

    if not ADMIN_WINDOW_CODE:
        return jsonify({'error': 'ADMIN_WINDOW_CODE não configurado no servidor'}), 500
    if (payload.get('code') or '').strip() != ADMIN_WINDOW_CODE:
        return jsonify({'error': 'Código RH incorreto'}), 403

    start_at = (payload.get('start_at') or '').strip()
    end_at   = (payload.get('end_at') or '').strip()
    if not start_at or not end_at:
        return jsonify({'error': 'Informe start_at e end_at (ISO-8601)'}), 400

    period = get_current_period()
    row = {'period': period, 'start_at': start_at, 'end_at': end_at}
    try:
        supabase.table('evaluation_periods').upsert(row, on_conflict='period').execute()
    except Exception as e:
        return jsonify({'error': 'Falha ao salvar janela (upsert evaluation_periods)', 'detail': str(e)}), 500

    w = get_window_row()
    return jsonify({
        'period': period,
        'start_at': (w or {}).get('start_at') or start_at,
        'end_at':   (w or {}).get('end_at') or end_at,
        'open': bool(w and w.get('start_at') and w.get('end_at')
                     and str(w['start_at']) <= str(w['end_at'])),
        'message': 'Janela atualizada com sucesso'
    }), 200

# ===================== Painel Admin embutido =====================
@app.route('/admin', methods=['GET'])
def admin_panel():
    html = """
<!DOCTYPE html><html lang="pt-BR"><head>
<meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Painel de Avaliações — Admin</title>
<style>
body{font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial;line-height:1.5;margin:0;background:#f7f7fb;color:#111}
.wrap{max-width:780px;margin:0 auto;padding:28px}
h1{font-size:22px;margin:0 0 8px}
.card{background:#fff;border:1px solid #e5e7eb;border-radius:12px;padding:18px;margin-top:16px;box-shadow:0 2px 6px rgba(0,0,0,.05)}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.row{display:grid;grid-template-columns:1fr 1fr;gap:12px}
label{display:block;font-size:12px;color:#555;margin-bottom:6px}
input,button{font:inherit}input[type=text],input[type=datetime-local]{width:100%;padding:10px;border:1px solid #d1d5db;border-radius:8px}
.btn{display:inline-block;padding:10px 14px;border-radius:8px;border:0;cursor:pointer;font-weight:700}
.btn.primary{background:#2563eb;color:#fff}.btn.ghost{background:#f3f4f6}
.muted{color:#6b7280;font-size:13px}
.status-pill{display:inline-block;padding:4px 10px;border-radius:999px;font-size:12px;font-weight:700}
.ok{background:#e7f9ee;color:#0a7b31;border:1px solid #b7efc8}
.warn{background:#fff6e6;color:#a15c00;border:1px solid #ffe2ae}
.err{background:#ffecec;color:#a10000;border:1px solid #ffbaba}
</style></head><body>
<div class="wrap">
  <h1>Painel de Avaliações — Admin</h1>
  <p class="muted">Defina o <strong>período atual</strong> e a <strong>janela</strong> (início/fim). Use o <b>código do RH</b>.</p>

  <div class="card" id="status"><div><strong>Status atual</strong></div><div id="status-content" class="muted">Carregando…</div></div>

  <div class="card">
    <div style="margin-bottom:10px"><strong>Período atual</strong></div>
    <div class="grid2">
      <div><label>Período (MMYYYY)</label><input type="text" id="period" placeholder="ex.: 102025"/></div>
      <div><label>Código RH</label><input type="text" id="codePeriod" placeholder="ex.: RH-2025-OK"/></div>
    </div>
    <div style="margin-top:10px">
      <button class="btn primary" id="savePeriodBtn">Salvar período atual</button>
      <span id="msgPeriod" class="muted"></span>
    </div>
  </div>

  <div class="card">
    <div style="margin-bottom:10px"><strong>Atualizar janela</strong></div>
    <div class="row">
      <div><label>Início (local)</label><input type="datetime-local" id="startAt"/></div>
      <div><label>Fim (local)</label><input type="datetime-local" id="endAt"/></div>
    </div>
    <div class="grid2" style="margin-top:10px">
      <div></div><div><label>Código RH</label><input type="text" id="codeWindow" placeholder="ex.: RH-2025-OK"/></div>
    </div>
    <div style="margin-top:10px">
      <button class="btn primary" id="saveWindowBtn">Salvar janela</button>
      <button class="btn ghost" id="reloadBtn">Recarregar status</button>
      <span id="msgWindow" class="muted"></span>
    </div>
  </div>

  <div class="card"><div><strong>Dicas</strong></div>
    <ul class="muted"><li>Período é etiqueta MMYYYY (ex.: <b>102025</b>).</li>
    <li>Datas são salvas em UTC; os campos de data/hora convertem do seu fuso para ISO.</li></ul>
  </div>
</div>

<script>
const $ = sel => document.querySelector(sel);
function fmtDate(iso){ if(!iso) return '-'; try{ return new Date(iso).toLocaleString(); }catch(e){ return iso; } }
function toUTCStringLocal(dt){ if(!dt) return null; return new Date(dt).toISOString(); }

async function loadStatus(){
  $('#status-content').textContent = 'Carregando…';
  try{
    const [p,w] = await Promise.all([
      fetch('/api/evaluations/current-period').then(r=>r.json()),
      fetch('/api/evaluations/window').then(r=>r.json())
    ]);
    if(p.period) $('#period').value = p.period;
    const pill = w.open ? '<span class="status-pill ok">ABERTA</span>'
                        : '<span class="status-pill warn">FECHADA</span>';
    $('#status-content').innerHTML = `${pill}<br><b>Período:</b> ${w.period||p.period||'-'}<br><b>Início:</b> ${fmtDate(w.start_at)}<br><b>Fim:</b> ${fmtDate(w.end_at)}`;
    if(w.start_at){ $('#startAt').value = new Date(w.start_at).toISOString().slice(0,16); }
    if(w.end_at){   $('#endAt').value   = new Date(w.end_at).toISOString().slice(0,16); }
  }catch(e){
    $('#status-content').innerHTML = '<span class="status-pill err">ERRO</span> '+e;
  }
}

async function savePeriod(){
  $('#msgPeriod').textContent = 'Salvando…';
  const period = ($('#period').value||'').trim();
  const code = ($('#codePeriod').value||'').trim();
  if(!period || !code){ $('#msgPeriod').textContent = 'Preencha período e código.'; return; }
  const r = await fetch('/api/evaluations/current-period', {
    method:'PUT', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({period, code})
  });
  const j = await r.json();
  $('#msgPeriod').textContent = r.ok ? 'OK' : ('Erro: '+(j.error||'falha'));
  if(r.ok) await loadStatus();
}

async function saveWindow(){
  $('#msgWindow').textContent = 'Salvando…';
  const code = ($('#codeWindow').value||'').trim();
  const s = $('#startAt').value, e = $('#endAt').value;
  if(!code || !s || !e){ $('#msgWindow').textContent = 'Preencha datas e código.'; return; }
  const r = await fetch('/api/evaluations/window', {
    method:'PUT', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({code, start_at: toUTCStringLocal(s), end_at: toUTCStringLocal(e)})
  });
  const j = await r.json();
  $('#msgWindow').textContent = r.ok ? 'OK' : ('Erro: '+(j.error||'falha'));
  if(r.ok) await loadStatus();
}

document.addEventListener('DOMContentLoaded', ()=>{
  loadStatus();
  $('#savePeriodBtn').addEventListener('click', savePeriod);
  $('#saveWindowBtn').addEventListener('click', saveWindow);
  $('#reloadBtn').addEventListener('click', loadStatus);
});
</script>
</body></html>
    """
    return html

# ===================== Exec =====================

# ========= Employees: obter/atualizar um funcionário =========
@app.route('/api/employees/<int:employee_id>', methods=['GET'])
def get_employee(employee_id):
    try:
        r = (
            supabase.table('employees')
            .select('*')
            .eq('id', employee_id)
            .maybe_single()

            .execute()
        )
        if not r.data:
            return jsonify({'error': 'Funcionário não encontrado'}), 404
        return jsonify(r.data), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/employees/<int:employee_id>', methods=['PUT'])
def update_employee(employee_id: int):
    try:
        data = request.get_json(silent=True) or {}

        # ✅ competência vem da URL (?competence=YYYY-MM-01) ou mês atual
        comp = _competence_from_request()

        # ✅ Bloqueia edição se competência do contexto estiver FECHADA
        _assert_competence_context_open_or_admin(comp, data)
        _remove_context_fields_from_employee_payload(data)

        # nunca enviar esses campos pro Supabase
        # (employees não tem competence, e admin_code é só autorização)
        data.pop("competence", None)
        data.pop("admin_code", None)

        # 1) pega o registro atual (para garantir que existe)
        current = (
            supabase.table("employees")
            .select("*")
            .eq("id", employee_id)
            .maybe_single()
            .execute()
        ).data

        if not current:
            return jsonify({
                "error": "NOT_FOUND",
                "message": "Funcionário não encontrado."
            }), 404

        # 2) atualiza employee
        r = (
            supabase.table("employees")
            .update(data)
            .eq("id", employee_id)
            .execute()
        )

        updated_list = r.data or []
        if not updated_list:
            # fallback: buscar novamente
            updated = (
                supabase.table("employees")
                .select("*")
                .eq("id", employee_id)
                .maybe_single()
                .execute()
            ).data
        else:
            updated = updated_list[0]

        if not updated:
            return jsonify({
                "error": "UPDATE_FAILED",
                "message": "Falha ao atualizar funcionário."
            }), 500

        # 3) salva histórico (snapshot do estado atualizado)
        _save_employee_history(
            employee_id=int(employee_id),
            data_snapshot=updated,
            action="UPDATE",
            round_code=(updated.get("round_code") or None),
            competence=comp
        )

        return jsonify(updated), 200

    except PermissionError as e:
        comp = _competence_from_request()
        return jsonify({
            "error": "COMPETENCE_CLOSED",
            "message": str(e),
            "competence": comp.isoformat(),
            "status": "CLOSED"
        }), 423

    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ========= Movimentações salariais (histórico) =========
@app.route('/api/employees/<int:employee_id>/movements', methods=['GET'])
def list_salary_movements(employee_id):
    try:
        r = (
            supabase.table('salary_movements')
            .select('*')
            .eq('employee_id', employee_id)
            .order('movement_date', desc=True)
            .execute()
        )
        return jsonify(r.data or []), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/employees/<int:employee_id>/movements', methods=['POST'])
def add_salary_movement(employee_id):
    try:
        payload = request.get_json(force=True) or {}

        if not payload.get('movement_date') or payload.get('salary_value') is None:
            return jsonify({'error': 'Informe movement_date e salary_value'}), 400

        row = {
            'employee_id':  employee_id,
            'movement_date': payload['movement_date'],   # 'YYYY-MM-DD'
            'role_title':    payload.get('role_title'),
            'salary_value':  float(payload['salary_value']),
            'notes':         payload.get('notes')
        }
        supabase.table('salary_movements').insert(row).execute()
        return jsonify({'created': True}), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ===================== Relatório de PDI & Reconhecimento por Dimensões =====================

def classificar_colaborador(ratings: dict, final_rating: float,
                            pdi_threshold: float = 3.0,
                            reconhecimento_threshold: float = 4.5) -> str:
    """
    Classifica o colaborador em:
      - 'RECONHECIMENTO'    -> destaque positivo
      - 'PDI_OBRIGATORIO'   -> precisa de PDI
      - 'NEUTRO'            -> meio do caminho

    Critério simples (pode ser ajustado depois):
      - final_rating >= reconhecimento_threshold  -> RECONHECIMENTO
      - final_rating <= pdi_threshold             -> PDI_OBRIGATORIO
      - caso contrário                            -> NEUTRO
    """
    try:
        fr = float(final_rating or 0)
    except Exception:
        fr = 0.0

    if fr >= reconhecimento_threshold:
        return 'RECONHECIMENTO'
    if fr <= pdi_threshold:
        return 'PDI_OBRIGATORIO'
    return 'NEUTRO'


def buscar_avaliacoes_brutas(
    round_code: str | None = None,
    empresa: str | None = None,
    holding_id: str | None = None,
    empresa_id: str | None = None,
    filial_id: str | None = None,
    nivel_contexto: str | None = None
) -> list[dict]:
    """
    Lê do Supabase:
      - evaluations  (médias por dimensão e rating final)
      - employees    (dados do colaborador + gestor)

    Retorna uma lista de dicts já no formato que a tela de
    'Mapas de Reconhecimento e PDI' vai consumir.

    Agora também respeita contexto:
      - holding
      - empresa
      - filial
    """

    # 1) Buscar avaliações
    try:
        query = (
            supabase
            .table('evaluations')
            .select(
                'id,employee_id,round_code,'
                'institucional_avg,funcional_avg,individual_avg,metas_avg,'
                'final_rating'
            )
        )

        if round_code:
            query = query.eq('round_code', round_code)

        r_eval = query.execute()
        eval_rows = r_eval.data or []

    except Exception as e:
        print('[buscar_avaliacoes_brutas] erro ao buscar evaluations:', e)
        return []

    if not eval_rows:
        return []

    # 2) Extrair lista de IDs de colaboradores
    employee_ids = sorted({
        row.get('employee_id')
        for row in eval_rows
        if row.get('employee_id') is not None
    })

    if not employee_ids:
        return []

    # 3) Buscar dados dos colaboradores
    try:
        emp_query = (
            supabase
            .table('employees')
            .select(
                'id,'
                'nome,cargo,empresa,'
                'empresa_id,filial_id,'
                'company_name,branch_name,department_name,'
                'manager_name,manager_code'
            )
            .in_('id', employee_ids)
        )

        # Filtro antigo textual por empresa, mantido por compatibilidade
        if empresa:
            emp_query = emp_query.eq('empresa', empresa)

        # Filtro novo por contexto
        nivel = (nivel_contexto or '').strip().lower()

        if nivel == 'empresa' and empresa_id:
            emp_query = emp_query.eq('empresa_id', empresa_id)

        elif nivel == 'filial':
            if empresa_id:
                emp_query = emp_query.eq('empresa_id', empresa_id)
            if filial_id:
                emp_query = emp_query.eq('filial_id', filial_id)

        elif nivel == 'holding' and holding_id:
            emp_query = emp_query.eq('holding_id', holding_id)

        r_emp = emp_query.execute()
        emp_rows = r_emp.data or []

    except Exception as e:
        print('[buscar_avaliacoes_brutas] erro ao buscar employees:', e)
        return []

    if not emp_rows:
        return []

    emp_by_id = {
        row['id']: row
        for row in emp_rows
        if row.get('id') is not None
    }

    # 4) Montar lista final
    resultado = []

    for ev in eval_rows:
        emp_id = ev.get('employee_id')
        emp = emp_by_id.get(emp_id)

        if not emp:
            # Se aplicou filtro de contexto, alguns evaluations podem ficar sem employee
            continue

        def _f(v):
            try:
                return round(float(v or 0), 2)
            except Exception:
                return 0.0

        ratings = {
            'INSTITUCIONAL': _f(ev.get('institucional_avg')),
            'FUNCIONAL':     _f(ev.get('funcional_avg')),
            'INDIVIDUAL':    _f(ev.get('individual_avg')),
            'METAS':         _f(ev.get('metas_avg')),
        }

        final_rating = _f(ev.get('final_rating'))

        classificacao = classificar_colaborador(ratings, final_rating)

        resultado.append({
            'employee_id': emp_id,
            'employee_name': emp.get('nome'),
            'cargo': emp.get('cargo'),

            # Campos importantes para contexto/filtro no front
            'empresa': emp.get('empresa'),
            'empresa_id': emp.get('empresa_id'),
            'company_name': emp.get('company_name'),
            'filial_id': emp.get('filial_id'),
            'branch_name': emp.get('branch_name'),

            'department_name': emp.get('department_name'),
            'manager_name': emp.get('manager_name'),
            'manager_code': emp.get('manager_code'),

            'ratings': ratings,
            'final_rating': final_rating,
            'classificacao': classificacao,
            'pdi_flag': (classificacao == 'PDI_OBRIGATORIO'),
            'reconhecimento_flag': (classificacao == 'RECONHECIMENTO'),
            'round_code': ev.get('round_code'),
            'evaluation_id': ev.get('id'),
        })

    resultado.sort(
        key=lambda x: (
            (x.get('manager_name') or '').strip().upper(),
            (x.get('employee_name') or '').strip().upper()
        )
    )

    return resultado

@app.route('/api/relatorio-pdi-dimensoes', methods=['GET'])
def api_relatorio_pdi_dimensoes():
    """
    Endpoint consumido pela tela 'Mapa de Reconhecimento e PDI'.

    GET /api/relatorio-pdi-dimensoes?round_code=102025&empresa=MINHAEMPRESA

    Resposta:
    {
      "source": "supabase",
      "round_code": "102025",
      "generated_at": "2025-12-03T12:34:56Z",
      "criteria": {...},
      "avaliacoes": [ ... lista de colaboradores ... ]
    }
    """
    try:
        # Parâmetros opcionais
        round_code = (request.args.get('round_code') or '').strip()
        empresa = (request.args.get('empresa') or '').strip() or None

        holding_id = (request.args.get('holding_id') or '').strip() or None
        empresa_id = (request.args.get('empresa_id') or '').strip() or None
        filial_id = (request.args.get('filial_id') or '').strip() or None
        nivel_contexto = (request.args.get('nivel_contexto') or '').strip().lower() or None
        contexto_codigo = (request.args.get('contexto_codigo') or '').strip() or None
        
        print(
            '[api_relatorio_pdi_dimensoes] contexto recebido:',
            'nivel_contexto=', nivel_contexto,
            'holding_id=', holding_id,
            'empresa_id=', empresa_id,
            'filial_id=', filial_id,
            'contexto_codigo=', contexto_codigo
        )





        

        # ✅ Suporte a ?year=2025 (prioridade sobre active_round_code)
        year_param = (request.args.get('year') or '').strip()
        year = None
        try:
            if year_param:
                year = int(year_param)
        except Exception:
            year = None
        
        # Se vier year e NÃO vier round_code, tenta mapear para um round_code existente
        if (not round_code) and year:
            # tenta formatos comuns primeiro
            candidatos = [f'YE{year}', f'Start{year}']
            encontrado = None
        
            for cod in candidatos:
                try:
                    r_test = (
                        supabase
                        .table('evaluations')
                        .select('id')
                        .eq('round_code', cod)
                        .limit(1)
                        .execute()
                    )
                    if r_test.data:
                        encontrado = cod
                        break
                except Exception as e:
                    print('[api_relatorio_pdi_dimensoes] erro ao testar round_code', cod, e)
        
            # fallback: pegar o round_code mais frequente daquele evaluation_year
            if not encontrado:
                try:
                    r_all = (
                        supabase
                        .table('evaluations')
                        .select('round_code')
                        .eq('evaluation_year', year)
                        .execute()
                    )
                    rows = r_all.data or []
                    from collections import Counter
                    cnt = Counter([r.get('round_code') for r in rows if r.get('round_code')])
                    if cnt:
                        encontrado = cnt.most_common(1)[0][0]
                except Exception as e:
                    print('[api_relatorio_pdi_dimensoes] erro ao buscar round_code por evaluation_year:', e)

            # ✅ Se pediu um year e não existe round_code para esse ano, NÃO usar active_round_code
            if year and not encontrado:
                round_code = None
                avaliacoes = []
                criteria = {
                    'pdi_threshold': 3.0,
                    'reconhecimento_threshold': 4.5,
                    'descricao': (
                        'final_rating <= 3.0 => PDI_OBRIGATORIO; '
                        'final_rating >= 4.5 => RECONHECIMENTO; '
                        'demais => NEUTRO'
                    )
                }
                from datetime import datetime, timezone as _tz
                return jsonify({
                    'source': 'supabase',
                    'round_code': None,
                    'empresa': empresa,
                    'generated_at': datetime.now(_tz.utc).isoformat(),
                    'criteria': criteria,
                    'total_avaliacoes': 0,
                    'avaliacoes': [],
                    'message': f'Nenhum dado encontrado para o ano {year}'
                }), 200

        
            if encontrado:
                round_code = encontrado


        # Se não vier round_code, tenta pegar da system_config.active_round_code
        if not round_code:
            try:
                r_cfg = (
                    supabase
                    .table('system_config')
                    .select('config_value')
                    .eq('config_key', 'active_round_code')
                    .maybe_single()
                    
                    .execute()
                )
                round_code = (r_cfg.data or {}).get('config_value')
            except Exception as e:
                print('[api_relatorio_pdi_dimensoes] erro ao ler active_round_code:', e)
                # se não achar, fica None mesmo -> busca todas as avaliações

        avaliacoes = buscar_avaliacoes_brutas(
            round_code=round_code,
            empresa=empresa,
            holding_id=holding_id,
            empresa_id=empresa_id,
            filial_id=filial_id,
            nivel_contexto=nivel_contexto
        )


        # Afirmações reais do modelo ativo do contexto selecionado
        afirmacoes_por_dimensao = {}

        try:
            employee_ref_id = None

            if avaliacoes and isinstance(avaliacoes, list):
                employee_ref_id = avaliacoes[0].get('employee_id')

            if employee_ref_id:
                r_criteria = supabase.rpc(
                    'get_active_evaluation_criteria_for_employee',
                    {'p_employee_id': int(employee_ref_id)}
                ).execute()

                criteria_rows = r_criteria.data or []

                dim_label_map = {
                    'FUNCIONAL': 'Funcional',
                    'INDIVIDUAL': 'Individual',
                    'INSTITUCIONAL': 'Institucional',
                    'METAS': 'Metas'
                }

                for row in criteria_rows:
                    dim_raw = (row.get('dimension') or '').strip().upper()
                    dim_label = dim_label_map.get(dim_raw, dim_raw.title())

                    name = (row.get('name') or '').strip()
                    description = (row.get('description') or '').strip()

                    if name and description:
                        texto = f'{name} - {description}'
                    else:
                        texto = name or description

                    if dim_label and texto:
                        if dim_label not in afirmacoes_por_dimensao:
                            afirmacoes_por_dimensao[dim_label] = []
                        afirmacoes_por_dimensao[dim_label].append(texto)

        except Exception as e:
            print('[api_relatorio_pdi_dimensoes] erro ao buscar afirmações do modelo ativo:', e)
            afirmacoes_por_dimensao = {}
        

        # Pequeno resumo de critérios (só informativo para o front)
        criteria = {
            'pdi_threshold': 3.0,
            'reconhecimento_threshold': 4.5,
            'descricao': (
                'final_rating <= 3.0 => PDI_OBRIGATORIO; '
                'final_rating >= 4.5 => RECONHECIMENTO; '
                'demais => NEUTRO'
            )
        }

        from datetime import datetime, timezone as _tz  # uso local para evitar conflito

        return jsonify({
            'source': 'supabase',
            'round_code': round_code,
            'empresa': empresa,

            'nivel_contexto': nivel_contexto,
            'holding_id': holding_id,
            'empresa_id': empresa_id,
            'filial_id': filial_id,
            'contexto_codigo': contexto_codigo,


            
            'generated_at': datetime.now(_tz.utc).isoformat(),
            'criteria': criteria,
            'total_avaliacoes': len(avaliacoes),
            'afirmacoes_por_dimensao': afirmacoes_por_dimensao,
            'avaliacoes': avaliacoes
        }), 200
    except Exception as e:
        print('[api_relatorio_pdi_dimensoes] erro interno:', e)
        return jsonify({'error': 'internal', 'detail': str(e)}), 500


@app.route('/api/ninebox', methods=['GET'])
def api_ninebox():
    """
    GET /api/ninebox?round_code=YE2025&manager_name=FULANO
    - round_code opcional: se não vier, usa system_config.active_round_code
    - manager_name opcional: filtra o 9box por gestor (nome)
    """
    try:
        round_code = (request.args.get('round_code') or '').strip()
        manager_name = (request.args.get('manager_name') or '').strip()

        # se não vier round_code, pega a rodada ativa
        if not round_code:
            try:
                r_cfg = (
                    supabase
                    .table('system_config')
                    .select('config_value')
                    .eq('config_key', 'active_round_code')
                    .maybe_single()

                    
                    .execute()
                )
                round_code = ((r_cfg.data or {}).get('config_value') or '').strip()
            except Exception as e:
                print('[api_ninebox] erro ao ler active_round_code:', e)

        # consulta a VIEW v_ninebox_items
        q = (
            supabase
            .table('v_ninebox_items')
            .select(
                'employee_id,employee_name,cargo,empresa,department_name,'
                'manager_name,manager_code,'
                'final_rating,performance_rating,potential_rating,nine_box_position,'
                'round_code,evaluation_year,evaluation_date,created_at'
            )
        )

        if round_code:
            q = q.eq('round_code', round_code)

        # filtro por gestor via URL (compatível com o seu link atual ?manager_name=...)
        if manager_name:
            q = q.eq('manager_name', manager_name)

        # (opcional) se estiver usando /team?t=TOKEN, isso reforça segurança por manager_code
        referer = (request.headers.get('Referer') or '')
        from_manager_panel = '/manager' in referer
        mc = (request.cookies.get('manager_access') or '').strip()
        if mc and not from_manager_panel:
            q = q.eq('manager_code', mc)

        r = q.execute()
        items = r.data or []

        # agregado por posição 1..9
        counts = {str(i): 0 for i in range(1, 10)}
        for it in items:
            p = it.get('nine_box_position')
            if p is None:
                continue
            ps = str(p)
            if ps in counts:
                counts[ps] += 1

        return jsonify({
            'round_code': round_code,
            'manager_name': manager_name or None,
            'total': len(items),
            'counts': counts,
            'items': items
        }), 200

    except Exception as e:
        return jsonify({'error': 'internal', 'detail': str(e)}), 500

@app.route('/api/ninebox-contexto', methods=['GET'])
def api_ninebox_contexto():
    """
    GET /api/ninebox-contexto

    Versão multiempresa/multifilial do ninebox.

    Parâmetros opcionais:
      - round_code ou ciclo_codigo
      - cliente_id
      - holding_id
      - empresa_id
      - filial_id
      - manager_name

    Se não receber contexto, retorna dados gerais compatíveis com a lógica antiga.
    """
    try:
        round_code = (
            request.args.get('round_code')
            or request.args.get('ciclo_codigo')
            or ''
        ).strip()

        cliente_id = (request.args.get('cliente_id') or '').strip()
        holding_id = (request.args.get('holding_id') or '').strip()
        empresa_id = (request.args.get('empresa_id') or '').strip()
        filial_id = (request.args.get('filial_id') or '').strip()
        manager_name = (request.args.get('manager_name') or '').strip()

        # Se não vier round_code/ciclo_codigo, pega a rodada ativa antiga
        if not round_code:
            try:
                r_cfg = (
                    supabase
                    .table('system_config')
                    .select('config_value')
                    .eq('config_key', 'active_round_code')
                    .maybe_single()
                    .execute()
                )
                round_code = ((r_cfg.data or {}).get('config_value') or '').strip()
            except Exception as e:
                print('[api_ninebox_contexto] erro ao ler active_round_code:', e)

        q = (
            supabase
            .table('v_desempenho_contexto')
            .select(
                'evaluation_id,'
                'employee_id,employee_name,cargo,'
                'empresa_id,empresa_nome,'
                'holding_id,holding_nome,'
                'filial_id,filial_nome,'
                'department_name,'
                'manager_name,'
                'round_code,ciclo_codigo,evaluation_year,ano_referencia,'
                'final_rating,performance_rating,potential_rating,nine_box_position'
            )
        )

        if round_code:
            q = q.eq('round_code', round_code)

        if cliente_id:
            q = q.eq('cliente_id', cliente_id)

        if holding_id:
            q = q.eq('holding_id', holding_id)

        if empresa_id:
            q = q.eq('empresa_id', empresa_id)

        if filial_id:
            q = q.eq('filial_id', filial_id)

        if manager_name:
            q = q.eq('manager_name', manager_name)

        r = q.execute()
        rows = r.data or []

        items = []
        for row in rows:
            items.append({
                'evaluation_id': row.get('evaluation_id'),
                'employee_id': row.get('employee_id'),
                'employee_name': row.get('employee_name'),
                'cargo': row.get('cargo'),

                # Campos compatíveis com o front antigo
                'empresa': row.get('empresa_nome'),
                'department_name': row.get('department_name'),
                'manager_name': row.get('manager_name'),
                'manager_code': None,

                'final_rating': row.get('final_rating'),
                'performance_rating': row.get('performance_rating'),
                'potential_rating': row.get('potential_rating'),
                'nine_box_position': row.get('nine_box_position'),

                'round_code': row.get('ciclo_codigo') or row.get('round_code'),
                'evaluation_year': row.get('ano_referencia') or row.get('evaluation_year'),
                'evaluation_date': None,
                'created_at': None,

                # Campos novos multiempresa/multifilial
                'holding_id': row.get('holding_id'),
                'holding_nome': row.get('holding_nome'),
                'empresa_id': row.get('empresa_id'),
                'empresa_nome': row.get('empresa_nome'),
                'filial_id': row.get('filial_id'),
                'filial_nome': row.get('filial_nome'),
            })

        counts = {str(i): 0 for i in range(1, 10)}
        for it in items:
            p = it.get('nine_box_position')
            if p is None:
                continue
            ps = str(p)
            if ps in counts:
                counts[ps] += 1

        return jsonify({
            'round_code': round_code,
            'ciclo_codigo': round_code,
            'cliente_id': cliente_id or None,
            'holding_id': holding_id or None,
            'empresa_id': empresa_id or None,
            'filial_id': filial_id or None,
            'manager_name': manager_name or None,
            'total': len(items),
            'counts': counts,
            'items': items
        }), 200

    except Exception as e:
        print('[api_ninebox_contexto] erro:', e)
        return jsonify({'error': 'internal', 'detail': str(e)}), 500



@app.route('/api/rounds/list', methods=['GET'], endpoint='api_rounds_list_v2')
def api_rounds_list_v2():
    """
    Lista rodadas cadastradas em evaluation_rounds para o dropdown do 9box.
    """
    try:
        r = (
            supabase.table('evaluation_rounds')
            .select('code,status,opened_at,closed_at')
            .order('opened_at', desc=True)
            .execute()
        )
        return jsonify({'items': r.data or []}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500



# ===================== Sistema de Rodadas =====================
@app.route('/api/system-config', methods=['GET'])
def get_system_config():
    try:
        r = supabase.table('system_config').select('*').eq('config_key', 'active_round_code').execute()
        if r.data:
            return jsonify({'active_round_code': r.data[0]['config_value']})
        return jsonify({'active_round_code': None})  # sem fallback
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/system-config', methods=['PUT'])
def update_system_config():
    try:
        data = request.get_json()
        round_code = data.get('active_round_code', '').strip()
        
        if not round_code:
            return jsonify({'error': 'Código da rodada obrigatório'}), 400
            
        # Atualizar ou inserir configuração
        supabase.table('system_config').upsert({
            'config_key': 'active_round_code',
            'config_value': round_code,
            'description': f'Código da rodada ativa: {round_code}'
        }, on_conflict='config_key').execute()
        
        return jsonify({'message': 'Configuração atualizada com sucesso'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


def _require_rh_code(payload: dict):
    """
    Valida o código RH (ADMIN_WINDOW_CODE).
    Retorna (ok:bool, resp_json, http_status)
    """
    if not ADMIN_WINDOW_CODE:
        return (False, {'error': 'ADMIN_WINDOW_CODE não configurado no servidor'}, 500)

    code = (payload.get('code') or '').strip()
    if code != ADMIN_WINDOW_CODE:
        return (False, {'error': 'Código RH incorreto'}, 403)

    return (True, None, None)


def _get_active_round_code():
    r = (supabase.table('system_config')
         .select('config_value')
         .eq('config_key', 'active_round_code')
         .maybe_single()

         .execute())
    return (r.data or {}).get('config_value')


@app.route('/api/rounds/active', methods=['GET'])
def api_rounds_active():
    try:
        active = (_get_active_round_code() or '').strip() or None

        status = None
        if active:
            rr = (supabase.table('evaluation_rounds')
                  .select('code,status,opened_at,closed_at')
                  .eq('code', active)
                  .maybe_single()

                  .execute())
            if rr.data:
                status = rr.data

        return jsonify({
            'active_round_code': active,
            'active_round': status  # pode vir null se não existir na evaluation_rounds
        }), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/rounds', methods=['GET'])
def api_rounds_list():
    try:
        rr = (supabase.table('evaluation_rounds')
              .select('code,status,opened_at,closed_at')
              .order('opened_at', desc=True)
              .execute())
        return jsonify(rr.data or []), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/rounds/close-active', methods=['POST'])
def api_rounds_close_active():
    try:
        payload = request.get_json(force=True) or {}
        ok, err, status = _require_rh_code(payload)
        if not ok:
            return jsonify(err), status

        active = (_get_active_round_code() or '').strip()
        if not active:
            return jsonify({'error': 'Nenhuma rodada ativa configurada'}, 400

), 400

        # fecha no controle de rodadas
        supabase.table('evaluation_rounds').upsert({
            'code': active,
            'status': 'CLOSED',
            'closed_at': datetime.now(timezone.utc).isoformat()
        }, on_conflict='code').execute()

        return jsonify({'message': f'Rodada {active} fechada (somente leitura).'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/rounds/open', methods=['POST'])
def api_rounds_open():
    try:
        payload = request.get_json(force=True) or {}
        ok, err, status = _require_rh_code(payload)
        if not ok:
            return jsonify(err), status

        new_code = (payload.get('round_code') or '').strip()
        if not new_code:
            return jsonify({'error': 'round_code é obrigatório'}, 400)

        # 1) garante que a rodada exista como OPEN
        supabase.table('evaluation_rounds').upsert({
            'code': new_code,
            'status': 'OPEN',
            'opened_at': datetime.now(timezone.utc).isoformat(),
            'closed_at': None
        }, on_conflict='code').execute()

        # 2) seta como rodada ativa do sistema
        supabase.table('system_config').upsert({
            'config_key': 'active_round_code',
            'config_value': new_code,
            'description': f'Código da rodada ativa: {new_code}'
        }, on_conflict='config_key').execute()

        return jsonify({'message': f'Rodada ativa atualizada para {new_code}'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500







# ===================== Conexão Postgres direta (para simulação de mérito) =====================
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

def get_db_connection():
    """
    Usa DATABASE_URL (recomendado no Render).
    Exige que a env DATABASE_URL esteja configurada.
    """
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL não configurada no servidor")

    # Em ambientes como Supabase/Render, normalmente precisa de SSL
    return psycopg2.connect(DATABASE_URL, sslmode="require")



# ========= Mérito: carga única (SQL) =========
def load_merit_rows():
    """
    Executa o mesmo SQL de simulação de mérito e devolve uma lista de dicts (um por colaborador).
    Essa função é reaproveitada pelo /api/merit-simulation e pelo /api/relatorio-merito.
    """
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    sql = """
    WITH latest_eval AS (
      SELECT ev.*
      FROM evaluations ev
      JOIN (
        SELECT employee_id, MAX(evaluation_date) AS max_date
        FROM evaluations
        GROUP BY employee_id
      ) ult
        ON ult.employee_id = ev.employee_id
       AND ult.max_date = ev.evaluation_date
    ),
    emp_base AS (
      SELECT
        e.id,
        e.nome,
        e.cargo,
        e.empresa,
        e.company_name,
        e.branch_name,
        e.department_name,
        e.manager_name,
        e.salario,
        e.grade_group,
        e.grade_level,
        COALESCE(e.salary_region, 'R1') AS salary_region,
        COALESCE(e.salary_grade_year, 2025) AS salary_grade_year
      FROM employees e
    )
    SELECT
      emp.id AS employee_id,
      emp.nome AS employee_name,
      emp.cargo,
      COALESCE(emp.company_name, emp.empresa) AS company_name,
      emp.branch_name,
      emp.department_name,
      emp.manager_name,
      emp.salario AS current_salary,
      emp.grade_group,
      emp.grade_level,
      emp.salary_region,
      emp.salary_grade_year,
      sg.median_80,
      sg.median_100,
      sg.median_120,
      CASE
        WHEN sg.median_100 IS NULL OR sg.median_100 <= 0 THEN NULL
        ELSE ROUND((emp.salario / sg.median_100) * 100, 1)
      END AS pct_of_median,
      le.final_rating,
      ROUND(le.final_rating) AS final_rating_round,
      mm.band_order,
      CASE ROUND(le.final_rating)
        WHEN 1 THEN mm.inc_rating1
        WHEN 2 THEN mm.inc_rating2
        WHEN 3 THEN mm.inc_rating3
        WHEN 4 THEN mm.inc_rating4
        WHEN 5 THEN mm.inc_rating5
        ELSE 0
      END AS merit_percent,
      CASE
        WHEN mm.id IS NULL THEN NULL
        ELSE ROUND(
          emp.salario * (
            1 + (CASE ROUND(le.final_rating)
              WHEN 1 THEN mm.inc_rating1
              WHEN 2 THEN mm.inc_rating2
              WHEN 3 THEN mm.inc_rating3
              WHEN 4 THEN mm.inc_rating4
              WHEN 5 THEN mm.inc_rating5
              ELSE 0
            END) / 100.0
          ),
          2
        )
      END AS new_salary,
      CASE
        WHEN mm.id IS NULL THEN NULL
        ELSE ROUND(
          emp.salario * (
            (CASE ROUND(le.final_rating)
              WHEN 1 THEN mm.inc_rating1
              WHEN 2 THEN mm.inc_rating2
              WHEN 3 THEN mm.inc_rating3
              WHEN 4 THEN mm.inc_rating4
              WHEN 5 THEN mm.inc_rating5
              ELSE 0
            END) / 100.0
          ),
          2
        )
      END AS monthly_impact,
      CASE
        WHEN mm.id IS NULL THEN NULL
        ELSE ROUND(
          12 * emp.salario * (
            (CASE ROUND(le.final_rating)
              WHEN 1 THEN mm.inc_rating1
              WHEN 2 THEN mm.inc_rating2
              WHEN 3 THEN mm.inc_rating3
              WHEN 4 THEN mm.inc_rating4
              WHEN 5 THEN mm.inc_rating5
              ELSE 0
            END) / 100.0
          ),
          2
        )
      END AS annual_impact
    FROM emp_base emp
    LEFT JOIN salary_grades sg
      ON sg.year   = emp.salary_grade_year
     AND sg.region = emp.salary_region
     AND sg.group_no = emp.grade_group
    LEFT JOIN latest_eval le
      ON le.employee_id = emp.id
    LEFT JOIN merit_matrix mm
      ON mm.year   = emp.salary_grade_year
     AND mm.region = emp.salary_region
     AND CASE
           WHEN sg.median_100 IS NULL OR sg.median_100 <= 0 THEN NULL
           ELSE (emp.salario / sg.median_100) * 100
         END BETWEEN mm.pct_med_min AND mm.pct_med_max
    ORDER BY emp.manager_name, emp.nome;
    """

    cur.execute(sql)
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


@app.route("/api/merit-simulation", methods=["GET"])
def api_merit_simulation():
    """
    Continua igual: retorna a lista plana (um registro por colaborador),
    com impactos e percentuais de mérito.
    """
    rows = load_merit_rows()
    return jsonify({
        "count": len(rows),
        "items": rows
    })


@app.route("/api/relatorio-merito", methods=["GET"])
def api_relatorio_merito():
    """
    Novo endpoint para o painel de Mérito:
    - Agrupa por gestor (manager_name)
    - Dentro de cada gestor, lista os funcionários com salário, mediana, rating etc.

    Formato de resposta:
    [
      {
        "gestor": "Nome do Gestor",
        "funcionarios": [
          {
            "employeeId": ...,
            "nome": "...",
            "cargo": "...",
            "company": "...",
            "department": "...",
            "currentSalary": ...,
            "medianSalary": ...,
            "pctOfMedian": ...,
            "finalRating": ...,
            "meritPercent": ...,
            "newSalary": ...,
            "monthlyImpact": ...,
            "annualImpact": ...
          },
          ...
        ]
      },
      ...
    ]
    """
    rows = load_merit_rows()

    grupos = {}  # chave = nome do gestor

    for r in rows:
        gestor = (r.get("manager_name") or "Gestor sem nome").strip() or "Gestor sem nome"

        if gestor not in grupos:
            grupos[gestor] = {
                "gestor": gestor,
                "funcionarios": []
            }

        grupos[gestor]["funcionarios"].append({
            "employeeId":        r.get("employee_id"),
            "nome":              r.get("employee_name"),
            "cargo":             r.get("cargo"),
            "company":           r.get("company_name"),
            "department":        r.get("department_name"),
            "branch":            r.get("branch_name"),
            "currentSalary":     r.get("current_salary"),
            "medianSalary":      r.get("median_100"),
            "median80":          r.get("median_80"),
            "median120":         r.get("median_120"),
            "pctOfMedian":       r.get("pct_of_median"),
            "finalRating":       r.get("final_rating"),
            "finalRatingRound":  r.get("final_rating_round"),
            "meritPercent":      r.get("merit_percent"),
            "newSalary":         r.get("new_salary"),
            "monthlyImpact":     r.get("monthly_impact"),
            "annualImpact":      r.get("annual_impact"),
            "gradeGroup":        r.get("grade_group"),
            "gradeLevel":        r.get("grade_level"),
            "salaryRegion":      r.get("salary_region"),
            "salaryYear":        r.get("salary_grade_year"),
        })

    # converte dict -> lista
    resultado = list(grupos.values())
    return jsonify(resultado), 200


@app.route('/ninebox', methods=['GET'])
def ninebox_page():
    html = """
<!DOCTYPE html><html lang="pt-BR"><head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>9Box — Histórico</title>
<style>
  body{font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial;margin:0;background:#f7f7fb;color:#111}
  .wrap{max-width:1100px;margin:0 auto;padding:22px}
  h1{font-size:20px;margin:0 0 8px}
  .muted{color:#6b7280;font-size:13px}
  .card{background:#fff;border:1px solid #e5e7eb;border-radius:12px;padding:16px;margin-top:12px;box-shadow:0 2px 6px rgba(0,0,0,.05)}
  .row{display:flex;gap:10px;flex-wrap:wrap;align-items:end}
  label{display:block;font-size:12px;color:#555;margin-bottom:6px}
  select,input{font:inherit;padding:10px;border:1px solid #d1d5db;border-radius:10px;background:#fff}
  button{font:inherit;padding:10px 14px;border-radius:10px;border:0;cursor:pointer;font-weight:700;background:#2563eb;color:#fff}
  button.secondary{background:#111827}
  .grid{display:grid;grid-template-columns:120px 1fr;gap:12px;align-items:start}
  .kpi{display:flex;gap:10px;flex-wrap:wrap}
  .pill{display:inline-flex;align-items:center;gap:8px;padding:8px 12px;border-radius:999px;border:1px solid #e5e7eb;background:#f9fafb;font-weight:700}
  .pill small{font-weight:600;color:#6b7280}
  table{border-collapse:separate;border-spacing:8px;width:100%}
  td,th{background:#f9fafb;border:1px solid #e5e7eb;border-radius:12px;padding:14px;text-align:center}
  th{background:#fff}
  .cell{cursor:pointer;transition:transform .06s ease}
  .cell:hover{transform:translateY(-1px)}
  .cell b{font-size:22px;display:block}
  .legend{display:flex;gap:12px;flex-wrap:wrap}
  .legend span{font-size:12px;color:#6b7280}
  .list{margin-top:10px;overflow:auto}
  .list table{border-spacing:0;border-collapse:collapse}
  .list th,.list td{border-radius:0;border:1px solid #e5e7eb;background:#fff;padding:10px;text-align:left}
  .list th{background:#f3f4f6}
</style>
</head><body>
<div class="wrap">
  <h1>9Box — Histórico e Rodada Atual</h1>
  <div class="muted">Selecione a rodada (ex.: YE2025 / Start2026). Clique em um quadrante para listar as pessoas daquela célula.</div>

  <div class="card">
    <div class="row">
      <div>
        <label>Rodada</label>
        <select id="roundSelect"></select>
      </div>

      <div style="min-width:320px">
        <label>Filtrar por gestor (opcional)</label>
        <input id="managerInput" type="text" placeholder="Ex.: GABRIEL VICTOR BONDAN"/>
      </div>

      <div>
        <button onclick="loadNinebox()">Carregar 9Box</button>
      </div>

      <div>
        <button class="secondary" onclick="clearFilter()">Limpar filtro</button>
      </div>

      <div class="muted" id="msg" style="padding-bottom:10px"></div>
    </div>
  </div>

  <div class="card">
    <div class="kpi">
      <div class="pill"><small>Rodada:</small> <span id="kRound">-</span></div>
      <div class="pill"><small>Gestor:</small> <span id="kManager">Todos</span></div>
      <div class="pill"><small>Total:</small> <span id="kTotal">0</span></div>
    </div>

    <div class="legend" style="margin-top:10px">
      <span><b>Linhas:</b> Potencial (Alto → Médio → Baixo)</span>
      <span><b>Colunas:</b> Desempenho (Baixo → Médio → Alto)</span>
    </div>

    <div style="margin-top:12px">
      <table>
        <tr>
          <th></th>
          <th>Desempenho Baixo</th>
          <th>Desempenho Médio</th>
          <th>Desempenho Alto</th>
        </tr>

        <tr>
          <th>Potencial Alto</th>
          <td class="cell" onclick="showCell(1)"><b id="c1">0</b><div>Pos 1</div></td>
          <td class="cell" onclick="showCell(2)"><b id="c2">0</b><div>Pos 2</div></td>
          <td class="cell" onclick="showCell(3)"><b id="c3">0</b><div>Pos 3</div></td>
        </tr>

        <tr>
          <th>Potencial Médio</th>
          <td class="cell" onclick="showCell(4)"><b id="c4">0</b><div>Pos 4</div></td>
          <td class="cell" onclick="showCell(5)"><b id="c5">0</b><div>Pos 5</div></td>
          <td class="cell" onclick="showCell(6)"><b id="c6">0</b><div>Pos 6</div></td>
        </tr>

        <tr>
          <th>Potencial Baixo</th>
          <td class="cell" onclick="showCell(7)"><b id="c7">0</b><div>Pos 7</div></td>
          <td class="cell" onclick="showCell(8)"><b id="c8">0</b><div>Pos 8</div></td>
          <td class="cell" onclick="showCell(9)"><b id="c9">0</b><div>Pos 9</div></td>
        </tr>
      </table>
    </div>
  </div>

  <div class="card list">
    <div style="display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap">
      <div><b>Lista do quadrante:</b> <span id="cellTitle" class="muted">Nenhum selecionado</span></div>
    </div>
    <div style="margin-top:10px;overflow:auto">
      <table style="width:100%">
        <thead>
          <tr>
            <th>Colaborador</th>
            <th>Cargo</th>
            <th>Empresa</th>
            <th>Gestor</th>
            <th>Final</th>
            <th>Perf</th>
            <th>Pot</th>
            <th>Pos</th>
            <th>Rodada</th>
            <th>Data</th>
          </tr>
        </thead>
        <tbody id="tbody">
          <tr><td colspan="10" class="muted">Clique em um quadrante para listar.</td></tr>
        </tbody>
      </table>
    </div>
  </div>

</div>

<script>
  let lastPayload = null;

  function setMsg(t){ document.getElementById('msg').textContent = t || ''; }

  async function loadRoundsDropdown() {
    const sel = document.getElementById('roundSelect');
    sel.innerHTML = '';
    try {
      const [rList, rActive] = await Promise.all([
        fetch('/api/rounds/list').then(r=>r.json()),
        fetch('/api/rounds/active').then(r=>r.json())
      ]);

      const items = (rList.items || []);
      items.forEach(x=>{
        const opt = document.createElement('option');
        opt.value = x.code;
        opt.textContent = `${x.code} (${x.status})`;
        sel.appendChild(opt);
      });

      // se tiver ativa, seleciona ela
      const active = (rActive.active_round_code || '').trim();
      if (active) sel.value = active;
    } catch(e) {
      // fallback simples se o /api/rounds/list não existir
      ['Start2026','YE2025'].forEach(code=>{
        const opt = document.createElement('option');
        opt.value = code;
        opt.textContent = code;
        sel.appendChild(opt);
      });
    }
  }

  function clearFilter(){
    document.getElementById('managerInput').value = '';
    loadNinebox();
  }

  async function loadNinebox() {
    const round_code = (document.getElementById('roundSelect').value || '').trim();
    const manager_name = (document.getElementById('managerInput').value || '').trim();

    const qs = new URLSearchParams();
    if (round_code) qs.set('round_code', round_code);
    if (manager_name) qs.set('manager_name', manager_name);

    setMsg('Carregando...');
    try{
      const r = await fetch('/api/ninebox?' + qs.toString());
      const j = await r.json();
      if(!r.ok) throw new Error(j.error || ('HTTP ' + r.status));

      lastPayload = j;

      document.getElementById('kRound').textContent = j.round_code || '-';
      document.getElementById('kManager').textContent = j.manager_name || 'Todos';
      document.getElementById('kTotal').textContent = String(j.total || 0);

      const c = j.counts || {};
      for(let i=1;i<=9;i++){
        document.getElementById('c'+i).textContent = String(c[String(i)] || 0);
      }

      // limpa lista
      document.getElementById('cellTitle').textContent = 'Nenhum selecionado';
      document.getElementById('tbody').innerHTML = '<tr><td colspan="10" class="muted">Clique em um quadrante para listar.</td></tr>';

      setMsg('OK');
    }catch(e){
      setMsg('Erro: ' + e.message);
    }
  }

  function showCell(pos){
    if(!lastPayload || !Array.isArray(lastPayload.items)) return;
    const items = lastPayload.items.filter(x => Number(x.nine_box_position) === Number(pos));
    document.getElementById('cellTitle').textContent = 'Posição ' + pos + ' — ' + items.length + ' pessoa(s)';

    const tb = document.getElementById('tbody');
    if(items.length === 0){
      tb.innerHTML = '<tr><td colspan="10" class="muted">Sem pessoas nesse quadrante.</td></tr>';
      return;
    }

    tb.innerHTML = items.map(x => `
      <tr>
        <td>${x.employee_name || '-'}</td>
        <td>${x.cargo || '-'}</td>
        <td>${x.empresa || '-'}</td>
        <td>${x.manager_name || '-'}</td>
        <td>${(x.final_rating ?? '-')}</td>
        <td>${(x.performance_rating ?? '-')}</td>
        <td>${(x.potential_rating ?? '-')}</td>
        <td>${(x.nine_box_position ?? '-')}</td>
        <td>${x.round_code || '-'}</td>
        <td>${x.evaluation_date || '-'}</td>
      </tr>
    `).join('');
  }

  document.addEventListener('DOMContentLoaded', async ()=>{
    await loadRoundsDropdown();
    await loadNinebox();
  });
</script>
</body></html>
    """
    return html

@app.route('/team-ninebox')
def team_ninebox():
    """
    Gestor acessa por link com ?t=TOKEN.
    Se o token for válido, gravamos cookie httpOnly 'manager_access' e abrimos a tela do 9box.
    """
    t = (request.args.get('t') or '').strip()
    resp = make_response(ninebox_page())  # usa o mesmo HTML acima
    if t:
        info = verify_manager_token(t)
        if info and info.get('mc'):
            resp.set_cookie(
                'manager_access',
                info['mc'],
                max_age=30*24*3600,
                secure=True,
                httponly=True,
                samesite='Lax'
            )
        else:
            resp.set_cookie('manager_access', '', expires=0)
    return resp



# ===================== OKR Module: Empresas + Ciclos (Ano) =====================

def _okr_actor():
    """Quem alterou (audit). Reaproveita seu padrão."""
    try:
        return (request.headers.get("X-User") or "").strip() or "admin"
    except Exception:
        return "admin"


def _okr_log(company_id: int, cycle_id: int, entity_type: str, entity_id: int, action: str, data: dict):
    """Grava histórico em okr_history (audit trail)."""
    try:
        payload = {
            "company_id": company_id,
            "cycle_id": cycle_id,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "action": action,
            "changed_at": datetime.now(timezone.utc).isoformat(),
            "changed_by": _okr_actor(),
            "data": data or {}
        }
        supabase.table("okr_history").insert(payload).execute()
    except Exception as e:
        print("[OKR_HISTORY] erro ao gravar histórico:", e)


def _okr_get_or_create_company(company_name: str):
    """
    Garante que exista uma empresa em okr_companies.
    Retorna row {id, name, slug, ...}
    """
    name = (company_name or "").strip()
    if not name:
        return None

    # tenta achar por name (exato)
    try:
        r = (
            supabase.table("okr_companies")
            .select("*")
            .eq("name", name)
            .limit(1)
            .execute()
        )
        rows = r.data or []
        if rows:
            return rows[0]
    except Exception as e:
        print("[OKR] erro ao buscar company:", e)

    # cria se não achou
    try:
        # slug simples
        slug = name.lower().strip().replace(" ", "-")[:60]
        ins = supabase.table("okr_companies").insert({
            "name": name,
            "slug": slug
        }).execute()
        rows = ins.data or []
        return rows[0] if rows else None
    except Exception as e:
        print("[OKR] erro ao criar company:", e)
        return None


def _okr_get_active_cycle_id(company_id: int):
    """
    Lê okr_active_cycle (system_config) por empresa.
    Vamos guardar como: config_key = 'okr_active_cycle::<company_id>'
    """
    try:
        key = f"okr_active_cycle::{company_id}"
        r = (
            supabase.table("system_config")
            .select("config_value")
            .eq("config_key", key)
            .maybe_single()
            .execute()
        )
        val = (r.data or {}).get("config_value")
        return int(val) if val else None
    except Exception:
        return None


def _okr_set_active_cycle_id(company_id: int, cycle_id: int):
    try:
        key = f"okr_active_cycle::{company_id}"
        supabase.table("system_config").upsert({
            "config_key": key,
            "config_value": str(cycle_id),
            "description": f"Ciclo OKR ativo da empresa {company_id}: {cycle_id}"
        }, on_conflict="config_key").execute()
        return True
    except Exception as e:
        print("[OKR] erro ao setar ciclo ativo:", e)
        return False


@app.route("/api/okr/companies/ensure", methods=["POST"])
def api_okr_ensure_company():
    """
    POST /api/okr/companies/ensure
    Body: { "name": "Nome da Empresa" }
    Retorna a empresa existente ou criada.
    """
    try:
        body = request.get_json(silent=True) or {}
        name = (body.get("name") or "").strip()
        if not name:
            return jsonify({"error": "name obrigatório"}), 400

        row = _okr_get_or_create_company(name)
        if not row:
            return jsonify({"error": "Falha ao criar/buscar empresa"}), 500

        return jsonify(row), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/okr/cycles", methods=["GET"])
def api_okr_cycles_list():
    """
    GET /api/okr/cycles?company_name=EmpresaX
    ou  /api/okr/cycles?company_id=1
    Lista ciclos (anos) de uma empresa.
    """
    try:
        company_id = request.args.get("company_id", type=int)
        company_name = (request.args.get("company_name") or "").strip()

        if not company_id:
            if not company_name:
                return jsonify({"error": "company_id ou company_name obrigatório"}), 400
            comp = _okr_get_or_create_company(company_name)
            if not comp:
                return jsonify({"error": "empresa não encontrada"}), 404
            company_id = int(comp["id"])

        r = (
            supabase.table("okr_cycles")
            .select("*")
            .eq("company_id", company_id)
            .order("year", desc=True)
            .execute()
        )
        items = r.data or []

        active_cycle_id = _okr_get_active_cycle_id(company_id)

        return jsonify({
            "company_id": company_id,
            "active_cycle_id": active_cycle_id,
            "items": items
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/okr/cycles", methods=["POST"])
def api_okr_cycles_create():
    """
    POST /api/okr/cycles
    Body:
      {
        "company_name": "Empresa X",
        "year": 2026,
        "name": "OKRs 2026",
        "status": "ACTIVE"   (opcional)
      }

    Cria ciclo se não existir. Se já existir, retorna o existente.
    """
    try:
        body = request.get_json(silent=True) or {}
        company_name = (body.get("company_name") or "").strip()
        year = body.get("year")

        if not company_name:
            return jsonify({"error": "company_name obrigatório"}), 400
        if not year:
            return jsonify({"error": "year obrigatório"}), 400

        try:
            year = int(year)
        except Exception:
            return jsonify({"error": "year inválido"}), 400

        comp = _okr_get_or_create_company(company_name)
        if not comp:
            return jsonify({"error": "empresa não encontrada"}), 404
        company_id = int(comp["id"])

        # Se já existe, retorna
        existing = (
            supabase.table("okr_cycles")
            .select("*")
            .eq("company_id", company_id)
            .eq("year", year)
            .limit(1)
            .execute()
        ).data or []
        if existing:
            row = existing[0]
            return jsonify({"created": False, "cycle": row}), 200

        # cria
        row_ins = {
            "company_id": company_id,
            "year": year,
            "name": (body.get("name") or f"OKRs {year}").strip(),
            "status": (body.get("status") or "DRAFT").strip()
        }
        ins = supabase.table("okr_cycles").insert(row_ins).execute()
        rows = ins.data or []
        if not rows:
            return jsonify({"error": "Falha ao criar ciclo"}), 500

        cycle = rows[0]
        cycle_id = int(cycle["id"])

        # histórico
        _okr_log(company_id, cycle_id, "CYCLE", cycle_id, "CREATE", cycle)

        return jsonify({"created": True, "cycle": cycle}), 201

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/okr/cycles/active", methods=["PUT"])
def api_okr_cycles_set_active():
    """
    PUT /api/okr/cycles/active
    Body: { "company_id": 1, "cycle_id": 10 }
    Define o ciclo ativo (para facilitar telas e filtros).
    """
    try:
        body = request.get_json(silent=True) or {}
        company_id = body.get("company_id")
        cycle_id = body.get("cycle_id")

        if not company_id or not cycle_id:
            return jsonify({"error": "company_id e cycle_id obrigatórios"}), 400

        company_id = int(company_id)
        cycle_id = int(cycle_id)

        ok = _okr_set_active_cycle_id(company_id, cycle_id)
        if not ok:
            return jsonify({"error": "Falha ao salvar ciclo ativo"}), 500

        return jsonify({"message": "Ciclo ativo definido", "company_id": company_id, "cycle_id": cycle_id}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ===================== OKR Module: Objetivos (O) =====================

@app.route("/api/okr/objectives", methods=["GET"])
def api_okr_objectives_list():
    """
    GET /api/okr/objectives?company_id=1&cycle_id=1
    Lista objetivos do ciclo.
    """
    try:
        company_id = request.args.get("company_id", type=int)
        cycle_id = request.args.get("cycle_id", type=int)

        if not company_id or not cycle_id:
            return jsonify({"error": "company_id e cycle_id obrigatórios"}), 400

        r = (
            supabase.table("okr_objectives")
            .select("*")
            .eq("company_id", company_id)
            .eq("cycle_id", cycle_id)
            .order("id", desc=False)
            .execute()
        )
        return jsonify({"items": r.data or []}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/okr/objectives", methods=["POST"])
def api_okr_objectives_create():
    try:
        body = request.get_json(silent=True) or {}
        company_id = int(body.get("company_id") or 0)
        cycle_id = int(body.get("cycle_id") or 0)
        title = (body.get("title") or "").strip()

        if not company_id or not cycle_id or not title:
            return jsonify({"error": "company_id, cycle_id e title são obrigatórios"}), 400

        # ✅ idempotência sem maybe_single (evita 204 bug)
        r_exist = (
            supabase.table("okr_objectives")
            .select("*")
            .eq("company_id", company_id)
            .eq("cycle_id", cycle_id)
            .eq("title", title)
            .limit(1)
            .execute()
        )
        exists_list = r_exist.data or []
        if exists_list:
            return jsonify({"created": False, "objective": exists_list[0]}), 200

        row = {
            "company_id": company_id,
            "cycle_id": cycle_id,
            "title": title,
            "description": (body.get("description") or None),
            "level": (body.get("level") or "COMPANY").strip(),
            "owner_employee_id": body.get("owner_employee_id"),
            "status": (body.get("status") or "ACTIVE").strip(),
            "updated_at": datetime.now(timezone.utc).isoformat()
        }

        ins = supabase.table("okr_objectives").insert(row).execute()
        rows = ins.data or []
        if not rows:
            return jsonify({"error": "Falha ao criar objetivo"}), 500

        obj = rows[0]
        _okr_log(company_id, cycle_id, "OBJECTIVE", int(obj["id"]), "CREATE", obj)

        return jsonify({"created": True, "objective": obj}), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/okr/objectives/<int:objective_id>", methods=["PUT"])
def api_okr_objectives_update(objective_id: int):
    """
    PUT /api/okr/objectives/<id>
    Body: campos para atualizar
    """
    try:
        body = request.get_json(silent=True) or {}

        # pega atual
        cur = (
            supabase.table("okr_objectives")
            .select("*")
            .eq("id", objective_id)
            .maybe_single()
            .execute()
        ).data
        if not cur:
            return jsonify({"error": "Objetivo não encontrado"}), 404

        company_id = int(cur["company_id"])
        cycle_id = int(cur["cycle_id"])

        # monta patch permitido
        patch = {}
        for k in ["title", "description", "level", "owner_employee_id", "status"]:
            if k in body:
                patch[k] = body.get(k)

        if "title" in patch and patch["title"]:
            patch["title"] = str(patch["title"]).strip()

        patch["updated_at"] = datetime.now(timezone.utc).isoformat()

        r = (
            supabase.table("okr_objectives")
            .update(patch)
            .eq("id", objective_id)
            .execute()
        )
        updated = (r.data or [None])[0] or (
            supabase.table("okr_objectives").select("*").eq("id", objective_id).maybe_single().execute()
        ).data

        _okr_log(company_id, cycle_id, "OBJECTIVE", objective_id, "UPDATE", {"before": cur, "after": updated})
        return jsonify({"updated": True, "objective": updated}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/okr/objectives/<int:objective_id>", methods=["DELETE"])
def api_okr_objectives_delete(objective_id: int):
    try:
        cur = (
            supabase.table("okr_objectives")
            .select("*")
            .eq("id", objective_id)
            .maybe_single()
            .execute()
        ).data
        if not cur:
            return jsonify({"error": "Objetivo não encontrado"}), 404

        company_id = int(cur["company_id"])
        cycle_id = int(cur["cycle_id"])

        supabase.table("okr_objectives").delete().eq("id", objective_id).execute()
        _okr_log(company_id, cycle_id, "OBJECTIVE", objective_id, "DELETE", cur)

        return jsonify({"deleted": True}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ===================== OKR Module: Key Results (KR) =====================

@app.route("/api/okr/key-results", methods=["GET"])
def api_okr_krs_list():
    """
    GET /api/okr/key-results?company_id=1&cycle_id=1&objective_id=1(opcional)
    """
    try:
        company_id = request.args.get("company_id", type=int)
        cycle_id = request.args.get("cycle_id", type=int)
        objective_id = request.args.get("objective_id", type=int)

        if not company_id or not cycle_id:
            return jsonify({"error": "company_id e cycle_id obrigatórios"}), 400

        q = (
            supabase.table("okr_key_results")
            .select("*")
            .eq("company_id", company_id)
            .eq("cycle_id", cycle_id)
            .order("id", desc=False)
        )
        if objective_id:
            q = q.eq("objective_id", objective_id)

        r = q.execute()
        return jsonify({"items": r.data or []}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/okr/key-results", methods=["POST"])
def api_okr_krs_create():
    try:
        body = request.get_json(silent=True) or {}

        company_id = int(body.get("company_id") or 0)
        cycle_id = int(body.get("cycle_id") or 0)
        objective_id = int(body.get("objective_id") or 0)

        title = (body.get("title") or "").strip()
        metric_name = (body.get("metric_name") or "").strip()

        if not company_id or not cycle_id or not objective_id or not title or not metric_name:
            return jsonify({"error": "company_id, cycle_id, objective_id, title e metric_name são obrigatórios"}), 400

        # ✅ idempotência sem maybe_single (evita 204 bug)
        r_exist = (
            supabase.table("okr_key_results")
            .select("*")
            .eq("company_id", company_id)
            .eq("cycle_id", cycle_id)
            .eq("objective_id", objective_id)
            .eq("title", title)
            .eq("metric_name", metric_name)
            .limit(1)
            .execute()
        )
        exists_list = r_exist.data or []
        if exists_list:
            return jsonify({"created": False, "kr": exists_list[0]}), 200

        row = {
            "company_id": company_id,
            "cycle_id": cycle_id,
            "objective_id": objective_id,
            "title": title,
            "metric_name": metric_name,
            "metric_unit": (body.get("metric_unit") or "").strip(),
            "baseline": body.get("baseline"),
            "target": body.get("target"),
            "direction": (body.get("direction") or "UP").strip(),
            "data_source": body.get("data_source"),
            "owner_employee_id": body.get("owner_employee_id"),
            "status": (body.get("status") or "ACTIVE").strip(),
            "updated_at": datetime.now(timezone.utc).isoformat()
        }

        ins = supabase.table("okr_key_results").insert(row).execute()
        rows = ins.data or []
        if not rows:
            return jsonify({"error": "Falha ao criar KR"}), 500

        kr = rows[0]
        _okr_log(company_id, cycle_id, "KR", int(kr["id"]), "CREATE", kr)

        return jsonify({"created": True, "kr": kr}), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/okr/key-results/<int:kr_id>", methods=["PUT"])
def api_okr_krs_update(kr_id: int):
    try:
        body = request.get_json(silent=True) or {}

        cur = (
            supabase.table("okr_key_results")
            .select("*")
            .eq("id", kr_id)
            .maybe_single()
            .execute()
        ).data
        if not cur:
            return jsonify({"error": "KR não encontrado"}), 404

        company_id = int(cur["company_id"])
        cycle_id = int(cur["cycle_id"])

        patch = {}
        for k in ["title","metric_name","metric_unit","baseline","target","direction","data_source","owner_employee_id","status","objective_id"]:
            if k in body:
                patch[k] = body.get(k)

        if "title" in patch and patch["title"]:
            patch["title"] = str(patch["title"]).strip()
        if "metric_name" in patch and patch["metric_name"]:
            patch["metric_name"] = str(patch["metric_name"]).strip()

        patch["updated_at"] = datetime.now(timezone.utc).isoformat()

        r = supabase.table("okr_key_results").update(patch).eq("id", kr_id).execute()
        updated = (r.data or [None])[0] or (
            supabase.table("okr_key_results").select("*").eq("id", kr_id).maybe_single().execute()
        ).data

        _okr_log(company_id, cycle_id, "KR", kr_id, "UPDATE", {"before": cur, "after": updated})
        return jsonify({"updated": True, "kr": updated}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/okr/key-results/<int:kr_id>", methods=["DELETE"])
def api_okr_krs_delete(kr_id: int):
    try:
        cur = (
            supabase.table("okr_key_results")
            .select("*")
            .eq("id", kr_id)
            .maybe_single()
            .execute()
        ).data
        if not cur:
            return jsonify({"error": "KR não encontrado"}), 404

        company_id = int(cur["company_id"])
        cycle_id = int(cur["cycle_id"])

        supabase.table("okr_key_results").delete().eq("id", kr_id).execute()
        _okr_log(company_id, cycle_id, "KR", kr_id, "DELETE", cur)

        return jsonify({"deleted": True}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ===================== OKR Module: Links (schema atual okr_links) =====================

@app.route("/api/okr/links", methods=["GET"])
def api_okr_links_list():
    """
    GET /api/okr/links?company_id=1&cycle_id=1&to_kr_id=1(opcional)
    """
    try:
        company_id = request.args.get("company_id", type=int)
        cycle_id = request.args.get("cycle_id", type=int)
        to_kr_id = request.args.get("to_kr_id", type=int)

        if not company_id or not cycle_id:
            return jsonify({"error": "company_id e cycle_id obrigatórios"}), 400

        q = (
            supabase.table("okr_links")
            .select("*")
            .eq("company_id", company_id)
            .eq("cycle_id", cycle_id)
            .order("id", desc=False)
        )
        if to_kr_id:
            q = q.eq("to_kr_id", to_kr_id)

        r = q.execute()
        return jsonify({"items": r.data or []}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/okr/links", methods=["POST"])
def api_okr_links_create():
    """
    POST /api/okr/links

    1) INDIVIDUAL_GOAL_TO_KR:
      {"company_id":1,"cycle_id":1,"link_type":"INDIVIDUAL_GOAL_TO_KR","from_individual_goal_id":1245,"to_kr_id":1,"weight":1,"note":"..."}

    2) GOAL_TO_KR (okr_goals -> KR):
      {"company_id":1,"cycle_id":1,"link_type":"GOAL_TO_KR","from_goal_id":10,"to_kr_id":1,"weight":1,"note":"..."}

    3) GOAL_TO_GOAL (empurrar meta -> meta):
      {"company_id":1,"cycle_id":1,"link_type":"GOAL_TO_GOAL","from_goal_id":10,"to_goal_id":20,"weight":1,"note":"..."}
    """
    try:
        body = request.get_json(silent=True) or {}
        company_id = int(body.get("company_id") or 0)
        cycle_id = int(body.get("cycle_id") or 0)
        link_type = (body.get("link_type") or "").strip()

        from_goal_id = body.get("from_goal_id")
        to_goal_id = body.get("to_goal_id")
        to_kr_id = body.get("to_kr_id")

        # ✅ novo campo
        from_individual_goal_id = body.get("from_individual_goal_id")

        weight = body.get("weight", 1)
        note = body.get("note")

        if not company_id or not cycle_id or not link_type:
            return jsonify({"error": "company_id, cycle_id e link_type são obrigatórios"}), 400

        if link_type not in ("GOAL_TO_KR", "GOAL_TO_GOAL", "INDIVIDUAL_GOAL_TO_KR"):
            return jsonify({"error": "link_type inválido"}), 400

        # ===================== 1) INDIVIDUAL_GOAL_TO_KR =====================
        if link_type == "INDIVIDUAL_GOAL_TO_KR":
            if not from_individual_goal_id or not to_kr_id:
                return jsonify({"error": "from_individual_goal_id e to_kr_id são obrigatórios"}), 400

            r_exist = (
                supabase.table("okr_links")
                .select("*")
                .eq("company_id", company_id)
                .eq("cycle_id", cycle_id)
                .eq("link_type", link_type)
                .eq("from_individual_goal_id", int(from_individual_goal_id))
                .eq("to_kr_id", int(to_kr_id))
                .limit(1)
                .execute()
            )
            ex = r_exist.data or []
            if ex:
                return jsonify({"created": False, "link": ex[0]}), 200

            row = {
                "company_id": company_id,
                "cycle_id": cycle_id,
                "link_type": link_type,
                "from_individual_goal_id": int(from_individual_goal_id),
                "to_kr_id": int(to_kr_id),
                "weight": float(weight or 1),
                "note": note
            }

        # ===================== 2) GOAL_TO_KR =====================
        elif link_type == "GOAL_TO_KR":
            if not from_goal_id or not to_kr_id:
                return jsonify({"error": "from_goal_id e to_kr_id são obrigatórios"}), 400

            r_exist = (
                supabase.table("okr_links")
                .select("*")
                .eq("company_id", company_id)
                .eq("cycle_id", cycle_id)
                .eq("link_type", link_type)
                .eq("from_goal_id", int(from_goal_id))
                .eq("to_kr_id", int(to_kr_id))
                .limit(1)
                .execute()
            )
            ex = r_exist.data or []
            if ex:
                return jsonify({"created": False, "link": ex[0]}), 200

            row = {
                "company_id": company_id,
                "cycle_id": cycle_id,
                "link_type": link_type,
                "from_goal_id": int(from_goal_id),
                "to_kr_id": int(to_kr_id),
                "weight": float(weight or 1),
                "note": note
            }

        # ===================== 3) GOAL_TO_GOAL =====================
        else:
            if not from_goal_id or not to_goal_id:
                return jsonify({"error": "from_goal_id e to_goal_id são obrigatórios"}), 400

            r_exist = (
                supabase.table("okr_links")
                .select("*")
                .eq("company_id", company_id)
                .eq("cycle_id", cycle_id)
                .eq("link_type", link_type)
                .eq("from_goal_id", int(from_goal_id))
                .eq("to_goal_id", int(to_goal_id))
                .limit(1)
                .execute()
            )
            ex = r_exist.data or []
            if ex:
                return jsonify({"created": False, "link": ex[0]}), 200

            row = {
                "company_id": company_id,
                "cycle_id": cycle_id,
                "link_type": link_type,
                "from_goal_id": int(from_goal_id),
                "to_goal_id": int(to_goal_id),
                "weight": float(weight or 1),
                "note": note
            }

        ins = supabase.table("okr_links").insert(row).execute()
        rows = ins.data or []
        if not rows:
            return jsonify({"error": "Falha ao criar link"}), 500

        link = rows[0]
        _okr_log(company_id, cycle_id, "LINK", int(link["id"]), "CREATE", link)
        return jsonify({"created": True, "link": link}), 201

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/okr/links/<int:link_id>", methods=["DELETE"])
def api_okr_links_delete(link_id: int):
    try:
        cur = (
            supabase.table("okr_links")
            .select("*")
            .eq("id", link_id)
            .limit(1)
            .execute()
        ).data
        if not cur:
            return jsonify({"error": "Link não encontrado"}), 404

        row = cur[0]
        company_id = int(row["company_id"])
        cycle_id = int(row["cycle_id"])

        supabase.table("okr_links").delete().eq("id", link_id).execute()
        _okr_log(company_id, cycle_id, "LINK", link_id, "DELETE", row)
        return jsonify({"deleted": True}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ===================== OKR Module: KR Checkpoints & Progress =====================

def _month_start_str(s: str) -> str:
    """
    Recebe 'YYYY-MM' ou 'YYYY-MM-01' e devolve sempre 'YYYY-MM-01'
    """
    s = (s or "").strip()
    if not s:
        raise ValueError("month obrigatório (YYYY-MM ou YYYY-MM-01)")
    if len(s) == 7 and s[4] == "-":
        return s + "-01"
    # valida formato ISO
    d = datetime.fromisoformat(s).date()
    return f"{d.year:04d}-{d.month:02d}-01"


@app.route("/api/okr/krs/<int:kr_id>/checkpoint", methods=["POST"])
def api_okr_kr_checkpoint_upsert(kr_id: int):
    """
    POST /api/okr/krs/<kr_id>/checkpoint
    Body:
      {
        "company_id":1,
        "cycle_id":1,
        "month":"2026-02" (ou "2026-02-01"),
        "actual": 8,
        "forecast": 7,
        "status":"MEDIUM",
        "comment":"..."
      }
    Salva em okr_kr_checkpoints usando:
      competence (YYYY-MM-01) + kr_id
    """
    try:
        body = request.get_json(silent=True) or {}
        company_id = int(body.get("company_id") or 0)
        cycle_id = int(body.get("cycle_id") or 0)

        if not company_id or not cycle_id:
            return jsonify({"error": "company_id e cycle_id obrigatórios"}), 400

        competence = _month_start_str(str(body.get("month") or body.get("competence") or ""))

        actual = body.get("actual")
        forecast = body.get("forecast")
        status = (body.get("status") or "MEDIUM").strip().upper()
        comment = body.get("comment")

        row = {
            "company_id": company_id,
            "cycle_id": cycle_id,
            "kr_id": int(kr_id),
            "competence": competence,
            "actual": actual,
            "forecast": forecast,
            "status": status,
            "comment": comment,
            "updated_at": datetime.now(timezone.utc).isoformat()
        }

        # sua tabela tem unique(kr_id, competence)? se não tiver, vai inserir duplicado.
        # vamos usar on_conflict assumindo que você tem (kr_id, competence) OU (kr_id, competence) como unique.
        r = supabase.table("okr_kr_checkpoints").upsert(row, on_conflict="kr_id,competence").execute()
        rows = r.data or []
        if not rows:
            return jsonify({"error": "Falha ao salvar checkpoint"}), 500

        saved = rows[0]
        _okr_log(company_id, cycle_id, "KR_CHECKPOINT", int(saved["id"]), "UPSERT", saved)

        return jsonify({"saved": True, "checkpoint": saved}), 201

    except Exception as e:
        return jsonify({"error": str(e)}), 500


def _calc_progress_percent(baseline, target, actual, direction: str):
    """
    Retorna progresso 0..100 (float).
    direction:
      - UP: quanto maior melhor (baseline -> target)
      - DOWN: quanto menor melhor (baseline -> target)
    """
    try:
        b = float(baseline)
        t = float(target)
        a = float(actual)
    except Exception:
        return None

    direction = (direction or "UP").strip().upper()

    if direction == "DOWN":
        denom = (b - t)
        if denom == 0:
            return 0.0
        p = (b - a) / denom
    else:
        denom = (t - b)
        if denom == 0:
            return 0.0
        p = (a - b) / denom

    # clamp 0..1
    if p < 0:
        p = 0.0
    if p > 1:
        p = 1.0
    return round(p * 100.0, 2)


@app.route("/api/okr/krs/<int:kr_id>/progress", methods=["GET"])
def api_okr_kr_progress(kr_id: int):
    """
    GET /api/okr/krs/<kr_id>/progress?company_id=1&cycle_id=1
    Calcula progresso com base no ÚLTIMO checkpoint (maior competence).
    Usa tabela okr_kr_checkpoints (competence, actual).
    """
    try:
        company_id = request.args.get("company_id", type=int)
        cycle_id = request.args.get("cycle_id", type=int)
        if not company_id or not cycle_id:
            return jsonify({"error": "company_id e cycle_id obrigatórios"}), 400

        # 1) KR
        r_kr = (
            supabase.table("okr_key_results")
            .select("*")
            .eq("id", kr_id)
            .eq("company_id", company_id)
            .eq("cycle_id", cycle_id)
            .limit(1)
            .execute()
        )
        krs = r_kr.data or []
        if not krs:
            return jsonify({"error": "KR não encontrado"}), 404
        kr = krs[0]

        # 2) último checkpoint (por competence desc)
        r_cp = (
            supabase.table("okr_kr_checkpoints")
            .select("*")
            .eq("kr_id", kr_id)
            .eq("company_id", company_id)
            .eq("cycle_id", cycle_id)
            .order("competence", desc=True)
            .limit(1)
            .execute()
        )
        cps = r_cp.data or []
        last_cp = cps[0] if cps else None

        percent = None
        if last_cp and last_cp.get("actual") is not None:
            percent = _calc_progress_percent(
                kr.get("baseline"),
                kr.get("target"),
                last_cp.get("actual"),
                kr.get("direction")
            )

        return jsonify({
            "kr_id": kr_id,
            "company_id": company_id,
            "cycle_id": cycle_id,
            "baseline": kr.get("baseline"),
            "target": kr.get("target"),
            "direction": kr.get("direction"),
            "last_checkpoint": last_cp,
            "progress_percent": percent
        }), 200



    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ===== COLE A NOVA ROTA AQUI (começa no @app.route na coluna 1) =====
@app.route("/api/okr/krs/<int:kr_id>/linked-individual-goals", methods=["GET"])
def api_okr_kr_linked_individual_goals(kr_id: int):
    """
    GET /api/okr/krs/<kr_id>/linked-individual-goals?company_id=1&cycle_id=1
    Retorna as metas (individual_goals) linkadas ao KR via okr_links (INDIVIDUAL_GOAL_TO_KR)
    """
    try:
        company_id = request.args.get("company_id", type=int)
        cycle_id = request.args.get("cycle_id", type=int)
        if not company_id or not cycle_id:
            return jsonify({"error": "company_id e cycle_id obrigatórios"}), 400

        r_links = (
            supabase.table("okr_links")
            .select("id,from_individual_goal_id,weight,note,created_at")
            .eq("company_id", company_id)
            .eq("cycle_id", cycle_id)
            .eq("link_type", "INDIVIDUAL_GOAL_TO_KR")
            .eq("to_kr_id", kr_id)
            .order("id", desc=False)
            .execute()
        )
        links = r_links.data or []
        if not links:
            return jsonify({"items": []}), 200

        goal_ids = [x.get("from_individual_goal_id") for x in links if x.get("from_individual_goal_id") is not None]
        goal_ids = [int(x) for x in goal_ids if x is not None]
        if not goal_ids:
            return jsonify({"items": []}), 200

        r_goals = (
            supabase.table("individual_goals")
            .select("id,employee_id,goal_name,goal_description,weight,rating,round_code,evaluation_id")
            .in_("id", goal_ids)
            .execute()
        )
        goals = r_goals.data or []
        goals_by_id = {int(g["id"]): g for g in goals if g.get("id") is not None}

        out = []
        for l in links:
            gid = l.get("from_individual_goal_id")
            g = goals_by_id.get(int(gid)) if gid is not None else None
            out.append({
                "link_id": l.get("id"),
                "weight": l.get("weight"),
                "note": l.get("note"),
                "created_at": l.get("created_at"),
                "goal": g
            })

        return jsonify({"items": out}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500
# ===== FIM DA NOVA ROTA =====


# ===================== OKR Module: Settings (rating -> percent) =====================

def _okr_settings_default_row(company_id: int, cycle_id: int) -> dict:
    return {
        "company_id": company_id,
        "cycle_id": cycle_id,
        "rating_1_percent": 140,
        "rating_2_percent": 120,
        "rating_3_percent": 100,
        "rating_4_percent": 70,
        "rating_5_percent": 40,
        "clamp_over_100": True,
        "updated_at": datetime.now(timezone.utc).isoformat()
    }

from postgrest.exceptions import APIError

def _safe_exec_and_ignore_204(fn):
    """
    Alguns inserts/upserts retornam 204 e o client levanta APIError 'Missing response'.
    Aqui a gente ignora 204 e segue o fluxo (depois fazemos SELECT).
    """
    try:
        return fn()
    except APIError as e:
        payload = e.args[0] if e.args else None
        if isinstance(payload, dict) and str(payload.get("code")) == "204":
            return None
        raise




from postgrest.exceptions import APIError

def _safe_ignore_204(fn):
    try:
        return fn()
    except APIError as e:
        payload = e.args[0] if e.args else None
        if isinstance(payload, dict) and str(payload.get("code")) == "204":
            return None
        raise

@app.route("/api/okr/settings", methods=["GET"])
def api_okr_settings_get():
    """
    GET /api/okr/settings?company_id=1&cycle_id=1
    Se não existir, cria com default e retorna.
    """
    try:
        company_id = request.args.get("company_id", type=int)
        cycle_id = request.args.get("cycle_id", type=int)
        if not company_id or not cycle_id:
            return jsonify({"error": "company_id e cycle_id obrigatórios"}), 400

        # busca SEM maybe_single (evita bug 204)
        r = (
            supabase.table("okr_settings")
            .select("*")
            .eq("company_id", company_id)
            .eq("cycle_id", cycle_id)
            .limit(1)
            .execute()
        )
        rows = r.data or []
        row = rows[0] if rows else None

        if not row:
            payload = _okr_settings_default_row(company_id, cycle_id)
            _safe_ignore_204(lambda: supabase.table("okr_settings").insert(payload).execute())

            r2 = (
                supabase.table("okr_settings")
                .select("*")
                .eq("company_id", company_id)
                .eq("cycle_id", cycle_id)
                .limit(1)
                .execute()
            )
            rows2 = r2.data or []
            row = rows2[0] if rows2 else payload

        return jsonify({"settings": row}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/okr/settings", methods=["PUT"])
def api_okr_settings_put():
    """
    PUT /api/okr/settings
    """
    try:
        body = request.get_json(silent=True) or {}
        company_id = int(body.get("company_id") or 0)
        cycle_id = int(body.get("cycle_id") or 0)

        if not company_id or not cycle_id:
            return jsonify({"error": "company_id e cycle_id obrigatórios"}), 400

        def _num(name, default):
            v = body.get(name, default)
            try:
                return float(v)
            except Exception:
                return float(default)

        payload = {
            "company_id": company_id,
            "cycle_id": cycle_id,
            "rating_1_percent": _num("rating_1_percent", 140),
            "rating_2_percent": _num("rating_2_percent", 120),
            "rating_3_percent": _num("rating_3_percent", 100),
            "rating_4_percent": _num("rating_4_percent", 70),
            "rating_5_percent": _num("rating_5_percent", 40),
            "clamp_over_100": bool(body.get("clamp_over_100", True)),
            "updated_at": datetime.now(timezone.utc).isoformat()
        }

        _safe_ignore_204(lambda: supabase.table("okr_settings").upsert(payload, on_conflict="company_id,cycle_id").execute())

        r2 = (
            supabase.table("okr_settings")
            .select("*")
            .eq("company_id", company_id)
            .eq("cycle_id", cycle_id)
            .limit(1)
            .execute()
        )
        rows2 = r2.data or []
        saved = rows2[0] if rows2 else None
        if not saved:
            return jsonify({"error": "Falha ao salvar settings (sem retorno após re-busca)"}), 500

        _okr_log(company_id, cycle_id, "SETTINGS", int(saved["id"]), "UPSERT", saved)

        return jsonify({"saved": True, "settings": saved}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

def _rating_to_percent_from_settings(r, settings: dict):
    """
    Converte rating (1..5) para % usando okr_settings.
    Seu modelo: 1=excelente ... 5=insuficiente.
    """
    try:
        rr = int(float(r))
    except Exception:
        return None

    table = {
        1: float(settings.get("rating_1_percent", 140)),
        2: float(settings.get("rating_2_percent", 120)),
        3: float(settings.get("rating_3_percent", 100)),
        4: float(settings.get("rating_4_percent", 70)),
        5: float(settings.get("rating_5_percent", 40)),
    }
    return table.get(rr, None)



@app.route("/api/okr/krs/<int:kr_id>/progress-auto", methods=["GET"])
def api_okr_kr_progress_auto(kr_id: int):
    """
    GET /api/okr/krs/<kr_id>/progress-auto?company_id=1&cycle_id=1
    Progresso AUTOMÁTICO do KR baseado nas metas (individual_goals) linkadas.
    Usa okr_settings (rating->%) e clamp_over_100.
    """
    try:
        company_id = request.args.get("company_id", type=int)
        cycle_id = request.args.get("cycle_id", type=int)
        if not company_id or not cycle_id:
            return jsonify({"error": "company_id e cycle_id obrigatórios"}), 400

        # 1) carrega settings (sem maybe_single)
        rs = (
            supabase.table("okr_settings")
            .select("*")
            .eq("company_id", company_id)
            .eq("cycle_id", cycle_id)
            .limit(1)
            .execute()
        )
        srows = rs.data or []
        settings = srows[0] if srows else _okr_settings_default_row(company_id, cycle_id)
        clamp = bool(settings.get("clamp_over_100", True))

        # 2) links do tipo INDIVIDUAL_GOAL_TO_KR
        r_links = (
            supabase.table("okr_links")
            .select("id,from_individual_goal_id,weight,note,created_at")
            .eq("company_id", company_id)
            .eq("cycle_id", cycle_id)
            .eq("link_type", "INDIVIDUAL_GOAL_TO_KR")
            .eq("to_kr_id", kr_id)
            .order("id", desc=False)
            .execute()
        )
        links = r_links.data or []
        if not links:
            return jsonify({
                "kr_id": kr_id,
                "company_id": company_id,
                "cycle_id": cycle_id,
                "mode": "AUTO",
                "settings": settings,
                "items": [],
                "progress_percent_auto": None
            }), 200

        goal_ids = [x.get("from_individual_goal_id") for x in links if x.get("from_individual_goal_id") is not None]
        goal_ids = [int(x) for x in goal_ids if x is not None]
        if not goal_ids:
            return jsonify({
                "kr_id": kr_id,
                "company_id": company_id,
                "cycle_id": cycle_id,
                "mode": "AUTO",
                "settings": settings,
                "items": [],
                "progress_percent_auto": None
            }), 200

        # 3) metas (individual_goals)
        r_goals = (
            supabase.table("individual_goals")
            .select("id,employee_id,goal_name,weight,rating")
            .in_("id", goal_ids)
            .execute()
        )
        goals = r_goals.data or []
        goals_by_id = {int(g["id"]): g for g in goals if g.get("id") is not None}

        # 4) calcula média ponderada pelo weight do link
        items = []
        total_w = 0.0
        sum_w = 0.0

        for l in links:
            gid = l.get("from_individual_goal_id")
            g = goals_by_id.get(int(gid)) if gid is not None else None

            link_w = float(l.get("weight") or 1.0)
            rating = (g or {}).get("rating")
            pct = _rating_to_percent_from_settings(rating, settings) if rating is not None else None

            items.append({
                "link_id": l.get("id"),
                "from_individual_goal_id": gid,
                "link_weight": link_w,
                "goal": g,
                "rating": rating,
                "percent": pct
            })

            if pct is not None:
                total_w += link_w
                sum_w += (pct * link_w)

        progress = None
        if total_w > 0:
            progress = round(sum_w / total_w, 2)

        if progress is not None and clamp and progress > 100:
            progress = 100.0

        return jsonify({
            "kr_id": kr_id,
            "company_id": company_id,
            "cycle_id": cycle_id,
            "mode": "AUTO",
            "settings": settings,
            "items": items,
            "progress_percent_auto": progress
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

def _build_company_tree(rows):
    """
    rows: lista de dicts de okr_companies
    Retorna árvore: [{id, name, slug, company_type, children:[...]}]
    """
    by_id = {r["id"]: {**r, "children": []} for r in rows}
    roots = []

    for r in rows:
        pid = r.get("parent_company_id")
        node = by_id[r["id"]]
        if pid and pid in by_id:
            by_id[pid]["children"].append(node)
        else:
            roots.append(node)

    # ordenação opcional: sort_order, depois name
    def sort_children(n):
        n["children"].sort(key=lambda x: (x.get("sort_order") or 0, (x.get("name") or "").lower()))
        for c in n["children"]:
            sort_children(c)

    roots.sort(key=lambda x: (x.get("sort_order") or 0, (x.get("name") or "").lower()))
    for r in roots:
        sort_children(r)

    return roots


def _tree_to_flat_options(nodes, level=0, out=None):
    """
    Converte árvore em lista flat para <select>, com label indentado.
    """
    if out is None:
        out = []
    for n in nodes:
        prefix = ("— " * level)
        label = f"{prefix}{n.get('name')} ({n.get('company_type')})"
        out.append({
            "id": n.get("id"),
            "label": label,
            "name": n.get("name"),
            "slug": n.get("slug"),
            "company_type": n.get("company_type"),
            "parent_company_id": n.get("parent_company_id"),
        })
        if n.get("children"):
            _tree_to_flat_options(n["children"], level + 1, out)
    return out


@app.route("/api/okr/companies/tree", methods=["GET"])
def api_okr_companies_tree():
    """
    GET /api/okr/companies/tree
    params:
      include_inactive=true|false (default false)
      include_demo=true|false (default false) -> controla 'empresa-demo'
    Retorna:
      { tree:[...], options:[...] }
    """
    try:
        include_inactive = (request.args.get("include_inactive", "false").lower() == "true")
        include_demo = (request.args.get("include_demo", "false").lower() == "true")

        q = supabase.table("okr_companies").select(
            "id,name,slug,company_type,parent_company_id,active,sort_order"
        )

        if not include_inactive:
            q = q.eq("active", True)

        if not include_demo:
            q = q.neq("slug", "empresa-demo")

        r = q.execute()
        rows = r.data or []

        tree = _build_company_tree(rows)
        options = _tree_to_flat_options(tree)

        return jsonify({"tree": tree, "options": options}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/okr/org-units", methods=["GET"])
def api_okr_org_units():
    """
    GET /api/okr/org-units
    Retorna opções hierárquicas (HOLDING -> COMPANY -> DIVISION -> BUSINESS_LINE)
    para popular o SELECT do front.
    """
    try:
        r = (
            supabase.table("okr_companies")
            .select("id,name,slug,company_type,parent_company_id,sort_order,active")
            .order("sort_order", desc=False)
            .order("name", desc=False)
            .execute()
        )
        rows = r.data or []

        # agrupa por parent_company_id
        by_parent = {}
        for x in rows:
            by_parent.setdefault(x.get("parent_company_id"), []).append(x)

        def _sort(lst):
            return sorted(lst, key=lambda a: ((a.get("sort_order") or 0), (a.get("name") or "")))

        def walk(parent_id, depth):
            out = []
            for node in _sort(by_parent.get(parent_id, [])):
                prefix = "— " * depth
                out.append({
                    "id": node["id"],
                    "name": node.get("name"),
                    "slug": node.get("slug"),
                    "company_type": node.get("company_type"),
                    "parent_company_id": node.get("parent_company_id"),
                    "label": f"{prefix}{node.get('name')} ({node.get('company_type')})"
                })
                out.extend(walk(node["id"], depth + 1))
            return out

        options = walk(None, 0)
        return jsonify({"options": options}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ===================== Employee History (snapshot + movements) =====================

def _get_previous_closed_competence(comp: _date):
    """Retorna a competência CLOSED imediatamente anterior à informada."""
    try:
        r = (
            supabase.table("competence_locks")
            .select("competence")
            .eq("status", "CLOSED")
            .lt("competence", comp.isoformat())
            .order("competence", desc=True)
            .limit(1)
            .execute()
        )
        rows = r.data or []
        if not rows:
            return None
        return _date.fromisoformat(rows[0]["competence"])
    except Exception as e:
        print("[employee-history] erro _get_previous_closed_competence:", e)
        return None


def _rpc_month_snapshot(comp: _date):
    """
    Tenta montar snapshot do mês via RPC hc_month_rows.
    Retorna lista de colaboradores no formato esperado pelo frontend.
    """
    if not comp:
        return []

    try:
        rpc_res = supabase.rpc("hc_month_rows", {"p_competence": comp.isoformat()}).execute()
        rows = rpc_res.data or []
        out = []

        for r in rows:
            rt = str(r.get("registro_tipo") or "").upper()
            if rt not in ("HC", "LEAK"):
                continue
            if r.get("admission_after_month"):
                continue

            out.append({
                "id": r.get("employee_id"),
                "employee_id": r.get("employee_id"),
                "employee_code": r.get("employee_code"),
                "nome": r.get("nome"),
                "cargo": r.get("cargo"),
                "empresa": r.get("company_name") or r.get("empresa"),
                "company_name": r.get("company_name") or r.get("empresa"),
                "department_name": r.get("department_name"),
                "employment_status": r.get("employment_status"),
                "leave_reason": r.get("leave_reason"),
                "admission_date": r.get("admission_date"),
                "manager_name": r.get("manager_name") or "Sem gestor",
                "holding": r.get("holding"),
                "salario": r.get("salario"),
            })

        out.sort(key=lambda x: str(x.get("nome") or "").upper())
        return out

    except Exception as e:
        print("[employee-history] erro _rpc_month_snapshot:", e)
        return []


def _load_competence_movements(comp: _date):
    """Lê movimentos do employee_history da competência informada."""
    try:
        r = (
            supabase.table("employee_history")
            .select("employee_id,competence,round_code,action,changed_at,changed_by,data")
            .eq("competence", comp.isoformat())
            .order("changed_at", desc=False)
            .execute()
        )
        return r.data or []
    except Exception as e:
        print("[employee-history] erro _load_competence_movements:", e)
        return []


def _apply_movements_to_snapshot(base_snapshot: list, movements: list):
    """
    Aplica CREATE/UPDATE/DELETE em memória:
    - CREATE/UPDATE: substitui estado do colaborador pelo data mais recente
    - DELETE/REMOVE: remove do snapshot
    """
    by_id = {}

    for row in (base_snapshot or []):
        rid = row.get("id") or row.get("employee_id")
        if rid is None:
            continue
        by_id[int(rid)] = dict(row)

    for mv in (movements or []):
        action = str(mv.get("action") or "").upper()
        data = mv.get("data") or {}

        emp_id = mv.get("employee_id") or data.get("id") or data.get("employee_id")
        if emp_id is None:
            continue
        emp_id = int(emp_id)

        if action in ("DELETE", "REMOVE"):
            by_id.pop(emp_id, None)
            continue

        if isinstance(data, dict) and data:
            merged = dict(data)
            merged.setdefault("id", emp_id)
            by_id[emp_id] = merged

    snapshot = list(by_id.values())
    snapshot.sort(key=lambda x: str(x.get("nome") or "").upper())
    return snapshot


@app.route('/api/employee-history', methods=['GET'])
def api_employee_history():
    """
    GET /api/employee-history?competence=YYYY-MM-01

    Retorna:
    - snapshot: MONTH_SNAPSHOT da competência OU, se vazio, vigentes = mês anterior + movimentos do mês
    - movements: CREATE e UPDATE da competência
    """
    try:
        comp_str = (request.args.get('competence') or '').strip()
        if not comp_str:
            return jsonify({'error': 'competence obrigatória (YYYY-MM-01)'}), 400
        if len(comp_str) == 7 and comp_str[4] == '-':
            comp_str = comp_str + '-01'

        try:
            comp = _month_start(datetime.fromisoformat(comp_str).date())
        except (ValueError, TypeError):
            return jsonify({'error': 'competence inválida'}), 400

        comp_iso = comp.isoformat()

        # 1) Snapshot: MONTH_SNAPSHOT da competência
        snapshot = []
        try:
            r_snap = (
                supabase.table('employee_history')
                .select('employee_id, data')
                .eq('competence', comp_iso)
                .eq('action', 'MONTH_SNAPSHOT')
                .execute()
            )
            for row in (r_snap.data or []):
                d = row.get('data')
                if d is None:
                    continue
                if isinstance(d, str):
                    try:
                        d = json.loads(d)
                    except Exception:
                        continue
                if isinstance(d, dict):
                    d = dict(d)
                    d['employee_id'] = row.get('employee_id')
                    if d.get('id') is None:
                        d['id'] = row.get('employee_id')
                    snapshot.append(d)
        except Exception as e:
            print('[api_employee_history] snapshot:', e)

        # 2) Movimentações: CREATE e UPDATE da competência (ordenado por data)
        #    Paginação: buscar em lotes de 1000 para não perder nenhum registro
        movements = []
        try:
            page_size = 1000
            offset = 0
            while True:
                r_mov = (
                    supabase.table('employee_history')
                    .select('employee_id, action, changed_at, changed_by, data')
                    .eq('competence', comp_iso)
                    .in_('action', ['CREATE', 'UPDATE'])
                    .order('changed_at', desc=False)
                    .range(offset, offset + page_size - 1)
                    .execute()
                )
                rows = r_mov.data or []
                if not rows:
                    break
                for row in rows:
                    d = row.get('data')
                    if isinstance(d, str):
                        try:
                            d = json.loads(d) if d else {}
                        except Exception:
                            d = {}
                    movements.append({
                        'employee_id': row.get('employee_id'),
                        'action': row.get('action'),
                        'changed_at': row.get('changed_at'),
                        'changed_by': row.get('changed_by'),
                        'data': d if isinstance(d, dict) else {},
                        'previous_data': None
                    })
                offset += page_size
            # DEBUG: ver no Render Logs se o Pedro (250) está na resposta
            _pedro = sum(1 for m in movements if m.get('employee_id') == 250)
            print(f'[api_employee_history] competence={comp_iso} total_movements={len(movements)} employee_250_count={_pedro}')
        except Exception as e:
            print('[api_employee_history] movements:', e)

        # 3) Só vigentes quando o mês NÃO tem snapshot no DB E tem movimentos.
        #    Dez = 70 (tem snapshot). Jan = 73 (sem snapshot no DB + tem CREATE/UPDATE). Fev = 0 (sem snapshot, sem movimentos).
        if not snapshot and movements:
            try:
                if comp.month == 1:
                    comp_prev = comp.replace(year=comp.year - 1, month=12, day=1)
                else:
                    comp_prev = comp.replace(month=comp.month - 1, day=1)
                comp_prev_iso = comp_prev.isoformat()

                r_prev = (
                    supabase.table('employee_history')
                    .select('employee_id, data')
                    .eq('competence', comp_prev_iso)
                    .eq('action', 'MONTH_SNAPSHOT')
                    .execute()
                )
                base = {}
                for row in (r_prev.data or []):
                    d = row.get('data')
                    if d is None:
                        continue
                    if isinstance(d, str):
                        try:
                            d = json.loads(d)
                        except Exception:
                            continue
                    if isinstance(d, dict):
                        eid = row.get('employee_id')
                        if eid is not None:
                            d = dict(d)
                            d['id'] = d.get('id') or eid
                            d['employee_id'] = eid
                            base[eid] = d

                for m in movements:
                    eid = m.get('employee_id')
                    data = m.get('data') or {}
                    if eid is None:
                        continue
                    if m.get('action') == 'CREATE':
                        data = dict(data)
                        data['id'] = data.get('id') or eid
                        data['employee_id'] = eid
                        base[eid] = data
                    else:
                        if eid in base:
                            base[eid] = {**base[eid], **{k: v for k, v in data.items() if v is not None}}
                        else:
                            data = dict(data)
                            data['id'] = data.get('id') or eid
                            data['employee_id'] = eid
                            base[eid] = data

                snapshot = list(base.values())
            except Exception as e:
                print('[api_employee_history] vigentes:', e)
        # Se não tem movimentos (ex.: fev), snapshot fica o que veio do DB (vazio) = 0.

        return jsonify({
            'competence': comp_iso,
            'snapshot': snapshot,
            'movements': movements
        }), 200

    except Exception as e:
        return jsonify({'error': 'HISTORY_FAILED', 'details': str(e)}), 500

@app.route('/api/evaluations/<int:evaluation_id>/summary', methods=['GET', 'OPTIONS'])
def api_get_evaluation_summary(evaluation_id):
    """
    Consulta um resumo da avaliação.
    Usado pelo painel de workflow para exibir dados mesmo antes do workflow iniciar.
    Inclui dados básicos do profissional avaliado.
    """
    if request.method == 'OPTIONS':
        return ('', 204)

    try:
        # 1) Buscar avaliação
        r_eval = (
            supabase
            .table('evaluations')
            .select(
                'id, employee_id, evaluator_id, evaluation_year, evaluation_date, status, '
                'final_rating, nine_box_position, performance_rating, potential_rating, '
                'round_code, cliente_id, empresa_id, filial_id, modelo_avaliacao_id, '
                'versao_modelo_id, ciclo_avaliacao_id, evaluation_origem_id, created_at'
            )
            .eq('id', evaluation_id)
            .limit(1)
            .execute()
        )

        rows = r_eval.data or []

        if not rows:
            r_workflow = (
                supabase
                .table('evaluation_workflows')
                .select('evaluation_id, employee_id, round_code')
                .eq('evaluation_id', evaluation_id)
                .limit(1)
                .execute()
            )

            workflow_rows = r_workflow.data or []
            if workflow_rows:
                workflow_row = workflow_rows[0]
                employee_id = workflow_row.get('employee_id')
                round_code = workflow_row.get('round_code')
                employee = None

                if employee_id:
                    r_emp = (
                        supabase
                        .table('employees')
                        .select(
                            'id, nome, cargo, empresa, company_name, branch_name, department_name, '
                            'manager_name, email, emailLider, employee_code, manager_code, '
                            'holding, business_line, nivel, cliente_id, holding_id, empresa_id, filial_id'
                        )
                        .eq('id', employee_id)
                        .limit(1)
                        .execute()
                    )

                    emp_rows = r_emp.data or []
                    employee = emp_rows[0] if emp_rows else None

                rating_ctx = {}
                if round_code:
                    ratings_by_evaluation_id, ratings_by_employee_id = _get_workflow_rating_context_map(round_code)
                    rating_ctx = (
                        ratings_by_evaluation_id.get(evaluation_id)
                        or ratings_by_employee_id.get(employee_id)
                        or {}
                    )

                evaluation = {
                    'id': evaluation_id,
                    'employee_id': employee_id,
                    'evaluator_id': None,
                    'evaluation_year': None,
                    'evaluation_date': None,
                    'status': None,
                    'final_rating': rating_ctx.get('final_rating'),
                    'nine_box_position': rating_ctx.get('nine_box_position'),
                    'performance_rating': rating_ctx.get('performance_rating'),
                    'potential_rating': rating_ctx.get('potential_rating'),
                    'round_code': round_code,
                    'cliente_id': employee.get('cliente_id') if employee else None,
                    'empresa_id': employee.get('empresa_id') if employee else None,
                    'filial_id': employee.get('filial_id') if employee else None,
                    'modelo_avaliacao_id': None,
                    'versao_modelo_id': None,
                    'ciclo_avaliacao_id': None,
                    'evaluation_origem_id': None,
                    'created_at': None
                }

                return jsonify({
                    'success': True,
                    'evaluation': evaluation,
                    'employee': employee
                }), 200

        if not rows:
            return jsonify({
                'success': False,
                'error': 'avaliacao_nao_encontrada',
                'message': 'Avaliação não encontrada.'
            }), 404

        evaluation = rows[0]

        # 2) Buscar dados do profissional avaliado
        employee = None
        employee_id = evaluation.get('employee_id')

        if employee_id:
            r_emp = (
                supabase
                .table('employees')
                .select(
                    'id, nome, cargo, empresa, company_name, branch_name, department_name, '
                    'manager_name, email, emailLider, employee_code, manager_code, '
                    'holding, business_line, nivel, cliente_id, holding_id, empresa_id, filial_id'
                )
                .eq('id', employee_id)
                .limit(1)
                .execute()
            )

            emp_rows = r_emp.data or []
            employee = emp_rows[0] if emp_rows else None

        return jsonify({
            'success': True,
            'evaluation': evaluation,
            'employee': employee
        }), 200

    except Exception as e:
        print('[api_get_evaluation_summary] erro:', e)
        return jsonify({
            'success': False,
            'error': 'evaluation_summary_failed',
            'detail': str(e)
        }), 500


@app.route('/api/evaluations/<int:evaluation_id>/readonly', methods=['GET', 'OPTIONS'])
def api_get_evaluation_readonly(evaluation_id):
    """
    Consulta a avaliação completa em modo leitura.
    Usado pela página de ciência do profissional para exibir critérios,
    ratings e comentários do gestor sem permitir edição.
    """
    if request.method == 'OPTIONS':
        return ('', 204)

    try:
        # 1) Buscar avaliação
        r_eval = (
            supabase
            .table('evaluations')


            
            .select(
                'id, employee_id, evaluator_id, evaluation_year, evaluation_date, status, '
                'final_rating, nine_box_position, performance_rating, potential_rating, '
                'round_code, cliente_id, empresa_id, filial_id, modelo_avaliacao_id, '
                'versao_modelo_id, ciclo_avaliacao_id, evaluation_origem_id, created_at, '
                'dimension_weights, dimension_averages, goals_average, metas_avg'
            )

            
            .eq('id', evaluation_id)
            .limit(1)
            .execute()
        )

        eval_rows = r_eval.data or []

        if not eval_rows:
            return jsonify({
                'success': False,
                'error': 'avaliacao_nao_encontrada',
                'message': 'Avaliação não encontrada.'
            }), 404

        evaluation = eval_rows[0]

        # 2) Buscar profissional
        employee = None
        employee_id = evaluation.get('employee_id')

        if employee_id:
            r_emp = (
                supabase
                .table('employees')
                .select(
                    'id, nome, cargo, empresa, company_name, branch_name, department_name, '
                    'manager_name, email, emailLider, employee_code, manager_code, '
                    'holding, business_line, nivel, cliente_id, holding_id, empresa_id, filial_id'
                )
                .eq('id', employee_id)
                .limit(1)
                .execute()
            )

            emp_rows = r_emp.data or []
            employee = emp_rows[0] if emp_rows else None

        # 3) Buscar workflow
        workflow = None

        r_wf = (
            supabase
            .table('evaluation_workflows')
            .select('*')
            .eq('evaluation_id', evaluation_id)
            .limit(1)
            .execute()
        )

        wf_rows = r_wf.data or []
        workflow = wf_rows[0] if wf_rows else None

        # 4) Buscar respostas da avaliação
        r_resp = (
            supabase
            .table('evaluation_responses')
            .select(
                'id, evaluation_id, criteria_id, rating, goal_id, manager_comment, '
                'peso_usado, eixo_9box_usado, afirmativa_avaliacao_id'
            )
            .eq('evaluation_id', evaluation_id)
            .order('id', desc=False)
            .execute()
        )

        responses = r_resp.data or []

        criteria_ids = [
            r.get('criteria_id')
            for r in responses
            if r.get('criteria_id') is not None
        ]

        # 5) Buscar critérios/afirmações
        criteria_by_id = {}

        if criteria_ids:
            r_criteria = (
                supabase
                .table('evaluation_criteria')
                .select('id, dimension, type, name, description, weight')
                .in_('id', criteria_ids)
                .execute()
            )

            for c in (r_criteria.data or []):
                criteria_by_id[c.get('id')] = c

        # 6) Montar leitura completa
        responses_readonly = []

        rating_map = {
            1: 'Excelente',
            2: 'Superou',
            3: 'Atendeu',
            4: 'Não Atendeu',
            5: 'Insuficiente'
        }

        for resp in responses:
            criteria_id = resp.get('criteria_id')
            crit = criteria_by_id.get(criteria_id) or {}

            rating = resp.get('rating')

            responses_readonly.append({
                'response_id': resp.get('id'),
                'criteria_id': criteria_id,
                'dimension': crit.get('dimension') or '-',
                'type': crit.get('type') or '-',
                'name': crit.get('name') or '',
                'description': crit.get('description') or '',
                'weight': crit.get('weight'),
                'rating': rating,
                'rating_label': rating_map.get(rating, ''),
                'manager_comment': resp.get('manager_comment') or '',
                'peso_usado': resp.get('peso_usado'),
                'eixo_9box_usado': resp.get('eixo_9box_usado')
            })



        # 7) Buscar metas individuais da avaliação
        goals_readonly = []

        r_goals = (
            supabase
            .table('individual_goals')
            .select(
                'id, evaluation_id, employee_id, round_code, goal_name, goal_description, '
                'weight, rating, rating_1_criteria, rating_2_criteria, rating_3_criteria, '
                'rating_4_criteria, rating_5_criteria, goal_origem_id'
            )
            .eq('evaluation_id', evaluation_id)
            .order('id', desc=False)
            .execute()
        )

        goals = r_goals.data or []

        for goal in goals:
            goal_rating = goal.get('rating')

            goals_readonly.append({
                'goal_id': goal.get('id'),
                'goal_name': goal.get('goal_name') or '',
                'goal_description': goal.get('goal_description') or '',
                'weight': goal.get('weight'),
                'rating': goal_rating,
                'rating_label': rating_map.get(goal_rating, ''),
                'rating_1_criteria': goal.get('rating_1_criteria') or '',
                'rating_2_criteria': goal.get('rating_2_criteria') or '',
                'rating_3_criteria': goal.get('rating_3_criteria') or '',
                'rating_4_criteria': goal.get('rating_4_criteria') or '',
                'rating_5_criteria': goal.get('rating_5_criteria') or '',
                'goal_origem_id': goal.get('goal_origem_id')
            })

        
        # 7) Agrupar por dimensão para facilitar o front
        dimensions = {}

        for item in responses_readonly:
            dim = item.get('dimension') or '-'

            if dim not in dimensions:
                dimensions[dim] = []

            dimensions[dim].append(item)

        calculation_summary = {
            'dimension_weights': evaluation.get('dimension_weights'),
            'dimension_averages': evaluation.get('dimension_averages'),
            'goals_average': evaluation.get('goals_average'),
            'metas_avg': evaluation.get('metas_avg'),
            'final_rating': evaluation.get('final_rating'),
            'performance_rating': evaluation.get('performance_rating'),
            'potential_rating': evaluation.get('potential_rating'),
            'nine_box_position': evaluation.get('nine_box_position')
        }

        return jsonify({
            'success': True,
            'evaluation': evaluation,
            'employee': employee,
            'workflow': workflow,
            'responses_readonly': responses_readonly,
            'dimensions': dimensions,
            'goals_readonly': goals_readonly,
            'calculation_summary': calculation_summary
        }), 200

    except Exception as e:
        print('[api_get_evaluation_readonly] erro:', e)
        return jsonify({
            'success': False,
            'error': 'evaluation_readonly_failed',
            'detail': str(e)
        }), 500


@app.route('/api/portal/user-access', methods=['GET', 'OPTIONS'])
def api_get_portal_user_access():
    """
    Consulta o acesso do usuario logado para montar o Portal LeaderTrack.
    Recebe o e-mail do usuario WordPress pela querystring.
    Exemplo:
    /api/portal/user-access?email=mar.ramosesteves@gmail.com
    """
    if request.method == 'OPTIONS':
        return ('', 204)

    try:
        email = (request.args.get('email') or '').strip().lower()

        cliente_id = (request.args.get('cliente_id') or '').strip()
        holding_id = (request.args.get('holding_id') or '').strip()
        empresa_id = (request.args.get('empresa_id') or '').strip()
        filial_id = (request.args.get('filial_id') or '').strip()

        if not email:
            return jsonify({
                'success': False,
                'error': 'email_obrigatorio',
                'message': 'Informe o e-mail do usuario.'
            }), 400

        r_access = (
            supabase
            .table('usuarios_acessos')
            .select(
                'id, user_id, wp_user_email, perfil, cliente_id, holding_id, empresa_id, filial_id, '
                'employee_id, manager_code, manager_name, '
                'pode_ver_desempenho, pode_ver_ninebox, pode_ver_metas, pode_ver_remuneracao, '
                'pode_ver_ppl, pode_ver_leadertrack, pode_ver_indice_lideranca, '
                'pode_ver_leadertrack_executivo, pode_administrar, '
                'pode_ver_comite_avaliacao, pode_ver_gestor_avaliacao, '
                'pode_ver_ciencia_avaliacao, status'
            )
            .eq('status', 'ativo')
            .execute()
        )

        all_rows = r_access.data or []

        rows = []

        for row in all_rows:
            row_email = str(row.get('wp_user_email') or '').strip().lower()

            if row_email != email:
                continue

            row_cliente_id = str(row.get('cliente_id') or '').strip()
            row_holding_id = str(row.get('holding_id') or '').strip()
            row_empresa_id = str(row.get('empresa_id') or '').strip()
            row_filial_id = str(row.get('filial_id') or '').strip()

            # Admin geral sem holding/empresa/filial pode aparecer como fallback.
            is_admin_fallback = (
                not row_holding_id
                and not row_empresa_id
                and not row_filial_id
                and bool(row.get('pode_administrar'))
            )

            contexto_ok = True

            if cliente_id and row_cliente_id and row_cliente_id != cliente_id:
                contexto_ok = False

            if holding_id and row_holding_id and row_holding_id != holding_id:
                contexto_ok = False

            if empresa_id and row_empresa_id and row_empresa_id != empresa_id:
                contexto_ok = False

            if filial_id and row_filial_id and row_filial_id != filial_id:
                contexto_ok = False

            if contexto_ok or is_admin_fallback:
                rows.append(row)

        if not rows:
            return jsonify({
                'success': False,
                'error': 'acesso_nao_encontrado',
                'message': 'Nenhum acesso ativo encontrado para este e-mail.',
                'email': email
            }), 404

        def access_score(row):
            score = 0

            if holding_id and str(row.get('holding_id') or '').strip() == holding_id:
                score += 10

            if empresa_id and str(row.get('empresa_id') or '').strip() == empresa_id:
                score += 5

            if filial_id and str(row.get('filial_id') or '').strip() == filial_id:
                score += 3

            if row.get('pode_administrar'):
                score += 1

            return score

        rows = sorted(rows, key=access_score, reverse=True)

        access = dict(rows[0])
        manager_identity = _resolve_operational_manager_identity(
            rows,
            cliente_id=cliente_id,
            holding_id=holding_id,
            empresa_id=empresa_id,
            filial_id=filial_id
        )

        if manager_identity:
            access['workflow_manager_name'] = manager_identity.get('manager_name')
            access['workflow_manager_email'] = manager_identity.get('manager_email')
            access['workflow_manager_code'] = manager_identity.get('manager_code')
            access['workflow_manager_source'] = manager_identity.get('source')

            if (
                (not str(access.get('manager_name') or '').strip())
                or _is_top_hierarchy_marker(access.get('manager_name'))
            ) and manager_identity.get('manager_name'):
                access['manager_name'] = manager_identity.get('manager_name')

            if (
                (not str(access.get('manager_code') or '').strip())
                or _is_top_hierarchy_marker(access.get('manager_code'))
            ) and manager_identity.get('manager_code'):
                access['manager_code'] = manager_identity.get('manager_code')

            if manager_identity.get('manager_email'):
                access['manager_email'] = manager_identity.get('manager_email')

        portal_cards = []

        if access.get('pode_ver_comite_avaliacao') or access.get('pode_administrar'):
            portal_cards.append({
                'key': 'comite_avaliacao',
                'title': 'Comite de Avaliacao',
                'description': 'Aprovar, devolver e acompanhar avaliacoes do ciclo.',
                'url': '/comite-de-avaliacao-de-desempenho/'
            })

        if access.get('pode_ver_gestor_avaliacao') or access.get('pode_administrar'):
            portal_cards.append({
                'key': 'gestor_avaliacao',
                'title': 'Minhas Avaliacoes como Gestor',
                'description': 'Acompanhar sua equipe, enviar ao comite e registrar feedback.',
                'url': '/minhas-avaliacoes-de-desempenho-gestor/'
            })

        if access.get('pode_ver_ciencia_avaliacao') or access.get('pode_administrar'):
            portal_cards.append({
                'key': 'ciencia_avaliacao',
                'title': 'Minha Avaliacao',
                'description': 'Consultar a avaliacao completa e registrar ciencia.',
                'url': '/ciencia-da-avaliacao-de-desempenho/'
            })

        return jsonify({
            'success': True,
            'email': email,
            'access': access,
            'portal_cards': portal_cards
        }), 200

    except Exception as e:
        print('[api_get_portal_user_access] erro:', e)
        return jsonify({
            'success': False,
            'error': 'portal_user_access_failed',
            'detail': str(e)
        }), 500


def _is_top_hierarchy_marker(value):
    return str(value or '').strip().upper() == 'GOD'


def _resolve_operational_manager_identity(access_rows, cliente_id='', holding_id='', empresa_id='', filial_id=''):
    """
    Resolve a identidade operacional do gestor.

    Importante:
    - usuarios_acessos.manager_name / manager_code representam para quem o usuario responde
      e podem trazer marcadores como GOD.
    - para o workflow do gestor, precisamos da identidade do proprio gestor
      (nome / email / codigo do colaborador), para localizar sua equipe.
    """
    access_rows = access_rows or []

    if not access_rows:
        return {}

    def _score_access_row(row):
        score = 0

        if row.get('pode_ver_gestor_avaliacao'):
            score += 20

        if row.get('employee_id') is not None:
            score += 5

        if holding_id and str(row.get('holding_id') or '').strip() == holding_id:
            score += 10

        if empresa_id and str(row.get('empresa_id') or '').strip() == empresa_id:
            score += 5

        if filial_id and str(row.get('filial_id') or '').strip() == filial_id:
            score += 3

        if row.get('pode_administrar'):
            score += 1

        return score

    sorted_rows = sorted(access_rows, key=_score_access_row, reverse=True)

    employee_ids = []
    seen_ids = set()

    for row in sorted_rows:
        employee_id = row.get('employee_id')

        if employee_id is None:
            continue

        employee_id_str = str(employee_id).strip()

        if not employee_id_str or employee_id_str in seen_ids:
            continue

        seen_ids.add(employee_id_str)
        employee_ids.append(employee_id)

    employees_by_id = {}

    if employee_ids:
        try:
            r_emp = (
                supabase
                .table('employees')
                .select('id, nome, email, employee_code, cliente_id, holding_id, empresa_id, filial_id')
                .in_('id', employee_ids)
                .execute()
            )

            employees_by_id = {
                emp.get('id'): emp
                for emp in (r_emp.data or [])
                if emp.get('id') is not None
            }
        except Exception as e:
            print('[resolve_operational_manager_identity] erro ao buscar employees:', e)

    for row in sorted_rows:
        emp = employees_by_id.get(row.get('employee_id')) or {}

        manager_name = str(emp.get('nome') or '').strip()
        manager_email = str(emp.get('email') or '').strip().lower()
        manager_code = str(emp.get('employee_code') or '').strip()

        if manager_name or manager_email or manager_code:
            return {
                'manager_name': manager_name or None,
                'manager_email': manager_email or None,
                'manager_code': manager_code or None,
                'source': 'employee'
            }

    # Fallback defensivo: usa os campos do acesso somente quando nao sao marcadores de topo.
    for row in sorted_rows:
        manager_name = str(row.get('manager_name') or '').strip()
        manager_code = str(row.get('manager_code') or '').strip()

        if manager_name and not _is_top_hierarchy_marker(manager_name):
            return {
                'manager_name': manager_name,
                'manager_email': None,
                'manager_code': manager_code or None,
                'source': 'access'
            }

        if manager_code and not _is_top_hierarchy_marker(manager_code):
            return {
                'manager_name': None,
                'manager_email': None,
                'manager_code': manager_code,
                'source': 'access'
            }

    return {}



# ===================== Workflow de Avaliação de Desempenho =====================

def _is_demo_workflow_test_request():
    origin = str(request.headers.get('Origin') or '').strip().lower()
    trusted_origin = 'gestor.thehrkey.tech' in origin

    # O reset continua seguro porque:
    # 1) exige usuario com permissao de comite/admin no contexto esperado
    # 2) remove apenas registros marcados como demo
    # 3) recria somente o kit fake controlado
    # Por isso, aqui validamos o dominio de origem em vez de depender do Referer,
    # que pode vir vazio ou truncado em alguns cenarios do navegador.
    return trusted_origin


def _workflow_include_demo_rows():
    value = str(request.args.get('include_demo') or '').strip().lower()
    if value in {'1', 'true', 'sim', 'yes'}:
        return True

    referer = str(request.headers.get('Referer') or '').strip().lower()
    return '/teste/' in referer


def _is_demo_workflow_row(workflow_row):
    if not workflow_row:
        return False

    marker = str(workflow_row.get('committee_comment') or '').strip()
    return marker in DEMO_WORKFLOW_MARKERS


def _demo_workflow_status_sequence(final_status):
    sequence_map = {
        'enviada_ao_comite': ['enviada_ao_comite'],
        'em_calibracao_no_comite': ['enviada_ao_comite', 'em_calibracao_no_comite'],
        'aprovada_pelo_comite': ['enviada_ao_comite', 'em_calibracao_no_comite', 'aprovada_pelo_comite'],
        'devolvida_ao_gestor': ['enviada_ao_comite', 'em_calibracao_no_comite', 'devolvida_ao_gestor'],
        'feedback_realizado': ['enviada_ao_comite', 'em_calibracao_no_comite', 'aprovada_pelo_comite', 'feedback_realizado'],
        'ciencia_do_profissional': ['enviada_ao_comite', 'em_calibracao_no_comite', 'aprovada_pelo_comite', 'feedback_realizado', 'ciencia_do_profissional']
    }
    return sequence_map.get(final_status, ['enviada_ao_comite'])


def _build_demo_workflow_row(case_data, employee_row, evaluation_row, actor_email):
    now_iso = datetime.now(timezone.utc).isoformat()
    sequence = _demo_workflow_status_sequence(case_data.get('workflow_status'))
    final_status = sequence[-1]

    workflow_row = {
        'evaluation_id': evaluation_row.get('id'),
        'employee_id': employee_row.get('id'),
        'manager_name': employee_row.get('manager_name') or '',
        'round_code': evaluation_row.get('round_code'),
        'status_workflow': final_status,
        'submitted_by_manager_at': now_iso,
        'submitted_by_manager_by': actor_email,
        'committee_status': None,
        'committee_validated_at': None,
        'committee_validated_by': None,
        'committee_comment': DEMO_WORKFLOW_MARKER,
        'feedback_done_at': None,
        'feedback_done_by': None,
        'feedback_comment': None,
        'employee_acknowledged_at': None,
        'employee_acknowledgement_status': None,
        'employee_comment': None,
        'updated_at': now_iso
    }

    if 'em_calibracao_no_comite' in sequence:
        workflow_row['committee_status'] = 'em_calibracao'
        workflow_row['committee_validated_at'] = now_iso
        workflow_row['committee_validated_by'] = actor_email

    if 'aprovada_pelo_comite' in sequence:
        workflow_row['committee_status'] = 'calibrado'
        workflow_row['committee_validated_at'] = now_iso
        workflow_row['committee_validated_by'] = actor_email

    if final_status == 'devolvida_ao_gestor':
        workflow_row['committee_status'] = 'devolvida'

    if 'feedback_realizado' in sequence:
        workflow_row['feedback_done_at'] = now_iso
        workflow_row['feedback_done_by'] = actor_email
        workflow_row['feedback_comment'] = 'Kit demo: feedback registrado automaticamente.'

    if 'ciencia_do_profissional' in sequence:
        workflow_row['employee_acknowledged_at'] = now_iso
        workflow_row['employee_acknowledgement_status'] = 'de_acordo'
        workflow_row['employee_comment'] = 'Kit demo: ciencia registrada automaticamente.'

    return workflow_row


def _build_demo_log_rows(workflow_row, actor_email):
    sequence = _demo_workflow_status_sequence(workflow_row.get('status_workflow'))
    logs = []
    previous_status = None

    for status in sequence:
        action_role = 'gestor'
        action_comment = 'Kit demo do workflow recriado automaticamente.'

        if status in ['em_calibracao_no_comite', 'aprovada_pelo_comite', 'devolvida_ao_gestor']:
            action_role = 'comite'

        if status == 'feedback_realizado':
            action_role = 'gestor'
            action_comment = 'Kit demo: feedback registrado automaticamente.'

        if status == 'ciencia_do_profissional':
            action_role = 'profissional'
            action_comment = 'Kit demo: ciencia registrada automaticamente.'

        logs.append({
            'workflow_id': workflow_row.get('id'),
            'evaluation_id': workflow_row.get('evaluation_id'),
            'from_status': previous_status,
            'to_status': status,
            'action_by': actor_email,
            'action_role': action_role,
            'action_comment': action_comment
        })
        previous_status = status

    return logs


@app.route('/api/workflow/demo/reset', methods=['POST', 'OPTIONS'])
def api_reset_workflow_demo_kit():
    """
    Recria um kit fixo de avaliacoes demo para o workflow.

    Salvaguardas:
    - so funciona a partir do /teste/
    - exige confirmacao explicita
    - so remove registros de demo marcados pelo kit atual
    - tambem aceita limpar o conjunto legado de IDs fake conhecidos
    """
    if request.method == 'OPTIONS':
        return ('', 204)

    try:
        if not _is_demo_workflow_test_request():
            return jsonify({
                'success': False,
                'error': 'demo_reset_bloqueado',
                'message': 'O reset do kit demo so pode ser executado a partir do ambiente de teste.'
            }), 403

        payload = request.get_json(silent=True) or {}
        user_email = str(payload.get('user_email') or '').strip().lower()
        confirm_text = str(payload.get('confirm_text') or '').strip()

        if not user_email:
            return jsonify({
                'success': False,
                'error': 'user_email_obrigatorio',
                'message': 'Informe o e-mail do usuario para resetar o kit demo.'
            }), 400

        if confirm_text != DEMO_WORKFLOW_RESET_CONFIRM:
            return jsonify({
                'success': False,
                'error': 'confirmacao_invalida',
                'message': 'Confirme digitando exatamente RESET KIT DEMO.'
            }), 400

        q_access = (
            supabase
            .table('usuarios_acessos')
            .select(
                'id, wp_user_email, cliente_id, holding_id, empresa_id, filial_id, '
                'pode_ver_comite_avaliacao, pode_administrar, status'
            )
            .eq('status', 'ativo')
            .eq('wp_user_email', user_email)
            .execute()
        )

        access_rows = q_access.data or []
        acesso_ok = False

        for row in access_rows:
            row_cliente_id = str(row.get('cliente_id') or '').strip()
            row_holding_id = str(row.get('holding_id') or '').strip()
            row_empresa_id = str(row.get('empresa_id') or '').strip()
            row_filial_id = str(row.get('filial_id') or '').strip()

            is_expected_scope = (
                row_cliente_id == DEMO_WORKFLOW_CLIENTE_ID and
                (not row_holding_id or row_holding_id == DEMO_WORKFLOW_HOLDING_ID) and
                not row_empresa_id and
                not row_filial_id
            )

            if is_expected_scope and (row.get('pode_ver_comite_avaliacao') or row.get('pode_administrar')):
                acesso_ok = True
                break

        if not acesso_ok:
            return jsonify({
                'success': False,
                'error': 'acesso_demo_negado',
                'message': 'Seu usuario nao tem permissao de comite no contexto de teste para resetar o kit demo.'
            }), 403

        employee_ids = [case['employee_id'] for case in DEMO_WORKFLOW_EMPLOYEE_CASES]

        q_existing_evals = (
            supabase
            .table('evaluations')
            .select('id, employee_id, round_code, dimension_weights, dimension_averages')
            .eq('round_code', 'YE2026')
            .in_('employee_id', employee_ids)
            .execute()
        )

        existing_demo_evaluation_ids = []

        for row in (q_existing_evals.data or []):
            dimension_weights = row.get('dimension_weights') or {}
            dimension_averages = row.get('dimension_averages') or {}

            if (
                dimension_weights.get('demo_marker') == DEMO_WORKFLOW_MARKER
                or dimension_averages.get('demo_marker') == DEMO_WORKFLOW_MARKER
                or row.get('id') in LEGACY_DEMO_WORKFLOW_EVALUATION_IDS
            ):
                existing_demo_evaluation_ids.append(row.get('id'))

        existing_demo_evaluation_ids = sorted(set(
            [evaluation_id for evaluation_id in existing_demo_evaluation_ids if evaluation_id is not None]
        ))

        if existing_demo_evaluation_ids:
            try:
                supabase.table('evaluation_workflow_logs').delete().in_('evaluation_id', existing_demo_evaluation_ids).execute()
            except Exception as e:
                print('[api_reset_workflow_demo_kit] aviso ao limpar logs:', e)

            try:
                supabase.table('evaluation_workflows').delete().in_('evaluation_id', existing_demo_evaluation_ids).execute()
            except Exception as e:
                print('[api_reset_workflow_demo_kit] aviso ao limpar workflows:', e)

            try:
                supabase.table('evaluations').delete().in_('id', existing_demo_evaluation_ids).execute()
            except Exception as e:
                print('[api_reset_workflow_demo_kit] aviso ao limpar evaluations:', e)

        q_employees = (
            supabase
            .table('employees')
            .select(
                'id, nome, cargo, email, manager_name, company_name, branch_name, department_name, '
                'cliente_id, holding_id, empresa_id, filial_id'
            )
            .in_('id', employee_ids)
            .execute()
        )

        employees_by_id = {
            row.get('id'): row
            for row in (q_employees.data or [])
            if row.get('id') is not None
        }

        missing_employee_ids = [
            employee_id for employee_id in employee_ids
            if employee_id not in employees_by_id
        ]

        if missing_employee_ids:
            return jsonify({
                'success': False,
                'error': 'demo_employees_nao_encontrados',
                'message': 'Alguns profissionais do kit demo nao foram encontrados.',
                'employee_ids': missing_employee_ids
            }), 400

        created_items = []
        actor_email = user_email
        now_iso = datetime.now(timezone.utc).isoformat()

        for case_data in DEMO_WORKFLOW_EMPLOYEE_CASES:
            employee_row = employees_by_id.get(case_data['employee_id'])

            evaluation_insert = {
                'employee_id': employee_row.get('id'),
                'evaluator_id': 1,
                'evaluation_year': 2026,
                'evaluation_date': datetime.now(timezone.utc).date().isoformat(),
                'status': 'draft',
                'final_rating': case_data.get('final_rating'),
                'nine_box_position': case_data.get('nine_box_position'),
                'performance_rating': case_data.get('performance_rating'),
                'potential_rating': case_data.get('potential_rating'),
                'dimension_weights': {
                    'demo_marker': DEMO_WORKFLOW_MARKER,
                    'demo_type': 'workflow_kit',
                    'demo_reset_at': now_iso
                },
                'dimension_averages': {
                    'demo_marker': DEMO_WORKFLOW_MARKER,
                    'employee_name': employee_row.get('nome')
                },
                'round_code': 'YE2026',
                'cliente_id': employee_row.get('cliente_id') or DEMO_WORKFLOW_CLIENTE_ID,
                'empresa_id': employee_row.get('empresa_id'),
                'filial_id': employee_row.get('filial_id')
            }

            r_eval = (
                supabase
                .table('evaluations')
                .insert(evaluation_insert)
                .execute()
            )

            evaluation_rows = r_eval.data or []
            evaluation_row = evaluation_rows[0] if evaluation_rows else None

            if not evaluation_row:
                raise ValueError(f'Falha ao criar avaliacao demo para employee_id={employee_row.get("id")}')

            workflow_insert = _build_demo_workflow_row(case_data, employee_row, evaluation_row, actor_email)

            r_workflow = (
                supabase
                .table('evaluation_workflows')
                .insert(workflow_insert)
                .execute()
            )

            workflow_rows = r_workflow.data or []
            workflow_row = workflow_rows[0] if workflow_rows else workflow_insert

            log_rows = _build_demo_log_rows(workflow_row, actor_email)
            if log_rows:
                supabase.table('evaluation_workflow_logs').insert(log_rows).execute()

            created_items.append({
                'evaluation_id': evaluation_row.get('id'),
                'employee_id': employee_row.get('id'),
                'employee_name': employee_row.get('nome'),
                'manager_name': employee_row.get('manager_name'),
                'workflow_status': workflow_row.get('status_workflow')
            })

        return jsonify({
            'success': True,
            'message': 'Kit demo do workflow recriado com sucesso no ambiente de teste.',
            'deleted_evaluation_ids': existing_demo_evaluation_ids,
            'created_items': created_items,
            'marker': DEMO_WORKFLOW_MARKER
        }), 200

    except Exception as e:
        print('[api_reset_workflow_demo_kit] erro:', e)
        return jsonify({
            'success': False,
            'error': 'workflow_demo_reset_failed',
            'detail': str(e)
        }), 500


@app.route('/api/evaluations/<int:evaluation_id>/workflow/submit-manager', methods=['POST', 'OPTIONS'])
def api_workflow_submit_manager(evaluation_id):
    """
    Gestor finaliza a avaliação e envia para o comitê de avaliação de desempenho.

    Status gerado:
      enviada_ao_comite
    """
    if request.method == 'OPTIONS':
        return ('', 204)

    try:
        payload = request.get_json(silent=True) or {}

        action_by = (
            payload.get('action_by')
            or payload.get('user_email')
            or payload.get('manager_name')
            or 'gestor'
        )

        action_comment = (
            payload.get('comment')
            or payload.get('action_comment')
            or ''
        )

        # 1) Buscar avaliação
        r_eval = (
            supabase
            .table('evaluations')
            .select('*')
            .eq('id', evaluation_id)
            .limit(1)
            .execute()
        )

        eval_rows = r_eval.data or []

        if not eval_rows:
            return jsonify({
                'error': 'avaliacao_nao_encontrada',
                'message': 'Avaliação não encontrada para iniciar workflow.'
            }), 404

        ev = eval_rows[0]

        employee_id = ev.get('employee_id')
        manager_name = ev.get('manager_name') or payload.get('manager_name') or ''
        round_code = ev.get('round_code') or payload.get('round_code') or ''


        # Workflow formal permitido somente para avaliações Year End (YE)
        round_code_normalized = str(round_code or '').strip().upper()

        if not round_code_normalized.startswith('YE'):
            return jsonify({
                'error': 'workflow_apenas_year_end',
                'message': 'O workflow formal de comitê está disponível somente para avaliações Year End (YE).',
                'round_code': round_code
            }), 400



        

        # 2) Verificar workflow anterior, se existir
        r_prev = (
            supabase
            .table('evaluation_workflows')
            .select('*')
            .eq('evaluation_id', evaluation_id)
            .limit(1)
            .execute()
        )

        prev_rows = r_prev.data or []
        prev_workflow = prev_rows[0] if prev_rows else None
        from_status = prev_workflow.get('status_workflow') if prev_workflow else None

        # 3) Criar/atualizar workflow
        workflow_row = {
            'evaluation_id': evaluation_id,
            'employee_id': employee_id,
            'manager_name': manager_name,
            'round_code': round_code,
            'status_workflow': 'enviada_ao_comite',
            'submitted_by_manager_at': datetime.now(timezone.utc).isoformat(),
            'submitted_by_manager_by': str(action_by),
            'updated_at': datetime.now(timezone.utc).isoformat()
        }

        r_workflow = (
            supabase
            .table('evaluation_workflows')
            .upsert(workflow_row, on_conflict='evaluation_id')
            .execute()
        )

        workflow_data = r_workflow.data or []
        workflow = workflow_data[0] if workflow_data else workflow_row
        workflow_id = workflow.get('id') if isinstance(workflow, dict) else None

        # 4) Registrar log
        log_row = {
            'workflow_id': workflow_id,
            'evaluation_id': evaluation_id,
            'from_status': from_status,
            'to_status': 'enviada_ao_comite',
            'action_by': str(action_by),
            'action_role': 'gestor',
            'action_comment': str(action_comment)
        }

        supabase.table('evaluation_workflow_logs').insert(log_row).execute()

        return jsonify({
            'success': True,
            'message': 'Avaliação enviada ao comitê com sucesso.',
            'workflow': workflow
        }), 200

    except Exception as e:
        print('[api_workflow_submit_manager] erro:', e)
        return jsonify({
            'error': 'workflow_submit_manager_failed',
            'detail': str(e)
        }), 500


@app.route('/api/evaluations/<int:evaluation_id>/workflow/committee-approve', methods=['POST', 'OPTIONS'])
def api_workflow_committee_approve(evaluation_id):
    """
    Comitê valida a avaliação de desempenho e envia para a etapa de calibração.

    Status gerado:
      em_calibracao_no_comite
    """
    if request.method == 'OPTIONS':
        return ('', 204)

    try:
        payload = request.get_json(silent=True) or {}
        user_email = str(payload.get('user_email') or '').strip().lower()


        if not user_email:
            return jsonify({
                'success': False,
                'error': 'user_email_obrigatorio',
                'message': 'Informe user_email para aprovar avaliacao no comite.'
            }), 400


        r_eval_contexto = (
            supabase
            .table('evaluations')
            .select('id, employee_id, cliente_id, empresa_id, filial_id, round_code')
            .eq('id', evaluation_id)
            .limit(1)
            .execute()
        )

        eval_rows_contexto = r_eval_contexto.data or []

        if not eval_rows_contexto:
            return jsonify({
                'success': False,
                'error': 'avaliacao_nao_encontrada',
                'message': 'Avaliacao nao encontrada para validacao do comite.'
            }), 404

        eval_contexto = eval_rows_contexto[0]

        r_employee_contexto = (
            supabase
            .table('employees')
            .select('id, holding_id, empresa_id, filial_id')
            .eq('id', eval_contexto.get('employee_id'))
            .limit(1)
            .execute()
        )

        employee_rows_contexto = r_employee_contexto.data or []
        employee_contexto = employee_rows_contexto[0] if employee_rows_contexto else {}

        eval_cliente_id = str(eval_contexto.get('cliente_id') or '').strip()
        eval_holding_id = str(employee_contexto.get('holding_id') or '').strip()
        eval_empresa_id = str(eval_contexto.get('empresa_id') or employee_contexto.get('empresa_id') or '').strip()
        eval_filial_id = str(eval_contexto.get('filial_id') or employee_contexto.get('filial_id') or '').strip()


        q_access_comite = (
            supabase
            .table('usuarios_acessos')
            .select(
                'id, wp_user_email, perfil, cliente_id, holding_id, empresa_id, filial_id, '
                'pode_ver_comite_avaliacao, pode_administrar, status'
            )
            .eq('status', 'ativo')
            .execute()
        )

        access_rows_comite = q_access_comite.data or []
        acesso_approve_ok = False


        for access_row in access_rows_comite:
            row_email = str(access_row.get('wp_user_email') or '').strip().lower()

            if row_email != user_email:
                continue

            row_cliente_id = str(access_row.get('cliente_id') or '').strip()
            row_holding_id = str(access_row.get('holding_id') or '').strip()
            row_empresa_id = str(access_row.get('empresa_id') or '').strip()
            row_filial_id = str(access_row.get('filial_id') or '').strip()

            contexto_ok = True

            if eval_cliente_id and row_cliente_id and row_cliente_id != eval_cliente_id:
                contexto_ok = False

            if eval_holding_id and row_holding_id and row_holding_id != eval_holding_id:
                contexto_ok = False

            if eval_empresa_id and row_empresa_id and row_empresa_id != eval_empresa_id:
                contexto_ok = False

            if eval_filial_id and row_filial_id and row_filial_id != eval_filial_id:
                contexto_ok = False

            is_admin_fallback = (
                not row_holding_id
                and not row_empresa_id
                and not row_filial_id
                and bool(access_row.get('pode_administrar'))
            )

            pode_comite = bool(access_row.get('pode_ver_comite_avaliacao'))
            pode_admin = bool(access_row.get('pode_administrar'))

            if (contexto_ok or is_admin_fallback) and (pode_comite or pode_admin):
                acesso_approve_ok = True
                break

        if not acesso_approve_ok:
            return jsonify({
                'success': False,
                'error': 'acesso_comite_negado',
                'message': 'Usuario sem permissao para aprovar avaliacao no comite.'
            }), 403
        

        action_by = (
            payload.get('action_by')
            or payload.get('user_email')
            or payload.get('committee_user')
            or 'comite'
        )

        action_comment = (
            payload.get('comment')
            or payload.get('action_comment')
            or payload.get('committee_comment')
            or ''
        )

        # 1) Buscar workflow existente
        r_prev = (
            supabase
            .table('evaluation_workflows')
            .select('*')
            .eq('evaluation_id', evaluation_id)
            .limit(1)
            .execute()
        )

        prev_rows = r_prev.data or []

        if not prev_rows:
            return jsonify({
                'error': 'workflow_nao_encontrado',
                'message': 'Workflow não encontrado. A avaliação precisa ser enviada ao comitê antes da aprovação.'
            }), 404

        prev_workflow = prev_rows[0]
        workflow_id = prev_workflow.get('id')
        from_status = prev_workflow.get('status_workflow')

        if from_status != 'enviada_ao_comite':
            return jsonify({
                'success': False,
                'error': 'status_invalido',
                'message': 'A aprovação inicial do comitê só pode ocorrer quando a avaliação estiver enviada ao comitê.',
                'status_atual': from_status
            }), 400

        # 2) Atualizar workflow
        update_row = {
            'status_workflow': 'em_calibracao_no_comite',
            'committee_status': 'em_calibracao',
            'committee_validated_at': datetime.now(timezone.utc).isoformat(),
            'committee_validated_by': str(action_by),
            'committee_comment': str(action_comment),
            'updated_at': datetime.now(timezone.utc).isoformat()
        }

        r_update = (
            supabase
            .table('evaluation_workflows')
            .update(update_row)
            .eq('evaluation_id', evaluation_id)
            .execute()
        )

        workflow_data = r_update.data or []
        workflow = workflow_data[0] if workflow_data else {
            **prev_workflow,
            **update_row
        }

        # 3) Registrar log
        log_row = {
            'workflow_id': workflow_id,
            'evaluation_id': evaluation_id,
            'from_status': from_status,
            'to_status': 'em_calibracao_no_comite',
            'action_by': str(action_by),
            'action_role': 'comite',
            'action_comment': str(action_comment)
        }

        supabase.table('evaluation_workflow_logs').insert(log_row).execute()

        return jsonify({
            'success': True,
            'message': 'Avaliação aprovada na análise inicial e enviada para calibração do comitê.',
            'workflow': workflow
        }), 200

    except Exception as e:
        print('[api_workflow_committee_approve] erro:', e)
        return jsonify({
            'error': 'workflow_committee_approve_failed',
            'detail': str(e)
        }), 500


@app.route('/api/evaluations/<int:evaluation_id>/workflow/committee-return', methods=['POST', 'OPTIONS'])
def api_workflow_committee_return(evaluation_id):
    """
    Comitê devolve a avaliação ao gestor para ajustes.
    O comentário é obrigatório, pois representa a justificativa da decisão do comitê.
    """
    if request.method == 'OPTIONS':
        return ('', 204)

    try:
        payload = request.get_json(silent=True) or {}
        user_email = str(payload.get('user_email') or '').strip().lower()

        if not user_email:
            return jsonify({
                'success': False,
                'error': 'user_email_obrigatorio',
                'message': 'Informe user_email para devolver avaliacao no comite.'
            }), 400


        r_eval_contexto = (
            supabase
            .table('evaluations')
            .select('id, employee_id, cliente_id, empresa_id, filial_id, round_code')
            .eq('id', evaluation_id)
            .limit(1)
            .execute()
        )

        eval_rows_contexto = r_eval_contexto.data or []

        if not eval_rows_contexto:
            return jsonify({
                'success': False,
                'error': 'avaliacao_nao_encontrada',
                'message': 'Avaliacao nao encontrada para validacao do comite.'
            }), 404

        eval_contexto = eval_rows_contexto[0]


        r_employee_contexto = (
            supabase
            .table('employees')
            .select('id, holding_id, empresa_id, filial_id')
            .eq('id', eval_contexto.get('employee_id'))
            .limit(1)
            .execute()
        )

        employee_rows_contexto = r_employee_contexto.data or []
        employee_contexto = employee_rows_contexto[0] if employee_rows_contexto else {}

        eval_cliente_id = str(eval_contexto.get('cliente_id') or '').strip()
        eval_holding_id = str(employee_contexto.get('holding_id') or '').strip()
        eval_empresa_id = str(eval_contexto.get('empresa_id') or employee_contexto.get('empresa_id') or '').strip()
        eval_filial_id = str(eval_contexto.get('filial_id') or employee_contexto.get('filial_id') or '').strip()


        q_access_comite = (
            supabase
            .table('usuarios_acessos')
            .select(
                'id, wp_user_email, perfil, cliente_id, holding_id, empresa_id, filial_id, '
                'pode_ver_comite_avaliacao, pode_administrar, status'
            )
            .eq('status', 'ativo')
            .execute()
        )

        access_rows_comite = q_access_comite.data or []
        acesso_return_ok = False



        for access_row in access_rows_comite:
            row_email = str(access_row.get('wp_user_email') or '').strip().lower()

            if row_email != user_email:
                continue

            row_cliente_id = str(access_row.get('cliente_id') or '').strip()
            row_holding_id = str(access_row.get('holding_id') or '').strip()
            row_empresa_id = str(access_row.get('empresa_id') or '').strip()
            row_filial_id = str(access_row.get('filial_id') or '').strip()

            contexto_ok = True

            if eval_cliente_id and row_cliente_id and row_cliente_id != eval_cliente_id:
                contexto_ok = False

            if eval_holding_id and row_holding_id and row_holding_id != eval_holding_id:
                contexto_ok = False

            if eval_empresa_id and row_empresa_id and row_empresa_id != eval_empresa_id:
                contexto_ok = False

            if eval_filial_id and row_filial_id and row_filial_id != eval_filial_id:
                contexto_ok = False

            is_admin_fallback = (
                not row_holding_id
                and not row_empresa_id
                and not row_filial_id
                and bool(access_row.get('pode_administrar'))
            )

            pode_comite = bool(access_row.get('pode_ver_comite_avaliacao'))
            pode_admin = bool(access_row.get('pode_administrar'))

            if (contexto_ok or is_admin_fallback) and (pode_comite or pode_admin):
                acesso_return_ok = True
                break

        if not acesso_return_ok:
            return jsonify({
                'success': False,
                'error': 'acesso_comite_negado',
                'message': 'Usuario sem permissao para devolver avaliacao no comite.'
            }), 403
        

        action_by = (
            payload.get('action_by')
            or payload.get('user_email')
            or payload.get('committee_user')
            or 'comite'
        )

        comment = (
            payload.get('comment')
            or payload.get('committee_comment')
            or ''
        ).strip()

        if not comment:
            return jsonify({
                'success': False,
                'error': 'comentario_obrigatorio',
                'message': 'Informe uma justificativa para devolver a avaliação ao gestor.'
            }), 400

        # Buscar workflow existente
        r_wf = (
            supabase
            .table('evaluation_workflows')
            .select('*')
            .eq('evaluation_id', evaluation_id)
            .limit(1)
            .execute()
        )

        wf_rows = r_wf.data or []

        if not wf_rows:
            return jsonify({
                'success': False,
                'error': 'workflow_nao_encontrado',
                'message': 'Workflow não encontrado para esta avaliação.'
            }), 404

        workflow = wf_rows[0]
        workflow_id = workflow.get('id')
        from_status = workflow.get('status_workflow')

        if from_status not in ['enviada_ao_comite', 'em_calibracao_no_comite']:
            return jsonify({
                'success': False,
                'error': 'status_invalido',
                'message': 'A avaliação só pode ser devolvida ao gestor quando estiver em análise ou calibração no comitê.',
                'status_atual': from_status
            }), 400

        now_iso = datetime.utcnow().isoformat()

        update_payload = {
            'status_workflow': 'devolvida_ao_gestor',
            'committee_status': 'devolvida',
            'committee_validated_at': now_iso,
            'committee_validated_by': action_by,
            'committee_comment': comment,
            'updated_at': now_iso
        }

        r_update = (
            supabase
            .table('evaluation_workflows')
            .update(update_payload)
            .eq('id', workflow_id)
            .execute()
        )

        updated_rows = r_update.data or []

        # Registrar log
        log_payload = {
            'workflow_id': workflow_id,
            'evaluation_id': evaluation_id,
            'from_status': from_status,
            'to_status': 'devolvida_ao_gestor',
            'action_by': action_by,
            'action_role': 'comite',
            'action_comment': comment
        }

        supabase.table('evaluation_workflow_logs').insert(log_payload).execute()

        return jsonify({
            'success': True,
            'message': 'Avaliação devolvida ao gestor com justificativa do comitê.',
            'workflow': updated_rows[0] if updated_rows else None
        }), 200

    except Exception as e:
        print('[api_workflow_committee_return] erro:', e)
        return jsonify({
            'success': False,
            'error': 'committee_return_failed',
            'detail': str(e)
        }), 500


@app.route('/api/evaluations/<int:evaluation_id>/workflow/committee-finish-calibration', methods=['POST', 'OPTIONS'])
def api_workflow_committee_finish_calibration(evaluation_id):
    """
    Comitê conclui a calibração e libera a avaliação para o gestor registrar o feedback.

    Status gerado:
      aprovada_pelo_comite
    """
    if request.method == 'OPTIONS':
        return ('', 204)

    try:
        payload = request.get_json(silent=True) or {}
        user_email = str(payload.get('user_email') or '').strip().lower()

        if not user_email:
            return jsonify({
                'success': False,
                'error': 'user_email_obrigatorio',
                'message': 'Informe user_email para concluir a calibração da avaliação.'
            }), 400

        r_eval_contexto = (
            supabase
            .table('evaluations')
            .select('id, employee_id, cliente_id, empresa_id, filial_id, round_code')
            .eq('id', evaluation_id)
            .limit(1)
            .execute()
        )

        eval_rows_contexto = r_eval_contexto.data or []

        if not eval_rows_contexto:
            return jsonify({
                'success': False,
                'error': 'avaliacao_nao_encontrada',
                'message': 'Avaliacao nao encontrada para concluir a calibracao.'
            }), 404

        eval_contexto = eval_rows_contexto[0]

        r_employee_contexto = (
            supabase
            .table('employees')
            .select('id, holding_id, empresa_id, filial_id')
            .eq('id', eval_contexto.get('employee_id'))
            .limit(1)
            .execute()
        )

        employee_rows_contexto = r_employee_contexto.data or []
        employee_contexto = employee_rows_contexto[0] if employee_rows_contexto else {}

        eval_cliente_id = str(eval_contexto.get('cliente_id') or '').strip()
        eval_holding_id = str(employee_contexto.get('holding_id') or '').strip()
        eval_empresa_id = str(eval_contexto.get('empresa_id') or employee_contexto.get('empresa_id') or '').strip()
        eval_filial_id = str(eval_contexto.get('filial_id') or employee_contexto.get('filial_id') or '').strip()

        q_access_comite = (
            supabase
            .table('usuarios_acessos')
            .select(
                'id, wp_user_email, perfil, cliente_id, holding_id, empresa_id, filial_id, '
                'pode_ver_comite_avaliacao, pode_administrar, status'
            )
            .eq('status', 'ativo')
            .execute()
        )

        access_rows_comite = q_access_comite.data or []
        acesso_calibracao_ok = False

        for access_row in access_rows_comite:
            row_email = str(access_row.get('wp_user_email') or '').strip().lower()

            if row_email != user_email:
                continue

            row_cliente_id = str(access_row.get('cliente_id') or '').strip()
            row_holding_id = str(access_row.get('holding_id') or '').strip()
            row_empresa_id = str(access_row.get('empresa_id') or '').strip()
            row_filial_id = str(access_row.get('filial_id') or '').strip()

            contexto_ok = True

            if eval_cliente_id and row_cliente_id and row_cliente_id != eval_cliente_id:
                contexto_ok = False

            if eval_holding_id and row_holding_id and row_holding_id != eval_holding_id:
                contexto_ok = False

            if eval_empresa_id and row_empresa_id and row_empresa_id != eval_empresa_id:
                contexto_ok = False

            if eval_filial_id and row_filial_id and row_filial_id != eval_filial_id:
                contexto_ok = False

            is_admin_fallback = (
                not row_holding_id
                and not row_empresa_id
                and not row_filial_id
                and bool(access_row.get('pode_administrar'))
            )

            pode_comite = bool(access_row.get('pode_ver_comite_avaliacao'))
            pode_admin = bool(access_row.get('pode_administrar'))

            if (contexto_ok or is_admin_fallback) and (pode_comite or pode_admin):
                acesso_calibracao_ok = True
                break

        if not acesso_calibracao_ok:
            return jsonify({
                'success': False,
                'error': 'acesso_comite_negado',
                'message': 'Usuario sem permissao para concluir a calibracao no comite.'
            }), 403

        action_by = (
            payload.get('action_by')
            or payload.get('user_email')
            or payload.get('committee_user')
            or 'comite'
        )

        action_comment = (
            payload.get('comment')
            or payload.get('action_comment')
            or payload.get('committee_comment')
            or ''
        )

        r_prev = (
            supabase
            .table('evaluation_workflows')
            .select('*')
            .eq('evaluation_id', evaluation_id)
            .limit(1)
            .execute()
        )

        prev_rows = r_prev.data or []

        if not prev_rows:
            return jsonify({
                'success': False,
                'error': 'workflow_nao_encontrado',
                'message': 'Workflow não encontrado. A avaliação precisa passar pela análise inicial antes da calibração.'
            }), 404

        prev_workflow = prev_rows[0]
        workflow_id = prev_workflow.get('id')
        from_status = prev_workflow.get('status_workflow')

        if from_status != 'em_calibracao_no_comite':
            return jsonify({
                'success': False,
                'error': 'status_invalido',
                'message': 'A calibração só pode ser concluída quando a avaliação estiver na etapa de calibração do comitê.',
                'status_atual': from_status
            }), 400

        update_row = {
            'status_workflow': 'aprovada_pelo_comite',
            'committee_status': 'calibrada',
            'committee_validated_at': datetime.now(timezone.utc).isoformat(),
            'committee_validated_by': str(action_by),
            'committee_comment': str(action_comment),
            'updated_at': datetime.now(timezone.utc).isoformat()
        }

        r_update = (
            supabase
            .table('evaluation_workflows')
            .update(update_row)
            .eq('evaluation_id', evaluation_id)
            .execute()
        )

        workflow_data = r_update.data or []
        workflow = workflow_data[0] if workflow_data else {
            **prev_workflow,
            **update_row
        }

        log_row = {
            'workflow_id': workflow_id,
            'evaluation_id': evaluation_id,
            'from_status': from_status,
            'to_status': 'aprovada_pelo_comite',
            'action_by': str(action_by),
            'action_role': 'comite',
            'action_comment': str(action_comment)
        }

        supabase.table('evaluation_workflow_logs').insert(log_row).execute()

        return jsonify({
            'success': True,
            'message': 'Calibração concluída. A avaliação foi liberada para feedback do gestor.',
            'workflow': workflow
        }), 200

    except Exception as e:
        print('[api_workflow_committee_finish_calibration] erro:', e)
        return jsonify({
            'success': False,
            'error': 'workflow_committee_finish_calibration_failed',
            'detail': str(e)
        }), 500


@app.route('/api/evaluations/<int:evaluation_id>/workflow/resubmit-manager', methods=['POST', 'OPTIONS'])
def api_workflow_resubmit_manager(evaluation_id):
    """
    Gestor reenvia ao comitê uma avaliação que havia sido devolvida.
    O comentário representa a resposta/ajuste do gestor após a devolução.
    """
    if request.method == 'OPTIONS':
        return ('', 204)

    try:
        payload = request.get_json(silent=True) or {}

        action_by = (
            payload.get('action_by')
            or payload.get('user_email')
            or payload.get('manager_user')
            or 'gestor'
        )

        comment = (
            payload.get('comment')
            or payload.get('manager_comment')
            or ''
        ).strip()

        if not comment:
            return jsonify({
                'success': False,
                'error': 'comentario_obrigatorio',
                'message': 'Informe um comentário sobre os ajustes realizados antes de reenviar ao comitê.'
            }), 400

        # Buscar workflow existente
        r_wf = (
            supabase
            .table('evaluation_workflows')
            .select('*')
            .eq('evaluation_id', evaluation_id)
            .limit(1)
            .execute()
        )

        wf_rows = r_wf.data or []

        if not wf_rows:
            return jsonify({
                'success': False,
                'error': 'workflow_nao_encontrado',
                'message': 'Workflow não encontrado para esta avaliação.'
            }), 404

        workflow = wf_rows[0]
        workflow_id = workflow.get('id')
        from_status = workflow.get('status_workflow')

        if from_status != 'devolvida_ao_gestor':
            return jsonify({
                'success': False,
                'error': 'status_invalido',
                'message': 'A avaliação só pode ser reenviada ao comitê quando estiver devolvida ao gestor.',
                'status_atual': from_status
            }), 400

        now_iso = datetime.utcnow().isoformat()

        update_payload = {
            'status_workflow': 'enviada_ao_comite',
            'submitted_by_manager_at': now_iso,
            'submitted_by_manager_by': action_by,
            'updated_at': now_iso
        }

        r_update = (
            supabase
            .table('evaluation_workflows')
            .update(update_payload)
            .eq('id', workflow_id)
            .execute()
        )

        updated_rows = r_update.data or []

        # Registrar log
        log_payload = {
            'workflow_id': workflow_id,
            'evaluation_id': evaluation_id,
            'from_status': from_status,
            'to_status': 'enviada_ao_comite',
            'action_by': action_by,
            'action_role': 'gestor',
            'action_comment': comment
        }

        supabase.table('evaluation_workflow_logs').insert(log_payload).execute()

        return jsonify({
            'success': True,
            'message': 'Avaliação reenviada ao comitê após ajustes do gestor.',
            'workflow': updated_rows[0] if updated_rows else None
        }), 200

    except Exception as e:
        print('[api_workflow_resubmit_manager] erro:', e)
        return jsonify({
            'success': False,
            'error': 'resubmit_manager_failed',
            'detail': str(e)
        }), 500


@app.route('/api/evaluations/<int:evaluation_id>/workflow/manager-feedback', methods=['POST', 'OPTIONS'])
def api_workflow_manager_feedback(evaluation_id):
    """
    Gestor registra que realizou o feedback com o profissional.

    Status gerado:
      feedback_realizado
    """
    if request.method == 'OPTIONS':
        return ('', 204)

    try:
        payload = request.get_json(silent=True) or {}

        action_by = (
            payload.get('action_by')
            or payload.get('user_email')
            or payload.get('manager_name')
            or 'gestor'
        )

        action_comment = (
            payload.get('comment')
            or payload.get('action_comment')
            or payload.get('feedback_comment')
            or ''
        )

        # 1) Buscar workflow existente
        r_prev = (
            supabase
            .table('evaluation_workflows')
            .select('*')
            .eq('evaluation_id', evaluation_id)
            .limit(1)
            .execute()
        )

        prev_rows = r_prev.data or []

        if not prev_rows:
            return jsonify({
                'error': 'workflow_nao_encontrado',
                'message': 'Workflow não encontrado. A avaliação precisa passar pelo comitê antes do feedback.'
            }), 404

        prev_workflow = prev_rows[0]
        workflow_id = prev_workflow.get('id')
        from_status = prev_workflow.get('status_workflow')

        if from_status != 'aprovada_pelo_comite':
            return jsonify({
                'success': False,
                'error': 'status_invalido',
                'message': 'O feedback do gestor só pode ser registrado depois que o comitê concluir a calibração.',
                'status_atual': from_status
            }), 400

        # 2) Atualizar workflow
        update_row = {
            'status_workflow': 'feedback_realizado',
            'feedback_done_at': datetime.now(timezone.utc).isoformat(),
            'feedback_done_by': str(action_by),
            'feedback_comment': str(action_comment),
            'updated_at': datetime.now(timezone.utc).isoformat()
        }

        r_update = (
            supabase
            .table('evaluation_workflows')
            .update(update_row)
            .eq('evaluation_id', evaluation_id)
            .execute()
        )

        workflow_data = r_update.data or []
        workflow = workflow_data[0] if workflow_data else {
            **prev_workflow,
            **update_row
        }

        # 3) Registrar log
        log_row = {
            'workflow_id': workflow_id,
            'evaluation_id': evaluation_id,
            'from_status': from_status,
            'to_status': 'feedback_realizado',
            'action_by': str(action_by),
            'action_role': 'gestor',
            'action_comment': str(action_comment)
        }

        supabase.table('evaluation_workflow_logs').insert(log_row).execute()

        return jsonify({
            'success': True,
            'message': 'Feedback registrado com sucesso.',
            'workflow': workflow
        }), 200

    except Exception as e:
        print('[api_workflow_manager_feedback] erro:', e)
        return jsonify({
            'error': 'workflow_manager_feedback_failed',
            'detail': str(e)
        }), 500


def _validate_employee_acknowledgement_access(evaluation_id, actor_email):
    """
    Valida se o e-mail informado pode registrar ciencia da avaliacao.
    Regra: deve ser o profissional vinculado a avaliacao ou admin autorizado.
    """
    actor_email = str(actor_email or '').strip().lower()

    if not actor_email:
        return False, jsonify({
            'success': False,
            'error': 'user_email_obrigatorio',
            'message': 'Informe user_email ou employee_email para registrar a ciencia do profissional.'
        }), 400, None

    r_eval = (
        supabase
        .table('evaluations')
        .select('id, employee_id, cliente_id, empresa_id, filial_id, round_code')
        .eq('id', evaluation_id)
        .limit(1)
        .execute()
    )

    eval_rows = r_eval.data or []

    if not eval_rows:
        return False, jsonify({
            'success': False,
            'error': 'avaliacao_nao_encontrada',
            'message': 'Avaliacao nao encontrada para registrar ciencia.'
        }), 404, None

    evaluation = eval_rows[0]
    employee_id = evaluation.get('employee_id')

    if not employee_id:
        return False, jsonify({
            'success': False,
            'error': 'employee_id_nao_configurado',
            'message': 'A avaliacao nao possui profissional vinculado.'
        }), 400, None

    r_employee = (
        supabase
        .table('employees')
        .select('id, nome, email, cliente_id, holding_id, empresa_id, filial_id')
        .eq('id', employee_id)
        .limit(1)
        .execute()
    )

    employee_rows = r_employee.data or []
    employee = employee_rows[0] if employee_rows else {}

    eval_cliente_id = str(evaluation.get('cliente_id') or employee.get('cliente_id') or '').strip()
    eval_holding_id = str(employee.get('holding_id') or '').strip()
    eval_empresa_id = str(evaluation.get('empresa_id') or employee.get('empresa_id') or '').strip()
    eval_filial_id = str(evaluation.get('filial_id') or employee.get('filial_id') or '').strip()
    employee_email = str(employee.get('email') or '').strip().lower()

    q_access = (
        supabase
        .table('usuarios_acessos')
        .select(
            'id, wp_user_email, perfil, employee_id, cliente_id, holding_id, empresa_id, filial_id, '
            'pode_ver_ciencia_avaliacao, pode_administrar, status'
        )
        .eq('status', 'ativo')
        .eq('wp_user_email', actor_email)
        .execute()
    )

    access_rows = q_access.data or []

    for access_row in access_rows:
        row_cliente_id = str(access_row.get('cliente_id') or '').strip()
        row_holding_id = str(access_row.get('holding_id') or '').strip()
        row_empresa_id = str(access_row.get('empresa_id') or '').strip()
        row_filial_id = str(access_row.get('filial_id') or '').strip()
        row_employee_id = str(access_row.get('employee_id') or '').strip()

        contexto_ok = True

        if eval_cliente_id and row_cliente_id and row_cliente_id != eval_cliente_id:
            contexto_ok = False

        if eval_holding_id and row_holding_id and row_holding_id != eval_holding_id:
            contexto_ok = False

        if eval_empresa_id and row_empresa_id and row_empresa_id != eval_empresa_id:
            contexto_ok = False

        if eval_filial_id and row_filial_id and row_filial_id != eval_filial_id:
            contexto_ok = False

        pode_ciencia = bool(access_row.get('pode_ver_ciencia_avaliacao'))
        pode_admin = bool(access_row.get('pode_administrar'))

        employee_match = (
            (row_employee_id and row_employee_id == str(employee_id))
            or (employee_email and actor_email == employee_email)
        )

        is_admin_fallback = (
            not row_holding_id
            and not row_empresa_id
            and not row_filial_id
            and pode_admin
        )

        if (
            (pode_ciencia and employee_match and contexto_ok)
            or (pode_admin and contexto_ok)
            or is_admin_fallback
        ):
            return True, None, None, {
                'evaluation': evaluation,
                'employee': employee,
                'access': access_row
            }

    return False, jsonify({
        'success': False,
        'error': 'acesso_ciencia_negado',
        'message': 'Usuario sem permissao para registrar ciencia nesta avaliacao.'
    }), 403, None


@app.route('/api/evaluations/<int:evaluation_id>/workflow/employee-acknowledge', methods=['POST', 'OPTIONS'])
def api_workflow_employee_acknowledge(evaluation_id):
    """
    Profissional confirma ciência da avaliação.

    Pode registrar:
      - de_acordo
      - ciencia_com_ressalva
      - discordo

    Status gerado:
      ciencia_do_profissional
    """
    if request.method == 'OPTIONS':
        return ('', 204)

    try:
        payload = request.get_json(silent=True) or {}

        actor_email = (
            payload.get('user_email')
            or payload.get('employee_email')
            or payload.get('wp_user_email')
            or ''
        )

        if not actor_email and '@' in str(payload.get('action_by') or ''):
            actor_email = payload.get('action_by')

        access_ok, error_response, error_status, access_context = _validate_employee_acknowledgement_access(
            evaluation_id,
            actor_email
        )

        if not access_ok:
            return error_response, error_status

        acknowledgement_status = (
            payload.get('acknowledgement_status')
            or payload.get('employee_acknowledgement_status')
            or payload.get('status')
            or 'de_acordo'
        )

        action_by = (
            payload.get('action_by')
            or actor_email
            or payload.get('employee_email')
            or payload.get('employee_name')
            or 'profissional'
        )

        action_comment = (
            payload.get('comment')
            or payload.get('employee_comment')
            or payload.get('action_comment')
            or ''
        )

        # 1) Buscar workflow existente
        r_prev = (
            supabase
            .table('evaluation_workflows')
            .select('*')
            .eq('evaluation_id', evaluation_id)
            .limit(1)
            .execute()
        )

        prev_rows = r_prev.data or []

        if not prev_rows:
            return jsonify({
                'error': 'workflow_nao_encontrado',
                'message': 'Workflow não encontrado. O feedback precisa ser registrado antes da ciência do profissional.'
            }), 404

        prev_workflow = prev_rows[0]
        workflow_id = prev_workflow.get('id')
        from_status = prev_workflow.get('status_workflow')

        if from_status != 'feedback_realizado':
            return jsonify({
                'success': False,
                'error': 'status_invalido',
                'message': 'A ciência do profissional só pode ser registrada depois que o gestor informar o feedback.',
                'status_atual': from_status
            }), 400

        # 2) Atualizar workflow
        update_row = {
            'status_workflow': 'ciencia_do_profissional',
            'employee_acknowledged_at': datetime.now(timezone.utc).isoformat(),
            'employee_acknowledgement_status': str(acknowledgement_status),
            'employee_comment': str(action_comment),
            'updated_at': datetime.now(timezone.utc).isoformat()
        }

        r_update = (
            supabase
            .table('evaluation_workflows')
            .update(update_row)
            .eq('evaluation_id', evaluation_id)
            .execute()
        )

        workflow_data = r_update.data or []
        workflow = workflow_data[0] if workflow_data else {
            **prev_workflow,
            **update_row
        }

        # 3) Registrar log
        log_row = {
            'workflow_id': workflow_id,
            'evaluation_id': evaluation_id,
            'from_status': from_status,
            'to_status': 'ciencia_do_profissional',
            'action_by': str(action_by),
            'action_role': 'profissional',
            'action_comment': str(action_comment)
        }

        supabase.table('evaluation_workflow_logs').insert(log_row).execute()

        return jsonify({
            'success': True,
            'message': 'Ciência do profissional registrada com sucesso.',
            'workflow': workflow
        }), 200

    except Exception as e:
        print('[api_workflow_employee_acknowledge] erro:', e)
        return jsonify({
            'error': 'workflow_employee_acknowledge_failed',
            'detail': str(e)
        }), 500


@app.route('/api/evaluations/<int:evaluation_id>/workflow', methods=['GET', 'OPTIONS'])
def api_get_evaluation_workflow(evaluation_id):
    """
    Consulta o workflow atual da avaliação e seus logs.
    Usado pelo front-end para saber o status atual e o histórico.
    """
    if request.method == 'OPTIONS':
        return ('', 204)

    try:
        # 1) Buscar workflow principal
        r_workflow = (
            supabase
            .table('evaluation_workflows')
            .select('*')
            .eq('evaluation_id', evaluation_id)
            .limit(1)
            .execute()
        )

        workflow_rows = r_workflow.data or []
        workflow = workflow_rows[0] if workflow_rows else None

        # 2) Buscar logs do workflow
        r_logs = (
            supabase
            .table('evaluation_workflow_logs')
            .select('*')
            .eq('evaluation_id', evaluation_id)
            .order('created_at', desc=False)
            .execute()
        )

        logs = r_logs.data or []

        return jsonify({
            'success': True,
            'evaluation_id': evaluation_id,
            'workflow': workflow,
            'logs': logs
        }), 200

    except Exception as e:
        print('[api_get_evaluation_workflow] erro:', e)
        return jsonify({
            'error': 'workflow_get_failed',
            'detail': str(e)
        }), 500


def _get_workflow_context_employees(cliente_id='', holding_id='', empresa_id='', filial_id=''):
    """
    Busca profissionais dentro do contexto recebido pelo WordPress.
    Isso deixa o filtro de holding explicito antes de montar as listas do comite.
    """
    q_emp = (
        supabase
        .table('employees')
        .select(
            'id, nome, cargo, empresa, company_name, branch_name, department_name, '
            'manager_name, email, emailLider, employee_code, manager_code, '
            'holding, business_line, nivel, cliente_id, holding_id, empresa_id, filial_id'
        )
    )

    if cliente_id and not (holding_id or empresa_id or filial_id):
        q_emp = q_emp.eq('cliente_id', cliente_id)

    if holding_id:
        q_emp = q_emp.eq('holding_id', holding_id)

    if empresa_id:
        q_emp = q_emp.eq('empresa_id', empresa_id)

    if filial_id:
        q_emp = q_emp.eq('filial_id', filial_id)

    rows = q_emp.execute().data or []

    return {
        row.get('id'): row
        for row in rows
        if row.get('id') is not None
    }


def _get_workflow_nivel_contexto():
    return (
        request.args.get('nivel_contexto')
        or request.args.get('nivel')
        or request.args.get('contexto_nivel')
        or ''
    ).strip().lower()


def _get_evaluations_from_workflows(round_code, context_employees_by_id=None):
    q_workflows = (
        supabase
        .table('evaluation_workflows')
        .select('evaluation_id, employee_id, round_code')
        .eq('round_code', round_code)
    )

    workflow_rows = q_workflows.execute().data or []
    allowed_employee_ids = set((context_employees_by_id or {}).keys())

    if allowed_employee_ids:
        workflow_rows = [
            row for row in workflow_rows
            if row.get('employee_id') in allowed_employee_ids
        ]

    evaluation_ids = [
        row.get('evaluation_id')
        for row in workflow_rows
        if row.get('evaluation_id') is not None
    ]

    if not evaluation_ids:
        return []

    evaluations_by_id = {}

    r_eval = (
        supabase
        .table('evaluations')
        .select(
            'id, employee_id, evaluator_id, evaluation_year, evaluation_date, status, '
            'final_rating, nine_box_position, performance_rating, potential_rating, '
            'round_code, cliente_id, empresa_id, filial_id, created_at'
        )
        .in_('id', evaluation_ids)
        .execute()
    )

    for ev in (r_eval.data or []):
        evaluations_by_id[ev.get('id')] = ev

    fallback_rows = []
    for wf in workflow_rows:
        evaluation_id = wf.get('evaluation_id')
        ev = evaluations_by_id.get(evaluation_id)

        if ev:
            fallback_rows.append(ev)
            continue

        fallback_rows.append({
            'id': evaluation_id,
            'employee_id': wf.get('employee_id'),
            'round_code': wf.get('round_code') or round_code,
            'evaluator_id': None,
            'evaluation_year': None,
            'evaluation_date': None,
            'status': None,
            'final_rating': None,
            'nine_box_position': None,
            'performance_rating': None,
            'potential_rating': None,
            'cliente_id': None,
            'empresa_id': None,
            'filial_id': None,
            'created_at': None
        })

    return sorted(
        fallback_rows,
        key=lambda row: row.get('id') or 0,
        reverse=True
    )


def _get_workflow_rating_context_map(
    round_code,
    cliente_id='',
    holding_id='',
    empresa_id='',
    filial_id=''
):
    q_rating = (
        supabase
        .table('v_desempenho_contexto')
        .select(
            'evaluation_id,employee_id,'
            'final_rating,performance_rating,potential_rating,nine_box_position,'
            'round_code,ciclo_codigo'
        )
    )

    if round_code:
        q_rating = q_rating.eq('round_code', round_code)

    if cliente_id and not (holding_id or empresa_id or filial_id):
        q_rating = q_rating.eq('cliente_id', cliente_id)

    if holding_id:
        q_rating = q_rating.eq('holding_id', holding_id)

    if empresa_id:
        q_rating = q_rating.eq('empresa_id', empresa_id)

    if filial_id:
        q_rating = q_rating.eq('filial_id', filial_id)

    rows = q_rating.execute().data or []

    by_evaluation_id = {}
    by_employee_id = {}

    for row in rows:
        evaluation_id = row.get('evaluation_id')
        employee_id = row.get('employee_id')

        if evaluation_id is not None:
            by_evaluation_id[evaluation_id] = row

        if employee_id is not None:
            by_employee_id[employee_id] = row

    return by_evaluation_id, by_employee_id


def _coalesce_value(*values):
    for value in values:
        if value is not None:
            return value
    return None


@app.route('/api/workflow/evaluations', methods=['GET', 'OPTIONS'])
def api_list_workflow_evaluations():
    """
    Lista avaliações formais YE para o painel do comitê.
    Retorna avaliações enriquecidas com dados do profissional e status do workflow.
    Respeita contexto: cliente, holding, empresa e filial.

    Exemplos:
      /api/workflow/evaluations?round_code=YE2026
      /api/workflow/evaluations?round_code=YE2026&holding_id=...
      /api/workflow/evaluations?round_code=YE2026&empresa_id=...
      /api/workflow/evaluations?round_code=YE2026&filial_id=...
    """
    if request.method == 'OPTIONS':
        return ('', 204)

    try:
        round_code = (request.args.get('round_code') or 'YE2026').strip()

        cliente_id = (request.args.get('cliente_id') or '').strip()
        holding_id = (request.args.get('holding_id') or '').strip()
        empresa_id = (request.args.get('empresa_id') or '').strip()
        user_email = (request.args.get('user_email') or '').strip().lower()
        filial_id = (request.args.get('filial_id') or '').strip()
        nivel_contexto = _get_workflow_nivel_contexto()
        include_demo_rows = _workflow_include_demo_rows()

        print('[api_list_workflow_evaluations] contexto recebido:', {
            'round_code': round_code,
            'cliente_id': cliente_id,
            'holding_id': holding_id,
            'empresa_id': empresa_id,
            'filial_id': filial_id,
            'user_email': user_email,
            'nivel_contexto': nivel_contexto
        })



        if not user_email:
            return jsonify({
                'success': False,
                'error': 'user_email_obrigatorio',
                'message': 'Informe user_email para consultar avaliacoes do comite.'
            }), 400


        q_access = (
            supabase
            .table('usuarios_acessos')
            .select(
                'id, wp_user_email, perfil, cliente_id, holding_id, empresa_id, filial_id, '
                'pode_ver_comite_avaliacao, pode_administrar, status'
            )
            .eq('status', 'ativo')
            .execute()
        )

        access_rows_raw = q_access.data or []
        acesso_comite_ok = False



        for access_row in access_rows_raw:
            row_email = str(access_row.get('wp_user_email') or '').strip().lower()

            if row_email != user_email:
                continue

            row_cliente_id = str(access_row.get('cliente_id') or '').strip()
            row_holding_id = str(access_row.get('holding_id') or '').strip()
            row_empresa_id = str(access_row.get('empresa_id') or '').strip()
            row_filial_id = str(access_row.get('filial_id') or '').strip()

            contexto_ok = True

            if cliente_id and row_cliente_id and row_cliente_id != cliente_id:
                contexto_ok = False

            if holding_id and row_holding_id and row_holding_id != holding_id:
                contexto_ok = False

            if empresa_id and row_empresa_id and row_empresa_id != empresa_id:
                contexto_ok = False

            if filial_id and row_filial_id and row_filial_id != filial_id:
                contexto_ok = False

            is_admin_fallback = (
                not row_holding_id
                and not row_empresa_id
                and not row_filial_id
                and bool(access_row.get('pode_administrar'))
            )

            pode_comite = bool(access_row.get('pode_ver_comite_avaliacao'))
            pode_admin = bool(access_row.get('pode_administrar'))

            if (contexto_ok or is_admin_fallback) and (pode_comite or pode_admin):
                acesso_comite_ok = True
                break

        if not acesso_comite_ok:
            return jsonify({
                'success': False,
                'error': 'acesso_comite_negado',
                'message': 'Usuario sem permissao para consultar avaliacoes do comite.'
            }), 403

        


        

        context_employees_by_id = {}
        if cliente_id or holding_id or empresa_id or filial_id:
            context_employees_by_id = _get_workflow_context_employees(
                cliente_id=cliente_id,
                holding_id=holding_id,
                empresa_id=empresa_id,
                filial_id=filial_id
            )

            if not context_employees_by_id:
                return jsonify({
                    'success': True,
                    'round_code': round_code,
                    'contexto': {
                        'cliente_id': cliente_id,
                        'holding_id': holding_id,
                        'empresa_id': empresa_id,
                        'filial_id': filial_id,
                        'nivel': nivel_contexto
                    },
                    'managers': [],
                    'items': []
                }), 200

        # 1) Buscar avaliações da rodada
        q_eval = (
            supabase
            .table('evaluations')
            .select(
                'id, employee_id, evaluator_id, evaluation_year, evaluation_date, status, '
                'final_rating, nine_box_position, performance_rating, potential_rating, '
                'round_code, cliente_id, empresa_id, filial_id, created_at'
            )
            .eq('round_code', round_code)
        )

        if cliente_id:
            q_eval = q_eval.eq('cliente_id', cliente_id)

        if context_employees_by_id:
            q_eval = q_eval.in_('employee_id', list(context_employees_by_id.keys()))

        # Filtro direto por empresa/filial quando vier no contexto.
        # Holding será filtrada com base na tabela employees, porque evaluations não possui holding_id.
        if empresa_id:
            q_eval = q_eval.eq('empresa_id', empresa_id)

        if filial_id:
            q_eval = q_eval.eq('filial_id', filial_id)

        r_eval = (
            q_eval
            .order('id', desc=True)
            .execute()
        )

        evaluations = r_eval.data or []

        if not evaluations:
            evaluations = _get_evaluations_from_workflows(
                round_code,
                context_employees_by_id=context_employees_by_id
            )

        if not evaluations:
            return jsonify({
                'success': True,
                'round_code': round_code,
                'contexto': {
                    'cliente_id': cliente_id,
                    'holding_id': holding_id,
                    'empresa_id': empresa_id,
                    'filial_id': filial_id,
                    'nivel': nivel_contexto
                },
                'managers': [],
                'items': []
            }), 200

        employee_ids = [
            ev.get('employee_id')
            for ev in evaluations
            if ev.get('employee_id') is not None
        ]

        evaluation_ids = [
            ev.get('id')
            for ev in evaluations
            if ev.get('id') is not None
        ]

        # 2) Buscar profissionais avaliados
        employees_by_id = dict(context_employees_by_id)

        if employee_ids and not employees_by_id:
            q_emp = (
                supabase
                .table('employees')
                .select(
                    'id, nome, cargo, empresa, company_name, branch_name, department_name, '
                    'manager_name, email, emailLider, employee_code, manager_code, '
                    'holding, business_line, nivel, cliente_id, holding_id, empresa_id, filial_id'
                )
                .in_('id', employee_ids)
            )

            if cliente_id:
                q_emp = q_emp.eq('cliente_id', cliente_id)

            if holding_id:
                q_emp = q_emp.eq('holding_id', holding_id)

            if empresa_id:
                q_emp = q_emp.eq('empresa_id', empresa_id)

            if filial_id:
                q_emp = q_emp.eq('filial_id', filial_id)

            r_emp = q_emp.execute()

            for emp in (r_emp.data or []):
                employees_by_id[emp.get('id')] = emp

        # 3) Buscar workflows existentes
        workflows_by_evaluation_id = {}

        if evaluation_ids:
            r_workflows = (
                supabase
                .table('evaluation_workflows')
                .select('*')
                .in_('evaluation_id', evaluation_ids)
                .execute()
            )

            for wf in (r_workflows.data or []):
                workflows_by_evaluation_id[wf.get('evaluation_id')] = wf

        ratings_by_evaluation_id, ratings_by_employee_id = _get_workflow_rating_context_map(
            round_code,
            cliente_id=cliente_id,
            holding_id=holding_id,
            empresa_id=empresa_id,
            filial_id=filial_id
        )

        # 4) Montar itens enriquecidos
        # Importante: só entra item cujo employee passou no filtro de contexto.
        items = []

        for ev in evaluations:
            employee_id = ev.get('employee_id')
            evaluation_id = ev.get('id')

            emp = employees_by_id.get(employee_id)

            if not emp:
                continue

            wf = workflows_by_evaluation_id.get(evaluation_id)

            if _is_demo_workflow_row(wf) and not include_demo_rows:
                continue

            rating_ctx = (
                ratings_by_evaluation_id.get(evaluation_id)
                or ratings_by_employee_id.get(employee_id)
                or {}
            )

            manager_name = (
                emp.get('manager_name')
                or emp.get('emailLider')
                or 'Sem gestor identificado'
            )

            item = {
                'evaluation_id': evaluation_id,
                'employee_id': employee_id,
                'employee_name': emp.get('nome'),
                'employee_email': emp.get('email'),
                'cargo': emp.get('cargo'),
                'company_name': emp.get('company_name') or emp.get('empresa'),
                'branch_name': emp.get('branch_name'),
                'department_name': emp.get('department_name'),
                'manager_name': manager_name,
                'manager_email': emp.get('emailLider'),
                'holding': emp.get('holding'),
                'cliente_id': emp.get('cliente_id'),
                'holding_id': emp.get('holding_id'),
                'empresa_id': emp.get('empresa_id'),
                'filial_id': emp.get('filial_id'),
                'round_code': ev.get('round_code'),
                'evaluation_year': ev.get('evaluation_year'),
                'final_rating': _coalesce_value(ev.get('final_rating'), rating_ctx.get('final_rating')),
                'nine_box_position': _coalesce_value(ev.get('nine_box_position'), rating_ctx.get('nine_box_position')),
                'performance_rating': _coalesce_value(ev.get('performance_rating'), rating_ctx.get('performance_rating')),
                'potential_rating': _coalesce_value(ev.get('potential_rating'), rating_ctx.get('potential_rating')),
                'workflow_status': wf.get('status_workflow') if wf else None,
                'workflow': wf
            }

            items.append(item)

        # 5) Lista única de gestores
        managers_map = {}

        for item in items:
            key = item.get('manager_name') or 'Sem gestor identificado'

            if key not in managers_map:
                managers_map[key] = {
                    'manager_name': key,
                    'manager_email': item.get('manager_email'),
                    'total_avaliacoes': 0
                }

            managers_map[key]['total_avaliacoes'] += 1

        managers = sorted(
            list(managers_map.values()),
            key=lambda x: x.get('manager_name') or ''
        )

        return jsonify({
            'success': True,
            'round_code': round_code,
            'contexto': {
                'cliente_id': cliente_id,
                'holding_id': holding_id,
                'empresa_id': empresa_id,
                'filial_id': filial_id,
                'nivel': nivel_contexto
            },
            'managers': managers,
            'items': items
        }), 200

    except Exception as e:
        print('[api_list_workflow_evaluations] erro:', e)
        return jsonify({
            'success': False,
            'error': 'workflow_evaluations_list_failed',
            'detail': str(e)
        }), 500


@app.route('/api/workflow/calibration-overview', methods=['GET', 'OPTIONS'])
def api_workflow_calibration_overview():
    """
    Retorna uma visao comparativa para a etapa de calibracao do comite.
    A ideia e alimentar filtros, cards e graficos na tela de calibracao.

    Filtros opcionais:
      - round_code
      - cliente_id
      - holding_id
      - empresa_id
      - filial_id
      - manager_name
      - department_name
      - workflow_status
      - employee_name
    """
    if request.method == 'OPTIONS':
        return ('', 204)

    try:
        round_code = (request.args.get('round_code') or 'YE2026').strip()
        cliente_id = (request.args.get('cliente_id') or '').strip()
        holding_id = (request.args.get('holding_id') or '').strip()
        empresa_id = (request.args.get('empresa_id') or '').strip()
        filial_id = (request.args.get('filial_id') or '').strip()
        include_demo_rows = _workflow_include_demo_rows()
        user_email = (request.args.get('user_email') or '').strip().lower()
        manager_name_filter = (request.args.get('manager_name') or '').strip().lower()
        department_name_filter = (request.args.get('department_name') or '').strip().lower()
        workflow_status_filter = (request.args.get('workflow_status') or '').strip().lower()
        employee_name_filter = (request.args.get('employee_name') or '').strip().lower()

        if not user_email:
            return jsonify({
                'success': False,
                'error': 'user_email_obrigatorio',
                'message': 'Informe user_email para consultar a calibracao do comite.'
            }), 400

        q_access = (
            supabase
            .table('usuarios_acessos')
            .select(
                'id, wp_user_email, perfil, cliente_id, holding_id, empresa_id, filial_id, '
                'pode_ver_comite_avaliacao, pode_administrar, status'
            )
            .eq('status', 'ativo')
            .execute()
        )

        access_rows_raw = q_access.data or []
        acesso_comite_ok = False

        for access_row in access_rows_raw:
            row_email = str(access_row.get('wp_user_email') or '').strip().lower()

            if row_email != user_email:
                continue

            row_cliente_id = str(access_row.get('cliente_id') or '').strip()
            row_holding_id = str(access_row.get('holding_id') or '').strip()
            row_empresa_id = str(access_row.get('empresa_id') or '').strip()
            row_filial_id = str(access_row.get('filial_id') or '').strip()

            contexto_ok = True

            if cliente_id and row_cliente_id and row_cliente_id != cliente_id:
                contexto_ok = False

            if holding_id and row_holding_id and row_holding_id != holding_id:
                contexto_ok = False

            if empresa_id and row_empresa_id and row_empresa_id != empresa_id:
                contexto_ok = False

            if filial_id and row_filial_id and row_filial_id != filial_id:
                contexto_ok = False

            is_admin_fallback = (
                not row_holding_id
                and not row_empresa_id
                and not row_filial_id
                and bool(access_row.get('pode_administrar'))
            )

            pode_comite = bool(access_row.get('pode_ver_comite_avaliacao'))
            pode_admin = bool(access_row.get('pode_administrar'))

            if (contexto_ok or is_admin_fallback) and (pode_comite or pode_admin):
                acesso_comite_ok = True
                break

        if not acesso_comite_ok:
            return jsonify({
                'success': False,
                'error': 'acesso_comite_negado',
                'message': 'Usuario sem permissao para consultar a calibracao do comite.'
            }), 403

        context_employees_by_id = {}
        if cliente_id or holding_id or empresa_id or filial_id:
            context_employees_by_id = _get_workflow_context_employees(
                cliente_id=cliente_id,
                holding_id=holding_id,
                empresa_id=empresa_id,
                filial_id=filial_id
            )

            if not context_employees_by_id:
                return jsonify({
                    'success': True,
                    'round_code': round_code,
                    'filters': {
                        'cliente_id': cliente_id,
                        'holding_id': holding_id,
                        'empresa_id': empresa_id,
                        'filial_id': filial_id,
                        'manager_name': manager_name_filter,
                        'department_name': department_name_filter,
                        'workflow_status': workflow_status_filter,
                        'employee_name': employee_name_filter
                    },
                    'summary': {
                        'total_avaliacoes': 0,
                        'rating_medio_geral': None,
                        'status_counts': [],
                        'ratings_distribution': [],
                        'media_por_gestor': [],
                        'media_por_area': [],
                        'media_por_empresa': []
                    },
                    'items': []
                }), 200

        q_eval = (
            supabase
            .table('evaluations')
            .select(
                'id, employee_id, evaluator_id, evaluation_year, evaluation_date, status, '
                'final_rating, nine_box_position, performance_rating, potential_rating, '
                'round_code, cliente_id, empresa_id, filial_id, created_at'
            )
            .eq('round_code', round_code)
        )

        if cliente_id:
            q_eval = q_eval.eq('cliente_id', cliente_id)

        if context_employees_by_id:
            q_eval = q_eval.in_('employee_id', list(context_employees_by_id.keys()))

        if empresa_id:
            q_eval = q_eval.eq('empresa_id', empresa_id)

        if filial_id:
            q_eval = q_eval.eq('filial_id', filial_id)

        r_eval = q_eval.order('id', desc=True).execute()
        evaluations = r_eval.data or []

        if not evaluations:
            evaluations = _get_evaluations_from_workflows(
                round_code,
                context_employees_by_id=context_employees_by_id
            )

        if not evaluations:
            return jsonify({
                'success': True,
                'round_code': round_code,
                'filters': {
                    'manager_name': manager_name_filter,
                    'department_name': department_name_filter,
                    'workflow_status': workflow_status_filter,
                    'employee_name': employee_name_filter
                },
                'summary': {
                    'total_avaliacoes': 0,
                    'rating_medio_geral': None,
                    'status_counts': [],
                    'ratings_distribution': [],
                    'media_por_gestor': [],
                    'media_por_area': [],
                    'media_por_empresa': []
                },
                'items': []
            }), 200

        employee_ids = [
            ev.get('employee_id')
            for ev in evaluations
            if ev.get('employee_id') is not None
        ]

        evaluation_ids = [
            ev.get('id')
            for ev in evaluations
            if ev.get('id') is not None
        ]

        employees_by_id = dict(context_employees_by_id)

        if employee_ids and not employees_by_id:
            q_emp = (
                supabase
                .table('employees')
                .select(
                    'id, nome, cargo, empresa, company_name, branch_name, department_name, '
                    'manager_name, email, emailLider, employee_code, manager_code, '
                    'holding, business_line, nivel, cliente_id, holding_id, empresa_id, filial_id'
                )
                .in_('id', employee_ids)
            )

            if cliente_id:
                q_emp = q_emp.eq('cliente_id', cliente_id)

            if holding_id:
                q_emp = q_emp.eq('holding_id', holding_id)

            if empresa_id:
                q_emp = q_emp.eq('empresa_id', empresa_id)

            if filial_id:
                q_emp = q_emp.eq('filial_id', filial_id)

            r_emp = q_emp.execute()

            for emp in (r_emp.data or []):
                employees_by_id[emp.get('id')] = emp

        workflows_by_evaluation_id = {}

        if evaluation_ids:
            r_workflows = (
                supabase
                .table('evaluation_workflows')
                .select('*')
                .in_('evaluation_id', evaluation_ids)
                .execute()
            )

            for wf in (r_workflows.data or []):
                workflows_by_evaluation_id[wf.get('evaluation_id')] = wf

        ratings_by_evaluation_id, ratings_by_employee_id = _get_workflow_rating_context_map(
            round_code,
            cliente_id=cliente_id,
            holding_id=holding_id,
            empresa_id=empresa_id,
            filial_id=filial_id
        )

        items = []

        for ev in evaluations:
            employee_id = ev.get('employee_id')
            evaluation_id = ev.get('id')
            emp = employees_by_id.get(employee_id)

            if not emp:
                continue

            wf = workflows_by_evaluation_id.get(evaluation_id)

            if _is_demo_workflow_row(wf) and not include_demo_rows:
                continue

            rating_ctx = (
                ratings_by_evaluation_id.get(evaluation_id)
                or ratings_by_employee_id.get(employee_id)
                or {}
            )
            manager_name = str(emp.get('manager_name') or emp.get('emailLider') or 'Sem gestor identificado').strip()
            department_name = str(emp.get('department_name') or '').strip()
            employee_name = str(emp.get('nome') or '').strip()
            workflow_status = str(wf.get('status_workflow') if wf else 'sem_workflow' or '').strip()

            if manager_name_filter and manager_name.lower() != manager_name_filter:
                continue

            if department_name_filter and department_name.lower() != department_name_filter:
                continue

            if workflow_status_filter and workflow_status.lower() != workflow_status_filter:
                continue

            if employee_name_filter and employee_name_filter not in employee_name.lower():
                continue

            item = {
                'evaluation_id': evaluation_id,
                'employee_id': employee_id,
                'employee_name': employee_name,
                'employee_email': emp.get('email'),
                'cargo': emp.get('cargo'),
                'company_name': emp.get('company_name') or emp.get('empresa'),
                'branch_name': emp.get('branch_name'),
                'department_name': department_name,
                'manager_name': manager_name,
                'manager_email': emp.get('emailLider'),
                'holding': emp.get('holding'),
                'cliente_id': emp.get('cliente_id'),
                'holding_id': emp.get('holding_id'),
                'empresa_id': emp.get('empresa_id'),
                'filial_id': emp.get('filial_id'),
                'round_code': ev.get('round_code'),
                'evaluation_year': ev.get('evaluation_year'),
                'final_rating': _coalesce_value(ev.get('final_rating'), rating_ctx.get('final_rating')),
                'nine_box_position': _coalesce_value(ev.get('nine_box_position'), rating_ctx.get('nine_box_position')),
                'performance_rating': _coalesce_value(ev.get('performance_rating'), rating_ctx.get('performance_rating')),
                'potential_rating': _coalesce_value(ev.get('potential_rating'), rating_ctx.get('potential_rating')),
                'workflow_status': workflow_status,
                'workflow': wf
            }

            items.append(item)

        def _append_group_avg(bucket, key, rating_value):
            if key not in bucket:
                bucket[key] = {
                    'total': 0,
                    'rated_total': 0,
                    'sum': 0.0
                }

            bucket[key]['total'] += 1

            if rating_value is not None:
                bucket[key]['rated_total'] += 1
                bucket[key]['sum'] += float(rating_value)

        status_counts_map = {}
        ratings_distribution_map = {}
        manager_avg_map = {}
        department_avg_map = {}
        company_avg_map = {}
        rating_values = []

        for item in items:
            status_key = item.get('workflow_status') or 'sem_workflow'
            status_counts_map[status_key] = status_counts_map.get(status_key, 0) + 1

            rating_value = item.get('final_rating')
            rating_bucket = str(rating_value) if rating_value is not None else 'sem_rating'
            ratings_distribution_map[rating_bucket] = ratings_distribution_map.get(rating_bucket, 0) + 1

            if rating_value is not None:
                rating_values.append(float(rating_value))

            _append_group_avg(manager_avg_map, item.get('manager_name') or 'Sem gestor identificado', rating_value)
            _append_group_avg(department_avg_map, item.get('department_name') or 'Sem area informada', rating_value)
            _append_group_avg(company_avg_map, item.get('company_name') or 'Sem empresa informada', rating_value)

        def _format_avg_list(source_map, key_name):
            rows = []

            for key, meta in source_map.items():
                total = int(meta.get('total') or 0)
                rated_total = int(meta.get('rated_total') or 0)
                avg = round(meta.get('sum', 0.0) / rated_total, 2) if rated_total else None
                rows.append({
                    key_name: key,
                    'total_avaliacoes': total,
                    'avaliacoes_com_rating': rated_total,
                    'rating_medio': avg
                })

            return sorted(rows, key=lambda x: ((x.get('rating_medio') is None), -(x.get('rating_medio') or 0), x.get(key_name) or ''))

        rating_medio_geral = round(sum(rating_values) / len(rating_values), 2) if rating_values else None

        return jsonify({
            'success': True,
            'round_code': round_code,
            'filters': {
                'cliente_id': cliente_id,
                'holding_id': holding_id,
                'empresa_id': empresa_id,
                'filial_id': filial_id,
                'manager_name': manager_name_filter,
                'department_name': department_name_filter,
                'workflow_status': workflow_status_filter,
                'employee_name': employee_name_filter
            },
            'summary': {
                'total_avaliacoes': len(items),
                'rating_medio_geral': rating_medio_geral,
                'status_counts': [
                    {'workflow_status': k, 'total': v}
                    for k, v in sorted(status_counts_map.items(), key=lambda x: x[0])
                ],
                'ratings_distribution': [
                    {'rating': k, 'total': v}
                    for k, v in sorted(ratings_distribution_map.items(), key=lambda x: x[0])
                ],
                'media_por_gestor': _format_avg_list(manager_avg_map, 'manager_name'),
                'media_por_area': _format_avg_list(department_avg_map, 'department_name'),
                'media_por_empresa': _format_avg_list(company_avg_map, 'company_name')
            },
            'items': items
        }), 200

    except Exception as e:
        print('[api_workflow_calibration_overview] erro:', e)
        return jsonify({
            'success': False,
            'error': 'workflow_calibration_overview_failed',
            'detail': str(e)
        }), 500


@app.route('/api/manager/workflow/evaluations', methods=['GET', 'OPTIONS'])
def api_list_manager_workflow_evaluations():
    """
    Lista avaliações formais YE para a página do gestor.
    O gestor é identificado por e-mail, nome ou código.
    
    Exemplos:
      /api/manager/workflow/evaluations?round_code=YE2026&manager_email=god
      /api/manager/workflow/evaluations?round_code=YE2026&manager_name=GOD
    """
    if request.method == 'OPTIONS':
        return ('', 204)

    try:
        round_code = (request.args.get('round_code') or 'YE2026').strip()

        manager_email = (request.args.get('manager_email') or '').strip()
        manager_name = (request.args.get('manager_name') or '').strip()
        manager_code = (request.args.get('manager_code') or '').strip()
        user_email = (request.args.get('user_email') or '').strip().lower()

        cliente_id = (request.args.get('cliente_id') or '').strip()
        holding_id = (request.args.get('holding_id') or '').strip()
        empresa_id = (request.args.get('empresa_id') or '').strip()
        filial_id = (request.args.get('filial_id') or '').strip()
        include_demo_rows = _workflow_include_demo_rows()

        print('[api_list_manager_workflow_evaluations] filtros recebidos:', {
            'round_code': round_code,
            'manager_email': manager_email,
            'manager_name': manager_name,
            'manager_code': manager_code,
            'cliente_id': cliente_id,
            'holding_id': holding_id,
            'empresa_id': empresa_id,
            'filial_id': filial_id
        })

        # 1) Buscar profissionais do gestor
        q_emp = (
            supabase
            .table('employees')
            .select(
                'id, nome, cargo, empresa, company_name, branch_name, department_name, '
                'manager_name, email, emailLider, employee_code, manager_code, '
                'holding, business_line, nivel, cliente_id, holding_id, empresa_id, filial_id'
            )
        )

        if cliente_id:
            q_emp = q_emp.eq('cliente_id', cliente_id)

        if holding_id:
            q_emp = q_emp.eq('holding_id', holding_id)

        if empresa_id:
            q_emp = q_emp.eq('empresa_id', empresa_id)

        if filial_id:
            q_emp = q_emp.eq('filial_id', filial_id)

        # Filtro do gestor.
        # Primeiro buscamos os profissionais do contexto e depois filtramos em Python,
        # evitando uso de .or_(), que não está disponível neste cliente Supabase.

        
        if not manager_email and not manager_name and not manager_code:
            return jsonify({
                'success': False,
                'error': 'gestor_nao_informado',
                'message': 'Informe manager_email, manager_name ou manager_code para listar as avaliações do gestor.'
            }), 400


        # Seguranca: se a pagina informar user_email,
        # validar se o usuario logado pode consultar este gestor.
        if user_email:
            q_access = (
                supabase
                .table('usuarios_acessos')
                .select(
                    'id, wp_user_email, perfil, cliente_id, holding_id, empresa_id, filial_id, '
                    'employee_id, manager_name, manager_code, '
                    'pode_ver_gestor_avaliacao, pode_administrar, status'
                )
                .eq('status', 'ativo')
                .execute()
            )

            access_rows_raw = q_access.data or []
            access_rows = []

            for access_row in access_rows_raw:
                row_email = str(access_row.get('wp_user_email') or '').strip().lower()

                if row_email == user_email:
                    access_rows.append(access_row)

            operational_manager = _resolve_operational_manager_identity(
                access_rows,
                cliente_id=cliente_id,
                holding_id=holding_id,
                empresa_id=empresa_id,
                filial_id=filial_id
            )

            requested_is_top_marker = (
                _is_top_hierarchy_marker(manager_name)
                or _is_top_hierarchy_marker(manager_code)
            )

            if operational_manager and (
                requested_is_top_marker
                or (not manager_email and not manager_name and not manager_code)
            ):
                manager_email = str(operational_manager.get('manager_email') or '').strip()
                manager_name = str(operational_manager.get('manager_name') or '').strip()
                manager_code = str(operational_manager.get('manager_code') or '').strip()

            acesso_gestor_ok = False

            for access_row in access_rows:
                access_cliente_id = str(access_row.get('cliente_id') or '').strip()
                access_holding_id = str(access_row.get('holding_id') or '').strip()
                access_empresa_id = str(access_row.get('empresa_id') or '').strip()
                access_filial_id = str(access_row.get('filial_id') or '').strip()

                access_manager_name = str(access_row.get('manager_name') or '').strip().lower()
                access_manager_code = str(access_row.get('manager_code') or '').strip().lower()
                access_wp_email = str(access_row.get('wp_user_email') or '').strip().lower()

                pode_gestor = bool(access_row.get('pode_ver_gestor_avaliacao'))
                pode_admin = bool(access_row.get('pode_administrar'))

                contexto_ok = True

                if cliente_id and access_cliente_id and access_cliente_id != cliente_id:
                    contexto_ok = False

                if holding_id and access_holding_id and access_holding_id != holding_id:
                    contexto_ok = False

                if empresa_id and access_empresa_id and access_empresa_id != empresa_id:
                    contexto_ok = False

                if filial_id and access_filial_id and access_filial_id != filial_id:
                    contexto_ok = False

                gestor_ok = False
                gestor_operacional_ok = False

                if manager_email and access_wp_email and access_wp_email == manager_email.strip().lower():
                    gestor_ok = True

                if manager_name and access_manager_name and access_manager_name == manager_name.strip().lower():
                    gestor_ok = True

                if manager_code and access_manager_code and access_manager_code == manager_code.strip().lower():
                    gestor_ok = True

                if operational_manager:
                    op_manager_email = str(operational_manager.get('manager_email') or '').strip().lower()
                    op_manager_name = str(operational_manager.get('manager_name') or '').strip().lower()
                    op_manager_code = str(operational_manager.get('manager_code') or '').strip().lower()

                    if manager_email and op_manager_email and op_manager_email == manager_email.strip().lower():
                        gestor_operacional_ok = True

                    if manager_name and op_manager_name and op_manager_name == manager_name.strip().lower():
                        gestor_operacional_ok = True

                    if manager_code and op_manager_code and op_manager_code == manager_code.strip().lower():
                        gestor_operacional_ok = True

                if pode_admin and contexto_ok:
                    acesso_gestor_ok = True
                    break

                if pode_gestor and contexto_ok and (gestor_ok or gestor_operacional_ok):
                    acesso_gestor_ok = True
                    break

            if not acesso_gestor_ok:
                return jsonify({
                    'success': False,
                    'error': 'acesso_gestor_negado',
                    'message': 'Usuario sem permissao para consultar este gestor.'
                }), 403
        
        
        r_emp = q_emp.execute()
        employees_raw = r_emp.data or []
        
        def norm_txt(value):
            return str(value or '').strip().lower()
        
        manager_email_norm = norm_txt(manager_email)
        manager_name_norm = norm_txt(manager_name)
        manager_code_norm = norm_txt(manager_code)
        
        employees = []
        
        for emp in employees_raw:
            match_email = manager_email_norm and norm_txt(emp.get('emailLider')) == manager_email_norm
            match_name = manager_name_norm and norm_txt(emp.get('manager_name')) == manager_name_norm
            match_code = manager_code_norm and norm_txt(emp.get('manager_code')) == manager_code_norm
        
            if match_email or match_name or match_code:
                employees.append(emp)
        

        
        if not employees:
            return jsonify({
                'success': True,
                'round_code': round_code,
                'manager': {
                    'manager_email': manager_email,
                    'manager_name': manager_name,
                    'manager_code': manager_code
                },
                'items': []
            }), 200

        employees_by_id = {
            emp.get('id'): emp
            for emp in employees
            if emp.get('id') is not None
        }

        employee_ids = list(employees_by_id.keys())

        # 2) Buscar avaliações YE desses profissionais
        r_eval = (
            supabase
            .table('evaluations')
            .select(
                'id, employee_id, evaluator_id, evaluation_year, evaluation_date, status, '
                'final_rating, nine_box_position, performance_rating, potential_rating, '
                'round_code, cliente_id, empresa_id, filial_id, created_at'
            )
            .eq('round_code', round_code)
            .in_('employee_id', employee_ids)
            .order('id', desc=True)
            .execute()
        )

        evaluations = r_eval.data or []

        if not evaluations:
            return jsonify({
                'success': True,
                'round_code': round_code,
                'manager': {
                    'manager_email': manager_email,
                    'manager_name': manager_name,
                    'manager_code': manager_code
                },
                'items': []
            }), 200

        evaluation_ids = [
            ev.get('id')
            for ev in evaluations
            if ev.get('id') is not None
        ]

        # 3) Buscar workflows
        workflows_by_evaluation_id = {}

        if evaluation_ids:
            r_wf = (
                supabase
                .table('evaluation_workflows')
                .select('*')
                .in_('evaluation_id', evaluation_ids)
                .execute()
            )

            for wf in (r_wf.data or []):
                workflows_by_evaluation_id[wf.get('evaluation_id')] = wf

        # 4) Montar retorno
        items = []

        for ev in evaluations:
            emp = employees_by_id.get(ev.get('employee_id')) or {}
            wf = workflows_by_evaluation_id.get(ev.get('id'))

            if _is_demo_workflow_row(wf) and not include_demo_rows:
                continue

            items.append({
                'evaluation_id': ev.get('id'),
                'employee_id': ev.get('employee_id'),
                'employee_name': emp.get('nome'),
                'employee_email': emp.get('email'),
                'cargo': emp.get('cargo'),
                'company_name': emp.get('company_name') or emp.get('empresa'),
                'branch_name': emp.get('branch_name'),
                'department_name': emp.get('department_name'),
                'manager_name': emp.get('manager_name'),
                'manager_email': emp.get('emailLider'),
                'round_code': ev.get('round_code'),
                'evaluation_year': ev.get('evaluation_year'),
                'final_rating': ev.get('final_rating'),
                'nine_box_position': ev.get('nine_box_position'),
                'performance_rating': ev.get('performance_rating'),
                'potential_rating': ev.get('potential_rating'),
                'workflow_status': wf.get('status_workflow') if wf else None,
                'workflow': wf
            })

        return jsonify({
            'success': True,
            'round_code': round_code,
            'manager': {
                'manager_email': manager_email,
                'manager_name': manager_name,
                'manager_code': manager_code
            },
            'items': items
        }), 200

    except Exception as e:
        print('[api_list_manager_workflow_evaluations] erro:', e)
        return jsonify({
            'success': False,
            'error': 'manager_workflow_evaluations_failed',
            'detail': str(e)
        }), 500


@app.route('/api/employee/workflow/evaluations', methods=['GET', 'OPTIONS'])
def api_list_employee_workflow_evaluations():
    """
    Lista avaliacoes do profissional logado.
    Usado pela pagina Minha Avaliacao / Ciencia.
    Acesso validado por user_email na tabela usuarios_acessos.
    """
    if request.method == 'OPTIONS':
        return ('', 204)

    try:
        user_email = (request.args.get('user_email') or '').strip().lower()
        round_code = (request.args.get('round_code') or '').strip()

        cliente_id = (request.args.get('cliente_id') or '').strip()
        holding_id = (request.args.get('holding_id') or '').strip()
        empresa_id = (request.args.get('empresa_id') or '').strip()
        filial_id = (request.args.get('filial_id') or '').strip()
        include_demo_rows = _workflow_include_demo_rows()

        if not user_email:
            return jsonify({
                'success': False,
                'error': 'user_email_obrigatorio',
                'message': 'Informe user_email para listar as avaliacoes do profissional.'
            }), 400

        # 1) Buscar acesso ativo do usuario
        q_access = (
            supabase
            .table('usuarios_acessos')
            .select(
                'id, wp_user_email, perfil, cliente_id, holding_id, empresa_id, filial_id, '
                'employee_id, pode_ver_ciencia_avaliacao, pode_administrar, status'
            )
            .eq('status', 'ativo')
            .execute()
        )

        access_rows_raw = q_access.data or []
        access_rows = []

        for access_row in access_rows_raw:
            row_email = str(access_row.get('wp_user_email') or '').strip().lower()

            if row_email != user_email:
                continue

            row_cliente_id = str(access_row.get('cliente_id') or '').strip()
            row_holding_id = str(access_row.get('holding_id') or '').strip()
            row_empresa_id = str(access_row.get('empresa_id') or '').strip()
            row_filial_id = str(access_row.get('filial_id') or '').strip()

            contexto_ok = True

            if cliente_id and row_cliente_id and row_cliente_id != cliente_id:
                contexto_ok = False

            if holding_id and row_holding_id and row_holding_id != holding_id:
                contexto_ok = False

            if empresa_id and row_empresa_id and row_empresa_id != empresa_id:
                contexto_ok = False

            if filial_id and row_filial_id and row_filial_id != filial_id:
                contexto_ok = False

            is_admin_fallback = (
                not row_holding_id
                and not row_empresa_id
                and not row_filial_id
                and bool(access_row.get('pode_administrar'))
            )

            if contexto_ok or is_admin_fallback:
                access_rows.append(access_row)

        if not access_rows:
            return jsonify({
                'success': False,
                'error': 'acesso_nao_encontrado',
                'message': 'Nenhum acesso ativo encontrado para este usuario neste contexto.'
            }), 404

        def access_score(row):
            score = 0

            if holding_id and str(row.get('holding_id') or '').strip() == holding_id:
                score += 10

            if empresa_id and str(row.get('empresa_id') or '').strip() == empresa_id:
                score += 5

            if filial_id and str(row.get('filial_id') or '').strip() == filial_id:
                score += 3

            if row.get('pode_administrar'):
                score += 1

            return score

        access_rows = sorted(access_rows, key=access_score, reverse=True)
        access = access_rows[0]

        pode_ciencia = bool(access.get('pode_ver_ciencia_avaliacao'))
        pode_admin = bool(access.get('pode_administrar'))
        employee_id = access.get('employee_id')

        if not pode_ciencia and not pode_admin:
            return jsonify({
                'success': False,
                'error': 'acesso_ciencia_negado',
                'message': 'Usuario sem permissao para consultar avaliacoes como profissional.'
            }), 403

        if not employee_id and not pode_admin:
            return jsonify({
                'success': False,
                'error': 'employee_id_nao_configurado',
                'message': 'Acesso encontrado, mas sem employee_id configurado.'
            }), 400

        # 2) Buscar avaliacoes do profissional
        q_eval = (
            supabase
            .table('evaluations')
            .select(
                'id, employee_id, evaluation_year, evaluation_date, status, final_rating, '
                'nine_box_position, performance_rating, potential_rating, round_code, '
                'cliente_id, empresa_id, filial_id, created_at'
            )
        )

        if employee_id:
            q_eval = q_eval.eq('employee_id', employee_id)

        if round_code:
            q_eval = q_eval.eq('round_code', round_code)

        if cliente_id:
            q_eval = q_eval.eq('cliente_id', cliente_id)

        if empresa_id:
            q_eval = q_eval.eq('empresa_id', empresa_id)

        if filial_id:
            q_eval = q_eval.eq('filial_id', filial_id)

        r_eval = q_eval.order('id', desc=True).execute()
        evaluations = r_eval.data or []

        # 3) Se houver holding_id, filtrar via employees
        employee_ids = list({
            ev.get('employee_id')
            for ev in evaluations
            if ev.get('employee_id') is not None
        })

        employees_by_id = {}

        if employee_ids:
            q_emp = (
                supabase
                .table('employees')
                .select(
                    'id, nome, cargo, email, company_name, branch_name, department_name, '
                    'manager_name, holding_id, empresa_id, filial_id'
                )
                .in_('id', employee_ids)
            )

            r_emp = q_emp.execute()

            for emp in (r_emp.data or []):
                employees_by_id[emp.get('id')] = emp

        items = []

        for ev in evaluations:
            emp = employees_by_id.get(ev.get('employee_id')) or {}

            if holding_id:
                emp_holding_id = str(emp.get('holding_id') or '').strip()

                if emp_holding_id and emp_holding_id != holding_id:
                    continue

            # Buscar workflow da avaliacao
            workflow = None

            r_wf = (
                supabase
                .table('evaluation_workflows')
                .select('*')
                .eq('evaluation_id', ev.get('id'))
                .limit(1)
                .execute()
            )

            wf_rows = r_wf.data or []
            workflow = wf_rows[0] if wf_rows else None

            if _is_demo_workflow_row(workflow) and not include_demo_rows:
                continue

            items.append({
                'evaluation_id': ev.get('id'),
                'employee_id': ev.get('employee_id'),
                'employee_name': emp.get('nome'),
                'employee_email': emp.get('email'),
                'cargo': emp.get('cargo'),
                'company_name': emp.get('company_name'),
                'branch_name': emp.get('branch_name'),
                'department_name': emp.get('department_name'),
                'manager_name': emp.get('manager_name'),
                'evaluation_year': ev.get('evaluation_year'),
                'evaluation_date': ev.get('evaluation_date'),
                'round_code': ev.get('round_code'),
                'final_rating': ev.get('final_rating'),
                'nine_box_position': ev.get('nine_box_position'),
                'performance_rating': ev.get('performance_rating'),
                'potential_rating': ev.get('potential_rating'),
                'workflow_status': workflow.get('status_workflow') if workflow else None,
                'workflow': workflow
            })

        return jsonify({
            'success': True,
            'user_email': user_email,
            'access': access,
            'round_code': round_code,
            'items': items
        }), 200

    except Exception as e:
        print('[api_list_employee_workflow_evaluations] erro:', e)
        return jsonify({
            'success': False,
            'error': 'employee_workflow_evaluations_failed',
            'detail': str(e)
        }), 500



if __name__ == '__main__':
    app.run(debug=True)

