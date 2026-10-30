"""Idempotent, explicitly labelled demo dataset. Never overwrites non-demo records."""
from __future__ import annotations
import argparse,hashlib,json,os,secrets,time
from datetime import datetime,timedelta,timezone
from pathlib import Path
from urllib.request import Request,urlopen
from urllib.error import HTTPError

DATASET='labconnect-demo-20261030'
ROLES=['Administrador','Administrador de Accesos','Encargado de Laboratorio','Docente','Estudiante','Invitado','OSI - Auditor de Seguridad']
def demo_id(key):return 'demo'+hashlib.sha256((DATASET+':'+key).encode()).hexdigest()[:11]
def stamp(day,hour=9):
    # Scheduling in LabConnect follows wall-clock laboratory time (45-minute blocks).
    return day.replace(hour=16 if hour==17 else hour,minute=15 if hour==14 else 45 if hour==17 else 0,second=0,microsecond=0,tzinfo=None).isoformat()
class PocketBase:
    def __init__(self,env_file):
        cfg={}
        for line in Path(env_file).read_text(encoding='utf-8-sig').splitlines():
            if '=' in line and not line.lstrip().startswith('#'):
                k,v=line.split('=',1);cfg[k.strip()]=v.strip().strip('"').strip("'")
        self.base=os.environ.get('DEMO_POCKETBASE_URL','http://127.0.0.1:8090').rstrip('/')
        self.token='';self.token=self.request('POST','/api/collections/_superusers/auth-with-password',{'identity':cfg['POCKETBASE_AUTH_IDENTITY'],'password':cfg['POCKETBASE_AUTH_PASSWORD']})['token']
        self.schemas={c['name']:c for c in self.request('GET','/api/collections?perPage=500')['items']}
    def request(self,method,path,payload=None):
        if method=='GET':path+=('&' if '?' in path else '?')+'demo_nonce='+str(time.time_ns())
        data=json.dumps(payload).encode() if payload is not None else None
        try:
            with urlopen(Request(self.base+path,data=data,headers={'Authorization':self.token,'Content-Type':'application/json'},method=method),timeout=60) as r:
                b=r.read();return json.loads(b) if b else None
        except HTTPError as e:
            details=e.read().decode()
            if 'auth-with-password' in path:details='Authentication failed'
            raise RuntimeError(f'{method} {path}: HTTP {e.code}: {details}') from None
    def records(self,col):return self.request('GET','/api/collections/'+col+'/records?perPage=500')['items']
    def create(self,col,key,payload):
        rid=demo_id(col+':'+key)
        try:
            existing=self.request('GET',f'/api/collections/{col}/records/{rid}')
        except RuntimeError as e:
            if 'HTTP 404:' not in str(e):raise
        else:
            if existing.get('demo_dataset')!=DATASET:raise RuntimeError('Refusing to overwrite a record outside this dataset')
            return existing
        valid={f['name'] for f in self.schemas[col]['fields']}
        data={k:v for k,v in payload.items() if k in valid or k in ('password','passwordConfirm')}
        if col in ('loan_record','inventory_loan_records_v2') and data.get('return_condition')=='good':data['return_condition']='ok'
        data.update(id=rid,is_demo=True,demo_dataset=DATASET)
        return self.request('POST',f'/api/collections/{col}/records',data)
    def mark_schema(self):
        for c in list(self.schemas.values()):
            if c.get('system') or c['type']=='view' or c['name']=='role':continue
            fields=list(c['fields']);names={f['name'] for f in fields}
            if 'is_demo' not in names:fields.append({'name':'is_demo','type':'bool'})
            if 'demo_dataset' not in names:fields.append({'name':'demo_dataset','type':'text','max':80})
            if len(fields)!=len(c['fields']):self.schemas[c['name']]=self.request('PATCH','/api/collections/'+c['id'],{'fields':fields})

def repair_demo_schedule_times(pb):
    """Align this dataset's existing rows with the application's academic blocks."""
    def write(col,row,patch):
        if any(row.get(k)!=v for k,v in patch.items()):pb.request('PATCH',f'/api/collections/{col}/records/{row["id"]}',patch)
    for col in ('lab_reservation','lab_access_sessions_v2','lab_access_session'):
        for row in pb.records(col):
            if row.get('demo_dataset')!=DATASET:continue
            date=str(row.get('start_at',''))[:10]
            patch={'start_at':date+'T14:15:00','end_at':date+'T15:00:00'}
            if col=='lab_reservation':patch['is_active']=row.get('status') not in {'completed','absent','cancelled','rejected'}
            if col!='lab_reservation':patch.update(check_in_at=date+'T14:15:00',check_out_at=date+'T15:00:00')
            write(col,row,patch)
    for row in pb.records('lab_schedule'):
        if row.get('demo_dataset')==DATASET:write('lab_schedule',row,{'start_time':'10:45','end_time':'11:30'})
    for col,date_field in (('inventory_equipment_requests_v2','requested_at'),('user_penalty_reactivation_history','executed_at')):
        for index,row in enumerate(pb.records(col)):
            if row.get('demo_dataset')==DATASET and not row.get(date_field):
                write(col,row,{date_field:stamp(datetime.now()-timedelta(days=7+index*5))})
    for row in pb.records('tutorial_session'):
        if row.get('demo_dataset')==DATASET:
            date=row['session_date'];write('tutorial_session',row,{'start_time':'16:00','end_time':'16:45','start_at':date+'T16:00:00','end_at':date+'T16:45:00'})
    for col in ('loan_record','inventory_loan_records_v2'):
        for row in pb.records(col):
            if row.get('demo_dataset')==DATASET and row.get('return_condition')=='good':write(col,row,{'return_condition':'ok'})

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--env-file',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--apply',action='store_true');a=p.parse_args()
    if not a.apply:print('Dry run: 10 demo accounts, 3 laboratories, historical activities across 120 days, upcoming availability, and business-table examples. Use --apply.');return
    pb=PocketBase(a.env_file)
    pb.request('POST','/api/backups',{'name':f'pb_backup_before_demo_dataset_{int(time.time())}.zip'})
    pb.mark_schema()
    now=datetime.now(timezone(timedelta(hours=-4)))
    roles={r['name']:r for r in pb.records('role')}
    state=json.loads(a.output.read_text()) if a.output.exists() else {'dataset':DATASET,'users':{},'labs':[],'areas':[],'assets':[],'stock':[],'reservations':[],'tutorials':[]}
    for i,role in enumerate(ROLES+['Estudiante','Estudiante','Docente']):
        key=str(i);password=state['users'].get(key,{}).get('password') or secrets.token_urlsafe(24)+'Aa1!'
        email=f'demo.{i+1}@demo.labconnect.invalid'
        user=pb.create('users',key,{'email':email,'name':f'[DEMO] {role} {i+1}','role':roles[role]['id'],'password':password,'passwordConfirm':password,'verified':True,'is_active':True,'auth_provider':'local','profile_type':'student' if role=='Estudiante' else 'teacher' if role=='Docente' else 'staff','session_version':1,'security_locked':False,'user_code':f'DEMO-{i+1:03d}','must_change_password':False,'password_changed_at':stamp(now-timedelta(days=7)),'password_expires_at':stamp(now+timedelta(days=90)),'bio':'[DEMO] Cuenta ficticia de demostracion; no corresponde a una persona real.'})
        state['users'][key]={'id':user['id'],'email':email,'password':password,'role':role,'name':user['name']}
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(state,indent=2,ensure_ascii=False));a.output.chmod(0o600)
    users=list(state['users'].values());admin=users[0];manager=users[2];teacher=users[3];students=[u for u in users if u['role']=='Estudiante']
    areas=[];labs=[];assets=[];stock=[]
    for i,topic in enumerate(('Electronica','Computacion','Fisica')):
        area=pb.create('area',str(i),{'name':f'[DEMO] Area de {topic}','description':'Datos ficticios para demostracion de LabConnect','is_active':True});areas.append(area)
        lab=pb.create('laboratory',str(i),{'name':f'[DEMO] Laboratorio de {topic}','area_id':area['id'],'location':f'[DEMO] Bloque Academico, aula {201+i}','capacity':20+i*5,'description':'[DEMO] Espacio ficticio; no representa inventario ni infraestructura real.','is_active':True,'manager':manager['id'],'allowed_roles':[],'allowed_user_ids':[],'required_permissions':[]});labs.append(lab)
        for j,kind in enumerate(('Multimetro digital','Fuente regulable','Computadora de practicas')):
            asset=pb.create('asset',f'{i}-{j}',{'name':f'[DEMO] {kind} {i+1}.{j+1}','category':'Instrumentacion','location':lab['location'],'description':'[DEMO] Equipo ficticio para probar inventario y prestamos','serial_number':f'DEMO-{i+1}-{j+1:03d}','laboratory_id':lab['id'],'status':'available','status_updated_at':stamp(now-timedelta(days=20)),'status_updated_by':admin['email']});assets.append(asset)
        for j,kind in enumerate(('Resistencias 1 kOhm','Capacitores 100 uF','Cables de conexion')):
            item=pb.create('stock_item',f'{i}-{j}',{'name':f'[DEMO] {kind} {i+1}','category':'Material de practicas','unit':'unidades','quantity_available':150-j*20,'minimum_stock':20,'laboratory_id':lab['id'],'description':'[DEMO] Existencias ficticias','limite_reserva_usuario':15});stock.append(item)
            for m in range(4):
                pb.create('stock_movement',f'{i}-{j}-{m}',{'stock_item_id':item['id'],'stock_item_name':item['name'],'movement_type':'entry' if m==0 else 'consumption','quantity_change':200 if m==0 else -10,'quantity_after':200-m*10,'performed_by':admin['email'],'notes':'[DEMO] Movimiento historico ficticio','created':stamp(now-timedelta(days=100-m*25))})
    state.update(areas=[x['id'] for x in areas],labs=[x['id'] for x in labs],assets=[x['id'] for x in assets],stock=[x['id'] for x in stock])
    reservations=[]
    for i in range(108):
        day=now-timedelta(days=120-i);lab=labs[i%3];student=students[i%len(students)]
        status=('completed','completed','completed','absent','cancelled','rejected')[i%6]
        res=pb.create('lab_reservation',str(i),{'laboratory_id':lab['id'],'area_id':lab['area_id'],'requested_by':student['id'],'requested_by_name':student['name'],'requested_by_email':student['email'],'purpose':f'[DEMO] Practica historica de laboratorio {i+1}','start_at':stamp(day,14),'end_at':stamp(day,15),'status':status,'attendees_count':1+i%4,'notes':'[DEMO] Actividad ficticia distribuida en el tiempo','is_active':True,'approved_by':admin['id'],'approved_at':stamp(day-timedelta(days=1)),'requires_full_lab':False,'origin':'student','responsible_teacher':teacher['id'],'responsible_teacher_name':teacher['name']});reservations.append(res)
        if status=='completed':
            session={'reservation_id':res['id'],'laboratory_id':lab['id'],'requested_by':student['id'],'occupant_name':student['name'],'occupant_email':student['email'],'purpose':res['purpose'],'start_at':res['start_at'],'end_at':res['end_at'],'check_in_at':stamp(day,14),'check_out_at':stamp(day,15),'status':'closed','is_walk_in':False,'recorded_by':manager['name'],'notes':'[DEMO] Acceso historico ficticio','station_label':f'DEMO-{i%10+1}'}
            pb.create('lab_access_sessions_v2',str(i),session)
            if i<12:pb.create('lab_access_session',str(i),session)
        if i%3==0:
            item=stock[i%len(stock)]
            pb.create('supply_reservation',str(i),{'stock_item_id':item['id'],'laboratory_id':lab['id'],'requested_by':student['id'],'quantity':1+i%5,'status':'delivered' if status=='completed' else 'cancelled','notes':'[DEMO] Solicitud historica ficticia','requested_for':day.date().isoformat(),'lab_reservation_id':res['id'],'created':stamp(day),'recurrence':'once'})
    for i,lab in enumerate(labs):
        for offset in (3,7,12):
            student=students[i%len(students)];day=now+timedelta(days=offset)
            res=pb.create('lab_reservation',f'future-{i}-{offset}',{'laboratory_id':lab['id'],'area_id':lab['area_id'],'requested_by':student['id'],'requested_by_name':student['name'],'requested_by_email':student['email'],'purpose':'[DEMO] Proxima practica de laboratorio','start_at':stamp(day,14),'end_at':stamp(day,15),'status':'approved' if offset==3 else 'pending','attendees_count':2,'notes':'[DEMO] Reserva ficticia; no corresponde a una actividad real','is_active':True,'origin':'student','requires_full_lab':False});reservations.append(res)
        pb.create('lab_schedule',str(i),{'laboratory_id':lab['id'],'weekday':2,'start_time':'10:00','end_time':'11:00','subject':'[DEMO] Clase semanal de fundamentos','description':'[DEMO] Horario docente ficticio','teacher_id':teacher['id'],'teacher_name':teacher['name'],'is_active':True,'approval_status':'approved','approved_by':admin['id'],'approved_at':stamp(now)})
        pb.create('lab_block',str(i),{'laboratory_id':lab['id'],'start_at':stamp(now+timedelta(days=10),17),'end_at':stamp(now+timedelta(days=10),18),'reason':'[DEMO] Mantenimiento preventivo ficticio','block_type':'maintenance','created_by':admin['id'],'is_active':True})
    tutorials=[]
    for i in range(12):
        day=now+timedelta(days=(i-8)*7+4);lab=labs[i%3]
        t=pb.create('tutorial_session',str(i),{'tutor_id':teacher['id'],'tutor_name':teacher['name'],'tutor_email':teacher['email'],'topic':f'[DEMO] Refuerzo de circuitos y programacion {i+1}','description':'[DEMO] Tutoria ficticia para explorar inscripciones y asistencia','laboratory_id':lab['id'],'location':lab['name'],'session_date':day.date().isoformat(),'start_time':'16:00','end_time':'17:00','start_at':stamp(day,16),'end_at':stamp(day,17),'max_students':12,'is_published':True,'approval_status':'approved','requires_full_lab':False});tutorials.append(t)
        for j,student in enumerate(students[:2]):
            pb.create('tutorial_enrollment',f'{i}-{j}',{'session_id':t['id'],'tutorial_session_id':t['id'],'student_id':student['id'],'student_name':student['name'],'student_email':student['email'],'created_at':stamp(day-timedelta(days=2)),'attended':i<8,'performance_observation':'[DEMO] Ejercicio de seguimiento academico'})
            if i<8:pb.create('tutorial_session_attendance',f'{i}-{j}',{'session_id':t['id'],'student_id':student['id'],'attended':True,'performance_observation':'[DEMO] Practica completada'})
        if i<8:pb.create('tutorial_session_observation',str(i),{'session_id':t['id'],'tutor_id':teacher['id'],'observation':'[DEMO] Grupo de demostracion completo la practica.'})
    for i in range(12):
        student=students[i%len(students)];asset=assets[i%len(assets)];lab=labs[(i//3)%3];day=now-timedelta(days=60-i*4)
        loan={'asset_id':asset['id'],'asset_name':asset['name'],'asset_serial_number':asset['serial_number'],'laboratory_id':lab['id'],'laboratory_name':lab['name'],'borrower_id':student['id'],'borrower_name':student['name'],'borrower_email':student['email'],'borrower_role':'Estudiante','purpose':'[DEMO] Practica de mediciones','notes':'[DEMO] Prestamo ficticio','status':'returned','loaned_by':manager['name'],'returned_by':manager['name'],'loaned_at':stamp(day),'due_at':stamp(day,12),'returned_at':stamp(day,11),'return_condition':'good','return_notes':'[DEMO] Devolucion de ejemplo'}
        pb.create('inventory_loan_records_v2',str(i),loan)
        if i<3:pb.create('loan_record',str(i),loan)
        pb.create('inventory_equipment_requests_v2',str(i),{'asset_id':asset['id'],'asset_name':asset['name'],'asset_serial_number':asset['serial_number'],'laboratory_id':lab['id'],'laboratory_name':lab['name'],'requested_by':teacher['id'],'requested_by_name':teacher['name'],'requested_by_email':teacher['email'],'requested_by_role':'Docente','purpose':'[DEMO] Solicitud ficticia de equipo','status':'approved' if i<9 else 'pending','requested_at':stamp(day),'decided_at':stamp(day,10),'decided_by':manager['name'],'notes':'[DEMO] Solicitud demostrativa'})
        if i<4:pb.create('inventory_asset_maintenance_tickets_v2',str(i),{'asset_id':asset['id'],'asset_name':asset['name'],'laboratory_id':lab['id'],'ticket_type':'maintenance','title':'[DEMO] Calibracion preventiva','description':'[DEMO] Ticket ficticio cerrado para demostracion','severity':'low','status':'closed','reported_at':stamp(day),'reported_by':manager['email'],'resolved_at':stamp(day+timedelta(days=1)),'resolved_by':admin['email'],'resolution_notes':'[DEMO] Calibracion de ejemplo','asset_status_before':'available','asset_status_after_open':'maintenance','asset_status_after_close':'available'})
    for i in range(3):
        student=students[i];day=now-timedelta(days=40-i*7)
        penalty=pb.create('user_penalty',str(i),{'user_id':student['id'],'user_name':student['name'],'user_email':student['email'],'reason':'[DEMO] Incidencia ficticia ya regularizada','evidence_type':'damage_report','evidence_report_id':demo_id('evidence'+str(i)),'starts_at':stamp(day),'ends_at':stamp(day+timedelta(days=2)),'notes':'[DEMO] No afecta a usuarios reales','status':'lifted','is_active':False,'created_by':admin['id'],'created_by_name':admin['name'],'lifted_at':stamp(day+timedelta(days=1)),'lifted_by':admin['id'],'lift_reason':'[DEMO] Regularizacion simulada','created_at':stamp(day),'updated_at':stamp(day+timedelta(days=1))})
        pb.create('user_penalty_reactivation_history',str(i),{'penalty_id':penalty['id'],'user_id':student['id'],'user_name':student['name'],'user_email':student['email'],'actor_user_id':admin['id'],'actor_name':admin['name'],'executed_at':stamp(day+timedelta(days=1)),'lift_reason':'[DEMO] Demostracion','resolution_notes':'[DEMO] Incidencia regularizada','action_source':'demo_dataset','user_is_active_after':True,'privileges_restored':True,'regularization_confirmed':True})
        pb.create('security_incident',str(i),{'title':'[DEMO] Revision de acceso de ejemplo','description':'[DEMO] Incidente ficticio; no describe un ataque real','severity':'low','status':'closed','responsible':users[6]['name'],'evidence':{'dataset':DATASET,'synthetic':True}})
        pb.create('access_review',str(i),{'period':(now-timedelta(days=30*i)).strftime('%Y-%m'),'user_id':student['id'],'role_name':'Estudiante','reviewer_id':users[6]['id'],'decision':'maintain','observation':'[DEMO] Revision ficticia de permisos','status':'completed'})
        pb.create('security_audit_event',str(i),{'action':'demo.activity.generated','actor_id':admin['id'],'actor_email':admin['email'],'target_type':'demo_dataset','target_id':DATASET,'result':'success','reason':'[DEMO] Evento de demostracion, no evidencia historica real','metadata':{'synthetic':True,'dataset':DATASET,'simulated_at':stamp(now-timedelta(days=30*i))}})
        pb.create('role_change_history',str(i),{'actor_id':admin['id'],'actor_email':admin['email'],'actor_role':'Administrador','action':'demo.role_assignment','role_id':roles['Estudiante']['id'],'role_name':'Estudiante','target_user_id':student['id'],'target_email':student['email'],'before':{},'after':{'role':'Estudiante','synthetic':True},'reason':'[DEMO] Registro ficticio de asignacion; no es una modificacion historica real','result':'success'})
    state.update(reservations=[r['id'] for r in reservations],tutorials=[t['id'] for t in tutorials])
    a.output.write_text(json.dumps(state,indent=2,ensure_ascii=False));a.output.chmod(0o600)
    repair_demo_schedule_times(pb)
    counts={c:len([r for r in pb.records(c) if r.get('demo_dataset')==DATASET]) for c,s in pb.schemas.items() if not s.get('system') and s['type']!='view'}
    print(json.dumps({'dataset':DATASET,'counts':counts,'credentials_file':str(a.output)},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
