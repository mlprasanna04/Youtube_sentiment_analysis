import json
import io
import re
from flask import Flask, render_template, request, send_file
from textblob import TextBlob
from wordcloud import WordCloud
import matplotlib.pyplot as plt
import googleapiclient.discovery
import mysql.connector

app = Flask(__name__)

# YouTube API key
YOUTUBE_API_KEY = 'AIzaSyA-aJ43AUKn0ZdY9ppATH0FTB7hHPJM_qU'

# MySQL configuration
DB_CONFIG = {
    'host': 'localhost',
    'user': 'root',
    'password': 'Prasad04.',
    'database': 'analysis'
}

def connect_to_db():
    return mysql.connector.connect(**DB_CONFIG)

def create_tables():
    """Creates necessary MySQL tables for storing analysis results."""
    conn = connect_to_db()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS analysis_results (
            id INT AUTO_INCREMENT PRIMARY KEY,
            video_id VARCHAR(20),
            year INT,
            positive_count INT DEFAULT 0,
            negative_count INT DEFAULT 0,
            neutral_count INT DEFAULT 0,
            total_count INT DEFAULT 0,
            analysis_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(video_id, year)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sentiment_analysis_report (
            id INT AUTO_INCREMENT PRIMARY KEY,
            video_id VARCHAR(20),
            sentiment_period VARCHAR(10),
            positive_count INT DEFAULT 0,
            negative_count INT DEFAULT 0,
            neutral_count INT DEFAULT 0,
            total_count INT DEFAULT 0,
            analysis_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(video_id, sentiment_period)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS spam_analysis (
            id INT AUTO_INCREMENT PRIMARY KEY,
            video_id VARCHAR(20),
            spam_count INT DEFAULT 0,
            non_spam_count INT DEFAULT 0,
            total_count INT DEFAULT 0,
            analysis_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(video_id)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sponsored_analysis (
            id INT AUTO_INCREMENT PRIMARY KEY,
            video_id VARCHAR(20),
            sponsored_ads_count INT DEFAULT 0,
            promotions_count INT DEFAULT 0,
            analysis_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(video_id)
        )
    """)

    conn.commit()
    cursor.close()
    conn.close()

create_tables()

def get_video_id_from_url(url_or_id):
    match = re.search(r"(?:v=|\/)([0-9A-Za-z_-]{11}).*", url_or_id)
    return match.group(1) if match else url_or_id.strip()

def get_comments(video_id):
    comments = []
    youtube = googleapiclient.discovery.build("youtube", "v3", developerKey=YOUTUBE_API_KEY)

    request = youtube.commentThreads().list(
        part="snippet,replies",
        videoId=video_id,
        maxResults=100,
        textFormat="plainText"
    )

    while request:
        response = request.execute()
        for item in response["items"]:
            top_comment = item["snippet"]["topLevelComment"]["snippet"]
            text = top_comment["textDisplay"]
            year = int(top_comment["publishedAt"][:4])
            is_official = top_comment.get("authorIsChannelOwner", False)
            comments.append((text, year, top_comment["authorDisplayName"], is_official))

            if "replies" in item:
                for reply in item["replies"]["comments"]:
                    reply_text = reply["snippet"]["textDisplay"]
                    reply_year = int(reply["snippet"]["publishedAt"][:4])
                    reply_official = reply["snippet"].get("authorIsChannelOwner", False)
                    comments.append((reply_text, reply_year, reply["snippet"]["authorDisplayName"], reply_official))

        request = youtube.commentThreads().list_next(request, response)

    return comments

def analyze_sentiment_by_year(comments):
    sentiment_by_year = {}
    for comment, year, *_ in comments:
        if year not in sentiment_by_year:
            sentiment_by_year[year] = {'Positive': 0, 'Neutral': 0, 'Negative': 0}
        analysis = TextBlob(comment)
        polarity = analysis.sentiment.polarity
        if polarity > 0:
            sentiment_by_year[year]['Positive'] += 1
        elif polarity == 0:
            sentiment_by_year[year]['Neutral'] += 1
        else:
            sentiment_by_year[year]['Negative'] += 1
    return sentiment_by_year

def save_summary_to_db(video_id, sentiment_by_year):
    conn = connect_to_db()
    cursor = conn.cursor()
    query = """
        INSERT INTO analysis_results 
        (video_id, year, total_count, positive_count, neutral_count, negative_count)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE 
            total_count = VALUES(total_count),
            positive_count = VALUES(positive_count),
            neutral_count = VALUES(neutral_count),
            negative_count = VALUES(negative_count),
            analysis_time = CURRENT_TIMESTAMP
    """
    for year, counts in sentiment_by_year.items():
        total = counts['Positive'] + counts['Neutral'] + counts['Negative']
        cursor.execute(query, (video_id, year, total, counts['Positive'], counts['Neutral'], counts['Negative']))
    conn.commit()
    cursor.close()
    conn.close()

def store_total_sentiment_report(video_id, sentiment_by_year):
    conn = connect_to_db()
    cursor = conn.cursor()
    pos = sum(y['Positive'] for y in sentiment_by_year.values())
    neu = sum(y['Neutral'] for y in sentiment_by_year.values())
    neg = sum(y['Negative'] for y in sentiment_by_year.values())
    total = pos + neu + neg

    sql = """
        INSERT INTO sentiment_analysis_report 
        (video_id, sentiment_period, positive_count, negative_count, neutral_count, total_count)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE 
            positive_count = VALUES(positive_count),
            negative_count = VALUES(negative_count),
            neutral_count = VALUES(neutral_count),
            total_count = VALUES(total_count),
            analysis_time = CURRENT_TIMESTAMP
    """
    cursor.execute(sql, (video_id, 'total', pos, neg, neu, total))
    conn.commit()
    cursor.close()
    conn.close()

def analyze_spam(comments):
    spam_keywords = ['sponsored', 'ad', 'promotion', 'promoted', 'check out', 'discount', 'buy now']
    spam_count = sum(any(kw in comment.lower() for kw in spam_keywords) for comment, *_ in comments)
    return spam_count, len(comments) - spam_count

def save_spam_data(video_id, spam_count, non_spam_count):
    total = spam_count + non_spam_count
    conn = connect_to_db()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO spam_analysis (video_id, spam_count, non_spam_count, total_count)
        VALUES (%s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE 
            spam_count = VALUES(spam_count),
            non_spam_count = VALUES(non_spam_count),
            total_count = VALUES(total_count),
            analysis_time = CURRENT_TIMESTAMP
    """, (video_id, spam_count, non_spam_count, total))
    conn.commit()
    cursor.close()
    conn.close()

def analyze_sponsored_entries(comments):
    ads_keywords = ['sponsored', 'ad']
    promo_keywords = ['promotion', 'discount', 'buy now']
    ads = sum(any(kw in comment.lower() for kw in ads_keywords) for comment, *_ in comments)
    promos = sum(any(kw in comment.lower() for kw in promo_keywords) for comment, *_ in comments)
    return ads, promos

def save_sponsored_data(video_id, ads_count, promotions_count):
    conn = connect_to_db()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO sponsored_analysis (video_id, sponsored_ads_count, promotions_count)
        VALUES (%s, %s, %s)
        ON DUPLICATE KEY UPDATE 
            sponsored_ads_count = VALUES(sponsored_ads_count),
            promotions_count = VALUES(promotions_count),
            analysis_time = CURRENT_TIMESTAMP
    """, (video_id, ads_count, promotions_count))
    conn.commit()
    cursor.close()
    conn.close()

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/analyze', methods=['POST'])
def analyze():
    url_input = request.form.get('youtube_url')
    id_input = request.form.get('video_id')
    video_id = get_video_id_from_url(id_input if id_input else url_input)

    comments = get_comments(video_id)
    if not comments:
        return "No comments found for this video."

    # Perform sentiment analysis
    sentiment_by_year = analyze_sentiment_by_year(comments)
    save_summary_to_db(video_id, sentiment_by_year)
    store_total_sentiment_report(video_id, sentiment_by_year)

    # Run spam analysis and store it
    spam_count, non_spam_count = analyze_spam(comments)
    save_spam_data(video_id, spam_count, non_spam_count)

    # Calculate sentiment counts
    total = sum(sum(y.values()) for y in sentiment_by_year.values())
    positive = sum(y['Positive'] for y in sentiment_by_year.values())
    neutral = sum(y['Neutral'] for y in sentiment_by_year.values())
    negative = sum(y['Negative'] for y in sentiment_by_year.values())

    # Prepare data for pie/doughnut chart
    graph_data = {
        'labels': ['Positive', 'Neutral', 'Negative'],
        'values': [positive, neutral, negative]
    }

    return render_template('result.html', 
        video_id=video_id,
        total=total,
        positive=positive,
        neutral=neutral,
        negative=negative,
        details=sentiment_by_year,
        graph_data=graph_data
    )

@app.route('/wordcloud/<video_id>')
def wordcloud(video_id):
    comments = get_comments(video_id)
    if not comments:
        return "No comments found for this video."

    # Combine all the comments into one large text string
    all_comments_text = ' '.join(comment for comment, *_ in comments)

    # Generate the word cloud from the comments
    wordcloud_img = WordCloud(width=800, height=400, background_color='white').generate(all_comments_text)
    
    # Create an in-memory image to send as response
    img_io = io.BytesIO()
    plt.figure(figsize=(10, 5))
    plt.imshow(wordcloud_img, interpolation='bilinear')
    plt.axis('off')
    plt.savefig(img_io, format='png')
    img_io.seek(0)

    # Return the image directly as a response
    return send_file(img_io, mimetype='image/png')


@app.route('/spam_result/<video_id>')
def spam_result(video_id):
    conn = connect_to_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT spam_count, non_spam_count, total_count 
        FROM spam_analysis 
        WHERE video_id = %s
    """, (video_id,))
    result = cursor.fetchone()
    cursor.close()
    conn.close()

    if result:
        spam_count, non_spam_count, total_count = result
        if total_count > 0:
            spam_percent = round((spam_count / total_count) * 100, 2)
            non_spam_percent = round((non_spam_count / total_count) * 100, 2)
        else:
            spam_percent = non_spam_percent = 0.0

        return render_template(
            'spam_result.html',
            video_id=video_id,
            spam_count=spam_count,
            non_spam_count=non_spam_count,
            total_count=total_count,
            spam_percent=spam_percent,
            non_spam_percent=non_spam_percent
        )

    return f"No spam data available for video {video_id}."


@app.route('/sponsored_result/<video_id>')
def sponsored_result(video_id):
    comments = get_comments(video_id)
    if not comments:
        return f"No comments found for video {video_id}."

    ads_keywords = ['sponsored', 'ad']
    promo_keywords = ['promotion', 'discount', 'buy now']

    ads = set()
    promotions = set()
    official_comments = []

    ads_count = 0
    promotions_count = 0
    total = len(comments)

    for comment, year, author, is_official in comments:
        comment_lower = comment.lower()
        date = f"{year}-01-01"
        urls = re.findall(r'https?://\S+', comment)
        comment_id = (comment.strip(), tuple(urls))  # Unique identifier

        if any(kw in comment_lower for kw in ads_keywords):
            ads_count += 1
            if urls:
                ads.add(comment_id)
        elif any(kw in comment_lower for kw in promo_keywords):
            promotions_count += 1
            if urls:
                promotions.add(comment_id)

        if is_official:
            official_comments.append({'text': comment, 'date': date, 'urls': urls})

    # Convert sets to list of dicts for rendering
    ads_list = [{'text': c[0], 'date': f"{year}-01-01", 'urls': list(c[1])} for c in ads]
    promotions_list = [{'text': c[0], 'date': f"{year}-01-01", 'urls': list(c[1])} for c in promotions]

    ads_percent = round((ads_count / total) * 100, 2) if total else 0
    promotions_percent = round((promotions_count / total) * 100, 2) if total else 0

    return render_template(
        'sponsored_result.html',
        video_id=video_id,
        ads_count=ads_count,
        promotions_count=promotions_count,
        ads_percent=ads_percent,
        promotions_percent=promotions_percent,
        ads=ads_list,
        promotions=promotions_list,
        official_comments=official_comments
    )


@app.route('/analyze_sentiment_by_year/<video_id>')
def analyze_sentiment_by_year_route(video_id):
    conn = connect_to_db()
    cursor = conn.cursor()
    
    # Query to select sentiment counts for each year from 2021 to 2025
    cursor.execute("""
        SELECT year, positive_count, negative_count, neutral_count
        FROM analysis_results
        WHERE video_id = %s AND year BETWEEN 2021 AND 2025
        ORDER BY year
    """, (video_id,))
    
    # Fetch all the results
    results = cursor.fetchall()
    cursor.close()
    conn.close()

    # Prepare the data for Chart.js
    years = []
    positive_counts = []
    neutral_counts = []
    negative_counts = []

    # Process the query results into a format suitable for the frontend
    for year, positive, negative, neutral in results:
        years.append(str(year))
        positive_counts.append(positive)
        neutral_counts.append(neutral)
        negative_counts.append(negative)

    # Prepare graph_data dictionary
    graph_data = {
        'labels': years,
        'positive': positive_counts,
        'neutral': neutral_counts,
        'negative': negative_counts
    }

    # Render the template and pass the graph_data and video_id
    return render_template('analyze_sentiment_by_year.html', graph_data=graph_data, video_id=video_id)

if __name__ == '__main__':
    app.run(debug=True)