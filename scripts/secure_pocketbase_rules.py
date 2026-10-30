"""Apply the backend-owned write policy without changing fields or records.

Run on the PocketBase host with --env-file and --apply. The default is a dry run.
Backend services authenticate as a superuser and enforce role and workflow rules;
native PocketBase user tokens only expose the explicitly allowed read scopes.
"""
import argparse
import json
import time
from pathlib import Path

from seed_demo_data import PocketBase

OWNER_RULES = {
    'users': 'id = @request.auth.id',
    **{name: '@request.auth.id != "" && requested_by = @request.auth.id' for name in (
        'lab_reservation', 'supply_reservation', 'inventory_equipment_requests_v2',
        'lab_access_session', 'lab_access_sessions_v2',
    )},
    **{name: '@request.auth.id != "" && borrower_id = @request.auth.id' for name in (
        'inventory_loan_records_v2', 'loan_record',
    )},
    **{name: '@request.auth.id != "" && student_id = @request.auth.id' for name in (
        'tutorial_enrollment', 'tutorial_session_attendance',
    )},
    'lab_schedule': '@request.auth.id != "" && ((is_active = true && approval_status = "approved") || teacher_id = @request.auth.id)',
}
PRIVATE_COLLECTIONS = {
    'password_history', 'auth_session', 'security_audit_event', 'role_change_history',
    'security_incident', 'access_review', 'user_penalty',
    'user_penalty_reactivation_history', 'inventory_asset_maintenance_tickets_v2',
    'tutorial_session_observation', 'tutorial_session', 'prediction_cache',
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    pb = PocketBase(args.env_file)
    if args.apply:
        pb.request('POST', '/api/backups', {'name': f'pb_backup_before_rule_audit_{int(time.time())}.zip'})
    report = []
    for collection in pb.schemas.values():
        if collection.get('system'):
            continue
        patch = {} if collection['type'] == 'view' else dict.fromkeys(('createRule', 'updateRule', 'deleteRule'))
        name = collection['name']
        if name in OWNER_RULES:
            patch.update(listRule=OWNER_RULES[name], viewRule=OWNER_RULES[name])
        elif name in PRIVATE_COLLECTIONS:
            patch.update(listRule=None, viewRule=None)
        if patch and args.apply:
            pb.request('PATCH', '/api/collections/' + collection['id'], patch)
        report.append({'collection': name, **{key: patch.get(key, collection.get(key)) for key in (
            'listRule', 'viewRule', 'createRule', 'updateRule', 'deleteRule',
        )}})
    Path(args.output).write_text(json.dumps({'applied': args.apply, 'collections': report}, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'{len(report)} collections inspected; applied={args.apply}')


if __name__ == '__main__':
    main()
