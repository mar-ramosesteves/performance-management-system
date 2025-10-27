from flask import Flask, render_template, request, jsonify
import os
import json
from datetime import datetime
from supabase import create_client, Client

from datetime import datetime, timezone

import base64, hmac, hashlib, time
from urllib.parse import urlencode
from flask import make_response


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

# ===================== Configurações / Conexão =====================
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
ADMIN_WINDOW_CODE = os.getenv('ADMIN_WINDOW_CODE', '').strip()  # usado em PUTs protegidos

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

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

@app.route('/api/employees/manager', methods=['GET'])
def get_employees_by_manager():
    """
    Retorna somente os funcionários cujo manager_name corresponde ao nome informado.
    Uso: GET /api/employees/manager?name=NOME%20EXATO%20DO%20GESTOR
    """
    try:
        name = request.args.get('name', '').strip()
        if not name:
            return jsonify({'error': "Parâmetro 'name' é obrigatório (manager_name)."}), 400

        # Case-insensitive (ILIKE). Se você sempre copia e cola o nome exato, também funcionaria com eq.
        r = (
            supabase
            .table('employees')
            .select('*')
            .ilike('manager_name', name)   # sem % vira comparação case-insensitive exata
            .execute()
        )

        return jsonify(r.data or [])
    except Exception as e:
        print(f"Erro no endpoint /api/employees/manager: {str(e)}")
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
        data = request.get_json()
        r = supabase.table('employees').insert(data).execute()
        return jsonify(r.data)
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

        goal_ratings = [float(g['rating']) for g in (goals_data or []) if g.get('rating') is not None]
        metas_avg = sum(goal_ratings) / len(goal_ratings) if goal_ratings else 0

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
         .select('evaluation_id,criteria_id,rating')
         .eq('evaluation_id', evaluation_id)
         .order('criteria_id', desc=False)
         .execute())
    rows = r.data or []
    return [{
        'evaluation_id': x.get('evaluation_id'),
        'criteria_id': x.get('criteria_id'),
        'rating': x.get('rating')
    } for x in rows]

@app.route('/api/evaluations/latest', methods=['GET'])
def api_evaluations_latest():
    try:
        employee_id = request.args.get('employee_id', type=int)
        if not employee_id:
            return jsonify({'error': 'employee_id obrigatório'}), 400

        # Buscar avaliação
        r_ev = (supabase.table('evaluations')
                .select('*')
                .eq('employee_id', employee_id)
                .order('evaluation_date', desc=True)
                .order('created_at', desc=True)
                .limit(1)
                .execute())
        data = r_ev.data or []
        if not data:
            return jsonify({'error': 'nenhuma_avaliacao'}), 404
        ev = data[0]

        # Buscar respostas
        r_resp = (supabase.table('evaluation_responses')
                  .select('evaluation_id,criteria_id,rating')
                  .eq('evaluation_id', ev['id'])
                  .order('criteria_id', desc=False)
                  .execute())
        rows = r_resp.data or []

        responses = [{
            'evaluation_id': x.get('evaluation_id'),
            'criteria_id': x.get('criteria_id'),
            'rating': x.get('rating')
        } for x in rows]

        # Buscar metas da tabela individual_goals (sem evaluation_id)
        goals = []
        try:
            r_goals = (supabase.table('individual_goals')
                       .select('*')
                       .eq('employee_id', employee_id)
                       .execute())
            goals_data = r_goals.data or []
            
            # Converter para formato esperado pelo frontend
            for goal in goals_data:
                goals.append({
                    'index': goal.get('goal_index', 1),
                    'name': goal.get('goal_name', ''),
                    'description': goal.get('goal_description', ''),
                    'weight': float(goal.get('weight', 0)),
                    'rating_1_criteria': goal.get('rating_1_criteria', ''),
                    'rating_2_criteria': goal.get('rating_2_criteria', ''),
                    'rating_3_criteria': goal.get('rating_3_criteria', ''),
                    'rating_4_criteria': goal.get('rating_4_criteria', ''),
                    'rating_5_criteria': goal.get('rating_5_criteria', ''),
                    'rating': int(goal.get('rating', 0)) if goal.get('rating') else None
                })
        except Exception as e:
            print(f"Erro ao buscar metas: {e}")
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

# ===================== Evaluations CRUD =====================
@app.route('/api/evaluations', methods=['GET'])
def get_evaluations():
    try:
        r = supabase.table('evaluations').select('*').execute()
        return jsonify(r.data)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/evaluations', methods=['POST'])
def create_evaluation():
    try:
        data = request.get_json()

        # --- BLOQUEIO POR JANELA (usa helper is_window_open) ---
        # Se a janela NÃO estiver aberta, só permite salvar se vier o código do RH no body
        # ex.: { ..., "code": "SEU_ADMIN_WINDOW_CODE" }
        open_now, _, _, _ = is_window_open()
        override_code = (data.get('code') or '').strip()
        if not open_now:
            if not ADMIN_WINDOW_CODE or override_code != ADMIN_WINDOW_CODE:
                return jsonify({'error': 'Janela de avaliação fechada'}), 403
        # --- fim do bloqueio ---

        if not data.get('employee_id') or not data.get('responses'):
            return jsonify({'error': 'Dados obrigatórios não fornecidos'}), 400


        # DEBUG: verificar se round_code está chegando
        print(f"DEBUG: round_code recebido: {data.get('round_code')}")
        print(f"DEBUG: dados completos: {data}")
        evaluation_data = {
           'employee_id': data['employee_id'],
           'evaluator_id': data.get('evaluator_id', 1),
           'evaluation_year': data.get('evaluation_year', 2025),
           'round_code': data.get('round_code'),  # NOVO: código da rodada
           'dimension_weights': data.get('dimension_weights', {}),
           'dimension_averages': data.get('dimension_averages', {}),
           'final_rating': data.get('final_rating'),
           'goals_average': data.get('goals_average')
       }
        
        # Verificar se já existe avaliação para este funcionário no ano
        existing_eval = supabase.table('evaluations').select('id').eq('employee_id', data['employee_id']).eq('evaluation_year', data.get('evaluation_year', 2025)).execute()
        
        if existing_eval.data:
            # Atualizar avaliação existente
            evaluation_id = existing_eval.data[0]['id']
            supabase.table('evaluations').update(evaluation_data).eq('id', evaluation_id).execute()
            print(f"DEBUG: Avaliação {evaluation_id} atualizada")
        else:
            # Criar nova avaliação
            evaluation_response = supabase.table('evaluations').insert(evaluation_data).execute()
            if not evaluation_response.data:
                return jsonify({'error': 'Erro ao criar avaliação'}), 500
            evaluation_id = evaluation_response.data[0]['id']
            print(f"DEBUG: Nova avaliação {evaluation_id} criada")

        responses = []
        for criteria_id, rating in data['responses'].items():
            responses.append({
                'evaluation_id': evaluation_id,
                'criteria_id': int(criteria_id),
                'rating': int(rating)
            })
        if responses:
            supabase.table('evaluation_responses').insert(responses).execute()
            
        # Limpar metas antigas do funcionário
        try:
            supabase.table('individual_goals').delete().eq('employee_id', data['employee_id']).execute()
            print(f"Metas antigas deletadas para funcionário {data['employee_id']}")
        except Exception as e:
            print(f"Erro ao deletar metas antigas: {e}")

        # Salvar metas na tabela individual_goals
        if data.get('goals'):
            goals_to_save = []
            for goal in data['goals']:
                goals_to_save.append({
                    'employee_id': data['employee_id'],
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

        return jsonify({'evaluation_id': evaluation_id, 'message': 'Avaliação salva com sucesso!'})
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
        r = supabase.table('dimension_weights').select('*').execute()
        return jsonify(r.data)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/dimension-weights', methods=['PUT'])
def update_dimension_weights():
    try:
        data = request.get_json()
        for weight_data in data:
            supabase.table('dimension_weights').update({
                'weight': weight_data['weight']
            }).eq('dimension', weight_data['dimension']).execute()
        return jsonify({'message': 'Pesos atualizados com sucesso'})
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
             .single()
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
            .single()
            .execute()
        )
        if not r.data:
            return jsonify({'error': 'Funcionário não encontrado'}), 404
        return jsonify(r.data), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/employees/<int:employee_id>', methods=['PUT'])
def update_employee(employee_id):
    try:
        payload = request.get_json(force=True) or {}

        # Campos que permitimos atualizar
        allowed = {
            'nome','cargo','empresa','salario',              # já existentes
            'manager_name','admission_date','birth_date',    # novos
            'company_name','branch_name','department_name',
            'employment_status','leave_reason'
        }
        data = {k: v for k, v in payload.items() if k in allowed}

        if not data:
            return jsonify({'error': 'Nenhum campo válido informado'}), 400

        supabase.table('employees').update(data).eq('id', employee_id).execute()
        return jsonify({'updated': True, 'employee_id': employee_id}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


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

if __name__ == '__main__':
    app.run(debug=True)
