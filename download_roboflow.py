"""
download_roboflow.py
Downloads all Roboflow datasets using the Python API.
Handles both API-style downloads and direct download URL resolution.
"""
import os
import json
import requests
from roboflow import Roboflow

API_KEY = "gYWMwUzG9loPYOwtpD4j"

# Dataset 1 — already downloaded via API, keeping for reference
# Dataset 2 & 3 — resolved from direct download URLs below

# Direct download link IDs (from universe.roboflow.com/ds/<ID>?key=<KEY>)
DIRECT_LINKS = [
    {
        "ds_id": "uQYwc9HhyC",
        "key": "C8W9o0qppz",
        "location": "dataset/roboflow/dataset2",
        "label": "Dataset 2"
    },
    {
        "ds_id": "FdGUADHjeS",
        "key": "jLfa1ULha6",
        "location": "dataset/roboflow/dataset3",
        "label": "Dataset 3"
    },
]

# Roboflow SDK direct workspace downloads
SDK_PROJECTS = [
    {
        "workspace": "prebuilt",
        "project": "clothing-detection-2",
        "version": 12,
        "location": "dataset/roboflow/clothing_detection_2",
        "label": "Clothing Detection 2"
    }
]



def resolve_ds_id(ds_id, key):
    """Query Roboflow API to find workspace/project/version for a dataset download ID."""
    url = f"https://api.roboflow.com/ds/{ds_id}?api_key={API_KEY}&key={key}"
    r = requests.get(url, timeout=15)
    if r.status_code == 200:
        return r.json()
    # Fallback: try the dataset info endpoint
    url2 = f"https://api.roboflow.com/dataset/{ds_id}?api_key={API_KEY}"
    r2 = requests.get(url2, timeout=15)
    return r2.json() if r2.status_code == 200 else {}


def download_direct(ds_id, key, location, label):
    """Download a dataset directly using the zip download URL via requests."""
    import zipfile, io

    os.makedirs(location, exist_ok=True)
    print(f"\nDownloading {label} (ds/{ds_id})...")

    # Roboflow's download API endpoint
    download_url = f"https://api.roboflow.com/ds/{ds_id}/download?api_key={API_KEY}&key={key}&format=yolov8"
    
    # Try the download API
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/octet-stream,application/zip,*/*",
    }

    session = requests.Session()
    
    # First try: API download endpoint
    for attempt_url in [
        download_url,
        f"https://universe.roboflow.com/ds/{ds_id}?key={key}&api_key={API_KEY}",
        f"https://api.roboflow.com/dataset/{ds_id}?api_key={API_KEY}&format=yolov8",
    ]:
        try:
            r = session.get(attempt_url, headers=headers, timeout=60, allow_redirects=True)
            content_type = r.headers.get("Content-Type", "")
            print(f"  Trying: {attempt_url[:70]}...")
            print(f"  Status: {r.status_code}, Content-Type: {content_type[:50]}")
            
            if r.status_code == 200 and ("zip" in content_type or len(r.content) > 10000):
                # Try to unzip
                try:
                    zf = zipfile.ZipFile(io.BytesIO(r.content))
                    zf.extractall(location)
                    print(f"  Extracted {len(zf.namelist())} files to {location}")
                    return True
                except zipfile.BadZipFile:
                    # Might be JSON with a download URL
                    try:
                        info = r.json()
                        print(f"  Got JSON: {json.dumps(info, indent=2)[:300]}")
                        if "export" in info and "link" in info["export"]:
                            actual_url = info["export"]["link"]
                            r2 = session.get(actual_url, headers=headers, timeout=120)
                            zf = zipfile.ZipFile(io.BytesIO(r2.content))
                            zf.extractall(location)
                            print(f"  Extracted {len(zf.namelist())} files to {location}")
                            return True
                    except Exception as e2:
                        print(f"  JSON parse error: {e2}")
        except Exception as e:
            print(f"  Error: {e}")
    
    return False


def try_api_download(ds_id, key, location, label):
    """Try to find workspace/project info via API and use roboflow SDK."""
    rf = Roboflow(api_key=API_KEY)
    
    # Query the dataset info
    info_url = f"https://api.roboflow.com/ds/{ds_id}?api_key={API_KEY}&key={key}"
    r = requests.get(info_url, timeout=15)
    
    if r.status_code == 200:
        data = r.json()
        print(f"  API response: {json.dumps(data, indent=2)[:400]}")
        
        # Extract workspace/project if available
        workspace = data.get("workspace") or data.get("project", {}).get("workspace")
        project_id = data.get("project", {}).get("id") or data.get("id")
        version = data.get("version") or 1
        
        if workspace and project_id:
            print(f"  Found: {workspace}/{project_id} v{version}")
            try:
                proj = rf.workspace(workspace).project(project_id)
                ver = proj.version(version)
                dataset = ver.download("yolov8", location=location, overwrite=True)
                
                for split in ["train", "valid", "test"]:
                    img_dir = os.path.join(location, split, "images")
                    if os.path.exists(img_dir):
                        n = len([f for f in os.listdir(img_dir)
                                 if f.lower().endswith(('.jpg', '.jpeg', '.png'))])
                        print(f"  {split}: {n} images")
                return True
            except Exception as e:
                print(f"  SDK download failed: {e}")
    else:
        print(f"  API info query failed: {r.status_code} - {r.text[:200]}")
    
    return False


def main():
    print("=" * 60)
    print("  Roboflow Multi-Dataset Downloader")
    print("=" * 60)

    # Download direct link datasets (Dataset 2, Dataset 3)
    for link in DIRECT_LINKS:
        ds_id    = link["ds_id"]
        key      = link["key"]
        location = link["location"]
        label    = link["label"]

        # Skip if already downloaded
        yaml_path = os.path.join(location, "data.yaml")
        if os.path.exists(yaml_path):
            print(f"\n[SKIP] {label} already downloaded at {location}")
            continue

        # Try API-based resolution first
        success = try_api_download(ds_id, key, location, label)
        
        if not success:
            # Fall back to direct download
            success = download_direct(ds_id, key, location, label)
        
        if success:
            print(f"  [OK] {label} ready at {location}")
        else:
            print(f"  [FAIL] {label} — manual download may be needed")

    # Download SDK direct workspace datasets (Clothing Detection 2)
    rf = None
    for sdk_proj in SDK_PROJECTS:
        workspace = sdk_proj["workspace"]
        project = sdk_proj["project"]
        version = sdk_proj["version"]
        location = sdk_proj["location"]
        label = sdk_proj["label"]

        yaml_path = os.path.join(location, "data.yaml")
        if os.path.exists(yaml_path):
            print(f"\n[SKIP] {label} already downloaded at {location}")
            continue

        print(f"\nDownloading {label} via SDK ({workspace}/{project} v{version})...")
        try:
            if rf is None:
                rf = Roboflow(api_key=API_KEY)
            proj = rf.workspace(workspace).project(project)
            ver = proj.version(version)
            ver.download("yolov8", location=location, overwrite=True)
            print(f"  [OK] {label} ready at {location}")
        except Exception as e:
            print(f"  [FAIL] {label} — SDK download failed: {e}")


    # Summary
    print("\n" + "=" * 60)
    print("Download Summary:")
    for root, dirs, files in os.walk("dataset/roboflow"):
        yamls = [f for f in files if f == "data.yaml"]
        if yamls:
            import yaml
            with open(os.path.join(root, "data.yaml")) as f:
                d = yaml.safe_load(f)
            print(f"  {root}")
            print(f"    Classes: {d.get('names', [])}")
    print("=" * 60)
    print("Next: run  python merge_and_train.py")


if __name__ == "__main__":
    main()
