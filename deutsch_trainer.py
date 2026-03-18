#!/usr/bin/env python3
"""
🇩🇪 Deutsch B1 Trainer - AI German Learning App

USAGE:
  python deutsch_trainer.py                    # Default: port 9999, shared on network
  python deutsch_trainer.py --port 8080       # Custom port
  python deutsch_trainer.py --local-only      # Only localhost (secure mode)
  python deutsch_trainer.py --help            # Show all options

SHARING WITH FRIENDS:

  🏠 Local Network (same WiFi):
    1. Run: python deutsch_trainer.py
    2. Share your local IP: http://192.168.x.x:9999

  🌍 Internet (worldwide):
    1. Install ngrok: https://ngrok.com/download
    2. Run: python deutsch_trainer.py --ngrok
    3. Share the ngrok URL: https://xyz.ngrok.io

  🔒 Private use:
    python deutsch_trainer.py --local-only

SECURITY:
  - Local mode: Only your computer can access
  - Network mode: Anyone on same WiFi can access
  - Ngrok mode: Anyone worldwide can access (careful!)
  - API keys are processed locally, never shared
"""
import http.server, json, urllib.request, urllib.error, threading, webbrowser, sys, argparse, subprocess, time
import sqlite3, os, datetime, uuid

# Parse command line arguments
parser = argparse.ArgumentParser(description='🇩🇪 Deutsch B1 Trainer')
parser.add_argument('--port', '-p', type=int, default=9999, help='Port number (default: 9999)')
parser.add_argument('--host', type=str, default='0.0.0.0', help='Host to bind to (default: 0.0.0.0 for all interfaces)')
parser.add_argument('--local-only', action='store_true', help='Only allow local connections (127.0.0.1)')
parser.add_argument('--ngrok', action='store_true', help='Auto-start ngrok tunnel for internet sharing')
args = parser.parse_args()

PORT = args.port
HOST = '127.0.0.1' if args.local_only else args.host

# Database setup
DB_PATH = "deutsch_trainer_history.db"
DATABASE_URL = os.environ.get('DATABASE_URL')
USE_POSTGRES = bool(DATABASE_URL)

def get_connection():
    """Get database connection - PostgreSQL if DATABASE_URL set, else SQLite"""
    if USE_POSTGRES:
        import psycopg2
        return psycopg2.connect(DATABASE_URL)
    return sqlite3.connect(DB_PATH, timeout=10.0)

def adapt_sql(sql):
    """Convert ? placeholders to %s for PostgreSQL"""
    if USE_POSTGRES:
        return sql.replace('?', '%s')
    return sql

def init_database():
    """Initialize database for chat history (PostgreSQL or SQLite)"""
    conn = get_connection()
    cursor = conn.cursor()

    if USE_POSTGRES:
        auto_id = "SERIAL PRIMARY KEY"
        bool_default = "BOOLEAN DEFAULT FALSE"
    else:
        auto_id = "INTEGER PRIMARY KEY AUTOINCREMENT"
        bool_default = "BOOLEAN DEFAULT 0"

    # Create tables
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY,
            mode TEXT NOT NULL,
            telc_part TEXT,
            start_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            end_time TIMESTAMP,
            message_count INTEGER DEFAULT 0,
            total_score INTEGER,
            max_score INTEGER
        )
    ''')

    cursor.execute(f'''
        CREATE TABLE IF NOT EXISTS messages (
            id {auto_id},
            session_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            has_feedback {bool_default},
            FOREIGN KEY (session_id) REFERENCES sessions (id)
        )
    ''')

    cursor.execute(f'''
        CREATE TABLE IF NOT EXISTS telc_scores (
            id {auto_id},
            session_id TEXT NOT NULL,
            telc_part TEXT NOT NULL,
            total_score INTEGER NOT NULL,
            max_score INTEGER NOT NULL,
            content_score INTEGER,
            grammar_score INTEGER,
            vocabulary_score INTEGER,
            pronunciation_score INTEGER,
            interaction_score INTEGER,
            fluency_score INTEGER,
            detailed_feedback TEXT,
            strengths TEXT,
            weaknesses TEXT,
            recommendations TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (session_id) REFERENCES sessions (id)
        )
    ''')

    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_messages_session_time
        ON messages (session_id, timestamp)
    ''')

    if not USE_POSTGRES:
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_messages_date
            ON messages (date(timestamp))
        ''')
    else:
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_messages_date
            ON messages (CAST(timestamp AS DATE))
        ''')

    conn.commit()
    conn.close()
    db_label = "PostgreSQL" if USE_POSTGRES else DB_PATH
    print(f"📊 Database initialized: {db_label}")

def save_message(session_id, role, content, mode="unknown"):
    """Save a chat message to database"""
    try:
        conn = get_connection()
        cursor = conn.cursor()

        # Ensure session exists
        if USE_POSTGRES:
            cursor.execute(
                'INSERT INTO sessions (id, mode) VALUES (%s, %s) ON CONFLICT (id) DO NOTHING',
                (session_id, mode))
        else:
            cursor.execute(
                'INSERT OR IGNORE INTO sessions (id, mode) VALUES (?, ?)',
                (session_id, mode))

        # Check if message contains feedback
        has_feedback = "[FEEDBACK]:" in content.upper()

        # Insert message
        cursor.execute(adapt_sql('''
            INSERT INTO messages (session_id, role, content, has_feedback)
            VALUES (?, ?, ?, ?)
        '''), (session_id, role, content, has_feedback))

        # Update session message count
        cursor.execute(adapt_sql('''
            UPDATE sessions
            SET message_count = message_count + 1, end_time = CURRENT_TIMESTAMP
            WHERE id = ?
        '''), (session_id,))

        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"Error saving message: {e}")
        return False

def get_chat_history(date_str=None, limit=50):
    """Get chat history for a specific date or recent messages"""
    try:
        conn = get_connection()
        cursor = conn.cursor()

        if date_str:
            if USE_POSTGRES:
                cursor.execute('''
                    SELECT m.timestamp, s.mode, m.role, m.content, m.has_feedback
                    FROM messages m
                    JOIN sessions s ON m.session_id = s.id
                    WHERE CAST(m.timestamp AS DATE) = %s
                    ORDER BY m.timestamp ASC
                ''', (date_str,))
            else:
                cursor.execute('''
                    SELECT m.timestamp, s.mode, m.role, m.content, m.has_feedback
                    FROM messages m
                    JOIN sessions s ON m.session_id = s.id
                    WHERE date(m.timestamp) = ?
                    ORDER BY m.timestamp ASC
                ''', (date_str,))
        else:
            # Get recent messages
            cursor.execute(adapt_sql('''
                SELECT m.timestamp, s.mode, m.role, m.content, m.has_feedback
                FROM messages m
                JOIN sessions s ON m.session_id = s.id
                ORDER BY m.timestamp DESC
                LIMIT ?
            '''), (limit,))

        messages = cursor.fetchall()
        conn.close()

        return [{
            "timestamp": str(msg[0]),
            "mode": msg[1],
            "role": msg[2],
            "content": msg[3],
            "has_feedback": bool(msg[4])
        } for msg in messages]

    except Exception as e:
        print(f"Error getting chat history: {e}")
        return []

def get_daily_stats(days=7):
    """Get daily message statistics"""
    try:
        conn = get_connection()
        cursor = conn.cursor()

        if USE_POSTGRES:
            cursor.execute('''
                SELECT
                    CAST(timestamp AS DATE) as date,
                    COUNT(*) as total_messages,
                    COUNT(CASE WHEN role = 'user' THEN 1 END) as user_messages,
                    COUNT(CASE WHEN role = 'assistant' THEN 1 END) as ai_messages,
                    COUNT(CASE WHEN has_feedback = TRUE THEN 1 END) as feedback_messages
                FROM messages
                WHERE timestamp >= CURRENT_DATE - INTERVAL '%s days'
                GROUP BY CAST(timestamp AS DATE)
                ORDER BY date DESC
            ''', (days,))
        else:
            cursor.execute('''
                SELECT
                    date(timestamp) as date,
                    COUNT(*) as total_messages,
                    COUNT(CASE WHEN role = 'user' THEN 1 END) as user_messages,
                    COUNT(CASE WHEN role = 'assistant' THEN 1 END) as ai_messages,
                    COUNT(CASE WHEN has_feedback = 1 THEN 1 END) as feedback_messages
                FROM messages
                WHERE timestamp >= date('now', '-{} days')
                GROUP BY date(timestamp)
                ORDER BY date DESC
            '''.format(days))

        stats = cursor.fetchall()
        conn.close()

        return [{
            "date": str(stat[0]),
            "total_messages": stat[1],
            "user_messages": stat[2],
            "ai_messages": stat[3],
            "feedback_messages": stat[4]
        } for stat in stats]

    except Exception as e:
        print(f"Error getting daily stats: {e}")
        return []

def save_telc_score(session_id, telc_part, score_data):
    """Save TELC scoring results to database"""
    conn = None
    try:
        conn = get_connection()
        if not USE_POSTGRES:
            conn.execute('PRAGMA journal_mode=WAL')  # Better concurrency (SQLite only)
        cursor = conn.cursor()

        # Convert lists to strings for database storage
        def list_to_string(data, default=""):
            if isinstance(data, list):
                return "\n".join([f"• {item}" for item in data if item])
            return str(data) if data else default

        strengths_str = list_to_string(score_data.get("strengths", []))
        weaknesses_str = list_to_string(score_data.get("weaknesses", []))
        recommendations_str = list_to_string(score_data.get("recommendations", []))

        print(f"💾 Saving TELC score - Teil: {telc_part}, Total: {score_data.get('total_score', 0)}")
        print(f"💾 Strengths type: {type(score_data.get('strengths'))}, Value: {score_data.get('strengths')}")

        cursor.execute(adapt_sql('''
            INSERT INTO telc_scores (
                session_id, telc_part, total_score, max_score,
                content_score, grammar_score, vocabulary_score,
                pronunciation_score, interaction_score, fluency_score,
                detailed_feedback, strengths, weaknesses, recommendations
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        '''), (
            session_id, telc_part, score_data["total_score"], score_data["max_score"],
            score_data.get("content_score", 0), score_data.get("grammar_score", 0),
            score_data.get("vocabulary_score", 0), score_data.get("pronunciation_score", 0),
            score_data.get("interaction_score", 0), score_data.get("fluency_score", 0),
            score_data.get("detailed_feedback", ""), strengths_str, weaknesses_str, recommendations_str
        ))

        # Update session with total score in notes field (safer)
        try:
            # First try to add notes column if it doesn't exist
            cursor.execute('ALTER TABLE sessions ADD COLUMN notes TEXT')
            conn.commit()
        except Exception:
            # Column already exists, ignore
            conn.rollback()

        try:
            cursor.execute(adapt_sql('''
                UPDATE sessions SET notes = ? WHERE id = ?
            '''), (f"TELC {telc_part}: {score_data['total_score']}/{score_data['max_score']} pts", session_id))
        except Exception as update_error:
            print(f"⚠️  Warning: Failed to update session notes: {update_error}")
            # Don't fail the entire save if session update fails

        conn.commit()
        print(f"✅ TELC score saved successfully!")
        return True

    except Exception as e:
        print(f"❌ Error saving TELC score: {e}")
        return False

    finally:
        # Ensure connection is closed
        if conn:
            try:
                conn.close()
            except:
                pass

def get_telc_scores(session_id=None, days=30):
    """Get TELC scoring history"""
    try:
        conn = get_connection()
        cursor = conn.cursor()

        if session_id:
            cursor.execute(adapt_sql('''
                SELECT * FROM telc_scores WHERE session_id = ? ORDER BY timestamp DESC
            '''), (session_id,))
        else:
            if USE_POSTGRES:
                cursor.execute('''
                    SELECT * FROM telc_scores
                    WHERE timestamp >= CURRENT_DATE - INTERVAL '%s days'
                    ORDER BY timestamp DESC
                ''', (days,))
            else:
                cursor.execute('''
                    SELECT * FROM telc_scores
                    WHERE timestamp >= date('now', '-{} days')
                    ORDER BY timestamp DESC
                '''.format(days))

        scores = cursor.fetchall()
        conn.close()

        def string_to_list(data):
            """Convert database string back to list"""
            if isinstance(data, str) and data:
                items = data.split('\n')
                return [item.replace('• ', '').strip() for item in items if item.strip()]
            return []

        return [{
            "id": score[0],
            "session_id": score[1],
            "telc_part": score[2],
            "total_score": score[3],
            "max_score": score[4],
            "content_score": score[5],
            "grammar_score": score[6],
            "vocabulary_score": score[7],
            "pronunciation_score": score[8],
            "interaction_score": score[9],
            "fluency_score": score[10],
            "detailed_feedback": score[11],
            "strengths": string_to_list(score[12]),
            "weaknesses": string_to_list(score[13]),
            "recommendations": string_to_list(score[14]),
            "timestamp": str(score[15])
        } for score in scores]

    except Exception as e:
        print(f"Error getting TELC scores: {e}")
        return []

def analyze_telc_performance(conversation_text, telc_part, api_key=""):
    print(f"🎯 Starting TELC analysis for {telc_part}")
    print(f"📝 Conversation length: {len(conversation_text)} chars")
    print(f"📝 Word count: {len(conversation_text.split())} words")

    try:
        # Define TELC B1 scoring criteria based on official standards
        telc_criteria = {
            "teil1": {
                "max_score": 15,
                "criteria": {
                    "introduction": {"max": 5, "desc": "Giới thiệu bản thân rõ ràng"},
                    "questions": {"max": 5, "desc": "Trả lời câu hỏi về cá nhân"},
                    "fluency": {"max": 5, "desc": "Độ trôi chảy trong giao tiếp"}
                }
            },
            "teil2": {
                "max_score": 30,
                "criteria": {
                    "content": {"max": 8, "desc": "Nội dung phù hợp và ý kiến rõ ràng"},
                    "grammar": {"max": 8, "desc": "Ngữ pháp và cấu trúc câu"},
                    "vocabulary": {"max": 7, "desc": "Từ vựng phong phú và chính xác"},
                    "pronunciation": {"max": 7, "desc": "Phát âm và tốc độ nói"}
                }
            },
            "teil3": {
                "max_score": 30,
                "criteria": {
                    "interaction": {"max": 8, "desc": "Tương tác và hợp tác tốt"},
                    "negotiation": {"max": 8, "desc": "Đàm phán và đưa ra đề xuất"},
                    "grammar": {"max": 7, "desc": "Ngữ pháp trong tình huống thực tế"},
                    "coherence": {"max": 7, "desc": "Mạch lạc và logic trong lập luận"}
                }
            }
        }

        # Get the specific part criteria
        part_criteria = telc_criteria.get(telc_part, telc_criteria["teil2"])

        # Create AI analysis prompt based on TELC standards
        analysis_prompt = f"""
Du bist ein zertifizierter TELC B1 Prüfer. Analysiere diese deutsche Konversation für {telc_part.upper()} und bewerte nach offiziellen TELC B1 Kriterien:

KONVERSATION:
{conversation_text}

BEWERTUNGSKRITERIEN für {telc_part.upper()}:
{chr(10).join([f"- {k}: {v['desc']} (max {v['max']} Punkte)" for k, v in part_criteria['criteria'].items()])}

Bewerte jedes Kriterium von 0 bis maximum Punkte und gib detailliertes Feedback auf Vietnamesisch:
1. Konkrete Stärken (was war gut?)
2. Schwächen (was muss verbessert werden?)
3. Spezifische Empfehlungen für Verbesserung
4. B1 Sprachniveau Einschätzung

Antworte im JSON Format mit Punkten und vietnamesischem Feedback.
"""

        # Use AI for analysis
        print("🤖 Calling AI for TELC analysis...")
        ai_response = call_ai(analysis_prompt, use_vietnamese=True, api_key=api_key)
        print(f"🤖 AI response length: {len(ai_response)} chars")
        print(f"🤖 AI response preview: {ai_response[:200]}...")

        # Parse AI response and create scoring structure
        try:
            # Try to extract JSON from AI response
            import re
            json_match = re.search(r'\{.*\}', ai_response, re.DOTALL)
            if json_match:
                ai_analysis = json.loads(json_match.group())
            else:
                # Fallback to creating structure from text
                ai_analysis = {"analysis": ai_response}
        except:
            ai_analysis = {"analysis": ai_response}

        # Calculate scores from AI analysis or use intelligent estimation
        individual_scores = {}
        total_score = 0

        for criterion, details in part_criteria['criteria'].items():
            # Try to extract score from AI analysis or estimate based on conversation quality
            if criterion in ai_analysis:
                # Direct criterion name (e.g., "introduction": 2)
                score = min(ai_analysis[criterion], details['max'])
                print(f"🎯 Found AI score for {criterion}: {score}/{details['max']}")
            elif f"{criterion}_score" in ai_analysis:
                # Alternative format with "_score" suffix
                score = min(ai_analysis[f"{criterion}_score"], details['max'])
                print(f"🎯 Found AI score for {criterion}_score: {score}/{details['max']}")
            else:
                # Intelligent estimation based on conversation length and content
                score = estimate_criterion_score(conversation_text, criterion, details['max'], telc_part)
                print(f"🔢 Estimated score for {criterion}: {score}/{details['max']}")

            individual_scores[f"{criterion}_score"] = score
            total_score += score

        print(f"📊 Final scoring - Individual: {individual_scores}, Total: {total_score}/{part_criteria['max_score']}")

        # Extract feedback from AI analysis
        strengths = ai_analysis.get('strengths', extract_strengths(ai_response))
        weaknesses = ai_analysis.get('weaknesses', extract_weaknesses(ai_response))
        recommendations = ai_analysis.get('recommendations', extract_recommendations(ai_response))

        # Create final score data structure
        score_data = {
            "total_score": total_score,
            "max_score": part_criteria['max_score'],
            "telc_part": telc_part,
            "percentage": round((total_score / part_criteria['max_score']) * 100, 1),
            "level_assessment": get_level_assessment(total_score, part_criteria['max_score']),
            "detailed_feedback": ai_response,
            "strengths": strengths,
            "weaknesses": weaknesses,
            "recommendations": recommendations,
            "criteria_breakdown": part_criteria['criteria'],
            **individual_scores
        }

        return score_data

    except Exception as e:
        print(f"❌ Error analyzing TELC performance: {e}")
        import traceback
        traceback.print_exc()

        # Enhanced fallback scoring based on conversation analysis
        word_count = len(conversation_text.split())
        sentence_count = len([s for s in conversation_text.split('.') if s.strip()])
        char_count = len(conversation_text.strip())

        # Analyze conversation content for basic quality indicators
        german_words = ['ich', 'bin', 'ist', 'sind', 'haben', 'komme', 'aus', 'wohne', 'heisse']
        german_word_count = sum(1 for word in conversation_text.lower().split() if word in german_words)

        # Simple heuristic scoring with more sophisticated analysis
        max_scores = {"teil1": 15, "teil2": 30, "teil3": 30}
        max_score = max_scores.get(telc_part, 30)

        # Base score with multiple factors
        length_score = min(max_score // 2, word_count // 5)  # Length factor
        german_score = min(max_score // 3, german_word_count)  # German vocabulary
        structure_score = min(max_score // 3, sentence_count)  # Sentence structure

        base_score = min(max_score, length_score + german_score + structure_score)

        # Enhanced criteria breakdown
        criteria_scores = {}
        detailed_strengths = []
        detailed_weaknesses = []
        detailed_recommendations = []

        if telc_part == "teil1":
            intro_score = min(5, 2 + (german_word_count // 2))
            questions_score = min(5, 1 + (sentence_count // 2))
            fluency_score = min(5, max(1, word_count // 10))

            criteria_scores = {
                "introduction_score": intro_score,
                "questions_score": questions_score,
                "fluency_score": fluency_score
            }

            # Specific feedback for Teil 1
            if intro_score >= 3:
                detailed_strengths.append("Giới thiệu bản thân rõ ràng")
            else:
                detailed_weaknesses.append("Giới thiệu bản thân còn ngắn")

            if word_count >= 30:
                detailed_strengths.append(f"Sử dụng {word_count} từ - đủ dài")
            else:
                detailed_weaknesses.append("Cần trả lời dài hơn")

            detailed_recommendations.extend([
                "Luyện tập giới thiệu: 'Ich heiße..., ich komme aus..., ich wohne in...'",
                "Kể thêm về gia đình, công việc, sở thích"
            ])

        elif telc_part == "teil2":
            content_score = min(8, 2 + (word_count // 8))
            grammar_score = min(8, 2 + (german_word_count // 2))
            vocabulary_score = min(7, 2 + (word_count // 12))
            pronunciation_score = min(7, max(2, sentence_count))

            criteria_scores = {
                "content_score": content_score,
                "grammar_score": grammar_score,
                "vocabulary_score": vocabulary_score,
                "pronunciation_score": pronunciation_score
            }

            detailed_strengths.append("Có ý kiến về chủ đề")
            if word_count >= 50:
                detailed_strengths.append("Trình bày đủ chi tiết")

            detailed_weaknesses.extend([
                "Cần sử dụng thêm từ nối: deshalb, trotzdem, obwohl",
                "Cần đưa ra ví dụ cụ thể"
            ])

            detailed_recommendations.extend([
                "Luyện tập cấu trúc: 'Ich bin der Meinung, dass...'",
                "Sử dụng thêm từ nối để liên kết ý tưởng"
            ])

        else:  # teil3
            interaction_score = min(8, 2 + (sentence_count // 2))
            negotiation_score = min(8, 2 + (word_count // 10))
            grammar_score = min(7, 2 + (german_word_count // 2))
            coherence_score = min(7, max(2, sentence_count // 2))

            criteria_scores = {
                "interaction_score": interaction_score,
                "negotiation_score": negotiation_score,
                "grammar_score": grammar_score,
                "coherence_score": coherence_score
            }

            detailed_strengths.append("Tham gia lập kế hoạch")
            detailed_weaknesses.append("Cần đưa ra nhiều đề xuất hơn")
            detailed_recommendations.extend([
                "Luyện tập: 'Wie wäre es, wenn wir...'",
                "Sử dụng: 'Sollen wir...?', 'Was hältst du von...?'"
            ])

        # Add general analysis
        if word_count >= 20:
            detailed_strengths.append(f"Cuộc trò chuyện có độ dài phù hợp ({word_count} từ)")
        if german_word_count >= 5:
            detailed_strengths.append("Sử dụng từ vựng tiếng Đức cơ bản tốt")

        if not detailed_weaknesses:
            detailed_weaknesses.append("Cần AI analysis để đánh giá chính xác hơn")

        # Return enhanced fallback scoring
        return {
            "total_score": base_score,
            "max_score": max_score,
            "telc_part": telc_part,
            "percentage": round((base_score / max_score) * 100, 1),
            "level_assessment": get_level_assessment(base_score, max_score),
            "detailed_feedback": f"📊 Phân tích cơ bản:\n• {word_count} từ, {sentence_count} câu\n• {german_word_count} từ tiếng Đức cơ bản\n• Điểm ước tính: {base_score}/{max_score}\n\n⚠️ Lưu ý: Đây là phân tích cơ bản. Để có đánh giá chính xác, cần API key OpenRouter hợp lệ.",
            "strengths": detailed_strengths,
            "weaknesses": detailed_weaknesses,
            "recommendations": detailed_recommendations,
            "criteria_breakdown": telc_criteria[telc_part]['criteria'],
            **criteria_scores
        }

def estimate_criterion_score(conversation_text, criterion, max_score, telc_part):
    """Estimate score for a criterion based on conversation analysis"""
    text_length = len(conversation_text.strip())
    word_count = len(conversation_text.split())

    # Basic scoring based on content quality indicators
    if text_length < 50:
        return max(1, max_score // 4)  # Very short responses
    elif text_length < 150:
        return max(2, max_score // 2)  # Short responses
    elif text_length < 300:
        return max(3, max_score * 3 // 4)  # Good length responses
    else:
        return max_score - 1  # Comprehensive responses (leave room for perfection)

def extract_strengths(ai_response):
    """Extract strengths from AI response text"""
    strengths = []
    lines = ai_response.split('\n')
    in_strengths = False

    for line in lines:
        line = line.strip()
        if any(word in line.lower() for word in ['stärken', 'strengths', 'điểm mạnh', 'tốt']):
            in_strengths = True
            continue
        elif any(word in line.lower() for word in ['schwächen', 'weaknesses', 'điểm yếu', 'cần cải thiện']):
            in_strengths = False
        elif in_strengths and line and not line.startswith('{'):
            strengths.append(line.lstrip('- ').lstrip('* '))

    return strengths[:3] if strengths else ["Giao tiếp được cơ bản"]

def extract_weaknesses(ai_response):
    """Extract weaknesses from AI response text"""
    weaknesses = []
    lines = ai_response.split('\n')
    in_weaknesses = False

    for line in lines:
        line = line.strip()
        if any(word in line.lower() for word in ['schwächen', 'weaknesses', 'điểm yếu', 'cần cải thiện']):
            in_weaknesses = True
            continue
        elif any(word in line.lower() for word in ['empfehlung', 'recommendations', 'khuyến nghị', 'đề xuất']):
            in_weaknesses = False
        elif in_weaknesses and line and not line.startswith('{'):
            weaknesses.append(line.lstrip('- ').lstrip('* '))

    return weaknesses[:3] if weaknesses else ["Cần thực hành thêm để cải thiện"]

def extract_recommendations(ai_response):
    """Extract recommendations from AI response text"""
    recommendations = []
    lines = ai_response.split('\n')
    in_recommendations = False

    for line in lines:
        line = line.strip()
        if any(word in line.lower() for word in ['empfehlung', 'recommendations', 'khuyến nghị', 'đề xuất']):
            in_recommendations = True
            continue
        elif in_recommendations and line and not line.startswith('{'):
            recommendations.append(line.lstrip('- ').lstrip('* '))

    return recommendations[:3] if recommendations else ["Tiếp tục luyện tập hàng ngày"]

def call_ai(prompt, use_vietnamese=False, api_key="dummy"):
    """Call AI API for analysis - simplified version for scoring"""
    try:
        import urllib.request
        import urllib.parse
        import json

        # Free models on OpenRouter (March 2026)
        models = [
            "openrouter/free",
            "meta-llama/llama-3.3-70b-instruct:free",
            "mistralai/mistral-small-3.1-24b-instruct:free",
            "google/gemma-3-27b-it:free",
            "google/gemma-3-12b-it:free",
            "qwen/qwen3-next-80b-a3b-instruct:free",
            "nvidia/nemotron-3-super-120b-a12b:free",
            "nvidia/nemotron-3-nano-30b-a3b:free",
            "stepfun/step-3.5-flash:free",
            "openai/gpt-oss-120b:free",
            "openai/gpt-oss-20b:free",
            "nousresearch/hermes-3-llama-3.1-405b:free",
            "minimax/minimax-m2.5:free",
            "cognitivecomputations/dolphin-mistral-24b-venice-edition:free",
        ]

        system_prompt = "Du bist ein erfahrener TELC B1 Prüfer. Antworte auf Vietnamesisch mit detaillierter Bewertung." if use_vietnamese else "You are a professional TELC B1 examiner."

        for model in models:
            try:
                or_body = json.dumps({
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": prompt}
                    ],
                    "max_tokens": 800,
                    "temperature": 0.7,
                }).encode()

                req = urllib.request.Request(
                    "https://openrouter.ai/api/v1/chat/completions",
                    data=or_body,
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {api_key}",
                        "HTTP-Referer": "http://localhost:9999",
                    },
                    method="POST",
                )

                with urllib.request.urlopen(req, timeout=15) as resp:
                    response = json.loads(resp.read().decode())
                    if "choices" in response and response["choices"]:
                        content = response["choices"][0]["message"]["content"]
                        print(f"✅ AI call successful with model: {model}")
                        return content

            except Exception as e:
                print(f"❌ Model {model} failed: {e}")
                continue

        # If all models fail, return a fallback
        print("❌ All AI models failed, using fallback analysis")
        return "Phân tích AI không khả dụng. Sử dụng đánh giá cơ bản dựa trên độ dài và cấu trúc câu."

    except Exception as e:
        print(f"❌ AI call error: {e}")
        return f"Lỗi gọi AI: {str(e)}"

def get_level_assessment(score, max_score):
    """Get B1 level assessment based on score percentage"""
    percentage = (score / max_score) * 100

    if percentage >= 85:
        return "Xuất sắc - Đạt B1+ mạnh"
    elif percentage >= 75:
        return "Tốt - Đạt B1 vững"
    elif percentage >= 65:
        return "Khá - Đạt B1 cơ bản"
    elif percentage >= 50:
        return "Trung bình - Gần đạt B1"
    else:
        return "Cần cải thiện - Chưa đạt B1"

def start_ngrok(port):
    """Start ngrok tunnel and return public URL"""
    try:
        # Check if ngrok is installed
        result = subprocess.run(['ngrok', 'version'], capture_output=True, text=True, timeout=5)
        if result.returncode != 0:
            print("❌ Ngrok not found. Install from: https://ngrok.com/download")
            return None
    except (subprocess.TimeoutExpired, FileNotFoundError):
        print("❌ Ngrok not found. Install from: https://ngrok.com/download")
        return None

    try:
        print("🚀 Starting ngrok tunnel...")
        # Start ngrok in background
        process = subprocess.Popen(
            ['ngrok', 'http', str(port), '--log', '/dev/null'],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )

        # Wait a bit for ngrok to start
        time.sleep(3)

        # Get public URL from ngrok API
        try:
            import urllib.request, json
            response = urllib.request.urlopen('http://127.0.0.1:4040/api/tunnels', timeout=10)
            data = json.loads(response.read().decode())

            for tunnel in data['tunnels']:
                if tunnel['config']['addr'] == f'http://localhost:{port}':
                    public_url = tunnel['public_url']
                    print(f"✅ Ngrok tunnel ready: {public_url}")
                    return public_url, process
        except Exception as e:
            print(f"⚠️  Ngrok started but couldn't get URL: {e}")
            print("   Check manually at: http://localhost:4040")
            return None, process

    except Exception as e:
        print(f"❌ Failed to start ngrok: {e}")
        return None

    return None

HTML = r"""<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Deutsch B1 Trainer 🇩🇪</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;600;700&family=IBM+Plex+Mono:wght@500&display=swap');
:root{--bg:#07090f;--bdr:rgba(255,255,255,0.09);--txt:#e2e8f0;--mut:#475569;}
*{box-sizing:border-box;margin:0;padding:0;}
body{background:var(--bg);color:var(--txt);font-family:'IBM Plex Sans',sans-serif;min-height:100vh;display:flex;flex-direction:column;}
/* API SCREEN */
#apiScreen{flex:1;display:flex;flex-direction:column;align-items:center;justify-content:center;padding:32px;gap:18px;text-align:center;}
#apiScreen h1{font-size:clamp(26px,5vw,44px);font-weight:700;letter-spacing:-1.5px;}
#apiScreen h1 span{color:#3b82f6;}
.hint{background:rgba(59,130,246,0.08);border:1px solid rgba(59,130,246,0.22);border-radius:12px;padding:14px 18px;max-width:460px;font-size:13px;color:#93c5fd;line-height:1.75;text-align:left;}
.hint code{background:rgba(255,255,255,0.1);padding:2px 6px;border-radius:4px;font-family:'IBM Plex Mono',monospace;font-size:12px;}
.hint a{color:#60a5fa;}
#apiKeyInput{width:100%;max-width:460px;padding:12px 16px;background:rgba(255,255,255,0.07);border:1px solid rgba(255,255,255,0.15);border-radius:12px;color:#fff;font-size:15px;font-family:'IBM Plex Mono',monospace;outline:none;transition:border .2s;}
#apiKeyInput:focus{border-color:#3b82f666;}
#apiKeyInput::placeholder{color:#334155;}
#startBtn{width:100%;max-width:460px;padding:13px;background:linear-gradient(135deg,#3b82f6,#2563eb);border:none;border-radius:12px;color:#fff;font-size:15px;font-weight:700;cursor:pointer;font-family:inherit;transition:all .2s;}
#startBtn:hover{transform:translateY(-2px);box-shadow:0 8px 24px #3b82f644;}
#apiErr{color:#f87171;font-size:13px;min-height:18px;}
/* APP */
#app{flex:1;display:none;flex-direction:column;}
/* Landing */
#landing{flex:1;display:flex;flex-direction:column;align-items:center;justify-content:center;padding:32px;gap:14px;}
#landing h1{font-size:clamp(26px,5vw,44px);font-weight:700;letter-spacing:-1.5px;}
#landing h1 span{color:#3b82f6;}
.mode-btn{width:100%;max-width:460px;padding:20px 24px;background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.08);border-radius:16px;cursor:pointer;text-align:left;color:#fff;font-family:inherit;transition:all .22s;display:flex;align-items:center;gap:14px;}
.mode-btn:hover{transform:translateY(-3px);}
.mode-btn .lbl{font-size:16px;font-weight:700;}.mode-btn .dsc{font-size:12px;color:var(--mut);margin-top:2px;}
/* Chat */
#chat{flex:1;display:none;flex-direction:column;}
#chatHeader{padding:11px 18px;display:flex;align-items:center;justify-content:space-between;background:rgba(7,9,15,0.97);border-bottom:1px solid var(--bdr);position:sticky;top:0;z-index:20;}
#backBtn,#historyBtn,#scoreBtn{background:rgba(255,255,255,0.06);border:1px solid var(--bdr);color:var(--mut);border-radius:8px;padding:5px 12px;cursor:pointer;font-size:13px;font-family:inherit;margin-right:8px;}
#historyBtn:hover,#backBtn:hover,#scoreBtn:hover{background:rgba(255,255,255,0.1);}
#scoreBtn{background:rgba(251,191,36,0.1);border-color:rgba(251,191,36,0.3);color:#fbbf24;}
#modeTitle{font-weight:700;font-size:15px;}#turnCount{font-size:11px;color:#334155;}
#telcTimer{font-size:13px;color:#34d399;margin-top:2px;font-weight:600;}
#telcTimer.warning{color:#fbbf24;animation:pulse 1s infinite;}
#telcTimer.danger{color:#f87171;animation:pulse 0.5s infinite;}
@keyframes pulse{0%,100%{opacity:1;}50%{opacity:0.6;}}
#ttsToggle,#vnToggle{border-radius:20px;padding:5px 14px;cursor:pointer;font-size:12px;font-weight:700;font-family:inherit;border:1px solid;transition:all .2s;}
/* History Panel */
#historyPanel{position:fixed;top:0;right:-400px;width:400px;height:100vh;background:rgba(7,9,15,0.98);border-left:1px solid var(--bdr);transition:right 0.3s ease;z-index:30;display:flex;flex-direction:column;}
#historyPanel.open{right:0;}
#historyHeader{padding:16px;border-bottom:1px solid var(--bdr);display:flex;align-items:center;justify-content:space-between;}
#historyTitle{font-weight:700;font-size:16px;}
#closeHistoryBtn{background:rgba(255,255,255,0.06);border:1px solid var(--bdr);color:var(--mut);border-radius:8px;padding:4px 8px;cursor:pointer;font-size:12px;}
#historyControls{padding:12px 16px;border-bottom:1px solid var(--bdr);}
#historyDatePicker{background:rgba(255,255,255,0.07);border:1px solid var(--bdr);border-radius:8px;color:#fff;padding:6px 10px;font-size:13px;width:100%;margin-bottom:8px;}
#historyStats{font-size:11px;color:#64748b;}
#historyContent{flex:1;overflow-y:auto;padding:12px 16px;}
.history-day{margin-bottom:20px;}
.history-day-header{font-weight:600;color:#3b82f6;font-size:13px;margin-bottom:8px;padding:4px 0;border-bottom:1px solid rgba(59,130,246,0.2);}
.history-message{margin-bottom:8px;padding:8px 12px;border-radius:12px;font-size:13px;line-height:1.5;}
.history-message.user{background:rgba(59,130,246,0.1);border:1px solid rgba(59,130,246,0.2);margin-left:20px;}
.history-message.assistant{background:rgba(255,255,255,0.05);border:1px solid var(--bdr);}
.history-message .timestamp{font-size:10px;color:#64748b;margin-bottom:4px;}
.history-message .content{color:#e2e8f0;}
.history-feedback{background:rgba(16,185,129,0.1);border:1px solid rgba(16,185,129,0.2);border-radius:8px;padding:6px 10px;margin-top:4px;font-size:11px;color:#6ee7b7;}

/* Scoring Panel */
#scoringPanel{position:fixed;top:0;left:-420px;width:420px;height:100vh;background:rgba(7,9,15,0.98);border-right:1px solid var(--bdr);transition:left 0.3s ease;z-index:30;display:flex;flex-direction:column;}
#scoringPanel.open{left:0;}
#scoringHeader{padding:16px;border-bottom:1px solid var(--bdr);display:flex;align-items:center;justify-content:space-between;}
#scoringTitle{font-weight:700;font-size:16px;color:#fbbf24;}
#closeScoringBtn{background:rgba(255,255,255,0.06);border:1px solid var(--bdr);color:var(--mut);border-radius:8px;padding:4px 8px;cursor:pointer;font-size:12px;}
#scoringContent{flex:1;overflow-y:auto;padding:16px;}
.scoring-loading{text-align:center;color:#64748b;margin:40px 0;line-height:1.6;}
.score-section{margin-bottom:24px;padding:16px;background:rgba(251,191,36,0.05);border:1px solid rgba(251,191,36,0.2);border-radius:12px;}
.score-header{font-weight:600;font-size:15px;color:#fbbf24;margin-bottom:12px;display:flex;align-items:center;justify-content:space-between;}
.score-total{font-size:24px;font-weight:700;color:#fbbf24;}
.score-breakdown{margin-top:12px;}

/* Enhanced Scoring Results */
.scoring-results{padding:8px;}
.total-score{display:flex;align-items:center;gap:20px;margin-bottom:24px;padding:20px;background:rgba(59,130,246,0.1);border:1px solid rgba(59,130,246,0.3);border-radius:16px;}
.score-circle{display:flex;align-items:baseline;gap:4px;}
.score-number{font-size:36px;font-weight:800;color:#60a5fa;}
.score-max{font-size:20px;color:#94a3b8;font-weight:600;}
.score-details{flex:1;}
.score-percentage{font-size:20px;font-weight:700;color:#fbbf24;}
.score-level{font-size:14px;color:#34d399;font-weight:600;margin-top:4px;}
.score-part{font-size:12px;color:#64748b;text-transform:uppercase;margin-top:2px;}

.criteria-section{margin-bottom:24px;}
.criteria-section h3{color:#fbbf24;font-size:16px;margin-bottom:16px;font-weight:600;}

.score-item{display:flex;flex-direction:column;gap:8px;padding:12px 0;border-bottom:1px solid rgba(255,255,255,0.1);}
.score-item:last-child{border-bottom:none;}
.score-label{font-size:13px;color:#e2e8f0;font-weight:500;}
.score-bar-container{display:flex;align-items:center;gap:12px;}
.score-bar{height:8px;background:linear-gradient(90deg, #34d399, #fbbf24, #f87171);border-radius:4px;transition:width 0.3s ease;}
.score-text{font-size:13px;font-weight:600;color:#60a5fa;min-width:40px;}

.feedback-section{margin-bottom:20px;padding:16px;border-radius:12px;}
.feedback-section.strengths{background:rgba(16,185,129,0.1);border:1px solid rgba(16,185,129,0.2);}
.feedback-section.weaknesses{background:rgba(239,68,68,0.1);border:1px solid rgba(239,68,68,0.2);}
.feedback-section.recommendations{background:rgba(251,191,36,0.1);border:1px solid rgba(251,191,36,0.2);}
.feedback-section h3{margin:0 0 12px 0;font-size:14px;font-weight:600;}
.feedback-section.strengths h3{color:#34d399;}
.feedback-section.weaknesses h3{color:#fca5a5;}
.feedback-section.recommendations h3{color:#fbbf24;}
.feedback-section ul{margin:0;padding-left:20px;}
.feedback-section li{margin-bottom:6px;line-height:1.5;font-size:13px;}
.feedback-section.strengths li{color:#6ee7b7;}
.feedback-section.weaknesses li{color:#fca5a5;}
.feedback-section.recommendations li{color:#fde68a;}

.ai-analysis{margin-bottom:24px;padding:16px;background:rgba(99,102,241,0.1);border:1px solid rgba(99,102,241,0.2);border-radius:12px;}
.ai-analysis h3{color:#a5b4fc;margin:0 0 12px 0;font-size:14px;font-weight:600;}
.analysis-text{font-size:12px;color:#cbd5e1;line-height:1.6;}

.scoring-actions{display:flex;gap:12px;padding-top:16px;border-top:1px solid rgba(255,255,255,0.1);}
.btn-primary{background:linear-gradient(135deg, #3b82f6, #1d4ed8);border:none;color:white;padding:10px 20px;border-radius:8px;font-size:13px;font-weight:600;cursor:pointer;flex:1;}
.btn-secondary{background:rgba(255,255,255,0.06);border:1px solid rgba(255,255,255,0.2);color:#cbd5e1;padding:10px 20px;border-radius:8px;font-size:13px;font-weight:600;cursor:pointer;flex:1;}
.btn-primary:hover{transform:translateY(-1px);}
.btn-secondary:hover{background:rgba(255,255,255,0.1);}

/* TELC Timer and Time Up Panels */
.time-warning{animation:slideIn 0.3s ease-out;}
.time-up-panel{animation:slideIn 0.5s ease-out;}
.time-up-panel button{font-family:inherit;transition:all 0.2s;cursor:pointer;}
.time-up-panel button:hover{transform:translateY(-1px);opacity:0.9;}

@keyframes slideIn{
  from{opacity:0;transform:translateY(20px);}
  to{opacity:1;transform:translateY(0);}
}

@media (max-width: 768px) {
  .time-up-panel div[style*="display:flex"] {
    flex-direction: column;
    gap: 8px !important;
  }
  .time-up-panel button {
    width: 100%;
    padding: 8px 12px;
  }
}

/* Demo Exam Mode */
#demoExam{display:none;flex-direction:column;height:100vh;background:#0f172a;position:relative;}
#demoHeader{position:sticky;top:0;z-index:10;background:rgba(15,23,42,0.95);backdrop-filter:blur(8px);padding:12px 16px;border-bottom:1px solid rgba(245,158,11,0.2);}
#demoHeader .demo-title{font-size:16px;font-weight:700;color:#fbbf24;text-align:center;}
#demoHeader .demo-legend{display:flex;justify-content:center;gap:16px;margin-top:6px;font-size:11px;color:#94a3b8;}
#demoHeader .demo-legend span{display:flex;align-items:center;gap:4px;}
.demo-teil-nav{display:flex;gap:6px;justify-content:center;margin-top:8px;}
.demo-teil-btn{padding:6px 14px;border-radius:8px;border:1px solid rgba(245,158,11,0.3);background:rgba(245,158,11,0.08);color:#fbbf24;font-size:12px;font-weight:600;cursor:pointer;transition:all 0.2s;}
.demo-teil-btn:hover{background:rgba(245,158,11,0.15);}
.demo-teil-btn.active{background:rgba(245,158,11,0.25);border-color:#f59e0b;box-shadow:0 0 8px rgba(245,158,11,0.2);}
#demoMessages{flex:1;overflow-y:auto;padding:16px;display:flex;flex-direction:column;gap:12px;}
.demo-teil-separator{text-align:center;padding:16px 0 8px;font-size:14px;font-weight:700;color:#fbbf24;border-top:1px solid rgba(245,158,11,0.15);margin-top:8px;}
.demo-teil-separator .teil-desc{font-size:11px;color:#94a3b8;font-weight:400;margin-top:2px;}
.demo-wrap{display:flex;flex-direction:column;animation:slideIn 0.3s ease-out;}
.demo-wrap.prufer{align-items:center;}
.demo-wrap.kandidatA{align-items:flex-start;}
.demo-wrap.kandidatB{align-items:flex-end;}
.demo-row{display:flex;align-items:flex-start;gap:8px;max-width:85%;}
.demo-wrap.kandidatB .demo-row{flex-direction:row-reverse;}
.demo-speaker-tag{font-size:10px;font-weight:700;letter-spacing:0.5px;margin-bottom:2px;padding:0 4px;}
.demo-speaker-tag.prufer{color:#f59e0b;}
.demo-speaker-tag.kandidatA{color:#3b82f6;}
.demo-speaker-tag.kandidatB{color:#10b981;text-align:right;}
.demo-bub{padding:10px 14px;border-radius:12px;font-size:13px;line-height:1.6;max-width:100%;position:relative;}
.demo-bub.prufer{background:rgba(245,158,11,0.12);border:1px solid rgba(245,158,11,0.25);color:#fde68a;}
.demo-bub.kandidatA{background:rgba(59,130,246,0.12);border:1px solid rgba(59,130,246,0.25);color:#93c5fd;border-bottom-left-radius:4px;}
.demo-bub.kandidatB{background:rgba(16,185,129,0.12);border:1px solid rgba(16,185,129,0.25);color:#6ee7b7;border-bottom-right-radius:4px;}
.demo-bub .demo-tts-btn{position:absolute;top:4px;right:4px;background:none;border:none;cursor:pointer;font-size:12px;opacity:0.5;padding:2px 4px;}
.demo-bub .demo-tts-btn:hover{opacity:1;}
.demo-vn{font-size:11px;line-height:1.5;margin-top:4px;padding:4px 8px;border-radius:6px;font-style:italic;max-width:85%;}
.demo-wrap.prufer .demo-vn{color:rgba(245,158,11,0.6);background:rgba(245,158,11,0.05);}
.demo-wrap.kandidatA .demo-vn{color:rgba(59,130,246,0.6);background:rgba(59,130,246,0.05);}
.demo-wrap.kandidatB .demo-vn{color:rgba(16,185,129,0.6);background:rgba(16,185,129,0.05);text-align:right;align-self:flex-end;}
.demo-tip{font-size:11px;color:#fbbf24;background:rgba(245,158,11,0.08);border:1px solid rgba(245,158,11,0.15);border-radius:6px;padding:6px 10px;margin-top:4px;max-width:85%;}
.demo-tip::before{content:"💡 ";}
#demoControls{display:flex;align-items:center;gap:8px;padding:10px 16px;background:rgba(15,23,42,0.95);border-top:1px solid rgba(245,158,11,0.2);flex-wrap:wrap;justify-content:center;}
#demoControls button{padding:6px 12px;border-radius:8px;border:1px solid rgba(245,158,11,0.3);background:rgba(245,158,11,0.1);color:#fbbf24;font-size:12px;cursor:pointer;transition:all 0.2s;}
#demoControls button:hover{background:rgba(245,158,11,0.2);}
#demoControls button.active{background:rgba(245,158,11,0.3);border-color:#f59e0b;}
#demoProgress{font-size:11px;color:#94a3b8;}
@media (max-width: 768px) {
  .demo-row{max-width:95%;}
  .demo-vn,.demo-tip{max-width:95%;}
  #demoControls{gap:4px;padding:8px 10px;}
  #demoControls button{padding:4px 8px;font-size:11px;}
}

/* Embassy demo speaker styles */
.demo-wrap.beamter{align-items:flex-start;}
.demo-wrap.antragsteller{align-items:flex-end;}
.demo-speaker-tag.beamter{color:#a855f7;}
.demo-speaker-tag.antragsteller{color:#22c55e;text-align:right;}
.demo-bub.beamter{background:rgba(168,85,247,0.12);border:1px solid rgba(168,85,247,0.25);color:#d8b4fe;border-bottom-left-radius:4px;}
.demo-bub.antragsteller{background:rgba(34,197,94,0.12);border:1px solid rgba(34,197,94,0.25);color:#86efac;border-bottom-right-radius:4px;}
.demo-wrap.antragsteller .demo-row{flex-direction:row-reverse;}
.demo-wrap.beamter .demo-vn{color:rgba(168,85,247,0.6);background:rgba(168,85,247,0.05);}
.demo-wrap.antragsteller .demo-vn{color:rgba(34,197,94,0.6);background:rgba(34,197,94,0.05);text-align:right;align-self:flex-end;}

.score-value{font-size:14px;font-weight:600;color:#fbbf24;}
.score-feedback{margin-top:16px;padding:12px;background:rgba(16,185,129,0.1);border:1px solid rgba(16,185,129,0.2);border-radius:8px;}
.feedback-title{font-size:13px;font-weight:600;color:#34d399;margin-bottom:4px;}
.feedback-content{font-size:12px;color:#6ee7b7;line-height:1.5;}
@media (max-width: 768px){#historyPanel,#scoringPanel{width:100%;right:-100%;left:-100%;}}

/* Phrase Bank Panel */
#phraseBankPanel{position:fixed;top:0;right:-400px;width:400px;height:100vh;background:rgba(7,9,15,0.98);border-left:1px solid rgba(167,139,250,0.2);transition:right 0.3s ease;z-index:30;display:flex;flex-direction:column;overflow-y:auto;}
#phraseBankPanel.open{right:0;}
#phraseBankHeader{padding:16px;border-bottom:1px solid rgba(167,139,250,0.15);display:flex;justify-content:space-between;align-items:center;}
#phraseBankHeader .pb-title{font-size:15px;font-weight:700;color:#a78bfa;}
#phraseBankHeader .pb-close{background:none;border:1px solid rgba(167,139,250,0.3);color:#a78bfa;border-radius:6px;padding:4px 10px;cursor:pointer;font-size:14px;}
#phraseBankContent{padding:12px;flex:1;overflow-y:auto;}
.phrase-category{margin-bottom:16px;}
.phrase-category-title{font-size:12px;font-weight:700;color:#a78bfa;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:8px;padding-bottom:4px;border-bottom:1px solid rgba(167,139,250,0.15);}
.phrase-item{padding:8px 10px;margin-bottom:4px;border-radius:8px;cursor:pointer;border:1px solid rgba(167,139,250,0.1);transition:all 0.15s ease;}
.phrase-item:hover{background:rgba(167,139,250,0.12);border-color:rgba(167,139,250,0.3);}
.phrase-item .phrase-de{font-size:13px;color:#c4b5fd;font-weight:500;}
.phrase-item .phrase-vn{font-size:11px;color:#64748b;margin-top:2px;}
@media (max-width: 768px){#phraseBankPanel{width:100%;right:-100%;}}

/* B1 Structure Analysis */
.b1-structures{margin-top:16px;padding:12px;background:rgba(167,139,250,0.06);border:1px solid rgba(167,139,250,0.15);border-radius:10px;}
.b1-structures h3{font-size:14px;color:#a78bfa;margin-bottom:12px;}
.structure-category{margin-bottom:14px;}
.structure-category-label{font-size:12px;font-weight:700;color:#c4b5fd;margin-bottom:6px;}
.structure-item{display:flex;align-items:flex-start;gap:6px;padding:4px 0;font-size:12px;}
.structure-item.used{color:#34d399;}
.structure-item.missed{color:#f87171;}
.structure-item .structure-example{font-size:11px;color:#64748b;font-style:italic;margin-left:20px;}

/* Partner Mode bubbles in chat */
.partner-wrap{display:flex;flex-direction:column;margin-bottom:16px;animation:fadeUp 0.3s ease both;}
.partner-wrap.prufer{align-items:center;}
.partner-wrap.kandidatB{align-items:flex-start;}
.partner-speaker-tag{font-size:10px;font-weight:700;letter-spacing:0.5px;margin-bottom:2px;padding:0 4px;}
.partner-speaker-tag.prufer{color:#f59e0b;}
.partner-speaker-tag.kandidatB{color:#10b981;}
.partner-bub{padding:10px 14px;border-radius:12px;font-size:13.5px;line-height:1.65;max-width:76%;position:relative;}
.partner-bub.prufer{background:rgba(245,158,11,0.1);border:1px solid rgba(245,158,11,0.25);color:#fde68a;border-radius:12px;}
.partner-bub.kandidatB{background:rgba(16,185,129,0.1);border:1px solid rgba(16,185,129,0.25);color:#6ee7b7;border-bottom-left-radius:4px;}
.partner-bub .partner-spk-btn{position:absolute;top:4px;right:4px;background:none;border:none;cursor:pointer;font-size:12px;opacity:0.5;padding:2px 4px;}
.partner-bub .partner-spk-btn:hover{opacity:1;}

/* Simulation Mode */
.sim-progress{display:flex;gap:8px;padding:8px 16px;justify-content:center;align-items:center;border-bottom:1px solid rgba(255,255,255,0.06);}
.sim-step{padding:6px 14px;border-radius:16px;font-size:12px;font-weight:600;border:1px solid rgba(255,255,255,0.1);color:#64748b;transition:all 0.3s ease;}
.sim-step.active{background:rgba(59,130,246,0.15);border-color:rgba(59,130,246,0.4);color:#60a5fa;}
.sim-step.done{background:rgba(34,197,94,0.15);border-color:rgba(34,197,94,0.4);color:#34d399;}
.sim-step-arrow{color:#334155;font-size:14px;}
.sim-separator{text-align:center;padding:16px;margin:8px 16px;border:1px dashed rgba(255,255,255,0.1);border-radius:10px;color:#94a3b8;font-size:13px;font-weight:600;}

/* Combined Scoring */
.combined-score-circle{width:100px;height:100px;border-radius:50%;display:flex;flex-direction:column;align-items:center;justify-content:center;margin:0 auto 12px;}
.combined-score-circle.pass{background:rgba(34,197,94,0.15);border:3px solid #34d399;}
.combined-score-circle.fail{background:rgba(239,68,68,0.15);border:3px solid #f87171;}
.combined-teil-bar{display:flex;align-items:center;gap:8px;padding:6px 0;}
.combined-teil-label{font-size:12px;color:#94a3b8;width:50px;}
.combined-teil-fill{height:8px;border-radius:4px;transition:width 0.5s ease;}

.topic-picker{padding:12px 16px;width:100%;box-sizing:border-box;}
.topic-picker-label{font-size:13px;color:#94a3b8;margin-bottom:8px;display:flex;align-items:center;gap:8px;}
.topic-picker-back{background:none;border:none;color:#60a5fa;cursor:pointer;font-size:16px;padding:0 4px;font-family:inherit;}
.topic-picker-back:hover{color:#93c5fd;}
.topic-picker textarea{width:100%;min-height:60px;background:rgba(255,255,255,0.06);border:1px solid rgba(255,255,255,0.12);border-radius:10px;color:#e2e8f0;padding:10px 12px;font-size:13px;font-family:inherit;resize:vertical;line-height:1.5;}
.topic-picker textarea::placeholder{color:#4b5563;}
.topic-picker textarea:focus{outline:none;border-color:rgba(59,130,246,0.5);}
.topic-picker-buttons{display:flex;gap:8px;margin-top:10px;}
.topic-picker-buttons button{flex:1;padding:8px 12px;border-radius:10px;font-size:13px;font-weight:600;cursor:pointer;font-family:inherit;border:1px solid;transition:all .2s;}
.tp-random{background:rgba(251,191,36,0.1);border-color:rgba(251,191,36,0.3);color:#fbbf24;}
.tp-random:hover{background:rgba(251,191,36,0.18);}
.tp-start{background:rgba(16,185,129,0.1);border-color:rgba(16,185,129,0.3);color:#34d399;}
.tp-start:hover{background:rgba(16,185,129,0.18);}
#topics{padding:8px 14px;display:flex;gap:7px;overflow-x:auto;border-bottom:1px solid rgba(255,255,255,0.04);scrollbar-width:none;}
#topics::-webkit-scrollbar{display:none;}
.topic-btn{background:rgba(255,255,255,0.05);border:1px solid var(--bdr);color:var(--mut);border-radius:20px;padding:4px 13px;font-size:12px;cursor:pointer;white-space:nowrap;font-family:inherit;transition:color .15s;}
.topic-btn:hover{color:#cbd5e1;}
#messages{flex:1;overflow-y:auto;padding:20px 16px;max-width:740px;width:100%;margin:0 auto;}
.bwrap{display:flex;flex-direction:column;margin-bottom:20px;animation:fadeUp .3s ease both;}
.bwrap.user{align-items:flex-end;}.bwrap.ai{align-items:flex-start;}
.brow{display:flex;align-items:flex-end;gap:8px;}.bwrap.user .brow{flex-direction:row-reverse;}
.av{width:30px;height:30px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:13px;flex-shrink:0;}
.bub{max-width:76%;padding:11px 15px;font-size:14.5px;line-height:1.65;}
.bub.user{border-radius:18px 18px 4px 18px;}.bub.ai{background:rgba(255,255,255,0.07);border:1px solid var(--bdr);border-radius:18px 18px 18px 4px;}
.spkbtn{background:rgba(255,255,255,0.06);border:1px solid var(--bdr);border-radius:9px;color:var(--mut);padding:5px 9px;cursor:pointer;font-size:15px;flex-shrink:0;transition:all .2s;}
.spkbtn.on{background:rgba(59,130,246,0.12);}
.fb{max-width:76%;margin-top:7px;margin-left:38px;background:rgba(16,185,129,0.1);border:1px solid rgba(16,185,129,0.22);border-radius:12px;padding:8px 14px;font-size:13px;color:#6ee7b7;line-height:1.55;}
.typing-row{display:flex;align-items:center;gap:8px;margin-bottom:16px;color:#334155;font-size:13px;}
.dot{width:6px;height:6px;border-radius:50%;animation:blink 1.2s ease-in-out infinite;}
/* Input */
#inputWrap{background:rgba(7,9,15,0.97);border-top:1px solid var(--bdr);max-width:740px;width:100%;margin:0 auto;padding:12px 16px 18px;}
#statusBar{display:none;align-items:center;gap:8px;margin-bottom:10px;padding:8px 14px;border-radius:10px;}
#statusBar.rec{display:flex;background:rgba(59,130,246,0.09);border:1px solid rgba(59,130,246,0.28);}
#statusBar.err{display:flex;background:rgba(239,68,68,0.08);border:1px solid rgba(239,68,68,0.25);}
#recDot{width:8px;height:8px;border-radius:50%;background:#ef4444;animation:blink .7s infinite;flex-shrink:0;display:none;}
#recTime{font-family:'IBM Plex Mono',monospace;font-size:12px;color:#ef4444;font-weight:700;display:none;}
canvas#wv{transition:opacity .3s;opacity:.2;}canvas#wv.live{opacity:1;}
#stText{font-size:13px;}
.irow{display:flex;gap:9px;align-items:flex-end;}
#micBtn{width:46px;height:46px;border-radius:13px;flex-shrink:0;border:none;color:#fff;font-size:20px;cursor:pointer;transition:all .2s;}
#txtIn{flex:1;background:rgba(255,255,255,0.055);border:1px solid var(--bdr);border-radius:13px;color:#f1f5f9;font-size:14.5px;padding:10px 14px;resize:none;outline:none;font-family:inherit;line-height:1.55;}
#txtIn::placeholder{color:#1e293b;}
#clearBtn{width:36px;height:46px;border-radius:13px;flex-shrink:0;border:none;background:rgba(255,255,255,0.04);color:#64748b;font-size:16px;cursor:pointer;transition:all .2s;}
#clearBtn:hover{background:rgba(255,255,255,0.08);color:#94a3b8;}
#sndBtn{width:46px;height:46px;border-radius:13px;flex-shrink:0;border:none;color:#fff;font-size:20px;cursor:pointer;transition:all .2s;background:rgba(255,255,255,0.07);}
#hint{color:#1e293b;font-size:11px;margin-top:7px;text-align:center;}
#sttWarn,#mobileWarn{display:none;padding:8px 14px;background:rgba(251,191,36,0.08);border:1px solid rgba(251,191,36,0.25);border-radius:10px;font-size:13px;color:#fde68a;margin-bottom:10px;}
@media (max-width: 768px){
  .irow{flex-direction:column;gap:12px;}
  #micBtn,#sndBtn{width:100%;height:52px;font-size:22px;}
  #clearBtn{width:100%;height:44px;font-size:18px;}
  #txtIn{width:100%;min-height:48px;}
  .bub{max-width:90%;}
  .fb{max-width:90%;margin-left:0;}
}
@keyframes fadeUp{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:translateY(0)}}
@keyframes blink{0%,100%{opacity:1}50%{opacity:.25}}
::-webkit-scrollbar{width:4px;}::-webkit-scrollbar-thumb{background:rgba(255,255,255,0.07);border-radius:4px;}
</style>
</head>
<body>
<div id="apiScreen">
  <div style="font-size:54px">🇩🇪</div>
  <h1>Deutsch B1 <span>Trainer</span></h1>
  <p style="color:#475569;font-size:14px;max-width:400px;line-height:1.6">Luyện thi TELC B1 &amp; Phỏng vấn ĐSQ với AI</p>
  <div class="hint">
    🔑 Nhập <strong>OpenRouter API Key</strong> (miễn phí).<br/>
    Đăng ký &amp; lấy key tại: <a href="https://openrouter.ai/keys" target="_blank">openrouter.ai/keys</a><br/>
    Key dạng <code>sk-or-v1-...</code> • Nhiều model miễn phí<br/><br/>
    ✅ Miễn phí • Server local • Key không gửi ra ngoài.
  </div>
  <button onclick="skipToDemo()" style="width:100%;max-width:400px;padding:12px;margin-bottom:12px;border-radius:10px;border:1px solid rgba(245,158,11,0.4);background:rgba(245,158,11,0.1);color:#fbbf24;font-size:14px;font-weight:600;cursor:pointer;">🎬 Xem Demo Prüfung (Không cần API key)</button>
  <input id="apiKeyInput" type="password" placeholder="sk-or-v1-..." autocomplete="off"/>
  <button id="startBtn" onclick="initApp()">Bắt đầu →</button>
  <div id="apiErr"></div>
</div>

<div id="app">
  <div id="landing">
    <div style="font-size:50px">🇩🇪</div>
    <h1>Deutsch B1 <span>Trainer</span></h1>
    <p style="color:#475569;font-size:14px">Chọn chế độ luyện tập</p>
    <button class="mode-btn" onclick="selectMode('telc')" style="border-color:#3b82f633">
      <span style="font-size:24px">🎓</span>
      <div><div class="lbl">TELC B1 Mündliche Prüfung</div><div class="dsc">Teil 1: Kontaktaufnahme • Teil 2: Gespräch • Teil 3: Gemeinsam planen</div></div>
      <span style="margin-left:auto;color:#3b82f6;font-size:18px">→</span>
    </button>
    <button class="mode-btn" onclick="selectMode('embassy')" style="border-color:#a855f733">
      <span style="font-size:24px">🏛️</span>
      <div><div class="lbl">Phỏng vấn Đại Sứ Quán</div><div class="dsc">Phỏng vấn visa Sprachvisum • 4 Phase • 114 câu hỏi thực tế</div></div>
      <span style="margin-left:auto;color:#a855f7;font-size:18px">→</span>
    </button>
    <button class="mode-btn" onclick="selectMode('grammar')" style="border-color:#10b98133">
      <span style="font-size:24px">📚</span>
      <div><div class="lbl">Ngữ pháp B1</div><div class="dsc">Konjunktiv II, Passiv, Relativsätze...</div></div>
      <span style="margin-left:auto;color:#10b981;font-size:18px">→</span>
    </button>
    <button class="mode-btn" onclick="startDemoExam()" style="border-color:#f59e0b33">
      <span style="font-size:24px">🎬</span>
      <div><div class="lbl">Demo Prüfung ansehen</div><div class="dsc">Xem mẫu thi TELC B1 hoàn chỉnh • 3 Teil • Không cần API key</div></div>
      <span style="margin-left:auto;color:#f59e0b;font-size:18px">→</span>
    </button>
    <button class="mode-btn" onclick="startDemoEmbassy()" style="border-color:#a855f733">
      <span style="font-size:24px">🎬</span>
      <div><div class="lbl">Demo Phỏng vấn Visa</div><div class="dsc">Xem mẫu phỏng vấn Sprachvisum • 4 Phase • Hỏi đáp thực tế • Không cần API key</div></div>
      <span style="margin-left:auto;color:#a855f7;font-size:18px">→</span>
    </button>
    <div style="color:#1e293b;font-size:12px;display:flex;gap:24px;margin-top:8px;text-align:center;flex-wrap:wrap;justify-content:center;">
      <span>🎓 Chuẩn TELC B1 chính thức</span><span>🎙️ Nhận diện giọng nói</span><span>🔊 AI đọc tiếng Đức</span><span>🇻🇳 Phản hồi tiếng Việt</span><span>📊 Lưu lịch sử học</span>
    </div>
    <button class="mode-btn" onclick="toggleHistory()" style="border-color:#06b6d433;margin-top:12px;">
      <span style="font-size:24px">📊</span>
      <div><div class="lbl">Xem Lịch sử Chat</div><div class="dsc">Theo dõi tiến độ học • Thống kê hằng ngày</div></div>
      <span style="margin-left:auto;color:#06b6d4;font-size:18px">→</span>
    </button>
  </div>

  <div id="chat">
    <div id="chatHeader">
      <div style="display:flex;align-items:center;gap:11px">
        <button id="backBtn" onclick="goBack()">← Về</button>
        <button id="historyBtn" onclick="toggleHistory()">📊 Lịch sử</button>
        <button id="scoreBtn" onclick="requestTELCScoring()" style="display:none;">⭐ Chấm điểm</button>
        <button id="phraseBankBtn" onclick="togglePhraseBank()" style="display:none;padding:4px 10px;border-radius:8px;border:1px solid rgba(167,139,250,0.3);background:rgba(167,139,250,0.1);color:#a78bfa;font-size:12px;cursor:pointer;">📝 Mẫu câu</button>
        <div>
          <div id="modeTitle"></div>
          <div id="turnCount">0 lượt trả lời</div>
          <div id="telcTimer" style="display:none;">⏰ <span id="telcTimeDisplay">00:00</span></div>
        </div>
      </div>
      <div style="display:flex;gap:8px">
        <button id="vnToggle" onclick="toggleVN()">🇻🇳 VN Bật</button>
        <button id="ttsToggle" onclick="toggleTTS()">🔊 TTS Bật</button>
        <button id="speedToggle" onclick="toggleTTSSpeed()">⚡ Tốc độ: 1.2x</button>
      </div>
    </div>
    <div id="topics"></div>
    <div id="messages"></div>
    <div style="max-width:740px;width:100%;margin:0 auto">
      <div id="inputWrap">
        <div id="mobileWarn">📱 <strong>Mobile:</strong> 1) Test Audio để kiểm tra TTS 2) Reset Mic nếu ghi âm bị stuck 3) Bật volume max 4) Reload trang nếu vẫn lỗi</div>
        <div id="sttWarn">⚠️ Trình duyệt không hỗ trợ nhận diện giọng nói. Hãy dùng <strong>Chrome</strong>.</div>
        <div id="statusBar">
          <div id="recDot"></div><span id="recTime"></span>
          <canvas id="wv" width="140" height="32"></canvas>
          <span id="stText"></span>
        </div>
        <div class="irow">
          <button id="micBtn" onclick="toggleRec()" title="Nhấn để bắt đầu, nhấn lại để dừng và gửi">🎙</button>
          <textarea id="txtIn" rows="2" placeholder="Tippe auf Deutsch... hoặc nhấn 🎙 để nói"></textarea>
          <button id="clearBtn" onclick="clearInput()" title="Xóa text" style="width:36px;height:46px;border-radius:13px;border:none;background:rgba(255,255,255,0.04);color:#64748b;font-size:16px;cursor:pointer;">🗑️</button>
          <button id="sndBtn" onclick="sendMessage()">↑</button>
        </div>
        <div id="hint">🎙 Nhấn mic → nói 1-2 từ rõ ràng → tự động gửi &nbsp;|&nbsp; 🗑️ xóa text &nbsp;|&nbsp; Enter gửi &nbsp;|&nbsp; 🔊 nghe AI &nbsp;|&nbsp; 🇻🇳 bật/tắt feedback &nbsp;|&nbsp; 🔄 reset mic nếu stuck</div>
        <div id="mobileDebug" style="display:none;font-size:11px;color:#475569;margin-top:4px;text-align:center;"></div>
        <div id="audioTest" style="display:none;margin-top:8px;text-align:center;">
          <button id="testTTSBtn" style="padding:6px 12px;background:rgba(59,130,246,0.15);border:1px solid rgba(59,130,246,0.3);border-radius:8px;color:#60a5fa;font-size:12px;cursor:pointer;">🧪 Test Audio</button>
          <button id="testGoogleTTSBtn" style="padding:6px 12px;background:rgba(16,185,129,0.15);border:1px solid rgba(16,185,129,0.3);border-radius:8px;color:#34d399;font-size:12px;cursor:pointer;margin-left:8px;">🌐 Test Online</button>
          <button id="resetMicBtn" style="padding:6px 12px;background:rgba(239,68,68,0.15);border:1px solid rgba(239,68,68,0.3);border-radius:8px;color:#f87171;font-size:12px;cursor:pointer;margin-left:8px;">🔄 Reset Mic</button>
          <span id="testResult" style="margin-left:8px;font-size:11px;"></span>
        </div>
      </div>
    </div>
  </div>

  <!-- Demo Exam View -->
  <div id="demoExam">
    <div id="demoHeader">
      <div style="display:flex;align-items:center;justify-content:space-between;">
        <button onclick="exitDemoExam()" style="padding:6px 12px;border-radius:8px;border:1px solid rgba(245,158,11,0.3);background:rgba(245,158,11,0.1);color:#fbbf24;font-size:12px;cursor:pointer;">← Về</button>
        <div class="demo-title">🎬 Demo TELC B1 Mündliche Prüfung</div>
        <div style="width:50px;"></div>
      </div>
      <div class="demo-legend">
        <span><span style="color:#f59e0b;">&#9679;</span> Prüfer</span>
        <span><span style="color:#3b82f6;">&#9679;</span> Kandidat A</span>
        <span><span style="color:#10b981;">&#9679;</span> Kandidat B</span>
      </div>
      <div class="demo-teil-nav">
        <button class="demo-teil-btn active" onclick="jumpToTeil('teil1')">Teil 1</button>
        <button class="demo-teil-btn" onclick="jumpToTeil('teil2')">Teil 2</button>
        <button class="demo-teil-btn" onclick="jumpToTeil('teil3')">Teil 3</button>
      </div>
    </div>
    <div id="demoMessages"></div>
    <div id="demoControls">
      <button onclick="demoPlay()" id="demoPlayBtn">&#9654; Play</button>
      <button onclick="demoPause()" id="demoPauseBtn">&#10074;&#10074; Pause</button>
      <button onclick="demoReset()">&#8634; Reset</button>
      <button onclick="demoToggleVN()" id="demoVNBtn" class="active">VN: On</button>
      <button onclick="demoToggleTTS()" id="demoTTSBtn" class="active">TTS: On</button>
      <button onclick="demoToggleSpeed()" id="demoSpeedBtn">&#9201; 3s</button>
      <span id="demoProgress">0 / 0</span>
    </div>
  </div>

  <!-- History Panel -->
  <div id="historyPanel">
    <div id="historyHeader">
      <div id="historyTitle">📊 Lịch sử Chat</div>
      <button id="closeHistoryBtn" onclick="toggleHistory()">✕</button>
    </div>
    <div id="historyControls">
      <input type="date" id="historyDatePicker" onchange="loadHistoryByDate()" />
      <div id="historyStats">Loading statistics...</div>
    </div>
    <div id="historyContent">
      <div style="text-align:center;color:#64748b;margin-top:40px;">
        📈 Chọn ngày để xem lịch sử chat<br/>
        🎯 Theo dõi tiến độ học tiếng Đức
      </div>
    </div>
  </div>

  <!-- Scoring Panel -->
  <div id="scoringPanel">
    <div id="scoringHeader">
      <div id="scoringTitle">⭐ Chấm điểm TELC B1</div>
      <button id="closeScoringBtn" onclick="toggleScoring()">✕</button>
    </div>
    <div id="scoringContent">
      <div class="scoring-loading">
        📊 Chọn một Teil và chat để được chấm điểm<br/>
        🎯 Đánh giá theo tiêu chuẩn TELC B1 chính thức
      </div>
    </div>
  </div>

  <!-- Phrase Bank Panel -->
  <div id="phraseBankPanel">
    <div id="phraseBankHeader">
      <div class="pb-title">📝 Mẫu câu B1</div>
      <button class="pb-close" onclick="togglePhraseBank()">✕</button>
    </div>
    <div id="phraseBankContent"></div>
  </div>
</div>

<script>
const COLORS={telc:"#3b82f6",embassy:"#a855f7",grammar:"#10b981",demo:"#f59e0b"};
const LABELS={telc:"🎓 TELC B1 Mündliche Prüfung",embassy:"🏛️ Phỏng vấn ĐSQ",grammar:"📚 Ngữ pháp B1",demo:"🎬 Demo Prüfung"};
const TELC_PARTS={
  teil1: "Teil 1: Kontaktaufnahme (3-4 Min)",
  teil2: "Teil 2: Gespräch über ein Thema (5-6 Min)",
  teil3: "Teil 3: Gemeinsam etwas planen (5-6 Min)"
};

const EMBASSY_PHASES = {
  phase1: "Phase 1: Persönliche Daten",
  phase2: "Phase 2: Sprachkurs & Motivation",
  phase3: "Phase 3: Pläne & Finanzen",
  phase4: "Phase 4: Fähigkeiten & Risiken"
};

const EMBASSY_STARTERS = {
  phase1: "Guten Morgen. Bitte setzen Sie sich. Ich bin der Sachbearbeiter für Sprachvisa. Zunächst brauche ich einige persönliche Angaben. Wie heißen Sie und wie alt sind Sie?",
  phase2: "Gut, danke. Jetzt möchte ich über Ihre Deutschkenntnisse und Ihre Motivation sprechen. Welches Sprachniveau haben Sie und wo haben Sie Deutsch gelernt?",
  phase3: "Verstehe. Jetzt kommen wir zu Ihren Plänen und der Finanzierung. Was genau möchten Sie in Deutschland machen und wie finanzieren Sie Ihren Aufenthalt?",
  phase4: "Noch ein paar letzte Fragen. Was qualifiziert Sie besonders für dieses Visum und was machen Sie, wenn etwas schiefgeht?"
};

const EMBASSY_PHRASE_BANK = {
  phase1: {
    "Persönliche Angaben": [
      { de: "Ich heiße... und bin... Jahre alt.", vn: "Ten va tuoi" },
      { de: "Ich bin ledig / verheiratet.", vn: "Tinh trang hon nhan" },
      { de: "Ich habe einen Abschluss in...", vn: "Bang cap" },
      { de: "Meine Familie wohnt in...", vn: "Gia dinh o dau" },
      { de: "Ich komme aus... und wohne derzeit in...", vn: "Que va noi o hien tai" }
    ],
    "Familie & Bildung": [
      { de: "Meine Eltern arbeiten als...", vn: "Nghe nghiep bo me" },
      { de: "Ich habe... Geschwister.", vn: "So anh chi em" },
      { de: "Ich habe... an der Universität... studiert.", vn: "Nganh hoc va truong" }
    ]
  },
  phase2: {
    "Sprachkenntnisse": [
      { de: "Ich habe das Niveau B1 am... bestanden.", vn: "Dat trinh do B1 o dau" },
      { de: "Ich lerne seit... Monaten Deutsch.", vn: "Hoc tieng Duc bao lau" },
      { de: "Mein Kurs war bei... (Goethe/VHS).", vn: "Hoc o co so nao" }
    ],
    "Motivation": [
      { de: "Ich möchte in Deutschland studieren, weil...", vn: "Ly do muon hoc o Duc" },
      { de: "Deutschland hat die besten... Programme.", vn: "Duc co chuong trinh tot nhat" },
      { de: "Ich interessiere mich für den Studiengang...", vn: "Quan tam nganh hoc..." }
    ]
  },
  phase3: {
    "Finanzierung": [
      { de: "Ich habe ein Sperrkonto mit... Euro.", vn: "Tai khoan phong toa" },
      { de: "Meine Eltern finanzieren meinen Aufenthalt.", vn: "Bo me tai tro" },
      { de: "Ich habe eine Finanzierungsbestätigung von...", vn: "Xac nhan tai chinh" }
    ],
    "Unterkunft & Pläne": [
      { de: "Ich habe bereits ein Zimmer in... gefunden.", vn: "Da tim duoc phong" },
      { de: "Ich werde am... anfangen zu studieren.", vn: "Se bat dau hoc khi nao" },
      { de: "Nach dem Studium plane ich...", vn: "Ke hoach sau khi hoc" }
    ]
  },
  phase4: {
    "Qualifikationen": [
      { de: "Ich habe bereits Erfahrung in...", vn: "Da co kinh nghiem ve..." },
      { de: "Meine bisherigen Leistungen zeigen, dass...", vn: "Thanh tich cho thay..." },
      { de: "Ich bin besonders motiviert, weil...", vn: "Dong luc dac biet vi..." }
    ],
    "Rückkehr & Risiken": [
      { de: "Nach meinem Aufenthalt werde ich nach... zurückkehren.", vn: "Se quay ve sau khi..." },
      { de: "In meinem Heimatland habe ich... (Job/Familie).", vn: "O que co viec/gia dinh" },
      { de: "Falls etwas schiefgeht, werde ich...", vn: "Neu co van de, se..." },
      { de: "Ich habe einen Plan B: ...", vn: "Ke hoach du phong" }
    ]
  }
};

const TOPICS={
  telc:["Teil 1: Kontaktaufnahme","Teil 2: Gespräch über Thema","Teil 3: Gemeinsam planen"],
  embassy:["Phase 1: Persönliche Daten","Phase 2: Sprachkurs & Motivation","Phase 3: Pläne & Finanzen","Phase 4: Fähigkeiten & Risiken"],
  grammar:["Konjunktiv II","Passiv","Relativsätze","Perfekt vs Präteritum","Modalverben"],
};

const TELC_TEIL2_TOPICS = [
  "Haushaltspflichten und Geschlechterrollen",
  "Freiwilligenarbeit und Gemeinschaftsdienst",
  "Bei den Eltern wohnen vs. Unabhängigkeit",
  "Leben im Ausland",
  "Kino vs. Fernsehen",
  "Vor- und Nachteile sozialer Medien",
  "Umweltschutz im Alltag",
  "Arbeit und Freizeit",
  "Gesunde Ernährung"
];

const TELC_TEIL3_SCENARIOS = [
  "Eine Fahrradtour organisieren",
  "Eine Geburtstagsfeier planen",
  "Eine Abschiedsfeier arrangieren",
  "Ein Kursabschlussevent planen",
  "Einen Tagesausflug organisieren",
  "Ein Picknick im Park planen",
  "Eine Wochenendreise organisieren",
  "Ein Fest für internationale Studenten planen"
];
const STARTERS={
  telc:"Hallo! Ich bin Ihr TELC B1 Prüfer. Willkommen zur mündlichen Prüfung. Wir beginnen mit Teil 1 - Kontaktaufnahme. Stellen Sie sich bitte vor: Wie heißen Sie und woher kommen Sie?",
  embassy:"Guten Morgen. Bitte setzen Sie sich. Können Sie mir erklären, warum Sie nach Deutschland möchten?",
  grammar:"Hallo! Welches Grammatikthema möchtest du üben? Konjunktiv II, Passiv, oder Relativsätze?",
};

// TELC Timer Durations (in seconds)
const TELC_DURATIONS = {
  teil1: 240,  // 4 minutes - Kontaktaufnahme
  teil2: 360,  // 6 minutes - Gespräch über Thema
  teil3: 360   // 6 minutes - Gemeinsam planen
};

// TELC Suggestion Templates
const TELC_SUGGESTIONS = {
  teil1: [
    "Ich heiße... und ich komme aus...",
    "Ich wohne in... seit...",
    "Ich arbeite als... / Ich studiere...",
    "Meine Familie besteht aus...",
    "In meiner Freizeit...",
    "Ich spreche... Sprachen",
    "Ich bin ... Jahre alt"
  ],
  teil2: [
    "Ich bin der Meinung, dass...",
    "Meiner Ansicht nach...",
    "Einerseits..., andererseits...",
    "Das hat sowohl Vor- als auch Nachteile",
    "Aus meiner Erfahrung...",
    "Ich finde es wichtig, dass...",
    "Deshalb denke ich..."
  ],
  teil3: [
    "Wie wäre es, wenn wir...?",
    "Sollen wir...?",
    "Was hältst du von...?",
    "Ich schlage vor, dass...",
    "Wir könnten auch...",
    "Was ist deine Meinung dazu?",
    "Lass uns... planen"
  ]
};

const TELC_PHRASE_BANK = {
  teil1: {
    "Sich vorstellen": [
      { de: "Ich heiße... und komme aus...", vn: "Gioi thieu ten va que" },
      { de: "Ich wohne seit... Jahren in...", vn: "Noi song bao lau" },
      { de: "Ich bin... Jahre alt und arbeite als...", vn: "Tuoi va nghe nghiep" },
      { de: "Meine Familie besteht aus...", vn: "Thanh vien gia dinh" },
      { de: "Ich bin nach Deutschland gekommen, weil...", vn: "Ly do den Duc" }
    ],
    "Hobbys & Freizeit": [
      { de: "In meiner Freizeit... ich gern...", vn: "So thich" },
      { de: "Am Wochenende mache ich meistens...", vn: "Cuoi tuan thuong lam gi" },
      { de: "Ich interessiere mich sehr für...", vn: "Quan tam den..." }
    ],
    "Über Sprachen": [
      { de: "Ich spreche... und lerne seit... Deutsch", vn: "Ngon ngu va hoc tieng Duc" },
      { de: "Deutsch ist wichtig für mich, weil...", vn: "Tai sao tieng Duc quan trong" }
    ]
  },
  teil2: {
    "Meinung": [
      { de: "Meiner Meinung nach...", vn: "Theo y kien cua toi" },
      { de: "Ich finde, dass...", vn: "Toi thay rang..." },
      { de: "Ich bin der Meinung, dass...", vn: "Toi co y kien rang..." },
      { de: "Aus meiner Erfahrung...", vn: "Tu kinh nghiem cua toi..." }
    ],
    "Zustimmung": [
      { de: "Da hast du Recht!", vn: "Ban noi dung!" },
      { de: "Das sehe ich genauso.", vn: "Toi cung nghi vay." },
      { de: "Das ist ein guter Punkt.", vn: "Do la mot diem tot." }
    ],
    "Widerspruch": [
      { de: "Da bin ich anderer Meinung.", vn: "Toi co y kien khac." },
      { de: "Ich sehe das ein bisschen anders.", vn: "Toi thay hoi khac." },
      { de: "Einerseits..., andererseits...", vn: "Mot mat..., mat khac..." }
    ],
    "Begründung": [
      { de: "Das finde ich wichtig, weil...", vn: "Dieu do quan trong vi..." },
      { de: "Der Grund dafür ist...", vn: "Ly do la..." },
      { de: "Deshalb denke ich, dass...", vn: "Vi vay toi nghi rang..." }
    ]
  },
  teil3: {
    "Vorschläge": [
      { de: "Wie wäre es, wenn wir...?", vn: "The nao neu chung ta...?" },
      { de: "Ich schlage vor, dass wir...", vn: "Toi de xuat rang chung ta..." },
      { de: "Sollen wir vielleicht...?", vn: "Hay la chung ta...?" },
      { de: "Wir könnten auch...", vn: "Chung ta cung co the..." }
    ],
    "Reaktion": [
      { de: "Das ist eine gute Idee!", vn: "Do la y tuong tot!" },
      { de: "Einverstanden! Und was noch?", vn: "Dong y! Va gi nua?" },
      { de: "Ich bin nicht sicher, ob das klappt.", vn: "Toi khong chac dieu do co duoc khong." },
      { de: "Könntest du dich darum kümmern?", vn: "Ban co the lo viec do khong?" }
    ],
    "Zusammenfassung": [
      { de: "Fassen wir zusammen: ...", vn: "Tom tat lai: ..." },
      { de: "Dann sind wir uns einig, dass...", vn: "Vay chung ta dong y rang..." },
      { de: "Also, du machst... und ich mache...", vn: "Vay ban lam... va toi lam..." }
    ]
  }
};

const B1_STRUCTURE_PATTERNS = {
  "Konnektoren": {
    label: "Konnektoren (Linking words)",
    patterns: [
      { regex: /\bweil\b/i, name: "weil (because)", example: "Ich lerne Deutsch, weil ich in Berlin arbeite." },
      { regex: /\bobwohl\b/i, name: "obwohl (although)", example: "Obwohl es regnet, gehe ich spazieren." },
      { regex: /\bdeshalb\b/i, name: "deshalb (therefore)", example: "Es regnet, deshalb bleibe ich zu Hause." },
      { regex: /\btrotzdem\b/i, name: "trotzdem (nevertheless)", example: "Es regnet, trotzdem gehe ich raus." },
      { regex: /\bau(ss|ß)erdem\b/i, name: "außerdem (besides)", example: "Außerdem finde ich das Thema interessant." },
      { regex: /\beinerseits\b/i, name: "einerseits...andererseits", example: "Einerseits ist es gut, andererseits ist es teuer." },
      { regex: /\bdass\b/i, name: "dass (that)", example: "Ich finde, dass das wichtig ist." },
      { regex: /\bwenn\b/i, name: "wenn (if/when)", example: "Wenn ich Zeit habe, gehe ich ins Kino." }
    ]
  },
  "Konjunktiv II": {
    label: "Konjunktiv II (Subjunctive)",
    patterns: [
      { regex: /\bwürde\b/i, name: "würde + Infinitiv", example: "Ich würde gerne nach Berlin fahren." },
      { regex: /\bkönnte\b/i, name: "könnte (could)", example: "Wir könnten auch ins Kino gehen." },
      { regex: /\bhätte\b/i, name: "hätte (would have)", example: "Ich hätte gerne mehr Zeit." },
      { regex: /\bwäre\b/i, name: "wäre (would be)", example: "Das wäre eine gute Idee." },
      { regex: /\bsollte\b/i, name: "sollte (should)", example: "Wir sollten früher anfangen." }
    ]
  },
  "Meinung": {
    label: "Meinungsäußerung (Expressing opinion)",
    patterns: [
      { regex: /meiner meinung nach/i, name: "Meiner Meinung nach", example: "Meiner Meinung nach ist das richtig." },
      { regex: /ich finde,?\s/i, name: "Ich finde, ...", example: "Ich finde, das ist eine gute Idee." },
      { regex: /ich denke,?\s/i, name: "Ich denke, ...", example: "Ich denke, wir sollten das machen." },
      { regex: /ich bin der meinung/i, name: "Ich bin der Meinung", example: "Ich bin der Meinung, dass wir mehr Zeit brauchen." }
    ]
  },
  "Planung": {
    label: "Planungssprache (Planning language)",
    patterns: [
      { regex: /wie wäre es/i, name: "Wie wäre es, wenn...?", example: "Wie wäre es, wenn wir am Samstag gehen?" },
      { regex: /ich schlage vor/i, name: "Ich schlage vor", example: "Ich schlage vor, dass wir früh anfangen." },
      { regex: /sollen wir/i, name: "Sollen wir...?", example: "Sollen wir Kuchen mitbringen?" },
      { regex: /was h(ae|ä)ltst du/i, name: "Was hältst du von...?", example: "Was hältst du von meinem Vorschlag?" },
      { regex: /wir könnten/i, name: "Wir könnten...", example: "Wir könnten ein Picknick machen." },
      { regex: /fassen wir zusammen/i, name: "Fassen wir zusammen", example: "Fassen wir zusammen: du bringst Essen, ich bringe Getränke." }
    ]
  },
  "Perfekt": {
    label: "Perfekt (Present perfect)",
    patterns: [
      { regex: /\bhab(e|en|t)\s+\w+\s*(ge\w+t|ge\w+en)\b/i, name: "haben + Partizip II", example: "Ich habe gestern viel gelernt." },
      { regex: /\b(bin|bist|ist|sind|seid)\s+\w*\s*(ge\w+en|ge\w+t|gegangen|gefahren|gekommen)\b/i, name: "sein + Partizip II", example: "Ich bin nach Berlin gefahren." }
    ]
  }
};

const TELC_STARTERS = {
  teil1: "Hallo! Ich bin Ihr TELC B1 Prüfer. Wir beginnen mit Teil 1 - Kontaktaufnahme (3-4 Minuten). Stellen Sie sich bitte vor: Wie heißen Sie und woher kommen Sie?",

  teil2: "Sehr gut! Jetzt kommen wir zu Teil 2 - Gespräch über ein Thema (5-6 Minuten). Ich möchte mit Ihnen über ein wichtiges Thema sprechen. Was denken Sie über das Thema 'Bei den Eltern wohnen vs. eigene Wohnung'? Was ist Ihre Meinung dazu?",

  teil3: "Ausgezeichnet! Nun Teil 3 - Gemeinsam etwas planen (5-6 Minuten). Stellen Sie sich vor: Wir sind Kollegen und möchten zusammen eine Geburtstagsfeier für einen gemeinsamen Freund organisieren. Was ist Ihre erste Idee? Wo könnten wir feiern?"
};

const DEMO_SPEAKERS = {
  prufer:    { label: "Prüfer",     emoji: "\ud83d\udc68\u200d\ud83c\udfeb", color: "#f59e0b" },
  kandidatA: { label: "Kandidat A", emoji: "\ud83d\udc69",                   color: "#3b82f6" },
  kandidatB: { label: "Kandidat B", emoji: "\ud83d\udc68",                   color: "#10b981" }
};

const DEMO_EXAM_SCRIPT = {
  teil1: {
    title: "Teil 1: Kontaktaufnahme",
    description: "Sich vorstellen und Fragen beantworten (3-4 Minuten)",
    messages: [
      { speaker: "prufer", de: "Guten Tag! Willkommen zur mündlichen Prüfung TELC B1. Mein Name ist Herr Müller, ich bin Ihr Prüfer. Bitte stellen Sie sich vor. Kandidat A, fangen Sie an.", vn: "Prüfer chào và giới thiệu. Luôn dùng 'Sie' (trang trọng) trong thi.", tip: "Nghe kỹ câu hỏi của Prüfer, trả lời đầy đủ nhưng không quá dài." },
      { speaker: "kandidatA", de: "Guten Tag, Herr Müller! Ich heiße Anna Schmidt. Ich komme aus Vietnam, aber ich wohne seit zwei Jahren in Berlin. Ich bin 28 Jahre alt und arbeite als Krankenschwester in einem Krankenhaus.", vn: "Giới thiệu cơ bản: tên, quê, nơi ở, tuổi, nghề nghiệp. Dùng 'seit + Dativ' để nói thời gian.", tip: "Nói rõ ràng, tự tin. Prüfer đánh giá cả sự tự nhiên khi giao tiếp." },
      { speaker: "prufer", de: "Danke, Frau Schmidt. Und Sie, Kandidat B?", vn: "Prüfer chuyển sang thí sinh B." },
      { speaker: "kandidatB", de: "Hallo! Mein Name ist Thomas Nguyen. Ich bin 25 und komme ursprünglich aus Hanoi. Jetzt lebe ich in München und studiere Informatik an der Technischen Universität. Nebenbei arbeite ich als Werkstudent bei einer IT-Firma.", vn: "Giới thiệu chi tiết hơn: quê gốc, nơi sống hiện tại, ngành học, công việc. 'Ursprünglich' = ban đầu, gốc." },
      { speaker: "prufer", de: "Sehr gut. Frau Schmidt, was machen Sie gern in Ihrer Freizeit?", vn: "Câu hỏi về sở thích - chủ đề rất phổ biến trong Teil 1." },
      { speaker: "kandidatA", de: "In meiner Freizeit koche ich sehr gern, besonders vietnamesische Gerichte. Am Wochenende gehe ich oft mit Freunden spazieren oder wir besuchen zusammen ein Café. Ich habe auch angefangen, Yoga zu machen, weil es mir hilft, nach der Arbeit zu entspannen.", vn: "Liệt kê nhiều hoạt động, dùng 'weil' (Nebensatz) để giải thích lý do. Cấu trúc Perfekt: 'habe angefangen'.", tip: "Dùng Konnektoren (weil, deshalb, außerdem) để câu trả lời tự nhiên hơn." },
      { speaker: "prufer", de: "Und Herr Nguyen, wie sieht ein typisches Wochenende bei Ihnen aus?", vn: "Câu hỏi về cuối tuần - biến thể của câu hỏi sở thích." },
      { speaker: "kandidatB", de: "Am Samstagmorgen schlafe ich meistens aus, weil die Woche sehr anstrengend ist. Nachmittags treffe ich mich mit Kommilitonen zum Lernen oder wir spielen Fußball im Park. Sonntags telefoniere ich oft mit meiner Familie in Vietnam. Das finde ich sehr wichtig, obwohl der Zeitunterschied manchmal schwierig ist.", vn: "Mô tả chi tiết ngày cuối tuần. Dùng 'obwohl' (Nebensatz nhượng bộ) và 'meistens' (trạng từ tần suất)." }
    ]
  },
  teil2: {
    title: "Teil 2: Gespräch über ein Thema",
    description: "Über ein Thema sprechen und diskutieren (5-6 Minuten)",
    messages: [
      { speaker: "prufer", de: "Jetzt kommen wir zu Teil 2. Das Thema ist: 'Gruppenreisen oder alleine reisen - was ist besser?' Bitte diskutieren Sie miteinander. Kandidat A, was ist Ihre Meinung?", vn: "Prüfer giới thiệu chủ đề thảo luận. Hai thí sinh phải trao đổi với nhau, không chỉ nói với Prüfer.", tip: "Teil 2 yêu cầu thảo luận. Phải có ý kiến rõ ràng và lắng nghe đối phương." },
      { speaker: "kandidatA", de: "Meiner Meinung nach sind Gruppenreisen besser, besonders wenn man ein neues Land besucht. Erstens ist es sicherer, wenn man zusammen reist. Zweitens kann man die Kosten teilen, zum Beispiel für die Unterkunft oder das Mietauto. Außerdem macht es einfach mehr Spaß, Erlebnisse mit anderen zu teilen. Was denkst du, Thomas?", vn: "Nêu ý kiến rõ ràng với 'Meiner Meinung nach'. Dùng 'Erstens...Zweitens...Außerdem' để sắp xếp luận điểm. Cuối cùng hỏi lại đối phương.", tip: "Luôn hỏi lại thí sinh kia để tạo cuộc đối thoại tự nhiên." },
      { speaker: "kandidatB", de: "Da hast du einen guten Punkt, Anna. Aber ich sehe das ein bisschen anders. Ich reise lieber allein, weil man dann flexibler ist. Man kann selbst entscheiden, wohin man geht und wie lange man bleibt. Bei Gruppenreisen muss man immer Kompromisse machen, und das kann manchmal stressig sein.", vn: "Phản hồi lịch sự: 'Da hast du einen guten Punkt, aber...' Đưa ra ý kiến trái ngược mà không thô lỗ. 'Flexibler' = Komparativ.", tip: "Không nói 'Du hast Unrecht!' Thay bằng 'Ich sehe das anders' hoặc 'Da bin ich anderer Meinung'." },
      { speaker: "kandidatA", de: "Ja, das verstehe ich. Aber hast du keine Angst, alleine in einem fremden Land zu sein? Ich war einmal allein in Italien und habe mich manchmal einsam gefühlt. In einer Gruppe hat man immer jemanden zum Reden.", vn: "Hỏi lại để phản biện nhẹ nhàng. Dùng Perfekt kể kinh nghiệm cá nhân: 'Ich war...habe mich gefühlt'. Kinh nghiệm thực tế rất thuyết phục." },
      { speaker: "kandidatB", de: "Einerseits hast du Recht, dass man sich alleine manchmal einsam fühlen kann. Andererseits lernt man auf Alleinreisen viel leichter neue Leute kennen. Wenn ich allein reise, spreche ich viel mehr mit Einheimischen. Das ist auch gut für die Sprachkenntnisse!", vn: "'Einerseits...andererseits' = Một mặt...mặt khác. Cấu trúc B1 quan trọng để cân nhắc hai mặt. Đưa ra lợi ích cụ thể." },
      { speaker: "kandidatA", de: "Das stimmt, das ist ein guter Punkt. Vielleicht könnte man einen Kompromiss finden: Man könnte mit einer kleinen Gruppe reisen, aber auch freie Tage einplanen, an denen jeder alleine etwas machen kann. Was meinst du dazu?", vn: "Tìm giải pháp dung hòa = điểm cộng lớn. Dùng Konjunktiv II 'könnte man' để đề xuất lịch sự.", tip: "Tìm Kompromiss ở cuối thảo luận thể hiện kỹ năng giao tiếp cao." },
      { speaker: "kandidatB", de: "Ja, das finde ich einen super Kompromiss! So hat man das Beste von beiden Seiten. Man hat Gesellschaft, aber auch Freiheit. Ich würde das gerne mal ausprobieren.", vn: "Đồng ý với giải pháp. 'Ich würde gerne' = Konjunktiv II thể hiện mong muốn lịch sự." }
    ]
  },
  teil3: {
    title: "Teil 3: Gemeinsam etwas planen",
    description: "Zusammen eine Aktivität planen (5-6 Minuten)",
    messages: [
      { speaker: "prufer", de: "Sehr gut! Jetzt kommen wir zum letzten Teil. Sie möchten zusammen eine Abschiedsfeier für einen Kollegen organisieren, der ins Ausland geht. Bitte planen Sie die Feier gemeinsam.", vn: "Teil 3: Lên kế hoạch cùng nhau. Phải thảo luận và đồng ý về các chi tiết cụ thể.", tip: "Teil 3 quan trọng: phải hỏi ý kiến, đề xuất, đồng ý/phản đối, và đi đến kết luận." },
      { speaker: "kandidatA", de: "Okay, wir müssen eine Abschiedsfeier planen. Zuerst sollten wir über den Termin sprechen. Wann passt es dir am besten? Ich schlage vor, dass wir die Feier am Freitagabend machen, weil dann alle frei haben.", vn: "Bắt đầu có cấu trúc: 'Zuerst sollten wir...' Đề xuất với 'Ich schlage vor, dass...' + Nebensatz.", tip: "Bắt đầu bằng cách liệt kê những gì cần thảo luận, rồi đi từng điểm." },
      { speaker: "kandidatB", de: "Freitagabend klingt gut! Und wo sollen wir feiern? Wie wäre es mit einem Restaurant? Oder wir könnten bei jemandem zu Hause feiern, das wäre gemütlicher und billiger.", vn: "Đồng ý rồi đưa ra câu hỏi tiếp theo. 'Wie wäre es mit...' = Konjunktiv II đề xuất. Đưa ra 2 lựa chọn để thảo luận." },
      { speaker: "kandidatA", de: "Ich finde die Idee, bei jemandem zu Hause zu feiern, besser. In einem Restaurant ist es oft zu laut und zu teuer. Ich könnte meine Wohnung anbieten, sie ist groß genug für 15 Leute.", vn: "So sánh hai lựa chọn và chọn một. 'Ich könnte...anbieten' = đề nghị giúp đỡ. Đưa ra lý do cụ thể." },
      { speaker: "kandidatB", de: "Super, danke! Das ist sehr nett von dir. Was sollen wir zum Essen und Trinken besorgen? Sollen wir alles selbst kochen oder lieber etwas bestellen?", vn: "Cảm ơn và chuyển sang chủ đề tiếp theo: đồ ăn. Đưa ra hai lựa chọn rõ ràng." },
      { speaker: "kandidatA", de: "Ich schlage vor, dass jeder etwas mitbringt. Das ist einfacher und billiger. Ich könnte einen Kuchen backen und Salate machen. Könntest du dich um die Getränke kümmern?", vn: "Đề xuất mỗi người đóng góp. Phân chia nhiệm vụ cụ thể. 'Könntest du...?' = nhờ lịch sự.", tip: "Phân chia nhiệm vụ rõ ràng cho thấy kỹ năng tổ chức tốt." },
      { speaker: "kandidatB", de: "Klar, ich kümmere mich um die Getränke. Wasser, Saft, und vielleicht ein paar Flaschen Wein. Und was schenken wir unserem Kollegen? Hast du eine Idee?", vn: "Đồng ý và liệt kê cụ thể. Chuyển sang chủ đề tiếp: quà tặng." },
      { speaker: "kandidatA", de: "Hmm, wie wäre es, wenn wir zusammen ein Fotoalbum machen? Mit Fotos von der Arbeit und persönlichen Nachrichten von allen Kollegen. Das ist persönlicher als ein gekauftes Geschenk.", vn: "'Wie wäre es, wenn...' = đề xuất sáng tạo. So sánh 'persönlicher als' = Komparativ. Lý do tại sao lựa chọn này tốt hơn." },
      { speaker: "kandidatB", de: "Das ist eine tolle Idee! Ich finde das viel schöner als etwas zu kaufen. Wir könnten auch alle Kollegen bitten, einen kurzen Brief zu schreiben. Und was ist mit der Musik?", vn: "Đồng ý nhiệt tình, bổ sung thêm ý. Chuyển sang điểm tiếp theo." },
      { speaker: "kandidatA", de: "Gute Frage! Ich habe eine Playlist mit internationaler Musik. Oder sollen wir den Kollegen fragen, welche Musik er mag? Dann fassen wir zusammen: Freitagabend bei mir zu Hause, jeder bringt etwas mit, ich backe Kuchen, du besorgst Getränke, wir machen ein Fotoalbum als Geschenk, und ich kümmere mich um die Musik. Sind wir uns einig?", vn: "Tóm tắt kế hoạch ở cuối rất quan trọng. 'Fassen wir zusammen' = Hãy tóm tắt. Liệt kê tất cả các điểm đã thống nhất. 'Sind wir uns einig?' = kết thúc chuyên nghiệp.", tip: "Luôn tóm tắt kế hoạch ở cuối Teil 3 - đây là điểm cộng lớn với Prüfer." },
      { speaker: "kandidatB", de: "Ja, genau! Ich glaube, das wird eine schöne Feier. Unser Kollege wird sich bestimmt freuen. Dann sind wir fertig mit der Planung!", vn: "Xác nhận kế hoạch hoàn tất. 'Wird sich freuen' = Futur I thể hiện dự đoán. Kết thúc tích cực." }
    ]
  }
};

const DEMO_EMBASSY_SPEAKERS = {
  beamter:       { label: "Beamter",        emoji: "\ud83d\udc68\u200d\ud83d\udcbc", color: "#a855f7" },
  antragsteller: { label: "Antragsteller",  emoji: "\ud83e\uddd1",                   color: "#22c55e" }
};

const DEMO_EMBASSY_SCRIPT = {
  phase1: {
    title: "Phase 1: Persönliche Daten",
    description: "Tên, tuổi, gia đình, học vấn, sở thích (Câu 1–19)",
    messages: [
      { speaker: "beamter", de: "Guten Morgen. Bitte setzen Sie sich. Ich bin Herr Weber, zuständig für Sprachvisa. Darf ich Ihren Reisepass und Ihre Unterlagen sehen?", vn: "Beamter chào và yêu cầu xem giấy tờ.", tip: "Luôn mang đầy đủ: hộ chiếu, đơn xin visa, chứng chỉ, tài chính." },
      { speaker: "antragsteller", de: "Guten Morgen, Herr Weber. Ja, natürlich. Hier ist mein Reisepass und hier sind meine Unterlagen.", vn: "Chào lịch sự và đưa giấy tờ." },
      { speaker: "beamter", de: "Danke. Wie heißen Sie?", vn: "Câu 1: Tên bạn là gì?" },
      { speaker: "antragsteller", de: "Ich heiße Pham Thi Thu Phuong. Mein Familienname ist Pham und mein Vorname ist Thu Phuong.", vn: "Trả lời đầy đủ họ và tên." },
      { speaker: "beamter", de: "Wie alt sind Sie?", vn: "Câu 2: Bạn bao nhiêu tuổi?" },
      { speaker: "antragsteller", de: "Ich bin neunzehn Jahre alt.", vn: "'Neunzehn' = 19." },
      { speaker: "beamter", de: "Wann sind Sie geboren?", vn: "Câu 3: Ngày tháng năm sinh?" },
      { speaker: "antragsteller", de: "Ich bin am fünfzehnten Mai zweitausendsechs geboren.", vn: "'Am + Ordinalzahl + Monat + Jahr' cho ngày sinh." },
      { speaker: "beamter", de: "Wo wurden Sie geboren?", vn: "Câu 4: Sinh ra ở đâu?" },
      { speaker: "antragsteller", de: "Ich wurde in Hai Phong geboren. Das ist eine große Hafenstadt im Norden Vietnams.", vn: "'Hafenstadt' = thành phố cảng. Nêu thêm thông tin." },
      { speaker: "beamter", de: "Sind Sie verheiratet?", vn: "Câu 5: Đã kết hôn chưa?" },
      { speaker: "antragsteller", de: "Nein, ich bin ledig. Ich bin erst neunzehn Jahre alt.", vn: "'Ledig' = độc thân." },
      { speaker: "beamter", de: "Haben Sie Kinder?", vn: "Câu 6: Có con chưa?" },
      { speaker: "antragsteller", de: "Nein, ich habe keine Kinder.", vn: "Trả lời ngắn gọn, rõ ràng." },
      { speaker: "beamter", de: "Mit wem wohnen Sie jetzt zusammen?", vn: "Câu 7: Hiện sống cùng ai?" },
      { speaker: "antragsteller", de: "Ich wohne mit meinen Eltern und meinem jüngeren Bruder zusammen in Hai Phong.", vn: "Nêu cụ thể thành viên và nơi ở." },
      { speaker: "beamter", de: "Wie viele Mitglieder hat Ihre Familie?", vn: "Câu 8: Gia đình bao nhiêu người?" },
      { speaker: "antragsteller", de: "Meine Familie hat vier Mitglieder: mein Vater, meine Mutter, mein jüngerer Bruder und ich.", vn: "Liệt kê cụ thể." },
      { speaker: "beamter", de: "Haben Sie Geschwister? Was machen sie beruflich?", vn: "Câu 9: Anh chị em? Nghề nghiệp?" },
      { speaker: "antragsteller", de: "Ja, ich habe einen jüngeren Bruder. Er ist sechzehn Jahre alt und geht noch zur Schule. Er besucht die elfte Klasse.", vn: "Em trai 16 tuổi, lớp 11." },
      { speaker: "beamter", de: "Haben Sie Verwandte oder Freunde in Deutschland?", vn: "Câu 10: Có người thân ở Đức không?" },
      { speaker: "antragsteller", de: "Ja, meine Tante lebt in Berlin. Sie heißt Lan und wohnt seit fünf Jahren in Berlin-Marzahn. Sie arbeitet als Köchin in einem vietnamesischen Restaurant.", vn: "Có dì ở Berlin. Nêu tên, nơi ở, nghề nghiệp.", tip: "Thể hiện có mạng lưới hỗ trợ ở Đức." },
      { speaker: "beamter", de: "Welche Qualifikationen haben Sie?", vn: "Câu 11: Bằng cấp gì?" },
      { speaker: "antragsteller", de: "Ich habe mein Abitur im Juni 2024 gemacht. Außerdem habe ich das TELC B1 Zertifikat in Deutsch.", vn: "'Abitur' = tốt nghiệp THPT. Nêu cả chứng chỉ tiếng Đức." },
      { speaker: "beamter", de: "Was machen Sie beruflich?", vn: "Câu 12: Bạn làm nghề gì?" },
      { speaker: "antragsteller", de: "Ich bin zurzeit nicht berufstätig. Seit meinem Schulabschluss lerne ich Vollzeit Deutsch, um mich auf mein Leben in Deutschland vorzubereiten.", vn: "'Nicht berufstätig' = không đi làm. Học tiếng Đức full-time." },
      { speaker: "beamter", de: "Was ist Ihr aktueller Beruf?", vn: "Câu 13: Nghề nghiệp hiện tại?" },
      { speaker: "antragsteller", de: "Ich habe noch keinen Beruf. Ich habe gerade die Schule abgeschlossen und lerne jetzt Deutsch. Mein Ziel ist es, Erzieherin zu werden.", vn: "Chưa có nghề, nêu mục tiêu: Erzieherin." },
      { speaker: "beamter", de: "Was machen Sie momentan?", vn: "Câu 14: Hiện tại đang làm gì?" },
      { speaker: "antragsteller", de: "Momentan lerne ich jeden Tag Deutsch. Ich besuche einen Deutschkurs in Hai Phong, vier Stunden am Tag. Zu Hause übe ich noch zwei Stunden.", vn: "Mô tả lịch học hàng ngày." },
      { speaker: "beamter", de: "Was haben Sie seit Ihrem Schulabschluss im Juni 2024 bis heute gemacht?", vn: "Câu 15: Từ khi tốt nghiệp đã làm gì?" },
      { speaker: "antragsteller", de: "Nach meinem Schulabschluss habe ich sofort mit Deutsch angefangen. Von August 2024 bis März 2025 habe ich A1 und A2 gelernt. Dann habe ich B1 gelernt und im Oktober 2025 die TELC B1 Prüfung bestanden. Außerdem habe ich ein Praktikum in einem Kindergarten gemacht.", vn: "Lộ trình rõ: tốt nghiệp → học tiếng → đỗ B1 → thực tập.", tip: "Beamter muốn thấy không lãng phí thời gian." },
      { speaker: "beamter", de: "Haben Sie bereits Erfahrungen in diesem Bereich?", vn: "Câu 16: Có kinh nghiệm trong lĩnh vực này?" },
      { speaker: "antragsteller", de: "Ja, ich habe drei Monate ein Praktikum in einem Kindergarten in Hai Phong gemacht. Ich habe mit Kindern zwischen drei und sechs Jahren gearbeitet und beim Spielen, Essen und kreativen Aktivitäten geholfen.", vn: "3 tháng thực tập mầm non. Nêu chi tiết." },
      { speaker: "beamter", de: "Was war die schwierigste Situation während Ihres Praktikums in Vietnam?", vn: "Câu 17: Tình huống khó khăn nhất?" },
      { speaker: "antragsteller", de: "Ein Kind hat jeden Morgen geweint, weil es seine Mutter vermisst hat. Ich habe geduldig mit dem Kind gespielt und ihm Vertrauen gegeben. Nach zwei Wochen hat es mich angelächelt. Das war ein schönes Erlebnis.", vn: "Kể tình huống cụ thể → kiên nhẫn → kết quả tốt.", tip: "Câu trả lời cụ thể rất thuyết phục." },
      { speaker: "beamter", de: "Was ist Ihr Hobby?", vn: "Câu 18: Sở thích?" },
      { speaker: "antragsteller", de: "Meine Hobbys sind Lesen und Kochen. Ich lese gern vietnamesische Literatur und koche gern für meine Familie. Außerdem spiele ich Badminton.", vn: "Liệt kê sở thích: đọc sách, nấu ăn, cầu lông." },
      { speaker: "beamter", de: "Was ist Ihr Lieblingsessen?", vn: "Câu 19: Món ăn yêu thích?" },
      { speaker: "antragsteller", de: "Mein Lieblingsessen ist Phở. Das ist eine vietnamesische Suppe mit Reisnudeln und Rindfleisch. Meine Mutter kocht die beste Phở!", vn: "'Reisnudeln' = bún/phở. 'Rindfleisch' = thịt bò." }
    ]
  },
  phase2: {
    title: "Phase 2: Sprachkurs & Motivation",
    description: "Khóa học tiếng Đức, lý do chọn Đức, mục tiêu (Câu 20–51)",
    messages: [
      { speaker: "beamter", de: "Gut, danke. Kommen wir jetzt zu Ihrem Sprachkurs.", vn: "Chuyển sang phần khóa học tiếng Đức." },
      { speaker: "beamter", de: "Seit wann lernen Sie Deutsch?", vn: "Câu 20: Học tiếng Đức từ bao giờ?" },
      { speaker: "antragsteller", de: "Ich lerne seit August 2024 Deutsch. Das sind jetzt ungefähr eineinhalb Jahre.", vn: "'Seit + Dativ'. 'Eineinhalb Jahre' = 1,5 năm." },
      { speaker: "beamter", de: "Wie lange lernen Sie schon Deutsch? Wie ist Ihr aktuelles Sprachniveau?", vn: "Câu 21: Học bao lâu? Trình độ?" },
      { speaker: "antragsteller", de: "Ich lerne seit eineinhalb Jahren Deutsch. Mein aktuelles Niveau ist B1. Ich habe die TELC B1 Prüfung im Oktober 2025 bestanden.", vn: "Thời gian + trình độ + bằng chứng." },
      { speaker: "beamter", de: "Haben Sie schon ein Sprachzertifikat?", vn: "Câu 22: Có chứng chỉ chưa?" },
      { speaker: "antragsteller", de: "Ja, ich habe das TELC B1 Zertifikat. Hier ist es. Ich habe die Prüfung im Oktober 2025 bestanden.", vn: "Đưa bản gốc. 'Bestanden' = đã đỗ." },
      { speaker: "beamter", de: "Warum war Ihr B1-Ergebnis nicht so gut?", vn: "Câu 23: Tại sao kết quả B1 không tốt?" },
      { speaker: "antragsteller", de: "Ich war beim Sprechen nervös und habe deshalb nicht so gut abgeschnitten. Aber ich habe bestanden. Deshalb möchte ich in Deutschland mein Sprechen verbessern.", vn: "Thừa nhận điểm yếu → biến thành lý do đi Đức.", tip: "Không bao biện, biến yếu điểm thành động lực." },
      { speaker: "beamter", de: "Wo werden Sie Deutsch lernen?", vn: "Câu 24: Sẽ học ở đâu?" },
      { speaker: "antragsteller", de: "Ich werde an der Hartnackschule in Berlin Deutsch lernen.", vn: "Hartnackschule Berlin." },
      { speaker: "beamter", de: "Wie heißt Ihre Sprachschule in Berlin und wie viele Stunden lernen Sie pro Woche?", vn: "Câu 25: Trường tên gì, bao nhiêu giờ/tuần?" },
      { speaker: "antragsteller", de: "Meine Sprachschule heißt Hartnackschule Berlin. Ich werde zwanzig Stunden pro Woche lernen, vier Stunden pro Tag von Montag bis Freitag.", vn: "20 giờ/tuần = 4 giờ/ngày, thứ 2-6." },
      { speaker: "beamter", de: "Warum haben Sie diese Sprachschule gewählt?", vn: "Câu 26: Tại sao chọn trường này?" },
      { speaker: "antragsteller", de: "Die Hartnackschule hat eine lange Tradition und gute Bewertungen. Der Intensivkurs hat zwanzig Stunden pro Woche. Außerdem liegt die Schule in Berlin-Mitte, gut erreichbar von meiner Unterkunft.", vn: "3 lý do: uy tín, cường độ, vị trí." },
      { speaker: "beamter", de: "Wie lange dauert Ihr Sprachkurs?", vn: "Câu 27: Khóa học bao lâu?" },
      { speaker: "antragsteller", de: "Mein Sprachkurs dauert sechs Monate, von April bis September 2026.", vn: "6 tháng: 4-9/2026." },
      { speaker: "beamter", de: "Wie viele Monate dauert Ihr Sprachkurs genau?", vn: "Câu 28: Chính xác mấy tháng?" },
      { speaker: "antragsteller", de: "Der Kurs dauert genau sechs Monate.", vn: "Chính xác 6 tháng." },
      { speaker: "beamter", de: "Welche Niveaustufen werden Sie besuchen?", vn: "Câu 29: Học những trình độ nào?" },
      { speaker: "antragsteller", de: "Ich werde mit A2.2 beginnen und bis B2 lernen. Der Kurs geht von A2.2 über B1 bis B2.", vn: "Lộ trình: A2.2 → B1 → B2." },
      { speaker: "beamter", de: "Wie intensiv ist der Kurs?", vn: "Câu 30: Cường độ thế nào?" },
      { speaker: "antragsteller", de: "Es ist ein Intensivkurs mit zwanzig Unterrichtsstunden pro Woche. Vier Stunden täglich. Zusätzlich übe ich zu Hause zwei bis drei Stunden.", vn: "20 giờ/tuần + tự học 2-3 giờ/ngày." },
      { speaker: "beamter", de: "Haben Sie die Kursgebühren schon bezahlt?", vn: "Câu 31: Đã đóng học phí chưa?" },
      { speaker: "antragsteller", de: "Ja, ich habe die Kursgebühren bereits bezahlt. Hier ist die Zahlungsbestätigung.", vn: "Đã thanh toán. 'Zahlungsbestätigung' = biên lai.", tip: "Đã trả tiền = cam kết nghiêm túc." },
      { speaker: "beamter", de: "Warum lernen Sie wieder ab A2.2?", vn: "Câu 32: Tại sao học lại từ A2.2?" },
      { speaker: "antragsteller", de: "Meine Grundlage ist noch nicht stabil genug, besonders beim Sprechen und Hören. In Deutschland möchte ich von A2.2 anfangen, um meine Basis zu festigen.", vn: "'Festigen' = củng cố. Nền tảng chưa vững." },
      { speaker: "beamter", de: "Warum haben Sie sich für ein Sprachvisum entschieden und warum beginnen Sie mit A2.2?", vn: "Câu 33: Tại sao xin Sprachvisum và bắt đầu từ A2.2?" },
      { speaker: "antragsteller", de: "Ich brauche das Sprachvisum, weil ich mein Deutsch in einem deutschsprachigen Umfeld verbessern möchte. Ich beginne bei A2.2, um meine Grundlagen zu stärken und die B2-Prüfung sicher zu bestehen.", vn: "Sprachvisum = học trong môi trường Đức. A2.2 = củng cố." },
      { speaker: "beamter", de: "Warum wählen Sie das Niveau A2.2 und nicht B1?", vn: "Câu 34: Tại sao A2.2 thay vì B1?" },
      { speaker: "antragsteller", de: "Obwohl ich B1 bestanden habe, möchte ich Grammatik und Sprechen von A2.2 an aufbauen. In Vietnam habe ich vor allem Lesen und Schreiben gelernt. In Deutschland kann ich Hören und Sprechen besser üben.", vn: "'Obwohl' (B1 connector). Kỹ năng nghe-nói cần cải thiện." },
      { speaker: "beamter", de: "Wenn Sie bereits B1 gelernt haben, warum wiederholen Sie A2.2 in Deutschland?", vn: "Câu 35: Đã B1 sao lại học lại A2.2?" },
      { speaker: "antragsteller", de: "In Deutschland lerne ich die Sprache ganz anders. Ich kann täglich Deutsch hören und sprechen. Das ist wie ein neuer Start mit besserer Praxis. Nach sechs Monaten werde ich B2 erreichen.", vn: "Môi trường Đức giúp học khác, thực hành tốt hơn." },
      { speaker: "beamter", de: "Ist es nicht Zeitverschwendung, wieder bei A2.2 anzufangen, wenn Sie schon B1 gelernt haben?", vn: "Câu 36: Chẳng phải lãng phí thời gian sao?" },
      { speaker: "antragsteller", de: "Nein, ich glaube nicht. Eine gute Grundlage ist sehr wichtig. Wenn die Basis nicht stabil ist, habe ich später Probleme bei B2. Lieber langsam und sicher.", vn: "'Lieber langsam und sicher' = thà chậm mà chắc.", tip: "Câu hỏi provokativ — giữ bình tĩnh." },
      { speaker: "beamter", de: "Warum möchten Sie nach Deutschland kommen?", vn: "Câu 37: Tại sao đến Đức?" },
      { speaker: "antragsteller", de: "Ich möchte nach Deutschland, um mein Deutsch zu verbessern und eine Ausbildung zur Erzieherin zu machen. Deutschland hat ein sehr gutes Ausbildungssystem.", vn: "2 lý do: tiếng Đức + Ausbildung Erzieherin." },
      { speaker: "beamter", de: "Warum möchten Sie nach Deutschland kommen, um Deutsch zu lernen?", vn: "Câu 38: Tại sao sang Đức để học tiếng?" },
      { speaker: "antragsteller", de: "In Deutschland kann ich den ganzen Tag Deutsch hören und sprechen — im Supermarkt, auf der Straße, überall. Das ist viel besser als nur im Unterricht in Vietnam. Außerdem möchte ich die deutsche Kultur kennenlernen, weil ich als Erzieherin arbeiten möchte.", vn: "Môi trường ngôn ngữ + hiểu văn hóa cho nghề." },
      { speaker: "beamter", de: "Warum Deutschland?", vn: "Câu 39: Tại sao chọn Đức?" },
      { speaker: "antragsteller", de: "Deutschland braucht viele Erzieherinnen. Es gibt einen großen Fachkräftemangel in Kindergärten. Außerdem ist die Ausbildung praxisorientiert und international anerkannt.", vn: "'Fachkräftemangel' = thiếu nhân lực. 'Praxisorientiert' = hướng thực hành." },
      { speaker: "beamter", de: "Warum wollen Sie in Deutschland Deutsch lernen?", vn: "Câu 40: Tại sao sang Đức học tiếng?" },
      { speaker: "antragsteller", de: "Als Erzieherin muss ich mit deutschen Kindern und Eltern kommunizieren. Dafür reicht es nicht, nur Grammatik zu lernen. Ich muss die Alltagssprache verstehen. Das geht am besten in Deutschland.", vn: "Erzieherin cần giao tiếp hàng ngày → cần môi trường thực tế." },
      { speaker: "beamter", de: "Warum lernen Sie Deutsch nicht weiter in Vietnam?", vn: "Câu 41: Tại sao không học ở VN?" },
      { speaker: "antragsteller", de: "In Vietnam spreche ich nur im Unterricht Deutsch. Zu Hause und auf der Straße spreche ich Vietnamesisch. In Deutschland bin ich den ganzen Tag von Deutsch umgeben. Außerdem gibt es in Hai Phong nicht viele gute B2-Kurse.", vn: "'Umgeben' = bao quanh. So sánh: VN chỉ trong lớp, Đức cả ngày." },
      { speaker: "beamter", de: "Warum lernen Sie das Niveau B2 nicht in Vietnam, um Kosten zu sparen?", vn: "Câu 42: Sao không học B2 ở VN để tiết kiệm?" },
      { speaker: "antragsteller", de: "Es stimmt, in Vietnam wäre es billiger. Aber als Erzieherin brauche ich nicht nur die Prüfung, sondern auch praktische Sprachkompetenz. In Deutschland kann ich gleichzeitig Kultur und Bildungssystem kennenlernen.", vn: "Thừa nhận VN rẻ hơn, nhưng cần kỹ năng thực tế." },
      { speaker: "beamter", de: "Warum haben Sie keinen Sprachkurs in Ihrer Heimatstadt gesucht, sondern gehen nach Berlin?", vn: "Câu 43: Sao không học ở quê mà sang Berlin?" },
      { speaker: "antragsteller", de: "In Hai Phong gibt es nur wenige Deutschkurse und die Qualität ist begrenzt. Die Hartnackschule in Berlin ist eine bekannte Sprachschule. Außerdem wohnt meine Tante in Berlin und kann mir helfen.", vn: "Chất lượng dạy ở HP kém, Hartnackschule tốt, có dì hỗ trợ." },
      { speaker: "beamter", de: "Warum haben Sie sich für Berlin als Studienort entschieden?", vn: "Câu 44: Tại sao chọn Berlin?" },
      { speaker: "antragsteller", de: "Berlin ist eine internationale Stadt mit vielen Möglichkeiten. Meine Tante lebt dort. Die Hartnackschule ist sehr gut. Und Berlin hat viele Kindergärten für meine spätere Ausbildung.", vn: "4 lý do: quốc tế, có dì, trường tốt, cơ hội Ausbildung." },
      { speaker: "beamter", de: "Wissen Sie, dass man in Berlin Berlinerisch spricht? Haben Sie Angst vor Dialekten?", vn: "Câu 45: Biết giọng Berlin? Có sợ không?" },
      { speaker: "antragsteller", de: "Ja, ich weiß. Zum Beispiel sagt man ick statt ich. Aber in der Sprachschule spricht man Hochdeutsch. Ich finde es sogar interessant, Dialekte kennenzulernen.", vn: "Biết Berlinerisch, không sợ, trường dạy Hochdeutsch." },
      { speaker: "beamter", de: "Warum möchten Sie Erzieherin werden?", vn: "Câu 46: Tại sao chọn nghề Erzieherin?" },
      { speaker: "antragsteller", de: "Ich arbeite gern mit Kindern. Während meines Praktikums habe ich gemerkt, dass mir die Arbeit mit kleinen Kindern Freude macht. Kinder zu erziehen ist für mich eine sinnvolle Aufgabe.", vn: "Thích trẻ em + kinh nghiệm thực tập. 'Sinnvoll' = có ý nghĩa." },
      { speaker: "beamter", de: "Warum möchten Sie Erzieherin in Deutschland werden und nicht in Vietnam?", vn: "Câu 47: Tại sao Erzieherin ở Đức mà không ở VN?" },
      { speaker: "antragsteller", de: "In Deutschland hat der Beruf Erzieherin einen hohen Stellenwert und ein gutes Gehalt. In Vietnam verdient man als Kindergärtnerin sehr wenig. Die Ausbildung in Deutschland ist auch besser.", vn: "'Stellenwert' = giá trị nghề. Lương + chất lượng đào tạo." },
      { speaker: "beamter", de: "Warum Ausbildung in Deutschland und nicht in Vietnam?", vn: "Câu 48: Tại sao học nghề ở Đức?" },
      { speaker: "antragsteller", de: "Die Ausbildung in Deutschland ist dual — Theorie und Praxis gleichzeitig. In Vietnam gibt es dieses System nicht. Außerdem bekommt man in Deutschland während der Ausbildung ein Gehalt.", vn: "'Dual' = lý thuyết + thực hành. Có lương khi học." },
      { speaker: "beamter", de: "Wer hat Sie inspiriert, diesen Beruf zu wählen?", vn: "Câu 49: Ai truyền cảm hứng?" },
      { speaker: "antragsteller", de: "Meine Mutter ist Lehrerin. Sie hat mir gezeigt, wie wichtig Bildung ist. Meine Tante in Berlin hat erzählt, dass Deutschland viele Erzieherinnen braucht. Das hat mich motiviert.", vn: "Mẹ là giáo viên + dì kể về nhu cầu Erzieherin." },
      { speaker: "beamter", de: "Was ist Ihr Ziel?", vn: "Câu 50: Mục tiêu?" },
      { speaker: "antragsteller", de: "Mein Ziel ist: B2 erreichen, dann Ausbildung zur Sozialassistentin und danach zur Erzieherin. In fünf bis sechs Jahren möchte ich als staatlich anerkannte Erzieherin in Berlin arbeiten.", vn: "B2 → Sozialassistentin (2J) → Erzieherin (3J). 'Staatlich anerkannt' = được công nhận." },
      { speaker: "beamter", de: "Warum ist die Erzieher-Ausbildung für Sie so wichtig?", vn: "Câu 51: Tại sao đào tạo Erzieher quan trọng?" },
      { speaker: "antragsteller", de: "Die Ausbildung gibt mir eine sichere berufliche Zukunft. Erzieherinnen werden in Deutschland dringend gebraucht. Ich habe gute Jobchancen und kann einen Beitrag zur Gesellschaft leisten.", vn: "'Dringend gebraucht' = cần gấp. 'Beitrag zur Gesellschaft' = đóng góp cho XH." }
    ]
  },
  phase3: {
    title: "Phase 3: Pläne & Finanzen",
    description: "Kế hoạch, tài chính, nhà ở, hợp đồng (Câu 52–90)",
    messages: [
      { speaker: "beamter", de: "Jetzt sprechen wir über Ihre Pläne nach dem Sprachkurs und Ihre Finanzen.", vn: "Chuyển sang kế hoạch và tài chính — phần QUAN TRỌNG NHẤT." },
      { speaker: "beamter", de: "Was werden Sie nach Abschluss des Sprachkurses tun?", vn: "Câu 52: Sau khóa học tiếng sẽ làm gì?" },
      { speaker: "antragsteller", de: "Nach dem Sprachkurs werde ich die B2-Prüfung ablegen. Dann möchte ich mich für die Ausbildung zur Sozialassistentin bewerben. Die Ausbildung dauert zwei Jahre.", vn: "B2-Prüfung → Sozialassistentin (2 năm)." },
      { speaker: "beamter", de: "Was ist Ihr Plan nach dem Sprachkurs?", vn: "Câu 53: Kế hoạch sau khóa học?" },
      { speaker: "antragsteller", de: "Mein Plan: B2-Prüfung bestehen, dann Ausbildung zur Sozialassistentin, danach Erzieherin. Der gesamte Weg dauert fünf Jahre.", vn: "Tổng: B2 → SA (2J) → Erz (3J) = 5 năm." },
      { speaker: "beamter", de: "Was sind Ihre Pläne nach dem Sprachkurs?", vn: "Câu 54: Kế hoạch sau khóa học tiếng?" },
      { speaker: "antragsteller", de: "Ich möchte mein Sprachniveau auf B2 bringen und dann eine Ausbildung beginnen. Ich habe mich schon über Ausbildungsplätze in Berlin informiert.", vn: "B2 → Ausbildung. Đã tìm hiểu thông tin." },
      { speaker: "beamter", de: "Was machen Sie, wenn Sie den Kurs beendet haben?", vn: "Câu 55: Kết thúc khóa học thì làm gì?" },
      { speaker: "antragsteller", de: "Wenn ich den Kurs beendet habe, werde ich sofort die B2-Prüfung machen. Dann bewerbe ich mich für die Sozialassistentin-Ausbildung an einer Fachschule in Berlin.", vn: "B2 → nộp đơn Fachschule Berlin." },
      { speaker: "beamter", de: "Was müssen Sie tun, wenn Ihr Sprachkurs nach 6 Monaten endet?", vn: "Câu 56: Phải làm gì sau 6 tháng?" },
      { speaker: "antragsteller", de: "Nach sechs Monaten muss ich entweder mein Visum verlängern für die Ausbildung oder nach Vietnam zurückkehren. Ich plane, das Visum für die Ausbildung umzuwandeln.", vn: "Gia hạn visa cho Ausbildung hoặc về VN. 'Umwandeln' = chuyển đổi." },
      { speaker: "beamter", de: "Haben Sie vor, nach dem Sprachkurs in Deutschland zu bleiben?", vn: "Câu 57: Có ý định ở lại Đức?" },
      { speaker: "antragsteller", de: "Ja, ich möchte in Deutschland bleiben, um die Ausbildung zur Erzieherin zu machen. Aber nur mit dem richtigen Visum. Wenn das nicht möglich ist, kehre ich nach Vietnam zurück.", vn: "Muốn ở lại cho Ausbildung, nhưng hợp pháp. Sẵn sàng về VN." },
      { speaker: "beamter", de: "Haben Sie vor, nach der Ausbildung in Deutschland zu bleiben?", vn: "Câu 58: Ở lại sau Ausbildung?" },
      { speaker: "antragsteller", de: "Ja, ich möchte nach der Ausbildung einige Jahre als Erzieherin in Deutschland arbeiten. Danach möchte ich vielleicht nach Vietnam zurückkehren und dort im Bildungsbereich arbeiten.", vn: "Vài năm ở Đức → về VN làm giáo dục. Thể hiện kế hoạch dài hạn." },
      { speaker: "beamter", de: "Haben Sie schon einen Berufsvertrag?", vn: "Câu 59: Đã có hợp đồng nghề chưa?" },
      { speaker: "antragsteller", de: "Nein, noch nicht. Ich muss zuerst meinen Sprachkurs abschließen und B2 erreichen. Dann kann ich mich für eine Ausbildungsstelle bewerben.", vn: "Chưa có. Cần hoàn thành B2 trước." },
      { speaker: "beamter", de: "Was macht eine Sozialassistentin genau?", vn: "Câu 60: Sozialassistentin làm gì?" },
      { speaker: "antragsteller", de: "Eine Sozialassistentin arbeitet mit Kindern, Jugendlichen und Menschen mit Behinderung. Sie hilft bei der Betreuung, Pflege und Förderung. Es ist die erste Stufe vor der Erzieher-Ausbildung.", vn: "Làm việc với trẻ em, thanh niên, người khuyết tật. Bước đầu trước Erzieherin." },
      { speaker: "beamter", de: "Was ist der Unterschied zwischen einer Sozialassistentin und einer Erzieherin?", vn: "Câu 61: Khác biệt giữa SA và Erzieherin?" },
      { speaker: "antragsteller", de: "Die Sozialassistentin ist eine zweijährige Grundausbildung. Die Erzieherin ist eine weiterführende Ausbildung von drei Jahren. Eine Erzieherin hat mehr Verantwortung und kann eine Kindergartengruppe leiten.", vn: "SA = 2 năm cơ bản. Erzieherin = 3 năm nâng cao, nhiều trách nhiệm hơn." },
      { speaker: "beamter", de: "Welche Fächer werden Sie in der Ausbildung zur Sozialassistentin lernen?", vn: "Câu 62: Học những môn gì trong SA?" },
      { speaker: "antragsteller", de: "Ich werde Pädagogik, Psychologie, Gesundheit und Pflege, Ernährung und Hauswirtschaft lernen. Außerdem gibt es praktische Übungen in Kindergärten und sozialen Einrichtungen.", vn: "Sư phạm, tâm lý, sức khỏe, dinh dưỡng + thực hành." },
      { speaker: "beamter", de: "Wo möchten Sie nach der 5-jährigen Ausbildung arbeiten?", vn: "Câu 63: Sau 5 năm muốn làm việc ở đâu?" },
      { speaker: "antragsteller", de: "Ich möchte in einem Kindergarten in Berlin arbeiten. Berlin hat einen großen Bedarf an Erzieherinnen. Ich hoffe, dass ich dort eine gute Stelle finden werde.", vn: "Kindergarten ở Berlin. Nhu cầu lớn." },
      { speaker: "beamter", de: "Wo genau werden Sie Ihr Zeugnis anerkennen lassen?", vn: "Câu 64: Công nhận bằng ở đâu?" },
      { speaker: "antragsteller", de: "Ich werde mein vietnamesisches Zeugnis bei der Senatsverwaltung für Bildung in Berlin anerkennen lassen. Meine Agentur hat mir dabei schon geholfen.", vn: "'Senatsverwaltung für Bildung' = Sở Giáo dục Berlin." },
      { speaker: "beamter", de: "Welchem deutschen Schulabschluss entspricht Ihr vietnamesisches Zeugnis?", vn: "Câu 65: Bằng VN tương đương bằng Đức nào?" },
      { speaker: "antragsteller", de: "Mein vietnamesisches Abiturzeugnis entspricht dem Mittleren Schulabschluss, dem MSA, in Deutschland. Das reicht für die Ausbildung zur Sozialassistentin.", vn: "Tốt nghiệp THPT VN = MSA. Đủ cho SA." },
      { speaker: "beamter", de: "Was machen Sie, wenn Ihr Zeugnis nicht als MSA anerkannt wird?", vn: "Câu 66: Nếu bằng không được công nhận?" },
      { speaker: "antragsteller", de: "Wenn mein Zeugnis nicht anerkannt wird, kann ich eine Feststellungsprüfung machen. Das ist eine Prüfung, um die Gleichwertigkeit zu beweisen. Meine Agentur hat mich darüber informiert.", vn: "'Feststellungsprüfung' = kỳ thi xác định tương đương." },
      { speaker: "beamter", de: "Wie finanzieren Sie Ihren Aufenthalt in Deutschland?", vn: "Câu 67: Chi trả ở Đức thế nào?" },
      { speaker: "antragsteller", de: "Ich habe ein Sperrkonto bei Expatrio eröffnet. Auf dem Konto sind 11.208 Euro. Das entspricht 934 Euro pro Monat für zwölf Monate. Hier ist die Bestätigung.", vn: "Sperrkonto Expatrio: 11.208€ = 934€/tháng.", tip: "Số tiền Sperrkonto thay đổi hàng năm." },
      { speaker: "beamter", de: "Wer finanziert Ihren Sprachkurs und Ihre Lebenshaltungskosten?", vn: "Câu 68: Ai tài trợ?" },
      { speaker: "antragsteller", de: "Meine Eltern finanzieren meinen Aufenthalt. Mein Vater ist Geschäftsmann und meine Mutter ist Lehrerin. Sie haben das Geld auf mein Sperrkonto eingezahlt. Außerdem zahlt meine Tante keine Miete.", vn: "Bố mẹ tài trợ. Bố kinh doanh, mẹ giáo viên. Dì cho ở miễn phí." },
      { speaker: "beamter", de: "Wo werden Sie wohnen und wer finanziert Ihren Aufenthalt?", vn: "Câu 69: Ở đâu và ai tài trợ?" },
      { speaker: "antragsteller", de: "Ich werde bei meiner Tante in Berlin-Marzahn wohnen. Meine Tante hat eine Wohnung dort. Meine Eltern finanzieren meinen Aufenthalt über das Sperrkonto.", vn: "Ở với dì ở Marzahn. Bố mẹ tài trợ qua Sperrkonto." },
      { speaker: "beamter", de: "Wie viel Geld steht Ihnen monatlich zur Verfügung?", vn: "Câu 70: Mỗi tháng có bao nhiêu tiền?" },
      { speaker: "antragsteller", de: "Ich habe 934 Euro pro Monat vom Sperrkonto. Da ich bei meiner Tante wohne und keine Miete zahle, reicht das Geld gut für Essen, Transport und Materialien.", vn: "934€/tháng. Không trả tiền nhà → đủ sống." },
      { speaker: "beamter", de: "Wer hat Ihr Sperrkonto eröffnet?", vn: "Câu 71: Ai mở Sperrkonto?" },
      { speaker: "antragsteller", de: "Ich habe das Sperrkonto selbst bei Expatrio eröffnet. Es ist ein Online-Konto. Die Eröffnung war einfach.", vn: "Tự mở tại Expatrio online." },
      { speaker: "beamter", de: "Wie hoch ist der monatliche Betrag, den Sie zum Leben haben?", vn: "Câu 72: Số tiền hàng tháng?" },
      { speaker: "antragsteller", de: "Ich habe 934 Euro pro Monat. Davon brauche ich etwa 300 Euro für Essen, 90 Euro für Transport und den Rest für andere Kosten. Da ich keine Miete zahle, ist das ausreichend.", vn: "934€: ăn 300€, đi lại 90€, còn lại chi khác." },
      { speaker: "beamter", de: "Wer hat das Geld auf Ihr Sperrkonto eingezahlt?", vn: "Câu 73: Ai nộp tiền vào Sperrkonto?" },
      { speaker: "antragsteller", de: "Meine Eltern haben das Geld eingezahlt. Mein Vater hat das Geld von seinem Geschäftskonto überwiesen. Hier sind die Überweisungsbelege.", vn: "Bố mẹ nộp. Bố chuyển từ tài khoản kinh doanh.", tip: "Mang theo Überweisungsbelege (chứng từ chuyển tiền)." },
      { speaker: "beamter", de: "Wie lange reicht das Geld auf Ihrem Sperrkonto?", vn: "Câu 74: Tiền trong Sperrkonto đủ dùng bao lâu?" },
      { speaker: "antragsteller", de: "Das Geld reicht für zwölf Monate. Mein Sprachkurs dauert nur sechs Monate, also habe ich genug Geld.", vn: "12 tháng. Khóa học 6 tháng → dư." },
      { speaker: "beamter", de: "Wer hilft Ihnen, wenn das Geld auf dem Sperrkonto nicht ausreicht?", vn: "Câu 75: Ai giúp nếu tiền không đủ?" },
      { speaker: "antragsteller", de: "Meine Eltern werden mir zusätzliches Geld schicken, wenn nötig. Außerdem kann meine Tante in Berlin mich unterstützen. Mein Vater hat ein stabiles Einkommen.", vn: "Bố mẹ gửi thêm + dì hỗ trợ. Bố có thu nhập ổn định." },
      { speaker: "beamter", de: "Werden Ihre Eltern Sie auch während der 2-jährigen Sozialassistentin-Ausbildung unterstützen?", vn: "Câu 76: Bố mẹ hỗ trợ trong 2 năm SA?" },
      { speaker: "antragsteller", de: "In der Ausbildung bekomme ich ein Ausbildungsgehalt. Außerdem kann ich mit dem Ausbildungsvisum arbeiten. Meine Eltern haben zugesagt, mich zu unterstützen, falls nötig.", vn: "Có lương Ausbildung + được đi làm. Bố mẹ sẵn sàng hỗ trợ." },
      { speaker: "beamter", de: "Haben Sie vor, während des Sprachkurses zu arbeiten?", vn: "Câu 77: Có định đi làm thêm trong khi học?" },
      { speaker: "antragsteller", de: "Nein, während des Sprachkurses möchte ich mich voll auf das Lernen konzentrieren. Ich weiß, dass das Sprachvisum nur begrenzte Arbeitserlaubnis hat.", vn: "Không, tập trung học. Sprachvisum hạn chế làm việc." },
      { speaker: "beamter", de: "Wo werden Sie in Berlin wohnen?", vn: "Câu 78: Ở đâu tại Berlin?" },
      { speaker: "antragsteller", de: "Ich werde bei meiner Tante in Berlin-Marzahn wohnen. Sie hat eine Dreizimmerwohnung und ein Zimmer ist frei für mich.", vn: "Ở với dì ở Marzahn. Căn hộ 3 phòng, 1 phòng trống." },
      { speaker: "beamter", de: "Wo werden Sie während des Sprachkurses wohnen?", vn: "Câu 79: Ở đâu trong thời gian học?" },
      { speaker: "antragsteller", de: "Ich wohne bei meiner Tante Lan in Berlin-Marzahn. Sie hat mich eingeladen. Hier ist die Wohnungsgeberbestätigung.", vn: "'Wohnungsgeberbestätigung' = giấy xác nhận nơi ở.", tip: "Cần Wohnungsgeberbestätigung cho đăng ký cư trú." },
      { speaker: "beamter", de: "Wo werden Sie wohnen?", vn: "Câu 80: Bạn sẽ ở đâu?" },
      { speaker: "antragsteller", de: "Bei meiner Tante in Berlin-Marzahn. Die Adresse ist auf der Wohnungsgeberbestätigung.", vn: "Trả lời ngắn gọn, đưa giấy tờ." },
      { speaker: "beamter", de: "Ist die Wohnung Ihrer Verwandten groß genug für eine weitere Person?", vn: "Câu 81: Căn hộ đủ lớn không?" },
      { speaker: "antragsteller", de: "Ja, meine Tante hat eine Dreizimmerwohnung. Es gibt ein Schlafzimmer, ein Wohnzimmer und ein Gästezimmer. Das Gästezimmer ist für mich.", vn: "3 phòng: phòng ngủ, phòng khách, phòng khách cho mình." },
      { speaker: "beamter", de: "Was arbeitet die Verwandte, bei der Sie wohnen werden?", vn: "Câu 82: Người thân làm nghề gì?" },
      { speaker: "antragsteller", de: "Meine Tante arbeitet als Köchin in einem vietnamesischen Restaurant in Berlin. Sie lebt seit fünf Jahren in Deutschland und hat eine unbefristete Aufenthaltserlaubnis.", vn: "Dì làm đầu bếp, ở Đức 5 năm, có Niederlassungserlaubnis." },
      { speaker: "beamter", de: "Werden Sie bei Ihren Verwandten Miete zahlen?", vn: "Câu 83: Có phải trả tiền nhà không?" },
      { speaker: "antragsteller", de: "Nein, meine Tante hat gesagt, ich muss keine Miete zahlen. Ich werde aber bei den Nebenkosten und beim Einkaufen helfen.", vn: "Không trả tiền nhà. Giúp phụ phí và mua sắm." },
      { speaker: "beamter", de: "Was machen Sie, wenn Ihre Verwandten Sie nicht mehr bei sich wohnen lassen können?", vn: "Câu 84: Nếu dì không cho ở nữa?" },
      { speaker: "antragsteller", de: "Dann werde ich ein WG-Zimmer suchen. In Berlin gibt es viele Wohngemeinschaften für Studenten. Ich kann auch das Studentenwerk um Hilfe bitten.", vn: "'WG' = Wohngemeinschaft (ở ghép). Có Studentenwerk hỗ trợ.", tip: "Có kế hoạch dự phòng cho chỗ ở rất quan trọng." },
      { speaker: "beamter", de: "Wie kommen Sie von Ihrer Unterkunft zur Sprachschule?", vn: "Câu 85: Di chuyển đến trường thế nào?" },
      { speaker: "antragsteller", de: "Von Marzahn zur Hartnackschule fahre ich mit der S-Bahn und der U-Bahn. Die Fahrt dauert etwa 40 Minuten. Ich werde ein Monatsticket kaufen.", vn: "S-Bahn + U-Bahn, 40 phút. Mua vé tháng." },
      { speaker: "beamter", de: "Warum haben Sie sich für die Hartnackschule entschieden?", vn: "Câu 86: Tại sao chọn Hartnackschule?" },
      { speaker: "antragsteller", de: "Die Hartnackschule ist seit 1915 eine der ältesten Sprachschulen Berlins. Sie bietet Intensivkurse mit kleinen Gruppen. Meine Tante hat sie mir empfohlen.", vn: "Seit 1915, lâu đời. Intensivkurse, nhóm nhỏ. Dì giới thiệu." },
      { speaker: "beamter", de: "Können Sie den Kurs pausieren oder verkürzen?", vn: "Câu 87: Có thể tạm dừng hoặc rút ngắn?" },
      { speaker: "antragsteller", de: "Nein, ich möchte den Kurs nicht pausieren oder verkürzen. Ich brauche die vollen sechs Monate, um B2 zu erreichen. Die Schule erlaubt eine Pause nur bei Krankheit.", vn: "Không muốn dừng. Cần đủ 6 tháng cho B2." },
      { speaker: "beamter", de: "Was passiert, wenn Sie kein Visum erhalten?", vn: "Câu 88: Nếu không có visa?" },
      { speaker: "antragsteller", de: "Wenn ich kein Visum bekomme, werde ich in Vietnam weiter Deutsch lernen und mich beim nächsten Termin wieder bewerben. Ich gebe meinen Traum nicht auf.", vn: "Tiếp tục học ở VN và nộp lại. 'Traum nicht aufgeben' = không bỏ ước mơ." },
      { speaker: "beamter", de: "Welchen Kurs haben Sie gebucht?", vn: "Câu 89: Đã đăng ký khóa nào?" },
      { speaker: "antragsteller", de: "Ich habe den Intensivkurs Deutsch von A2.2 bis B2 gebucht. Der Kurs beginnt am ersten April 2026 und endet am dreißigsten September 2026.", vn: "Intensivkurs A2.2→B2, 01.04.–30.09.2026." },
      { speaker: "beamter", de: "Wie finanzieren Sie Ihre Zeit in Berlin?", vn: "Câu 90: Trang trải chi phí ở Berlin thế nào?" },
      { speaker: "antragsteller", de: "Ich habe das Sperrkonto mit 11.208 Euro. Ich wohne mietfrei bei meiner Tante. Meine monatlichen Kosten sind etwa 500 Euro für Essen, Transport und Materialien. Das Geld reicht gut.", vn: "Sperrkonto + ở miễn phí → 500€/tháng chi phí → dư.", tip: "Tính toán chi tiết thể hiện sự chuẩn bị kỹ." }
    ]
  },
  phase4: {
    title: "Phase 4: Fähigkeiten & Risiken",
    description: "Năng lực, chuẩn bị, rủi ro, câu hỏi nhanh (Câu 91–114 + 30 Schnellfragen)",
    messages: [
      { speaker: "beamter", de: "Zum Schluss habe ich noch einige Fragen zu Ihren Fähigkeiten und Risiken.", vn: "Phần cuối: năng lực, chuẩn bị, rủi ro." },
      { speaker: "beamter", de: "Warum ist Ihre Note in Englisch so niedrig, nur 3,4?", vn: "Câu 91: Tại sao điểm Anh thấp (3,4)?" },
      { speaker: "antragsteller", de: "Meine Englischnote war nicht gut, weil ich in der Schule mehr auf Mathematik und Literatur konzentriert war. Aber das zeigt auch, dass ich mich auf Deutsch konzentriere und nicht nach England oder Amerika möchte.", vn: "Thừa nhận + biến thành lý do: tập trung vào Đức, không phải Anh/Mỹ." },
      { speaker: "beamter", de: "Warum haben Sie in Englisch nur eine 3,4 erhalten?", vn: "Câu 92: Tại sao chỉ 3,4 môn Anh?" },
      { speaker: "antragsteller", de: "Englisch war nicht mein starkes Fach. Aber ich habe in Deutsch viel mehr Motivation und lerne sehr fleißig. Mein B1-Ergebnis zeigt, dass ich Sprachen lernen kann, wenn ich motiviert bin.", vn: "Anh không giỏi, nhưng Đức có động lực → B1 chứng minh." },
      { speaker: "beamter", de: "Warum ist Ihre Englischnote so niedrig?", vn: "Câu 93: Tại sao điểm Anh thấp?" },
      { speaker: "antragsteller", de: "Ich hatte nicht viel Interesse an Englisch. Aber seit ich Deutsch lerne, habe ich entdeckt, dass ich Sprachen mag, wenn ich ein klares Ziel habe. Deutsch ist meine Leidenschaft.", vn: "'Leidenschaft' = đam mê. Biến điểm yếu thành điểm mạnh." },
      { speaker: "beamter", de: "Ihre Note in Literatur ist sehr gut, 8,5, aber in Englisch sehr schwach, 3,4. Warum?", vn: "Câu 94: Văn 8,5 nhưng Anh 3,4. Tại sao?" },
      { speaker: "antragsteller", de: "Literatur war mein Lieblingsfach. Ich liebe es zu lesen und zu schreiben. Englisch war für mich abstrakt, weil ich keinen konkreten Grund hatte, es zu lernen. Jetzt mit Deutsch habe ich ein klares Ziel: Erzieherin werden.", vn: "Văn yêu thích, Anh trừu tượng. Đức có mục tiêu rõ ràng." },
      { speaker: "beamter", de: "Glauben Sie, dass Sie mit einer 3,4 in Englisch die Ausbildung in Deutschland schaffen?", vn: "Câu 95: Với 3,4 Anh, có hoàn thành Ausbildung?" },
      { speaker: "antragsteller", de: "Ja, denn die Ausbildung ist auf Deutsch, nicht auf Englisch. Mein Deutsch ist B1 und wird besser. Meine guten Noten in Literatur und Mathematik zeigen, dass ich fleißig und lernfähig bin.", vn: "Ausbildung = tiếng Đức, không phải Anh. Điểm Văn/Toán chứng minh năng lực.", tip: "Tự tin nhưng không kiêu ngạo." },
      { speaker: "beamter", de: "Was sind die wichtigsten Eigenschaften einer Erzieherin?", vn: "Câu 96: Phẩm chất quan trọng nhất của Erzieherin?" },
      { speaker: "antragsteller", de: "Geduld, Einfühlungsvermögen und Kreativität. Man muss Kinder verstehen und auf ihre Bedürfnisse eingehen. Außerdem braucht man Teamfähigkeit, weil man mit Kollegen und Eltern zusammenarbeitet.", vn: "Kiên nhẫn, đồng cảm, sáng tạo, làm việc nhóm." },
      { speaker: "beamter", de: "Wie gehen Sie um, wenn ein Kind im Kindergarten ständig weint?", vn: "Câu 97: Xử lý trẻ khóc liên tục?" },
      { speaker: "antragsteller", de: "Zuerst versuche ich herauszufinden, warum das Kind weint. Dann tröste ich es und gebe ihm Sicherheit. Ich spreche ruhig und biete eine Aktivität an, die das Kind ablenkt. Geduld ist sehr wichtig.", vn: "Tìm nguyên nhân → an ủi → đánh lạc hướng. 'Trösten' = an ủi." },
      { speaker: "beamter", de: "Sind Sie gesundheitlich für die Arbeit mit Kindern geeignet?", vn: "Câu 98: Sức khỏe có đủ để làm việc với trẻ?" },
      { speaker: "antragsteller", de: "Ja, ich bin gesund. Ich habe ein ärztliches Attest mitgebracht. Ich treibe regelmäßig Sport und bin körperlich fit.", vn: "Khỏe mạnh, có giấy khám sức khỏe, chơi thể thao." },
      { speaker: "beamter", de: "Was wissen Sie über den Kinderschutz in Deutschland?", vn: "Câu 99: Biết gì về bảo vệ trẻ em ở Đức?" },
      { speaker: "antragsteller", de: "In Deutschland ist der Kinderschutz sehr streng. Kinder haben ein Recht auf gewaltfreie Erziehung. Das Jugendamt schützt Kinder vor Misshandlung und Vernachlässigung. Als Erzieherin habe ich eine Meldepflicht.", vn: "'Gewaltfreie Erziehung' = giáo dục không bạo lực. 'Meldepflicht' = nghĩa vụ báo cáo." },
      { speaker: "beamter", de: "Was wissen Sie über die Erziehung in Deutschland im Vergleich zu Vietnam?", vn: "Câu 100: So sánh giáo dục Đức-VN?" },
      { speaker: "antragsteller", de: "In Deutschland lernen Kinder durch Spielen und Entdecken. Es gibt weniger Druck als in Vietnam. Die Kinder sollen selbstständig werden. In Vietnam ist die Erziehung oft strenger und akademischer.", vn: "Đức: học qua chơi, tự lập. VN: nghiêm ngặt, học thuật hơn." },
      { speaker: "beamter", de: "Erzieher ist ein stressiger Beruf. Haben Sie davor Angst?", vn: "Câu 101: Nghề áp lực, có sợ không?" },
      { speaker: "antragsteller", de: "Nein, ich habe keine Angst. Stress gehört zu jedem Beruf. Während meines Praktikums habe ich gelernt, mit Stress umzugehen. Ich finde Freude in der Arbeit mit Kindern, und das gibt mir Energie.", vn: "Không sợ. Đã học cách xử lý stress khi thực tập." },
      { speaker: "beamter", de: "Haben Sie Angst vor der anstrengenden Ausbildung?", vn: "Câu 102: Có lo lắng về Ausbildung vất vả?" },
      { speaker: "antragsteller", de: "Ich bin bereit für die Herausforderung. Ich weiß, dass die Ausbildung anstrengend sein wird, aber ich bin motiviert. Ich habe schon bewiesen, dass ich hart arbeiten kann — ich habe B1 in eineinhalb Jahren geschafft.", vn: "Sẵn sàng. Đã chứng minh bằng B1 trong 1,5 năm." },
      { speaker: "beamter", de: "Wie werden Sie mit deutschen Eltern kommunizieren, wenn Ihr Deutsch noch nicht perfekt ist?", vn: "Câu 103: Giao tiếp với phụ huynh Đức khi tiếng Đức chưa hoàn hảo?" },
      { speaker: "antragsteller", de: "Ich werde offen und freundlich sein. Wenn ich ein Wort nicht verstehe, frage ich nach. Einfache und klare Sprache ist am wichtigsten. Außerdem werde ich mein Deutsch jeden Tag verbessern.", vn: "Cởi mở, hỏi lại khi không hiểu, ngôn ngữ đơn giản." },
      { speaker: "beamter", de: "Wie haben Sie sich auf das Leben in Deutschland vorbereitet?", vn: "Câu 104: Chuẩn bị cho cuộc sống ở Đức?" },
      { speaker: "antragsteller", de: "Ich habe viel über Deutschland gelesen. Ich kenne die Kultur, die Bürokratie und die wichtigsten Regeln. Meine Tante erzählt mir regelmäßig vom Alltag in Berlin. Außerdem lerne ich jeden Tag Deutsch.", vn: "Đọc về Đức, dì kể chuyện, học tiếng mỗi ngày." },
      { speaker: "beamter", de: "Wie haben Sie sich auf den Kulturschock in Deutschland vorbereitet?", vn: "Câu 105: Chuẩn bị cho sốc văn hóa?" },
      { speaker: "antragsteller", de: "Meine Tante hat mir erzählt, dass das Leben in Deutschland anders ist. Zum Beispiel muss man pünktlich sein und den Müll trennen. Ich finde das gut und bin darauf vorbereitet. Außerdem bin ich offen für neue Erfahrungen.", vn: "Dì đã kể: đúng giờ, phân loại rác. Sẵn sàng và cởi mở." },
      { speaker: "beamter", de: "Was wird für Sie in Deutschland die größte Herausforderung sein?", vn: "Câu 106: Thách thức lớn nhất?" },
      { speaker: "antragsteller", de: "Die größte Herausforderung wird die Sprache sein. Auch wenn ich B1 habe, ist der Alltag auf Deutsch schwieriger als im Unterricht. Aber ich bin motiviert und werde jeden Tag üben.", vn: "Ngôn ngữ = thách thức lớn nhất. Có động lực vượt qua." },
      { speaker: "beamter", de: "Was machen Sie, wenn Sie Schwierigkeiten beim Lernen in Deutschland haben?", vn: "Câu 107: Nếu gặp khó khăn khi học?" },
      { speaker: "antragsteller", de: "Dann bitte ich meine Lehrer um Hilfe. Ich kann auch Nachhilfe nehmen. Meine Tante kann mir im Alltag helfen. Und es gibt viele Online-Ressourcen zum Deutschlernen.", vn: "Nhờ giáo viên, gia sư, dì, tài nguyên online." },
      { speaker: "beamter", de: "Was werden Sie tun, wenn Sie Ihr Visum nicht bekommen?", vn: "Câu 108: Nếu không có visa?" },
      { speaker: "antragsteller", de: "Dann werde ich in Vietnam weiter Deutsch lernen und mich beim nächsten Termin wieder bewerben. Ich kann auch versuchen, über eine andere Sprachschule ein Visum zu bekommen.", vn: "Tiếp tục học ở VN, nộp lại, thử trường khác." },
      { speaker: "beamter", de: "Was machen Sie, wenn Ihr Visum abgelehnt wird?", vn: "Câu 109: Visa bị từ chối thì sao?" },
      { speaker: "antragsteller", de: "Wenn das Visum abgelehnt wird, frage ich nach dem Grund. Dann verbessere ich meine Unterlagen und bewerbe mich erneut. Ich kann auch eine Remonstration einlegen.", vn: "'Remonstration' = khiếu nại quyết định visa." },
      { speaker: "beamter", de: "Was machen Sie, wenn Sie die B2-Prüfung in Deutschland nicht bestehen?", vn: "Câu 110: Nếu không đỗ B2?" },
      { speaker: "antragsteller", de: "Dann wiederhole ich den Kurs und die Prüfung. Ich habe genug Geld für eine Verlängerung. Und ich kann zusätzlich Nachhilfe nehmen.", vn: "Lặp lại khóa + thêm gia sư. Đủ tài chính." },
      { speaker: "beamter", de: "Was machen Sie, wenn Sie das gewünschte Deutschniveau nicht erreichen?", vn: "Câu 111: Nếu không đạt trình độ mong muốn?" },
      { speaker: "antragsteller", de: "Wenn ich B2 nicht erreiche, werde ich meinen Aufenthalt verlängern und weiter lernen. Wenn das nicht möglich ist, kehre ich nach Vietnam zurück und lerne dort weiter.", vn: "Gia hạn hoặc về VN tiếp tục học. Luôn có Plan B." },
      { speaker: "beamter", de: "Was machen Sie, wenn Sie das Visum bekommen?", vn: "Câu 112: Nếu được visa?" },
      { speaker: "antragsteller", de: "Wenn ich das Visum bekomme, buche ich sofort den Flug nach Berlin. Dann melde ich mich bei der Sprachschule an und bei der Meldestelle in Marzahn. Ich freue mich sehr darauf!", vn: "Đặt vé → đăng ký trường → đăng ký cư trú. 'Meldestelle' = nơi đăng ký cư trú." },
      { speaker: "beamter", de: "Wie ist das Wetter heute?", vn: "Câu 113: Thời tiết hôm nay?" },
      { speaker: "antragsteller", de: "Heute ist es sonnig und warm, ungefähr dreißig Grad. Typisches Wetter in Vietnam.", vn: "Trả lời nhanh, tự nhiên." },
      { speaker: "beamter", de: "Welches Datum haben wir heute?", vn: "Câu 114: Hôm nay ngày mấy?" },
      { speaker: "antragsteller", de: "Heute ist der vierzehnte März zweitausendsechsundzwanzig.", vn: "Nói ngày tháng bằng tiếng Đức.", tip: "Câu hỏi nhanh kiểm tra phản xạ — trả lời không do dự." },
      { speaker: "beamter", de: "Gut. Jetzt ein paar schnelle Fragen zur Überprüfung Ihrer Sprachkenntnisse. Bitte antworten Sie spontan.", vn: "30 câu hỏi nhanh kiểm tra phản xạ ngôn ngữ A2/B1." },
      { speaker: "beamter", de: "Welcher Tag ist heute?", vn: "Schnellfrage 1: Hôm nay thứ mấy?" },
      { speaker: "antragsteller", de: "Heute ist Freitag.", vn: "Wochentage: Montag bis Sonntag." },
      { speaker: "beamter", de: "Welcher Monat ist jetzt?", vn: "Schnellfrage 2: Tháng mấy?" },
      { speaker: "antragsteller", de: "Jetzt ist März.", vn: "Monate: Januar bis Dezember." },
      { speaker: "beamter", de: "Welche Jahreszeit haben wir jetzt?", vn: "Schnellfrage 3: Mùa gì?" },
      { speaker: "antragsteller", de: "In Deutschland ist jetzt Frühling. In Vietnam ist es heiß.", vn: "Jahreszeiten: Frühling, Sommer, Herbst, Winter." },
      { speaker: "beamter", de: "Wie spät ist es jetzt?", vn: "Schnellfrage 4: Mấy giờ?" },
      { speaker: "antragsteller", de: "Es ist jetzt zehn Uhr vormittags.", vn: "'Vormittags' = buổi sáng." },
      { speaker: "beamter", de: "In welchem Jahr sind Sie geboren?", vn: "Schnellfrage 5: Sinh năm nào?" },
      { speaker: "antragsteller", de: "Ich bin im Jahr zweitausendsechs geboren.", vn: "2006." },
      { speaker: "beamter", de: "Was ist Ihre Lieblingsfarbe?", vn: "Schnellfrage 6: Màu yêu thích?" },
      { speaker: "antragsteller", de: "Meine Lieblingsfarbe ist Blau.", vn: "Farben: Rot, Blau, Grün, Gelb, Weiß, Schwarz..." },
      { speaker: "beamter", de: "Wie viele Sprachen sprechen Sie?", vn: "Schnellfrage 7: Nói bao nhiêu thứ tiếng?" },
      { speaker: "antragsteller", de: "Ich spreche zwei Sprachen: Vietnamesisch und Deutsch. Ein bisschen Englisch auch.", vn: "Vietnamesisch + Deutsch + ít Anh." },
      { speaker: "beamter", de: "Wie alt ist Ihre Mutter?", vn: "Schnellfrage 8: Mẹ bao nhiêu tuổi?" },
      { speaker: "antragsteller", de: "Meine Mutter ist fünfundvierzig Jahre alt.", vn: "'Fünfundvierzig' = 45." },
      { speaker: "beamter", de: "Wie viele Stunden schlafen Sie pro Nacht?", vn: "Schnellfrage 9: Ngủ mấy tiếng?" },
      { speaker: "antragsteller", de: "Ich schlafe ungefähr sieben Stunden pro Nacht.", vn: "'Ungefähr' = khoảng." },
      { speaker: "beamter", de: "Wie viele Personen leben in Ihrer Familie?", vn: "Schnellfrage 10: Bao nhiêu người trong gia đình?" },
      { speaker: "antragsteller", de: "Vier Personen: mein Vater, meine Mutter, mein Bruder und ich.", vn: "4 người." },
      { speaker: "beamter", de: "Was essen Sie normalerweise zum Frühstück?", vn: "Schnellfrage 11: Ăn sáng gì?" },
      { speaker: "antragsteller", de: "Zum Frühstück esse ich meistens Phở oder Brot mit Ei.", vn: "'Meistens' = thường." },
      { speaker: "beamter", de: "Wie kommen Sie zur Schule?", vn: "Schnellfrage 12: Đi đến trường bằng gì?" },
      { speaker: "antragsteller", de: "Ich fahre mit dem Motorrad zur Schule.", vn: "'Motorrad' = xe máy." },
      { speaker: "beamter", de: "Was machen Sie in Ihrer Freizeit?", vn: "Schnellfrage 13: Thời gian rảnh làm gì?" },
      { speaker: "antragsteller", de: "In meiner Freizeit lese ich Bücher und spiele Badminton.", vn: "Đọc sách + cầu lông." },
      { speaker: "beamter", de: "Welche Musik hören Sie gern?", vn: "Schnellfrage 14: Thích nhạc gì?" },
      { speaker: "antragsteller", de: "Ich höre gern Pop-Musik, vietnamesische und internationale.", vn: "Pop-Musik." },
      { speaker: "beamter", de: "Treiben Sie Sport?", vn: "Schnellfrage 15: Có chơi thể thao?" },
      { speaker: "antragsteller", de: "Ja, ich spiele Badminton und jogge manchmal.", vn: "'Joggen' = chạy bộ." },
      { speaker: "beamter", de: "Wie oft gehen Sie ins Kino?", vn: "Schnellfrage 16: Đi xem phim bao lâu?" },
      { speaker: "antragsteller", de: "Ich gehe ungefähr einmal im Monat ins Kino.", vn: "'Einmal im Monat' = 1 lần/tháng." },
      { speaker: "beamter", de: "Können Sie kochen?", vn: "Schnellfrage 17: Biết nấu ăn không?" },
      { speaker: "antragsteller", de: "Ja, ich kann kochen. Ich koche gern vietnamesische Gerichte, zum Beispiel Phở und Frühlingsrollen.", vn: "'Frühlingsrollen' = nem rán/chả giò." },
      { speaker: "beamter", de: "Wie ist das Wetter in Vietnam?", vn: "Schnellfrage 18: Thời tiết VN?" },
      { speaker: "antragsteller", de: "In Vietnam ist es meistens warm und feucht. Im Norden gibt es vier Jahreszeiten, im Süden nur zwei: Regenzeit und Trockenzeit.", vn: "'Feucht' = ẩm. 'Regenzeit' = mùa mưa." },
      { speaker: "beamter", de: "Was ist die Hauptstadt von Vietnam?", vn: "Schnellfrage 19: Thủ đô VN?" },
      { speaker: "antragsteller", de: "Die Hauptstadt von Vietnam ist Hanoi.", vn: "Hanoi = Hà Nội." },
      { speaker: "beamter", de: "Kennen Sie eine berühmte Stadt in Deutschland?", vn: "Schnellfrage 20: Biết thành phố nổi tiếng ở Đức?" },
      { speaker: "antragsteller", de: "Ja, Berlin ist die Hauptstadt von Deutschland. Und München ist auch sehr bekannt.", vn: "Berlin = thủ đô. München cũng nổi tiếng." },
      { speaker: "beamter", de: "Was wissen Sie über Berlin?", vn: "Schnellfrage 21: Biết gì về Berlin?" },
      { speaker: "antragsteller", de: "Berlin ist die größte Stadt in Deutschland mit fast vier Millionen Einwohnern. Es gibt das Brandenburger Tor, die Berliner Mauer und viele Museen.", vn: "3,7 triệu dân. Brandenburger Tor, Berliner Mauer." },
      { speaker: "beamter", de: "Welche deutschen Wörter kennen Sie schon?", vn: "Schnellfrage 22: Biết những từ Đức nào?" },
      { speaker: "antragsteller", de: "Ich kenne viele Wörter! Zum Beispiel: Kindergarten, Wanderlust, Gemütlichkeit. Das sind sogar Wörter, die auch im Englischen verwendet werden.", vn: "Kindergarten, Wanderlust, Gemütlichkeit — từ Đức dùng trong tiếng Anh." },
      { speaker: "beamter", de: "Wie fühlen Sie sich heute?", vn: "Schnellfrage 23: Hôm nay cảm thấy thế nào?" },
      { speaker: "antragsteller", de: "Ich bin ein bisschen nervös, aber auch froh, dass ich hier bin.", vn: "'Nervös' = hồi hộp. 'Froh' = vui." },
      { speaker: "beamter", de: "Sind Sie nervös?", vn: "Schnellfrage 24: Có hồi hộp không?" },
      { speaker: "antragsteller", de: "Ja, ein bisschen. Aber ich habe mich gut vorbereitet und bin zuversichtlich.", vn: "'Zuversichtlich' = tự tin." },
      { speaker: "beamter", de: "Sind Sie müde?", vn: "Schnellfrage 25: Có mệt không?" },
      { speaker: "antragsteller", de: "Nein, ich bin nicht müde. Ich habe gut geschlafen.", vn: "'Müde' = mệt. 'Gut geschlafen' = ngủ ngon." },
      { speaker: "beamter", de: "Freuen Sie sich auf Deutschland?", vn: "Schnellfrage 26: Có vui mừng đến Đức không?" },
      { speaker: "antragsteller", de: "Ja, ich freue mich sehr! Ich kann es kaum erwarten, nach Berlin zu fliegen und meine Tante zu sehen.", vn: "'Ich kann es kaum erwarten' = tôi nóng lòng chờ đợi." },
      { speaker: "beamter", de: "Lernen Sie gern Deutsch?", vn: "Schnellfrage 27: Có thích học Đức không?" },
      { speaker: "antragsteller", de: "Ja, ich lerne sehr gern Deutsch. Die Sprache ist manchmal schwer, aber sie macht mir Spaß.", vn: "'Spaß machen' = vui, thú vị." },
      { speaker: "beamter", de: "Was war Ihr Lieblingsfach in der Schule?", vn: "Schnellfrage 28: Môn yêu thích?" },
      { speaker: "antragsteller", de: "Mein Lieblingsfach war Literatur. Ich habe eine 8,5 in Literatur bekommen.", vn: "Văn học = 8,5 điểm." },
      { speaker: "beamter", de: "Wie viele Stunden lernen Sie Deutsch pro Tag?", vn: "Schnellfrage 29: Học Đức mấy tiếng/ngày?" },
      { speaker: "antragsteller", de: "Ich lerne sechs Stunden pro Tag: vier Stunden im Kurs und zwei Stunden zu Hause.", vn: "6 giờ: 4 trên lớp + 2 ở nhà." },
      { speaker: "beamter", de: "Haben Sie einen Lieblingslehrer?", vn: "Schnellfrage 30: Có giáo viên yêu thích?" },
      { speaker: "antragsteller", de: "Ja, meine Deutschlehrerin Frau Nguyen. Sie ist sehr geduldig und motiviert mich immer weiterzulernen.", vn: "'Geduldig' = kiên nhẫn. 'Motivieren' = tạo động lực." },
      { speaker: "beamter", de: "Vielen Dank, Frau Pham. Ihr Deutsch ist gut. Wir werden Ihren Antrag prüfen. Sie bekommen in vier bis sechs Wochen eine Antwort. Auf Wiedersehen.", vn: "Kết thúc phỏng vấn. 'Antrag prüfen' = xem xét đơn. 4-6 tuần chờ kết quả." },
      { speaker: "antragsteller", de: "Vielen Dank, Herr Weber. Ich freue mich auf Ihre Antwort. Auf Wiedersehen und einen schönen Tag noch!", vn: "Cảm ơn lịch sự. 'Einen schönen Tag noch' = chúc ngày tốt lành.", tip: "Ấn tượng cuối cùng rất quan trọng!" }
    ]
  }
};

function getPrompt(mode, withVNFeedback, telcPart = null, embassyPhase = null) {
  if (mode === 'telc') {
    let prompt = getTELCPrompt(telcPart || 'teil1');
    if (withVNFeedback) {
      return prompt + " Format: Deutsche Antwort ZUERST, dann neue Zeile [FEEDBACK]: Feedback auf Vietnamesisch mit B1-spezifischen Tipps. Max 100 Wörter.";
    } else {
      return prompt + " Antworte nur auf Deutsch, kein vietnamesisches Feedback.";
    }
  }

  if (mode === 'embassy' && embassyPhase) {
    let prompt = getEmbassyPrompt(embassyPhase);
    if (withVNFeedback) {
      return prompt + " Format: Antwort auf Deutsch ZUERST, dann neue Zeile [FEEDBACK]: Bewerte auf Vietnamesisch ob die Antwort überzeugend für den Beamten ist. Gib konkrete Verbesserungsvorschläge. Max 80 Wörter.";
    } else {
      return prompt + " Antworte nur auf Deutsch, kein vietnamesisches Feedback.";
    }
  }

  const base = {
    embassy: "Du simulierst einen deutschen Botschaftsbeamten. Führe Visuminterview auf Deutsch. ANTWORT-ÜBERPRÜFUNG: Wenn die Antwort zu kurz ist (unter 5 Wörter) oder nicht zur Frage passt, wiederhole die Frage und gib eine Beispielantwort in Klammern. Beispiel: 'Ich brauche mehr Details. (Sie könnten sagen: \"Ich möchte ein Studienvisum beantragen, weil...\")'",
    grammar: "Du bist B1 Grammatiklehrer. Übe Konjunktiv II, Passiv, Relativsätze, Perfekt vs Präteritum. ANTWORT-ÜBERPRÜFUNG: Wenn die Antwort zu kurz ist oder grammatisch nicht zur Aufgabe passt, gib die korrekte Antwort als Beispiel und stelle eine neue ähnliche Aufgabe."
  };

  if (withVNFeedback) {
    return {
      embassy: base.embassy + " Format: Antwort ZUERST, dann neue Zeile [FEEDBACK]: Feedback auf Vietnamesisch. Max 80 Wörter.",
      grammar: base.grammar + " Format: Aufgabe ZUERST, dann [FEEDBACK]: Erklärung auf Vietnamesisch. Max 80 Wörter."
    }[mode];
  } else {
    return {
      embassy: base.embassy + " Antworte nur auf Deutsch, kein vietnamesisches Feedback.",
      grammar: base.grammar + " Antworte nur auf Deutsch, kein vietnamesisches Feedback."
    }[mode];
  }
}

function getTELCPrompt(part) {
  const prompts = {
    teil1: `Du bist offizieller TELC B1 Prüfer für Teil 1: Kontaktaufnahme (3-4 Minuten).

TELC B1 BEWERTUNGSKRITERIEN:
- Inhalt/Ausdruck: Rolle erfüllen, Wortschatz, Sprechabsicht
- Kommunikationsstrategien: Flüssigkeit, Kompensation bei Wortfindung
- Grammatik: Morphologie und Satzverknüpfung (Konnektoren wichtig!)
- Aussprache: Verständlichkeit über Perfektion

GESPRÄCHSFÜHRUNG:
- Stelle persönliche Fragen systematisch: Name, Herkunft, Wohnsituation, Familie, Beruf/Studium, Sprachen, Reisen
- Ermutige ausführliche Antworten: "Erzählen Sie mehr..."
- Bei kurzen Antworten nachfragen: "Wie ist das für Sie?"
- Verwende B1-Niveau Sprache, keine komplexen Strukturen
- Achte auf natürlichen Gesprächsfluss

ANTWORT-ÜBERPRÜFUNG (IMMER prüfen!):
- Wenn die Antwort zu kurz ist (weniger als 2 Sätze oder unter 5 Wörter):
  → Gib 1-2 Beispielantworten als Vorschlag in Klammern
  → Beispiel: Frage "Woher kommen Sie?" → Antwort "Vietnam" → Sage: "Ah, Vietnam! Erzählen Sie mehr! (Zum Beispiel: 'Ich komme aus Vietnam, aus Ho-Chi-Minh-Stadt. Das ist eine große Stadt im Süden.')"
- Wenn die Antwort nicht zur Frage passt:
  → Wiederhole die Frage freundlich und gib eine Beispielantwort
  → Beispiel: "Ich glaube, ich habe nach Ihrem Beruf gefragt. (Sie könnten sagen: 'Ich arbeite als... bei...' oder 'Ich studiere... an der Universität...')"
- Ermutige IMMER zu vollständigen Sätzen statt einzelner Wörter

TELC-SPEZIFISCH: Kommunikationsfähigkeit wichtiger als Grammatikperfektion!`,

    teil2: `Du bist Kandidat B in einer TELC B1 mündlichen Prüfung, Teil 2: Gespräch über ein Thema (5-6 Minuten).

DEINE ROLLE: Du bist ein anderer Prüfungsteilnehmer (NICHT der Prüfer, NICHT ein Lehrer).
Du diskutierst gleichberechtigt mit deinem Gesprächspartner über das Thema.

GESPRÄCHSVERHALTEN:
- Teile deine eigene Meinung zum Thema
- Stimme manchmal zu: "Da hast du Recht", "Das sehe ich genauso"
- Widersprich manchmal höflich: "Ich sehe das anders", "Da bin ich anderer Meinung"
- Frage nach der Meinung des Partners: "Was denkst du?", "Wie siehst du das?"
- Bringe eigene Erfahrungen ein: "Bei mir ist das so..."
- Verwende B1-Strukturen: weil, obwohl, deshalb, einerseits...andererseits

ANTWORT-ÜBERPRÜFUNG (IMMER prüfen!):
- Wenn der Partner zu kurz antwortet (weniger als 2 Sätze oder unter 5 Wörter):
  → Reagiere kurz auf das Gesagte, dann schlage Formulierungen vor
  → Beispiel: Antwort "Ja, stimmt" → "Ja, das stimmt! Aber kannst du das genauer erklären? (Du könntest zum Beispiel sagen: 'Ich finde, dass... weil...' oder 'Meiner Meinung nach ist es wichtig, dass...')"
- Wenn die Antwort nicht zum Thema passt:
  → Lenke freundlich zurück zum Thema und schlage passende Sätze vor
  → Beispiel: "Hmm, ich glaube, wir sollten über [Thema] sprechen. (Du könntest sagen: 'Was ich zu dem Thema denke, ist...' oder 'Ich habe die Erfahrung gemacht, dass...')"
- Stelle IMMER eine Nachfrage, wenn die Antwort zu kurz war

WICHTIG:
- Du bist KEIN Lehrer und KEIN Bewerter - du bist ein gleichwertiger Gesprächspartner
- Sprich auf B1-Niveau (nicht zu einfach, nicht zu komplex)
- Halte deine Antworten kurz (2-4 Sätze), damit der Partner auch sprechen kann
- Duze den Partner (ihr seid beide Kandidaten)`,

    teil3: `Du bist Kandidat B in einer TELC B1 mündlichen Prüfung, Teil 3: Gemeinsam etwas planen (5-6 Minuten).

DEINE ROLLE: Du bist ein anderer Prüfungsteilnehmer (NICHT der Prüfer, NICHT ein Lehrer).
Ihr plant gemeinsam eine Aktivität.

PLANUNGSVERHALTEN:
- Mache eigene Vorschläge: "Wie wäre es, wenn wir...", "Ich schlage vor..."
- Reagiere auf Vorschläge des Partners: zustimmen, ergänzen, oder Alternativen vorschlagen
- Verteile Aufgaben: "Könntest du... übernehmen?", "Ich könnte mich um... kümmern"
- Arbeite auf eine gemeinsame Lösung hin
- Fasse am Ende zusammen, wenn passend

ANTWORT-ÜBERPRÜFUNG (IMMER prüfen!):
- Wenn der Partner zu kurz antwortet (weniger als 2 Sätze oder unter 5 Wörter):
  → Reagiere kurz, dann schlage konkrete Formulierungen vor
  → Beispiel: Antwort "Ok" → "Ok, aber was genau schlägst du vor? (Du könntest sagen: 'Wie wäre es, wenn wir am Samstag...' oder 'Ich schlage vor, dass wir zuerst...')"
- Wenn die Antwort nicht zum Planungsthema passt:
  → Lenke zurück und gib Beispiele für passende Vorschläge
  → Beispiel: "Lass uns weiter planen! (Du könntest sagen: 'Ich könnte mich um... kümmern' oder 'Wollen wir... am... machen?')"
- Ermutige IMMER zu konkreten Details: Wann? Wo? Was? Wer macht was?

WICHTIG:
- Du bist KEIN Lehrer und KEIN Bewerter - du bist ein gleichwertiger Planungspartner
- Sprich auf B1-Niveau
- Halte deine Antworten kurz (2-4 Sätze)
- Duze den Partner
- Bringe praktische Details ein: Zeit, Ort, Kosten, Aufgabenverteilung`
  };

  return prompts[part] || prompts.teil1;
}

function getEmbassyPrompt(phase) {
  const prompts = {
    phase1: `Du bist ein deutscher Botschaftsbeamter (Sachbearbeiter) bei einem Sprachvisum-Interview. Phase 1: Persönliche Daten.

ROLLE: Formell, professionell, Sie-Form. Stelle EINE Frage auf einmal. Warte auf die Antwort, bevor du die nächste Frage stellst.

FRAGEN FÜR DIESE PHASE (stelle sie natürlich, nicht als Liste):
1. Wie heißen Sie? Wie alt sind Sie?
2. Was ist Ihr Familienstand? Haben Sie Kinder?
3. Wo wohnen Sie derzeit?
4. Was haben Sie studiert? Welchen Abschluss haben Sie?
5. Was arbeiten Sie zurzeit? Seit wann?
6. Was machen Sie in Ihrer Freizeit?
7. Haben Sie Geschwister? Was machen Ihre Eltern beruflich?
8. Waren Sie schon einmal im Ausland?

VERHALTEN:
- Sei höflich aber sachlich, wie ein echter Beamter
- Stelle Nachfragen, wenn Antworten vage oder zu kurz sind
- Zeige angemessenes Interesse, aber keine übermäßige Freundlichkeit

ANTWORT-ÜBERPRÜFUNG:
- Wenn die Antwort zu kurz ist (unter 5 Wörter): Sage "Können Sie das genauer erklären?" und gib eine Beispielantwort in Klammern.
  Beispiel: Frage "Was arbeiten Sie?" → Antwort "IT" → "IT ist ein weites Feld. Können Sie das genauer beschreiben? (Sie könnten sagen: 'Ich arbeite als Softwareentwickler bei der Firma... seit zwei Jahren.')"
- Wenn die Antwort nicht zur Frage passt: Wiederhole die Frage freundlich.`,

    phase2: `Du bist ein deutscher Botschaftsbeamter bei einem Sprachvisum-Interview. Phase 2: Sprachkurs und Motivation.

ROLLE: Formell, Sie-Form. Stelle EINE Frage auf einmal. Sei etwas prüfender als in Phase 1 - du willst die Ernsthaftigkeit der Motivation einschätzen.

FRAGEN FÜR DIESE PHASE:
1. Welches Deutsch-Niveau haben Sie? Haben Sie ein Zertifikat?
2. Wo haben Sie Deutsch gelernt? Wie lange?
3. Warum wollen Sie nach Deutschland? Was ist Ihre Motivation?
4. Warum gerade Deutschland und nicht ein anderes Land?
5. Haben Sie sich über Sprachkurse in Deutschland informiert? Welche?
6. An welcher Sprachschule möchten Sie Ihren Kurs machen?
7. Was möchten Sie nach dem Sprachkurs machen?
8. Kennen Sie jemanden in Deutschland?

VERHALTEN:
- Hinterfrage die Motivation kritisch: "Warum genau Deutschland?"
- Bei vagen Antworten nachhaken: "Das klingt etwas allgemein. Was genau meinen Sie?"
- Prüfe, ob der Antragsteller sich wirklich informiert hat

ANTWORT-ÜBERPRÜFUNG:
- Zu kurze Antworten: "Ich brauche mehr Details." + Beispielantwort in Klammern.
- Unklare Motivation: "Das überzeugt mich noch nicht ganz. Können Sie konkreter werden?"
  Beispiel: "Ich mag Deutschland" → "Das freut mich, aber ich brauche einen konkreteren Grund. (Sie könnten sagen: 'Ich möchte an der TU München Informatik studieren, und dafür brauche ich C1-Deutschkenntnisse.')"`,

    phase3: `Du bist ein deutscher Botschaftsbeamter bei einem Sprachvisum-Interview. Phase 3: Pläne und Finanzen.

ROLLE: Formell, Sie-Form. Stelle EINE Frage auf einmal. Sei in dieser Phase BESONDERS SKEPTISCH und genau - Finanzen und konkrete Pläne sind der kritischste Teil des Interviews.

FRAGEN FÜR DIESE PHASE:
1. Wie finanzieren Sie Ihren Aufenthalt in Deutschland?
2. Haben Sie ein Sperrkonto? Wie viel Geld ist darauf?
3. Wer hat das Geld eingezahlt? Woher kommt das Geld?
4. Wo werden Sie in Deutschland wohnen? Haben Sie schon eine Unterkunft?
5. Haben Sie eine Krankenversicherung für Deutschland?
6. Wie lange planen Sie in Deutschland zu bleiben?
7. Was machen Sie, wenn das Geld nicht reicht?
8. Haben Sie einen Mietvertrag oder eine Wohnungsbestätigung?

VERHALTEN:
- Sei STRENG bei finanziellen Fragen - das ist der wichtigste Teil
- Hake nach bei unklaren Geldquellen: "Wie können Ihre Eltern das finanzieren? Was arbeiten sie?"
- Prüfe auf Widersprüche in den Angaben
- Zeige professionelle Skepsis: "Das müssen Sie nachweisen können."

ANTWORT-ÜBERPRÜFUNG:
- Ungenaue Finanzangaben: "Das reicht mir so nicht. Ich brauche genaue Zahlen."
  Beispiel: "Meine Eltern zahlen" → "Wie genau? Haben Sie eine Verpflichtungserklärung? Wie hoch ist das monatliche Einkommen Ihrer Eltern? (Sie könnten sagen: 'Mein Vater ist Ingenieur und verdient... pro Monat. Er hat eine Verpflichtungserklärung unterschrieben.')"
- Fehlende Dokumente: "Haben Sie einen Nachweis dafür?"`,

    phase4: `Du bist ein deutscher Botschaftsbeamter bei einem Sprachvisum-Interview. Phase 4: Fähigkeiten und Risiken.

ROLLE: Formell, Sie-Form. Stelle EINE Frage auf einmal. Diese Phase testet die Rückkehrbereitschaft und prüft auf Einwanderungsabsichten.

FRAGEN FÜR DIESE PHASE:
1. Was qualifiziert Sie besonders für ein Sprachvisum?
2. Was werden Sie nach dem Sprachkurs / Studium machen?
3. Planen Sie, nach Deutschland zurückzukehren? Warum?
4. Was bindet Sie an Ihr Heimatland?
5. Haben Sie dort einen Job, auf den Sie zurückkehren?
6. Was machen Sie, wenn Sie den Sprachkurs nicht bestehen?
7. Was machen Sie, wenn Ihr Visum nicht verlängert wird?
8. Möchten Sie langfristig in Deutschland bleiben?

SCHNELLE NACHFRAGEN (stelle 2-3 davon spontan):
- "Haben Sie schon ein Rückflugticket?"
- "Haben Sie Immobilien in Ihrem Heimatland?"
- "Wann haben Sie Ihren letzten Job gekündigt?"
- "Haben Sie Familie in Deutschland?"
- "Wie gut sprechen Sie wirklich Deutsch? Erzählen Sie mir etwas auf Deutsch über Ihre Stadt."

VERHALTEN:
- Sei direkt und stelle auch unbequeme Fragen
- Teste die Rückkehrbereitschaft: "Was genau zieht Sie zurück in Ihr Heimatland?"
- Stelle spontane Fragen, um die Reaktionsfähigkeit zu testen
- Sei professionell aber bestimmt

ANTWORT-ÜBERPRÜFUNG:
- Vage Rückkehrpläne: "Das klingt nicht sehr überzeugend. Was konkret haben Sie in Ihrem Heimatland?"
  Beispiel: "Ich komme zurück" → "Warum? Was genau wartet auf Sie? (Sie könnten sagen: 'Ich habe eine feste Stelle bei... die auf mich wartet' oder 'Meine Familie hat ein Geschäft, das ich übernehmen werde.')"
- Widersprüche: Weise höflich auf Unstimmigkeiten hin.`
  };

  return prompts[phase] || prompts.phase1;
}

let API_KEY="",mode=null,msgs=[],autoSpeak=true,vietnameseFeedback=true;
let isRec=false,recSec=0,recTimer=null,speakIdx=-1,recognition=null,waveAnim=null,waveT=0,isSpeaking=false;
let isMobile=false,audioUnlocked=false,localTTSFailed=false;
let autoStopTimer=null; // Global timer for auto-stopping recording
let sessionId=generateSessionId(); // Unique session for this chat
let currentTELCPart=null; // Track current TELC part (teil1, teil2, teil3)
let ttsSpeed = 1.2; // Default TTS speed (can be adjusted)

// Embassy interview state
let currentEmbassyPhase = null; // Track current embassy phase (phase1-phase4)
let embassySimulationMode = false;
let embassySimPhaseStart = {}; // {phase1: msgIndex, phase2: msgIndex, ...}
let embassyUserMsgCount = 0; // Count user messages in current phase for advance hint

// TELC Timer System
let telcTimer = null;
let telcTimeLeft = 0;
let telcTimerStarted = false;
let telcTimeWarningShown = false;

// Simulation mode state
let telcSimulationMode = false;
let telcSimTeilStart = {}; // {teil1: msgIndex, teil2: msgIndex, teil3: msgIndex}

function generateSessionId(){
  return 'session_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9);
}

async function saveMessageToDB(role, content){
  try{
    const response = await fetch("/save-message", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        session_id: sessionId,
        role: role,
        content: content,
        mode: mode || "unknown"
      })
    });
    if(!response.ok){
      console.warn("Failed to save message:", await response.text());
    }
  }catch(e){
    console.warn("Error saving message:", e);
  }
}

function initApp(){
  const k=document.getElementById("apiKeyInput").value.trim();
  const errEl=document.getElementById("apiErr");
  if(!k){errEl.textContent="Vui lòng nhập API key.";return;}
  if(!k.startsWith("sk-or")||k.length<20){errEl.textContent="Key không hợp lệ — OpenRouter key bắt đầu bằng sk-or-...";return;}
  API_KEY=k; errEl.textContent="";
  document.getElementById("apiScreen").style.display="none";
  const app=document.getElementById("app");
  app.style.display="flex";app.style.flexDirection="column";
  window.speechSynthesis?.getVoices();
  if(window.speechSynthesis) window.speechSynthesis.onvoiceschanged=()=>window.speechSynthesis.getVoices();
}
// Mobile detection and audio setup
function detectMobile(){
  isMobile = /Android|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(navigator.userAgent) ||
             (navigator.maxTouchPoints && navigator.maxTouchPoints > 2);
  console.log("Mobile detected:", isMobile);
}

function unlockAudio(){
  if(audioUnlocked) return Promise.resolve();

  return new Promise((resolve)=>{
    // Create silent audio context to unlock
    const AudioContext = window.AudioContext || window.webkitAudioContext;
    if(AudioContext){
      const ctx = new AudioContext();
      const buffer = ctx.createBuffer(1, 1, 22050);
      const source = ctx.createBufferSource();
      source.buffer = buffer;
      source.connect(ctx.destination);
      source.start(0);
      ctx.resume().then(()=>{
        audioUnlocked = true;
        console.log("Audio unlocked");
        if(isMobile) updateMobileDebug();
        resolve();
      });
    }

    // Also unlock speech synthesis
    if(window.speechSynthesis){
      const utterance = new SpeechSynthesisUtterance("");
      utterance.volume = 0;
      window.speechSynthesis.speak(utterance);
    }

    setTimeout(()=>{
      audioUnlocked = true;
      if(isMobile) updateMobileDebug();
      resolve();
    }, 100);
  });
}

document.addEventListener("DOMContentLoaded",()=>{
  detectMobile();

  document.getElementById("apiKeyInput").addEventListener("keydown",e=>{if(e.key==="Enter")initApp();});
  document.getElementById("txtIn").addEventListener("keydown",e=>{if(e.key==="Enter"&&!e.shiftKey){e.preventDefault();sendMessage();}});

  // Mobile touch handlers for audio unlock
  if(isMobile){
    const unlockEvents = ['touchstart', 'touchend', 'click'];
    const unlockHandler = ()=>{
      unlockAudio().then(()=>{
        unlockEvents.forEach(event=>{
          document.removeEventListener(event, unlockHandler);
        });
      });
    };

    unlockEvents.forEach(event=>{
      document.addEventListener(event, unlockHandler, {once: true, passive: true});
    });
  }
});

function selectMode(m){
  // Unlock audio on mobile when user selects mode (user gesture)
  if(isMobile && !audioUnlocked){
    unlockAudio().then(()=>{
      console.log("Audio unlocked via mode selection");
    });
  }

  // Start new session
  sessionId = generateSessionId();
  mode=m;msgs=[];speakIdx=-1;
  currentTELCPart=null; // Reset TELC part
  currentEmbassyPhase=null; // Reset embassy phase
  embassySimulationMode=false;
  embassySimPhaseStart={};
  embassyUserMsgCount=0;
  const c=COLORS[m];
  document.getElementById("landing").style.display="none";
  const ch=document.getElementById("chat");ch.style.display="flex";ch.style.flexDirection="column";
  document.getElementById("modeTitle").textContent=LABELS[m];
  document.getElementById("chatHeader").style.borderBottomColor=c+"33";
  document.getElementById("turnCount").textContent="0 lượt trả lời";
  if(m === 'telc') {
    document.getElementById("topics").innerHTML=`
      <button class="topic-btn" onclick="startTELCPart('teil1')" style="background:rgba(59,130,246,0.1);border-color:rgba(59,130,246,0.3);">Teil 1: Kontaktaufnahme</button>
      <button class="topic-btn" onclick="showTopicPicker('teil2')" style="background:rgba(16,185,129,0.1);border-color:rgba(16,185,129,0.3);">Teil 2: Gespräch über Thema</button>
      <button class="topic-btn" onclick="showTopicPicker('teil3')" style="background:rgba(251,191,36,0.1);border-color:rgba(251,191,36,0.3);">Teil 3: Gemeinsam planen</button>
      <button class="topic-btn" onclick="startFullSimulation()" style="background:rgba(239,68,68,0.1);border-color:rgba(239,68,68,0.3);color:#f87171;font-weight:600;">🏆 Simulation (1→2→3)</button>
    `;
  } else if(m === 'embassy') {
    document.getElementById("topics").innerHTML=`
      <button class="topic-btn" onclick="startEmbassyPhase('phase1')" style="background:rgba(168,85,247,0.1);border-color:rgba(168,85,247,0.3);">Phase 1: Persönliche Daten</button>
      <button class="topic-btn" onclick="startEmbassyPhase('phase2')" style="background:rgba(59,130,246,0.1);border-color:rgba(59,130,246,0.3);">Phase 2: Sprachkurs & Motivation</button>
      <button class="topic-btn" onclick="startEmbassyPhase('phase3')" style="background:rgba(251,191,36,0.1);border-color:rgba(251,191,36,0.3);">Phase 3: Pläne & Finanzen</button>
      <button class="topic-btn" onclick="startEmbassyPhase('phase4')" style="background:rgba(239,68,68,0.1);border-color:rgba(239,68,68,0.3);">Phase 4: Fähigkeiten & Risiken</button>
      <button class="topic-btn" onclick="startFullEmbassyInterview()" style="background:rgba(34,197,94,0.1);border-color:rgba(34,197,94,0.3);color:#22c55e;font-weight:600;">🏛️ Vollständiges Interview (1→2→3→4)</button>
    `;
  } else {
    document.getElementById("topics").innerHTML=TOPICS[m].map(t=>
      `<button class="topic-btn" onclick="sendMsg('Lass uns über &quot;${t}&quot; sprechen.')">${t}</button>`).join("");
  }
  const mb=document.getElementById("micBtn");
  mb.style.background=`linear-gradient(135deg,${c},${c}88)`;
  mb.style.boxShadow=`0 4px 14px ${c}44`;
  document.getElementById("sndBtn").style.background=`linear-gradient(135deg,${c},${c}99)`;
  const hasStt=!!(window.SpeechRecognition||window.webkitSpeechRecognition);
  document.getElementById("sttWarn").style.display=hasStt?"none":"block";

  // Show mobile warning if on mobile
  document.getElementById("mobileWarn").style.display=isMobile?"block":"none";

  // Mobile debug info
  if(isMobile){
    updateMobileDebug();
    setupMobileAudioTest();
  }

  updateTTSBtn();
  updateVNBtn();
  document.getElementById("messages").innerHTML="";

  // Show/hide phrase bank button
  document.getElementById("phraseBankBtn").style.display = (m === 'telc' || m === 'embassy') ? "inline-block" : "none";

  if(m === 'telc') {
    // For TELC, don't start with generic message, wait for Teil selection
    const welcomeMsg = "Willkommen zur TELC B1 mündlichen Prüfung! Wählen Sie einen Teil aus, um zu beginnen:";
    addBubble("assistant", welcomeMsg, 0);
    if(autoSpeak) speak(welcomeMsg, 0);
  } else if(m === 'embassy') {
    // For embassy, wait for phase selection
    const welcomeMsg = "Willkommen beim Visa-Interview! Wählen Sie eine Phase aus oder starten Sie das vollständige Interview:";
    addBubble("assistant", welcomeMsg, 0);
    if(autoSpeak) speak(welcomeMsg, 0);
  } else {
    // For other modes, use standard starter
    const s=STARTERS[m];
    msgs.push({role:"assistant",content:s});
    addBubble("assistant",s,0);
    saveMessageToDB("assistant", s);
    if(autoSpeak) speak(s,0);
  }
}

function goBack(){
  // Stop all audio
  stopAllSpeech();

  if(isRec)stopRec(false); // Don't auto-send when going back

  // Reset states
  mode=null;msgs=[];
  currentTELCPart=null; // Reset TELC part
  currentEmbassyPhase=null; // Reset embassy phase
  embassySimulationMode=false;
  embassySimPhaseStart={};
  embassyUserMsgCount=0;

  // Reset simulation mode
  telcSimulationMode = false;
  telcSimTeilStart = {};

  // Stop TELC timer
  stopTELCTimer();

  // Switch UI
  document.getElementById("chat").style.display="none";
  const l=document.getElementById("landing");l.style.display="flex";l.style.flexDirection="column";
  document.getElementById("messages").innerHTML="";
  document.getElementById("txtIn").value=""; // Clear input
  setStatus("idle");

  // Hide score button and phrase bank
  document.getElementById("scoreBtn").style.display = "none";
  document.getElementById("phraseBankBtn").style.display = "none";
  document.getElementById("phraseBankPanel").classList.remove("open");
}

function addBubble(role,content,idx){
  // Partner mode routing: AI replies in Teil 2/3 render as Kandidat B
  if(role === "assistant" && (currentTELCPart === 'teil2' || currentTELCPart === 'teil3')) {
    addBubblePartner("kandidatB", content, idx);
    return;
  }
  const c=COLORS[mode]||"#3b82f6",isUser=role==="user";
  const parts=content.split(/\[FEEDBACK\]:/i);
  const main=parts[0].trim(),fb=parts.slice(1).join("").trim();
  const wrap=document.createElement("div");wrap.className=`bwrap ${isUser?"user":"ai"}`;
  const row=document.createElement("div");row.className="brow";
  if(!isUser){
    const av=document.createElement("div");av.className="av";
    av.style.cssText=`background:${c}22;border:1.5px solid ${c}55;`;av.textContent="🤖";row.appendChild(av);
  }
  const bub=document.createElement("div");bub.className=`bub ${isUser?"user":"ai"}`;
  if(isUser){bub.style.background=`linear-gradient(135deg,${c}dd,${c}99)`;bub.style.boxShadow=`0 4px 18px ${c}44`;}
  bub.textContent=main;row.appendChild(bub);
  if(!isUser){
    const btn=document.createElement("button");btn.className="spkbtn";
    btn.id=`spk${idx}`;btn.textContent="🔊";
    btn.style.color=c;btn.style.setProperty("--c",c);

    // Mobile-friendly event handlers
    if(isMobile){
      btn.addEventListener('touchstart', async (e) => {
        e.preventDefault();
        if(!audioUnlocked) await unlockAudio();
        speak(content,idx);
      });
      btn.addEventListener('click', (e) => {
        e.preventDefault(); // Prevent double-firing on mobile
      });
    } else {
      btn.onclick=()=>speak(content,idx);
    }

    row.appendChild(btn);
  }
  wrap.appendChild(row);
  if(fb && vietnameseFeedback){
    const d=document.createElement("div");d.className="fb";
    d.innerHTML=`💡 <strong>Phản hồi:</strong> ${esc(fb)}`;wrap.appendChild(d);
  }
  const el=document.getElementById("messages");el.appendChild(wrap);el.scrollTop=el.scrollHeight;

  // Update score button visibility after adding message
  updateScoreButtonVisibility();
}

function showTyping(){
  const c=COLORS[mode]||"#3b82f6";
  const d=document.createElement("div");d.className="typing-row";d.id="typing";
  d.innerHTML=`<div class="av" style="background:${c}22;border:1.5px solid ${c}55">🤖</div>`+
    [0,.2,.4].map(dl=>`<div class="dot" style="background:${c};animation-delay:${dl}s"></div>`).join("")+
    `<span>Đang soạn...</span>`;
  const el=document.getElementById("messages");el.appendChild(d);el.scrollTop=el.scrollHeight;
}
function hideTyping(){document.getElementById("typing")?.remove();}
function esc(s){const d=document.createElement("div");d.textContent=s;return d.innerHTML;}

// Gọi OpenRouter API qua local proxy
async function callAPI(messages, systemOverride){
  const systemPrompt = systemOverride || getPrompt(mode, vietnameseFeedback, currentTELCPart, currentEmbassyPhase);
  const res=await fetch("/api",{
    method:"POST",
    headers:{"Content-Type":"application/json","X-Api-Key":API_KEY},
    body:JSON.stringify({system:systemPrompt,messages}),
  });
  const raw=await res.text();
  let data;
  try{ data=JSON.parse(raw); }
  catch(e){ throw new Error("Server trả về dữ liệu không hợp lệ: "+raw.slice(0,100)); }
  console.log("API response:", data);
  if(data.error){
    const msg=typeof data.error==="object"?data.error.message:String(data.error);
    throw new Error(msg);
  }
  // Support both {text:...} and {choices:[...]} formats
  if(data.text) return data.text;
  if(data.choices && data.choices[0]) return data.choices[0].message?.content||data.choices[0].text||"";
  throw new Error("Không parse được response: "+JSON.stringify(data).slice(0,150));
}

async function sendMsg(content){
  if(!content||!mode)return;

  // Stop any current speech when sending new message
  stopAllSpeech();

  const idx=msgs.length;
  msgs.push({role:"user",content});
  addBubble("user",content,idx);
  document.getElementById("turnCount").textContent=`${msgs.filter(m=>m.role==="user").length} lượt trả lời`;
  document.getElementById("txtIn").value="";

  // Save user message to database
  saveMessageToDB("user", content);

  // Check if answer is too short and build enhanced prompt
  let systemPrompt = null;
  const wordCount = content.trim().split(/\s+/).length;
  if (wordCount < 5) {
    systemPrompt = getPrompt(mode, vietnameseFeedback, currentTELCPart, currentEmbassyPhase);
    const lastAI = msgs.filter(m => m.role === 'assistant').slice(-1)[0];
    const lastQuestion = lastAI ? lastAI.content.replace(/\[FEEDBACK\][\s\S]*/i, '').trim() : '';
    systemPrompt += `\n\nWICHTIG: Die letzte Antwort des Kandidaten war SEHR KURZ (nur ${wordCount} Wörter: "${content}"). ` +
      `Bitte reagiere auf die Antwort, gib 1-2 Beispielantworten als Vorschlag (in Klammern), und stelle eine Nachfrage. ` +
      (lastQuestion ? `Die vorherige Frage/Aussage war: "${lastQuestion.slice(0, 150)}"` : '');
  }

  showTyping();
  try{
    const reply=await callAPI(msgs.map(m=>({role:m.role,content:m.content})), systemPrompt);
    hideTyping();
    const ai=msgs.length;msgs.push({role:"assistant",content:reply});
    addBubble("assistant",reply,ai);

    // Save AI reply to database
    saveMessageToDB("assistant", reply);

    if(autoSpeak)speak(reply,ai);

    // Embassy: check if we should show advance hint
    if(mode === 'embassy' && currentEmbassyPhase) {
      maybeShowEmbassyAdvanceHint();
    }
  }catch(e){
    hideTyping();
    const ei=msgs.length;
    let errorMsg = `⚠️ Lỗi kết nối AI: ${e.message}`;

    // Provide helpful guidance based on error
    if(e.message.includes("API key")){
      errorMsg += "\n\n💡 Kiểm tra API key tại openrouter.ai/keys";
    } else if(e.message.includes("quota") || e.message.includes("credits")){
      errorMsg += "\n\n💡 Hết quota miễn phí. Đợi reset hoặc nạp thêm credit.";
    } else {
      errorMsg += "\n\n💡 Thử lại sau vài giây hoặc kiểm tra mạng.";
    }

    msgs.push({role:"assistant",content:errorMsg});
    addBubble("assistant",errorMsg,ei);

    // Save error message to database too
    saveMessageToDB("assistant", errorMsg);
  }
}

function clearInput(){
  document.getElementById("txtIn").value="";
  document.getElementById("txtIn").focus();
  setStatus("idle");
}

function forceResetMic(){
  console.log("🔄 Force resetting mic state...");

  // Force stop everything
  if(isRec){
    stopRec(false);
  }

  // Clear all timers
  if(recTimer){
    clearInterval(recTimer);
    recTimer=null;
  }
  if(autoStopTimer){
    clearTimeout(autoStopTimer);
    autoStopTimer=null;
  }

  // Reset all state variables
  isRec=false;
  recognition=null;
  speakIdx=-1;
  isSpeaking=false;

  // Stop wave animation
  stopWave();

  // Reset mic button
  const mb=document.getElementById("micBtn");
  const col=COLORS[mode]||"#3b82f6";
  mb.textContent="🎙";
  mb.style.background=`linear-gradient(135deg,${col},${col}88)`;
  mb.style.boxShadow=`0 4px 14px ${col}44`;
  mb.disabled=false;

  // Reset UI elements
  document.getElementById("txtIn").placeholder="Tippe auf Deutsch... hoặc nhấn 🎙 để nói";
  setStatus("idle");

  // Stop any speech
  try{
    if(window.speechSynthesis){
      window.speechSynthesis.cancel();
    }
  }catch(e){}

  console.log("✅ Mic state reset completed");
}

function sendMessage(){const v=document.getElementById("txtIn").value.trim();if(v)sendMsg(v);}

// History panel functions
function toggleHistory(){
  const panel = document.getElementById("historyPanel");
  const isOpen = panel.classList.contains("open");

  if(isOpen){
    panel.classList.remove("open");
  } else {
    panel.classList.add("open");
    loadDailyStats();
    // Set default date to today
    const today = new Date().toISOString().split('T')[0];
    document.getElementById("historyDatePicker").value = today;
    loadHistoryByDate();
  }
}

async function loadDailyStats(days = 7){
  try{
    const response = await fetch(`/stats?days=${days}`);
    const data = await response.json();

    if(data.stats && data.stats.length > 0){
      const totalMessages = data.stats.reduce((sum, day) => sum + day.total_messages, 0);
      const totalDays = data.stats.length;
      const avgPerDay = (totalMessages / Math.max(totalDays, 1)).toFixed(1);

      document.getElementById("historyStats").innerHTML = `
        📈 ${totalMessages} tin nhắn trong ${totalDays} ngày<br/>
        📊 Trung bình: ${avgPerDay} tin nhắn/ngày
      `;
    } else {
      document.getElementById("historyStats").textContent = "📊 Chưa có dữ liệu thống kê";
    }
  } catch(e){
    console.error("Failed to load stats:", e);
    document.getElementById("historyStats").textContent = "❌ Không thể tải thống kê";
  }
}

async function loadHistoryByDate(){
  const dateInput = document.getElementById("historyDatePicker");
  const selectedDate = dateInput.value;

  if(!selectedDate){
    document.getElementById("historyContent").innerHTML = `
      <div style="text-align:center;color:#64748b;margin-top:40px;">
        📅 Hãy chọn ngày để xem lịch sử
      </div>
    `;
    return;
  }

  try{
    document.getElementById("historyContent").innerHTML = `
      <div style="text-align:center;color:#64748b;margin-top:40px;">
        ⏳ Đang tải lịch sử...
      </div>
    `;

    const response = await fetch(`/history?date=${selectedDate}`);
    const data = await response.json();

    if(data.messages && data.messages.length > 0){
      displayHistoryMessages(data.messages, selectedDate);
    } else {
      document.getElementById("historyContent").innerHTML = `
        <div style="text-align:center;color:#64748b;margin-top:40px;">
          📅 ${selectedDate}<br/>
          💬 Không có tin nhắn nào<br/>
          🎯 Hãy chat để tạo lịch sử!
        </div>
      `;
    }
  } catch(e){
    console.error("Failed to load history:", e);
    document.getElementById("historyContent").innerHTML = `
      <div style="text-align:center;color:#f87171;margin-top:40px;">
        ❌ Không thể tải lịch sử<br/>
        ${e.message}
      </div>
    `;
  }
}

function displayHistoryMessages(messages, date){
  const content = document.getElementById("historyContent");

  // Group messages by session or conversation flow
  const groupedMessages = [];
  let currentGroup = [];

  messages.forEach((msg, index) => {
    if(msg.role === 'user' && currentGroup.length > 0){
      // Start new group when user sends message
      groupedMessages.push([...currentGroup]);
      currentGroup = [msg];
    } else {
      currentGroup.push(msg);
    }

    // Last group
    if(index === messages.length - 1 && currentGroup.length > 0){
      groupedMessages.push(currentGroup);
    }
  });

  let html = `
    <div class="history-day">
      <div class="history-day-header">📅 ${date} (${messages.length} tin nhắn)</div>
  `;

  groupedMessages.forEach((group, groupIndex) => {
    group.forEach(msg => {
      const timestamp = new Date(msg.timestamp).toLocaleTimeString('vi-VN', {
        hour: '2-digit',
        minute: '2-digit'
      });

      const parts = msg.content.split(/\\[FEEDBACK\\]:/i);
      const mainContent = parts[0].trim();
      const feedbackContent = parts.slice(1).join('').trim();

      html += `
        <div class="history-message ${msg.role}">
          <div class="timestamp">${timestamp} • ${msg.mode}</div>
          <div class="content">${escapeHtml(mainContent)}</div>
          ${feedbackContent ? `<div class="history-feedback">💡 ${escapeHtml(feedbackContent)}</div>` : ''}
        </div>
      `;
    });
  });

  html += '</div>';
  content.innerHTML = html;
}

function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

// TELC B1 specific functions
function startTELCPart(part, customTopic = null) {
  console.log(`Starting TELC ${part}` + (customTopic ? ` with custom topic` : ''));
  currentTELCPart = part;

  // In simulation mode: don't clear messages, add separator instead
  if(telcSimulationMode) {
    telcSimTeilStart[part] = msgs.length;
    const sep = document.createElement('div');
    sep.className = 'sim-separator';
    sep.textContent = '━━━ ' + part.toUpperCase() + ' ━━━';
    document.getElementById("messages").appendChild(sep);
    updateSimProgress(part);
  } else {
    // Clear previous messages and start fresh
    msgs = [];
    document.getElementById("messages").innerHTML = "";
  }
  document.getElementById("turnCount").textContent = "0 lượt trả lời";

  // Restore topic buttons (in case topic picker was showing) then highlight active part
  if(!telcSimulationMode) {
    restoreTELCTopicButtons();
    updateTELCTopicButtons(part);
  }

  // Partner Mode for Teil 2 & 3: Prüfer intro then Kandidat B opening
  if(part === 'teil2' || part === 'teil3') {
    let pruferIntro, kandidatBOpening;

    if(part === 'teil2') {
      const topic = customTopic || TELC_TEIL2_TOPICS[Math.floor(Math.random() * TELC_TEIL2_TOPICS.length)];
      pruferIntro = `Jetzt kommen wir zu Teil 2 - Gespräch über ein Thema. Das Thema ist: "${topic}". Bitte diskutieren Sie miteinander.`;
      kandidatBOpening = `Also, zum Thema "${topic}" - ich finde das sehr interessant. Meiner Meinung nach ist das ein wichtiges Thema. Was denkst du darüber?`;
    } else {
      const scenario = customTopic || TELC_TEIL3_SCENARIOS[Math.floor(Math.random() * TELC_TEIL3_SCENARIOS.length)];
      pruferIntro = `Nun kommen wir zu Teil 3 - Gemeinsam etwas planen. Stellen Sie sich vor: Sie möchten zusammen ${scenario.toLowerCase()}. Bitte planen Sie gemeinsam.`;
      kandidatBOpening = `Okay, lass uns das zusammen planen! Ich schlage vor, dass wir zuerst über den Termin sprechen. Wann passt es dir am besten?`;
    }

    // Show Prüfer intro
    addBubblePartner("prufer", pruferIntro, msgs.length);
    if(autoSpeak) speak(pruferIntro, msgs.length);

    // After a delay, show Kandidat B opening
    setTimeout(() => {
      const kbIdx = msgs.length;
      msgs.push({role: "assistant", content: kandidatBOpening});
      addBubblePartner("kandidatB", kandidatBOpening, kbIdx);
      saveMessageToDB("assistant", kandidatBOpening);
      if(autoSpeak) setTimeout(() => speak(kandidatBOpening, kbIdx), 500);
    }, 2000);
  } else {
    // Teil 1: unchanged Prüfer behavior
    let starter = TELC_STARTERS[part];
    msgs.push({role: "assistant", content: starter});
    addBubble("assistant", starter, 0);
    saveMessageToDB("assistant", starter);
    if(autoSpeak) speak(starter, 0);
  }

  // Update header to show current part
  const partTitles = {
    teil1: "🎓 TELC B1 - Teil 1: Kontaktaufnahme (3-4 Min)",
    teil2: "🗣️ TELC B1 - Teil 2: Gespräch über Thema (5-6 Min)",
    teil3: "🤝 TELC B1 - Teil 3: Gemeinsam planen (5-6 Min)"
  };
  document.getElementById("modeTitle").textContent = partTitles[part];

  // Start TELC timer for this part
  startTELCTimer(part);

  // Update score button visibility
  updateScoreButtonVisibility();

  // Refresh phrase bank if open
  if(document.getElementById("phraseBankPanel").classList.contains("open")) {
    renderPhraseBank();
  }
}

function updateTELCTopicButtons(activePart) {
  const buttons = document.querySelectorAll('.topic-btn');
  buttons.forEach(btn => {
    btn.style.opacity = '0.6';
    btn.style.background = 'rgba(255,255,255,0.05)';
  });

  // Highlight active part
  if(activePart === 'teil1') {
    buttons[0].style.opacity = '1';
    buttons[0].style.background = 'rgba(59,130,246,0.2)';
  } else if(activePart === 'teil2') {
    buttons[1].style.opacity = '1';
    buttons[1].style.background = 'rgba(16,185,129,0.2)';
  } else if(activePart === 'teil3') {
    buttons[2].style.opacity = '1';
    buttons[2].style.background = 'rgba(251,191,36,0.2)';
  }
}

function cleanTextForTTS(text) {
  return text
    // Remove brackets and content inside
    .replace(/\[.*?\]/g, '')
    // Replace dashes with commas for better speech flow
    .replace(/\s-\s/g, ', ')
    // Clean up multiple spaces
    .replace(/\s+/g, ' ')
    // Remove problematic chars but keep basic punctuation
    .replace(/[()]/g, '')
    // Break long sentences at natural points
    .replace(/(\.|!|\?)\s+/g, '$1 ')
    .trim();
}

function breakIntoChunks(text, maxLength = 200) {
  const sentences = text.split(/(?<=[.!?])\s+/);
  const chunks = [];
  let currentChunk = '';

  for (const sentence of sentences) {
    if ((currentChunk + ' ' + sentence).length > maxLength && currentChunk) {
      chunks.push(currentChunk.trim());
      currentChunk = sentence;
    } else {
      currentChunk = currentChunk ? currentChunk + ' ' + sentence : sentence;
    }
  }

  if (currentChunk) chunks.push(currentChunk.trim());
  return chunks.filter(chunk => chunk.length > 0);
}

async function speak(text, idx) {
  const synth = window.speechSynthesis;

  // Mobile audio unlock check
  if(isMobile && !audioUnlocked){
    console.log("Mobile: unlocking audio first");
    await unlockAudio();
  }

  // If clicking same button, stop current speech
  if (speakIdx === idx && isSpeaking) {
    stopAllSpeech();
    return;
  }

  // Stop any current speech
  if (isSpeaking) {
    stopAllSpeech();
  }

  // Check if we should use Google TTS fallback on mobile
  if(isMobile && (localTTSFailed || !synth || synth.getVoices().length === 0)){
    console.log("Using Google TTS fallback for mobile");
    speakWithGoogleTTS(text, idx);
    return;
  }

  if (!synth) return;

  const rawText = text.split(/\[FEEDBACK\]/i)[0].trim();
  if (!rawText) return;

  const cleanText = cleanTextForTTS(rawText);
  const chunks = breakIntoChunks(cleanText, 180); // Shorter chunks for reliability

  console.log(`TTS: Breaking text into ${chunks.length} chunks`);

  speakIdx = idx;
  isSpeaking = true;
  setSpeakBtn(idx, true, chunks.length > 1);

  let currentChunkIdx = 0;
  const originalText = text; // Store for error fallback

  function speakNextChunk() {
    if (currentChunkIdx >= chunks.length) {
      // Finished naturally
      isSpeaking = false;
      speakIdx = -1;
      setSpeakBtn(idx, false);
      console.log("TTS completed successfully");
      return;
    }

    if (!isSpeaking || speakIdx !== idx) {
      // Was stopped externally
      console.log("TTS stopped externally");
      return;
    }

    const chunk = chunks[currentChunkIdx];
    console.log(`TTS chunk ${currentChunkIdx + 1}/${chunks.length}: "${chunk.substring(0, 50)}..."`);

    const utt = new SpeechSynthesisUtterance(chunk);
    utt.lang = "de-DE";
    utt.rate = isMobile ? Math.min(ttsSpeed, 1.1) : ttsSpeed; // Use user-configured speed
    utt.pitch = 1.05; // Slightly higher pitch for clarity
    utt.volume = isMobile ? 1 : 0.95; // Good volume

    // Find best German voice with preference for quality
    const voices = synth.getVoices();
    let de = voices.find(v => v.lang === "de-DE" && (v.name.includes("Google") || v.name.includes("Premium"))) ||
             voices.find(v => v.lang === "de-DE" && v.name.includes("Female")) ||
             voices.find(v => v.lang === "de-DE" && !v.name.includes("(Enhanced)")) ||
             voices.find(v => v.lang.startsWith("de-DE")) ||
             voices.find(v => v.lang.startsWith("de"));

    if (!de && isMobile) {
      // Enhanced mobile fallback - prefer higher quality voices
      de = voices.find(v => v.name.includes("Google") || v.name.includes("Siri")) ||
           voices.find(v => v.default) ||
           voices[0];
      console.warn("Mobile: No German voice, using enhanced fallback:", de?.name);
    }
    if (de) {
      utt.voice = de;
      console.log("Using German voice:", de.name, "| Lang:", de.lang);
    }

    utt.onstart = () => {
      console.log(`TTS chunk ${currentChunkIdx + 1} started`);
    };

    utt.onend = () => {
      console.log(`TTS chunk ${currentChunkIdx + 1} ended`);
      currentChunkIdx++;
      // Small delay between chunks for smoother flow
      if (isSpeaking && speakIdx === idx) {
        setTimeout(speakNextChunk, 100);
      }
    };

    utt.onerror = (e) => {
      console.warn(`TTS chunk ${currentChunkIdx + 1} error:`, e.error);

      // Mobile-specific error handling
      if(isMobile){
        if(e.error === 'not-allowed' || e.error === 'audio-hardware-error'){
          console.warn("Mobile local TTS failed, marking for Google TTS fallback");
          localTTSFailed = true;

          // Stop current attempt and retry with Google TTS
          stopAllSpeech();
          setTimeout(() => {
            speakWithGoogleTTS(originalText, idx);
          }, 100);
          return;
        }

        // Show user instruction for other errors
        const btn = document.getElementById(`spk${idx}`);
        if(btn){
          btn.title = "Audio error - try online TTS button";
          btn.style.background = "rgba(251,191,36,0.15)";
        }
      }

      currentChunkIdx++;
      // Try next chunk on error
      if (isSpeaking && speakIdx === idx) {
        setTimeout(speakNextChunk, 200);
      }
    };

    try {
      synth.speak(utt);
    } catch (e) {
      console.error("TTS speak error:", e);
      currentChunkIdx++;
      setTimeout(speakNextChunk, 200);
    }
  }

  // Start speaking
  if (synth.getVoices().length === 0) {
    synth.onvoiceschanged = () => {
      setTimeout(speakNextChunk, 100);
    };
    // Force trigger on mobile
    if(isMobile) synth.getVoices();
  } else {
    speakNextChunk();
  }
}

// Fallback TTS using Google Translate (for mobile browsers without TTS support)
function playGoogleTTS(text, onEnd) {
  if(!text) return;

  const cleanText = encodeURIComponent(text.substring(0, 200)); // Limit length
  const audioUrl = `https://translate.google.com/translate_tts?ie=UTF-8&q=${cleanText}&tl=de&client=tw-ob`;

  const audio = new Audio();
  audio.crossOrigin = "anonymous";

  audio.oncanplay = () => {
    console.log("Google TTS audio ready");
    audio.play().catch(e => {
      console.error("Failed to play Google TTS:", e);
      if(onEnd) onEnd();
    });
  };

  audio.onended = () => {
    console.log("Google TTS finished");
    if(onEnd) onEnd();
  };

  audio.onerror = (e) => {
    console.error("Google TTS error:", e);
    if(onEnd) onEnd();
  };

  // Set source to trigger loading
  audio.src = audioUrl;
  audio.load();
}

// Main function to speak using Google TTS
function speakWithGoogleTTS(text, idx) {
  const rawText = text.split(/\[FEEDBACK\]/i)[0].trim();
  if (!rawText) return;

  const cleanText = cleanTextForTTS(rawText);
  console.log(`Speaking with Google TTS: "${cleanText.substring(0, 50)}..."`);

  speakIdx = idx;
  isSpeaking = true;
  setSpeakBtn(idx, true, false, true); // Mark as online

  playGoogleTTS(cleanText, () => {
    // Finished speaking
    isSpeaking = false;
    speakIdx = -1;
    setSpeakBtn(idx, false);
  });
}
function setSpeakBtn(idx,on,isChunked=false,isOnline=false){
  const b=document.getElementById(`spk${idx}`);if(!b)return;
  const c=COLORS[mode]||"#3b82f6";

  if(on){
    if(isOnline){
      b.textContent="🌐";
      b.title="Đang đọc online (Google TTS) - click để dừng";
    }else if(isChunked){
      b.textContent="⏸️";
      b.title="Đang đọc text dài (nhiều đoạn) - click để dừng";
    }else{
      b.textContent="⏹";
      b.title="Đang đọc - click để dừng";
    }
  }else{
    b.textContent="🔊";
    b.title="Click để nghe";
    b.style.background=""; // Reset any error styling
  }

  b.classList.toggle("on",on);
  b.style.borderColor=on?c:"rgba(255,255,255,0.09)";
}
function stopAllSpeech(){
  if(isSpeaking){
    window.speechSynthesis?.cancel();
    isSpeaking=false;
    if(speakIdx>=0)setSpeakBtn(speakIdx,false);
    speakIdx=-1;
    console.log("All speech stopped");
  }
}

function toggleTTS(){
  autoSpeak=!autoSpeak;
  if(!autoSpeak){
    stopAllSpeech();
  }
  updateTTSBtn();
}

function updateTTSBtn(){
  const btn=document.getElementById("ttsToggle"),c=COLORS[mode]||"#3b82f6";
  btn.textContent=autoSpeak?"🔊 TTS Bật":"🔇 TTS Tắt";
  btn.style.background=autoSpeak?`${c}1a`:"rgba(255,255,255,0.05)";
  btn.style.borderColor=autoSpeak?`${c}55`:"rgba(255,255,255,0.09)";
  btn.style.color=autoSpeak?c:"#475569";
}

function toggleVN(){
  vietnameseFeedback=!vietnameseFeedback;
  updateVNBtn();

  // Toggle visibility of existing feedback bubbles
  document.querySelectorAll(".fb").forEach(fb=>{
    fb.style.display=vietnameseFeedback?"block":"none";
  });
}

function updateVNBtn(){
  const btn=document.getElementById("vnToggle"),c=COLORS[mode]||"#3b82f6";
  btn.textContent=vietnameseFeedback?"🇻🇳 VN Bật":"🇻🇳 VN Tắt";
  btn.style.background=vietnameseFeedback?`${c}1a`:"rgba(255,255,255,0.05)";
  btn.style.borderColor=vietnameseFeedback?`${c}55`:"rgba(255,255,255,0.09)";
  btn.style.color=vietnameseFeedback?c:"#475569";
}

function updateMobileDebug(){
  if(!isMobile) return;

  const debug = document.getElementById("mobileDebug");
  if(!debug) return;

  const synth = window.speechSynthesis;
  const voices = synth ? synth.getVoices() : [];
  const deVoices = voices.filter(v => v.lang.startsWith("de"));
  const hasGermanVoice = deVoices.length > 0;

  // More detailed debug info
  const info = [
    `Audio: ${audioUnlocked ? "✅" : "❌"}`,
    `TTS: ${synth ? "✅" : "❌"}`,
    `German: ${hasGermanVoice ? "✅" : "❌"}`,
    `Voices: ${voices.length}`,
    `Speaking: ${synth && synth.speaking ? "✅" : "❌"}`,
    `Pending: ${synth && synth.pending ? "✅" : "❌"}`
  ].join(" | ");

  debug.textContent = info;
  debug.style.display = "block";

  // Log voice details
  if(deVoices.length > 0){
    console.log("German voices available:", deVoices.map(v => `${v.name} (${v.lang})`));
  } else {
    console.warn("No German voices found. Available voices:", voices.slice(0,3).map(v => `${v.name} (${v.lang})`));
  }
}

function setupMobileAudioTest(){
  const testBtn = document.getElementById("testTTSBtn");
  const testGoogleBtn = document.getElementById("testGoogleTTSBtn");
  const testResult = document.getElementById("testResult");
  const testContainer = document.getElementById("audioTest");

  if(!testBtn || !testResult) return;

  testContainer.style.display = "block";

  // Test Google TTS
  if(testGoogleBtn){
    testGoogleBtn.onclick = () => {
      testResult.textContent = "Testing online TTS...";
      testResult.style.color = "#34d399";

      playGoogleTTS("Hallo, das ist ein Test", () => {
        testResult.textContent = "✅ Online TTS works!";
        testResult.style.color = "#10b981";
      });
    };
  }

  // Reset Mic button
  const resetMicBtn = document.getElementById("resetMicBtn");
  if(resetMicBtn){
    resetMicBtn.onclick = () => {
      forceResetMic();
      testResult.textContent = "🔄 Mic reset completed";
      testResult.style.color = "#f87171";
    };
  }

  testBtn.onclick = async () => {
    testResult.textContent = "Testing...";
    testBtn.disabled = true;

    try {
      // First unlock audio if needed
      if(!audioUnlocked){
        await unlockAudio();
      }

      updateMobileDebug(); // Refresh debug info

      const synth = window.speechSynthesis;
      if(!synth){
        testResult.textContent = "❌ No TTS support";
        testResult.style.color = "#f87171";
        return;
      }

      // Test with simple German text
      const testText = "Hallo";
      const utterance = new SpeechSynthesisUtterance(testText);
      utterance.lang = "de-DE";
      utterance.volume = 1;
      utterance.rate = 1.1;
      utterance.pitch = 1;

      // Find German voice
      const voices = synth.getVoices();
      const germanVoice = voices.find(v => v.lang.startsWith("de"));
      if(germanVoice){
        utterance.voice = germanVoice;
        console.log("Using German voice:", germanVoice.name);
      } else {
        console.warn("No German voice, using default");
      }

      let hasStarted = false;
      let hasEnded = false;

      utterance.onstart = () => {
        hasStarted = true;
        testResult.textContent = "🔊 Playing...";
        testResult.style.color = "#10b981";
        console.log("TTS started successfully");
      };

      utterance.onend = () => {
        hasEnded = true;
        if(hasStarted){
          testResult.textContent = "✅ Audio works!";
          testResult.style.color = "#10b981";
        }
        testBtn.disabled = false;
        updateMobileDebug();
      };

      utterance.onerror = (e) => {
        console.error("TTS error:", e);
        testResult.textContent = `❌ Error: ${e.error}`;
        testResult.style.color = "#f87171";
        testBtn.disabled = false;

        // Specific error messages
        if(e.error === 'not-allowed'){
          testResult.textContent += " (Need user gesture)";
        } else if(e.error === 'audio-hardware-error'){
          testResult.textContent += " (Audio hardware issue)";
        }
      };

      // Timeout check
      setTimeout(() => {
        if(!hasStarted && !hasEnded){
          testResult.textContent = "⏳ TTS may be slow on this device";
          testResult.style.color = "#f59e0b";
        }
      }, 3000);

      // Clear existing speech and speak
      synth.cancel();

      // Alternative method for problematic mobile browsers
      if(isMobile && voices.length === 0){
        // Try to trigger voices loading on mobile
        synth.onvoiceschanged = () => {
          const newVoices = synth.getVoices();
          console.log("Voices loaded after onvoiceschanged:", newVoices.length);
          updateMobileDebug();
          if(newVoices.length > 0){
            const newGermanVoice = newVoices.find(v => v.lang.startsWith("de"));
            if(newGermanVoice) utterance.voice = newGermanVoice;
            synth.speak(utterance);
          }
        };
        // Trigger voice loading
        synth.getVoices();
      } else {
        synth.speak(utterance);
      }

      // Also log technical details
      console.log("TTS Test Details:", {
        userAgent: navigator.userAgent,
        voices: voices.length,
        germanVoices: voices.filter(v => v.lang.startsWith("de")).length,
        audioUnlocked: audioUnlocked,
        synth: !!synth,
        speaking: synth.speaking,
        pending: synth.pending,
        platform: navigator.platform
      });

    } catch(error) {
      console.error("TTS test failed:", error);
      testResult.textContent = `❌ Error: ${error.message}`;
      testResult.style.color = "#f87171";
      testBtn.disabled = false;
    }
  };
}

function toggleRec(){
  console.log("toggleRec called, isRec:", isRec, "autoStopTimer:", autoStopTimer);

  if(isRec){
    stopRec();
    return;
  }

  const SR=window.SpeechRecognition||window.webkitSpeechRecognition;
  if(!SR){
    setStatus("err","⚠️ Trình duyệt không hỗ trợ mic. Hãy dùng Chrome!");
    return;
  }

  // Stop any playing speech before starting recording
  stopAllSpeech();

  // Always create fresh recognition instance
  recognition=null;

  // Check mic permission first
  if(navigator.permissions){
    navigator.permissions.query({name:"microphone"}).then(p=>{
      console.log("Mic permission:", p.state);
      if(p.state==="denied") {
        setStatus("err","⚠️ Mic bị chặn. Vào chrome://settings/content/microphone → bỏ chặn localhost:9999");
        return;
      }
    }).catch(()=>{});
  }

  console.log("Creating new SpeechRecognition instance");

  const rec=new SR();
  rec.lang="de-DE";
  rec.continuous=true; // Keep continuous but fix logic
  rec.interimResults=true;
  rec.maxAlternatives=1;

  // Reset all variables for fresh start
  let final="";
  let interim="";
  let hasReceivedFinal=false;
  let lastFinalIndex=-1;
  let lastFinalTime=0;
  let speechSegments=[];

  // Clear global timer
  if(autoStopTimer){
    clearTimeout(autoStopTimer);
    autoStopTimer=null;
  }

  console.log("Recognition configured, setting up event handlers...");

  rec.onstart=()=>{
    console.log("Speech recognition started");
    isRec=true;recognition=rec;
    final="";interim="";recSec=0;hasReceivedFinal=false;
    lastFinalIndex=-1;lastFinalTime=0;speechSegments=[];

    setStatus("rec");startWave();
    recTimer=setInterval(()=>{recSec++;document.getElementById("recTime").textContent=fmtSec(recSec);},1000);
    const mb=document.getElementById("micBtn");
    mb.textContent="⏹";mb.style.background="linear-gradient(135deg,#ef4444,#dc2626)";
    mb.style.boxShadow="0 0 20px #ef444477";
    document.getElementById("txtIn").placeholder="🔴 Đang nghe tiếng Đức...";

    // Auto-stop after 20 seconds for single utterance
    autoStopTimer=setTimeout(()=>{
      console.log("Auto-stopping recording after 20s");
      if(isRec) stopRec(true);
    }, 20000);
  };

  rec.onresult=e=>{
    let currentInterim="";
    let newFinalSegments=[];
    const now=Date.now();

    // Process only new results to avoid duplicates
    for(let i=e.resultIndex;i<e.results.length;i++){
      const t=e.results[i][0].transcript.trim();
      if(!t) continue;

      if(e.results[i].isFinal){
        // New final result - check if it's really new
        if(i > lastFinalIndex){
          // Check if this might be a duplicate of recent speech
          const isDuplicate=speechSegments.some(seg=>
            seg.text.toLowerCase()===t.toLowerCase() &&
            (now-seg.timestamp)<3000 // within 3 seconds
          );

          if(!isDuplicate){
            speechSegments.push({text:t, timestamp:now});
            newFinalSegments.push(t);
            lastFinalIndex=i;
            lastFinalTime=now;
            hasReceivedFinal=true;
            console.log(`New final: "${t}" (index ${i})`);
          }else{
            console.log(`Ignoring duplicate: "${t}"`);
          }
        }
      }else{
        // Interim result
        currentInterim=t;
      }
    }

    // Build final text from segments
    final=speechSegments.map(seg=>seg.text).join(" ");

    // Show current state
    const show=(final + (currentInterim ? " " + currentInterim : "")).trim();
    document.getElementById("txtIn").value=show;
    document.getElementById("stText").textContent=show||"Đang nghe...";

    // Debug logging
    if(newFinalSegments.length > 0){
      console.log(`🎙️ Speech segments:`, speechSegments);
      console.log(`📝 Final text: "${final}"`);
    }

    // Auto-stop logic - more aggressive for single words
    if(newFinalSegments.length > 0){
      if(autoStopTimer) {
        clearTimeout(autoStopTimer);
        console.log("Cleared previous autoStopTimer");
      }

      // Quick stop for short single words
      const totalWords=final.split(/\s+/).filter(w=>w).length;
      const stopDelay=totalWords <= 2 ? 1000 : 2000;

      autoStopTimer=setTimeout(()=>{
        console.log(`Auto-stopping after ${stopDelay}ms (${totalWords} words)`);
        if(isRec) stopRec(true);
      }, stopDelay);

      console.log(`Set autoStopTimer for ${stopDelay}ms`);
    }
  };

  rec.onerror=e=>{
    console.error("Speech recognition error:", e.error);
    if(autoStopTimer)clearTimeout(autoStopTimer);
    stopRec(false);
    const map={
      "not-allowed":"⚠️ Chưa cho phép mic. Nhấn 🔒 trên thanh địa chỉ → Cho phép Microphone.",
      "no-speech":"⚠️ Không nghe thấy giọng nói. Hãy nói to hơn và thử lại.",
      "network":"⚠️ Lỗi mạng STT. Kiểm tra kết nối internet.",
      "audio-capture":"⚠️ Không tìm thấy mic. Kiểm tra mic đã cắm chưa.",
      "aborted":"⚠️ Ghi âm bị hủy.",
      "language-not-supported":"⚠️ Ngôn ngữ Đức không được hỗ trợ trên trình duyệt này."
    };
    setStatus("err",map[e.error]||`⚠️ Lỗi mic: ${e.error}`);
  };

  rec.onend=()=>{
    console.log("Speech recognition ended naturally");
    if(autoStopTimer){
      clearTimeout(autoStopTimer);
      autoStopTimer=null;
    }

    const text=(final||document.getElementById("txtIn").value).trim();
    const wasRecording=isRec;

    // Always call stopRec to clean up state, but don't auto-send if we already have text
    if(wasRecording){
      console.log("Recognition ended with text:", text);
      stopRec(false); // Don't auto-send, we'll handle it manually

      if(text){
        setTimeout(()=>{
          sendMsg(text);
          document.getElementById("txtIn").value=""; // Clear after sending
        },200);
      }
    }
  };

  try{
    rec.start();
    console.log("Starting speech recognition...");
  }catch(e){
    console.error("Failed to start speech recognition:", e);
    setStatus("err","⚠️ Không thể khởi động mic. Thử tải lại trang.");

    // Reset state on error
    isRec=false;
    recognition=null;
    const mb=document.getElementById("micBtn");
    mb.disabled=false;
    mb.textContent="🎙";
  }
}
function stopRec(autoSend=true){
  console.log("Stopping recording, autoSend:", autoSend);

  // Clear all timers globally
  try{
    if(recTimer){
      clearInterval(recTimer);
      recTimer=null;
    }
    if(autoStopTimer){
      clearTimeout(autoStopTimer);
      autoStopTimer=null;
    }
  }catch(e){
    console.warn("Error clearing timers:", e);
    // Force reset
    recTimer=null;
    autoStopTimer=null;
  }

  const wasRec=isRec;
  const currentText=document.getElementById("txtIn").value.trim();

  // Reset all state variables FIRST
  isRec=false;
  recognition=null;
  stopWave();

  // Stop recognition safely
  try{
    if(window.speechSynthesis) window.speechSynthesis.cancel(); // Clear any pending speech
  }catch(e){
    console.warn("Error clearing speech synthesis:", e);
  }

  // Reset UI
  const col=COLORS[mode]||"#3b82f6";
  const mb=document.getElementById("micBtn");
  mb.textContent="🎙";
  mb.style.background=`linear-gradient(135deg,${col},${col}88)`;
  mb.style.boxShadow=`0 4px 14px ${col}44`;
  mb.disabled=false; // Ensure button is clickable
  document.getElementById("txtIn").placeholder="Tippe auf Deutsch... hoặc nhấn 🎙 để nói";

  // Clear status immediately for next use
  setStatus("idle");

  // Auto-send if requested and we have text
  if(autoSend && wasRec && currentText){
    console.log("Auto-sending text:", currentText);
    setTimeout(()=>{
      sendMsg(currentText);
      // Clear input after sending
      document.getElementById("txtIn").value="";
    },200);
  } else if(!autoSend) {
    // If not auto-sending, keep the text for manual editing
    console.log("Keeping text for manual review:", currentText);
  }

  console.log("Recording stopped successfully, ready for next recording");
}
function startWave(){
  const cv=document.getElementById("wv"),ctx=cv.getContext("2d"),c=COLORS[mode]||"#3b82f6";
  cv.classList.add("live");waveT=0;
  const draw=()=>{
    if(!isRec){ctx.clearRect(0,0,cv.width,cv.height);return;}
    waveAnim=requestAnimationFrame(draw);waveT+=0.1;
    ctx.clearRect(0,0,cv.width,cv.height);ctx.strokeStyle=c;ctx.lineWidth=2;ctx.beginPath();
    for(let x=0;x<cv.width;x++){
      const y=cv.height/2+Math.sin(x*.07+waveT)*9*Math.abs(Math.sin(waveT*.5))+Math.sin(x*.14+waveT*1.3)*4;
      x===0?ctx.moveTo(x,y):ctx.lineTo(x,y);
    }
    ctx.stroke();
  };draw();
}
function stopWave(){
  cancelAnimationFrame(waveAnim);
  const cv=document.getElementById("wv");cv.classList.remove("live");
  cv.getContext("2d").clearRect(0,0,cv.width,cv.height);
}
function setStatus(state,msg=""){
  const bar=document.getElementById("statusBar"),dot=document.getElementById("recDot"),
        timer=document.getElementById("recTime"),st=document.getElementById("stText");
  bar.className="";dot.style.display="none";timer.style.display="none";
  if(state==="rec"){
    bar.className="rec";dot.style.display="block";timer.style.display="block";
    st.style.color="#64748b";st.textContent="Nói tiếng Đức → dừng tự động";
  }else if(state==="err"){
    bar.className="err";st.style.color="#fca5a5";st.textContent=msg;
  }else{st.textContent="";}
}
function fmtSec(s){return`${String(Math.floor(s/60)).padStart(2,"0")}:${String(s%60).padStart(2,"0")}`;}

// TELC Scoring functions
function toggleScoring() {
  const panel = document.getElementById("scoringPanel");
  const isOpen = panel.classList.contains("open");

  if(isOpen) {
    panel.classList.remove("open");
  } else {
    panel.classList.add("open");
    // Show initial content
    document.getElementById("scoringContent").innerHTML = `
      <div class="scoring-loading">
        🎯 <strong>Hướng dẫn chấm điểm TELC B1:</strong><br/><br/>
        1️⃣ Chọn một Teil (Teil 1, 2, hoặc 3)<br/>
        2️⃣ Thực hiện cuộc trò chuyện hoàn chỉnh<br/>
        3️⃣ Nhấn nút <strong>⭐ Chấm điểm</strong> để được đánh giá<br/><br/>
        📊 Hệ thống sẽ phân tích theo tiêu chuẩn TELC B1 chính thức<br/>
        🇻🇳 Phản hồi chi tiết bằng tiếng Việt
      </div>
    `;
  }
}

async function requestTELCScoring() {
  console.log("🎯 TELC Scoring requested...");
  console.log("Current TELC Part:", currentTELCPart);
  console.log("Messages count:", msgs.length);
  console.log("Session ID:", sessionId);

  if(!currentTELCPart) {
    alert("⚠️ Hãy chọn một Teil trước khi chấm điểm!");
    return;
  }

  if(msgs.length < 3) {
    alert("⚠️ Cuộc trò chuyện quá ngắn! Hãy chat ít nhất 3 tin nhắn để được chấm điểm.");
    return;
  }

  // Show scoring panel
  const panel = document.getElementById("scoringPanel");
  if(!panel.classList.contains("open")) {
    toggleScoring();
  }

  // Show loading with more detail
  document.getElementById("scoringContent").innerHTML = `
    <div class="scoring-loading">
      ⏳ <strong>Đang phân tích cuộc trò chuyện...</strong><br/><br/>
      📋 Teil: ${currentTELCPart?.toUpperCase()}<br/>
      💬 Tin nhắn: ${msgs.filter(m => m.role === 'user').length} từ người dùng<br/>
      🤖 AI đang đánh giá theo tiêu chuẩn TELC B1<br/>
      📊 Tính toán điểm theo các tiêu chí chính thức<br/>
      ⭐ Vui lòng chờ 15-20 giây...
    </div>
  `;

  try {
    // Prepare conversation text for analysis (only user messages)
    const userMessages = msgs.filter(m => m.role === 'user');
    const conversationText = userMessages.map(m => m.content).join('\n\n');

    console.log("User messages for scoring:", userMessages.length);
    console.log("Conversation text preview:", conversationText.substring(0, 200) + "...");

    if(!conversationText.trim()) {
      throw new Error("Không có tin nhắn người dùng để chấm điểm");
    }

    const requestData = {
      session_id: sessionId,
      telc_part: currentTELCPart,
      conversation: conversationText
    };

    console.log("Sending request to /score-telc:", requestData);

    const response = await fetch('/score-telc', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Api-Key': API_KEY || ''
      },
      body: JSON.stringify(requestData)
    });

    console.log("Response status:", response.status);
    const responseText = await response.text();
    console.log("Response text:", responseText);

    if(!response.ok) {
      throw new Error(`Server lỗi ${response.status}: ${responseText}`);
    }

    const result = JSON.parse(responseText);
    console.log("Scoring result:", result);

    if(result.success && result.scores) {
      console.log("✅ Scoring successful, displaying results");
      displayScoringResults(result.scores);
    } else {
      throw new Error(result.error || "Không có kết quả chấm điểm");
    }

  } catch(error) {
    console.error("❌ Scoring error:", error);
    console.error("Error stack:", error.stack);

    document.getElementById("scoringContent").innerHTML = `
      <div style="color:#f87171;text-align:center;padding:20px;">
        ❌ <strong>Lỗi chấm điểm:</strong><br/><br/>
        ${error.message}<br/><br/>
        🔧 <strong>Chi tiết debug:</strong><br/>
        Teil: ${currentTELCPart || 'không có'}<br/>
        Tin nhắn: ${msgs.length}<br/>
        Session: ${sessionId}<br/><br/>
        ${error.message.includes('401') ?
          '🔑 <strong>API Key Issue:</strong><br/>Kiểm tra OpenRouter API key tại <a href="https://openrouter.ai/keys" target="_blank">openrouter.ai/keys</a><br/>Hoặc dùng phân tích cơ bản (không cần AI)' :
          '💡 Vui lòng thử lại hoặc check console (F12) để debug'
        }
      </div>
    `;
  }
}

function formatFeedbackList(data) {
  if(!data) return '<li>Không có thông tin</li>';

  // Handle both array and string formats
  let items = [];
  if(Array.isArray(data)) {
    items = data;
  } else if(typeof data === 'string') {
    // Convert string back to array (split by bullet points or newlines)
    items = data.split('\n').map(item => item.replace(/^•\s*/, '').trim()).filter(item => item);
  } else {
    items = [String(data)];
  }

  return items.map(item => `<li>${item}</li>`).join('');
}

function displayScoringResults(scores) {
  const content = document.getElementById("scoringContent");

  console.log("📊 Displaying scoring results:", scores);

  // Create score breakdown display
  const criteriaBreakdown = Object.keys(scores.criteria_breakdown || {})
    .map(criterion => {
      const details = scores.criteria_breakdown[criterion];
      const score = scores[`${criterion}_score`] || 0;
      const percentage = Math.round((score / details.max) * 100);

      return `
        <div class="score-item">
          <div class="score-label">${details.desc}</div>
          <div class="score-bar-container">
            <div class="score-bar" style="width:${percentage}%"></div>
            <div class="score-text">${score}/${details.max}</div>
          </div>
        </div>
      `;
    }).join('');

  content.innerHTML = `
    <div class="scoring-results">
      <!-- Overall Score -->
      <div class="total-score">
        <div class="score-circle">
          <div class="score-number">${scores.total_score}</div>
          <div class="score-max">/${scores.max_score}</div>
        </div>
        <div class="score-details">
          <div class="score-percentage">${scores.percentage}%</div>
          <div class="score-level">${scores.level_assessment}</div>
          <div class="score-part">${scores.telc_part?.toUpperCase()}</div>
        </div>
      </div>

      <!-- Criteria Breakdown -->
      <div class="criteria-section">
        <h3>📊 Phân tích chi tiết</h3>
        ${criteriaBreakdown}
      </div>

      <!-- Strengths -->
      <div class="feedback-section strengths">
        <h3>💪 Điểm mạnh</h3>
        <ul>
          ${formatFeedbackList(scores.strengths)}
        </ul>
      </div>

      <!-- Weaknesses -->
      <div class="feedback-section weaknesses">
        <h3>⚠️ Cần cải thiện</h3>
        <ul>
          ${formatFeedbackList(scores.weaknesses)}
        </ul>
      </div>

      <!-- Recommendations -->
      <div class="feedback-section recommendations">
        <h3>💡 Khuyến nghị</h3>
        <ul>
          ${formatFeedbackList(scores.recommendations)}
        </ul>
      </div>

      <!-- B1 Structure Analysis -->
      ${renderB1StructureHTML(analyzeB1Structures(msgs.filter(m => m.role === 'user')))}

      <!-- AI Analysis -->
      <div class="ai-analysis">
        <h3>🤖 Phân tích AI đầy đủ</h3>
        <div class="analysis-text">${scores.detailed_feedback || 'Không có phân tích chi tiết'}</div>
      </div>

      <!-- Action Buttons -->
      <div class="scoring-actions">
        <button onclick="requestTELCScoring()" class="btn-primary">🔄 Chấm lại</button>
        <button onclick="toggleScoring()" class="btn-secondary">✓ Đóng</button>
      </div>
    </div>
  `;
}

// Show score button when in TELC mode and have conversation
function updateScoreButtonVisibility() {
  const scoreBtn = document.getElementById("scoreBtn");
  const shouldShow = (currentTELCPart || currentEmbassyPhase) && msgs.length >= 3;

  if(shouldShow) {
    scoreBtn.style.display = "block";
    scoreBtn.textContent = "⭐ Chấm điểm";
  } else {
    scoreBtn.style.display = "none";
  }
}

// ===== Phrase Bank =====
function togglePhraseBank() {
  const panel = document.getElementById("phraseBankPanel");
  const isOpen = panel.classList.contains("open");
  if(isOpen) {
    panel.classList.remove("open");
  } else {
    panel.classList.add("open");
    renderPhraseBank();
  }
}

function renderPhraseBank() {
  let bank, label;
  if(mode === 'embassy') {
    const phase = currentEmbassyPhase || 'phase1';
    bank = EMBASSY_PHRASE_BANK[phase];
    label = phase.toUpperCase();
  } else {
    const part = currentTELCPart || 'teil1';
    bank = TELC_PHRASE_BANK[part];
    label = part.toUpperCase();
  }
  if(!bank) return;

  let html = '<div style="font-size:11px;color:#64748b;margin-bottom:12px;text-align:center;">' +
    label + ' — Nhấn vào mẫu câu để chèn</div>';

  for(const category in bank) {
    html += '<div class="phrase-category">';
    html += '<div class="phrase-category-title">' + category + '</div>';
    bank[category].forEach(phrase => {
      const escaped = phrase.de.replace(/'/g, "\\'").replace(/"/g, '&quot;');
      html += '<div class="phrase-item" onclick="insertPhrase(\'' + escaped + '\')">';
      html += '<div class="phrase-de">' + phrase.de + '</div>';
      html += '<div class="phrase-vn">' + phrase.vn + '</div>';
      html += '</div>';
    });
    html += '</div>';
  }

  document.getElementById("phraseBankContent").innerHTML = html;
}

function insertPhrase(text) {
  const input = document.getElementById("txtIn");
  const start = input.selectionStart;
  const end = input.selectionEnd;
  const before = input.value.substring(0, start);
  const after = input.value.substring(end);
  const separator = before.length > 0 && !before.endsWith(' ') ? ' ' : '';
  input.value = before + separator + text + after;
  input.focus();
  const newPos = start + separator.length + text.length;
  input.setSelectionRange(newPos, newPos);
}

// ===== Topic Picker for Teil 2 & 3 =====
function showTopicPicker(part) {
  const label = part === 'teil2' ? 'Teil 2: Thema eingeben' : 'Teil 3: Szenario eingeben';
  const placeholder = part === 'teil2'
    ? 'z.B. Gesunde Ernährung \u2014 Was essen Sie normalerweise? Ist Ihnen gesundes Essen wichtig?'
    : 'z.B. Einen Ausflug planen \u2014 Sie möchten mit Freunden einen Tagesausflug machen. Planen Sie zusammen.';

  document.getElementById("topics").innerHTML = `
    <div class="topic-picker">
      <div class="topic-picker-label">
        <button class="topic-picker-back" onclick="restoreTELCTopicButtons()">\u2190</button>
        <span>${label}</span>
      </div>
      <textarea id="customTopicInput" placeholder="${placeholder}"></textarea>
      <div class="topic-picker-buttons">
        <button class="tp-random" onclick="startTELCPart('${part}')">&#x1F3B2; Zufällig</button>
        <button class="tp-start" onclick="startTELCPart('${part}', document.getElementById('customTopicInput').value.trim() || null)">&#x25B6; Start</button>
      </div>
    </div>
  `;
  document.getElementById("customTopicInput").focus();
}

function restoreTELCTopicButtons() {
  document.getElementById("topics").innerHTML = `
    <button class="topic-btn" onclick="startTELCPart('teil1')" style="background:rgba(59,130,246,0.1);border-color:rgba(59,130,246,0.3);">Teil 1: Kontaktaufnahme</button>
    <button class="topic-btn" onclick="showTopicPicker('teil2')" style="background:rgba(16,185,129,0.1);border-color:rgba(16,185,129,0.3);">Teil 2: Gespräch über Thema</button>
    <button class="topic-btn" onclick="showTopicPicker('teil3')" style="background:rgba(251,191,36,0.1);border-color:rgba(251,191,36,0.3);">Teil 3: Gemeinsam planen</button>
    <button class="topic-btn" onclick="startFullSimulation()" style="background:rgba(239,68,68,0.1);border-color:rgba(239,68,68,0.3);color:#f87171;font-weight:600;">&#x1F3C6; Simulation (1\u21922\u21923)</button>
  `;
}

// ===== Embassy Interview Functions =====
function startEmbassyPhase(phase) {
  console.log(`Starting embassy ${phase}`);
  currentEmbassyPhase = phase;
  embassyUserMsgCount = 0;

  // In simulation mode: don't clear messages, add separator instead
  if(embassySimulationMode) {
    embassySimPhaseStart[phase] = msgs.length;
    const sep = document.createElement('div');
    sep.className = 'sim-separator';
    sep.textContent = '━━━ ' + EMBASSY_PHASES[phase] + ' ━━━';
    document.getElementById("messages").appendChild(sep);
    updateEmbassySimProgress(phase);
  } else {
    // Clear previous messages and start fresh
    msgs = [];
    document.getElementById("messages").innerHTML = "";
    restoreEmbassyPhaseButtons();
    updateEmbassyPhaseButtons(phase);
  }
  document.getElementById("turnCount").textContent = "0 lượt trả lời";

  // Send the phase starter message
  const starter = EMBASSY_STARTERS[phase];
  msgs.push({role: "assistant", content: starter});
  addBubble("assistant", starter, 0);
  saveMessageToDB("assistant", starter);
  if(autoSpeak) speak(starter, 0);

  // Update phrase bank if open
  const phraseBankPanel = document.getElementById("phraseBankPanel");
  if(phraseBankPanel && phraseBankPanel.classList.contains("open")) {
    renderPhraseBank();
  }
}

function restoreEmbassyPhaseButtons() {
  document.getElementById("topics").innerHTML = `
    <button class="topic-btn" onclick="startEmbassyPhase('phase1')" style="background:rgba(168,85,247,0.1);border-color:rgba(168,85,247,0.3);">Phase 1: Persönliche Daten</button>
    <button class="topic-btn" onclick="startEmbassyPhase('phase2')" style="background:rgba(59,130,246,0.1);border-color:rgba(59,130,246,0.3);">Phase 2: Sprachkurs & Motivation</button>
    <button class="topic-btn" onclick="startEmbassyPhase('phase3')" style="background:rgba(251,191,36,0.1);border-color:rgba(251,191,36,0.3);">Phase 3: Pläne & Finanzen</button>
    <button class="topic-btn" onclick="startEmbassyPhase('phase4')" style="background:rgba(239,68,68,0.1);border-color:rgba(239,68,68,0.3);">Phase 4: Fähigkeiten & Risiken</button>
    <button class="topic-btn" onclick="startFullEmbassyInterview()" style="background:rgba(34,197,94,0.1);border-color:rgba(34,197,94,0.3);color:#22c55e;font-weight:600;">🏛️ Vollständiges Interview (1→2→3→4)</button>
  `;
}

function updateEmbassyPhaseButtons(activePhase) {
  const buttons = document.querySelectorAll('.topic-btn');
  const phaseColors = {
    phase1: 'rgba(168,85,247,0.2)',
    phase2: 'rgba(59,130,246,0.2)',
    phase3: 'rgba(251,191,36,0.2)',
    phase4: 'rgba(239,68,68,0.2)'
  };
  const phaseIndex = { phase1: 0, phase2: 1, phase3: 2, phase4: 3 };

  buttons.forEach(btn => {
    btn.style.opacity = '0.6';
    btn.style.background = 'rgba(255,255,255,0.05)';
  });

  const idx = phaseIndex[activePhase];
  if(idx !== undefined && buttons[idx]) {
    buttons[idx].style.opacity = '1';
    buttons[idx].style.background = phaseColors[activePhase];
  }
}

function startFullEmbassyInterview() {
  console.log("🏛️ Starting full embassy interview simulation");
  embassySimulationMode = true;
  embassySimPhaseStart = {};
  msgs = [];
  document.getElementById("messages").innerHTML = "";

  // Replace phase buttons with progress bar
  document.getElementById("topics").innerHTML = `
    <div class="sim-progress">
      <div class="sim-step active" id="embSimStep1">Phase 1</div>
      <div class="sim-step-arrow">→</div>
      <div class="sim-step" id="embSimStep2">Phase 2</div>
      <div class="sim-step-arrow">→</div>
      <div class="sim-step" id="embSimStep3">Phase 3</div>
      <div class="sim-step-arrow">→</div>
      <div class="sim-step" id="embSimStep4">Phase 4</div>
    </div>
  `;

  // Show intro message
  const introDiv = document.createElement('div');
  introDiv.innerHTML = `
    <div style="background:rgba(168,85,247,0.1);border:1px solid rgba(168,85,247,0.3);color:#a855f7;padding:16px;border-radius:12px;margin:16px;text-align:center;">
      <div style="font-size:16px;font-weight:700;margin-bottom:8px;">🏛️ Sprachvisum-Interview Simulation</div>
      <div style="font-size:13px;color:#94a3b8;">Phase 1 (Persönlich) → Phase 2 (Motivation) → Phase 3 (Finanzen) → Phase 4 (Risiken)</div>
    </div>
  `;
  document.getElementById("messages").appendChild(introDiv);

  // Start with Phase 1
  startEmbassyPhase('phase1');
}

function updateEmbassySimProgress(activePhase) {
  const steps = { phase1: 'embSimStep1', phase2: 'embSimStep2', phase3: 'embSimStep3', phase4: 'embSimStep4' };
  const order = ['phase1', 'phase2', 'phase3', 'phase4'];
  const activeIdx = order.indexOf(activePhase);

  order.forEach((phase, idx) => {
    const el = document.getElementById(steps[phase]);
    if(!el) return;
    el.className = 'sim-step';
    if(idx < activeIdx) el.classList.add('done');
    else if(idx === activeIdx) el.classList.add('active');
  });
}

function proceedToNextEmbassyPhase() {
  console.log("➡️ Proceeding to next embassy phase");

  // Remove advance hint if present
  const hint = document.getElementById('embassyAdvanceHint');
  if(hint) hint.remove();

  const phases = ['phase1', 'phase2', 'phase3', 'phase4'];
  const currentIndex = phases.indexOf(currentEmbassyPhase);
  const nextPhase = currentIndex < phases.length - 1 ? phases[currentIndex + 1] : null;

  if(nextPhase) {
    // Show transition message
    const transitionDiv = document.createElement('div');
    transitionDiv.innerHTML = `
      <div style="background:rgba(34,197,94,0.1);border:1px solid rgba(34,197,94,0.3);color:#22c55e;padding:8px 12px;border-radius:8px;margin:8px 16px;text-align:center;font-size:13px;">
        ➡️ <strong>Weiter zu ${EMBASSY_PHASES[nextPhase]}</strong>
      </div>
    `;
    const messagesEl = document.getElementById("messages");
    messagesEl.appendChild(transitionDiv);
    messagesEl.scrollTop = messagesEl.scrollHeight;

    setTimeout(() => {
      startEmbassyPhase(nextPhase);
    }, 1000);
  } else {
    // All phases completed
    const completedDiv = document.createElement('div');
    completedDiv.innerHTML = `
      <div style="background:rgba(34,197,94,0.1);border:1px solid rgba(34,197,94,0.3);color:#22c55e;padding:16px;border-radius:12px;margin:16px;text-align:center;">
        <div style="font-size:16px;font-weight:700;margin-bottom:8px;">🎉 Interview beendet!</div>
        <div style="font-size:14px;">Alle vier Phasen des Sprachvisum-Interviews wurden abgeschlossen. Gut gemacht!</div>
        <div style="margin-top:12px;">
          <button onclick="goBack()" style="background:rgba(168,85,247,0.2);border:1px solid rgba(168,85,247,0.3);color:#a855f7;padding:8px 16px;border-radius:8px;cursor:pointer;font-size:13px;">🏠 Về trang chủ</button>
        </div>
      </div>
    `;
    const messagesEl = document.getElementById("messages");
    messagesEl.appendChild(completedDiv);
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }
}

function maybeShowEmbassyAdvanceHint() {
  embassyUserMsgCount++;

  // Show hint every 4 user messages
  if(embassyUserMsgCount % 4 !== 0) return;

  // Don't show if already showing
  if(document.getElementById('embassyAdvanceHint')) return;

  const phases = ['phase1', 'phase2', 'phase3', 'phase4'];
  const currentIndex = phases.indexOf(currentEmbassyPhase);
  const isLastPhase = currentIndex >= phases.length - 1;
  const nextLabel = isLastPhase ? null : EMBASSY_PHASES[phases[currentIndex + 1]];

  const hintDiv = document.createElement('div');
  hintDiv.id = 'embassyAdvanceHint';
  hintDiv.innerHTML = `
    <div style="background:rgba(168,85,247,0.08);border:1px solid rgba(168,85,247,0.25);padding:8px 12px;border-radius:8px;margin:8px 16px;display:flex;align-items:center;justify-content:space-between;font-size:12px;">
      <span style="color:#a855f7;">💡 ${embassyUserMsgCount} câu trả lời trong phase này</span>
      <div style="display:flex;gap:6px;">
        ${!isLastPhase ? `<button onclick="proceedToNextEmbassyPhase()" style="background:rgba(34,197,94,0.15);border:1px solid rgba(34,197,94,0.3);color:#22c55e;padding:4px 10px;border-radius:6px;cursor:pointer;font-size:11px;">➡️ ${nextLabel}</button>` : ''}
        <button onclick="this.parentNode.parentNode.parentNode.remove()" style="background:rgba(255,255,255,0.05);border:1px solid rgba(255,255,255,0.15);color:#94a3b8;padding:4px 10px;border-radius:6px;cursor:pointer;font-size:11px;">Weiter üben</button>
      </div>
    </div>
  `;

  const messagesEl = document.getElementById("messages");
  messagesEl.appendChild(hintDiv);
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

// ===== B1 Structure Analysis =====
function analyzeB1Structures(userMessages) {
  const text = userMessages.map(m => m.content).join(' ');
  const results = {};

  for(const catKey in B1_STRUCTURE_PATTERNS) {
    const cat = B1_STRUCTURE_PATTERNS[catKey];
    const used = [];
    const missed = [];

    cat.patterns.forEach(p => {
      if(p.regex.test(text)) {
        used.push(p);
      } else {
        missed.push(p);
      }
    });

    results[catKey] = { label: cat.label, used, missed };
  }

  return results;
}

function renderB1StructureHTML(structures) {
  let html = '<div class="b1-structures"><h3>📐 B1 Sprachstrukturen</h3>';

  for(const catKey in structures) {
    const cat = structures[catKey];
    html += '<div class="structure-category">';
    html += '<div class="structure-category-label">' + cat.label +
      ' (' + cat.used.length + '/' + (cat.used.length + cat.missed.length) + ')</div>';

    cat.used.forEach(p => {
      html += '<div class="structure-item used">✓ ' + p.name + '</div>';
    });

    cat.missed.forEach(p => {
      html += '<div class="structure-item missed">✗ ' + p.name + '</div>';
      html += '<div class="structure-item"><span class="structure-example">→ ' + p.example + '</span></div>';
    });

    html += '</div>';
  }

  html += '</div>';
  return html;
}

// ===== Partner Mode =====
function addBubblePartner(speaker, content, idx) {
  const parts = content.split(/\[FEEDBACK\]:/i);
  const main = parts[0].trim();
  const fb = parts.slice(1).join("").trim();

  const wrap = document.createElement("div");
  wrap.className = 'partner-wrap ' + speaker;

  const tag = document.createElement("div");
  tag.className = 'partner-speaker-tag ' + speaker;
  const speakerInfo = DEMO_SPEAKERS[speaker] || { label: speaker, emoji: "🤖" };
  tag.textContent = speakerInfo.emoji + ' ' + speakerInfo.label;
  wrap.appendChild(tag);

  const bub = document.createElement("div");
  bub.className = 'partner-bub ' + speaker;
  bub.textContent = main;

  // Add speak button
  const spkBtn = document.createElement("button");
  spkBtn.className = "partner-spk-btn";
  spkBtn.textContent = "🔊";
  spkBtn.onclick = () => speak(main, idx);
  bub.appendChild(spkBtn);

  wrap.appendChild(bub);

  if(fb && vietnameseFeedback) {
    const fbDiv = document.createElement("div");
    fbDiv.className = "fb";
    fbDiv.style.marginLeft = "0";
    fbDiv.innerHTML = '💡 <strong>Phản hồi:</strong> ' + esc(fb);
    wrap.appendChild(fbDiv);
  }

  const el = document.getElementById("messages");
  el.appendChild(wrap);
  el.scrollTop = el.scrollHeight;

  updateScoreButtonVisibility();
}

function toggleTTSSpeed() {
  // Cycle through speeds: 0.8, 1.0, 1.2, 1.5, 1.8
  const speeds = [0.8, 1.0, 1.2, 1.5, 1.8];
  const currentIndex = speeds.indexOf(ttsSpeed);
  const nextIndex = (currentIndex + 1) % speeds.length;
  ttsSpeed = speeds[nextIndex];

  // Update button text
  const speedBtn = document.getElementById("speedToggle");
  speedBtn.textContent = `⚡ Tốc độ: ${ttsSpeed}x`;

  // Show feedback
  console.log("TTS speed changed to:", ttsSpeed);

  // Test the new speed if not currently speaking
  if(!isSpeaking && msgs.length > 0) {
    // Quick test with a short German phrase
    testTTSSpeed();
  }
}

function testTTSSpeed() {
  if(isSpeaking) return; // Don't interrupt current speech

  const synth = window.speechSynthesis;
  if(!synth) return;

  const testText = "Neue Geschwindigkeit";
  const utterance = new SpeechSynthesisUtterance(testText);
  utterance.lang = "de-DE";
  utterance.rate = isMobile ? Math.min(ttsSpeed, 1.1) : ttsSpeed;
  utterance.volume = 0.7; // Quieter for test
  utterance.pitch = 1.05;

  // Find German voice
  const voices = synth.getVoices();
  const de = voices.find(v => v.lang.startsWith("de"));
  if(de) utterance.voice = de;

  synth.speak(utterance);
}

// ===== Demo Exam Mode =====
let demoPlaying = false, demoPaused = false, demoTimer = null;
let demoCurrentTeil = 'teil1', demoGlobalIndex = 0;
let demoShowVN = true, demoAutoTTS = true;
let demoDelay = 3000, demoAllMessages = [];
let demoTTSStartTime = 0;
let demoMode = 'telc'; // 'telc' or 'embassy'

function startDemoExam() {
  demoMode = 'telc';
  document.getElementById('landing').style.display = 'none';
  document.getElementById('chat').style.display = 'none';

  // Set TELC header
  document.getElementById('demoHeader').innerHTML = `
    <div style="display:flex;align-items:center;justify-content:space-between;">
      <button onclick="exitDemoExam()" style="padding:6px 12px;border-radius:8px;border:1px solid rgba(245,158,11,0.3);background:rgba(245,158,11,0.1);color:#fbbf24;font-size:12px;cursor:pointer;">\u2190 V\u1ec1</button>
      <div class="demo-title">\ud83c\udfac Demo TELC B1 M\u00fcndliche Pr\u00fcfung</div>
      <div style="width:50px;"></div>
    </div>
    <div class="demo-legend">
      <span><span style="color:#f59e0b;">\u25cf</span> Pr\u00fcfer</span>
      <span><span style="color:#3b82f6;">\u25cf</span> Kandidat A</span>
      <span><span style="color:#10b981;">\u25cf</span> Kandidat B</span>
    </div>
    <div class="demo-teil-nav">
      <button class="demo-teil-btn active" onclick="jumpToTeil('teil1')">Teil 1</button>
      <button class="demo-teil-btn" onclick="jumpToTeil('teil2')">Teil 2</button>
      <button class="demo-teil-btn" onclick="jumpToTeil('teil3')">Teil 3</button>
    </div>
  `;

  const el = document.getElementById('demoExam');
  el.style.display = 'flex';
  demoReset();
  jumpToTeil('teil1');
  demoPlay();
}

function startDemoEmbassy() {
  demoMode = 'embassy';
  document.getElementById('landing').style.display = 'none';
  document.getElementById('chat').style.display = 'none';

  // Set embassy header
  document.getElementById('demoHeader').innerHTML = `
    <div style="display:flex;align-items:center;justify-content:space-between;">
      <button onclick="exitDemoExam()" style="padding:6px 12px;border-radius:8px;border:1px solid rgba(168,85,247,0.3);background:rgba(168,85,247,0.1);color:#c084fc;font-size:12px;cursor:pointer;">\u2190 V\u1ec1</button>
      <div class="demo-title" style="color:#c084fc;">\ud83c\udfec Demo Ph\u1ecfng v\u1ea5n Sprachvisum</div>
      <div style="width:50px;"></div>
    </div>
    <div class="demo-legend">
      <span><span style="color:#a855f7;">\u25cf</span> Beamter</span>
      <span><span style="color:#22c55e;">\u25cf</span> Antragsteller</span>
    </div>
    <div class="demo-teil-nav">
      <button class="demo-teil-btn active" onclick="jumpToTeil('phase1')" style="border-color:rgba(168,85,247,0.3);background:rgba(168,85,247,0.08);color:#c084fc;">Phase 1</button>
      <button class="demo-teil-btn" onclick="jumpToTeil('phase2')" style="border-color:rgba(168,85,247,0.3);background:rgba(168,85,247,0.08);color:#c084fc;">Phase 2</button>
      <button class="demo-teil-btn" onclick="jumpToTeil('phase3')" style="border-color:rgba(168,85,247,0.3);background:rgba(168,85,247,0.08);color:#c084fc;">Phase 3</button>
      <button class="demo-teil-btn" onclick="jumpToTeil('phase4')" style="border-color:rgba(168,85,247,0.3);background:rgba(168,85,247,0.08);color:#c084fc;">Phase 4</button>
    </div>
  `;

  const el = document.getElementById('demoExam');
  el.style.display = 'flex';
  demoReset();
  jumpToTeil('phase1');
  demoPlay();
}

function exitDemoExam() {
  demoStop();
  document.getElementById('demoExam').style.display = 'none';
  if (document.getElementById('app').style.display !== 'none') {
    document.getElementById('landing').style.display = '';
  } else {
    document.getElementById('apiScreen').style.display = '';
  }
}

function skipToDemo() {
  document.getElementById('apiScreen').style.display = 'none';
  const app = document.getElementById('app');
  app.style.display = '';
  document.getElementById('landing').style.display = 'none';
  document.getElementById('chat').style.display = 'none';
  // Default to TELC demo from skip button
  startDemoExam();
}

function buildDemoMessageList(startSection) {
  const script = demoMode === 'embassy' ? DEMO_EMBASSY_SCRIPT : DEMO_EXAM_SCRIPT;
  const sections = demoMode === 'embassy'
    ? ['phase1', 'phase2', 'phase3', 'phase4']
    : ['teil1', 'teil2', 'teil3'];
  const startIdx = sections.indexOf(startSection);
  const result = [];
  for (let i = startIdx; i < sections.length; i++) {
    const s = sections[i];
    const data = script[s];
    result.push({ type: 'separator', teil: s, title: data.title, description: data.description });
    for (const msg of data.messages) {
      result.push({ type: 'message', teil: s, ...msg });
    }
  }
  return result;
}

function addDemoTeilSeparator(teil) {
  const script = demoMode === 'embassy' ? DEMO_EMBASSY_SCRIPT : DEMO_EXAM_SCRIPT;
  const data = script[teil];
  const container = document.getElementById('demoMessages');
  const div = document.createElement('div');
  div.className = 'demo-teil-separator';
  div.innerHTML = `${data.title}<div class="teil-desc">${data.description}</div>`;
  container.appendChild(div);
  container.scrollTop = container.scrollHeight;
}

function addDemoBubble(speaker, de, vn, tip) {
  const container = document.getElementById('demoMessages');
  const speakers = demoMode === 'embassy' ? DEMO_EMBASSY_SPEAKERS : DEMO_SPEAKERS;
  const info = speakers[speaker];
  const wrap = document.createElement('div');
  wrap.className = `demo-wrap ${speaker}`;

  const tag = document.createElement('div');
  tag.className = `demo-speaker-tag ${speaker}`;
  tag.textContent = `${info.emoji} ${info.label}`;
  wrap.appendChild(tag);

  const row = document.createElement('div');
  row.className = 'demo-row';
  const bub = document.createElement('div');
  bub.className = `demo-bub ${speaker}`;
  bub.textContent = de;

  const ttsBtn = document.createElement('button');
  ttsBtn.className = 'demo-tts-btn';
  ttsBtn.textContent = '\ud83d\udd0a';
  ttsBtn.title = 'Nghe';
  ttsBtn.onclick = function(e) { e.stopPropagation(); demoSpeakText(de); };
  bub.appendChild(ttsBtn);
  row.appendChild(bub);
  wrap.appendChild(row);

  if (vn) {
    const vnEl = document.createElement('div');
    vnEl.className = 'demo-vn';
    vnEl.textContent = vn;
    vnEl.style.display = demoShowVN ? '' : 'none';
    wrap.appendChild(vnEl);
  }
  if (tip) {
    const tipEl = document.createElement('div');
    tipEl.className = 'demo-tip';
    tipEl.textContent = tip;
    tipEl.style.display = demoShowVN ? '' : 'none';
    wrap.appendChild(tipEl);
  }

  container.appendChild(wrap);
  container.scrollTop = container.scrollHeight;
}

function demoPlay() {
  if (demoPaused) {
    demoPaused = false;
    const synth = window.speechSynthesis;
    if (synth && synth.paused) {
      // Was paused mid-speech: resume TTS, poll for completion
      synth.resume();
      demoTTSStartTime = Date.now(); // Reset timeout for resumed speech
      demoTimer = setTimeout(() => demoWaitTTSThenNext(), 200);
    } else {
      // Was paused between messages: schedule next step
      demoTimer = setTimeout(() => demoStepNext(), 500);
    }
    return;
  }
  if (demoPlaying) return;
  demoPlaying = true;
  demoPaused = false;
  demoStepNext();
}

function demoPause() {
  demoPaused = true;
  if (demoTimer) { clearTimeout(demoTimer); demoTimer = null; }
  const synth = window.speechSynthesis;
  if (synth && synth.speaking) synth.pause();
}

function demoStop() {
  demoPlaying = false;
  demoPaused = false;
  if (demoTimer) { clearTimeout(demoTimer); demoTimer = null; }
  const synth = window.speechSynthesis;
  if (synth) synth.cancel();
}

function demoReset() {
  demoStop();
  demoGlobalIndex = 0;
  document.getElementById('demoMessages').innerHTML = '';
  updateDemoProgress();
}

function demoWaitTTSThenNext() {
  // Poll until TTS finishes, then wait demoDelay before next step
  // Includes a max-wait safeguard for Chrome bug where synth.speaking stays true
  if (!demoPlaying || demoPaused) return;
  const synth = window.speechSynthesis;
  const elapsed = Date.now() - demoTTSStartTime;
  const maxWait = 30000; // 30s max wait per message, covers even long sentences
  const stillSpeaking = synth && (synth.speaking || synth.pending);

  if (stillSpeaking && elapsed < maxWait) {
    // Chrome bug workaround: periodically call resume() to unstick paused speech
    if (elapsed > 5000 && synth.speaking && !synth.pending) {
      synth.pause();
      synth.resume();
    }
    demoTimer = setTimeout(() => demoWaitTTSThenNext(), 250);
  } else {
    // Either TTS finished or we hit the safety timeout
    if (stillSpeaking) synth.cancel(); // Force stop if stuck
    demoTimer = setTimeout(() => demoStepNext(), demoDelay);
  }
}

function demoStepNext() {
  if (!demoPlaying || demoPaused) return;
  if (demoGlobalIndex >= demoAllMessages.length) {
    demoPlaying = false;
    updateDemoProgress();
    return;
  }

  const item = demoAllMessages[demoGlobalIndex];
  if (item.type === 'separator') {
    addDemoTeilSeparator(item.teil);
    updateDemoTeilButtons(item.teil);
    demoCurrentTeil = item.teil;
    demoGlobalIndex++;
    updateDemoProgress();
    demoTimer = setTimeout(() => demoStepNext(), 800);
  } else {
    addDemoBubble(item.speaker, item.de, item.vn, item.tip);
    demoGlobalIndex++;
    updateDemoProgress();
    if (demoAutoTTS) {
      demoTTSStartTime = Date.now();
      demoSpeakText(item.de);
      demoTimer = setTimeout(() => demoWaitTTSThenNext(), 300);
    } else {
      demoTimer = setTimeout(() => demoStepNext(), demoDelay);
    }
  }
}

function jumpToTeil(teil) {
  demoStop();
  demoGlobalIndex = 0;
  document.getElementById('demoMessages').innerHTML = '';
  demoAllMessages = buildDemoMessageList(teil);
  demoCurrentTeil = teil;
  updateDemoTeilButtons(teil);
  updateDemoProgress();
}

function demoToggleVN() {
  demoShowVN = !demoShowVN;
  const btn = document.getElementById('demoVNBtn');
  btn.textContent = demoShowVN ? 'VN: On' : 'VN: Off';
  btn.classList.toggle('active', demoShowVN);
  document.querySelectorAll('.demo-vn, .demo-tip').forEach(el => {
    el.style.display = demoShowVN ? '' : 'none';
  });
}

function demoToggleTTS() {
  demoAutoTTS = !demoAutoTTS;
  const btn = document.getElementById('demoTTSBtn');
  btn.textContent = demoAutoTTS ? 'TTS: On' : 'TTS: Off';
  btn.classList.toggle('active', demoAutoTTS);
  if (!demoAutoTTS) stopAllSpeech();
}

function demoToggleSpeed() {
  const speeds = [2000, 3000, 5000, 8000];
  const labels = ['2s', '3s', '5s', '8s'];
  const idx = speeds.indexOf(demoDelay);
  const next = (idx + 1) % speeds.length;
  demoDelay = speeds[next];
  document.getElementById('demoSpeedBtn').textContent = '\u23f1 ' + labels[next];
}

function demoSpeakText(text) {
  const synth = window.speechSynthesis;
  if (!synth) return;
  synth.cancel();
  const cleaned = cleanTextForTTS(text);
  const chunks = breakIntoChunks(cleaned);
  if (chunks.length === 0) return;
  const voices = synth.getVoices();
  const deVoice = voices.find(v => v.lang.startsWith('de'));
  for (const chunk of chunks) {
    const u = new SpeechSynthesisUtterance(chunk);
    u.lang = 'de-DE';
    u.rate = 0.9;
    u.pitch = 1.05;
    if (deVoice) u.voice = deVoice;
    synth.speak(u);
  }
}

function updateDemoTeilButtons(activeTeil) {
  const btns = document.querySelectorAll('.demo-teil-btn');
  const sections = demoMode === 'embassy'
    ? ['phase1', 'phase2', 'phase3', 'phase4']
    : ['teil1', 'teil2', 'teil3'];
  btns.forEach((btn, i) => {
    btn.classList.toggle('active', sections[i] === activeTeil);
  });
}

function updateDemoProgress() {
  const total = demoAllMessages.length;
  const shown = Math.min(demoGlobalIndex, total);
  document.getElementById('demoProgress').textContent = `${shown} / ${total}`;
}

// TELC Timer Functions
function startTELCTimer(part) {
  if(!part || !TELC_DURATIONS[part]) return;

  // Stop any existing timer
  stopTELCTimer();

  console.log(`🕐 Starting TELC timer for ${part}: ${TELC_DURATIONS[part]} seconds`);

  telcTimeLeft = TELC_DURATIONS[part];
  telcTimerStarted = true;
  telcTimeWarningShown = false;

  // Show timer
  const timerEl = document.getElementById("telcTimer");
  timerEl.style.display = "block";
  timerEl.className = ""; // Reset classes

  // Update display immediately
  updateTimerDisplay();

  // Start countdown
  telcTimer = setInterval(() => {
    telcTimeLeft--;
    updateTimerDisplay();

    // Warning at 1 minute left
    if(telcTimeLeft === 60 && !telcTimeWarningShown) {
      showTimeWarning();
      telcTimeWarningShown = true;
    }

    // Time up!
    if(telcTimeLeft <= 0) {
      handleTimeUp();
    }
  }, 1000);
}

function stopTELCTimer() {
  if(telcTimer) {
    clearInterval(telcTimer);
    telcTimer = null;
  }
  telcTimerStarted = false;
  telcTimeWarningShown = false;

  // Hide timer
  const timerEl = document.getElementById("telcTimer");
  timerEl.style.display = "none";
  timerEl.className = "";

  console.log("🕐 TELC timer stopped");
}

function updateTimerDisplay() {
  const minutes = Math.floor(telcTimeLeft / 60);
  const seconds = telcTimeLeft % 60;
  const display = `${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`;

  const timerEl = document.getElementById("telcTimer");
  const displayEl = document.getElementById("telcTimeDisplay");

  displayEl.textContent = display;

  // Color coding
  if(telcTimeLeft <= 30) {
    timerEl.className = "danger";
  } else if(telcTimeLeft <= 60) {
    timerEl.className = "warning";
  } else {
    timerEl.className = "";
  }
}

function showTimeWarning() {
  console.log("⚠️ TELC Time Warning: 1 minute left");

  // Show warning message
  const warningDiv = document.createElement('div');
  warningDiv.className = 'time-warning';
  warningDiv.innerHTML = `
    <div style="background:rgba(251,191,36,0.1);border:1px solid rgba(251,191,36,0.3);color:#fbbf24;padding:8px 12px;border-radius:8px;margin:8px 16px;text-align:center;font-size:13px;">
      ⚠️ <strong>Noch 1 Minute!</strong> Zeit läuft ab...
    </div>
  `;

  const messagesEl = document.getElementById("messages");
  messagesEl.appendChild(warningDiv);
  messagesEl.scrollTop = messagesEl.scrollHeight;

  // Auto-remove after 3 seconds
  setTimeout(() => {
    if(warningDiv.parentNode) {
      warningDiv.parentNode.removeChild(warningDiv);
    }
  }, 3000);
}

function handleTimeUp() {
  console.log("⏰ TELC Time Up!");

  stopTELCTimer();

  // In simulation mode: auto-advance after brief message
  if(telcSimulationMode) {
    const autoDiv = document.createElement('div');
    autoDiv.innerHTML = `
      <div style="background:rgba(239,68,68,0.1);border:1px solid rgba(239,68,68,0.3);color:#f87171;padding:8px 12px;border-radius:8px;margin:8px 16px;text-align:center;font-size:13px;">
        ⏰ <strong>Zeit ist um!</strong> Automatisch weiter...
      </div>
    `;
    const messagesEl = document.getElementById("messages");
    messagesEl.appendChild(autoDiv);
    messagesEl.scrollTop = messagesEl.scrollHeight;
    setTimeout(() => proceedToNextPart(), 2000);
    return;
  }

  // Show time up message with suggestions
  const suggestions = TELC_SUGGESTIONS[currentTELCPart] || [];
  const randomSuggestion = suggestions[Math.floor(Math.random() * suggestions.length)];

  const timeUpDiv = document.createElement('div');
  timeUpDiv.className = 'time-up-panel';
  timeUpDiv.innerHTML = `
    <div style="background:rgba(239,68,68,0.1);border:1px solid rgba(239,68,68,0.3);color:#f87171;padding:16px;border-radius:12px;margin:16px;text-align:center;">
      <div style="font-size:16px;font-weight:700;margin-bottom:8px;">⏰ Zeit ist um!</div>
      <div style="font-size:14px;margin-bottom:12px;">
        ${currentTELCPart?.toUpperCase()} ist beendet. Hier ist ein Vorschlag für Ihre Antwort:
      </div>

      <div style="background:rgba(34,197,94,0.1);border:1px solid rgba(34,197,94,0.3);color:#22c55e;padding:12px;border-radius:8px;margin:8px 0;font-style:italic;">
        "💡 ${randomSuggestion}"
      </div>

      <div style="display:flex;gap:8px;justify-content:center;margin-top:12px;">
        <button onclick="extendTELCTime()" style="background:rgba(59,130,246,0.1);border:1px solid rgba(59,130,246,0.3);color:#3b82f6;padding:6px 12px;border-radius:6px;cursor:pointer;font-size:12px;">
          +2 Min Verlängern
        </button>
        <button onclick="proceedToNextPart()" style="background:rgba(34,197,94,0.1);border:1px solid rgba(34,197,94,0.3);color:#22c55e;padding:6px 12px;border-radius:6px;cursor:pointer;font-size:12px;">
          Weiter zum nächsten Teil
        </button>
        <button onclick="closeTimeUpPanel()" style="background:rgba(255,255,255,0.1);border:1px solid rgba(255,255,255,0.2);color:#cbd5e1;padding:6px 12px;border-radius:6px;cursor:pointer;font-size:12px;">
          Schließen
        </button>
      </div>
    </div>
  `;

  const messagesEl = document.getElementById("messages");
  messagesEl.appendChild(timeUpDiv);
  messagesEl.scrollTop = messagesEl.scrollHeight;

  // Store reference for cleanup
  window.currentTimeUpPanel = timeUpDiv;
}

function extendTELCTime() {
  console.log("⏰ Extending TELC time by 2 minutes");

  // Add 2 minutes
  telcTimeLeft += 120;
  telcTimerStarted = true;

  // Restart timer
  telcTimer = setInterval(() => {
    telcTimeLeft--;
    updateTimerDisplay();

    if(telcTimeLeft <= 0) {
      handleTimeUp();
    }
  }, 1000);

  // Show timer again
  const timerEl = document.getElementById("telcTimer");
  timerEl.style.display = "block";
  updateTimerDisplay();

  // Close time up panel
  closeTimeUpPanel();

  // Show extension message
  const extendDiv = document.createElement('div');
  extendDiv.innerHTML = `
    <div style="background:rgba(59,130,246,0.1);border:1px solid rgba(59,130,246,0.3);color:#3b82f6;padding:8px 12px;border-radius:8px;margin:8px 16px;text-align:center;font-size:13px;">
      ⏰ <strong>Zeit verlängert!</strong> +2 Minuten hinzugefügt
    </div>
  `;

  const messagesEl = document.getElementById("messages");
  messagesEl.appendChild(extendDiv);
  messagesEl.scrollTop = messagesEl.scrollHeight;

  // Auto-remove after 3 seconds
  setTimeout(() => {
    if(extendDiv.parentNode) {
      extendDiv.parentNode.removeChild(extendDiv);
    }
  }, 3000);
}

function proceedToNextPart() {
  console.log("➡️ Proceeding to next TELC part");

  closeTimeUpPanel();

  // Determine next part
  const parts = ['teil1', 'teil2', 'teil3'];
  const currentIndex = parts.indexOf(currentTELCPart);
  const nextPart = currentIndex < parts.length - 1 ? parts[currentIndex + 1] : null;

  if(nextPart) {
    // Start next part
    setTimeout(() => {
      startTELCPart(nextPart);
    }, 1000);

    // Show transition message
    const transitionDiv = document.createElement('div');
    transitionDiv.innerHTML = `
      <div style="background:rgba(34,197,94,0.1);border:1px solid rgba(34,197,94,0.3);color:#22c55e;padding:8px 12px;border-radius:8px;margin:8px 16px;text-align:center;font-size:13px;">
        ➡️ <strong>Weiter zu ${nextPart.toUpperCase()}</strong>
      </div>
    `;

    const messagesEl = document.getElementById("messages");
    messagesEl.appendChild(transitionDiv);
    messagesEl.scrollTop = messagesEl.scrollHeight;
  } else {
    // All parts completed
    if(telcSimulationMode) {
      // Combined scoring for simulation mode
      requestCombinedScoring();
    } else {
      const completedDiv = document.createElement('div');
      completedDiv.innerHTML = `
        <div style="background:rgba(34,197,94,0.1);border:1px solid rgba(34,197,94,0.3);color:#22c55e;padding:16px;border-radius:12px;margin:16px;text-align:center;">
          <div style="font-size:16px;font-weight:700;margin-bottom:8px;">🎉 TELC B1 Prüfung beendet!</div>
          <div style="font-size:14px;">Alle drei Teile wurden abgeschlossen. Gut gemacht!</div>
        </div>
      `;

      const messagesEl = document.getElementById("messages");
      messagesEl.appendChild(completedDiv);
      messagesEl.scrollTop = messagesEl.scrollHeight;
    }
  }
}

function closeTimeUpPanel() {
  if(window.currentTimeUpPanel && window.currentTimeUpPanel.parentNode) {
    window.currentTimeUpPanel.parentNode.removeChild(window.currentTimeUpPanel);
    window.currentTimeUpPanel = null;
  }
}

// ===== Full Exam Simulation =====
function startFullSimulation() {
  console.log("🏆 Starting full TELC simulation");
  telcSimulationMode = true;
  telcSimTeilStart = {};
  msgs = [];
  document.getElementById("messages").innerHTML = "";

  // Replace topic buttons with progress bar
  document.getElementById("topics").innerHTML = `
    <div class="sim-progress">
      <div class="sim-step active" id="simStep1">Teil 1</div>
      <div class="sim-step-arrow">→</div>
      <div class="sim-step" id="simStep2">Teil 2</div>
      <div class="sim-step-arrow">→</div>
      <div class="sim-step" id="simStep3">Teil 3</div>
    </div>
  `;

  // Show intro message
  const introDiv = document.createElement('div');
  introDiv.innerHTML = `
    <div style="background:rgba(239,68,68,0.1);border:1px solid rgba(239,68,68,0.3);color:#f87171;padding:16px;border-radius:12px;margin:16px;text-align:center;">
      <div style="font-size:16px;font-weight:700;margin-bottom:8px;">🏆 TELC B1 Prüfungssimulation</div>
      <div style="font-size:13px;color:#94a3b8;">Teil 1 (4 Min) → Teil 2 (6 Min) → Teil 3 (6 Min) → Gesamtbewertung (max 75 Punkte)</div>
    </div>
  `;
  document.getElementById("messages").appendChild(introDiv);

  // Start with Teil 1
  startTELCPart('teil1');
}

function updateSimProgress(activePart) {
  const steps = { teil1: 'simStep1', teil2: 'simStep2', teil3: 'simStep3' };
  const order = ['teil1', 'teil2', 'teil3'];
  const activeIdx = order.indexOf(activePart);

  order.forEach((part, idx) => {
    const el = document.getElementById(steps[part]);
    if(!el) return;
    el.className = 'sim-step';
    if(idx < activeIdx) el.classList.add('done');
    else if(idx === activeIdx) el.classList.add('active');
  });
}

async function requestCombinedScoring() {
  console.log("🏆 Requesting combined scoring for simulation");

  // Show scoring panel
  const panel = document.getElementById("scoringPanel");
  if(!panel.classList.contains("open")) {
    toggleScoring();
  }

  document.getElementById("scoringContent").innerHTML = `
    <div class="scoring-loading">
      ⏳ <strong>Đang phân tích toàn bộ bài thi...</strong><br/><br/>
      📋 Đánh giá Teil 1, Teil 2 và Teil 3<br/>
      🤖 AI đang chấm điểm theo tiêu chuẩn TELC B1<br/>
      ⭐ Vui lòng chờ...
    </div>
  `;

  const results = {};
  const parts = ['teil1', 'teil2', 'teil3'];

  try {
    for(const part of parts) {
      const startIdx = telcSimTeilStart[part] || 0;
      const endIdx = parts.indexOf(part) < parts.length - 1
        ? (telcSimTeilStart[parts[parts.indexOf(part) + 1]] || msgs.length)
        : msgs.length;

      const partMsgs = msgs.slice(startIdx, endIdx).filter(m => m.role === 'user');
      const text = partMsgs.map(m => m.content).join('\\n\\n');

      if(!text.trim()) {
        results[part] = { total_score: 0, max_score: part === 'teil1' ? 15 : 30, percentage: 0 };
        continue;
      }

      const response = await fetch('/score-telc', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Api-Key': API_KEY || '' },
        body: JSON.stringify({ session_id: sessionId, telc_part: part, conversation: text })
      });

      if(response.ok) {
        const data = JSON.parse(await response.text());
        if(data.success && data.scores) {
          results[part] = data.scores;
        } else {
          results[part] = { total_score: 0, max_score: part === 'teil1' ? 15 : 30, percentage: 0 };
        }
      } else {
        results[part] = { total_score: 0, max_score: part === 'teil1' ? 15 : 30, percentage: 0 };
      }
    }

    displayCombinedScoringResults(results);
  } catch(error) {
    console.error("Combined scoring error:", error);
    document.getElementById("scoringContent").innerHTML = `
      <div style="color:#f87171;text-align:center;padding:20px;">
        ❌ <strong>Lỗi chấm điểm:</strong> ${error.message}
      </div>
    `;
  }
}

function displayCombinedScoringResults(results) {
  const teil1 = results.teil1 || {};
  const teil2 = results.teil2 || {};
  const teil3 = results.teil3 || {};

  const total = (teil1.total_score || 0) + (teil2.total_score || 0) + (teil3.total_score || 0);
  const maxTotal = 75;
  const percentage = Math.round((total / maxTotal) * 100);
  const passed = percentage >= 60;

  // B1 structure analysis across all user messages
  const allUserMsgs = msgs.filter(m => m.role === 'user');
  const structureHTML = renderB1StructureHTML(analyzeB1Structures(allUserMsgs));

  const content = document.getElementById("scoringContent");
  content.innerHTML = `
    <div class="scoring-results">
      <div style="text-align:center;margin-bottom:16px;">
        <div class="combined-score-circle ${passed ? 'pass' : 'fail'}">
          <div style="font-size:24px;font-weight:800;">${total}</div>
          <div style="font-size:12px;color:#94a3b8;">/ ${maxTotal}</div>
        </div>
        <div style="font-size:18px;font-weight:700;color:${passed ? '#34d399' : '#f87171'};">
          ${passed ? '✅ BESTANDEN' : '❌ NICHT BESTANDEN'}
        </div>
        <div style="font-size:13px;color:#64748b;margin-top:4px;">${percentage}% — Mindestens 60% benötigt</div>
      </div>

      <div style="margin-bottom:16px;">
        <h3 style="font-size:14px;color:#94a3b8;margin-bottom:8px;">📊 Per-Teil Ergebnis</h3>
        <div class="combined-teil-bar">
          <div class="combined-teil-label">Teil 1</div>
          <div style="flex:1;background:rgba(255,255,255,0.06);border-radius:4px;overflow:hidden;">
            <div class="combined-teil-fill" style="width:${Math.round(((teil1.total_score||0)/(teil1.max_score||15))*100)}%;background:#3b82f6;"></div>
          </div>
          <div style="font-size:12px;color:#60a5fa;width:40px;text-align:right;">${teil1.total_score||0}/${teil1.max_score||15}</div>
        </div>
        <div class="combined-teil-bar">
          <div class="combined-teil-label">Teil 2</div>
          <div style="flex:1;background:rgba(255,255,255,0.06);border-radius:4px;overflow:hidden;">
            <div class="combined-teil-fill" style="width:${Math.round(((teil2.total_score||0)/(teil2.max_score||30))*100)}%;background:#10b981;"></div>
          </div>
          <div style="font-size:12px;color:#34d399;width:40px;text-align:right;">${teil2.total_score||0}/${teil2.max_score||30}</div>
        </div>
        <div class="combined-teil-bar">
          <div class="combined-teil-label">Teil 3</div>
          <div style="flex:1;background:rgba(255,255,255,0.06);border-radius:4px;overflow:hidden;">
            <div class="combined-teil-fill" style="width:${Math.round(((teil3.total_score||0)/(teil3.max_score||30))*100)}%;background:#f59e0b;"></div>
          </div>
          <div style="font-size:12px;color:#fbbf24;width:40px;text-align:right;">${teil3.total_score||0}/${teil3.max_score||30}</div>
        </div>
      </div>

      ${structureHTML}

      <div class="scoring-actions" style="margin-top:16px;">
        <button onclick="toggleScoring()" class="btn-secondary">✓ Đóng</button>
        <button onclick="goBack()" class="btn-primary">🏠 Về trang chủ</button>
      </div>
    </div>
  `;
}

</script>
</body>
</html>"""

class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        status = str(args[1]) if len(args) > 1 else "?"
        if status not in ("200", "304"):
            print(f"  {args[0]}  [{status}]")

    def do_OPTIONS(self):
        self.send_response(200)
        self._cors(); self.end_headers()

    def do_GET_old(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self._cors(); self.end_headers()
        self.wfile.write(HTML.encode("utf-8"))

    def do_POST(self):
        if self.path == "/api":
            self._handle_ai_api()
        elif self.path == "/save-message":
            self._handle_save_message()
        elif self.path == "/score-telc":
            self._handle_score_telc()
        else:
            self.send_response(404); self.end_headers(); return

    def do_GET(self):
        if self.path == "/":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self._cors(); self.end_headers()
            self.wfile.write(HTML.encode("utf-8"))
        elif self.path.startswith("/history"):
            self._handle_get_history()
        elif self.path.startswith("/stats"):
            self._handle_get_stats()
        elif self.path.startswith("/scores"):
            self._handle_get_scores()
        else:
            self.send_response(404)
            self._cors(); self.end_headers()

    def _handle_ai_api(self):

        length  = int(self.headers.get("Content-Length", 0))
        payload = json.loads(self.rfile.read(length))
        api_key = self.headers.get("X-Api-Key", "").strip()

        if not api_key:
            self._json(400, {"error": "Missing API key"})
            return

        system   = payload.get("system", "")
        messages = payload.get("messages", [])

        # Free models on OpenRouter (March 2026)
        models = [
            "openrouter/free",
            "meta-llama/llama-3.3-70b-instruct:free",
            "mistralai/mistral-small-3.1-24b-instruct:free",
            "google/gemma-3-27b-it:free",
            "google/gemma-3-12b-it:free",
            "qwen/qwen3-next-80b-a3b-instruct:free",
            "nvidia/nemotron-3-super-120b-a12b:free",
            "nvidia/nemotron-3-nano-30b-a3b:free",
            "stepfun/step-3.5-flash:free",
            "openai/gpt-oss-120b:free",
            "openai/gpt-oss-20b:free",
            "nousresearch/hermes-3-llama-3.1-405b:free",
            "minimax/minimax-m2.5:free",
            "cognitivecomputations/dolphin-mistral-24b-venice-edition:free",
        ]
        last_err = "No model available"
        for model in models:
            max_tokens = 1500

            or_body = json.dumps({
                "model": model,
                "messages": [{"role": "system", "content": payload.get("system", "")}] +
                            payload.get("messages", []),
                "max_tokens": max_tokens,
                "temperature": 0.7,
                "top_p": 1,
            }).encode()
            req = urllib.request.Request(
                "https://openrouter.ai/api/v1/chat/completions",
                data=or_body,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {api_key}",
                    "HTTP-Referer": "http://localhost:9999",
                },
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=60) as r:
                    data = json.loads(r.read())
                if data.get("error"):
                    last_err = data["error"].get("message", str(data["error"]))
                    print(f"  Model {model} → error: {last_err[:80]}")
                    continue
                print(f"  Full response: {str(data)[:400]}")
                text = None
                try:
                    import re
                    if data.get("choices"):
                        choice = data["choices"][0]
                        msg = choice.get("message", {}) or {}

                        # Try different fields in order of preference
                        candidates = [
                            msg.get("content"),
                            msg.get("reasoning"),
                            choice.get("text"),
                            choice.get("delta", {}).get("content") if choice.get("delta") else None
                        ]

                        raw = next((c for c in candidates if c), "")
                        text = re.sub(r"<think>.*?</think>", "", str(raw), flags=re.DOTALL).strip() if raw else ""

                        # Check reasoning_details array (OpenRouter format)
                        if not text:
                            rd = choice.get("reasoning_details") or []
                            text = " ".join(r.get("thinking","") for r in rd if r.get("thinking")).strip()

                        # Check if finish_reason indicates truncation and try to use partial content
                        if not text and choice.get("finish_reason") == "length":
                            # Model hit token limit, but might have started generating something
                            partial = str(msg.get("content") or "").strip()
                            if len(partial) > 10:  # Accept partial if it's substantial
                                text = partial + " [Antwort abgeschnitten - bitte kürzer fragen]"

                    elif data.get("candidates"):
                        # Gemini format
                        text = data["candidates"][0]["content"]["parts"][0]["text"]
                    elif data.get("text"):
                        # Direct text format
                        text = data["text"]

                    print(f"  Extracted text[:80]: {repr(text[:80]) if text else 'EMPTY'}")

                    # Accept shorter responses for German conversation
                    if text and len(text.strip()) < 10:
                        print(f"  Response too short ({len(text)} chars), trying next model")
                        last_err = f"Response too short: '{text[:50]}'"
                        text = None
                except Exception as parse_err:
                    print(f"  Parse err: {parse_err}")

                if not text:
                    last_err = f"Could not extract text from: {str(data)[:300]}"
                    print(f"  {last_err}")
                    continue
                print(f"  ✅ Used: {model} | text[:60]: {text[:60]}")
                self._json(200, {"text": text})
                return
            except urllib.error.HTTPError as e:
                err = e.read()
                try:
                    last_err = json.loads(err)["error"]["message"]
                except:
                    last_err = err.decode()[:200]
                print(f"  Model {model} → {e.code}: {last_err[:80]}")
                if e.code == 401:
                    self._json(401, {"error": "API key không hợp lệ. Kiểm tra lại key tại openrouter.ai/keys"})
                    return
                elif e.code == 402:
                    last_err = "Insufficient credits. Check your OpenRouter account balance."
                elif e.code == 429:
                    import time
                    time.sleep(2)
                continue
            except Exception as e:
                last_err = str(e)
                print(f"  Proxy error: {e}")
                break
        # Fallback response if all models fail
        fallback_responses = {
            "telc": "Hallo! Entschuldigung, ich habe Verbindungsprobleme. Können Sie Ihre Frage bitte wiederholen? [FEEDBACK]: Xin lỗi, AI đang có vấn đề kết nối. Hãy thử lại sau hoặc kiểm tra API key.",
            "embassy": "Guten Tag. Es tut mir leid, aber ich habe gerade technische Probleme. Könnten Sie bitte einen Moment warten? [FEEDBACK]: Lỗi kết nối AI. Thử lại sau vài giây.",
            "grammar": "Entschuldigung, ich habe gerade Probleme mit der Verbindung. Versuchen wir es nochmal? [FEEDBACK]: Lỗi AI. Hãy thử lại câu hỏi."
        }

        # Try to determine mode from system prompt to give appropriate fallback
        system_text = payload.get("system", "").lower()
        if "telc" in system_text:
            fallback_mode = "telc"
        elif "botschaft" in system_text or "visa" in system_text:
            fallback_mode = "embassy"
        elif "grammatik" in system_text:
            fallback_mode = "grammar"
        else:
            fallback_mode = "telc"  # default

        print(f"  All models failed, using fallback for {fallback_mode}")
        self._json(200, {"text": fallback_responses[fallback_mode]})

    def _handle_save_message(self):
        """Handle saving chat messages to database"""
        try:
            length = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(length))

            session_id = payload.get("session_id")
            role = payload.get("role")
            content = payload.get("content")
            mode = payload.get("mode", "unknown")

            if not all([session_id, role, content]):
                self._json(400, {"error": "Missing required fields"})
                return

            success = save_message(session_id, role, content, mode)
            if success:
                self._json(200, {"status": "saved"})
            else:
                self._json(500, {"error": "Failed to save message"})

        except Exception as e:
            print(f"Error handling save message: {e}")
            self._json(500, {"error": "Server error"})

    def _handle_get_history(self):
        """Handle getting chat history"""
        try:
            # Parse query parameters from URL
            from urllib.parse import urlparse, parse_qs
            parsed_url = urlparse(self.path)
            query_params = parse_qs(parsed_url.query)

            date_str = query_params.get("date", [None])[0]
            limit = int(query_params.get("limit", [50])[0])

            history = get_chat_history(date_str, limit)
            self._json(200, {"messages": history})

        except Exception as e:
            print(f"Error handling get history: {e}")
            self._json(500, {"error": "Server error"})

    def _handle_get_stats(self):
        """Handle getting daily statistics"""
        try:
            from urllib.parse import urlparse, parse_qs
            parsed_url = urlparse(self.path)
            query_params = parse_qs(parsed_url.query)

            days = int(query_params.get("days", [7])[0])
            stats = get_daily_stats(days)
            self._json(200, {"stats": stats})

        except Exception as e:
            print(f"Error handling get stats: {e}")
            self._json(500, {"error": "Server error"})

    def _handle_score_telc(self):
        """Handle TELC scoring request"""
        try:
            length = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(length))
            api_key = self.headers.get("X-Api-Key", "").strip()

            session_id = payload.get("session_id")
            telc_part = payload.get("telc_part")
            conversation = payload.get("conversation", "")

            print(f"🎯 TELC scoring request: Teil={telc_part}, Session={session_id}")
            print(f"💬 Conversation length: {len(conversation)} chars")

            if not all([session_id, telc_part]):
                self._json(400, {"error": "Missing required fields"})
                return

            if not conversation.strip():
                self._json(400, {"error": "Empty conversation text"})
                return

            # Analyze the conversation for TELC scoring (pass API key if available)
            score_data = analyze_telc_performance(conversation, telc_part, api_key)

            print(f"📊 Score analysis complete: {score_data.get('total_score', 0)}/{score_data.get('max_score', 30)}")

            # Save to database
            success = save_telc_score(session_id, telc_part, score_data)

            if success:
                print("✅ Score saved to database successfully")
                self._json(200, {"success": True, "scores": score_data})
            else:
                print("❌ Failed to save score to database")
                self._json(500, {"error": "Failed to save score"})

        except Exception as e:
            print(f"❌ Error handling TELC scoring: {e}")
            import traceback
            traceback.print_exc()
            self._json(500, {"error": f"Server error: {str(e)}"})

    def _handle_get_scores(self):
        """Handle getting TELC scores"""
        try:
            from urllib.parse import urlparse, parse_qs
            parsed_url = urlparse(self.path)
            query_params = parse_qs(parsed_url.query)

            session_id = query_params.get("session_id", [None])[0]
            days = int(query_params.get("days", [30])[0])

            scores = get_telc_scores(session_id, days)
            self._json(200, {"scores": scores})

        except Exception as e:
            print(f"Error handling get scores: {e}")
            self._json(500, {"error": "Server error"})

    def _json(self, code, obj, raw=None):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self._cors(); self.end_headers()
        self.wfile.write(raw if raw is not None else json.dumps(obj).encode())

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin",  "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Api-Key")
        # Basic security headers
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")

if __name__ == "__main__":
    # Get local IP address
    import socket as _s
    try:
        # Connect to external address to find local IP
        s = _s.socket(_s.AF_INET, _s.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
    except:
        local_ip = "localhost"

    ngrok_url = None
    ngrok_process = None

    print(f"\n{'='*60}")
    print(f"  🇩🇪  Deutsch B1 Trainer")
    print(f"{'='*60}")
    print(f"  🏠  Local:    http://localhost:{PORT}")

    if HOST == '127.0.0.1':
        print(f"  🔒  Mode:     LOCAL ONLY (chỉ máy này)")
    else:
        if local_ip != "localhost":
            print(f"  🌐  Network:  http://{local_ip}:{PORT}")
            print(f"  👫  LAN:      Bạn bè cùng WiFi: http://{local_ip}:{PORT}")
        print(f"  🔓  Mode:     NETWORK SHARED (chia sẻ mạng)")

    # Start ngrok if requested
    if args.ngrok:
        result = start_ngrok(PORT)
        if result:
            ngrok_url, ngrok_process = result
            print(f"  🌍  Internet: {ngrok_url}")
            print(f"  🔥  Global:   Bạn bè khắp thế giới có thể truy cập!")
        else:
            print(f"  ⚠️  Ngrok:    Failed to start internet tunnel")

    print(f"  ⏹   Stop:     Ctrl+C")
    print(f"  📚  Guide:    cat SHARING_GUIDE.md")

    if not args.ngrok:
        if local_ip == "localhost":
            print(f"  💡  Network:  python deutsch_trainer.py  (to share on WiFi)")
        print(f"  🌍  Internet: python deutsch_trainer.py --ngrok  (worldwide)")
        print(f"  🔧  Setup:    ./setup_ngrok.sh  (if ngrok missing)")
    print(f"{'='*60}\n")

    # Open browser for local user
    url_to_open = ngrok_url if ngrok_url else f"http://localhost:{PORT}"
    threading.Timer(0.8, lambda: webbrowser.open(url_to_open)).start()

    # Initialize database
    init_database()

    try:
        http.server.HTTPServer.allow_reuse_address = True
        srv = http.server.HTTPServer((HOST, PORT), Handler)
        srv.socket.setsockopt(_s.SOL_SOCKET, _s.SO_REUSEADDR, 1)

        if HOST == '127.0.0.1':
            print(f"✅ Server started on LOCAL ONLY (port {PORT})")
        else:
            print(f"✅ Server started on ALL INTERFACES (port {PORT})")
            if local_ip != "localhost":
                print(f"📱 Friends can access: http://{local_ip}:{PORT}")
                print(f"🔥 If friends can't connect, check firewall settings")
        print()
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n  🛑 Server stopped.")
        if ngrok_process:
            print("  🔌 Stopping ngrok tunnel...")
            ngrok_process.terminate()
            try:
                ngrok_process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                ngrok_process.kill()
        sys.exit(0)
    except OSError as e:
        print(f"\n❌ Error starting server: {e}")
        if "Permission denied" in str(e):
            print("💡 Try a different port: python deutsch_trainer.py --port 8080")
        elif "Address already in use" in str(e):
            print(f"💡 Port {PORT} is busy. Try: python deutsch_trainer.py --port 8888")
        if ngrok_process:
            ngrok_process.terminate()
        sys.exit(1)
