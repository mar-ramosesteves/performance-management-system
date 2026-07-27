from datetime import datetime, timezone

from flask import jsonify, request


PDI_DIMENSION_LABELS = {
    'FUNCIONAL': 'Funcional',
    'INDIVIDUAL': 'Individual',
    'INSTITUCIONAL': 'Institucional',
    'METAS': 'Metas',
}


def _to_float(value):
    try:
        return float(value)
    except Exception:
        return None


def _dimension_classification(rating):
    value = _to_float(rating)
    if value is None or value <= 0:
        return {'status': 'SEM_RATING', 'pdi_required': False, 'recognition': False}
    if value < 2.5:
        return {'status': 'RECONHECIMENTO', 'pdi_required': False, 'recognition': True}
    if value >= 3.5:
        return {'status': 'PDI_OBRIGATORIO', 'pdi_required': True, 'recognition': False}
    return {'status': 'OK', 'pdi_required': False, 'recognition': False}


def _general_recognition(final_rating):
    value = _to_float(final_rating)
    return bool(value is not None and value > 0 and value < 2.5)


def _axis_bucket(value):
    score = _to_float(value)
    if score is None:
        return None
    if score >= 7:
        return 'alto'
    if score >= 4:
        return 'medio'
    return 'baixo'


def _is_proactive_9box(performance_rating, potential_rating):
    performance_bucket = _axis_bucket(performance_rating)
    potential_bucket = _axis_bucket(potential_rating)
    return (
        (potential_bucket == 'alto' and performance_bucket == 'alto')
        or (potential_bucket == 'medio' and performance_bucket == 'alto')
        or (potential_bucket == 'alto' and performance_bucket == 'medio')
    )


def _context_matches_access(access_row, cliente_id='', holding_id='', empresa_id='', filial_id=''):
    row_cliente_id = str(access_row.get('cliente_id') or '').strip()
    row_holding_id = str(access_row.get('holding_id') or '').strip()
    row_empresa_id = str(access_row.get('empresa_id') or '').strip()
    row_filial_id = str(access_row.get('filial_id') or '').strip()
    if cliente_id and row_cliente_id and row_cliente_id != cliente_id:
        return False
    if holding_id and row_holding_id and row_holding_id != holding_id:
        return False
    if empresa_id and row_empresa_id and row_empresa_id != empresa_id:
        return False
    if filial_id and row_filial_id and row_filial_id != filial_id:
        return False
    return True


def _plan_origin_type(item):
    has_mandatory = bool(item.get('mandatory_pdi') or item.get('pdi_required_dimensions'))
    has_proactive = bool(item.get('proactive_pdi'))
    if has_mandatory and has_proactive:
        return 'misto'
    if has_mandatory:
        return 'obrigatorio_desempenho'
    if has_proactive:
        return 'proativo_9box'
    return 'manual'


def _plan_title(item, cycle_code):
    employee_name = (item.get('employee_name') or 'Profissional').strip()
    return f'PDI {cycle_code} - {employee_name}' if cycle_code else f'PDI - {employee_name}'


def register_pdi_routes(app, supabase, buscar_avaliacoes_brutas, get_active_round_code, require_rh_code):
    def validate_rh_read_access(user_email, cliente_id='', holding_id='', empresa_id='', filial_id=''):
        email = (user_email or '').strip().lower()
        if not email:
            return False, {
                'error': 'USER_EMAIL_REQUIRED',
                'message': 'Informe user_email para consultar elegibilidade de PDI.'
            }, 400

        try:
            r_access = (
                supabase
                .table('usuarios_acessos')
                .select(
                    'id, wp_user_email, perfil, cliente_id, holding_id, empresa_id, filial_id, '
                    'pode_ver_comite_avaliacao, pode_administrar, status'
                )
                .eq('wp_user_email', email)
                .eq('status', 'ativo')
                .execute()
            )
            rows = r_access.data or []
        except Exception as exc:
            print('[pdi] erro ao validar acesso:', exc)
            return False, {
                'error': 'ACCESS_CHECK_FAILED',
                'message': 'Nao foi possivel validar o acesso ao PDI.'
            }, 500

        for row in rows:
            contexto_ok = _context_matches_access(
                row,
                cliente_id=cliente_id,
                holding_id=holding_id,
                empresa_id=empresa_id,
                filial_id=filial_id,
            )
            is_admin_fallback = (
                not str(row.get('cliente_id') or '').strip()
                and bool(row.get('pode_administrar'))
            )
            pode_ler = bool(row.get('pode_administrar')) or bool(row.get('pode_ver_comite_avaliacao'))
            if (contexto_ok or is_admin_fallback) and pode_ler:
                return True, None, None

        return False, {
            'error': 'PDI_ACCESS_DENIED',
            'message': 'Usuario sem permissao para consultar PDI neste contexto.'
        }, 403

    def existing_plan_keys(cycle_code, employee_ids):
        keys = set()
        if not cycle_code or not employee_ids:
            return keys
        try:
            r = (
                supabase
                .table('pdi_plans')
                .select('id,employee_id,cycle_code,origin_type,status')
                .eq('cycle_code', cycle_code)
                .in_('employee_id', employee_ids)
                .execute()
            )
            for row in (r.data or []):
                emp_id = row.get('employee_id')
                if emp_id is not None:
                    keys.add((str(emp_id), 'any'))
                    if row.get('origin_type'):
                        keys.add((str(emp_id), str(row.get('origin_type'))))
        except Exception as exc:
            print('[pdi] pdi_plans indisponivel:', exc)
        return keys

    @app.route('/api/pdi/eligibility', methods=['GET', 'OPTIONS'])
    def api_pdi_eligibility():
        if request.method == 'OPTIONS':
            return ('', 204)
        try:
            round_code = (
                request.args.get('round_code')
                or request.args.get('ciclo_codigo')
                or ''
            ).strip()
            year_param = (request.args.get('year') or '').strip()
            empresa = (request.args.get('empresa') or '').strip() or None
            cliente_id = (request.args.get('cliente_id') or '').strip()
            holding_id = (request.args.get('holding_id') or '').strip()
            empresa_id = (request.args.get('empresa_id') or '').strip()
            filial_id = (request.args.get('filial_id') or '').strip()
            user_email = (request.args.get('user_email') or '').strip().lower()
            nivel_contexto = (
                request.args.get('nivel_contexto')
                or request.args.get('contexto_nivel')
                or ''
            ).strip().lower() or None

            ok_access, err_access, status_access = validate_rh_read_access(
                user_email, cliente_id=cliente_id, holding_id=holding_id,
                empresa_id=empresa_id, filial_id=filial_id,
            )
            if not ok_access:
                return jsonify(err_access), status_access

            if not round_code and year_param:
                try:
                    year = int(year_param)
                except Exception:
                    year = None
                if year:
                    for cod in [f'YE{year}', f'Start{year}']:
                        try:
                            r_test = (
                                supabase.table('evaluations')
                                .select('id')
                                .eq('round_code', cod)
                                .limit(1)
                                .execute()
                            )
                            if r_test.data:
                                round_code = cod
                                break
                        except Exception as exc:
                            print('[pdi] erro ao testar round_code', cod, exc)

            if not round_code:
                round_code = get_active_round_code()

            dimension_rows = buscar_avaliacoes_brutas(
                round_code=round_code,
                empresa=empresa,
                holding_id=holding_id or None,
                empresa_id=empresa_id or None,
                filial_id=filial_id or None,
                nivel_contexto=nivel_contexto,
            )

            pdi_by_employee = {}
            all_employee_ids = set()

            for row in dimension_rows:
                employee_id = row.get('employee_id')
                if employee_id is None:
                    continue
                emp_key = str(employee_id)
                all_employee_ids.add(employee_id)
                ratings = row.get('ratings') or {}
                dimensions = []
                required_dimensions = []
                recognition_dimensions = []

                for dim_code, dim_label in PDI_DIMENSION_LABELS.items():
                    rating = ratings.get(dim_code)
                    classification = _dimension_classification(rating)
                    dim_payload = {
                        'dimension_code': dim_code,
                        'dimension_label': dim_label,
                        'rating': rating,
                        'status': classification['status'],
                        'pdi_required': classification['pdi_required'],
                        'recognition': classification['recognition'],
                    }
                    dimensions.append(dim_payload)
                    if classification['pdi_required']:
                        required_dimensions.append(dim_payload)
                    if classification['recognition']:
                        recognition_dimensions.append(dim_payload)

                pdi_by_employee[emp_key] = {
                    'employee_id': employee_id,
                    'employee_name': row.get('employee_name'),
                    'cargo': row.get('cargo'),
                    'department_name': row.get('department_name'),
                    'manager_name': row.get('manager_name'),
                    'manager_code': row.get('manager_code'),
                    'cliente_id': row.get('cliente_id') or cliente_id or None,
                    'holding_id': row.get('holding_id') or holding_id or None,
                    'empresa_id': row.get('empresa_id') or empresa_id or None,
                    'empresa_nome': row.get('company_name') or row.get('empresa'),
                    'filial_id': row.get('filial_id') or filial_id or None,
                    'filial_nome': row.get('branch_name'),
                    'round_code': row.get('round_code') or round_code,
                    'evaluation_id': row.get('evaluation_id'),
                    'final_rating': row.get('final_rating'),
                    'dimensions': dimensions,
                    'pdi_required_dimensions': required_dimensions,
                    'recognition_dimensions': recognition_dimensions,
                    'general_recognition': _general_recognition(row.get('final_rating')),
                    'proactive_pdi': False,
                    'nine_box_position': None,
                    'performance_rating': None,
                    'potential_rating': None,
                    'eligibility_sources': [],
                }

                if required_dimensions:
                    pdi_by_employee[emp_key]['eligibility_sources'].append({
                        'type': 'obrigatorio_desempenho',
                        'label': 'PDI obrigatorio por dimensao',
                        'dimensions': [d['dimension_code'] for d in required_dimensions],
                        'evaluation_id': row.get('evaluation_id'),
                    })

            try:
                q9 = (
                    supabase
                    .table('v_desempenho_contexto')
                    .select(
                        'evaluation_id,employee_id,employee_name,cargo,'
                        'cliente_id,holding_id,holding_nome,empresa_id,empresa_nome,'
                        'filial_id,filial_nome,department_name,manager_name,'
                        'round_code,ciclo_codigo,evaluation_year,ano_referencia,'
                        'final_rating,performance_rating,potential_rating,nine_box_position'
                    )
                )
                if round_code:
                    q9 = q9.eq('round_code', round_code)
                if cliente_id:
                    q9 = q9.eq('cliente_id', cliente_id)
                if holding_id:
                    q9 = q9.eq('holding_id', holding_id)
                if empresa_id:
                    q9 = q9.eq('empresa_id', empresa_id)
                if filial_id:
                    q9 = q9.eq('filial_id', filial_id)
                ninebox_rows = (q9.execute()).data or []
            except Exception as exc:
                print('[pdi] erro ao buscar 9Box:', exc)
                ninebox_rows = []

            for row in ninebox_rows:
                employee_id = row.get('employee_id')
                if employee_id is None:
                    continue
                emp_key = str(employee_id)
                all_employee_ids.add(employee_id)
                try:
                    box = int(row.get('nine_box_position'))
                except Exception:
                    box = None

                if emp_key not in pdi_by_employee:
                    pdi_by_employee[emp_key] = {
                        'employee_id': employee_id,
                        'employee_name': row.get('employee_name'),
                        'cargo': row.get('cargo'),
                        'department_name': row.get('department_name'),
                        'manager_name': row.get('manager_name'),
                        'manager_code': None,
                        'cliente_id': row.get('cliente_id') or cliente_id or None,
                        'holding_id': row.get('holding_id') or holding_id or None,
                        'empresa_id': row.get('empresa_id') or empresa_id or None,
                        'empresa_nome': row.get('empresa_nome'),
                        'filial_id': row.get('filial_id') or filial_id or None,
                        'filial_nome': row.get('filial_nome'),
                        'round_code': row.get('ciclo_codigo') or row.get('round_code') or round_code,
                        'evaluation_id': row.get('evaluation_id'),
                        'final_rating': row.get('final_rating'),
                        'dimensions': [],
                        'pdi_required_dimensions': [],
                        'recognition_dimensions': [],
                        'general_recognition': _general_recognition(row.get('final_rating')),
                        'proactive_pdi': False,
                        'nine_box_position': None,
                        'performance_rating': None,
                        'potential_rating': None,
                        'eligibility_sources': [],
                    }

                item = pdi_by_employee[emp_key]
                item['nine_box_position'] = box
                item['performance_rating'] = row.get('performance_rating')
                item['potential_rating'] = row.get('potential_rating')

                if _is_proactive_9box(row.get('performance_rating'), row.get('potential_rating')):
                    item['proactive_pdi'] = True
                    if not any(s.get('type') == 'proativo_9box' for s in item['eligibility_sources']):
                        item['eligibility_sources'].append({
                            'type': 'proativo_9box',
                            'label': 'PDI proativo por 9Box',
                            'nine_box_position': box,
                            'performance_rating': row.get('performance_rating'),
                            'potential_rating': row.get('potential_rating'),
                        })

            existing_keys = existing_plan_keys(round_code, list(all_employee_ids))
            items = []
            totals = {
                'employees_evaluated': len(pdi_by_employee),
                'mandatory_pdi_employees': 0,
                'proactive_pdi_employees': 0,
                'general_recognition_employees': 0,
                'dimension_recognition_employees': 0,
                'eligible_employees': 0,
                'already_has_plan_employees': 0,
            }

            for emp_key, item in pdi_by_employee.items():
                has_mandatory = bool(item['pdi_required_dimensions'])
                has_proactive = bool(item['proactive_pdi'])
                has_dimension_recognition = bool(item['recognition_dimensions'])
                has_general_recognition = bool(item['general_recognition'])
                item['mandatory_pdi'] = has_mandatory
                item['eligible_for_pdi'] = has_mandatory or has_proactive
                item['already_has_any_plan'] = (emp_key, 'any') in existing_keys
                if has_mandatory:
                    totals['mandatory_pdi_employees'] += 1
                if has_proactive:
                    totals['proactive_pdi_employees'] += 1
                if has_general_recognition:
                    totals['general_recognition_employees'] += 1
                if has_dimension_recognition:
                    totals['dimension_recognition_employees'] += 1
                if item['eligible_for_pdi']:
                    totals['eligible_employees'] += 1
                if item['already_has_any_plan']:
                    totals['already_has_plan_employees'] += 1
                items.append(item)

            items.sort(key=lambda x: (
                0 if x.get('eligible_for_pdi') else 1,
                (x.get('manager_name') or '').strip().upper(),
                (x.get('employee_name') or '').strip().upper(),
            ))

            return jsonify({
                'source': 'supabase',
                'module': 'pdi',
                'round_code': round_code,
                'year': year_param or None,
                'generated_at': datetime.now(timezone.utc).isoformat(),
                'context': {
                    'nivel_contexto': nivel_contexto,
                    'cliente_id': cliente_id or None,
                    'holding_id': holding_id or None,
                    'empresa_id': empresa_id or None,
                    'filial_id': filial_id or None,
                },
                'criteria': {
                    'dimension_recognition': 'media da dimensao abaixo de 2.5',
                    'dimension_ok': 'media da dimensao de 2.5 ate antes de 3.5',
                    'mandatory_pdi': 'media da dimensao maior ou igual a 3.5',
                    'general_recognition': 'rating final abaixo de 2.5',
                    'proactive_pdi_rule': (
                        'Alto Potencial x Alto Desempenho; '
                        'Medio Potencial x Alto Desempenho; '
                        'Alto Potencial x Medio Desempenho'
                    ),
                },
                'totals': totals,
                'items': items,
            }), 200
        except Exception as exc:
            print('[pdi] erro interno eligibility:', exc)
            return jsonify({'error': 'internal', 'detail': str(exc)}), 500

    @app.route('/api/pdi/plans', methods=['GET', 'OPTIONS'])
    def api_pdi_plans_list():
        if request.method == 'OPTIONS':
            return ('', 204)
        try:
            user_email = (request.args.get('user_email') or '').strip().lower()
            cycle_code = (
                request.args.get('cycle_code')
                or request.args.get('round_code')
                or request.args.get('ciclo_codigo')
                or ''
            ).strip()
            cliente_id = (request.args.get('cliente_id') or '').strip()
            holding_id = (request.args.get('holding_id') or '').strip()
            empresa_id = (request.args.get('empresa_id') or '').strip()
            filial_id = (request.args.get('filial_id') or '').strip()

            ok_access, err_access, status_access = validate_rh_read_access(
                user_email, cliente_id=cliente_id, holding_id=holding_id,
                empresa_id=empresa_id, filial_id=filial_id,
            )
            if not ok_access:
                return jsonify(err_access), status_access

            q = supabase.table('pdi_plans').select('*').order('created_at', desc=True)
            if cycle_code:
                q = q.eq('cycle_code', cycle_code)
            if cliente_id:
                q = q.eq('cliente_id', cliente_id)
            if holding_id:
                q = q.eq('holding_id', holding_id)
            if empresa_id:
                q = q.eq('empresa_id', empresa_id)
            if filial_id:
                q = q.eq('filial_id', filial_id)

            plans = (q.execute()).data or []
            plan_ids = [p.get('id') for p in plans if p.get('id') is not None]
            dimensions_by_plan = {}
            actions_by_plan = {}
            trainings_by_plan = {}
            checkins_by_plan = {}

            if plan_ids:
                for table_name, bucket in [
                    ('pdi_plan_dimensions', dimensions_by_plan),
                    ('pdi_actions', actions_by_plan),
                    ('training_assignments', trainings_by_plan),
                    ('pdi_monthly_checkins', checkins_by_plan),
                ]:
                    try:
                        rows = (
                            supabase
                            .table(table_name)
                            .select('*')
                            .in_('pdi_plan_id', plan_ids)
                            .execute()
                        ).data or []
                        for row in rows:
                            bucket.setdefault(row.get('pdi_plan_id'), []).append(row)
                    except Exception as exc:
                        print(f'[pdi] erro ao buscar {table_name}:', exc)

            items = []
            for plan in plans:
                pid = plan.get('id')
                item = dict(plan)
                item['dimensions'] = dimensions_by_plan.get(pid, [])
                item['actions'] = actions_by_plan.get(pid, [])
                item['training_assignments'] = trainings_by_plan.get(pid, [])
                item['monthly_checkins'] = checkins_by_plan.get(pid, [])
                items.append(item)

            return jsonify({
                'source': 'supabase',
                'module': 'pdi',
                'cycle_code': cycle_code or None,
                'total': len(items),
                'items': items,
            }), 200
        except Exception as exc:
            print('[pdi] erro interno plans:', exc)
            return jsonify({'error': 'internal', 'detail': str(exc)}), 500

    @app.route('/api/pdi/generate-from-eligibility', methods=['POST', 'OPTIONS'])
    def api_pdi_generate_from_eligibility():
        if request.method == 'OPTIONS':
            return ('', 204)
        try:
            payload = request.get_json() or {}
            ok, err, status = require_rh_code(payload)
            if not ok:
                return jsonify(err), status

            user_email = (payload.get('user_email') or payload.get('actor_email') or '').strip().lower()
            cycle_code = (
                payload.get('cycle_code')
                or payload.get('round_code')
                or payload.get('ciclo_codigo')
                or ''
            ).strip()
            year = payload.get('year')
            items = payload.get('items') or []

            if not user_email:
                return jsonify({'error': 'USER_EMAIL_REQUIRED'}), 400
            if not cycle_code:
                return jsonify({'error': 'CYCLE_CODE_REQUIRED'}), 400
            if not isinstance(items, list) or not items:
                return jsonify({'error': 'ITEMS_REQUIRED'}), 400

            created = []
            skipped = []
            errors = []

            for item in items:
                try:
                    employee_id = int(item.get('employee_id'))
                except Exception:
                    errors.append({'employee_id': item.get('employee_id'), 'error': 'INVALID_EMPLOYEE_ID'})
                    continue

                has_mandatory = bool(item.get('mandatory_pdi') or item.get('pdi_required_dimensions'))
                has_proactive = bool(item.get('proactive_pdi'))
                if not has_mandatory and not has_proactive:
                    skipped.append({'employee_id': employee_id, 'reason': 'not_eligible'})
                    continue

                try:
                    existing = (
                        supabase.table('pdi_plans')
                        .select('id,status,origin_type')
                        .eq('employee_id', employee_id)
                        .eq('cycle_code', cycle_code)
                        .limit(1)
                        .execute()
                    )
                    existing_rows = existing.data or []
                    if existing_rows:
                        skipped.append({
                            'employee_id': employee_id,
                            'reason': 'already_exists',
                            'pdi_plan_id': existing_rows[0].get('id'),
                        })
                        continue
                except Exception as exc:
                    errors.append({'employee_id': employee_id, 'error': 'existing_plan_check_failed', 'detail': str(exc)})
                    continue

                origin_type = _plan_origin_type(item)
                now_iso = datetime.now(timezone.utc).isoformat()
                plan_payload = {
                    'cliente_id': item.get('cliente_id'),
                    'holding_id': item.get('holding_id'),
                    'empresa_id': item.get('empresa_id'),
                    'filial_id': item.get('filial_id'),
                    'employee_id': employee_id,
                    'manager_name': item.get('manager_name'),
                    'cycle_code': cycle_code,
                    'year': year,
                    'origin_type': origin_type,
                    'origin_evaluation_id': item.get('evaluation_id'),
                    'origin_ninebox_position': item.get('nine_box_position'),
                    'status': 'ativo',
                    'title': _plan_title(item, cycle_code),
                    'summary': 'PDI gerado a partir da elegibilidade automatica do The HR Key.',
                    'created_by_email': user_email,
                    'created_at': now_iso,
                    'updated_at': now_iso,
                }

                try:
                    inserted_plan = supabase.table('pdi_plans').insert(plan_payload).execute()
                    plan = (inserted_plan.data or [{}])[0]
                    plan_id = plan.get('id')
                    dimension_rows = []
                    for dim in (item.get('pdi_required_dimensions') or []):
                        if dim.get('dimension_code'):
                            dimension_rows.append({
                                'pdi_plan_id': plan_id,
                                'dimension_code': dim.get('dimension_code'),
                                'source_rating': dim.get('rating'),
                                'source_reason': 'PDI obrigatorio por dimensao na avaliacao de desempenho.',
                                'created_at': now_iso,
                                'updated_at': now_iso,
                            })
                    if dimension_rows:
                        supabase.table('pdi_plan_dimensions').insert(dimension_rows).execute()
                    supabase.table('pdi_events').insert({
                        'pdi_plan_id': plan_id,
                        'event_type': 'pdi_created_from_eligibility',
                        'event_payload': {
                            'origin_type': origin_type,
                            'eligibility_sources': item.get('eligibility_sources') or [],
                            'pdi_required_dimensions': item.get('pdi_required_dimensions') or [],
                            'proactive_pdi': has_proactive,
                            'nine_box_position': item.get('nine_box_position'),
                        },
                        'actor_email': user_email,
                        'created_at': now_iso,
                    }).execute()
                    created.append({
                        'employee_id': employee_id,
                        'employee_name': item.get('employee_name'),
                        'pdi_plan_id': plan_id,
                        'origin_type': origin_type,
                        'dimensions_created': len(dimension_rows),
                    })
                except Exception as exc:
                    errors.append({'employee_id': employee_id, 'error': 'plan_creation_failed', 'detail': str(exc)})

            return jsonify({
                'created_count': len(created),
                'skipped_count': len(skipped),
                'error_count': len(errors),
                'created': created,
                'skipped': skipped,
                'errors': errors,
            }), 200
        except Exception as exc:
            print('[pdi] erro interno generate:', exc)
            return jsonify({'error': 'internal', 'detail': str(exc)}), 500

    @app.route('/api/pdi/plans/<int:pdi_plan_id>/monthly-checkin', methods=['PUT', 'OPTIONS'])
    def api_pdi_monthly_checkin_upsert(pdi_plan_id):
        if request.method == 'OPTIONS':
            return ('', 204)
        try:
            payload = request.get_json() or {}
            ok, err, status = require_rh_code(payload)
            if not ok:
                return jsonify(err), status

            actor_email = (payload.get('user_email') or payload.get('actor_email') or '').strip().lower()
            reference_month = (payload.get('reference_month') or '').strip()
            if not actor_email:
                return jsonify({'error': 'USER_EMAIL_REQUIRED'}), 400
            if not reference_month:
                return jsonify({'error': 'REFERENCE_MONTH_REQUIRED'}), 400

            try:
                progress_percent = float(payload.get('progress_percent') or 0)
            except Exception:
                return jsonify({'error': 'INVALID_PROGRESS_PERCENT'}), 400
            progress_percent = max(0, min(100, progress_percent))

            status_summary = (payload.get('status_summary') or 'sem_atualizacao').strip()
            valid_statuses = {'sem_atualizacao', 'no_prazo', 'atencao', 'atrasado', 'concluido_no_mes'}
            if status_summary not in valid_statuses:
                return jsonify({'error': 'INVALID_STATUS_SUMMARY'}), 400

            now_iso = datetime.now(timezone.utc).isoformat()
            row = {
                'pdi_plan_id': pdi_plan_id,
                'reference_month': reference_month,
                'progress_percent': progress_percent,
                'status_summary': status_summary,
                'professional_comment': payload.get('professional_comment'),
                'manager_comment': payload.get('manager_comment'),
                'rh_comment': payload.get('rh_comment'),
                'next_steps': payload.get('next_steps'),
                'updated_by_email': actor_email,
                'updated_at': now_iso,
                'created_at': payload.get('created_at') or now_iso,
            }
            result = (
                supabase.table('pdi_monthly_checkins')
                .upsert(row, on_conflict='pdi_plan_id,reference_month')
                .execute()
            )
            try:
                supabase.table('pdi_events').insert({
                    'pdi_plan_id': pdi_plan_id,
                    'event_type': 'monthly_checkin_upserted',
                    'event_payload': {
                        'reference_month': reference_month,
                        'progress_percent': progress_percent,
                        'status_summary': status_summary,
                    },
                    'actor_email': actor_email,
                    'created_at': now_iso,
                }).execute()
            except Exception as exc:
                print('[pdi] erro ao registrar evento mensal:', exc)

            return jsonify({
                'message': 'Acompanhamento mensal salvo.',
                'item': (result.data or [row])[0],
            }), 200
        except Exception as exc:
            print('[pdi] erro interno monthly:', exc)
            return jsonify({'error': 'internal', 'detail': str(exc)}), 500
