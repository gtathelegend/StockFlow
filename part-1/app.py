from flask import Flask
from models import db, Warehouse
from routes import products_bp


def create_app(config=None):
    app = Flask(__name__)

    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///stockflow.db"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    if config:
        app.config.update(config)

    db.init_app(app)
    app.register_blueprint(products_bp)

    with app.app_context():
        db.create_all()
        # Seed a default warehouse if none exist
        if not Warehouse.query.first():
            db.session.add(Warehouse(name="Main Warehouse", location="New York"))
            db.session.add(Warehouse(name="West Coast Warehouse", location="Los Angeles"))
            db.session.commit()

    return app


if __name__ == "__main__":
    app = create_app()
    app.run(debug=True)
