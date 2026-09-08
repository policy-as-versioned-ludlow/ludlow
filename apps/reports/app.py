from flask import Flask

# Reports team's app (real-estate epic, ticket 08). Moderately old Flask
# (see requirements.txt) -- the middle case between ledger's laggard and
# api's current tree.
app = Flask(__name__)


@app.route("/")
def index():
    return "reports\n"


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
