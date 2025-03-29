import streamlit as st
import requests
import time

#posting file and api endpoint
POSTINGS_URL = "https://fd4c61a1-d161-4de2-92e4-50fd468a8e82.mock.pstmn.io/postings"
MATCH_API_URL = "http://127.0.0.1:8000/match"
CALENDLY_API_URL = "http://localhost:8000/generate-calendly-link-send-email"

def fetch_postings():
    """Fetches job postings from the mock API and ensures it's a list."""
    try:
        response = requests.get(POSTINGS_URL)
        response.raise_for_status()
        data = response.json()
        
        if isinstance(data, dict):
            data = data.get("postings", [])

        if not isinstance(data, list):
            st.error("Unexpected API response format")
            return []
        
        return data
    except requests.exceptions.RequestException as e:
        st.error(f"Error fetching postings: {e}")
        return []

def send_email(candidate_id, candidate_name, candidate_email, job_title):
    """Sends a request to generate a Calendly link."""
    payload = {
        "candidate_id": candidate_id,
        "candidate_name": candidate_name,
        "candidate_email": candidate_email,
        "job_title": job_title
    }
    try:
        response = requests.post(CALENDLY_API_URL, json=payload)
        response.raise_for_status()
        response_data = response.json()
        st.success("Email sent Successfully!")
        st.write(response_data.get("msg", "No message available"))
    except requests.exceptions.RequestException as e:
        st.error(f"Error generating Calendly link: {e}")

def main():
    st.markdown(
        """
        <style>
            .stApp { background-color: #022E34; padding: 20px; }
            .stTitle { text-align: center; font-size: 28px; font-weight: bold; color: #0d47a1; }
            .stHeader { font-size: 22px; font-weight: bold; color: #1565c0; margin-bottom: 10px; }
            .stSuccess { color: green; font-weight: bold; }
            .candidate-card { background-color: white; padding: 15px; border-radius: 8px; box-shadow: 2px 2px 10px rgba(0,0,0,0.1); margin-bottom: 15px; border-left: 5px solid #1e88e5; }
            .candidate-header { font-size: 20px; font-weight: bold; color: #61c6e2; }
        </style>
        """,
        unsafe_allow_html=True
    )

    st.image("ideals_white.png", width=150)
    st.title("Job Matching Interface")

    if "candidates" not in st.session_state:
        st.session_state.candidates = []
    if "show_email" not in st.session_state:
        st.session_state.show_email = {}
    if "selected_job" not in st.session_state:
        st.session_state.selected_job = ""
    if "selected_model" not in st.session_state:
        st.session_state.selected_model = ""

    postings = fetch_postings()

    if postings:
        try:
            job_ids = [f"{posting['id']} - {posting['text']}" for posting in postings 
                       if isinstance(posting, dict) and "id" in posting and "text" in posting]
        except TypeError:
            st.error("Unexpected data format in postings")
            return

        job_models = ["gemma2-9b-it", "llama3-8b-8192", "deepseek-r1-distill-qwen-32b","qwen-2.5-32b"]

        selected_job = st.selectbox("Select Job ID", job_ids)
        selected_model_name = st.selectbox("Select Model Name", job_models)

        job_id = selected_job.split(" - ")[0]  
        job_title = selected_job.split(" - ")[1] 
        if st.button("Send", key="send_button", help="Click to fetch candidate matches"):
            payload = {
                "job_id": job_id,
                "model_name": selected_model_name,
            }
            with st.spinner("Processing... Please wait."):
                time.sleep(2)  
                try:
                    response = requests.post(MATCH_API_URL, json=payload)
                    response.raise_for_status()
                    st.session_state.candidates = response.json()
                except requests.exceptions.RequestException as e:
                    st.error(f"Error calling match API: {e}")

    if st.session_state.candidates:
        for candidate in st.session_state.candidates:
            with st.container():
                st.markdown("<div class='candidate-card'>", unsafe_allow_html=True)
                st.markdown(f"<div class='candidate-header'>{candidate['name']}</div>", unsafe_allow_html=True)
                st.write(f"**Candidate ID:** {candidate['candidate_id']}")
                st.write(f"**Candidate Email:** {candidate['email']}")
                st.write(f"**Fit Out Score:** {candidate['match_score']}")
                st.write(f"**Job Title:** {candidate['job_title']}")
                ai_response = st.text_area("Modify AI Response", candidate["assessment"], key=f"response_{candidate['candidate_id']}")
                
                action_key = f"action_{candidate['candidate_id']}"
                if action_key not in st.session_state:
                    st.session_state[action_key] = "Select an option"
                
                action = st.selectbox("Action", ["Select an option", "Move to Next Stage", "Rejected"], key=action_key)
                
                if action == "Move to Next Stage":
                    st.session_state.show_email[candidate['candidate_id']] = True
                    st.success("Comment saved and stage updated in the platform:")
                    st.write(ai_response)
                else:
                    st.session_state.show_email[candidate['candidate_id']] = False
                    
                if st.session_state.show_email.get(candidate['candidate_id']):
                    if st.button("Send Email", key=f"email_{candidate['candidate_id']}"):
                        with st.spinner("Sending Email... Please wait."):
                            time.sleep(1)
                            send_email(candidate['candidate_id'], candidate['name'], candidate['email'], candidate['job_title'])
                st.markdown("</div>", unsafe_allow_html=True)
    else:
        st.warning("No candidates available.")

if __name__ == "__main__":
    main()