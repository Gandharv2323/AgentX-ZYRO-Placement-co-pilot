"""Adaptive mock interviews: score by rubric coverage, remember weak topics.

ponytail: keyword rubric scoring, not an LLM judge — deterministic, free, and
the demo needs a number that is reproducible. Swap `score_answer` for a model
call when answer quality matters more than repeatability.
"""
from __future__ import annotations

import json
import re
import uuid

from . import db

# topic -> list of (question_en, question_hi, keywords_en, keywords_hi)
BANK: dict[str, list[tuple[str, str, list[str], list[str]]]] = {
    "python": [
        ("Explain the difference between a list and a tuple, and when you would pick each.",
         "लिस्ट और ट्यूपल में क्या फ़र्क है, और आप किसे कब चुनेंगे?",
         ["immutable", "mutable", "hashable", "memory", "performance", "tuple"],
         ["अपरिवर्तनीय", "परिवर्तनीय", "मेमोरी", "प्रदर्शन"]),
        ("What does a Python generator do that a list does not?",
         "पायथन जनरेटर क्या करता है जो लिस्ट नहीं करती?",
         ["lazy", "yield", "memory", "iterator", "stream"],
         ["आलसी", "मेमोरी", "इटरेटर"]),
        ("How would you debug a function that returns the wrong value only in production?",
         "ऐसे फ़ंक्शन को कैसे डीबग करेंगे जो सिर्फ़ प्रोडक्शन में ग़लत मान लौटाता है?",
         ["log", "reproduce", "input", "test", "traceback", "environment"],
         ["लॉग", "दोहराना", "इनपुट", "टेस्ट"]),
        ("When would you reach for asyncio instead of threads?",
         "थ्रेड्स के बजाय asyncio कब इस्तेमाल करेंगे?",
         ["io", "concurrency", "event loop", "blocking", "gIL"],
         ["आईओ", "इवेंट लूप", "ब्लॉकिंग"]),
    ],
    "sql": [
        ("How do you find the second highest salary in a table, and why is that approach safe?",
         "सेकंड सबसे ज़्यादा सैलरी कैसे निकालेंगे, और यह तरीक़ा सुरक्षित क्यों है?",
         ["limit", "distinct", "null", "tie", "offset", "subquery", "window"],
         ["डिस्टिंक्ट", "नल", "सबक्वेरी"]),
        ("What does an index cost you, not just what does it save?",
         "इंडेक्स क्या बचाता है और क्या कीमत भी लेता है?",
         ["write", "insert", "storage", "selectivity", "update", "scan"],
         ["लिखना", "स्टोरेज", "अपडेट"]),
        ("A query got slow after a deploy. Walk me through how you would find out why.",
         "डिप्लॉय के बाद क्वेरी धीमी हो गई। आप कैसे पता लगाएँगे?",
         ["explain", "plan", "index", "scan", "rows", "profile"],
         ["प्लान", "इंडेक्स", "स्कैन"]),
        ("What is the difference between a left join and an inner join, in one sentence?",
         "लेफ्ट जॉइन और इनर जॉइन में एक वाक्य में अंतर बताइए।",
         ["unmatched", "null", "match", "preserve", "all rows"],
         ["बेमेल", "नल", "सभी पंक्तियाँ"]),
    ],
    "dbms": [
        ("Explain transaction isolation levels in terms you would use with a teammate.",
         "ट्रांज़ैक्शन आइसोलेशन लेवल को टीममेट को समझाते हुए बताइए।",
         ["dirty", "phantom", "repeatable", "serializable", "commit", "read"],
         ["गंदा", "फैंटम", "कमिट"]),
        ("What is a deadlock, and how would you prevent one in application code?",
         "डेडलॉक क्या है और ऐप कोड में उसे कैसे रोकेंगे?",
         ["lock", "order", "timeout", "retry", "transaction", "cycle"],
         ["लॉक", "क्रम", "टाइमआउट", "रीट्राई"]),
        ("Normalisation: give me one table you would deliberately NOT normalise, and why.",
         "नॉर्मलाइज़ेशन: एक टेबल बताइए जिसे जानबूझकर नॉर्मलाइज़ नहीं करेंगे, और क्यों?",
         ["read", "join", "denormalise", "performance", "report", "cache"],
         ["रीड", "जॉइन", "प्रदर्शन", "रिपोर्ट"]),
        ("What does ACID's durability actually promise you after a crash?",
         "क्रैश के बाद ACID की ड्यूरेबिलिटी वास्तव में क्या गारंटी देती है?",
         ["disk", "log", "wal", "commit", "fsync", "recover"],
         ["डिस्क", "लॉग", "कमिट"]),
    ],
    "os": [
        ("What happens, step by step, when a program calls read() on a file?",
         "जब प्रोग्राम फ़ाइल पर read() कॉल करता है तो क्रम से क्या होता है?",
         ["kernel", "syscall", "buffer", "cache", "page", "interrupt"],
         ["कर्नेल", "बफ़र", "कैश"]),
        ("Threads vs processes: what do you gain and what do you lose?",
         "थ्रेड बनाम प्रोसेस: क्या मिलता है और क्या खोता है?",
         ["memory", "isolation", "context switch", "share", "crash", "stack"],
         ["मेमोरी", "आइसोलेशन", "साझा"]),
        ("What is virtual memory solving? Describe one thing that breaks when it runs out.",
         "वर्चुअल मेमोरी कौन सी समस्या हल करती है? ख़त्म होने पर क्या टूटता है?",
         ["swap", "page fault", "address", "oom", "thrash", "physical"],
         ["स्वैप", "पेज फ़ॉल्ट", "पता"]),
    ],
    "networks": [
        ("What actually happens between typing a URL and the first byte of the response?",
         "URL टाइप करने से पहले बाइट आने तक वास्तव में क्या होता है?",
         ["dns", "tcp", "tls", "handshake", "http", "request", "cache"],
         ["डीएनएस", "हैंडशेक", "अनुरोध"]),
        ("Why does HTTP/2 multiplex requests on one connection, and what did that fix?",
         "HTTP/2 एक कनेक्शन पर अनुरोध क्यों मल्टीप्लेक्स करता है, क्या ठीक हुआ?",
         ["head of line", "stream", "multiplex", "latency", "parallel", "hOL"],
         ["लेटेंसी", "स्ट्रीम", "समानांतर"]),
        ("A user says your API is slow only on mobile data. What do you measure first?",
         "यूज़र कहता है API सिर्फ़ मोबाइल डेटा पर धीमी है। पहले क्या मापेंगे?",
         ["latency", "payload", "time to first byte", "retry", "timeout", "compression", "tTFB"],
         ["लेटेंसी", "पेलोड", "समय"]),
    ],
    "dsa": [
        ("Given a list of hundreds of thousands of numbers, how do you find the top ten fast?",
         "लाखों संख्याओं में से टॉप दस जल्दी कैसे निकालेंगे?",
         ["heap", "O(n log k)", "sort", "partition", "stream", "priority"],
         ["हीप", "सॉर्ट", "स्ट्रीम"]),
        ("When is a hash map the wrong choice?",
         "हैश मैप कब ग़लत चुनाव है?",
         ["collision", "order", "memory", "worst case", "range", "hash"],
         ["टकराव", "क्रम", "मेमोरी"]),
        ("Explain recursion to someone who only knows loops.",
         "जो सिर्फ़ लूप जानता है उसे रिकर्शन समझाइए।",
         ["base case", "stack", "call", "self", "terminate", "overhead"],
         ["आधार", "स्टैक", "कॉल"]),
    ],
    "ml": [
        ("Your model is 95% accurate and useless. What is the first thing you check?",
         "मॉडल 95% सटीक है पर बेकार है। पहले क्या जाँचेंगे?",
         ["class imbalance", "baseline", "precision", "recall", "confusion", "data leak", "auc"],
         ["असंतुलन", "बेसलाइन", "प्रिसिज़न", "रीकॉल"]),
        ("How do you know a feature is leaking label information?",
         "कैसे पता चलेगा कि फ़ीचर लेबल की जानकारी लीक कर रहा है?",
         ["too good", "time", "pipeline", "holdout", "leak", "future"],
         ["बहुत अच्छा", "समय", "लीक"]),
        ("Explain overfitting to a product manager.",
         "प्रोडक्ट मैनेजर को ओवरफ़िटिंग समझाइए।",
         ["generalise", "memorise", "variance", "validation", "new data", "noise"],
         ["सामान्य", "याद", "नया डेटा"]),
    ],
    "system_design": [
        ("Design a job board that ranks openings for students. Where does it break first?",
         "छात्रों के लिए नौकरियाँ रैंक करने वाला जॉब बोर्ड डिज़ाइन करें। सबसे पहले क्या टूटेगा?",
         ["index", "rank", "cache", "freshness", "deadline", "search", "scale"],
         ["इंडेक्स", "रैंक", "कैश", "ताज़ा"]),
        ("You must never send an email twice. What is the smallest design that guarantees it?",
         "एक ईमेल दो बार कभी नहीं जाना चाहिए। सबसे छोटा डिज़ाइन क्या होगा?",
         ["idempotency", "unique", "queue", "transaction", "retry", "dedupe", "constraint"],
         ["आइडेंपोटेंसी", "यूनिक", "ट्रांज़ैक्शन"]),
    ],
    "behavioral": [
        ("Tell me about a time you shipped something and it broke. What did you do next?",
         "ऐसा मौक़ा बताइए जब कुछ भेजा और टूट गया। आगे क्या किया?",
         ["own", "fix", "communicate", "learn", "postmortem", "rollback"],
         ["ज़िम्मेदारी", "ठीक", "सीखा"]),
        ("Describe a decision you made where the trade-off was not obvious.",
         "ऐसा निर्णय बताइए जिसमें ट्रेड-ऑफ़ स्पष्ट नहीं था।",
         ["trade", "because", "alternative", "cost", "decided", "measure"],
         ["कारण", "विकल्प", "लागत"]),
        ("A teammate disagrees with your approach in review. Walk me through what you did.",
         "रीव्यू में टीममेट आपके तरीक़े से सहमत नहीं है। क्या किया, बताइए।",
         ["listen", "evidence", "discuss", "disagree", "commit", "data"],
         ["सुना", "सबूत", "चर्चा"]),
    ],
}

TOPIC_HINTS = [
    ("sql", ["sql", "database", "postgres", "query"]),
    ("ml", ["ml", "machine learning", "data science", "ai", "model"]),
    ("python", ["python", "backend", "api", "fastapi"]),
    ("dbms", ["dbms", "transaction", "storage"]),
    ("system_design", ["design", "architect", "scal"]),
]


def _question(language: str, topic: str, q: tuple) -> tuple[str, dict]:
    text = q[1] if language == "hi" else q[0]
    rubric = [{"point": k, "weight": 1} for k in (q[3] if language == "hi" else q[2])]
    return text, {"keyword_groups": rubric}


def create_interview(conn, student_id: str, role: str, language: str, limit: int = 6) -> dict:
    weak = [dict(r) for r in conn.execute(
        "SELECT * FROM topics WHERE student_id=? AND avg_score < 3.0 ORDER BY avg_score ASC, last_seen ASC",
        (student_id,))]
    asked = {r["topic"] for r in conn.execute(
        "SELECT q.topic FROM answers a JOIN questions q ON q.id=a.question_id "
        "JOIN interviews i ON i.id=q.interview_id WHERE i.student_id=?", (student_id,))}

    wanted: list[tuple[str, str, str | None]] = []
    for t in weak[:3]:
        if t["topic"] in BANK:
            wanted.append((t["topic"], "reopened", f"Reopened: {t['topic'].upper()} scored {t['avg_score']:.1f}/5 "
                                                    f"in your last session ({t['attempts']} attempt(s))"))
    role_l = (role or "").lower()
    for topic, hints in TOPIC_HINTS:
        if topic in BANK and any(h in role_l for h in hints) and topic not in [w[0] for w in wanted]:
            wanted.append((topic, "role", f"From the role: {role}"))
    if len(wanted) < limit:
        for topic in BANK:
            if topic not in [w[0] for w in wanted] and topic in asked:
                continue
            if topic not in [w[0] for w in wanted]:
                wanted.append((topic, "coverage", "Broad coverage"))
            if len(wanted) >= limit:
                break
    if len(wanted) < limit:
        for topic in BANK:
            if topic not in [w[0] for w in wanted]:
                wanted.append((topic, "coverage", "Broad coverage"))
            if len(wanted) >= limit:
                break

    interview_id = f"int_{uuid.uuid4().hex[:10]}"
    conn.execute("INSERT INTO interviews(id,student_id,role,language,status,created_at) VALUES(?,?,?,?,'active',?)",
                 (interview_id, student_id, role, language, db.iso()))
    questions = []
    for idx, (topic, kind, prov) in enumerate(wanted[:limit]):
        # pick the bank item least recently asked for this topic when possible
        items = BANK[topic]
        q = items[idx % len(items)]
        text, rubric = _question(language, topic, q)
        qid = f"q_{uuid.uuid4().hex[:10]}"
        conn.execute(
            "INSERT INTO questions(id,interview_id,idx,topic,text_en,text_hi,rubric_json,provenance,reason) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (qid, interview_id, idx, topic, q[0], q[1], json.dumps(rubric), prov, kind))
        questions.append({"id": qid, "idx": idx, "topic": topic, "text": text, "provenance": prov})
    conn.commit()
    return {"interview_id": interview_id, "questions": questions}


def score_answer(conn, question_id: str, text: str) -> dict:
    q = conn.execute("SELECT * FROM questions WHERE id=?", (question_id,)).fetchone()
    if not q:
        return {}
    rubric = json.loads(q["rubric_json"] or "{}").get("keyword_groups", [])
    low = (text or "").lower()
    matched, missing = [], []
    for group in rubric:
        if group["point"].lower() in low:
            matched.append(group["point"])
        else:
            missing.append(group["point"])
    coverage = len(matched) / max(len(rubric), 1)
    raw = coverage
    if len(low.strip()) < 30:
        raw -= 0.15
    if re.search(r"\bbecause\b|\btrade.?off\b|\bso that\b|\bक्योंकि\b", low):
        raw += 0.1
    score = round(max(0.5, min(5.0, 0.5 + 4.5 * max(raw, 0.0))), 1)
    feedback = {
        "score": score,
        "strong": (f"Covered {', '.join(matched[:3])}" if matched else "No rubric points hit yet"),
        "missing": missing[:4],
        "note": "Score is rubric coverage, not fluency." if text.strip() else "No evidence yet.",
    }
    conn.execute(
        "INSERT INTO answers(id,question_id,text,score,matched_json,feedback_json,created_at) "
        "VALUES(?,?,?,?,?,?,?) ON CONFLICT(question_id) DO UPDATE SET text=excluded.text, score=excluded.score, "
        "matched_json=excluded.matched_json, feedback_json=excluded.feedback_json",
        (f"ans_{uuid.uuid4().hex[:10]}", question_id, text, score, json.dumps(matched),
         json.dumps(feedback), db.iso()))
    conn.commit()
    return feedback


def complete_interview(conn, student_id: str, interview_id: str) -> dict:
    rows = [dict(r) for r in conn.execute(
        "SELECT q.topic, a.score FROM questions q LEFT JOIN answers a ON a.question_id=q.id "
        "WHERE q.interview_id=?", (interview_id,))]
    per_topic: dict[str, list[float]] = {}
    for r in rows:
        per_topic.setdefault(r["topic"], []).append(r["score"] or 0.5)
    scorecard = []
    for topic, scores in per_topic.items():
        avg = round(sum(scores) / len(scores), 1)
        prev = conn.execute("SELECT * FROM topics WHERE student_id=? AND topic=?", (student_id, topic)).fetchone()
        attempts = (prev["attempts"] if prev else 0) + 1
        conn.execute(
            "INSERT INTO topics(student_id,topic,attempts,avg_score,best_score,last_score,last_seen) "
            "VALUES(?,?,?,?,?,?,?) ON CONFLICT(student_id,topic) DO UPDATE SET attempts=excluded.attempts, "
            "avg_score=excluded.avg_score, best_score=MAX(topics.best_score, excluded.best_score), "
            "last_score=excluded.last_score, last_seen=excluded.last_seen",
            (student_id, topic, attempts, avg, max(scores), avg, db.iso()))
        scorecard.append({"topic": topic, "score": avg, "previous": prev["avg_score"] if prev else None,
                          "delta": round(avg - prev["avg_score"], 1) if prev else None})
    overall = round(sum(c["score"] for c in scorecard) / max(len(scorecard), 1), 1)
    conn.execute("UPDATE interviews SET status='completed', overall=?, completed_at=? WHERE id=?",
                 (overall, db.iso(), interview_id))
    weak = sorted([c for c in scorecard if c["score"] < 3.0], key=lambda c: c["score"])[:2]
    for w in weak:
        conn.execute("INSERT INTO memories(student_id,kind,text,created_at) VALUES(?,?,?,?)",
                     (student_id, "weak_topic",
                      f"{w['topic']} scored {w['score']}/5 — reopen it next session", db.iso()))
    conn.commit()
    return {"scorecard": sorted(scorecard, key=lambda c: c["score"]), "overall": overall,
            "weak": [w["topic"] for w in weak]}
