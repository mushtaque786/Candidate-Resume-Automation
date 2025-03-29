# Candidate-Resume-Automation

How to Run Test Task - POC Code

Step 1: Install Dependencies

Run the following command to install all required dependencies from requirements.txt:

pip install -r /path/to/requirements.txt

Step 2: Start the FastAPI Server

Execute the following command to run main.py and start the FastAPI application:

uvicorn main:app --reload

Once the server is running, click on the URL displayed in the terminal to access the API.

To view FastAPI endpoint documentation, open one of the following links in your browser:

Swagger UI: http://127.0.0.1:8000/docs

Redoc: http://127.0.0.1:8000/redoc

Step 3: Run the UI for API Interaction

To test the API using a simple UI dashboard, run UI.py with Streamlit:

streamlit run UI.py

This will launch the Streamlit interface, allowing you to interact with the API visually.
To view  UI open Local URL: http://localhost:8501
