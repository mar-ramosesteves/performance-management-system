from flask import Flask, render_template, request, jsonify
import os
from supabase import create_client, Client

app = Flask(__name__)

# Configuração do Supabase
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')

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
        
        # Calcular posição na matriz 9-box
        nine_box_position = calculate_nine_box_position(performance_rating, potential_rating)
        
        return {
            'institucional_avg': round(institucional_avg, 2),
            'funcional_avg': round(funcional_avg, 2),
            'individual_avg': round(individual_avg, 2),
            'metas_avg': round(metas_avg, 2),
            'final_rating': round(final_rating, 2),
            'performance_rating': round(performance_rating, 2),
            'potential_rating': round(potential_rating, 2),
            'nine_box_position': nine_box_position
        }
        
    except Exception as e:
        print(f"Erro ao calcular scores: {e}")
        return None

def calculate_nine_box_position(performance, potential):
    """Calcula a posição na matriz 9-box baseada em performance e potencial"""
    # Converter ratings para posições na matriz 9-box
    # Performance: 1-5 -> 1-3 (baixo, médio, alto)
    # Potencial: 1-5 -> 1-3 (baixo, médio, alto)
    
    if performance <= 2:
        perf_pos = 1  # Alto
    elif performance <= 3.5:
        perf_pos = 2  # Médio
    else:
        perf_pos = 3  # Baixo
    
    if potential <= 2:
        pot_pos = 1  # Alto
    elif potential <= 3.5:
        pot_pos = 2  # Médio
    else:
        pot_pos = 3  # Baixo
    
    # Calcular posição na matriz 9-box (1-9)
    # Matriz: (potencial-1) * 3 + (4-performance)
    nine_box = (pot_pos - 1) * 3 + (4 - perf_pos)
    
    return nine_box

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
        
        # Criar a avaliação
        evaluation_data = {
            'employee_id': data['employee_id'],
            'evaluator_id': data['evaluator_id'],
            'evaluation_year': data['evaluation_year']
        }
        
        evaluation_response = supabase.table('evaluations').insert(evaluation_data).execute()
        
        if evaluation_response.data:
            evaluation_id = evaluation_response.data[0]['id']
            
            # Calcular scores
            scores = calculate_evaluation_scores(
                evaluation_id,
                data['responses'],
                data.get('goals', []),
                data.get('dimension_weights', {})
            )
            
            # Atualizar avaliação com os scores calculados
            if scores:
                supabase.table('evaluations').update(scores).eq('id', evaluation_id).execute()
            
            # Criar as respostas da avaliação
            responses = []
            for criteria_id, rating in data['responses'].items():
                response_data = {
                    'evaluation_id': evaluation_id,
                    'criteria_id': int(criteria_id),
                    'rating': rating
                }
                responses.append(response_data)
            
            if responses:
                supabase.table('evaluation_responses').insert(responses).execute()
            
            # Criar as metas se existirem
            if data.get('goals'):
                goals = []
                for goal in data['goals']:
                    goal_data = {
                        'evaluation_id': evaluation_id,
                        'employee_id': data['employee_id'],
                        'goal_name': goal.get('name', ''),
                        'goal_description': goal.get('description', ''),
                        'weight': goal.get('weight', 0),
                        'rating': goal.get('rating', 0)
                    }
                    goals.append(goal_data)
                
                if goals:
                    supabase.table('individual_goals').insert(goals).execute()
            
            return jsonify({
                'evaluation_id': evaluation_id,
                'scores': scores,
                'message': 'Avaliação salva com sucesso!'
            })
        else:
            return jsonify({'error': 'Erro ao criar avaliação'}), 500
            
    except Exception as e:
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

if __name__ == '__main__':
    app.run(debug=True)
