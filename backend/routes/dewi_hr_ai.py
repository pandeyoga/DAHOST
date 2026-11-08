"""
Session 15 — P2-8, P2-9, P2-10: HR AI Features

P2-8: AI Resume Screening
- POST /api/hr/ai/resume-screen/{candidate_id}  — AI screens candidate resume
- GET  /api/hr/ai/resume-screen/history          — History of screenings
- POST /api/hr/ai/resume-screen/{candidate_id}/suggestion — Terima/Ubah/Tolak usulan skor AI (K28)

P2-9: Predictive Attrition
- POST /api/hr/ai/attrition/predict              — Predict attrition risk
- GET  /api/hr/ai/attrition/dashboard            — Attrition risk dashboard

P2-10: Performance Coaching AI
- POST /api/hr/ai/coaching/{employee_id}         — Generate coaching plan
- GET  /api/hr/ai/coaching/history               — Coaching history
"""
import uuid
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, List
from fastapi import APIRouter, Request, Query, HTTPException
from pydantic import BaseModel, Field
from database import get_db
from auth import require_auth
from services.ai import (
    AIError, Pseudonymizer, SuggestionDecision, ai_http_error, ai_json, ai_text, clamp_number,
    decide_suggestion, new_suggestion, pick_enum, require_ai, with_untrusted_rule, wrap_untrusted,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/hr/ai", tags=["hr-ai"])

# 2026-11-02 (No.60): tier, bukan tuple ("openai","gpt-5.1"); kunci dikelola services.ai.
# 2026-11-02 (K29): Opus hanya untuk Laporan Eksekutif → AI SDM memakai standard (Sonnet).
LLM_TIER = "standard"

# K27 (2026-11-02): nama karyawan/pelamar → kode samaran (KRY-xxx / PLM-xxx), gaji TIDAK
# PERNAH dikirim; jawaban AI dipetakan balik ke nama asli di server.
# K28: skor kandidat = USULAN (`ai_suggestion`), bukan nilai resmi; output divalidasi enum.
RECOMMENDATIONS = ("Strongly Recommended", "Recommended", "Consider", "Not Recommended")
RISK_LEVELS = ("high", "medium", "low")
CULTURE_FIT = ("high", "medium", "low")
SKILL_MATCH = ("yes", "partial", "no")


def _score_0_100(v):
    n = clamp_number(v, 0, 100)
    if n is None:
        raise ValueError("harus angka 0–100")
    return int(round(n))


CANDIDATE_SUGGESTION_RULES = {"ai_score": _score_0_100, "ai_recommendation": RECOMMENDATIONS}


def _now():
    return datetime.now(timezone.utc)

def ok(data=None, meta=None):
    r = {"success": True}
    if data is not None:
        r["data"] = data
    if meta is not None:
        r["metadata"] = meta
    return r

def serialize(o):
    if isinstance(o, list):
        return [serialize(i) for i in o]
    if isinstance(o, dict):
        return {k: serialize(v) for k, v in o.items() if k != "_id"}
    if isinstance(o, datetime):
        return o.isoformat()
    return o

async def _call_ai(system_msg: str, user_msg: str, tag: str, user_id: Optional[str] = None) -> str:
    # 2026-11-02: gerbang & galat ramah dari services.ai (dulu 500 "EMERGENT_LLM_KEY ...").
    feature = f"hr-ai-{tag}"
    await require_ai(feature, user_id=user_id, tier=LLM_TIER)
    try:
        return await ai_text(feature, system_msg, user_msg, tier=LLM_TIER, user_id=user_id)
    except AIError as e:
        raise ai_http_error(e)

def _parse_json_response(text: str) -> dict:
    try:
        start = text.find("{")
        end   = text.rfind("}") + 1
        if start >= 0 and end > start:
            return json.loads(text[start:end])
    except Exception:
        logging.getLogger(__name__).debug("suppressed exception", exc_info=True)
    return {"raw_response": text}


# ═══════════════════════════════════════════════════════════════════════
#  P2-8: AI RESUME SCREENING
# ═══════════════════════════════════════════════════════════════════════

class ResumeScreenRequest(BaseModel):
    job_requirements: Optional[str] = Field(default="", description="Deskripsi persyaratan posisi")
    focus_areas: Optional[List[str]] = Field(default_factory=list, description="Area yang ingin difokuskan: skills, experience, education")


@router.post("/resume-screen/{candidate_id}")
async def screen_resume(
    candidate_id: str,
    payload: ResumeScreenRequest,
    request: Request,
):
    """
    P2-8: AI Resume Screening.
    Analisis profil kandidat vs. persyaratan posisi, berikan skor dan rekomendasi.
    """
    user = await require_auth(request)
    db = get_db()

    # Get candidate data
    candidate = await db.dewi_recruitment_candidates.find_one(
        {"candidate_id": candidate_id}, {"_id": 0}
    )
    if not candidate:
        raise HTTPException(404, "Kandidat tidak ditemukan")

    # Get job info
    job = None
    if candidate.get("job_id"):
        job = await db.dewi_recruitment_jobs.find_one(
            {"job_id": candidate["job_id"]}, {"_id": 0}
        )

    # K27: nama pelamar → PLM-xxx; CV (teks pihak luar) disamarkan (nama, HP, email) dan
    # dibungkus pembatas (K28). Email/telepon/alamat kandidat tidak pernah ikut.
    ps = Pseudonymizer()
    ref = ps.code(candidate.get("name"), "pelamar", parts=True) or "PLM-000"
    candidate_profile = {
        "ref": ref,
        "position_applied": candidate.get("position_applied"),
        "experience_years": candidate.get("experience_years"),
        "education": candidate.get("education"),
        "skills": candidate.get("skills", []),
        "current_stage": candidate.get("stage", ""),
        "source": candidate.get("source", ""),
    }
    cv_block = wrap_untrusted(ps.scrub(candidate.get("cv_text", "")), "cv")

    job_info = {}
    if job:
        job_info = {
            "title": job.get("title"),
            "department": job.get("department"),
            "requirements": job.get("requirements", []),
            "description": job.get("description", ""),
        }

    system_prompt = with_untrusted_rule("""Kamu adalah AI HR Recruiter untuk CV. Dewi Aditya.
Analisis profil kandidat dan berikan penilaian objektif untuk posisi yang dilamar.
Kandidat disebut dengan kode samaran (mis. PLM-001); pakai kode itu, jangan menebak nama.
Format JSON response:
{
  "overall_score": 85,
  "recommendation": "Strongly Recommended / Recommended / Consider / Not Recommended",
  "strengths": ["strength 1", "strength 2", "strength 3"],
  "weaknesses": ["weakness 1", "weakness 2"],
  "skill_match": [{"skill": "", "match": "yes/partial/no", "notes": ""}],
  "experience_assessment": "penilaian pengalaman",
  "education_assessment": "penilaian pendidikan",
  "culture_fit": "high/medium/low",
  "interview_questions": ["pertanyaan 1 untuk interview", "pertanyaan 2"],
  "summary": "ringkasan penilaian keseluruhan"
}""")

    user_prompt = f"""Profil Kandidat:\n{ai_json(candidate_profile)}

Teks CV kandidat:
{cv_block}

Info Posisi:\n{ai_json(job_info)}

Persyaratan Tambahan: {ps.scrub(payload.job_requirements) or 'Tidak ada'}
Fokus Area: {', '.join(payload.focus_areas) if payload.focus_areas else 'Semua area'}"""

    raw = await _call_ai(system_prompt, user_prompt, "resume-screen", user.get("id"))
    analysis = _validate_screening(ps.restore(_parse_json_response(raw)))

    # Save to DB
    doc = {
        "id": str(uuid.uuid4()),
        "type": "resume_screening",
        "candidate_id": candidate_id,
        "candidate_name": candidate.get("name"),
        "position": candidate.get("position_applied"),
        "analysis": analysis,
        "generated_at": _now().isoformat(),
    }
    await db.hr_ai_results.insert_one(doc)

    # K28 (2026-11-02): skor AI = USULAN. `ai_score`/`ai_recommendation` resmi baru
    # berubah saat HR menekan Terima/Ubah (endpoint .../suggestion), aktor dicatat saat itu.
    suggestion = None
    if analysis.get("overall_score") is not None:
        suggestion = new_suggestion(
            {"ai_score": analysis["overall_score"], "ai_recommendation": analysis.get("recommendation")},
            feature="hr-ai-resume-screen", user=user, reason=analysis.get("summary", ""),
            extra={"screening_id": doc["id"]})
        await db.dewi_recruitment_candidates.update_one(
            {"candidate_id": candidate_id}, {"$set": {"ai_suggestion": suggestion}})

    shown = {k: v for k, v in candidate_profile.items() if k != "ref"}
    shown["name"] = candidate.get("name")
    return ok(data={"analysis": analysis, "candidate": serialize(shown), "ai_suggestion": suggestion,
                    "generated_at": doc["generated_at"]})


def _validate_screening(analysis: dict) -> dict:
    """K28: skor 0–100 & enum yang sah; nilai di luar itu dikosongkan (bukan dikarang)."""
    a = dict(analysis or {})
    if "raw_response" in a:
        return a
    score = clamp_number(a.get("overall_score"), 0, 100)
    a["overall_score"] = None if score is None else int(round(score))
    a["recommendation"] = pick_enum(a.get("recommendation"), RECOMMENDATIONS)
    a["culture_fit"] = pick_enum(a.get("culture_fit"), CULTURE_FIT)
    a["skill_match"] = [
        {**sm, "match": pick_enum(sm.get("match"), SKILL_MATCH, "no")}
        for sm in (a.get("skill_match") or []) if isinstance(sm, dict)
    ]
    return a


@router.post("/resume-screen/{candidate_id}/suggestion")
async def decide_screening_suggestion(candidate_id: str, payload: SuggestionDecision, request: Request):
    """K28: HR menerima / mengubah / menolak usulan skor AI kandidat (aktor dicatat di sini)."""
    user = await require_auth(request)
    db = get_db()
    cand = await db.dewi_recruitment_candidates.find_one({"candidate_id": candidate_id}, {"_id": 0})
    if not cand:
        raise HTTPException(404, "Kandidat tidak ditemukan")
    official, decided = decide_suggestion(cand.get("ai_suggestion"), payload, user=user,
                                          rules=CANDIDATE_SUGGESTION_RULES, current=cand)
    patch = {"ai_suggestion": decided, "updated_at": _now()}
    if official:
        patch.update(official)
        patch["ai_score_decided_by"] = decided["decided_by"]
        patch["ai_score_decided_at"] = decided["decided_at"]
    await db.dewi_recruitment_candidates.update_one({"candidate_id": candidate_id}, {"$set": patch})
    return ok(data={"candidate_id": candidate_id, "ai_suggestion": decided, "applied": official})


@router.get("/resume-screen/history")
async def get_screening_history(request: Request, limit: int = Query(20, ge=1, le=200)):
    await require_auth(request)
    db = get_db()
    docs = await db.hr_ai_results.find({"type": "resume_screening"}, {"_id": 0}).sort("generated_at", -1).limit(limit).to_list(limit)
    return ok(data=serialize(docs))


# ═══════════════════════════════════════════════════════════════════════
#  P2-9: PREDICTIVE ATTRITION
# ═══════════════════════════════════════════════════════════════════════

@router.post("/attrition/predict")
async def predict_attrition(
    request: Request,
    department: Optional[str] = Query(None, description="Filter by department"),
):
    """
    P2-9: Predictive Attrition.
    Analisis faktor risiko resign untuk semua karyawan aktif.
    """
    user = await require_auth(request)
    db = get_db()

    # 2026-11-02: karyawan aktif = `active: True` (field employment_status tidak ada → dulu 0).
    query = {"active": True}
    if department:
        query["department"] = department

    employees = await db.rahaza_employees.find(query, {"_id": 0}).to_list(200)
    if not employees:
        return ok(data=[], meta={"total": 0})

    # For each employee, gather attrition indicators
    # K27 (2026-11-02): ke AI hanya kode samaran KRY-xxx + indikator; nama, id, dan GAJI
    # (base_rate) tidak dikirim dan tidak dikembalikan (`raw_employee_data` dihapus).
    ps = Pseudonymizer()
    emp_data = []
    ref_map = {}
    for emp in employees:
        emp_id = emp.get("id") or emp.get("employee_code")

        # Count absence days (last 90 days) — RC-01/K6: SSOT events; status nyata
        # hanya hadir/izin/sakit → "absence" = izin+sakit
        since90 = _now() - timedelta(days=90)
        absence_count = await db.rahaza_attendance_events.count_documents({
            "employee_id": emp_id,
            "status": {"$in": ["izin", "sakit"]},
            "date": {"$gte": since90.strftime("%Y-%m-%d")}
        })

        # Count late arrivals — K1: is_late tak tersedia di data (shift_id kosong);
        # hitung hanya bila field is_late True (jujur 0 bila tak ada, JANGAN mengarang)
        late_count = await db.rahaza_attendance_events.count_documents({
            "employee_id": emp_id,
            "is_late": True,
            "date": {"$gte": since90.strftime("%Y-%m-%d")}
        })

        # Get leave requests (last 6 months)
        since180 = _now() - timedelta(days=180)
        # 2026-11-09 (audit HR P6): dulu `created_at` (tersimpan sebagai datetime) dibandingkan dengan TEKS ISO →
        # Mongo tidak pernah mencocokkan beda tipe, hitungan selalu 0. Kini memakai `from_date` (teks YYYY-MM-DD,
        # tipe sama) dan hanya pengajuan yang tidak ditolak/dibatalkan.
        leave_count = await db.rahaza_leave_requests.count_documents({
            "employee_id": emp_id,
            "from_date": {"$gte": since180.strftime("%Y-%m-%d")},
            "status": {"$nin": ["rejected", "cancelled", "draft"]},
        })

        # Years of service
        join_date = emp.get("join_date", "")
        years_service = 0
        if join_date:
            try:
                jd = datetime.strptime(str(join_date)[:10], "%Y-%m-%d")
                years_service = round((_now() - jd.replace(tzinfo=timezone.utc)).days / 365, 1)
            except Exception:
                logging.getLogger(__name__).debug("suppressed exception", exc_info=True)

        ref = ps.code(emp.get("name") or emp_id, "karyawan")
        ref_map[ref] = {"employee_id": emp_id, "name": emp.get("name"), "department": emp.get("department")}
        emp_data.append({
            "ref": ref,
            "department": emp.get("department"),
            "job_title": emp.get("job_title"),
            "grade": emp.get("grade"),
            "years_service": years_service,
            "absence_90d": absence_count,
            "late_90d": late_count,
            "leave_requests_6m": leave_count,
        })

    system_prompt = """Kamu adalah AI People Analytics specialist untuk CV. Dewi Aditya.
Analisis data karyawan dan prediksi risiko attrition (resign) untuk setiap karyawan.
Karyawan disebut dengan kode samaran `ref` (mis. KRY-001); pakai kode itu apa adanya.
Format JSON response:
{
  "employees": [
    {
      "ref": "KRY-001",
      "risk_level": "high/medium/low",
      "risk_score": 75,
      "risk_factors": ["faktor 1", "faktor 2"],
      "retention_suggestions": ["saran 1", "saran 2"]
    }
  ],
  "department_summary": [{"department": "", "avg_risk": 0.0, "high_risk_count": 0}],
  "overall_insights": "narasi insight keseluruhan",
  "priority_actions": ["aksi prioritas 1", "aksi prioritas 2"]
}"""

    # 2026-11-09 (audit HR P6): dulu hanya 10 karyawan pertama yang dikirim (`emp_data[:10]`) walau dasbor
    # menyebut "semua karyawan aktif". Kini semua karyawan dianalisis, per kelompok `ATTRITION_BATCH` orang
    # (satu panggilan AI per kelompok), lalu hasilnya digabung.
    analysis = await _attrition_batches(system_prompt, emp_data, ps, ref_map, user.get("id"))

    # Save to DB
    doc = {
        "id": str(uuid.uuid4()),
        "type": "attrition_prediction",
        "department": department,
        "employee_count": len(emp_data),
        "analysis": analysis,
        "generated_at": _now().isoformat(),
    }
    await db.hr_ai_results.insert_one(doc)

    # K27: `raw_employee_data` (berisi base_salary) DIHAPUS dari respons.
    return ok(data={"analysis": analysis, "generated_at": doc["generated_at"]})


ATTRITION_BATCH = 40


def batches(rows: list, size: int = ATTRITION_BATCH) -> list:
    """Bagi daftar menjadi kelompok berukuran `size` (kelompok terakhir boleh lebih kecil)."""
    size = max(1, int(size or ATTRITION_BATCH))
    return [rows[i:i + size] for i in range(0, len(rows), size)]


async def _attrition_batches(system_prompt: str, emp_data: list, ps: Pseudonymizer, ref_map: dict,
                             user_id) -> dict:
    """Analisis semua karyawan per kelompok; gabungkan `employees`, ringkasan departemen, dan aksi prioritas."""
    gabung: dict = {"employees": [], "department_summary": [], "overall_insights": "", "priority_actions": []}
    kelompok = batches(emp_data)
    insights = []
    for i, rows in enumerate(kelompok, 1):
        catatan = f" (kelompok {i} dari {len(kelompok)})" if len(kelompok) > 1 else ""
        raw = await _call_ai(system_prompt, f"Data karyawan aktif{catatan}:\n{ai_json(rows)}", "attrition", user_id)
        part = _restore_attrition(_parse_json_response(raw), ps, ref_map)
        gabung["employees"] += [e for e in part.get("employees") or [] if isinstance(e, dict)]
        gabung["department_summary"] += [d for d in part.get("department_summary") or [] if isinstance(d, dict)]
        for a in part.get("priority_actions") or []:
            if a not in gabung["priority_actions"]:
                gabung["priority_actions"].append(a)
        if part.get("overall_insights"):
            insights.append(str(part["overall_insights"]))
    gabung["overall_insights"] = "\n\n".join(insights)
    return gabung


def _restore_attrition(analysis: dict, ps: Pseudonymizer, ref_map: dict) -> dict:
    """Petakan balik KRY-xxx → id/nama/departemen asli (di server) + validasi enum risiko."""
    a = ps.restore(dict(analysis or {}))
    if not isinstance((analysis or {}).get("employees"), list):
        return a
    emps = []
    for e in analysis["employees"]:
        if not isinstance(e, dict):
            continue
        ref = str(e.get("ref") or e.get("employee_id") or "")
        real = ref_map.get(ps.canonical(ref) or ref) or {}
        row = ps.restore({k: v for k, v in e.items() if k not in ("ref", "name", "employee_id", "department")})
        row.update({
            "employee_id": real.get("employee_id"),
            "name": real.get("name") or ps.real_name(ref),
            "department": real.get("department"),
            "risk_level": pick_enum(e.get("risk_level"), RISK_LEVELS),
            "risk_score": clamp_number(e.get("risk_score"), 0, 100),
        })
        emps.append(row)
    a["employees"] = emps
    return a


@router.get("/attrition/dashboard")
async def get_attrition_dashboard(request: Request, limit: int = Query(5, ge=1, le=200)):
    """Get latest attrition predictions."""
    await require_auth(request)
    db = get_db()
    docs = await db.hr_ai_results.find({"type": "attrition_prediction"}, {"_id": 0}).sort("generated_at", -1).limit(limit).to_list(limit)
    return ok(data=serialize(docs))


# ═══════════════════════════════════════════════════════════════════════
#  P2-10: PERFORMANCE COACHING AI
# ═══════════════════════════════════════════════════════════════════════

class CoachingRequest(BaseModel):
    focus: Optional[str] = Field(default="overall", description="Fokus coaching: performance, leadership, technical, communication, time_management")
    goals: Optional[str] = Field(default="", description="Tujuan spesifik yang ingin dicapai")


@router.post("/coaching/{employee_id}")
async def generate_coaching_plan(
    employee_id: str,
    payload: CoachingRequest,
    request: Request,
):
    """
    P2-10: AI Performance Coaching Plan.
    Generate personalized coaching plan berdasarkan data kinerja karyawan.
    """
    user = await require_auth(request)
    db = get_db()

    # Get employee
    employee = await db.rahaza_employees.find_one(
        {"$or": [{"id": employee_id}, {"employee_code": employee_id}]}, {"_id": 0, "password": 0}
    )
    if not employee:
        raise HTTPException(404, "Karyawan tidak ditemukan")

    emp_id = employee.get("id") or employee.get("employee_code")

    # Get latest performance review — T-17 (FASE 3): SSOT dewi_perf_reviews (hris_reviews tak pernah ditulis)
    latest_review = await db.dewi_perf_reviews.find_one(
        {"employee_id": emp_id}, {"_id": 0}, sort=[("created_at", -1)]
    )

    # Get attendance summary (last 3 months) — RC-01/K6: SSOT events; status nyata hadir/izin/sakit
    since90 = _now() - timedelta(days=90)
    att_total = await db.rahaza_attendance_events.count_documents({"employee_id": emp_id, "date": {"$gte": since90.strftime("%Y-%m-%d")}})
    att_late  = await db.rahaza_attendance_events.count_documents({"employee_id": emp_id, "is_late": True, "date": {"$gte": since90.strftime("%Y-%m-%d")}})
    att_absent= await db.rahaza_attendance_events.count_documents({"employee_id": emp_id, "status": {"$in": ["izin", "sakit"]}, "date": {"$gte": since90.strftime("%Y-%m-%d")}})

    # Get completed training — T-17 (FASE 3): SSOT dewi_lms_enrollments (hris_training_completions tak pernah ditulis)
    trainings = [
        {"training_name": e.get("course_title"), "score": e.get("quiz_score"), "completed_at": e.get("completed_at")}
        for e in await db.dewi_lms_enrollments.find(
            {"employee_id": emp_id, "status": "completed"},
            {"_id": 0, "course_title": 1, "quiz_score": 1, "completed_at": 1}
        ).sort("completed_at", -1).limit(5).to_list(5)
    ]

    # K27 (2026-11-02): nama → KRY-xxx (dipetakan balik di server); gaji tidak ikut.
    ps = Pseudonymizer()
    profile = {
        "ref": ps.code(employee.get("name") or emp_id, "karyawan", parts=True),
        "job_title": employee.get("job_title"),
        "department": employee.get("department"),
        "grade": employee.get("grade"),
        "years_service": 0,
        "performance_scores": {
            "latest_score": latest_review.get("final_score") if latest_review else None,
            "criteria_scores": latest_review.get("criteria_scores", {}) if latest_review else {},
        } if latest_review else None,
        "attendance": {"total_days_90d": att_total, "late_days": att_late, "absent_days": att_absent},
        "completed_trainings": len(trainings),
        "focus_area": payload.focus,
        "goals": ps.scrub(payload.goals or ""),
    }

    # Years of service
    join_date = employee.get("join_date", "")
    if join_date:
        try:
            jd = datetime.strptime(str(join_date)[:10], "%Y-%m-%d")
            profile["years_service"] = round((_now() - jd.replace(tzinfo=timezone.utc)).days / 365, 1)
        except Exception:
            logging.getLogger(__name__).debug("suppressed exception", exc_info=True)

    system_prompt = """Kamu adalah AI Performance Coach untuk CV. Dewi Aditya.
Buat rencana coaching personal yang spesifik, actionable, dan realistis untuk karyawan.
Karyawan disebut dengan kode samaran `ref` (mis. KRY-001); pakai kode itu, jangan menebak nama.
Format JSON:
{
  "coaching_title": "Judul program coaching",
  "employee_summary": "ringkasan profil dan situasi karyawan",
  "key_development_areas": ["area 1", "area 2", "area 3"],
  "smart_goals": [
    {"goal": "", "timeline": "30/60/90 hari", "measurement": "cara mengukur"}
  ],
  "weekly_actions": ["aksi minggu 1", "aksi minggu 2", "aksi minggu 3", "aksi minggu 4"],
  "recommended_trainings": ["training 1", "training 2"],
  "manager_support": "apa yang perlu dilakukan manager",
  "milestones": [{"month": 1, "target": ""}, {"month": 2, "target": ""}, {"month": 3, "target": ""}],
  "motivational_message": "pesan motivasi personal"
}"""

    user_prompt = f"Profil karyawan:\n{ai_json(profile)}"

    raw = await _call_ai(system_prompt, user_prompt, "coaching", user.get("id"))
    plan = ps.restore(_parse_json_response(raw))

    # Save to DB
    doc = {
        "id": str(uuid.uuid4()),
        "type": "coaching_plan",
        "employee_id": emp_id,
        "employee_name": employee.get("name"),
        "focus": payload.focus,
        "plan": plan,
        "generated_at": _now().isoformat(),
    }
    await db.hr_ai_results.insert_one(doc)

    return ok(data={"plan": plan, "employee": {
        "name": employee.get("name"),
        "job_title": employee.get("job_title"),
        "department": employee.get("department"),
    }, "generated_at": doc["generated_at"]})


@router.get("/coaching/history")
async def get_coaching_history(request: Request, employee_id: Optional[str] = None, limit: int = Query(20, ge=1, le=200)):
    await require_auth(request)
    db = get_db()
    query = {"type": "coaching_plan"}
    if employee_id:
        query["employee_id"] = employee_id
    docs = await db.hr_ai_results.find(query, {"_id": 0}).sort("generated_at", -1).limit(limit).to_list(limit)
    return ok(data=serialize(docs))


# ═══════════════════════════════════════════════════════════════════════
#  HELPER: List employees (for dropdowns)
# ═══════════════════════════════════════════════════════════════════════

@router.get("/employees/list")
async def list_employees_for_ai(request: Request):
    """List active employees for dropdown selectors in AI modules."""
    await require_auth(request)
    db = get_db()
    emps = await db.rahaza_employees.find(
        {"active": True},  # 2026-11-02: dulu employment_status (tidak ada di data) → daftar kosong
        {"_id": 0, "id": 1, "employee_code": 1, "name": 1, "department": 1, "job_title": 1, "grade": 1}
    ).sort("name", 1).to_list(200)
    return ok(data=serialize(emps))
