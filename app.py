from flask import Flask, render_template, request, jsonify
import os
import json
from supabase import create_client, Client

app = Flask(__name__)

# Configuração do Supabase
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
EVAL_PERIOD = os.getenv('EVAL_PERIOD', '082025')  # use o seu código de período (ex.: 082025)
ADMIN_WINDOW_CODE = os.getenv('ADMIN_WINDOW_CODE')


# Inicializar cliente Supabase
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/employees', methods=['GET'])
def get_employees():
    try:
        response = supabase.table('employees').select('*').execute()
        return jsonify(response.data)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/employees', methods=['POST'])
def create_employee():
    try:
        data = request.get_json()
        response = supabase.table('employees').insert(data).execute()
        return jsonify(response.data)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/salary-grades', methods=['GET'])
def get_salary_grades():
    try:
        response = supabase.table('salary_grades').select('*').execute()
        return jsonify(response.data)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/evaluation-criteria', methods=['GET'])
def get_evaluation_criteria():
    try:
        response = supabase.table('evaluation_criteria').select('*').order('dimension', desc=False).execute()
        return jsonify(response.data)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/evaluation-criteria', methods=['POST'])
def create_evaluation_criteria():
    try:
        data = request.get_json()
        response = supabase.table('evaluation_criteria').insert(data).execute()
        return jsonify(response.data)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/evaluation-criteria/<int:criteria_id>', methods=['PUT'])
def update_evaluation_criteria(criteria_id):
    try:
        data = request.get_json()
        response = supabase.table('evaluation_criteria').update(data).eq('id', criteria_id).execute()
        return jsonify(response.data)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

def calculate_evaluation_scores(evaluation_id, responses, goals_data, dimension_weights):
    """Calcula as notas por dimensão e nota final"""
    try:
        print(f"DEBUG: calculate_evaluation_scores chamada com evaluation_id={evaluation_id}")
        print(f"DEBUG: responses={responses}")
        print(f"DEBUG: goals_data={goals_data}")
        print(f"DEBUG: dimension_weights={dimension_weights}")
        
        # Buscar critérios para agrupar por dimensão
        criteria_response = supabase.table('evaluation_criteria').select('*').execute()
        criteria = {c['id']: c for c in criteria_response.data}
        
        # Agrupar respostas por dimensão
        dimension_ratings = {
            'INSTITUCIONAL': [],
            'FUNCIONAL': [],
            'INDIVIDUAL': []
        }
        
        for criteria_id, rating in responses.items():
            if int(criteria_id) in criteria:
                dimension = criteria[int(criteria_id)]['dimension']
                dimension_ratings[dimension].append(rating)
        
        # Calcular médias por dimensão
        institucional_avg = sum(dimension_ratings['INSTITUCIONAL']) / len(dimension_ratings['INSTITUCIONAL']) if dimension_ratings['INSTITUCIONAL'] else 0
        funcional_avg = sum(dimension_ratings['FUNCIONAL']) / len(dimension_ratings['FUNCIONAL']) if dimension_ratings['FUNCIONAL'] else 0
        individual_avg = sum(dimension_ratings['INDIVIDUAL']) / len(dimension_ratings['INDIVIDUAL']) if dimension_ratings['INDIVIDUAL'] else 0
        
        # Calcular média das metas
        goal_ratings = [g['rating'] for g in goals_data if g.get('rating')]
        metas_avg = sum(goal_ratings) / len(goal_ratings) if goal_ratings else 0
        
        # Calcular rating final ponderado
        final_rating = (
            institucional_avg * (dimension_weights.get('INSTITUCIONAL', 0) / 100) +
            funcional_avg * (dimension_weights.get('FUNCIONAL', 0) / 100) +
            individual_avg * (dimension_weights.get('INDIVIDUAL', 0) / 100) +
            metas_avg * (dimension_weights.get('METAS', 0) / 100)
        )
        
        # Calcular ratings para matriz 9-box
        # Performance = média de todos os critérios de DESEMPENHO
        performance_ratings = []
        potential_ratings = []
        
        for criteria_id, rating in responses.items():
            if int(criteria_id) in criteria:
                criteria_type = criteria[int(criteria_id)]['type']
                if criteria_type == 'DESEMPENHO':
                    performance_ratings.append(rating)
                elif criteria_type == 'POTENCIAL':
                    potential_ratings.append(rating)
        
        performance_rating = sum(performance_ratings) / len(performance_ratings) if performance_ratings else 0
        potential_rating = sum(potential_ratings) / len(potential_ratings) if potential_ratings else 0
        
        print(f"DEBUG: performance_rating={performance_rating}, potential_rating={potential_rating}")
        
        # Calcular posição na matriz 9-box usando a tabela de correlação
        nine_box_position = calculate_nine_box_position(performance_rating, potential_rating)
        
        # Converter os ratings para valores 9-box (1-9)
        def rating_to_9box(rating):
            """Converte rating (1-5) para 9-box (1-9) usando a tabela de correlação"""
            rounded_rating = round(rating, 1)
            correlation_table = {
                1.0: 9.0, 1.1: 8.8, 1.2: 8.6, 1.3: 8.4, 1.4: 8.2, 1.5: 8.0,
                1.6: 7.8, 1.7: 7.6, 1.8: 7.4, 1.9: 7.2, 2.0: 7.0, 2.1: 6.8,
                2.2: 6.6, 2.3: 6.4, 2.4: 6.2, 2.5: 6.0, 2.6: 5.8, 2.7: 5.6,
                2.8: 5.4, 2.9: 5.2, 3.0: 5.0, 3.1: 4.8, 3.2: 4.6, 3.3: 4.4,
                3.4: 4.2, 3.5: 4.0, 3.6: 3.8, 3.7: 3.6, 3.8: 3.4, 3.9: 3.2,
                4.0: 3.0, 4.1: 2.8, 4.2: 2.6, 4.3: 2.4, 4.4: 2.2, 4.5: 2.0,
                4.6: 1.8, 4.7: 1.6, 4.8: 1.4, 4.9: 1.2, 5.0: 1.0
            }
            if rounded_rating in correlation_table:
                return correlation_table[rounded_rating]
            else:
                return 10 - (rounded_rating * 2)
        
        # Converter para valores 9-box
        performance_9box = rating_to_9box(performance_rating)
        potential_9box = rating_to_9box(potential_rating)
        
        print(f"DEBUG: performance_rating convertido: {performance_rating} -> {performance_9box}")
        print(f"DEBUG: potential_rating convertido: {potential_rating} -> {potential_9box}")
        
        return {
            'institucional_avg': round(institucional_avg, 2),
            'funcional_avg': round(funcional_avg, 2),
            'individual_avg': round(individual_avg, 2),
            'metas_avg': round(metas_avg, 2),
            'final_rating': round(final_rating, 2),
            'performance_rating': round(performance_9box, 2),  # Salvar valor convertido (1-9)
            'potential_rating': round(potential_9box, 2),      # Salvar valor convertido (1-9)
            'nine_box_position': nine_box_position
        }
        
    except Exception as e:
        print(f"Erro ao calcular scores: {e}")
        return None

def calculate_nine_box_position(performance, potential):
    """Calcula a posição na matriz 9-box baseada na tabela de correlação"""
    
    def rating_to_9box(rating):
        """Converte rating (1-5) para 9-box (1-9) usando a tabela de correlação"""
        rounded_rating = round(rating, 1)
        
        correlation_table = {
            1.0: 9.0, 1.1: 8.8, 1.2: 8.6, 1.3: 8.4, 1.4: 8.2, 1.5: 8.0,
            1.6: 7.8, 1.7: 7.6, 1.8: 7.4, 1.9: 7.2, 2.0: 7.0, 2.1: 6.8,
            2.2: 6.6, 2.3: 6.4, 2.4: 6.2, 2.5: 6.0, 2.6: 5.8, 2.7: 5.6,
            2.8: 5.4, 2.9: 5.2, 3.0: 5.0, 3.1: 4.8, 3.2: 4.6, 3.3: 4.4,
            3.4: 4.2, 3.5: 4.0, 3.6: 3.8, 3.7: 3.6, 3.8: 3.4, 3.9: 3.2,
            4.0: 3.0, 4.1: 2.8, 4.2: 2.6, 4.3: 2.4, 4.4: 2.2, 4.5: 2.0,
            4.6: 1.8, 4.7: 1.6, 4.8: 1.4, 4.9: 1.2, 5.0: 1.0
        }
        
        if rounded_rating in correlation_table:
            return correlation_table[rounded_rating]
        else:
            return 10 - (rounded_rating * 2)
    
    # Converter ratings para valores 9-box
    performance_9box = rating_to_9box(performance)
    potential_9box = rating_to_9box(potential)
    
    # CORREÇÃO: Usar a tabela de correlação para determinar as posições
    # Baseado na tabela: 1-3=Baixo, 4-6=Médio, 7-9=Alto
    
    # Determinar posição de Performance (1-3)
    if performance_9box >= 7:
        perf_pos = 1  # Alto Desempenho
    elif performance_9box >= 4:
        perf_pos = 2  # Médio Desempenho
    else:
        perf_pos = 3  # Baixo Desempenho
    
    # Determinar posição de Potencial (1-3)
    if potential_9box >= 7:
        pot_pos = 1  # Alto Potencial
    elif potential_9box >= 4:
        pot_pos = 2  # Médio Potencial
    else:
        pot_pos = 3  # Baixo Potencial
    
    # Calcular posição final na matriz 9-box (1-9)
    # Matriz: (potencial - 1) * 3 + (4 - performance)
    nine_box_position = (pot_pos - 1) * 3 + (4 - perf_pos)
    
    return nine_box_position
    
    # ===== Helpers para buscar a ÚLTIMA avaliação preenchida =====
def _to_num(v, default=None):
    try:
        return float(v)
    except Exception:
        return default

def _get_latest_evaluation(employee_id: int):
    """Busca a avaliação mais recente do funcionário."""
    r = (supabase.table('evaluations')
         .select('*')
         .eq('employee_id', employee_id)
         .order('evaluation_date', desc=True)
         .order('created_at', desc=True)
         .limit(1)
         .execute())
    data = r.data or []
    return data[0] if data else None

def _get_responses_rows(evaluation_id: int):
    """Retorna linhas de evaluation_responses usando apenas 'rating' (sem 'score')."""
    r = (supabase.table('evaluation_responses')
         .select('evaluation_id, criteria_id, rating')   # ⬅️ score removido
         .eq('evaluation_id', evaluation_id)
         .order('criteria_id', desc=False)
         .execute())
    rows = r.data or []
    return [{
        'evaluation_id': x.get('evaluation_id'),
        'criteria_id': x.get('criteria_id'),
        'rating': x.get('rating')   # ⬅️ só rating
    } for x in rows]


def _extract_weights(ev: dict):
    """Extrai pesos das dimensões (aceita JSON na coluna ou colunas soltas)."""
    w = ev.get('dimension_weights') or ev.get('weights')
    if isinstance(w, str):
        try:
            w = json.loads(w)
        except Exception:
            w = None
    if isinstance(w, dict):
        up = {str(k).upper(): v for k, v in w.items()}
        return {
            'INSTITUCIONAL': _to_num(up.get('INSTITUCIONAL'), 25),
            'FUNCIONAL':     _to_num(up.get('FUNCIONAL'), 25),
            'INDIVIDUAL':    _to_num(up.get('INDIVIDUAL'), 25),
            'METAS':         _to_num(up.get('METAS'), 25),
        }
    # Fallback: colunas separadas na tabela evaluations
    return {
        'INSTITUCIONAL': _to_num(ev.get('weight_institucional'), 25),
        'FUNCIONAL':     _to_num(ev.get('weight_funcional'), 25),
        'INDIVIDUAL':    _to_num(ev.get('weight_individual'), 25),
        'METAS':         _to_num(ev.get('weight_metas'), 25),
    }

def _extract_goals(ev: dict):
    """Extrai metas se você salva JSON na própria avaliação (opcional)."""
    g = ev.get('goals') or ev.get('individual_goals')
    if isinstance(g, str):
        try:
            g = json.loads(g)
        except Exception:
            g = None
    return g if isinstance(g, list) else []

# ===== Rotas novas =====

@app.route('/api/evaluations/latest', methods=['GET'])
def api_evaluations_latest():
    try:
        employee_id = request.args.get('employee_id', type=int)
        if not employee_id:
            return jsonify({'error': 'employee_id obrigatório'}), 400

        # 1) última avaliação
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

        # 2) responses
        try:
            r_resp = (supabase.table('evaluation_responses')
                      .select('evaluation_id, criteria_id, rating')  # ⬅️ score removido
                      .eq('evaluation_id', ev['id'])
                      .order('criteria_id', desc=False)
                      .execute())
            rows = r_resp.data or []
            responses = [{
                'evaluation_id': x.get('evaluation_id'),
                'criteria_id': x.get('criteria_id'),
                'rating': x.get('rating')
            } for x in rows]
        except Exception as e:
            return jsonify({
                'error': 'erro_ao_buscar_responses',
                'detail': str(e)
            }), 500


        # 3) pesos/metas (se tiver)
        import json as _json
        w = ev.get('dimension_weights') or ev.get('weights')
        if isinstance(w, str):
            try:
                w = _json.loads(w)
            except Exception:
                w = None
        if isinstance(w, dict):
            up = {str(k).upper(): v for k, v in w.items()}
            weights = {
                'INSTITUCIONAL': float(up.get('INSTITUCIONAL', 25) or 25),
                'FUNCIONAL':     float(up.get('FUNCIONAL', 25) or 25),
                'INDIVIDUAL':    float(up.get('INDIVIDUAL', 25) or 25),
                'METAS':         float(up.get('METAS', 25) or 25),
            }
        else:
            weights = {
                'INSTITUCIONAL': float(ev.get('weight_institucional') or 25),
                'FUNCIONAL':     float(ev.get('weight_funcional') or 25),
                'INDIVIDUAL':    float(ev.get('weight_individual') or 25),
                'METAS':         float(ev.get('weight_metas') or 25),
            }

        g = ev.get('goals') or ev.get('individual_goals')
        if isinstance(g, str):
            try:
                g = _json.loads(g)
            except Exception:
                g = None
        goals = g if isinstance(g, list) else []

        return jsonify({
            'evaluation': ev,
            'responses': responses,
            'weights': weights,
            'goals': goals
        })

    except Exception as e:
        # retorna o erro textual pra gente saber a causa
        return jsonify({'error': 'internal', 'detail': str(e)}), 500

# (Opcional) Mantém compatibilidade se o front ainda chamar esta rota
@app.route('/api/evaluation-responses', methods=['GET'])
def api_evaluation_responses():
    evaluation_id = request.args.get('evaluation_id', type=int)
    if not evaluation_id:
        return jsonify({'error': 'evaluation_id obrigatório'}), 400
    return jsonify(_get_responses_rows(evaluation_id))


@app.route('/api/evaluations', methods=['GET'])
def get_evaluations():
    try:
        response = supabase.table('evaluations').select('*').execute()
        return jsonify(response.data)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/evaluations', methods=['POST'])
def create_evaluation():
    try:
        data = request.get_json()
        print(f"Dados recebidos: {data}")  # Para debug
        
        # Verificar se os dados necessários existem
        if not data.get('employee_id') or not data.get('responses'):
            return jsonify({'error': 'Dados obrigatórios não fornecidos'}), 400
        
        # Criar a avaliação básica primeiro
        evaluation_data = {
            'employee_id': data['employee_id'],
            'evaluator_id': data.get('evaluator_id', 1),  # Default 1 se não fornecido
            'evaluation_year': data.get('evaluation_year', 2025)  # Default 2025 se não fornecido
        }
        
        evaluation_response = supabase.table('evaluations').insert(evaluation_data).execute()
        
        if evaluation_response.data:
            evaluation_id = evaluation_response.data[0]['id']
            
            # Criar as respostas da avaliação
            responses = []
            for criteria_id, rating in data['responses'].items():
                response_data = {
                    'evaluation_id': evaluation_id,
                    'criteria_id': int(criteria_id),
                    'rating': int(rating)
                }
                responses.append(response_data)
            
            if responses:
                supabase.table('evaluation_responses').insert(responses).execute()
            
            # Calcular scores se possível
            try:
                scores = calculate_evaluation_scores(
                    evaluation_id,
                    data['responses'],
                    data.get('goals', []),
                    data.get('dimension_weights', {})
                )
                
                # Atualizar avaliação com os scores calculados
                if scores:
                    supabase.table('evaluations').update(scores).eq('id', evaluation_id).execute()
            except Exception as calc_error:
                print(f"Erro ao calcular scores: {calc_error}")
                # Continuar mesmo se o cálculo falhar
            
            return jsonify({
                'evaluation_id': evaluation_id,
                'message': 'Avaliação salva com sucesso!'
            })
        else:
            return jsonify({'error': 'Erro ao criar avaliação'}), 500
            
    except Exception as e:
        print(f"Erro: {e}")  # Para debug
        return jsonify({'error': str(e)}), 500



@app.route('/api/evaluations/<int:evaluation_id>', methods=['GET'])
def get_evaluation(evaluation_id):
    try:
        # Buscar a avaliação
        evaluation_response = supabase.table('evaluations').select('*').eq('id', evaluation_id).execute()
        
        if evaluation_response.data:
            evaluation = evaluation_response.data[0]
            
            # Buscar as respostas
            responses_response = supabase.table('evaluation_responses').select('*').eq('evaluation_id', evaluation_id).execute()
            evaluation['responses'] = responses_response.data
            
            return jsonify(evaluation)
        else:
            return jsonify({'error': 'Avaliação não encontrada'}), 404
            
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/individual-goals', methods=['GET'])
def get_individual_goals():
    try:
        response = supabase.table('individual_goals').select('*').execute()
        return jsonify(response.data)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/individual-goals', methods=['POST'])
def create_individual_goal():
    try:
        data = request.get_json()
        response = supabase.table('individual_goals').insert(data).execute()
        return jsonify(response.data)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/dimension-weights', methods=['GET'])
def get_dimension_weights():
    try:
        response = supabase.table('dimension_weights').select('*').execute()
        return jsonify(response.data)
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

from datetime import datetime

@app.route('/api/current-period', methods=['GET'])
def get_current_period():
    try:
        now = datetime.utcnow().isoformat()
        response = supabase.table('evaluation_periods')\
            .select('*')\
            .lte('start_at', now)\
            .gte('end_at', now)\
            .eq('is_open', True)\
            .limit(1)\
            .execute()
        
        if response.data:
            return jsonify(response.data[0])
        else:
            return jsonify({'error': 'Nenhum período aberto no momento'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# --- Helpers com tratamento de erro para diagnosticar 500 ---
def get_window_row():
    """Lê a VIEW evaluation_windows_status para o período atual."""
    try:
        r = (
            supabase.table('evaluation_windows_status')
            .select('*')
            .eq('period', EVAL_PERIOD)  # EVAL_PERIOD vem do ambiente (ex.: 082025)
            .limit(1)
            .execute()
        )
        rows = r.data or []
        return rows[0] if rows else None
    except Exception as e:
        # Devolve exceção para a rota exibir (temporariamente, só para diagnóstico)
        raise RuntimeError(f'Erro ao ler evaluation_windows_status: {e}')

@app.route('/api/evaluations/window', methods=['GET'])
def api_get_window():
    try:
        w = get_window_row()
        return jsonify({
            'period': EVAL_PERIOD,
            'open': bool(w and w.get('is_open')),
            'start_at': (w or {}).get('start_at'),
            'end_at':   (w or {}).get('end_at'),
            # incluir w bruto ajuda a depurar (remova depois)
            'debug_row': w
        }), 200
    except Exception as e:
        # MOSTRAR O ERRO EXATO no navegador (temporário, para debug)
        return jsonify({'error': str(e)}), 500


# =====================  ADMIN PAINEL SIMPLES  =====================
# Página /admin para abrir/fechar período de avaliações (janela)
# Usa a rota já existente: PUT /api/evaluations/window (com ADMIN_WINDOW_CODE)

@app.route('/admin', methods=['GET'])
def admin_panel():
    # HTML simples, sem template, entrega a página do painel
    html = """
<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width,initial-scale=1" />
<title>Painel de Avaliações — Admin</title>
<style>
  body{font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial;line-height:1.5;margin:0;background:#f7f7fb;color:#111}
  .wrap{max-width:780px;margin:0 auto;padding:28px}
  h1{font-size:22px;margin:0 0 8px}
  .card{background:#fff;border:1px solid #e5e7eb;border-radius:12px;padding:18px;margin-top:16px;box-shadow:0 2px 6px rgba(0,0,0,.05)}
  .row{display:grid;grid-template-columns:1fr 1fr;gap:12px}
  label{display:block;font-size:12px;color:#555;margin-bottom:6px}
  input,button{font:inherit}
  input[type=text], input[type=datetime-local]{width:100%;padding:10px;border:1px solid #d1d5db;border-radius:8px}
  .btn{display:inline-block;padding:10px 14px;border-radius:8px;border:0;cursor:pointer;font-weight:700}
  .btn.primary{background:#2563eb;color:#fff}
  .btn.ghost{background:#f3f4f6}
  .muted{color:#6b7280;font-size:13px}
  .status-pill{display:inline-block;padding:4px 10px;border-radius:999px;font-size:12px;font-weight:700}
  .ok{background:#e7f9ee;color:#0a7b31;border:1px solid #b7efc8}
  .warn{background:#fff6e6;color:#a15c00;border:1px solid #ffe2ae}
  .err{background:#ffecec;color:#a10000;border:1px solid #ffbaba}
  .grid2{display:grid;grid-template-columns:1fr 1fr;gap:12px}
  .footer{margin-top:18px;display:flex;gap:8px;align-items:center}
  code{background:#f3f4f6;border:1px solid #e5e7eb;border-radius:6px;padding:2px 6px}
</style>
</head>
<body>
  <div class="wrap">
    <h1>Painel de Avaliações — Admin</h1>
    <p class="muted">Abra ou feche a janela de avaliações. Use o <strong>código do RH</strong> para confirmar a alteração.</p>

    <div class="card" id="status">
      <div><strong>Status atual</strong></div>
      <div id="status-content" class="muted">Carregando…</div>
    </div>

    <div class="card">
      <div style="margin-bottom:10px"><strong>Atualizar janela</strong></div>
      <div class="grid2">
        <div>
          <label>Período (ex.: 2025H2 ou 082025)</label>
          <input type="text" id="period" placeholder="ex.: 2025H2" />
        </div>
        <div>
          <label>Código RH (ADMIN_WINDOW_CODE)</label>
          <input type="text" id="code" placeholder="ex.: RH-2025-OK" />
        </div>
      </div>
      <div class="row" style="margin-top:10px">
        <div>
          <label>Início (fuso local — será convertido p/ UTC)</label>
          <input type="datetime-local" id="startAt" />
        </div>
        <div>
          <label>Fim (fuso local — será convertido p/ UTC)</label>
          <input type="datetime-local" id="endAt" />
        </div>
      </div>
      <div class="footer">
        <button class="btn primary" id="saveBtn">Salvar janela</button>
        <button class="btn ghost" id="reloadBtn">Recarregar status</button>
        <span id="msg" class="muted"></span>
      </div>
    </div>

    <div class="card">
      <div><strong>Dicas</strong></div>
      <ul class="muted">
        <li><strong>Período</strong> é só uma etiqueta (texto): ex. <code>2025H2</code> ou <code>2025-10</code>.</li>
        <li>Datas são salvas em <strong>UTC</strong>. Os campos acima convertem automaticamente do seu horário local para UTC.</li>
        <li>Se a janela estiver “fechada”, salvamentos no front são bloqueados, a menos que você envie o Código RH no body.</li>
      </ul>
    </div>
  </div>

<script>
  const $ = (sel) => document.querySelector(sel);

  function fmtDate(iso) {
    if (!iso) return '-';
    try { return new Date(iso).toLocaleString(); } catch(e) { return iso; }
  }

  async function loadStatus() {
    $('#status-content').textContent = 'Carregando…';
    try {
      const r = await fetch('/api/evaluations/window');
      const j = await r.json();
      if (r.ok) {
        const pill = j.open
          ? '<span class="status-pill ok">ABERTA</span>'
          : '<span class="status-pill warn">FECHADA</span>';
        $('#status-content').innerHTML = `
          ${pill}<br>
          <strong>Período:</strong> ${j.period || '-'}<br>
          <strong>Início:</strong> ${fmtDate(j.start_at)}<br>
          <strong>Fim:</strong> ${fmtDate(j.end_at)}
        `;
        // preenche campos com valores atuais (se houver)
        if (j.period) $('#period').value = j.period;
        if (j.start_at) {
          const d = new Date(j.start_at);
          $('#startAt').value = d.toISOString().slice(0,16); // yyyy-MM-ddTHH:mm
        }
        if (j.end_at) {
          const d = new Date(j.end_at);
          $('#endAt').value = d.toISOString().slice(0,16);
        }
      } else {
        $('#status-content').innerHTML = '<span class="status-pill err">ERRO</span> ' + (j.error || 'Falha ao carregar status');
      }
    } catch (e) {
      $('#status-content').innerHTML = '<span class="status-pill err">ERRO</span> ' + e;
    }
  }

  function toUTCStringLocal(datetimeLocal) {
    if (!datetimeLocal) return null;
    // datetime-local vem sem timezone; interpretamos como local e convertemos para UTC ISO
    const d = new Date(datetimeLocal);
    return d.toISOString(); // ISO com 'Z'
  }

  async function saveWindow() {
    $('#msg').textContent = 'Salvando…';
    try {
      const period = $('#period').value.trim();
      const code = $('#code').value.trim();
      const startAtLocal = $('#startAt').value;
      const endAtLocal = $('#endAt').value;
      if (!period || !code || !startAtLocal || !endAtLocal) {
        $('#msg').textContent = 'Preencha período, código, início e fim.';
        return;
      }
      // envia para variável de ambiente do backend (EVAL_PERIOD) usando um truque simples:
      // primeiro salvamos as datas; depois você ajusta EVAL_PERIOD no Render se quiser fixar lá também.
      // Mas aqui, como a API /api/evaluations/window usa EVAL_PERIOD do servidor, vamos apenas salvar as datas para o período já configurado no servidor.
      // Se quiser alterar o período no servidor, atualize a env var EVAL_PERIOD no Render.
      const payload = {
        code: code,
        start_at: toUTCStringLocal(startAtLocal),
        end_at: toUTCStringLocal(endAtLocal)
      };
      const r = await fetch('/api/evaluations/window', {
        method: 'PUT',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify(payload)
      });
      const j = await r.json();
      if (r.ok) {
        $('#msg').textContent = 'Janela atualizada com sucesso.';
        await loadStatus();
      } else {
        $('#msg').textContent = 'Erro: ' + (j.error || 'falha ao salvar');
      }
    } catch (e) {
      $('#msg').textContent = 'Erro: ' + e;
    }
  }

  document.addEventListener('DOMContentLoaded', () => {
    loadStatus();
    $('#saveBtn').addEventListener('click', saveWindow);
    $('#reloadBtn').addEventListener('click', loadStatus);
  });
</script>
</body>
</html>
    """
    return html
# =====================  /ADMIN PAINEL  =====================


if __name__ == '__main__':
    app.run(debug=True)
