from flask import Flask, render_template, request, jsonify
import os

app = Flask(__name__)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/employees', methods=['GET'])
def get_employees():
    # Dados de exemplo para testar
    sample_employees = [
        {
            "id": 1,
            "nome": "João Silva",
            "cargo": "Analista",
            "empresa": "Empresa Exemplo",
            "salario": 5000
        },
        {
            "id": 2,
            "nome": "Maria Santos",
            "cargo": "Gerente",
            "empresa": "Empresa Exemplo",
            "salario": 8000
        }
    ]
    return jsonify(sample_employees)

@app.route('/api/employees', methods=['POST'])
def create_employee():
    try:
        data = request.get_json()
        # Por enquanto, apenas retorna os dados recebidos
        return jsonify({"message": "Funcionário criado com sucesso", "data": data})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True)
