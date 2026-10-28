import os, csv, io
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, render_template, redirect, url_for, request, flash, abort, Response, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_wtf.csrf import CSRFProtect
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import uuid
from sqlalchemy import or_, func

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-only-change-me')
db_url = os.getenv('DATABASE_URL', 'sqlite:///helpdesk.db')
if db_url.startswith('postgres://'): db_url = db_url.replace('postgres://', 'postgresql+psycopg://', 1)
elif db_url.startswith('postgresql://'): db_url = db_url.replace('postgresql://', 'postgresql+psycopg://', 1)
app.config.update(SQLALCHEMY_DATABASE_URI=db_url, SQLALCHEMY_TRACK_MODIFICATIONS=False, MAX_CONTENT_LENGTH=8*1024*1024, UPLOAD_FOLDER=os.path.join(app.root_path,'uploads'))
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
db = SQLAlchemy(app); login_manager = LoginManager(app); login_manager.login_view = 'login'; login_manager.login_message_category='warning'; CSRFProtect(app)

PRIORITIES = ['Low','Medium','High','Urgent','Critical']
STATUSES = ['New','Assigned','In Progress','Pending','Resolved','Closed','Reopened']
CATEGORIES = ['Hardware','Software','Network','Account','Email','Application Support','Other']
ALLOWED_EXTENSIONS = {'png','jpg','jpeg','gif','pdf','txt','csv','doc','docx','xls','xlsx','log'}
ROLES = ['customer','agent','lead','admin']
SLA_HOURS = {'Low':(24,120),'Medium':(8,72),'High':(4,24),'Urgent':(1,8),'Critical':(0.5,4)}

class User(UserMixin, db.Model):
    id=db.Column(db.Integer,primary_key=True); name=db.Column(db.String(100),nullable=False); email=db.Column(db.String(160),unique=True,nullable=False,index=True); password_hash=db.Column(db.String(255),nullable=False); role=db.Column(db.String(20),default='customer',nullable=False); department=db.Column(db.String(100),default=''); phone=db.Column(db.String(40),default=''); active=db.Column(db.Boolean,default=True); created_at=db.Column(db.DateTime,default=datetime.utcnow)
    def set_password(self,p): self.password_hash=generate_password_hash(p)
    def check_password(self,p): return check_password_hash(self.password_hash,p)
    @property
    def is_staff(self): return self.role in ('agent','lead','admin')

class Ticket(db.Model):
    id=db.Column(db.Integer,primary_key=True); number=db.Column(db.String(24),unique=True,index=True); subject=db.Column(db.String(180),nullable=False); description=db.Column(db.Text,nullable=False); category=db.Column(db.String(60),nullable=False); priority=db.Column(db.String(20),default='Medium'); status=db.Column(db.String(30),default='New'); customer_id=db.Column(db.Integer,db.ForeignKey('user.id'),nullable=False); assignee_id=db.Column(db.Integer,db.ForeignKey('user.id')); team=db.Column(db.String(100),default='Service Desk'); created_at=db.Column(db.DateTime,default=datetime.utcnow); updated_at=db.Column(db.DateTime,default=datetime.utcnow,onupdate=datetime.utcnow); first_response_at=db.Column(db.DateTime); resolved_at=db.Column(db.DateTime); response_due=db.Column(db.DateTime); resolution_due=db.Column(db.DateTime); resolution_summary=db.Column(db.Text); root_cause=db.Column(db.Text); solution=db.Column(db.Text); escalated=db.Column(db.Boolean,default=False); rating=db.Column(db.Integer); feedback=db.Column(db.Text)
    customer=db.relationship('User',foreign_keys=[customer_id]); assignee=db.relationship('User',foreign_keys=[assignee_id]); messages=db.relationship('Message',backref='ticket',cascade='all, delete-orphan',order_by='Message.created_at'); events=db.relationship('Event',backref='ticket',cascade='all, delete-orphan',order_by='Event.created_at')
    @property
    def sla_state(self):
        if self.status in ('Resolved','Closed'): return 'Met' if (not self.resolved_at or self.resolved_at<=self.resolution_due) else 'Breached'
        now=datetime.utcnow()
        if self.resolution_due and now>self.resolution_due: return 'Breached'
        if self.resolution_due and (self.resolution_due-now).total_seconds()<3600: return 'At risk'
        return 'On track'
class Message(db.Model):
    id=db.Column(db.Integer,primary_key=True); ticket_id=db.Column(db.Integer,db.ForeignKey('ticket.id'),nullable=False); user_id=db.Column(db.Integer,db.ForeignKey('user.id')); body=db.Column(db.Text,nullable=False); internal=db.Column(db.Boolean,default=False); created_at=db.Column(db.DateTime,default=datetime.utcnow); author=db.relationship('User')
class Attachment(db.Model):
    id=db.Column(db.Integer,primary_key=True);ticket_id=db.Column(db.Integer,db.ForeignKey('ticket.id'),nullable=False);uploader_id=db.Column(db.Integer,db.ForeignKey('user.id'));original_name=db.Column(db.String(255),nullable=False);stored_name=db.Column(db.String(255),nullable=False);created_at=db.Column(db.DateTime,default=datetime.utcnow);uploader=db.relationship('User')
class Event(db.Model):
    id=db.Column(db.Integer,primary_key=True); ticket_id=db.Column(db.Integer,db.ForeignKey('ticket.id'),nullable=False); user_id=db.Column(db.Integer,db.ForeignKey('user.id')); action=db.Column(db.String(120)); detail=db.Column(db.String(255),default=''); created_at=db.Column(db.DateTime,default=datetime.utcnow); actor=db.relationship('User')
class Article(db.Model):
    id=db.Column(db.Integer,primary_key=True); title=db.Column(db.String(180),nullable=False); category=db.Column(db.String(60),default='General'); body=db.Column(db.Text,nullable=False); published=db.Column(db.Boolean,default=True); author_id=db.Column(db.Integer,db.ForeignKey('user.id')); created_at=db.Column(db.DateTime,default=datetime.utcnow); author=db.relationship('User')
class Notice(db.Model):
    id=db.Column(db.Integer,primary_key=True); user_id=db.Column(db.Integer,db.ForeignKey('user.id'),nullable=False); text=db.Column(db.String(255)); link=db.Column(db.String(255)); read=db.Column(db.Boolean,default=False); created_at=db.Column(db.DateTime,default=datetime.utcnow)

@login_manager.user_loader
def load_user(uid): return db.session.get(User,int(uid))

def role_required(*roles):
    def dec(fn):
        @wraps(fn)
        @login_required
        def wrapped(*a,**kw):
            if current_user.role not in roles: abort(403)
            return fn(*a,**kw)
        return wrapped
    return dec

def notify(user_id,text,link):
    if user_id and user_id != getattr(current_user,'id',None): db.session.add(Notice(user_id=user_id,text=text,link=link))
def log_event(ticket,action,detail=''):
    db.session.add(Event(ticket_id=ticket.id,user_id=current_user.id,action=action,detail=detail))
def visible_ticket_query():
    q=Ticket.query
    if current_user.role=='customer': q=q.filter_by(customer_id=current_user.id)
    elif current_user.role=='agent': q=q.filter_by(assignee_id=current_user.id)
    return q

def can_view(ticket):
    return current_user.is_staff or ticket.customer_id==current_user.id

def ticket_or_404(tid):
    t=db.session.get(Ticket,tid)
    if not t or not can_view(t): abort(404)
    return t

@app.context_processor
def common():
    unread=Notice.query.filter_by(user_id=current_user.id,read=False).count() if current_user.is_authenticated else 0
    return dict(PRIORITIES=PRIORITIES,STATUSES=STATUSES,CATEGORIES=CATEGORIES,unread=unread,now=datetime.utcnow())

@app.route('/')
def home(): return render_template('home.html')
@app.route('/health')
def health(): return {'status':'ok'}
@app.route('/login',methods=['GET','POST'])
def login():
    if current_user.is_authenticated:return redirect(url_for('dashboard'))
    if request.method=='POST':
        email=request.form.get('email','').strip().lower(); u=User.query.filter(func.lower(User.email)==email).first()
        if u and u.check_password(request.form.get('password','')) and u.active:
            login_user(u,remember=bool(request.form.get('remember'))); return redirect(request.args.get('next') or url_for('home'))
        flash('Email or password is incorrect, or the account is inactive.','danger')
    return render_template('login.html')
@app.route('/register',methods=['GET','POST'])
def register():
    if request.method=='POST':
        name=request.form.get('name','').strip(); email=request.form.get('email','').strip().lower(); password=request.form.get('password','')
        if not name or len(password)<8: flash('Enter your name and a password of at least 8 characters.','danger')
        elif User.query.filter_by(email=email).first(): flash('That email is already registered.','danger')
        else:
            u=User(name=name,email=email,role='customer');u.set_password(password);db.session.add(u);db.session.commit();login_user(u);flash('Welcome! Your account is ready.','success');return redirect(request.args.get('next') or url_for('home'))
    return render_template('register.html')
@app.route('/logout',methods=['POST'])
@login_required
def logout(): logout_user();flash('You have been signed out.','success');return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    q=visible_ticket_query(); tickets=q.order_by(Ticket.updated_at.desc()).limit(8).all(); counts={s:q.filter_by(status=s).count() for s in STATUSES}; total=q.count()
    if current_user.is_staff:
        allq=Ticket.query; resolved=allq.filter(Ticket.resolved_at.isnot(None)).all(); responded=allq.filter(Ticket.first_response_at.isnot(None)).all()
        response_hours=[(t.first_response_at-t.created_at).total_seconds()/3600 for t in responded]
        resolution_hours=[(t.resolved_at-t.created_at).total_seconds()/3600 for t in resolved]
        sla_met=sum(1 for t in resolved if t.resolved_at and t.resolution_due and t.resolved_at<=t.resolution_due)
        stats={'total':total,'open':sum(counts.get(x,0) for x in ['New','Assigned','In Progress','Pending','Reopened']),'resolved':counts.get('Resolved',0)+counts.get('Closed',0),'sla':round(sla_met/len(resolved)*100) if resolved else 100,'avg_response':round(sum(response_hours)/len(response_hours),1) if response_hours else None,'avg_resolve':round(sum(resolution_hours)/len(resolution_hours),1) if resolution_hours else None}
        workload= db.session.query(User,func.count(Ticket.id)).outerjoin(Ticket, (Ticket.assignee_id==User.id)&(~Ticket.status.in_(['Resolved','Closed']))).filter(User.role=='agent',User.active==True).group_by(User.id).all()
    else: stats={'total':total,'open':sum(counts.get(x,0) for x in ['New','Assigned','In Progress','Pending','Reopened']),'resolved':counts.get('Resolved',0)+counts.get('Closed',0),'sla':None,'avg_response':None,'avg_resolve':None};workload=[]
    return render_template('dashboard.html',tickets=tickets,counts=counts,stats=stats,workload=workload)

@app.route('/tickets')
@login_required
def tickets():
    q=visible_ticket_query(); term=request.args.get('q','').strip(); status=request.args.get('status','');priority=request.args.get('priority','');category=request.args.get('category','')
    if term:q=q.join(User,Ticket.customer_id==User.id).filter(or_(Ticket.number.ilike(f'%{term}%'),Ticket.subject.ilike(f'%{term}%'),User.name.ilike(f'%{term}%')))
    if status:q=q.filter_by(status=status)
    if priority:q=q.filter_by(priority=priority)
    if category:q=q.filter_by(category=category)
    results=q.order_by(Ticket.created_at.desc()).all()
    return render_template('tickets.html',tickets=results,filters={'q':term,'status':status,'priority':priority,'category':category})

@app.route('/tickets/new',methods=['GET','POST'])
@login_required
def new_ticket():
    if request.method=='POST':
        subject=request.form.get('subject','').strip();description=request.form.get('description','').strip();category=request.form.get('category','');priority=request.form.get('priority','Medium');upload=request.files.get('attachment')
        bad_file=bool(upload and upload.filename and ('.' not in upload.filename or upload.filename.rsplit('.',1)[1].lower() not in ALLOWED_EXTENSIONS))
        if not subject or len(subject)>180 or not description or category not in CATEGORIES or priority not in PRIORITIES: flash('Please complete all required fields with valid values.','danger')
        elif bad_file: flash('This file type is not supported. Attach a PDF, image, office document, CSV, text, or log file.','danger')
        else:
            rhrs,shrs=SLA_HOURS[priority];ticket=Ticket(subject=subject,description=description,category=category,priority=priority,customer_id=current_user.id,response_due=datetime.utcnow()+timedelta(hours=rhrs),resolution_due=datetime.utcnow()+timedelta(hours=shrs));db.session.add(ticket);db.session.flush();ticket.number=f"HD-{datetime.utcnow().year}-{ticket.id:04d}";db.session.add(Event(ticket_id=ticket.id,user_id=current_user.id,action='Ticket created',detail=f'{priority} priority · {category}'))
            if upload and upload.filename:
                stored=uuid.uuid4().hex+'_'+secure_filename(upload.filename);upload.save(os.path.join(app.config['UPLOAD_FOLDER'],stored));db.session.add(Attachment(ticket_id=ticket.id,uploader_id=current_user.id,original_name=secure_filename(upload.filename),stored_name=stored))
            db.session.commit()
            for u in User.query.filter(User.role.in_(['lead','admin'])).all():notify(u.id,f'New {priority.lower()} ticket {ticket.number}',url_for('ticket_detail',tid=ticket.id))
            db.session.commit();flash(f'Ticket {ticket.number} created.','success');return redirect(url_for('ticket_detail',tid=ticket.id))
    return render_template('new_ticket.html')

@app.route('/tickets/<int:tid>',methods=['GET','POST'])
@login_required
def ticket_detail(tid):
    t=ticket_or_404(tid)
    if request.method=='POST':
        action=request.form.get('action')
        if action=='reply':
            body=request.form.get('body','').strip();internal=request.form.get('internal')=='1' and current_user.is_staff
            if not body:flash('Message cannot be empty.','danger')
            else:
                db.session.add(Message(ticket_id=t.id,user_id=current_user.id,body=body,internal=internal))
                if current_user.is_staff and not internal and not t.first_response_at:t.first_response_at=datetime.utcnow()
                recipient=t.customer_id if current_user.is_staff else t.assignee_id
                if not internal:notify(recipient,f'New reply on {t.number}',url_for('ticket_detail',tid=t.id))
                log_event(t,'Internal note added' if internal else 'Reply sent');db.session.commit();flash('Your message was added.','success')
        elif action=='assign' and current_user.role in ('lead','admin'):
            aid=request.form.get('assignee_id',type=int);assignee=db.session.get(User,aid) if aid else None
            if aid and (not assignee or assignee.role not in ('agent','lead') or not assignee.active):flash('Choose an active support agent.','danger')
            else:
                old=t.assignee.name if t.assignee else 'Unassigned';t.assignee_id=aid;t.status='Assigned' if aid and t.status=='New' else t.status;log_event(t,'Ticket assigned',f'{old} → {assignee.name if assignee else "Unassigned"}');notify(aid,f'{t.number} assigned to you',url_for('ticket_detail',tid=t.id));db.session.commit();flash('Assignment updated.','success')
        elif action=='status' and current_user.is_staff:
            status=request.form.get('status');valid={'New':['Assigned'],'Assigned':['In Progress','Pending','Reopened'],'In Progress':['Pending','Resolved','Reopened'],'Pending':['In Progress','Resolved','Reopened'],'Resolved':['Closed','Reopened'],'Closed':['Reopened'],'Reopened':['Assigned','In Progress','Pending','Resolved']}
            if status not in valid.get(t.status,[]):flash(f'Cannot change {t.status} to {status}.','danger')
            else:
                old=t.status;t.status=status
                if status=='Resolved':t.resolved_at=datetime.utcnow();t.resolution_summary=request.form.get('summary','').strip();t.root_cause=request.form.get('root_cause','').strip();t.solution=request.form.get('solution','').strip()
                if status=='Reopened':t.resolved_at=None
                log_event(t,'Status changed',f'{old} → {status}');notify(t.customer_id,f'{t.number} is now {status}',url_for('ticket_detail',tid=t.id));db.session.commit();flash(f'Ticket marked {status.lower()}.','success')
        elif action=='escalate' and current_user.is_staff:
            reason=request.form.get('reason','').strip();t.escalated=True;log_event(t,'Escalated',reason or 'Escalated by support');
            for u in User.query.filter(User.role.in_(['lead','admin'])).all():notify(u.id,f'{t.number} has been escalated',url_for('ticket_detail',tid=t.id))
            db.session.commit();flash('Ticket escalated to the team lead.','success')
        elif action=='customer_status' and t.customer_id==current_user.id:
            target=request.form.get('status');reason=request.form.get('reason','').strip()
            if target=='Closed' and t.status=='Resolved':
                t.status='Closed';log_event(t,'Resolution confirmed','Customer confirmed the issue is resolved.');db.session.commit();flash('Ticket closed. Thank you for confirming.','success')
            elif target=='Reopened' and t.status in ('Resolved','Closed'):
                if not reason:flash('Please explain why the issue needs to be reopened.','danger')
                else:
                    old=t.status;t.status='Reopened';t.resolved_at=None;log_event(t,'Ticket reopened',reason);notify(t.assignee_id,f'{t.number} was reopened by the customer',url_for('ticket_detail',tid=t.id));db.session.commit();flash('Ticket reopened for the support team.','success')
            else:flash('That customer action is not available for the current ticket status.','danger')
        elif action=='feedback' and t.customer_id==current_user.id and t.status in ('Resolved','Closed'):
            rating=request.form.get('rating',type=int);feedback=request.form.get('feedback','').strip()
            if rating not in range(1,6):flash('Select a rating from 1 to 5.','danger')
            else:t.rating=rating;t.feedback=feedback;db.session.commit();flash('Thanks for your feedback!','success')
        return redirect(url_for('ticket_detail',tid=t.id))
    agents=User.query.filter(User.role.in_(['agent','lead']),User.active==True).order_by(User.name).all() if current_user.role in ('lead','admin') else []
    attachments=Attachment.query.filter_by(ticket_id=t.id).order_by(Attachment.created_at.asc()).all()
    return render_template('ticket_detail.html',ticket=t,agents=agents,attachments=attachments)

@app.route('/tickets/<int:tid>/attachments/<int:aid>')
@login_required
def download_attachment(tid,aid):
    ticket=ticket_or_404(tid);attachment=Attachment.query.filter_by(id=aid,ticket_id=ticket.id).first_or_404()
    return send_from_directory(app.config['UPLOAD_FOLDER'],attachment.stored_name,as_attachment=True,download_name=attachment.original_name)

@app.route('/knowledge',methods=['GET','POST'])
@login_required
def knowledge():
    if request.method=='POST':
        if not current_user.is_staff:abort(403)
        title=request.form.get('title','').strip();body=request.form.get('body','').strip();category=request.form.get('category','General').strip()
        if title and body:db.session.add(Article(title=title,body=body,category=category,author_id=current_user.id));db.session.commit();flash('Knowledge article published.','success');return redirect(url_for('knowledge'))
        flash('Title and article content are required.','danger')
    term=request.args.get('q','').strip();q=Article.query.filter_by(published=True)
    if term:q=q.filter(or_(Article.title.ilike(f'%{term}%'),Article.body.ilike(f'%{term}%'),Article.category.ilike(f'%{term}%')))
    return render_template('knowledge.html',articles=q.order_by(Article.created_at.desc()).all(),term=term)

@app.route('/reports')
@role_required('lead','admin')
def reports():
    tickets=Ticket.query.order_by(Ticket.created_at.desc()).all();bycat={c:Ticket.query.filter_by(category=c).count() for c in CATEGORIES};bypriority={p:Ticket.query.filter_by(priority=p).count() for p in PRIORITIES}
    return render_template('reports.html',tickets=tickets,bycat=bycat,bypriority=bypriority)
@app.route('/reports/export')
@role_required('lead','admin')
def export_report():
    output=io.StringIO();w=csv.writer(output);w.writerow(['Ticket','Subject','Customer','Category','Priority','Status','Agent','Created UTC','First response UTC','Resolved UTC','SLA','Rating'])
    for t in Ticket.query.order_by(Ticket.created_at.desc()).all():w.writerow([t.number,t.subject,t.customer.name,t.category,t.priority,t.status,t.assignee.name if t.assignee else '',t.created_at.isoformat(),t.first_response_at.isoformat() if t.first_response_at else '',t.resolved_at.isoformat() if t.resolved_at else '',t.sla_state,t.rating or ''])
    return Response(output.getvalue(),mimetype='text/csv',headers={'Content-Disposition':'attachment; filename=helpdesk-report.csv'})

@app.route('/team',methods=['GET','POST'])
@role_required('admin')
def team():
    if request.method=='POST':
        name=request.form.get('name','').strip();email=request.form.get('email','').strip().lower();role=request.form.get('role','agent');password=request.form.get('password','')
        if not name or not email or role not in ROLES or len(password)<8:flash('Provide valid details and a password of at least 8 characters.','danger')
        elif User.query.filter_by(email=email).first():flash('Email already exists.','danger')
        else:u=User(name=name,email=email,role=role,department=request.form.get('department',''));u.set_password(password);db.session.add(u);db.session.commit();flash(f'{name} added as {role}.','success');return redirect(url_for('team'))
    users=User.query.order_by(User.role,User.name).all();load=db.session.query(User,func.count(Ticket.id)).outerjoin(Ticket,(Ticket.assignee_id==User.id)&(~Ticket.status.in_(['Resolved','Closed']))).filter(User.role.in_(['agent','lead'])).group_by(User.id).all()
    return render_template('team.html',users=users,load=load)
@app.route('/profile',methods=['GET','POST'])
@login_required
def profile():
    if request.method=='POST':
        current_user.name=request.form.get('name','').strip();current_user.phone=request.form.get('phone','').strip();current_user.department=request.form.get('department','').strip()
        if not current_user.name:flash('Name is required.','danger')
        else:db.session.commit();flash('Profile updated.','success')
    return render_template('profile.html')
@app.route('/notifications')
@login_required
def notifications():
    rows=Notice.query.filter_by(user_id=current_user.id).order_by(Notice.created_at.desc()).limit(50).all()
    for n in rows:n.read=True
    db.session.commit();return render_template('notifications.html',notices=rows)
@app.errorhandler(403)
def forbidden(e):return render_template('error.html',code=403,message='You do not have permission to access this page.'),403
@app.errorhandler(404)
def not_found(e):return render_template('error.html',code=404,message='This page or ticket could not be found.'),404

with app.app_context():
    db.create_all()
    # Keep already-created demo accounts aligned with the requested helpdesk domain.
    for demo_user in User.query.filter(User.email.like('%@helpdesk.demo')).all():
        demo_user.email=demo_user.email.replace('@helpdesk.demo','@helpdesk.com.kh')
    db.session.commit()
    for cat in CATEGORIES:
        pass
    if os.getenv('SEED_DEMO','true').lower()=='true' and User.query.count()==0:
        demo=[('Amina Customer','customer@helpdesk.com.kh','Customer123!','customer'),('Dara Agent','agent@helpdesk.com.kh','Agent123!','agent'),('Sokha Lead','lead@helpdesk.com.kh','Lead123!','lead'),('Admin User','admin@helpdesk.com.kh','Admin123!','admin')]
        for name,email,pw,role in demo:u=User(name=name,email=email,role=role,department='IT Support');u.set_password(pw);db.session.add(u)
        db.session.commit()
        customer=User.query.filter_by(role='customer').first();agent=User.query.filter_by(role='agent').first()
        samples=[('Laptop cannot connect to office Wi-Fi','After the latest update my laptop sees the network but will not connect.','Network','High','In Progress'),('Access request for finance application','Please grant me access to the monthly reporting workspace.','Account','Medium','Assigned'),('Printer on level two is offline','The shared printer is showing an offline status.','Hardware','Low','New')]
        for subject,desc,cat,pri,status in samples:
            rh,sh=SLA_HOURS[pri];t=Ticket(subject=subject,description=desc,category=cat,priority=pri,status=status,customer_id=customer.id,assignee_id=agent.id if status!='New' else None,response_due=datetime.utcnow()+timedelta(hours=rh),resolution_due=datetime.utcnow()+timedelta(hours=sh));db.session.add(t);db.session.flush();t.number=f'HD-{datetime.utcnow().year}-{t.id:04d}';db.session.add(Event(ticket_id=t.id,user_id=customer.id,action='Ticket created'));db.session.add(Message(ticket_id=t.id,user_id=agent.id,body='We are looking into this and will update you shortly.') if status=='In Progress' else Message(ticket_id=t.id,user_id=customer.id,body=desc))
        db.session.add(Article(title='Quick Wi-Fi troubleshooting',category='Network',body='1. Confirm Wi-Fi is enabled.\n2. Forget the office network and reconnect.\n3. Restart the device.\n4. If the issue continues, submit a ticket with your device name and location.',author_id=agent.id));db.session.commit()

    bootstrap_email=os.getenv('ADMIN_EMAIL','').strip().lower();bootstrap_password=os.getenv('ADMIN_PASSWORD','')
    if bootstrap_email and len(bootstrap_password)>=12 and User.query.filter_by(role='admin').count()==0 and User.query.filter(func.lower(User.email)==bootstrap_email).first() is None:
        admin=User(name=os.getenv('ADMIN_NAME','Workspace Admin'),email=bootstrap_email,role='admin',department='IT Support');admin.set_password(bootstrap_password);db.session.add(admin);db.session.commit()

if __name__=='__main__': app.run(host='0.0.0.0',port=int(os.getenv('PORT',5000)),debug=True)
