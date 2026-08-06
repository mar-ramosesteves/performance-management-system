import re
import unicodedata
from datetime import date, datetime, timezone

from flask import jsonify, request


WEIGHTS = {
    "conhecimento": 0.22,
    "complexidade": 0.24,
    "responsabilidade": 0.26,
    "lideranca_influencia": 0.16,
    "autonomia_risco": 0.12,
}

CLASSES = [
    ("A", 0, 149),
    ("B", 150, 249),
    ("C", 250, 349),
    ("D", 350, 449),
    ("E", 450, 549),
    ("F", 550, 649),
    ("G", 650, 749),
    ("H", 750, 849),
    ("I", 850, 924),
    ("J", 925, 1000),
]

QUESTIONS = [
    {"id": "CON_01", "pillar": "conhecimento", "label": "Escolaridade minima normalmente exigida", "options": ["Fundamental", "Medio", "Tecnico", "Superior", "Pos-graduacao"]},
    {"id": "CON_02", "pillar": "conhecimento", "label": "Tempo minimo de experiencia pratica esperado", "options": ["Ate 1 ano", "1 a 2 anos", "3 a 5 anos", "6 a 8 anos", "Mais de 8 anos"]},
    {"id": "CON_03", "pillar": "conhecimento", "label": "Conhecimento tecnico especializado exigido", "options": ["Nao", "Baixo", "Medio", "Alto", "Referencia tecnica"]},
    {"id": "CON_04", "pillar": "conhecimento", "label": "Disponibilidade desse conhecimento no mercado", "options": ["Muito facil", "Facil", "Moderada", "Dificil", "Muito dificil"]},
    {"id": "CON_05", "pillar": "conhecimento", "label": "Exigencia de normas, certificacoes ou requisitos regulados", "options": ["Nao", "Pontual", "Moderada", "Alta", "Critica"]},
    {"id": "CON_06", "pillar": "conhecimento", "label": "Conhecimento de processos de outras areas", "options": ["Nao", "Uma area", "Algumas areas", "Varias areas", "Visao integrada"]},
    {"id": "CON_07", "pillar": "conhecimento", "label": "Capacidade analitica requerida", "options": ["Baixa", "Moderada", "Alta", "Muito alta", "Estrategica"]},
    {"id": "CON_08", "pillar": "conhecimento", "label": "Necessidade de atualizacao tecnica", "options": ["Rara", "Ocasional", "Frequente", "Continua", "Permanente"]},
    {"id": "COM_01", "pillar": "complexidade", "label": "Natureza das atividades", "options": ["Rotineiras", "Variadas com procedimento", "Exigem interpretacao", "Pouco padronizadas", "Ineditas ou estrategicas"]},
    {"id": "COM_02", "pillar": "complexidade", "label": "Tipo de problema resolvido", "options": ["Simples", "Operacional variado", "Tecnico ou analitico", "Complexo", "Estrategico e ambiguo"]},
    {"id": "COM_03", "pillar": "complexidade", "label": "Nivel de ambiguidade", "options": ["Nao ha", "Baixo", "Moderado", "Alto", "Constante"]},
    {"id": "COM_04", "pillar": "complexidade", "label": "Horizonte de planejamento", "options": ["Diario", "Semanal", "Mensal", "Trimestral", "Anual ou maior"]},
    {"id": "COM_05", "pillar": "complexidade", "label": "Participacao em melhoria de processos", "options": ["Nao participa", "Sugere melhorias", "Implementa na area", "Lidera interareas", "Redesenha processos"]},
    {"id": "COM_06", "pillar": "complexidade", "label": "Exigencia de inovacao", "options": ["Nao", "Adaptacoes simples", "Melhorias frequentes", "Solucoes novas", "Cria modelos ou estrategias"]},
    {"id": "COM_07", "pillar": "complexidade", "label": "Integracao com outras areas", "options": ["Nao", "Baixa", "Media", "Alta", "Critica"]},
    {"id": "COM_08", "pillar": "complexidade", "label": "Volume e criticidade de informacoes", "options": ["Baixo", "Moderado", "Alto", "Muito alto", "Muito alto e critico"]},
    {"id": "RES_01", "pillar": "responsabilidade", "label": "Impacto principal do cargo", "options": ["Execucao individual", "Processo", "Area", "Varias areas", "Empresa ou unidade"]},
    {"id": "RES_02", "pillar": "responsabilidade", "label": "Impacto financeiro de erro", "options": ["Baixo", "Moderado", "Alto", "Muito alto", "Critico"]},
    {"id": "RES_03", "pillar": "responsabilidade", "label": "Risco trabalhista, legal, fiscal ou reputacional", "options": ["Nao", "Baixo", "Moderado", "Alto", "Critico"]},
    {"id": "RES_04", "pillar": "responsabilidade", "label": "Influencia em receita, margem, custo ou produtividade", "options": ["Nao direta", "Pequena", "Moderada", "Alta", "Critica"]},
    {"id": "RES_05", "pillar": "responsabilidade", "label": "Orcamento administrado", "options": ["Nao administra", "Baixo", "Moderado", "Alto", "Estrategico"]},
    {"id": "RES_06", "pillar": "responsabilidade", "label": "Responsabilidade por ativos, contratos ou dados sensiveis", "options": ["Nao", "Baixa", "Media", "Alta", "Critica"]},
    {"id": "RES_07", "pillar": "responsabilidade", "label": "Percepcao do resultado por clientes ou diretoria", "options": ["Pouca", "Equipe", "Area", "Varias areas ou clientes", "Cliente final, diretoria ou mercado"]},
    {"id": "RES_08", "pillar": "responsabilidade", "label": "Impacto na continuidade da operacao", "options": ["Baixo", "Moderado", "Alto", "Muito alto", "Critico"]},
    {"id": "LID_01", "pillar": "lideranca_influencia", "label": "Lideranca direta de pessoas", "options": ["Nao", "Ate 5", "6 a 20", "21 a 50", "Mais de 50"]},
    {"id": "LID_02", "pillar": "lideranca_influencia", "label": "Lideranca de lideres ou especialistas", "options": ["Nao", "Especialistas", "Supervisores", "Gerentes", "Executivos ou estrutura ampla"]},
    {"id": "LID_03", "pillar": "lideranca_influencia", "label": "Influencia sem autoridade formal", "options": ["Nao", "Baixa", "Media", "Alta", "Decisiva"]},
    {"id": "LID_04", "pillar": "lideranca_influencia", "label": "Negociacao interna ou externa", "options": ["Nao", "Simples", "Moderada", "Complexa", "Estrategica"]},
    {"id": "LID_05", "pillar": "lideranca_influencia", "label": "Representacao da empresa", "options": ["Nao", "Ocasional", "Frequente", "Temas relevantes", "Temas estrategicos ou sensiveis"]},
    {"id": "LID_06", "pillar": "lideranca_influencia", "label": "Desenvolvimento de pessoas", "options": ["Nao", "Apoia colegas", "Treina equipe", "Desenvolve lideres", "Define capacidades futuras"]},
    {"id": "LID_07", "pillar": "lideranca_influencia", "label": "Influencia em carreira, remuneracao ou desempenho", "options": ["Nao", "Pequena", "Moderada", "Alta", "Decisiva"]},
    {"id": "LID_08", "pillar": "lideranca_influencia", "label": "Comunicacao com alta gestao", "options": ["Nao", "Ocasional", "Frequente", "Recorrente relevante", "Estrategica"]},
    {"id": "AUT_01", "pillar": "autonomia_risco", "label": "Dependencia de instrucoes detalhadas", "options": ["Sempre", "Na maior parte", "Parcialmente", "Pouco", "Quase nunca"]},
    {"id": "AUT_02", "pillar": "autonomia_risco", "label": "Autonomia para tomar decisoes", "options": ["Baixa", "Moderada", "Alta", "Muito alta", "Estrategica"]},
    {"id": "AUT_03", "pillar": "autonomia_risco", "label": "Necessidade de aprovacao superior", "options": ["Sempre", "Frequentemente", "Decisoes relevantes", "Apenas excecoes", "Raramente"]},
    {"id": "AUT_04", "pillar": "autonomia_risco", "label": "Horizonte das decisoes", "options": ["Imediato", "Dias ou semanas", "Meses", "Ano", "Mais de um ano"]},
    {"id": "AUT_05", "pillar": "autonomia_risco", "label": "Definicao de politicas, normas ou diretrizes", "options": ["Nao", "Apoia", "Area propria", "Interareas", "Organizacionais"]},
    {"id": "AUT_06", "pillar": "autonomia_risco", "label": "Assuncao de riscos calculados", "options": ["Nao", "Baixo", "Moderado", "Alto", "Estrategico"]},
    {"id": "AUT_07", "pillar": "autonomia_risco", "label": "Decisao com informacoes incompletas", "options": ["Raramente", "Ocasionalmente", "Frequentemente", "Quase sempre", "Essencial"]},
    {"id": "AUT_08", "pillar": "autonomia_risco", "label": "Liberdade para propor mudancas estruturais", "options": ["Nao", "Pequenas mudancas", "Mudancas na area", "Mudancas interareas", "Mudancas organizacionais"]},
]


def _clean(value):
    value = str(value or "").strip()
    return value or None


def _context(source):
    return {
        "cliente_id": _clean(source.get("cliente_id")),
        "holding_id": _clean(source.get("holding_id")),
        "empresa_id": _clean(source.get("empresa_id")),
        "filial_id": _clean(source.get("filial_id")),
    }


def _apply_context(query, ctx):
    for key in ["cliente_id", "holding_id", "empresa_id", "filial_id"]:
        if ctx.get(key):
            query = query.eq(key, ctx[key])
    return query


def _option_value(raw_value):
    try:
        value = int(raw_value)
    except Exception:
        return None
    return max(1, min(5, value))


def _class_for_score(score):
    for code, min_score, max_score in CLASSES:
        if min_score <= score <= max_score:
            return {"class_code": code, "min_score": min_score, "max_score": max_score}
    return {"class_code": "J", "min_score": 925, "max_score": 1000}


def _profile_value(raw_value):
    if raw_value in [None, ""]:
        return None
    try:
        value = int(raw_value)
    except Exception:
        raise ValueError("profile_value deve ser inteiro entre -4 e 4.")
    if value < -4 or value > 4:
        raise ValueError("profile_value deve estar entre -4 e 4.")
    return value


def _answer_value(rows_by_id, question_id):
    row = rows_by_id.get(question_id) or {}
    return int(row.get("value") or 0)


def _alerts(answer_rows, pillar_scores):
    rows_by_id = {row["question_id"]: row for row in answer_rows}
    alerts = []
    leadership_people = _answer_value(rows_by_id, "LID_01")
    leadership_leaders = _answer_value(rows_by_id, "LID_02")
    impact = _answer_value(rows_by_id, "RES_01")
    autonomy = _answer_value(rows_by_id, "AUT_02")
    decision_horizon = _answer_value(rows_by_id, "AUT_04")
    specialization = _answer_value(rows_by_id, "CON_03")
    education = _answer_value(rows_by_id, "CON_01")
    complexity = (pillar_scores.get("complexidade") or {}).get("score_0_100") or 0

    if leadership_people <= 1 and leadership_leaders >= 3:
        alerts.append({"code": "lidera_lideres_sem_time_direto", "message": "Cargo indica lideranca de lideres sem lideranca direta informada."})
    if leadership_people <= 1 and impact >= 5:
        alerts.append({"code": "alto_impacto_sem_lideranca", "message": "Cargo sem lideranca direta foi marcado com impacto organizacional muito alto."})
    if education <= 2 and specialization >= 5:
        alerts.append({"code": "especializacao_alta_com_escolaridade_baixa", "message": "Conhecimento de referencia tecnica com escolaridade minima baixa. Revisar evidencia."})
    if autonomy <= 2 and decision_horizon >= 5:
        alerts.append({"code": "decisao_longa_com_baixa_autonomia", "message": "Decisoes de longo prazo foram combinadas com baixa autonomia."})
    if complexity < 35 and impact >= 5:
        alerts.append({"code": "baixa_complexidade_alto_impacto", "message": "Complexidade baixa combinada com impacto muito alto. Conferir respostas."})
    return alerts


def calculate_score(answers):
    pillar_values = {pillar: [] for pillar in WEIGHTS.keys()}
    answer_rows = []
    missing = []

    for question in QUESTIONS:
        value = _option_value((answers or {}).get(question["id"]))
        if value is None:
            missing.append(question["id"])
            continue
        pillar_values[question["pillar"]].append(value)
        answer_rows.append({
            "question_id": question["id"],
            "pillar": question["pillar"],
            "label": question["label"],
            "value": value,
            "answer_label": question["options"][value - 1],
        })

    pillar_scores = {}
    weighted_average = 0.0
    total_weight_used = 0.0
    for pillar, weight in WEIGHTS.items():
        values = pillar_values.get(pillar) or []
        if not values:
            pillar_scores[pillar] = {"average_raw": None, "score_0_100": None, "answered": 0}
            continue
        avg = sum(values) / len(values)
        pillar_scores[pillar] = {
            "average_raw": round(avg, 2),
            "score_0_100": round(((avg - 1) / 4) * 100, 1),
            "answered": len(values),
        }
        weighted_average += avg * weight
        total_weight_used += weight

    score = 0
    if total_weight_used:
        avg = weighted_average / total_weight_used
        score = max(0, min(1000, int(round(((avg - 1) / 4) * 1000))))

    sorted_pillars = sorted(
        [{"pillar": pillar, **data} for pillar, data in pillar_scores.items() if data.get("score_0_100") is not None],
        key=lambda row: row["score_0_100"],
        reverse=True,
    )

    return {
        "score": score,
        "job_class": _class_for_score(score),
        "pillar_scores": pillar_scores,
        "strongest_pillars": sorted_pillars[:2],
        "weakest_pillars": sorted_pillars[-2:],
        "answers": answer_rows,
        "missing_questions": missing,
        "completion": {"answered": len(answer_rows), "total": len(QUESTIONS), "percent": round((len(answer_rows) / len(QUESTIONS)) * 100, 1)},
        "alerts": _alerts(answer_rows, pillar_scores),
    }


def _table_error(error):
    detail = str(error)
    if "job_" in detail or "Could not find the table" in detail or "relation" in detail:
        return jsonify({
            "success": False,
            "error": "job_architecture_tables_missing",
            "message": "As tabelas do modulo de avaliacao de cargos ainda precisam ser criadas no Supabase.",
            "detail": detail,
        }), 501
    return jsonify({"success": False, "error": "job_architecture_failed", "detail": detail}), 500


def _safe_select(supabase, table_name, select_fields="*", filters=None, order_by=None, desc=True, limit=None):
    try:
        query = supabase.table(table_name).select(select_fields)
        for key, value in (filters or {}).items():
            if value not in [None, ""]:
                query = query.eq(key, value)
        if order_by:
            query = query.order(order_by, desc=desc)
        if limit:
            query = query.limit(limit)
        result = query.execute()
        return {"ok": True, "table": table_name, "data": result.data or []}
    except Exception as exc:
        return {"ok": False, "table": table_name, "error": str(exc), "data": []}


def _normalize_job_title(title):
    raw = str(title or "").strip()
    if not raw:
        return ""

    text = unicodedata.normalize("NFKD", raw)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower()
    replacements = {
        r"\bsr\.?\b": "senior",
        r"\bsenior\b": "senior",
        r"\bpl\.?\b": "pleno",
        r"\bjr\.?\b": "junior",
        r"\ban\.?\b": "analista",
        r"\bcoord\.?\b": "coordenador",
        r"\bsup\.?\b": "supervisor",
        r"\bger\.?\b": "gerente",
        r"\baux\.?\b": "auxiliar",
        r"\bassoc\.?\b": "associado",
        r"\bfinancas\b": "financeiro",
        r"\bfinanceira\b": "financeiro",
        r"\brh\b": "recursos humanos",
        r"\bdp\b": "departamento pessoal",
    }
    for pattern, replacement in replacements.items():
        text = re.sub(pattern, replacement, text)
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _title_tokens(normalized_title):
    stopwords = {"de", "da", "do", "das", "dos", "e", "em", "a", "o"}
    return {token for token in normalized_title.split() if token and token not in stopwords}


def _similarity(left, right):
    left_tokens = _title_tokens(left)
    right_tokens = _title_tokens(right)
    if not left_tokens or not right_tokens:
        return 0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def _first_clean(row, keys):
    for key in keys:
        value = _clean((row or {}).get(key))
        if value:
            return value
    return None


def _short_id(value):
    value = _clean(value)
    if not value:
        return None
    return value if len(value) <= 12 else f"{value[:8]}..."


def _add_context_option(options, option_id, label=None, **extra):
    option_id = _clean(option_id)
    if not option_id:
        return
    current = options.get(option_id) or {"id": option_id}
    current["label"] = _clean(label) or current.get("label") or _short_id(option_id) or option_id
    for key, value in extra.items():
        cleaned = _clean(value)
        if cleaned and not current.get(key):
            current[key] = cleaned
    options[option_id] = current


def _sort_context_options(options):
    return sorted(options.values(), key=lambda row: (row.get("label") or "").lower())


def register_job_architecture_routes(app, supabase, require_rh_code):
    @app.route("/api/job-architecture/questions", methods=["GET", "OPTIONS"])
    def api_job_architecture_questions():
        if request.method == "OPTIONS":
            return ("", 204)
        return jsonify({
            "success": True,
            "version": "MVP_2026_08_06",
            "weights": WEIGHTS,
            "classes": [{"class_code": c, "min_score": mn, "max_score": mx} for c, mn, mx in CLASSES],
            "questions": QUESTIONS,
        }), 200

    @app.route("/api/job-architecture/context-options", methods=["GET", "OPTIONS"])
    def api_job_architecture_context_options():
        if request.method == "OPTIONS":
            return ("", 204)
        try:
            clientes = {}
            holdings = {}
            empresas = {}
            filiais = {}
            sources = []

            # Preferencia: tabelas mestre, quando existirem. Se nao existirem,
            # a rota continua funcionando com os dados reais de employees.
            master_specs = [
                ("clientes", clientes, ["id", "cliente_id"], ["nome", "name", "razao_social", "nome_fantasia", "cliente_nome"]),
                ("holdings", holdings, ["id", "holding_id"], ["nome", "name", "razao_social", "nome_fantasia", "holding_nome"]),
                ("empresas", empresas, ["id", "empresa_id"], ["nome", "name", "razao_social", "nome_fantasia", "empresa_nome", "company_name"]),
                ("filiais", filiais, ["id", "filial_id"], ["nome", "name", "razao_social", "nome_fantasia", "filial_nome", "branch_name"]),
            ]
            for table_name, target, id_keys, label_keys in master_specs:
                result = _safe_select(supabase, table_name, "*", limit=2000)
                if not result.get("ok"):
                    continue
                rows = result.get("data") or []
                if rows:
                    sources.append(table_name)
                for row in rows:
                    item_id = _first_clean(row, id_keys)
                    _add_context_option(
                        target,
                        item_id,
                        _first_clean(row, label_keys),
                        cliente_id=_first_clean(row, ["cliente_id"]),
                        holding_id=_first_clean(row, ["holding_id"]),
                        empresa_id=_first_clean(row, ["empresa_id"]),
                    )

            employees_result = _safe_select(
                supabase,
                "employees",
                "cliente_id,holding_id,empresa_id,filial_id,holding,company_name,empresa,branch_name,business_line",
                limit=5000,
            )
            employee_rows = employees_result.get("data") or []
            if employees_result.get("ok") and employee_rows:
                sources.append("employees")

            for row in employee_rows:
                cliente_id = _clean(row.get("cliente_id"))
                holding_id = _clean(row.get("holding_id"))
                empresa_id = _clean(row.get("empresa_id"))
                filial_id = _clean(row.get("filial_id"))
                holding_label = _first_clean(row, ["holding", "business_line"])
                empresa_label = _first_clean(row, ["company_name", "empresa"])
                filial_label = _first_clean(row, ["branch_name"])

                if cliente_id:
                    _add_context_option(clientes, cliente_id, None)
                if holding_id:
                    _add_context_option(holdings, holding_id, holding_label, cliente_id=cliente_id)
                if empresa_id:
                    _add_context_option(empresas, empresa_id, empresa_label, cliente_id=cliente_id, holding_id=holding_id)
                if filial_id:
                    _add_context_option(
                        filiais,
                        filial_id,
                        filial_label,
                        cliente_id=cliente_id,
                        holding_id=holding_id,
                        empresa_id=empresa_id,
                    )

            return jsonify({
                "success": True,
                "sources": sources,
                "clientes": _sort_context_options(clientes),
                "holdings": _sort_context_options(holdings),
                "empresas": _sort_context_options(empresas),
                "filiais": _sort_context_options(filiais),
                "counts": {
                    "clientes": len(clientes),
                    "holdings": len(holdings),
                    "empresas": len(empresas),
                    "filiais": len(filiais),
                },
                "note": "Opcoes construidas apenas a partir de cadastros reais disponiveis no Supabase.",
            }), 200
        except Exception as exc:
            return _table_error(exc)

    @app.route("/api/job-architecture/profile-interpretations", methods=["GET", "OPTIONS"])
    def api_job_architecture_profile_interpretations():
        if request.method == "OPTIONS":
            return ("", 204)
        try:
            ctx = _context(request.args)
            query = supabase.table("job_profile_interpretations").select("*").eq("active", True)
            if ctx.get("cliente_id"):
                # Busca configuracoes do cliente e tambem referencias globais.
                all_rows = query.execute().data or []
                rows = []
                for row in all_rows:
                    row_cliente = _clean(row.get("cliente_id"))
                    row_holding = _clean(row.get("holding_id"))
                    if row_cliente and row_cliente != ctx.get("cliente_id"):
                        continue
                    if row_holding and row_holding != ctx.get("holding_id"):
                        continue
                    rows.append(row)
            else:
                rows = query.is_("cliente_id", "null").execute().data or []

            rows.sort(key=lambda row: int(row.get("profile_value") or 0))
            return jsonify({"success": True, "profile_interpretations": rows}), 200
        except Exception as exc:
            return _table_error(exc)

    @app.route("/api/job-architecture/evaluate", methods=["POST", "OPTIONS"])
    def api_job_architecture_evaluate():
        if request.method == "OPTIONS":
            return ("", 204)
        data = request.get_json(silent=True) or {}
        return jsonify({
            "success": True,
            "status": "calculated_without_persistence",
            "result": calculate_score(data.get("answers") or {}),
            "governance": {
                "official_only_after_human_review": True,
                "message": "Resultado tecnico inicial. Nao e avaliacao oficial sem revisao humana.",
            },
        }), 200

    @app.route("/api/job-architecture/positions", methods=["GET", "POST", "OPTIONS"])
    def api_job_architecture_positions():
        if request.method == "OPTIONS":
            return ("", 204)

        if request.method == "GET":
            try:
                ctx = _context(request.args)
                approved_only = str(request.args.get("approved_only", "true")).lower() != "false"
                query = _apply_context(supabase.table("job_positions").select("*"), ctx)
                if approved_only:
                    query = query.in_("status", ["aprovado", "ativo"])
                result = query.order("title", desc=False).execute()
                return jsonify({"success": True, "positions": result.data or []}), 200
            except Exception as exc:
                return _table_error(exc)

        try:
            data = request.get_json(silent=True) or {}
            ok, err, status = require_rh_code(data)
            if not ok:
                return jsonify(err), status

            ctx = _context(data)
            title = str(data.get("title") or data.get("cargo") or "").strip()
            if not ctx.get("cliente_id"):
                return jsonify({"success": False, "error": "cliente_id_obrigatorio"}), 400
            if not title:
                return jsonify({"success": False, "error": "title_obrigatorio"}), 400

            now_iso = datetime.now(timezone.utc).isoformat()
            payload = {
                **ctx,
                "title": title,
                "internal_code": _clean(data.get("internal_code")),
                "job_family": _clean(data.get("job_family")),
                "organizational_level": _clean(data.get("organizational_level")),
                "area": _clean(data.get("area")),
                "department": _clean(data.get("department")),
                "mission": _clean(data.get("mission")),
                "responsibilities": data.get("responsibilities") or [],
                "deliverables": data.get("deliverables") or [],
                "indicators": data.get("indicators") or [],
                "status": data.get("status") or "rascunho",
                "source": data.get("source") or "manual",
                "created_at": now_iso,
                "updated_at": now_iso,
            }
            result = supabase.table("job_positions").insert(payload).execute()
            return jsonify({"success": True, "position": (result.data or [payload])[0]}), 201
        except Exception as exc:
            return _table_error(exc)

    @app.route("/api/job-architecture/positions/<int:position_id>/descriptions", methods=["GET", "POST", "OPTIONS"])
    def api_job_architecture_position_descriptions(position_id):
        if request.method == "OPTIONS":
            return ("", 204)

        if request.method == "GET":
            try:
                result = (
                    supabase
                    .table("job_position_description_versions")
                    .select("*")
                    .eq("job_position_id", position_id)
                    .order("created_at", desc=True)
                    .execute()
                )
                return jsonify({"success": True, "descriptions": result.data or []}), 200
            except Exception as exc:
                return _table_error(exc)

        try:
            data = request.get_json(silent=True) or {}
            ok, err, status = require_rh_code(data)
            if not ok:
                return jsonify(err), status

            now_iso = datetime.now(timezone.utc).isoformat()
            payload = {
                "job_position_id": position_id,
                "version_label": data.get("version_label") or f"DESC_{date.today().isoformat()}",
                "status": data.get("status") or "rascunho",
                "mission": _clean(data.get("mission")),
                "responsibilities": data.get("responsibilities") or [],
                "deliverables": data.get("deliverables") or [],
                "indicators": data.get("indicators") or [],
                "required_education": _clean(data.get("required_education")),
                "required_experience": _clean(data.get("required_experience")),
                "technical_knowledge": data.get("technical_knowledge") or [],
                "behavioral_requirements": data.get("behavioral_requirements") or [],
                "internal_relationships": data.get("internal_relationships") or [],
                "external_relationships": data.get("external_relationships") or [],
                "autonomy_description": _clean(data.get("autonomy_description")),
                "decision_scope": _clean(data.get("decision_scope")),
                "financial_impact": _clean(data.get("financial_impact")),
                "operational_impact": _clean(data.get("operational_impact")),
                "people_leadership": _clean(data.get("people_leadership")),
                "direct_reports_count": data.get("direct_reports_count"),
                "manager_position_title": _clean(data.get("manager_position_title")),
                "subordinate_positions": data.get("subordinate_positions") or [],
                "work_context": _clean(data.get("work_context")),
                "evidence_notes": _clean(data.get("evidence_notes")),
                "created_by": _clean(data.get("created_by")),
                "reviewed_by": _clean(data.get("reviewed_by")),
                "created_at": now_iso,
                "updated_at": now_iso,
            }

            result = supabase.table("job_position_description_versions").insert(payload).execute()
            description = (result.data or [payload])[0]

            supabase.table("job_positions").update({
                "mission": payload["mission"],
                "responsibilities": payload["responsibilities"],
                "deliverables": payload["deliverables"],
                "indicators": payload["indicators"],
                "updated_at": now_iso,
            }).eq("id", position_id).execute()

            return jsonify({"success": True, "description": description}), 201
        except Exception as exc:
            return _table_error(exc)

    @app.route("/api/job-architecture/descriptions/<int:description_id>/approve", methods=["POST", "OPTIONS"])
    def api_job_architecture_approve_description(description_id):
        if request.method == "OPTIONS":
            return ("", 204)
        try:
            data = request.get_json(silent=True) or {}
            ok, err, status = require_rh_code(data)
            if not ok:
                return jsonify(err), status
            now_iso = datetime.now(timezone.utc).isoformat()
            payload = {
                "status": data.get("status") or "aprovado",
                "approved_by": _clean(data.get("approved_by")),
                "approved_at": now_iso,
                "updated_at": now_iso,
            }
            result = (
                supabase
                .table("job_position_description_versions")
                .update(payload)
                .eq("id", description_id)
                .execute()
            )
            return jsonify({"success": True, "description": (result.data or [payload])[0]}), 200
        except Exception as exc:
            return _table_error(exc)

    @app.route("/api/job-architecture/audit/cargo-variants", methods=["GET", "OPTIONS"])
    def api_job_architecture_audit_cargo_variants():
        if request.method == "OPTIONS":
            return ("", 204)
        try:
            ctx = _context(request.args)
            query = supabase.table("employees").select("id,nome,cargo,cliente_id,holding_id,empresa_id,filial_id")
            query = _apply_context(query, ctx)
            result = query.execute()
            employees = result.data or []

            variants = {}
            for employee in employees:
                original = str(employee.get("cargo") or "").strip()
                if not original:
                    original = "Sem cargo informado"
                normalized = _normalize_job_title(original)
                bucket = variants.setdefault(normalized, {
                    "normalized_title": normalized,
                    "suggested_official_title": original,
                    "count": 0,
                    "original_titles": {},
                    "sample_employees": [],
                })
                bucket["count"] += 1
                bucket["original_titles"][original] = bucket["original_titles"].get(original, 0) + 1
                if len(bucket["sample_employees"]) < 5:
                    bucket["sample_employees"].append({
                        "employee_id": employee.get("id"),
                        "nome": employee.get("nome"),
                        "cargo": original,
                    })

            grouped = []
            for bucket in variants.values():
                titles = sorted(bucket["original_titles"].items(), key=lambda item: item[1], reverse=True)
                bucket["suggested_official_title"] = titles[0][0] if titles else bucket["suggested_official_title"]
                bucket["original_titles"] = [{"title": title, "count": count} for title, count in titles]
                grouped.append(bucket)

            grouped.sort(key=lambda row: row["count"], reverse=True)

            possible_merges = []
            for index, left in enumerate(grouped):
                for right in grouped[index + 1:]:
                    score = _similarity(left["normalized_title"], right["normalized_title"])
                    if score >= 0.72 and left["normalized_title"] != right["normalized_title"]:
                        possible_merges.append({
                            "left": left["suggested_official_title"],
                            "right": right["suggested_official_title"],
                            "left_normalized": left["normalized_title"],
                            "right_normalized": right["normalized_title"],
                            "similarity": round(score, 2),
                            "recommendation": "revisar_manual_antes_de_unificar",
                        })

            return jsonify({
                "success": True,
                "status": "audit_only_no_data_change",
                "message": "Auditoria de grafias. Nenhum dado foi alterado.",
                "total_employees": len(employees),
                "unique_normalized_titles": len(grouped),
                "groups": grouped,
                "possible_merges": possible_merges[:80],
            }), 200
        except Exception as exc:
            return jsonify({"success": False, "error": "cargo_variant_audit_failed", "detail": str(exc)}), 500

    @app.route("/api/job-architecture/benchmarks/hay/import", methods=["POST", "OPTIONS"])
    def api_job_architecture_import_hay_benchmark():
        if request.method == "OPTIONS":
            return ("", 204)
        try:
            data = request.get_json(silent=True) or {}
            ok, err, status = require_rh_code(data)
            if not ok:
                return jsonify(err), status

            ctx = _context(data)
            if not ctx.get("cliente_id"):
                return jsonify({"success": False, "error": "cliente_id_obrigatorio"}), 400

            dry_run = data.get("dry_run", True)
            dry_run = False if str(dry_run).lower() in ["false", "0", "nao", "não"] else bool(dry_run)
            source_file_name = _clean(data.get("source_file_name")) or "hay_benchmark_import"
            records = data.get("records") or []
            factor_records = data.get("factor_records") or []

            if not isinstance(records, list) or not records:
                return jsonify({"success": False, "error": "records_obrigatorio"}), 400

            benchmark_rows = []
            factor_rows_by_title = {}
            for factor in factor_records:
                title_key = _normalize_job_title(factor.get("cargo"))
                factor_rows_by_title.setdefault(title_key, []).append(factor)

            for row in records:
                title = str(row.get("cargo") or row.get("original_title") or "").strip()
                if not title:
                    continue
                profile_value = _profile_value(row.get("profile_value")) if row.get("profile_value") not in [None, ""] else None
                benchmark_rows.append({
                    **ctx,
                    "source_file_name": source_file_name,
                    "original_title": title,
                    "normalized_title": _normalize_job_title(title),
                    "hay_points": row.get("total_points") or row.get("hay_points"),
                    "hay_grade": row.get("grade") or row.get("hay_grade"),
                    "hay_profile_value": profile_value,
                    "hay_factor_data": {
                        "know_how_level": row.get("know_how_level"),
                        "know_how_points": row.get("know_how_points"),
                        "problem_solving_level": row.get("problem_solving_level"),
                        "problem_solving_points": row.get("problem_solving_points"),
                        "accountability_level": row.get("accountability_level"),
                        "accountability_points": row.get("accountability_points"),
                        "long_profile": row.get("long_profile"),
                        "source_sheet": row.get("source_sheet"),
                        "source_row": row.get("source_row"),
                    },
                    "calibration_notes": row.get("remarks"),
                })

            if dry_run:
                return jsonify({
                    "success": True,
                    "status": "dry_run_no_data_change",
                    "message": "Importacao validada sem gravar dados.",
                    "benchmark_rows": len(benchmark_rows),
                    "factor_rows_received": len(factor_records),
                    "source_file_name": source_file_name,
                    "scope": ctx,
                }), 200

            inserted = supabase.table("job_hay_benchmark_imports").insert(benchmark_rows).execute()
            inserted_rows = inserted.data or []
            inserted_by_title = {
                _normalize_job_title(row.get("original_title")): row
                for row in inserted_rows
                if row.get("id")
            }

            factor_payload = []
            for title_key, factors in factor_rows_by_title.items():
                imported_row = inserted_by_title.get(title_key)
                if not imported_row:
                    continue
                for factor in factors:
                    factor_payload.append({
                        "hay_benchmark_import_id": imported_row["id"],
                        "factor_name": factor.get("factor_name"),
                        "factor_level": factor.get("factor_level"),
                        "factor_profile": factor.get("factor_profile"),
                        "points": factor.get("points"),
                        "source_sheet": factor.get("source_sheet"),
                        "source_row": factor.get("source_row"),
                        "source_column": factor.get("source_column"),
                        "raw_label": factor.get("cargo"),
                    })

            inserted_factors = []
            if factor_payload:
                inserted_factors = supabase.table("job_hay_benchmark_factor_points").insert(factor_payload).execute().data or []

            return jsonify({
                "success": True,
                "status": "imported",
                "benchmark_rows": len(inserted_rows),
                "factor_rows": len(inserted_factors),
                "source_file_name": source_file_name,
                "scope": ctx,
            }), 201
        except ValueError as exc:
            return jsonify({"success": False, "error": "valor_invalido", "detail": str(exc)}), 400
        except Exception as exc:
            return _table_error(exc)

    @app.route("/api/job-architecture/descriptions/source-documents", methods=["GET", "OPTIONS"])
    def api_job_architecture_source_documents():
        if request.method == "OPTIONS":
            return ("", 204)
        try:
            ctx = _context(request.args)
            query = supabase.table("job_position_description_source_documents").select("*")
            query = _apply_context(query, ctx)
            status = _clean(request.args.get("source_quality_status"))
            if status:
                query = query.eq("source_quality_status", status)
            result = query.order("imported_at", desc=True).limit(500).execute()
            return jsonify({"success": True, "source_documents": result.data or []}), 200
        except Exception as exc:
            return _table_error(exc)

    @app.route("/api/job-architecture/descriptions/source-documents/import", methods=["POST", "OPTIONS"])
    def api_job_architecture_import_source_documents():
        if request.method == "OPTIONS":
            return ("", 204)
        try:
            data = request.get_json(silent=True) or {}
            ok, err, status = require_rh_code(data)
            if not ok:
                return jsonify(err), status

            ctx = _context(data)
            if not ctx.get("cliente_id"):
                return jsonify({"success": False, "error": "cliente_id_obrigatorio"}), 400

            dry_run = data.get("dry_run", True)
            dry_run = False if str(dry_run).lower() in ["false", "0", "nao", "não"] else bool(dry_run)
            records = data.get("records") or []
            if not isinstance(records, list) or not records:
                return jsonify({"success": False, "error": "records_obrigatorio"}), 400

            rows = []
            for record in records:
                file_name = _clean(record.get("file_name"))
                if not file_name:
                    continue
                match = record.get("best_hay_match") or {}
                similarity = match.get("similarity")
                try:
                    similarity = float(similarity) if similarity not in [None, ""] else None
                except Exception:
                    similarity = None
                rows.append({
                    **ctx,
                    "source_file_name": file_name,
                    "source_relative_path": _clean(record.get("relative_path")),
                    "source_folder": _clean(record.get("folder")),
                    "extracted_title": _clean(record.get("title_from_file")),
                    "normalized_title": _clean(record.get("normalized_title")),
                    "extracted_text": record.get("text_preview") or record.get("extracted_text"),
                    "sections_detected": record.get("sections_detected") or {},
                    "match_confidence": similarity,
                    "source_quality_status": (
                        "match_forte_nao_revisado"
                        if similarity is not None and similarity >= 0.75
                        else "referencia_nao_revisada"
                    ),
                    "manual_review_required": True,
                    "notes": record.get("notes"),
                })

            if dry_run:
                return jsonify({
                    "success": True,
                    "status": "dry_run_no_data_change",
                    "message": "Documentos fonte validados sem gravar dados.",
                    "source_document_rows": len(rows),
                    "scope": ctx,
                }), 200

            inserted = supabase.table("job_position_description_source_documents").insert(rows).execute()
            return jsonify({
                "success": True,
                "status": "imported",
                "source_document_rows": len(inserted.data or []),
                "scope": ctx,
            }), 201
        except Exception as exc:
            return _table_error(exc)

    @app.route("/api/job-architecture/positions/<int:position_id>/evaluation", methods=["POST", "OPTIONS"])
    def api_job_architecture_position_evaluation(position_id):
        if request.method == "OPTIONS":
            return ("", 204)
        try:
            data = request.get_json(silent=True) or {}
            ok, err, status = require_rh_code(data)
            if not ok:
                return jsonify(err), status

            result = calculate_score(data.get("answers") or {})
            now_iso = datetime.now(timezone.utc).isoformat()
            version_payload = {
                "job_position_id": position_id,
                "version_label": data.get("version_label") or f"MVP_{date.today().isoformat()}",
                "status": data.get("status") or "avaliado",
                "score": result["score"],
                "class_code": result["job_class"]["class_code"],
                "grade_code": _clean(data.get("grade_code")),
                "profile_value": _profile_value(data.get("profile_value")),
                "pillar_scores": result["pillar_scores"],
                "alerts": result["alerts"],
                "source": data.get("source") or "manual",
                "review_notes": data.get("review_notes"),
                "created_at": now_iso,
                "updated_at": now_iso,
            }
            inserted_version = supabase.table("job_evaluation_versions").insert(version_payload).execute()
            version = (inserted_version.data or [version_payload])[0]
            version_id = version.get("id")

            if version_id:
                rows = [{
                    "job_evaluation_version_id": version_id,
                    "question_id": row["question_id"],
                    "pillar": row["pillar"],
                    "answer_value": row["value"],
                    "answer_label": row["answer_label"],
                    "created_at": now_iso,
                } for row in result["answers"]]
                if rows:
                    supabase.table("job_evaluation_answers").insert(rows).execute()

            supabase.table("job_positions").update({
                "current_score": result["score"],
                "current_class_code": result["job_class"]["class_code"],
                "current_grade_code": _clean(data.get("grade_code")),
                "current_profile_value": _profile_value(data.get("profile_value")),
                "status": data.get("position_status") or "avaliado",
                "updated_at": now_iso,
            }).eq("id", position_id).execute()

            return jsonify({"success": True, "position_id": position_id, "evaluation_version": version, "result": result}), 201
        except Exception as exc:
            return _table_error(exc)

    @app.route("/api/job-architecture/positions/<int:position_id>/approve", methods=["POST", "OPTIONS"])
    def api_job_architecture_approve_position(position_id):
        if request.method == "OPTIONS":
            return ("", 204)
        try:
            data = request.get_json(silent=True) or {}
            ok, err, status = require_rh_code(data)
            if not ok:
                return jsonify(err), status
            now_iso = datetime.now(timezone.utc).isoformat()
            payload = {
                "status": data.get("status") or "aprovado",
                "approved_by": _clean(data.get("approved_by")),
                "approved_at": now_iso,
                "approval_notes": _clean(data.get("approval_notes")),
                "updated_at": now_iso,
            }
            result = supabase.table("job_positions").update(payload).eq("id", position_id).execute()
            return jsonify({"success": True, "position": (result.data or [payload])[0]}), 200
        except Exception as exc:
            return _table_error(exc)

    @app.route("/api/job-architecture/retention-risk-context", methods=["GET", "OPTIONS"])
    def api_job_architecture_retention_risk_context():
        if request.method == "OPTIONS":
            return ("", 204)
        employee_id = request.args.get("employee_id")
        if not employee_id:
            return jsonify({"success": False, "error": "employee_id_obrigatorio"}), 400

        employee_result = _safe_select(supabase, "employees", "*", {"id": employee_id}, limit=1)
        employee = (employee_result.get("data") or [{}])[0] if employee_result.get("ok") else {}
        job_position_id = employee.get("job_position_id") or request.args.get("job_position_id")

        position_result = {"ok": True, "table": "job_positions", "data": []}
        evaluation_result = {"ok": True, "table": "job_evaluation_versions", "data": []}
        if job_position_id:
            position_result = _safe_select(supabase, "job_positions", "*", {"id": job_position_id}, limit=1)
            evaluation_result = _safe_select(supabase, "job_evaluation_versions", "*", {"job_position_id": job_position_id}, "created_at", True, 1)

        return jsonify({
            "success": True,
            "status": "context_only_no_risk_score",
            "message": "Conector inicial preparado. O IRP final ainda depende de modelo validado e fontes completas.",
            "employee_id": employee_id,
            "job_position_id": job_position_id,
            "sources": {
                "employee": employee_result,
                "job_position": position_result,
                "job_evaluation": evaluation_result,
                "performance": _safe_select(supabase, "evaluations", "*", {"employee_id": employee_id}, "created_at", True, 3),
                "individual_goals": _safe_select(supabase, "individual_goals", "*", {"employee_id": employee_id}, "created_at", True, 10),
                "leadertrack_devolutivas": _safe_select(supabase, "leadertrack_devolutivas", "*", {"employee_id": employee_id}, "created_at", True, 3),
                "leadertrack_pdi_acompanhamento": _safe_select(supabase, "leadertrack_pdi_acompanhamento", "*", {"employee_id": employee_id}, "created_at", True, 10),
            },
            "future_risk_dimensions": [
                "equilibrio_interno",
                "equilibrio_externo",
                "gap_financeiro",
                "total_rewards",
                "lideranca",
                "saude_emocional",
                "microambiente",
                "desempenho",
                "potencial",
                "perspectiva_de_carreira",
            ],
        }), 200
