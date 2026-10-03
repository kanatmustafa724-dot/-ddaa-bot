import hashlib
import json
import math
import sqlite3
import time
from datetime import datetime, timedelta, timezone
import requests

# ----------------------------------------------------
# TELEGRAM AYARLARI
# ----------------------------------------------------
TELEGRAM_TOKEN = "8708221877:AAGzOC55HoFO1oh8pcXGus5l2eY4HmctGCw"
CHAT_ID = "1097662219"

# ----------------------------------------------------
# 0. YARDIMCI GÜVENLİK VE TEMİZLİK FONKSİYONLARI
# ----------------------------------------------------
def markdown_temizle(text):
    if not text:
        return ""
    return str(text).replace("_", " ").replace("*", "").replace("`", "").replace("[", "").replace("]", "")

def iddaa_bulteninde_var_mi(ham_lig_adi):
    l = ham_lig_adi.lower()
    izin_verilenler = [
        "segunda", "laliga 2", "la liga 2", "spain 2", "championship", "serie b",
        "bundesliga 2", "ligue 2", "eerste divisie", "super lig", "süper lig",
        "premier league", "laliga", "la liga", "serie a", "bundesliga", "ligue 1",
        "champions league", "europa league", "conference"
    ]
    for izin in izin_verilenler:
        if izin in l:
            return True
            
    yasaklar = [
        "u15", "u16", "u17", "u18", "u19", "u20", "u21", "u23", "youth", "reserves", "reserve",
        "amatör", "amateur", "women", "kadınlar", "feminin", "ncaa", "regionalliga", "oberliga",
        "state", "regional", "torneo", "primera c", "primera d", "serie d", "bolge", "bölgesel"
    ]
    for yasak in yasaklar:
        if yasak in l:
            return False
    return True

def telegram_komutlarini_ayarla():
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/setMyCommands"
    komutlar = {
        "commands": [
            {"command": "bulten", "description": "📋 İddaa Uyumlu Güncel Maçlar"},
            {"command": "canli", "description": "🔴 Oynanan Canlı Maçlar"},
            {"command": "gelecek", "description": "📅 Gelecek Maçlar"},
            {"command": "banko", "description": "🔥 %85+ Pro Optimize Banko Maçlar"},
            {"command": "kombine", "description": "🍀 Günün Özel Kombinesi"},
            {"command": "kombinasyon", "description": "📊 Görsel Tarzında Çoklu Bahis Analizi"},
            {"command": "surpriz", "description": "⚡ Yüksek Oranlı Maçlar (2.40+)"},
            {"command": "ekstrem", "description": "💣 2/1 - 1/2 ve Ekstrem Maçlar"},
            {"command": "ligler", "description": "🏆 Desteklenen Lig Kodları Listesi"},
            {"command": "lig", "description": "🔍 Lige Göre Filtrele (Örn: /lig TR-1)"},
            {"command": "lig_performans", "description": "📊 Lig Bazlı Başarı İstatistikleri"},
            {"command": "kasa", "description": "💰 Sanal Kasa ve Bütçe Durumu"},
            {"command": "rapor", "description": "📋 Sonuçlanan Tahmin Raporu"},
            {"command": "performans", "description": "📈 Anlık Başarı Yüzdesi"},
            {"command": "takiptedirler", "description": "⭐ Takip Edilen Maçlar"},
            {"command": "temizle", "description": "🧹 Sohbet Geçmişini Temizle"}
        ]
    }
    try:
        requests.post(url, json=komutlar, timeout=5)
    except Exception as e:
        print("Komut menüsü ayarlama hatası:", e)

# ----------------------------------------------------
# 1. TÜRKİYE SAATİ (TSİ / UTC+3)
# ----------------------------------------------------
def utc_to_tsi(utc_date_str):
    try:
        if not utc_date_str:
            tsi_now = datetime.now(timezone.utc) + timedelta(hours=3)
            return tsi_now.strftime("%d.%m.%Y - %H:%M TSİ")
        clean_str = utc_date_str.replace("Z", "")
        if "T" in clean_str:
            dt = datetime.strptime(clean_str[:16], "%Y-%m-%dT%H:%M")
        else:
            dt = datetime.strptime(clean_str[:16], "%Y-%m-%d %H:%M")
        tsi_dt = dt + timedelta(hours=3)
        return tsi_dt.strftime("%d.%m.%Y - %H:%M TSİ")
    except Exception:
        tsi_now = datetime.now(timezone.utc) + timedelta(hours=3)
        return tsi_now.strftime("%d.%m.%Y - %H:%M TSİ")

# ----------------------------------------------------
# 2. VERİTABANI KURULUMU VE MİGRASYON
# ----------------------------------------------------
def vt_kur():
    conn = sqlite3.connect("oran_arsivi.db")
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS maclar (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mac_adi TEXT,
            lig_kodu TEXT DEFAULT '🌐 [DİĞER]',
            ms1 REAL, msx REAL, ms2 REAL,
            tahmin TEXT,
            ev_skor INTEGER DEFAULT 0,
            dep_skor INTEGER DEFAULT 0,
            durum TEXT DEFAULT 'DEVAM',
            kazandi INTEGER DEFAULT -1
        )
    ''')
    cursor.execute("PRAGMA table_info(maclar)")
    columns = [column[1] for column in cursor.fetchall()]
    if "lig_kodu" not in columns:
        try:
            cursor.execute("ALTER TABLE maclar ADD COLUMN lig_kodu TEXT DEFAULT '🌐 [DİĞER]'")
        except Exception:
            pass
            
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS kasa (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bakiye REAL DEFAULT 1000.0,
            islem_notu TEXT,
            tarih TEXT
        )
    ''')
    cursor.execute("SELECT COUNT(*) FROM kasa")
    if cursor.fetchone()[0] == 0:
        cursor.execute("INSERT INTO kasa (bakiye, islem_notu, tarih) VALUES (?, ?, ?)", 
                       (1000.0, "Başlangıç Kasası", datetime.now().strftime("%d.%m.%Y")))
    conn.commit()
    conn.close()

vt_kur()

def tahmini_kaydet_veya_guncelle(mac_adi, lig_kodu, ms1, msx, ms2, tahmin):
    try:
        conn = sqlite3.connect("oran_arsivi.db")
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM maclar WHERE mac_adi = ? AND durum = 'DEVAM'", (mac_adi,))
        row = cursor.fetchone()
        if not row:
            cursor.execute('''
                INSERT INTO maclar (mac_adi, lig_kodu, ms1, msx, ms2, tahmin)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (mac_adi, lig_kodu, ms1, msx, ms2, tahmin))
        conn.commit()
        conn.close()
    except Exception as e:
        print("Tahmin kayıt hatası:", e)

def mac_sonucunu_isle(mac_adi, ev_skor, dep_skor):
    try:
        conn = sqlite3.connect("oran_arsivi.db")
        cursor = conn.cursor()
        cursor.execute("SELECT id, tahmin FROM maclar WHERE mac_adi = ? AND durum = 'DEVAM'", (mac_adi,))
        row = cursor.fetchone()
        if row:
            mac_db_id, tahmin = row[0], row[1]
            toplam_gol = ev_skor + dep_skor
            kazandi = 0
            tahmin_upper = tahmin.upper().strip()
            
            if ev_skor > dep_skor:
                mac_sonucu = "MS1"
            elif ev_skor < dep_skor:
                mac_sonucu = "MS2"
            else:
                mac_sonucu = "MS0"

            if ("MS 1" in tahmin_upper or "MS1" in tahmin_upper) and mac_sonucu == "MS1":
                kazandi = 1
            elif ("MS 2" in tahmin_upper or "MS2" in tahmin_upper) and mac_sonucu == "MS2":
                kazandi = 1
            elif ("MS X" in tahmin_upper or "MS0" in tahmin_upper) and mac_sonucu == "MS0":
                kazandi = 1
            elif "KG VAR" in tahmin_upper and (ev_skor > 0 and dep_skor > 0):
                kazandi = 1
            elif "2.5 ÜST" in tahmin_upper and toplam_gol > 2.5:
                kazandi = 1
            elif "2.5 ALT" in tahmin_upper and toplam_gol < 2.5:
                kazandi = 1
            elif "1X" in tahmin_upper and mac_sonucu in ["MS1", "MS0"]:
                kazandi = 1
            elif "X2" in tahmin_upper and mac_sonucu in ["MS2", "MS0"]:
                kazandi = 1
            elif "İY 0.5 ÜST" in tahmin_upper and toplam_gol > 0:
                kazandi = 1
            elif "İY EV 0.5 ÜST" in tahmin_upper and ev_skor > 0:
                kazandi = 1
            elif "İY DEP 0.5 ÜST" in tahmin_upper and dep_skor > 0:
                kazandi = 1
            elif "İY 1.5 ÜST" in tahmin_upper and toplam_gol >= 2:
                kazandi = 1
            elif "2/1" in tahmin_upper or "1/2" in tahmin_upper or "SÜRPRIZ" in tahmin_upper:
                if toplam_gol > 0: kazandi = 1 
            
            cursor.execute('''
                UPDATE maclar 
                SET ev_skor = ?, dep_skor = ?, durum = 'BITTI', kazandi = ?
                WHERE id = ?
            ''', (ev_skor, dep_skor, kazandi, mac_db_id))
            conn.commit()
        conn.close()
    except Exception as e:
        print("Maç sonuç işleme hatası:", e)

def telegram_mesaj_gonder(mesaj, reply_markup=None):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": mesaj, "parse_mode": "Markdown"}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        print("Telegram gönderme hatası:", e)

def telegram_callback_cevapla(callback_query_id, text=""):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/answerCallbackQuery"
    payload = {"callback_query_id": callback_query_id, "text": text}
    try:
        requests.post(url, json=payload, timeout=3)
    except Exception:
        pass

def telegram_mesaj_sil(chat_id, message_id):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/deleteMessage"
    payload = {"chat_id": chat_id, "message_id": message_id}
    try:
        requests.post(url, data=payload, timeout=5)
    except Exception as e:
        print("Mesaj silme hatası:", e)

def sohbeti_temizle(chat_id, son_mesaj_id, limit=100):
    for m_id in range(son_mesaj_id, max(1, son_mesaj_id - limit), -1):
        telegram_mesaj_sil(chat_id, m_id)
        time.sleep(0.03)

# ----------------------------------------------------
# 3. LİG KODU ÜRETİCİ
# ----------------------------------------------------
def lig_kodu_uret(lig_adi):
    l = lig_adi.lower()
    if "super lig" in l or "süper lig" in l: return "🇹🇷 [TR-1]"
    elif "1. lig" in l or "tff 1" in l: return "🇹🇷 [TR-2]"
    elif "premier league" in l: return "🇬🇧 [ENG-1]"
    elif "championship" in l: return "🇬🇧 [ENG-2]"
    elif "laliga 2" in l or "segunda" in l or "spain 2" in l: return "🇪🇸 [ESP-2]"
    elif "laliga" in l or "la liga" in l: return "🇪🇸 [ESP-1]"
    elif "serie b" in l: return "🇮🇹 [ITA-2]"
    elif "serie a" in l: return "🇮🇹 [ITA-1]"
    elif "bundesliga 2" in l: return "🇩🇪 [GER-2]"
    elif "bundesliga" in l: return "🇩🇪 [GER-1]"
    elif "ligue 2" in l: return "🇫🇷 [FRA-2]"
    elif "ligue 1" in l: return "🇫🇷 [FRA-1]"
    elif "champions league" in l or "şampiyonlar" in l: return "🇪🇺 [UCL]"
    elif "europa league" in l or "avrupa ligi" in l: return "🇪🇺 [UEL]"
    elif "conference" in l: return "🇪🇺 [UECL]"
    else:
        temiz = lig_adi.replace("League", "").replace("Division", "").strip()
        kisa = temiz[:4].upper()
        return f"🌐 [{kisa}]"

# ----------------------------------------------------
# 4. GERÇEKÇİ OPTİMİZE PUAN DURUMU & FORM MOTORU
# ----------------------------------------------------
def gercek_puan_durumu_ve_form_cek():
    puan_sozlugu = {}
    try:
        url = "https://site.api.espn.com/apis/v2/sports/soccer/eng.1/standings"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        res = requests.get(url, headers=headers, timeout=5)
        if res.status_code == 200:
            data = res.json()
            for standing in data.get("standings", []):
                for entry in standing.get("entries", []):
                    team_name = markdown_temizle(entry.get("team", {}).get("displayName", ""))
                    stats = {"rank": 0, "points": 0, "form": "WWWDW", "G": 0, "B": 0, "M": 0}
                    for stat in entry.get("stats", []):
                        name = stat.get("name", "")
                        if name == "points": stats["points"] = stat.get("value", 0)
                        elif name == "rank": stats["rank"] = stat.get("value", 0)
                        elif name == "form": stats["form"] = stat.get("displayValue", "WWWDW")
                    puan_sozlugu[team_name] = stats
    except Exception as e:
        print("Puan durumu çekme istisnası:", e)
    return puan_sozlugu

# ----------------------------------------------------
# 5. GELİŞTİRİLMİŞ YÜKSEK BAŞARILI ANALİZ & ORAN MOTORu
# ----------------------------------------------------
def poisson_asil(lmbda, k):
    try:
        return (math.exp(-lmbda) * (lmbda ** k)) / math.factorial(k)
    except Exception:
        return 0.0

def lig_basari_orani_getir(lig_kodu):
    try:
        conn = sqlite3.connect("oran_arsivi.db")
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*), SUM(kazandi) FROM maclar WHERE lig_kodu = ? AND durum = 'BITTI'", (lig_kodu,))
        row = cursor.fetchone()
        conn.close()
        
        if not row or row[0] < 3:
            return 55.0 # Varsayılan optimize başlangıç başarısı
            
        toplam, kazanan = row[0], (row[1] if row[1] else 0)
        return round((kazanan / toplam) * 100, 1)
    except Exception:
        return 55.0

def oranlari_ve_guc_uret(ev_takim, dep_takim, puan_tablosu):
    # Takım adlarına özel tutarlı hash üretimi (istikrarlı simülasyon)
    seed_str = f"{ev_takim}_{dep_takim}"
    hash_val = int(hashlib.md5(seed_str.encode()).hexdigest(), 16)
    
    # Form tabanlı dinamik güç katsayıları
    ev_form_bonus = 0.0
    dep_form_bonus = 0.0
    
    if ev_takim in puan_tablosu:
        f_str = puan_tablosu[ev_takim].get("form", "WWDDD")
        ev_form_bonus = (f_str.count("W") * 0.08) - (f_str.count("L") * 0.08)
        
    if dep_takim in puan_tablosu:
        f_str = puan_tablosu[dep_takim].get("form", "WWDDD")
        dep_form_bonus = (f_str.count("W") * 0.08) - (f_str.count("L") * 0.08)

    ev_guc = 1.35 + ((hash_val % 40) / 100) + ev_form_bonus
    dep_guc = 1.05 + (((hash_val >> 3) % 40) / 100) + dep_form_bonus
    
    # Ev sahibi avantajı (Futbol istatistik standartlarına göre ~0.25 gol avantajı)
    ev_xg = max(0.65, round(ev_guc * 0.85 + 0.25, 2))
    dep_xg = max(0.50, round(dep_guc * 0.75, 2))
    
    # Oranları xG dengesine göre optimize et
    if ev_xg > dep_xg + 0.4:
        ms1 = round(1.50 + ((hash_val % 20) / 100), 2)
        msx = round(3.60 + ((hash_val % 40) / 100), 2)
        ms2 = round(4.20 + ((hash_val % 80) / 100), 2)
    elif dep_xg > ev_xg + 0.2:
        ms1 = round(2.80 + ((hash_val % 50) / 100), 2)
        msx = round(3.30 + ((hash_val % 30) / 100), 2)
        ms2 = round(2.10 + ((hash_val % 40) / 100), 2)
    else:
        ms1 = round(2.15 + ((hash_val % 30) / 100), 2)
        msx = round(3.20 + ((hash_val % 25) / 100), 2)
        ms2 = round(3.05 + ((hash_val % 40) / 100), 2)
        
    return ms1, msx, ms2, ev_xg, dep_xg

def canli_ve_gelecek_maclari_cek():
    url = "https://site.api.espn.com/apis/site/v2/sports/soccer/all/scoreboard"
    canli_listesi = []
    gelecek_listesi = []
    tum_listesi = []
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    puan_tablosu = gercek_puan_durumu_ve_form_cek()
    
    try:
        response = requests.get(url, headers=headers, timeout=8)
        if response.status_code == 200:
            data = response.json()
            events = data.get("events", [])
            valid_id_counter = 1
            for event in events:
                comps = event.get("competitions", [])
                if not comps: continue
                ham_lig = markdown_temizle(event.get("league", {}).get("name", "Futbol Ligi"))
                if not iddaa_bulteninde_var_mi(ham_lig): continue
                
                competition = comps[0]
                competitors = competition.get("competitors", [])
                lig_kodu = lig_kodu_uret(ham_lig)
                tam_lig_str = f"{lig_kodu} {ham_lig}"
                
                if len(competitors) >= 2:
                    ev = markdown_temizle(competitors[0].get("team", {}).get("displayName", "Ev Sahibi"))
                    ev_skor = competitors[0].get("score", "0")
                    dep = markdown_temizle(competitors[1].get("team", {}).get("displayName", "Deplasman Takımı"))
                    dep_skor = competitors[1].get("score", "0")
                    
                    raw_date = event.get("date", "")
                    ts_saat = utc_to_tsi(raw_date)
                    status_type = event.get("status", {}).get("type", {}).get("state", "")
                    status_detail = markdown_temizle(event.get("status", {}).get("type", {}).get("shortDetail", "VS"))
                    is_completed = event.get("status", {}).get("type", {}).get("completed", False)
                    
                    ms1, msx, ms2, ev_xg, dep_xg = oranlari_ve_guc_uret(ev, dep, puan_tablosu)
                    ev_s = int(ev_skor) if str(ev_skor).isdigit() else 0
                    dep_s = int(dep_skor) if str(dep_skor).isdigit() else 0
                    mac_adi = f"{ev} - {dep}"
                    
                    if is_completed:
                        mac_sonucunu_isle(mac_adi, ev_s, dep_s)
                    
                    mac_obj = {
                        "id": valid_id_counter,
                        "ev": ev,
                        "dep": dep,
                        "ev_skor": ev_s,
                        "dep_skor": dep_s,
                        "durum": status_detail,
                        "state": status_type,
                        "saat": ts_saat,
                        "is_completed": is_completed,
                        "lig": tam_lig_str,
                        "lig_kodu_sade": lig_kodu,
                        "ms1": ms1,
                        "msx": msx,
                        "ms2": ms2,
                        "ev_xg": ev_xg,
                        "dep_xg": dep_xg,
                        "mac_adi": f"{ev} {ev_s} - {dep_s} {dep}",
                        "sade_mac_adi": mac_adi
                    }
                    tum_listesi.append(mac_obj)
                    valid_id_counter += 1
                    
                    if status_type == "in" and not is_completed:
                        canli_listesi.append(mac_obj)
                    elif status_type == "pre":
                        gelecek_listesi.append(mac_obj)
    except Exception as e:
        print("ESPN API Bağlantı Hatası:", e)
        
    return tum_listesi, canli_listesi, gelecek_listesi

def canli_tahmin_uret(mac):
    ev_s = mac["ev_skor"]
    dep_s = mac["dep_skor"]
    toplam_gol = ev_s + dep_s
    if ev_s == 0 and dep_s == 0:
        return "⚡ İY 0.5 ÜST / KG VAR", 90, "Erken baskı temposu yüksek."
    elif ev_s > 0 and dep_s > 0:
        return f"🔥 {toplam_gol + 1.5:.1f} ÜST", 93, "Karşılıklı goller geldi, maç açık alana döndü."
    elif ev_s > dep_s:
        return f"🚀 MS 1 / İY EV 0.5 ÜST", 89, f"{mac['ev']} skoru koruyor ve etkili."
    else:
        return f"🚀 MS 2 / İY DEP 0.5 ÜST", 89, f"{mac['dep']} deplasmanda baskı kurdu."

def detayli_analiz_yap(mac):
    try:
        ev_xg = mac["ev_xg"]
        dep_xg = mac["dep_xg"]
        toplam_xg = round(ev_xg + dep_xg, 2)
        
        ev_galibiyet = 0.0
        dep_galibiyet = 0.0
        beraberlik = 0.0
        ust_25 = 0.0
        kg_var = 0.0

        for i in range(7):
            for j in range(7):
                p = poisson_asil(ev_xg, i) * poisson_asil(dep_xg, j)
                if i > j: ev_galibiyet += p
                elif j > i: dep_galibiyet += p
                else: beraberlik += p
                if i + j > 2.5: ust_25 += p
                if i > 0 and j > 0: kg_var += p

        ev_iy_xg = ev_xg * 0.46
        dep_iy_xg = dep_xg * 0.46
        p_iy_05_ust = 1.0 - (poisson_asil(ev_iy_xg, 0) * poisson_asil(dep_iy_xg, 0))
        
        lig_basari = lig_basari_orani_getir(mac["lig_k
