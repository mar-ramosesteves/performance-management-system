from flask import Flask, render_template, request, jsonify
import os
from supabase import create_client, Client

app = Flask(__name__)

# Configuração do Supabase
SUPABASE_URL = "sua_url_do_supabase_aqui"
SUPABASE_KEY = "sua_chave_do_supabase_aqui"

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

if __name__ == '__main__':
    app.run(debug=True)
