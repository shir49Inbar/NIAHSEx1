import pandas as pd
import numpy as np

# 1. טעינת הנתונים הקיימים (כדי לא להריץ את ה-Crawler מחדש)
input_file = "output/books_processed.csv"
df = pd.read_csv(input_file)

# 2. הגדרת העמודות לחישוב לפי דרישות המטלה
cols = ["Price in USD", "Year", "StarRating", "NumberOfReviews", "NumberOfAuthors"]

# 3. ניקוי נתונים: המרה לנומרי (ערכי "None" או טקסט יהפכו ל-NaN וינוטרלו מהחישוב)
temp_df = df[cols].copy()
for col in cols:
    temp_df[col] = pd.to_numeric(temp_df[col], errors='coerce')

# 4. חישוב הסטטיסטיקות (Pandas מתעלם אוטומטית מערכי NaN בממוצע ובסטיית תקן)
summary = temp_df.agg(['mean', 'std', 'min', 'max', 'median']).transpose()

# 5. הוספת עמודת Total Rows (סך כל השורות ב-DF המקורי)
summary['Total Rows'] = len(df)

# 6. סידור מחדש של הטבלה למבנה הנדרש (סטטיסטיקה כשורות, עמודות כעמודות)
summary = summary.transpose()
summary.index = ["Mean", "Standard Deviation", "Min", "Max", "Median", "Total Rows"]

# 7. עיגול ל-2 ספרות אחרי הנקודה (חשוב לציון!) ושמירה
summary = summary.round(2)
summary.to_csv("output/books_summary.csv", encoding="utf-8-sig")

print("הקובץ output/books_summary.csv עודכן בהצלחה עם הנתונים הקיימים.")