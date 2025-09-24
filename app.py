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
    
    print(f"DEBUG: calculate_nine_box_position chamada com performance={performance}, potential={potential}")
    
    def rating_to_9box(rating):
        """Converte rating (1-5) para 9-box (1-9) usando a tabela de correlação"""
        # Arredondar para 1 casa decimal
        rounded_rating = round(rating, 1)
        
        print(f"DEBUG: rating original: {rating}, arredondado: {rounded_rating}")
        
        # Tabela de correlação exata da sua imagem
        correlation_table = {
            1.0: 9.0, 1.1: 8.8, 1.2: 8.6, 1.3: 8.4, 1.4: 8.2, 1.5: 8.0,
            1.6: 7.8, 1.7: 7.6, 1.8: 7.4, 1.9: 7.2, 2.0: 7.0, 2.1: 6.8,
            2.2: 6.6, 2.3: 6.4, 2.4: 6.2, 2.5: 6.0, 2.6: 5.8, 2.7: 5.6,
            2.8: 5.4, 2.9: 5.2, 3.0: 5.0, 3.1: 4.8, 3.2: 4.6, 3.3: 4.4,
            3.4: 4.2, 3.5: 4.0, 3.6: 3.8, 3.7: 3.6, 3.8: 3.4, 3.9: 3.2,
            4.0: 3.0, 4.1: 2.8, 4.2: 2.6, 4.3: 2.4, 4.4: 2.2, 4.5: 2.0,
            4.6: 1.8, 4.7: 1.6, 4.8: 1.4, 4.9: 1.2, 5.0: 1.0
        }
        
        # Procurar na tabela
        if rounded_rating in correlation_table:
            result = correlation_table[rounded_rating]
            print(f"DEBUG: Encontrado na tabela: {rounded_rating} -> {result}")
        else:
            # Se não encontrar, usar a fórmula
            result = 10 - (rounded_rating * 2)
            print(f"DEBUG: Não encontrado na tabela, usando fórmula: {result}")
        
        return result
    
    # Converter ratings para valores 9-box
    performance_9box = rating_to_9box(performance)
    potential_9box = rating_to_9box(potential)
    
    print(f"DEBUG: Performance: {performance} -> 9-box: {performance_9box}")
    print(f"DEBUG: Potential: {potential} -> 9-box: {potential_9box}")
    
    # Por enquanto, vamos retornar apenas a média dos dois valores 9-box
    # Isso vai nos mostrar se a conversão está funcionando
    nine_box_position = round((performance_9box + potential_9box) / 2)
    
    print(f"DEBUG: nine_box_position calculado: {nine_box_position}")
    
    return nine_box_position

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

if __name__ == '__main__':
    app.run(debug=True)
