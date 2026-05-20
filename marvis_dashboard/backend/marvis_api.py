from flask import Flask, send_from_directory
app=Flask(__name__,static_folder="../frontend",static_url_path="")

@app.route("/api/results")
def results():
    return send_from_directory("../outputs","results.json")

@app.route("/")
def home():
    return send_from_directory("../frontend","index.html")

if __name__=="__main__":
    app.run(debug=True)
