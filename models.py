from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin
from sqlalchemy import JSON
from datetime import datetime

db = SQLAlchemy()

def setup_db(app):
    db.init_app(app)

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(128))
    oauth = db.relationship('OAuth', backref='user', lazy=True)
    profile_pic = db.Column(db.String(20), nullable=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @staticmethod
    def get_or_create(email):
        user = User.query.filter_by(email=email).first()
        if user is None:
            user = User(email=email)
            db.session.add(user)
            db.session.commit()
        return user

    def serialize(self):
        return {
            'id': self.id,
            'username': self.username,
        }

class Scorecard(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    course_id = db.Column(db.Integer, db.ForeignKey('course.id'), nullable=False)
    active = db.Column(db.Boolean, default=False, nullable=False)
    total_score = db.Column(db.Integer, nullable=True)
    date_played = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    user = db.relationship('User', backref=db.backref('scorecards', lazy=True))
    course = db.relationship('Course', backref=db.backref('scorecards', lazy=True))

class Course(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)
    par = db.Column(db.Integer, nullable=False)
    holes = db.Column(db.Integer, nullable=False)
    total_distance = db.Column(db.Integer, nullable=False)
    latitude = db.Column(db.Float, nullable=False)
    longitude = db.Column(db.Float, nullable=False)
    hole_info = db.relationship('Hole', backref='course', lazy=True)

class Hole(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.Integer, db.ForeignKey('course.id'), nullable=False)
    hole_number = db.Column(db.Integer, nullable=False)
    distance = db.Column(db.Integer, nullable=False)
    par = db.Column(db.Integer, nullable=False)

class OAuth(db.Model):
    provider_user_id = db.Column(db.String(256), primary_key=True)
    provider_name = db.Column(db.String(50), nullable=False)
    provider = db.Column(db.String(50))  # add this line
    token = db.Column(JSON, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

class ScorecardDetail(db.Model):
    __tablename__ = 'scorecard_detail'

    id = db.Column(db.Integer, primary_key=True)
    scorecard_id = db.Column(db.Integer, db.ForeignKey('scorecard.id'), nullable=False)
    hole_id = db.Column(db.Integer, db.ForeignKey('hole.id'), nullable=False)
    throws = db.Column(db.Integer, nullable=False)

    __table_args__ = (db.UniqueConstraint('scorecard_id', 'hole_id', name='_scorecard_hole_uc'),)

    scorecard = db.relationship('Scorecard', backref=db.backref('scorecard_details', lazy=True))
    hole = db.relationship('Hole', backref=db.backref('scorecard_details', lazy=True))

class FriendRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    receiver_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    status = db.Column(db.String(10), nullable=False, default='Pending')
    timestamp = db.Column(db.DateTime, index=True, default=datetime.utcnow)

    sender = db.relationship('User', foreign_keys=[sender_id])
    receiver = db.relationship('User', foreign_keys=[receiver_id])

class Friendship(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user1_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    user2_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    timestamp = db.Column(db.DateTime, index=True, default=datetime.utcnow)

    user1 = db.relationship('User', foreign_keys=[user1_id])
    user2 = db.relationship('User', foreign_keys=[user2_id])

class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    receiver_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    content = db.Column(db.String(500))
    timestamp = db.Column(db.DateTime, index=True, default=datetime.utcnow)

    def __repr__(self):
        return f'<Message {self.content}>'

