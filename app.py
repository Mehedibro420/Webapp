import threading
import time
from flask import Flask, jsonify, render_template

app = Flask(__name__)

# ==========================================
# আপনার মনমতো বটের কোডটি এখানে সেট করে রাখবেন
# ==========================================
def my_custom_bot_code():
    print("--- সিস্টেম রান হওয়া শুরু হয়েছে ---")
    try:
        # ⬇️ ⬇️ আপনার আসল কোড বা বটের লজিক এখানে পেস্ট করবেন ⬇️ ⬇️
        # উদাহরণ হিসেবে নিচে একটি লুপ দেওয়া হলো:
        for i in range(1, 11):
            print(f"বট কাজ করছে... ধাপ {i}")
            time.sleep(1) # ১ সেকেন্ড বিরতি
        # ⬆️ ⬆️ আপনার কোড এখানে শেষ হবে ⬆️ ⬆️
        
        print("--- সিস্টেম সফলভাবে সম্পন্ন হয়েছে ---")
        
    except Exception as e:
        print(f"কোডে কোনো সমস্যা হয়েছে: {str(e)}")

# ==========================================
# সার্ভার এবং ওয়েবসাইটের রুটস (Routes)
# ==========================================

@app.route("/")
def index():
    # ওয়েবসাইট ভিজিট করলে এই পেজটি দেখাবে
    return render_template("index.html")

@app.route("/run-bot", methods=["POST"])
def run_bot():
    try:
        # threading ব্যবহার করার কারণে ইউজার ক্লিক করার সাথে সাথে ব্যাকগ্রাউন্ডে কোড चालू হবে
        bot_thread = threading.Thread(target=my_custom_bot_code)
        bot_thread.start()
        
        return jsonify({"status": "success", "message": "সিস্টেম সফলভাবে চালু হয়েছে! ব্যাকগ্রাউন্ডে কাজ চলছে।"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

if __name__ == "__main__":
    # ২৪/৭ হোস্টিং সার্ভারে রান করার জন্য host="0.0.0.0" থাকা আবশ্যক
    app.run(host="0.0.0.0", port=5000, debug=True)