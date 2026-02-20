from fastapi import FastAPI
import os, json, base64, io
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from openai import OpenAI

app = FastAPI()

# ---------- OPENAI ----------
client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

# ---------- GOOGLE DRIVE ----------
SCOPES = ["https://www.googleapis.com/auth/drive"]
service_account_info = json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"])

credentials = service_account.Credentials.from_service_account_info(
    service_account_info, scopes=SCOPES
)

drive = build("drive", "v3", credentials=credentials)

# ---------- HELPERS ----------
def get_folder_id(name):
    res = drive.files().list(
        q=f"mimeType='application/vnd.google-apps.folder' and name='{name}'",
        fields="files(id,name)"
    ).execute()
    files = res.get("files", [])
    return files[0]["id"] if files else None

def list_images(folder_id):
    res = drive.files().list(
        q=f"'{folder_id}' in parents and mimeType contains 'image/'",
        fields="files(id,name)"
    ).execute()
    return res.get("files", [])

def download_file(file_id):
    return drive.files().get_media(fileId=file_id).execute()

def upload_json(parent_id, name, content):
    fh = io.BytesIO(
        json.dumps(content, indent=2).encode("utf-8")
    )

    media = MediaIoBaseUpload(
        fh,
        mimetype="application/json",
        resumable=False
    )

    drive.files().create(
        body={
            "name": name,
            "parents": [parent_id]
        },
        media_body=media,
        fields="id"
    ).execute()

def move_file(file_id, new_parent):
    file = drive.files().get(
        fileId=file_id,
        fields="parents"
    ).execute()

    previous_parents = ",".join(file.get("parents", []))

    drive.files().update(
        fileId=file_id,
        addParents=new_parent,
        removeParents=previous_parents,
        fields="id, parents"
    ).execute()

# ---------- ENDPOINTS ----------
@app.get("/")
def root():
    return {"status": "contentengine running"}

@app.post("/launch")
def launch(posts_per_image: int = 2, keywords: str = ""):
    new_id = get_folder_id("new")
    used_id = get_folder_id("used")
    out_id = get_folder_id("output")

    if not all([new_id, used_id, out_id]):
        return {"error": "Drive folders missing"}

    images = list_images(new_id)
    processed = []

    for img in images:
        raw = download_file(img["id"])
        b64 = base64.b64encode(raw).decode()

        image_folder = drive.files().create(
            body={
                "name": os.path.splitext(img["name"])[0],
                "mimeType": "application/vnd.google-apps.folder",
                "parents": [out_id]
            },
            fields="id"
        ).execute()["id"]

        for i in range(posts_per_image):
            prompt = f"""
Create a Pinterest pin for this product image.

Rules:
- English
- Title with purchase intent
- Description: 4–7 sentences
- 15–30 relevant keywords used naturally
- No hashtags
- No emojis
- Each pin must be worded differently

Keywords (optional): {keywords}

Return ONLY valid JSON:
{{"title":"...","description":"..."}}
"""

            resp = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {"type": "image_base64", "image_base64": b64}
                        ]
                    }
                ]
            )

            content = json.loads(resp.choices[0].message.content)
            upload_json(image_folder, f"pin_{i+1}.json", content)

        move_file(img["id"], used_id)
        processed.append(img["name"])

    return {"processed": processed}
