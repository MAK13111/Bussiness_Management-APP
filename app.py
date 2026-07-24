from flask import Flask, render_template

from core.schema import init_schema, populate_defaults

from routes.purchases import purchases_bp
from routes.sales import sales_bp
from routes.items import items_bp
from routes.parties import parties_bp
from routes.department import department_bp
from routes.reports import reports_bp
from routes.tally import tally_bp
from routes.dashboard import dashboard_bp
from routes.setting import setting_bp
from routes.legacy import legacy_bp

app = Flask(__name__)

app.register_blueprint(purchases_bp)
app.register_blueprint(sales_bp)
app.register_blueprint(items_bp)
app.register_blueprint(parties_bp)
app.register_blueprint(department_bp)
app.register_blueprint(reports_bp)
app.register_blueprint(tally_bp)
app.register_blueprint(dashboard_bp)
app.register_blueprint(setting_bp)
app.register_blueprint(legacy_bp)

@app.route("/")
def index():
    return render_template("base.html")

def init_app():
    init_schema()
    populate_defaults()

if __name__ == "__main__":
    init_app()
    app.run(debug=False, host='0.0.0.0', port=5000)
