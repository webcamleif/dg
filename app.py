from flask import Flask, render_template, request, redirect, url_for, flash, session, current_app, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from models import User, Scorecard, Course, Hole, db, setup_db, ScorecardDetail
from flask_dance.contrib.google import make_google_blueprint, google
from flask_dance.consumer.storage.sqla import SQLAlchemyStorage
from models import OAuth
from flask_login import current_user, login_user, logout_user
from flask_login import LoginManager
from werkzeug.middleware.proxy_fix import ProxyFix
from flask_dance.consumer import oauth_authorized
from sqlalchemy.orm.exc import NoResultFound
from flask_login import login_required
from flask_uploads import UploadSet, configure_uploads, IMAGES
from math import radians, cos, sin, asin, sqrt
import os, secrets, logging

photos = UploadSet('photos', IMAGES)
app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app)
app.logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
handler.setLevel(logging.INFO)
app.logger.addHandler(handler)
login_manager = LoginManager()
login_manager.login_view = 'login'
login_manager.init_app(app)
app.config['UPLOADED_PHOTOS_DEST'] = os.getcwd() + '/static/images'
configure_uploads(app, photos)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:////home/hendrikx/application/test.db'
app.config['SECRET_KEY'] = 'your_secret_key'  # Replace with your secret key
app.config['GOOGLE_OAUTH_CLIENT_ID'] = os.getenv('GOOGLE_CLIENT_ID')
app.config['GOOGLE_OAUTH_CLIENT_SECRET'] = os.getenv('GOOGLE_CLIENT_SECRET')
setup_db(app)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

google_bp = make_google_blueprint(
    client_id=app.config.get('GOOGLE_OAUTH_CLIENT_ID'),
    client_secret=app.config.get('GOOGLE_OAUTH_CLIENT_SECRET'),
    scope=["openid", "https://www.googleapis.com/auth/userinfo.email", "https://www.googleapis.com/auth/userinfo.profile"],
    redirect_to="home",
    storage=SQLAlchemyStorage(OAuth, db.session, user=current_user)
)
app.register_blueprint(google_bp, url_prefix="/login")

def populate_vallentuna_course():
    vallentuna = Course.query.filter_by(name="Vallentuna").first()

    if not vallentuna:  # Check if the course does not exist
        vallentuna = Course(name="Vallentuna", par=56, holes=18, total_distance=1382, 
                            latitude=59.5419569021072, longitude=18.078881033956797)
        db.session.add(vallentuna)
        db.session.commit()

        hole_distances = [94, 67, 95, 71, 47, 67, 89, 92, 118, 30, 68, 39, 53, 67, 88, 60, 139, 108]
        hole_pars = [3, 3, 3, 3, 3, 3, 3, 3, 4, 3, 3, 3, 3, 3, 3, 3, 4, 3]

        for i in range(18):
            hole = Hole(course_id=vallentuna.id, hole_number=i+1, distance=hole_distances[i], par=hole_pars[i])
            db.session.add(hole)

        db.session.commit()

def haversine(lon1, lat1, lon2, lat2):
    lon1, lat1, lon2, lat2 = map(radians, [lon1, lat1, lon2, lat2])
    dlon = lon2 - lon1 
    dlat = lat2 - lat1 
    a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
    c = 2 * asin(sqrt(a)) 
    r = 6371 # Radius of earth in kilometers
    return c * r

@oauth_authorized.connect_via(google_bp)
def google_logged_in(blueprint, token):
    if not token:
        flash("Failed to log in with Google.", category="error")
        return redirect(url_for('login'))

    resp = blueprint.session.get("/oauth2/v1/userinfo")
    if not resp.ok:
        msg = "Failed to fetch user info from Google."
        flash(msg, category="error")
        return redirect(url_for('login'))

    google_info = resp.json()
    email = google_info["email"]

    query = User.query.filter_by(email=email)
    try:
        user = query.one()
    except NoResultFound:
        return redirect(url_for('create_display_name', email=email))

    login_user(user)

    flash("Successfully signed in with Google.")
    return redirect(url_for('home'))

@app.errorhandler(404)
def page_not_found(e):
    return render_template('404.html'), 404

@app.route('/')
def index():
    return redirect(url_for('home'))

@app.route('/available_courses')
@login_required
def available_courses():
    user_lat = float(request.args.get('lat'))
    user_lon = float(request.args.get('lon'))
    courses = Course.query.all()
    courses_list = []
    for course in courses:
        dist = haversine(user_lon, user_lat, course.longitude, course.latitude)
        courses_list.append({
            'id': course.id,
            'name': course.name,
            'distance': dist,
        })
    courses_list.sort(key=lambda x: x['distance']) # Sort courses by distance
    return jsonify(courses_list)

@app.route('/select_course', methods=['POST'])
@login_required
def select_course():
    course_id = request.form.get('course_id')
    user_id = current_user.id

    # Set the previously active scorecard to inactive
    active_scorecard = Scorecard.query.filter_by(user_id=current_user.id, active=True).first()
    if active_scorecard:
        active_scorecard.active = False
        db.session.commit()

    # Create a new scorecard and set it to active
    new_scorecard = Scorecard(user_id=user_id, course_id=course_id, active=True)
    db.session.add(new_scorecard)
    db.session.commit()

    return jsonify({'result': 'success', 'scorecard_id': new_scorecard.id})

@app.route('/get_throw_count', methods=['GET'])
@login_required
def get_throw_count():
    scorecard_id = request.args.get('scorecard_id')
    hole_number = request.args.get('hole_number')
    scorecard = Scorecard.query.get(scorecard_id)
    
    if scorecard is None:
        return jsonify({'result': 'failure', 'message': 'Invalid scorecard.'})

    hole = Hole.query.filter_by(course_id=scorecard.course_id, hole_number=hole_number).first()

    if hole is None:
        return jsonify({'result': 'failure', 'message': 'Invalid hole.'})
    if scorecard and scorecard.user_id == current_user.id and hole:
        scorecard_detail = ScorecardDetail.query.filter_by(scorecard_id=scorecard.id, hole_id=hole.id).first()
        if scorecard_detail:
            throw_count = scorecard_detail.throws if scorecard_detail.throws is not None else 0
            return jsonify({'throw_count': throw_count})
        else:
            return jsonify({'result': 'failure', 'message': 'No ScorecardDetail found for this scorecard and hole.'})
    else:
        return jsonify({'result': 'failure', 'message': 'Invalid scorecard or hole.'})

@app.route('/update_throw_count', methods=['POST'])
@login_required
def update_throw_count():
    scorecard_id = request.form.get('scorecard_id')
    hole_number = request.form.get('hole_number')
    throw_count = int(request.form.get('throw_count'))  # Convert the throw count to an integer
    scorecard = Scorecard.query.get_or_404(scorecard_id)  # Change here
    hole = Hole.query.filter_by(course_id=scorecard.course_id, hole_number=hole_number).first()

    if scorecard and scorecard.user_id == current_user.id and hole:
        app.logger.info("Found scorecard and hole, updating throw count")
        scorecard_detail = ScorecardDetail.query.filter_by(scorecard_id=scorecard.id, hole_id=hole.id).first()
        if not scorecard_detail:
            app.logger.info("No scorecard detail found, creating new one")
            scorecard_detail = ScorecardDetail(scorecard_id=scorecard.id, hole_id=hole.id, throws=throw_count)
            db.session.add(scorecard_detail)
        else:
            scorecard_detail.throws = throw_count
        db.session.commit()
        return jsonify({'result': 'success'})
    else:
        return jsonify({'result': 'failure', 'message': 'Invalid scorecard or hole.'})

@app.route('/get_hole_info', methods=['GET'])
@login_required
def get_hole_info():
    course_id = request.args.get('course_id')
    hole_number = request.args.get('hole_number')
    hole = Hole.query.filter_by(course_id=course_id, hole_number=hole_number).first()
    if hole:
        return jsonify({'hole_number': hole.hole_number, 'distance': hole.distance, 'par': hole.par})
    else:
        return jsonify({'result': 'failure', 'message': 'Invalid hole.'})

@app.route('/get_total_score', methods=['GET'])
@login_required
def get_total_score():
    scorecard_id = request.args.get('scorecard_id')
    scorecard = Scorecard.query.get(scorecard_id)

    if scorecard is None:
        return jsonify({'result': 'failure', 'message': 'Invalid scorecard.'})

    scorecard_details = ScorecardDetail.query.filter_by(scorecard_id=scorecard.id).all()
    total_score = 0
    for scorecard_detail in scorecard_details:
        if scorecard_detail.throws > 0:  # Add this condition
            hole = Hole.query.get(scorecard_detail.hole_id)
            total_score += scorecard_detail.throws - hole.par

    return jsonify({'total_score': total_score})

@app.route('/home', defaults={'hole_number': 1})
@login_required
def home(hole_number):
    active_course = None
    active_scorecard = db.session.query(Scorecard).filter_by(user_id=current_user.id, active=True).first()
    if active_scorecard:
        active_course = Course.query.get(active_scorecard.course_id)
        holes = Hole.query.filter_by(course_id=active_course.id).order_by(Hole.hole_number).all()
        active_hole = Hole.query.filter_by(course_id=active_course.id, hole_number=hole_number).first()
    else:
        holes = []
        active_hole = None
    courses = Course.query.all()
    return render_template('home.html', active_scorecard=active_scorecard, courses=courses, holes=holes, active_hole=active_hole, active_course=active_course)

@app.route('/courses')
@login_required
def courses():
    courses = Course.query.all()  # fetch all courses from the database
    return render_template('courses.html', courses=courses)

@app.route('/view_course/<int:course_id>')
def view_course(course_id):
    course = Course.query.options(joinedload('hole_info')).get(course_id)
    if course is None:
        flash('Course not found')
        return redirect(url_for('courses'))
    return render_template('course.html', course=course)

@app.route('/create_scorecard', methods=['POST'])
@login_required
def create_scorecard():
    course_id = request.form.get('course_id')
    user_id = current_user.id
    
    # Set the previously active scorecard to inactive
    active_scorecard = Scorecard.query.filter_by(user_id=current_user.id, active=True).first()
    if active_scorecard:
        active_scorecard.active = False
        db.session.commit()

    # Create a new scorecard and set it to active
    new_scorecard = Scorecard(user_id=user_id, course_id=course_id, active=True) # add active=True here
    db.session.add(new_scorecard)
    db.session.commit()

    return jsonify({'result': 'success', 'scorecard_id': new_scorecard.id})

@app.route('/get_scorecard', methods=['GET'])
@login_required
def get_scorecard():
    scorecard_id = request.args.get('scorecard_id')
    scorecard = Scorecard.query.get(scorecard_id)

    if scorecard is None:
        return jsonify({'result': 'failure', 'message': 'Invalid scorecard.'})

    if scorecard and scorecard.user_id == current_user.id:
        holes = Hole.query.filter_by(course_id=scorecard.course_id).order_by(Hole.hole_number).all()
        scorecard_data = []
        for hole in holes:
            scorecard_detail = ScorecardDetail.query.filter_by(scorecard_id=scorecard.id, hole_id=hole.id).first()
            throw_count = scorecard_detail.throws if scorecard_detail and scorecard_detail.throws is not None else 0
            scorecard_data.append({
                'hole_number': hole.hole_number,
                'distance': hole.distance,
                'par': hole.par,
                'throws': throw_count
            })
        return jsonify(scorecard_data)
    else:
        return jsonify({'result': 'failure', 'message': 'Invalid scorecard.'})

@app.route('/end_round', methods=['POST'])
@login_required
def end_round():
    scorecard_id = request.form.get('scorecard_id')
    scorecard = Scorecard.query.get(scorecard_id)
    if scorecard and scorecard.user_id == current_user.id:
        scorecard_details = ScorecardDetail.query.filter_by(scorecard_id=scorecard.id).all()
        total_score = 0
        for scorecard_detail in scorecard_details:
            hole = Hole.query.get(scorecard_detail.hole_id)
            total_score += scorecard_detail.throws - hole.par
        
        # Save the total score to the scorecard (assuming a new attribute "total_score" in Scorecard model)
        scorecard.total_score = total_score
        scorecard.active = False
        db.session.commit()
        return jsonify({'result': 'success', 'total_score': total_score})
    return jsonify({'result': 'error', 'message': 'Scorecard not found or user not authorized'})

@app.route('/create_display_name', methods=['GET', 'POST'])
def create_display_name():
    if request.method == 'POST':
        username = request.form['username']
        email = request.args.get('email')
        if len(username) <= 10:
            if not User.query.filter_by(username=username).first():
                user = User(username=username, email=email)
                db.session.add(user)
                db.session.commit()
                login_user(user)
                flash("Successfully signed in with Google.")
                return redirect(url_for('home'))
            else:
                flash("Username already in use, please choose another.")
        else:
            flash("Username should be maximum 10 characters long.")
    return render_template('create_display_name.html', email=request.args.get('email'))

@app.route('/statistics')
@login_required
def statistics():
    scorecards = Scorecard.query.filter_by(user_id=current_user.id).all()
    scores = []
    for scorecard in scorecards:
        scorecard_details = ScorecardDetail.query.filter_by(scorecard_id=scorecard.id).all()
        total_score = 0
        for scorecard_detail in scorecard_details:
            hole = Hole.query.get(scorecard_detail.hole_id)
            total_score += scorecard_detail.throws - hole.par
        course = Course.query.get(scorecard.course_id)
        scores.append({'course_name': course.name, 'total_score': total_score})
    return render_template('statistics.html', scores=scores)

@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    if request.method == 'POST' and 'photo' in request.files:
        filename = photos.save(request.files['photo'])
        current_user.profile_pic = filename
        db.session.commit()
        flash("Profile picture has been updated!")
        return redirect(url_for('profile'))
    return render_template('profile.html', user=current_user)


@app.route("/logout")
def logout():
    logout_user()
    return redirect(url_for('home'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('home'))
    return render_template('login.html')

if __name__ == "__main__":
    with app.app_context():
        db.create_all()  # Create tables based on the models
        populate_vallentuna_course()
    app.run(host='172.16.69.5', port=5000, debug=True)

