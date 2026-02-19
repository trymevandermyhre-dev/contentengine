from fastapi import FastAPI
import os
import json
from google.oauth2 import service_account
from googleapiclient.discovery import build

app = FastAPI()

@app.get("/")
def root():
    return {"status": "contentengine running"}

# ---- GOOGLE DRIVE SETUP ----

SCOPES = ["https://www.googleapis.com/auth/drive"]

service_account_info = json.loads(
    os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"]
)

credentials = service_account.Credentials.from_service_account_info(
    service_account_info, scopes=SCOPES
)

drive_service = build("drive", "v3", credentials=credentials)

# ---- HELPERS ----

def get_folder_id(name):
    results = drive_service.files().list(
        q=f"mimeType='application/vnd.google-apps.folder' and name='{name}'",
        fields="files(id, name)"
    ).execute()
    files = results.get("files", [])
    return files[0]["id"] if files else None

# ---- ENDPOINT ----

@app.get("/list-new")
def list_new_images():
    folder_id = get_folder_id("new")
    if not folder_id:
        return {"error": "new folder not found"}

    results = drive_service.files().list(
        q=f"'{folder_id}' in parents and mimeType contains 'image/'",
        fields="files(name)"
    ).execute()

    return [f["name"] for f in results.get("files", [])]

