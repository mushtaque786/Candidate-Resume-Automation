import requests
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from groq import Groq
from typing import List, Dict
import json
import re
import random
import PyPDF2
import smtplib
import http.client
import os
from email.mime.text import MIMEText

load_dotenv()

# Initialize FastAPI app
app = FastAPI()


client = Groq(api_key=os.getenv("GROQ_API_KEY"))
CALENDLY_API_KEY = os.getenv("CALENDLY_API_KEY")
LEVER_API_KEY = os.getenv("LEVER_API_KEY")
SMTP_EMAIL = os.getenv("SMTP_EMAIL")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")

# API endpoints
POSTINGS_URL = "https://fd4c61a1-d161-4de2-92e4-50fd468a8e82.mock.pstmn.io/postings"
CANDIDATES_URL = "https://fd4c61a1-d161-4de2-92e4-50fd468a8e82.mock.pstmn.io/candidates"
LEVER_API_BASE = "https://api.lever.co/v1"
CALENDLY_LINK = "https://api.calendly.com"


# Pydantic models
class Candidate(BaseModel):
    id: str
    name: str
    headline: str
    location: str
    tags: List[str]
    origin: str
    opportunityLocation: str
    emails: List[str]
    resume_url: str

class JobPosting(BaseModel):
    id: str
    text: str
    categories: Dict
    tags: List[str]
    content: Dict
    country: str
    workplaceType: str

class MatchRequest(BaseModel):
    job_id: str
    model_name: str

class MatchResponse(BaseModel):
    candidate_id: str
    name: str
    match_score: float
    email: str
    assessment: str
    job_title: str

class CalendlyRequest(BaseModel):
    candidate_id: str
    candidate_name: str
    candidate_email: str
    job_title: str


# Fetch and parse resume from URL
def fetch_resume_summary(resume_url: str) -> str:
    try:
        response = requests.get(resume_url)
        response.raise_for_status()
        pdf_file = PyPDF2.PdfReader(response.content)
        text = ""
        for page in pdf_file.pages:
            text += page.extract_text()
        return text[:1000]  # Limit to 1000 chars for LLM
    except Exception as e:
        return f"Failed to fetch resume: {str(e)}"



def sanitize_text(text: str) -> str:
    # Remove control characters
    return re.sub(r"[\x00-\x1F\x7F]", "", text)


def get_llm_assessment(candidate: Dict, posting: Dict, model_name: str) -> Dict:
    try:
        # Sanitize candidate data
        candidate = {key: sanitize_text(value) if isinstance(value, str) else value for key, value in candidate.items()}

        # Fetch and sanitize resume details
        resume_details = sanitize_text(fetch_resume_summary(candidate["resume_url"]))
        resume_details = json.dumps(resume_details)  

        # Prepare job and candidate details
        job_details = {
            "title": posting["text"],
            "commitment": posting["categories"]["commitment"],
            "location": posting["categories"]["location"],
            "team": posting["categories"]["team"],
            "all_locations": posting["categories"]["allLocations"],
            "tags": posting["tags"],
            "description": posting["content"]["description"],
            "requirements": "\n".join([f"{lst['text']}: {lst['content']}" for lst in posting["content"]["lists"]]),
            "country": posting["country"],
            "workplace_type": posting["workplaceType"]
        }

        cand_details = {
            "headline": candidate["headline"],
            "location": candidate["location"],
            "tags": candidate["tags"],
            "origin": candidate["origin"],
            "opportunity_location": candidate["opportunityLocation"],
            "resume_complete_summary": resume_details
        }

        # Prepare LLM prompt
        prompt = f"""
        You are an AI talent evaluator. Your task is to assess how well a candidate matches a job posting based on their skills, experience, and qualifications.

        Instructions:
        Evaluate the candidate objectively without bias or unnecessary criticism.
        Ensure no humiliation or negative wording in your assessment.
        Return only a structured JSON response—no extra explanations or text.

        Job Posting Details:
        Title: {job_details["title"]}
        Commitment: {job_details["commitment"]}
        Location: {job_details["location"]}
        Team: {job_details["team"]}
        All Locations: {', '.join(job_details["all_locations"])}
        Tags: {', '.join(job_details["tags"])}
        Description: {job_details["description"]}
        Requirements: {job_details["requirements"]}
        Country: {job_details["country"]}
        Workplace Type: {job_details["workplace_type"]}

        Candidate Details:
        Headline: {cand_details["headline"]}
        Location: {cand_details["location"]}
        Tags: {', '.join(cand_details["tags"])}
        Origin: {cand_details["origin"]}
        Opportunity Location: {cand_details["opportunity_location"]}
        Resume Summary: {resume_details}

        Evaluation Criteria:
        Assess the candidate based on:

        Skill & Experience Match - Does the candidate's experience align with job requirements?
        Location Fit - Is the candidate located in an eligible area or open to relocation?
        Education & Qualifications - Do they meet or exceed the required credentials?

        Language Proficiency - Are they fluent in the necessary languages?

        Output Format (JSON Only)
        Return your response in the exact format below, with a match score (0-100) and a concise, constructive assessment.

        {{
          "score": <number>,
          "assessment": "<brief, neutral explanation of strengths and areas for improvement>"
        }}
        """

        # Call LLM with the specified model
        completion = client.chat.completions.create(
            model=model_name,
            messages=[{"role": "user", "content": prompt}],
            temperature=1,
            max_tokens=1024,
            top_p=1,
            stream=False,
            stop=None,
        )

        # Collect streaming response
        full_response = completion.choices[0].message.content

        # Clean up the response
        cleaned_response = full_response.strip()
        if cleaned_response.startswith("```json"):
            cleaned_response = cleaned_response[7:] 
        if cleaned_response.endswith("```"):
            cleaned_response = cleaned_response[:-3] 
        cleaned_response = cleaned_response.strip()
        print("Cleaned LLM Response:", cleaned_response)

        # Check if the response is empty
        if not cleaned_response.strip():
            print(f"Empty response for candidate: {candidate['id']}")
            return {"score": 0, "assessment": "No response from LLM"}

        try:
            result = json.loads(cleaned_response)
            return result
        except json.JSONDecodeError as e:
            print(f"Error parsing LLM response for candidate: {candidate['id']}")
            print(f"Raw response: {cleaned_response}")
            return {"score": 0, "assessment": "Invalid response format from LLM"}

    except Exception as e:
        print(f"Error generating LLM assessment for candidate: {candidate['id']}")
        print(f"Error details: {str(e)}")
        return {"score": 0, "assessment": "Error generating assessment"}
    



# Lever API stage change
def move_candidate_to_next_stage(candidate_id: str):
    headers = {"Authorization": f"Bearer {LEVER_API_KEY}"}
    payload = {"stage": "next-stage-id"}
    response = requests.post(
        f"{LEVER_API_BASE}/candidates/{candidate_id}/stage",
        headers=headers,
        json=payload
    )
    return response.status_code == 200

# Send email with Calendly link
def send_candidate_email(candidate: Dict, job_title: str):
    msg = MIMEText(
        f"Congrats {candidate['name']},\n\nYou've been moved to the next stage for the {job_title} role. "
        f"Please book a meeting with the recruiter here: {CALENDLY_LINK}\n\nBest regards,\nRecruitment Team"
    )
    msg["Subject"] = "Next Steps in Your Application"
    msg["From"] = SMTP_EMAIL
    msg["To"] = candidate["emails"][0]

    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.starttls()
        server.login(SMTP_EMAIL, SMTP_PASSWORD)
        server.send_message(msg)


def fetch_data():
    try:
        # Fetch postings and candidates from the respective URLs
        postings_response = requests.get(POSTINGS_URL)
        candidates_response = requests.get(CANDIDATES_URL)

        postings_response.raise_for_status()
        candidates_response.raise_for_status()

        # Parse the JSON responses
        postings = postings_response.json().get("postings", [])
        candidates = candidates_response.json().get("candidates", [])

        # Log the count of candidates
        print(f"Number of candidates fetched: {len(candidates)}")

        return postings, candidates
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Data fetch failed: {str(e)}")
    

# FastAPI endpoint
@app.post("/match", response_model=List[MatchResponse])
async def match_candidates(request: MatchRequest):
    #select random 10 candidate and pass to llm model function to get fitout score.
    postings, candidates = fetch_data()
    print(f"Total candidates: {len(candidates)}")
    posting = next((p for p in postings if p["id"] == request.job_id), None)

    if not posting:
        raise HTTPException(status_code=404, detail="Job posting not found")

    # Select 10 random candidates
    random_candidates = random.sample(candidates, min(10, len(candidates)))

    matches = []
    for candidate in random_candidates:
        print(candidate)
        result = get_llm_assessment(candidate, posting,request.model_name)
        print("=="*50)
        print("LLM Result:", result)
        match_response = MatchResponse(
            candidate_id=candidate["id"],
            name=candidate["name"],
            match_score=result["score"],
            email=candidate["emails"][0],
            assessment=result["assessment"],
            job_title=posting['text']
        )

        
        matches.append(match_response)
       
        #if we set manual thresold then HR don't need to move to next stage system automtically take care of that. 
        # Move to next stage and notify if approved
        # if score > 70:  # Threshold for approval
        #     if move_candidate_to_next_stage(candidate["id"]):
        #         send_candidate_email(candidate, posting["text"])
        #         print(f"Moved {candidate['name']} to next stage and sent email.")
        #     else:
        #         print(f"Failed to move {candidate['name']} to next stage.")

    return matches




@app.post("/generate-calendly-link-send-email")
async def generate_calendly_link(request: CalendlyRequest):
    try:
        # Mock API call to Calendly to generate link and send email
        conn = http.client.HTTPSConnection("stoplight.io")
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {CALENDLY_API_KEY}"
        }
        payload = json.dumps({
            "max_event_count": 1,
            "owner": "https://api.calendly.com/event_types/012345678901234567890",
            "owner_type": "EventType"
        })
        conn.request("POST", "/mocks/calendly/api-docs/395/scheduling_links", payload, headers)
        res = conn.getresponse()
        data = res.read()
        mock_response = json.loads(data.decode("utf-8"))  # Parse JSON response

        # Log the mock response
        print("Mock Calendly API Response:", mock_response)

        
        candidate_name=request.candidate_name
        candidate_email=request.candidate_email
        job_title=request.job_title
        calendly_link=mock_response["resource"]["booking_url"]
        
        body= (f"Dear {candidate_name},\n\n"
            f"Congratulations! You've been shortlisted for the {job_title} role.\n"
            f"Please use the following link to book a meeting at your convenience:\n\n"
            f"{calendly_link}\n\n"
            f"Best regards,\nRecruitment Team")
        msg = MIMEText( body )
        msg["Subject"] = f"Meeting Invitation for {job_title}"
        msg["From"] = SMTP_EMAIL
        msg["To"] = candidate_email
        print(msg)
        
        # Send the email using SMTP
        #comment- below code as we don't have credential to send. 
        # with smtplib.SMTP("smtp.gmail.com", 587) as server:
        #     server.starttls()
        #     server.login(SMTP_EMAIL, SMTP_PASSWORD)
        #     server.send_message(msg)

        print(f"Calendly link sent to {candidate_name} ({candidate_email}) for {job_title}.")
        return {
            "status": "success",
            "message": f"Calendly link sent to {request.candidate_email}",
            "link": mock_response["resource"]["booking_url"],
            "msg":body  
        }

    except Exception as e:
        print(f"Error in mock Calendly link generation: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to generate Calendly link: {str(e)}")
    



# Pre-filtering function - Commenting now as are not doing it yet.
# def pre_filter_candidate(candidate: Dict, posting: Dict) -> bool:
#     """Filter candidates based on 40% match criteria."""
#     match_criteria = 0
#     total_criteria = 5  # location, skills/tags, experience, job title, education

#     # Location match
#     job_location = posting["categories"]["location"]
#     cand_location = candidate["opportunityLocation"] or candidate["location"]
#     if job_location.lower() in cand_location.lower():
#         match_criteria += 1

#     # Skills/Tags match
#     job_skills = set(posting["content"].get("lists", [{}])[1].get("content", "").lower().split())
#     cand_skills = set(tag.lower() for tag in candidate["tags"])
#     if job_skills & cand_skills:
#         match_criteria += 1

#     # Experience match (inferred from tags or resume if available)
#     job_exp = "5+" if "senior" in posting["text"].lower() else "1+"
#     cand_exp = any("year" in tag.lower() or "experience" in tag.lower() for tag in candidate["tags"])
#     if cand_exp or job_exp == "1+":
#         match_criteria += 1

#     # Job title match
#     job_title = posting["text"].lower()
#     cand_title = candidate.get("headline", "").lower()
#     if any(word in cand_title for word in job_title.split()):
#         match_criteria += 1

#     match_criteria += 1 

#     return (match_criteria / total_criteria) >= 0.4

