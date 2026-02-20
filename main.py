from fastapi import FastAPI
import os, json, base64
from google.oauth2 import service_account
from googleapiclient.discovery import build
from openai import OpenAI

app = FastAPI()
client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

# ---- GOOGLE DRIVE ----
SCOPES = ["https://www.googleapis.com/auth/drive"]
service_account_info = json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"])
credentials = service_account.Credentials.from_service_account_info(
    service_account_info, scopes=SCOPES
)
drive = build("drive", "v3", credentials=credentials)

def get_folder_id(name):
    r = drive.files().list(
        q=f"mimeType='application/vnd.google-apps.folder' and name='{name}'",
        fields="files(id,name)"
    ).execute()
    f = r.get("files", [])
    return f[0]["id"] if f else None

def list_images(folder_id):
    r = drive.files().list(
        q=f"'{folder_id}' in parents and mimeType contains 'image/'",
        fields="files(id,name)"
    ).execute()
    return r.get("files", [])

def download_file(file_id):
    data = drive.files().get_media(fileId=file_id).execute()
    return data

def upload_json(parent_id, name, content):
    drive.files().create(
        body={"name": name, "parents": [parent_id]},
        media_body=json.dumps(content),
        fields="id"
    ).execute()

def move_file(file_id, new_parent):
    drive.files().update(
        fileId=file_id,
        addParents=new_parent,
        removeParents="root",
        fields="id, parents"
    ).execute()

# ---- ENDPOINTS ----
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
    results = []

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
- No hashtags, no emojis
- Vary wording between pins

Keywords (optional): {keywords}

Return ONLY valid JSON:
{{"title":"...","description":"..."}}
"""
            resp = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{
                    "role": "user",
                    "content": [
                        {"type":"text","text":prompt},
                        {"type":"image_base64","image_base64":b64}
                    ]
                }]
            )
            content = json.loads(resp.choices[0].message.content)
            upload_json(image_folder, f"pin_{i+1}.json", content)

        move_file(img["id"], used_id)
        results.append(img["name"])

    return {"processed": results}
