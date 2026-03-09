# מדריך העלאה ל-Railway — SurgeNet

## מה תקבל בסוף
כתובת אינטרנט כמו: `https://surgenet-production.up.railway.app`
כל בית חולים נכנס מהדפדפן — ללא התקנה.

---

## שלב 1 — העלה ל-GitHub

### א. צור Repository חדש
1. כנס ל-github.com
2. לחץ על **"New repository"** (כפתור ירוק)
3. שם: `surgenet`
4. בחר **Private** (סודי — חשוב!)
5. לחץ **"Create repository"**

### ב. העלה את הקבצים
בחר **"uploading an existing file"** ולחץ **"choose your files"**

העלה את הקבצים הבאים:
- `app.py`
- `database.py`
- `requirements.txt`
- `Procfile`
- `railway.json`
- תיקיית `templates/` (כולל `index.html` בפנים)

לחץ **"Commit changes"**

---

## שלב 2 — חבר ל-Railway

1. כנס ל-**railway.app**
2. לחץ **"Login with GitHub"**
3. לחץ **"New Project"**
4. בחר **"Deploy from GitHub repo"**
5. בחר את ה-repo `surgenet`
6. Railway יתחיל לבנות אוטומטית (כ-2 דקות)

---

## שלב 3 — הגדר משתנה סביבה

ב-Railway, לך ל: **Variables** ← הוסף:
```
SECRET_KEY = [מחרוזת אקראית ארוכה, לדוגמה: xK9mP2qL8nR5vT3w]
```

---

## שלב 4 — קבל את הכתובת

1. לחץ על **"Settings"**
2. לחץ **"Generate Domain"**
3. תקבל כתובת כמו: `surgenet-production.up.railway.app`

**זהו! המערכת פעילה.**

---

## כניסה ראשונה
- כתובת: הכתובת שקיבלת מ-Railway
- שם משתמש: `admin`
- סיסמה: `admin123`

**⚠️ שנה את הסיסמה מיד לאחר הכניסה הראשונה!**

---

## הערות חשובות

### גיבוי נתונים
Railway מספק volume לשמירת הנתונים.
ב-Railway לך ל: **Add Volume** → Mount Path: `/app`

### עלות
- תוכנית חינמית: $5 קרדיט חודשי (מספיק לשימוש קל)
- תוכנית מקצועית: $20/חודש (ללא הגבלה)

### אבטחה לפני שימוש אמיתי
- [ ] החלף סיסמת admin
- [ ] הגדר SECRET_KEY חזק
- [ ] הוסף HTTPS (Railway מספק אוטומטית)
- [ ] הוסף Volume לגיבוי DB
