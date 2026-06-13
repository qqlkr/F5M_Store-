from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import os
import requests
from datetime import datetime
from pymongo import MongoClient
from bson.objectid import ObjectId
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = "fahm_store_secure_secret_key_2026" 
app.config['PERMANENT_SESSION_LIFETIME'] = 2592000 

# إعدادات مجلد رفع الملفات والصور المسموحة
UPLOAD_FOLDER = 'static/uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp', 'gif'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# إنشاء مجلد الرفع تلقائياً إذا لم يكن موجوداً لمنع الأخطاء
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

ADMIN_PASSWORD = "015388"
WHATSAPP_NUMBER = "966538812067"

BANK_DETAILS = {
    "AlRajhi": {"name": "مصرف الراجحي", "iban": "SA1234567890123456789012", "holder": "F5M"},
    "STC": {"name": "STC Bank", "iban": "SA9876543210987654321098", "holder": "F5M"}
}

MONGO_URI = "mongodb+srv://fjjwjs32_db_user:aderenyeager7%267@cluster0.638wcem.mongodb.net/?appName=Cluster0"
mongo_client = MongoClient(MONGO_URI)
db = mongo_client["F5M_Store_DB"]

users_collection = db["users"]
products_collection = db["products"]
coupons_collection = db["coupons"]
pages_collection = db["pages"]  
orders_collection = db["orders"]

def is_user_logged_in():
    return "user" in session

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.context_processor
def inject_pages():
    pages = list(pages_collection.find())
    return dict(custom_pages=pages)

@app.route("/user-login")
def user_login():
    if is_user_logged_in(): return redirect(url_for("index"))
    discord_login_url = "https://discord.com/api/oauth2/authorize?client_id=YOUR_CLIENT_ID&redirect_uri=YOUR_REDIRECT&response_type=code&scope=identify"
    return render_template("user_login.html", login_url=discord_login_url)

@app.route("/")
def index():
    if not is_user_logged_in(): return redirect(url_for("user_login"))
    products = list(products_collection.find({"page_id": "main"}).sort("_id", -1))
    return render_template("index.html", products=products, whatsapp=WHATSAPP_NUMBER, user=session["user"])

@app.route("/page/<page_id>")
def view_page(page_id):
    if not is_user_logged_in(): return redirect(url_for("user_login"))
    page = pages_collection.find_one({"_id": ObjectId(page_id)})
    if not page: return "الصفحة غير موجودة", 404
    products = list(products_collection.find({"page_id": page_id}).sort("_id", -1))
    return render_template("custom_page.html", page=page, products=products, user=session["user"])

@app.route("/cart")
def cart():
    if not is_user_logged_in(): return redirect(url_for("user_login"))
    return render_template("cart.html", bank_details=BANK_DETAILS)

@app.route("/validate-coupon", methods=["POST"])
def validate_coupon():
    data = request.json
    code = data.get("code", "").upper()
    coupon = coupons_collection.find_one({"code": code})
    if coupon:
        return jsonify({"valid": True, "discount": coupon["discount"]})
    return jsonify({"valid": False, "message": "كود الخصم غير صحيح!"})

# مسار معالجة الطلب البنكي واستقبال ملف الإيصال الحقيقي
@app.route("/submit-bank-order", methods=["POST"])
def submit_bank_order():
    if not is_user_logged_in(): 
        return jsonify({"success": False, "message": "غير مسجل دخول"}), 403
    
    # استقبال نصوص وجسد البيانات المرسلة عبر FormData
    import json
    items = json.loads(request.form.get("items", "[]"))
    total = request.form.get("total", "0")
    bank_type = request.form.get("bank_type", "")
    
    # التحقق من وجود الملف المرفوع
    if 'receipt_file' not in request.files:
        return jsonify({"success": False, "message": "يرجى إرفاق ملف صورة الإيصال أولاً!"})
    
    file = request.files['receipt_file']
    if file.filename == '':
        return jsonify({"success": False, "message": "لم يتم اختيار أي ملف!"})
        
    if not file or not allowed_file(file.filename):
        return jsonify({"success": False, "message": "صيغة الملف غير مدعومة! يرجى رفع صورة فقط."})

    # 1. فحص توفر الكميات بالمخزن
    for item in items:
        prod = products_collection.find_one({"_id": ObjectId(item["id"])})
        if not prod or prod.get("quantity", 0) < item["quantity"]:
            return jsonify({"success": False, "message": f"عذراً، الكمية المطلوبة من {item['name']} غير متوفرة حالياً!"})
            
    # 2. حفظ الملف على السيرفر بملف آمن فريد
    filename = secure_filename(f"{int(datetime.utcnow().timestamp())}_{file.filename}")
    file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(file_path)
    
    # 3. خصم الكمية من المخزون بـ MongoDB تلقائياً
    for item in items:
        products_collection.update_one(
            {"_id": ObjectId(item["id"])},
            {"$inc": {"quantity": -int(item["quantity"])}}
        )
        
    # 4. حفظ الفاتورة بقاعدة البيانات
    order_doc = {
        "user": session["user"],
        "items": items,
        "total": total,
        "bank_type": bank_type,
        "receipt_path": f"/{file_path}",
        "status": "بانتظار المراجعة",
        "date": datetime.now().strftime("%Y-%m-%d %H:%M")
    }
    orders_collection.insert_one(order_doc)
    
    # تحضير رسالة الدعم الفني عبر الواتساب للعميل لإعلامك بالتحويل
    base_url = request.host_url.rstrip('/')
    full_receipt_url = f"{base_url}/{file_path}"
    msg = f"مرحباً متجر F5M، قمت بالتحويل البنكي عبر {bank_type}.%0A%0Aالإجمالي: {total}%0Aرابط الإيصال المرفوع: {full_receipt_url}"
    whatsapp_url = f"https://wa.me/{WHATSAPP_NUMBER}?text={msg}"
    
    return jsonify({"success": True, "url": whatsapp_url})

# --- لوحة التحكم المعتادة للإدارة ---
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if request.form.get("password") == ADMIN_PASSWORD:
            session["admin"] = True
            return redirect("/admin")
    return render_template("login.html")

@app.route("/admin")
def admin():
    if not session.get("admin"): return redirect("/login")
    products = list(products_collection.find().sort("_id", -1))
    coupons = list(coupons_collection.find())
    pages = list(pages_collection.find())
    orders = list(orders_collection.find().sort("_id", -1))
    return render_template("admin.html", products=products, coupons=coupons, pages=pages, orders=orders)

@app.route("/update-order/<id>/<status>")
def update_order(id, status):
    if not session.get("admin"): return redirect("/login")
    orders_collection.update_one({"_id": ObjectId(id)}, {"$set": {"status": status}})
    return redirect("/admin")

@app.route("/add-product", methods=["POST"])
def add_product():
    if not session.get("admin"): return redirect("/login")
    product = {
        "name": request.form.get("name"),
        "price": float(request.form.get("price")),
        "image": request.form.get("image"),
        "quantity": int(request.form.get("quantity")),
        "description": request.form.get("description"),
        "page_id": request.form.get("page_id")
    }
    products_collection.insert_one(product)
    return redirect("/admin")

@app.route("/delete-product/<id>")
def delete_product(id):
    if not session.get("admin"): return redirect("/login")
    products_collection.delete_one({"_id": ObjectId(id)})
    return redirect("/admin")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 20040))
    app.run(host="0.0.0.0", port=port)
