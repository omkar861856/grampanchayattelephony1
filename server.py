import os
import re
import json
import uuid
import datetime
import hashlib
from pathlib import Path
from typing import List, Dict, Any, Optional
from fastapi import FastAPI, Form, HTTPException, Query, BackgroundTasks
from fastapi.responses import Response, FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import requests
import mimetypes
from dotenv import load_dotenv

# Ensure proper MIME types for static files in Linux environments
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("image/svg+xml", ".svg")
mimetypes.add_type("audio/x-wav", ".wav")

# Load Environment Variables
load_dotenv(override=True)

# App Definition
app = FastAPI(
    title="Gram Panchayat Telephony (GPT) Dashboard",
    description="Live voice telephony campaign manager for Gram Panchayat administration",
    version="1.0.0"
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Constants & Paths
DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)

VILLAGERS_FILE = DATA_DIR / "villagers.json"
CALLS_FILE = DATA_DIR / "calls.json"
PROMPTS_FILE = DATA_DIR / "prompts.json"

# XML Response Helper
class XMLResponse(Response):
    media_type = "application/xml"

def make_response_xml(elements: str) -> XMLResponse:
    xml_content = f'<?xml version="1.0" encoding="UTF-8"?>\n<Response>\n{elements}\n</Response>'
    return XMLResponse(content=xml_content)

# File DB Helpers
def load_json(path: Path, default: Any = []) -> Any:
    if not path.exists():
        save_json(path, default)
        return default
    with open(path, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except Exception as e:
            print(f"Error loading {path}: {e}")
            return default

def save_json(path: Path, data: Any):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

# Initialize files
load_json(VILLAGERS_FILE, [
    {"id": "v_1", "name": "Ram Singh", "phone": "+919876543210", "village_ward": "Rajpur Village - Ward 1", "status": "Active"},
    {"id": "v_2", "name": "Sita Devi", "phone": "+919876543211", "village_ward": "Rajpur Village - Ward 2", "status": "Active"},
    {"id": "v_3", "name": "Abdul Khan", "phone": "+919876543212", "village_ward": "Sarang Village - Ward 1", "status": "Active"},
    {"id": "v_4", "name": "Geeta Patel", "phone": "+919876543213", "village_ward": "Sarang Village - Ward 3", "status": "Active"},
])
load_json(CALLS_FILE, [])

# Default Prompts Initializer
load_json(PROMPTS_FILE, [
    {"id": "survey_intro", "name": "Survey Introduction", "text": "Hello! This is an automated survey call from your Gram Panchayat. Please take a few seconds to provide feedback on our local services."},
    {"id": "survey_q1", "name": "Survey Question 1 (Rating)", "text": "Rate water supply cleanliness and frequency: press 1 for poor, up to 5 for excellent."},
    {"id": "survey_q2", "name": "Survey Question 2 (Recommend)", "text": "Would you recommend the new road repair scheme? Press 1 for Yes, 2 for No."},
    {"id": "survey_q3", "name": "Survey Question 3 (Experience)", "text": "Overall experience with the Panchayat office: Press 1 for Good, 2 for Neutral, 3 for Poor."},
    {"id": "survey_outro", "name": "Survey Outro / Thank You", "text": "Thank you for completing the Gram Panchayat feedback survey. Goodbye!"},
    {"id": "summon_intro", "name": "Summoning Invitation Template", "text": "Hello. This is a summoning reminder from your Gram Panchayat. You are requested to attend a meeting at the Panchayat office on {date} at {time} for {purpose}. Please press 1 to confirm your visit, press 2 to request a reschedule, press 3 to cancel this visit, or press 9 to repeat these details."},
    {"id": "summon_confirm", "name": "Summoning Confirmed Text", "text": "Your summoning confirmation is successfully registered. Thank you. See you soon."},
    {"id": "summon_reschedule", "name": "Summoning Reschedule Text", "text": "Reschedule request received. Please visit or contact the Panchayat Secretary directly. Goodbye."},
    {"id": "summon_cancel", "name": "Summoning Cancel Text", "text": "Your summoning request is cancelled. Goodbye."},
    {"id": "summon_cancel_confirm", "name": "Summoning Cancel Confirmation Ask", "text": "Are you sure you want to cancel this visit request? Press 1 to confirm cancellation, or 2 to go back."},
    {"id": "inbound_main", "name": "Inbound Main IVR Menu", "text": "Welcome to the Gram Panchayat Telephony services. Press 1 for Agricultural schemes and support. Press 2 for complaints and grievances registration. Press 3 for Panchayat taxes and birth or death certificates. Press 0 to connect to the Sarpanch. Press 9 to repeat this menu."},
    {"id": "complaint_record_intro", "name": "Inbound Complaint Recording Intro", "text": "Please record your complaint or grievance details clearly after the tone. Press pound when done."},
    {"id": "complaint_recorded", "name": "Inbound Complaint Recorded Success", "text": "Your complaint recording has been received and saved. We will look into it. Thank you."}
])

# Pydantic Schemas
class VillagerSchema(BaseModel):
    id: Optional[str] = None
    name: str
    phone: str
    village_ward: str
    status: Optional[str] = "Active"

class CampaignSchema(BaseModel):
    villager_ids: List[str]
    type: str  # survey, summoning, announcement
    details: Dict[str, Any]

class PromptSchema(BaseModel):
    text: str

# Helper to log events inside a call session audit trail
def log_call_event(call_id: str, event_text: str, digits: Optional[str] = None):
    calls = load_json(CALLS_FILE)
    for c in calls:
        if c["id"] == call_id:
            c["history"] = c.get("history", [])
            c["history"].append({
                "time": datetime.datetime.utcnow().isoformat() + "Z",
                "event": event_text
            })
            if digits is not None:
                c["digits_pressed"] = c.get("digits_pressed", [])
                c["digits_pressed"].append(digits)
            break
    save_json(CALLS_FILE, calls)

# --- Sarvam AI Text to Speech Helper (with Cache) ---
def get_audio_xml(text: str, prompt_id: Optional[str] = None) -> str:
    load_dotenv(override=True)
    public_url = os.getenv("PUBLIC_URL")
    api_key = os.getenv("SARVAM_API_KEY")

    # Cache path (absolute)
    audio_dir = Path(__file__).parent.resolve() / "static" / "audio"
    audio_dir.mkdir(exist_ok=True, parents=True)
    
    # Predictable name if prompt_id is present, otherwise md5 of content
    if prompt_id:
        filename = f"{prompt_id}.wav"
    else:
        text_hash = hashlib.md5(text.encode("utf-8")).hexdigest()
        filename = f"{text_hash}.wav"
        
    filepath = audio_dir / filename

    # 1. If audio file is already cached on disk (including pre-synthesized prompts), serve <Play> URL immediately
    if filepath.exists():
        return f"<Play>{public_url}/audio/{filename}</Play>"

    # 2. If no API key and file not cached, return safe ASCII text inside <Speak> (Vobiz drops non-ASCII Devanagari)
    if not api_key or api_key == "your_sarvam_api_key":
        clean_text = text if text.isascii() else "Gram Panchayat notification."
        return f"<Speak>{clean_text}</Speak>"

    try:
        # Request synthesis if not cached
        import time as pytime
        from sarvamai import SarvamAI
        client = SarvamAI(api_subscription_key=api_key)
        
        # Read settings from env, default to Marathi (mr-IN) / Shreya voice
        lang_code = os.getenv("SARVAM_TTS_LANGUAGE", "mr-IN")
        speaker = os.getenv("SARVAM_TTS_SPEAKER", "shreya")
        
        # Translate if English is detected (with retries)
        if re.search(r'[a-zA-Z]{2,}', text):
            for attempt in range(2):
                try:
                    res = client.text.translate(
                        input=text,
                        source_language_code="en-IN",
                        target_language_code="mr-IN"
                    )
                    if res and hasattr(res, "translated_text") and res.translated_text:
                        text = res.translated_text
                        break
                except Exception as e:
                    print(f"[TRANSLATE ATTEMPT {attempt+1} FAILED] {e}")
                    pytime.sleep(0.5)

        # Synthesize voice (with retries)
        synthesized_data = None
        for attempt in range(2):
            try:
                res = client.text_to_speech.convert(
                    text=text,
                    target_language_code=lang_code,
                    model="bulbul:v3",
                    speaker=speaker
                )
                if res and res.audios:
                    synthesized_data = res.audios[0]
                    break
            except Exception as e:
                print(f"[SYNTHESIS ATTEMPT {attempt+1} FAILED] {e}")
                pytime.sleep(0.5)
                
        if not synthesized_data:
            raise Exception("Failed to synthesize audio after retries.")

        import base64
        audio_bytes = base64.b64decode(synthesized_data)
        with open(filepath, "wb") as f:
            f.write(audio_bytes)

        # Return Vobiz Play XML referencing the cached static audio file
        return f"<Play>{public_url}/audio/{filename}</Play>"

    except Exception as e:
        print(f"[ERROR] Sarvam TTS generation failed: {e}")
        clean_text = text if text.isascii() else "Gram Panchayat notification."
        return f"<Speak>{clean_text}</Speak>"

# --- Vobiz API Trigger Call Function ---
def trigger_vobiz_call(to_number: str, call_type: str, call_id: str, villager_id: str) -> tuple[Optional[str], Optional[str]]:
    load_dotenv(override=True)
    auth_id = os.getenv("VOBIZ_AUTH_ID")
    auth_token = os.getenv("VOBIZ_AUTH_TOKEN")
    from_number = os.getenv("FROM_NUMBER")
    public_url = os.getenv("PUBLIC_URL")

    if not auth_id or not auth_token or auth_id == "your_vobiz_auth_id":
        err = "Missing VOBIZ_AUTH_ID or VOBIZ_AUTH_TOKEN credentials"
        print(f"[ERROR] {err}")
        return None, err

    if not from_number or from_number == "+91XXXXXXXXXX":
        err = "Missing or default FROM_NUMBER credential"
        print(f"[ERROR] {err}")
        return None, err

    url = f"https://api.vobiz.ai/api/v1/Account/{auth_id}/Call/"
    
    # Callback answer URL with campaign tracking parameters
    answer_url = f"{public_url}/webhooks/answer?type={call_type}&call_id={call_id}&villager_id={villager_id}"

    hangup_url = f"{public_url}/webhooks/hangup"
    payload = {
        "from": from_number,
        "to": to_number,
        "answer_url": answer_url,
        "answer_method": "POST",
        "hangup_url": hangup_url,
        "hangup_method": "POST"
    }

    headers = {
        "X-Auth-ID": auth_id,
        "X-Auth-Token": auth_token,
        "Content-Type": "application/json"
    }

    try:
        res = requests.post(url, json=payload, headers=headers, timeout=10)
        if res.status_code in [200, 201]:
            res_data = res.json()
            call_uuid = res_data.get("CallUUID") or res_data.get("request_uuid") or res_data.get("id")
            return call_uuid, None
        else:
            err = f"HTTP {res.status_code} - {res.text}"
            print(f"Vobiz Call API error: {err}")
            return None, err
    except Exception as e:
        err = f"Connection error: {e}"
        print(f"Error connecting to Vobiz Call API: {err}")
        return None, err

# --- API Endpoints ---

# System config status
@app.get("/api/config")
def get_config():
    return {
        "mode": "live",
        "configured": bool(os.getenv("VOBIZ_AUTH_ID") and os.getenv("VOBIZ_AUTH_TOKEN"))
    }

# Voice Prompts Library CRUD
@app.get("/api/prompts")
def get_prompts():
    return load_json(PROMPTS_FILE)

@app.put("/api/prompts/{prompt_id}")
def update_prompt(prompt_id: str, p: PromptSchema):
    prompts = load_json(PROMPTS_FILE)
    api_key = os.getenv("SARVAM_API_KEY")
    
    original_text = p.text
    final_text = original_text
    translation_chars = 0
    synthesis_chars = len(final_text)
    
    # Check if input text contains English words (letters) and translate to Marathi
    if api_key and api_key != "your_sarvam_api_key" and re.search(r'[a-zA-Z]{2,}', original_text):
        try:
            from sarvamai import SarvamAI
            client = SarvamAI(api_subscription_key=api_key)
            print(f"[TRANSLATION] English characters detected. Translating to Marathi: {original_text}")
            res = client.text.translate(
                input=original_text,
                source_language_code="en-IN",
                target_language_code="mr-IN"
            )
            if res and hasattr(res, "translated_text") and res.translated_text:
                final_text = res.translated_text
                translation_chars = len(original_text)
                synthesis_chars = len(final_text)
                print(f"[TRANSLATION] Translated result: {final_text}")
        except Exception as e:
            print(f"[TRANSLATION ERROR] Failed to translate: {e}")

    # Calculate Sarvam costs (Translation: ₹20/10K chars, TTS: ₹15/10K chars)
    translation_cost = translation_chars * (20.0 / 10000.0)
    synthesis_cost = synthesis_chars * (15.0 / 10000.0)
    total_cost = translation_cost + synthesis_cost

    cost_data = {
        "translation_chars": translation_chars,
        "translation_cost": round(translation_cost, 4),
        "synthesis_chars": synthesis_chars,
        "synthesis_cost": round(synthesis_cost, 4),
        "total_cost": round(total_cost, 4)
    }

    for idx, item in enumerate(prompts):
        if item["id"] == prompt_id:
            prompts[idx]["text"] = final_text
            prompts[idx]["cost_info"] = cost_data
            save_json(PROMPTS_FILE, prompts)
            
            # Immediately delete old cached file if exists, forcing pre-synthesis regeneration
            audio_path = Path("static/audio") / f"{prompt_id}.wav"
            if audio_path.exists():
                try:
                    audio_path.unlink()
                except Exception:
                    pass
            
            # Pre-generate/synthesize the audio file using Sarvam TTS immediately
            get_audio_xml(final_text, prompt_id=prompt_id)
            return prompts[idx]
            
    raise HTTPException(status_code=404, detail="Prompt not found")

# Villagers CRUD
@app.get("/api/villagers")
def get_villagers():
    return load_json(VILLAGERS_FILE)

@app.post("/api/villagers")
def add_villager(v: VillagerSchema):
    villagers = load_json(VILLAGERS_FILE)
    v.id = "v_" + str(uuid.uuid4())[:8]
    villagers.append(v.model_dump())
    save_json(VILLAGERS_FILE, villagers)
    return v

@app.put("/api/villagers/{v_id}")
def update_villager(v_id: str, v: VillagerSchema):
    villagers = load_json(VILLAGERS_FILE)
    for idx, item in enumerate(villagers):
        if item["id"] == v_id:
            v.id = v_id
            villagers[idx] = v.model_dump()
            save_json(VILLAGERS_FILE, villagers)
            return v
    raise HTTPException(status_code=404, detail="Villager not found")

@app.delete("/api/villagers/{v_id}")
def delete_villager(v_id: str):
    villagers = load_json(VILLAGERS_FILE)
    updated = [item for item in villagers if item["id"] != v_id]
    if len(updated) == len(villagers):
        raise HTTPException(status_code=404, detail="Villager not found")
    save_json(VILLAGERS_FILE, updated)
    return {"message": "Deleted successfully"}

# Preview Campaign TTS
class PreviewSchema(BaseModel):
    text: str

@app.post("/api/campaigns/preview")
def preview_campaign_tts(p: PreviewSchema):
    api_key = os.getenv("SARVAM_API_KEY")
    public_url = os.getenv("PUBLIC_URL")
    
    original_text = p.text
    final_text = original_text
    translation_chars = 0
    synthesis_chars = len(final_text)
    
    # Translate if English is detected
    if api_key and api_key != "your_sarvam_api_key" and re.search(r'[a-zA-Z]{2,}', original_text):
        try:
            from sarvamai import SarvamAI
            client = SarvamAI(api_subscription_key=api_key)
            res = client.text.translate(
                input=original_text,
                source_language_code="en-IN",
                target_language_code="mr-IN"
            )
            if res and hasattr(res, "translated_text") and res.translated_text:
                final_text = res.translated_text
                translation_chars = len(original_text)
                synthesis_chars = len(final_text)
        except Exception as e:
            print(f"[PREVIEW TRANSLATE ERROR] {e}")

    # Calculate cost (Translation: ₹20/10K chars, TTS: ₹15/10K chars)
    translation_cost = translation_chars * (20.0 / 10000.0)
    synthesis_cost = synthesis_chars * (15.0 / 10000.0)
    total_cost = translation_cost + synthesis_cost

    cost_data = {
        "translation_chars": translation_chars,
        "translation_cost": round(translation_cost, 4),
        "synthesis_chars": synthesis_chars,
        "synthesis_cost": round(synthesis_cost, 4),
        "total_cost": round(total_cost, 4)
    }

    # Generate or return audio file cache (uniquely md5 hashed)
    audio_xml = get_audio_xml(final_text)
    
    # Retrieve audio file URL from the returned XML <Play> URL
    match = re.search(r'<Play>(.*?)</Play>', audio_xml)
    audio_url = match.group(1) if match else None

    return {
        "translated_text": final_text,
        "audio_url": audio_url,
        "cost_info": cost_data
    }

# Helper function for background campaign execution
def background_trigger_campaign(camp: CampaignSchema, calls_state: List[dict]):
    # Load prompts for synthesis
    prompts = {p["id"]: p for p in load_json(PROMPTS_FILE)}

    # Pre-generate and cache all required voice prompts before placing calls
    try:
        if camp.type == "survey":
            for p_id in ["survey_intro", "survey_q1", "survey_q2", "survey_q3", "survey_outro"]:
                p_item = prompts.get(p_id, {})
                get_audio_xml(p_item.get("text", ""), prompt_id=p_id)
        elif camp.type == "summoning":
            date = camp.details.get("date", "soon")
            time = camp.details.get("time", "office hours")
            purpose = camp.details.get("purpose", "official meet")
            summon_template = prompts.get("summon_intro", {}).get("text", "Summoning reminder.")
            summon_text = summon_template.format(date=date, time=time, purpose=purpose)
            
            # Pre-synthesize the dynamic summoning details
            get_audio_xml(summon_text)
            
            # Pre-synthesize the choice templates
            for p_id in ["summon_confirm", "summon_reschedule", "summon_cancel", "summon_cancel_confirm"]:
                p_item = prompts.get(p_id, {})
                get_audio_xml(p_item.get("text", ""), prompt_id=p_id)
        elif camp.type == "announcement":
            announcement_text = camp.details.get("announcement", "")
            get_audio_xml(announcement_text)
            
            outro_item = prompts.get("survey_outro", {})
            get_audio_xml(outro_item.get("text", ""), prompt_id="survey_outro")
    except Exception as e:
        print(f"[BACKGROUND PRE-SYNTHESIS ERROR] {e}")

    # Process and place calls
    for c_log in calls_state:
        call_id = c_log["id"]
        v_id = c_log["villager_id"]
        phone = c_log["phone"]
        
        # Trigger Vobiz API
        try:
            uuid_val, err_msg = trigger_vobiz_call(phone, camp.type, call_id, v_id)
            if uuid_val:
                c_log["vobiz_uuid"] = uuid_val
                c_log["status"] = "queued"
                c_log["history"].append({
                    "time": datetime.datetime.utcnow().isoformat() + "Z", 
                    "event": "Call successfully queued on Vobiz"
                })
            else:
                c_log["status"] = "failed"
                c_log["history"].append({
                    "time": datetime.datetime.utcnow().isoformat() + "Z", 
                    "event": f"Vobiz trigger failed: {err_msg or 'Unknown Error'}"
                })
        except Exception as e:
            c_log["status"] = "failed"
            c_log["history"].append({
                "time": datetime.datetime.utcnow().isoformat() + "Z", 
                "event": f"Vobiz trigger error: {e}"
            })
            
    # Save the updated call logs (merge back with other existing records in the file)
    current_calls = load_json(CALLS_FILE)
    calls_map = {c["id"]: c for c in current_calls}
    for c_log in calls_state:
        calls_map[c_log["id"]] = c_log
    save_json(CALLS_FILE, list(calls_map.values()))


# Trigger Campaign Calls (Non-blocking: immediately queues background tasks to prevent client-side timeouts)
@app.post("/api/campaigns/trigger")
def trigger_campaign(camp: CampaignSchema, background_tasks: BackgroundTasks):
    villagers = {v["id"]: v for v in load_json(VILLAGERS_FILE)}
    
    # Load prompts for TTS cost calculation
    prompts = {p["id"]: p for p in load_json(PROMPTS_FILE)}

    calls_state = []

    for v_id in camp.villager_ids:
        if v_id not in villagers:
            continue
        villager = villagers[v_id]
        call_id = "c_" + str(uuid.uuid4())[:8]
        phone = villager["phone"]

        # Calculate estimated TTS cost for this call
        tts_cost = 0.0
        try:
            if camp.type == "survey":
                for p_id in ["survey_intro", "survey_q1", "survey_q2", "survey_q3", "survey_outro"]:
                    p_item = prompts.get(p_id, {})
                    if p_item.get("cost_info"):
                        tts_cost += p_item["cost_info"]["total_cost"]
                    else:
                        tts_cost += len(p_item.get("text", "")) * 0.0015
            elif camp.type == "summoning":
                date = camp.details.get("date", "soon")
                time = camp.details.get("time", "office hours")
                purpose = camp.details.get("purpose", "official meet")
                summon_template = prompts.get("summon_intro", {}).get("text", "Summoning reminder.")
                summon_text = summon_template.format(date=date, time=time, purpose=purpose)
                
                tts_cost += len(summon_text) * 0.0015
                for p_id in ["summon_confirm", "summon_reschedule", "summon_cancel", "summon_cancel_confirm"]:
                    p_item = prompts.get(p_id, {})
                    if p_item.get("cost_info"):
                        tts_cost += p_item["cost_info"]["total_cost"]
                    else:
                        tts_cost += len(p_item.get("text", "")) * 0.0015
            elif camp.type == "announcement":
                announcement_text = camp.details.get("announcement", "")
                tts_cost += len(announcement_text) * 0.0015
                outro_item = prompts.get("survey_outro", {})
                if outro_item.get("cost_info"):
                    tts_cost += outro_item["cost_info"]["total_cost"]
                else:
                    tts_cost += len(outro_item.get("text", "")) * 0.0015
        except Exception:
            pass

        # Call Log Entry
        call_log = {
            "id": call_id,
            "villager_id": v_id,
            "villager_name": villager["name"],
            "phone": phone,
            "type": camp.type,
            "status": "calling",
            "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
            "duration_seconds": 0,
            "telephony_cost": 0.0,
            "tts_cost": round(tts_cost, 4),
            "total_cost": round(tts_cost, 4),
            "survey_results": {} if camp.type == "survey" else None,
            "summoning_status": "pending" if camp.type == "summoning" else None,
            "announcement_played": False if camp.type == "announcement" else None,
            "vobiz_uuid": None,
            "campaign_details": camp.details,
            "digits_pressed": [],
            "history": [
                {"time": datetime.datetime.utcnow().isoformat() + "Z", "event": "Campaign call initiated"}
            ]
        }
        calls_state.append(call_log)

    # Save logs immediately (status: calling) so UI registers them instantly
    calls = load_json(CALLS_FILE)
    calls.extend(calls_state)
    save_json(CALLS_FILE, calls)

    # Enqueue background execution task for pre-synthesis and call routing
    background_tasks.add_task(background_trigger_campaign, camp, calls_state)

    return {
        "status": "success",
        "triggered_count": len(calls_state)
    }

# Call history logs
@app.get("/api/calls")
def get_calls():
    return load_json(CALLS_FILE)

# Analytics Stats
@app.get("/api/calls/stats")
def get_stats():
    calls = load_json(CALLS_FILE)
    
    total = len(calls)
    success = sum(1 for c in calls if c["status"] in ["completed", "answered"])
    no_answer = sum(1 for c in calls if c["status"] == "no_answer")
    failed = sum(1 for c in calls if c["status"] == "failed")
    
    # Surveys stats
    survey_calls = [c for c in calls if c["type"] == "survey" and c["survey_results"]]
    total_surveys = len(survey_calls)
    avg_rating = 0.0
    rec_yes = 0
    rec_no = 0
    satisfaction_good = 0
    satisfaction_neutral = 0
    satisfaction_poor = 0

    if total_surveys > 0:
        ratings = []
        for s in survey_calls:
            results = s["survey_results"]
            if "q1_rating" in results:
                ratings.append(int(results["q1_rating"]))
            if results.get("q2_recommend") == "yes":
                rec_yes += 1
            elif results.get("q2_recommend") == "no":
                rec_no += 1
                
            exp = results.get("q3_experience")
            if exp == "good":
                satisfaction_good += 1
            elif exp == "neutral":
                satisfaction_neutral += 1
            elif exp == "poor":
                satisfaction_poor += 1
                
        if ratings:
            avg_rating = round(sum(ratings) / len(ratings), 1)

    # Summoning stats
    summoning_calls = [c for c in calls if c["type"] == "summoning"]
    total_summons = len(summoning_calls)
    sum_confirmed = sum(1 for c in summoning_calls if c["summoning_status"] == "confirmed")
    sum_reschedule = sum(1 for c in summoning_calls if c["summoning_status"] == "reschedule_requested")
    sum_cancelled = sum(1 for c in summoning_calls if c["summoning_status"] == "cancelled")
    sum_pending = sum(1 for c in summoning_calls if c["summoning_status"] == "pending")

    return {
        "total_calls": total,
        "success_rate": round((success / total * 100), 1) if total > 0 else 0.0,
        "no_answer_count": no_answer,
        "failed_count": failed,
        "surveys": {
            "total": total_surveys,
            "avg_rating": avg_rating,
            "rec_yes": rec_yes,
            "rec_no": rec_no,
            "satisfaction_good": satisfaction_good,
            "satisfaction_neutral": satisfaction_neutral,
            "satisfaction_poor": satisfaction_poor
        },
        "summoning": {
            "total": total_summons,
            "confirmed": sum_confirmed,
            "reschedule": sum_reschedule,
            "cancelled": sum_cancelled,
            "pending": sum_pending
        }
    }

# Export results to CSV
@app.get("/api/calls/export")
def export_csv():
    calls = load_json(CALLS_FILE)
    csv_content = "CallID,Name,Phone,Type,Status,Timestamp,Details\n"
    for c in calls:
        details = ""
        if c["type"] == "survey" and c["survey_results"]:
            res = c["survey_results"]
            details = f"Rating: {res.get('q1_rating')}; Recommend: {res.get('q2_recommend')}; Experience: {res.get('q3_experience')}"
        elif c["type"] == "summoning":
            details = f"Status: {c.get('summoning_status')}"
        csv_content += f"{c['id']},{c['villager_name']},{c['phone']},{c['type']},{c['status']},{c['timestamp']},{details}\n"
    
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=panchayat_call_logs.csv"}
    )


# --- Vobiz Webhook Callback Endpoints ---

@app.post("/webhooks/answer")
async def answer_webhook(
    type: Optional[str] = None,
    call_id: Optional[str] = None,
    villager_id: Optional[str] = None,
    CallUUID: Optional[str] = Form(None),
    From: Optional[str] = Form(None)
):
    public_url = os.getenv("PUBLIC_URL")

    # Update Call UUID in log
    if call_id and CallUUID:
        calls = load_json(CALLS_FILE)
        for c in calls:
            if c["id"] == call_id:
                c["vobiz_uuid"] = CallUUID
                c["status"] = "answered"
        save_json(CALLS_FILE, calls)
        log_call_event(call_id, "Call answered by user")

    # Inbound call fallback (serve the Main Panchayat Inbound IVR menu)
    if not type:
        prompts = {p["id"]: p["text"] for p in load_json(PROMPTS_FILE)}
        menu_text = prompts.get("inbound_main", "Welcome to the Panchayat services.")
        return make_response_xml(
            f'<Gather inputType="dtmf" action="{public_url}/webhooks/complaints/ivr-main-choice" numDigits="1" timeout="10">'
            f'  {get_audio_xml(menu_text, "inbound_main")}'
            f'</Gather>'
            f'<Hangup />'
        )

    # Retrieve campaign details if stored locally
    campaign_details = {}
    calls = load_json(CALLS_FILE)
    for c in calls:
        if c["id"] == call_id:
            campaign_details = c.get("campaign_details", {})
            break

    # Outbound Survey Campaign Answer
    if type == "survey":
        prompts = {p["id"]: p["text"] for p in load_json(PROMPTS_FILE)}
        survey_intro = prompts.get("survey_intro", "Hello! This is an automated survey call from your Gram Panchayat.")
        q1 = prompts.get("survey_q1", "Rate water supply cleanliness: press 1-5.")
        return make_response_xml(
            f'<Gather inputType="dtmf" action="{public_url}/webhooks/survey-q1-result?call_id={call_id}&amp;villager_id={villager_id}" numDigits="1" timeout="10">'
            f'  {get_audio_xml(survey_intro, "survey_intro")}'
            f'  {get_audio_xml(q1, "survey_q1")}'
            f'</Gather>'
            f'<Hangup />'
        )

    # Outbound Summoning Campaign Answer
    elif type == "summoning":
        date = campaign_details.get("date", "soon")
        time = campaign_details.get("time", "office hours")
        purpose = campaign_details.get("purpose", "official meet")
        
        prompts = {p["id"]: p["text"] for p in load_json(PROMPTS_FILE)}
        summon_template = prompts.get("summon_intro", "Summoning reminder.")
        summon_intro = summon_template.format(date=date, time=time, purpose=purpose)

        return make_response_xml(
            f'<Gather inputType="dtmf" action="{public_url}/webhooks/appt-choice?call_id={call_id}" numDigits="1" timeout="10">'
            f'  {get_audio_xml(summon_intro)}'
            f'</Gather>'
            f'<Hangup />'
        )

    # Outbound Announcement Campaign Answer
    elif type == "announcement":
        announcement_text = campaign_details.get("announcement", "Important announcement from your local Gram Panchayat.")
        prompts = {p["id"]: p["text"] for p in load_json(PROMPTS_FILE)}
        outro_text = prompts.get("survey_outro", "Thank you. Goodbye.")

        # Log Announcement Finished
        for c in calls:
            if c["id"] == call_id:
                c["status"] = "completed"
                c["announcement_played"] = True
        save_json(CALLS_FILE, calls)
        log_call_event(call_id, "Broadcast announcement completed")

        return make_response_xml(
            f'{get_audio_xml(announcement_text)}'
            f'{get_audio_xml(outro_text, "survey_outro")}'
            f'<Hangup />'
        )

    return make_response_xml('<Speak>Invalid call routing parameter. Goodbye.</Speak><Hangup />')

# Survey Steps
@app.post("/webhooks/survey-q1")
def survey_q1(call_id: str, villager_id: str):
    public_url = os.getenv("PUBLIC_URL")
    prompts = {p["id"]: p["text"] for p in load_json(PROMPTS_FILE)}
    q1 = prompts.get("survey_q1", "Rate water supply cleanliness: press 1-5.")

    return make_response_xml(
        f'<Gather inputType="dtmf" action="{public_url}/webhooks/survey-q1-result?call_id={call_id}&amp;villager_id={villager_id}" numDigits="1">'
        f'  {get_audio_xml(q1, "survey_q1")}'
        f'</Gather>'
        f'<Redirect>{public_url}/webhooks/survey-q1?call_id={call_id}&amp;villager_id={villager_id}</Redirect>'
    )

@app.post("/webhooks/survey-q1-result")
def survey_q1_result(call_id: str, villager_id: str, Digits: str = Form("5")):
    public_url = os.getenv("PUBLIC_URL")
    log_call_event(call_id, f"Answered Survey Q1: {Digits}", digits=Digits)

    # Save Q1 Rating
    calls = load_json(CALLS_FILE)
    for c in calls:
        if c["id"] == call_id:
            c["survey_results"]["q1_rating"] = int(Digits) if Digits.isdigit() else 5
            break
    save_json(CALLS_FILE, calls)

    prompts = {p["id"]: p["text"] for p in load_json(PROMPTS_FILE)}
    q2 = prompts.get("survey_q2", "Recommend new scheme? Press 1 for Yes, 2 for No.")

    return make_response_xml(
        f'<Gather inputType="dtmf" action="{public_url}/webhooks/survey-q2-result?call_id={call_id}&amp;villager_id={villager_id}" numDigits="1" timeout="10">'
        f'  {get_audio_xml(q2, "survey_q2")}'
        f'</Gather>'
        f'<Hangup />'
    )

@app.post("/webhooks/survey-q2-result")
def survey_q2_result(call_id: str, villager_id: str, Digits: str = Form("1")):
    public_url = os.getenv("PUBLIC_URL")
    log_call_event(call_id, f"Answered Survey Q2: {Digits}", digits=Digits)
    rec = "yes" if Digits == "1" else "no"
    
    calls = load_json(CALLS_FILE)
    for c in calls:
        if c["id"] == call_id:
            c["survey_results"]["q2_recommend"] = rec
            break
    save_json(CALLS_FILE, calls)

    prompts = {p["id"]: p["text"] for p in load_json(PROMPTS_FILE)}
    q3 = prompts.get("survey_q3", "Overall experience: Press 1 for Good, 2 Neutral, 3 Poor.")

    return make_response_xml(
        f'<Gather inputType="dtmf" action="{public_url}/webhooks/survey-q3-result?call_id={call_id}&amp;villager_id={villager_id}" numDigits="1" timeout="10">'
        f'  {get_audio_xml(q3, "survey_q3")}'
        f'</Gather>'
        f'<Hangup />'
    )

@app.post("/webhooks/survey-q3-result")
def survey_q3_result(call_id: str, villager_id: str, Digits: str = Form("1")):
    log_call_event(call_id, f"Answered Survey Q3: {Digits}", digits=Digits)
    exp = "good" if Digits == "1" else ("neutral" if Digits == "2" else "poor")
    
    calls = load_json(CALLS_FILE)
    for c in calls:
        if c["id"] == call_id:
            c["survey_results"]["q3_experience"] = exp
            c["status"] = "completed"
            break
    save_json(CALLS_FILE, calls)
    log_call_event(call_id, "Survey Campaign Completed")

    prompts = {p["id"]: p["text"] for p in load_json(PROMPTS_FILE)}
    outro = prompts.get("survey_outro", "Thank you. Goodbye.")

    return make_response_xml(
        f'{get_audio_xml(outro, "survey_outro")}'
        f'<Hangup />'
    )

# Summoning Routing Choice
@app.post("/webhooks/appt-choice")
def appt_choice(call_id: str, Digits: str = Form("1")):
    public_url = os.getenv("PUBLIC_URL")
    log_call_event(call_id, f"Key pressed in Summoning Menu: {Digits}", digits=Digits)
    
    prompts = {p["id"]: p["text"] for p in load_json(PROMPTS_FILE)}

    status = "pending"
    speak = ""
    redirect = ""

    if Digits == "1":
        status = "confirmed"
        text = prompts.get("summon_confirm", "Your summoning is confirmed. Thank you.")
        speak = f"{get_audio_xml(text, 'summon_confirm')}<Hangup />"
    elif Digits == "2":
        status = "reschedule_requested"
        text = prompts.get("summon_reschedule", "Reschedule request received.")
        speak = f"{get_audio_xml(text, 'summon_reschedule')}<Hangup />"
    elif Digits == "3":
        text = prompts.get("summon_cancel_confirm", "Are you sure you want to cancel?")
        speak = (
            f'<Gather inputType="dtmf" action="{public_url}/webhooks/appt-cancel-confirm?call_id={call_id}" numDigits="1" timeout="10">'
            f'  {get_audio_xml(text, "summon_cancel_confirm")}'
            f'</Gather>'
            f'<Hangup />'
        )
    elif Digits == "9":
        redirect = f'<Redirect>{public_url}/webhooks/answer?type=summoning&amp;call_id={call_id}</Redirect>'
    else:
        speak = get_audio_xml("Invalid key entry.")
        redirect = f'<Redirect>{public_url}/webhooks/answer?type=summoning&amp;call_id={call_id}</Redirect>'

    if status != "pending":
        calls = load_json(CALLS_FILE)
        for c in calls:
            if c["id"] == call_id:
                c["summoning_status"] = status
                c["status"] = "completed"
                break
        save_json(CALLS_FILE, calls)
        log_call_event(call_id, f"Summoning status finalized to {status.upper()}")

    return make_response_xml(speak + redirect)

@app.post("/webhooks/appt-cancel-confirm")
def appt_cancel_confirm(call_id: str, Digits: str = Form("1")):
    public_url = os.getenv("PUBLIC_URL")
    log_call_event(call_id, f"Cancellation confirm menu choice: {Digits}", digits=Digits)
    prompts = {p["id"]: p["text"] for p in load_json(PROMPTS_FILE)}

    if Digits == "1":
        calls = load_json(CALLS_FILE)
        for c in calls:
            if c["id"] == call_id:
                c["summoning_status"] = "cancelled"
                c["status"] = "completed"
                break
        save_json(CALLS_FILE, calls)
        log_call_event(call_id, "Summoning status finalized to CANCELLED")
        
        text = prompts.get("summon_cancel", "Your summoning is cancelled. Goodbye.")
        return make_response_xml(f"{get_audio_xml(text, 'summon_cancel')}<Hangup />")
    
    return make_response_xml(f'<Redirect>{public_url}/webhooks/answer?type=summoning&amp;call_id={call_id}</Redirect>')

# Inbound Call Grievance/Complaint Main Menu Choice
@app.post("/webhooks/complaints/ivr-main-choice")
def complaints_ivr_choice(Digits: str = Form("0")):
    public_url = os.getenv("PUBLIC_URL")
    prompts = {p["id"]: p["text"] for p in load_json(PROMPTS_FILE)}

    if Digits == "1":
        return make_response_xml(
            f'{get_audio_xml("Connecting to the Agricultural Extension officer. Please hold.")}'
            '<Dial><Number>+919999900001</Number></Dial>'
            '<Hangup />'
        )
    elif Digits == "2":
        text = prompts.get("complaint_record_intro", "Please record complaint details after the tone.")
        return make_response_xml(
            f'{get_audio_xml(text, "complaint_record_intro")}'
            f'<Record action="{public_url}/webhooks/complaints/recorded" maxLength="30" playBeep="true" />'
        )
    elif Digits == "3":
        return make_response_xml(
            f'{get_audio_xml("For certificates, submit documents at the Panchayat Sewa Kendra on weekdays from 10 AM to 4 PM. Thank you.")}'
            '<Hangup />'
        )
    elif Digits == "0":
        return make_response_xml(
            f'{get_audio_xml("Connecting call directly to the Panchayat Head, Sarpanch. Please hold.")}'
            '<Dial><Number>+919999900000</Number></Dial>'
            '<Hangup />'
        )
    return make_response_xml(f'<Redirect>{public_url}/webhooks/answer</Redirect>')

@app.post("/webhooks/complaints/recorded")
def complaints_recorded():
    prompts = {p["id"]: p["text"] for p in load_json(PROMPTS_FILE)}
    text = prompts.get("complaint_recorded", "Grievance received. Thank you.")
    return make_response_xml(
        f'{get_audio_xml(text, "complaint_recorded")}'
        '<Hangup />'
    )

# Hangup Event Logging
@app.post("/webhooks/hangup")
def hangup_callback(
    CallUUID: Optional[str] = Form(None),
    Duration: Optional[str] = Form(None),
    CallDuration: Optional[str] = Form(None),
    CallStatus: Optional[str] = Form(None)
):
    import math
    if CallUUID:
        calls = load_json(CALLS_FILE)
        for c in calls:
            if c["vobiz_uuid"] == CallUUID:
                # Log hangup event
                status_lbl = CallStatus or "DISCONNECTED"
                c["history"].append({
                    "time": datetime.datetime.utcnow().isoformat() + "Z",
                    "event": f"Call hung up (Status: {status_lbl})"
                })
                
                # Determine duration in seconds
                dur_str = Duration or CallDuration
                dur_sec = int(dur_str) if dur_str and dur_str.isdigit() else 0
                
                # Fallback: calculate duration from timeline history if Vobiz returns 0
                if dur_sec == 0:
                    answered_time = None
                    hangup_time = None
                    for h in c["history"]:
                        if "Call answered" in h["event"]:
                            try:
                                answered_time = datetime.datetime.fromisoformat(h["time"].replace("Z", ""))
                            except Exception:
                                pass
                        elif "Call hung up" in h["event"]:
                            try:
                                hangup_time = datetime.datetime.fromisoformat(h["time"].replace("Z", ""))
                            except Exception:
                                pass
                    if answered_time and hangup_time:
                        dur_sec = max(0, int((hangup_time - answered_time).total_seconds()))
                
                # Calculate costs (round up call minutes, flat ₹0.40/minute rate)
                call_minutes = math.ceil(dur_sec / 60.0)
                telephony_cost = call_minutes * 0.40
                
                c["duration_seconds"] = dur_sec
                c["telephony_cost"] = round(telephony_cost, 4)
                c["total_cost"] = round(c.get("tts_cost", 0.0) + telephony_cost, 4)
                
                # Update status
                if CallStatus:
                    c["status"] = CallStatus.lower()
                elif c["status"] in ["calling", "queued"]:
                    c["status"] = "no_answer"
                break
        save_json(CALLS_FILE, calls)
    return {"status": "ok"}


# Serve static web dashboard
static_path = (Path(__file__).parent.resolve() / "static")
static_path.mkdir(exist_ok=True)

app.mount("/", StaticFiles(directory=str(static_path), html=True), name="static")
