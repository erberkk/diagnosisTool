from datetime import datetime
import functools
import os
from flask import Flask, redirect, render_template, request, session, url_for, jsonify
from werkzeug.utils import secure_filename
import pymongo
from decouple import config
import pandas as pd
from bson.objectid import ObjectId


app = Flask('app')  # Flask uygulaması oluşturur
app.secret_key = config('secret')  # Flask uygulamasının gizli anahtarını .env dosyasından ayarlar
my_client = pymongo.MongoClient(config('mongo_url'))  # MongoDB istemcisini .env dosyasındaki URL ile başlatır
my_db = my_client[config('db_name')]  # MongoDB veritabanını .env dosyasındaki isimle seçer

if not os.path.exists('uploads'):  # Eğer 'uploads' klasörü mevcut değilse,
    os.makedirs('uploads')  # 'uploads' klasörünü oluşturur


def get_sequence(seq_name):  # Veritabanında belirli bir sayaç için sıra numarası alır veya oluşturur
    return my_db.counters.find_one_and_update(filter={"_id": seq_name}, update={"$inc": {"seq": 1}}, upsert=True)["seq"]


def my_log(action, message, user_name):  # Kullanıcı eylemlerini kaydetmek için bir log kaydı oluşturur
    log_id = get_sequence("log")  # Log için benzersiz bir ID alır
    return my_db.logs.insert_one({  # Log kaydını veritabanına ekler
        "_id": log_id,
        "action": action,
        "message": message,
        "user_name": user_name,
        "log_date": datetime.now()
    })


def my_logon(username, password):  # Kullanıcı adı ve şifre ile giriş yapmayı sağlar
    user_info = my_db.users.find_one({"_id": username})  # Kullanıcı adına göre kullanıcı bilgilerini arar
    if user_info and password == user_info.get("password"):  # Eğer kullanıcı bulunursa ve şifre eşleşirse,
        session["user_info"] = user_info  # Kullanıcı bilgilerini oturum değişkenine kaydeder
        return user_info  # Kullanıcı bilgilerini döndürür
    else:
        return None  # Eğer kullanıcı bulunamazsa veya şifre eşleşmezse, None döndürür


def login_required(route):  # Giriş yapmış kullanıcılar için koruma sağlayan bir dekoratör
    @functools.wraps(route)
    def route_wrapper(*args, **kwargs):
        if session.get("user_info") is None:  # Eğer kullanıcı oturumu mevcut değilse,
            return redirect(url_for("login"))  # Giriş sayfasına yönlendirir
        return route(*args, **kwargs)  # Aksi takdirde, asıl rotayı çağırır
    return route_wrapper  # Dekoratörü döndürür


@app.route('/login', methods=["GET", "POST"])
def login():
    if request.method == 'POST':  # Eğer form gönderilmişse kullanıcı adı ve şifre al
        username = request.form.get("username")
        pwd = request.form.get("pwd")
        user_info = my_logon(username=username, password=pwd)
        if user_info:
            return redirect(url_for("index"))
        else:
            return render_template("main.html", error="Invalid username or password")
    return render_template("login.html")


@app.route('/dataTable')
def data_table():
    # Veritabanından hasta verilerini çek ve dataTable.html şablonuna gönder
    patients = list(my_db.patientData.find())
    return render_template('dataTable.html', patients=patients)


@app.route('/')
@login_required
def index():
    # Ana sayfayı (main.html) göster
    return render_template('main.html')


@app.route('/ref')
def ref():
    # Referans sayfasını (ref.html) göster
    return render_template('ref.html')


@app.route('/submit', methods=['POST'])
def submit():
    # Form verilerini al
    name = request.form.get("name")
    age = int(request.form.get("age"))
    weight = float(request.form.get("weight", 0))  # Eğer değer yoksa 0 olarak kabul et
    height = float(request.form.get("height", 0))  # Eğer değer yoksa 0 olarak kabul et

    # BMI hesaplaması
    bmi = weight / ((height / 100) ** 2) if height > 0 else 0

    patient_data = {
        "_id": ObjectId(),
        "name": name,
        "age": age,
        "weight": weight,
        "height": height,
        "bmi": round(bmi, 2),  # BMI değerini yuvarla
        "sigara": "sigara" in request.form,
        "alkol": "alkol" in request.form,
        "drug": "drug" in request.form,
        "familyHistory": request.form.get("familyHistory"),
        "bloodPressure": request.form.get("bloodPressure"),
        "symptom": request.form.get("symptom"),
        "blood_values": []
    }

    # Kan değerlerini Excel dosyasından oku
    if 'bloodValues' in request.files:
        file = request.files['bloodValues']
        if file and file.filename.endswith('.xlsx'):
            filename = secure_filename(file.filename)
            filepath = os.path.join('uploads', filename)
            file.save(filepath)

            # Excel dosyasını oku
            df = pd.read_excel(filepath)
            blood_values = df.to_dict(orient='records')  # DataFrame'i dictionary listesine dönüştür

            # Okunan kan değerlerini patient_data içine ekleyin
            patient_data["blood_values"].extend(blood_values)

            os.remove(filepath)  # Dosyayı işledikten sonra sil

    # Veritabanına patientData ekleyin
    my_db.patientData.insert_one(patient_data)

    # Formdan gelen verileri al ve veritabanına kaydet
    # Kan değerlerini içeren Excel dosyasını işle ve veritabanına ekle
    return redirect(url_for('index'))


@app.route('/api/diagnosis', methods=['GET'])
def get_all_inventory():
    # Tüm hasta verilerini JSON formatında döndür
    try:
        patients = list(my_db.patientData.find())
        for patient in patients:
            patient['_id'] = str(patient['_id'])
        return jsonify(patients)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/patients/<string:patient_name>', methods=['GET'])
def get_patient_by_name(patient_name):
    # Belirli bir isme sahip hastanın verilerini JSON formatında döndür
    try:
        patient = my_db.patientData.find_one({"name": patient_name})
        if patient:
            patient['_id'] = str(patient['_id'])
            return jsonify(patient)
        else:
            return jsonify({'error': 'Patient not found'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    app.run(debug=True)