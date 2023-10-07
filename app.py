from flask import Flask, render_template, request, redirect, url_for, flash, session, current_app, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from models import User, Scorecard, Course, Hole, db, setup_db, ScorecardDetail, Friendship, FriendRequest, Message
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
from PIL import Image, ImageDraw, ImageFont
from flask_socketio import SocketIO, send, emit
from datetime import datetime, timedelta
import os, secrets, logging

photos = UploadSet('photos', IMAGES)
app = Flask(__name__)
socketio = SocketIO(app)
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

@socketio.on('send_message')
def handle_message(data):
    # Save the message to the database
    message = Message(sender_id=current_user.id, receiver_id=data['receiver_id'], content=data['content'])
    db.session.add(message)
    db.session.commit()

    # Emit the message to the receiver
    emit('receive_message', {
        'content': data['content'],
        'sender_name': current_user.username,  # Add sender's name
        'sender_id': current_user.id,
        'timestamp': datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')  # Add timestamp
    }, room=data['receiver_id'])


@app.route('/get_chat_history', methods=['POST'])
@login_required
def get_chat_history():
    try:
        receiver_id = request.json.get('receiver_id')
        messages = Message.query.filter(
            (Message.sender_id == current_user.id) & (Message.receiver_id == receiver_id) |
            (Message.sender_id == receiver_id) & (Message.receiver_id == current_user.id)
        ).order_by(Message.timestamp.asc()).all()
        return jsonify([message.serialize() for message in messages])
    except Exception as e:
        current_app.logger.error(f"Error fetching chat history: {e}")
        return jsonify({"error": "An error occurred while fetching chat history."}), 500

@app.before_request
def update_last_seen():
    if current_user.is_authenticated:
        current_user.last_seen = datetime.utcnow()
        db.session.commit()

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

def generate_default_profile_picture(username):
    width, height = 150, 150
    image = Image.new('RGB', (width, height), color='lightgray')
    draw = ImageDraw.Draw(image)
    font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"  # Update the font path
    font = ImageFont.truetype(font_path, size=70)  # Adjusted font size
    text = username[0].upper()
    text_width, text_height = draw.textsize(text, font=font)
    position = ((width - text_width) / 2, (height - text_height) / 2 - 10)  # Adjusted position
    draw.text(position, text, fill='black', font=font)
    image.save(f'static/images/{username}.png')

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
                generate_default_profile_picture(username)
                user = User(username=username, email=email, profile_pic=f'{username}.png')
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
    best_rounds = []
    last_five_rounds = []

    for scorecard in scorecards:
        scorecard_details = ScorecardDetail.query.filter_by(scorecard_id=scorecard.id).all()
        total_score = 0
        for scorecard_detail in scorecard_details:
            hole = Hole.query.get(scorecard_detail.hole_id)
            total_score += scorecard_detail.throws - hole.par
        course = Course.query.get(scorecard.course_id)
        scores.append({'course_name': course.name, 'total_score': total_score})

    # Get a list of all the courses the user has played
    course_ids = {scorecard.course_id for scorecard in scorecards}
    for course_id in course_ids:
        course = Course.query.get(course_id)
        # Query the database to get the scorecard with the lowest total score for each course
        best_round = db.session.query(Scorecard).filter_by(user_id=current_user.id, course_id=course_id).order_by(Scorecard.total_score.asc()).first()
        if best_round:
            best_rounds.append({'course_name': course.name, 'best_score': best_round.total_score})

        # Query the database to get the last 5 scorecards for each course
        last_five = db.session.query(Scorecard).filter_by(user_id=current_user.id, course_id=course_id).order_by(Scorecard.date_played.desc()).limit(5).all()
        last_five_scores = [{'date_played': scorecard.date_played, 'total_score': scorecard.total_score} for scorecard in last_five]
        last_five_rounds.append({'course_name': course.name, 'scores': last_five_scores})

    return render_template('statistics.html', scores=scores, best_rounds=best_rounds, last_five_rounds=last_five_rounds)

@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    if request.method == 'POST' and 'picture' in request.files:
        filename = photos.save(request.files['picture'])
        current_user.profile_pic = filename
        db.session.commit()
        flash("Profile picture has been updated!")
        return redirect(url_for('profile'))
    
    friendships = Friendship.query.filter(
        (Friendship.user1 == current_user) | (Friendship.user2 == current_user)
    ).all()
    friends = [
        friendship.user1 if friendship.user1 != current_user else friendship.user2
        for friendship in friendships
    ]
    incoming_requests = FriendRequest.query.filter_by(receiver=current_user).all()

    return render_template('profile.html', user=current_user, friends=friends, incoming_requests=incoming_requests)

@app.route('/search_users', methods=['POST'])
@login_required
def search_users():
    query = request.json['query']
    users = User.query.filter(User.username.like(f'%{query}%'), User.id != current_user.id).all()
    return jsonify(users=[user.serialize() for user in users])

@app.route('/send_request', methods=['POST'])
@login_required
def send_request():
    user_id = request.json['user_id']
    user = User.query.get(user_id)
    existing_request = FriendRequest.query.filter_by(sender=current_user, receiver=user).first()
    existing_friendship = Friendship.query.filter(
        (Friendship.user1 == current_user) & (Friendship.user2 == user) |
        (Friendship.user2 == current_user) & (Friendship.user1 == user)
    ).first()
    if user and not existing_request and not existing_friendship:
        friend_request = FriendRequest(sender=current_user, receiver=user)
        db.session.add(friend_request)
        db.session.commit()
        return jsonify(success=True)
    else:
        return jsonify(success=False, error='Friend request already sent, user not found, or already friends')

@app.route('/remove_friend/<int:user_id>', methods=['POST'])
@login_required
def remove_friend(user_id):
    friendship = Friendship.query.filter(
        (Friendship.user1 == current_user) & (Friendship.user2_id == user_id) |
        (Friendship.user2 == current_user) & (Friendship.user1_id == user_id)
    ).first()
    if friendship:
        db.session.delete(friendship)
        db.session.commit()
        flash('Friend removed.')
    return redirect(url_for('profile'))

@app.route('/accept_request/<int:request_id>', methods=['POST'])
@login_required
def accept_request(request_id):
    request = FriendRequest.query.get(request_id)
    if request and request.receiver == current_user:
        friendship = Friendship(user1=request.sender, user2=request.receiver)
        db.session.add(friendship)
        db.session.delete(request)
        db.session.commit()
        flash('Friend request accepted!')
    return redirect(url_for('profile'))

@app.route('/decline_request/<int:request_id>', methods=['POST'])
@login_required
def decline_request(request_id):
    request = FriendRequest.query.get(request_id)
    if request and request.receiver == current_user:
        db.session.delete(request)
        db.session.commit()
        flash('Friend request declined.')
    return redirect(url_for('profile'))

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

