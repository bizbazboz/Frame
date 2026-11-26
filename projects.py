"""Local project selection and management; OIDC still protects the whole library."""
from flask import abort, g, redirect, render_template, request, session, url_for
from sqlalchemy import func

PUBLIC_ENDPOINTS = {'static', 'manifest', 'service_worker', 'login', 'callback', 'logout'}
CONTEXT_ENDPOINTS = {'rotate_photo', 'download_version', 'campaigns', 'delete_campaign', 'reddit_analytics', 'reddit_sync', 'dashboard', 'import_photos', 'media', 'image_preview', 'gallery', 'pool_review', 'group',
                    'bulk_edit', 'delete_group', 'delete_version', 'campaign', 'tags', 'accounts', 'projects', 'inspiration', 'delete_inspiration', 'upload_start', 'upload_status', 'upload_chunk', 'upload_finish', 'upload_cancel'}


def register_projects(app, db, Project, PhotoGroup, InspirationLink):
    @app.before_request
    def select_project():
        if not request.endpoint or request.endpoint in PUBLIC_ENDPOINTS:
            return
        explicit = request.args.get('project')
        submitted = request.form.get('project_context') if request.method == 'POST' else None
        if explicit is not None and submitted and explicit != submitted:
            abort(400, 'Project context changed. Reload this page.')
        if explicit is None:
            explicit = submitted
        if explicit is not None:
            try:
                selected = db.session.get(Project, int(explicit))
            except ValueError:
                abort(400, 'Invalid project.')
            if not selected:
                abort(404, 'Project not found.')
        else:
            selected = db.session.get(Project, session['project_id']) if session.get('project_id') else None
            if not selected:
                selected = Project.query.order_by(Project.id).first()
                if not selected:
                    abort(503, 'No projects available. Apply the database migrations.')
                session['project_id'] = selected.id
        g.project = selected

    @app.url_defaults
    def keep_project_context(endpoint, values):
        if endpoint in CONTEXT_ENDPOINTS and 'project' not in values and getattr(g, 'project', None):
            values['project'] = g.project.id

    @app.context_processor
    def project_context():
        project = getattr(g, 'project', None)
        return {'current_project': project,
                'projects': Project.query.order_by(Project.name, Project.id).all() if project else []}

    @app.post('/projects/switch')
    def switch_project():
        project_id = request.form.get('project_id', type=int)
        selected = db.session.get(Project, project_id) if project_id else None
        if not selected:
            abort(404, 'Project not found.')
        session['project_id'] = selected.id
        state = request.form.get('return_state', '')
        if state in ('pool', 'staging', 'never_post', 'final', 'all'):
            return redirect(url_for('gallery', state=state, project=selected.id))
        return redirect(url_for('dashboard', project=selected.id))

    def name_from_form(exclude_id=None):
        name = request.form.get('name', '').strip()
        if not name or len(name) > 80:
            abort(400, 'Project names must contain 1–80 characters.')
        if any(item.id != exclude_id and item.name.casefold() == name.casefold() for item in Project.query.all()):
            abort(409, 'A project with this name already exists.')
        return name

    @app.route('/projects', methods=['GET', 'POST'])
    def projects():
        if request.method == 'POST':
            action = request.form.get('action')
            if action == 'create':
                item = Project(name=name_from_form())
                db.session.add(item)
                db.session.commit()
                session['project_id'] = item.id
                return redirect(url_for('dashboard', project=item.id))
            project_id = request.form.get('project_id', type=int)
            item = db.session.get(Project, project_id) if project_id else None
            if not item:
                abort(404, 'Project not found.')
            redirect_id = g.project.id
            if action == 'rename':
                item.name = name_from_form(item.id)
            elif action == 'delete':
                if Project.query.count() <= 1:
                    abort(409, 'The last project cannot be deleted.')
                if PhotoGroup.query.filter_by(project_id=item.id).first():
                    abort(409, "Move or delete this project's photos before deleting it.")
                if InspirationLink.query.filter_by(project_id=item.id).first():
                    abort(409, "Remove this project's inspiration links before deleting it.")
                upload_model = app.extensions.get('upload_sessions')
                if upload_model is not None and upload_model.query.filter_by(project_id=item.id, status='active').first():
                    abort(409, 'Cancel active uploads before deleting this project.')
                if item.id == redirect_id:
                    redirect_id = Project.query.filter(Project.id != item.id).order_by(Project.id).first().id
                if session.get('project_id') == item.id:
                    session['project_id'] = redirect_id
                db.session.delete(item)
            else:
                abort(400, 'Invalid project action.')
            db.session.commit()
            return redirect(url_for('projects', project=redirect_id))
        counts = dict(db.session.query(PhotoGroup.project_id, func.count(PhotoGroup.id)).group_by(PhotoGroup.project_id).all())
        inspiration_counts = dict(db.session.query(InspirationLink.project_id, func.count(InspirationLink.id)).group_by(InspirationLink.project_id).all())
        return render_template('projects.html', project_counts=counts, inspiration_counts=inspiration_counts)
